"""STELLA v0.28.0 tests — P3 batch 1 (R76–R102, minus R92).

Engine half (R76–R91): plain-words OOM, orphan checkpoints,
autoconfig, disk guard, raw-error leaks, export estimate, create
timeout, export cleanup order, quoted Modelfile paths, BOM,
requant collisions, base_ref health, settings_source round-trip,
dead notes key, purge prompts, trash size + auto-purge.
GUI/chat half (R93–R102): un-pickable jobs, Quit + Ctrl+Q,
2.5 s finish moment, no-match search, dataset drag-and-drop,
Shortcuts registry, recorded cap-hit/cancelled replies, "just do
it" anywhere, custom base URL, cloud model buttons.
"""
import io
import json
import os
import shutil
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from stella.model import STELLA_VERSION, StellaError, Store

ROOT = Path(__file__).resolve().parent.parent


def _run_cli_subprocess(home, *args):
    """Run the real `python -m stella.cli` in a subprocess."""
    import subprocess

    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


def test_version_is_0_28_0(home):
    """The version is 0.28.0 everywhere the CLI reports it."""
    assert STELLA_VERSION == "0.28.0"
    res = _run_cli_subprocess(home, "--version")
    assert res.returncode == 0
    assert "0.28.0" in res.stdout


@pytest.fixture()
def window(qapp, seeded, settings):
    """The main window on the seeded store (one profile, one
    project) — the same fixture test_gui.py uses, defined here so
    this file stands alone. Teardown waits for any running job
    before closing, so a worker cannot leak into the next
    test."""
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    from tests.test_gui import _wait_for_all_workers

    _wait_for_all_workers(win, qapp)
    win.close()


def test_window_title_carries_version(window):
    """The window title carries STELLA 0.28.0."""
    assert "0.28.0" in window.windowTitle()


# -- R76: out-of-memory gets a plain-words message --------------------


@pytest.mark.parametrize(
    "exc, is_oom",
    [
        (MemoryError(), True),
        (MemoryError("allocation failed"), True),
        (RuntimeError("CUDA out of memory. Tried to allocate 1.5 GiB"), True),
        (RuntimeError("CPU out of memory"), True),
        (RuntimeError("std::bad_alloc"), True),
        (RuntimeError("cannot allocate memory"), True),
        (RuntimeError("torch.OutOfMemoryError: CUDA out of memory"), True),
        (RuntimeError("something else entirely"), False),
        (ValueError("out of bounds"), False),
        (StellaError("no dataset"), False),
    ],
)
def test_oom_message_plain_words(exc, is_oom):
    from stella.tool_errors import oom_message

    message = oom_message(exc)
    if is_oom:
        assert message is not None
        assert message == (
            "The machine ran out of memory. Close other programs "
            "and try again, or pick a smaller model."
        )
        assert "Traceback" not in message
        assert "CUDA" not in message
    else:
        assert message is None


def _oom_train_setup(tmp_path, monkeypatch):
    """A runnable train_project setup whose loader raises."""
    import stella.train as train_mod
    from test_train import _tiny_project

    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    return store


def test_train_project_oom_loader_plain_words(tmp_path, monkeypatch):
    """R76: a MemoryError from the model loader surfaces as the
    plain-words message, not raw torch text."""
    from stella.train import train_project

    store = _oom_train_setup(tmp_path, monkeypatch)

    def boom():
        raise MemoryError("allocation failed")

    with pytest.raises(StellaError) as exc:
        train_project(store, "tiny", "proof", _model_loader=boom)
    assert "ran out of memory" in str(exc.value)
    assert "Close other programs" in str(exc.value)
    assert "allocation failed" not in str(exc.value)


def test_train_project_torch_oom_text_plain_words(tmp_path, monkeypatch):
    """R76: torch's OutOfMemoryError text (a RuntimeError) is
    translated the same way."""
    from stella.train import train_project

    store = _oom_train_setup(tmp_path, monkeypatch)

    def boom():
        raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")

    with pytest.raises(StellaError) as exc:
        train_project(store, "tiny", "proof", _model_loader=boom)
    assert "ran out of memory" in str(exc.value)
    assert "CUDA" not in str(exc.value)


def test_train_worker_oom_plain_words(qapp, store, monkeypatch):
    """R76: the GUI worker is the last line of defence — an OOM
    raised anywhere in the run shows the plain-words message."""
    import stella.train as train_mod
    from stella.gui import TrainWorker

    def boom(*args, **kwargs):
        raise MemoryError()

    monkeypatch.setattr(train_mod, "train_project", boom)
    seen = []
    worker = TrainWorker(store, "p1", "proj")
    worker.finished.connect(lambda ok, msg: seen.append((ok, msg)))
    worker.run()
    assert len(seen) == 1
    ok, message = seen[0]
    assert ok is False
    assert message.startswith("The machine ran out of memory.")
    assert "Training failed:" not in message


# -- R77: crash-proof checkpoints, orphans, CLI delete/prune --------


class _FakeTorch(types.ModuleType):
    """A torch stand-in with just what _save_checkpoint uses."""

    def save(self, obj, path):
        Path(path).write_bytes(b"optimizer-state")

    def get_rng_state(self):
        return b"rng"


class _FakeModel:
    def __init__(self, fail=False):
        self.fail = fail

    def save_pretrained(self, path):
        out = Path(path)
        out.mkdir(parents=True, exist_ok=True)
        (out / "adapter_config.json").write_text("{}\n")
        if self.fail:
            raise RuntimeError("disk died mid-save")


class _FakeOptimizer:
    def state_dict(self):
        return {}


def _install_fake_torch_for_save(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _FakeTorch("torch"))


def test_save_checkpoint_uses_tmp_and_rename(tmp_path, monkeypatch):
    """R77: a save lands via tmp+rename — the step dir holds all
    three files and no .tmp dir is left behind."""
    from stella.train import _save_checkpoint

    _install_fake_torch_for_save(monkeypatch)
    ckpt = tmp_path / "checkpoints" / "step-5"
    _save_checkpoint(
        _FakeModel(), _FakeOptimizer(), ckpt,
        {"step": 5, "epoch": 1, "examples_seen_in_epoch": 10},
    )
    assert (ckpt / "adapter_config.json").is_file()
    assert (ckpt / "optimizer.pt").is_file()
    assert (ckpt / "training_state.json").is_file()
    assert not (tmp_path / "checkpoints" / "step-5.tmp").exists()


def test_save_checkpoint_crash_leaves_no_orphan(tmp_path, monkeypatch):
    """R77: a crash mid-save leaves no half-written step dir and
    no tmp dir behind — the previous step (if any) is untouched."""
    from stella.train import _save_checkpoint

    _install_fake_torch_for_save(monkeypatch)
    ckpt = tmp_path / "checkpoints" / "step-5"
    with pytest.raises(RuntimeError, match="disk died"):
        _save_checkpoint(
            _FakeModel(fail=True), _FakeOptimizer(), ckpt,
            {"step": 5, "epoch": 1, "examples_seen_in_epoch": 10},
        )
    assert not ckpt.exists()
    assert not (tmp_path / "checkpoints" / "step-5.tmp").exists()


def test_save_checkpoint_replaces_previous_save(tmp_path, monkeypatch):
    """R77: re-saving a step replaces the old dir only once the
    new one is complete."""
    from stella.train import _save_checkpoint

    _install_fake_torch_for_save(monkeypatch)
    ckpt = tmp_path / "checkpoints" / "step-5"
    ckpt.mkdir(parents=True)
    (ckpt / "old-marker.txt").write_text("old")
    _save_checkpoint(
        _FakeModel(), _FakeOptimizer(), ckpt,
        {"step": 5, "epoch": 1, "examples_seen_in_epoch": 10},
    )
    assert not (ckpt / "old-marker.txt").exists()
    assert (ckpt / "training_state.json").is_file()


def _write_checkpoint_dir(ckpt_dir, step, state=True):
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    (ckpt_dir / "adapter_config.json").write_text("{}\n")
    if state:
        (ckpt_dir / "training_state.json").write_text(
            json.dumps({"step": step, "epoch": 1, "loss": 1.5})
        )


def _checkpoint_project(store, tmp_path):
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    return store.project_dir("tiny", "proof") / "checkpoints"


def test_list_orphan_checkpoints(store):
    """R77: step dirs with no readable state file, plus stale
    .tmp dirs, are orphans; good checkpoints are not."""
    from stella.train import list_orphan_checkpoints

    ckpts = _checkpoint_project(store, None)
    _write_checkpoint_dir(ckpts / "step-10", 10)
    _write_checkpoint_dir(ckpts / "step-20", 20, state=False)
    _write_checkpoint_dir(ckpts / "step-30.tmp", 30)
    (ckpts / "step-40").mkdir()
    (ckpts / "step-40" / "training_state.json").write_text("{broken")
    (ckpts / "notes.txt").write_text("not a checkpoint")
    orphans = list_orphan_checkpoints(store, "tiny", "proof")
    assert [o["name"] for o in orphans] == [
        "step-20", "step-30.tmp", "step-40",
    ]
    assert all(o["size_bytes"] >= 0 for o in orphans)


def test_list_checkpoints_skips_tmp_dirs(store):
    """R77: a `.tmp` dir is a save in progress, never listed —
    even once its state file is written."""
    from stella.train import list_checkpoints

    ckpts = _checkpoint_project(store, None)
    _write_checkpoint_dir(ckpts / "step-10", 10)
    _write_checkpoint_dir(ckpts / "step-20.tmp", 20)
    assert [c["step"] for c in list_checkpoints(store, "tiny", "proof")] == [10]


def test_reap_orphan_checkpoints_grace(store):
    """R77: the reaper takes old orphans only — a young one could
    be a live save. force (under the job lock) takes all."""
    import time

    from stella.train import (
        ORPHAN_GRACE_SECONDS,
        list_orphan_checkpoints,
        reap_orphan_checkpoints,
    )

    ckpts = _checkpoint_project(store, None)
    _write_checkpoint_dir(ckpts / "step-10", 10, state=False)
    _write_checkpoint_dir(ckpts / "step-20", 20, state=False)
    old = time.time() - ORPHAN_GRACE_SECONDS - 60
    os.utime(ckpts / "step-10", (old, old))
    result = reap_orphan_checkpoints(store, "tiny", "proof")
    assert result["reaped"] == ["step-10"]
    assert result["skipped"] == ["step-20"]
    assert not (ckpts / "step-10").exists()
    assert (ckpts / "step-20").exists()
    forced = reap_orphan_checkpoints(store, "tiny", "proof", force=True)
    assert forced["reaped"] == ["step-20"]
    assert list_orphan_checkpoints(store, "tiny", "proof") == []


def _cli_args(**kwargs):
    args = SimpleNamespace(json=False, yes=False)
    args.__dict__.update(kwargs)
    return args


def _run_cli_cmd(monkeypatch, home, func, args, stdin=""):
    """Call a cmd_* function in-process with a temp home and a
    canned stdin."""
    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return func(args)


def test_cli_delete_checkpoint_prompts(store, home, monkeypatch, capsys):
    """R77: delete-checkpoint asks first; No keeps it, Yes deletes
    it, --yes skips the prompt, a missing step refuses."""
    from stella.cli import cmd_delete_checkpoint

    ckpts = _checkpoint_project(store, home)
    _write_checkpoint_dir(ckpts / "step-10", 10)
    _write_checkpoint_dir(ckpts / "step-20", 20)
    args = _cli_args(profile="tiny", name="proof", step=10)
    assert _run_cli_cmd(
        monkeypatch, home, cmd_delete_checkpoint, args, stdin="n\n"
    ) == 1
    assert (ckpts / "step-10").is_dir()
    assert _run_cli_cmd(
        monkeypatch, home, cmd_delete_checkpoint, args, stdin="y\n"
    ) == 0
    assert not (ckpts / "step-10").exists()
    assert "Deleted checkpoint step-10" in capsys.readouterr().out
    args = _cli_args(profile="tiny", name="proof", step=20, yes=True)
    assert _run_cli_cmd(monkeypatch, home, cmd_delete_checkpoint, args) == 0
    assert not (ckpts / "step-20").exists()
    args = _cli_args(profile="tiny", name="proof", step=99, yes=True)
    assert _run_cli_cmd(monkeypatch, home, cmd_delete_checkpoint, args) == 1


def test_cli_delete_checkpoint_deletes_orphan(store, home, monkeypatch):
    """R77: an orphan step dir (no state file) is deletable by
    step — orphans are not invisible to the CLI delete."""
    from stella.cli import cmd_delete_checkpoint

    ckpts = _checkpoint_project(store, home)
    _write_checkpoint_dir(ckpts / "step-10", 10, state=False)
    args = _cli_args(profile="tiny", name="proof", step=10, yes=True)
    assert _run_cli_cmd(monkeypatch, home, cmd_delete_checkpoint, args) == 0
    assert not (ckpts / "step-10").exists()


def test_cli_prune_checkpoints(store, home, monkeypatch, capsys):
    """R77: prune-checkpoints keeps the newest N, asks first, and
    cleans up old orphans with it."""
    import time

    from stella.cli import cmd_prune_checkpoints
    from stella.train import ORPHAN_GRACE_SECONDS

    ckpts = _checkpoint_project(store, home)
    for step in (10, 20, 30, 40, 50):
        _write_checkpoint_dir(ckpts / f"step-{step}", step)
    _write_checkpoint_dir(ckpts / "step-60", 60, state=False)
    old = time.time() - ORPHAN_GRACE_SECONDS - 60
    os.utime(ckpts / "step-60", (old, old))
    args = _cli_args(profile="tiny", name="proof", keep=2)
    assert _run_cli_cmd(
        monkeypatch, home, cmd_prune_checkpoints, args, stdin="n\n"
    ) == 1
    assert (ckpts / "step-10").is_dir()
    args = _cli_args(profile="tiny", name="proof", keep=2, yes=True)
    assert _run_cli_cmd(monkeypatch, home, cmd_prune_checkpoints, args) == 0
    assert sorted(d.name for d in ckpts.iterdir()) == ["step-40", "step-50"]
    out = capsys.readouterr().out
    assert "Deleted 3 old checkpoints" in out
    assert "cleaned up 1 unfinished checkpoint folder" in out


# -- R78: autoconfig looks at the model and the machine --------------


def _auto_project(store, rank=8, seq=1024):
    store.create_profile("p1")
    store.create_project("p1", "proj")
    store.update_project(
        "p1", "proj",
        settings={"rank": rank, "max_seq_len": seq},
        settings_source="auto",
    )


def test_refresh_announces_changed_settings(store, tmp_path, monkeypatch):
    """R78: a re-resolve that changes rank/seq says so — a warning
    event and a line in the run log, naming old and new."""
    import stella.train as train_mod

    _auto_project(store)
    monkeypatch.setattr(
        train_mod, "measure_pc",
        lambda home=None: {
            "ram_available_gb": 1.0,
            "disk_free_gb": 50.0,
            "cpu_count": 8,
        },
    )
    events = []
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    settings = train_mod.refresh_auto_settings(
        store, "p1", "proj", on_event=events.append, work_dir=work_dir,
    )
    assert settings["rank"] == 4
    assert settings["max_seq_len"] == 512
    warnings = [e for e in events if e.get("type") == "warning"]
    assert len(warnings) == 1
    assert "rank 8 to 4" in warnings[0]["message"]
    assert "max sequence length 1024 to 512" in warnings[0]["message"]
    log = (work_dir / "train_log.jsonl").read_text()
    assert "rank 8 to 4" in log


def test_refresh_silent_when_unchanged(store, monkeypatch):
    """R78: no change, no announcement."""
    import stella.train as train_mod

    _auto_project(store, rank=4, seq=512)
    monkeypatch.setattr(
        train_mod, "measure_pc",
        lambda home=None: {
            "ram_available_gb": 1.0,
            "disk_free_gb": 50.0,
            "cpu_count": 8,
        },
    )
    events = []
    train_mod.refresh_auto_settings(store, "p1", "proj", on_event=events.append)
    assert events == []


def test_refresh_leaves_manual_alone(store, monkeypatch):
    """R78: a manual project is never re-resolved or announced."""
    import stella.train as train_mod

    store.create_profile("p1")
    store.create_project(
        "p1", "proj", settings={"rank": 16, "max_seq_len": 2048}
    )
    events = []
    settings = train_mod.refresh_auto_settings(
        store, "p1", "proj", on_event=events.append
    )
    assert settings["rank"] == 16
    assert settings["max_seq_len"] == 2048
    assert events == []


def test_refresh_uses_model_size(store, monkeypatch):
    """R78: a 3B+ base shrinks the recipe even with plenty of RAM
    — the model size shapes the re-resolve."""
    import stella.train as train_mod

    _auto_project(store)
    monkeypatch.setattr(
        train_mod, "measure_pc",
        lambda home=None: {
            "ram_available_gb": 16.0,
            "disk_free_gb": 50.0,
            "cpu_count": 8,
        },
    )
    monkeypatch.setattr(train_mod, "_auto_model_params_b", lambda s, p: 3.5)
    settings = train_mod.refresh_auto_settings(store, "p1", "proj")
    assert settings["rank"] == 4
    assert settings["max_seq_len"] == 512


# -- R79: the training path checks free disk --------------------------


def test_check_disk_fit_refuses_when_short():
    """R79: a run that cannot fit refuses in plain words, naming
    the need and what is free."""
    from stella.train import check_disk_fit

    with pytest.raises(StellaError) as exc:
        check_disk_fit(2 * 1024**3, 1024**3)
    message = str(exc.value)
    assert "Not enough free disk to train" in message
    assert "delete old checkpoints" in message
    assert "Traceback" not in message


def test_check_disk_fit_passes_with_room():
    from stella.train import check_disk_fit

    check_disk_fit(1024**3, 10 * 1024**3)


def test_check_disk_fit_never_refuses_unreadable_disk():
    """R79: an unreadable disk is not a reason to refuse — the
    writes themselves fail readably then."""
    from stella.train import check_disk_fit

    check_disk_fit(10 * 1024**3, None)


def test_estimate_run_disk_bytes_counts_checkpoints():
    """R79: the shared disk formula — merged weights plus one
    checkpoint per interval plus the final one plus the adapter."""
    from stella.train import _CHECKPOINT_BYTES_PER_PARAM, estimate_run_disk_bytes

    got = estimate_run_disk_bytes(
        base_bytes=1000, trainable_params=100,
        total_steps=100, checkpoint_steps=50,
    )
    # 100 steps / 50 = 2 intervals + final = 3 checkpoints.
    assert got == 1000 + 3 * 100 * _CHECKPOINT_BYTES_PER_PARAM + 100 * 4
    none = estimate_run_disk_bytes(
        base_bytes=1000, trainable_params=100,
        total_steps=100, checkpoint_steps=0,
    )
    assert none == 1000 + 100 * _CHECKPOINT_BYTES_PER_PARAM + 100 * 4


def test_train_project_refuses_on_full_disk(tmp_path, monkeypatch):
    """R79: a training run refuses to start when the disk cannot
    hold it — before the model loads."""
    import shutil
    from types import SimpleNamespace

    import stella.train as train_mod
    from stella.train import train_project
    from test_train import _tiny_project

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    monkeypatch.setattr(
        train_mod, "available_ram_bytes", lambda: 8 * 1024**3
    )
    monkeypatch.setattr(
        train_mod, "load_model_metadata",
        lambda ref: {
            "params": 100_000,
            "hidden_size": 64,
            "num_layers": 2,
            "intermediate_size": 128,
            "bytes_per_param": 2,
            "base_bytes": 200_000,
        },
    )
    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda path: SimpleNamespace(total=10**9, used=10**9, free=0),
    )
    with pytest.raises(StellaError, match="Not enough free disk"):
        train_project(store, "tiny", "proof")
    # A refused run never stamps the project training.
    assert store.get_project("tiny", "proof")["status"] == "draft"


# -- R80: no raw library text in the GGUF-path messages ---------------


def test_ollama_generate_hides_raw_error(monkeypatch):
    """R80: a refused connection says what to do, not the errno."""
    import urllib.error
    import urllib.request

    from stella.ollama import generate

    def _boom(req, timeout=None):
        raise urllib.error.URLError(
            ConnectionRefusedError(111, "Connection refused")
        )

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(StellaError) as exc:
        generate("qwen:1b", "hello")
    message = str(exc.value)
    assert message == "Ollama did not answer. Is Ollama running on this PC?"
    assert "111" not in message
    assert "Connection refused" not in message


def test_hf_load_message_generic_fallback():
    """R80: an unclassified load failure gets the generic plain
    words, not the first raw transformers line."""
    from stella.train import _hf_load_message

    message = _hf_load_message(
        "owner/model",
        RuntimeError("transformers.models.llama.modeling_llama blew up"),
    )
    assert "transformers.models.llama" not in message
    assert "Check the name and the network, then try again" in message


def test_hf_load_message_classified_branches_intact():
    """R80: the classified branches are untouched — only the
    fallback changed."""
    from stella.train import _hf_load_message

    assert "no model with that name" in _hf_load_message(
        "owner/model", RuntimeError("404 Repository Not Found")
    )
    assert "the download failed" in _hf_load_message(
        "owner/model", RuntimeError("Connection timed out")
    )


# -- R81: CLI export shows the estimate -------------------------------


def test_cli_export_shows_estimate(home, monkeypatch, capsys):
    """R81: CLI export prints the same estimate the GUI shows,
    before the export starts."""
    import stella.gguf as gguf_mod
    from stella.cli import cmd_export_gguf

    monkeypatch.setenv("STELLA_HOME", str(home))
    monkeypatch.setattr(
        gguf_mod, "estimate_export",
        lambda store, profile, project, quant=None: {
            "merged_bytes": 3 * 1024**3,
            "gguf_bytes": 1024**3,
            "f16_bytes": 3 * 1024**3,
            "disk_bytes": 7 * 1024**3,
            "time_note": "roughly minutes",
            "quant": "Q4_K_M",
            "params": 1_700_000_000,
            "base_bytes": 3 * 1024**3,
        },
    )

    def _fake_export(*args, **kwargs):
        return {
            "merged_hf": "/tmp/merged",
            "quant": "Q4_K_M",
            "gguf": "/tmp/out.gguf",
            "gguf_bytes": 123,
            "modelfile": "/tmp/Modelfile",
            "ollama_create": "ollama create x -f /tmp/Modelfile",
            "ollama_name": "x",
        }

    monkeypatch.setattr(gguf_mod, "export_gguf", _fake_export)
    args = _cli_args(
        profile="p", project="q", dir="/tmp/out", quant="Q4_K_M",
        from_checkpoint=None, from_sleep=None, force=False, create=False,
    )
    assert cmd_export_gguf(args) == 0
    out = capsys.readouterr().out
    assert "Export merges about 3.0 GB" in out
    assert "1.0 GB" in out and "GGUF file" in out
    assert out.index("Export merges") < out.index("Merged HF weights")


# -- R82: create_in_ollama gets a timeout -----------------------------


def _slow_ollama_bin(tmp_path, sleep_seconds=30):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "ollama"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        f"time.sleep({sleep_seconds})\n"
    )
    script.chmod(0o755)
    return bindir


def test_create_in_ollama_times_out(tmp_path, monkeypatch):
    """R82: a hung `ollama create` stops on the timeout with a
    plain-words message."""
    from stella.gguf import create_in_ollama

    bindir = _slow_ollama_bin(tmp_path)
    monkeypatch.setenv(
        "PATH", str(bindir) + os.pathsep + os.environ["PATH"]
    )
    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/x.gguf\n")
    with pytest.raises(StellaError) as exc:
        create_in_ollama("x", modelfile, timeout=0.5)
    assert "ollama create timed out" in str(exc.value)
    assert "Try again" in str(exc.value)


def test_cli_export_create_passes_timeout(home, monkeypatch):
    """R82: the CLI --create call passes the 30-minute timeout."""
    import stella.gguf as gguf_mod
    from stella.cli import cmd_export_gguf

    monkeypatch.setenv("STELLA_HOME", str(home))
    seen = {}

    def _no_estimate(*args, **kwargs):
        raise StellaError("no adapter yet")

    monkeypatch.setattr(gguf_mod, "estimate_export", _no_estimate)
    monkeypatch.setattr(
        gguf_mod, "export_gguf",
        lambda *a, **k: {
            "merged_hf": "/tmp/merged",
            "quant": "Q4_K_M",
            "gguf": "/tmp/out.gguf",
            "gguf_bytes": 123,
            "modelfile": "/tmp/Modelfile",
            "ollama_create": "ollama create x -f /tmp/Modelfile",
            "ollama_name": "x",
        },
    )

    def _fake_create(name, modelfile, **kwargs):
        seen.update(kwargs)
        return "created"

    monkeypatch.setattr(gguf_mod, "create_in_ollama", _fake_create)
    args = _cli_args(
        profile="p", project="q", dir="/tmp/out", quant="Q4_K_M",
        from_checkpoint=None, from_sleep=None, force=False, create=True,
    )
    assert cmd_export_gguf(args) == 0
    assert seen["timeout"] == gguf_mod.SUBPROCESS_TIMEOUT_SECONDS == 1800


# -- R83: export cleanup order and the force gate ---------------------


def _export_store(tmp_path):
    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    return store


def test_export_refuses_gguf_appearing_mid_run(tmp_path, monkeypatch):
    """R83: a GGUF that appears mid-run without --force is refused
    and kept, not silently unlinked."""
    import stella.gguf as gguf_mod
    from stella.gguf import export_gguf
    from test_gguf import FakeRunner

    store = _export_store(tmp_path)
    out = tmp_path / "out"
    gguf_path = out / "proof-q4-k-m.gguf"

    def _planting_merge(base_ref, adapter_dir, merged_dir, **kwargs):
        merged_dir.mkdir(parents=True, exist_ok=True)
        (merged_dir / "config.json").write_text(
            '{"model_type": "gpt2"}\n'
        )
        # A concurrent export finishing mid-merge.
        gguf_path.write_bytes(b"the other export's file")

    monkeypatch.setattr(gguf_mod, "merge_adapter", _planting_merge)
    with pytest.raises(StellaError, match="appeared while the export"):
        export_gguf(
            store, "tiny", "proof", out,
            _runner=FakeRunner(), _model_loader=lambda *a, **k: (None, None),
        )
    assert gguf_path.read_bytes() == b"the other export's file"


def test_export_force_replaces_midrun_gguf(tmp_path, monkeypatch):
    """R83: with --force, a GGUF that appears mid-run is the
    deliberate overwrite, and the export succeeds."""
    import stella.gguf as gguf_mod
    from stella.gguf import export_gguf
    from test_gguf import FakeRunner

    store = _export_store(tmp_path)
    out = tmp_path / "out"
    gguf_path = out / "proof-q4-k-m.gguf"

    def _planting_merge(base_ref, adapter_dir, merged_dir, **kwargs):
        merged_dir.mkdir(parents=True, exist_ok=True)
        (merged_dir / "config.json").write_text(
            '{"model_type": "gpt2"}\n'
        )
        gguf_path.write_bytes(b"the other export's file")

    monkeypatch.setattr(gguf_mod, "merge_adapter", _planting_merge)
    result = export_gguf(
        store, "tiny", "proof", out, force=True,
        _runner=FakeRunner(), _model_loader=lambda *a, **k: (None, None),
    )
    assert Path(result["gguf"]).read_bytes() == b"GGUF-Q4_K_M-fake"


def test_export_lock_time_recheck_refuses_before_merge(tmp_path, monkeypatch):
    """R83: a GGUF that appears between the pre-flight check and
    the lock is refused before the merge wastes minutes."""
    import stella.gguf as gguf_mod
    from stella.gguf import export_gguf
    from test_gguf import FakeRunner

    store = _export_store(tmp_path)
    out = tmp_path / "out"
    gguf_path = out / "proof-q4-k-m.gguf"
    real_lock = gguf_mod.job_lock

    def _planting_lock(*args, **kwargs):
        gguf_path.write_bytes(b"the other export's file")
        return real_lock(*args, **kwargs)

    monkeypatch.setattr(gguf_mod, "job_lock", _planting_lock)
    ran = []

    def _recording_merge(base_ref, adapter_dir, merged_dir, **kwargs):
        ran.append(True)

    monkeypatch.setattr(gguf_mod, "merge_adapter", _recording_merge)
    with pytest.raises(StellaError, match="appeared while the export"):
        export_gguf(
            store, "tiny", "proof", out,
            _runner=FakeRunner(), _model_loader=lambda *a, **k: (None, None),
        )
    assert ran == []  # the merge never started
    assert gguf_path.read_bytes() == b"the other export's file"


def test_export_refusal_keeps_stale_merged_dir(tmp_path, monkeypatch):
    """R83: a refused export no longer deletes the stale merged
    dir — the cleanup lives inside the lock now."""
    import shutil
    from types import SimpleNamespace

    import stella.gguf as gguf_mod
    import stella.train as train_mod
    from stella.gguf import export_gguf
    from test_gguf import FakeRunner

    store = _export_store(tmp_path)
    out = tmp_path / "out"
    merged = out / "proof-merged-hf"
    merged.mkdir(parents=True)
    (merged / "marker.txt").write_text("stale but precious")
    monkeypatch.setattr(
        train_mod, "load_model_metadata",
        lambda ref: {
            "params": 10**9,
            "base_bytes": 2 * 1024**3,
            "architectures": ["LlamaForCausalLM"],
            "hidden_size": 2048,
            "num_layers": 24,
            "intermediate_size": 8192,
            "bytes_per_param": 2,
        },
    )
    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda path: SimpleNamespace(total=10**9, used=10**9, free=0),
    )
    with pytest.raises(StellaError, match="Not enough free disk"):
        export_gguf(store, "tiny", "proof", out, _runner=FakeRunner())
    assert (merged / "marker.txt").read_text() == "stale but precious"


# -- R84: the --modelfile fallback handles quoted spaced paths --------


def test_modelfile_blob_quoted_spaced_path(tmp_path, monkeypatch):
    """R84: a quoted FROM path with spaces resolves — the quotes
    are stripped, not carried into the path."""
    from stella.requant import _modelfile_blob
    from test_requant import fake_ollama_bin

    spaced = tmp_path / "model dir" / "my model.gguf"
    spaced.parent.mkdir()
    spaced.write_bytes(b"GGUF-fake")
    bindir = fake_ollama_bin(tmp_path, show_from=f'"{spaced}"')
    monkeypatch.setenv(
        "PATH", str(bindir) + os.pathsep + os.environ["PATH"]
    )
    assert _modelfile_blob("qwen3.5:4b") == spaced


def test_modelfile_blob_unquoted_spaced_path(tmp_path, monkeypatch):
    """R84: an unquoted spaced path still works — the split was
    never the problem."""
    from stella.requant import _modelfile_blob
    from test_requant import fake_ollama_bin

    spaced = tmp_path / "model dir" / "my model.gguf"
    spaced.parent.mkdir()
    spaced.write_bytes(b"GGUF-fake")
    bindir = fake_ollama_bin(tmp_path, show_from=str(spaced))
    monkeypatch.setenv(
        "PATH", str(bindir) + os.pathsep + os.environ["PATH"]
    )
    assert _modelfile_blob("qwen3.5:4b") == spaced


# -- R85: prompts are stripped of a byte-order mark -------------------


def test_read_prompts_strips_bom(tmp_path):
    """R85: a BOM'd prompts file reads clean — no invisible
    character at the start of prompt 1."""
    from stella.distill import _read_prompts

    path = tmp_path / "prompts.txt"
    path.write_bytes(
        b"\xef\xbb\xbfWhat is 2+2?\nWrite a haiku.\n"
    )
    assert _read_prompts(path) == ["What is 2+2?", "Write a haiku."]


def test_read_prompts_bomless_unchanged(tmp_path):
    from stella.distill import _read_prompts

    path = tmp_path / "prompts.txt"
    path.write_text("Hello.\nWorld.\n", encoding="utf-8")
    assert _read_prompts(path) == ["Hello.", "World."]


# -- R86: requant work files are unique per job -----------------------


class _CaptureRunner:
    """Pretends to be llama-quantize + `ollama create`, recording
    every command."""

    def __init__(self):
        self.commands = []

    def __call__(self, cmd):
        self.commands.append(list(cmd))
        if "llama-quantize" in cmd[0]:
            pos = [a for a in cmd[1:] if not a.startswith("--")]
            Path(pos[1]).write_bytes(b"GGUF-fake")


def _requant_env(monkeypatch, tmp_path):
    """Fake Ollama models + llama.cpp + ollama on PATH."""
    from test_requant import (
        fake_llama_cpp,
        fake_ollama_bin,
        fake_ollama_models,
    )

    models, blob = fake_ollama_models(tmp_path)
    cpp = fake_llama_cpp(tmp_path)
    bindir = fake_ollama_bin(tmp_path)
    monkeypatch.setenv("LLAMA_CPP_DIR", str(cpp))
    monkeypatch.setenv("OLLAMA_MODELS", str(models))
    monkeypatch.setenv(
        "PATH", str(bindir) + os.pathsep + os.environ["PATH"]
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    return models


def test_requant_uses_unique_job_dir_per_run(tmp_path, monkeypatch):
    """R86: two requants of the same tag never share a work-file
    name — each run gets its own job dir, for the GGUF and the
    Modelfile alike."""
    from stella.requant import requant_model

    models = _requant_env(monkeypatch, tmp_path)
    work = tmp_path / "work"
    runners = []
    for _ in range(2):
        runner = _CaptureRunner()
        runners.append(runner)
        requant_model(
            "qwen3.5:4b",
            work_dir=work, _runner=runner, _models_dir=models,
        )
    quant_cmds = [r.commands[0] for r in runners]
    create_cmds = [r.commands[1] for r in runners]
    out_paths = [
        Path([a for a in cmd[1:] if not a.startswith("--")][1])
        for cmd in quant_cmds
    ]
    modelfiles = [Path(cmd[cmd.index("-f") + 1]) for cmd in create_cmds]
    assert out_paths[0] != out_paths[1]
    assert modelfiles[0] != modelfiles[1]
    assert out_paths[0].parent != out_paths[1].parent
    # Both job dirs live under the work dir, and both are cleaned
    # up after a successful create.
    assert out_paths[0].parent.parent == work
    assert list(work.iterdir()) == []


# -- R87: base_ref is checked against the actual weights --------------


def _local_model_dir(tmp_path, name="model", with_weights=True):
    d = tmp_path / name
    d.mkdir()
    (d / "config.json").write_text(
        json.dumps({
            "hidden_size": 64,
            "num_hidden_layers": 2,
            "intermediate_size": 128,
            "architectures": ["LlamaForCausalLM"],
        })
    )
    if with_weights:
        (d / "model.safetensors").write_bytes(b"weights")
    return d


@pytest.mark.parametrize(
    "ref, warned",
    [
        ("", False),
        ("lfm3:1.7b", True),  # an Ollama tag, not weights
        ("qwen3.5", True),  # a bare tag
        ("/tmp/model.gguf", True),  # a GGUF file
        ("LiquidAI/LFM3-1.7B", False),  # well-shaped, uncached: no guess
        ("owner/model", False),
        ("not a repo", True),  # not shaped like owner/model
        ("owner/", True),
        ("a/b/c", True),
    ],
)
def test_base_ref_warnings_text_refs(ref, warned):
    """R87: tags, GGUF files, and malformed ids warn; a
    well-shaped repo id never warns on a guess."""
    from stella.train import base_ref_warnings

    warnings = base_ref_warnings(ref)
    assert bool(warnings) is warned
    if warned:
        assert "Training needs" in warnings[0] or "does not look like" in warnings[0]


def test_base_ref_warnings_local_folder(tmp_path):
    """R87: a local folder with no model warns; one that holds a
    model does not."""
    from stella.train import base_ref_warnings

    empty = tmp_path / "empty"
    empty.mkdir()
    assert base_ref_warnings(str(empty))
    assert "does not hold a model" in base_ref_warnings(str(empty))[0]
    good = _local_model_dir(tmp_path)
    assert base_ref_warnings(str(good)) == []
    no_weights = _local_model_dir(tmp_path, "bare", with_weights=False)
    assert base_ref_warnings(str(no_weights))


def test_cli_create_profile_warns_on_tag_base(home, monkeypatch, capsys):
    """R87: creating a profile with a tag as --base warns in plain
    words — and still creates it (a warning, never a refusal)."""
    from stella.cli import cmd_create_profile

    monkeypatch.setenv("STELLA_HOME", str(home))
    args = _cli_args(
        name="p1", tag="", role="fast", display="", base="lfm3:1.7b",
    )
    assert cmd_create_profile(args) == 0
    out = capsys.readouterr().out
    assert "Created profile 'p1'" in out
    assert "Warning: 'lfm3:1.7b' is an Ollama tag" in out
    assert Store(home).get_profile("p1")["base_ref"] == "lfm3:1.7b"


def test_import_warns_on_bad_base_ref(seeded, tmp_path):
    """R87: importing a package whose base ref is a local folder
    with no model warns — the import still lands. (A tag-valued
    base stays silent at import: it is the store's synced
    default, not a mistake.)"""
    from stella import export as export_mod

    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    empty = tmp_path / "no-model-here"
    empty.mkdir()
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["profile"]["base_ref"] = str(empty)
    manifest_path.write_text(json.dumps(manifest))
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert any("does not hold a model" in w for w in result["warnings"])
    assert fresh.get_profile("lfm3-tool")["base_ref"] == str(empty)


def test_import_silent_on_tag_base_ref(seeded, tmp_path):
    """R87: a tag-valued base ref is the synced default (T54) —
    importing one warns about nothing."""
    from stella import export as export_mod

    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["profile"]["base_ref"] = "lfm3:1.7b"
    manifest_path.write_text(json.dumps(manifest))
    fresh = Store(tmp_path / "fresh-home")
    result = export_mod.import_export(fresh, out)
    assert not any("Ollama tag" in w for w in result["warnings"])


# -- R88: settings_source survives the round-trip ---------------------


def test_manifest_carries_settings_source(seeded, tmp_path):
    """R88: the manifest block carries the settings source."""
    from stella import export as export_mod

    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["project"]["settings_source"] == "auto"


def test_create_project_settings_source_auto_reresolves(store):
    """R88: restoring an auto project re-resolves for this PC
    instead of freezing the source PC's values."""
    from stella.autoconfig import compute_settings, measure_pc

    store.create_profile("p1")
    data = store.create_project(
        "p1", "proj",
        settings={"rank": 16, "max_seq_len": 2048},
        settings_source="auto",
    )
    assert data["settings_source"] == "auto"
    measurement = measure_pc(store.home)
    expected = compute_settings(
        measurement["ram_available_gb"],
        disk_free_gb=measurement["disk_free_gb"],
        cpu_count=measurement["cpu_count"],
    )
    assert data["settings"]["rank"] == expected["rank"]
    assert data["settings"]["max_seq_len"] == expected["max_seq_len"]


def test_create_project_settings_source_manual_keeps(store):
    """R88: restoring a manual project keeps the passed values."""
    store.create_profile("p1")
    data = store.create_project(
        "p1", "proj",
        settings={"rank": 16, "max_seq_len": 2048},
        settings_source="manual",
    )
    assert data["settings_source"] == "manual"
    assert data["settings"]["rank"] == 16
    assert data["settings"]["max_seq_len"] == 2048


def test_create_project_bad_settings_source_refused(store):
    store.create_profile("p1")
    with pytest.raises(StellaError, match="settings source must be"):
        store.create_project(
            "p1", "proj", settings={}, settings_source="banana"
        )


def test_export_import_keeps_auto(seeded, tmp_path):
    """R88: an auto project stays auto after an export/import
    round-trip."""
    from stella import export as export_mod

    assert seeded.get_project("lfm3-tool", "tool-calls")[
        "settings_source"
    ] == "auto"
    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    fresh = Store(tmp_path / "fresh-home")
    export_mod.import_export(fresh, out)
    assert fresh.get_project("lfm3-tool", "tool-calls")[
        "settings_source"
    ] == "auto"


def test_import_old_package_without_source_is_manual(seeded, tmp_path):
    """R88: a package that predates the field imports as manual —
    today's behaviour, never auto."""
    from stella import export as export_mod

    out = export_mod.export_project(seeded, "lfm3-tool", "tool-calls", tmp_path)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["project"]["settings_source"]
    manifest_path.write_text(json.dumps(manifest))
    fresh = Store(tmp_path / "fresh-home")
    export_mod.import_export(fresh, out)
    assert fresh.get_project("lfm3-tool", "tool-calls")[
        "settings_source"
    ] == "manual"


# -- R89: the LFM3 template has no dead notes key ---------------------


def test_lfm3_template_has_no_notes_key():
    """R89: the dead settings["notes"] key is gone from the
    template."""
    from stella import templates as templates_mod

    template = templates_mod.load_template("lfm3-tool-format")
    assert "notes" not in template["settings"]


def test_no_template_carries_dropped_settings_keys():
    """R89: no template carries a settings key that
    validate_settings drops — the next dead key is caught by the
    suite instead of a review."""
    from stella import templates as templates_mod
    from stella.model import validate_settings

    for template in templates_mod.list_templates():
        settings = template["settings"]
        kept = validate_settings(dict(settings))
        assert set(kept) == set(settings), template["name"]


# -- R90: CLI --purge asks first --------------------------------------


def test_cli_purge_profile_prompts(store, home, monkeypatch, capsys):
    """R90: --purge asks first (default No); No and EOF keep the
    profile, Yes and --yes purge it."""
    from stella.cli import cmd_delete_profile

    store.create_profile("p1")
    args = _cli_args(name="p1", purge=True)
    assert _run_cli_cmd(
        monkeypatch, home, cmd_delete_profile, args, stdin="n\n"
    ) == 1
    assert store.get_profile("p1") is not None
    assert "Delete profile 'p1' forever?" in capsys.readouterr().err
    assert _run_cli_cmd(
        monkeypatch, home, cmd_delete_profile, args, stdin=""
    ) == 1
    assert store.get_profile("p1") is not None
    assert _run_cli_cmd(
        monkeypatch, home, cmd_delete_profile, args, stdin="y\n"
    ) == 0
    with pytest.raises(StellaError):
        store.get_profile("p1")


def test_cli_purge_profile_yes_skips_prompt(store, home, monkeypatch, capsys):
    """R90: --yes is the escape for scripts — no prompt."""
    from stella.cli import cmd_delete_profile

    store.create_profile("p1")
    args = _cli_args(name="p1", purge=True, yes=True)
    assert _run_cli_cmd(monkeypatch, home, cmd_delete_profile, args) == 0
    assert "forever?" not in capsys.readouterr().err
    with pytest.raises(StellaError):
        store.get_profile("p1")


def test_cli_purge_project_prompts(store, home, monkeypatch):
    """R90: the project purge asks first too."""
    from stella.cli import cmd_delete_project

    store.create_profile("p1")
    store.create_project("p1", "proj")
    args = _cli_args(profile="p1", name="proj", purge=True)
    assert _run_cli_cmd(
        monkeypatch, home, cmd_delete_project, args, stdin="n\n"
    ) == 1
    assert store.get_project("p1", "proj") is not None
    args = _cli_args(profile="p1", name="proj", purge=True, yes=True)
    assert _run_cli_cmd(monkeypatch, home, cmd_delete_project, args) == 0
    with pytest.raises(StellaError):
        store.get_project("p1", "proj")


# -- R91: the trash shows its size and purges old items ---------------


def test_list_trash_shows_size(store):
    """R91: each trashed item carries its disk use, counted from
    the folder."""
    store.create_profile("p1")
    store.create_project("p1", "proj")
    project_dir = store.project_dir("p1", "proj")
    (project_dir / "big.bin").write_bytes(b"x" * 100_000)
    store.delete_project("p1", "proj")
    entries = store.list_trash()
    assert len(entries) == 1
    assert entries[0]["size_bytes"] >= 100_000


def test_purge_old_trash(store):
    """R91: items older than the auto-purge age go; recent ones
    and undated (hand-moved) ones stay."""
    from stella.model import TRASH_AUTO_PURGE_DAYS

    assert TRASH_AUTO_PURGE_DAYS == 30
    store.create_profile("p1")
    for name in ("old", "new"):
        store.create_project("p1", name)
        store.delete_project("p1", name)
    entries = {e["project"]: e for e in store.list_trash()}
    old_path = Path(entries["old"]["path"])
    new_name = old_path.name.rsplit("-", 2)[0] + "-20200101-000000"
    old_path.rename(old_path.parent / new_name)
    undated = store.trash_dir / "hand-moved-folder"
    undated.mkdir()
    (undated / "file.txt").write_text("keep me")
    result = store.purge_old_trash()
    assert result["purged"] == [new_name]
    assert result["freed_bytes"] > 0
    remaining = {e["name"] for e in store.list_trash()}
    assert entries["new"]["name"] in remaining
    assert "hand-moved-folder" in remaining


def test_trash_dialog_shows_size_and_auto_purges(qapp, store):
    """R91: the Trash window shows each item's size and the total,
    names the 30-day age, and purges old items when it opens."""
    from types import SimpleNamespace

    from stella.gui import TrashDialog

    store.create_profile("p1")
    for name in ("old", "new"):
        store.create_project("p1", name)
        (store.project_dir("p1", name) / "big.bin").write_bytes(b"x" * 5000)
        store.delete_project("p1", name)
    entries = {e["project"]: e for e in store.list_trash()}
    old_path = Path(entries["old"]["path"])
    old_path.rename(
        old_path.parent / (old_path.name.rsplit("-", 2)[0] + "-20200101-000000")
    )
    main = SimpleNamespace(store=store)
    dialog = TrashDialog(main)
    try:
        assert dialog.list_widget.count() == 1
        label = dialog.list_widget.item(0).text()
        assert "project new" in label
        assert "KB" in label or "bytes" in label
        summary = dialog.summary_label.text()
        assert "Trash holds" in summary
        assert "30 days" in summary
        assert "1 old item" in summary
        assert "were deleted just now" in summary
        assert store.list_trash()[0]["project"] == "new"
    finally:
        dialog.close()


@pytest.fixture()
def agent(store, monkeypatch):
    """A chat agent with a fake model list, like test_chat_agent's."""
    import stella.chat_agent as chat_mod
    from stella.chat_agent import ChatAgent

    monkeypatch.setattr(
        chat_mod, "list_models", lambda: ["lfm3:1.7b"]
    )
    return ChatAgent(store, "lfm3:1.7b")


def _select_session(window):
    """Pick the seeded project in the tree (sets the session)."""
    window.set_session("lfm3-tool", "tool-calls")


def _drop_event(path):
    """A synthetic drop of one local file, for the R97 tests."""
    from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(
        QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    # The event holds a bare pointer to the mime data: keep it
    # alive on the event, or mimeData() reads freed memory.
    event._mime = mime
    return event


def _valid_jsonl(tmp_path):
    """A real valid dataset file to drop: a copy of the bundled
    sample, so the drop's own check reports it ok."""
    dest = tmp_path / "dropped.jsonl"
    shutil.copy(ROOT / "data" / "sample-tool-calls.jsonl", dest)
    return dest


# -- R93: a picked job can be un-picked ------------------------------


def test_picked_job_can_be_unpicked_and_go_disarms(window, qapp):
    """R93 Done: clicking a picked job again un-picks it, and Go
    disarms — there is a way back from a pick."""
    _select_session(window)
    window._checklist_dismiss()
    train = window.job_buttons["train"]
    assert train.isChecked() is False
    assert window.go_btn.isEnabled() is False
    train.click()
    assert train.isChecked() is True
    assert window.go_btn.isEnabled() is True
    train.click()
    assert train.isChecked() is False
    assert window.go_btn.isEnabled() is False


def test_switching_jobs_keeps_one_pick(window, qapp):
    """R93: the buttons are non-exclusive toggles, but switching
    still works — picking a second job un-picks the first, so at
    most one job is ever picked."""
    _select_session(window)
    window._checklist_dismiss()
    train = window.job_buttons["train"]
    sleep = window.job_buttons["sleep"]
    train.click()
    sleep.click()
    assert train.isChecked() is False
    assert sleep.isChecked() is True
    assert window._picked_job() == "sleep"
    assert window.go_btn.isEnabled() is True


# -- R94: Quit in the File menu, Ctrl+Q ------------------------------


def _file_menu(window):
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is not None and menu.title() == "File":
            return menu
    raise AssertionError("no File menu")


def test_file_menu_has_quit_with_ctrl_q(window):
    """R94 Done: File has Quit, with Ctrl+Q."""
    quit_action = window._menu_action_quit
    assert quit_action.text() == "Quit"
    assert quit_action.shortcut().toString() == "Ctrl+Q"
    assert quit_action in _file_menu(window).actions()


def test_quit_action_closes_window(window, qapp):
    """R94: Quit closes the app, through the window's own close
    path (no job is running, so it closes at once)."""
    assert window.isVisible()
    window._menu_action_quit.trigger()
    qapp.processEvents()
    assert window.isVisible() is False


# -- R95: the finish moment lingers ---------------------------------


def test_finish_moment_lingers_two_and_a_half_seconds(window, qapp):
    """R95 Done: the finish card stays readable for 2–3 s — still
    up a full second in, gone once the linger ends."""
    from PySide6.QtTest import QTest

    from stella.gui import JobCard

    assert JobCard.FINISH_MOMENT_MS == 2500
    window._checklist_dismiss()
    card = window.job_card
    card.start("Training", True)
    card.finish_moment("Trained 4 steps.", reduced_motion=False)
    QTest.qWait(1000)
    assert card.isVisible()
    assert card.status_label.text() == "Trained 4 steps."
    deadline = 0
    while card.isVisible():
        QTest.qWait(100)
        deadline += 100
        assert deadline < 4000
    assert card.isVisible() is False


# -- R96: a no-match search says so ---------------------------------


def test_howto_search_no_match_says_so(window, qapp):
    """R96 Done: a no-match search says so in the pane, and
    clearing it restores the picked topic's body."""
    howto = window.open_howto_window()
    qapp.processEvents()
    howto.search_box.setText("zzzznope")
    qapp.processEvents()
    assert howto.content.toPlainText() == (
        "Nothing matches 'zzzznope'. Try fewer words."
    )
    howto.search_box.clear()
    qapp.processEvents()
    assert "fine-tunes small AI models" in howto.content.toPlainText()
    howto.close()


def test_howto_search_match_leaves_topic_body_alone(window, qapp):
    """R96: a search that matches never clobbers the picked topic's
    body — only the no-match line is written and restored."""
    howto = window.open_howto_window()
    qapp.processEvents()
    from PySide6.QtCore import Qt

    rows = howto.topic_list.findItems("Training", Qt.MatchExactly)
    howto.topic_list.setCurrentRow(howto.topic_list.row(rows[0]))
    qapp.processEvents()
    assert "hours" in howto.content.toPlainText()
    howto.search_box.setText("sleep")
    qapp.processEvents()
    assert "hours" in howto.content.toPlainText()
    howto.search_box.setText("zzzznope")
    qapp.processEvents()
    assert "Nothing matches 'zzzznope'" in howto.content.toPlainText()
    howto.search_box.setText("sleep")
    qapp.processEvents()
    assert "hours" in howto.content.toPlainText()
    howto.close()


# -- R97: drag-and-drop for a dataset file ---------------------------


def test_dropping_jsonl_on_pick_dataset_sets_it(
    window, qapp, seeded, tmp_path
):
    """R97 Done: dropping a .jsonl file onto the dataset picker
    sets the dataset, with the same check as the dialog pick."""
    _select_session(window)
    window._checklist_dismiss()
    path = _valid_jsonl(tmp_path)
    window.train_pick_dataset_btn.dropEvent(_drop_event(path))
    qapp.processEvents()
    assert seeded.get_project("lfm3-tool", "tool-calls")[
        "dataset_ref"
    ] == str(path)
    assert "examples" in window.statusBar().currentMessage()


def test_dropping_txt_on_pick_dataset_refuses(
    window, qapp, seeded, tmp_path, monkeypatch
):
    """R97: a dropped .txt is refused in plain words and sets
    nothing — never a silently broken dataset."""
    _select_session(window)
    window._checklist_dismiss()
    warned = []
    monkeypatch.setattr(window, "_warn", warned.append)
    bad = tmp_path / "notes.txt"
    bad.write_text("not a dataset\n")
    window.train_pick_dataset_btn.dropEvent(_drop_event(bad))
    qapp.processEvents()
    assert warned and "not a .jsonl file" in warned[0]
    assert seeded.get_project("lfm3-tool", "tool-calls")[
        "dataset_ref"
    ] == "forge-traces.jsonl"


def test_dropping_jsonl_on_project_dataset_field(
    window, qapp, seeded, tmp_path
):
    """R97: dropping a .jsonl file on the project window's Dataset
    field fills it like Browse does, and the check below says
    what it holds."""
    _select_session(window)
    win = window.open_project_window("lfm3-tool", "tool-calls")
    path = _valid_jsonl(tmp_path)
    win.dataset_edit.dropEvent(_drop_event(path))
    qapp.processEvents()
    assert win.dataset_edit.text() == str(path)
    assert "examples" in win.dataset_info.text()
    # Saving persists the dropped path, like a Browse pick.
    assert win.save() is True
    assert seeded.get_project("lfm3-tool", "tool-calls")[
        "dataset_ref"
    ] == str(path)
    win.close()


def test_drop_widgets_accept_only_file_drags(qapp):
    """R97: a drag carrying a local file is accepted, a drag
    carrying plain text is ignored (no drop, no surprise)."""
    from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent

    from stella.gui import DropButton

    btn = DropButton("Pick dataset file")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/data.jsonl")])
    event = QDragEnterEvent(
        QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    btn.dragEnterEvent(event)
    assert event.isAccepted()
    text_mime = QMimeData()
    text_mime.setText("hello")
    text_event = QDragEnterEvent(
        QPoint(5, 5), Qt.CopyAction, text_mime,
        Qt.LeftButton, Qt.NoModifier,
    )
    btn.dragEnterEvent(text_event)
    assert text_event.isAccepted() is False
    btn.close()


# -- R98: the Shortcuts topic, from one registry --------------------


def test_shortcuts_topic_is_generated_from_registry():
    """R98 Done: every shortcut is listed in How to Use, and the
    topic text is exactly what the registry generates — it cannot
    drift from the code."""
    from stella.howto import topic_text, topic_titles
    from stella.shortcuts import SHORTCUTS, shortcuts_topic_text

    assert "Shortcuts" in topic_titles()
    body = topic_text("Shortcuts")
    assert body == shortcuts_topic_text()
    assert len(body) > 200
    for _sid, keys, action, where in SHORTCUTS:
        assert keys in body, keys
        assert action in body, action
        assert where in body, where


def _gui_shortcuts(window):
    """Every shortcut the live main window actually wires: its
    QShortcuts plus its menu actions' shortcuts."""
    from PySide6.QtGui import QShortcut

    found = set()
    for shortcut in window.findChildren(QShortcut):
        found.add(shortcut.key().toString())
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is None:
            continue
        for sub in menu.actions():
            if not sub.shortcut().isEmpty():
                found.add(sub.shortcut().toString())
    return found


def test_every_registered_shortcut_is_wired_in_gui(window):
    """R98: every shortcut in the registry exists in the GUI —
    the help never promises a key that does nothing."""
    from stella.shortcuts import SHORTCUTS

    wired = _gui_shortcuts(window)
    for _sid, keys, _action, _where in SHORTCUTS:
        assert keys in wired, keys


def test_no_gui_shortcut_outside_registry(window):
    """R98: every shortcut the GUI wires is in the registry — a
    key added to the window and nowhere else fails here instead
    of going undocumented."""
    from stella.shortcuts import SHORTCUTS

    registered = {keys for _sid, keys, _a, _w in SHORTCUTS}
    assert _gui_shortcuts(window) <= registered


def test_shortcut_for_unknown_id_raises():
    """R98: a typo in the wiring fails loudly, not silently."""
    from stella.shortcuts import shortcut_for

    with pytest.raises(KeyError):
        shortcut_for("no-such-shortcut")


# -- R99: the stopped reply is recorded -----------------------------


def test_cancelled_reply_is_recorded_in_history(agent):
    """R99 (folded in): the cancelled reply is recorded in the
    history like any other reply — the record has no hole where
    the agent stopped. The cap-hit half is pinned by the extended
    test_twelve_call_cap in test_chat_agent.py."""
    def cancelling(model, messages):
        agent.request_cancel()
        return "Hello."

    agent._chat_fn = cancelling
    reply = agent.reply("go")
    assert reply == "Stopped. Tell me what you want to do next."
    assert agent._history[-1] == {"role": "assistant", "content": reply}


# -- R100: "just do it" matches anywhere -----------------------------


def test_just_do_it_matches_anywhere_in_message():
    """R100 Done: the phrase triggers wherever it appears in a
    message, not only at the start."""
    from stella.chat_agent import _is_just_do_it

    assert _is_just_do_it("just do it")
    assert _is_just_do_it("ok, just do it")
    assert _is_just_do_it("please just do it")
    assert _is_just_do_it("do the whole thing for me")
    assert _is_just_do_it("go ahead and train it")
    assert _is_just_do_it("hello there") is False
    assert _is_just_do_it("what projects do i have") is False


def test_just_do_it_mid_message_shows_plan(agent):
    """R100: "ok, just do it" runs the plan-first flow the
    greeting promises — the plan shows, nothing runs yet."""
    text = agent.reply("ok, just do it")
    assert agent.pending_plan is not None
    assert text.startswith("I will:")
    assert "Say go ahead to run it" in text


def test_refusal_still_wins_over_just_do_it(agent):
    """R100: the refusal path still runs first — "don't just do
    it" with a plan pending refuses, it does not trigger."""
    agent.reply("just do it")
    assert agent.pending_plan is not None
    reply = agent.reply("don't just do it")
    assert reply.startswith("Okay, I will not do that.")
    assert agent.pending_plan is None


# -- R101: a full endpoint URL works as a custom base URL ------------


def test_custom_base_url_ending_in_chat_completions(home, monkeypatch):
    """R101 Done: a custom base URL ending in /chat/completions
    produces a single-suffixed endpoint, not a doubled path."""
    import stella.providers as prov_mod
    from stella.providers import chat, save_key

    seen = {}

    def fake_openai(display, endpoint, key, model, messages, **kw):
        seen["endpoint"] = endpoint
        return "hi"

    monkeypatch.setattr(prov_mod, "_openai_chat", fake_openai)
    save_key(
        home, "custom", "test-key",
        base_url="https://example.com/v1/chat/completions",
        model="m",
    )
    assert (
        chat("custom", "m", [{"role": "user", "content": "hi"}], home)
        == "hi"
    )
    assert seen["endpoint"] == "https://example.com/v1/chat/completions"


def test_custom_base_url_with_chat_completions_mid_path(home, monkeypatch):
    """R101: only the exact trailing segment is stripped — a base
    URL that merely contains the string earlier is left alone."""
    import stella.providers as prov_mod
    from stella.providers import chat, save_key

    seen = {}

    def fake_openai(display, endpoint, key, model, messages, **kw):
        seen["endpoint"] = endpoint
        return "hi"

    monkeypatch.setattr(prov_mod, "_openai_chat", fake_openai)
    save_key(
        home, "custom", "test-key",
        base_url="https://example.com/chat/completions/v1",
        model="m",
    )
    chat("custom", "m", [{"role": "user", "content": "hi"}], home)
    assert seen["endpoint"] == (
        "https://example.com/chat/completions/v1/chat/completions"
    )


def test_custom_base_url_plain_gets_suffix(home, monkeypatch):
    """R101: a plain base URL still gets the suffix appended once."""
    import stella.providers as prov_mod
    from stella.providers import chat, save_key

    seen = {}

    def fake_openai(display, endpoint, key, model, messages, **kw):
        seen["endpoint"] = endpoint
        return "hi"

    monkeypatch.setattr(prov_mod, "_openai_chat", fake_openai)
    save_key(
        home, "custom", "test-key",
        base_url="https://example.com/v1", model="m",
    )
    chat("custom", "m", [{"role": "user", "content": "hi"}], home)
    assert seen["endpoint"] == "https://example.com/v1/chat/completions"


# -- R102: cloud models as chat-window buttons -----------------------


def test_chat_window_offers_cloud_models_as_buttons(
    window, seed_models, qapp
):
    """R102 Done: the chat window's buttons include the configured
    cloud models, labelled with their provider — and clicking one
    chats with it, on its own provider."""
    from stella.gui import ChatWindow
    from stella.providers import save_key

    save_key(window.store.home, "groq", "test-key")
    seed_models(["lfm3:1.7b", "qwen3.5:2b"])
    assert window.chat_model == ""
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert [b.text() for b in chat.model_buttons] == [
        "lfm3:1.7b",
        "qwen3.5:2b",
        "openai/gpt-oss-120b (Groq)",
        "openai/gpt-oss-20b (Groq)",
    ]
    assert "provider in brackets" in chat.messages.toPlainText()
    chat.model_buttons[2].click()
    qapp.processEvents()
    assert window.chat_provider == "groq"
    assert window.chat_model == "openai/gpt-oss-120b"
    assert "I will chat with openai/gpt-oss-120b" in (
        chat.messages.toPlainText()
    )
    assert chat.model_pick_scroll.isVisible() is False
    chat.close()


def test_chat_window_cloud_buttons_show_when_ollama_down(
    window, seed_models, qapp
):
    """R102: the cloud buttons render even when the Ollama list is
    empty — Ollama being down does not hide the cloud models."""
    from stella.gui import ChatWindow
    from stella.providers import save_key

    save_key(window.store.home, "gemini", "test-key")
    seed_models([])
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert [b.text() for b in chat.model_buttons] == [
        "gemini-3.8-flash (Gemini)",
        "gemini-3.5-flash-lite (Gemini)",
    ]
    assert "Ollama is not answering" in chat.messages.toPlainText()
    chat.model_buttons[0].click()
    qapp.processEvents()
    assert window.chat_provider == "gemini"
    assert window.chat_model == "gemini-3.8-flash"
    chat.close()


def test_chat_window_no_cloud_buttons_without_key(
    window, seed_models, qapp
):
    """R102: a cloud model with no saved key gets no button — a
    dead button is worse than no button."""
    from stella.gui import ChatWindow

    seed_models(["lfm3:1.7b"])
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert [b.text() for b in chat.model_buttons] == ["lfm3:1.7b"]
    chat.close()


def test_chat_window_custom_model_button(window, seed_models, qapp):
    """R102: the custom provider's own model gets a button too,
    labelled Custom, and clicking it sets the custom provider."""
    from stella.gui import ChatWindow
    from stella.providers import save_key

    save_key(
        window.store.home, "custom", "test-key",
        base_url="https://example.com/v1", model="my-model",
    )
    seed_models(["lfm3:1.7b"])
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert [b.text() for b in chat.model_buttons] == [
        "lfm3:1.7b",
        "my-model (Custom)",
    ]
    chat.model_buttons[1].click()
    qapp.processEvents()
    assert window.chat_provider == "custom"
    assert window.chat_model == "my-model"
    chat.close()
