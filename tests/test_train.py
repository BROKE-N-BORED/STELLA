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
    check_ram_fit,
    detect_target_modules,
    estimate_training_bytes,
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
            "max_seq_len": 64,
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
    assert store.get_project("tiny", "proof")["status"] == "trained"
    log_lines = (project_dir / "train_log.jsonl").read_text().splitlines()
    assert len([json.loads(line) for line in log_lines
                if "loss" in json.loads(line)]) == 3
    checkpoints = list_checkpoints(store, "tiny", "proof")
    assert [c["step"] for c in checkpoints] == [1, 2, 3]
    kinds = {e["type"] for e in events}
    assert {"started", "step", "checkpoint", "val", "done"} <= kinds


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
    assert store.get_project("tiny", "proof")["status"] == "trained"
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
