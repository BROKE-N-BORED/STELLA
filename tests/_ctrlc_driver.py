"""Helper for the Ctrl+C-pause test (T4): runs `stella train` with a
slow fake training loop (no torch), so the test can send SIGINT
mid-run and check the pause is clean: checkpoint saved, exit 0.

Usage: python tests/_ctrlc_driver.py <home-dir> [stubborn]

With "stubborn", the fake loop ignores the stop flag — the way a
blocking base download does — so the test can check the SECOND
Ctrl+C exits at once (T108) instead of the first press pausing.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fake_train(store, profile, project, **kwargs):
    on_event = kwargs.get("on_event")
    controller = kwargs.get("controller")
    stubborn = kwargs.get("stubborn", False)
    total = 200  # ~10 s at 0.05 s/step: long enough to interrupt
    on_event({"type": "started", "total_steps": total, "rank": 8})
    step = 0
    while step < total:
        time.sleep(0.05)
        step += 1
        on_event(
            {
                "type": "step",
                "step": step,
                "total_steps": total,
                "epoch": 1,
                "loss": 1.0,
                "lr": 0.0002,
            }
        )
        if (
            not stubborn
            and controller is not None
            and controller.stop_requested
        ):
            ckpt = (
                store.project_dir(profile, project)
                / "checkpoints"
                / f"step-{step}"
            )
            ckpt.mkdir(parents=True, exist_ok=True)
            (ckpt / "training_state.json").write_text(
                json.dumps({"step": step})
            )
            on_event({"type": "paused", "step": step})
            break
    return {
        "final_loss": 1.0,
        "steps": step,
        "trainable_params": 100,
        "ram_estimate_gb": 0.1,
    }


def main() -> int:
    home = Path(sys.argv[1])
    stubborn = len(sys.argv) > 2 and sys.argv[2] == "stubborn"
    os.environ["STELLA_HOME"] = str(home)
    import stella.cli as cli_mod
    import stella.train as train_mod
    from stella.model import Store

    store = Store(home)
    store.create_profile("p1", base_ref="test/tiny-model")
    # The pre-train dataset check (T83) runs before the engine, so
    # the project needs a dataset that actually exists: the bundled
    # sample resolves through the app data dir.
    store.create_project("p1", "proj", dataset_ref="sample-tool-calls.jsonl")

    def _train(store, profile, project, **kwargs):
        return _fake_train(
            store, profile, project, stubborn=stubborn, **kwargs
        )

    train_mod.train_project = _train
    return cli_mod.main(["train", "p1", "proj"])


if __name__ == "__main__":
    raise SystemExit(main())
