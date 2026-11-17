"""v0.27.0 tests — the review P2 batch 2 (R52–R75): --json
honoured or plainly refused on every command, export commands that
fail clean before printing a size, chat pre-flight failures on
stderr plus a CLI way to save a provider key, CLI clone commands,
the nameless-profile warning that fires only when truly nameless,
installer advice that names the package, a doctor that does not
repair launch files for a broken venv, an uninstall that checks
ownership first, a base install that fails fast offline, a 5 GB
training preflight, a resumable training download, a click-only
uninstall, the probe judge that gets all 11 edge cases right, the
probe gate that recomputes its delta, sleep delete/prune/size, the
governing-seat warning for role-only profiles, the CLI probe that
auto-detects like the GUI, the README and How to Use refresh, the
fixture that no longer opens the real store, executed download
helpers, full error-map coverage, fixture teardown that waits for
jobs, and a Resume button that is only live when there is
something to resume. The topical tests live with their modules;
this file carries the version pins and the slice-level checks.
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
    this file stands alone. R74: teardown waits for any running
    job before closing, so a worker cannot leak into the next
    test."""
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    from tests.test_gui import _wait_for_all_workers

    _wait_for_all_workers(win, qapp)
    win.close()


# -- Version --------------------------------------------------------


def test_version_is_0_27_0(home):
    """The version is 0.27.0 everywhere the CLI reports it."""
    from stella.model import STELLA_VERSION

    assert STELLA_VERSION == "0.27.0"
    res = run_cli(home, "--version")
    assert res.returncode == 0
    assert "0.27.0" in res.stdout


def test_window_title_carries_version(window):
    """The window title carries STELLA 0.27.0."""
    assert "0.27.0" in window.windowTitle()


# -- Slice: the new commands exist ---------------------------------


def test_sleep_delete_and_prune_commands_listed(home):
    """`stella sleep-delete` and `stella sleep-prune` are real
    commands (R66)."""
    for command in ("sleep-delete", "sleep-prune"):
        res = run_cli(home, command, "--help")
        assert res.returncode == 0
        assert f"stella {command}" in res.stdout


def test_probe_gate_option_listed(home):
    """`stella probe --gate` is a real option (R68): it forces the
    gate on a profile the auto-detect would probe
    informationally."""
    res = run_cli(home, "probe", "--help")
    assert res.returncode == 0
    assert "--gate" in res.stdout


# -- Slice: the new commands exist ----------------------------------


def test_new_commands_listed(home):
    """R54/R55: save-key, list-keys, remove-key, clone-profile,
    and clone-project are real commands with worked examples."""
    for command in (
        "save-key", "list-keys", "remove-key",
        "clone-profile", "clone-project",
    ):
        res = run_cli(home, command, "--help")
        assert res.returncode == 0, command
        assert "examples:" in res.stdout, command
        assert f"stella {command}" in res.stdout, command


# -- Slice: the new mechanisms exist --------------------------------


def test_uninstall_desktop_file_exists_in_tree():
    """R63: the click-only uninstall ships beside the installer."""
    path = ROOT / "Uninstall Stella.desktop"
    assert path.is_file()
    assert os.access(path, os.X_OK)
    assert (ROOT / "uninstall_launcher.py").is_file()


def test_wheel_fetch_module_exists():
    """R62: the resumable wheel fetcher is importable."""
    from stella import wheel_fetch

    assert callable(wheel_fetch.fetch_file)
    assert callable(wheel_fetch.fetch_wheels)


def test_doctor_explains_a_missing_library():
    """R57: the doctor's library map answers through its explain
    mode, so the installer can name the package."""
    from stella.doctor import explain_missing_library

    advice = explain_missing_library(
        "libEGL.so.1: cannot open shared object file"
    )
    assert advice is not None
    assert "libegl1" in advice
    assert explain_missing_library("some other failure") is None


def test_howto_opens_on_getting_started(window, qapp):
    """R92 (Joshua's call 2026-11-17): How to Use opens on Getting
    started, with its body already shown — not an empty pane."""
    howto = window.open_howto_window()
    qapp.processEvents()
    assert howto.topic_list.currentItem().text() == "Getting started"
    assert "fine-tunes small AI models" in howto.content.toPlainText()
    howto.close()
