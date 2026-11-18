"""Installer tests (T69 + the installer slice T42/T62-T68/T130/T132-T140).

The real scripts run in a scratch HOME against a copied tree. The
tree copy gets a fake venv python: a shell wrapper that no-ops pip
installs (no network in the suite) and delegates everything else to
the real test python, which has PySide6. So the install path under
test is real — venv check, QApplication check, icon render, desktop
file, symlink, receipt — except the download itself.

One sandbox fact shapes the helper: /tmp is a 512 MB tmpfs, so the
disk-space preflight (T133) would spuriously fail a test run from
tmp_path. Every run sets STELLA_INSTALL_MIN_FREE_KB to a tiny value
except the preflight test itself, which sets it huge.
"""

from __future__ import annotations

import configparser
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from stella.model import STELLA_VERSION

ROOT = Path(__file__).resolve().parent.parent
REAL_PYTHON = sys.executable

ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


# ---------------------------------------------------------------- helpers


def copy_tree(tmp_path: Path, name: str = "stella") -> Path:
    """A fresh copy of the tree (no caches, no venv, no receipt)."""
    dest = tmp_path / name
    shutil.copytree(
        ROOT, dest,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", ".venv", ".git",
            ".stella-install-receipt",
        ),
    )
    return dest


def make_home(tmp_path: Path, name: str = "home", desktop: bool = False) -> Path:
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    if desktop:
        (home / "Desktop").mkdir(exist_ok=True)
    return home


def make_wrapper_venv(
    tree: Path,
    pip_mode: str = "noop",
    qt_probe: str = "ok",
    stub_dir: Path | None = None,
    pip_fail_on: str | None = None,
) -> None:
    """A fake .venv/bin/python: pip installs are no-ops (or failures),
    everything else runs the real test python. `qt_probe="fail"`
    makes the throwaway-QApplication check fail with a missing-lib
    error, the way a real missing system lib would. `pip_fail_on`
    fails only the pip call whose arguments contain that substring
    (e.g. the PySide6 download, not the pip upgrade)."""
    bindir = tree / ".venv" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    pip_exit = "0" if pip_mode == "noop" else "1"
    pip_fail_block = ""
    if pip_fail_on is not None:
        pip_fail_block = (
            'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then\n'
            f'  case "$*" in\n    *{pip_fail_on}*) exit 1 ;;\n  esac\n'
            "fi\n"
        )
    qt_block = ""
    if qt_probe == "fail":
        qt_block = (
            'if [ "$1" = "-c" ]; then\n'
            "  case \"$2\" in\n"
            "    *QApplication*)\n"
            '      echo "libEGL.so.1: cannot open shared object file" >&2\n'
            "      exit 1\n"
            "      ;;\n"
            "  esac\n"
            "fi\n"
        )
    stub_block = ""
    if stub_dir is not None:
        stub_block = (
            f'export PYTHONPATH="{stub_dir}'
            '${PYTHONPATH:+:$PYTHONPATH}"\n'
        )
    wrapper = bindir / "python"
    wrapper.write_text(
        "#!/bin/sh\n"
        "# Fake venv python for installer tests (see test_installer.py).\n"
        + stub_block
        + pip_fail_block
        + 'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then\n'
        f"  exit {pip_exit}\n"
        "fi\n"
        + qt_block
        + f'exec "{REAL_PYTHON}" "$@"\n'
    )
    wrapper.chmod(0o755)


def run_script(
    tree: Path,
    home: Path,
    script: str,
    *args: str,
    env_extra: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Run one of the tree's scripts with a scratch HOME."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    # The preflight threshold would fail on the 512 MB /tmp tmpfs;
    # the preflight test overrides this itself.
    env.setdefault("STELLA_INSTALL_MIN_FREE_KB", "1024")
    # R60: no real network in the suite — the connectivity
    # pre-check is skipped except in its own test, which points
    # it at a dead local address.
    env.setdefault("STELLA_INSTALL_SKIP_NET_CHECK", "1")
    if env_extra:
        # R118: a None value REMOVES the variable (a test that
        # must run display-less strips QT_QPA_PLATFORM/DISPLAY
        # rather than inheriting the pytest process's values).
        for key, value in env_extra.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    return subprocess.run(
        ["bash", script, *args],
        cwd=tree, env=env, capture_output=True, text=True,
        input=input_text, timeout=timeout, check=False,
    )


def run_install(tree: Path, home: Path, **kw) -> subprocess.CompletedProcess:
    return run_script(tree, home, "install.sh", **kw)


def installed(
    tree: Path, home: Path, env_extra: dict[str, str] | None = None,
    **venv_kw
) -> subprocess.CompletedProcess:
    """A tree + HOME with a completed base install (or a failed
    assertion with the install output attached). Extra keywords go
    to make_wrapper_venv; env_extra goes to the install run."""
    make_wrapper_venv(tree, **venv_kw)
    res = run_install(tree, home, env_extra=env_extra)
    assert res.returncode == 0, (
        f"install failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )
    return res


def parse_desktop(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str  # keep Icon=/Exec= case as written
    cp.read(path)
    return cp


def resolve_desktop_icon(desktop_file: Path, home: Path) -> Path | None:
    """Resolve the Icon= value the way GLib/Gtk do (freedesktop icon
    theme spec): an absolute path must exist; a theme name is looked
    up in the hicolor theme under the XDG data dirs. Returns the
    resolved file, or None when nothing resolves (the generic-gear
    case). A quoted Icon= never resolves — that is the A6-W1 bug
    this check exists to catch, and no GLib binding is available in
    this sandbox, so the lookup is implemented here."""
    icon = parse_desktop(desktop_file).get("Desktop Entry", "Icon")
    if icon != icon.strip() or '"' in icon or "'" in icon:
        return None
    if "/" in icon:
        found = Path(icon)
        return found if found.is_file() and found.stat().st_size > 0 else None
    data_dirs = [home / ".local" / "share"]
    data_dirs += [
        Path(d) for d in os.environ.get(
            "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
        ).split(":")
        if d
    ]
    for base in data_dirs:
        for size in ICON_SIZES:
            for ext in ("png", "svg", "xpm"):
                found = (
                    base / "icons" / "hicolor" / f"{size}x{size}"
                    / "apps" / f"{icon}.{ext}"
                )
                if found.is_file() and found.stat().st_size > 0:
                    return found
    return None


def make_train_stubs(tmp_path: Path) -> Path:
    """Fake torch/transformers/peft/accelerate modules plus dist-info
    dirs, so the training fast path (T134) and the receipt (T139)
    can be tested without the 2 GB download."""
    stubs = tmp_path / "train-stubs"
    stubs.mkdir()
    for name, version in (
        ("torch", "2.15.0+cpu"),
        ("transformers", "5.22.2"),
        ("peft", "0.21.2"),
        ("accelerate", "1.15.0"),
    ):
        (stubs / f"{name}.py").write_text(
            f'__version__ = "{version}"\n\n'
            "def get_num_threads():\n"
            "    return 4\n"
        )
        dist = stubs / f"{name}-{version}.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(
            "Metadata-Version: 2.1\n"
            f"Name: {name}\n"
            f"Version: {version}\n"
        )
    return stubs


def make_xdg_user_dir_stub(tmp_path: Path) -> Path:
    """A fake `xdg-user-dir` on a fresh bin dir (the real tool is
    not installed in the sandbox): it reads
    $XDG_CONFIG_HOME/user-dirs.dirs and prints XDG_DESKTOP_DIR
    with $HOME expanded, falling back to $HOME/Desktop — the
    real tool's contract, which is all the code under test
    relies on. Returns the bin dir; prepend it to PATH."""
    bindir = tmp_path / "xdg-bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "xdg-user-dir"
    stub.write_text(
        "#!/bin/sh\n"
        "# Fake xdg-user-dir for installer tests (see test_installer.py).\n"
        "config=\"${XDG_CONFIG_HOME:-$HOME/.config}/user-dirs.dirs\"\n"
        "dir=\"\"\n"
        "if [ -f \"$config\" ]; then\n"
        "  dir=$(grep '^XDG_DESKTOP_DIR=' \"$config\" "
        "| cut -d= -f2- | tr -d '\"')\n"
        "  case \"$dir\" in\n"
        "    '$HOME/'*) dir=\"$HOME/${dir#\\$HOME/}\" ;;\n"
        "    '$HOME') dir=\"$HOME\" ;;\n"
        "  esac\n"
        "fi\n"
        "if [ -n \"$dir\" ]; then printf '%s\\n' \"$dir\"; "
        "else printf '%s\\n' \"$HOME/Desktop\"; fi\n"
    )
    stub.chmod(0o755)
    return bindir


def make_localized_desktop_env(tmp_path: Path, home: Path) -> dict[str, str]:
    """Env for a localized desktop (R119): XDG_CONFIG_HOME points
    at a fixture whose user-dirs.dirs names $HOME/Bureau as the
    desktop, and the fake xdg-user-dir is first on PATH. The
    caller creates the Bureau dir itself (a resolved dir that
    does not exist gets no copy, as before)."""
    config_home = tmp_path / "xdg-config"
    config_home.mkdir(exist_ok=True)
    (config_home / "user-dirs.dirs").write_text(
        'XDG_DESKTOP_DIR="$HOME/Bureau"\n'
    )
    bindir = make_xdg_user_dir_stub(tmp_path)
    return {
        "XDG_CONFIG_HOME": str(config_home),
        "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
    }


# ---------------------------------------------------------------- static


def test_scripts_are_executable_in_tree():
    """T65: a fresh clone has the scripts executable."""
    for name in (
        "run.sh", "stella-cli", "install.sh", "install-training.sh",
        "run_tests.sh", "uninstall.sh",
    ):
        path = ROOT / name
        assert path.is_file(), f"missing: {name}"
        assert os.access(path, os.X_OK), f"not executable: {name}"


def test_install_desktop_file_is_executable_in_tree():
    """T64/T65: the double-click installer must be executable or
    Nemo will not offer to launch it."""
    path = ROOT / "Install Stella.desktop"
    assert path.is_file()
    assert os.access(path, os.X_OK)


def test_pip_lines_carry_timeout_and_retries():
    """T67: every pip install line in the installers (and the test
    runner) retries on a slow connection instead of failing at 15 s."""
    for name in ("install.sh", "install-training.sh", "run_tests.sh"):
        text = (ROOT / name).read_text()
        pip_lines = [
            ln for ln in text.splitlines()
            if "pip install" in ln and not ln.strip().startswith("#")
        ]
        assert pip_lines, f"no pip install line in {name}"
        for line in pip_lines:
            assert "--timeout 120" in line, f"{name}: {line}"
            assert "--retries 10" in line, f"{name}: {line}"


def test_requirements_are_pinned_and_consumed():
    """T130: the pinned files name the verified versions, and the
    installers consume them instead of naming bare packages."""
    base = (ROOT / "requirements-base.txt").read_text()
    assert "PySide6-Essentials==6.12.0" in base
    assert "PySide6-Addons==6.12.0" in base
    train = (ROOT / "requirements-train.txt").read_text()
    assert "torch==2.15.0+cpu" in train
    assert "transformers==5.22.2" in train
    assert "peft==0.21.2" in train
    assert "accelerate==1.15.0" in train
    assert "download.pytorch.org/whl/cpu" in train
    install = (ROOT / "install.sh").read_text()
    assert "-r \"$DIR/requirements-base.txt\"" in install
    assert "PySide6-Essentials PySide6-Addons" not in install
    training = (ROOT / "install-training.sh").read_text()
    assert "-r \"$DIR/requirements-train.txt\"" in training
    assert "transformers peft accelerate" not in training


def test_license_mit_and_ci_workflow():
    """T130: LICENSE is MIT; CI runs the suite on push."""
    license_text = (ROOT / "LICENSE").read_text()
    assert "MIT License" in license_text
    assert "Broke n' Bored" in license_text
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    assert ci.is_file()
    ci_text = ci.read_text()
    assert "pytest" in ci_text
    assert "requirements-base.txt" in ci_text
    assert "requirements-train.txt" in ci_text
    assert "push" in ci_text


def test_gitignore_covers_receipt_venv_and_pycache():
    """T130/T139: the ignore rules cover the venv, caches, homes,
    and the per-install receipt."""
    ignored = (ROOT / ".gitignore").read_text()
    for rule in (".venv/", "__pycache__/", ".stella/",
                 ".stella-install-receipt"):
        assert rule in ignored, f"missing .gitignore rule: {rule}"


def test_readme_documents_install_upgrade_removal_repair():
    """T64/T66/T137/T140: the README's install story names a file
    that exists, qualifies the stella command, and documents the
    upgrade, repair, and removal paths."""
    readme = (ROOT / "README.md").read_text()
    # Flattened: the phrases may wrap across lines in the source.
    flat = " ".join(readme.split())
    assert "Install Stella.desktop" in flat
    assert "open a new terminal" in flat
    assert "log out and back in" in flat
    assert "## Upgrade to a new version" in readme
    assert "delete the old folder" in flat
    assert "## Moved the folder? Repair it" in readme
    assert "stella-cli doctor" in flat
    assert "## Remove Stella" in readme
    assert "bash uninstall.sh" in flat


# ---------------------------------------------------------------- install


def test_install_end_to_end(tmp_path):
    """T69/T63/T136/T138/T139: a full install in a scratch HOME with
    no Desktop dir — launcher, theme icon, symlink, receipt, and a
    success message that claims only what landed."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path, desktop=False)
    install_res = installed(tree, home)

    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    assert launcher.is_file()
    entry = parse_desktop(launcher)
    assert entry.get("Desktop Entry", "Name") == "Stella"
    assert entry.get("Desktop Entry", "Exec") == f'"{tree}/run.sh"'
    assert entry.get("Desktop Entry", "Icon") == "stella"
    assert entry.get("Desktop Entry", "Terminal") == "false"

    hicolor = home / ".local" / "share" / "icons" / "hicolor"
    for size in ICON_SIZES:
        icon = hicolor / f"{size}x{size}" / "apps" / "stella.png"
        assert icon.is_file() and icon.stat().st_size > 0, f"missing {size}"
    assert (hicolor / "index.theme").is_file()

    link = home / ".local" / "bin" / "stella"
    assert link.is_symlink()
    assert link.resolve() == (tree / "stella-cli").resolve()
    res = subprocess.run(
        [str(link), "--version"], cwd=tree,
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 0
    assert res.stdout.strip() == f"stella {STELLA_VERSION}"

    receipt = tree / ".stella-install-receipt"
    assert receipt.is_file()
    receipt_text = receipt.read_text()
    assert f"stella_version: {STELLA_VERSION}" in receipt_text
    assert "pyside6: 6.12.0" in receipt_text
    assert "installed_at:" in receipt_text
    assert f"launcher: {launcher}" in receipt_text
    assert "icons: hicolor" in receipt_text

    assert "Traceback" not in install_res.stdout + install_res.stderr


def test_install_success_message_reflects_reality(tmp_path):
    """T136: with no ~/Desktop the message claims no desktop icon;
    with ~/.local/bin off PATH it says to open a new terminal; the
    version line is labeled."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path, desktop=False)
    res = installed(tree, home)
    assert f"Stella {STELLA_VERSION} is installed." in res.stdout
    assert "double-click Stella on the desktop" not in res.stdout
    assert "open a new terminal" in res.stdout
    assert "Traceback" not in res.stdout + res.stderr


def test_install_claims_desktop_icon_when_copy_lands(tmp_path):
    """T136: with a ~/Desktop dir the copy lands and the message
    claims it."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path, desktop=True)
    res = installed(tree, home)
    copy = home / "Desktop" / "Stella.desktop"
    assert copy.is_file()
    assert os.access(copy, os.X_OK)
    assert "double-click Stella on the desktop" in res.stdout
    receipt = (tree / ".stella-install-receipt").read_text()
    assert f"desktop_copy: {copy}" in receipt


def test_icon_resolves_via_theme_lookup(tmp_path):
    """T69/T138: the installed launcher's icon resolves through the
    freedesktop lookup GLib performs — and a quoted Icon= (the
    A6-W1 bug) resolves to nothing."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    found = resolve_desktop_icon(launcher, home)
    assert found is not None
    assert found.name == "stella.png"

    quoted = tmp_path / "quoted.desktop"
    quoted.write_text(
        "[Desktop Entry]\nType=Application\nName=Stella\n"
        'Icon="stella"\n'
    )
    assert resolve_desktop_icon(quoted, home) is None
    missing = tmp_path / "missing.desktop"
    missing.write_text(
        "[Desktop Entry]\nType=Application\nName=Stella\n"
        "Icon=/no/such/dir/stella.png\n"
    )
    assert resolve_desktop_icon(missing, home) is None


def test_reinstall_is_idempotent(tmp_path):
    """T69: running install.sh twice leaves one working install."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    res = run_install(tree, home)
    assert res.returncode == 0, res.stdout + res.stderr
    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    assert launcher.is_file()
    assert (home / ".local" / "bin" / "stella").is_symlink()
    assert (tree / ".stella-install-receipt").is_file()


def test_sabotaged_import_leaves_no_launcher(tmp_path):
    """T63: a sabotaged final check exits 1 with no desktop file,
    no symlink, and no receipt left behind."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    (tree / "stella" / "__init__.py").write_text(
        'raise RuntimeError("sabotaged")\n'
    )
    make_wrapper_venv(tree)
    res = run_install(tree, home)
    assert res.returncode == 1
    assert "Stella did not import after install." in res.stderr
    assert not (home / ".local" / "share" / "applications"
                / "stella.desktop").exists()
    assert not (home / ".local" / "bin" / "stella").exists()
    assert not (tree / ".stella-install-receipt").exists()


def test_stray_file_at_venv_survives_with_real_error(tmp_path):
    """T42: a stray file at .venv gets the real venv error (not the
    python3-venv message) and is not deleted."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    stray = tree / ".venv"
    stray.write_text("do not delete me\n")
    res = run_install(tree, home)
    assert res.returncode == 1
    assert stray.is_file()
    assert stray.read_text() == "do not delete me\n"
    out = res.stdout + res.stderr
    assert "python3-venv is missing" not in out
    assert "Unable to create directory" in out
    assert "could not create the Python environment" in out


def test_missing_venv_module_names_the_fix(tmp_path):
    """T42: a python3 without the venv module still gets the exact
    named fix."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    fake_python = stubs / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "echo \"ModuleNotFoundError: No module named 'venv'\" >&2\n"
        "exit 1\n"
    )
    fake_python.chmod(0o755)
    env = {"PATH": f"{stubs}:{os.environ['PATH']}"}
    res = run_install(tree, home, env_extra=env)
    assert res.returncode == 1
    assert "python3-venv is missing" in res.stderr
    assert "sudo apt install python3-venv" in res.stderr
    assert not (tree / ".venv").exists()


def test_run_sh_without_pyside6_fails_visibly(tmp_path):
    """T62: a venv without PySide6 prints a plain message naming
    the fix — no traceback."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    bindir = tree / ".venv" / "bin"
    bindir.mkdir(parents=True)
    # System python3 has no PySide6: the post-pip-failure state.
    (bindir / "python").symlink_to("/usr/bin/python3")
    res = run_script(tree, home, "run.sh")
    assert res.returncode == 1
    out = res.stdout + res.stderr
    assert "Traceback" not in out
    assert "ModuleNotFoundError" not in out
    assert "PySide6 is missing" in out
    assert "bash install.sh" in out


def test_pip_failure_gets_a_stella_line(tmp_path):
    """T132: a failed pip install ends with a Stella line naming
    the step and the retry."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    make_wrapper_venv(tree, pip_fail_on="requirements-base.txt")
    res = run_install(tree, home)
    assert res.returncode == 1
    out = res.stdout + res.stderr
    assert "PySide6 download failed" in out
    assert "run bash install.sh again" in out
    assert not (home / ".local" / "share" / "applications"
                / "stella.desktop").exists()


def test_disk_preflight_refuses(tmp_path):
    """T133: with too little free space the install refuses before
    downloading, naming the space needed — base and training."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    huge = {"STELLA_INSTALL_MIN_FREE_KB": "999999999"}
    res = run_install(tree, home, env_extra=huge)
    assert res.returncode == 1
    assert "not enough free disk space" in res.stderr
    # The message names the (overridden) space needed: 999999999 KB.
    assert "976562 MB" in res.stderr
    assert "Free some space" in res.stderr
    assert not (tree / ".venv").exists()

    tree2 = copy_tree(tmp_path, "stella2")
    make_wrapper_venv(tree2)
    res = run_script(tree2, home, "install-training.sh", env_extra=huge)
    assert res.returncode == 1
    assert "not enough free disk space" in res.stderr
    assert "953 GB" in res.stderr


def test_pyside6_check_names_missing_lib(tmp_path):
    """T135: when the throwaway QApplication cannot start, the
    install fails with the real error named. R57: the advice
    names the apt package to install, the way the doctor does."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    make_wrapper_venv(tree, qt_probe="fail")
    res = run_install(tree, home)
    assert res.returncode == 1
    out = res.stdout + res.stderr
    assert "cannot start a window" in out
    assert "libEGL.so.1" in out
    assert "sudo apt install libegl1" in out
    assert not (home / ".local" / "share" / "applications"
                / "stella.desktop").exists()


def test_clone_without_pngs_renders_icons(tmp_path):
    """T69: a clone (SVG only, no PNGs) renders the icons at
    install time and still lands a working install."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    for png in (tree / "assets").glob("*.png"):
        png.unlink()
    assert (tree / "assets" / "stella.svg").is_file()
    installed(tree, home)
    for size in ICON_SIZES:
        assert (tree / "assets" / f"stella-{size}.png").is_file()
    assert (tree / "assets" / "stella.png").is_file()
    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    assert resolve_desktop_icon(launcher, home) is not None


def test_install_stella_desktop_runs_installer(tmp_path):
    """T64: the double-click launcher resolves its own folder (via
    %k, not the working directory) and runs install.sh with bash.
    Its Exec line carries no nested escaped quotes (GLib rejects
    those) and it asks for a terminal so the result stays visible."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    make_wrapper_venv(tree)
    desktop = tree / "Install Stella.desktop"
    entry = parse_desktop(desktop)
    assert entry.get("Desktop Entry", "Name") == "Install Stella"
    assert entry.get("Desktop Entry", "Terminal") == "true"
    assert entry.get("Desktop Entry", "Type") == "Application"
    exec_line = entry.get("Desktop Entry", "Exec")
    assert "install_launcher.py" in exec_line
    assert "%k" in exec_line
    assert '\\"' not in exec_line  # no nested escaped quotes
    # The launcher it runs is the file that runs install.sh.
    launcher_src = (tree / "install_launcher.py").read_text()
    assert '"install.sh"' in launcher_src
    assert '"bash"' in launcher_src
    # Run the Exec line the way the desktop environment would, from
    # a different working directory, with %k expanded to the file.
    argv = [str(desktop) if a == "%k" else a for a in shlex.split(exec_line)]
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["STELLA_INSTALL_MIN_FREE_KB"] = "1024"
    # No real network in the suite (R60): the connectivity check is
    # covered by its own test, so skip it here like run_script does.
    env["STELLA_INSTALL_SKIP_NET_CHECK"] = "1"
    res = subprocess.run(
        argv, cwd=tmp_path, env=env, capture_output=True, text=True,
        input="\n", timeout=300, check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"Stella {STELLA_VERSION} is installed." in res.stdout
    assert (home / ".local" / "share" / "applications"
            / "stella.desktop").is_file()
    assert (home / ".local" / "bin" / "stella").is_symlink()


def test_install_training_desktop_file_is_executable_in_tree():
    """R13: the double-click training installer must be executable
    or Nemo will not offer to launch it."""
    path = ROOT / "Install Training Stella.desktop"
    assert path.is_file()
    assert os.access(path, os.X_OK)


def test_install_training_desktop_runs_training_installer(tmp_path):
    """R13: the training double-click launcher resolves its own
    folder (via %k, not the working directory) and runs
    install-training.sh with bash. Its Exec line carries no
    nested escaped quotes (GLib rejects those) and it asks for a
    terminal so the result stays visible."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    stubs = make_train_stubs(tmp_path)
    make_wrapper_venv(tree, stub_dir=stubs)
    desktop = tree / "Install Training Stella.desktop"
    entry = parse_desktop(desktop)
    assert entry.get("Desktop Entry", "Name") == "Install Stella Training"
    assert entry.get("Desktop Entry", "Terminal") == "true"
    assert entry.get("Desktop Entry", "Type") == "Application"
    exec_line = entry.get("Desktop Entry", "Exec")
    assert "install_training_launcher.py" in exec_line
    assert "%k" in exec_line
    assert '\\"' not in exec_line  # no nested escaped quotes
    # The launcher it runs is the file that runs install-training.sh.
    launcher_src = (tree / "install_training_launcher.py").read_text()
    assert '"install-training.sh"' in launcher_src
    assert '"bash"' in launcher_src
    # Run the Exec line the way the desktop environment would, from
    # a different working directory, with %k expanded to the file.
    # The stubbed venv takes the training fast path (already
    # installed), so no download happens.
    argv = [str(desktop) if a == "%k" else a for a in shlex.split(exec_line)]
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["STELLA_INSTALL_MIN_FREE_KB"] = "1024"
    res = subprocess.run(
        argv, cwd=tmp_path, env=env, capture_output=True, text=True,
        input="\n", timeout=300, check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Training packages are already installed." in res.stdout
    assert "Training install finished." in res.stdout


def test_install_places_training_icon_on_desktop(tmp_path):
    """R13: the base install puts the training installer on the
    desktop too, executable, so training setup is one
    double-click from the desktop."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path, desktop=True)
    res = installed(tree, home)
    icon = home / "Desktop" / "Install Stella Training.desktop"
    assert icon.is_file()
    assert os.access(icon, os.X_OK)
    assert "Training installs from the desktop too" in res.stdout


def test_desktop_training_icon_runs_from_the_desktop(tmp_path):
    """v0.27.0 (R13 fix): the Desktop copy of the training icon
    names this install's launcher by absolute path — the tree
    copy's %k form resolves to ~/Desktop, where the launcher is
    not, so the v0.25.0 Desktop copy failed on double-click with
    \"can't open file\". Run the Desktop copy the way the desktop
    environment would, from another working directory, with %k
    expanded to the Desktop copy."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path, desktop=True)
    stubs = make_train_stubs(tmp_path)
    installed(tree, home, stub_dir=stubs)
    icon = home / "Desktop" / "Install Stella Training.desktop"
    assert icon.is_file()
    exec_line = parse_desktop(icon).get("Desktop Entry", "Exec")
    assert "%k" not in exec_line
    assert str(tree / "install_training_launcher.py") in exec_line
    assert '\\"' not in exec_line  # no nested escaped quotes
    argv = [str(icon) if a == "%k" else a for a in shlex.split(exec_line)]
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["STELLA_INSTALL_MIN_FREE_KB"] = "1024"
    res = subprocess.run(
        argv, cwd=tmp_path, env=env, capture_output=True, text=True,
        input="\n", timeout=300, check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Training packages are already installed." in res.stdout
    assert "Training install finished." in res.stdout


# ---------------------------------------------------------------- training


def test_training_fast_path(tmp_path):
    """T134: a second run with everything installed exits in
    seconds with the plain message."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    stubs = make_train_stubs(tmp_path)
    make_wrapper_venv(tree, stub_dir=stubs)
    start = time.monotonic()
    res = run_script(tree, home, "install-training.sh")
    elapsed = time.monotonic() - start
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Training packages are already installed." in res.stdout
    assert elapsed < 60


def test_training_pip_failure_gets_a_stella_line(tmp_path):
    """T132: a failed training download ends with a Stella line
    naming the step and the retry."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    make_wrapper_venv(tree, pip_mode="fail")
    res = run_script(tree, home, "install-training.sh")
    assert res.returncode == 1
    out = res.stdout + res.stderr
    assert "training packages download failed" in out
    assert "run bash install-training.sh again" in out


def test_training_install_updates_receipt(tmp_path):
    """T139: after the training install the receipt names the
    torch versions too (and keeps the base install's time)."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    stubs = make_train_stubs(tmp_path)
    # Base install first, with no training stack present.
    installed(tree, home)
    receipt = (tree / ".stella-install-receipt").read_text()
    assert "torch:" not in receipt
    installed_at = [ln for ln in receipt.splitlines()
                    if ln.startswith("installed_at:")][0]
    # Now the training stack is present (stubs on the venv path).
    make_wrapper_venv(tree, stub_dir=stubs)
    res = run_script(tree, home, "install-training.sh")
    assert res.returncode == 0, res.stdout + res.stderr
    receipt = (tree / ".stella-install-receipt").read_text()
    assert "torch: 2.15.0+cpu" in receipt
    assert "transformers: 5.22.2" in receipt
    assert "peft: 0.21.2" in receipt
    assert "accelerate: 1.15.0" in receipt
    assert installed_at in receipt  # the base install time survives


# ---------------------------------------------------------------- uninstall


def test_uninstall_removes_artifacts_keeps_data(tmp_path):
    """T137: uninstall after install leaves no artifacts — except
    ~/.stella, which is kept."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path, desktop=True)
    installed(tree, home)
    data = home / ".stella" / "profiles"
    data.mkdir(parents=True)
    (data / "keep.json").write_text("{}\n")
    res = run_script(tree, home, "uninstall.sh", "--yes")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Your data is still in" in res.stdout
    assert not (home / ".local" / "share" / "applications"
                / "stella.desktop").exists()
    assert not (home / "Desktop" / "Stella.desktop").exists()
    assert not (home / "Desktop" / "Install Stella Training.desktop").exists()
    assert not (home / ".local" / "bin" / "stella").exists()
    assert not (tree / ".venv").exists()
    assert not (tree / ".stella-install-receipt").exists()
    hicolor = home / ".local" / "share" / "icons" / "hicolor"
    for size in ICON_SIZES:
        assert not (hicolor / f"{size}x{size}" / "apps"
                    / "stella.png").exists()
    assert (data / "keep.json").is_file()


def test_uninstall_remove_data(tmp_path):
    """T137: --remove-data removes ~/.stella too."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    (home / ".stella").mkdir()
    (home / ".stella" / "keep.json").write_text("{}\n")
    res = run_script(tree, home, "uninstall.sh", "--remove-data")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not (home / ".stella").exists()


def test_uninstall_asks_and_defaults_to_no(tmp_path):
    """T137: the interactive prompt defaults to No — an empty
    answer keeps the data."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    (home / ".stella").mkdir()
    (home / ".stella" / "keep.json").write_text("{}\n")
    res = run_script(tree, home, "uninstall.sh", input_text="\n")
    assert res.returncode == 0, res.stdout + res.stderr
    assert (home / ".stella" / "keep.json").is_file()
    assert not (home / ".local" / "bin" / "stella").exists()


# ---------------------------------------------------------------- doctor


def test_doctor_repairs_after_move(tmp_path):
    """T66/T138: move the folder, run the doctor, and the launcher
    and the stella command work again from the new location — and
    the menu icon (hicolor, in HOME) never noticed the move."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    moved = tmp_path / "moved to"
    shutil.move(str(tree), str(moved))
    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    assert str(tree / "run.sh") in launcher.read_text()
    link = home / ".local" / "bin" / "stella"
    assert not link.exists()  # dangling now
    env = dict(os.environ)
    env["HOME"] = str(home)
    res = subprocess.run(
        ["bash", "stella-cli", "doctor"], cwd=moved, env=env,
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "FIXED" in res.stdout
    assert str(moved / "run.sh") in launcher.read_text()
    assert link.resolve() == (moved / "stella-cli").resolve()
    res = subprocess.run(
        [str(link), "--version"], cwd=moved,
        capture_output=True, text=True, check=False,
    )
    assert res.stdout.strip() == f"stella {STELLA_VERSION}"
    assert resolve_desktop_icon(launcher, home) is not None
    receipt = (moved / ".stella-install-receipt").read_text()
    assert f"install_dir: {moved}" in receipt


def test_doctor_fix_writes_no_receipt_without_an_install(tmp_path):
    """T66/T139: a repair on a folder that was never installed
    writes NO receipt — there is no complete install to record,
    and a receipt claiming one would lie about a broken install.
    R58: with no venv the doctor no longer repairs the launch
    artifacts either — it names the broken venv instead, so no
    launcher is written at all."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    env = dict(os.environ)
    env["HOME"] = str(home)
    res = subprocess.run(
        ["bash", "stella-cli", "doctor"], cwd=tree, env=env,
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert res.returncode == 1  # venv still missing: honest failure
    assert "Python environment" in res.stdout
    assert not (home / ".local" / "share" / "applications"
                / "stella.desktop").exists()
    assert not (home / ".local" / "bin" / "stella").exists()
    assert not (tree / ".stella-install-receipt").exists()


def test_doctor_reports_broken_venv(tmp_path):
    """T66: a broken venv is reported with the fix named."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    shutil.rmtree(tree / ".venv")
    env = dict(os.environ)
    env["HOME"] = str(home)
    res = subprocess.run(
        ["bash", "stella-cli", "doctor", "--check"], cwd=tree, env=env,
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert res.returncode == 1
    assert "BROKEN" in res.stdout
    assert "venv" in res.stdout
    assert "bash install.sh" in res.stdout


def test_doctor_check_only_reports_without_fixing(tmp_path):
    """T66: --check reports a stale launcher without fixing it."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    moved = tmp_path / "moved"
    shutil.move(str(tree), str(moved))
    env = dict(os.environ)
    env["HOME"] = str(home)
    res = subprocess.run(
        ["bash", "stella-cli", "doctor", "--check"], cwd=moved, env=env,
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert res.returncode == 1
    assert "BROKEN" in res.stdout
    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    assert str(tree / "run.sh") in launcher.read_text()


# ---------------------------------------------------------------- test runner


def test_run_tests_sh_refuses_bare_checkout(tmp_path):
    """T68: on a bare checkout run_tests.sh refuses with the plain
    message instead of pip-installing into system Python."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    res = run_script(tree, home, "run_tests.sh")
    assert res.returncode == 1
    out = res.stdout + res.stderr
    assert "bash install.sh first" in out
    assert "externally-managed" not in out
    assert "Installing pytest" not in out


# ---------------------------------------------------------------- v0.27.0


def test_uninstall_leaves_a_newer_install_alone(tmp_path):
    """R59: after an upgrade (install B re-points the launcher,
    desktop icon, and command), running the OLD folder's
    uninstall leaves the NEW install's artifacts alone — and
    still removes the old folder's own venv and receipt."""
    tree_a = copy_tree(tmp_path, "stella-a")
    tree_b = copy_tree(tmp_path, "stella-b")
    home = make_home(tmp_path, desktop=True)
    installed(tree_a, home)
    installed(tree_b, home)
    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    desktop = home / "Desktop" / "Stella.desktop"
    link = home / ".local" / "bin" / "stella"
    training = home / "Desktop" / "Install Stella Training.desktop"
    assert str(tree_b / "run.sh") in launcher.read_text()
    assert str(tree_b / "run.sh") in desktop.read_text()
    assert link.resolve() == (tree_b / "stella-cli").resolve()
    assert str(tree_b / "install_training_launcher.py") in training.read_text()

    res = run_script(tree_a, home, "uninstall.sh", "--yes")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "left alone" in res.stdout
    # The newer install's artifacts survive, still pointing at B.
    assert str(tree_b / "run.sh") in launcher.read_text()
    assert str(tree_b / "run.sh") in desktop.read_text()
    assert link.resolve() == (tree_b / "stella-cli").resolve()
    assert str(tree_b / "install_training_launcher.py") in training.read_text()
    # The old folder's own install is gone.
    assert not (tree_a / ".venv").exists()
    assert not (tree_a / ".stella-install-receipt").exists()
    # ... while the new folder's install is untouched.
    assert (tree_b / ".venv").exists()
    assert (tree_b / ".stella-install-receipt").exists()


def test_uninstall_removes_its_own_neighbour_folder_launchers(tmp_path):
    """R59: the ownership check is "points at this folder's
    run.sh", not a prefix match — a launcher pointing at a
    neighbouring folder (stella-2, which contains "stella" as a
    substring) is NOT this install's to remove."""
    tree = copy_tree(tmp_path, "stella")
    home = make_home(tmp_path)
    installed(tree, home)
    neighbour = tmp_path / "stella-2"
    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    text = launcher.read_text().replace(
        str(tree / "run.sh"), str(neighbour / "run.sh")
    )
    launcher.write_text(text)
    res = run_script(tree, home, "uninstall.sh", "--yes")
    assert res.returncode == 0, res.stdout + res.stderr
    assert launcher.is_file()
    assert "left alone" in res.stdout


def test_install_says_what_it_is_waiting_for(tmp_path):
    """R60: a base install says what is being downloaded before
    each pip step, so a slow connection never looks stuck."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    res = installed(tree, home)
    assert "PySide6 download" in res.stdout
    assert "this can take a few minutes on a slow connection" in res.stdout


def test_install_fails_fast_with_no_network(tmp_path):
    """R60: with no network, the base install fails in seconds
    with a plain message — it does not sit in pip's retry loop
    for minutes in silence. The check is pointed at a dead
    local address, so no real network is involved."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    make_wrapper_venv(tree)
    start = time.monotonic()
    res = run_script(
        tree, home, "install.sh",
        env_extra={
            "STELLA_INSTALL_SKIP_NET_CHECK": "",
            "STELLA_INSTALL_NET_CHECK_URL": "http://127.0.0.1:1/",
        },
    )
    elapsed = time.monotonic() - start
    assert res.returncode == 1
    assert elapsed < 30, f"took {elapsed:.1f}s"
    out = res.stdout + res.stderr
    assert "Checking the network connection" in out
    assert "no network connection" in out
    assert "PySide6 download" not in out  # pip never started


def test_training_preflight_default_is_5_gb(tmp_path):
    """R61: the training preflight defaults to 5 GB — the
    conservative number until R23 measures the real peak — and
    the refusal names it."""
    text = (ROOT / "install-training.sh").read_text()
    assert 'STELLA_INSTALL_MIN_FREE_KB:-5242880' in text
    assert "--no-cache-dir" in text
    # Behavioural: with the threshold at its default (an empty
    # override means "use the default") and a disk reporting
    # 1 GB free, the install refuses and names 5 GB. The disk
    # size comes from a fake df on PATH — the suite's TMPDIR is
    # the workspace, which has far more than 5 GB free.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_df = bindir / "df"
    fake_df.write_text("#!/bin/sh\necho Avail\necho 1000000\n")
    fake_df.chmod(0o755)
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    make_wrapper_venv(tree)
    res = run_script(
        tree, home, "install-training.sh",
        env_extra={
            "STELLA_INSTALL_MIN_FREE_KB": "",
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
        },
    )
    assert res.returncode == 1
    assert "not enough free disk space" in res.stderr
    assert "5 GB" in res.stderr


# -- R62: the training download resumes, through the real script --


def _make_report_writing_venv(tree, report_json):
    """A fake .venv/bin/python whose pip writes a --dry-run
    --report (the given JSON) instead of resolving, and no-ops
    every other pip call. Everything else runs the real test
    python."""
    bindir = tree / ".venv" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    wrapper = bindir / "python"
    wrapper.write_text(
        "#!/bin/sh\n"
        "# Fake venv python for the R62 resume test: pip --dry-run\n"
        "# writes the canned report; other pip calls are no-ops.\n"
        'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then\n'
        "  prev=\"\"\n"
        "  report=\"\"\n"
        '  for arg in "$@"; do\n'
        '    if [ "$prev" = "--report" ]; then report="$arg"; fi\n'
        '    prev="$arg"\n'
        "  done\n"
        '  if [ -n "$report" ]; then\n'
        "    cat > \"$report\" <<'R62_REPORT_EOF'\n"
        + report_json
        + "\nR62_REPORT_EOF\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        f'exec "{REAL_PYTHON}" "$@"\n'
    )
    wrapper.chmod(0o755)


class _ResumeWheelServer:
    """A tiny Range-supporting wheel server for the R62
    installer test: two fake wheels, a kill mode that cuts
    every download short, and a request log."""

    def __init__(self):
        import hashlib
        from http.server import (
            BaseHTTPRequestHandler,
            ThreadingHTTPServer,
        )

        self.files = {
            "torch-2.15.0-cp312-cp312-manylinux.whl": b"T" * 4096,
            "peft-0.21.2-py3-none-any.whl": b"P" * 2048,
        }
        self.hashes = {
            name: hashlib.sha256(data).hexdigest()
            for name, data in self.files.items()
        }
        self.log = []
        self.mode = "normal"
        self.kill_after = 512
        state = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                name = self.path.lstrip("/")
                data = state.files.get(name)
                if data is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                range_header = self.headers.get("Range")
                start = 0
                status = 200
                if range_header:
                    try:
                        start = int(
                            range_header.split("=", 1)[1].split("-", 1)[0]
                        )
                    except ValueError:
                        start = 0
                    if start >= len(data):
                        self.send_response(416)
                        self.send_header(
                            "Content-Range", f"bytes */{len(data)}"
                        )
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        state.log.append(
                            (self.path, range_header, 0, 416)
                        )
                        return
                    status = 206
                body = data[start:]
                cut = (
                    state.mode == "kill"
                    and len(body) > state.kill_after
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
                    self.wfile.write(body[: state.kill_after])
                    self.wfile.flush()
                    state.log.append(
                        (self.path, range_header, state.kill_after,
                         status)
                    )
                    self.close_connection = True
                    return
                self.wfile.write(body)
                self.wfile.flush()
                state.log.append(
                    (self.path, range_header, len(body), status)
                )

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )

    @property
    def port(self):
        return self._httpd.server_address[1]

    def url(self, name):
        return f"http://127.0.0.1:{self.port}/{name}"

    def report_json(self):
        import json as json_mod

        return json_mod.dumps({
            "version": "1",
            "install": [
                {
                    "download_info": {
                        "url": self.url(name),
                        "archive_info": {
                            "hashes": {"sha256": self.hashes[name]}
                        },
                    },
                }
                for name in self.files
            ],
        })

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        return False


def test_training_download_resumes_through_the_real_script(tmp_path):
    """R62: install-training.sh, run against a local wheel
    server, fails partway with a resume message when the
    download is cut — and the next run picks up where it
    stopped (a Range request for the remainder), finishing the
    download. The runs end at the import check (no real torch
    in the test env), which proves the download itself got
    past the failure."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    wheels = tmp_path / "wheels"
    env = {"STELLA_WHEEL_DIR": str(wheels)}
    with _ResumeWheelServer() as server:
        _make_report_writing_venv(tree, server.report_json())
        server.mode = "kill"
        res = run_script(
            tree, home, "install-training.sh", env_extra=env,
        )
        assert res.returncode == 1
        out = res.stdout + res.stderr
        assert "stopped partway" in out
        assert "pick up where it stopped" in out
        part = (
            wheels / "torch-2.15.0-cp312-cp312-manylinux.whl.part"
        )
        assert part.is_file()
        partial_size = part.stat().st_size
        assert 0 < partial_size < 4096

        server.mode = "normal"
        server.log.clear()
        res = run_script(
            tree, home, "install-training.sh", env_extra=env,
        )
        # Past the download: the failure now is the import check
        # (no real torch), not the download.
        assert res.returncode == 1
        assert "cannot be imported" in res.stdout + res.stderr
        assert (
            wheels / "torch-2.15.0-cp312-cp312-manylinux.whl"
        ).read_bytes() == b"T" * 4096
        assert (
            wheels / "peft-0.21.2-py3-none-any.whl"
        ).read_bytes() == b"P" * 2048
        ranges = [entry[1] for entry in server.log if entry[1]]
        assert ranges, "the second run made no Range request"
        resumed_at = int(
            ranges[0].split("=", 1)[1].split("-", 1)[0]
        )
        assert resumed_at == partial_size


def test_training_install_falls_back_when_no_report(tmp_path):
    """R62: when pip cannot list the wheels first (the resolve
    step fails), the training install falls back to the direct
    download instead of dying — the install is never worse
    than before."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    # pip fails everywhere: resolve fails, direct download fails.
    make_wrapper_venv(tree, pip_mode="fail")
    res = run_script(tree, home, "install-training.sh")
    assert res.returncode == 1
    out = res.stdout + res.stderr
    assert "could not be listed first" in out
    assert "training packages download failed" in out
    assert "run bash install-training.sh again" in out


def _make_no_index_failing_venv(tree, report_json, direct_ok=True):
    """A fake .venv/bin/python for the v0.30.0 fallback test:
    pip --dry-run writes the canned report; the --no-index
    install fails (as it did on the real PC when pip could not
    parse a %2B wheel name); the direct install succeeds — or
    fails, when direct_ok is False. Everything else runs the
    real test python."""
    bindir = tree / ".venv" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    direct_exit = "0" if direct_ok else "1"
    wrapper = bindir / "python"
    wrapper.write_text(
        "#!/bin/sh\n"
        "# Fake venv python for the v0.30.0 fallback test.\n"
        'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then\n'
        '  prev=""\n'
        '  report=""\n'
        "  no_index=0\n"
        '  for arg in "$@"; do\n'
        '    if [ "$prev" = "--report" ]; then report="$arg"; fi\n'
        '    if [ "$arg" = "--no-index" ]; then no_index=1; fi\n'
        '    prev="$arg"\n'
        "  done\n"
        '  if [ -n "$report" ]; then\n'
        "    cat > \"$report\" <<'R62_REPORT_EOF'\n"
        + report_json
        + "\nR62_REPORT_EOF\n"
        "    exit 0\n"
        "  fi\n"
        '  if [ "$no_index" = "1" ]; then\n'
        "    exit 1\n"
        "  fi\n"
        f"  exit {direct_exit}\n"
        "fi\n"
        f'exec "{REAL_PYTHON}" "$@"\n'
    )
    wrapper.chmod(0o755)


def test_training_install_falls_back_when_local_install_fails(
    tmp_path,
):
    """v0.30.0: when the --no-index install of the fetched wheels
    fails, install-training.sh falls through to the direct
    download instead of dying — re-running would repeat the
    identical failure, since the fetched wheels are already
    cached. The run ends at the import check (no real torch),
    which proves the fallback ran."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    wheels = tmp_path / "wheels"
    env = {"STELLA_WHEEL_DIR": str(wheels)}
    with _ResumeWheelServer() as server:
        _make_no_index_failing_venv(tree, server.report_json())
        res = run_script(
            tree, home, "install-training.sh", env_extra=env,
        )
        assert res.returncode == 1
        out = res.stdout + res.stderr
        assert "downloading them directly instead" in out
        assert "cannot be imported" in out
        assert "training packages download failed" not in out
        assert (
            wheels / "torch-2.15.0-cp312-cp312-manylinux.whl"
        ).read_bytes() == b"T" * 4096
        assert (
            wheels / "peft-0.21.2-py3-none-any.whl"
        ).read_bytes() == b"P" * 2048


def test_training_install_errors_when_both_install_paths_fail(
    tmp_path,
):
    """v0.30.0: the "download failed" error shows only when BOTH
    install paths fail — the local install and the direct
    download after it."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    wheels = tmp_path / "wheels"
    env = {"STELLA_WHEEL_DIR": str(wheels)}
    with _ResumeWheelServer() as server:
        _make_no_index_failing_venv(
            tree, server.report_json(), direct_ok=False
        )
        res = run_script(
            tree, home, "install-training.sh", env_extra=env,
        )
        assert res.returncode == 1
        out = res.stdout + res.stderr
        assert "downloading them directly instead" in out
        assert "training packages download failed" in out
        assert "run bash install-training.sh again" in out
        assert "cannot be imported" not in out


# -- R63: click-only uninstall --------------------------------------


def test_uninstall_desktop_file_is_executable_in_tree():
    """R63: the double-click uninstaller must be executable or
    Nemo will not offer to launch it."""
    path = ROOT / "Uninstall Stella.desktop"
    assert path.is_file()
    assert os.access(path, os.X_OK)


def test_uninstall_desktop_file_validates():
    """R63: desktop-file-validate is clean, when the tool is
    available in the sandbox."""
    validator = shutil.which("desktop-file-validate")
    if validator is None:
        pytest.skip("desktop-file-validate not installed")
    res = subprocess.run(
        [validator, str(ROOT / "Uninstall Stella.desktop")],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_uninstall_desktop_runs_uninstaller(tmp_path):
    """R63: the double-click uninstaller resolves its own folder
    (via %k, not the working directory) and runs uninstall.sh
    with bash. Its Exec line carries no nested escaped quotes
    (GLib rejects those) and it asks for a terminal so the data
    question can be answered. The data is kept: the prompt's
    default answer is No."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path, desktop=True)
    installed(tree, home)
    data = home / ".stella" / "profiles"
    data.mkdir(parents=True)
    (data / "keep.json").write_text("{}\n")
    desktop = tree / "Uninstall Stella.desktop"
    entry = parse_desktop(desktop)
    assert entry.get("Desktop Entry", "Name") == "Uninstall Stella"
    assert entry.get("Desktop Entry", "Terminal") == "true"
    assert entry.get("Desktop Entry", "Type") == "Application"
    exec_line = entry.get("Desktop Entry", "Exec")
    assert "uninstall_launcher.py" in exec_line
    assert "%k" in exec_line
    assert '\\"' not in exec_line  # no nested escaped quotes
    # The launcher it runs is the file that runs uninstall.sh.
    launcher_src = (tree / "uninstall_launcher.py").read_text()
    assert '"uninstall.sh"' in launcher_src
    assert '"bash"' in launcher_src
    # Run the Exec line the way the desktop environment would,
    # from a different working directory, with %k expanded to
    # the file. One newline answers the data question with the
    # default (No, keep the data); the launcher's wait for Enter
    # then sees EOF and does not hang.
    argv = [str(desktop) if a == "%k" else a for a in shlex.split(exec_line)]
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["STELLA_INSTALL_MIN_FREE_KB"] = "1024"
    res = subprocess.run(
        argv, cwd=tmp_path, env=env, capture_output=True, text=True,
        input="\n", timeout=300, check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Uninstall finished." in res.stdout
    assert "Your data is still in" in res.stdout
    assert (data / "keep.json").is_file()
    assert not (home / ".local" / "share" / "applications"
                / "stella.desktop").exists()
    assert not (home / "Desktop" / "Stella.desktop").exists()
    assert not (home / "Desktop" / "Install Stella Training.desktop").exists()
    assert not (home / ".local" / "bin" / "stella").exists()
    assert not (tree / ".venv").exists()
    assert not (tree / ".stella-install-receipt").exists()


# -- v0.29.0 (R114–R121, R128, R120) ---------------------------------


def test_readme_documents_pre_install_generic_icon():
    """R114: the pre-install icon cannot be given within the
    desktop-entry spec (no relative Icon=, unknown unzip
    location), so the limitation is documented in the README's
    install section and the generic icon is accepted."""
    readme = (ROOT / "README.md").read_text()
    flat = " ".join(readme.split())
    assert "shows a plain generic icon until Stella is installed" in flat
    assert "no spec-compliant way" in flat
    assert "The generic icon is accepted" in flat


def test_failed_reinstall_keeps_the_old_receipt(tmp_path):
    """R117: a re-install that fails early (here, the disk
    preflight) keeps the previous good receipt — the old
    up-front `rm -f` deleted it before the preflight, so the
    doctor reported "no install receipt" for a complete install.
    T63 still holds: a failed FRESH install leaves no receipt."""
    # Fresh half: nothing installed, preflight fails, no receipt.
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    huge = {"STELLA_INSTALL_MIN_FREE_KB": "999999999"}
    res = run_install(tree, home, env_extra=huge)
    assert res.returncode == 1
    assert not (tree / ".stella-install-receipt").exists()
    # Re-install half: a good install, then a failing re-run.
    tree2 = copy_tree(tmp_path, "stella2")
    installed(tree2, home)
    receipt = tree2 / ".stella-install-receipt"
    assert receipt.is_file()
    before = receipt.read_text()
    res = run_install(tree2, home, env_extra=huge)
    assert res.returncode == 1
    assert "not enough free disk space" in res.stderr
    assert receipt.is_file()
    assert receipt.read_text() == before


def test_clone_without_pngs_renders_icons_display_less(tmp_path):
    """R118: the icon render runs offscreen, exactly as the
    QApplication check does — a clone (SVG only, no PNGs) renders
    its icons with no display and no QT_QPA_PLATFORM inherited
    from the test process."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    for png in (tree / "assets").glob("*.png"):
        png.unlink()
    assert (tree / "assets" / "stella.svg").is_file()
    make_wrapper_venv(tree)
    res = run_install(
        tree, home,
        env_extra={"QT_QPA_PLATFORM": None, "DISPLAY": None},
    )
    assert res.returncode == 0, res.stdout + res.stderr
    for size in ICON_SIZES:
        assert (tree / "assets" / f"stella-{size}.png").is_file()
    assert (tree / "assets" / "stella.png").is_file()


def test_install_uses_the_localized_desktop_dir(tmp_path):
    """R119: with XDG_CONFIG_HOME naming a localized desktop
    ($HOME/Bureau), the install lands both desktop icons there —
    and the receipt records the Bureau copy, not ~/Desktop."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    (home / "Bureau").mkdir()
    env = make_localized_desktop_env(tmp_path, home)
    res = installed(tree, home, env_extra=env)
    assert (home / "Bureau" / "Stella.desktop").is_file()
    assert (home / "Bureau" / "Install Stella Training.desktop").is_file()
    assert not (home / "Desktop").exists()
    assert "double-click Stella on the desktop" in res.stdout
    receipt = (tree / ".stella-install-receipt").read_text()
    assert f"desktop_copy: {home / 'Bureau' / 'Stella.desktop'}" in receipt


def test_uninstall_removes_the_localized_desktop_icon(tmp_path):
    """R119: uninstall removes the desktop icons from the resolved
    dir — and from ~/Desktop too, when they differ, so an icon
    installed by an older (~/Desktop-only) version is not left
    behind when the desktop has since been localized."""
    # Localized install, localized uninstall: Bureau icons go.
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    (home / "Bureau").mkdir()
    env = make_localized_desktop_env(tmp_path, home)
    installed(tree, home, env_extra=env)
    assert (home / "Bureau" / "Stella.desktop").is_file()
    res = run_script(tree, home, "uninstall.sh", "--yes", env_extra=env)
    assert res.returncode == 0, res.stdout + res.stderr
    assert not (home / "Bureau" / "Stella.desktop").exists()
    assert not (home / "Bureau" / "Install Stella Training.desktop").exists()
    # Plain install, localized uninstall: the ~/Desktop icons go
    # too (both dirs are tried).
    tree2 = copy_tree(tmp_path, "stella2")
    home2 = make_home(tmp_path, "home2", desktop=True)
    installed(tree2, home2)
    assert (home2 / "Desktop" / "Stella.desktop").is_file()
    env2 = make_localized_desktop_env(tmp_path, home2)
    res = run_script(tree2, home2, "uninstall.sh", "--yes", env_extra=env2)
    assert res.returncode == 0, res.stdout + res.stderr
    assert not (home2 / "Desktop" / "Stella.desktop").exists()
    assert not (home2 / "Desktop" / "Install Stella Training.desktop").exists()


def test_uninstall_falls_back_to_manual_icon_removal(tmp_path):
    """R115: when the venv python is broken, the python icon
    remover fails — and the manual rm loop runs as a real
    fallback, so the hicolor PNGs are still removed. The old
    `|| true` swallowed the failure and left them behind."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    hicolor = home / ".local" / "share" / "icons" / "hicolor"
    for size in ICON_SIZES:
        assert (hicolor / f"{size}x{size}" / "apps"
                / "stella.png").is_file()
    # Break the venv python: every call exits 1, as a damaged
    # venv's failed stella.install import would.
    venv_python = tree / ".venv" / "bin" / "python"
    venv_python.write_text("#!/bin/sh\nexit 1\n")
    venv_python.chmod(0o755)
    res = run_script(tree, home, "uninstall.sh", "--yes")
    assert res.returncode == 0, res.stdout + res.stderr
    for size in ICON_SIZES:
        assert not (hicolor / f"{size}x{size}" / "apps"
                    / "stella.png").exists()


def _plant_pip_cache(home: Path) -> Path:
    """A small fake pip cache (a few KB of wheels)."""
    cache = home / ".cache" / "pip"
    cache.mkdir(parents=True)
    (cache / "wheel.whl").write_bytes(b"x" * 4096)
    return cache


def test_uninstall_offers_to_clear_the_pip_cache(tmp_path):
    """R116: after the venv is gone, uninstall offers to clear the
    pip cache, naming the size — answering yes removes it, the
    default (empty answer) keeps it. The threshold is overridden
    for the test (a real cache is ~2 GB; the planted one is KB)."""
    env = {"STELLA_UNINSTALL_PIP_CACHE_MIN_KB": "1"}
    # Yes: the first line answers the data question (No, keep
    # the data), the second answers the pip-cache offer.
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    cache = _plant_pip_cache(home)
    res = run_script(
        tree, home, "uninstall.sh", env_extra=env, input_text="\ny\n",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "in the pip cache. Remove it?" in res.stdout
    assert "Removed the pip cache." in res.stdout
    assert not cache.exists()
    # Default No: one empty line answers the data question, and
    # the pip-cache read hits EOF — the cache stays.
    tree2 = copy_tree(tmp_path, "stella2")
    home2 = make_home(tmp_path, "home2")
    installed(tree2, home2)
    cache2 = _plant_pip_cache(home2)
    res = run_script(
        tree2, home2, "uninstall.sh", env_extra=env, input_text="\n",
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "in the pip cache. Remove it?" in res.stdout
    assert cache2.is_dir()


def test_uninstall_keeps_pip_cache_when_yes_or_tiny(tmp_path):
    """R116: --yes asks nothing, so the pip cache is kept without
    an offer; and a cache below the (default 100 MB) threshold is
    not worth asking about, so no offer appears either."""
    # --yes: no offer, cache kept.
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    cache = _plant_pip_cache(home)
    res = run_script(
        tree, home, "uninstall.sh", "--yes",
        env_extra={"STELLA_UNINSTALL_PIP_CACHE_MIN_KB": "1"},
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "pip cache" not in res.stdout
    assert cache.is_dir()
    # Tiny cache, default threshold: no offer, cache kept.
    tree2 = copy_tree(tmp_path, "stella2")
    home2 = make_home(tmp_path, "home2")
    installed(tree2, home2)
    cache2 = _plant_pip_cache(home2)
    res = run_script(tree2, home2, "uninstall.sh", input_text="\n")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "pip cache" not in res.stdout
    assert cache2.is_dir()


def test_ci_runs_lint_and_scheduled_runs():
    """R120: CI validates the desktop files, shellchecks the
    scripts, and runs on a weekly schedule — not only on push/PR."""
    ci_text = (
        ROOT / ".github" / "workflows" / "ci.yml"
    ).read_text()
    assert "schedule:" in ci_text
    assert "cron:" in ci_text
    assert "desktop-file-validate" in ci_text
    assert "shellcheck" in ci_text
    assert "desktop-file-utils" in ci_text


def test_desktop_files_validate_and_scripts_shellcheck_clean():
    """R120: the checks CI runs, when the tools are available in
    the sandbox — every .desktop file validates, every script
    shellchecks clean (the lint job runs them for real in CI)."""
    validator = shutil.which("desktop-file-validate")
    shellcheck = shutil.which("shellcheck")
    if validator is None and shellcheck is None:
        pytest.skip("neither desktop-file-validate nor shellcheck installed")
    if validator is not None:
        res = subprocess.run(
            [validator, *[str(p) for p in ROOT.glob("*.desktop")]],
            capture_output=True, text=True,
        )
        assert res.returncode == 0, res.stdout + res.stderr
    if shellcheck is not None:
        scripts = [str(p) for p in ROOT.glob("*.sh")] + [str(ROOT / "stella-cli")]
        res = subprocess.run(
            [shellcheck, *scripts], capture_output=True, text=True,
        )
        assert res.returncode == 0, res.stdout + res.stderr


# -- R121: click-only doctor ----------------------------------------


def test_repair_desktop_file_is_executable_in_tree():
    """R121: the double-click repair entry must be executable or
    Nemo will not offer to launch it."""
    path = ROOT / "Repair Stella.desktop"
    assert path.is_file()
    assert os.access(path, os.X_OK)


def test_repair_desktop_file_validates():
    """R121: desktop-file-validate is clean, when the tool is
    available in the sandbox."""
    validator = shutil.which("desktop-file-validate")
    if validator is None:
        pytest.skip("desktop-file-validate not installed")
    res = subprocess.run(
        [validator, str(ROOT / "Repair Stella.desktop")],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def _run_desktop_exec(desktop: Path, home: Path, cwd: Path,
                      input_text: str = "\n") -> subprocess.CompletedProcess:
    """Run a .desktop file's Exec line the way the desktop
    environment would: %k expanded to the file, from a different
    working directory, with a scratch HOME."""
    exec_line = parse_desktop(desktop).get("Desktop Entry", "Exec")
    argv = [str(desktop) if a == "%k" else a for a in shlex.split(exec_line)]
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["STELLA_INSTALL_MIN_FREE_KB"] = "1024"
    return subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, text=True,
        input=input_text, timeout=300, check=False,
    )


def test_repair_desktop_repairs_after_move(tmp_path):
    """R121: the double-click repair entry resolves its own folder
    (via %k, not the working directory) and runs the doctor: a
    moved folder's launcher is re-pointed, and the result stays
    on screen until Enter. Its Exec line carries no nested
    escaped quotes (GLib rejects those) and it asks for a
    terminal so the report is visible."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    moved = tmp_path / "moved to"
    shutil.move(str(tree), str(moved))
    launcher = home / ".local" / "share" / "applications" / "stella.desktop"
    assert str(tree / "run.sh") in launcher.read_text()
    desktop = moved / "Repair Stella.desktop"
    entry = parse_desktop(desktop)
    assert entry.get("Desktop Entry", "Name") == "Repair Stella"
    assert entry.get("Desktop Entry", "Terminal") == "true"
    assert entry.get("Desktop Entry", "Type") == "Application"
    exec_line = entry.get("Desktop Entry", "Exec")
    assert "repair_launcher.py" in exec_line
    assert "%k" in exec_line
    assert '\\"' not in exec_line  # no nested escaped quotes
    # The launcher it runs is the file that runs the doctor.
    launcher_src = (moved / "repair_launcher.py").read_text()
    assert "stella.doctor" in launcher_src
    res = _run_desktop_exec(desktop, home, tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "FIXED" in res.stdout
    assert "Repair finished." in res.stdout
    assert str(moved / "run.sh") in launcher.read_text()
    receipt = (moved / ".stella-install-receipt").read_text()
    assert f"install_dir: {moved}" in receipt


def test_repair_desktop_runs_without_a_venv(tmp_path):
    """R121: the repair launcher never assumes a working venv — it
    runs the doctor under the system python3, so with the venv
    deleted entirely the doctor still runs and names the venv
    problem instead of dying before it starts."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    installed(tree, home)
    shutil.rmtree(tree / ".venv")
    desktop = tree / "Repair Stella.desktop"
    res = _run_desktop_exec(desktop, home, tmp_path)
    assert res.returncode == 1  # broken checks remain: honest failure
    assert "Python environment" in res.stdout
    assert "bash install.sh" in res.stdout
    assert "The check found problems" in res.stdout


# -- R128: pytest config --------------------------------------------


def test_pytest_ini_has_timeout_and_gui_marker():
    """R128: the suite runs under a per-test timeout (a hung test
    times out instead of holding CI) and the GUI suite is marked
    as a group, so it can be run or skipped together."""
    import configparser

    ini = configparser.ConfigParser()
    ini.read(ROOT / "pytest.ini")
    assert ini.has_option("pytest", "timeout")
    assert int(ini.get("pytest", "timeout")) > 0
    markers = ini.get("pytest", "markers")
    assert "gui:" in markers
    gui_src = (ROOT / "tests" / "test_gui.py").read_text()
    assert "pytestmark = pytest.mark.gui" in gui_src


def test_pytest_timeout_is_wired_into_both_install_paths():
    """R128: pytest-timeout is installed wherever pytest is —
    run_tests.sh and both CI jobs — or the timeout in pytest.ini
    would silently do nothing."""
    assert "pytest-timeout" in (ROOT / "run_tests.sh").read_text()
    ci_text = (
        ROOT / ".github" / "workflows" / "ci.yml"
    ).read_text()
    assert ci_text.count("pytest-timeout") == 2
