"""Install helpers shared by install.sh, install-training.sh, and
`stella doctor` (T63, T66, T138, T139).

One writer for the app-menu launcher, the hicolor icons, and the
install receipt, so the installer and the doctor can never drift
apart. Stdlib only: this module must import even when PySide6 is
missing (a broken install is exactly when the doctor runs).

Called from bash as:
  python -m stella.install desktop <tree> <home> [theme|path]
  python -m stella.install receipt <tree> <home> <version>
  python -m stella.install icons <tree> <home>
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
RECEIPT_NAME = ".stella-install-receipt"
LAUNCHER_NAME = "stella.desktop"


def desktop_entry_text(install_dir: Path, icon: str) -> str:
    """The app-menu launcher. Icon= is NEVER quoted: GLib strips
    quotes from Exec= but NOT from Icon=, so a quoted Icon= shows
    the generic gear (T14). Exec= stays quoted so a spaced install
    path still launches."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Stella\n"
        "Comment=Fine-tune models on your own PC\n"
        f'Exec="{install_dir}/run.sh"\n'
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "StartupWMClass=Stella\n"
        "StartupNotify=true\n"
        "Keywords=fine-tune;machine learning;AI;LoRA;training;\n"
        "Version=1.0\n"
    )


def launcher_path(home_dir: Path) -> Path:
    return home_dir / ".local" / "share" / "applications" / LAUNCHER_NAME


def symlink_path(home_dir: Path) -> Path:
    return home_dir / ".local" / "bin" / "stella"


def hicolor_dir(home_dir: Path) -> Path:
    return home_dir / ".local" / "share" / "icons" / "hicolor"


def hicolor_icon_path(home_dir: Path, size: int) -> Path:
    return hicolor_dir(home_dir) / f"{size}x{size}" / "apps" / "stella.png"


def write_desktop_entry(
    install_dir: Path, home_dir: Path, icon: str = "stella"
) -> Path:
    """Write the app-menu launcher. `icon` is the theme name
    ("stella") when the hicolor install landed, else the absolute
    path to assets/stella.png."""
    dest = launcher_path(home_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = desktop_entry_text(install_dir, icon)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, dest)
    return dest


def _hicolor_index_text() -> str:
    """A minimal index.theme for the user's hicolor dir, written
    only when none exists: it makes the theme a real theme (and
    lets gtk-update-icon-cache build its cache)."""
    dirs = ",".join(f"{s}x{s}/apps" for s in ICON_SIZES)
    lines = [
        "[Icon Theme]",
        "Name=Hicolor",
        "Comment=Fallback icon theme",
        f"Directories={dirs}",
        "",
    ]
    for size in ICON_SIZES:
        lines += [
            f"[{size}x{size}/apps]",
            f"Size={size}",
            "Context=Applications",
            "Type=Fixed",
            "",
        ]
    return "\n".join(lines)


def install_hicolor_icons(install_dir: Path, home_dir: Path) -> bool:
    """Copy the rendered PNGs into the hicolor theme (T138), so the
    menu icon survives a folder move. True when every size landed."""
    assets = install_dir / "assets"
    if not (assets / "stella-48.png").is_file():
        return False
    ok = True
    for size in ICON_SIZES:
        src = assets / f"stella-{size}.png"
        dest = hicolor_icon_path(home_dir, size)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        except OSError:
            ok = False
    index = hicolor_dir(home_dir) / "index.theme"
    if not index.exists():
        try:
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(_hicolor_index_text())
        except OSError:
            ok = False
    if shutil.which("gtk-update-icon-cache"):
        subprocess.run(
            ["gtk-update-icon-cache", "-f", "-t", str(hicolor_dir(home_dir))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False,
        )
    return ok


def remove_hicolor_icons(home_dir: Path) -> None:
    """Undo install_hicolor_icons (uninstall.sh). Leaves the
    index.theme alone: it may predate Stella."""
    for size in ICON_SIZES:
        try:
            hicolor_icon_path(home_dir, size).unlink()
        except OSError:
            pass
    if shutil.which("gtk-update-icon-cache"):
        subprocess.run(
            ["gtk-update-icon-cache", "-f", "-t", str(hicolor_dir(home_dir))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False,
        )


def hicolor_icons_present(home_dir: Path) -> bool:
    return all(
        hicolor_icon_path(home_dir, size).is_file() for size in ICON_SIZES
    )


def _dist_version(name: str) -> str | None:
    try:
        from importlib.metadata import version
    except ImportError:  # pragma: no cover - Python 3.8 fallback
        return None
    try:
        return version(name)
    except Exception:
        return None


def write_receipt(
    install_dir: Path, home_dir: Path, stella_version: str
) -> Path:
    """Write the install receipt (T139): versions, artifact paths,
    install time. A base install writes it; a training install
    re-writes it with the torch versions added (installed_at is
    preserved across re-writes). Written only for a complete
    install: install.sh deletes any stale receipt up front, so a
    failed install leaves no receipt behind."""
    tree = Path(install_dir)
    home = Path(home_dir)
    dest = tree / RECEIPT_NAME
    installed_at = None
    if dest.is_file():
        for line in dest.read_text(errors="replace").splitlines():
            if line.startswith("installed_at:"):
                installed_at = line.split(":", 1)[1].strip()
                break
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if installed_at is None:
        installed_at = now
    desktop_copy = home / "Desktop" / "Stella.desktop"
    lines = [
        "# Stella install receipt. Written by install.sh (and updated by",
        "# install-training.sh). Send this file to Arlo when an install",
        "# breaks: it names the versions, the artifact paths, and the time.",
        f"stella_version: {stella_version}",
        f"installed_at: {installed_at}",
        f"updated_at: {now}",
        f"install_dir: {tree}",
        f"launcher: {launcher_path(home)}",
        "desktop_copy: "
        + (str(desktop_copy) if desktop_copy.is_file() else "not installed"),
        f"symlink: {symlink_path(home)}",
        "icons: "
        + ("hicolor" if hicolor_icons_present(home) else "absolute path"),
    ]
    for label, dist in (
        ("pyside6", "PySide6-Essentials"),
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("peft", "peft"),
        ("accelerate", "accelerate"),
    ):
        ver = _dist_version(dist)
        if ver is not None:
            lines.append(f"{label}: {ver}")
    tmp = dest.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, dest)
    return dest


def read_receipt(install_dir: Path) -> dict[str, str]:
    """The receipt as a dict (missing file reads as empty)."""
    dest = Path(install_dir) / RECEIPT_NAME
    out: dict[str, str] = {}
    if not dest.is_file():
        return out
    for line in dest.read_text(errors="replace").splitlines():
        if line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: python -m stella.install "
            "desktop <tree> <home> [theme|path] | "
            "receipt <tree> <home> <version> | icons <tree> <home>"
        )
        return 0 if args and args[0] in ("-h", "--help") else 2
    cmd = args[0]
    try:
        if cmd == "desktop" and len(args) in (3, 4):
            tree, home = Path(args[1]), Path(args[2])
            mode = args[3] if len(args) == 4 else "theme"
            icon = "stella" if mode == "theme" else str(tree / "assets" / "stella.png")
            write_desktop_entry(tree, home, icon)
            return 0
        if cmd == "receipt" and len(args) == 4:
            write_receipt(Path(args[1]), Path(args[2]), args[3])
            return 0
        if cmd == "icons" and len(args) == 3:
            return 0 if install_hicolor_icons(Path(args[1]), Path(args[2])) else 1
    except OSError as exc:
        print(f"stella.install: {exc}", file=sys.stderr)
        return 1
    print(f"stella.install: unknown command: {' '.join(args)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
