"""One model-loading job at a time, across CLI invocations (T29).

The GUI's single job slot is the UX; this lock is the safety. Two
model-loading jobs at once — a train holding ~6 GB while a probe
loads two bases (~7 GB) — is a real OOM shape on an 8 GB machine,
and the GUI slot cannot stop two separate CLI invocations, or the
CLI racing the window.

The lock is a file in the Stella home (`job.lock`), held with
`flock` for the whole job. A second job refuses at once with a
message naming the running job. `flock` is released by the kernel
when the holder dies, so a crashed job never leaves a stuck lock
behind — the file stays, but the next job locks it fine. The file's
content names the running job (plus its pid), so the refusal can
say what is running instead of just "something".

The lock is held by the engine entry points that load models:
train_project, export_gguf, probe_project, and sleep_project
(which loads models twice — the consolidation train, then the
replay — so it holds one lock for the whole cycle and the inner
train call skips its own, via skip=True). It is acquired AFTER
the cheap checks (bad profile, missing dataset, nothing to
resume), so a mistake in the command is still reported even
while another job runs — the lock only fires when the run is
otherwise ready to start.
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .model import StellaError

LOCK_NAME = "job.lock"

# How long a refused job waits for the holder's name to appear in
# the lock file (the holder writes it right after locking, so a
# first read can catch an empty file). Past this, the refusal
# names "another job" instead of stalling the error.
_HOLDER_WAIT_SECONDS = 0.5


def _read_holder(path: Path) -> str:
    """The job name in the lock file, or "another job" when the
    file is empty or unreadable."""
    deadline = time.monotonic() + _HOLDER_WAIT_SECONDS
    while True:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            text = ""
        if text:
            return text
        if time.monotonic() >= deadline:
            return "another job"
        time.sleep(0.02)


@contextmanager
def job_lock(home: str | Path, job_name: str, *, skip: bool = False):
    """Hold the home's job lock for one model-loading job.

    `job_name` is the plain-words name the refusal shows ("training
    lfm3-tool/tool-calls"). `skip=True` takes no lock at all: for a
    nested engine call (sleep's inner train) whose caller already
    holds the lock for the whole job.
    """
    if skip:
        yield
        return
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    path = home / LOCK_NAME
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Someone else holds it: name the running job.
            other = _read_holder(path)
            raise StellaError(
                f"Another job is already running: {other}. "
                "Wait for it to finish, then try again."
            ) from None
        os.ftruncate(fd, 0)
        os.write(fd, f"{job_name} (pid {os.getpid()})\n".encode("utf-8"))
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
