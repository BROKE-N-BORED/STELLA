"""STELLA training engine — micro-LoRA fine-tuning on CPU.

The proof loop (Item 3): take a base model from Hugging Face, LoRA-tune
it on a small JSONL dataset, checkpoint as it goes, and land a finished
adapter in the project. The adapter then goes through stella/gguf.py to
become a GGUF + Ollama model.

Design rules for this machine (Ryzen 3 3250U, 8 GB RAM, no GPU):

- LoRA only by default. A full fine-tune of a 1.7B model needs ~28 GB
  of optimizer state alone — the RAM guard refuses it outright.
- CPU only, batch 1, gradient accumulation. Steps are slow; that is
  expected. Hours for a few hundred examples, checkpointed throughout.
- Base weights load in bf16; the LoRA adapter trains in fp32 under a
  CPU bf16 autocast. That is the recipe that fits 8 GB.
- Training NEVER starts from a GGUF or an Ollama tag — fine-tuning
  needs HF transformers weights. `base_ref` on the profile must be a
  Hugging Face repo id (e.g. LiquidAI/LFM3-1.7B) or a local HF folder.
- torch / transformers / peft are OPTIONAL imports. This module must
  import cleanly on a base Stella install (PySide6 only); every
  function that needs the training stack raises a StellaError naming
  `bash install-training.sh` when the stack is missing.

LFM3 note: LiquidAI/LFM3-1.7B ships remote modeling code (its
config.json maps AutoModel to modeling_lfm3.py), so loading uses
trust_remote_code=True. That runs code from the model repo — the
standard Hugging Face flow for this model, and the repo is Liquid AI's
own. The config was confirmed live from huggingface.co (model_type
"lfm3", 24 layers, hidden 2048, vocab 128000, BF16, 1.73B params).
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
from pathlib import Path

from .model import STELLA_VERSION, StellaError, Store

# First proof target — confirmed from the live model card, not guessed.
LFM3_HF_REPO = "LiquidAI/LFM3-1.7B"

TRAINING_DEPS = ("torch", "transformers", "peft", "accelerate")
TRAINING_INSTALL_HINT = (
    "Training needs the training packages (torch, transformers, peft, "
    "accelerate). Run this once in the Stella folder:\n"
    "  bash install-training.sh"
)

# 8 GB is the hard ceiling on Joshua's PC; 1 GB stays reserved for the
# OS, Python, and the tokenizer so training never swaps the machine dead.
RAM_LIMIT_BYTES = 8 * 1024**3
RAM_HEADROOM_BYTES = 1 * 1024**3

# LoRA target suffixes, checked against the model's real module names.
# Covers standard attention/MLP projections, GPT-2 style, and LLaMA style.
TARGET_SUFFIXES = (
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
    "c_attn", "c_proj", "c_fc",
    "Wqkv", "fc1", "fc2",
)

DEFAULT_TRAIN = {
    "method": "lora",
    "rank": 8,
    "learning_rate": 0.0002,
    "epochs": 3,
    "batch_size": 1,
    "grad_accum": 8,
    "max_seq_len": 1024,
    "checkpoint_steps": 50,
    "val_fraction": 0.1,
    "warmup_steps": 5,
    "seed": 42,
}

# Dataset roles, in order of appearance in a conversation.
DATASET_ROLES = ("system", "user", "assistant")


# -- dependency gate ------------------------------------------------

def training_deps_missing() -> list[str]:
    """Which training packages are not installed (empty = ready).

    Uses find_spec, not import — importing torch takes seconds, and
    this gate runs on every Train click and every `stella train`.
    The real imports happen later, when training actually starts.
    """
    import importlib.util

    return [
        name for name in TRAINING_DEPS
        if importlib.util.find_spec(name) is None
    ]


def require_training_deps() -> None:
    missing = training_deps_missing()
    if missing:
        raise StellaError(
            f"Training packages missing: {', '.join(missing)}.\n"
            + TRAINING_INSTALL_HINT
        )


# -- dataset --------------------------------------------------------

def _validate_messages(messages: object, line_no: int) -> list[dict]:
    if not isinstance(messages, list) or len(messages) < 2:
        raise StellaError(
            f"dataset line {line_no}: 'messages' must be a list of at "
            "least 2 messages"
        )
    cleaned = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise StellaError(
                f"dataset line {line_no}: message {i} is not an object"
            )
        role = msg.get("role")
        content = msg.get("content")
        if role not in DATASET_ROLES:
            raise StellaError(
                f"dataset line {line_no}: message {i} has role {role!r} "
                f"(must be one of {', '.join(DATASET_ROLES)})"
            )
        if not isinstance(content, str) or not content.strip():
            raise StellaError(
                f"dataset line {line_no}: message {i} has empty content"
            )
        cleaned.append({"role": role, "content": content})
    if cleaned[-1]["role"] != "assistant":
        raise StellaError(
            f"dataset line {line_no}: the last message must be from the "
            "assistant (that is what the model learns to write)"
        )
    return cleaned


def validate_dataset_row(row: object, line_no: int) -> tuple[str, list[dict]]:
    """Validate one dataset row. Returns (format, messages).

    Shared by load_dataset (whole-file validation) and the sleep
    phase (per-row validation of dreamed examples) — one rule for
    what a row is, wherever the row comes from.
    """
    if not isinstance(row, dict):
        raise StellaError(f"dataset line {line_no}: must be a JSON object")
    if "messages" in row:
        return "messages", _validate_messages(row["messages"], line_no)
    if "prompt" in row and "completion" in row:
        prompt = row["prompt"]
        completion = row["completion"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise StellaError(f"dataset line {line_no}: empty prompt")
        if not isinstance(completion, str) or not completion.strip():
            raise StellaError(f"dataset line {line_no}: empty completion")
        return "prompt", [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": completion},
        ]
    raise StellaError(
        f"dataset line {line_no}: needs 'messages' or "
        "'prompt' + 'completion'"
    )


def load_dataset(path: str | Path) -> tuple[list[dict], dict]:
    """Read + validate a JSONL dataset.

    Two formats, one per file (mixed files are rejected):

    - prompt/completion: {"prompt": "...", "completion": "..."}
    - messages: {"messages": [{"role": "user", "content": "..."},
      {"role": "assistant", "content": "..."}]}

    Returns (examples, info). Each example is normalized to
    {"messages": [...]} so the trainer has one shape to handle.
    """
    path = Path(path)
    if not path.is_file():
        raise StellaError(f"dataset not found: {path}")
    examples: list[dict] = []
    fmt: str | None = None
    prompt_chars = 0
    completion_chars = 0
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StellaError(
                f"dataset line {line_no}: not valid JSON: {exc}"
            ) from exc
        row_fmt, messages = validate_dataset_row(row, line_no)
        if fmt is None:
            fmt = row_fmt
        elif fmt != row_fmt:
            raise StellaError(
                f"dataset line {line_no}: mixed formats. The file "
                f"started as {fmt!r} but this row is {row_fmt!r}"
            )
        prompt_chars += sum(len(m["content"]) for m in messages[:-1])
        completion_chars += len(messages[-1]["content"])
        examples.append({"messages": messages})
    if len(examples) < 2:
        raise StellaError(
            f"dataset has {len(examples)} example(s). At least 2 are "
            "needed (1 to train on, 1 to validate)"
        )
    info = {
        "path": str(path),
        "format": fmt,
        "count": len(examples),
        "avg_prompt_chars": round(prompt_chars / len(examples)),
        "avg_completion_chars": round(completion_chars / len(examples)),
    }
    return examples, info


def split_dataset(
    examples: list[dict], val_fraction: float = 0.1, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    """Deterministic train/validate split (same seed = same split)."""
    order = list(range(len(examples)))
    random.Random(seed).shuffle(order)
    n_val = int(round(len(examples) * val_fraction))
    n_val = max(0, min(n_val, len(examples) - 1))
    val_idx = set(order[:n_val])
    train = [ex for i, ex in enumerate(examples) if i not in val_idx]
    val = [ex for i, ex in enumerate(examples) if i in val_idx]
    return train, val


def resolve_dataset_ref(
    store: Store, profile: str, project: str, ref: str
) -> Path:
    """Find a dataset by ref: absolute path, project dir, home dir,
    or the bundled Stella data dir (for the sample dataset)."""
    candidates = []
    raw = Path(ref).expanduser()
    candidates.append(raw)
    if not raw.is_absolute():
        candidates.append(store.project_dir(profile, project) / ref)
        candidates.append(store.home / ref)
        app_data = Path(__file__).resolve().parent.parent / "data" / ref
        candidates.append(app_data)
    for cand in candidates:
        if cand.is_file():
            return cand
    looked = "\n  ".join(str(c) for c in candidates)
    raise StellaError(f"dataset not found: {ref!r}\nLooked in:\n  {looked}")


# -- RAM guard ------------------------------------------------------

def estimate_training_bytes(
    *,
    params: int,
    trainable_params: int,
    base_bytes_per_param: int = 2,
    seq_len: int = 1024,
    batch_size: int = 1,
    hidden_size: int = 2048,
    num_layers: int = 24,
) -> tuple[int, dict]:
    """Estimate peak training RAM. Returns (total_bytes, breakdown).

    Math, all in bytes:
    - base weights: params x bytes-per-param (bf16 = 2)
    - gradients: trainable params x 4 (fp32, trainable only)
    - AdamW states: trainable params x 8 (fp32 m + v)
    - fp32 master copy of trainable weights: trainable x 4
    - activations: batch x seq x hidden x layers x 34 (stored tensors
      per layer for backward, deliberately conservative)
    - headroom: 1 GB for the OS, Python, tokenizer
    """
    weights = params * base_bytes_per_param
    grads = trainable_params * 4
    optimizer = trainable_params * 8
    master = trainable_params * 4
    activations = batch_size * seq_len * hidden_size * num_layers * 34
    total = weights + grads + optimizer + master + activations + RAM_HEADROOM_BYTES
    breakdown = {
        "base_weights": weights,
        "gradients": grads,
        "optimizer_states": optimizer,
        "trainable_master_copy": master,
        "activations": activations,
        "headroom": RAM_HEADROOM_BYTES,
        "total": total,
    }
    return total, breakdown


def _gb(n: int) -> str:
    return f"{n / 1024**3:.2f} GB"


def check_ram_fit(estimate_bytes: int, limit_bytes: int = RAM_LIMIT_BYTES) -> None:
    """Refuse to train if the estimate does not fit the RAM ceiling."""
    if estimate_bytes > limit_bytes:
        raise StellaError(
            f"Training would need about {_gb(estimate_bytes)} of RAM, "
            f"over the {_gb(limit_bytes)} ceiling on this PC.\n"
            "Lower max_seq_len or the LoRA rank, or pick a smaller base "
            "model. A full fine-tune of a 1.7B model does not fit, ever: "
            "its optimizer state alone is ~28 GB."
        )


# -- model loading --------------------------------------------------

def _looks_like_gguf_or_tag(base_ref: str) -> str | None:
    """Return why a base_ref is NOT trainable HF weights, or None."""
    if base_ref.lower().endswith(".gguf"):
        return "a GGUF file"
    if Path(base_ref).expanduser().exists():
        return None  # a local folder — assume HF weights live there
    if "/" not in base_ref:
        return "an Ollama tag, not a Hugging Face repo"
    return None


def load_base_model(base_ref: str, *, dtype: str = "bfloat16"):
    """Load tokenizer + base model from HF weights (never GGUF).

    Returns (model, tokenizer). dtype is "bfloat16" for real models
    (fits 8 GB) or "float32" for tiny test models.
    """
    require_training_deps()
    bad = _looks_like_gguf_or_tag(base_ref)
    if bad is not None:
        raise StellaError(
            f"base_ref {base_ref!r} is {bad} . Training needs Hugging "
            f"Face transformers weights. Set base_ref to a repo id "
            f"like {LFM3_HF_REPO!r}, or a local folder of HF weights."
        )
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch_dtype = torch.bfloat16 if dtype == "bfloat16" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(
        base_ref, trust_remote_code=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        base_ref, torch_dtype=torch_dtype, trust_remote_code=True,
    )
    model.config.use_cache = False  # no KV cache while training
    return model, tokenizer


def detect_target_modules(model) -> list[str]:
    """Find the LoRA target modules this model actually has.

    Scans the model's linear layers and returns the leaf names that
    match known projection suffixes (q_proj, k_proj, ...). Raises if
    none match, naming what the model does have.
    """
    import torch

    found: set[str] = set()
    all_linear: set[str] = set()
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.Linear):
            leaf = name.rsplit(".", 1)[-1]
            all_linear.add(leaf)
            if leaf in TARGET_SUFFIXES:
                found.add(leaf)
    # GPT-2 style Conv1D layers are also LoRA-able (PEFT handles them).
    try:
        from transformers.pytorch_utils import Conv1D
    except ImportError:  # transformers moved it in some versions
        Conv1D = None  # type: ignore[assignment]
    if Conv1D is not None:
        for name, module in model.named_modules():
            if isinstance(module, Conv1D):
                leaf = name.rsplit(".", 1)[-1]
                all_linear.add(leaf)
                if leaf in TARGET_SUFFIXES:
                    found.add(leaf)
    if not found:
        raise StellaError(
            "No LoRA target modules found in this model. Its linear "
            f"layers are named: {', '.join(sorted(all_linear)) or 'none'}"
        )
    return sorted(found)


# -- tokenization ---------------------------------------------------

def _render_fallback(messages: list[dict]) -> tuple[str, str]:
    """Plain-text prompt/completion split when the tokenizer has no
    chat template: 'Role: content' lines, assistant last."""
    prompt_lines = []
    for msg in messages[:-1]:
        prompt_lines.append(f"{msg['role'].capitalize()}: {msg['content']}")
    prompt_lines.append("Assistant:")
    prompt = "\n".join(prompt_lines)
    completion = " " + messages[-1]["content"]
    return prompt, completion


def tokenize_example(tokenizer, example: dict, max_seq_len: int) -> dict:
    """Tokenize one example into input_ids + labels.

    The prompt part is masked (-100) so loss is only on the completion
    — the model learns to WRITE the answer, not to predict the question.
    If the pair is too long, the prompt is cut from the left and the
    completion is kept whole.
    """
    messages = example["messages"]
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            prompt_text = tokenizer.apply_chat_template(
                messages[:-1], tokenize=False, add_generation_prompt=True
            )
            completion_text = messages[-1]["content"]
        except Exception:
            prompt_text, completion_text = _render_fallback(messages)
    else:
        prompt_text, completion_text = _render_fallback(messages)
    prompt_ids = tokenizer.encode(prompt_text)
    completion_ids = tokenizer.encode(completion_text, add_special_tokens=False)
    eos = tokenizer.eos_token_id
    if eos is not None:
        completion_ids = completion_ids + [eos]
    if len(prompt_ids) + len(completion_ids) > max_seq_len:
        keep = max(0, max_seq_len - len(completion_ids))
        prompt_ids = prompt_ids[-keep:] if keep else []
    input_ids = prompt_ids + completion_ids
    labels = [-100] * len(prompt_ids) + list(completion_ids)
    return {"input_ids": input_ids, "labels": labels}


def _collate(tokenizer, batch: list[dict]):
    """Pad one batch. Returns (input_ids, attention_mask, labels)."""
    import torch

    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        pad_id = tokenizer.eos_token_id or 0
    max_len = max(len(b["input_ids"]) for b in batch)
    input_ids = []
    attention = []
    labels = []
    for b in batch:
        n = max_len - len(b["input_ids"])
        input_ids.append(b["input_ids"] + [pad_id] * n)
        attention.append([1] * len(b["input_ids"]) + [0] * n)
        labels.append(b["labels"] + [-100] * n)
    return (
        torch.tensor(input_ids, dtype=torch.long),
        torch.tensor(attention, dtype=torch.long),
        torch.tensor(labels, dtype=torch.long),
    )


def evaluate_loss(
    model,
    tokenizer,
    examples: list[dict],
    *,
    max_seq_len: int = 1024,
    batch_size: int = 1,
    limit: int = 50,
) -> float | None:
    """Average completion loss of `model` on `examples` (no gradients).

    One evaluation path, shared by the training loop's per-epoch
    validation and the sleep phase's replay check. Returns None when
    there are no examples. Restores the model's train/eval mode
    afterwards, so calling it mid-training is safe.
    """
    import torch

    if not examples:
        return None
    was_training = model.training
    tokenized = [
        tokenize_example(tokenizer, ex, max_seq_len) for ex in examples
    ]
    use_bf16 = next(model.parameters()).dtype == torch.bfloat16
    model.eval()
    total_loss = 0.0
    count = 0
    try:
        with torch.no_grad():
            for i in range(0, min(len(tokenized), limit), batch_size):
                batch = tokenized[i : i + batch_size]
                input_ids, attention, labels = _collate(tokenizer, batch)
                with torch.autocast(
                    device_type="cpu", dtype=torch.bfloat16, enabled=use_bf16
                ):
                    out = model(
                        input_ids=input_ids,
                        attention_mask=attention,
                        labels=labels,
                    )
                total_loss += float(out.loss.detach()) * len(batch)
                count += len(batch)
    finally:
        if was_training:
            model.train()
    return total_loss / max(1, count)


# -- checkpoints ----------------------------------------------------

def list_checkpoints(
    store: Store, profile: str, project: str, *, ckpt_dir: Path | None = None
) -> list[dict]:
    """Checkpoints for a project, oldest first.

    `ckpt_dir` overrides the checkpoint folder — the sleep phase
    lists the checkpoints of one cycle, not the whole project.
    """
    if ckpt_dir is None:
        ckpt_dir = store.project_dir(profile, project) / "checkpoints"
    out = []
    if not ckpt_dir.is_dir():
        return out
    for d in sorted(ckpt_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("step-"):
            continue
        state_file = d / "training_state.json"
        if not state_file.is_file():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append(
            {
                "step": state.get("step", 0),
                "path": str(d),
                "loss": state.get("loss"),
                "epoch": state.get("epoch"),
            }
        )
    out.sort(key=lambda c: c["step"])
    return out


def _save_checkpoint(model, optimizer, ckpt_dir: Path, state: dict) -> None:
    import torch

    ckpt_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(ckpt_dir))
    torch.save(
        {
            "optimizer": optimizer.state_dict(),
            "step": state["step"],
            "epoch": state["epoch"],
            "examples_seen_in_epoch": state["examples_seen_in_epoch"],
        },
        ckpt_dir / "optimizer.pt",
    )
    (ckpt_dir / "training_state.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _append_log(project_dir: Path, record: dict) -> None:
    with (project_dir / "train_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


# -- the training loop ----------------------------------------------

class TrainController:
    """Pause handle: the GUI calls request_stop(), the loop checks
    stop_requested after each optimizer step and checkpoints cleanly."""

    def __init__(self):
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    @property
    def stop_requested(self) -> bool:
        return self._stop


def _lr_multiplier(step: int, warmup: int, total: int) -> float:
    if total <= 0:
        return 1.0
    if step < warmup:
        return (step + 1) / max(1, warmup)
    return max(0.0, 1.0 - (step - warmup) / max(1, total - warmup))


def run_training_loop(
    model,
    tokenizer,
    train_examples: list[dict],
    val_examples: list[dict],
    config: dict,
    project_dir: Path,
    *,
    on_event=None,
    controller: TrainController | None = None,
    start_step: int = 0,
    start_epoch: int = 0,
    skip_in_epoch: int = 0,
    optimizer=None,
) -> dict:
    """The loop itself, separated from model loading so tests can pass
    a tiny random model. Returns a summary dict."""
    import torch

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    batch_size = int(config.get("batch_size", 1))
    grad_accum = int(config.get("grad_accum", 8))
    max_seq_len = int(config.get("max_seq_len", 1024))
    epochs = int(config.get("epochs", 3))
    lr = float(config.get("learning_rate", 0.0002))
    rank = int(config.get("rank", 8))
    warmup = int(config.get("warmup_steps", 5))
    checkpoint_steps = int(config.get("checkpoint_steps", 50))
    seed = int(config.get("seed", 42))
    use_bf16 = next(model.parameters()).dtype == torch.bfloat16

    steps_per_epoch = max(1, math.ceil(len(train_examples) / (batch_size * grad_accum)))
    total_steps = steps_per_epoch * epochs
    if start_step >= total_steps:
        raise StellaError(
            f"already at step {start_step} of {total_steps}. Nothing left to train"
        )

    if optimizer is None:
        trainable = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(trainable, lr=lr, weight_decay=0.0)

    tokenized = [tokenize_example(tokenizer, ex, max_seq_len) for ex in train_examples]

    def evaluate() -> float | None:
        return evaluate_loss(
            model, tokenizer, val_examples,
            max_seq_len=max_seq_len, batch_size=batch_size, limit=50,
        )

    emit({"type": "started", "total_steps": total_steps, "rank": rank})
    model.train()
    step = start_step
    stopped = False
    last_loss: float | None = None
    epoch = start_epoch
    examples_seen = skip_in_epoch
    for epoch in range(start_epoch, epochs):
        order = list(range(len(tokenized)))
        random.Random(seed + epoch).shuffle(order)
        if epoch == start_epoch and skip_in_epoch:
            order = order[skip_in_epoch:]
        examples_seen = skip_in_epoch if epoch == start_epoch else 0
        micro_idx = 0
        accum_loss = 0.0
        accum_count = 0
        while micro_idx < len(order):
            batch_idx = order[micro_idx : micro_idx + batch_size]
            micro_idx += len(batch_idx)
            examples_seen += len(batch_idx)
            batch = [tokenized[i] for i in batch_idx]
            input_ids, attention, labels = _collate(tokenizer, batch)
            with torch.autocast(
                device_type="cpu", dtype=torch.bfloat16, enabled=use_bf16
            ):
                out = model(
                    input_ids=input_ids, attention_mask=attention, labels=labels
                )
                loss = out.loss / grad_accum
            loss.backward()
            accum_loss += float(out.loss.detach())
            accum_count += 1
            is_last_micro = micro_idx >= len(order)
            if accum_count % grad_accum != 0 and not is_last_micro:
                continue
            # Optimizer step.
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0
            )
            mult = _lr_multiplier(step, warmup, total_steps)
            for group in optimizer.param_groups:
                group["lr"] = lr * mult
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            last_loss = accum_loss / max(1, accum_count)
            accum_loss = 0.0
            accum_count = 0
            step += 1
            record = {
                "step": step,
                "epoch": epoch + 1,
                "loss": round(last_loss, 4),
                "lr": round(lr * mult, 8),
            }
            _append_log(project_dir, record)
            emit(
                {
                    "type": "step",
                    "step": step,
                    "total_steps": total_steps,
                    "epoch": epoch + 1,
                    "loss": last_loss,
                    "lr": lr * mult,
                }
            )
            if checkpoint_steps > 0 and step % checkpoint_steps == 0:
                state = {
                    "step": step,
                    "epoch": epoch + 1,
                    "loss": last_loss,
                    "examples_seen_in_epoch": examples_seen,
                    "stella_version": STELLA_VERSION,
                }
                ckpt = project_dir / "checkpoints" / f"step-{step}"
                _save_checkpoint(model, optimizer, ckpt, state)
                emit({"type": "checkpoint", "step": step, "path": str(ckpt)})
            if controller is not None and controller.stop_requested:
                stopped = True
                break
        if stopped:
            break
        val_loss = evaluate()
        if val_loss is not None:
            _append_log(
                project_dir,
                {"step": step, "epoch": epoch + 1, "val_loss": round(val_loss, 4)},
            )
            emit({"type": "val", "epoch": epoch + 1, "loss": val_loss})
        if step >= total_steps:
            break

    # Final checkpoint (also the resume point if the run is paused).
    state = {
        "step": step,
        "epoch": min(epochs, epoch + 1) if not stopped else epoch + 1,
        "loss": last_loss,
        "examples_seen_in_epoch": examples_seen,
        "stella_version": STELLA_VERSION,
    }
    ckpt = project_dir / "checkpoints" / f"step-{step}"
    _save_checkpoint(model, optimizer, ckpt, state)
    emit({"type": "checkpoint", "step": step, "path": str(ckpt)})

    if not stopped:
        adapter_dir = project_dir / "adapter"
        if adapter_dir.exists():
            shutil.rmtree(adapter_dir)
        model.save_pretrained(str(adapter_dir))
        tokenizer.save_pretrained(str(adapter_dir))
        (adapter_dir / "training_summary.json").write_text(
            json.dumps(
                {
                    "steps": step,
                    "epochs": epochs,
                    "final_loss": last_loss,
                    "rank": rank,
                    "stella_version": STELLA_VERSION,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        emit({"type": "done", "steps": step, "adapter": str(adapter_dir)})
    else:
        emit({"type": "paused", "step": step, "path": str(ckpt)})

    return {
        "steps": step,
        "total_steps": total_steps,
        "final_loss": last_loss,
        "stopped": stopped,
        "checkpoint": str(ckpt),
    }


# -- project-level entry point --------------------------------------

def train_project(
    store: Store,
    profile: str,
    project: str,
    *,
    max_steps: int | None = None,
    resume: bool = False,
    dataset_path: str | Path | None = None,
    base_ref: str | None = None,
    on_event=None,
    controller: TrainController | None = None,
    _model_loader=None,
    _dtype: str = "bfloat16",
    work_dir: str | Path | None = None,
    update_status: bool = True,
    settings_override: dict | None = None,
) -> dict:
    """Train one project end to end. Returns a summary dict.

    `_model_loader` is a test hook: a callable returning
    (model, tokenizer) so tests can train a tiny random model with no
    downloads. Real runs always load from Hugging Face.

    `work_dir` overrides where checkpoints, the adapter, and the log
    go (default: the project dir). The sleep phase trains into its
    own cycle dir. `update_status=False` leaves the project status
    untouched — sleep is a background consolidation job, not a
    retrain of the project. `settings_override` merges over the
    project settings for this run only (sleep caps the LoRA rank
    at 8) without touching the stored project.
    """
    require_training_deps()
    prof = store.get_profile(profile)
    proj = store.get_project(profile, project)
    project_dir = store.project_dir(profile, project)
    work_dir = Path(work_dir) if work_dir is not None else project_dir
    work_dir.mkdir(parents=True, exist_ok=True)

    settings = dict(DEFAULT_TRAIN)
    settings.update(proj.get("settings", {}) or {})
    if settings_override:
        settings.update(settings_override)
    if max_steps is not None:
        # A step cap is a short proof run: shrink the epoch budget to
        # fit it (epochs are re-derived from the cap below).
        settings["_max_steps"] = int(max_steps)

    ref = base_ref or prof.get("base_ref") or ""
    if not ref:
        raise StellaError(
            f"profile {profile!r} has no base_ref. Set it to the "
            f"Hugging Face repo of the base model (e.g. {LFM3_HF_REPO!r})"
        )
    # Refuse GGUF / Ollama tags here, not just in load_base_model —
    # the check must hold even when a test injects a model loader.
    bad = _looks_like_gguf_or_tag(ref)
    if bad is not None:
        raise StellaError(
            f"base_ref {ref!r} is {bad} . Training needs Hugging "
            f"Face transformers weights. Set base_ref to a repo id "
            f"like {LFM3_HF_REPO!r}, or a local folder of HF weights."
        )

    # Dataset first (cheap), model second (expensive).
    if dataset_path is not None:
        data_path = Path(dataset_path).expanduser()
        if not data_path.is_file():
            raise StellaError(f"dataset not found: {data_path}")
    else:
        dataset_ref = proj.get("dataset_ref") or ""
        if not dataset_ref:
            raise StellaError(
                f"project {project!r} has no dataset set. Pick a .jsonl "
                "dataset in the Train panel, or use the sample dataset"
            )
        data_path = resolve_dataset_ref(store, profile, project, dataset_ref)
    examples, info = load_dataset(data_path)
    train_examples, val_examples = split_dataset(
        examples,
        float(settings.get("val_fraction", 0.1)),
        int(settings.get("seed", 42)),
    )

    # Load the base, then the RAM guard (needs real param counts).
    if _model_loader is not None:
        model, tokenizer = _model_loader()
    else:
        model, tokenizer = load_base_model(ref, dtype=_dtype)
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model

    targets = detect_target_modules(model)
    peft_config = LoraConfig(
        r=int(settings.get("rank", 8)),
        lora_alpha=int(settings.get("rank", 8)) * 2,
        lora_dropout=0.05,
        target_modules=targets,
        task_type="CAUSAL_LM",
    )

    start_step = 0
    start_epoch = 0
    skip_in_epoch = 0
    optimizer = None
    if resume:
        checkpoints = list_checkpoints(
            store, profile, project, ckpt_dir=work_dir / "checkpoints"
        )
        if not checkpoints:
            raise StellaError(
                "nothing to resume. This project has no checkpoints yet"
            )
        latest = checkpoints[-1]
        ckpt_dir = Path(latest["path"])
        model = PeftModel.from_pretrained(
            model, str(ckpt_dir), is_trainable=True
        )
        state_file = ckpt_dir / "training_state.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        start_step = int(state.get("step", 0))
        start_epoch = int(state.get("epoch", 1)) - 1
        skip_in_epoch = int(state.get("examples_seen_in_epoch", 0))
        trainable = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(
            trainable, lr=float(settings.get("learning_rate", 0.0002)),
            weight_decay=0.0,
        )
        opt_file = ckpt_dir / "optimizer.pt"
        if opt_file.is_file():
            saved = torch.load(str(opt_file), map_location="cpu", weights_only=False)
            optimizer.load_state_dict(saved["optimizer"])
    else:
        model = get_peft_model(model, peft_config)

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    cfg = model.config if hasattr(model, "config") else None
    hidden = getattr(cfg, "hidden_size", 2048) if cfg else 2048
    layers = getattr(cfg, "num_hidden_layers", 24) if cfg else 24
    base_bpp = 2 if _dtype == "bfloat16" else 4
    estimate, _breakdown = estimate_training_bytes(
        params=total_params,
        trainable_params=trainable_params,
        base_bytes_per_param=base_bpp,
        seq_len=int(settings.get("max_seq_len", 1024)),
        batch_size=int(settings.get("batch_size", 1)),
        hidden_size=hidden,
        num_layers=layers,
    )
    check_ram_fit(estimate)

    # A step cap turns into fewer epochs (never partial-epoch math in
    # the loop — the loop always runs whole epochs).
    if settings.get("_max_steps"):
        steps_per_epoch = max(
            1,
            math.ceil(
                len(train_examples)
                / (int(settings.get("batch_size", 1)) * int(settings.get("grad_accum", 8)))
            ),
        )
        epochs_needed = max(1, math.ceil(int(settings["_max_steps"]) / steps_per_epoch))
        settings["epochs"] = min(int(settings.get("epochs", 3)), epochs_needed)

    if update_status:
        store.update_project(profile, project, status="training")
    try:
        summary = run_training_loop(
            model,
            tokenizer,
            train_examples,
            val_examples,
            settings,
            work_dir,
            on_event=on_event,
            controller=controller,
            start_step=start_step,
            start_epoch=start_epoch,
            skip_in_epoch=skip_in_epoch,
            optimizer=optimizer,
        )
    except Exception:
        if update_status:
            store.update_project(profile, project, status="paused")
        raise
    if update_status:
        store.update_project(
            profile, project, status="paused" if summary["stopped"] else "trained"
        )
    summary["dataset"] = info
    summary["trainable_params"] = trainable_params
    summary["target_modules"] = targets
    summary["ram_estimate_gb"] = round(estimate / 1024**3, 2)
    return summary
