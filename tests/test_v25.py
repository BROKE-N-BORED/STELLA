"""v0.25.0 tests — the review P1s (R3, R5, R6, R8, R9, R10, R11,
R12, R16 on this half): the sleep-adapter export path, vision
detection on requant and export, the bounded GGUF magic read, the
orphan-sleep heal that keeps its hashes, the doctor's real icon
value and correct libxcb packages, the fresh Groq/Gemini lists,
and the base-install test gates. The topical tests live with their
modules; this file carries the version pins and the slice-level
checks.
"""

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

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    yield win
    win.close()


# -- Version --------------------------------------------------------
# (moved to test_v26.py — the version is 0.26.0 now)


# -- Slice: the new flags exist -------------------------------------


def test_export_from_sleep_option_listed(home):
    """`stella export-gguf --from-sleep` is a real option (R3)."""
    res = run_cli(home, "export-gguf", "--help")
    assert res.returncode == 0
    assert "--from-sleep" in res.stdout
