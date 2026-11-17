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
        "libxcb-render.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxcb-render0",
    ),
    (
        "libxcb-shm.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxcb-shm0",
    ),
    (
        "libxcb-shape.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxcb-shape0",
    ),
    (
        "libxcb-randr.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxcb-randr0",
    ),
    (
        "libxcb-xfixes.so.0: cannot open shared object file: "
        "No such file or directory",
        "libxcb-xfixes0",
    ),
    (
        "libxcb-sync.so.1: cannot open shared object file: "
        "No such file or directory",
        "libxcb-sync1",
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


# -- R9: the doctor writes a real icon value, and the sticky ------
# Icon=path launcher is no longer reported OK ----------------------


def _fake_tree(tmp_path, venv=True):
    """A minimal install folder: run.sh + the icon files, plus a
    working venv by default — a stub python that exits 0, so the
    PySide6 check passes without a real window. R58: the doctor
    only repairs launch artifacts when the venv is present, so
    the repair tests need one; pass venv=False for the
    broken-venv tests."""
    from stella.install import ICON_SIZES

    tree = tmp_path / "tree"
    (tree / "assets").mkdir(parents=True)
    (tree / "run.sh").write_text("#!/bin/sh\n")
    (tree / "assets" / "stella.png").write_bytes(b"fake png")
    for size in ICON_SIZES:
        (tree / "assets" / f"stella-{size}.png").write_bytes(b"fake png")
    if venv:
        bindir = tree / ".venv" / "bin"
        bindir.mkdir(parents=True)
        stub = bindir / "python"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    return tree


def _launcher_check(checks):
    return next(c for c in checks if c.name == "launcher")


def _plant_launcher(home, tree, icon):
    """A launcher whose Exec points at this tree, with the given
    Icon= value."""
    from stella import install as install_mod

    dest = install_mod.launcher_path(home)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Stella\n"
        f'Exec="{tree}/run.sh"\n'
        f"Icon={icon}\n"
        "Terminal=false\n"
    )
    return dest


def test_doctor_fix_writes_real_icon_path_when_hicolor_absent(tmp_path):
    """R9: with no hicolor icons installed, fix-mode doctor writes
    the absolute path to assets/stella.png — never the literal
    mode word "path"."""
    from stella import install as install_mod
    from stella.doctor import FIXED, run_checks

    tree = _fake_tree(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    assert not install_mod.hicolor_icons_present(home)
    checks = run_checks(tree, home, fix=True)
    assert _launcher_check(checks).status == FIXED
    text = install_mod.launcher_path(home).read_text()
    assert f"Icon={tree / 'assets' / 'stella.png'}" in text
    assert "Icon=path" not in text


def test_doctor_fix_writes_theme_icon_when_hicolor_present(tmp_path):
    """R9: with hicolor icons installed, the doctor still writes
    the theme name — the path branch must not leak into it."""
    from stella import install as install_mod
    from stella.doctor import FIXED, run_checks

    tree = _fake_tree(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    assert install_mod.install_hicolor_icons(tree, home)
    checks = run_checks(tree, home, fix=True)
    assert _launcher_check(checks).status == FIXED
    text = install_mod.launcher_path(home).read_text()
    assert "Icon=stella\n" in text


def test_icon_path_launcher_is_broken_not_ok(tmp_path):
    """R9, the sticky half: a launcher with a current Exec but a
    literal Icon=path is BROKEN on a check-only run — the old
    Exec-only check reported it OK forever."""
    from stella.doctor import BROKEN, run_checks

    tree = _fake_tree(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    _plant_launcher(home, tree, "path")
    checks = run_checks(tree, home, fix=False)
    check = _launcher_check(checks)
    assert check.status == BROKEN
    assert "icon" in check.detail


def test_icon_path_launcher_is_fixed_by_doctor(tmp_path):
    """R9: fix-mode doctor repairs the sticky launcher instead of
    leaving it — the rewritten file carries the real icon."""
    from stella import install as install_mod
    from stella.doctor import FIXED, run_checks

    tree = _fake_tree(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    _plant_launcher(home, tree, "path")
    checks = run_checks(tree, home, fix=True)
    assert _launcher_check(checks).status == FIXED
    text = install_mod.launcher_path(home).read_text()
    assert "Icon=path" not in text
    assert f"Icon={tree / 'assets' / 'stella.png'}" in text


def test_launcher_with_good_icon_is_ok(tmp_path):
    """The new currency check does not flag a healthy launcher:
    a current Exec with the theme icon (or a real icon path)
    still reads OK."""
    from stella.doctor import OK, run_checks

    tree = _fake_tree(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    _plant_launcher(home, tree, "stella")
    assert _launcher_check(run_checks(tree, home, fix=False)).status == OK
    _plant_launcher(home, tree, str(tree / "assets" / "stella.png"))
    assert _launcher_check(run_checks(tree, home, fix=False)).status == OK
    _plant_launcher(home, tree, "/no/such/icon.png")
    assert _launcher_check(
        run_checks(tree, home, fix=False)
    ).status == BROKEN


# -- R57: the installer names the package ---------------------------


@pytest.mark.parametrize("stderr, package", MISSING_LIBRARY_CASES)
def test_explain_missing_library_names_the_package(stderr, package):
    """R57: explain_missing_library names the same package the
    PySide6 check names — the installer shares the doctor's map,
    so the two can never disagree."""
    from stella.doctor import explain_missing_library

    advice = explain_missing_library(stderr)
    assert advice is not None
    assert package in advice
    assert f"sudo apt install {package}" in advice


def test_explain_missing_library_unknown_is_none():
    """R57: a failure naming no known library gets no invented
    diagnosis — the installer keeps its generic advice then."""
    from stella.doctor import explain_missing_library

    assert explain_missing_library("Aborted (core dumped)") is None
    assert explain_missing_library("") is None


def test_doctor_explain_mode(tmp_path, capsys):
    """R57: `python -m stella.doctor explain <file>` prints the
    fix for a captured Qt failure (exit 0), and stays silent
    with exit 1 when the failure names no known library."""
    from stella.doctor import main

    err_file = tmp_path / "qt.err"
    err_file.write_text(
        "libEGL.so.1: cannot open shared object file\n"
        "Aborted (core dumped)\n"
    )
    assert main(["explain", str(err_file)]) == 0
    out = capsys.readouterr().out
    assert "sudo apt install libegl1" in out
    err_file.write_text("Aborted (core dumped)\n")
    assert main(["explain", str(err_file)]) == 1
    assert capsys.readouterr().out == ""
    assert main(["explain", str(tmp_path / "missing.err")]) == 1
    assert main(["explain"]) == 2


# -- R58: a broken venv blocks launch repairs -----------------------


def _check_by_name(checks, name):
    return next(c for c in checks if c.name == name)


def test_doctor_with_broken_venv_repairs_nothing(tmp_path):
    """R58: fix-mode doctor on a folder with no venv writes no
    launcher, no symlink, and no icons — each step names the
    broken venv as the blocking cause instead of reporting
    FIXED, and no receipt is written."""
    from stella import install as install_mod
    from stella.doctor import BROKEN, run_checks

    tree = _fake_tree(tmp_path, venv=False)
    home = tmp_path / "home"
    home.mkdir()
    checks = run_checks(tree, home, fix=True)
    assert _check_by_name(checks, "venv").status == BROKEN
    assert _check_by_name(checks, "pyside6").status == BROKEN
    for name in ("launcher", "symlink", "icon"):
        check = _check_by_name(checks, name)
        assert check.status == BROKEN, name
        assert "Python environment" in check.detail, name
        assert "install.sh" in check.detail, name
    assert not install_mod.launcher_path(home).exists()
    assert not install_mod.symlink_path(home).exists()
    assert not install_mod.hicolor_icons_present(home)
    assert not (tree / ".stella-install-receipt").exists()
    assert not any(c.status == "FIXED" for c in checks)


def test_doctor_check_mode_with_broken_venv_names_the_venv(tmp_path):
    """R58: --check on a folder with no venv names the venv too —
    the old "run stella doctor to re-link it" sent the user in a
    loop, since the doctor cannot fix this without a venv."""
    from stella.doctor import BROKEN, run_checks

    tree = _fake_tree(tmp_path, venv=False)
    home = tmp_path / "home"
    home.mkdir()
    checks = run_checks(tree, home, fix=False)
    check = _check_by_name(checks, "launcher")
    assert check.status == BROKEN
    assert "Python environment" in check.detail
    assert "run stella doctor" not in check.detail


def test_doctor_with_venv_still_repairs(tmp_path):
    """R58, the other side: with a working venv, a stale launcher
    and a missing symlink are still repaired as before."""
    from stella import install as install_mod
    from stella.doctor import FIXED, run_checks

    tree = _fake_tree(tmp_path, venv=True)
    home = tmp_path / "home"
    home.mkdir()
    checks = run_checks(tree, home, fix=True)
    assert _check_by_name(checks, "launcher").status == FIXED
    assert _check_by_name(checks, "symlink").status == FIXED
    assert install_mod.launcher_path(home).is_file()
    assert install_mod.symlink_path(home).is_symlink()
