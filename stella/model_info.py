"""STELLA model info — what a model does, and whether it fits this PC.

The model picker (T18) shows one plain line per model for what it
does, plus a fit verdict (size plus RAM) from the backend's PC
measurement. This module is that knowledge, Qt-free and stdlib-only
so the picker and the tests can use it with no GUI import.

- ``describe_model(tag)`` — one plain line for what the model does,
  matched on the family name inside the tag. Unknown families get
  the honest generic line: a general chat model.
- ``params_from_tag(tag)`` — billions of parameters, parsed from the
  size suffix in the tag (``:2b``, ``-1.7b``, ``:8b``). None when the
  tag carries no size.
- ``estimate_training_ram_gb(params_b)`` — the picker RAM rule,
  reconciled with the training estimator
  (train.estimate_training_bytes, R43): resident base weights at
  1 byte per param (2 bytes per param times the 0.5 resident
  share, train.RESIDENT_WEIGHTS_FRACTION), plus about 2.7 GB for
  activations at the default recipe, the LoRA optimizer state,
  and headroom. LFM3 1.7B comes out at about 4.4 GB, matching the
  recalibrated training estimate (4.34 GB); an 8B model comes out
  over 10 GB, which is why the guide says 1.5 to 2 billion
  parameters fit and 8 billion does not.
- ``fit_verdict(tag, size_bytes, ram_total_gb)`` — the picker's
  verdict line, judged against TOTAL RAM (R43): free RAM is a
  transient number — it drops whenever a browser is open — so a
  verdict against it calls the recommended starter "too big" one
  minute and fine the next. Total RAM is stable; the RAM guard in
  train.py still checks the free RAM for real at train time.
"""

from __future__ import annotations

import re

# One plain line per model family, matched on a substring of the
# tag (lowercased). The lookup tries the longest name first, so
# "codellama" beats "llama" — tuple order does not matter.
KNOWN_MODELS: tuple[tuple[str, str], ...] = (
    ("lfm3", "Liquid AI's small fast model. A good first pick."),
    ("minicpm", "A small model that can read pictures as well as words."),
    ("qwen", "A general chat model, good at following instructions."),
    ("granite", "IBM's model for code and business writing."),
    ("llama", "Meta's general chat model."),
    ("mistral", "A fast general chat model."),
    ("gemma", "Google's small open model."),
    ("phi", "Microsoft's small model, strong for its size."),
    ("deepseek", "A model built for code and reasoning."),
    ("smollm", "A tiny model for simple jobs."),
    ("tinyllama", "A tiny model for simple jobs."),
    ("stablelm", "A small general chat model."),
    ("orca", "A small model tuned to follow instructions."),
    ("vicuna", "A general chat model."),
    ("falcon", "A general chat model."),
    ("codellama", "A model built for writing code."),
    ("starcoder", "A model built for writing code."),
)

GENERIC_DESCRIPTION = "A general chat model."

# Training RAM, in GB per billion parameters (resident base
# weights), plus a flat allowance — reconciled with
# train.estimate_training_bytes (R43), so the picker and the
# training estimate can never disagree again:
# - weights: 2 bytes per param x the 0.5 resident share
#   (train.RESIDENT_WEIGHTS_FRACTION: safetensors weights are
#   mmap'd and stream from disk) = 1 byte per param.
# - fixed: activations at the default recipe (batch 1, seq 1024,
#   hidden 2048, 24 layers) about 1.6 GB, plus 1 GB headroom
#   (train.RAM_HEADROOM_BYTES), plus about 0.1 GB of LoRA
#   optimizer/master state at rank 8 — about 2.7 GB.
# LFM3 1.7B: 1.7 + 2.7 = 4.4 GB, against the recalibrated
# training estimate of 4.34 GB. The cross-check lives in
# tests/test_model_info.py: if the estimator changes, the test
# fails and the constants move with it.
_GB_PER_PARAM_B = 1.0
_FIXED_OVERHEAD_GB = 2.7

# "2b", "1.7b", "8b" at the end of a tag or a tag segment: the
# parameter count the tag itself carries.
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)


def describe_model(tag: str) -> str:
    """One plain line for what this model does."""
    lowered = tag.lower()
    # Longest name first: "codellama" and "tinyllama" both contain
    # "llama", and the longer, more specific match must win.
    for name, line in sorted(KNOWN_MODELS, key=lambda pair: -len(pair[0])):
        if name in lowered:
            return line
    return GENERIC_DESCRIPTION


def params_from_tag(tag: str) -> float | None:
    """Billions of parameters, parsed from the tag's size suffix,
    or None when the tag carries no size."""
    matches = _SIZE_RE.findall(tag)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def estimate_training_ram_gb(params_b: float) -> float:
    """RAM training this model needs, in GB. See the module
    docstring for the grounding."""
    return round(params_b * _GB_PER_PARAM_B + _FIXED_OVERHEAD_GB, 1)


def fits_this_pc(tag: str, ram_total_gb: float | None) -> bool | None:
    """True when training this model fits this PC's TOTAL RAM, False
    when it does not, None when the tag carries no size to judge by
    (or the RAM could not be measured). The picker's short verdict;
    fit_verdict is the full line. Judged against total RAM, not
    free RAM (R43): free RAM is transient, total RAM is the stable
    property of the PC — and the RAM guard checks free RAM for
    real at train time."""
    params_b = params_from_tag(tag)
    if params_b is None or ram_total_gb is None:
        return None
    return estimate_training_ram_gb(params_b) <= ram_total_gb


def _format_gb(gb: float) -> str:
    return f"{gb:.1f} GB"


def fit_verdict(
    tag: str,
    size_bytes: int | None,
    ram_total_gb: float | None,
) -> str:
    """The picker's fit line for one model: what it does is the
    caller's job (describe_model); this is size plus RAM, in plain
    words. Fits, too big, or honestly unknown. Judged against total
    RAM (R43); the too-big line says Stella checks the free RAM
    again at train time, so a verdict is never stated as more
    final than it is."""
    from .provision import format_size

    params_b = params_from_tag(tag)
    size_text = (
        f"About {format_size(size_bytes)} to download"
        if size_bytes
        else ""
    )
    if params_b is None:
        if size_text:
            return (
                f"{size_text}. Stella will check it fits this PC "
                "when you train."
            )
        return "Size unknown. Stella will check it fits when you train."
    needs_gb = estimate_training_ram_gb(params_b)
    if ram_total_gb is None:
        line = f"Needs about {_format_gb(needs_gb)} of RAM to train."
        if size_text:
            line = f"{size_text}. {line}"
        return line + " This PC's total RAM could not be measured."
    if needs_gb <= ram_total_gb:
        line = (
            f"Fits this PC. Needs about {_format_gb(needs_gb)} of RAM "
            "to train."
        )
        if size_text:
            line += f" {size_text}."
        return line
    return (
        f"Too big for this PC. Needs about {_format_gb(needs_gb)} of "
        f"RAM to train, and this PC has "
        f"{_format_gb(ram_total_gb)} in total. Stella checks the "
        "free RAM again when you train."
    )
