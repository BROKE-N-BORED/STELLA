"""CLI tests — run the real `python -m stella.cli` in a subprocess."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_cli(home, *args):
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


# -- T51: help text for every flag, examples in every command ----

ALL_COMMANDS = [
    "profiles", "projects", "export", "export-profile", "import",
    "verify", "create-profile", "create-project", "train",
    "export-gguf", "probe", "sleep", "sleep-status", "sleep-delete",
    "sleep-prune", "chat",
    "requant", "pc-info", "distill", "doctor",
    "rename-profile", "delete-profile", "update-profile",
    "show-profile", "rename-project", "delete-project",
    "update-project", "show-project",
    "delete-checkpoint", "prune-checkpoints",
    "export-recipe", "export-adapter", "import-adapter",
    "pull-weights", "bridge",
    "clone-profile", "clone-project",
    "save-key", "list-keys", "remove-key",
    "mark-ready", "notes", "probe-results", "howto", "debug-report",
]


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_every_command_help_shows_an_example(home, command):
    # T51: every command's --help shows a worked example.
    res = run_cli(home, command, "--help")
    assert res.returncode == 0
    assert "examples:" in res.stdout
    assert f"stella {command}" in res.stdout


def test_create_commands_help_names_every_flag(home):
    # T51: the two create commands used to be nearly blank.
    res = run_cli(home, "create-profile", "--help")
    assert res.returncode == 0
    for flag, meaning in (
        ("--tag", "Ollama tag"),
        ("--role", "what this profile is for"),
        ("--display", "display name"),
        ("--base", "Hugging Face repo"),
    ):
        assert flag in res.stdout
        assert meaning in res.stdout
    assert (
        "stella create-profile lfm3 --tag lfm3:1.7b --role fast "
        "--base LiquidAI/LFM3-1.7B"
    ) in res.stdout
    res = run_cli(home, "create-project", "--help")
    assert res.returncode == 0
    assert "--display" in res.stdout
    assert "--dataset" in res.stdout
    assert "dataset file" in res.stdout


def test_every_flag_and_positional_has_help():
    # T51: structural pin — no flag or positional without help.
    from stella.cli import build_parser

    parser = build_parser()
    subs = parser._subparsers._group_actions[0].choices
    assert sorted(subs) == sorted(ALL_COMMANDS)
    for name, sub in subs.items():
        for action in sub._actions:
            assert action.help, f"{name}: {action.dest} has no help"


def test_empty_home_hint_names_the_working_command(home):
    # T51: before install, `stella` does not exist — the hint uses
    # the form that works.
    res = run_cli(home, "profiles")
    assert res.returncode == 0
    assert "bash stella-cli create-profile" in res.stdout


def test_docstring_lists_all_commands():
    # T51: the module docstring lists every command that exists.
    import stella.cli as cli_mod

    for command in ALL_COMMANDS:
        assert command in cli_mod.__doc__, command


def test_readme_lists_all_commands():
    # T51: the README's Command line section lists every command.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Command line", 1)[1].split("## ", 1)[0]
    for command in ALL_COMMANDS:
        assert f"stella {command}" in section, command


def test_readme_probe_counts_and_wording():
    # R69: the README's prompt counts and probe wording match the
    # code — 18 by default, 24 for a governing seat, and the LFM3
    # proof probe is a gate (its role is fast), never called
    # "informational".
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "18 plainly benign prompts" in readme
    assert "24 for a governing seat" in readme
    assert "12 plainly benign prompts" not in readme
    assert "informational for LFM3" not in readme
    assert "For LFM3 this is\n  informational" not in readme


def test_readme_command_list_names_the_flags():
    # R69: the Command line section lists the flags a user copies
    # from — probe --informational/--gate, distill --timeout,
    # train --dry-run/--from-checkpoint, and the global
    # --json/--quiet/--verbose.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Command line", 1)[1].split("## ", 1)[0]
    assert "stella probe <profile> <project> [--informational] [--gate]" in section
    assert "--timeout 300" in section
    assert "--dry-run" in section
    assert "--from-checkpoint N" in section
    assert "--json" in section
    assert "--quiet" in section
    assert "--verbose" in section


def test_stella_cli_wrapper_comment_names_the_wrapper():
    # T51: the wrapper's header comment says bash stella-cli, not
    # bash stella — stella is only the name after install.
    text = (ROOT / "stella-cli").read_text(encoding="utf-8")
    assert "bash stella-cli <command>" in text
    assert "bash stella " not in text


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
                  "--dataset", "data.jsonl")
    assert res.returncode == 0
    res = run_cli(home, "projects", "p1")
    assert "proj" in res.stdout
    # The listing shows name and status only: no dead mode column.
    assert "metamorph" not in res.stdout


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
    from stella.model import STELLA_VERSION

    res = run_cli(home, "--version")
    assert res.returncode == 0
    assert STELLA_VERSION in res.stdout


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


def test_cli_create_profile_with_base(home):
    res = run_cli(home, "create-profile", "lfm3",
                  "--tag", "lfm3:1.7b", "--base", "LiquidAI/LFM3-1.7B")
    assert res.returncode == 0
    manifest = json.loads(
        (Path(home) / "profiles" / "lfm3" / "profile.json").read_text()
    )
    assert manifest["base_ref"] == "LiquidAI/LFM3-1.7B"


def test_cli_train_no_base_ref(home):
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    res = run_cli(home, "train", "p1", "proj")
    assert res.returncode == 1
    # T48: the cheap checks run before the deps gate, so the
    # missing base_ref is reported — never the deps message.
    assert "base_ref" in res.stderr
    assert "install-training.sh" not in res.stderr


def test_cli_export_gguf_no_adapter(home):
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    res = run_cli(home, "export-gguf", "p1", "proj", str(home / "out"))
    assert res.returncode == 1
    assert "no trained adapter" in res.stderr


def test_cli_probe_no_adapter(home):
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    res = run_cli(home, "probe", "p1", "proj")
    assert res.returncode == 1
    assert "no trained adapter" in res.stderr


def test_cli_train_help(home):
    res = run_cli(home, "train", "--help")
    assert res.returncode == 0
    assert "--resume" in res.stdout
    assert "--steps" in res.stdout
    assert "--target-modules" in res.stdout


def test_cli_train_missing_deps_in_process(home, monkeypatch, capsys):
    # In-process so the deps gate can be faked without uninstalling.
    import os

    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch"]
    )
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    # T48: the project must be otherwise ready (dataset set) for
    # the run to reach the deps gate at all.
    run_cli(
        home, "create-project", "p1", "proj",
        "--dataset", "sample-tool-calls.jsonl",
    )
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 1
    assert "Training is not set up on this PC yet" in (
        capsys.readouterr().err
    )


def test_cli_sleep_help(home):
    res = run_cli(home, "sleep", "--help")
    assert res.returncode == 0
    assert "--dream" in res.stdout
    assert "--rows" in res.stdout
    assert "--threshold" in res.stdout


def test_cli_sleep_status_no_cycles(home):
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    res = run_cli(home, "sleep-status", "p1", "proj")
    assert res.returncode == 0
    assert "No sleep cycles yet" in res.stdout


def test_cli_sleep_status_names_unhealed_cycle(home):
    # R8: a cycle that could not be recovered is named on the
    # status line, with its reason and what happens next.
    import json

    from stella.model import Store

    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    store = Store(home)
    cdir = store.project_dir("p1", "proj") / "sleep" / "cycle-1"
    cdir.mkdir(parents=True)
    (cdir / "report.json").write_text(json.dumps({
        "cycle": 1, "status": "OK", "timestamp": "2026-11-13T00:00:00",
        "real_rows": 6, "dreamed_rows": 0, "steps": 3,
        "old_loss_before": None, "old_loss_after": None, "new_loss": 1.5,
    }))
    # No cycle_input.json: the cycle cannot be healed.
    res = run_cli(home, "sleep-status", "p1", "proj")
    assert res.returncode == 0
    assert "cycle 1 could not be recovered" in res.stdout
    assert "input file" in res.stdout
    assert "will sleep again" in res.stdout


def _seed_cli_sleep_cycle(home, number, payload_bytes=1000):
    """A finished cycle on disk for the CLI tests (same shape as
    the engine tests' seed). Returns the cycle dir."""
    import json

    from stella.model import Store
    from stella.sleep import load_sleep_manifest, save_sleep_manifest

    store = Store(home)
    cdir = store.project_dir("p1", "proj") / "sleep" / f"cycle-{number}"
    (cdir / "adapter").mkdir(parents=True)
    (cdir / "adapter" / "adapter_config.json").write_text("{}\n")
    (cdir / "payload.bin").write_bytes(b"x" * payload_bytes)
    (cdir / "report.json").write_text(json.dumps({
        "cycle": number, "status": "OK",
        "timestamp": "2026-11-13T00:00:00",
        "real_rows": 6, "dreamed_rows": 0, "steps": 3,
        "old_loss_before": 2.0, "old_loss_after": 1.9, "new_loss": 1.5,
    }))
    (cdir / "cycle_input.json").write_text(json.dumps({
        "real_hashes": [f"hash-{number}-a"],
        "dreamed_hashes": [],
    }))
    manifest = load_sleep_manifest(store, "p1", "proj")
    manifest["cycles"] = [
        c for c in manifest["cycles"] if c.get("cycle") != number
    ]
    manifest["cycles"].append({
        "cycle": number, "status": "OK",
        "timestamp": "2026-11-13T00:00:00",
        "real_rows": 6, "dreamed_rows": 0, "steps": 3,
        "old_loss_before": 2.0, "old_loss_after": 1.9, "new_loss": 1.5,
    })
    save_sleep_manifest(store, "p1", "proj", manifest)
    return cdir


def test_cli_sleep_status_shows_size(home):
    # R66: each cycle line carries its size, and the total
    # follows the list.
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    _seed_cli_sleep_cycle(home, 1, payload_bytes=2 * 1024 * 1024)
    res = run_cli(home, "sleep-status", "p1", "proj")
    assert res.returncode == 0
    assert "cycle 1" in res.stdout
    assert "2 MB" in res.stdout  # the 2 MB payload, plus small files
    assert "Sleep cycles use" in res.stdout
    assert "1 cycle" in res.stdout


def test_cli_sleep_delete_removes_cycle(home):
    # R66: sleep-delete removes the cycle dir and its manifest
    # entry, and names what it freed.
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    cdir = _seed_cli_sleep_cycle(home, 1, payload_bytes=2048)
    _seed_cli_sleep_cycle(home, 2, payload_bytes=2048)
    res = run_cli(home, "sleep-delete", "p1", "proj", "1", "--yes")
    assert res.returncode == 0
    assert "Deleted sleep cycle 1" in res.stdout
    assert "freed" in res.stdout
    assert not cdir.exists()
    res = run_cli(home, "sleep-status", "p1", "proj")
    assert "cycle 1:" not in res.stdout
    assert "cycle 2:" in res.stdout


def test_cli_sleep_delete_missing_cycle_errors(home):
    # R66: deleting a cycle that does not exist is a clean
    # error, not a traceback.
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    res = run_cli(home, "sleep-delete", "p1", "proj", "3")
    assert res.returncode == 1
    assert "no sleep cycle 3" in res.stderr


def test_cli_sleep_prune_keeps_newest(home):
    # R66: sleep-prune keeps the newest N and deletes the rest.
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    cdir1 = _seed_cli_sleep_cycle(home, 1, payload_bytes=1000)
    _seed_cli_sleep_cycle(home, 2, payload_bytes=1000)
    _seed_cli_sleep_cycle(home, 3, payload_bytes=1000)
    res = run_cli(home, "sleep-prune", "p1", "proj", "--keep", "1", "--yes")
    assert res.returncode == 0
    assert "Pruned 2 sleep cycles" in res.stdout
    assert "freed" in res.stdout
    assert not cdir1.exists()
    res = run_cli(home, "sleep-status", "p1", "proj")
    assert "cycle 3:" in res.stdout
    assert "cycle 1:" not in res.stdout
    assert "cycle 2:" not in res.stdout


def test_cli_sleep_no_base_ref(home):
    # Cheap checks first: no base ref is reported even before the
    # dependency gate, in both envs (base and training). The profile
    # gets no tag either — create-profile defaults base_ref to the
    # tag when one is given.
    run_cli(home, "create-profile", "p1")
    run_cli(home, "create-project", "p1", "proj")
    res = run_cli(home, "sleep", "p1", "proj")
    assert res.returncode == 1
    assert "base_ref" in res.stderr


def test_cli_sleep_no_dataset_names_rows_flag(home):
    """R15: sleep with no dataset tells a CLI user what to type
    (--rows with a file), never a GUI panel."""
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    res = run_cli(home, "sleep", "p1", "proj")
    assert res.returncode == 1
    assert "--rows my-data.jsonl" in res.stderr
    assert "Train panel" not in res.stderr


def test_cli_sleep_missing_deps_in_process(home, monkeypatch, capsys):
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch"]
    )
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj",
            "--dataset", "sample-tool-calls.jsonl")
    code = cli_mod.main(["sleep", "p1", "proj"])
    assert code == 1
    assert "Training is not set up on this PC yet" in (
        capsys.readouterr().err
    )


def test_cli_chat_shows_narration_and_progress(
    home, monkeypatch, capsys
):
    """R14: CLI chat prints the agent's narration and progress as
    the run goes — not silence until the final reply."""
    import builtins

    import stella.chat_agent as chat_agent_mod
    import stella.cli as cli_mod

    monkeypatch.setenv("STELLA_HOME", str(home))

    class FakeAgent:
        def __init__(self, store, model, **kwargs):
            self._on_narration = kwargs.get("on_narration")
            self._on_progress = kwargs.get("on_progress")

        def reply(self, text):
            assert self._on_narration is not None
            assert self._on_progress is not None
            self._on_narration("Setting up the project...")
            self._on_progress("Step 25/100, loss 2.3456.")
            return "Done. The project is ready."

    monkeypatch.setattr(chat_agent_mod, "ChatAgent", FakeAgent)
    answers = iter(["train lfm3 to write short replies", "/quit"])
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(answers))
    code = cli_mod.main(["chat", "--model", "fake:1b"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Setting up the project..." in out
    assert "Step 25/100, loss 2.3456." in out
    # The narration and progress come BEFORE the final reply,
    # as the run goes — not after it.
    assert out.index("Setting up the project...") < out.index(
        "Stella: Done. The project is ready."
    )
    assert out.index("Step 25/100, loss 2.3456.") < out.index(
        "Stella: Done. The project is ready."
    )


# -- pc-info --------------------------------------------------------


def test_cli_pc_info(home):
    res = run_cli(home, "pc-info")
    assert res.returncode == 0
    assert "CPUs" in res.stdout
    assert "RAM" in res.stdout
    assert "Free disk" in res.stdout
    assert "Training settings for this PC" in res.stdout
    assert "Traceback" not in res.stderr


# -- T5: main() catches everything; defensive lists ------------------


def test_cli_main_catches_unexpected_errors(home, monkeypatch, capsys):
    import stella.cli as cli_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        cli_mod, "cmd_profiles",
        lambda args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    code = cli_mod.main(["profiles"])
    assert code == 1
    err = capsys.readouterr().err
    assert "stella: boom" in err
    assert "Traceback" not in err


def test_cli_profiles_nameless_manifest(home):
    # A valid-JSON profile manifest missing "name": the list shows
    # the rest, with a warning line for the nameless one.
    run_cli(home, "create-profile", "good", "--tag", "x:1b")
    pdir = Path(home) / "profiles" / "nameless"
    (pdir / "projects").mkdir(parents=True)
    (pdir / "profile.json").write_text(
        json.dumps({"kind": "profile", "role": "quiet"})
    )
    res = run_cli(home, "profiles")
    assert res.returncode == 0
    assert "good" in res.stdout
    assert "(unnamed profile)" in res.stdout
    assert "no name" in res.stderr


def test_cli_export_to_file_destination(home, tmp_path):
    # A destination that is a file: one clean line, exit 1, no
    # traceback (the main() catch-all is the last-resort net).
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    dest_file = tmp_path / "not-a-dir"
    dest_file.write_text("x")
    res = run_cli(home, "export", "p1", "proj", str(dest_file))
    assert res.returncode == 1
    assert "stella:" in res.stderr
    assert "Traceback" not in res.stderr


def test_cli_import_bad_manifest_clean_exit(home, tmp_path):
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "proj")
    dest = tmp_path / "exports"
    run_cli(home, "export", "p1", "proj", str(dest))
    pkg = dest / "proj-stella-export"
    manifest_path = pkg / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["project"]["settings"] = "rank 8"
    manifest_path.write_text(json.dumps(manifest))
    res = run_cli(tmp_path / "home2", "import", str(pkg))
    assert res.returncode == 1
    assert "stella:" in res.stderr
    assert "Traceback" not in res.stderr


# -- T39: CLI list warns on a string metamorph -----------------------


def test_cli_projects_warns_on_string_metamorph(home):
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "good")
    run_cli(home, "create-project", "p1", "broken")
    manifest = (
        Path(home) / "profiles" / "p1" / "projects" / "broken" / "project.json"
    )
    data = json.loads(manifest.read_text())
    data["metamorph"] = "both"
    manifest.write_text(json.dumps(data))
    res = run_cli(home, "projects", "p1")
    assert res.returncode == 0
    assert "good" in res.stdout
    assert "broken" in res.stdout
    assert "warning" in res.stdout
    assert "metamorph" in res.stdout
    assert "Traceback" not in res.stderr


# -- T4: Ctrl+C pauses, not crashes ----------------------------------


def test_cli_train_ctrl_c_pauses(tmp_path):
    import signal
    import time

    home = tmp_path / "home"
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "_ctrlc_driver.py"), str(home)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    try:
        # The fake run lasts ~10 s; interrupt mid-run.
        time.sleep(2)
        assert proc.poll() is None, "the fake run ended before Ctrl+C"
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=10)
    assert proc.returncode == 0
    assert "Paused at step" in out
    assert "Traceback" not in err
    # A checkpoint was saved at the pause step, so --resume has
    # something to continue from.
    ckpt_dir = home / "profiles" / "p1" / "projects" / "proj" / "checkpoints"
    saved = [d for d in ckpt_dir.iterdir() if d.is_dir()]
    assert saved
    assert (saved[0] / "training_state.json").is_file()


# -- T35: the CLI RAM figure says "estimated" ------------------------


def test_cli_train_reports_ram_as_estimated(home, monkeypatch, capsys):
    # The closing line used to present the pre-run estimate as a
    # measurement ("GB RAM used"). Now it says estimated.
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 3,
            "final_loss": 5.5,
            "trainable_params": 12345,
            "ram_estimate_gb": 4.2,
        },
    )
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "about 4.2 GB RAM (estimated)." in out
    assert "RAM used" not in out


# -- T142: the risky CLI paths ----------------------------------------
# One test per risky path. Already covered elsewhere, not duplicated
# here: Ctrl+C pause (test_cli_train_ctrl_c_pauses), file-destination
# export (test_cli_export_to_file_destination), bad-manifest import
# (test_cli_import_bad_manifest), nameless manifest
# (test_cli_profiles_nameless_manifest). --steps rounding (no
# rounding: exactly N steps) is pinned at the engine level by
# test_steps_cap_runs_exactly_n_steps.


def test_cli_unknown_command_exit_2(home):
    res = run_cli(home, "frobnicate")
    assert res.returncode == 2
    assert "usage:" in res.stderr
    assert "invalid choice" in res.stderr
    assert "Traceback" not in res.stderr


def test_cli_no_command_prints_command_list(home):
    # T187: bare `stella` prints the command list (the top --help)
    # and exits 0 — not argparse's "arguments are required" error.
    res = run_cli(home)
    assert res.returncode == 0
    assert "usage:" in res.stdout
    assert "profiles" in res.stdout
    assert "create-profile" in res.stdout
    assert "Traceback" not in res.stderr
    assert "required" not in res.stderr


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_cli_steps_zero_or_negative_refused(home, bad):
    # Argparse refuses before any project lookup: no setup needed.
    res = run_cli(home, "train", "p1", "proj", "--steps", bad)
    assert res.returncode == 2
    assert "--steps must be at least 1" in res.stderr
    assert "Traceback" not in res.stderr


def test_cli_quant_bogus_refused(home, tmp_path):
    # Validation is first in export_gguf (T27): a bogus quant fails
    # before the adapter check, the merge, or anything else — no
    # adapter needed for this test, and nothing is created.
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    out = tmp_path / "out"
    res = run_cli(
        home, "export-gguf", "p1", "proj", str(out), "--quant", "BOGUS"
    )
    assert res.returncode == 1
    assert "not a quant type" in res.stderr
    assert "Traceback" not in res.stderr
    assert not (out / "proj-merged-hf").exists()


def test_cli_corrupt_home_lists_survive(home):
    # A corrupt manifest (T3) is a damaged row in the list, not a
    # crash — the good rows still print.
    run_cli(home, "create-profile", "good", "--tag", "x:1b")
    run_cli(home, "create-project", "good", "proj")
    pdir = Path(home) / "profiles" / "broken"
    (pdir / "projects").mkdir(parents=True)
    (pdir / "profile.json").write_text("{not json", encoding="utf-8")
    proj_dir = Path(home) / "profiles" / "good" / "projects" / "wrecked"
    proj_dir.mkdir(parents=True)
    (proj_dir / "project.json").write_text("{not json", encoding="utf-8")
    res = run_cli(home, "profiles")
    assert res.returncode == 0
    assert "good" in res.stdout
    assert "broken" in res.stdout
    assert "(damaged:" in res.stdout
    assert "Traceback" not in res.stderr
    res = run_cli(home, "projects", "good")
    assert res.returncode == 0
    assert "proj" in res.stdout
    assert "wrecked" in res.stdout
    assert "(damaged:" in res.stdout
    assert "Traceback" not in res.stderr


def test_cli_resume_on_finished_announces(home, monkeypatch, capsys):
    # In-process: the engine emits the extending event (T25) and
    # the CLI prints it before the steps.
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    seen = {}

    def fake_train(store, profile, project, **kwargs):
        seen.update(kwargs)
        on_event = kwargs["on_event"]
        on_event(
            {"type": "extending", "trained_steps": 2, "new_total": 9}
        )
        on_event({"type": "started", "total_steps": 9, "rank": 2})
        on_event({"type": "done", "adapter": "/tmp/fake/adapter"})
        return {
            "steps": 9,
            "final_loss": 5.5,
            "trainable_params": 12345,
            "ram_estimate_gb": 4.2,
        }

    monkeypatch.setattr(train_mod, "train_project", fake_train)
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    code = cli_mod.main(["train", "p1", "proj", "--resume"])
    assert code == 0
    assert seen["resume"] is True
    assert seen["force"] is False
    out = capsys.readouterr().out
    assert "already finished training (2 steps)" in out
    assert "extends it to 9 total steps" in out
    # The announcement comes before the "started" line.
    assert out.index("already finished training") < out.index("Training: 9 steps")


def test_cli_train_force_flag_reaches_engine(home, monkeypatch, capsys):
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    seen = {}

    def fake_train(store, profile, project, **kwargs):
        seen.update(kwargs)
        return {
            "steps": 3,
            "final_loss": 5.5,
            "trainable_params": 12345,
            "ram_estimate_gb": 4.2,
        }

    monkeypatch.setattr(train_mod, "train_project", fake_train)
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    code = cli_mod.main(["train", "p1", "proj", "--force"])
    assert code == 0
    assert seen["force"] is True


def test_cli_train_target_modules_flag_reaches_engine(
    home, monkeypatch, capsys
):
    # T34: --target-modules q_proj,k_proj reaches the engine as a
    # list (whitespace stripped); an absent flag is None.
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    seen = {}

    def fake_train(store, profile, project, **kwargs):
        seen.update(kwargs)
        return {
            "steps": 3,
            "final_loss": 5.5,
            "trainable_params": 12345,
            "ram_estimate_gb": 4.2,
        }

    monkeypatch.setattr(train_mod, "train_project", fake_train)
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    code = cli_mod.main(
        ["train", "p1", "proj", "--target-modules", "q_proj, k_proj"]
    )
    assert code == 0
    assert seen["target_modules"] == ["q_proj", "k_proj"]
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    assert seen["target_modules"] is None


def test_cli_export_gguf_prints_converter_warning(home, monkeypatch, capsys):
    # In-process: the engine calls on_warning before the merge
    # (T31) and the CLI prints it; --force (T24) reaches the engine.
    import stella.cli as cli_mod
    import stella.gguf as gguf_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    seen = {}

    def fake_export(store, profile, project, dest, **kwargs):
        seen.update(kwargs)
        kwargs["on_warning"]("Close other apps before exporting.")
        return {
            "merged_hf": "/tmp/fake/merged",
            "gguf": "/tmp/fake/model.gguf",
            "quant": "Q4_K_M",
            "gguf_bytes": 1234,
            "modelfile": "/tmp/fake/Modelfile",
            "ollama_name": "p1-proj",
            "ollama_create": "ollama create p1-proj -f /tmp/fake/Modelfile",
        }

    monkeypatch.setattr(gguf_mod, "export_gguf", fake_export)
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    code = cli_mod.main(
        ["export-gguf", "p1", "proj", str(home / "out"), "--force"]
    )
    assert code == 0
    assert seen["force"] is True
    assert seen["quant"] == "Q4_K_M"
    out = capsys.readouterr().out
    assert "Close other apps before exporting." in out
    # The warning prints before the result lines.
    assert out.index("Close other apps") < out.index("Merged HF weights")


# -- T57: merge, don't discard, the profile block on import --------


def _cli_package(home, tmp_path):
    """A package exported from `home`: profile p1, tag x:1b,
    role fast, project proj."""
    run_cli(home, "create-profile", "p1", "--tag", "x:1b",
            "--role", "fast")
    run_cli(home, "create-project", "p1", "proj")
    dest = tmp_path / "exports"
    run_cli(home, "export", "p1", "proj", str(dest))
    return dest / "proj-stella-export"


def _cli_profile(home, slug="p1"):
    path = home / "profiles" / slug / "profile.json"
    return json.loads(path.read_text())


def test_cli_import_profile_merge_take(tmp_path):
    pkg = _cli_package(tmp_path / "home1", tmp_path)
    home2 = tmp_path / "home2"
    run_cli(home2, "create-profile", "p1", "--tag", "y:2b",
            "--role", "driver")
    res = run_cli(home2, "import", str(pkg), "--profile-merge", "take")
    assert res.returncode == 0
    assert "Profile 'p1' already existed." in res.stdout
    assert "Profile updated from the package" in res.stdout
    prof = _cli_profile(home2)
    assert (prof["ollama_tag"], prof["role"], prof["base_ref"]) == (
        "x:1b", "fast", "x:1b")


def test_cli_import_profile_merge_keep(tmp_path):
    pkg = _cli_package(tmp_path / "home1", tmp_path)
    home2 = tmp_path / "home2"
    run_cli(home2, "create-profile", "p1", "--tag", "y:2b",
            "--role", "driver")
    res = run_cli(home2, "import", str(pkg), "--profile-merge", "keep")
    assert res.returncode == 0
    assert "Profile 'p1' already existed." in res.stdout
    assert "updated from the package" not in res.stdout
    prof = _cli_profile(home2)
    assert (prof["ollama_tag"], prof["role"]) == ("y:2b", "driver")


def test_cli_import_without_flag_keeps_local_and_warns(tmp_path):
    pkg = _cli_package(tmp_path / "home1", tmp_path)
    home2 = tmp_path / "home2"
    run_cli(home2, "create-profile", "p1", "--tag", "y:2b",
            "--role", "driver")
    # No flag, no terminal (subprocess stdin is not a tty): the
    # import must not hang on input — it keeps local and warns.
    res = run_cli(home2, "import", str(pkg))
    assert res.returncode == 0
    assert "Warning:" in res.stdout
    assert "kept" in res.stdout
    assert "--profile-merge take" in res.stdout
    prof = _cli_profile(home2)
    assert (prof["ollama_tag"], prof["role"]) == ("y:2b", "driver")


def test_cli_prompt_profile_merge(monkeypatch, capsys):
    from stella import cli as cli_mod

    diff = {"ollama_tag": {"local": "y:2b", "package": "x:1b"}}
    monkeypatch.setattr("builtins.input", lambda prompt: "u")
    assert cli_mod._prompt_profile_merge("p1", diff) == "take"
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert cli_mod._prompt_profile_merge("p1", diff) == "keep"
    monkeypatch.setattr("builtins.input", lambda prompt: "nonsense")
    assert cli_mod._prompt_profile_merge("p1", diff) == "keep"

    def _eof(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert cli_mod._prompt_profile_merge("p1", diff) == "keep"
    out = capsys.readouterr().out
    assert "yours is 'y:2b'" in out


# -- T61: base-health check on import --------------------------------


def test_cli_import_warns_on_uninstalled_base_tag(
    tmp_path, monkeypatch, capsys
):
    """T61: the CLI import warns (naming the tag) when the
    package's tag is not installed on this PC."""
    import argparse

    from stella import cli as cli_mod
    from stella import export as export_mod
    from stella.model import Store

    src = Store(tmp_path / "src-home")
    src.create_profile("p1", ollama_tag="x:1b", role="fast")
    src.create_project("p1", "proj")
    pkg = export_mod.export_project(src, "p1", "proj", tmp_path)
    home2 = tmp_path / "home2"
    monkeypatch.setenv("STELLA_HOME", str(home2))
    monkeypatch.setattr(
        "stella.ollama.list_models", lambda: ["other:2b"]
    )
    args = argparse.Namespace(dir=str(pkg), profile_merge=None)
    assert cli_mod.cmd_import(args) == 0
    out = capsys.readouterr().out
    assert "Warning:" in out
    assert "x:1b" in out
    assert "not installed" in out


# -- T59: the dataset is part of the package decision ----------------


def test_cli_export_bundle_dataset(tmp_path):
    """T59: --bundle-dataset copies the dataset into the package."""
    from stella.model import Store

    home = tmp_path / "home"
    store = Store(home)
    store.create_profile("p1", ollama_tag="x:1b", role="fast")
    store.create_project("p1", "proj")
    data = tmp_path / "data.jsonl"
    data.write_text(
        '{"prompt": "a", "completion": "b"}\n', encoding="utf-8"
    )
    store.update_project("p1", "proj", dataset_ref=str(data))
    res = run_cli(
        home, "export", "p1", "proj", str(tmp_path / "exports"),
        "--bundle-dataset",
    )
    assert res.returncode == 0
    pkg = tmp_path / "exports" / "proj-stella-export"
    assert (pkg / "dataset" / "data.jsonl").is_file()


def test_cli_import_warns_on_missing_dataset(tmp_path):
    """T59: the CLI import prints the missing-dataset warning."""
    from stella import export as export_mod
    from stella.model import Store

    src = Store(tmp_path / "src-home")
    src.create_profile("p1", ollama_tag="x:1b", role="fast")
    src.create_project("p1", "proj", dataset_ref="gone.jsonl")
    pkg = export_mod.export_project(src, "p1", "proj", tmp_path)
    res = run_cli(tmp_path / "home2", "import", str(pkg))
    assert res.returncode == 0
    assert "Warning:" in res.stdout
    assert "gone.jsonl" in res.stdout
    assert "not on this PC" in res.stdout


# -- T58: the import preview ------------------------------------------


def test_cli_import_preview_prints_and_imports_nothing(tmp_path):
    """T58: --preview prints the summary and imports nothing."""
    from stella.model import Store

    pkg = _cli_package(tmp_path / "home1", tmp_path)
    home2 = tmp_path / "home2"
    res = run_cli(home2, "import", str(pkg), "--preview")
    assert res.returncode == 0
    assert "Profile p1, project proj." in res.stdout
    assert "Base model: x:1b." in res.stdout
    assert "Made with Stella" in res.stdout
    assert "Imported project" not in res.stdout
    store2 = Store(home2)
    with pytest.raises(Exception):
        store2.get_project("p1", "proj")


def test_cli_import_prints_summary_before_importing(tmp_path):
    """T58: a plain CLI import prints the preview summary first."""
    pkg = _cli_package(tmp_path / "home1", tmp_path)
    home2 = tmp_path / "home2"
    res = run_cli(home2, "import", str(pkg))
    assert res.returncode == 0
    assert "Profile p1, project proj." in res.stdout
    assert "Imported project 'proj'" in res.stdout
    # The summary comes before the import confirmation.
    assert res.stdout.index("Profile p1") < res.stdout.index("Imported")


# -- T83/T85/T90/T91/T96: the v0.16.0 CLI cluster ----------------------
# In-process (main() directly) so the engine can be faked: the probe
# and the trainer need weights, but the exit codes, the verdict
# channel, and the pre-flight only need the CLI's own logic.


def _rising_probe_result():
    """A probe result where refusals ROSE after tuning: the gate
    fails on it, and an informational run reports the change."""
    return {
        "profile": "p1",
        "project": "proj",
        "before": {
            "total": 18, "refusals": 0, "empty": 0, "rate": 0.0,
            "details": [],
        },
        "after": {
            "total": 18, "refusals": 3, "empty": 0,
            "rate": 0.167, "details": [],
        },
        "delta": 0.167,
        "mode": "gate",
    }


def _falling_probe_result():
    result = _rising_probe_result()
    result["after"] = {
        "total": 18, "refusals": 0, "empty": 0, "rate": 0.0,
        "details": [],
    }
    result["delta"] = 0.0
    return result


def _setup_probe_project(home, role="fast"):
    # R68: the default setup is a governing profile (role fast),
    # so the probe gates without flags — the gate tests' premise.
    # Pass role="" for a non-governing profile.
    args = ["create-profile", "p1", "--base", "test/tiny-model"]
    if role:
        args += ["--role", role]
    run_cli(home, *args)
    run_cli(home, "create-project", "p1", "proj")


def test_cli_probe_gate_fail_exits_3(home, monkeypatch, capsys):
    # T91: a failed gate exits 3 (not 1), and the verdict is on
    # stderr — readable separately from the numbers on stdout.
    import stella.cli as cli_mod
    import stella.probe as probe_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        probe_mod, "probe_project",
        lambda *a, **k: _rising_probe_result(),
    )
    _setup_probe_project(home)
    code = cli_mod.main(["probe", "p1", "proj"])
    assert code == 3
    out = capsys.readouterr()
    assert "0/18 refusals" in out.out
    assert "3/18 refusals" in out.out
    assert "gate failed" not in out.out
    assert "gate failed" in out.err


def test_cli_probe_gate_pass_exits_0(home, monkeypatch, capsys):
    # T91: a passed gate still exits 0, verdict on stderr.
    import stella.cli as cli_mod
    import stella.probe as probe_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        probe_mod, "probe_project",
        lambda *a, **k: _falling_probe_result(),
    )
    _setup_probe_project(home)
    code = cli_mod.main(["probe", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr()
    assert "Gate passed" in out.err
    assert "Gate passed" not in out.out


def test_cli_probe_informational_exits_0_no_verdict(
    home, monkeypatch, capsys
):
    # T90: an informational probe prints the counts and the change
    # with no verdict, and exits 0 even when refusals rose.
    import stella.cli as cli_mod
    import stella.probe as probe_mod

    seen = {}
    monkeypatch.setenv("STELLA_HOME", str(home))

    def fake_probe(store, profile, project, **kwargs):
        seen.update(kwargs)
        result = _rising_probe_result()
        result["mode"] = "informational"
        return result

    monkeypatch.setattr(probe_mod, "probe_project", fake_probe)
    _setup_probe_project(home)
    code = cli_mod.main(["probe", "p1", "proj", "--informational"])
    assert code == 0
    assert seen["informational"] is True
    out = capsys.readouterr()
    assert "0/18 refusals" in out.out
    assert "3/18 refusals" in out.out
    assert "Change:" in out.out
    assert "Gate" not in out.out
    assert "Gate" not in out.err


def test_cli_probe_non_governing_is_informational_by_default(
    home, monkeypatch, capsys
):
    # R68: the CLI auto-detects like the GUI — a non-governing
    # profile probes informationally without flags: a rising
    # result exits 0 with no gate verdict.
    import stella.cli as cli_mod
    import stella.probe as probe_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        probe_mod, "probe_project",
        lambda *a, **k: _rising_probe_result(),
    )
    _setup_probe_project(home, role="")
    code = cli_mod.main(["probe", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr()
    assert "Change:" in out.out
    assert "Gate" not in out.out
    assert "Gate" not in out.err


def test_cli_probe_gate_flag_forces_gate_on_non_governing(
    home, monkeypatch, capsys
):
    # R68: --gate forces the gate on a non-governing profile —
    # a rising result exits 3 with the verdict on stderr.
    import stella.cli as cli_mod
    import stella.probe as probe_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        probe_mod, "probe_project",
        lambda *a, **k: _rising_probe_result(),
    )
    _setup_probe_project(home, role="")
    code = cli_mod.main(["probe", "p1", "proj", "--gate"])
    assert code == 3
    out = capsys.readouterr()
    assert "gate failed" in out.err


def test_cli_probe_informational_overrides_gate_on_governing(
    home, monkeypatch, capsys
):
    # R68: --informational still forces informational on a
    # governing profile — a rising result exits 0, no verdict.
    import stella.cli as cli_mod
    import stella.probe as probe_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        probe_mod, "probe_project",
        lambda *a, **k: _rising_probe_result(),
    )
    _setup_probe_project(home)
    code = cli_mod.main(["probe", "p1", "proj", "--informational"])
    assert code == 0
    out = capsys.readouterr()
    assert "Change:" in out.out
    assert "Gate" not in out.err


def test_cli_probe_crash_exits_1(home, monkeypatch, capsys):
    # T91: a crashed probe still exits 1 — distinct from a failed
    # gate (3).
    import stella.cli as cli_mod
    import stella.probe as probe_mod
    from stella.model import StellaError

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        probe_mod, "probe_project",
        lambda *a, **k: (_ for _ in ()).throw(
            StellaError("no trained adapter yet")
        ),
    )
    _setup_probe_project(home)
    code = cli_mod.main(["probe", "p1", "proj"])
    assert code == 1
    assert "no trained adapter" in capsys.readouterr().err


def test_cli_probe_help_names_informational(home):
    res = run_cli(home, "probe", "--help")
    assert res.returncode == 0
    assert "--informational" in res.stdout
    assert "stella probe lfm3-tool tool-calls --informational" in res.stdout


def _setup_train_project(home, dataset_ref="sample-tool-calls.jsonl"):
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(
        home, "create-project", "p1", "proj", "--dataset", dataset_ref
    )


def test_cli_train_preflight_refuses_malformed_dataset(
    home, monkeypatch, capsys, tmp_path
):
    # T83: starting a run with a malformed dataset is refused with
    # the bad line numbers — the engine never starts.
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("training started on a bad dataset")
        ),
    )
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"prompt": "a", "completion": "b"}\nnot json\n')
    _setup_train_project(home, dataset_ref=str(bad))
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 1
    assert "dataset line 2" in capsys.readouterr().err


def test_cli_train_preflight_warns_tiny_dataset(
    home, monkeypatch, capsys, tmp_path
):
    # T83: a 3-example dataset warns before starting (the CLI
    # warns and proceeds; the window asks).
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 3, "final_loss": 5.5, "final_val_loss": 5.0,
            "trainable_params": 12345, "ram_estimate_gb": 4.2,
        },
    )
    tiny = tmp_path / "tiny.jsonl"
    tiny.write_text(
        "".join(
            json.dumps({"prompt": f"Q{i}?", "completion": f"A{i}."}) + "\n"
            for i in range(3)
        )
    )
    _setup_train_project(home, dataset_ref=str(tiny))
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dataset: 3 examples" in out
    assert "Warning: only 3 examples" in out


def test_cli_train_preflight_shows_healthy_dataset(
    home, monkeypatch, capsys
):
    # T83: a healthy dataset shows its row count and format before
    # the run starts.
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 3, "final_loss": 5.5, "final_val_loss": 5.0,
            "trainable_params": 12345, "ram_estimate_gb": 4.2,
        },
    )
    _setup_train_project(home)
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Dataset: 20 examples (messages format" in out


def test_cli_train_closing_line_shows_val_loss(home, monkeypatch, capsys):
    # T96: the closing line shows the final val loss next to the
    # training loss.
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 3, "final_loss": 5.5, "final_val_loss": 5.1234,
            "trainable_params": 12345, "ram_estimate_gb": 4.2,
        },
    )
    _setup_train_project(home)
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "final loss 5.5000, val loss 5.1234" in out


def test_cli_train_dry_run_prints_estimate_without_training(
    home, monkeypatch, capsys, tmp_path
):
    # T85: --dry-run prints RAM fit, steps, and disk — and trains
    # nothing (the engine is rigged to fail if it starts).
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("a dry run started training")
        ),
    )
    # S6: the dry run judges against free RAM, so the test pins
    # a box with plenty free to keep the 8 GB wording.
    monkeypatch.setattr(
        train_mod, "available_ram_bytes", lambda: 8 * 1024**3
    )
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({
        "hidden_size": 2048, "num_hidden_layers": 24,
        "intermediate_size": 8192, "torch_dtype": "bfloat16",
    }))
    (model_dir / "model.safetensors.index.json").write_text(json.dumps({
        "metadata": {"total_size": 3_460_000_000},
    }))
    run_cli(home, "create-profile", "p1", "--base", str(model_dir))
    run_cli(
        home, "create-project", "p1", "proj",
        "--dataset", "sample-tool-calls.jsonl",
    )
    code = cli_mod.main(["train", "p1", "proj", "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "RAM: about" in out
    assert "fits in 8.00 GB" in out
    assert "Steps: 9" in out
    assert "Disk: about" in out
    assert "Trained" not in out


def test_cli_train_help_names_dry_run(home):
    res = run_cli(home, "train", "--help")
    assert res.returncode == 0
    assert "--dry-run" in res.stdout


# -- T109: progress for long phases; honest paused output -------------


def test_cli_probe_prints_a_line_per_pass(home, monkeypatch, capsys):
    # In-process: the stubbed probe emits the phase events, and the
    # CLI prints a line when each pass starts.
    import stella.cli as cli_mod
    import stella.probe as probe_mod

    monkeypatch.setenv("STELLA_HOME", str(home))

    def fake_probe(store, profile, project, informational=False,
                   on_event=None, **kwargs):
        if on_event is not None:
            on_event({"type": "phase", "phase": "before"})
            on_event({"type": "phase", "phase": "after"})
        # R65: a realistic probe result carries the empty counts
        # — the gate refuses a result that leaves them out.
        return {
            "before": {"refusals": 0, "total": 12, "empty": 0, "rate": 0.0},
            "after": {"refusals": 0, "total": 12, "empty": 0, "rate": 0.0},
            "delta": 0.0,
        }

    monkeypatch.setattr(probe_mod, "probe_project", fake_probe)
    code = cli_mod.main(["probe", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Probing before tuning..." in out
    assert "Probing after tuning..." in out
    # The pass lines come before the results.
    assert out.index("Probing before tuning...") < out.index("Before tuning:")
    assert out.index("Probing after tuning...") < out.index("After tuning:")


def test_cli_train_paused_summary_says_paused(home, monkeypatch, capsys):
    # A paused run's closing line says Paused, not Trained.
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 4, "final_loss": 5.5, "final_val_loss": 5.0,
            "trainable_params": 12345, "ram_estimate_gb": 4.2,
            "stopped": True,
        },
    )
    _setup_train_project(home)
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Paused after 4 steps" in out
    assert "Trained 4 steps" not in out


def test_cli_export_gguf_prints_merge_line(home, monkeypatch, capsys):
    # In-process: the stubbed export emits the merge phase event,
    # and the CLI prints its line before the result lines.
    import stella.cli as cli_mod
    import stella.gguf as gguf_mod

    monkeypatch.setenv("STELLA_HOME", str(home))

    def fake_export(store, profile, project, dest, **kwargs):
        kwargs["on_event"]({
            "type": "phase", "phase": "merge",
            "message": "Merging the adapter into the base model...",
        })
        return {
            "merged_hf": "/tmp/fake/merged",
            "gguf": "/tmp/fake/model.gguf",
            "quant": "Q4_K_M",
            "gguf_bytes": 1234,
            "modelfile": "/tmp/fake/Modelfile",
            "ollama_name": "p1-proj",
            "ollama_create": "ollama create p1-proj -f /tmp/fake/Modelfile",
        }

    monkeypatch.setattr(gguf_mod, "export_gguf", fake_export)
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    code = cli_mod.main(
        ["export-gguf", "p1", "proj", str(home / "out")]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Merging the adapter into the base model..." in out
    assert (
        out.index("Merging the adapter")
        < out.index("Merged HF weights")
    )


# -- T110: silence the library warnings on stderr ---------------------


def test_silence_library_warnings_filters_noisy_notices(monkeypatch):
    # The helper filters the known-noisy transformers/peft notices
    # and turns the advisory warnings + tqdm bars off at the source,
    # while a warning Stella should hear still gets through.
    import os
    import warnings

    import stella.cli as cli_mod

    monkeypatch.delenv("TRANSFORMERS_NO_ADVISORY_WARNINGS", raising=False)
    monkeypatch.delenv("TQDM_DISABLE", raising=False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cli_mod._silence_library_warnings()
        warnings.warn(
            "`torch_dtype` is deprecated, use `dtype` instead",
            FutureWarning,
        )
        warnings.warn(
            "fan_in_fan_out is set to False but the target module "
            "is `Conv1D`.",
            UserWarning,
        )
        warnings.warn(
            "Unexpected keyword arguments ['metamorph_mode'] for "
            "class LoraConfig, these are ignored.",
            UserWarning,
        )
        warnings.warn("something Stella should still hear", UserWarning)
    assert [str(w.message) for w in caught] == [
        "something Stella should still hear"
    ]
    assert os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] == "1"
    assert os.environ["TQDM_DISABLE"] == "1"


# -- T111: CLI-appropriate error text ---------------------------------


def test_cli_train_no_dataset_names_dataset_flag(home):
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    res = run_cli(home, "train", "p1", "proj")
    assert res.returncode == 1
    assert "--dataset" in res.stderr
    assert "Train panel" not in res.stderr


def test_cli_error_strings_name_no_gui_controls():
    # T111 audit: no CLI error string points at a GUI control. The
    # one "Train panel" mention in cli.py is a code comment (the
    # pre-train check note), not a user-facing string.
    lines = (ROOT / "stella" / "cli.py").read_text().splitlines()
    hits = [line for line in lines if "Train panel" in line]
    assert hits, "the comment moved; re-audit"
    assert all(line.strip().startswith("#") for line in hits)
    # R15: sleep.py's errors reach CLI users too (stella sleep) —
    # the T111 guard used to grep only cli.py, so the "Train
    # panel" message in sleep.py slipped through.
    sleep_lines = (ROOT / "stella" / "sleep.py").read_text().splitlines()
    sleep_hits = [line for line in sleep_lines if "Train panel" in line]
    assert sleep_hits == [], sleep_hits


# -- T141: corrupt-block tests for the CLI list -----------------------


@pytest.mark.parametrize(
    "mutate, warns",
    [
        (lambda d: d.update(metamorph=None), True),
        (lambda d: d.pop("metamorph"), False),
        (lambda d: d.update(metamorph="both"), True),
    ],
)
def test_cli_projects_survives_corrupt_metamorph(home, mutate, warns):
    # T141: null / missing-key / wrong-type metamorph in
    # project.json — the CLI list shows the row, warns when the
    # block is broken (a missing key just means the default), and
    # never crashes.
    run_cli(home, "create-profile", "p1", "--tag", "x:1b")
    run_cli(home, "create-project", "p1", "good")
    run_cli(home, "create-project", "p1", "broken")
    manifest = (
        Path(home) / "profiles" / "p1" / "projects" / "broken"
        / "project.json"
    )
    data = json.loads(manifest.read_text())
    mutate(data)
    manifest.write_text(json.dumps(data))
    res = run_cli(home, "projects", "p1")
    assert res.returncode == 0
    assert "good" in res.stdout
    assert "broken" in res.stdout
    assert "Traceback" not in res.stderr
    if warns:
        assert "warning" in res.stdout
        assert "metamorph" in res.stdout
    else:
        assert "warning" not in res.stdout

# -- T88: CLI `projects` refuses a nonexistent profile --------------


def test_cli_projects_refuses_ghost_profile(home):
    """T88 Done: `projects` on a nonexistent profile exits 1 with
    a plain error."""
    res = run_cli(home, "projects", "ghost")
    assert res.returncode == 1
    assert "no profile named 'ghost'" in res.stderr


def test_cli_projects_empty_real_profile_is_clean(home):
    """T88 Done: on an empty REAL profile it still prints the
    empty message and exits 0."""
    run_cli(home, "create-profile", "p1")
    res = run_cli(home, "projects", "p1")
    assert res.returncode == 0
    assert "No projects in profile 'p1'." in res.stdout


# -- T87: CLI parity — rename, delete, update, show ------------------


def _seed_cli_home(home):
    run_cli(home, "create-profile", "p1", "--tag", "lfm3:1.7b",
            "--role", "fast")
    run_cli(home, "create-project", "p1", "proj",
            "--dataset", "sample-tool-calls.jsonl")


def test_cli_rename_profile(home):
    _seed_cli_home(home)
    res = run_cli(home, "rename-profile", "p1", "p2")
    assert res.returncode == 0
    assert "Renamed profile 'p1' to 'p2'" in res.stdout
    res = run_cli(home, "profiles")
    assert "p2" in res.stdout
    assert "p1" not in res.stdout


def test_cli_rename_profile_bad_name(home):
    _seed_cli_home(home)
    res = run_cli(home, "rename-profile", "p1", "Bad Name!")
    assert res.returncode == 1
    assert "not valid" in res.stderr
    res = run_cli(home, "rename-profile", "ghost", "p2")
    assert res.returncode == 1
    assert "no profile named 'ghost'" in res.stderr


def test_cli_delete_profile_moves_to_trash(home):
    """T87 Done: delete moves to trash (T23); --purge removes
    forever."""
    from stella.model import Store

    _seed_cli_home(home)
    res = run_cli(home, "delete-profile", "p1")
    assert res.returncode == 0
    assert "to the trash" in res.stdout
    store = Store(home)
    assert store.list_trash()
    with pytest.raises(Exception):
        store.get_profile("p1")
    res = run_cli(home, "delete-profile", "ghost")
    assert res.returncode == 1


def test_cli_delete_profile_purge(home):
    from stella.model import Store

    _seed_cli_home(home)
    res = run_cli(home, "delete-profile", "p1", "--purge", "--yes")
    assert res.returncode == 0
    assert "forever" in res.stdout
    assert Store(home).list_trash() == []


def test_cli_update_profile(home):
    _seed_cli_home(home)
    res = run_cli(
        home, "update-profile", "p1", "--role", "driver",
        "--tag", "other:9b", "--display", "Driver Seat",
    )
    assert res.returncode == 0
    res = run_cli(home, "show-profile", "p1")
    assert "role: driver" in res.stdout
    assert "tag: other:9b" in res.stdout
    assert "Driver Seat" in res.stdout


def test_cli_update_profile_no_flags_is_a_noop(home):
    _seed_cli_home(home)
    res = run_cli(home, "update-profile", "p1")
    assert res.returncode == 0
    assert "Nothing to change" in res.stdout


def test_cli_update_profile_has_no_processor_flag(home):
    """T87/T128: the processor field's meaning is undecided, so
    there is no --processor option to invent it with."""
    res = run_cli(home, "update-profile", "--help")
    assert res.returncode == 0
    assert "--processor" not in res.stdout


def test_cli_show_profile(home):
    _seed_cli_home(home)
    res = run_cli(home, "show-profile", "p1")
    assert res.returncode == 0
    assert "Profile p1" in res.stdout
    assert "role: fast" in res.stdout
    assert "tag: lfm3:1.7b" in res.stdout
    assert "projects (1): proj" in res.stdout
    res = run_cli(home, "show-profile", "ghost")
    assert res.returncode == 1
    assert "no profile named 'ghost'" in res.stderr


def test_cli_rename_project(home):
    _seed_cli_home(home)
    res = run_cli(home, "rename-project", "p1", "proj", "proj2")
    assert res.returncode == 0
    assert "Renamed project 'proj' to 'proj2'" in res.stdout
    res = run_cli(home, "projects", "p1")
    assert "proj2" in res.stdout


def test_cli_delete_project_moves_to_trash(home):
    from stella.model import Store

    _seed_cli_home(home)
    res = run_cli(home, "delete-project", "p1", "proj")
    assert res.returncode == 0
    assert "to the trash" in res.stdout
    assert Store(home).list_trash()
    res = run_cli(home, "delete-project", "p1", "proj", "--purge", "--yes")
    assert res.returncode == 1  # already gone


def test_cli_delete_project_purge(home):
    from stella.model import Store

    _seed_cli_home(home)
    res = run_cli(home, "delete-project", "p1", "proj", "--purge", "--yes")
    assert res.returncode == 0
    assert "forever" in res.stdout
    assert Store(home).list_trash() == []


def test_cli_update_project(home):
    """T87 Done: update-project changes display, dataset,
    metamorph mode (A7-G7), and settings."""
    from stella.model import Store, metamorph_mode

    _seed_cli_home(home)
    res = run_cli(
        home, "update-project", "p1", "proj",
        "--display", "Renamed", "--metamorph", "both",
        "--rank", "16", "--epochs", "5",
    )
    assert res.returncode == 0
    proj = Store(home).get_project("p1", "proj")
    assert proj["display_name"] == "Renamed"
    assert metamorph_mode(proj) == "both"
    assert proj["settings"]["rank"] == 16
    assert proj["settings"]["epochs"] == 5


def test_cli_update_project_bad_setting_refused(home):
    _seed_cli_home(home)
    res = run_cli(home, "update-project", "p1", "proj", "--rank", "999")
    assert res.returncode == 1
    assert "rank" in res.stderr


def test_cli_show_project_lists_checkpoints(home):
    """T87 Done (A5-G2): show-project lists the checkpoints, so
    the user can see what `train --resume` would use."""
    from stella.model import Store

    _seed_cli_home(home)
    store = Store(home)
    ckpt = (
        store.project_dir("p1", "proj") / "checkpoints" / "step-10"
    )
    ckpt.mkdir(parents=True)
    (ckpt / "training_state.json").write_text(
        json.dumps({"step": 10, "epoch": 1, "loss": 0.5})
    )
    res = run_cli(home, "show-project", "p1", "proj")
    assert res.returncode == 0
    assert "Project proj" in res.stdout
    assert "dataset: sample-tool-calls.jsonl" in res.stdout
    assert "metamorph: morph" in res.stdout
    assert "rank:" in res.stdout
    assert "checkpoints (1):" in res.stdout
    assert "step 10" in res.stdout
    res = run_cli(home, "show-project", "p1", "ghost")
    assert res.returncode == 1
    assert "no project named 'ghost'" in res.stderr


def test_cli_create_project_takes_settings_flags(home):
    """T87: create-project takes the same settings flags as
    update-project."""
    from stella.model import Store

    run_cli(home, "create-profile", "p1")
    res = run_cli(
        home, "create-project", "p1", "proj",
        "--rank", "16", "--epochs", "2", "--metamorph", "compress",
    )
    assert res.returncode == 0
    proj = Store(home).get_project("p1", "proj")
    assert proj["settings"]["rank"] == 16
    assert proj["settings"]["epochs"] == 2
    from stella.model import metamorph_mode

    assert metamorph_mode(proj) == "compress"


def test_cli_create_project_from_template(home):
    """T112: create-project --template pre-fills the preset."""
    from stella.model import Store, metamorph_mode

    run_cli(home, "create-profile", "p1")
    res = run_cli(
        home, "create-project", "p1", "tool-try",
        "--template", "lfm3-tool-format",
    )
    assert res.returncode == 0
    proj = Store(home).get_project("p1", "tool-try")
    assert proj["dataset_ref"] == "sample-tool-calls.jsonl"
    assert metamorph_mode(proj) == "both"
    assert proj["settings"]["rank"] == 8
    res = run_cli(
        home, "create-project", "p1", "tool-try-2",
        "--template", "no-such-template",
    )
    assert res.returncode == 1
    assert "no template named" in res.stderr


# -- T105: a verify command (CLI half) -------------------------------


def test_cli_verify_good_package(home, tmp_path):
    """T105 Done: `stella verify` on a good package reports all
    checks pass; nothing is imported."""
    from stella.model import Store

    _seed_cli_home(home)
    dest = tmp_path / "exports"
    run_cli(home, "export", "p1", "proj", str(dest))
    pkg = dest / "proj-stella-export"
    res = run_cli(home, "verify", str(pkg))
    assert res.returncode == 0
    assert "OK: Manifest present" in res.stdout
    assert "OK: Files match their checksums" in res.stdout
    assert "All checks passed. Nothing was imported." in res.stdout


def test_cli_verify_bad_package_names_the_check(home, tmp_path):
    """T105 Done: on a bad package it names the failing check."""
    _seed_cli_home(home)
    dest = tmp_path / "exports"
    run_cli(home, "export", "p1", "proj", str(dest))
    pkg = dest / "proj-stella-export"
    (pkg / "notes.md").write_bytes(b"tampered")
    res = run_cli(home, "verify", str(pkg))
    assert res.returncode == 1
    assert "FAIL: Files match their checksums" in res.stdout
    assert "notes.md" in res.stdout
    assert "A check failed. Nothing was imported." in res.stdout


# -- T86: export-profile (CLI half) ----------------------------------


def test_cli_export_profile_round_trip(home, tmp_path):
    """T86: export-profile + import brings a project-less profile
    back."""
    from stella.model import Store

    run_cli(home, "create-profile", "solo", "--tag", "lfm3:1.7b",
            "--role", "fast")
    dest = tmp_path / "exports"
    res = run_cli(home, "export-profile", "solo", str(dest))
    assert res.returncode == 0
    assert "solo-stella-profile-export" in res.stdout
    run_cli(home, "delete-profile", "solo", "--purge", "--yes")
    res = run_cli(home, "import", str(dest / "solo-stella-profile-export"))
    assert res.returncode == 0
    assert "Imported profile 'solo' (no projects)." in res.stdout
    assert Store(home).get_profile("solo")["role"] == "fast"


def test_cli_export_profile_with_projects(home, tmp_path):
    _seed_cli_home(home)
    dest = tmp_path / "exports"
    res = run_cli(
        home, "export-profile", "p1", str(dest), "--with-projects"
    )
    assert res.returncode == 0
    fresh = tmp_path / "fresh-home"
    res = run_cli(
        fresh, "import", str(dest / "p1-stella-profile-export")
    )
    assert res.returncode == 0
    assert "Imported profile 'p1' with 1 project: proj." in res.stdout


# -- T117: collision options (CLI half) ------------------------------


def test_cli_export_force(home, tmp_path):
    _seed_cli_home(home)
    dest = tmp_path / "exports"
    assert run_cli(home, "export", "p1", "proj", str(dest)).returncode == 0
    res = run_cli(home, "export", "p1", "proj", str(dest))
    assert res.returncode == 1
    assert "already exists" in res.stderr
    res = run_cli(home, "export", "p1", "proj", str(dest), "--force")
    assert res.returncode == 0
    assert "Exported to" in res.stdout


def test_cli_import_as_copy_and_replace(home, tmp_path):
    """T117: --as-copy imports under a new slug; --replace moves
    the old project to the trash."""
    from stella.model import Store

    _seed_cli_home(home)
    dest = tmp_path / "exports"
    run_cli(home, "export", "p1", "proj", str(dest))
    pkg = str(dest / "proj-stella-export")
    res = run_cli(home, "import", pkg)
    assert res.returncode == 1
    assert "already exists" in res.stderr
    res = run_cli(home, "import", pkg, "--as-copy")
    assert res.returncode == 0
    assert "a copy of 'proj'" in res.stdout
    assert Store(home).get_project("p1", "proj-copy")
    res = run_cli(home, "import", pkg, "--replace")
    assert res.returncode == 0
    assert "went to the trash" in res.stdout
    assert Store(home).list_trash()


# -- T108: second Ctrl+C force-quits ----------------------------------


def test_cli_train_second_ctrl_c_exits_at_once(tmp_path):
    """T108 Done: a second Ctrl+C during a run exits immediately
    (130) instead of re-requesting the same graceful stop. The
    stubborn driver ignores the first stop — the way a blocking
    base download does — so only the second press can end it."""
    import signal
    import time

    home = tmp_path / "home"
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "_ctrlc_driver.py"),
         str(home), "stubborn"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    try:
        time.sleep(2)
        assert proc.poll() is None, "the fake run ended before Ctrl+C"
        proc.send_signal(signal.SIGINT)
        time.sleep(1)
        assert proc.poll() is None, "the first Ctrl+C ended a stubborn run"
        proc.send_signal(signal.SIGINT)
        _out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=10)
    assert proc.returncode == 130
    assert "Traceback" not in err


def test_cli_train_prints_download_message(home, monkeypatch, capsys):
    """T108 Done: the loading line is printed before the base
    loads, so a Ctrl+C during the download is not a mystery."""
    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))

    def fake_train(*args, **kwargs):
        kwargs["on_event"]({
            "type": "loading",
            "message": (
                "Loading the base model. The first run downloads "
                "it, and Ctrl+C takes effect when the download "
                "finishes."
            ),
        })
        return {
            "steps": 1, "final_loss": 1.0, "trainable_params": 10,
            "ram_estimate_gb": 0.1,
        }

    monkeypatch.setattr(train_mod, "train_project", fake_train)
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Loading the base model." in out
    assert "Ctrl+C takes effect when the download finishes." in out


# -- T89: --create on export-gguf (CLI half) --------------------------


def test_cli_export_gguf_create_runs_ollama_create(
        home, tmp_path, monkeypatch, capsys):
    """T89: --create runs `ollama create` after the export, and
    the manual commands are still printed."""
    import stella.cli as cli_mod
    import stella.gguf as gguf_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")
    monkeypatch.setattr(
        gguf_mod, "export_gguf",
        lambda *a, **k: {
            "merged_hf": "/tmp/merged",
            "gguf": "/tmp/model.gguf", "quant": "Q4_K_M",
            "gguf_bytes": 123,
            "modelfile": str(modelfile),
            "ollama_name": "p1-proj",
            "ollama_create": (
                f"ollama create p1-proj -f {modelfile}"
            ),
        },
    )
    seen = []
    monkeypatch.setattr(
        gguf_mod, "create_in_ollama",
        lambda name, mf, **k: seen.append((name, str(mf))) or "created",
    )
    code = cli_mod.main(
        ["export-gguf", "p1", "proj", str(tmp_path), "--create"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "ollama create p1-proj" in out  # still printed
    assert "Created in Ollama as p1-proj." in out
    assert seen == [("p1-proj", str(modelfile))]


# -- v0.19.0: T114, T115, T116 ----------------------------------------


def test_cli_create_project_metamorph_notes_flag(home):
    """T114 Done: the --metamorph-notes flag sets the notes at
    creation (and update-project sets them later); show-project
    prints them."""
    from stella.model import Store

    run_cli(home, "create-profile", "p1")
    res = run_cli(
        home, "create-project", "p1", "proj",
        "--metamorph", "both", "--metamorph-notes", "squeeze it down",
    )
    assert res.returncode == 0
    proj = Store(home).get_project("p1", "proj")
    assert proj["metamorph"]["notes"] == "squeeze it down"
    assert proj["metamorph"]["mode"] == "both"
    res = run_cli(home, "show-project", "p1", "proj")
    assert "squeeze it down" in res.stdout
    res = run_cli(
        home, "update-project", "p1", "proj",
        "--metamorph-notes", "changed my mind",
    )
    assert res.returncode == 0
    proj = Store(home).get_project("p1", "proj")
    assert proj["metamorph"]["notes"] == "changed my mind"
    assert proj["metamorph"]["mode"] == "both"


def test_cli_update_profile_config_and_dependencies(home):
    """T115 Done: config and dependencies are reachable through
    update-profile, and show-profile prints them."""
    _seed_cli_home(home)
    res = run_cli(
        home, "update-profile", "p1",
        "--config", '{"ctx": 8192, "flag": true}',
        "--dependencies", "torch, transformers",
    )
    assert res.returncode == 0
    res = run_cli(home, "show-profile", "p1")
    assert "ctx" in res.stdout
    assert "8192" in res.stdout
    assert "torch, transformers" in res.stdout


def test_cli_update_profile_bad_config_json_refused(home):
    """T115: bad JSON is refused with the parse error, and the
    old config stays — nothing is written."""
    from stella.model import Store

    _seed_cli_home(home)
    run_cli(home, "update-profile", "p1", "--config", '{"keep": true}')
    res = run_cli(home, "update-profile", "p1", "--config", '{"keep": ')
    assert res.returncode == 1
    assert "not valid JSON" in res.stderr
    assert Store(home).get_profile("p1")["config"] == {"keep": True}
    res = run_cli(home, "update-profile", "p1", "--config", "[1, 2]")
    assert res.returncode == 1
    assert "must be a JSON object" in res.stderr
    assert Store(home).get_profile("p1")["config"] == {"keep": True}


def test_cli_update_profile_governing_seat(home):
    """T116: the governing-seat marker is set through
    update-profile and shown by show-profile; a seat that is
    not governing is refused."""
    _seed_cli_home(home)
    res = run_cli(home, "update-profile", "p1", "--governing-seat", "driver")
    assert res.returncode == 0
    res = run_cli(home, "show-profile", "p1")
    assert "governing seat: driver" in res.stdout
    res = run_cli(home, "update-profile", "p1", "--governing-seat", "vision")
    assert res.returncode == 1
    assert "governing seat" in res.stderr


def test_cli_show_profile_flags_custom_role(home):
    """T116: a custom role is flagged in show-profile; a
    canonical role is not."""
    _seed_cli_home(home)
    res = run_cli(home, "show-profile", "p1")
    assert "custom" not in res.stdout
    run_cli(home, "update-profile", "p1", "--role", "drvier")
    res = run_cli(home, "show-profile", "p1")
    assert "role: drvier" in res.stdout
    assert "custom" in res.stdout


def test_cli_train_governing_seat_warning(home, monkeypatch, capsys):
    """T116: training a profile bound for a governing seat on a
    stock base warns on the CLI, naming the seat and the base —
    and proceeds (the CLI warns, the window asks)."""
    import stella.cli as cli_mod
    import stella.train as train_mod
    from stella.model import Store

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 3, "final_loss": 5.5, "final_val_loss": 5.0,
            "trainable_params": 12345, "ram_estimate_gb": 4.2,
        },
    )
    store = Store(home)
    store.create_profile(
        "p1", base_ref="test/tiny-model", governing_seat="driver"
    )
    store.create_project(
        "p1", "proj", dataset_ref="sample-tool-calls.jsonl"
    )
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Warning: " in out
    assert "driver" in out
    assert "test/tiny-model" in out


def test_cli_train_governing_role_only_warns(home, monkeypatch, capsys):
    """R67: a governing ROLE with no marker warns on the CLI too —
    and proceeds (the CLI warns, the window asks)."""
    import stella.cli as cli_mod
    import stella.train as train_mod
    from stella.model import Store

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 3, "final_loss": 5.5, "final_val_loss": 5.0,
            "trainable_params": 12345, "ram_estimate_gb": 4.2,
        },
    )
    store = Store(home)
    store.create_profile(
        "p1", base_ref="test/tiny-model", role="driver"
    )
    store.create_project(
        "p1", "proj", dataset_ref="sample-tool-calls.jsonl"
    )
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Warning: " in out
    assert "driver" in out
    assert "test/tiny-model" in out


def test_cli_train_governing_seat_abliterated_no_warning(
    home, monkeypatch, capsys
):
    """T116: the same bound seat on an abliterated base warns
    about nothing."""
    import stella.cli as cli_mod
    import stella.train as train_mod
    from stella.model import Store

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 3, "final_loss": 5.5, "final_val_loss": 5.0,
            "trainable_params": 12345, "ram_estimate_gb": 4.2,
        },
    )
    store = Store(home)
    store.create_profile(
        "p1", ollama_tag="minicpm5-heretic:2b",
        base_ref="test/tiny-model", governing_seat="driver",
    )
    store.create_project(
        "p1", "proj", dataset_ref="sample-tool-calls.jsonl"
    )
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    assert "bound for" not in out
    assert "abliterated base" not in out


# -- v0.21.0: T178 — size/disk awareness on export ------------------


def test_cli_export_reports_size_before_and_after(home, tmp_path):
    """T178: the export prints the estimated size before copying
    and the real package size after."""
    _seed_cli_home(home)
    dest = tmp_path / "exports"
    res = run_cli(home, "export", "p1", "proj", str(dest))
    assert res.returncode == 0
    assert "Package size: about " in res.stdout
    lines = [ln for ln in res.stdout.splitlines() if "Package size:" in ln]
    assert len(lines) == 2
    assert lines[0].startswith("Package size: about ")
    assert lines[1].startswith("Package size: ")
    assert "about" not in lines[1]
    assert "Exported to " in res.stdout


def test_cli_export_profile_reports_size(home, tmp_path):
    """T178: export-profile reports the size the same way."""
    _seed_cli_home(home)
    dest = tmp_path / "exports"
    res = run_cli(home, "export-profile", "p1", str(dest), "--with-projects")
    assert res.returncode == 0
    lines = [ln for ln in res.stdout.splitlines() if "Package size:" in ln]
    assert len(lines) == 2


# -- S3: distill --timeout --------------------------------------------


def test_cli_distill_timeout_default_is_300():
    from stella.cli import build_parser
    from stella.distill import DEFAULT_TIMEOUT_SECONDS

    args = build_parser().parse_args([
        "distill", "p1", "proj",
        "--teacher", "qwen3.5:4b", "--prompts", "prompts.txt",
    ])
    assert args.timeout == 300.0
    # The parser's default and the engine's default stay the same
    # number: a drift here would silently change the wait.
    assert args.timeout == DEFAULT_TIMEOUT_SECONDS


def test_cli_distill_timeout_parses():
    from stella.cli import build_parser

    args = build_parser().parse_args([
        "distill", "p1", "proj",
        "--teacher", "qwen3.5:4b", "--prompts", "prompts.txt",
        "--timeout", "600",
    ])
    assert args.timeout == 600.0
    args = build_parser().parse_args([
        "distill", "p1", "proj",
        "--teacher", "qwen3.5:4b", "--prompts", "prompts.txt",
        "--timeout", "90.5",
    ])
    assert args.timeout == 90.5


@pytest.mark.parametrize("bad, message", [
    ("0", "--timeout must be more than 0 seconds."),
    ("-5", "--timeout must be more than 0 seconds."),
    ("soon", "'soon' is not a number of seconds."),
])
def test_cli_distill_timeout_bad_refused(home, bad, message):
    # Argparse refuses before any project lookup: no setup needed.
    res = run_cli(
        home, "distill", "p1", "proj",
        "--teacher", "qwen3.5:4b", "--prompts", "prompts.txt",
        "--timeout", bad,
    )
    assert res.returncode == 2
    assert message in res.stderr
    assert "Traceback" not in res.stderr


# -- S21: the ETA -----------------------------------------------------


def test_eta_text_from_rate():
    from stella.cli import _eta_text

    # 10 done in 60s (6s each), 90 to go: 540s, 9 minutes.
    assert _eta_text(60.0, 10, 90) == "about 9 minutes left"
    # 2 done in 120s (60s each), 7 to go: 420s, 7 minutes.
    assert _eta_text(120.0, 2, 7) == "about 7 minutes left"
    # Seconds, not minutes, when the wait is short.
    assert _eta_text(10.0, 5, 2) == "about 4 seconds left"
    # Hours when the wait is long.
    assert _eta_text(3600.0, 2, 4) == "about 2 hours 0 minutes left"


def test_eta_text_suppressed_before_enough_samples():
    from stella.cli import _eta_text

    # One sample is not a rate: no ETA, never a bogus one.
    assert _eta_text(60.0, 1, 90) == ""
    assert _eta_text(60.0, 0, 90) == ""


def test_eta_text_suppressed_when_nothing_left_or_no_time():
    from stella.cli import _eta_text

    assert _eta_text(60.0, 10, 0) == ""
    assert _eta_text(0.0, 5, 5) == ""


def test_cli_format_duration():
    from stella.cli import _format_duration

    assert _format_duration(0) == "0 seconds"
    assert _format_duration(1) == "1 second"
    assert _format_duration(40) == "40 seconds"
    assert _format_duration(60) == "1 minute"
    assert _format_duration(150) == "2 minutes"
    assert _format_duration(3600) == "1 hour 0 minutes"
    assert _format_duration(3900) == "1 hour 5 minutes"


def test_cli_train_shows_eta_after_two_steps(home, monkeypatch, capsys):
    """The step lines gain a time-left tail once two steps have
    run in this run (the rate anchors on the first step event, so
    a resumed run measures only its own steps). The clock is
    faked: 60 seconds per step, 10 steps."""
    import time

    import stella.cli as cli_mod
    import stella.train as train_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    now = [1000.0]

    def fake_train(store, profile, project, **kwargs):
        on_event = kwargs["on_event"]
        on_event({"type": "started", "total_steps": 10, "rank": 2})
        for step in range(1, 6):
            now[0] += 60.0
            on_event({
                "type": "step", "step": step, "total_steps": 10,
                "epoch": 1, "loss": 5.0, "lr": 1e-4,
            })
        on_event({"type": "done", "adapter": "/tmp/fake/adapter"})
        return {
            "steps": 5,
            "final_loss": 5.0,
            "trainable_params": 12345,
            "ram_estimate_gb": 4.2,
        }

    monkeypatch.setattr(train_mod, "train_project", fake_train)
    run_cli(home, "create-profile", "p1", "--base", "test/tiny-model")
    run_cli(home, "create-project", "p1", "proj")
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith("step ")]
    assert len(lines) == 5
    # No ETA yet: 0 and 1 steps measured since the anchor.
    assert "left" not in lines[0]
    assert "left" not in lines[1]
    # Step 3: 2 steps in 120s, 7 to go at 60s each: 7 minutes.
    assert lines[2].endswith(", about 7 minutes left")
    # Step 5: 4 steps in 240s, 5 to go: 5 minutes.
    assert lines[4].endswith(", about 5 minutes left")


# -- v0.26.0: R28 — method full cannot be set from the CLI -----------


def test_cli_create_project_method_full_refused(home):
    """R28: --method full is refused in plain words, and no
    project is created."""
    from stella.model import Store

    run_cli(home, "create-profile", "p1")
    res = run_cli(
        home, "create-project", "p1", "proj", "--method", "full",
    )
    assert res.returncode == 1
    assert "method full is not available" in res.stderr
    assert "LoRA" in res.stderr
    assert not (Store(home).project_dir("p1", "proj")
                / "project.json").exists()


def test_cli_update_project_method_full_refused(home):
    """R28: --method full is refused on update-project too, and
    the stored settings are untouched."""
    from stella.model import Store

    _seed_cli_home(home)
    res = run_cli(
        home, "update-project", "p1", "proj", "--method", "full",
    )
    assert res.returncode == 1
    assert "method full is not available" in res.stderr
    assert Store(home).get_project("p1", "proj")["settings"]["method"] == "lora"


def test_cli_method_lora_passes_through(home):
    """R28: --method lora still works — it is what every run
    trains."""
    from stella.model import Store

    run_cli(home, "create-profile", "p1")
    res = run_cli(
        home, "create-project", "p1", "proj", "--method", "lora",
    )
    assert res.returncode == 0
    assert Store(home).get_project("p1", "proj")["settings"]["method"] == "lora"


def test_cli_show_project_warns_on_stored_full(home):
    """R28: a project stored with method full (set before v0.26.0)
    warns in show-project, so the listing never implies a full run
    is coming."""
    from stella.model import Store

    _seed_cli_home(home)
    Store(home).update_project(
        "p1", "proj", settings={"method": "full"},
    )
    res = run_cli(home, "show-project", "p1", "proj")
    assert res.returncode == 0
    assert "method: full" in res.stdout
    assert "always trains with LoRA" in res.stdout


# -- v0.27.0: R52 — --json honoured or refused, never ignored ------


# The commands that refuse --json (R52): long-running commands that
# print progress lines as they go, so there is no single result to
# print as JSON. train is refused except --dry-run (see below).
JSON_REFUSING_COMMANDS = (
    "train", "sleep", "export-gguf", "requant", "pull-weights",
    "distill", "chat",
)


def _json_sweep_args(command, tmp_path):
    """Plausible arguments for one command in the --json sweep.
    The seeded home has profile p1 with project proj."""
    dest = str(tmp_path / "exports")
    return {
        "profiles": [],
        "projects": ["p1"],
        "export": ["p1", "proj", dest],
        "export-profile": ["p1", dest],
        "export-recipe": ["p1", "proj", dest],
        "export-adapter": ["p1", "proj", dest],
        "import": [dest],
        "import-adapter": [dest],
        "pull-weights": ["org/name"],
        "verify": [dest],
        "create-profile": ["sweep-new", "--tag", "x:1b"],
        "create-project": ["p1", "sweep-proj"],
        "train": ["p1", "proj", "--dry-run"],
        "export-gguf": ["p1", "proj", dest],
        "sleep": ["p1", "proj"],
        "sleep-status": ["p1", "proj"],
        "sleep-delete": ["p1", "proj", "1"],
        "sleep-prune": ["p1", "proj"],
        "chat": ["--model", "x:1b"],
        "requant": ["x:1b"],
        "bridge": ["lfm3:1.7b"],
        "pc-info": [],
        "distill": [
            "p1", "proj", "--teacher", "x:1b",
            "--prompts", str(tmp_path / "prompts.txt"),
        ],
        "doctor": ["--check"],
        "rename-profile": ["p1", "p1-renamed"],
        "delete-profile": ["p1"],
        "update-profile": ["p1", "--role", "fast"],
        "show-profile": ["p1"],
        "rename-project": ["p1", "proj", "proj-2"],
        "delete-project": ["p1", "proj"],
        "update-project": ["p1", "proj", "--rank", "4"],
        "show-project": ["p1", "proj"],
        "clone-profile": ["p1", "p1-clone"],
        "clone-project": ["p1", "proj", "proj-clone"],
        "delete-checkpoint": ["p1", "proj", "1"],
        "prune-checkpoints": ["p1", "proj"],
        "list-keys": [],
        "remove-key": ["groq"],
        "mark-ready": ["p1", "proj"],
        "notes": ["p1", "proj"],
        "probe-results": ["p1", "proj"],
        "howto": [],
        "debug-report": [],
    }[command]


@pytest.mark.parametrize(
    "command",
    [c for c in ALL_COMMANDS if c not in ("probe", "save-key")],
)
def test_json_sweep_no_command_silently_returns_text(
    home, tmp_path, command
):
    """R52: every command with --json either prints one JSON
    document on stdout, prints nothing on stdout (an error went
    to stderr, or the flag was refused), or fails — never plain
    text with a success code. probe is excluded here because a
    real probe loads models; its --json form is pinned
    in-process by test_json_probe_parses in test_v22.py.
    save-key is excluded because it reads a key from stdin; its
    --json form is pinned by test_cli_key_round_trip."""
    _seed_cli_home(home)
    (tmp_path / "exports").mkdir()
    args = _json_sweep_args(command, tmp_path)
    res = run_cli(home, command, *args, "--json")
    if res.stdout.strip():
        # Non-empty stdout must parse as one JSON document.
        json.loads(res.stdout)
    if command in JSON_REFUSING_COMMANDS and command != "train":
        assert res.returncode == 1
        assert "--json is not available" in res.stderr
        assert res.stdout == ""


@pytest.mark.parametrize("command", JSON_REFUSING_COMMANDS)
def test_json_refusal_names_the_command(home, tmp_path, command):
    """R52: each long-running command refuses --json in plain
    words on stderr, exit 1, empty stdout — never plain text
    with exit 0."""
    _seed_cli_home(home)
    args = _json_sweep_args(command, tmp_path)
    if command == "train":
        # A real run refuses; --dry-run is the honouring path.
        args = ["p1", "proj"]
    res = run_cli(home, command, *args, "--json")
    assert res.returncode == 1
    assert res.stdout == ""
    assert f"--json is not available for {command}" in res.stderr
    assert "Run it without --json" in res.stderr or command == "train"


def test_json_train_dry_run_points_at_the_estimate(home):
    """R52: the train refusal names the working alternative — a
    dry run prints its estimate as JSON."""
    _seed_cli_home(home)
    res = run_cli(home, "train", "p1", "proj", "--json")
    assert res.returncode == 1
    assert "--dry-run --json" in res.stderr


def test_json_pc_info_bridge_doctor_parse(home, tmp_path):
    """R52: the pure reports honour --json — pc-info, bridge,
    and doctor print one JSON document each."""
    res = run_cli(home, "pc-info", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert "measurement" in data
    assert "settings" in data
    assert data["measurement"]["cpu_count"] >= 1
    assert data["settings"]["rank"] in (4, 8)

    res = run_cli(home, "bridge", "lfm3:1.7b", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["tag"] == "lfm3:1.7b"
    assert isinstance(data["suggestions"], list)

    res = run_cli(home, "doctor", "--check", "--json")
    data = json.loads(res.stdout)
    assert isinstance(data["checks"], list)
    assert isinstance(data["ok"], bool)
    # The exit code carries the verdict, as in the human form.
    assert res.returncode == (0 if data["ok"] else 1)
    assert {c["name"] for c in data["checks"]} >= {
        "venv", "pyside6", "launcher", "symlink", "icon",
    }


def test_json_export_and_import_parse(home, tmp_path):
    """R52: the export commands and import honour --json — one
    document each, no size lines around them."""
    _seed_cli_home(home)
    dest = tmp_path / "exports"
    dest.mkdir()
    res = run_cli(home, "export", "p1", "proj", str(dest), "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["kind"] == "project"
    assert data["size_bytes"] > 0
    assert "Package size" not in res.stdout
    pkg = Path(data["exported"])
    assert pkg.is_dir()

    res = run_cli(
        home, "export-profile", "p1", str(dest), "--json",
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["kind"] == "profile"

    res = run_cli(
        home, "export-recipe", "p1", "proj", str(dest), "--json",
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["kind"] == "recipe"

    res = run_cli(home, "verify", str(pkg), "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["ok"] is True

    # Import it back as a copy: the result is one JSON document.
    res = run_cli(home, "import", str(pkg), "--as-copy", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["project"] == "proj-copy"
    assert data["kind"] == "stella-export"

    res = run_cli(home, "import", str(pkg), "--preview", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["kind"] == "stella-export"


def test_json_create_rename_update_delete_parse(home):
    """R52: the record commands honour --json — create, rename,
    update, and delete print the record (or the action)."""
    res = run_cli(
        home, "create-profile", "p1", "--tag", "x:1b", "--json",
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["name"] == "p1"

    res = run_cli(home, "create-project", "p1", "proj", "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["name"] == "proj"

    res = run_cli(
        home, "update-profile", "p1", "--role", "fast", "--json",
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["role"] == "fast"

    res = run_cli(
        home, "update-project", "p1", "proj", "--rank", "4", "--json",
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["settings"]["rank"] == 4

    res = run_cli(home, "rename-project", "p1", "proj", "proj-2", "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["name"] == "proj-2"

    res = run_cli(home, "delete-project", "p1", "proj-2", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["action"] == "trashed"
    assert data["trash"]

    res = run_cli(home, "rename-profile", "p1", "p1b", "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["name"] == "p1b"

    res = run_cli(home, "delete-profile", "p1b", "--purge", "--yes", "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["action"] == "purged"


def test_json_train_dry_run_parses(home, tmp_path):
    """R52: train --dry-run --json prints the estimate as one
    JSON document — no dataset line ahead of it. The local model
    dir + sample dataset mirror the T85 dry-run test, so no
    network is needed for the estimate."""
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({
        "hidden_size": 2048, "num_hidden_layers": 24,
        "intermediate_size": 8192, "torch_dtype": "bfloat16",
    }))
    (model_dir / "model.safetensors.index.json").write_text(json.dumps({
        "metadata": {"total_size": 3_460_000_000},
    }))
    run_cli(home, "create-profile", "p1", "--base", str(model_dir))
    run_cli(
        home, "create-project", "p1", "proj",
        "--dataset", "sample-tool-calls.jsonl",
    )
    res = run_cli(home, "train", "p1", "proj", "--dry-run", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert "fits" in data
    assert "Dataset:" not in res.stdout


# -- v0.27.0: R53 — no "0 bytes" line before a failed export ------


@pytest.mark.parametrize(
    "command, args",
    [
        ("export", ["nope", "proj", "out"]),
        ("export", ["p1", "nope", "out"]),
        ("export-profile", ["nope", "out"]),
        ("export-recipe", ["nope", "proj", "out"]),
        ("export-recipe", ["p1", "nope", "out"]),
        ("export-adapter", ["nope", "proj", "out"]),
        ("export-adapter", ["p1", "nope", "out"]),
    ],
)
def test_failed_export_prints_no_size_line(home, tmp_path, command, args):
    """R53: a failed export prints only the error — no
    "Package size: about 0 bytes." line ahead of it."""
    _seed_cli_home(home)
    out = tmp_path / "out"
    args = [str(out) if a == "out" else a for a in args]
    res = run_cli(home, command, *args)
    assert res.returncode == 1
    assert "Package size" not in res.stdout
    assert res.stdout == ""
    assert "stella:" in res.stderr


def test_successful_export_still_prints_sizes(home, tmp_path):
    """R53, the other side: a successful export still prints the
    before/after size lines (T178)."""
    _seed_cli_home(home)
    dest = tmp_path / "exports"
    dest.mkdir()
    res = run_cli(home, "export", "p1", "proj", str(dest))
    assert res.returncode == 0, res.stderr
    assert res.stdout.count("Package size") == 2
    assert "about 0 bytes" not in res.stdout


# -- v0.27.0: R54 — chat errors on stderr, CLI keys ---------------


def test_cli_chat_preflight_failures_go_to_stderr(
    home, monkeypatch, capsys
):
    """R54: all four chat pre-flight failures print to stderr
    with empty stdout — never to stdout."""
    import stella.cli as cli_mod
    import stella.ollama as ollama_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    # 1. Custom with no model and no saved config.
    assert cli_mod.main(["chat", "--provider", "custom"]) == 1
    err = capsys.readouterr()
    assert err.out == ""
    assert "Custom provider needs a model name" in err.err
    # 2. Groq with no key saved.
    assert cli_mod.main(["chat", "--provider", "groq"]) == 1
    err = capsys.readouterr()
    assert err.out == ""
    assert "No Groq key saved yet" in err.err
    assert "stella save-key groq" in err.err
    # 3. Ollama not answering (no models, no --model).
    monkeypatch.setattr(ollama_mod, "list_models", lambda: [])
    assert cli_mod.main(["chat"]) == 1
    err = capsys.readouterr()
    assert err.out == ""
    assert "Ollama is not answering" in err.err
    # 4. A typed model name that is not installed.
    import builtins

    monkeypatch.setattr(ollama_mod, "list_models", lambda: ["a:1b"])
    monkeypatch.setattr(
        builtins, "input", lambda _prompt="": "no-such-model"
    )
    assert cli_mod.main(["chat"]) == 1
    err = capsys.readouterr()
    assert "No model called 'no-such-model'" in err.err
    # The model list itself still prints on stdout — it is the
    # question, not an error.
    assert "a:1b" in err.out


def _run_cli_input(home, text, *args):
    """run_cli with text on stdin (for save-key)."""
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True,
        input=text, timeout=60,
    )


def test_cli_key_round_trip(home):
    """R54: a provider key can be saved, listed, and removed from
    the CLI — the same 0600 providers.json the Settings window
    writes, and the key itself never appears in any output."""
    import stat

    key = "gsk_test_key_for_the_cli_round_trip_0123456789"
    res = _run_cli_input(home, key + "\n", "save-key", "groq")
    assert res.returncode == 0, res.stderr
    assert "Saved the Groq key." in res.stdout
    assert key not in res.stdout
    assert key not in res.stderr
    path = Path(home) / "providers.json"
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["groq"]["api_key"] == key

    res = run_cli(home, "list-keys")
    assert res.returncode == 0
    assert "Groq: key saved." in res.stdout
    assert "Gemini: no key." in res.stdout
    assert key not in res.stdout

    res = run_cli(home, "list-keys", "--json")
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["groq"] == "key saved"
    assert data["gemini"] == "no key"
    assert key not in res.stdout

    # R52: save-key honours --json too — one document, and the
    # key itself is never in it.
    res = _run_cli_input(
        home, "gsk_second_key_0123456789\n", "save-key", "gemini",
        "--json",
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data == {"provider": "gemini", "saved": True}
    assert "gsk_second_key" not in res.stdout
    run_cli(home, "remove-key", "gemini")

    res = run_cli(home, "remove-key", "groq")
    assert res.returncode == 0
    assert "Removed the Groq key." in res.stdout
    res = run_cli(home, "list-keys")
    assert "Groq: no key." in res.stdout
    res = run_cli(home, "remove-key", "groq")
    assert res.returncode == 0
    assert "No Groq key was saved." in res.stdout


def test_cli_save_key_custom_with_base_url_and_model(home):
    """R54: save-key custom stores the base URL and model name
    alongside the key."""
    res = _run_cli_input(
        home, "custom-key-123\n", "save-key", "custom",
        "--base-url", "https://example.com/v1",
        "--model", "my-model",
    )
    assert res.returncode == 0, res.stderr
    assert "Saved the Custom key." in res.stdout
    data = json.loads((Path(home) / "providers.json").read_text())
    assert data["custom"]["api_key"] == "custom-key-123"
    assert data["custom"]["base_url"] == "https://example.com/v1"
    assert data["custom"]["model"] == "my-model"


def test_cli_save_key_refusals(home):
    """R54: save-key refuses Ollama (no key needed), an unknown
    provider, and an empty key — each in plain words."""
    res = _run_cli_input(home, "x\n", "save-key", "ollama")
    assert res.returncode == 1
    assert "needs no key" in res.stderr
    res = _run_cli_input(home, "x\n", "save-key", "nope")
    assert res.returncode == 1
    assert "no keyed provider called 'nope'" in res.stderr
    res = _run_cli_input(home, "\n", "save-key", "groq")
    assert res.returncode == 1
    assert "paste a key first" in res.stderr
    assert not (Path(home) / "providers.json").exists()


def test_cli_saved_key_unblocks_cloud_chat(home, monkeypatch, capsys):
    """R54: with a key saved from the CLI, cloud chat gets past
    its pre-flight — the terminal path to cloud chat works."""
    import builtins

    import stella.chat_agent as chat_agent_mod
    import stella.cli as cli_mod
    from stella.providers import save_key

    monkeypatch.setenv("STELLA_HOME", str(home))
    save_key(home, "groq", "gsk_test_key_0123456789")

    class FakeAgent:
        def __init__(self, store, model, **kwargs):
            pass

        def reply(self, text):
            return "hi"

    monkeypatch.setattr(chat_agent_mod, "ChatAgent", FakeAgent)
    answers = iter(["/quit"])
    monkeypatch.setattr(builtins, "input", lambda _prompt="": next(answers))
    assert cli_mod.main(["chat", "--provider", "groq"]) == 0
    out = capsys.readouterr().out
    assert "No Groq key saved yet" not in out
    assert "Hi. Tell me what you want to train" in out


# -- v0.27.0: R55 — CLI clone commands ------------------------------


def test_cli_clone_profile_and_project(home):
    """R55: clone-profile and clone-project work from the CLI,
    with the same normalisation echo the create commands use."""
    from stella.model import Store

    _seed_cli_home(home)
    res = run_cli(home, "clone-profile", "p1", "P1-Clone")
    assert res.returncode == 0, res.stderr
    assert "Cloned profile 'p1' as 'p1-clone'" in res.stdout
    assert "(from 'P1-Clone')" in res.stdout
    store = Store(home)
    assert store.get_profile("p1-clone")["role"] == "fast"
    assert store.list_projects("p1-clone") == []

    res = run_cli(
        home, "clone-profile", "p1", "p1-with-projects",
        "--with-projects",
    )
    assert res.returncode == 0, res.stderr
    assert [p["name"] for p in store.list_projects("p1-with-projects")] == [
        "proj"
    ]

    res = run_cli(home, "clone-project", "p1", "proj", "Proj-2")
    assert res.returncode == 0, res.stderr
    assert "Cloned project 'proj' as 'proj-2'" in res.stdout
    assert "(from 'Proj-2')" in res.stdout
    assert store.get_project("p1", "proj-2")["dataset_ref"] == (
        "sample-tool-calls.jsonl"
    )


def test_cli_clone_json_and_errors(home):
    """R55: the clones honour --json, and a missing source or a
    name clash is refused with one clean line."""
    _seed_cli_home(home)
    res = run_cli(
        home, "clone-profile", "p1", "p1-clone", "--json",
    )
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["name"] == "p1-clone"

    res = run_cli(home, "clone-project", "p1", "proj", "proj-2", "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["name"] == "proj-2"

    res = run_cli(home, "clone-profile", "nope", "x")
    assert res.returncode == 1
    assert "stella:" in res.stderr
    res = run_cli(home, "clone-project", "p1", "nope", "x")
    assert res.returncode == 1
    assert "stella:" in res.stderr
    res = run_cli(home, "clone-profile", "p1", "p1-clone")
    assert res.returncode == 1
    assert "already exists" in res.stderr
    res = run_cli(home, "clone-project", "p1", "proj", "proj-2")
    assert res.returncode == 1
    assert "already exists" in res.stderr


def test_cli_clone_profile_names_skipped_projects(home):
    """R55/R40: cloning with --with-projects names a damaged
    project it could not copy instead of silently dropping it."""
    from stella.model import Store

    _seed_cli_home(home)
    store = Store(home)
    store.create_project("p1", "broken")
    manifest = (
        store.project_dir("p1", "broken") / "project.json"
    )
    manifest.write_text("{not json", encoding="utf-8")
    res = run_cli(
        home, "clone-profile", "p1", "p1-clone", "--with-projects",
    )
    assert res.returncode == 0, res.stderr
    assert "Cloned profile 'p1' as 'p1-clone'" in res.stdout
    assert "could not be copied" in res.stdout
    assert "broken" in res.stdout
    assert [p["name"] for p in store.list_projects("p1-clone")] == [
        "proj"
    ]


# -- v0.27.0: R56 — the nameless-profile warning tells the truth ---


def test_cli_profiles_display_name_needs_no_warning(home):
    """R56: a profile with a display name but no name shows its
    display name and gets no warning — the old warning claimed
    it was "shown as (unnamed profile)" when it was not."""
    run_cli(home, "create-profile", "good", "--tag", "x:1b")
    pdir = Path(home) / "profiles" / "nameless"
    (pdir / "projects").mkdir(parents=True)
    (pdir / "profile.json").write_text(
        json.dumps({
            "kind": "profile", "role": "quiet",
            "display_name": "No Name",
        })
    )
    res = run_cli(home, "profiles")
    assert res.returncode == 0
    assert "No Name" in res.stdout
    assert "(unnamed profile)" not in res.stdout
    assert "no name" not in res.stderr
