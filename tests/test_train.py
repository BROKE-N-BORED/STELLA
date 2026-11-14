"""Training engine tests.

Pure-Python checks (dataset validation, RAM math, splits) run on any
install. The heavy checks (a real 2-step LoRA run on a tiny random
model, checkpoint + resume) need the training stack and skip cleanly
when it is missing — a base install (PySide6 only) still goes green.
"""
import json
from pathlib import Path

import pytest

from stella.model import StellaError
from stella.train import (
    TrainController,
    check_dataset,
    check_ram_fit,
    detect_target_modules,
    estimate_run,
    estimate_training_bytes,
    format_estimate,
    format_estimate_short,
    list_checkpoints,
    load_dataset,
    require_training_deps,
    resolve_dataset_ref,
    split_dataset,
    train_project,
)

ROOT = Path(__file__).resolve().parent.parent


class FakeTokenizer:
    """Minimal tokenizer interface: encode + ids + save_pretrained."""

    def __init__(self, vocab_size=256):
        self.vocab_size = vocab_size
        self.eos_token_id = 0
        self.pad_token_id = 0
        self.eos_token = "<eos>"
        self.pad_token = "<pad>"

    def encode(self, text, add_special_tokens=True):
        return [(ord(c) % 254) + 1 for c in text]

    def save_pretrained(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        (Path(path) / "tokenizer_config.json").write_text("{}\n")

    def decode(self, ids, skip_special_tokens=True):
        return "".join(chr((i - 1) % 254 + 1) if i else "" for i in ids)


@pytest.fixture()
def need_torch():
    return pytest.importorskip("torch", reason="training stack not installed")


def tiny_model_and_tokenizer():
    """A tiny random GPT-2 (no downloads): 2 layers, 64 hidden."""
    from transformers import GPT2Config, GPT2LMHeadModel

    config = GPT2Config(
        vocab_size=256, n_layer=2, n_head=2, n_embd=64,
        n_positions=64, n_ctx=64,
    )
    return GPT2LMHeadModel(config), FakeTokenizer()


def write_dataset(path, rows):
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return path


def prompt_rows(n=4):
    return [
        {"prompt": f"Question {i}?", "completion": f"Answer {i}."}
        for i in range(n)
    ]


def message_rows(n=4):
    return [
        {
            "messages": [
                {"role": "user", "content": f"Question {i}?"},
                {"role": "assistant", "content": f"Answer {i}."},
            ]
        }
        for i in range(n)
    ]


# -- dataset validation (no torch needed) ---------------------------

def test_load_dataset_prompt_format(tmp_path):
    path = write_dataset(tmp_path / "d.jsonl", prompt_rows(3))
    examples, info = load_dataset(path)
    assert info["format"] == "prompt"
    assert info["count"] == 3
    assert examples[0]["messages"][0]["role"] == "user"
    assert examples[0]["messages"][1]["role"] == "assistant"


def test_load_dataset_messages_format(tmp_path):
    path = write_dataset(tmp_path / "d.jsonl", message_rows(3))
    examples, info = load_dataset(path)
    assert info["format"] == "messages"
    assert info["count"] == 3


def test_load_dataset_bad_json_names_line(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text(
        '{"prompt": "a", "completion": "b"}\nnot json\n',
        encoding="utf-8",
    )
    with pytest.raises(StellaError, match="line 2"):
        load_dataset(path)


def test_load_dataset_bad_role(tmp_path):
    rows = message_rows(2)
    rows[1]["messages"][0]["role"] = "robot"
    path = write_dataset(tmp_path / "d.jsonl", rows)
    with pytest.raises(StellaError, match="role 'robot'"):
        load_dataset(path)


def test_load_dataset_last_message_must_be_assistant(tmp_path):
    rows = [
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "and?"},
            ]
        },
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ]
        },
    ]
    path = write_dataset(tmp_path / "d.jsonl", rows)
    with pytest.raises(StellaError, match="last message must be"):
        load_dataset(path)


def test_load_dataset_mixed_formats_rejected(tmp_path):
    rows = prompt_rows(1) + message_rows(1)
    path = write_dataset(tmp_path / "d.jsonl", rows)
    with pytest.raises(StellaError, match="mixed formats"):
        load_dataset(path)


def test_load_dataset_too_small(tmp_path):
    path = write_dataset(tmp_path / "d.jsonl", prompt_rows(1))
    with pytest.raises(StellaError, match="At least 2"):
        load_dataset(path)


def test_load_dataset_missing_file(tmp_path):
    with pytest.raises(StellaError, match="not found"):
        load_dataset(tmp_path / "nope.jsonl")


# -- T45: the dataset check for display -----------------------------


def test_check_dataset_ok_counts_split_and_previews(seeded, tmp_path):
    path = write_dataset(tmp_path / "d.jsonl", message_rows(10))
    check = check_dataset(seeded, "lfm3-tool", "tool-calls", str(path))
    assert check["status"] == "ok"
    assert check["count"] == 10
    assert check["train"] == 9
    assert check["val"] == 1
    assert check["format"] == "messages"
    assert check["preview"] == ["Question 0?", "Question 1?", "Question 2?"]
    assert check["error"] is None
    assert check["path"] == str(path)


def test_check_dataset_missing_names_the_ref(seeded):
    check = check_dataset(
        seeded, "lfm3-tool", "tool-calls", "/no/such/place/data.jsonl"
    )
    assert check["status"] == "missing"
    assert "not found" in check["error"]
    assert check["count"] == 0


def test_check_dataset_malformed_names_the_line(seeded, tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text(
        '{"prompt": "a", "completion": "b"}\nnot json\n',
        encoding="utf-8",
    )
    check = check_dataset(seeded, "lfm3-tool", "tool-calls", str(path))
    assert check["status"] == "invalid"
    assert "line 2" in check["error"]


def test_check_dataset_unset_and_sample(seeded):
    assert check_dataset(
        seeded, "lfm3-tool", "tool-calls", ""
    )["status"] == "unset"
    assert check_dataset(
        seeded, "lfm3-tool", "tool-calls", "  "
    )["status"] == "unset"
    # The bundled sample resolves and validates.
    check = check_dataset(
        seeded, "lfm3-tool", "tool-calls", "sample-tool-calls.jsonl"
    )
    assert check["status"] == "ok"
    assert check["count"] == 20


def test_sample_dataset_validates():
    examples, info = load_dataset(ROOT / "data" / "sample-tool-calls.jsonl")
    assert info["format"] == "messages"
    assert info["count"] == 20
    tool_calls = sum(
        1 for ex in examples if "<tool_call>" in ex["messages"][-1]["content"]
    )
    assert tool_calls == 14  # 14 tool calls, 6 plain answers


# -- splits ---------------------------------------------------------

def test_split_deterministic_and_sized():
    examples = prompt_rows(20)
    train_a, val_a = split_dataset(examples, 0.1, 42)
    train_b, val_b = split_dataset(examples, 0.1, 42)
    assert len(train_a) == 18
    assert len(val_a) == 2
    assert train_a == train_b
    assert val_a == val_b
    assert len({id(e) for e in train_a + val_a}) == 20


# -- RAM guard ------------------------------------------------------

def test_ram_estimate_lfm3_lora_fits():
    # LFM3 1.7B, bf16 base, LoRA rank 8 on all projections (~8M params).
    total, breakdown = estimate_training_bytes(
        params=1_730_000_000,
        trainable_params=8_100_000,
        base_bytes_per_param=2,
        seq_len=1024,
        batch_size=1,
        hidden_size=2048,
        num_layers=24,
    )
    assert total < 8 * 1024**3  # fits the 8 GB ceiling
    assert breakdown["base_weights"] == 1_730_000_000 * 2
    check_ram_fit(total)  # must not raise


def test_ram_guard_refuses_full_finetune():
    # A full fine-tune trains every param: optimizer state alone is
    # ~28 GB for a 1.7B model. The guard must refuse it outright.
    total, _ = estimate_training_bytes(
        params=1_730_000_000,
        trainable_params=1_730_000_000,
        base_bytes_per_param=2,
    )
    assert total > 8 * 1024**3
    with pytest.raises(StellaError, match="over the 8.00 GB ceiling"):
        check_ram_fit(total)


def test_ram_guard_boundary():
    check_ram_fit(8 * 1024**3)  # exactly at the ceiling: allowed
    with pytest.raises(StellaError):
        check_ram_fit(8 * 1024**3 + 1)


# -- dependency gate ------------------------------------------------

def test_require_training_deps_names_installer(monkeypatch):
    import stella.train as train_mod

    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch", "peft"]
    )
    with pytest.raises(StellaError, match="install-training.sh"):
        require_training_deps()


# -- dataset resolution ---------------------------------------------

def test_resolve_dataset_ref_finds_sample(seeded):
    path = resolve_dataset_ref(
        seeded, "lfm3-tool", "tool-calls", "sample-tool-calls.jsonl"
    )
    assert path.is_file()
    assert path.name == "sample-tool-calls.jsonl"


def test_resolve_dataset_ref_missing_lists_places(seeded):
    with pytest.raises(StellaError, match="Looked in"):
        resolve_dataset_ref(seeded, "lfm3-tool", "tool-calls", "ghost.jsonl")


# -- target modules (needs torch) -----------------------------------

def test_detect_target_modules_tiny_gpt2(need_torch):
    model, _ = tiny_model_and_tokenizer()
    targets = detect_target_modules(model)
    # GPT-2: c_attn (attention), c_fc + c_proj (MLP) — all LoRA-able.
    assert targets == ["c_attn", "c_fc", "c_proj"]


def test_detect_target_modules_none_found(need_torch):
    import torch

    model = torch.nn.Sequential(torch.nn.Linear(4, 4))
    with pytest.raises(StellaError, match="No LoRA target modules"):
        detect_target_modules(model)


def _install_fake_torch(monkeypatch):
    """A torch stand-in so detect_target_modules can be tested
    without the training stack: nn.Linear is a plain class."""
    import sys
    import types

    fake = types.ModuleType("torch")

    class Linear:
        pass

    nn = types.ModuleType("torch.nn")
    nn.Linear = Linear
    fake.nn = nn
    monkeypatch.setitem(sys.modules, "torch", fake)
    return Linear


class _FakeLayerModel:
    """A model whose linear leaves are whatever names it is given."""

    def __init__(self, linear, leaves):
        self._linear = linear
        self._leaves = leaves

    def named_modules(self):
        for leaf in self._leaves:
            yield f"layers.0.{leaf}", self._linear()
        yield "layers.0.norm", object()


def test_detect_target_modules_override_honored(monkeypatch):
    # T34: an unrecognized architecture trains with a hand-supplied
    # list — the override is used as-is (sorted, deduped).
    Linear = _install_fake_torch(monkeypatch)
    model = _FakeLayerModel(Linear, ["weird_attn", "weird_mlp"])
    assert detect_target_modules(
        model, override=["weird_mlp", "weird_attn", "weird_attn"]
    ) == ["weird_attn", "weird_mlp"]


def test_detect_target_modules_override_missing_names(monkeypatch):
    # T34: an override name the model does not have is refused,
    # naming the missing one and what the model does have.
    Linear = _install_fake_torch(monkeypatch)
    model = _FakeLayerModel(Linear, ["weird_attn"])
    with pytest.raises(StellaError, match="weird_nope"):
        detect_target_modules(model, override=["weird_attn", "weird_nope"])
    try:
        detect_target_modules(model, override=["weird_nope"])
    except StellaError as exc:
        assert "weird_attn" in str(exc)


def test_detect_target_modules_failure_names_override(monkeypatch):
    # T34: when detection fails, the error names the override.
    Linear = _install_fake_torch(monkeypatch)
    model = _FakeLayerModel(Linear, ["weird_attn", "weird_mlp"])
    with pytest.raises(StellaError, match="--target-modules"):
        detect_target_modules(model)


def test_detect_target_modules_empty_override_falls_back(monkeypatch):
    # T34: an empty or missing override is auto-detection.
    Linear = _install_fake_torch(monkeypatch)
    model = _FakeLayerModel(Linear, ["q_proj", "k_proj", "weird"])
    assert detect_target_modules(model, override=[]) == ["k_proj", "q_proj"]
    assert detect_target_modules(model, override=None) == ["k_proj", "q_proj"]


# -- T48: cheap checks before the deps gate -----------------------

def test_train_bad_profile_reported_before_deps_gate(tmp_path):
    # T48: on a base install, a wrong profile name is reported —
    # not the deps message.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    with pytest.raises(StellaError, match="no profile"):
        train_project(store, "ghost", "proof")


def test_train_missing_dataset_reported_before_deps_gate(tmp_path):
    # T48: a missing dataset is reported, not the deps message.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project("tiny", "proof", dataset_ref="ghost.jsonl")
    with pytest.raises(StellaError, match="dataset not found"):
        train_project(store, "tiny", "proof")


def test_train_no_checkpoints_reported_before_deps_gate(tmp_path):
    # T48: --resume with no checkpoints is refused, not the deps.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    with pytest.raises(StellaError, match="nothing to resume"):
        train_project(store, "tiny", "proof", resume=True)


def test_train_no_base_ref_reported_before_deps_gate(tmp_path):
    # T48: a profile with no base_ref is reported, not the deps.
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("p1")  # no base_ref
    data = write_dataset(tmp_path / "data.jsonl", prompt_rows(4))
    store.create_project("p1", "proj", dataset_ref=str(data))
    with pytest.raises(StellaError, match="base_ref"):
        train_project(store, "p1", "proj")


def test_train_deps_gate_fires_only_when_ready(tmp_path, monkeypatch):
    # T48: with everything else ready, the deps message is what a
    # base install reports. The missing deps are faked so this
    # holds in a full env too.
    import stella.train as train_mod
    from stella.model import Store

    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch"]
    )
    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    with pytest.raises(StellaError, match="install-training"):
        train_project(store, "tiny", "proof")


# -- the real loop on a tiny model (needs the training stack) -------

def _tiny_project(store, tmp_path, rows=4):
    store.create_profile(
        "tiny", ollama_tag="", role="test", base_ref="test/tiny-model"
    )
    data = write_dataset(tmp_path / "tiny.jsonl", prompt_rows(rows))
    store.create_project(
        "tiny", "proof",
        dataset_ref=str(data),
        settings={
            "epochs": 1,
            "batch_size": 1,
            "grad_accum": 1,
            "rank": 2,
            "max_seq_len": 128,
            "checkpoint_steps": 1,
            "val_fraction": 0.25,
            "warmup_steps": 1,
            "seed": 42,
        },
    )
    return store


def test_two_step_lora_run_saves_adapter(need_torch, tmp_path):
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    events = []
    summary = train_project(
        store, "tiny", "proof",
        on_event=events.append,
        _model_loader=tiny_model_and_tokenizer,
        _dtype="float32",
    )
    # 4 examples, 1 val -> 3 train, batch 1, grad_accum 1 -> 3 steps.
    assert summary["steps"] == 3
    assert summary["stopped"] is False
    assert summary["final_loss"] is not None
    assert summary["trainable_params"] > 0
    assert summary["target_modules"] == ["c_attn", "c_fc", "c_proj"]
    project_dir = store.project_dir("tiny", "proof")
    assert (project_dir / "adapter" / "adapter_config.json").is_file()
    assert (project_dir / "adapter" / "training_summary.json").is_file()
    assert store.get_project("tiny", "proof")["status"] == "done"
    log_lines = (project_dir / "train_log.jsonl").read_text().splitlines()
    assert len([json.loads(line) for line in log_lines
                if "loss" in json.loads(line)]) == 3
    checkpoints = list_checkpoints(store, "tiny", "proof")
    assert [c["step"] for c in checkpoints] == [1, 2, 3]
    kinds = {e["type"] for e in events}
    assert {"started", "step", "checkpoint", "val", "done"} <= kinds


def test_train_project_honors_target_modules_flag(need_torch, tmp_path):
    # T34: a hand-supplied target list reaches the LoRA config and
    # the summary.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    summary = train_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer,
        _dtype="float32",
        target_modules=["c_attn"],
    )
    assert summary["target_modules"] == ["c_attn"]


def test_train_project_uses_stored_target_modules(need_torch, tmp_path):
    # T34: the stored setting is used when no flag is passed.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project(
        "tiny", "proof", settings={"target_modules": ["c_fc"]}
    )
    summary = train_project(
        store, "tiny", "proof",
        _model_loader=tiny_model_and_tokenizer,
        _dtype="float32",
    )
    assert summary["target_modules"] == ["c_fc"]


def test_train_failure_marks_failed(need_torch, tmp_path, monkeypatch):
    # T53: a run that errors is failed — a crash is not a pause.
    import stella.train as train_mod
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(train_mod, "run_training_loop", _boom)
    with pytest.raises(RuntimeError, match="boom"):
        train_project(
            store, "tiny", "proof",
            _model_loader=tiny_model_and_tokenizer,
            _dtype="float32",
        )
    assert store.get_project("tiny", "proof")["status"] == "failed"


def test_pause_then_resume_completes(need_torch, tmp_path):
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project(
        "tiny", "proof", settings={"epochs": 2}
    )
    controller = TrainController()

    def stop_after_first_step(event):
        if event.get("type") == "step" and event["step"] >= 1:
            controller.request_stop()

    summary = train_project(
        store, "tiny", "proof",
        on_event=stop_after_first_step,
        controller=controller,
        _model_loader=tiny_model_and_tokenizer,
        _dtype="float32",
    )
    assert summary["stopped"] is True
    assert summary["steps"] == 1
    assert store.get_project("tiny", "proof")["status"] == "paused"

    resumed = train_project(
        store, "tiny", "proof",
        resume=True,
        _model_loader=tiny_model_and_tokenizer,
        _dtype="float32",
    )
    # 2 epochs x 3 steps = 6 total; the resume finished the rest.
    assert resumed["stopped"] is False
    assert resumed["steps"] == 6
    assert store.get_project("tiny", "proof")["status"] == "done"
    assert (store.project_dir("tiny", "proof") / "adapter").is_dir()


def test_train_refuses_gguf_base(need_torch, tmp_path):
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("g", base_ref="model-q4_k_m.gguf")
    data = write_dataset(tmp_path / "d.jsonl", prompt_rows(2))
    store.create_project("g", "p", dataset_ref=str(data))
    with pytest.raises(StellaError, match="GGUF file"):
        train_project(
            store, "g", "p",
            _model_loader=tiny_model_and_tokenizer,
            _dtype="float32",
        )


def test_train_refuses_ollama_tag_base(need_torch, tmp_path):
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("g", base_ref="lfm3:1.7b")
    data = write_dataset(tmp_path / "d.jsonl", prompt_rows(2))
    store.create_project("g", "p", dataset_ref=str(data))
    with pytest.raises(StellaError, match="Ollama tag"):
        train_project(
            store, "g", "p",
            _model_loader=tiny_model_and_tokenizer,
            _dtype="float32",
        )


def test_resume_without_checkpoints_fails(need_torch, tmp_path):
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    with pytest.raises(StellaError, match="no checkpoints"):
        train_project(
            store, "tiny", "proof",
            resume=True,
            _model_loader=tiny_model_and_tokenizer,
            _dtype="float32",
        )


# -- T6: engine-side range checks (no torch needed: validation runs
# before the torch import, so a bad value is refused on any install)


@pytest.mark.parametrize(
    "bad, name",
    [
        ({"rank": -5}, "rank"),
        ({"rank": 0}, "rank"),
        ({"rank": "banana"}, "rank"),
        ({"rank": 2.5}, "rank"),
        ({"epochs": 0}, "epochs"),
        ({"epochs": "three"}, "epochs"),
        ({"learning_rate": -0.5}, "learning_rate"),
        ({"learning_rate": 0}, "learning_rate"),
        ({"learning_rate": float("inf")}, "learning_rate"),
        ({"learning_rate": float("nan")}, "learning_rate"),
        ({"batch_size": 0}, "batch_size"),
        ({"grad_accum": 0}, "grad_accum"),
        ({"max_seq_len": 3}, "max_seq_len"),
        ({"checkpoint_steps": -1}, "checkpoint_steps"),
        ({"warmup_steps": -3}, "warmup_steps"),
        ({"seed": "x"}, "seed"),
    ],
)
def test_run_training_loop_rejects_bad_setting(tmp_path, bad, name):
    from stella.train import run_training_loop

    with pytest.raises(StellaError, match=name):
        run_training_loop(None, None, [], [], bad, tmp_path)


def test_run_training_loop_accepts_engine_bounds(tmp_path):
    # The engine bounds are looser than the stored ones: a short
    # sequence length (64) is fine to RUN even though the model
    # layer would not store it. The loop then fails on the missing
    # torch import (or the None model) — the point is it gets PAST
    # validation, which is what this asserts by the error type.
    from stella.train import run_training_loop, validate_run_settings

    cleaned = validate_run_settings(
        {"rank": 2, "max_seq_len": 64, "checkpoint_steps": 1}
    )
    assert cleaned["rank"] == 2
    assert cleaned["max_seq_len"] == 64
    assert cleaned["epochs"] == 3  # defaults fill in
    with pytest.raises((ModuleNotFoundError, AttributeError, TypeError)):
        run_training_loop(
            None, None, [], [],
            {"rank": 2, "max_seq_len": 64},
            tmp_path,
        )


def test_validate_run_settings_coerces(tmp_path):
    from stella.train import validate_run_settings

    cleaned = validate_run_settings({"rank": "8", "epochs": 2.0})
    assert cleaned["rank"] == 8
    assert cleaned["epochs"] == 2


# -- T5: HF load failures are plain StellaErrors --------------------


def _install_fake_transformers(monkeypatch, failure):
    """A fake torch + transformers in sys.modules, so
    load_base_model can be tested with no downloads and no torch."""
    import sys
    import types

    torch_mod = types.ModuleType("torch")
    torch_mod.bfloat16 = "bfloat16"
    torch_mod.float32 = "float32"
    monkeypatch.setitem(sys.modules, "torch", torch_mod)

    def _boom(*args, **kwargs):
        raise failure

    transformers_mod = types.ModuleType("transformers")

    class FakeTokenizer:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            _boom()

    class FakeModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            _boom()

    transformers_mod.AutoTokenizer = FakeTokenizer
    transformers_mod.AutoModelForCausalLM = FakeModel
    monkeypatch.setitem(sys.modules, "transformers", transformers_mod)


def test_load_base_model_wraps_hf_failure(monkeypatch, tmp_path):
    import stella.train as train_mod

    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    _install_fake_transformers(
        monkeypatch, ValueError("Couldn't instantiate the backend tokenizer")
    )
    with pytest.raises(StellaError, match="could not load the base model"):
        train_mod.load_base_model("someone/no-such-model")


def test_load_base_model_names_empty_dir(monkeypatch, tmp_path):
    import stella.train as train_mod

    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    empty = tmp_path / "empty-model"
    empty.mkdir()
    _install_fake_transformers(monkeypatch, ValueError("no files here"))
    with pytest.raises(
        StellaError, match="does not hold a model"
    ):
        train_mod.load_base_model(str(empty))


def test_load_base_model_names_repo_not_found(monkeypatch):
    import stella.train as train_mod

    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    _install_fake_transformers(
        monkeypatch, ValueError("Repository Not Found for url")
    )
    with pytest.raises(StellaError, match="no model with that name"):
        train_mod.load_base_model("someone/no-such-model")


# -- T22: optimizer.pt loads safely -----------------------------------


def test_resume_refuses_malicious_optimizer_pickle(need_torch, tmp_path):
    import os
    import pickle

    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project("tiny", "proof", settings={"epochs": 2})
    controller = TrainController()

    def stop_after_first_step(event):
        if event.get("type") == "step" and event["step"] >= 1:
            controller.request_stop()

    train_project(
        store, "tiny", "proof",
        on_event=stop_after_first_step,
        controller=controller,
        _model_loader=tiny_model_and_tokenizer,
        _dtype="float32",
    )
    ckpt = store.project_dir("tiny", "proof") / "checkpoints" / "step-1"
    assert (ckpt / "optimizer.pt").is_file()
    marker = tmp_path / "pwned"

    class Boom:
        def __reduce__(self):
            return (os.system, (f"touch {marker}",))

    # A crafted optimizer.pt carrying a pickle payload, as a hostile
    # export package could: loading it must refuse, never execute.
    (ckpt / "optimizer.pt").write_bytes(
        pickle.dumps(
            {
                "optimizer": Boom(),
                "step": 1,
                "epoch": 1,
                "examples_seen_in_epoch": 0,
            }
        )
    )
    with pytest.raises(StellaError, match="cannot be loaded safely"):
        train_project(
            store, "tiny", "proof",
            resume=True,
            _model_loader=tiny_model_and_tokenizer,
            _dtype="float32",
        )
    assert not marker.exists()


def test_no_torch_load_runs_unsafe():
    # Audit pin (T22): the only torch.load in the tree is the resume
    # path, and it loads with weights_only=True.
    text = (ROOT / "stella" / "train.py").read_text()
    assert text.count("torch.load(") == 1
    assert "weights_only=False" not in text
    call = text[text.index("torch.load("):]
    assert "weights_only=True" in call[:300]


# -- T99: completions are bound to max_seq_len ------------------------


def test_tokenize_bounds_overlong_completion():
    from stella.train import tokenize_example

    # The audit's probe: a 200-char completion at max_seq_len=64
    # used to come out as 202 tokens. Now it is bound to the cap.
    example = {
        "messages": [
            {"role": "user", "content": "Question?"},
            {"role": "assistant", "content": "A" * 200},
        ]
    }
    out = tokenize_example(FakeTokenizer(), example, 64)
    assert len(out["input_ids"]) == 64
    assert out["truncated"] is True
    # The head of the answer survives, and the end token closes it.
    assert out["input_ids"][-1] == 0  # eos
    assert out["labels"][-1] == 0
    # The prompt was dropped entirely (no room left); the labels
    # still mask exactly the prompt part (here: nothing).
    assert len(out["labels"]) == 64


def test_tokenize_normal_completion_unchanged():
    from stella.train import tokenize_example

    example = {
        "messages": [
            {"role": "user", "content": "Question?"},
            {"role": "assistant", "content": "Answer."},
        ]
    }
    out = tokenize_example(FakeTokenizer(), example, 64)
    assert out["truncated"] is False
    # Prompt (fallback render) + completion + eos, nothing cut.
    assert len(out["input_ids"]) == len("User: Question?\nAssistant:") + len(" Answer.") + 1
    assert out["input_ids"][-1] == 0
    assert out["labels"][: len("User: Question?\nAssistant:")] == (
        [-100] * len("User: Question?\nAssistant:")
    )


def test_tokenize_bounds_completion_without_eos():
    from stella.train import tokenize_example

    class NoEosTokenizer(FakeTokenizer):
        def __init__(self):
            super().__init__()
            self.eos_token_id = None

    example = {
        "messages": [
            {"role": "user", "content": "Q?"},
            {"role": "assistant", "content": "B" * 200},
        ]
    }
    out = tokenize_example(NoEosTokenizer(), example, 64)
    assert len(out["input_ids"]) == 64
    assert out["truncated"] is True


def test_training_loop_warns_on_cut_examples(need_torch, tmp_path):
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile(
        "tiny", ollama_tag="", role="test", base_ref="test/tiny-model"
    )
    rows = [
        {"prompt": f"Question {i}?", "completion": "Long answer " * 20}
        for i in range(4)
    ]
    data = write_dataset(tmp_path / "long.jsonl", rows)
    store.create_project(
        "tiny", "proof",
        dataset_ref=str(data),
        settings={
            "epochs": 1,
            "batch_size": 1,
            "grad_accum": 1,
            "rank": 2,
            "max_seq_len": 128,
            "checkpoint_steps": 0,
            "val_fraction": 0.25,
            "warmup_steps": 1,
            "seed": 42,
        },
    )
    events = []

    def long_loader():
        # The stock tiny model has 64 positions; the cut sequences
        # are 128 tokens, so this loader widens the positions.
        from transformers import GPT2Config, GPT2LMHeadModel

        config = GPT2Config(
            vocab_size=256, n_layer=2, n_head=2, n_embd=64,
            n_positions=256, n_ctx=256,
        )
        return GPT2LMHeadModel(config), FakeTokenizer()

    train_project(
        store, "tiny", "proof",
        on_event=events.append,
        _model_loader=long_loader,
        _dtype="float32",
    )
    warnings = [e for e in events if e["type"] == "warning"]
    assert len(warnings) == 1
    # 4 rows, 1 val: 3 train rows were cut to fit.
    assert "3 example(s)" in warnings[0]["message"]
    assert "128" in warnings[0]["message"]


# -- T28: the RAM guard estimates before loading anything ------------


def _fake_model_dir(tmp_path, *, total_size=3_460_000_000, dtype="bfloat16"):
    """A local HF folder with a config + a safetensors index, but no
    weights: enough to estimate from, impossible to load from."""
    d = tmp_path / "fake-model"
    d.mkdir()
    (d / "config.json").write_text(
        json.dumps(
            {
                "model_type": "lfm3",
                "hidden_size": 2048,
                "num_hidden_layers": 24,
                "intermediate_size": 8192,
                "vocab_size": 128000,
                "torch_dtype": dtype,
            }
        ),
        encoding="utf-8",
    )
    (d / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "metadata": {"total_size": total_size},
                "weight_map": {"w": "model-00001-of-00001.safetensors"},
            }
        ),
        encoding="utf-8",
    )
    return d


def test_load_model_metadata_local_dir(tmp_path):
    from stella.train import load_model_metadata

    d = _fake_model_dir(tmp_path)
    meta = load_model_metadata(str(d))
    assert meta["hidden_size"] == 2048
    assert meta["num_layers"] == 24
    assert meta["intermediate_size"] == 8192
    assert meta["base_bytes"] == 3_460_000_000
    assert meta["bytes_per_param"] == 2
    assert meta["params"] == 1_730_000_000


def test_load_model_metadata_single_safetensors(tmp_path):
    from stella.train import load_model_metadata

    d = tmp_path / "single"
    d.mkdir()
    (d / "config.json").write_text(
        json.dumps(
            {
                "hidden_size": 512,
                "num_hidden_layers": 6,
                "intermediate_size": 2048,
                "torch_dtype": "float32",
            }
        ),
        encoding="utf-8",
    )
    (d / "model.safetensors").write_bytes(b"x" * 1000)
    meta = load_model_metadata(str(d))
    assert meta["base_bytes"] == 1000
    assert meta["bytes_per_param"] == 4
    assert meta["params"] == 250


def test_load_model_metadata_gpt2_style_config(tmp_path):
    from stella.train import load_model_metadata

    d = tmp_path / "gpt2ish"
    d.mkdir()
    (d / "config.json").write_text(
        json.dumps(
            {
                "n_embd": 64,
                "n_layer": 2,
                "vocab_size": 256,
                "torch_dtype": "float32",
            }
        ),
        encoding="utf-8",
    )
    (d / "model.safetensors").write_bytes(b"x" * 800)
    meta = load_model_metadata(str(d))
    assert meta["hidden_size"] == 64
    assert meta["num_layers"] == 2
    assert meta["intermediate_size"] == 256  # hidden * 4 fallback
    assert meta["params"] == 200


def test_load_model_metadata_missing_config(tmp_path):
    from stella.train import load_model_metadata

    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(StellaError, match="does not hold a model"):
        load_model_metadata(str(d))


def test_load_model_metadata_no_weights(tmp_path):
    from stella.train import load_model_metadata

    d = tmp_path / "noweights"
    d.mkdir()
    (d / "config.json").write_text(
        json.dumps({"hidden_size": 64, "num_hidden_layers": 2}),
        encoding="utf-8",
    )
    with pytest.raises(StellaError, match="no weight files"):
        load_model_metadata(str(d))


def test_estimate_training_from_metadata_lfm3_fits(tmp_path):
    from stella.train import estimate_training_from_metadata

    d = _fake_model_dir(tmp_path)
    total, breakdown = estimate_training_from_metadata(
        str(d), {"rank": 8, "max_seq_len": 1024, "batch_size": 1}
    )
    assert total < 8 * 1024**3
    assert breakdown["base_weights"] == 3_460_000_000
    # The LoRA estimate assumes all 7 targets: ~9M trainable for
    # LFM3 at rank 8 (the old hand-counted figure was 8.1M).
    assert breakdown["optimizer_states"] > 0


def test_estimate_lora_params_math():
    from stella.train import estimate_lora_params

    # rank 2, hidden 64, intermediate 256, 2 layers:
    # per layer 2 * (8*64 + 3*(64+256)) = 2 * 1472 = 2944; x2 = 5888.
    assert estimate_lora_params(
        hidden_size=64, intermediate_size=256, num_layers=2, rank=2
    ) == 5888


def test_train_refuses_before_loading_when_it_wont_fit(
    monkeypatch, tmp_path
):
    # A model that cannot fit is refused before any load: the loader
    # is booby-trapped, so a load attempt would explode instead of
    # raising the RAM error. No torch needed — nothing loads.
    import stella.train as train_mod
    from stella.model import Store

    monkeypatch.setattr(train_mod, "require_training_deps", lambda: None)
    monkeypatch.setattr(
        train_mod, "load_base_model",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("the base was loaded")
        ),
    )
    d = _fake_model_dir(tmp_path, total_size=20_000_000_000)
    store = Store(tmp_path / "home")
    store.create_profile("big", base_ref=str(d))
    data = write_dataset(tmp_path / "d.jsonl", prompt_rows(4))
    store.create_project("big", "proof", dataset_ref=str(data))
    with pytest.raises(StellaError, match="over the 8.00 GB ceiling"):
        train_project(store, "big", "proof")


def test_train_metadata_estimate_then_loads_tiny_model(need_torch, tmp_path):
    # The fits path, end to end with no injected loader: the
    # metadata estimate runs on a real saved tiny model, it fits,
    # the model loads, and the run completes.
    from stella.model import Store

    base, tokenizer = tiny_model_and_tokenizer()
    model_dir = tmp_path / "tiny-model"
    base.save_pretrained(str(model_dir))
    tokenizer.save_pretrained(str(model_dir))
    store = Store(tmp_path / "home")
    store.create_profile("tiny", base_ref=str(model_dir))
    data = write_dataset(tmp_path / "d.jsonl", prompt_rows(4))
    store.create_project(
        "tiny", "proof",
        dataset_ref=str(data),
        settings={
            "epochs": 1,
            "batch_size": 1,
            "grad_accum": 1,
            "rank": 2,
            "max_seq_len": 128,
            "checkpoint_steps": 0,
            "val_fraction": 0.25,
            "warmup_steps": 1,
            "seed": 42,
        },
    )
    summary = train_project(store, "tiny", "proof", _dtype="float32")
    assert summary["steps"] == 3
    assert summary["stopped"] is False
    assert (store.project_dir("tiny", "proof") / "adapter").is_dir()
    assert store.get_project("tiny", "proof")["status"] == "done"


def test_remote_metadata_from_fetched_files(monkeypatch, tmp_path):
    # The Hub path, with the network replaced by local files.
    import stella.train as train_mod
    from stella.train import load_model_metadata

    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "hidden_size": 1024,
                "num_hidden_layers": 12,
                "intermediate_size": 4096,
                "torch_dtype": "bfloat16",
            }
        ),
        encoding="utf-8",
    )
    index_file = tmp_path / "index.json"
    index_file.write_text(
        json.dumps({"metadata": {"total_size": 2_000_000_000}}),
        encoding="utf-8",
    )

    def fake_fetch(repo, filename):
        if filename == "config.json":
            return config_file
        if filename == "model.safetensors.index.json":
            return index_file
        raise FileNotFoundError(filename)

    monkeypatch.setattr(train_mod, "_fetch_hf_file", fake_fetch)
    meta = load_model_metadata("someone/some-model")
    assert meta["params"] == 1_000_000_000
    assert meta["hidden_size"] == 1024


def test_remote_metadata_unreadable_config_refuses(monkeypatch):
    import stella.train as train_mod
    from stella.train import load_model_metadata

    def fake_fetch(repo, filename):
        raise ConnectionError("no network here")

    monkeypatch.setattr(train_mod, "_fetch_hf_file", fake_fetch)
    with pytest.raises(StellaError, match="could not check whether"):
        load_model_metadata("someone/some-model")


# -- T33: every split keeps at least one validation row --------------


@pytest.mark.parametrize("n", [2, 3, 4, 5, 6])
def test_split_keeps_at_least_one_val_row(n):
    examples = [{"prompt": f"Q{i}?", "completion": f"A{i}."} for i in range(n)]
    train, val = split_dataset(examples, 0.1, 42)
    assert len(val) >= 1
    assert len(train) >= 1
    assert len(train) + len(val) == n
    # No row is in both halves, none is lost.
    assert {id(x) for x in train}.isdisjoint({id(x) for x in val})


def test_split_two_examples_is_one_and_one():
    # The case load_dataset promises: "1 to train on, 1 to
    # validate". Before T33 it validated on 0.
    examples = [
        {"prompt": "Q0?", "completion": "A0."},
        {"prompt": "Q1?", "completion": "A1."},
    ]
    train, val = split_dataset(examples, 0.1, 42)
    assert len(train) == 1
    assert len(val) == 1


# -- T32: seeding — same seed, same adapter --------------------------


def _seeded_loader(seed=123):
    """A loader that builds the same random base every time: the
    base init itself is random, so the loader seeds it."""

    def load():
        import torch

        torch.manual_seed(seed)
        return tiny_model_and_tokenizer()

    return load


def _adapter_tensors(adapter_dir):
    from safetensors.torch import load_file

    return load_file(str(Path(adapter_dir) / "adapter_model.safetensors"))


def test_same_seed_trains_identical_adapters(need_torch, tmp_path):
    import torch
    from stella.model import Store

    summaries = []
    adapters = []
    for i in range(2):
        data_dir = tmp_path / f"d{i}"
        data_dir.mkdir()
        store = _tiny_project(Store(tmp_path / f"home{i}"), data_dir)
        summary = train_project(
            store, "tiny", "proof",
            _model_loader=_seeded_loader(), _dtype="float32",
        )
        summaries.append(summary)
        adapters.append(
            _adapter_tensors(
                store.project_dir("tiny", "proof") / "adapter"
            )
        )
    assert summaries[0]["final_loss"] == summaries[1]["final_loss"]
    assert adapters[0].keys() == adapters[1].keys()
    for key in adapters[0]:
        assert torch.equal(adapters[0][key], adapters[1][key]), key


def test_pause_resume_matches_uninterrupted(need_torch, tmp_path):
    # The audit's probe: pause after step 2, resume — pre-pause
    # losses matched, post-pause losses diverged (5.6149 vs
    # 5.6010) because the RNG state was not saved. Now the whole
    # run is bit-identical to an uninterrupted one.
    import torch
    from stella.model import Store

    def run(store_dir, pause_at=None):
        store_dir.mkdir(parents=True, exist_ok=True)
        store = _tiny_project(Store(store_dir), store_dir)
        store.update_project("tiny", "proof", settings={"epochs": 2})
        controller = TrainController()
        losses: list[float] = []

        def collect(event):
            if event.get("type") == "step":
                losses.append(event["loss"])
                if pause_at is not None and event["step"] >= pause_at:
                    controller.request_stop()

        summary = train_project(
            store, "tiny", "proof",
            on_event=collect, controller=controller,
            _model_loader=_seeded_loader(), _dtype="float32",
        )
        if pause_at is not None:
            assert summary["stopped"] is True
            assert summary["steps"] == pause_at
            resumed = train_project(
                store, "tiny", "proof", resume=True,
                on_event=collect,
                _model_loader=_seeded_loader(), _dtype="float32",
            )
            assert resumed["stopped"] is False
            assert resumed["steps"] == 6
        return losses, _adapter_tensors(
            store.project_dir("tiny", "proof") / "adapter"
        )

    plain_losses, plain_adapter = run(tmp_path / "plain")
    paused_losses, paused_adapter = run(tmp_path / "paused", pause_at=2)
    assert len(plain_losses) == 6
    assert plain_losses == paused_losses
    assert plain_adapter.keys() == paused_adapter.keys()
    for key in plain_adapter:
        assert torch.equal(plain_adapter[key], paused_adapter[key]), key


def test_checkpoint_saves_rng_state(need_torch, tmp_path):
    import torch
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    train_project(
        store, "tiny", "proof",
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    opt_file = (
        store.project_dir("tiny", "proof")
        / "checkpoints" / "step-3" / "optimizer.pt"
    )
    saved = torch.load(str(opt_file), map_location="cpu", weights_only=True)
    assert "rng_state" in saved
    assert saved["rng_state"].dtype == torch.uint8


def test_resume_without_rng_state_still_works(need_torch, tmp_path):
    # A pre-v0.10.0 checkpoint carries no RNG state: the resume
    # proceeds without it instead of crashing.
    import torch
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project("tiny", "proof", settings={"epochs": 2})
    controller = TrainController()

    def stop_after_first_step(event):
        if event.get("type") == "step" and event["step"] >= 1:
            controller.request_stop()

    train_project(
        store, "tiny", "proof",
        on_event=stop_after_first_step, controller=controller,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    ckpt = store.project_dir("tiny", "proof") / "checkpoints" / "step-1"
    opt_file = ckpt / "optimizer.pt"
    saved = torch.load(str(opt_file), map_location="cpu", weights_only=True)
    assert "rng_state" in saved
    del saved["rng_state"]
    torch.save(saved, opt_file)
    resumed = train_project(
        store, "tiny", "proof", resume=True,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert resumed["stopped"] is False
    assert resumed["steps"] == 6


# -- T56: --steps is a real cap --------------------------------------


def test_steps_cap_runs_exactly_n_steps(need_torch, tmp_path):
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project("tiny", "proof", settings={"epochs": 3})
    events: list[dict] = []
    summary = train_project(
        store, "tiny", "proof", max_steps=2,
        on_event=events.append,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    # 3 epochs x 3 steps = 9 on the schedule; the cap stops at 2,
    # mid-epoch — and that is completion, not a pause.
    assert summary["steps"] == 2
    assert summary["stopped"] is False
    assert summary["total_steps"] == 2
    assert store.get_project("tiny", "proof")["status"] == "done"
    assert (store.project_dir("tiny", "proof") / "adapter").is_dir()
    started = [e for e in events if e["type"] == "started"]
    assert started[0]["total_steps"] == 2
    assert len([e for e in events if e["type"] == "step"]) == 2
    assert any(e["type"] == "done" for e in events)


def test_steps_cap_larger_than_schedule_runs_schedule(need_torch, tmp_path):
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    summary = train_project(
        store, "tiny", "proof", max_steps=99,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert summary["steps"] == 3
    assert summary["total_steps"] == 3


@pytest.mark.parametrize("bad", [0, -1, -10])
def test_steps_zero_or_negative_refused(bad, tmp_path):
    # The engine refuses on its own, before the training deps are
    # even required — no torch needed for this test.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    with pytest.raises(StellaError, match="--steps must be at least 1"):
        train_project(store, "tiny", "proof", max_steps=bad)


def test_resume_with_steps_trains_exactly_n_more(need_torch, tmp_path):
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project("tiny", "proof", settings={"epochs": 2})
    controller = TrainController()

    def stop_after_first_step(event):
        if event.get("type") == "step" and event["step"] >= 1:
            controller.request_stop()

    first = train_project(
        store, "tiny", "proof",
        on_event=stop_after_first_step, controller=controller,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert first["steps"] == 1
    events: list[dict] = []
    resumed = train_project(
        store, "tiny", "proof", resume=True, max_steps=2,
        on_event=events.append,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    # 1 done + 2 more = 3 of the 6-step schedule. The cap is a
    # remaining-steps budget, so the new total is 3, not 2.
    assert resumed["steps"] == 3
    assert resumed["total_steps"] == 3
    assert resumed["stopped"] is False
    assert store.get_project("tiny", "proof")["status"] == "done"
    started = [e for e in events if e["type"] == "started"]
    assert started[0]["total_steps"] == 3


# -- T25: re-training a trained project refuses (or --force) ---------


def _adapter_bytes(project_dir):
    adapter = Path(project_dir) / "adapter"
    return {
        p.name: p.read_bytes()
        for p in sorted(adapter.iterdir())
        if p.is_file()
    }


def test_retrain_done_project_refuses_without_force(need_torch, tmp_path):
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    train_project(
        store, "tiny", "proof",
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert store.get_project("tiny", "proof")["status"] == "done"
    before = _adapter_bytes(store.project_dir("tiny", "proof"))
    with pytest.raises(StellaError, match="already trained"):
        train_project(
            store, "tiny", "proof",
            _model_loader=_seeded_loader(), _dtype="float32",
        )
    try:
        train_project(
            store, "tiny", "proof",
            _model_loader=_seeded_loader(), _dtype="float32",
        )
    except StellaError as exc:
        assert "--force" in str(exc)
    # The finished adapter is untouched, byte for byte.
    assert _adapter_bytes(store.project_dir("tiny", "proof")) == before


def test_retrain_done_project_with_force_retrains(need_torch, tmp_path):
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    train_project(
        store, "tiny", "proof",
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    summary = train_project(
        store, "tiny", "proof", force=True,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert summary["steps"] == 3
    assert summary["stopped"] is False
    assert store.get_project("tiny", "proof")["status"] == "done"


def test_resume_on_done_announces_extension(need_torch, tmp_path):
    # The audit's case: a --steps 2 proof run finishes (status
    # trained), then --resume extends it to the full schedule.
    # The run announces the extension + the new total first.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project("tiny", "proof", settings={"epochs": 3})
    first = train_project(
        store, "tiny", "proof", max_steps=2,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert first["steps"] == 2
    assert store.get_project("tiny", "proof")["status"] == "done"
    events: list[dict] = []
    resumed = train_project(
        store, "tiny", "proof", resume=True,
        on_event=events.append,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert resumed["steps"] == 9
    kinds = [e["type"] for e in events]
    assert "extending" in kinds
    # The announcement comes before the "started" line.
    assert kinds.index("extending") < kinds.index("started")
    extending = events[kinds.index("extending")]
    assert extending["trained_steps"] == 2
    assert extending["new_total"] == 9


def test_resume_on_paused_does_not_announce_extension(need_torch, tmp_path):
    # A resume on a merely paused project is normal, not an
    # extension: no announcement.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    store.update_project("tiny", "proof", settings={"epochs": 2})
    controller = TrainController()

    def stop_after_first_step(event):
        if event.get("type") == "step" and event["step"] >= 1:
            controller.request_stop()

    train_project(
        store, "tiny", "proof",
        on_event=stop_after_first_step, controller=controller,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert store.get_project("tiny", "proof")["status"] == "paused"
    events: list[dict] = []
    train_project(
        store, "tiny", "proof", resume=True,
        on_event=events.append,
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert "extending" not in [e["type"] for e in events]


def test_sleep_not_blocked_by_done_status(need_torch, tmp_path):
    # Sleep consolidates a trained project with update_status=False:
    # the T25 refusal must not block it.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    train_project(
        store, "tiny", "proof",
        _model_loader=_seeded_loader(), _dtype="float32",
    )
    assert store.get_project("tiny", "proof")["status"] == "done"
    cycle_dir = tmp_path / "cycle"
    summary = train_project(
        store, "tiny", "proof",
        _model_loader=_seeded_loader(), _dtype="float32",
        work_dir=cycle_dir, update_status=False,
    )
    assert summary["steps"] == 3
    assert (cycle_dir / "adapter").is_dir()
    assert store.get_project("tiny", "proof")["status"] == "done"


# -- T83: the pre-train dataset health check --------------------------


def _dataset_project(store, tmp_path, rows):
    """A project whose dataset is `rows` prompt/completion rows."""
    data = write_dataset(tmp_path / "data.jsonl", rows)
    store.create_profile("p1", base_ref="test/tiny-model")
    store.create_project("p1", "proj", dataset_ref=str(data))
    return store


def test_check_dataset_marks_tiny_dataset(tmp_path):
    # T83: a 3-example dataset is ok but tiny — the pre-train
    # check asks before starting on one.
    from stella.model import Store

    store = _dataset_project(
        Store(tmp_path / "home"), tmp_path, prompt_rows(3)
    )
    check = check_dataset(store, "p1", "proj", str(tmp_path / "data.jsonl"))
    assert check["status"] == "ok"
    assert check["count"] == 3
    assert check["tiny"] is True


def test_check_dataset_healthy_dataset_not_tiny(tmp_path):
    # T83: 20 examples is a healthy dataset — not tiny, with a
    # token estimate attached.
    from stella.model import Store

    store = _dataset_project(
        Store(tmp_path / "home"), tmp_path, prompt_rows(20)
    )
    check = check_dataset(store, "p1", "proj", str(tmp_path / "data.jsonl"))
    assert check["status"] == "ok"
    assert check["count"] == 20
    assert check["tiny"] is False
    assert check["est_tokens"] > 0


def test_check_dataset_estimates_tokens(tmp_path):
    # T83: the token estimate is chars / 4 — 4 rows of
    # "Question i?" (11 chars) + "Answer i." (9 chars) is 80
    # chars, about 20 tokens.
    from stella.model import Store

    store = _dataset_project(
        Store(tmp_path / "home"), tmp_path, prompt_rows(4)
    )
    check = check_dataset(store, "p1", "proj", str(tmp_path / "data.jsonl"))
    assert check["est_tokens"] == 20


def test_check_dataset_bad_rows_carry_no_token_estimate(tmp_path):
    # T83: a failing check reports the error, not numbers —
    # est_tokens stays 0 and tiny stays False.
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("p1", base_ref="test/tiny-model")
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"prompt": "a", "completion": "b"}\nnot json\n')
    store.create_project("p1", "proj", dataset_ref=str(bad))
    check = check_dataset(store, "p1", "proj", str(bad))
    assert check["status"] == "invalid"
    assert "line 2" in check["error"]
    assert check["est_tokens"] == 0
    assert check["tiny"] is False


# -- T84/T85: the pre-train estimate (RAM fit + steps + disk) ---------


def _fake_model_dir(path, total_size=3_460_000_000):
    """A local HF folder with a config + a weight-size index — no
    real weights, so the metadata read is fast and offline. The
    default size is an LFM3-shaped 1.7B bf16 base."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps({
        "hidden_size": 2048, "num_hidden_layers": 24,
        "intermediate_size": 8192, "torch_dtype": "bfloat16",
    }))
    (path / "model.safetensors.index.json").write_text(json.dumps({
        "metadata": {"total_size": total_size},
    }))
    return path


def _estimable_project(store, tmp_path, total_size=3_460_000_000, rows=20):
    """A project on a local fake model with a real dataset — the
    estimate runs entirely offline against it."""
    model_dir = _fake_model_dir(tmp_path / "model", total_size)
    data = write_dataset(tmp_path / "data.jsonl", prompt_rows(rows))
    store.create_profile("p1", base_ref=str(model_dir))
    store.create_project("p1", "proj", dataset_ref=str(data))
    return store


def test_estimate_run_fits_small_model(tmp_path):
    # T84/T85: an LFM3-shaped base on the defaults fits — and the
    # estimate names steps, disk, and time, not just RAM.
    from stella.model import Store

    store = _estimable_project(Store(tmp_path / "home"), tmp_path)
    estimate = estimate_run(store, "p1", "proj")
    assert estimate["fits"] is True
    assert estimate["ram_gb"] < 8.0
    # 20 rows, 2 held out: 18 train, batch 1, grad_accum 8 ->
    # 3 steps/epoch x 3 epochs.
    assert estimate["steps"] == 9
    assert estimate["dataset_count"] == 20
    assert estimate["train_examples"] == 18
    assert estimate["val_examples"] == 2
    assert estimate["disk_bytes"] > estimate["base_bytes"]
    assert estimate["time_note"]


def test_estimate_run_wont_fit_huge_model(tmp_path):
    # T84: a 100 GB base will not fit, and the estimate says so
    # without loading anything.
    from stella.model import Store

    store = _estimable_project(
        Store(tmp_path / "home"), tmp_path, total_size=100_000_000_000
    )
    estimate = estimate_run(store, "p1", "proj")
    assert estimate["fits"] is False
    assert estimate["ram_gb"] > 8.0


def test_estimate_run_never_loads_the_model(tmp_path, monkeypatch):
    # T85: the no-load proof — the estimate runs with the model
    # loader rigged to fail, and still answers.
    import stella.train as train_mod
    from stella.model import Store

    def _boom(*args, **kwargs):
        raise AssertionError("the estimate loaded the model")

    monkeypatch.setattr(train_mod, "load_base_model", _boom)
    store = _estimable_project(Store(tmp_path / "home"), tmp_path)
    estimate = estimate_run(store, "p1", "proj")
    assert estimate["fits"] is True


def test_estimate_run_needs_base_ref(tmp_path):
    # T84: with no base ref there is nothing to estimate from —
    # the estimate refuses instead of guessing.
    from stella.model import Store

    store = Store(tmp_path / "home")
    store.create_profile("p1")  # no base_ref
    data = write_dataset(tmp_path / "data.jsonl", prompt_rows(4))
    store.create_project("p1", "proj", dataset_ref=str(data))
    with pytest.raises(StellaError, match="base_ref"):
        estimate_run(store, "p1", "proj")


def test_estimate_run_refuses_bad_dataset(tmp_path):
    # T84/T85: a malformed dataset is refused with the bad line
    # named, like the pre-train check.
    from stella.model import Store

    store = Store(tmp_path / "home")
    model_dir = _fake_model_dir(tmp_path / "model")
    store.create_profile("p1", base_ref=str(model_dir))
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"prompt": "a", "completion": "b"}\nnot json\n')
    store.create_project("p1", "proj", dataset_ref=str(bad))
    with pytest.raises(StellaError, match="line 2"):
        estimate_run(store, "p1", "proj")


def test_format_estimate_names_fit_steps_and_disk(tmp_path):
    # T85: the dry-run report answers all three questions.
    from stella.model import Store

    store = _estimable_project(Store(tmp_path / "home"), tmp_path)
    report = format_estimate(estimate_run(store, "p1", "proj"))
    assert "RAM: about" in report
    assert "fits in 8.00 GB" in report
    assert "Steps: 9" in report
    assert "Disk: about" in report
    assert "Time: roughly" in report


def test_format_estimate_warns_when_it_wont_fit(tmp_path):
    # T85: an over-budget dry run warns before the run starts.
    from stella.model import Store

    store = _estimable_project(
        Store(tmp_path / "home"), tmp_path, total_size=100_000_000_000
    )
    report = format_estimate(estimate_run(store, "p1", "proj"))
    assert "will not fit in 8.00 GB" in report
    assert "will not fit this PC" in report


def test_format_estimate_short_shows_fit_not_settings(tmp_path):
    # T84/T16: the one-liner shows fit and time — no settings
    # (no rank, no seq len, no batch) anywhere in it.
    from stella.model import Store

    store = _estimable_project(Store(tmp_path / "home"), tmp_path)
    short = format_estimate_short(estimate_run(store, "p1", "proj"))
    assert short.startswith("Fits in 8 GB")
    assert "9 steps" in short
    assert "rank" not in short
    assert "seq" not in short
    assert "batch" not in short


# -- T96: the final val loss in the run summary -----------------------


def test_two_step_lora_run_reports_final_val_loss(need_torch, tmp_path):
    # T96: run_training_loop returns the final val loss, and the
    # training summary file carries it too.
    from stella.model import Store

    store = _tiny_project(Store(tmp_path / "home"), tmp_path)
    summary = train_project(
        store, "tiny", "proof",
        on_event=lambda event: None,
        _model_loader=tiny_model_and_tokenizer,
        _dtype="float32",
    )
    assert summary["final_val_loss"] is not None
    assert summary["final_loss"] is not None
    saved = json.loads(
        (
            store.project_dir("tiny", "proof")
            / "adapter" / "training_summary.json"
        ).read_text()
    )
    assert saved["final_val_loss"] == summary["final_val_loss"]
