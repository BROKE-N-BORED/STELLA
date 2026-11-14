"""v0.22.0 tests — the packages/CLI/tree slice (T170, T171, T172,
T173, T174, T180, T181, T184, T185, T186, T187)."""
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

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
    this file stands alone."""
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    win.close()


@pytest.fixture()
def rich_window(qapp, store, settings):
    """The main window on a three-profile store, for the T180/T181
    filter, sort, and multi-select tests: alpha (driver, no
    projects), beta (fast, two projects), gamma (fast, one
    project)."""
    from stella.gui import MainWindow

    store.create_profile(
        "alpha", display_name="Alpha One", role="driver",
        ollama_tag="lfm3:1.7b",
    )
    store.create_profile(
        "beta", display_name="Beta Two", role="fast",
        ollama_tag="lfm3:1.7b",
    )
    store.create_profile(
        "gamma", display_name="Gamma Three", role="fast",
        ollama_tag="lfm3:1.7b",
    )
    store.create_project("beta", "proj-a")
    store.create_project("beta", "proj-b")
    store.create_project("gamma", "proj-c")
    win = MainWindow(store=store, settings=settings)
    win.show()
    qapp.processEvents()
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    win.close()


def _wait_for_job(window, qapp, timeout_ms=20000):
    """Wait until the window's job-card worker finishes."""
    from PySide6.QtTest import QTest

    waited = 0
    while True:
        worker = window._job_worker
        if worker is None or not worker.isRunning():
            break
        QTest.qWait(50)
        waited += 50
        assert waited < timeout_ms, "job did not finish in time"
    qapp.processEvents()


def _select_session(window):
    window.set_session("lfm3-tool", "tool-calls")


def _make_adapter(store, profile, project, rank=8):
    """A fake trained adapter in the project dir."""
    adapter = store.project_dir(profile, project) / "adapter"
    adapter.mkdir(exist_ok=True)
    (adapter / "adapter_config.json").write_text(
        json.dumps({"r": rank, "lora_alpha": 16})
    )
    (adapter / "adapter_model.safetensors").write_bytes(b"fake-weights")
    return adapter


def _top_order(window):
    return [
        window.tree.topLevelItem(i).data(0, 256)[0]
        for i in range(window.tree.topLevelItemCount())
    ]


def _visible_tops(window):
    return [
        window.tree.topLevelItem(i).data(0, 256)[0]
        for i in range(window.tree.topLevelItemCount())
        if not window.tree.topLevelItem(i).isHidden()
    ]


# -- T170: recipe export/import -------------------------------------


def test_recipe_round_trip(seeded, tmp_path):
    """T170: a recipe round-trips the settings, notes, and
    metamorph mode — and carries no weights."""
    import stella.export as export_mod
    from stella.model import Store

    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_recipe(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    assert pkg.name == "tool-calls-stella-recipe-export"
    assert not (pkg / "weights").exists()
    assert not (pkg / "checkpoints").exists()
    assert not (pkg / "probe_results.json").exists()
    manifest = json.loads((pkg / "manifest.json").read_text())
    assert manifest["kind"] == "stella-recipe-export"
    fresh = Store(tmp_path / "fresh")
    result = export_mod.import_export(fresh, pkg)
    assert result["project"] == "tool-calls"
    proj = fresh.get_project("lfm3-tool", "tool-calls")
    assert proj["settings"] == seeded.get_project(
        "lfm3-tool", "tool-calls"
    )["settings"]
    assert proj["dataset_ref"] == "forge-traces.jsonl"
    assert fresh.read_notes("lfm3-tool", "tool-calls") == (
        seeded.read_notes("lfm3-tool", "tool-calls")
    )


def test_recipe_missing_dataset_warns(seeded, tmp_path):
    """T170: a recipe whose dataset is not on the importing PC
    warns at import — and still imports."""
    import stella.export as export_mod
    from stella.model import Store

    seeded.update_project(
        "lfm3-tool", "tool-calls",
        dataset_ref=str(tmp_path / "not-here.jsonl"),
    )
    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_recipe(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    fresh = Store(tmp_path / "fresh")
    result = export_mod.import_export(fresh, pkg)
    assert result["project"] == "tool-calls"
    assert result["dataset_missing"] is True
    assert any(
        "not on this PC" in w for w in result.get("warnings", [])
    )


def test_recipe_export_has_no_weights_or_checkpoints(seeded, tmp_path):
    """T170: even a trained project exports a recipe with no
    weights and no checkpoints."""
    import stella.export as export_mod

    _make_adapter(seeded, "lfm3-tool", "tool-calls")
    ckpt = seeded.project_dir("lfm3-tool", "tool-calls") / "checkpoints"
    ckpt.mkdir(exist_ok=True)
    (ckpt / "checkpoint-10").mkdir(exist_ok=True)
    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_recipe(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    names = {p.name for p in pkg.iterdir()}
    assert "weights" not in names
    assert "checkpoints" not in names
    assert "manifest.json" in names
    assert "README.md" in names


# -- T171: single-file packages -------------------------------------


def _export_zip(seeded, tmp_path, kind):
    """Export one package of the given kind as a .stella zip."""
    import stella.export as export_mod

    dest = tmp_path / "exports"
    dest.mkdir(exist_ok=True)
    if kind == "project":
        return export_mod.export_project(
            seeded, "lfm3-tool", "tool-calls", dest, as_zip=True
        )
    if kind == "profile":
        return export_mod.export_profile(
            seeded, "lfm3-tool", dest, include_projects=True,
            as_zip=True,
        )
    if kind == "recipe":
        return export_mod.export_recipe(
            seeded, "lfm3-tool", "tool-calls", dest, as_zip=True
        )
    if kind == "adapter":
        _make_adapter(seeded, "lfm3-tool", "tool-calls")
        return export_mod.export_adapter(
            seeded, "lfm3-tool", "tool-calls", dest, as_zip=True
        )
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["project", "profile", "recipe", "adapter"])
def test_zip_round_trip_per_kind(seeded, tmp_path, kind):
    """T171: every package kind round-trips as a single .stella
    file — the zip holds exactly the folder package."""
    import stella.export as export_mod
    from stella.model import Store

    path = _export_zip(seeded, tmp_path, kind)
    assert path.suffix == ".stella"
    assert path.is_file()
    with zipfile.ZipFile(path) as zf:
        assert "manifest.json" in zf.namelist()
        assert not any(name.startswith("/") for name in zf.namelist())
    fresh = Store(tmp_path / "fresh")
    result = export_mod.import_export(fresh, path)
    if kind == "profile":
        assert result["profile"] == "lfm3-tool"
        assert "tool-calls" in result["projects"]
    else:
        assert result["project"] == "tool-calls"
    if kind == "adapter":
        assert (
            fresh.project_dir("lfm3-tool", "tool-calls")
            / "adapter" / "adapter_model.safetensors"
        ).is_file()


def test_folder_import_unchanged(seeded, tmp_path):
    """T171: folder import still works exactly as before — the
    zip form adds a path, it does not change the folder one."""
    import stella.export as export_mod
    from stella.model import Store

    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_project(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    assert pkg.is_dir()
    fresh = Store(tmp_path / "fresh")
    result = export_mod.import_export(fresh, pkg)
    assert result["project"] == "tool-calls"
    assert fresh.get_project("lfm3-tool", "tool-calls") is not None


def test_verify_check_preview_accept_zips(seeded, tmp_path):
    """T171: verify, check, and preview read a .stella file
    exactly like a folder."""
    import stella.export as export_mod

    path = _export_zip(seeded, tmp_path, "project")
    manifest = export_mod.verify_export(path)
    assert manifest["kind"] == "stella-export"
    report = export_mod.check_export(path)
    assert report["ok"] is True
    summary = export_mod.preview_export(seeded, path)
    assert summary["project"] == "tool-calls"


def test_zip_slip_refused(seeded, tmp_path):
    """T171: a zip whose members escape the package folder is
    refused whole — no partial extract, nothing written."""
    import stella.export as export_mod
    from stella.model import StellaError, Store

    dest = tmp_path / "exports"
    dest.mkdir()
    bad = dest / "evil.stella"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.txt", "escape")
        zf.writestr(
            "manifest.json",
            json.dumps({
                "stella_version": "0.22.0", "format": 1,
                "kind": "stella-export",
                "profile": {"name": "lfm3-tool"},
                "project": {"name": "tool-calls"},
            }),
        )
    fresh = Store(tmp_path / "fresh")
    with pytest.raises(StellaError, match="escape"):
        export_mod.import_export(fresh, bad)
    assert not (dest / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()


# -- T173: adapter library ------------------------------------------


def test_adapter_round_trip(seeded, tmp_path):
    """T173: an adapter export carries the weights and the
    manifest block, and imports as a new project around them."""
    import stella.export as export_mod
    from stella.model import Store

    _make_adapter(seeded, "lfm3-tool", "tool-calls", rank=16)
    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_adapter(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    manifest = json.loads((pkg / "manifest.json").read_text())
    assert manifest["kind"] == "stella-adapter-export"
    assert manifest["adapter"]["rank"] == 16
    assert manifest["adapter"]["base"] in (
        "LiquidAI/LFM3-1.7B", "lfm3:1.7b"
    )
    fresh = Store(tmp_path / "fresh")
    result = export_mod.import_adapter_export(fresh, pkg)
    assert result["project"] == "tool-calls"
    assert result["into_existing"] is False
    proj = fresh.get_project("lfm3-tool", "tool-calls")
    assert proj["status"] == "done"
    assert proj["settings"]["rank"] == 16
    assert (
        fresh.project_dir("lfm3-tool", "tool-calls")
        / "adapter" / "adapter_model.safetensors"
    ).is_file()


def test_adapter_import_into_same_base_project(seeded, tmp_path):
    """T173: an adapter imports into an existing project with
    the same base."""
    import stella.export as export_mod

    _make_adapter(seeded, "lfm3-tool", "tool-calls")
    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_adapter(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    seeded.create_project("lfm3-tool", "other")
    result = export_mod.import_adapter_export(
        seeded, pkg, into_profile="lfm3-tool", into_project="other"
    )
    assert result["into_existing"] is True
    assert result["project"] == "other"
    assert (
        seeded.project_dir("lfm3-tool", "other")
        / "adapter" / "adapter_model.safetensors"
    ).is_file()
    assert seeded.get_project("lfm3-tool", "other")["status"] == "done"


def test_adapter_import_into_new_project(seeded, tmp_path):
    """T173: an adapter imports into a new project created
    around it — and a taken name lands under a copy name."""
    import stella.export as export_mod
    from stella.model import Store

    _make_adapter(seeded, "lfm3-tool", "tool-calls")
    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_adapter(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    fresh = Store(tmp_path / "fresh")
    fresh.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    fresh.create_project("lfm3-tool", "tool-calls")
    result = export_mod.import_adapter_export(fresh, pkg)
    assert result["project"] == "tool-calls-copy"
    assert result.get("copy_of") == "tool-calls"
    assert fresh.get_project(
        "lfm3-tool", "tool-calls-copy"
    )["status"] == "done"


def test_adapter_import_base_mismatch_refuses(seeded, tmp_path):
    """T173: an adapter never lands on a project for another
    base — the import refuses, naming both bases."""
    import stella.export as export_mod
    from stella.model import StellaError

    _make_adapter(seeded, "lfm3-tool", "tool-calls")
    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_adapter(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    seeded.create_profile(
        "qwen", ollama_tag="qwen:4b", base_ref="Qwen/Qwen3-4B"
    )
    seeded.create_project("qwen", "qp")
    with pytest.raises(StellaError, match="base"):
        export_mod.import_adapter_export(
            seeded, pkg, into_profile="qwen", into_project="qp"
        )
    assert not (
        seeded.project_dir("qwen", "qp") / "adapter"
    ).exists()


def test_adapter_import_refuses_when_target_has_adapter(
    seeded, tmp_path
):
    """T173: a target that already has a trained adapter refuses
    the import — remove it first."""
    import stella.export as export_mod
    from stella.model import StellaError

    _make_adapter(seeded, "lfm3-tool", "tool-calls")
    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_adapter(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    seeded.create_project("lfm3-tool", "other")
    _make_adapter(seeded, "lfm3-tool", "other")
    with pytest.raises(StellaError, match="already has"):
        export_mod.import_adapter_export(
            seeded, pkg, into_profile="lfm3-tool",
            into_project="other",
        )


def test_adapter_export_refuses_without_adapter(seeded, tmp_path):
    """T173: exporting an adapter from a project with no trained
    adapter refuses — there is nothing to share."""
    import stella.export as export_mod
    from stella.model import StellaError

    dest = tmp_path / "exports"
    dest.mkdir()
    with pytest.raises(StellaError, match="no trained adapter"):
        export_mod.export_adapter(
            seeded, "lfm3-tool", "tool-calls", dest
        )


# -- T172: machine-readable and quiet output ------------------------


def test_json_profiles_parses(home, seeded):
    """T172: `profiles --json` prints valid JSON — a list of
    profile records, parseable by a script."""
    res = run_cli(home, "profiles", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert isinstance(data, list)
    assert data[0]["name"] == "lfm3-tool"


def test_json_flag_works_before_the_subcommand(home, seeded):
    """T172: the global flags work before the subcommand too —
    `stella --json profiles`, not just `profiles --json`."""
    res = run_cli(home, "--json", "profiles")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data[0]["name"] == "lfm3-tool"


def test_json_projects_parses(home, seeded):
    """T172: `projects --json` prints valid JSON."""
    res = run_cli(home, "projects", "lfm3-tool", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert isinstance(data, list)
    assert data[0]["name"] == "tool-calls"


def test_json_show_profile_and_project_parse(home, seeded):
    """T172: `show-profile` and `show-project` print valid JSON."""
    res = run_cli(home, "show-profile", "lfm3-tool", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["name"] == "lfm3-tool"
    res = run_cli(
        home, "show-project", "lfm3-tool", "tool-calls", "--json"
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["name"] == "tool-calls"


def test_json_verify_parses(home, seeded, tmp_path):
    """T172: `verify --json` prints the whole check report as
    valid JSON."""
    import stella.export as export_mod

    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_project(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    res = run_cli(home, "verify", str(pkg), "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["ok"] is True


def test_json_probe_parses(monkeypatch, seeded, capsys):
    """T172: `probe --json` prints the whole probe result as one
    JSON document (in-process, with a faked probe)."""
    import stella.cli as cli
    import stella.probe as probe_mod

    result = {
        "before": {
            "refusals": 0, "total": 18, "rate": 0.0, "empty": 0,
        },
        "after": {
            "refusals": 0, "total": 18, "rate": 0.0, "empty": 0,
        },
        "delta": 0.0,
        "probe_set": "fast",
        "mode": "informational",
    }
    monkeypatch.setattr(cli, "_store", lambda: seeded)
    monkeypatch.setattr(
        probe_mod, "probe_project", lambda *a, **k: result
    )
    args = SimpleNamespace(
        profile="lfm3-tool", project="tool-calls",
        informational=True, json=True, quiet=False, verbose=False,
    )
    assert cli.cmd_probe(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["probe_set"] == "fast"
    assert data["before"]["total"] == 18


def test_probe_human_form_names_the_set(monkeypatch, seeded, capsys):
    """T174: the human probe form prints which set ran."""
    import stella.cli as cli
    import stella.probe as probe_mod

    result = {
        "before": {
            "refusals": 0, "total": 24, "rate": 0.0, "empty": 0,
        },
        "after": {
            "refusals": 0, "total": 24, "rate": 0.0, "empty": 0,
        },
        "delta": 0.0,
        "probe_set": "driver",
        "mode": "informational",
    }
    monkeypatch.setattr(cli, "_store", lambda: seeded)
    monkeypatch.setattr(
        probe_mod, "probe_project", lambda *a, **k: result
    )
    args = SimpleNamespace(
        profile="lfm3-tool", project="tool-calls",
        informational=True, json=False, quiet=False, verbose=False,
    )
    assert cli.cmd_probe(args) == 0
    out = capsys.readouterr().out
    assert "Probe set: driver (24 prompts)." in out


def _train_args(quiet=False):
    return SimpleNamespace(
        profile="lfm3-tool", project="tool-calls", dataset=None,
        dry_run=False, base=None, target_modules=None, steps=None,
        resume=False, from_checkpoint=None, force=False,
        json=False, quiet=quiet, verbose=False,
    )


def _fake_train(monkeypatch):
    """A fake training run that emits started/step/checkpoint/
    done events, so --quiet can be tested without training."""
    import stella.train as train_mod

    monkeypatch.setattr(
        train_mod, "check_dataset",
        lambda *a, **k: {
            "status": "ok", "count": 10, "format": "jsonl",
            "est_tokens": 100, "tiny": False,
        },
    )

    def fake_train_project(*args, on_event=None, **kwargs):
        on_event({"type": "started", "total_steps": 2, "rank": 8})
        on_event({
            "type": "step", "step": 1, "total_steps": 2,
            "epoch": 1, "loss": 1.0, "lr": 0.0002,
        })
        on_event({"type": "checkpoint", "step": 1})
        on_event({"type": "done", "adapter": "/tmp/adapter"})
        return {
            "status": "done", "final_loss": 1.0,
            "final_val_loss": None, "steps": 2,
            "trainable_params": 1000, "ram_estimate_gb": 4,
        }

    monkeypatch.setattr(
        train_mod, "train_project", fake_train_project
    )


def test_quiet_suppresses_train_steps(monkeypatch, seeded, capsys):
    """T172: `--quiet` silences the per-step and checkpoint lines
    on a train run — the started/done lines still print."""
    import stella.cli as cli

    monkeypatch.setattr(cli, "_store", lambda: seeded)
    _fake_train(monkeypatch)
    assert cli.cmd_train(_train_args(quiet=True)) == 0
    out = capsys.readouterr().out
    assert "step 1/2" not in out
    assert "checkpoint saved" not in out
    assert "Training: 2 steps" in out
    assert "Done. Adapter saved" in out


def test_loud_train_prints_steps(monkeypatch, seeded, capsys):
    """T172: without --quiet, the per-step lines print as
    before."""
    import stella.cli as cli

    monkeypatch.setattr(cli, "_store", lambda: seeded)
    _fake_train(monkeypatch)
    assert cli.cmd_train(_train_args(quiet=False)) == 0
    out = capsys.readouterr().out
    assert "step 1/2" in out
    assert "checkpoint saved: step 1" in out


def test_verbose_shows_traceback(monkeypatch, seeded, capsys):
    """T172: `--verbose` prints the full traceback behind the
    catch-all; without it, the clean one-line error stands."""
    import stella.cli as cli

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_store", boom)
    assert cli.main(["profiles"]) == 1
    err = capsys.readouterr()
    assert "stella: boom" in err.err
    assert "Traceback" not in err.err
    assert cli.main(["--verbose", "profiles"]) == 1
    err = capsys.readouterr()
    assert "stella: boom" in err.err
    assert "Traceback" in err.err
    assert "RuntimeError: boom" in err.err


# -- T184: pull-weights ---------------------------------------------


def test_pull_weights_bad_repo_id(home):
    """T184: a repo id that is not org/name is refused with a
    plain message, exit 1 — no download attempted."""
    res = run_cli(home, "pull-weights", "not-a-repo-id")
    assert res.returncode == 1
    assert "not a Hugging Face repo id" in res.stderr


def test_pull_weights_downloads_with_fake(monkeypatch, capsys):
    """T184: `pull-weights` downloads through provision's
    run_download (faked here — no real network) and says the
    plain words."""
    import stella.cli as cli
    import stella.provision as provision_mod

    monkeypatch.setattr(provision_mod, "hub_available", lambda: True)

    def fake_download(repo, _print=print):
        _print("PROGRESS 100 200")
        _print("DONE /tmp/weights")
        return 0

    monkeypatch.setattr(
        provision_mod, "run_download", fake_download
    )
    args = SimpleNamespace(
        repo="LiquidAI/LFM3-1.7B", json=False, quiet=False,
        verbose=False,
    )
    assert cli.cmd_pull_weights(args) == 0
    out = capsys.readouterr().out
    assert "Pulling weights for LiquidAI/LFM3-1.7B..." in out
    assert "Downloaded to /tmp/weights." in out
    assert "of" in out  # the PROGRESS line, in plain words


def test_pull_weights_quiet_suppresses_progress(monkeypatch, capsys):
    """T172: `--quiet` silences the pull-weights progress lines."""
    import stella.cli as cli
    import stella.provision as provision_mod

    monkeypatch.setattr(provision_mod, "hub_available", lambda: True)
    monkeypatch.setattr(
        provision_mod, "run_download",
        lambda repo, _print=print: (
            _print("PROGRESS 100 200"),
            _print("DONE /tmp/weights"),
            0,
        )[-1],
    )
    args = SimpleNamespace(
        repo="LiquidAI/LFM3-1.7B", json=False, quiet=True,
        verbose=False,
    )
    assert cli.cmd_pull_weights(args) == 0
    out = capsys.readouterr().out
    assert "Downloaded to /tmp/weights." in out
    assert "100 B of 200 B" not in out


def test_install_training_sh_uses_pull_weights():
    """T184: install-training.sh ends with the short command —
    no nested-quote one-liner anywhere in the file."""
    text = (ROOT / "install-training.sh").read_text()
    assert "stella pull-weights LiquidAI/LFM3-1.7B" in text
    assert "snapshot_download" not in text
    assert 'python -c "from huggingface_hub' not in text


# -- T187: small CLI polish -----------------------------------------


def test_create_profile_echoes_normalization(home):
    """T187: creating a profile with a name that normalizes says
    so — the user asked for one name and got another."""
    res = run_cli(home, "create-profile", "UPPER-Case")
    assert res.returncode == 0, res.stderr
    assert "Created profile 'upper-case' (from 'UPPER-Case')" in (
        res.stdout
    )


def test_rename_echoes_normalization(home, seeded):
    """T187: renaming to a name that normalizes says so."""
    res = run_cli(
        home, "rename-profile", "lfm3-tool", "NEW-Name"
    )
    assert res.returncode == 0, res.stderr
    assert "(from 'NEW-Name')" in res.stdout
    assert "'new-name'" in res.stdout


def test_bare_stella_prints_command_list(home):
    """T187: bare `stella` prints the command list and exits 0 —
    not argparse's \"arguments are required\" error."""
    res = run_cli(home)
    assert res.returncode == 0
    assert "usage:" in res.stdout.lower()
    assert "profiles" in res.stdout
    assert "required" not in res.stderr


# NOTE: the version tests moved to test_v23.py (test_version_is_0_23_0,
# test_window_title_carries_version) — the version is 0.23.0 now.


# -- T174: per-role probe sets --------------------------------------


def test_probe_set_files_exist_for_all_roles():
    """T174: every canonical role has a probe set file, and each
    set is non-empty."""
    from stella.model import CANONICAL_ROLES
    from stella.probe import PROBE_SETS_DIR, load_probe_set

    for role in CANONICAL_ROLES:
        assert (PROBE_SETS_DIR / f"{role}.json").is_file(), role
        name, prompts, note = load_probe_set(role)
        assert name == role
        assert len(prompts) >= 12, role
        assert note is None


def test_governing_sets_carry_the_full_battery():
    """T174: the governing seats (driver, reviewer, tester, fast)
    get the full 18-prompt refusal battery plus role-specific
    prompts — 24 in all."""
    from stella.model import GOVERNING_SEATS
    from stella.probe import REFUSAL_PROMPTS, load_probe_set

    for role in GOVERNING_SEATS:
        _name, prompts, _note = load_probe_set(role)
        assert len(prompts) == len(REFUSAL_PROMPTS) + 6, role
        for prompt in REFUSAL_PROMPTS:
            assert prompt in prompts, (role, prompt)
        extras = [p for p in prompts if p not in REFUSAL_PROMPTS]
        assert len(extras) == 6, role


def test_non_governing_sets_are_role_specific():
    """T174: vision, all-rounder, and utility get their own
    12-prompt sets — genuinely different prompts, not copies of
    the default."""
    from stella.probe import REFUSAL_PROMPTS, load_probe_set

    seen = {}
    for role in ("vision", "all-rounder", "utility"):
        _name, prompts, _note = load_probe_set(role)
        assert len(prompts) == 12, role
        assert set(prompts) != set(REFUSAL_PROMPTS)
        assert len(set(prompts)) == 12, role  # no duplicates
        seen[role] = set(prompts)
    assert seen["vision"] != seen["all-rounder"]
    assert seen["vision"] != seen["utility"]
    assert seen["all-rounder"] != seen["utility"]


def test_probe_set_fallback_for_unknown_and_blank_role():
    """T174: a role with no set file (custom or blank) falls
    back to the default set, silently — no note, no error."""
    from stella.probe import (
        DEFAULT_PROBE_SET, REFUSAL_PROMPTS, load_probe_set,
    )

    for role in ("not-a-role", "", "custom-seat"):
        name, prompts, note = load_probe_set(role)
        assert name == DEFAULT_PROBE_SET
        assert prompts == REFUSAL_PROMPTS
        assert note is None


def test_probe_set_invalid_file_falls_back_with_note(
    monkeypatch, tmp_path
):
    """T174: a set file that cannot be read falls back to the
    default set AND says so — a broken file must not fail the
    probe silently."""
    import stella.probe as probe_mod
    from stella.probe import (
        DEFAULT_PROBE_SET, REFUSAL_PROMPTS,
    )

    sets_dir = tmp_path / "probe_sets"
    sets_dir.mkdir()
    (sets_dir / "fast.json").write_text("{ not json")
    monkeypatch.setattr(probe_mod, "PROBE_SETS_DIR", sets_dir)
    name, prompts, note = probe_mod.load_probe_set("fast")
    assert name == DEFAULT_PROBE_SET
    assert prompts == REFUSAL_PROMPTS
    assert note is not None
    assert "fast" in note


def test_probe_project_records_probe_set(tmp_path):
    """T174: the probe results record which set ran — the set
    name lands in probe_results.json."""
    pytest.importorskip("torch", reason="training stack not installed")
    from stella.model import Store
    from stella.probe import REFUSAL_PROMPTS, probe_project

    store = Store(tmp_path / "home")
    store.create_profile(
        "tiny", base_ref="test/tiny-model", role="driver"
    )
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    n_prompts = len(REFUSAL_PROMPTS) + 6

    def loader(base_ref, adapter_dir):
        return object(), object()

    def generate(prompt):
        return "Here is the answer."

    result = probe_project(
        store, "tiny", "proof", _model_loader=loader,
        _generate=generate,
    )
    assert result["probe_set"] == "driver"
    assert result["before"]["total"] == n_prompts
    saved = json.loads(
        (
            store.project_dir("tiny", "proof") / "probe_results.json"
        ).read_text()
    )
    assert saved["probe_set"] == "driver"


# -- T180: search, filter, and sort ---------------------------------


def test_filter_by_text_narrows_live(rich_window, qapp):
    """T180: typing in the filter box narrows the list live —
    matching display name, slug, role, and tag."""
    rich_window.tree_filter.setText("beta")
    qapp.processEvents()
    assert _visible_tops(rich_window) == ["beta"]
    rich_window.tree_filter.setText("fast")
    qapp.processEvents()
    assert _visible_tops(rich_window) == ["beta", "gamma"]
    rich_window.tree_filter.setText("lfm3:1.7b")
    qapp.processEvents()
    assert _visible_tops(rich_window) == ["alpha", "beta", "gamma"]
    rich_window.tree_filter.setText("")
    qapp.processEvents()
    assert _visible_tops(rich_window) == ["alpha", "beta", "gamma"]


def test_filter_by_role(rich_window, qapp):
    """T180: the role filter shows only that role."""
    rich_window.tree_role_filter.setCurrentText("driver")
    qapp.processEvents()
    assert _visible_tops(rich_window) == ["alpha"]
    rich_window.tree_role_filter.setCurrentText("fast")
    qapp.processEvents()
    assert _visible_tops(rich_window) == ["beta", "gamma"]
    rich_window.tree_role_filter.setCurrentText("All roles")
    qapp.processEvents()
    assert _visible_tops(rich_window) == ["alpha", "beta", "gamma"]


def test_sort_name_is_default_and_orders(rich_window, qapp):
    """T180: name sort is the default order — not the old
    filesystem order."""
    assert rich_window.tree_sort.currentText() == "Name"
    assert _top_order(rich_window) == ["alpha", "beta", "gamma"]


def test_sort_by_role(rich_window, qapp):
    """T180: role sort orders by role, ties by name."""
    rich_window.tree_sort.setCurrentText("Role")
    qapp.processEvents()
    assert _top_order(rich_window) == ["alpha", "beta", "gamma"]


def test_sort_by_recently_used(rich_window, qapp):
    """T180: recently-used sort puts the last-used profile first
    and the never-used last."""
    rich_window.store.touch_last_used("gamma")
    rich_window.refresh_tree()
    rich_window.tree_sort.setCurrentText("Recently used")
    qapp.processEvents()
    assert _top_order(rich_window)[0] == "gamma"


def test_sort_by_project_count(rich_window, qapp):
    """T180: project-count sort puts the most-projected profile
    first, ties by name."""
    rich_window.tree_sort.setCurrentText("Project count")
    qapp.processEvents()
    assert _top_order(rich_window) == ["beta", "gamma", "alpha"]


def test_selection_preserved_when_filter_matches(rich_window, qapp):
    """T180: filtering keeps the current selection when the
    selected profile still matches."""
    rich_window.set_session("beta", "proj-a")
    qapp.processEvents()
    rich_window.tree_filter.setText("beta")
    qapp.processEvents()
    current = rich_window.tree.currentItem()
    assert current is not None
    assert current.data(0, 256) == ("beta", "proj-a")
    assert rich_window._current_profile == "beta"
    assert rich_window._current_project == "proj-a"


def test_filter_no_match_says_so(rich_window, qapp):
    """T180: a filter that matches nothing says so, instead of
    looking like an empty store."""
    rich_window.tree_filter.setText("zzz-no-match")
    qapp.processEvents()
    assert _visible_tops(rich_window) == []
    assert rich_window.tree_hint.text() == (
        "No profiles match that filter."
    )
    assert rich_window.tree_hint.isVisible()
    rich_window.tree_filter.setText("")
    qapp.processEvents()
    assert rich_window.tree_hint.text() == ""


# -- T181: bulk operations / multi-select ---------------------------


def test_tree_context_menu_offers_bulk_actions(rich_window, qapp):
    """T181: with several profiles selected, the right-click
    menu offers the bulk actions — delete, export, role change."""
    rich_window.tree.topLevelItem(0).setSelected(True)
    rich_window.tree.topLevelItem(1).setSelected(True)
    menu = rich_window._tree_context_menu(
        rich_window.tree.topLevelItem(0)
    )
    texts = [a.text() for a in menu.actions()]
    assert "Delete 2 selected profiles..." in texts
    assert "Export 2 selected profiles..." in texts
    assert "Change role for 2 selected profiles..." in texts


def test_single_selection_menu_unchanged(rich_window, qapp):
    """T181: a single selection shows Rename only — the
    single-profile behavior is exactly as before."""
    rich_window.tree.topLevelItem(0).setSelected(True)
    menu = rich_window._tree_context_menu(
        rich_window.tree.topLevelItem(0)
    )
    assert [a.text() for a in menu.actions()] == ["Rename"]


def test_single_click_selection_unchanged(rich_window, qapp):
    """T181: single-click selection still sets the session, as
    before multi-select."""
    rich_window.set_session("beta", "proj-a")
    qapp.processEvents()
    assert rich_window._current_profile == "beta"
    assert rich_window._current_project == "proj-a"
    assert rich_window.tree.currentItem() is not None


def test_multi_select_delete(rich_window, monkeypatch, qapp):
    """T181: bulk delete moves every selected profile to the
    trash with ONE confirm naming them all."""
    from PySide6.QtWidgets import QMessageBox

    seen = []

    def fake_exec(self):
        seen.append(self)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    rich_window.tree.topLevelItem(0).setSelected(True)
    rich_window.tree.topLevelItem(1).setSelected(True)
    slugs = rich_window._selected_profiles()
    assert slugs == ["alpha", "beta"]
    rich_window._bulk_delete_profiles(slugs)
    qapp.processEvents()
    assert len(seen) == 1
    assert "2 profiles" in seen[0].text()
    assert "Alpha One" in seen[0].informativeText()
    assert "Beta Two" in seen[0].informativeText()
    names = [p["name"] for p in rich_window.store.list_profiles()]
    assert names == ["gamma"]
    entries = rich_window.store.list_trash()
    assert sorted(e["profile"] for e in entries) == [
        "alpha", "beta",
    ]
    assert "2 profiles" in rich_window.statusBar().currentMessage()


def test_multi_select_delete_cancel_does_nothing(
    rich_window, monkeypatch, qapp
):
    """T181: answering No to the bulk delete leaves everything
    where it was."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.No
    )
    rich_window._bulk_delete_profiles(["alpha", "beta"])
    qapp.processEvents()
    names = [p["name"] for p in rich_window.store.list_profiles()]
    assert names == ["alpha", "beta", "gamma"]


def test_multi_select_export(
    rich_window, tmp_path, monkeypatch, qapp
):
    """T181: bulk export writes one package per selected
    profile, with one include-projects question for all."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog

    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    clicker = QTimer()
    clicker.setInterval(50)

    def click_include():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_include_button"):
            clicker.stop()
            dlg._stella_include_button.click()

    clicker.timeout.connect(click_include)
    clicker.start()
    rich_window._bulk_export_profiles(["alpha", "beta"])
    _wait_for_job(rich_window, qapp)
    clicker.stop()
    for slug in ("alpha", "beta"):
        pkg = dest / f"{slug}-stella-profile-export"
        assert pkg.is_dir(), slug
        manifest = json.loads((pkg / "manifest.json").read_text())
        assert manifest["kind"] == "stella-profile-export"
    beta = json.loads(
        (
            dest / "beta-stella-profile-export" / "manifest.json"
        ).read_text()
    )
    assert [p["name"] for p in beta["projects"]] == [
        "proj-a", "proj-b",
    ]
    assert not (dest / "gamma-stella-profile-export").exists()


def test_multi_select_role_change(rich_window, monkeypatch, qapp):
    """T181: bulk role change applies one picked role to the
    whole selection."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(
        QInputDialog, "getItem",
        lambda *a, **k: ("tester", True),
    )
    rich_window._bulk_change_role(["alpha", "beta"])
    qapp.processEvents()
    assert rich_window.store.get_profile("alpha")["role"] == "tester"
    assert rich_window.store.get_profile("beta")["role"] == "tester"
    assert rich_window.store.get_profile("gamma")["role"] == "fast"
    assert "2 profiles" in rich_window.statusBar().currentMessage()


# -- T170/T173/T174: GUI entry points -------------------------------


def test_recipe_and_adapter_menu_enabled_with_session(
    window, qapp
):
    """T170/T173: Export recipe and Export adapter are enabled
    with a session, and the zip entries too."""
    _select_session(window)
    qapp.processEvents()
    assert window._menu_action_export_recipe.isEnabled()
    assert window._menu_action_export_adapter.isEnabled()
    assert window._menu_action_export_project_zip.isEnabled()
    assert window._menu_action_export_profile_zip.isEnabled()
    assert window._menu_action_import_zip.isEnabled()


def test_adapter_export_warns_without_adapter(
    window, monkeypatch, qapp
):
    """T173: exporting an adapter from a project with no trained
    adapter warns instead of starting a job."""
    from PySide6.QtWidgets import QMessageBox

    seen = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: seen.append(a[-1] if a else ""),
    )
    _select_session(window)
    window.export_adapter()
    qapp.processEvents()
    assert len(seen) == 1
    assert "no trained adapter" in seen[0]
    assert window._job_worker is None or (
        not window._job_worker.isRunning()
    )


def test_probe_results_dialog_shows_set_name(window, qapp):
    """T174: the probe results dialog shows which set ran."""
    from stella.gui import ProbeResultsDialog

    result = {
        "before": {"refusals": 0, "total": 24, "details": []},
        "after": {"refusals": 0, "total": 24, "details": []},
        "delta": 0.0,
        "probe_set": "driver",
        "mode": "informational",
    }
    dialog = ProbeResultsDialog(window, result)
    assert dialog.set_label is not None
    assert dialog.set_label.text() == (
        "Probe set: driver (24 prompts)."
    )


def test_import_preview_dialog_adapter_checkbox(
    window, seeded, tmp_path, qapp
):
    """T173: the import preview offers importing an adapter into
    the current project — unchecked by default, and into_project
    reports the pick."""
    import stella.export as export_mod
    from stella.gui import ImportPreviewDialog

    _make_adapter(seeded, "lfm3-tool", "tool-calls")
    dest = tmp_path / "exports"
    dest.mkdir()
    pkg = export_mod.export_adapter(
        seeded, "lfm3-tool", "tool-calls", dest
    )
    summary = export_mod.preview_export(seeded, pkg)
    assert summary["kind"] == "stella-adapter-export"
    dialog = ImportPreviewDialog(
        window, summary,
        into_option=("lfm3-tool", "tool-calls"),
    )
    assert dialog._into_checkbox is not None
    assert not dialog._into_checkbox.isChecked()
    assert dialog.into_project() is None
    dialog._into_checkbox.setChecked(True)
    assert dialog.into_project() == ("lfm3-tool", "tool-calls")
    plain = ImportPreviewDialog(window, summary)
    assert plain._into_checkbox is None
    assert plain.into_project() is None


# -- T185: desktop-file polish --------------------------------------


def test_generated_desktop_file_fields(tmp_path):
    """T185: the generated launcher carries StartupNotify=true,
    Keywords, and Version=1.0."""
    from stella.install import desktop_entry_text

    text = desktop_entry_text(tmp_path / "stella", "stella")
    fields = dict(
        line.split("=", 1)
        for line in text.splitlines()
        if "=" in line
    )
    assert fields["StartupNotify"] == "true"
    assert fields["Version"] == "1.0"
    assert "fine-tune" in fields["Keywords"]
    assert fields["Type"] == "Application"
    assert fields["Name"] == "Stella"


def test_generated_desktop_file_validates(tmp_path):
    """T185: desktop-file-validate is clean, when the tool is
    available in the sandbox."""
    from stella.install import desktop_entry_text

    validator = shutil.which("desktop-file-validate")
    if validator is None:
        pytest.skip("desktop-file-validate not installed")
    path = tmp_path / "stella.desktop"
    path.write_text(
        desktop_entry_text(tmp_path / "stella", "stella")
    )
    res = subprocess.run(
        [validator, str(path)], capture_output=True, text=True
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_checked_in_install_desktop_fields():
    """T185: the checked-in Install Stella.desktop carries the
    same polish fields."""
    text = (ROOT / "Install Stella.desktop").read_text()
    fields = dict(
        line.split("=", 1)
        for line in text.splitlines()
        if "=" in line
    )
    assert fields["StartupNotify"] == "true"
    assert fields["Version"] == "1.0"
    assert fields["Keywords"]


# -- T186: --help for the scripts -----------------------------------


@pytest.mark.parametrize(
    "script",
    ["install.sh", "install-training.sh", "run.sh"],
)
def test_script_help_exits_zero_without_side_effects(
    script, tmp_path
):
    """T186: each script answers --help with usage and exits 0,
    without installing or running anything."""
    copy = tmp_path / script
    shutil.copy(ROOT / script, copy)
    res = subprocess.run(
        ["bash", str(copy), "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    assert "Usage:" in res.stdout
    assert script in res.stdout
    # No side effects: nothing else appeared in the temp dir.
    assert sorted(p.name for p in tmp_path.iterdir()) == [script]


# -- Version --------------------------------------------------------
# (moved to test_v23.py — the version is 0.23.0 now)
