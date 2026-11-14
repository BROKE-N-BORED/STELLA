"""T29 — one job at a time, enforced in the engine.

The lock lives in the Stella home (job.lock, flock): a second
model-loading job refuses at once with the running job named,
even across CLI invocations. A crashed holder never leaves a
stuck lock (the kernel releases flock on death).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from stella.job_lock import job_lock
from stella.model import StellaError, Store

ROOT = Path(__file__).resolve().parent.parent


def run_cli(home, *args):
    """Run the real `python -m stella.cli` in a subprocess (same
    shape as tests/test_cli.py's helper)."""
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


def _seed_trainable(store, tmp_path):
    """A profile + project that passes every cheap check, so a
    train/probe/export call reaches the lock (not an earlier
    error)."""
    store.create_profile("p1", base_ref="test/tiny-model")
    data = tmp_path / "data.jsonl"
    data.write_text(
        "\n".join(
            json.dumps(
                {
                    "messages": [
                        {"role": "user", "content": f"Question {i}?"},
                        {"role": "assistant", "content": f"Answer {i}."},
                    ]
                }
            )
            for i in range(4)
        )
        + "\n",
        encoding="utf-8",
    )
    store.create_project("p1", "proj", dataset_ref=str(data))
    adapter = store.project_dir("p1", "proj") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    return store


def test_second_acquire_refused_and_names_the_job(tmp_path):
    home = tmp_path / "home"
    with job_lock(home, "training p1/proj"):
        with pytest.raises(StellaError) as exc:
            with job_lock(home, "refusal probe p1/proj"):
                pass
    assert "already running" in str(exc.value)
    assert "training p1/proj" in str(exc.value)


def test_lock_released_when_the_job_ends(tmp_path):
    home = tmp_path / "home"
    with job_lock(home, "training p1/proj"):
        pass
    # A finished job's lock is free for the next one.
    with job_lock(home, "refusal probe p1/proj"):
        pass


def test_lock_skip_takes_no_lock(tmp_path):
    home = tmp_path / "home"
    with job_lock(home, "sleep p1/proj"):
        # The nested call (sleep's inner train) does not fight the
        # outer lock it already holds.
        with job_lock(home, "training p1/proj", skip=True):
            pass


def test_train_refuses_while_locked(tmp_path):
    from stella.train import train_project

    # No deps faking needed: the gate sits inside the lock (T48),
    # so the lock refusal fires before the gate is even reached.
    store = _seed_trainable(Store(tmp_path / "home"), tmp_path)
    with job_lock(store.home, "refusal probe p1/proj"):
        with pytest.raises(StellaError) as exc:
            train_project(
                store, "p1", "proj", _model_loader=lambda: (None, None)
            )
    assert "already running" in str(exc.value)
    assert "refusal probe p1/proj" in str(exc.value)


def test_probe_refuses_while_locked(tmp_path):
    from stella.probe import probe_project

    store = _seed_trainable(Store(tmp_path / "home"), tmp_path)
    with job_lock(store.home, "training p1/proj"):
        with pytest.raises(StellaError) as exc:
            probe_project(
                store, "p1", "proj",
                _model_loader=lambda a, b: (object(), object()),
                _generate=lambda p: "Here is the answer.",
            )
    assert "already running" in str(exc.value)
    assert "training p1/proj" in str(exc.value)


def test_export_gguf_refuses_while_locked(tmp_path):
    from stella.gguf import export_gguf

    store = _seed_trainable(Store(tmp_path / "home"), tmp_path)
    with job_lock(store.home, "training p1/proj"):
        with pytest.raises(StellaError) as exc:
            export_gguf(
                store, "p1", "proj", tmp_path / "out",
                _runner=lambda cmd: None,
                _model_loader=lambda a, b: (object(), object()),
            )
    assert "already running" in str(exc.value)
    assert "training p1/proj" in str(exc.value)


def test_sleep_refuses_while_locked(tmp_path):
    from stella.sleep import sleep_project

    store = _seed_trainable(Store(tmp_path / "home"), tmp_path)
    with job_lock(store.home, "training p1/proj"):
        with pytest.raises(StellaError) as exc:
            sleep_project(
                store, "p1", "proj", _model_loader=lambda: (None, None)
            )
    assert "already running" in str(exc.value)
    assert "training p1/proj" in str(exc.value)


def test_cheap_checks_still_fire_while_locked(tmp_path):
    """A bad profile name is reported even while another job runs:
    the cheap checks run before the lock, so a mistake in the
    command is never masked by the lock."""
    from stella.train import train_project

    store = Store(tmp_path / "home")
    with job_lock(store.home, "training p1/proj"):
        with pytest.raises(StellaError) as exc:
            train_project(
                store, "ghost", "proj", _model_loader=lambda: (None, None)
            )
    assert "no profile" in str(exc.value)


def test_second_cli_invocation_refuses_while_locked(tmp_path, home):
    """Two CLI invocations: the second refuses with the running
    job named — the lock works across processes, not just threads.
    Train is the vehicle: its cheap checks pass on the seeded
    store, so the lock is what the second invocation hits (the
    deps gate sits inside the lock, T48)."""
    store = _seed_trainable(Store(home), tmp_path)
    driver = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tests" / "_joblock_driver.py"),
            str(home),
            "training p1/proj",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert driver.stdout.readline().strip() == "READY"
        res = run_cli(home, "train", "p1", "proj")
    finally:
        driver.terminate()
        driver.wait(timeout=10)
    assert res.returncode == 1
    assert "already running" in res.stderr
    assert "training p1/proj" in res.stderr
