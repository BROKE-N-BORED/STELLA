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
import time
from pathlib import Path

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
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", script, *args],
        cwd=tree, env=env, capture_output=True, text=True,
        input=input_text, timeout=timeout, check=False,
    )


def run_install(tree: Path, home: Path, **kw) -> subprocess.CompletedProcess:
    return run_script(tree, home, "install.sh", **kw)


def installed(
    tree: Path, home: Path, **venv_kw
) -> subprocess.CompletedProcess:
    """A tree + HOME with a completed base install (or a failed
    assertion with the install output attached). Extra keywords go
    to make_wrapper_venv."""
    make_wrapper_venv(tree, **venv_kw)
    res = run_install(tree, home)
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
    assert res.stdout.strip() == "stella 0.16.0"

    receipt = tree / ".stella-install-receipt"
    assert receipt.is_file()
    receipt_text = receipt.read_text()
    assert "stella_version: 0.16.0" in receipt_text
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
    assert "Stella 0.16.0 is installed." in res.stdout
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
    install fails with the real error named."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    make_wrapper_venv(tree, qt_probe="fail")
    res = run_install(tree, home)
    assert res.returncode == 1
    out = res.stdout + res.stderr
    assert "cannot start a window" in out
    assert "libEGL.so.1" in out
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
    res = subprocess.run(
        argv, cwd=tmp_path, env=env, capture_output=True, text=True,
        input="\n", timeout=300, check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Stella 0.16.0 is installed." in res.stdout
    assert (home / ".local" / "share" / "applications"
            / "stella.desktop").is_file()
    assert (home / ".local" / "bin" / "stella").is_symlink()


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
    assert res.stdout.strip() == "stella 0.16.0"
    assert resolve_desktop_icon(launcher, home) is not None
    receipt = (moved / ".stella-install-receipt").read_text()
    assert f"install_dir: {moved}" in receipt


def test_doctor_fix_writes_no_receipt_without_an_install(tmp_path):
    """T66/T139: a repair on a folder that was never installed fixes
    the launch artifacts but writes NO receipt — there is no complete
    install to record, and a receipt claiming one would lie about a
    broken install."""
    tree = copy_tree(tmp_path)
    home = make_home(tmp_path)
    env = dict(os.environ)
    env["HOME"] = str(home)
    res = subprocess.run(
        ["bash", "stella-cli", "doctor"], cwd=tree, env=env,
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert res.returncode == 1  # venv still missing: honest failure
    assert (home / ".local" / "share" / "applications"
            / "stella.desktop").is_file()  # a fix did happen
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
