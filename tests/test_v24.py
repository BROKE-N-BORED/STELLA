"""v0.24.0 tests — the Stella half of the Stella + OST improvement
list (2026-11-15): the requant fix, the single-file HF defect, the
RAM recalibration, the Ollama bridge, the distill timeout and
keep-alive, live progress, plain-words tool errors, and the doctor
that names the real fix. The topical tests live with their modules;
this file carries the version pins and the slice-level checks."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_cli(home, *args):
    """Run the real `python -m stella.cli` in a subprocess."""
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture()
def window(qapp, seeded, settings):
    """The main window on the seeded store (one profile, one
    project) — the same fixture test_gui.py uses, defined here so
    this file stands alone."""
    from stella.gui import MainWindow

    win = MainWindow()
    win.show()
    yield win
    win.close()


# -- Version --------------------------------------------------------
# (moved to test_v25.py — the version is 0.25.0 now)


# -- Slice: the new commands exist ---------------------------------


def test_bridge_command_listed(home):
    """`stella bridge` is a real command (S23)."""
    res = run_cli(home, "--help")
    assert res.returncode == 0
    assert "bridge" in res.stdout


def test_distill_timeout_option_listed(home):
    """`stella distill --timeout` is a real option (S3)."""
    res = run_cli(home, "distill", "--help")
    assert res.returncode == 0
    assert "--timeout" in res.stdout
