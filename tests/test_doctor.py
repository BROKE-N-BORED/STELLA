"""Doctor tests — the PySide6 check names the fix that works (S19).

The throwaway-QApplication run is faked: _run returns a canned
result, so no real venv or window is needed.
"""
import types
from pathlib import Path

import pytest

import stella.doctor as doctor_mod
from stella.doctor import BROKEN, OK, _check_pyside6

FAKE_PYTHON = Path("/fake/stella/.venv/bin/python")


def _fake_run(monkeypatch, returncode, stderr="", stdout=""):
    """Make doctor._run return one canned result."""

    def _run(cmd, env=None, timeout=120):
        return types.SimpleNamespace(
            returncode=returncode, stderr=stderr, stdout=stdout,
        )

    monkeypatch.setattr(doctor_mod, "_run", _run)


# (failure output, the package the advice must name)
MISSING_LIBRARY_CASES = [
    (
        "libEGL.so.1: cannot open shared object file: "
        "No such file or directory",
        "libegl1",
    ),
    (
        "libGL.so.1: cannot open shared object file: "
        "No such file or directory",
        "libgl1",
    ),
    (
        "libGLESv2.so.2: cannot open shared object file: "
        "No such file or directory",
        "libgles2",
    ),
    (
        "From 6.5.0, xcb-cursor0 or libxcb-cursor0 is needed to "
        "load the Qt xcb platform plugin.",
        "libxcb-cursor0",
    ),
    (
        "libxcb-icccm.so.4: cannot open shared object file: "
        "No such file or directory",
        "libxcb-icccm4",
    ),
    (
        "libxcb-image.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxcb-image0",
    ),
    (
        "libxcb-keysyms.so.1: cannot open shared object file: "
        "No such file or directory",
        "libxcb-keysyms1",
    ),
    (
        "libxcb-render-util.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxcb-render-util0",
    ),
    (
        "libxcb-util.so.1: cannot open shared object file: "
        "No such file or directory",
        "libxcb-util1",
    ),
    (
        "libxcb-xkb.so.1: cannot open shared object file: "
        "No such file or directory",
        "libxcb-xkb1",
    ),
    (
        "libxkbcommon-x11.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxkbcommon-x11-0",
    ),
    (
        "libxkbcommon.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxkbcommon0",
    ),
    (
        "libxcb.so.1: cannot open shared object file: "
        "No such file or directory",
        "libxcb1",
    ),
    (
        "libX11.so.6: cannot open shared object file: "
        "No such file or directory",
        "libx11-6",
    ),
]


@pytest.mark.parametrize("stderr, package", MISSING_LIBRARY_CASES)
def test_pyside6_missing_library_names_apt_package(
    monkeypatch, stderr, package
):
    """S19: a missing system library is fixed by installing its
    package, not by reinstalling Stella — the advice names the
    exact apt command, and the install.sh advice is gone."""
    _fake_run(monkeypatch, 1, stderr=stderr)
    check = _check_pyside6(FAKE_PYTHON)
    assert check.status == BROKEN
    assert f"sudo apt install {package}" in check.detail
    assert "install.sh" not in check.detail
    assert "missing from this PC" in check.detail


def test_pyside6_missing_library_found_on_stdout(monkeypatch):
    """The diagnosis reads stdout too when stderr is empty."""
    _fake_run(
        monkeypatch, 1, stdout="libEGL.so.1: cannot open shared "
        "object file: No such file or directory",
    )
    check = _check_pyside6(FAKE_PYTHON)
    assert check.status == BROKEN
    assert "sudo apt install libegl1" in check.detail


def test_pyside6_missing_library_shows_the_library_line(monkeypatch):
    """The cause shown is the line naming the library, not the
    trailing "Aborted" line."""
    _fake_run(
        monkeypatch, 1,
        stderr="libEGL.so.1: cannot open shared object file\nAborted",
    )
    check = _check_pyside6(FAKE_PYTHON)
    assert "libEGL.so.1: cannot open shared object file" in check.detail
    assert "Aborted" not in check.detail


def test_pyside6_unmapped_error_keeps_old_wording(monkeypatch):
    """S19: an error naming no known library keeps the old
    wording — no diagnosis is invented."""
    _fake_run(
        monkeypatch, 1,
        stderr="Traceback (most recent call last):\n"
        "ModuleNotFoundError: No module named 'PySide6'",
    )
    check = _check_pyside6(FAKE_PYTHON)
    assert check.status == BROKEN
    assert "run bash install.sh again" in check.detail
    assert "apt install" not in check.detail


def test_pyside6_check_passes_when_window_starts(monkeypatch):
    _fake_run(monkeypatch, 0)
    check = _check_pyside6(FAKE_PYTHON)
    assert check.status == OK
    assert "PySide6 starts a window" in check.detail


def test_doctor_names_no_dev_machine_paths():
    """The doctor speaks to the user's Mint PC, where system
    libraries come from apt: no path from this dev machine may
    appear in the doctor or in these tests. The needles are
    built from fragments so the forbidden strings never appear
    as literals in this file itself."""
    needles = [
        "qt" + "-libs",
        "work" + "space/" + "qt" + "-libs",
        "forge" + "-test-home",
        "/home/" + "hatch",
        "stella" + "-v24b",
        "LD_" + "LIBRARY_PATH",
    ]
    root = Path(__file__).resolve().parent.parent
    sources = {
        "doctor.py": (root / "stella" / "doctor.py").read_text(
            encoding="utf-8"
        ),
        "test_doctor.py": Path(__file__).read_text(encoding="utf-8"),
    }
    for name, text in sources.items():
        for needle in needles:
            assert needle not in text, f"{needle!r} in {name}"
