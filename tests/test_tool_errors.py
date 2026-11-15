"""Tool error translation tests (S22).

Each mapped raw error translates to its plain-words message plus
what to do, with the raw tail kept as a detail line. An unknown
error still shows its raw tail behind a plain-words lead.
"""
import pytest

from stella.tool_errors import translate_tool_error


@pytest.mark.parametrize(
    "raw, plain, action",
    [
        (
            "error: requantizing from type q4_K is disabled",
            "already quantized",
            "too old",
        ),
        (
            "llama_quantize: unknown quant type Q9_ZZ",
            "not one the quantizer knows",
            "Q4_K_M",
        ),
        (
            "Error: model 'ghost:1b' not found",
            "does not have that model installed",
            "pull the model first",
        ),
        (
            "Model architecture lfm3 is not supported by convert",
            "does not support this model type",
            "Update llama.cpp",
        ),
        (
            "failed to load model: not a valid GGUF file",
            "could not be read",
            "broken download",
        ),
        (
            "write failed: No space left on device",
            "disk ran out of space",
            "Free some disk space",
        ),
        (
            "open failed: Permission denied",
            "could not write",
            "permissions",
        ),
        (
            "dial tcp: connection refused",
            "Ollama is not answering",
            "Start Ollama",
        ),
        (
            "std::bad_alloc: out of memory",
            "ran out of memory",
            "Close other programs",
        ),
        (
            "open: No such file or directory",
            "file the tool needed is missing",
            "llama.cpp install",
        ),
    ],
)
def test_each_mapped_error_translates(raw, plain, action):
    message = translate_tool_error(raw, what="Shrinking 'x'", code=1)
    assert message.startswith("Shrinking 'x' failed (1).")
    assert plain in message
    assert action in message
    # The raw text is kept as a detail line, never hidden.
    assert "The tool said:" in message
    assert raw in message


def test_specific_entry_beats_generic_one():
    # "model not found" contains "not found" — the specific
    # Ollama entry must win over the generic missing-file one.
    message = translate_tool_error(
        "model 'ghost:1b' not found", what="ollama create", code=1
    )
    assert "does not have that model installed" in message
    assert "file the tool needed is missing" not in message


def test_unquoted_model_file_falls_through_to_missing_file():
    # No quotes around a tag: this is a missing file, not a
    # missing Ollama model.
    message = translate_tool_error(
        "model file not found", what="the converter", code=1
    )
    assert "file the tool needed is missing" in message


def test_unknown_error_shows_raw_tail_with_plain_lead():
    message = translate_tool_error(
        "something completely unexpected 98765",
        what="the converter", code=2,
    )
    assert message.startswith("the converter failed (2). The tool failed.")
    assert "Try again" in message
    assert "something completely unexpected 98765" in message


def test_empty_error_text_is_named():
    message = translate_tool_error("", what="the converter", code=1)
    assert "(no error text)" in message


def test_only_the_last_five_lines_are_kept():
    raw = "\n".join(f"line {i}" for i in range(10))
    message = translate_tool_error(raw, what="the converter", code=1)
    assert "line 0" not in message
    assert "line 9" in message


def test_matching_ignores_case():
    message = translate_tool_error(
        "NO SPACE LEFT ON DEVICE", what="the converter", code=1
    )
    assert "disk ran out of space" in message
