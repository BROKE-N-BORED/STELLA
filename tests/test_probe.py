"""Refusal probe tests — scoring, gate, and the before/after run.

Scoring is pure Python. The project-level probe runs against injected
fake models/generation, so no weights are needed; the real generation
path is exercised only where a tiny model exists (see
test_probe_real_tiny_model, skipped without the training stack).
"""
import json

import pytest

from stella.model import StellaError
from stella.probe import (
    REFUSAL_PROMPTS,
    is_refusal,
    probe_gate,
    probe_project,
    run_probe,
)


def test_refusal_markers_detected():
    assert is_refusal("I'm sorry, I can't help with that.")
    assert is_refusal("I cannot help with this request.")
    assert is_refusal("As an AI language model, I must decline.")
    assert is_refusal("I'm unable to do that right now.")


def test_plain_answers_are_not_refusals():
    assert not is_refusal("The capital of France is Paris.")
    assert not is_refusal("Here is the function:\n\ndef add(a, b):\n    return a + b")
    assert not is_refusal("Run ls -la to list the files.")
    assert not is_refusal("")


def test_refusal_prompt_set_is_all_benign():
    assert len(REFUSAL_PROMPTS) == 12
    for prompt in REFUSAL_PROMPTS:
        assert prompt.strip()
        assert "?" in prompt or prompt.endswith(".")


def test_run_probe_counts_with_fake_generate():
    def generate(prompt):
        if "haiku" in prompt or "capital" in prompt:
            return "I'm sorry, I can't help with that."
        return "Here is the answer."

    result = run_probe(None, None, _generate=generate)
    assert result["total"] == 12
    assert result["refusals"] == 2
    assert result["rate"] == pytest.approx(2 / 12, abs=0.001)
    refused = [d for d in result["details"] if d["refused"]]
    assert len(refused) == 2


def test_probe_gate_passes_when_rate_falls_or_holds():
    ok, msg = probe_gate(
        {"before": {"rate": 0.25}, "after": {"rate": 0.0}, "delta": -0.25}
    )
    assert ok is True
    assert "Gate passed" in msg
    ok, _ = probe_gate(
        {"before": {"rate": 0.0}, "after": {"rate": 0.0}, "delta": 0.0}
    )
    assert ok is True


def test_probe_gate_fails_when_rate_rises():
    ok, msg = probe_gate(
        {"before": {"rate": 0.0}, "after": {"rate": 0.25}, "delta": 0.25}
    )
    assert ok is False
    assert "ROSE" in msg
    assert "gate failed" in msg


def test_probe_project_before_after_with_fakes(tmp_path):
    pytest.importorskip("torch", reason="training stack not installed")
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")

    calls = {"n": 0}

    def loader(base_ref, adapter_dir):
        return object(), object()

    def generate(prompt):
        # First 12 calls are the "before" probe (no refusals),
        # next 12 are "after" (3 refusals).
        calls["n"] += 1
        if calls["n"] > 12 and calls["n"] <= 15:
            return "I'm sorry, I can't help with that."
        return "Here is the answer."

    result = probe_project(
        store, "tiny", "proof", _model_loader=loader, _generate=generate
    )
    assert result["before"]["refusals"] == 0
    assert result["after"]["refusals"] == 3
    assert result["delta"] == pytest.approx(0.25)
    saved = json.loads(
        (store.project_dir("tiny", "proof") / "probe_results.json").read_text()
    )
    assert saved["after"]["refusals"] == 3


def test_probe_project_without_adapter_fails(tmp_path):
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    with pytest.raises(StellaError, match="no trained adapter"):
        probe_project(store, "tiny", "proof", _model_loader=lambda a, b: (None, None))


# -- T10: the probe never holds two base models at once --------------


def test_probe_loads_one_base_at_a_time(tmp_path):
    pytest.importorskip("torch", reason="training stack not installed")
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref="test/tiny-model")
    store.create_project("tiny", "proof")
    adapter = store.project_dir("tiny", "proof") / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")

    class CountedModel:
        """A fake model that counts how many are alive at once."""

        live = 0
        peak = 0

        def __init__(self):
            type(self).live += 1
            type(self).peak = max(type(self).peak, type(self).live)

        def __del__(self):
            type(self).live -= 1

    def loader(base_ref, adapter_dir):
        return CountedModel(), object()

    calls = {"n": 0}

    def generate(prompt):
        calls["n"] += 1
        if calls["n"] > 12 and calls["n"] <= 15:
            return "I'm sorry, I can't help with that."
        return "Here is the answer."

    result = probe_project(
        store, "tiny", "proof", _model_loader=loader, _generate=generate
    )
    # Before/after counts are unchanged by the one-at-a-time load.
    assert result["before"]["refusals"] == 0
    assert result["after"]["refusals"] == 3
    # And two models were never alive at once: the second load
    # happened only after the first was freed.
    assert CountedModel.peak == 1
    assert CountedModel.live == 0
