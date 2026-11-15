"""STELLA tool error translation (S22).

llama.cpp and Ollama print raw tool errors ("requantizing from
type q4_K is disabled") that mean nothing to a user. This module
translates them: a curated map of known raw substrings to a
plain-words message plus what to do. The StellaError leads with
the translation and keeps the raw tail as a detail line — the raw
text is never hidden entirely, because it helps debugging.

Shared by the requant runner (requant._run) and the GGUF-export
runner (gguf._run, plus the `ollama create` step). Stdlib-only,
no Stella imports, so both can use it without a cycle.
"""

from __future__ import annotations

# (raw substrings, plain-words message, what to do). An entry
# matches when ALL of its substrings are present (lowercased);
# first match wins, so the specific entries come before the
# generic ones: the quoted "model 'x' not found" entries must
# beat the generic "file not found", and the requantize entries
# must beat the generic converter entry.
_TRANSLATIONS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("requantizing from type",),
        "The quantizer refused because this model is already "
        "quantized.",
        "Stella passes the flag that allows re-quantizing, so this "
        "usually means the installed llama-quantize is too old to "
        "know that flag. Update llama.cpp and try again.",
    ),
    (
        ("requantize is disabled",),
        "The quantizer refused because this model is already "
        "quantized.",
        "Stella passes the flag that allows re-quantizing, so this "
        "usually means the installed llama-quantize is too old to "
        "know that flag. Update llama.cpp and try again.",
    ),
    (
        ("requantizing is disabled",),
        "The quantizer refused because this model is already "
        "quantized.",
        "Stella passes the flag that allows re-quantizing, so this "
        "usually means the installed llama-quantize is too old to "
        "know that flag. Update llama.cpp and try again.",
    ),
    (
        ("unknown quant",),
        "The quant type is not one the quantizer knows.",
        "Pick a quant from the list Stella knows, like Q4_K_M.",
    ),
    (
        ("invalid quant",),
        "The quant type is not one the quantizer knows.",
        "Pick a quant from the list Stella knows, like Q4_K_M.",
    ),
    (
        ("invalid quantization",),
        "The quant type is not one the quantizer knows.",
        "Pick a quant from the list Stella knows, like Q4_K_M.",
    ),
    # Ollama quotes the tag: model 'ghost:1b' not found. The
    # quote is part of the match, so a plain "model file not
    # found" still falls through to the missing-file entry.
    (
        ("model '", "not found"),
        "Ollama does not have that model installed.",
        "Check the tag, or pull the model first.",
    ),
    (
        ('model "', "not found"),
        "Ollama does not have that model installed.",
        "Check the tag, or pull the model first.",
    ),
    (
        ("not supported",),
        "The installed converter does not support this model type.",
        "Update llama.cpp to a newer version, or pick a base model "
        "with a supported architecture.",
    ),
    (
        ("unsupported",),
        "The installed converter does not support this model type.",
        "Update llama.cpp to a newer version, or pick a base model "
        "with a supported architecture.",
    ),
    (
        ("failed to load model",),
        "The model file could not be read.",
        "It may be a broken download. Pull the model again, or "
        "export it again.",
    ),
    (
        ("not a valid gguf",),
        "The model file could not be read.",
        "It may be a broken download. Pull the model again, or "
        "export it again.",
    ),
    (
        ("invalid gguf",),
        "The model file could not be read.",
        "It may be a broken download. Pull the model again, or "
        "export it again.",
    ),
    (
        ("bad magic",),
        "The model file could not be read.",
        "It may be a broken download. Pull the model again, or "
        "export it again.",
    ),
    (
        ("not a gguf",),
        "The model file could not be read.",
        "It may be a broken download. Pull the model again, or "
        "export it again.",
    ),
    (
        ("no space left",),
        "The disk ran out of space.",
        "Free some disk space and try again.",
    ),
    (
        ("disk full",),
        "The disk ran out of space.",
        "Free some disk space and try again.",
    ),
    (
        ("enospc",),
        "The disk ran out of space.",
        "Free some disk space and try again.",
    ),
    (
        ("permission denied",),
        "The tool could not write where it needed to.",
        "Check the folder's permissions, or pick a work folder "
        "Stella can write to.",
    ),
    (
        ("operation not permitted",),
        "The tool could not write where it needed to.",
        "Check the folder's permissions, or pick a work folder "
        "Stella can write to.",
    ),
    (
        ("connection refused",),
        "Ollama is not answering.",
        "Start Ollama and try again.",
    ),
    (
        ("could not connect",),
        "Ollama is not answering.",
        "Start Ollama and try again.",
    ),
    (
        ("failed to connect",),
        "Ollama is not answering.",
        "Start Ollama and try again.",
    ),
    (
        ("connection reset",),
        "Ollama is not answering.",
        "Start Ollama and try again.",
    ),
    (
        ("out of memory",),
        "The machine ran out of memory.",
        "Close other programs and try again, or pick a smaller model.",
    ),
    (
        ("cannot allocate memory",),
        "The machine ran out of memory.",
        "Close other programs and try again, or pick a smaller model.",
    ),
    (
        ("bad_alloc",),
        "The machine ran out of memory.",
        "Close other programs and try again, or pick a smaller model.",
    ),
    (
        ("no such file or directory",),
        "A file the tool needed is missing.",
        "Check the llama.cpp install and that the model file is "
        "still there, then try again.",
    ),
    (
        ("file not found",),
        "A file the tool needed is missing.",
        "Check the llama.cpp install and that the model file is "
        "still there, then try again.",
    ),
    (
        ("no such file",),
        "A file the tool needed is missing.",
        "Check the llama.cpp install and that the model file is "
        "still there, then try again.",
    ),
)

_UNKNOWN_PLAIN = "The tool failed."
_UNKNOWN_ACTION = (
    "Try again. If it keeps failing, the tool's own error below "
    "may help."
)


def translate_tool_error(
    raw: str, *, what: str, code: int | None = None
) -> str:
    """A raw tool failure as a plain-words message.

    `what` names the step ("Shrinking 'qwen3.5:4b' to Q4_K_M",
    "the converter"); `code` is the exit code when there is one.
    The message leads with the translation, then the raw tail
    (last 5 lines) under "The tool said:", so the original error
    is still there for debugging."""
    lowered = (raw or "").lower()
    plain = _UNKNOWN_PLAIN
    action = _UNKNOWN_ACTION
    for needles, candidate_plain, candidate_action in _TRANSLATIONS:
        if all(needle in lowered for needle in needles):
            plain = candidate_plain
            action = candidate_action
            break
    tail_lines = (raw or "").strip().splitlines()[-5:]
    tail = "\n".join(tail_lines) or "(no error text)"
    head = f"{what} failed"
    if code is not None:
        head += f" ({code})"
    return f"{head}. {plain}\n{action}\n\nThe tool said:\n{tail}"
