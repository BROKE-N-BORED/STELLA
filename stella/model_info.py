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
  grounded in the training estimator (train.estimate_training_bytes):
  base weights at 2 bytes per param, plus about 3 GB for activations,
  the optimizer, and headroom. LFM3 1.7B comes out at about 6.4 GB,
  matching the real estimate; a 3B model comes out over 8 GB, which
  is why the guide says 1.5 to 2 billion parameters fit and 8
  billion does not.
- ``fit_verdict(tag, size_bytes, ram_available_gb)`` — the picker's
  verdict line. Fits, too big, or honestly unknown when the size
  cannot be parsed (Stella checks for real at train time — the RAM
  guard in train.py refuses a run that will not fit).
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

# Training RAM, in GB per billion parameters (bf16 weights), plus a
# flat allowance for activations, the optimizer, and headroom — see
# the module docstring for the grounding.
_GB_PER_PARAM_B = 2.0
_FIXED_OVERHEAD_GB = 3.0

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


def fits_this_pc(tag: str, ram_available_gb: float | None) -> bool | None:
    """True when training this model fits this PC's free RAM, False
    when it does not, None when the tag carries no size to judge by
    (or the RAM could not be measured). The picker's short verdict;
    fit_verdict is the full line."""
    params_b = params_from_tag(tag)
    if params_b is None or ram_available_gb is None:
        return None
    return estimate_training_ram_gb(params_b) <= ram_available_gb


def _format_gb(gb: float) -> str:
    return f"{gb:.1f} GB"


def fit_verdict(
    tag: str,
    size_bytes: int | None,
    ram_available_gb: float | None,
) -> str:
    """The picker's fit line for one model: what it does is the
    caller's job (describe_model); this is size plus RAM, in plain
    words. Fits, too big, or honestly unknown."""
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
    if ram_available_gb is None:
        line = f"Needs about {_format_gb(needs_gb)} of RAM to train."
        if size_text:
            line = f"{size_text}. {line}"
        return line + " This PC's free RAM could not be measured."
    if needs_gb <= ram_available_gb:
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
        f"{_format_gb(ram_available_gb)} free."
    )
