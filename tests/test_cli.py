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
    # Either the deps gate or the base_ref check fires first — both
    # name the fix. The profile has no HF base, so one of them must.
    assert ("base_ref" in res.stderr
            or "install-training.sh" in res.stderr)


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
    run_cli(home, "create-project", "p1", "proj")
    code = cli_mod.main(["train", "p1", "proj"])
    assert code == 1
    assert "install-training.sh" in capsys.readouterr().err


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
    assert "install-training.sh" in capsys.readouterr().err


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


def test_cli_no_command_exit_2(home):
    res = run_cli(home)
    assert res.returncode == 2
    assert "usage:" in res.stderr
    assert "Traceback" not in res.stderr


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


def test_cli_resume_on_trained_announces(home, monkeypatch, capsys):
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
