"""Provisioning tests: weights status, size/disk checks, the
download helper, and the DownloadManager subprocess wrapper.

No test here ever downloads real weights: snapshot_download is
always mocked, and the DownloadManager tests run tiny local
python -c scripts that print the same PROGRESS/DONE/ERROR lines.
"""
import sys
import time

import pytest

from stella import provision


# -- repo ids and cache paths ---------------------------------------


def test_is_hf_repo_id():
    assert provision.is_hf_repo_id("LiquidAI/LFM3-1.7B")
    assert not provision.is_hf_repo_id("lfm3:1.7b")
    assert not provision.is_hf_repo_id("matern/minicpm5-heretic:2b")
    assert not provision.is_hf_repo_id("qwen3.5")
    assert not provision.is_hf_repo_id("")
    assert not provision.is_hf_repo_id(None)


def test_repo_cache_dir_naming(tmp_path, monkeypatch):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )
    assert provision.repo_cache_dir("LiquidAI/LFM3-1.7B") == (
        tmp_path / "hub" / "models--LiquidAI--LFM3-1.7B"
    )


def test_hub_cache_dir_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "cache"))
    assert provision.hub_cache_dir() == tmp_path / "cache"
    monkeypatch.delenv("HF_HUB_CACHE")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert provision.hub_cache_dir() == tmp_path / "hf" / "hub"


def test_format_size():
    assert provision.format_size(0) == "0 bytes"
    assert provision.format_size(44) == "44 bytes"
    assert provision.format_size(1536) == "1.5 KB"
    assert provision.format_size(820 * 1024 * 1024) == "820.0 MB"
    assert provision.format_size(int(3.5 * 1024**3)) == "3.5 GB"


# -- weights status -------------------------------------------------


def _hf_profile(store):
    store.create_profile("lfm3-hf", base_ref="LiquidAI/LFM3-1.7B")
    return "lfm3-hf"


def test_weights_status_no_repo(seeded):
    status = provision.weights_status(seeded, "lfm3-tool")
    assert status["state"] == "no-repo"
    # create_profile falls back base_ref to the Ollama tag, so the
    # repo field holds the tag — still not a Hugging Face repo id.
    assert status["repo"] == "lfm3:1.7b"


def test_weights_status_missing(store, tmp_path, monkeypatch):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )
    slug = _hf_profile(store)
    status = provision.weights_status(store, slug)
    assert status["state"] == "missing"
    assert status["repo"] == "LiquidAI/LFM3-1.7B"
    assert status["size_bytes"] == 0


def test_weights_status_partial(store, tmp_path, monkeypatch):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )
    slug = _hf_profile(store)
    blobs = tmp_path / "hub" / "models--LiquidAI--LFM3-1.7B" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "abc123.incomplete").write_bytes(b"x" * 1024)
    status = provision.weights_status(store, slug)
    assert status["state"] == "partial"
    assert status["size_bytes"] == 1024


def test_weights_status_ready(store, tmp_path, monkeypatch):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )
    slug = _hf_profile(store)
    snap = (
        tmp_path / "hub" / "models--LiquidAI--LFM3-1.7B"
        / "snapshots" / "deadbeef"
    )
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    (snap / "model.safetensors").write_bytes(b"x" * 2048)
    status = provision.weights_status(store, slug)
    assert status["state"] == "ready"
    assert status["size_bytes"] == 2050
    assert status["path"] == str(snap)


def test_weights_status_config_without_weights_is_partial(
    store, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )
    slug = _hf_profile(store)
    snap = (
        tmp_path / "hub" / "models--LiquidAI--LFM3-1.7B"
        / "snapshots" / "deadbeef"
    )
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    status = provision.weights_status(store, slug)
    assert status["state"] == "partial"


# -- size and disk --------------------------------------------------


class _FakeSibling:
    def __init__(self, size):
        self.size = size


class _FakeInfo:
    def __init__(self, sizes):
        self.siblings = [_FakeSibling(s) for s in sizes]


class _FakeApi:
    def __init__(self, sizes):
        self._sizes = sizes

    def model_info(self, repo_id):
        return _FakeInfo(self._sizes)


def test_estimate_repo_size_sums_siblings():
    api = _FakeApi([100, 200, 300])
    assert provision.estimate_repo_size("a/b", _api=api) == 600


def test_estimate_repo_size_none_on_failure():
    class _Boom:
        def model_info(self, repo_id):
            raise RuntimeError("no network")

    assert provision.estimate_repo_size("a/b", _api=_Boom()) is None
    assert provision.estimate_repo_size("a/b", _api=_FakeApi([])) is None


def test_check_disk(tmp_path):
    assert provision.check_disk(1, path=tmp_path)["fits"] is True
    huge = provision.check_disk(10**18, path=tmp_path)
    assert huge["fits"] is False
    assert huge["free_bytes"] > 0


def _cap(lines):
    """A _print seam for run_download: print takes flush=, append doesn't."""
    return lambda msg, **kwargs: lines.append(msg)

# -- run_download ---------------------------------------------------


def test_run_download_success(monkeypatch, tmp_path):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )
    lines = []
    result = provision.run_download(
        "a/b",
        _snapshot_download=lambda repo: "/fake/cache/a-b",
        _api=_FakeApi([]),
        _print=_cap(lines),
    )
    assert result == 0
    assert lines[-1] == "DONE /fake/cache/a-b"
    assert not any(line.startswith("ERROR") for line in lines)


def test_run_download_failure_is_plain_words(monkeypatch, tmp_path):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )

    def boom(repo):
        raise RuntimeError("kaboom")

    lines = []
    result = provision.run_download(
        "a/b", _snapshot_download=boom, _api=_FakeApi([]),
        _print=_cap(lines),
    )
    assert result == 1
    assert lines[-1] == "ERROR kaboom"


def test_run_download_repo_not_found_is_plain_words(monkeypatch, tmp_path):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )

    class RepositoryNotFoundError(Exception):
        pass

    def boom(repo):
        raise RepositoryNotFoundError("404 Client Error")

    lines = []
    result = provision.run_download(
        "a/b", _snapshot_download=boom, _api=_FakeApi([]),
        _print=_cap(lines),
    )
    assert result == 1
    assert lines[-1] == (
        "ERROR That repo does not exist on Hugging Face. "
        "Check the name."
    )


def test_run_download_connection_error_is_plain_words(monkeypatch, tmp_path):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )

    def boom(repo):
        raise ConnectionError("Failed to resolve huggingface.co")

    lines = []
    result = provision.run_download(
        "a/b", _snapshot_download=boom, _api=_FakeApi([]),
        _print=_cap(lines),
    )
    assert result == 1
    assert lines[-1] == (
        "ERROR No connection to Hugging Face. "
        "Check the network and try again."
    )


def test_run_download_refuses_when_disk_too_small(monkeypatch, tmp_path):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )
    called = []
    lines = []
    result = provision.run_download(
        "a/b",
        _snapshot_download=lambda repo: called.append(repo),
        _api=_FakeApi([10**18]),
        _print=_cap(lines),
    )
    assert result == 1
    assert called == []  # the download never started
    assert lines[-1].startswith("ERROR Not enough disk space.")


def test_run_download_reports_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(
        provision, "hub_cache_dir", lambda: tmp_path / "hub"
    )

    def slow(repo):
        time.sleep(1.2)
        return "/fake/cache/a-b"

    lines = []
    result = provision.run_download(
        "a/b", _snapshot_download=slow, _api=_FakeApi([1000]),
        _print=_cap(lines),
    )
    assert result == 0
    progress = [ln for ln in lines if ln.startswith("PROGRESS")]
    assert len(progress) >= 1
    assert progress[-1].startswith("PROGRESS 0 1000")


# -- main() ---------------------------------------------------------


def test_main_usage_error():
    assert provision.main([]) == 2
    assert provision.main(["download"]) == 2
    assert provision.main(["fetch", "a/b"]) == 2


def test_main_rejects_non_repo_id(capsys):
    assert provision.main(["download", "lfm3:1.7b"]) == 1
    assert "ERROR" in capsys.readouterr().out


def test_main_requires_hub(monkeypatch, capsys):
    monkeypatch.setattr(provision, "hub_available", lambda: False)
    assert provision.main(["download", "a/b"]) == 1
    out = capsys.readouterr().out
    # v0.35.0: the same plain-words message as the window and the
    # chat download paths - click directions and the size note,
    # no Train panel, no terminal line, no package names.
    assert out.startswith("ERROR ")
    assert "Training is not set up on this PC yet" in out
    assert "Install training" in out
    assert "main screen" in out
    assert "Install Stella Training" in out
    assert "about 2 GB" in out
    for banned in ("Train panel", "Terminal", "install-training",
                   "Hugging Face packages"):
        assert banned not in out, banned


def test_main_delegates_to_run_download(monkeypatch):
    monkeypatch.setattr(provision, "hub_available", lambda: True)
    monkeypatch.setattr(
        provision, "run_download", lambda repo: 0
    )
    assert provision.main(["download", "a/b"]) == 0


# -- DownloadManager ------------------------------------------------


def _wait_until(qapp, pred, timeout_ms=8000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    qapp.processEvents()
    return pred()


def test_download_manager_parses_progress_and_done(qapp):
    from stella.gui import DownloadManager

    manager = DownloadManager(
        command=[
            sys.executable, "-c",
            "print('PROGRESS 50 100', flush=True); "
            "print('DONE /tmp/x', flush=True)",
        ]
    )
    progress = []
    finished = []
    manager.progress.connect(lambda d, t: progress.append((d, t)))
    manager.finished.connect(lambda ok, msg: finished.append((ok, msg)))
    assert manager.start("a/b") is True
    assert _wait_until(qapp, lambda: bool(finished))
    assert progress == [(50, 100)]
    assert finished == [(True, "/tmp/x")]


def test_download_manager_error(qapp):
    from stella.gui import DownloadManager

    manager = DownloadManager(
        command=[
            sys.executable, "-c",
            "import sys; print('ERROR boom', flush=True); sys.exit(1)",
        ]
    )
    finished = []
    manager.finished.connect(lambda ok, msg: finished.append((ok, msg)))
    manager.start("a/b")
    assert _wait_until(qapp, lambda: bool(finished))
    assert finished == [(False, "boom")]


def test_download_manager_cancel(qapp):
    from stella.gui import DownloadManager

    manager = DownloadManager(
        command=[
            sys.executable, "-c",
            "import time; print('PROGRESS 1 100', flush=True); "
            "time.sleep(30)",
        ]
    )
    progress = []
    finished = []
    manager.progress.connect(lambda d, t: progress.append((d, t)))
    manager.finished.connect(lambda ok, msg: finished.append((ok, msg)))
    manager.start("a/b")
    assert _wait_until(qapp, lambda: bool(progress))
    assert manager.is_running()
    assert manager.start("a/b") is False  # one download at a time
    manager.cancel()
    assert _wait_until(qapp, lambda: bool(finished))
    assert manager.was_cancelled()
    assert finished[0][0] is False
    assert "pick up where it left off" in finished[0][1]
