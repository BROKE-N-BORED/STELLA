"""`stella doctor` — check the install and repair what a move broke (T66).

Everything install.sh writes is an absolute path to the install
folder, so moving the folder leaves a dead menu entry and a dangling
`stella` command. The doctor verifies the venv, PySide6, launcher,
symlink, and icon, and re-links what is stale. A broken venv cannot
be repaired in place: it is reported with the fix named
(run bash install.sh again).

Stdlib only: the doctor must run even when PySide6 is missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import install as install_mod

OK = "OK"
FIXED = "FIXED"
BROKEN = "BROKEN"
INFO = "INFO"


@dataclass
class Check:
    name: str
    status: str
    detail: str


def find_install_dir() -> Path:
    """The tree this copy of Stella lives in."""
    return Path(__file__).resolve().parent.parent


def _stella_version() -> str:
    try:
        from .model import STELLA_VERSION

        return STELLA_VERSION
    except Exception:
        return "?"


def _run(cmd: list[str], env: dict | None = None, timeout: int = 120):
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, env=env,
        check=False,
    )


# S19: system libraries the Qt window code needs, mapped to the
# Debian/Ubuntu package that provides each one. Order matters:
# the specific names come before the generic ones they contain
# (libxcb-xkb before libxcb, libxkbcommon-x11 before libxkbcommon),
# so the first match is the most specific. Every package here is
# a real Debian package name (libegl1/libgl1/libgles2 are the
# libglvnd dispatch libraries; the libxcb/libxkbcommon set is
# what the Qt xcb platform plugin loads).
# R10: the generic "libxcb" key used to swallow every libxcb-*
# library and misdiagnose it as libxcb1 — the six unmapped ones
# now have their own entries, and the fallback matches only the
# bare "libxcb.so" library itself.
_MISSING_LIBRARY_PACKAGES = (
    ("libxcb-cursor", "libxcb-cursor0"),
    ("libxcb-icccm", "libxcb-icccm4"),
    ("libxcb-image", "libxcb-image0"),
    ("libxcb-keysyms", "libxcb-keysyms1"),
    ("libxcb-render-util", "libxcb-render-util0"),
    ("libxcb-render", "libxcb-render0"),
    ("libxcb-shm", "libxcb-shm0"),
    ("libxcb-shape", "libxcb-shape0"),
    ("libxcb-randr", "libxcb-randr0"),
    ("libxcb-xfixes", "libxcb-xfixes0"),
    ("libxcb-sync", "libxcb-sync1"),
    ("libxcb-util", "libxcb-util1"),
    ("libxcb-xkb", "libxcb-xkb1"),
    ("libxkbcommon-x11", "libxkbcommon-x11-0"),
    ("libxkbcommon", "libxkbcommon0"),
    ("libxcb.so", "libxcb1"),
    ("libEGL.so", "libegl1"),
    ("libGLESv2.so", "libgles2"),
    ("libGL.so", "libgl1"),
    ("libX11.so", "libx11-6"),
)


def _missing_library(output: str) -> tuple[str, str] | None:
    """The (library, package) the failure names, or None. The
    library name is matched as a substring of the whole output,
    so both "libEGL.so.1: cannot open shared object file" and
    "libxcb-cursor0 ... is needed to load the Qt xcb platform
    plugin" are caught. None means the error names no library
    this map knows: no diagnosis is invented then."""
    for library, package in _MISSING_LIBRARY_PACKAGES:
        if library in output:
            return library, package
    return None


def _check_pyside6(venv_python: Path) -> Check:
    """The same throwaway-QApplication check install.sh runs (T135):
    import-only would pass where creating a window fails."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    try:
        res = _run(
            [str(venv_python), "-c",
             "from PySide6.QtWidgets import QApplication;"
             " import sys; app = QApplication(sys.argv)"],
            env=env, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check("pyside6", BROKEN,
                     f"the PySide6 check could not run ({exc}); "
                     "run bash install.sh again")
    if res.returncode == 0:
        return Check("pyside6", OK, "PySide6 starts a window")
    output = res.stderr or res.stdout or ""
    lines = output.strip().splitlines()
    cause = lines[-1].strip() if lines else "unknown error"
    # S19: a missing system library is NOT fixed by reinstalling
    # Stella, so the old advice ("run bash install.sh again")
    # sent the user around in a loop. When the error names a
    # library this map knows, name the package and the exact
    # command that fixes it on this PC instead.
    found = _missing_library(output)
    if found is not None:
        library, package = found
        # The line naming the library is the cause worth showing:
        # the last line is often just "Aborted".
        for line in lines:
            if library in line:
                cause = line.strip()
                break
        name = library.split(".so")[0]
        return Check("pyside6", BROKEN,
                     f"PySide6 cannot start a window ({cause}). "
                     f"The system library {name} is missing from "
                     "this PC. Install it with: "
                     f"sudo apt install {package}")
    return Check("pyside6", BROKEN,
                 f"PySide6 cannot start a window ({cause}); "
                 "run bash install.sh again")


def _launcher_is_current(tree: Path, home: Path) -> tuple[bool, str]:
    """(is_current, why_not). Exec must point at this tree's
    run.sh AND Icon must be a real value: the theme name
    "stella", or an absolute path to an icon file that exists.
    The old check looked only at Exec, so a launcher with a
    literal Icon=path (a mode word, never an icon value) read
    as current forever (R9) — the second run reported OK while
    the broken icon stayed in the file."""
    launcher = install_mod.launcher_path(home)
    if not launcher.is_file():
        return False, "no menu launcher"
    exec_ok = False
    icon_seen = False
    icon_ok = False
    for line in launcher.read_text(errors="replace").splitlines():
        if line.startswith("Exec="):
            exec_ok = str(tree / "run.sh") in line
        elif line.startswith("Icon="):
            icon_seen = True
            value = line.split("=", 1)[1].strip()
            icon_ok = value == "stella" or (
                value.startswith("/") and Path(value).is_file()
            )
    if not exec_ok:
        return False, "points at another folder"
    if not icon_seen:
        return False, "has no icon set"
    if not icon_ok:
        return False, "names an icon that does not exist"
    return True, ""


def _fix_launcher(tree: Path, home: Path) -> Check:
    # R9: write_desktop_entry takes the icon VALUE (theme name or
    # absolute path), not the mode word — the old else branch
    # passed the literal word "path" and the launcher showed the
    # generic icon. Same translation as the CLI wrapper
    # (install.py main: "theme" -> "stella", "path" -> the PNG).
    icon = (
        "stella"
        if install_mod.hicolor_icons_present(home)
        else str(tree / "assets" / "stella.png")
    )
    try:
        install_mod.write_desktop_entry(tree, home, icon)
    except OSError as exc:
        return Check("launcher", BROKEN, f"could not rewrite it ({exc})")
    if shutil.which("update-desktop-database"):
        _run(["update-desktop-database",
              str(install_mod.launcher_path(home).parent)])
    # The desktop copy is a copy of the launcher: refresh it too
    # when one exists, so it stops pointing at the old folder.
    desktop_copy = home / "Desktop" / "Stella.desktop"
    if desktop_copy.is_file():
        try:
            shutil.copyfile(install_mod.launcher_path(home), desktop_copy)
            os.chmod(desktop_copy, 0o755)
            if shutil.which("gio"):
                _run(["gio", "set", str(desktop_copy),
                      "metadata::trusted", "true"])
        except OSError:
            pass
    return Check("launcher", FIXED,
                 f"rewritten to point at {tree}")


def run_checks(tree: Path, home: Path, fix: bool = True) -> list[Check]:
    """Check the install at `tree` for user `home`. With fix=True,
    stale launchers, symlinks, and icons are repaired in place."""
    tree = Path(tree)
    home = Path(home)
    checks: list[Check] = []

    # 1. venv
    venv_python = tree / ".venv" / "bin" / "python"
    venv_ok = venv_python.is_file() and os.access(venv_python, os.X_OK)
    if venv_ok:
        checks.append(Check("venv", OK, str(venv_python)))
    else:
        checks.append(Check(
            "venv", BROKEN,
            "no Python environment at .venv; run bash install.sh "
            "from the Stella folder"))

    # 2. PySide6 (needs the venv to run)
    if venv_ok:
        checks.append(_check_pyside6(venv_python))
    else:
        checks.append(Check(
            "pyside6", BROKEN,
            "cannot check without the venv; run bash install.sh"))

    # 3. launcher
    launcher = install_mod.launcher_path(home)
    launcher_current, launcher_stale = _launcher_is_current(tree, home)
    if launcher_current:
        checks.append(Check("launcher", OK, str(launcher)))
    elif not launcher.is_file():
        if fix:
            checks.append(_fix_launcher(tree, home))
        else:
            checks.append(Check(
                "launcher", BROKEN,
                "no menu launcher; run stella doctor to write one"))
    elif fix:
        checks.append(_fix_launcher(tree, home))
    else:
        checks.append(Check(
            "launcher", BROKEN,
            f"the menu launcher {launcher_stale}; "
            "run stella doctor to re-link it"))

    # 4. symlink
    link = install_mod.symlink_path(home)
    target = tree / "stella-cli"
    # resolve() with strict=False also resolves a dangling link to
    # its target path, so a stale link compares unequal here.
    link_ok = link.is_symlink() and link.resolve() == target.resolve()
    if link_ok:
        checks.append(Check("symlink", OK, f"{link} -> {target}"))
    elif fix:
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
            checks.append(Check("symlink", FIXED,
                                f"re-linked to {target}"))
        except OSError as exc:
            checks.append(Check("symlink", BROKEN,
                                f"could not re-link it ({exc})"))
    else:
        checks.append(Check(
            "symlink", BROKEN,
            "the stella command does not point here; "
            "run stella doctor to re-link it"))

    # 5. icon
    if install_mod.hicolor_icons_present(home):
        checks.append(Check("icon", OK, "hicolor theme (survives a move)"))
    elif (tree / "assets" / "stella-48.png").is_file() and fix:
        if install_mod.install_hicolor_icons(tree, home):
            checks.append(Check("icon", FIXED,
                                "copied into the hicolor theme"))
        else:
            checks.append(Check(
                "icon", BROKEN,
                "could not install the icons; run bash install.sh"))
    elif (tree / "assets" / "stella-48.png").is_file():
        checks.append(Check(
            "icon", BROKEN,
            "the menu icons are missing; run stella doctor to fix them"))
    else:
        checks.append(Check(
            "icon", BROKEN,
            "no icon files in assets/; run bash install.sh"))

    # 6. receipt (information, never a failure). A repair moves the
    # install, so refresh the receipt first: it names the old folder
    # until it is re-written. But only refresh a receipt that exists:
    # a folder that was never installed has no install to record, and
    # a receipt claiming one would lie about a broken install (T139:
    # the receipt records a complete install, not a failed one).
    if fix and any(c.status == FIXED for c in checks):
        old = install_mod.read_receipt(tree)
        if old:
            version = old.get("stella_version") or _stella_version()
            try:
                install_mod.write_receipt(tree, home, version)
            except OSError:
                pass
    receipt = install_mod.read_receipt(tree)
    if receipt:
        checks.append(Check(
            "receipt", INFO,
            "installed " + receipt.get("installed_at", "unknown")
            + ", Stella " + receipt.get("stella_version", "?")))
    else:
        checks.append(Check(
            "receipt", INFO,
            "no install receipt (this install predates v0.15, "
            "or the last install did not finish)"))

    return checks


def format_report(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [
        f"{c.status:6} {c.name:<{width}}  {c.detail}" for c in checks
    ]
    broken = [c for c in checks if c.status == BROKEN]
    if broken:
        lines.append(
            f"{len(broken)} problem(s) need attention; "
            "the fix is named above.")
    elif any(c.status == FIXED for c in checks):
        lines.append("Repaired. Open Stella from the menu to check it.")
    else:
        lines.append("Everything checks out.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    fix = "--check" not in args
    checks = run_checks(find_install_dir(), Path.home(), fix=fix)
    print(format_report(checks))
    return 1 if any(c.status == BROKEN for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
