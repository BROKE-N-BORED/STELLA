"""Wheel-fetch tests (R62): the training download resumes.

A local HTTP server stands in for the wheel index: it serves fake
wheels, supports Range, logs every request (so a test can prove
the re-run asked for the remainder, not the whole file again),
and can cut a download short or ignore Range entirely. No real
network is used.
"""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from stella.wheel_fetch import (
    CannotFetchError,
    WheelFetchError,
    fetch_file,
    fetch_wheels,
    wheels_from_report,
)

WHEEL_A = b"A" * 4096
WHEEL_B = b"B" * 2048


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _WheelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address):
        super().__init__(address, _WheelHandler)
        self.files = {
            "torch-2.15.0-cp312-cp312-manylinux.whl": WHEEL_A,
            "peft-0.21.2-py3-none-any.whl": WHEEL_B,
        }
        self.log = []  # (path, range_header, bytes_served, status)
        self.mode = "normal"  # "normal" | "kill" | "no-range"
        self.kill_after = 512


class _WheelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output clean
        pass

    def do_GET(self):
        name = self.path.lstrip("/")
        data = self.server.files.get(name)
        if data is None:
            # Log before answering: the client can return the
            # moment the response lands, so a log written after
            # the body would race the test's assertions.
            self.server.log.append((self.path, None, 0, 404))
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        range_header = self.headers.get("Range")
        start = 0
        status = 200
        if self.server.mode != "no-range" and range_header:
            try:
                start = int(
                    range_header.split("=", 1)[1].split("-", 1)[0]
                )
            except ValueError:
                start = 0
            if start >= len(data):
                self.server.log.append(
                    (self.path, range_header, 0, 416)
                )
                self.send_response(416)
                self.send_header(
                    "Content-Range", f"bytes */{len(data)}"
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        body = data[start:]
        # In kill mode the server promises the whole remainder
        # but closes after a few bytes: the client must see a
        # cut download, not a short file.
        cut = (
            self.server.mode == "kill"
            and len(body) > self.server.kill_after
        )
        self.send_response(status)
        if status == 206:
            self.send_header(
                "Content-Range",
                f"bytes {start}-{len(data) - 1}/{len(data)}",
            )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if cut:
            self.server.log.append(
                (self.path, range_header, self.server.kill_after, 206
                 if status == 206 else 200)
            )
            self.wfile.write(body[: self.server.kill_after])
            self.wfile.flush()
            self.close_connection = True
            return
        self.server.log.append(
            (self.path, range_header, len(body), status)
        )
        self.wfile.write(body)
        self.wfile.flush()


@pytest.fixture()
def wheel_server():
    server = _WheelServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def no_retry(monkeypatch):
    """No sleeps between retries: the retry behaviour is what is
    tested, not the waiting."""
    import stella.wheel_fetch as fetch_mod

    monkeypatch.setattr(fetch_mod, "RETRY_DELAYS", (0.0, 0.0))


def _url(server, name):
    port = server.server_address[1]
    return f"http://127.0.0.1:{port}/{name}"


def _report(server):
    return {
        "version": "1",
        "install": [
            {
                "download_info": {
                    "url": _url(
                        server,
                        "torch-2.15.0-cp312-cp312-manylinux.whl",
                    ),
                    "archive_info": {
                        "hashes": {"sha256": _sha(WHEEL_A)}
                    },
                },
            },
            {
                "download_info": {
                    "url": _url(
                        server, "peft-0.21.2-py3-none-any.whl"
                    ),
                    "archive_info": {
                        "hashes": {"sha256": _sha(WHEEL_B)}
                    },
                },
            },
        ],
    }


def _quiet(_text):
    pass


# -- fetch_file -----------------------------------------------------


def test_fetch_downloads_a_wheel_from_scratch(
    wheel_server, tmp_path, no_retry
):
    """R62: a first fetch downloads the whole wheel and checks
    its hash — no .part file left behind."""
    dest = fetch_file(
        _url(wheel_server, "torch-2.15.0-cp312-cp312-manylinux.whl"),
        tmp_path,
        expected_sha256=_sha(WHEEL_A),
        _print=_quiet,
    )
    assert dest.read_bytes() == WHEEL_A
    assert not (tmp_path / (dest.name + ".part")).exists()
    assert len(wheel_server.log) == 1
    _path, range_header, served, status = wheel_server.log[0]
    assert range_header is None
    assert served == len(WHEEL_A)
    assert status == 200


def test_fetch_resumes_a_partial_file(wheel_server, tmp_path, no_retry):
    """R62: with half a wheel already on disk, the fetch asks for
    the remainder only — the server serves the missing bytes and
    no more."""
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    name = "torch-2.15.0-cp312-cp312-manylinux.whl"
    (wheel_dir / (name + ".part")).write_bytes(WHEEL_A[:2048])
    dest = fetch_file(
        _url(wheel_server, name),
        wheel_dir,
        expected_sha256=_sha(WHEEL_A),
        _print=_quiet,
    )
    assert dest.read_bytes() == WHEEL_A
    assert len(wheel_server.log) == 1
    _path, range_header, served, status = wheel_server.log[0]
    assert range_header == "bytes=2048-"
    assert served == len(WHEEL_A) - 2048
    assert status == 206


def test_fetch_restarts_when_server_ignores_range(
    wheel_server, tmp_path, no_retry
):
    """R62: a server that answers 200 to a Range request gets a
    clean restart — the stale partial file is dropped, not
    appended to, so the wheel is never corrupted."""
    wheel_server.mode = "no-range"
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    name = "peft-0.21.2-py3-none-any.whl"
    (wheel_dir / (name + ".part")).write_bytes(WHEEL_B[:1024])
    dest = fetch_file(
        _url(wheel_server, name),
        wheel_dir,
        expected_sha256=_sha(WHEEL_B),
        _print=_quiet,
    )
    assert dest.read_bytes() == WHEEL_B
    assert len(wheel_server.log) == 1
    assert wheel_server.log[0][3] == 200
    assert wheel_server.log[0][2] == len(WHEEL_B)


def test_fetch_finalizes_a_complete_partial_file(
    wheel_server, tmp_path, no_retry
):
    """R62: when the partial file already holds the whole wheel,
    the server answers 416 and the fetch finishes without
    downloading a byte."""
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    name = "peft-0.21.2-py3-none-any.whl"
    (wheel_dir / (name + ".part")).write_bytes(WHEEL_B)
    dest = fetch_file(
        _url(wheel_server, name),
        wheel_dir,
        expected_sha256=_sha(WHEEL_B),
        _print=_quiet,
    )
    assert dest.read_bytes() == WHEEL_B
    assert len(wheel_server.log) == 1
    assert wheel_server.log[0][3] == 416
    assert wheel_server.log[0][2] == 0


def test_fetch_skips_a_finished_wheel(
    wheel_server, tmp_path, no_retry
):
    """R62: a finished wheel with a matching hash is left alone —
    a re-run costs no request at all."""
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    name = "peft-0.21.2-py3-none-any.whl"
    (wheel_dir / name).write_bytes(WHEEL_B)
    dest = fetch_file(
        _url(wheel_server, name),
        wheel_dir,
        expected_sha256=_sha(WHEEL_B),
        _print=_quiet,
    )
    assert dest.read_bytes() == WHEEL_B
    assert wheel_server.log == []


def test_fetch_rejects_a_bad_hash(wheel_server, tmp_path, no_retry):
    """R62: a wheel whose hash does not match is refused, not
    kept — and no finished file is left behind."""
    with pytest.raises(WheelFetchError):
        fetch_file(
            _url(wheel_server, "peft-0.21.2-py3-none-any.whl"),
            tmp_path,
            expected_sha256="0" * 64,
            _print=_quiet,
        )
    assert not (tmp_path / "peft-0.21.2-py3-none-any.whl").exists()


# -- report parsing -------------------------------------------------


def test_wheels_from_report(wheel_server):
    """R62: the wheel list comes from a pip --dry-run --report,
    with the URL, file name, and hash per wheel."""
    wheels = wheels_from_report(_report(wheel_server))
    assert [w["name"] for w in wheels] == [
        "torch-2.15.0-cp312-cp312-manylinux.whl",
        "peft-0.21.2-py3-none-any.whl",
    ]
    assert wheels[0]["sha256"] == _sha(WHEEL_A)
    assert wheels[0]["url"].endswith(wheels[0]["name"])


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"install": "not-a-list"},
        {"install": [{"download_info": {}}]},
        {"install": [{"download_info": {"url": ""}}]},
        {"install": [{"nope": True}]},
        {
            "install": [
                {
                    "download_info": {
                        "url": "https://example.com/pkg-1.0.tar.gz",
                    }
                }
            ]
        },
        {"install": []},
    ],
)
def test_wheels_from_report_rejects_bad_reports(report):
    """R62: a malformed report, a missing URL, or a non-wheel
    entry cannot be fetched outside pip — the installer falls
    back to the direct download instead of guessing."""
    with pytest.raises(CannotFetchError):
        wheels_from_report(report)


def test_fetch_wheels_returns_2_for_a_bad_report(tmp_path):
    """R62: fetch_wheels returns 2 (fall back to the direct
    download) for a missing or malformed report."""
    assert fetch_wheels(
        tmp_path / "missing.json", tmp_path / "wheels",
        _print=_quiet,
    ) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert fetch_wheels(bad, tmp_path / "wheels", _print=_quiet) == 2
    non_wheel = tmp_path / "sdist.json"
    non_wheel.write_text(json.dumps({
        "install": [{
            "download_info": {
                "url": "https://example.com/pkg-1.0.tar.gz",
            },
        }],
    }))
    assert fetch_wheels(
        non_wheel, tmp_path / "wheels", _print=_quiet
    ) == 2


# -- the resume, end to end -----------------------------------------


def test_fetch_wheels_resumes_after_a_cut_download(
    wheel_server, tmp_path, no_retry
):
    """R62: a download cut short fails with exit 1 and keeps its
    partial files; the next run resumes from them and finishes —
    the server sees Range requests for the remainders only."""
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(wheel_server)))
    wheel_dir = tmp_path / "wheels"

    wheel_server.mode = "kill"
    assert fetch_wheels(
        report_path, wheel_dir, _print=_quiet
    ) == 1
    # The first wheel is partial (retries resumed and added
    # bytes each time); the second was never started.
    part = (
        wheel_dir
        / "torch-2.15.0-cp312-cp312-manylinux.whl.part"
    )
    assert part.is_file()
    partial_size = part.stat().st_size
    assert 0 < partial_size < len(WHEEL_A)
    assert not (
        wheel_dir / "peft-0.21.2-py3-none-any.whl"
    ).exists()
    served_first_run = sum(entry[2] for entry in wheel_server.log)
    assert served_first_run < len(WHEEL_A) + len(WHEEL_B)

    wheel_server.mode = "normal"
    wheel_server.log.clear()
    assert fetch_wheels(
        report_path, wheel_dir, _print=_quiet
    ) == 0
    assert (
        wheel_dir / "torch-2.15.0-cp312-cp312-manylinux.whl"
    ).read_bytes() == WHEEL_A
    assert (
        wheel_dir / "peft-0.21.2-py3-none-any.whl"
    ).read_bytes() == WHEEL_B
    # The resumed wheel was asked for by Range; the bytes already
    # on disk were not fetched again.
    ranges = [
        entry[1] for entry in wheel_server.log if entry[1]
    ]
    assert ranges, "the second run made no Range request"
    assert ranges[0].startswith("bytes=")
    resumed_at = int(ranges[0].split("=", 1)[1].split("-", 1)[0])
    assert resumed_at == partial_size
    served_second_run = sum(entry[2] for entry in wheel_server.log)
    assert served_second_run < len(WHEEL_A) + len(WHEEL_B)
