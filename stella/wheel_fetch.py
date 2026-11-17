"""Resumable training-wheel downloads (R62).

pip cannot resume a partial wheel: an interrupted download
re-fetches the whole wheel from scratch, and the torch wheel is
the better part of a gigabyte. So the training installer fetches
the wheels OUTSIDE pip and installs from the local files:

1. pip resolves the pinned requirements WITHOUT downloading
   (`pip install --dry-run --report`), producing a report that
   names every wheel URL and its sha256.
2. This module downloads each wheel into a cache dir, resuming
   any partial file with HTTP Range — a stopped download picks
   up where it left off instead of starting over.
3. pip installs from the cache (`pip install --no-index
   --find-links <dir>`).

Stdlib only (urllib): the training packages do not exist yet when
this runs. A wheel is downloaded to `<name>.part` and renamed to
its final name only when complete and hash-checked, so a partial
file is never mistaken for a finished wheel.

Exit codes from main(), which install-training.sh relies on:
0 = every wheel fetched; 1 = a download failed (the partial files
stay, so a re-run resumes — the script must NOT fall back to a
plain pip install then, or the resume is lost); 2 = the wheels
cannot be fetched outside pip at all (bad report, a non-wheel
entry) — the script falls back to the direct download.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# Bytes per read while streaming a wheel down.
CHUNK_BYTES = 1024 * 1024

# How many times one wheel is retried after a transient failure
# (each retry resumes from the partial file, so a retry costs
# only the bytes still missing).
MAX_ATTEMPTS = 3

# Seconds between retries: 1, then 2. Short on purpose — a retry
# is a resume, not a restart.
RETRY_DELAYS = (1.0, 2.0)


class WheelFetchError(Exception):
    """A wheel could not be fetched, in plain words."""


class CannotFetchError(Exception):
    """The wheels cannot be fetched outside pip at all (a bad
    report, or an entry that is not a wheel)."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _check_hash(path: Path, expected: str | None) -> bool:
    """True when the file matches its expected sha256 (or when no
    hash is known — nothing to check against)."""
    if not expected:
        return True
    return _sha256_file(path) == expected.lower()


def _file_name(url: str) -> str:
    """The wheel file name from its URL. Only the last path
    segment is kept, so a hostile URL cannot escape the wheel
    dir with ../ or an absolute path."""
    name = Path(urlparse(url).path).name
    if not name or name in (".", ".."):
        raise CannotFetchError(
            f"the wheel URL {url!r} names no file to download"
        )
    return name


def wheels_from_report(report: dict) -> list[dict]:
    """The wheels a pip --dry-run --report names: one
    {"url", "name", "sha256"} per package to install. Raises
    CannotFetchError when the report is not shaped the way pip
    writes it, or when any entry is not a wheel (an sdist has no
    wheel file to fetch, and pip would need the network to build
    it — that is the direct-download path, not this one)."""
    if not isinstance(report, dict):
        raise CannotFetchError("the pip report is not a JSON object")
    entries = report.get("install")
    if not isinstance(entries, list):
        raise CannotFetchError(
            "the pip report names no packages to install"
        )
    wheels = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise CannotFetchError(
                "the pip report holds a package entry that is not "
                "an object"
            )
        info = entry.get("download_info") or {}
        url = info.get("url") if isinstance(info, dict) else None
        if not isinstance(url, str) or not url:
            raise CannotFetchError(
                "the pip report names a package with no download "
                "address"
            )
        name = _file_name(url)
        if not name.endswith(".whl"):
            raise CannotFetchError(
                f"{name} is not a wheel file, so it cannot be "
                "fetched and installed from local files"
            )
        archive = info.get("archive_info") or {}
        hashes = archive.get("hashes") or {}
        sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
        wheels.append({
            "url": url,
            "name": name,
            "sha256": sha256 if isinstance(sha256, str) else None,
        })
    if not wheels:
        raise CannotFetchError(
            "the pip report names no packages to install"
        )
    return wheels


def _total_size(resp, have: int) -> int | None:
    """The full file size from a response, or None when the server
    does not say. A 206 reply carries Content-Range ("bytes
    have-end/total"); a 200 reply carries Content-Length."""
    content_range = resp.headers.get("Content-Range", "")
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[1].strip()
        if total.isdigit():
            return int(total)
    length = resp.headers.get("Content-Length")
    if length and length.isdigit():
        # On a 206 the length is the remainder, not the whole file.
        if resp.status == 206:
            return have + int(length)
        return int(length)
    return None


def _open(url: str, have: int, *, _opener=None):
    """Open a wheel URL, asking to resume at `have` bytes when
    there is a partial file. Returns the response. A server that
    does not support Range answers 200 (start over); one that
    does answers 206 (continue)."""
    req = urllib.request.Request(url, method="GET")
    if have > 0:
        req.add_header("Range", f"bytes={have}-")
    opener = _opener or urllib.request.urlopen
    return opener(req, timeout=120)


def fetch_file(
    url: str,
    dest_dir: Path | str,
    *,
    expected_sha256: str | None = None,
    _opener=None,
    _print=print,
) -> Path:
    """Download one wheel with resume (R62). A partial
    `<name>.part` file is continued with HTTP Range; a finished
    wheel that matches its hash is left alone. Returns the final
    path. Raises WheelFetchError when the download fails after
    its retries — the partial file stays for the next run."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _file_name(url)
    dest = dest_dir / name
    part = dest_dir / (name + ".part")
    if dest.is_file():
        if _check_hash(dest, expected_sha256):
            return dest
        # A finished-looking file with the wrong hash is worse
        # than no file: drop it and fetch again.
        dest.unlink()
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        have = part.stat().st_size if part.is_file() else 0
        try:
            resp = _open(url, have, _opener=_opener)
        except urllib.error.HTTPError as exc:
            # 416 means the partial file already holds the whole
            # wheel (the server has nothing left to send): check
            # it and finish, without fetching a byte.
            if exc.code == 416 and have > 0:
                if _check_hash(part, expected_sha256):
                    os.replace(part, dest)
                    return dest
                part.unlink()
                last_error = WheelFetchError(
                    f"{name} was already downloaded but its hash "
                    "does not match, so it will be fetched again"
                )
                continue
            last_error = exc
        except (
            urllib.error.URLError,
            OSError,
            TimeoutError,
            http.client.HTTPException,
        ) as exc:
            # HTTPException covers a connection cut mid-body
            # (IncompleteRead) and a garbled reply (BadStatusLine):
            # both are transient here, retried with resume.
            last_error = exc
        else:
            try:
                total = _total_size(resp, have)
                if resp.status == 206 and have > 0:
                    _print(
                        f"Picking up {name} where it stopped "
                        f"({have:,} of {total:,} bytes already "
                        "here)."
                        if total is not None
                        else f"Picking up {name} where it stopped."
                    )
                    mode = "ab"
                else:
                    # 200 (or a first fetch): start from the top.
                    # A stale partial file is dropped, not
                    # appended to — appending a full body to a
                    # partial file would corrupt the wheel.
                    if have > 0:
                        _print(
                            f"The server cannot pick up {name} "
                            "where it stopped, so it is downloading "
                            "again from the start."
                        )
                    else:
                        _print(f"Downloading {name}...")
                    have = 0
                    mode = "wb"
                digest = hashlib.sha256()
                if mode == "ab":
                    # The hash must cover the whole file, so the
                    # resumed bytes are hashed from the partial
                    # file before the new bytes arrive — streamed,
                    # never read whole: a partial torch wheel is
                    # hundreds of megabytes.
                    with open(part, "rb") as existing:
                        while True:
                            chunk = existing.read(CHUNK_BYTES)
                            if not chunk:
                                break
                            digest.update(chunk)
                fetched = have
                with open(part, mode) as handle:
                    while True:
                        try:
                            chunk = resp.read(CHUNK_BYTES)
                        except http.client.IncompleteRead as exc:
                            # The connection was cut mid-body: keep
                            # the bytes that did arrive before the
                            # cut, so the retry resumes past them
                            # instead of re-fetching them.
                            if exc.partial:
                                handle.write(exc.partial)
                                digest.update(exc.partial)
                                fetched += len(exc.partial)
                            raise WheelFetchError(
                                f"{name} stopped at {fetched:,} bytes"
                            ) from exc
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        fetched += len(chunk)
                if total is not None and fetched != total:
                    raise WheelFetchError(
                        f"{name} stopped at {fetched:,} of "
                        f"{total:,} bytes"
                    )
                if expected_sha256 and (
                    digest.hexdigest() != expected_sha256.lower()
                ):
                    part.unlink(missing_ok=True)
                    raise WheelFetchError(
                        f"{name} downloaded but its hash does not "
                        "match, so it will be fetched again"
                    )
                os.replace(part, dest)
                _print(f"Downloaded {name}.")
                return dest
            except WheelFetchError as exc:
                last_error = exc
            except (
                OSError,
                urllib.error.URLError,
                http.client.HTTPException,
            ) as exc:
                last_error = exc
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
        if attempt + 1 < MAX_ATTEMPTS:
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            _print(
                f"The download of {name} stopped; trying again in "
                f"{delay:.0f} second(s), picking up where it stopped."
            )
            time.sleep(delay)
    raise WheelFetchError(
        f"could not download {name}: {last_error or 'unknown error'}"
    )


def fetch_wheels(
    report_path: Path | str,
    wheel_dir: Path | str,
    *,
    _opener=None,
    _print=print,
) -> int:
    """Fetch every wheel a pip report names (R62). Returns 0 when
    all are fetched, 1 when a download failed (partial files stay
    for the next run), 2 when the wheels cannot be fetched outside
    pip at all."""
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _print(
            "The pip report could not be read, so the wheels "
            "cannot be fetched one by one."
        )
        return 2
    try:
        wheels = wheels_from_report(report)
    except CannotFetchError as exc:
        _print(f"{exc}.")
        return 2
    _print(
        f"Downloading {len(wheels)} training wheel(s), picking up "
        "where any earlier download stopped."
    )
    for wheel in wheels:
        try:
            fetch_file(
                wheel["url"], wheel_dir,
                expected_sha256=wheel["sha256"],
                _opener=_opener, _print=_print,
            )
        except WheelFetchError as exc:
            _print(
                f"stella: {exc}. Run bash install-training.sh again "
                "to pick up where it stopped."
            )
            return 1
    _print("All training wheels are downloaded.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """`python -m stella.wheel_fetch fetch <report.json> <dir>`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3 or args[0] != "fetch":
        print(
            "usage: python -m stella.wheel_fetch fetch "
            "<pip-report.json> <wheel-dir>",
            file=sys.stderr,
        )
        return 2
    return fetch_wheels(args[1], args[2])


if __name__ == "__main__":
    raise SystemExit(main())
