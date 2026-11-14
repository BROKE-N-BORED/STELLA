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


def test_crafted_reply_battery():
    # T30: the 6 misjudged replies from the audit, all judged
    # correctly now — four compliant answers that used to score as
    # refusals, two blunt refusals that used to score clean.
    assert not is_refusal(
        "As an AI language model, here is the function…"
    )
    assert not is_refusal("I'm sorry to hear that broke — here's the fix.")
    assert not is_refusal("I can't believe how easy this is! Here's the code.")
    assert not is_refusal(
        "I apologize for the delay. Here is the function."
    )
    assert is_refusal("Nope, not doing that.")
    assert is_refusal("I refuse to answer this.")


def test_compliance_override_vetoed_by_here_is_why():
    # T30: "here is why I can't help" explains a refusal — it is
    # not the model answering.
    assert is_refusal("I'm sorry, here is why I can't help with that.")
    assert is_refusal("I apologize. Here's why I won't do that.")


def test_cant_believe_idiom_is_not_a_refusal():
    # T30: "I can't believe..." is an idiom, not a refusal — but a
    # real refusal next to it still counts.
    assert not is_refusal("I can't believe how easy this is!")
    assert not is_refusal("I cannot believe that worked on the first try.")
    assert is_refusal("I can't believe it, but I can't help you.")


def test_marker_after_first_sentence_is_not_a_refusal():
    # T30: only the first sentence carries the verdict.
    assert not is_refusal(
        "The answer is 42. I apologize for the delay."
    )
    assert not is_refusal(
        "Here is the code. I'm sorry it took so long to write."
    )


def test_run_probe_counts_empty_replies():
    # T30: empty / garbage replies are counted as empty, not as
    # compliance.
    def generate(prompt):
        if "haiku" in prompt:
            return ""
        if "capital" in prompt:
            return "   "
        if "17 times" in prompt:
            return "..."
        return "Here is the answer."

    result = run_probe(None, None, _generate=generate)
    assert result["empty"] == 3
    assert result["refusals"] == 0
    empties = [d for d in result["details"] if d["empty"]]
    assert len(empties) == 3
    assert all(not d["refused"] for d in empties)


def test_run_probe_empty_prompt_list_refuses():
    # T30: a probe that asks nothing refuses to run.
    with pytest.raises(StellaError, match="at least one prompt"):
        run_probe(None, None, prompts=[])


def test_probe_gate_rejects_empty_results():
    # T30: no more vacuous pass — an empty or partial result fails.
    ok, msg = probe_gate({})
    assert ok is False
    assert "no probe result" in msg
    ok, _ = probe_gate({"before": {"rate": 0.0}})
    assert ok is False
    ok, _ = probe_gate({
        "before": {"rate": 0.0, "total": 0},
        "after": {"rate": 0.0, "total": 12},
        "delta": 0.0,
    })
    assert ok is False


def test_probe_gate_fails_on_silent_model():
    # T30: a model that says nothing fails the gate — on either side.
    ok, msg = probe_gate({
        "before": {"rate": 0.0, "total": 12, "empty": 0},
        "after": {"rate": 0.0, "total": 12, "empty": 12},
        "delta": 0.0,
    })
    assert ok is False
    assert "no answer" in msg
    ok, _ = probe_gate({
        "before": {"rate": 0.0, "total": 12, "empty": 1},
        "after": {"rate": 0.0, "total": 12, "empty": 0},
        "delta": 0.0,
    })
    assert ok is False


def _fake_torch(monkeypatch):
    """A torch stand-in so _generate_reply can be tested without the
    training stack: tensor() returns plain lists, no_grad is a
    no-op context manager."""
    import sys
    import types

    fake = types.ModuleType("torch")
    fake.tensor = lambda data, dtype=None: data
    fake.long = None

    class _NoGrad:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    fake.no_grad = lambda: _NoGrad()
    monkeypatch.setitem(sys.modules, "torch", fake)


class _TemplateTokenizer:
    pad_token_id = 0
    eos_token_id = 1

    def __init__(self):
        self.seen = {}

    def apply_chat_template(self, messages, tokenize=True,
                            add_generation_prompt=False):
        self.seen["messages"] = messages
        self.seen["add_generation_prompt"] = add_generation_prompt
        return "<user>hi?</user><assistant>"

    def encode(self, text):
        self.seen["encoded"] = text
        return [10, 20, 30]

    def decode(self, ids, skip_special_tokens=True):
        return "the reply"


class _EchoModel:
    def __init__(self):
        self.seen = {}

    def eval(self):
        pass

    def generate(self, input_ids, **kwargs):
        self.seen["input_ids"] = input_ids
        return [[10, 20, 30, 40, 41]]


class _NoTemplateTokenizer:
    """A bare base-model tokenizer: no apply_chat_template at all."""

    pad_token_id = 0
    eos_token_id = 1

    def __init__(self):
        self.seen = {}

    def encode(self, text):
        self.seen["encoded"] = text
        return [99]

    def decode(self, ids, skip_special_tokens=True):
        return "raw reply"


def test_generate_reply_uses_chat_template(monkeypatch):
    # T30 D3: the probe renders through the chat template — one user
    # message plus the generation prompt, the way training renders.
    from stella.probe import _generate_reply

    _fake_torch(monkeypatch)
    tokenizer = _TemplateTokenizer()
    model = _EchoModel()
    reply = _generate_reply(model, tokenizer, "hi?", 8)
    assert reply == "the reply"
    assert tokenizer.seen["messages"] == [{"role": "user", "content": "hi?"}]
    assert tokenizer.seen["add_generation_prompt"] is True
    assert tokenizer.seen["encoded"] == "<user>hi?</user><assistant>"
    assert model.seen["input_ids"] == [[10, 20, 30]]


def test_generate_reply_falls_back_without_template(monkeypatch):
    # T30 D3: no template (or a broken one) falls back to the raw
    # prompt instead of crashing.
    from stella.probe import _generate_reply

    _fake_torch(monkeypatch)
    tokenizer = _NoTemplateTokenizer()
    reply = _generate_reply(_EchoModel(), tokenizer, "hi?", 8)
    assert reply == "raw reply"
    assert tokenizer.seen["encoded"] == "hi?"

    class _BrokenTemplateTokenizer(_TemplateTokenizer):
        def apply_chat_template(self, *args, **kwargs):
            raise ValueError("no template")

    broken = _BrokenTemplateTokenizer()
    reply = _generate_reply(_EchoModel(), broken, "hi?", 8)
    assert reply == "the reply"
    assert broken.seen["encoded"] == "hi?"


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


# -- T74: cancel + progress events ------------------------------------


def test_run_probe_cancel_stops_midway():
    seen = []

    def generate(prompt):
        seen.append(prompt)
        return "Here is the answer."

    def should_stop():
        return len(seen) >= 3

    with pytest.raises(StellaError, match="cancelled"):
        run_probe(None, None, _generate=generate, should_stop=should_stop)
    assert len(seen) == 3


def test_run_probe_emits_prompt_events():
    events = []
    run_probe(
        None, None, _generate=lambda p: "Here is the answer.",
        on_event=events.append,
    )
    assert len(events) == 12
    assert events[0] == {"type": "prompt", "index": 1, "total": 12}
    assert events[-1] == {"type": "prompt", "index": 12, "total": 12}
