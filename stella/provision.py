"""STELLA model provisioning: one-click base-model downloads.

A profile's base_ref names a Hugging Face repo (for example
LiquidAI/LFM3-1.7B). Training loads the base from the Hugging Face
cache, so the weights must be on disk first. This module answers
"are they there?" and downloads them, in a subprocess the UI can
cancel, with progress.

The download runs as `python -m stella.provision download <repo>` in
a separate process (see DownloadManager in gui.py): killing the
process stops the download, and the Hugging Face hub resumes
interrupted downloads on the next run, so a cancelled download never
loses what it already fetched.

No Qt here on purpose: the status checks and the download helper are
plain Python, testable without a window, and the subprocess that runs
the download must not import Qt at all.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path

from .model import Store, StellaError

# How often the download helper reports progress (seconds).
POLL_SECONDS = 0.5


# ---------------------------------------------------------------- paths


def hub_cache_dir() -> Path:
    """The Hugging Face hub cache dir, honouring HF_HOME/HF_HUB_CACHE."""
    override = os.environ.get("HF_HUB_CACHE") or os.environ.get("HF_HOME")
    if override:
        base = Path(override).expanduser()
        # HF_HOME points at the huggingface dir itself; HF_HUB_CACHE
        # points straight at the hub cache.
        if os.environ.get("HF_HUB_CACHE"):
            return base
        return base / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def repo_cache_dir(repo_id: str) -> Path:
    """Cache dir for one repo: models--<org>--<name>."""
    safe = repo_id.replace("/", "--")
    return hub_cache_dir() / f"models--{safe}"


def _dir_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for root, _dirs, files in os.walk(path, followlinks=True):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _snapshot_dirs(repo_id: str) -> list[Path]:
    snaps = repo_cache_dir(repo_id) / "snapshots"
    if not snaps.is_dir():
        return []
    return [d for d in sorted(snaps.iterdir()) if d.is_dir()]


def _downloaded_bytes(repo_id: str) -> int:
    """Bytes fetched so far: the blobs dir holds every file the hub
    has downloaded (partial files included, as .incomplete files)."""
    return _dir_size(repo_cache_dir(repo_id) / "blobs")


def is_hf_repo_id(value: str) -> bool:
    """True when a string looks like a Hugging Face repo id.

    A repo id is "org/name" with no tag colon. An Ollama tag has a
    colon ("lfm3:1.7b", "matern/minicpm5-heretic:2b") and is not a
    repo id, even when namespaced.
    """
    value = (value or "").strip()
    return "/" in value and ":" not in value


def hub_available() -> bool:
    """True when huggingface_hub is importable (it ships with the
    training packages, see install-training.sh)."""
    import importlib.util

    return importlib.util.find_spec("huggingface_hub") is not None


# ---------------------------------------------------------------- status


def weights_status(store: Store, profile: str) -> dict:
    """Where do this profile's base weights stand?

    Returns {"repo", "state", "size_bytes", "path"} where state is:
    "no-repo" (no Hugging Face repo set), "missing" (nothing on
    disk), "partial" (some files, not a usable snapshot), "ready"
    (a snapshot with config + weights).
    """
    data = store.get_profile(profile)
    repo = (data.get("base_ref") or "").strip()
    if not is_hf_repo_id(repo):
        return {"repo": repo, "state": "no-repo", "size_bytes": 0,
                "path": None}
    cache = repo_cache_dir(repo)
    size = _dir_size(cache) if cache.exists() else 0
    for snap in _snapshot_dirs(repo):
        has_config = (snap / "config.json").exists()
        has_weights = bool(
            list(snap.glob("*.safetensors")) + list(snap.glob("*.bin"))
        )
        if has_config and has_weights:
            return {"repo": repo, "state": "ready", "size_bytes": size,
                    "path": str(snap)}
    if size > 0:
        return {"repo": repo, "state": "partial", "size_bytes": size,
                "path": str(cache)}
    return {"repo": repo, "state": "missing", "size_bytes": 0,
            "path": None}


def estimate_repo_size(repo_id: str, *, _api=None) -> int | None:
    """Total download size in bytes, from the Hub file list.

    Returns None when the size cannot be found (no network, unknown
    repo) — the download still works, it just shows bytes fetched
    instead of a percentage.
    """
    try:
        if _api is None:
            from huggingface_hub import HfApi

            _api = HfApi()
        info = _api.model_info(repo_id)
        total = 0
        for sibling in getattr(info, "siblings", []) or []:
            size = getattr(sibling, "size", None)
            if isinstance(size, int):
                total += size
        return total or None
    except Exception:
        return None


def check_disk(required_bytes: int, *, path: Path | None = None) -> dict:
    """Is there room for a download of this size? Returns
    {"fits", "free_bytes"} for the disk holding the HF cache."""
    target = path or hub_cache_dir()
    target.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(target).free
    return {"fits": free >= required_bytes, "free_bytes": free}


def format_size(num_bytes: int) -> str:
    """Bytes as a plain size: 3.5 GB, 820 MB, 44 KB."""
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "bytes":
                return f"{int(size)} bytes"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} bytes"


# ---------------------------------------------------------------- download


def _plain_error(exc: Exception) -> str:
    """A download failure in plain words."""
    name = type(exc).__name__
    text = str(exc)
    if name in ("RepositoryNotFoundError", "HFValidationError") or (
        "404" in text and "not found" in text.lower()
    ):
        return "That repo does not exist on Hugging Face. Check the name."
    if name in ("ConnectionError", "ConnectError", "TimeoutError",
                "MaxRetryError") or "Failed to resolve" in text:
        return "No connection to Hugging Face. Check the network and try again."
    if "offline" in text.lower():
        return "Hugging Face is in offline mode. Check the network and try again."
    return text or name


def run_download(repo_id: str, *, _snapshot_download=None, _api=None,
                 _print=print) -> int:
    """Download one repo's weights, reporting progress on stdout.

    Prints "PROGRESS <downloaded> <total>" lines (total 0 when the
    size is unknown), then "DONE <path>" or "ERROR <message>".
    Returns 0 on success, 1 on failure. Used by the subprocess the
    GUI spawns; _snapshot_download/_api are test seams.
    """
    total = estimate_repo_size(repo_id, _api=_api) or 0
    if total > 0:
        # Check the disk BEFORE downloading anything: a 3.5 GB
        # download that dies at 90% full is a wasted afternoon.
        disk = check_disk(total)
        if not disk["fits"]:
            _print(
                f"ERROR Not enough disk space. The download needs about "
                f"{format_size(total)} and there is "
                f"{format_size(disk['free_bytes'])} free.",
                flush=True,
            )
            return 1
    stop = threading.Event()

    def _poll():
        while not stop.wait(POLL_SECONDS):
            _print(f"PROGRESS {_downloaded_bytes(repo_id)} {total}",
                   flush=True)

    poller = threading.Thread(target=_poll, daemon=True)
    poller.start()
    try:
        if _snapshot_download is None:
            from huggingface_hub import snapshot_download

            _snapshot_download = snapshot_download
        path = _snapshot_download(repo_id)
    except Exception as exc:  # noqa: BLE001 - every failure is a message
        stop.set()
        _print(f"ERROR {_plain_error(exc)}", flush=True)
        return 1
    stop.set()
    _print(f"PROGRESS {_downloaded_bytes(repo_id)} {total}", flush=True)
    _print(f"DONE {path}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Subprocess entry: python -m stella.provision download <repo>."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "download":
        print("usage: python -m stella.provision download <repo-id>",
              file=sys.stderr)
        return 2
    repo_id = args[1]
    if not is_hf_repo_id(repo_id):
        print(f"ERROR {repo_id!r} is not a Hugging Face repo id "
              "(it should look like org/name).", flush=True)
        return 1
    if not hub_available():
        print("ERROR The Hugging Face packages are not installed. "
              "Run this once in the Stella folder: "
              "bash install-training.sh", flush=True)
        return 1
    return run_download(repo_id)


if __name__ == "__main__":
    raise SystemExit(main())
