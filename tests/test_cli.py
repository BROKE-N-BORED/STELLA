"""CLI tests — run the real `python -m stella.cli` in a subprocess."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_cli(home, *args):
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


def test_cli_profiles_empty(home):
    res = run_cli(home, "profiles")
    assert res.returncode == 0
    assert "No profiles yet" in res.stdout


def test_cli_create_profile_and_list(home):
    res = run_cli(home, "create-profile", "lfm3-tool",
                  "--tag", "lfm3:1.7b", "--role", "fast")
    assert res.returncode == 0
    res = run_cli(home, "profiles")
    assert "lfm3-tool" in res.stdout
    assert "fast" in res.stdout
    assert "lfm3:1.7b" in res.stdout


def test_cli_create_profile_bad_name(home):
    res = run_cli(home, "create-profile", "../evil")
    assert res.returncode == 1
    assert "not valid" in res.stderr


def test_cli_projects_flow(home):
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    res = run_cli(home, "projects", "p1")
    assert "No projects" in res.stdout
    res = run_cli(home, "create-project", "p1", "proj",
                  "--dataset", "data.jsonl", "--metamorph", "both")
    assert res.returncode == 0
    res = run_cli(home, "projects", "p1")
    assert "proj" in res.stdout
    assert "both" in res.stdout


def test_cli_export_and_import(home, tmp_path):
    run_cli(home, "create-profile", "p1", "--tag", "x:1b", "--role", "fast")
    run_cli(home, "create-project", "p1", "proj")
    dest = tmp_path / "exports"
    res = run_cli(home, "export", "p1", "proj", str(dest))
    assert res.returncode == 0
    pkg = dest / "proj-stella-export"
    assert (pkg / "manifest.json").is_file()
    assert json.loads((pkg / "manifest.json").read_text())["kind"] == "stella-export"

    home2 = tmp_path / "home2"
    res = run_cli(home2, "import", str(pkg))
    assert res.returncode == 0
    res = run_cli(home2, "profiles")
    assert "p1" in res.stdout
    res = run_cli(home2, "projects", "p1")
    assert "proj" in res.stdout


def test_cli_export_missing_project(home, tmp_path):
    run_cli(home, "create-profile", "p1")
    res = run_cli(home, "export", "p1", "ghost", str(tmp_path))
    assert res.returncode == 1
    assert "no project" in res.stderr


def test_cli_version(home):
    res = run_cli(home, "--version")
    assert res.returncode == 0
    assert "0.1" in res.stdout


def test_cli_through_symlink(home, tmp_path):
    # The installed `stella` command is a symlink into the app folder;
    # the wrapper must resolve it and still find the package.
    link = tmp_path / "stella"
    link.symlink_to(ROOT / "stella-cli")
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    res = subprocess.run(
        ["bash", str(link), "profiles"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0
    assert "No profiles yet" in res.stdout
