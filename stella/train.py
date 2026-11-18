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
  function that needs the training stack raises a StellaError with
  TRAINING_INSTALL_HINT, which names the click path first
  (Install training in the Train panel, or double-clicking
  Install Stella Training) and keeps the terminal command as the
  fallback.

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
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .autoconfig import compute_settings, measure_pc
from .job_lock import job_lock
from .model import STELLA_VERSION, StellaError, Store, metamorph_mode
from .ollama_bridge import bridge_error_message, classify_base_ref

# First proof target — confirmed from the live model card, not guessed.
LFM3_HF_REPO = "LiquidAI/LFM3-1.7B"

TRAINING_DEPS = ("torch", "transformers", "peft", "accelerate")
TRAINING_INSTALL_HINT = (
    "Training needs the training packages (torch, transformers, peft, "
    "accelerate). Install them by pressing Install training in the "
    "Train panel, or by double-clicking Install Stella Training in "
    "the Stella folder. It downloads about 2 GB. "
    "In a terminal: bash install-training.sh"
)

# 8 GB is the hard ceiling on Joshua's PC; 1 GB stays reserved for the
# OS, Python, and the tokenizer so training never swaps the machine dead.
RAM_LIMIT_BYTES = 8 * 1024**3
RAM_HEADROOM_BYTES = 1 * 1024**3

# How much of the base weights count as resident RAM in the
# estimate (S6). The old formula counted every weight byte as
# resident, which overstated peak RAM about 2.7x: the training
# probe (2026-11-15, Qwen2.5-Coder-0.5B) measured a 0.85 GB peak
# against a 2.30 GB estimate, with only 0.36 GB resident at load
# for ~1 GB of weights — safetensors weights are mmap'd and stream
# from disk, so they do not all sit in RAM. The probe-grounded
# resident share at load is ~0.36x; the estimate uses 0.5x to keep
# a safety margin, and still overstates the measured 0.5B peak
# more than twofold. Never lower this without a new probe.
RESIDENT_WEIGHTS_FRACTION = 0.5

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
# "tool" (T157) carries a tool result: it validates, renders as
# masked prompt content, and is never trained on — the model
# learns from the assistant turns around the tool results, not
# from the results themselves.
DATASET_ROLES = ("system", "user", "assistant", "tool")

# A dataset under this many examples is "tiny" (T83): it trains, but
# the model learns almost nothing general from it, so the pre-train
# check asks the user to confirm instead of starting silently. The
# bundled sample (20 examples) sits above the line on purpose.
TINY_DATASET_BELOW = 10

# Rough tokens-per-character for the pre-train token estimate (T83):
# English text averages about 4 characters per token. The estimate
# is an order of magnitude, not a tokenizer count — it is computed
# without loading any model, so it stays cheap.
CHARS_PER_TOKEN = 4


# -- engine-side settings validation (T6, D6) -----------------------
# The model layer (model.validate_settings) guards what gets STORED.
# The engine guards what gets RUN: a hand-edited project.json can
# still reach the loop, so the loop re-checks every numeric setting
# it reads — with the engine's own bounds, which are looser than the
# stored ones (a test or replay pass may legitimately run a short
# sequence length the model layer would not store). Each rule is
# (kind, low, high); None means unbounded on that side. A bad value
# is refused with a StellaError naming the setting, before anything
# loads or trains.
RUN_SETTING_RULES = {
    "rank": ("int", 1, None),
    "learning_rate": ("float", 0.0, None),  # strictly > 0, checked below
    "epochs": ("int", 1, None),
    "batch_size": ("int", 1, None),
    "grad_accum": ("int", 1, None),
    "max_seq_len": ("int", 8, None),
    "checkpoint_steps": ("int", 0, None),
    "warmup_steps": ("int", 0, None),
    "seed": ("int", None, None),
}

_RUN_DEFAULTS = {
    "rank": 8,
    "learning_rate": 0.0002,
    "epochs": 3,
    "batch_size": 1,
    "grad_accum": 8,
    "max_seq_len": 1024,
    "checkpoint_steps": 50,
    "warmup_steps": 5,
    "seed": 42,
}


def validate_run_settings(config: dict) -> dict:
    """Validate the numeric settings a run actually reads.

    Pure Python (no torch) so it runs before any heavy import.
    Returns the resolved values (defaults filled in, numbers
    coerced). Raises StellaError naming the setting on the first
    bad value: wrong type, non-finite, or out of range.
    """
    import math

    if not isinstance(config, dict):
        raise StellaError("training settings must be an object")
    cleaned: dict = {}
    for key, (kind, low, high) in RUN_SETTING_RULES.items():
        value = config.get(key, _RUN_DEFAULTS[key])
        if isinstance(value, bool):
            raise StellaError(f"{key} must be a number, not {value!r}")
        try:
            number = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError, OverflowError):
            raise StellaError(
                f"{key} must be a number, not {value!r}"
            ) from None
        if kind == "int" and float(value) != number:
            raise StellaError(
                f"{key} must be a whole number, not {value!r}"
            )
        if kind == "float" and not math.isfinite(number):
            raise StellaError(
                f"{key} must be a real number, not {value!r}"
            )
        if key == "learning_rate" and number <= 0:
            raise StellaError(
                "learning_rate must be above 0, not "
                f"{value!r} (a run with no learning rate learns nothing)"
            )
        if low is not None and number < low:
            raise StellaError(
                f"{key} must be at least {low}, not {value!r}"
            )
        if high is not None and number > high:
            raise StellaError(
                f"{key} must be at most {high}, not {value!r}"
            )
        cleaned[key] = number
    return cleaned


def _auto_model_params_b(store: Store, profile: str) -> float | None:
    """R78: the profile base model's size in billions of
    parameters, or None when it cannot be found out (no base ref,
    unreadable metadata, no network). Best effort only —
    autoconfig treats unknown as plenty, and a failure here must
    never fail the run."""
    try:
        prof = store.get_profile(profile)
    except StellaError:
        return None
    ref = (prof.get("base_ref") or "").strip()
    if not ref:
        return None
    try:
        meta = load_model_metadata(ref)
    except Exception:
        return None
    params = meta.get("params")
    if not isinstance(params, (int, float)) or params <= 0:
        return None
    return params / 1e9


def _auto_settings_changed_message(
    old: dict, new: dict, changed: list[str]
) -> str:
    """R78: the re-resolve announcement, naming old → new for
    each changed setting."""
    parts = []
    for key in changed:
        if key == "rank":
            parts.append(f"rank {old[key]} to {new[key]}")
        elif key == "max_seq_len":
            parts.append(
                f"max sequence length {old[key]} to {new[key]}"
            )
        elif key == "checkpoint_steps":
            parts.append(
                f"checkpoints every {old[key]} steps to every "
                f"{new[key]} steps"
            )
        else:
            parts.append(f"{key} {old[key]} to {new[key]}")
    return (
        "The automatic training settings changed for this run: "
        + ", ".join(parts)
        + ". The run uses the new settings."
    )


def refresh_auto_settings(
    store: Store, profile: str, project: str, *,
    on_event=None, work_dir: str | Path | None = None,
) -> dict:
    """Re-resolve an "auto" project's settings from a fresh
    measurement of this PC, and store the fresh values (the project
    stays "auto"). A "manual" project — or one with no source
    recorded, which reads as manual — is left exactly as it is.
    Returns the settings the run should use.

    R78: the re-resolve is model-aware — the base model's size
    shapes the recipe alongside RAM, disk, and CPU. When the
    re-resolve changes a setting, the change is announced — a
    warning event (which reaches the GUI job log) and a line in
    the run log, naming old and new — so the same project never
    silently trains different settings on different days.
    """
    proj = store.get_project(profile, project)
    if proj.get("settings_source", "manual") != "auto":
        return dict(proj.get("settings", {}) or {})
    measurement = measure_pc(store.home)
    computed = compute_settings(
        measurement["ram_available_gb"],
        model_params_b=_auto_model_params_b(store, profile),
        disk_free_gb=measurement["disk_free_gb"],
        cpu_count=measurement["cpu_count"],
    )
    old = dict(proj.get("settings", {}) or {})
    changed = [
        key for key in computed
        if key in old and old[key] != computed[key]
    ]
    updated = store.update_project(
        profile, project, settings=computed, settings_source="auto"
    )
    if changed:
        message = _auto_settings_changed_message(old, computed, changed)
        _emit_warning(on_event, message)
        if work_dir is not None:
            _append_log(
                Path(work_dir), {"event": "warning", "message": message}
            )
    return dict(updated["settings"])


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


def training_install_script() -> Path:
    """install-training.sh beside this Stella install (R13)."""
    return Path(__file__).resolve().parent.parent / "install-training.sh"


def run_training_install(
    *,
    on_line=None,
    should_stop=None,
    script: Path | None = None,
) -> None:
    """Run install-training.sh, streaming its output (R13).

    The click-only training install from the GUI: the Install
    training button runs the script through this function so the
    output shows as progress in the Train log. (The desktop
    launcher runs the same script directly; it does not come
    through here.) Each output line goes to `on_line` as it
    callable) cancels between lines, killing the install. Raises
    StellaError, in plain words, when the script is missing, the
    install is cancelled, or the install fails. `script`
    overrides the script path (tests).
    """
    import select
    import signal
    import subprocess

    path = Path(script) if script is not None else training_install_script()
    if not path.is_file():
        raise StellaError(
            "The training installer is not in this Stella folder. "
            "Reinstall Stella, then try again."
        )
    proc = subprocess.Popen(
        ["bash", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # Its own session, so a cancel kills the whole install
        # (bash and the pip it started), not just the shell.
        start_new_session=True,
    )
    assert proc.stdout is not None
    try:
        while True:
            if should_stop is not None and should_stop():
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.wait()
                raise StellaError("Training install cancelled.")
            ready, _, _ = select.select([proc.stdout], [], [], 0.5)
            if ready:
                line = proc.stdout.readline()
                if not line:
                    break
                if on_line is not None:
                    on_line(line.rstrip("\n"))
            elif proc.poll() is not None:
                break
        rc = proc.wait()
        # Drain lines the read buffer already holds: a fast exit
        # can leave the last lines buffered past the select loop.
        for line in proc.stdout:
            if on_line is not None:
                on_line(line.rstrip("\n"))
    finally:
        # A failure above must not leave the install running.
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
    if rc != 0:
        raise StellaError(
            "Training install did not finish. Check the lines above "
            "for the reason, then press Install training again."
        )


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


def iter_dataset_rows(path: str | Path):
    """Validate a JSONL dataset line by line, streaming (T158).

    Yields (line_no, row_format, messages) per non-blank row,
    reading the file one line at a time — a 100 MB dataset
    validates without ever holding the file (or the rows) in
    memory. Raises StellaError naming the first bad line, the
    same as load_dataset. The caller decides what to keep: the
    trainer keeps every row, the streaming check keeps counts.
    """
    path = Path(path)
    if not path.is_file():
        raise StellaError(f"dataset not found: {path}")
    fmt: str | None = None
    with path.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, 1):
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
            yield line_no, row_fmt, messages


def load_dataset(path: str | Path) -> tuple[list[dict], dict]:
    """Read + validate a JSONL dataset.

    Two formats, one per file (mixed files are rejected):

    - prompt/completion: {"prompt": "...", "completion": "..."}
    - messages: {"messages": [{"role": "user", "content": "..."},
      {"role": "assistant", "content": "..."}]}

    Returns (examples, info). Each example is normalized to
    {"messages": [...]} so the trainer has one shape to handle.
    The file is read line by line (T158) — the rows are still
    all held (training needs them), but the raw file text never
    is. `info` also carries "bytes", the file size, for the
    dataset-size check.
    """
    path = Path(path)
    examples: list[dict] = []
    fmt: str | None = None
    prompt_chars = 0
    completion_chars = 0
    for _line_no, row_fmt, messages in iter_dataset_rows(path):
        fmt = row_fmt
        prompt_chars += sum(len(m["content"]) for m in messages[:-1])
        completion_chars += len(messages[-1]["content"])
        examples.append({"messages": messages})
    if len(examples) < 2:
        raise StellaError(
            f"dataset has {len(examples)} example(s). At least 2 are "
            "needed (1 to train on, 1 to validate)"
        )
    try:
        file_bytes = path.stat().st_size
    except OSError:
        file_bytes = 0
    info = {
        "path": str(path),
        "format": fmt,
        "count": len(examples),
        "avg_prompt_chars": round(prompt_chars / len(examples)),
        "avg_completion_chars": round(completion_chars / len(examples)),
        "bytes": file_bytes,
    }
    return examples, info


def stream_dataset_info(
    path: str | Path,
    *,
    val_fraction: float = 0.1,
    seed: int = 42,
) -> dict:
    """A dataset's shape without holding the rows (T158).

    Streams the file once: validates every row, counts the
    examples, splits train/val by the content-hash rule (the
    hashes are kept — 8 bytes a row — never the rows), previews
    the first 3, and estimates the token count. Returns the same
    "info" shape load_dataset returns, plus train/val counts.
    The dataset health check runs on this, so a 100 MB file
    checks without loading whole.
    """
    path = Path(path)
    count = 0
    fmt: str | None = None
    prompt_chars = 0
    completion_chars = 0
    preview: list[str] = []
    hashes: list[float] = []
    for _line_no, row_fmt, messages in iter_dataset_rows(path):
        fmt = row_fmt
        prompt_chars += sum(len(m["content"]) for m in messages[:-1])
        completion_chars += len(messages[-1]["content"])
        hashes.append(_row_val_hash({"messages": messages}, seed))
        if len(preview) < 3:
            first = messages[0]["content"] if messages else ""
            first = " ".join(first.split())
            preview.append(
                first[:80] + ("..." if len(first) > 80 else "")
            )
        count += 1
    if count < 2:
        raise StellaError(
            f"dataset has {count} example(s). At least 2 are "
            "needed (1 to train on, 1 to validate)"
        )
    frac = min(max(float(val_fraction), 0.0), 1.0)
    is_val = [h < frac for h in hashes]
    if not any(is_val):
        is_val[min(range(count), key=lambda i: hashes[i])] = True
    if all(is_val):
        is_val[max(range(count), key=lambda i: hashes[i])] = False
    n_val = sum(is_val)
    try:
        file_bytes = path.stat().st_size
    except OSError:
        file_bytes = 0
    total_chars = prompt_chars + completion_chars
    return {
        "path": str(path),
        "format": fmt,
        "count": count,
        "train": count - n_val,
        "val": n_val,
        "avg_prompt_chars": round(prompt_chars / count),
        "avg_completion_chars": round(completion_chars / count),
        "preview": preview,
        "est_tokens": total_chars // CHARS_PER_TOKEN,
        "bytes": file_bytes,
    }


def _row_val_hash(example: dict, seed: int) -> float:
    """One example's val-membership hash (T155), in [0, 1).

    The row's messages as canonical JSON, salted with the seed,
    through SHA-256 — namespaced with a version tag so a future
    scheme change does not silently re-split old datasets. The
    same row always hashes the same way, so adding rows never
    moves an old row's val membership (unlike the old shuffle,
    which re-dealt the whole deck on every run). A prompt /
    completion row hashes as its normalized messages form, so
    the same content splits the same way in either format.
    """
    import hashlib

    messages = example.get("messages")
    if messages is None:
        messages = [
            {"role": "user", "content": example.get("prompt", "")},
            {"role": "assistant", "content": example.get("completion", "")},
        ]
    canonical = json.dumps(messages, sort_keys=True)
    digest = hashlib.sha256(
        f"stella-val-v1:{seed}:{canonical}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def split_dataset(
    examples: list[dict], val_fraction: float = 0.1, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    """Train/validate split by content hash (T155).

    A row validates when its content hash falls in the lowest
    `val_fraction` of the range — membership depends only on the
    row itself, so adding rows never moves an old row between
    train and val, and val loss stays comparable across runs.

    Always keeps at least one example for validation (T33) — a
    2-example dataset used to validate on 0 rows while load_dataset
    promised "1 to train on, 1 to validate". The cap at n - 1 keeps
    at least one example for training. The two guards are the one
    exception to stability: a dataset with no row under the
    threshold validates on its lowest-hash row, and a new row
    with an even lower hash can take that slot — with no stored
    memory of past splits, a stateless rule cannot do better.
    """
    frac = min(max(float(val_fraction), 0.0), 1.0)
    hashes = [_row_val_hash(ex, seed) for ex in examples]
    val_idx = {i for i, h in enumerate(hashes) if h < frac}
    if not val_idx and examples:
        # No row fell under the threshold: the lowest-hash row
        # validates (T33), so the run still has a val signal.
        val_idx = {min(range(len(examples)), key=lambda i: hashes[i])}
    if len(val_idx) >= len(examples) and examples:
        # Every row fell under the threshold: the highest-hash row
        # trains, so the run still has something to learn from.
        val_idx.discard(
            max(range(len(examples)), key=lambda i: hashes[i])
        )
    train = [ex for i, ex in enumerate(examples) if i not in val_idx]
    val = [ex for i, ex in enumerate(examples) if i in val_idx]
    return train, val


def val_membership_hashes(
    examples: list[dict], val_fraction: float = 0.1, seed: int = 42
) -> list[bool]:
    """Per-row val membership (T155/T158): True when the row
    validates under the content-hash split. The streaming dataset
    check counts train/val without holding the rows — it hashes
    each row as it passes and applies the same guards."""
    frac = min(max(float(val_fraction), 0.0), 1.0)
    hashes = [_row_val_hash(ex, seed) for ex in examples]
    is_val = [h < frac for h in hashes]
    if hashes and not any(is_val):
        is_val[min(range(len(hashes)), key=lambda i: hashes[i])] = True
    if hashes and all(is_val):
        is_val[max(range(len(hashes)), key=lambda i: hashes[i])] = False
    return is_val


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


def check_dataset(store: Store, profile: str, project: str,
                  ref: str) -> dict:
    """Check a dataset ref for display (T45): resolve it, validate
    the JSONL with the trainer's own validator, count the examples,
    split train/val, and preview the first 3. The check streams
    the file (T158) — a big dataset checks without loading whole.
    Returns a dict; never raises — a bad dataset is a report, not
    a crash:

      status: "unset" (no ref), "ok", "missing", "invalid"
      count, train, val: example counts (0 unless ok)
      format: "messages" or "prompt" (None unless ok)
      preview: the first message of the first 3 examples, trimmed
      error: the plain-words problem (None unless missing/invalid)
      path: the resolved file (None unless found)
      tiny: True when the dataset is ok but under
        TINY_DATASET_BELOW examples (T83) — the pre-train check
        asks before starting on one
      est_tokens: rough total token count (T83), chars / 4 — 0
        unless ok
      bytes: the dataset file size (T158) — 0 unless ok
    """
    ref = (ref or "").strip()
    empty = {
        "status": "unset", "count": 0, "train": 0, "val": 0,
        "format": None, "preview": [], "error": None, "path": None,
        "tiny": False, "est_tokens": 0, "bytes": 0,
    }
    if not ref:
        return empty
    try:
        path = resolve_dataset_ref(store, profile, project, ref)
    except StellaError:
        return {**empty, "status": "missing",
                "error": f"dataset not found: {ref!r}"}
    try:
        info = stream_dataset_info(path)
    except StellaError as exc:
        return {**empty, "status": "invalid", "error": str(exc),
                "path": str(path)}
    return {
        "status": "ok", "count": info["count"],
        "train": info["train"], "val": info["val"],
        "format": info["format"], "preview": info["preview"],
        "error": None, "path": str(path),
        "tiny": info["count"] < TINY_DATASET_BELOW,
        "est_tokens": info["est_tokens"],
        "bytes": info["bytes"],
    }


# -- dataset size (T158) -------------------------------------------
# A dataset competes with the model for the same 8 GB: the rows
# sit in memory as Python dicts, then again as tokenized
# input_ids + labels lists. A tokenized token costs about 72
# bytes — two Python-int lists (input_ids and labels) at roughly
# 36 bytes a token each (pointer + int object) — so the estimate
# is deliberately rough and on the high side.

_TOKENIZED_BYTES_PER_TOKEN = 72

# Warn before tokenizing a dataset over either line: the run
# still starts, but the user knows it will be heavy.
DATASET_WARN_BYTES = 10 * 1024 * 1024
DATASET_WARN_ROWS = 5000


def estimate_dataset_bytes(file_bytes: int, est_tokens: int) -> int:
    """RAM for one dataset, roughly (T158): the file's own bytes
    (the rows live as Python strings and dicts) plus the
    tokenized copy (input_ids + labels, per token)."""
    return int(file_bytes) + int(est_tokens) * _TOKENIZED_BYTES_PER_TOKEN


def check_dataset_fit(
    dataset_bytes: int,
    training_bytes: int,
    limit_bytes: int = RAM_LIMIT_BYTES,
    *,
    available_bytes: int | None = None,
) -> None:
    """Refuse a run whose dataset would not fit alongside the
    model (T158): the training estimate (T28) plus the dataset
    estimate, against the same limit. The message names both
    numbers, so the fix (a smaller dataset, or a smaller base)
    is obvious. `available_bytes` tightens the limit to what is
    free right now, as in check_ram_fit."""
    limit = min(
        limit_bytes,
        effective_ram_limit_bytes(available_bytes)
        if available_bytes is not None else limit_bytes,
    )
    total = dataset_bytes + training_bytes
    if total > limit:
        if available_bytes is not None and available_bytes < limit_bytes:
            raise StellaError(
                f"This dataset would not fit alongside the model: "
                f"training needs about {_gb(training_bytes)} of RAM "
                f"and the dataset about {_gb(dataset_bytes)}, "
                f"together over the {_gb(available_bytes)} free on "
                "this PC right now.\n"
                "Close other programs and try again, train on a "
                "smaller dataset, or use a smaller base model."
            )
        raise StellaError(
            f"This dataset would not fit alongside the model: "
            f"training needs about {_gb(training_bytes)} of RAM "
            f"and the dataset about {_gb(dataset_bytes)}, "
            f"together over the {_gb(limit_bytes)} ceiling on "
            "this PC.\n"
            "Train on a smaller dataset, or use a smaller base model."
        )


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
    - base weights: params x bytes-per-param x
      RESIDENT_WEIGHTS_FRACTION (0.5) — safetensors weights are
      mmap'd and stream from disk, so only about half count as
      resident (probe-grounded, see the constant above)
    - gradients: trainable params x 4 (fp32, trainable only)
    - AdamW states: trainable params x 8 (fp32 m + v)
    - fp32 master copy of trainable weights: trainable x 4
    - activations: batch x seq x hidden x layers x 34 (stored tensors
      per layer for backward, deliberately conservative)
    - headroom: 1 GB for the OS, Python, tokenizer
    """
    weights_full = params * base_bytes_per_param
    weights = int(weights_full * RESIDENT_WEIGHTS_FRACTION)
    grads = trainable_params * 4
    optimizer = trainable_params * 8
    master = trainable_params * 4
    activations = batch_size * seq_len * hidden_size * num_layers * 34
    total = weights + grads + optimizer + master + activations + RAM_HEADROOM_BYTES
    breakdown = {
        "base_weights": weights,
        "base_weights_full": weights_full,
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


def available_ram_bytes() -> int | None:
    """RAM free on this PC right now (MemAvailable), in bytes, via
    autoconfig's measurement — or None when it cannot be read.
    A test seam: tests patch this instead of /proc/meminfo."""
    try:
        available_gb = measure_pc()["ram_available_gb"]
    except Exception:
        return None
    if available_gb is None:
        return None
    return int(available_gb * 1024**3)


def effective_ram_limit_bytes(available_bytes: int | None = None) -> int:
    """The RAM limit a run is actually judged against (S6): the
    8 GB ceiling, or what is free right now, whichever is smaller.
    A fixed ceiling alone would start a run the box cannot
    currently fit — Ollama holding models, for one. Unknown
    available RAM (None) means the ceiling on its own: the guard
    never invents a smaller limit it cannot measure."""
    if available_bytes is None:
        available_bytes = available_ram_bytes()
    if available_bytes is None:
        return RAM_LIMIT_BYTES
    return min(RAM_LIMIT_BYTES, available_bytes)


def check_ram_fit(
    estimate_bytes: int,
    limit_bytes: int = RAM_LIMIT_BYTES,
    *,
    available_bytes: int | None = None,
) -> None:
    """Refuse to train if the estimate does not fit the RAM limit.

    `available_bytes` (MemAvailable, when the caller measured it)
    tightens the limit to what is free right now, and the refusal
    then says so — closing other programs is the fix, not a
    smaller model. Without it, the refusal names the ceiling, as
    before."""
    limit = effective_ram_limit_bytes(available_bytes) \
        if available_bytes is not None else limit_bytes
    limit = min(limit, limit_bytes)
    if estimate_bytes > limit:
        if available_bytes is not None and available_bytes < limit_bytes:
            raise StellaError(
                f"Training would need about {_gb(estimate_bytes)} of "
                f"RAM, and this PC has only {_gb(available_bytes)} "
                "free right now.\n"
                "Close other programs and try again (Ollama may be "
                "holding models in memory). Or lower max_seq_len or "
                "the LoRA rank, or pick a smaller base model."
            )
        raise StellaError(
            f"Training would need about {_gb(estimate_bytes)} of RAM, "
            f"over the {_gb(limit_bytes)} ceiling on this PC.\n"
            "Lower max_seq_len or the LoRA rank, or pick a smaller base "
            "model. A full fine-tune of a 1.7B model does not fit, ever: "
            "its optimizer state alone is ~28 GB."
        )


# -- model metadata: size without loading (T28) ----------------------
# The RAM guard used to load the base model first and ask whether it
# fit afterwards — on 8 GB, loading a 1.7B base to ask whether it
# fits can OOM the machine the guard exists to protect. The estimate
# now comes from the model's config + weight sizes, read off disk
# (or fetched as two small files from the Hub), never from a loaded
# model. A run that will not fit is refused before any load.

_DTYPE_BYTES = {
    "float32": 4, "fp32": 4,
    "float16": 2, "fp16": 2,
    "bfloat16": 2, "bf16": 2,
}


def _metadata_from_config(config: dict, base_bytes: int) -> dict:
    """Shape + size from a config.json dict and the weight bytes.

    Handles both modern configs (hidden_size / num_hidden_layers /
    intermediate_size) and GPT-2-style ones (n_embd / n_layer /
    n_inner). The parameter count is the weight bytes divided by
    the dtype size — close enough for a guard, and it never
    understates the weights themselves."""
    hidden = int(
        config.get("hidden_size")
        or config.get("n_embd")
        or config.get("d_model")
        or 2048
    )
    layers = int(
        config.get("num_hidden_layers")
        or config.get("n_layer")
        or 24
    )
    intermediate = int(
        config.get("intermediate_size")
        or config.get("n_inner")
        or config.get("d_ff")
        or hidden * 4
    )
    dtype = str(
        config.get("torch_dtype") or config.get("dtype") or "bfloat16"
    ).lower()
    bpp = _DTYPE_BYTES.get(dtype, 2)
    # The architecture names (T97): the GGUF pre-flight checks the
    # first one against the installed converter's supported list.
    # A config without the field, or a non-list value, reads as no
    # architectures — the check is skipped, never guessed.
    archs = config.get("architectures")
    if not isinstance(archs, list):
        archs = []
    return {
        "params": max(1, base_bytes // bpp),
        "hidden_size": hidden,
        "num_layers": layers,
        "intermediate_size": intermediate,
        "base_bytes": base_bytes,
        "bytes_per_param": bpp,
        "architectures": [str(a) for a in archs],
    }


def _local_model_metadata(base_dir: Path) -> dict:
    """Metadata of a local HF folder, from config.json + the weight
    files. Raises StellaError when the folder holds no model."""
    config_path = base_dir / "config.json"
    if not config_path.is_file():
        raise StellaError(
            f"could not check whether {str(base_dir)!r} fits this PC: "
            "that folder does not hold a model (no config.json)."
        )
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise StellaError(
            f"could not check whether {str(base_dir)!r} fits this PC: "
            f"its config.json cannot be read ({exc})."
        ) from exc
    if not isinstance(config, dict):
        raise StellaError(
            f"could not check whether {str(base_dir)!r} fits this PC: "
            "its config.json does not hold an object."
        )
    index_path = base_dir / "model.safetensors.index.json"
    total_size = None
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            total_size = index.get("metadata", {}).get("total_size")
        except (json.JSONDecodeError, OSError, AttributeError):
            total_size = None
    if total_size is None:
        weight_files = sorted(base_dir.glob("*.safetensors")) or sorted(
            base_dir.glob("*.bin")
        )
        total_size = sum(f.stat().st_size for f in weight_files)
    if not total_size:
        raise StellaError(
            f"could not check whether {str(base_dir)!r} fits this PC: "
            "no weight files found there."
        )
    return _metadata_from_config(config, int(total_size))


def _fetch_hf_file(repo: str, filename: str) -> Path:
    """One small file from the Hub (config.json, the safetensors
    index) — from the local cache when it is there, else the
    network. A test seam: tests patch this instead of the network."""
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=repo, filename=filename))


def _hf_file_size_via_head(url: str) -> int | None:
    """A Hub file's size from a HEAD request (Content-Length),
    via huggingface_hub's metadata fetch, which follows the
    Hub's redirect to the file store. None when the HEAD is
    refused or answers without a size. Never raises."""
    try:
        from huggingface_hub import get_hf_file_metadata

        size = get_hf_file_metadata(url).size
    except Exception:
        return None
    return size if isinstance(size, int) and size > 0 else None


def _hf_file_size_via_range(url: str) -> int | None:
    """A Hub file's size from a one-byte ranged GET (Range:
    bytes=0-0, total from Content-Range), for when the HEAD is
    refused. Downloads one byte, never the file. None on any
    failure. Never raises."""
    try:
        import re
        import urllib.request

        req = urllib.request.Request(
            url, headers={"Range": "bytes=0-0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_range = resp.headers.get("Content-Range") or ""
            match = re.search(r"/(\d+)\s*$", content_range)
            if match:
                return int(match.group(1))
            length = resp.headers.get("Content-Length")
            if length is not None and resp.status == 200:
                # No range support and a full reply: the length
                # is the file size, but only trust it when the
                # server answered the whole file in one go.
                return int(length)
    except Exception:
        return None
    return None


def _fetch_hf_file_size(repo: str, filename: str) -> int | None:
    """One Hub file's size in bytes, HEAD first with a ranged
    GET as the fallback. A test seam: tests patch this instead
    of the network. Never raises: None means unknowable."""
    try:
        from huggingface_hub import hf_hub_url

        url = hf_hub_url(repo, filename)
    except Exception:
        return None
    return _hf_file_size_via_head(url) or _hf_file_size_via_range(url)


def _cached_model_metadata(base_ref: str) -> dict | None:
    """Metadata of a Hub repo from the local cache alone (R25):
    no network, no huggingface_hub import. A snapshot holding a
    config.json plus weight files is enough — the snapshot files
    are links into the blobs dir, so stat follows them to the
    real sizes. None when nothing usable is cached: the caller
    falls back to the network path. This is what makes a cached
    single-file model work offline: the network path sizes its
    weights over the Hub API, which refuses with no network even
    when the weights are already on the disk."""
    from .provision import repo_cache_dir

    snaps = repo_cache_dir(base_ref) / "snapshots"
    if not snaps.is_dir():
        return None
    for snap in sorted(snaps.iterdir()):
        if not snap.is_dir():
            continue
        config_path = snap / "config.json"
        if not config_path.is_file():
            continue
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(config, dict):
            continue
        total = 0
        try:
            members = list(snap.iterdir())
        except OSError:
            continue
        for item in members:
            if item.name.endswith((".safetensors", ".bin")):
                try:
                    if item.is_file():
                        total += item.stat().st_size
                except OSError:
                    continue
        if total > 0:
            return _metadata_from_config(config, total)
    return None


def _remote_model_metadata(base_ref: str) -> dict:
    """Metadata of a Hub repo, from its config + weight sizes —
    two small downloads, never the weights."""
    # R25: the cache first. A cached model answers offline, with
    # no network call at all — the network path below is only for
    # a model that is not on the disk yet.
    cached = _cached_model_metadata(base_ref)
    if cached is not None:
        return cached
    try:
        config_path = _fetch_hf_file(base_ref, "config.json")
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise StellaError(
            f"could not check whether {base_ref!r} fits this PC: its "
            "config could not be read (no network, or the model is "
            "not cached locally). Download the weights first, or "
            "point base_ref at a local folder."
        ) from exc
    if not isinstance(config, dict):
        raise StellaError(
            f"could not check whether {base_ref!r} fits this PC: its "
            "config could not be read."
        )
    total_size = None
    try:
        index_path = _fetch_hf_file(base_ref, "model.safetensors.index.json")
        index = json.loads(index_path.read_text(encoding="utf-8"))
        total_size = index.get("metadata", {}).get("total_size")
    except Exception:
        total_size = None
    if total_size is None:
        # Single-file model, no index: ask the Hub for the file list.
        # The Hub returns size None for every sibling of
        # single-file models, so a bare sum comes out 0 — resolve
        # each weight file's size with a HEAD request instead
        # (S24: this unblocks Qwen2.5-Coder-1.5B, LFM3-1.7B, and
        # every other single-file model).
        try:
            from huggingface_hub import HfApi

            info = HfApi().model_info(base_ref)
            total = 0
            for s in info.siblings:
                if not s.rfilename.endswith((".safetensors", ".bin")):
                    continue
                size = s.size or _fetch_hf_file_size(
                    base_ref, s.rfilename
                )
                total += size or 0
            total_size = total or None
        except Exception:
            total_size = None
    if not total_size:
        # R25: a genuine refusal names the next step, mirroring
        # the config-failure message above — the old text named
        # no next step at all.
        raise StellaError(
            f"could not check whether {base_ref!r} fits this PC: the "
            "size of its weights could not be read (no network, or "
            "the model is not cached locally). Download the weights "
            "first, or point base_ref at a local folder."
        )
    return _metadata_from_config(config, int(total_size))


def load_model_metadata(base_ref: str) -> dict:
    """A model's size + shape without loading its weights (T28).

    A local folder reads config.json + the weight files; a Hub repo
    id fetches the config + the safetensors index (two small files).
    Returns params, hidden_size, num_layers, intermediate_size,
    base_bytes, bytes_per_param. Raises StellaError when the size
    cannot be found out — the guard would rather refuse than guess.
    An Ollama tag or GGUF file is refused with the bridge error
    (S23), not the misleading "config could not be read".
    """
    path = Path(base_ref).expanduser()
    if path.is_dir():
        return _local_model_metadata(path)
    kind, _detail = classify_base_ref(base_ref)
    if kind in ("gguf", "ollama"):
        raise StellaError(bridge_error_message(base_ref))
    return _remote_model_metadata(base_ref)


def base_ref_warnings(base_ref: str) -> list[str]:
    """R87: plain-words problems with a base_ref, checked against
    the actual weights — the T12 soft-warning pattern extended
    from the Ollama tag to the base. Empty list = no problem.
    Warns (never refuses) when the ref is a GGUF file or an
    Ollama tag (training cannot start from either), a local
    folder that holds no model, or a name that is not shaped like
    a Hugging Face repo id. A repo id that is not cached locally
    is never warned about: checking it would need the network,
    a network failure must not become a false warning, and the
    Hub answers 401, not 404, for a missing repo, so existence
    cannot be told from here anyway. The train path still refuses
    an unresolvable ref, later, with the bridge error — this is
    the early warning, not the gate."""
    ref = (base_ref or "").strip()
    if not ref:
        return []
    kind, _detail = classify_base_ref(ref)
    if kind == "gguf":
        return [
            f"{ref!r} is a GGUF file. Training needs Hugging Face "
            "weights, not the file Ollama runs."
        ]
    if kind == "ollama":
        return [
            f"{ref!r} is an Ollama tag, not a Hugging Face repo. "
            "Training needs the Hugging Face repo of the base model."
        ]
    if kind == "local":
        try:
            load_model_metadata(ref)
        except StellaError:
            return [
                f"the folder {ref!r} does not hold a model (no "
                "config or weights found there)."
            ]
        return []
    # A Hub repo id: shaped like owner/model, or it is a typo.
    # (A well-shaped id that is not cached cannot be checked
    # without the network, so it is never warned about on a guess.)
    if not re.fullmatch(r"[^/\s:]+/[^/\s:]+", ref):
        return [
            f"{ref!r} does not look like a Hugging Face repo name. "
            "A repo name looks like owner/model."
        ]
    return []


def estimate_lora_params(
    *,
    hidden_size: int,
    intermediate_size: int,
    num_layers: int,
    rank: int,
) -> int:
    """LoRA trainable params, assuming the standard 7 targets
    (q/k/v/o + gate/up/down). Conservative: a model with fewer
    targets trains fewer params, so the estimate never understates
    the optimizer state the guard is budgeting for."""
    per_layer = rank * (
        8 * hidden_size + 3 * (hidden_size + intermediate_size)
    )
    return per_layer * num_layers


def estimate_training_from_metadata(
    base_ref: str, settings: dict
) -> tuple[int, dict]:
    """The RAM estimate from metadata alone (T28) — no weights
    loaded. Returns (total_bytes, breakdown), like
    estimate_training_bytes."""
    meta = load_model_metadata(base_ref)
    trainable = estimate_lora_params(
        hidden_size=meta["hidden_size"],
        intermediate_size=meta["intermediate_size"],
        num_layers=meta["num_layers"],
        rank=int(settings.get("rank", 8)),
    )
    return estimate_training_bytes(
        params=meta["params"],
        trainable_params=trainable,
        base_bytes_per_param=meta["bytes_per_param"],
        seq_len=int(settings.get("max_seq_len", 1024)),
        batch_size=int(settings.get("batch_size", 1)),
        hidden_size=meta["hidden_size"],
        num_layers=meta["num_layers"],
    )


# -- pre-train estimate: RAM fit + steps + disk, no model load ------
# (T84/T85). One function serves the Train panel's estimate label
# (T84) and the dry run (T85) — the display math lives here, not in
# two places. Everything comes from metadata (T28) + the dataset
# file: the base model is never loaded, so asking "will this fit"
# cannot itself OOM the machine.

# Bytes per trainable parameter a checkpoint holds, roughly: the
# adapter weights (fp32 master copy) + the AdamW optimizer state
# (fp32 m + v) + the saved gradients. Deliberately on the high
# side — the disk estimate should overstate, never understate.
_CHECKPOINT_BYTES_PER_PARAM = 16


def _rough_time_note(total_steps: int) -> str:
    """A rough time band for a step count, in plain words (T84).

    Orders of magnitude, not a promise: a CPU optimizer step on a
    1.7B base takes on the order of a minute on this PC (several
    micro-steps of forward + backward each), so the bands run from
    minutes to many hours. The label says "rough" so nobody reads
    it as a schedule."""
    if total_steps < 10:
        return "roughly minutes"
    if total_steps < 100:
        return "roughly tens of minutes to an hour"
    if total_steps < 500:
        return "roughly hours"
    return "roughly many hours"


def _effective_settings_for_estimate(
    store: Store, profile: str, project: str,
    model_params_b: float | None = None,
) -> dict:
    """The settings a run would use (T84): the auto-config recipe
    for an "auto" project, re-resolved from a fresh measurement
    WITHOUT storing it (a display refresh must not write), or the
    stored settings for a "manual" one. The user never sees these
    numbers (T16) — the estimate shows fit and time, not knobs.
    R78: the re-resolve is model-aware when the caller knows the
    base size, like the run-start one."""
    proj = store.get_project(profile, project)
    settings = dict(DEFAULT_TRAIN)
    if proj.get("settings_source", "manual") == "auto":
        measurement = measure_pc(store.home)
        settings.update(compute_settings(
            measurement["ram_available_gb"],
            model_params_b=model_params_b,
            disk_free_gb=measurement["disk_free_gb"],
            cpu_count=measurement["cpu_count"],
        ))
    else:
        settings.update(proj.get("settings", {}) or {})
    return settings


def _no_dataset_error(project: str, *, cli: bool) -> StellaError:
    """The no-dataset error, worded for the frontend asking (T111).

    A terminal user has no Train panel, so the CLI names the CLI
    fix (--dataset); the window names the panel, as before."""
    if cli:
        return StellaError(
            f"project {project!r} has no dataset set. Use "
            "--dataset <file> to train with a .jsonl dataset, or "
            "create-project --dataset <file> when creating a project."
        )
    return StellaError(
        f"project {project!r} has no dataset set. Pick a .jsonl "
        "dataset in the Train panel, or use the sample dataset"
    )


def estimate_run_disk_bytes(
    *,
    base_bytes: int,
    trainable_params: int,
    total_steps: int,
    checkpoint_steps: int,
) -> int:
    """The disk one run needs (R79): the merged weights (a full
    copy of the base) + one checkpoint per checkpoint interval
    plus the final one + the finished adapter. Shared by
    estimate_run and the train-start disk guard, so the estimate
    and the refusal agree."""
    if checkpoint_steps > 0:
        n_checkpoints = total_steps // checkpoint_steps + 1
    else:
        n_checkpoints = 1
    return (
        base_bytes
        + n_checkpoints * trainable_params * _CHECKPOINT_BYTES_PER_PARAM
        + trainable_params * 4
    )


# R79: headroom above the run's own disk need — the disk must hold
# the run plus this much spare, so a nearly-full disk refuses
# before the run starts filling it.
DISK_HEADROOM_BYTES = 512 * 1024 * 1024


def check_disk_fit(needed_bytes: int, free_bytes: int | None) -> None:
    """R79: refuse when the disk cannot hold this run. `needed`
    is the run's own new disk need (its checkpoints, the merged
    weights, the adapter); the headroom rides on top. Existing
    checkpoints are NOT added in — they are already on the disk,
    so free space already excludes them, and adding them would
    refuse runs that fit. An unreadable disk (free_bytes None)
    never refuses — the writes themselves fail readably then.
    Raises StellaError in plain words."""
    if free_bytes is None:
        return
    total_needed = needed_bytes + DISK_HEADROOM_BYTES
    if free_bytes < total_needed:
        raise StellaError(
            "Not enough free disk to train: this run needs about "
            f"{_fmt_disk(total_needed)} free (the checkpoints it "
            "will write, plus the merged weights, plus room to "
            "spare), and this disk has "
            f"{_fmt_disk(free_bytes)} free. Free some space, or "
            "delete old checkpoints first."
        )


def estimate_run(
    store: Store,
    profile: str,
    project: str,
    *,
    dataset_path: str | Path | None = None,
    base_ref: str | None = None,
    cli: bool = False,
) -> dict:
    """The pre-train estimate (T84/T85), from metadata only.

    RAM fit (T28's honest estimator, no model load), the step
    count for the dataset + settings, the disk the run needs
    (checkpoints + adapter + merged weights), and a rough time
    band. Raises StellaError when the answer cannot be found out
    (no base ref, unreadable model metadata, bad dataset) — the
    caller reports it plainly instead of guessing.

    Returns: fits, estimate_bytes, limit_bytes, ram_available_bytes,
    ram_gb, steps,
    disk_bytes, time_note, dataset_count, dataset_format,
    est_tokens, train_examples, val_examples, trainable_params,
    base_bytes.
    """
    prof = store.get_profile(profile)
    proj = store.get_project(profile, project)
    ref = base_ref or prof.get("base_ref") or ""
    if not ref:
        raise StellaError(
            f"profile {profile!r} has no base_ref. Set it to the "
            f"Hugging Face repo of the base model (e.g. {LFM3_HF_REPO!r})"
        )
    # R78: the metadata loads first, so the estimate uses the same
    # model-aware recipe the run will use — otherwise the estimate
    # could refuse a run that would have shrunk and fit.
    meta = load_model_metadata(ref)
    params = meta.get("params")
    settings = _effective_settings_for_estimate(
        store, profile, project,
        model_params_b=params / 1e9 if params else None,
    )
    settings.update(validate_run_settings(settings))
    trainable = estimate_lora_params(
        hidden_size=meta["hidden_size"],
        intermediate_size=meta["intermediate_size"],
        num_layers=meta["num_layers"],
        rank=int(settings.get("rank", 8)),
    )
    estimate_bytes, _breakdown = estimate_training_bytes(
        params=meta["params"],
        trainable_params=trainable,
        base_bytes_per_param=meta["bytes_per_param"],
        seq_len=int(settings.get("max_seq_len", 1024)),
        batch_size=int(settings.get("batch_size", 1)),
        hidden_size=meta["hidden_size"],
        num_layers=meta["num_layers"],
    )
    # S6: "fits" is judged against what is free right now, not
    # just the fixed ceiling — the dry run must not promise a run
    # the box cannot currently fit.
    ram_available = available_ram_bytes()
    limit_bytes = effective_ram_limit_bytes(ram_available)
    if dataset_path is not None:
        data_path = Path(dataset_path).expanduser()
        if not data_path.is_file():
            raise StellaError(f"dataset not found: {data_path}")
    else:
        dataset_ref = proj.get("dataset_ref") or ""
        if not dataset_ref:
            raise _no_dataset_error(project, cli=cli)
        data_path = resolve_dataset_ref(store, profile, project, dataset_ref)
    examples, info = load_dataset(data_path)
    train_examples, val_examples = split_dataset(
        examples,
        float(settings.get("val_fraction", 0.1)),
        int(settings.get("seed", 42)),
    )
    steps_per_epoch = max(
        1,
        math.ceil(
            len(train_examples)
            / (
                int(settings.get("batch_size", 1))
                * int(settings.get("grad_accum", 8))
            )
        ),
    )
    total_steps = steps_per_epoch * int(settings.get("epochs", 3))
    # Disk: the merged weights (a full copy of the base) + one
    # checkpoint per checkpoint interval plus the final one + the
    # finished adapter. A checkpoint interval of 0 means no
    # mid-run checkpoints, only the final save. The formula lives
    # in estimate_run_disk_bytes, shared with the train-start
    # disk guard (R79).
    disk_bytes = estimate_run_disk_bytes(
        base_bytes=meta["base_bytes"],
        trainable_params=trainable,
        total_steps=total_steps,
        checkpoint_steps=int(settings.get("checkpoint_steps", 50)),
    )
    total_chars = (
        info["avg_prompt_chars"] + info["avg_completion_chars"]
    ) * len(examples)
    # R24: the fit answer counts the dataset too — the run-time
    # check (check_dataset_fit) always did, so an estimate that
    # ignored it said "fits" for runs the guard then refused.
    dataset_bytes = estimate_dataset_bytes(
        info.get("bytes", 0), total_chars // CHARS_PER_TOKEN
    )
    total_bytes = estimate_bytes + dataset_bytes
    return {
        "fits": total_bytes <= limit_bytes,
        "estimate_bytes": estimate_bytes,
        "dataset_bytes": dataset_bytes,
        "total_bytes": total_bytes,
        "limit_bytes": limit_bytes,
        "ram_available_bytes": ram_available,
        "ram_gb": round(estimate_bytes / 1024**3, 2),
        "steps": total_steps,
        "disk_bytes": disk_bytes,
        "time_note": _rough_time_note(total_steps),
        "dataset_count": len(examples),
        "dataset_format": info["format"],
        "est_tokens": total_chars // CHARS_PER_TOKEN,
        "train_examples": len(train_examples),
        "val_examples": len(val_examples),
        "trainable_params": trainable,
        "base_bytes": meta["base_bytes"],
    }


def _fmt_disk(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.0f} MB"
    return f"{n:,} bytes"


def format_estimate(estimate: dict) -> str:
    """The dry-run report (T85): RAM fit, steps, disk, time — one
    line each, in plain words. Shared by the CLI flag and the
    Train panel's Estimate button."""
    available = estimate.get("ram_available_bytes")
    limit = estimate.get("limit_bytes", RAM_LIMIT_BYTES)
    dataset_bytes = estimate.get(
        "dataset_bytes",
        estimate.get("total_bytes", estimate["estimate_bytes"])
        - estimate["estimate_bytes"],
    )
    total_bytes = estimate.get(
        "total_bytes", estimate["estimate_bytes"] + dataset_bytes
    )
    if estimate["fits"]:
        fit = f"fits in {_gb(limit)}"
    elif available is not None and available < RAM_LIMIT_BYTES:
        fit = (
            f"will not fit: only {_gb(available)} free right now, "
            f"and the run needs {_gb(total_bytes)}"
        )
    else:
        fit = f"will not fit in {_gb(limit)}"
    lines = [
        f"RAM: about {_gb(estimate['estimate_bytes'])} for training "
        f"plus {_gb(dataset_bytes)} for the dataset ({fit}).",
        f"Steps: {estimate['steps']} "
        f"({estimate['train_examples']} training examples, "
        f"{estimate['val_examples']} held out to validate).",
        f"Disk: about {_fmt_disk(estimate['disk_bytes'])} "
        "(checkpoints plus the adapter plus the merged weights).",
        # R111(c): the time note already says "roughly" — the
        # doubled "(rough)" hedge is dropped.
        f"Time: {estimate['time_note']} on this PC.",
    ]
    if not estimate["fits"]:
        if available is not None and available < RAM_LIMIT_BYTES:
            lines.append(
                "This run will not fit right now. Close other "
                "programs and try again, train on a smaller "
                "dataset, or pick a smaller base model."
            )
        else:
            lines.append(
                "This run will not fit this PC. Train on a smaller "
                "dataset, pick a smaller base model, or train it "
                "elsewhere."
            )
    return "\n".join(lines)


def format_estimate_short(estimate: dict) -> str:
    """The one-line estimate for the Train panel label (T84): fit
    and time, no settings (T16 — the user never sees the knobs)."""
    available = estimate.get("ram_available_bytes")
    limit = estimate.get("limit_bytes", RAM_LIMIT_BYTES)
    # R24: the one-liner quotes the total the fit was judged on
    # (training plus dataset), so the number and the verdict agree.
    total_bytes = estimate.get(
        "total_bytes",
        estimate["estimate_bytes"]
        + estimate.get("dataset_bytes", 0),
    )
    total_gb = round(total_bytes / 1024**3, 2)
    if estimate["fits"]:
        if limit >= RAM_LIMIT_BYTES:
            return (
                f"Fits in 8 GB (about {total_gb} GB, dataset "
                f"included). "
                f"{estimate['steps']} steps, {estimate['time_note']}."
            )
        free = _gb(available) if available is not None else _gb(limit)
        return (
            f"Fits (about {total_gb} GB, "
            f"{free} free). "
            f"{estimate['steps']} steps, {estimate['time_note']}."
        )
    if available is not None and available < RAM_LIMIT_BYTES:
        return (
            f"Will not fit right now (about {total_gb} GB, "
            f"only {_gb(available)} free). Close other programs, "
            "train on a smaller dataset, or pick a smaller model."
        )
    return (
        f"Will not fit in 8 GB (about {total_gb} GB). "
        "Train on a smaller dataset, pick a smaller model, or "
        "train it elsewhere."
    )


# -- model loading --------------------------------------------------

def _looks_like_gguf_or_tag(base_ref: str) -> str | None:
    """Return why a base_ref is NOT trainable HF weights, or None.
    One rule, shared with the bridge (S23): a GGUF file, or an
    Ollama tag (a ":" version, or a bare name with no "/")."""
    kind, detail = classify_base_ref(base_ref)
    if kind in ("gguf", "ollama"):
        return detail
    return None


def load_base_model(base_ref: str, *, dtype: str = "bfloat16"):
    """Load tokenizer + base model from HF weights (never GGUF).

    Returns (model, tokenizer). dtype is "bfloat16" for real models
    (fits 8 GB) or "float32" for tiny test models.
    """
    require_training_deps()
    bad = _looks_like_gguf_or_tag(base_ref)
    if bad is not None:
        raise StellaError(bridge_error_message(base_ref))
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch_dtype = torch.bfloat16 if dtype == "bfloat16" else torch.float32
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            base_ref, trust_remote_code=True
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(
            base_ref, torch_dtype=torch_dtype, trust_remote_code=True,
        )
    except Exception as exc:
        # An HF load failure is a plain-words StellaError naming the
        # repo/path and the likely cause — never a raw traceback
        # from inside transformers (T5, A8-W9).
        raise StellaError(_hf_load_message(base_ref, exc)) from exc
    model.config.use_cache = False  # no KV cache while training
    return model, tokenizer


def _hf_load_message(base_ref: str, exc: Exception) -> str:
    """A plain-words cause for a failed from_pretrained call."""
    detail = str(exc).strip().splitlines()
    lowered = " ".join(detail).lower()
    if Path(base_ref).expanduser().is_dir():
        return (
            f"could not load the base model from {base_ref!r}: that "
            "folder does not hold a model (no tokenizer or weights "
            "found there)."
        )
    if "not found" in lowered or "404" in lowered or "no such" in lowered:
        return (
            f"could not load the base model {base_ref!r}: no model "
            "with that name was found. Check the name."
        )
    if any(
        word in lowered
        for word in ("connect", "timed out", "timeout", "resolve",
                     "network", "unreachable", "temporary failure")
    ):
        return (
            f"could not load the base model {base_ref!r}: the download "
            "failed. Check the network and try again."
        )
    # R80: the old fallback returned the first raw transformers
    # line verbatim — library internals in a user-facing message.
    # The generic closing branch says the same thing in plain
    # words; the raw line stays on the exception chain (the
    # caller raises `from exc`) for debugging.
    return (
        f"could not load the base model {base_ref!r}. Check the name "
        "and the network, then try again."
    )


def detect_target_modules(model, override: list[str] | None = None) -> list[str]:
    """Find the LoRA target modules this model actually has.

    Scans the model's linear layers and returns the leaf names that
    match known projection suffixes (q_proj, k_proj, ...). Raises if
    none match, naming what the model does have.

    `override` (T34) is a hand-supplied list for architectures the
    scan does not recognize: every name must exist as a linear
    layer leaf in the model (else the error names the missing ones
    and what the model does have), and the override is used as-is.
    An empty or missing override falls back to auto-detection.
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
    if override:
        missing = [name for name in override if name not in all_linear]
        if missing:
            raise StellaError(
                "target_modules names layers this model does not have: "
                f"{', '.join(missing)}. Its linear layers are named: "
                f"{', '.join(sorted(all_linear)) or 'none'}"
            )
        return sorted(set(override))
    if not found:
        raise StellaError(
            "No LoRA target modules found in this model. Its linear "
            f"layers are named: {', '.join(sorted(all_linear)) or 'none'}"
            ". To train it anyway, name the layers to train with "
            "--target-modules on the train command (e.g. "
            "--target-modules q_proj,k_proj), or set target_modules "
            "in the project settings."
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


# The probe content _chat_turn_end_ids renders through the
# template: distinctive, so find() lands on the content and not
# on template text.
_TURN_END_PROBE = "StellaTurnEndProbe"


def _chat_turn_end_ids(tokenizer) -> list[int]:
    """The tokens the tokenizer's chat template appends after an
    assistant message's content (T100) — e.g. [<|im_end|>] for a
    Qwen-shaped template. Found by rendering one probe assistant
    turn through the template and reading the tokens after the
    probe content. [] when there is no template, the template
    defines no terminator, or the terminator cannot be told from
    a turn separator: only special tokens count, so a trailing
    newline (the template's separator between turns) is never
    mistaken for one. A tokenizer with no special-token list
    yields [] rather than a guess."""
    if not hasattr(tokenizer, "apply_chat_template"):
        return []
    try:
        rendered = tokenizer.apply_chat_template(
            [{"role": "assistant", "content": _TURN_END_PROBE}],
            tokenize=False,
            add_generation_prompt=False,
        )
    except Exception:
        return []
    if not isinstance(rendered, str):
        return []
    idx = rendered.find(_TURN_END_PROBE)
    if idx < 0:
        return []
    suffix = rendered[idx + len(_TURN_END_PROBE):]
    if not suffix:
        return []
    try:
        ids = tokenizer.encode(suffix, add_special_tokens=False)
    except Exception:
        return []
    special = getattr(tokenizer, "all_special_ids", None)
    if special is None:
        return []
    return [i for i in ids if i in special]


class _SegmentationFailed(Exception):
    """The chat template would not segment into per-turn pieces
    (a prefix render is not a prefix of the full render) — the
    multi-turn tokenizer falls back to the plain renderer."""


def _template_segments(tokenizer, messages: list[dict]):
    """One multi-turn conversation as (text, is_completion)
    segments through the chat template (T156).

    For each assistant turn, the render up to that turn (with a
    generation prompt) is the masked prompt, and the render
    through the turn minus that prefix is the trained completion
    — content plus the template's own turn end. Anything the
    template appends after the last turn is masked prompt.
    Raises _SegmentationFailed when a prefix render is not a
    prefix of the longer render (some templates re-render the
    whole conversation when a turn is added).
    """
    segments: list[tuple[str, bool]] = []
    consumed = ""
    for j, msg in enumerate(messages):
        if msg["role"] != "assistant":
            continue
        pre = tokenizer.apply_chat_template(
            messages[:j], tokenize=False, add_generation_prompt=True
        )
        post = tokenizer.apply_chat_template(
            messages[:j + 1], tokenize=False, add_generation_prompt=False
        )
        if not isinstance(pre, str) or not isinstance(post, str):
            raise _SegmentationFailed()
        if not post.startswith(pre) or not pre.startswith(consumed):
            raise _SegmentationFailed()
        if pre[len(consumed):]:
            segments.append((pre[len(consumed):], False))
        if post[len(pre):]:
            segments.append((post[len(pre):], True))
        consumed = post
    full = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )
    if not isinstance(full, str) or not full.startswith(consumed):
        raise _SegmentationFailed()
    if full[len(consumed):]:
        segments.append((full[len(consumed):], False))
    return segments


def _fallback_segments(messages: list[dict]):
    """The same segmentation through the plain renderer (T156):
    'Role: content' lines, each assistant turn a completion.
    For a single-turn row this renders exactly what
    _render_fallback renders — the multi-turn path only runs
    when there is more than one assistant turn."""
    segments: list[tuple[str, bool]] = []
    for idx, msg in enumerate(messages):
        sep = "\n" if idx else ""
        if msg["role"] == "assistant":
            segments.append((sep + "Assistant:", False))
            segments.append((" " + msg["content"], True))
        else:
            segments.append(
                (sep + f"{msg['role'].capitalize()}: {msg['content']}", False)
            )
    return segments


def _tokenize_multi_turn(tokenizer, messages: list[dict], max_seq_len: int) -> dict:
    """Tokenize a multi-turn row (T156): EVERY assistant turn is
    trained (unmasked), every user/system/tool turn is masked
    prompt. The template path segments through apply_chat_template
    (each turn's end token rides inside its completion); the
    plain path segments through the fallback renderer and ends
    the row with the template turn end, or EOS when the template
    defines none (the same tail the single-turn path appends).

    Truncation cuts from the left of the whole row: the earliest
    prompt tokens go first, then the earliest turns — the most
    recent turns are always kept, and the final turn's end tokens
    are never cut. "truncated" says a completion token was cut.
    """
    templated = False
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            segments = _template_segments(tokenizer, messages)
            templated = True
        except Exception:
            segments = _fallback_segments(messages)
    else:
        segments = _fallback_segments(messages)
    input_ids: list[int] = []
    labels: list[int] = []
    for i, (text, is_completion) in enumerate(segments):
        if not text:
            continue
        if i == 0:
            ids = tokenizer.encode(text)
        else:
            ids = tokenizer.encode(text, add_special_tokens=False)
        input_ids.extend(ids)
        labels.extend(ids if is_completion else [-100] * len(ids))
    # The tail (T100): the template path already ends each turn
    # with the template's own terminator, so it needs nothing —
    # unless the template defines no terminator, in which case
    # EOS closes the row (the single-turn rule). The plain path
    # has no turn ends at all, so it always appends the tail.
    tail: list[int] = []
    if not templated or not _chat_turn_end_ids(tokenizer):
        turn_end = _chat_turn_end_ids(tokenizer)
        eos = tokenizer.eos_token_id
        tail = list(turn_end)
        if not tail and eos is not None:
            tail = [eos]
        input_ids.extend(tail)
        labels.extend(tail)
    truncated = False
    tail_len = len(tail)
    while len(input_ids) > max_seq_len and len(input_ids) > tail_len:
        dropped = labels.pop(0)
        input_ids.pop(0)
        if dropped != -100:
            truncated = True
    return {"input_ids": input_ids, "labels": labels, "truncated": truncated}


def tokenize_example(tokenizer, example: dict, max_seq_len: int) -> dict:
    """Tokenize one example into input_ids + labels.

    The prompt part is masked (-100) so loss is only on the completion
    — the model learns to WRITE the answer, not to predict the question.
    If the pair is too long, the prompt is cut from the left and the
    completion is kept whole.

    Multi-turn rows (T156) train EVERY assistant turn: each turn's
    completion is unmasked, each user/system/tool turn is masked.
    A single assistant turn takes the original path, unchanged.
    """
    messages = example["messages"]
    if sum(1 for m in messages if m["role"] == "assistant") > 1:
        return _tokenize_multi_turn(tokenizer, messages, max_seq_len)
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
    # End the completion the way the template ends a turn (T100):
    # when the chat template defines an assistant-turn end token
    # (<|im_end|> for a Qwen-shaped template), it goes on instead
    # of EOS — the tuned model learns to end its turn the way the
    # template expects, instead of running on in Ollama. With no
    # template terminator, EOS as before.
    turn_end = _chat_turn_end_ids(tokenizer)
    eos = tokenizer.eos_token_id
    tail = list(turn_end)
    if not tail and eos is not None:
        tail = [eos]
    completion_ids = completion_ids + tail
    # Bound the completion too (T99): the old code truncated only
    # the prompt, so a completion longer than max_seq_len sailed
    # through whole — a 200-char completion at max_seq_len=64 came
    # out as 202 tokens, and the RAM estimate assumes no sequence
    # exceeds the cap. An over-long completion is cut to the cap,
    # keeping its head and the end token; "truncated" says it
    # happened so the loop can count and report it.
    truncated = False
    if len(completion_ids) > max_seq_len:
        truncated = True
        head_len = max(0, max_seq_len - len(tail))
        completion_ids = completion_ids[:head_len] + tail
    if len(prompt_ids) + len(completion_ids) > max_seq_len:
        keep = max(0, max_seq_len - len(completion_ids))
        prompt_ids = prompt_ids[-keep:] if keep else []
    input_ids = prompt_ids + completion_ids
    labels = [-100] * len(prompt_ids) + list(completion_ids)
    return {"input_ids": input_ids, "labels": labels, "truncated": truncated}


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

def _dir_size_bytes(path: Path) -> int:
    """A directory's size in bytes (T150): every file under it,
    symlinks not followed. Unreadable files count 0 rather than
    failing the listing."""
    total = 0
    try:
        entries = list(path.rglob("*"))
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def list_checkpoints(
    store: Store, profile: str, project: str, *, ckpt_dir: Path | None = None
) -> list[dict]:
    """Checkpoints for a project, oldest first.

    `ckpt_dir` overrides the checkpoint folder — the sleep phase
    lists the checkpoints of one cycle, not the whole project.
    Each entry carries step, path, loss, epoch — plus size_bytes
    (the checkpoint's disk use, T150) and modified (its save time
    as a Unix timestamp, for the date the list shows).
    """
    if ckpt_dir is None:
        ckpt_dir = store.project_dir(profile, project) / "checkpoints"
    out = []
    if not ckpt_dir.is_dir():
        return out
    for d in sorted(ckpt_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("step-"):
            continue
        # R77: a `.tmp` dir is a save in progress, not a
        # checkpoint — never listed, never resumed from.
        if d.name.endswith(".tmp"):
            continue
        state_file = d / "training_state.json"
        if not state_file.is_file():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        try:
            modified = state_file.stat().st_mtime
        except OSError:
            modified = 0.0
        out.append(
            {
                "step": state.get("step", 0),
                "path": str(d),
                "loss": state.get("loss"),
                "epoch": state.get("epoch"),
                "size_bytes": _dir_size_bytes(d),
                "modified": modified,
            }
        )
    out.sort(key=lambda c: c["step"])
    return out


def delete_checkpoint(store: Store, profile: str, project: str,
                      step: int) -> dict:
    """Delete one checkpoint, permanently (T150).

    The point is freeing disk — the trash does not free disk, so
    there is no trash here. The caller confirms first (the window
    asks, showing the size, defaulting to No). Returns the step
    and the bytes freed. Raises StellaError when the checkpoint
    does not exist.
    """
    ckpt_dir = (
        store.project_dir(profile, project) / "checkpoints" / f"step-{step}"
    )
    if not ckpt_dir.is_dir():
        raise StellaError(
            f"no checkpoint step-{step} for project {project!r}"
        )
    freed = _dir_size_bytes(ckpt_dir)
    shutil.rmtree(ckpt_dir)
    return {"step": int(step), "freed_bytes": freed}


def prune_checkpoints(store: Store, profile: str, project: str,
                      keep: int = 3) -> dict:
    """Delete all but the newest N checkpoints (T150).

    Permanent, like delete_checkpoint — the caller confirms
    first, showing the size before and after. Returns the kept
    and deleted steps, the total size before and after, and the
    bytes freed. `keep` must be at least 1: pruning to zero
    would destroy every resume point.
    """
    if keep < 1:
        raise StellaError(
            "pruning must keep at least 1 checkpoint (the newest "
            "one is the resume point)"
        )
    checkpoints = list_checkpoints(store, profile, project)
    total_before = sum(c["size_bytes"] for c in checkpoints)
    kept = checkpoints[-keep:] if checkpoints else []
    doomed = checkpoints[:-keep] if len(checkpoints) > keep else []
    freed = 0
    deleted_steps: list[int] = []
    for ck in doomed:
        freed += _dir_size_bytes(Path(ck["path"]))
        shutil.rmtree(ck["path"])
        deleted_steps.append(ck["step"])
    total_after = total_before - freed
    return {
        "kept": [c["step"] for c in kept],
        "deleted": deleted_steps,
        "freed_bytes": freed,
        "total_before": total_before,
        "total_after": total_after,
    }


def _save_checkpoint(model, optimizer, ckpt_dir: Path, state: dict) -> None:
    import torch

    # R77: write to a tmp dir and rename into place — a crash
    # mid-save leaves a `.tmp` dir, never a half-written step-N.
    # A stale tmp dir from a crashed save is cleared first. A
    # previous save of this same step is replaced only once the
    # new one is complete (rename onto a non-empty dir fails, so
    # the old dir goes just before the rename — the window where
    # the step is missing is one rename). A failed save removes
    # the tmp dir and leaves any previous step-N untouched.
    tmp_dir = ckpt_dir.with_name(ckpt_dir.name + ".tmp")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        model.save_pretrained(str(tmp_dir))
        torch.save(
            {
                "optimizer": optimizer.state_dict(),
                "step": state["step"],
                "epoch": state["epoch"],
                "examples_seen_in_epoch": state["examples_seen_in_epoch"],
                # The torch RNG state (T32): resume restores it, so the
                # dropout draws continue exactly where they left off
                # and a paused run is bit-identical to an uninterrupted
                # one. A ByteTensor loads fine under weights_only=True.
                "rng_state": torch.get_rng_state(),
            },
            tmp_dir / "optimizer.pt",
        )
        (tmp_dir / "training_state.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    if ckpt_dir.exists():
        shutil.rmtree(ckpt_dir)
    tmp_dir.rename(ckpt_dir)


def list_orphan_checkpoints(
    store: Store, profile: str, project: str, *, ckpt_dir: Path | None = None
) -> list[dict]:
    """Orphan checkpoint folders for a project (R77): step dirs
    with no readable training_state.json (a crash mid-save, from
    before tmp+rename) plus stale `.tmp` dirs (a crash mid-save
    since). Each entry carries name, path, size_bytes, modified.
    A live run's in-progress tmp dir looks exactly like a stale
    one — callers must not reap without the grace (see
    reap_orphan_checkpoints) or the job lock."""
    if ckpt_dir is None:
        ckpt_dir = store.project_dir(profile, project) / "checkpoints"
    out = []
    if not ckpt_dir.is_dir():
        return out
    for d in sorted(ckpt_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("step-"):
            continue
        orphan = False
        if d.name.endswith(".tmp"):
            orphan = True
        else:
            state_file = d / "training_state.json"
            if not state_file.is_file():
                orphan = True
            else:
                try:
                    json.loads(state_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                    orphan = True
        if not orphan:
            continue
        try:
            modified = d.stat().st_mtime
        except OSError:
            modified = 0.0
        out.append(
            {
                "name": d.name,
                "path": str(d),
                "size_bytes": _dir_size_bytes(d),
                "modified": modified,
            }
        )
    return out


# R77: an orphan younger than this is left alone unless the caller
# holds the job lock (force=True) — a live run's in-progress save
# looks exactly like a crashed one.
ORPHAN_GRACE_SECONDS = 3600


def reap_orphan_checkpoints(
    store: Store, profile: str, project: str, *,
    ckpt_dir: Path | None = None,
    force: bool = False,
) -> dict:
    """Delete orphan checkpoint folders (R77). Without force, only
    orphans older than ORPHAN_GRACE_SECONDS go — a live run's
    in-progress save is never touched. With force (the caller
    holds the job lock, so no run is writing), every orphan goes.
    Returns the reaped names, the skipped (too young) names, and
    the bytes freed."""
    import time

    orphans = list_orphan_checkpoints(
        store, profile, project, ckpt_dir=ckpt_dir
    )
    now = time.time()
    reaped: list[str] = []
    skipped: list[str] = []
    freed = 0
    for orphan in orphans:
        if not force and now - orphan["modified"] < ORPHAN_GRACE_SECONDS:
            skipped.append(orphan["name"])
            continue
        path = Path(orphan["path"])
        freed += _dir_size_bytes(path)
        shutil.rmtree(path, ignore_errors=True)
        reaped.append(orphan["name"])
    return {
        "reaped": reaped,
        "skipped": skipped,
        "freed_bytes": freed,
    }


def _append_log(project_dir: Path, record: dict) -> None:
    with (project_dir / "train_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _emit_warning(on_event, message: str) -> None:
    """A warning event, when there is someone listening."""
    if on_event is not None:
        on_event({"type": "warning", "message": message})


def _oom_error(exc: BaseException) -> StellaError | None:
    """R76: the plain-words StellaError for an out-of-memory
    failure, or None when the exception is not one. The wording
    is tool_errors' — the same message the llama.cpp paths use."""
    from .tool_errors import oom_message

    message = oom_message(exc)
    return StellaError(message) if message is not None else None


def _run_started_at() -> str:
    """The run id (T151): the start time, ISO, UTC — unique per
    run and readable in the log without decoding anything."""
    return datetime.now(timezone.utc).isoformat()


def list_runs(project_dir: str | Path) -> list[dict]:
    """Past runs for one project, oldest first (T151), rebuilt
    from train_log.jsonl.

    Each run is date (started_at), steps, final loss, total
    steps, whether it stopped early, and its loss curve
    ([(step, loss), ...]) for the chart. Runs written since
    v0.20.0 carry explicit run_started / run_finished records;
    older logs split on a step that goes down (a new run starts
    at step 1 again), the same boundary the live chart uses.
    The settings snapshot rides in the run_started record for
    future comparison — stored, never displayed (T16: the user
    never sees settings values).
    """
    log_path = Path(project_dir) / "train_log.jsonl"
    runs: list[dict] = []
    if not log_path.is_file():
        return runs
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return runs

    def new_run(started_at: str | None) -> dict:
        return {
            "run_id": started_at or "",
            "started_at": started_at,
            "steps": 0,
            "total_steps": 0,
            "final_loss": None,
            "stopped": False,
            "finished": False,
            "points": [],
        }

    current: dict | None = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        event = record.get("event")
        if event == "run_started":
            current = new_run(record.get("started_at"))
            current["total_steps"] = int(record.get("total_steps") or 0)
            current["run_id"] = record.get("run_id") or current["run_id"]
            runs.append(current)
            continue
        if event == "run_finished":
            if current is None:
                current = new_run(record.get("started_at"))
                runs.append(current)
            current["finished"] = True
            current["stopped"] = bool(record.get("stopped"))
            try:
                current["steps"] = int(record.get("steps") or current["steps"])
            except (TypeError, ValueError):
                pass
            final = record.get("final_loss")
            if final is not None:
                try:
                    current["final_loss"] = float(final)
                except (TypeError, ValueError):
                    pass
            continue
        if "loss" not in record or "step" not in record:
            continue
        try:
            step = int(record["step"])
            loss = float(record["loss"])
        except (TypeError, ValueError):
            continue
        if current is None:
            # A log from before run records: the first step opens
            # an implicit run.
            current = new_run(None)
            runs.append(current)
        elif current["points"] and step <= current["points"][-1][0]:
            # A step that goes down starts a new run (an old log
            # with no run_started record, or a resumed run that
            # restarted its numbering).
            current = new_run(None)
            runs.append(current)
        current["points"].append((step, loss))
        current["steps"] = max(current["steps"], step)
        if current["final_loss"] is None or step >= current["steps"]:
            current["final_loss"] = loss
        try:
            current["total_steps"] = int(
                record.get("total_steps") or current["total_steps"]
            )
        except (TypeError, ValueError):
            pass
    # A run that never finished has no final loss of its own —
    # its last point is the latest loss, which the loop above
    # already recorded.
    return runs


def _settings_drift(stored: dict, current: dict) -> list[str]:
    """Keys whose value changed between the stored run settings
    and the current ones (T98), in stored order. A stored key the
    current run does not carry counts as drift too."""
    return [
        key
        for key, value in stored.items()
        if key not in current or current[key] != value
    ]


def _record_mode_in_adapter_config(adapter_dir: Path, mode: str) -> None:
    """Write the training mode into the adapter's own config
    (T143). peft writes adapter_config.json, so the mode is added
    with a post-write edit; peft ignores the extra key on load
    (it warns, and the CLI filters that notice — see
    cli._silence_library_warnings). A config that cannot be read
    back is left alone: the summary already carries the mode."""
    config_path = Path(adapter_dir) / "adapter_config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(config, dict):
        return
    config["metamorph_mode"] = mode
    try:
        config_path.write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


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


def dataset_fingerprint(path: str | Path, row_count: int) -> dict:
    """A dataset's fingerprint (R26): the SHA-256 of the file
    bytes plus the row count. Stored in every checkpoint's state;
    on resume the stored fingerprint is compared with the current
    dataset, so an edit between pause and resume is refused
    instead of silently training the wrong rows. The hash is
    streamed (1 MB chunks), so fingerprinting never holds the
    file in memory."""
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "rows": int(row_count)}


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
    max_steps: int | None = None,
    extending: bool = False,
    mode: str | None = None,
    dataset_fingerprint: dict | None = None,
) -> dict:
    """The loop itself, separated from model loading so tests can pass
    a tiny random model. Returns a summary dict (steps, total_steps,
    final_loss, final_val_loss, stopped, checkpoint). `max_steps` caps
    the run at that many optimizer steps from `start_step` (T56):
    reaching the cap is completion, not a pause — the adapter is
    saved and the run reports done. `extending` (T25) marks a
    resume on a project that already finished training: the loop
    announces the extension and the new total before starting.
    `mode` (T143) is the project's stored metamorph mode string,
    recorded in the training summary and the adapter config at
    train time; None records nothing. `dataset_fingerprint` (R26)
    is the dataset's fingerprint dict, stored in every checkpoint
    state so a resume can tell whether the dataset changed since
    the pause; None (a caller that has no dataset file) stores
    nothing."""
    # Validate first, before the torch import: a bad value is
    # refused with a plain message naming the setting, never a raw
    # ValueError/ZeroDivisionError from a bare int()/float() (T6).
    checked = validate_run_settings(config)
    # The run's settings, snapshotted into every checkpoint state
    # (T98): on resume, the stored settings are compared with the
    # run's fresh ones, so a changed rank (or any other knob) is
    # warned about instead of silently dropped. val_fraction rides
    # along: it shapes the train/val split, which resume rebuilds.
    snapshot_settings = dict(checked)
    try:
        snapshot_settings["val_fraction"] = float(
            config.get("val_fraction", 0.1)
        )
    except (TypeError, ValueError):
        snapshot_settings["val_fraction"] = 0.1
    import torch

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    batch_size = checked["batch_size"]
    grad_accum = checked["grad_accum"]
    max_seq_len = checked["max_seq_len"]
    epochs = checked["epochs"]
    lr = checked["learning_rate"]
    rank = checked["rank"]
    warmup = checked["warmup_steps"]
    checkpoint_steps = checked["checkpoint_steps"]
    seed = checked["seed"]
    use_bf16 = next(model.parameters()).dtype == torch.bfloat16

    steps_per_epoch = max(1, math.ceil(len(train_examples) / (batch_size * grad_accum)))
    schedule_total = steps_per_epoch * epochs
    # A step cap (T56) is a remaining-steps budget from wherever
    # the run starts — fresh or resumed — never more than the
    # schedule itself. The LR schedule decays over the capped
    # total, so a short proof run still anneals properly.
    if max_steps is not None:
        if max_steps <= 0:
            raise StellaError("--steps must be at least 1.")
        total_steps = min(schedule_total, start_step + max_steps)
    else:
        total_steps = schedule_total
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

    # A resume on a project that already finished training extends
    # it past what the user originally asked for (T25): say so
    # first, with the new total — before the "started" line, so the
    # announcement is the first thing the user reads. The CLI and
    # GUI both print it.
    # The run record (T151) opens the run in the log first: the
    # run history splits runs on it, and the settings snapshot
    # rides along for future comparison (stored, never displayed).
    run_id = _run_started_at()
    _append_log(
        project_dir,
        {
            "event": "run_started",
            "run_id": run_id,
            "started_at": run_id,
            "total_steps": total_steps,
            "settings": snapshot_settings,
        },
    )
    if extending:
        emit(
            {
                "type": "extending",
                "trained_steps": start_step,
                "new_total": total_steps,
            }
        )
    emit({"type": "started", "total_steps": total_steps, "rank": rank})
    # Over-long completions were cut to fit (T99): say how many, so
    # the user knows the data was shortened instead of wondering why
    # the model never learned the long answers.
    cut = sum(1 for b in tokenized if b.get("truncated"))
    if cut:
        emit(
            {
                "type": "warning",
                "message": (
                    f"{cut} example(s) were longer than {max_seq_len} "
                    "tokens and were cut short to fit. Shorten them, "
                    "or raise max seq len, to train on the full text."
                ),
            }
        )
    model.train()
    step = start_step
    stopped = False
    # The last step saved in-loop (T159): when the final step is
    # a checkpoint step, the loop already saved it — the final
    # save below must not save (and emit) it twice.
    last_saved_step: int | None = None
    last_loss: float | None = None
    # The final val loss (T96): the last epoch-end validation, so
    # the run summary can report whether the tune generalized.
    # None when no epoch finished (a run stopped mid-first-epoch
    # never validated).
    last_val_loss: float | None = None
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
        # Steps taken in this epoch (T109): a resumed epoch the
        # run never trained in — paused exactly at its end — has
        # none, and re-validating it would print a stale line for
        # an epoch the resumed run did not train.
        steps_this_epoch = 0
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
            steps_this_epoch += 1
            record = {
                "step": step,
                # The run total, so the GUI can re-render this line
                # later as the same friendly "step N/total" text the
                # user watched live (T13).
                "total_steps": total_steps,
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
                    "settings": snapshot_settings,
                }
                # R26: the dataset fingerprint rides in every
                # checkpoint, so a resume can tell whether the
                # dataset changed since the pause.
                if dataset_fingerprint is not None:
                    state["dataset_fingerprint"] = dict(dataset_fingerprint)
                ckpt = project_dir / "checkpoints" / f"step-{step}"
                _save_checkpoint(model, optimizer, ckpt, state)
                last_saved_step = step
                emit({"type": "checkpoint", "step": step, "path": str(ckpt)})
            if controller is not None and controller.stop_requested:
                stopped = True
                break
            if step >= total_steps:
                # The step cap (T56): a completed short run, not a
                # pause — break out mid-epoch, save the adapter,
                # report done.
                break
        if stopped:
            break
        if steps_this_epoch == 0:
            # No new steps in this epoch (a resume that landed
            # exactly at its end): skip the validation, or the
            # output claims an epoch finished that this run never
            # trained (T109).
            if step >= total_steps:
                break
            continue
        val_loss = evaluate()
        if val_loss is not None:
            last_val_loss = val_loss
            _append_log(
                project_dir,
                {"step": step, "epoch": epoch + 1, "val_loss": round(val_loss, 4)},
            )
            emit({"type": "val", "epoch": epoch + 1, "loss": val_loss})
        if step >= total_steps:
            break

    # Final checkpoint (also the resume point if the run is paused).
    # T159: when the last step was already saved in-loop, the final
    # save is skipped — same directory, same content, one event.
    # The checkpoint path still names the step, for the return and
    # the paused event below.
    ckpt = project_dir / "checkpoints" / f"step-{step}"
    if last_saved_step != step:
        state = {
            "step": step,
            "epoch": min(epochs, epoch + 1) if not stopped else epoch + 1,
            "loss": last_loss,
            "examples_seen_in_epoch": examples_seen,
            "stella_version": STELLA_VERSION,
            "settings": snapshot_settings,
        }
        # R26: the final checkpoint carries the fingerprint too.
        if dataset_fingerprint is not None:
            state["dataset_fingerprint"] = dict(dataset_fingerprint)
        _save_checkpoint(model, optimizer, ckpt, state)
        emit({"type": "checkpoint", "step": step, "path": str(ckpt)})

    if not stopped:
        adapter_dir = project_dir / "adapter"
        if adapter_dir.exists():
            shutil.rmtree(adapter_dir)
        model.save_pretrained(str(adapter_dir))
        tokenizer.save_pretrained(str(adapter_dir))
        # Provenance (T143): the mode the project was in when it
        # trained, recorded as stored — so a future "was this
        # adapter compressed?" has an answer in the artifacts. The
        # adapter config carries it too, via a post-write edit
        # (peft writes that file, not Stella).
        summary_data = {
            "steps": step,
            "epochs": epochs,
            "final_loss": last_loss,
            "final_val_loss": last_val_loss,
            "rank": rank,
            "stella_version": STELLA_VERSION,
        }
        if mode is not None:
            summary_data["metamorph_mode"] = mode
            _record_mode_in_adapter_config(adapter_dir, mode)
        (adapter_dir / "training_summary.json").write_text(
            json.dumps(summary_data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        emit({"type": "done", "steps": step, "adapter": str(adapter_dir)})
    else:
        emit({"type": "paused", "step": step, "path": str(ckpt)})

    # The run record closes (T151): the history reads the steps
    # and final loss off this line. A crashed run never writes
    # one — the history shows its points with no finish line.
    _append_log(
        project_dir,
        {
            "event": "run_finished",
            "run_id": run_id,
            "steps": step,
            "final_loss": last_loss,
            "stopped": stopped,
        },
    )

    return {
        "steps": step,
        "total_steps": total_steps,
        "final_loss": last_loss,
        "final_val_loss": last_val_loss,
        "stopped": stopped,
        "checkpoint": str(ckpt),
    }


# -- crashed-run reconciliation (R27) ------------------------------
# A hard crash (an OOM kill, power loss, the window closed
# mid-run) writes nothing: the project keeps status "training"
# forever and the list shows a dead run as live. The fix is a
# reconciliation at start-up: a "training" project with no live
# job behind it is a crashed run. It becomes "paused" when
# checkpoints exist (it can be resumed) and "failed" when none
# do, and the run log gains a run_crashed record so the history
# shows the crash. The job lock is the liveness signal — the
# kernel releases it when the holder dies — so a run on another
# process is never misread as dead.


def reconcile_stale_training(store: Store) -> list[dict]:
    """Mark crashed runs as crashed (R27).

    Every project whose status is "training" while no job holds
    the home's lock is a run that died without writing its
    ending: it becomes "paused" when checkpoints exist (the run
    can be resumed) and "failed" otherwise. Returns one entry
    per reconciled run: profile, project, status ("paused" or
    "failed"), and resumable (True when checkpoints exist, so
    the caller can offer resume). Returns [] when a job is live
    — a "training" status then may be the live run itself.
    Never raises on a damaged row: a project that cannot be read
    is skipped, not reconciled."""
    from .job_lock import job_lock_held

    reconciled: list[dict] = []
    if job_lock_held(store.home):
        return reconciled
    for prof in store.list_profiles():
        if prof.get("_damaged"):
            continue
        profile = prof["name"]
        for proj in store.list_projects(profile):
            if proj.get("_damaged"):
                continue
            if proj.get("status") != "training":
                continue
            project = proj["name"]
            try:
                checkpoints = list_checkpoints(store, profile, project)
            except StellaError:
                continue
            resumable = bool(checkpoints)
            new_status = "paused" if resumable else "failed"
            try:
                store.update_project(profile, project, status=new_status)
            except StellaError:
                continue
            _append_log(
                store.project_dir(profile, project),
                {
                    "event": "run_crashed",
                    "status": new_status,
                    "resumable": resumable,
                },
            )
            reconciled.append(
                {
                    "profile": profile,
                    "project": project,
                    "status": new_status,
                    "resumable": resumable,
                }
            )
    return reconciled


# -- project-level entry point --------------------------------------

def train_project(
    store: Store,
    profile: str,
    project: str,
    *,
    max_steps: int | None = None,
    resume: bool = False,
    from_checkpoint: int | None = None,
    dataset_path: str | Path | None = None,
    base_ref: str | None = None,
    on_event=None,
    controller: TrainController | None = None,
    force: bool = False,
    _model_loader=None,
    _dtype: str = "bfloat16",
    work_dir: str | Path | None = None,
    update_status: bool = True,
    settings_override: dict | None = None,
    target_modules: list[str] | None = None,
    _skip_job_lock: bool = False,
    cli: bool = False,
) -> dict:
    """Train one project end to end. Returns a summary dict.

    `_model_loader` is a test hook: a callable returning
    (model, tokenizer) so tests can train a tiny random model with no
    downloads. Real runs always load from Hugging Face.

    `from_checkpoint` (T150) resumes from checkpoints/step-N
    instead of the latest one — it implies resume. A missing step
    is refused before anything loads, naming the checkpoints that
    do exist.

    `work_dir` overrides where checkpoints, the adapter, and the log
    go (default: the project dir). The sleep phase trains into its
    own cycle dir. `update_status=False` leaves the project status
    untouched — sleep is a background consolidation job, not a
    retrain of the project. `settings_override` merges over the
    project settings for this run only (sleep caps the LoRA rank
    at 8) without touching the stored project. `target_modules`
    (T34) is a hand-supplied LoRA target list for architectures
    the auto-detection does not recognize; it wins over the
    stored setting, and an empty or missing list falls back to
    auto-detection. `_skip_job_lock` skips the one-job lock (T29):
    sleep passes it because it already holds the lock for the
    whole cycle.
    `cli` (T111) words the no-dataset error for the terminal
    (--dataset) instead of the window (the Train panel).
    """
    # The step cap is validated first, before the training deps
    # are even required (T56): 0 or a negative number is refused
    # with a plain message on any machine, torch or no torch.
    if max_steps is not None:
        try:
            max_steps = int(max_steps)
        except (TypeError, ValueError):
            raise StellaError(
                "--steps must be a whole number of steps."
            ) from None
        if max_steps <= 0:
            raise StellaError("--steps must be at least 1.")
    # A from-checkpoint resume is a resume (T150): the checkpoint
    # picker passes the step and nothing else.
    if from_checkpoint is not None:
        resume = True
    # Cheap checks first (T48): the profile lookup, settings,
    # trained-refusal, base_ref, and dataset resolution below all
    # run BEFORE the dependency gate, so a base install reports
    # the real problem (a wrong profile name, a missing dataset)
    # instead of the deps message. The gate sits inside the job
    # lock, after every cheap check.
    prof = store.get_profile(profile)
    proj = store.get_project(profile, project)
    project_dir = store.project_dir(profile, project)
    work_dir = Path(work_dir) if work_dir is not None else project_dir
    work_dir.mkdir(parents=True, exist_ok=True)

    # Auto projects re-resolve their settings from a fresh
    # measurement at run start (manual ones are untouched). Sleep
    # runs (update_status=False) never rewrite the project — the
    # consolidation job trains with its own override.
    if update_status:
        refresh_auto_settings(
            store, profile, project,
            on_event=on_event, work_dir=work_dir,
        )
        proj = store.get_project(profile, project)

    settings = dict(DEFAULT_TRAIN)
    settings.update(proj.get("settings", {}) or {})
    if settings_override:
        settings.update(settings_override)
    # Engine-side range check on the effective settings, before
    # anything loads (T6, D6).
    settings.update(validate_run_settings(settings))
    # R28: a project stored with method "full" (set before v0.26.0
    # closed the CLI path) still trains LoRA — there is no full
    # path in the engine. Say so at run start, never silently.
    if settings.get("method") == "full":
        _emit_warning(
            on_event,
            "this project says method full, but Stella always "
            "trains with LoRA on this PC, so this run trains LoRA. "
            "Full fine-tuning needs far more RAM than this PC has.",
        )

    # A finished project is not re-trained by accident (T25): a
    # fresh run on one refuses unless --force makes the intent
    # explicit. Sleep (update_status=False) is a background
    # consolidation job, not a retrain — it is never blocked.
    if update_status and not resume and not force:
        if proj.get("status") == "done":
            raise StellaError(
                f"project {project!r} is already trained. Use "
                "--force to re-train it (the current adapter will "
                "be replaced)."
            )

    # Training trusts base_ref (T54): the Hugging Face repo or
    # local folder of the weights — never the Ollama tag, which is
    # how Ollama knows the model, not where the weights live. The
    # tag and the ref usually match (the store syncs them), and
    # differ only when the weights live somewhere else.
    ref = base_ref or prof.get("base_ref") or ""
    if not ref:
        raise StellaError(
            f"profile {profile!r} has no base_ref. Set it to the "
            f"Hugging Face repo of the base model (e.g. {LFM3_HF_REPO!r})"
        )
    # Refuse GGUF / Ollama tags here, not just in load_base_model —
    # the check must hold even when a test injects a model loader.
    # The bridge error (S23) names the likely Hugging Face repo and
    # the `stella bridge` command.
    bad = _looks_like_gguf_or_tag(ref)
    if bad is not None:
        raise StellaError(bridge_error_message(ref))

    # Dataset first (cheap), model second (expensive).
    if dataset_path is not None:
        data_path = Path(dataset_path).expanduser()
        if not data_path.is_file():
            raise StellaError(f"dataset not found: {data_path}")
    else:
        dataset_ref = proj.get("dataset_ref") or ""
        if not dataset_ref:
            raise _no_dataset_error(project, cli=cli)
        data_path = resolve_dataset_ref(store, profile, project, dataset_ref)
    examples, info = load_dataset(data_path)
    train_examples, val_examples = split_dataset(
        examples,
        float(settings.get("val_fraction", 0.1)),
        int(settings.get("seed", 42)),
    )
    # R26: the dataset's fingerprint — stored in every checkpoint
    # this run writes, and compared with the stored one on resume.
    fingerprint = dataset_fingerprint(data_path, len(examples))
    # The dataset-size warning (T158): a big dataset is said out
    # loud before tokenization, with its size — the run still
    # starts, but the user knows it will be heavy. The refusal
    # (a dataset that will not fit alongside the model) comes
    # later, once the training estimate exists.
    dataset_bytes = estimate_dataset_bytes(
        info.get("bytes", 0),
        (
            (info["avg_prompt_chars"] + info["avg_completion_chars"])
            * len(examples)
        )
        // CHARS_PER_TOKEN,
    )
    if (
        info.get("bytes", 0) > DATASET_WARN_BYTES
        or len(examples) > DATASET_WARN_ROWS
    ):
        _emit_warning(
            on_event,
            f"This dataset is large ({len(examples):,} examples, "
            f"about {_fmt_disk(info.get('bytes', 0))}). It will use "
            f"about {_gb(dataset_bytes)} of RAM while training, "
            "on top of the model.",
        )

    # --resume with no checkpoints is refused here (T48), before
    # the deps gate — the user should not have to install the
    # training stack to learn there is nothing to resume. The list
    # is reused inside the lock for the actual resume.
    resume_checkpoints = None
    resume_step = None
    # R26: True when the chosen checkpoint carries no dataset
    # fingerprint (saved before v0.26.0) — the resume goes ahead,
    # but the run warns that it cannot tell whether the dataset
    # changed since the pause.
    resume_fingerprint_unknown = False
    if resume:
        resume_checkpoints = list_checkpoints(
            store, profile, project, ckpt_dir=work_dir / "checkpoints"
        )
        if not resume_checkpoints:
            raise StellaError(
                "nothing to resume. This project has no checkpoints yet"
            )
        if from_checkpoint is not None:
            # Resume from a SELECTED checkpoint (T150): the step
            # must exist, and the refusal names what does.
            steps = [c["step"] for c in resume_checkpoints]
            if from_checkpoint not in steps:
                have = ", ".join(
                    f"step-{s}" for s in steps
                )
                raise StellaError(
                    f"no checkpoint step-{from_checkpoint} for "
                    f"project {project!r}. This project has: {have}"
                )
            resume_step = from_checkpoint
        # R26: the dataset check runs here, before the lock, the
        # deps gate, and the model load — a changed dataset
        # refuses cheaply. The chosen checkpoint's stored
        # fingerprint is compared with the current dataset's; a
        # mismatch refuses (resuming would train the wrong rows),
        # and a missing fingerprint (an old checkpoint) is noted
        # for the warning in the resume block below.
        chosen_step = (
            resume_step
            if resume_step is not None
            else resume_checkpoints[-1]["step"]
        )
        chosen = next(
            c for c in resume_checkpoints if c["step"] == chosen_step
        )
        state_file = Path(chosen["path"]) / "training_state.json"
        try:
            stored_state = json.loads(
                state_file.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            stored_state = {}
        stored_fp = (
            stored_state.get("dataset_fingerprint")
            if isinstance(stored_state, dict)
            else None
        )
        if isinstance(stored_fp, dict):
            if stored_fp != fingerprint:
                raise StellaError(
                    "the dataset changed since the pause, so "
                    "resuming would train the wrong rows. Start a "
                    "fresh run instead (the old checkpoints stay "
                    "on disk), or put the dataset back the way it "
                    "was and resume again."
                )
        else:
            resume_fingerprint_unknown = True

    # One job at a time (T29): the engine lock. The cheap checks
    # above ran without it, so a bad profile or dataset is still
    # reported even while another job runs — but from here on this
    # run loads models, so it holds the home's job lock until it
    # returns. Sleep passes _skip_job_lock: it already holds the
    # lock for the whole cycle (train + replay).
    with job_lock(
        store.home, f"training {profile}/{project}",
        skip=_skip_job_lock,
    ):
        # The deps gate (T48): the cheap checks above ran first, so
        # this message only appears when the run is otherwise ready
        # to start.
        require_training_deps()

        # The RAM guard estimates BEFORE loading anything (T28): the
        # estimate comes from the model's config + weight sizes, never
        # from a loaded model. A run that will not fit is refused here,
        # before the base is anywhere near memory. (A test-injected
        # loader skips the pre-load estimate — the test controls its own
        # fake world — and the post-load guard below still applies.)
        if _model_loader is None:
            pre_estimate, _ = estimate_training_from_metadata(ref, settings)
            # S6: the guard judges against what is free right now,
            # not just the fixed ceiling — a run Ollama has already
            # crowded out must refuse before it loads anything.
            available = available_ram_bytes()
            check_ram_fit(pre_estimate, available_bytes=available)
            # The dataset fit (T158): the dataset must fit
            # alongside the model, not just the model on its own.
            check_dataset_fit(
                dataset_bytes, pre_estimate, available_bytes=available
            )
            # R79: the disk guard — a run must not start on a disk
            # that cannot hold its checkpoints. The metadata read
            # is the same one the RAM guard just did (cached by
            # the Hub client on the second call). A test-injected
            # loader skips it, like the RAM guard above.
            meta = load_model_metadata(ref)
            trainable = estimate_lora_params(
                hidden_size=meta["hidden_size"],
                intermediate_size=meta["intermediate_size"],
                num_layers=meta["num_layers"],
                rank=int(settings.get("rank", 8)),
            )
            total_steps = (
                max(
                    1,
                    math.ceil(
                        len(train_examples)
                        / (
                            int(settings.get("batch_size", 1))
                            * int(settings.get("grad_accum", 8))
                        )
                    ),
                )
                * int(settings.get("epochs", 3))
            )
            try:
                free_disk = shutil.disk_usage(work_dir).free
            except OSError:
                free_disk = None
            check_disk_fit(
                estimate_run_disk_bytes(
                    base_bytes=meta["base_bytes"],
                    trainable_params=trainable,
                    total_steps=total_steps,
                    checkpoint_steps=int(
                        settings.get("checkpoint_steps", 50)
                    ),
                ),
                free_disk,
            )

        # T165: the profile was just used — a real training run
        # (not a sleep consolidation, which passes
        # update_status=False) stamps last-used when the run
        # starts. Every refusal above (bad dataset, no resume,
        # missing deps, will-not-fit) happens before this line,
        # so a run that never started never stamps.
        if update_status:
            store.touch_last_used(profile)

        # R77: a crashed save leaves orphan checkpoint folders —
        # this run holds the job lock, so no other run is writing
        # and every orphan is safe to reap. Said out loud (event
        # + run log), so a reaped folder is never a mystery.
        reaped = reap_orphan_checkpoints(
            store, profile, project,
            ckpt_dir=work_dir / "checkpoints", force=True,
        )
        if reaped["reaped"]:
            count = len(reaped["reaped"])
            message = (
                f"cleaned up {count} unfinished checkpoint "
                f"folder{'s' if count != 1 else ''} from an "
                "interrupted save "
                f"({_fmt_disk(reaped['freed_bytes'])} freed)."
            )
            if on_event is not None:
                on_event({"type": "warning", "message": message})
            _append_log(work_dir, {"event": "warning", "message": message})

        # Load the base, then check the guard a second time with the
        # real param counts (belt and braces: the pre-load estimate
        # already refused anything that cannot fit).
        # T108: the base load is a blocking call — a first run
        # downloads gigabytes before the loop the stop flag can
        # reach. Say so before it starts, so a Ctrl+C during the
        # download is not a mystery: the first press waits for the
        # download, the second exits at once (the CLI handler).
        if on_event is not None:
            on_event({
                "type": "loading",
                "model": ref,
                "message": (
                    f"Loading {ref}... The first run downloads "
                    "it, and Ctrl+C takes effect when the "
                    "download finishes."
                ),
            })
        # R76: the base load is the first big allocation — an
        # out-of-memory here gets the plain-words message, not
        # raw torch text.
        try:
            if _model_loader is not None:
                model, tokenizer = _model_loader()
            else:
                model, tokenizer = load_base_model(ref, dtype=_dtype)
        except Exception as exc:
            oom = _oom_error(exc)
            if oom is not None:
                raise oom from exc
            raise
        import torch
        from peft import LoraConfig, PeftModel, get_peft_model

        # T34: a hand-supplied target list wins — the CLI flag first,
        # then the stored project setting — and an empty or missing
        # list falls back to auto-detection.
        override = target_modules
        if override is None:
            override = settings.get("target_modules") or None
        targets = detect_target_modules(model, override=override)
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
            # The checkpoint list was already read before the lock
            # (T48) — the empty case was refused there, so this
            # list is non-empty. A selected checkpoint (T150)
            # wins over the latest one.
            checkpoints = resume_checkpoints
            if resume_step is not None:
                latest = next(
                    c for c in checkpoints if c["step"] == resume_step
                )
            else:
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
            # The resume contract (T98): the checkpoint carries the
            # settings the paused run trained with. When the
            # project's current settings differ, the run continues
            # with the checkpoint's adapter (its rank is baked in),
            # so the drift is warned about — event + log — never
            # silently dropped. Old checkpoints (before v0.17.0)
            # carry no settings and resume as before, unwarned.
            stored_settings = state.get("settings")
            if isinstance(stored_settings, dict):
                drift = _settings_drift(stored_settings, settings)
                if drift:
                    message = (
                        "training settings changed since the pause "
                        f"({', '.join(drift)}). Resuming with the "
                        "checkpoint's adapter, which keeps the "
                        "settings it was paused with."
                    )
                    if on_event is not None:
                        on_event({"type": "warning", "message": message})
                    _append_log(
                        work_dir, {"event": "warning", "message": message}
                    )
            # R26: an old checkpoint carries no dataset
            # fingerprint, so the run cannot tell whether the
            # dataset changed since the pause — it says so
            # (event + log) instead of resuming silently. A
            # checkpoint WITH a fingerprint was already compared
            # before the lock, so this only fires for old ones.
            if resume_fingerprint_unknown:
                message = (
                    "this checkpoint was saved before Stella "
                    "recorded which dataset it trained on, so it "
                    "cannot tell whether the dataset changed "
                    "since the pause. Resuming anyway."
                )
                if on_event is not None:
                    on_event({"type": "warning", "message": message})
                _append_log(
                    work_dir, {"event": "warning", "message": message}
                )
            trainable = [p for p in model.parameters() if p.requires_grad]
            optimizer = torch.optim.AdamW(
                trainable, lr=float(settings.get("learning_rate", 0.0002)),
                weight_decay=0.0,
            )
            opt_file = ckpt_dir / "optimizer.pt"
            if opt_file.is_file():
                # Safe load (T22): optimizer.pt travels cross-machine
                # inside export packages, so it loads with
                # weights_only=True — a pickle payload is refused, never
                # executed. A checkpoint that cannot load safely is a
                # plain error, not a traceback.
                try:
                    saved = torch.load(
                        str(opt_file), map_location="cpu", weights_only=True
                    )
                except Exception as exc:
                    raise StellaError(
                        f"checkpoint {ckpt_dir.name} cannot be loaded "
                        "safely (its optimizer file is not a plain "
                        f"optimizer state): {exc}"
                    ) from exc
                optimizer.load_state_dict(saved["optimizer"])
                # Restore the torch RNG state (T32): the dropout draws
                # continue exactly where the pause left them. Old
                # checkpoints (before v0.10.0) carry no RNG state —
                # they resume with the RNG wherever it is, as before.
                rng_state = saved.get("rng_state")
                if rng_state is not None:
                    torch.set_rng_state(rng_state)
            else:
                # A missing optimizer file restarts the optimizer
                # from scratch (T98): the Adam moments reset
                # mid-run and the loss curve jumps. Warn (event +
                # log) instead of silently starting fresh.
                message = (
                    f"checkpoint {ckpt_dir.name} has no optimizer "
                    "file, so the optimizer starts fresh. The loss "
                    "may jump for a few steps."
                )
                if on_event is not None:
                    on_event({"type": "warning", "message": message})
                _append_log(
                    work_dir, {"event": "warning", "message": message}
                )
        else:
            # Seed everything (T32): the seed drives the LoRA init
            # (A/B matrices) and every dropout draw, so a fresh run
            # with the same seed trains the same adapter. Set before
            # the adapter is built — the init itself is random. A
            # resume never reseeds: the checkpoint's RNG state is
            # restored above instead, and reseeding would break
            # pause/resume exactness.
            torch.manual_seed(int(settings.get("seed", 42)))
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
        # Post-load, the ceiling only: the model is already in
        # RAM, so free RAM has already dropped by its footprint
        # and judging the full estimate against what is left
        # would count the weights twice. The pre-load check above
        # is the guard that uses free RAM.
        check_ram_fit(estimate)

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
                max_steps=max_steps,
                # A resume on a finished project extends a finished
                # run (T25): the loop announces it before starting.
                extending=bool(
                    resume and update_status
                    and proj.get("status") == "done"
                ),
                # The project's stored mode string (T143), recorded
                # in the summary and the adapter config at train
                # time — as stored, no reading picked.
                mode=metamorph_mode(proj),
                # R26: the dataset fingerprint, stored in every
                # checkpoint this run writes.
                dataset_fingerprint=fingerprint,
            )
        except Exception as exc:
            # A crash is not a pause (T53): a run that errors is
            # failed, so the project never looks resumable when
            # there is no clean checkpoint to resume from. A
            # graceful stop returns a summary with stopped=True
            # and lands in "paused" below, not here.
            if update_status:
                store.update_project(profile, project, status="failed")
            # R76: an out-of-memory crash mid-run gets the
            # plain-words message, not raw torch text.
            oom = _oom_error(exc)
            if oom is not None:
                raise oom from exc
            raise
        if update_status:
            store.update_project(
                profile, project, status="paused" if summary["stopped"] else "done"
            )
        summary["dataset"] = info
        summary["trainable_params"] = trainable_params
        summary["target_modules"] = targets
        summary["ram_estimate_gb"] = round(estimate / 1024**3, 2)
        return summary
