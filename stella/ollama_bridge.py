"""STELLA Ollama-to-training bridge (S23).

Training needs Hugging Face transformers weights, never the GGUF
file Ollama runs — but the user knows their models by Ollama tag
("qwen3.5:4b"), not by Hub repo id. The bridge is the crossing:

- ``classify_base_ref`` — is this base_ref an Ollama tag, a GGUF
  file, a local folder, or a plausible Hub repo id? The train
  path refuses tags and GGUF files with the bridge error instead
  of the misleading "config could not be read".
- ``suggest_hf_repos`` — the Hugging Face repo candidates for a
  known Ollama tag, from a small curated map. Every repo in the
  map was verified to exist on the Hub (checked 2026-11-15); an
  unknown tag gets an honest "Stella doesn't know yet", never a
  fabricated guess. Suggestions are candidates the user confirms
  — Stella never silently sets a repo.
- ``bridge_error_message`` — the plain-words train refusal: what
  the problem is, what to do, and the `stella bridge` command.

Deliberately not in the map: bonsai-2 has no verifiable Hub
transformers repo — its author has no models on the Hub at all
— so it stays unknown rather than guessed, and the reviewer
(dolphinlabs/qwen3.5-uncensored) is unverified, so it stays
unknown too. Granite 4.1 maps to its base the same way
MiniCPM5-Heretic and the abliterated coder do (verified
2026-11-18: ibm-granite/granite-4.1-3b-base has config.json +
2 safetensors, transformers library, zero GGUF files).
"""

from __future__ import annotations

from pathlib import Path

# (Ollama tag, Hugging Face repo, where the suggestion comes from).
# Every repo was verified to exist on the Hub (the first nine on
# 2026-11-15, the Granite base on 2026-11-18). Tags are matched
# lowercased; a tag without a version matches every versioned
# entry for that model.
KNOWN_BRIDGE: tuple[tuple[str, str, str], ...] = (
    ("lfm3", "LiquidAI/LFM3-1.7B",
     "Liquid AI's own repo for this model"),
    ("lfm3:1.7b", "LiquidAI/LFM3-1.7B",
     "Liquid AI's own repo for this model"),
    ("qwen3.5:2b", "Qwen/Qwen3.5-2B",
     "Qwen's own repo for this model"),
    ("qwen3.5:4b", "Qwen/Qwen3.5-4B",
     "Qwen's own repo for this model"),
    ("qwen3-vl:2b", "Qwen/Qwen3-VL-2B-Instruct",
     "Qwen's own repo for this model"),
    ("qwen3-vl:2b-instruct", "Qwen/Qwen3-VL-2B-Instruct",
     "Qwen's own repo for this model"),
    ("qwen2.5-coder:1.5b", "Qwen/Qwen2.5-Coder-1.5B",
     "Qwen's own repo for this model"),
    ("huihui_ai/qwen2.5-coder-abliterate:1.5b",
     "Qwen/Qwen2.5-Coder-1.5B",
     "the base model this Ollama tag is tuned from"),
    ("maternion/minicpm5-heretic:2b", "openbmb/MiniCPM5-2B",
     "the base model this Ollama tag is tuned from"),
    # v0.32.0: verified on the Hub 2026-11-18 (config.json + 2
    # safetensors, transformers library, zero GGUF files).
    ("huihui_ai/granite4.1-abliterated:3b",
     "ibm-granite/granite-4.1-3b-base",
     "the base model this Ollama tag is tuned from"),
)


def _normalize(tag: str) -> str:
    return (tag or "").strip().lower()


def _base_name(tag: str) -> str:
    """The tag with its version stripped: "qwen3.5:2b-q4_K_M"
    becomes "qwen3.5", "lfm3:1.7b" becomes "lfm3". The org
    prefix is kept ("huihui_ai/x:1b" becomes "huihui_ai/x"): the
    version is the part after the last ":" in the model's own
    name segment. Shared with the live Hugging Face lookup
    (hub_lookup), which searches by this base name."""
    wanted = _normalize(tag)
    last = wanted.rsplit("/", 1)[-1]
    if ":" not in last:
        return wanted
    return wanted.rsplit(":", 1)[0]


def suggest_hf_repos(tag: str) -> list[dict]:
    """Hugging Face repo candidates for an Ollama tag.

    An exact tag match returns its repo; a tag without a version
    returns every versioned entry for that model (deduped by
    repo). An unknown tag returns []. Each candidate is
    {"repo": ..., "source": ...} — the source says where the
    suggestion comes from, so the user can judge it."""
    wanted = _normalize(tag)
    if not wanted:
        return []
    found: list[dict] = []
    seen: set[str] = set()

    def add(repo: str, source: str) -> None:
        if repo not in seen:
            seen.add(repo)
            found.append({"repo": repo, "source": source})

    for known_tag, repo, source in KNOWN_BRIDGE:
        if known_tag == wanted:
            add(repo, source)
    if found:
        return found
    # No exact match: try the model name without its version.
    base = _base_name(wanted)
    for known_tag, repo, source in KNOWN_BRIDGE:
        if known_tag == base or known_tag.startswith(base + ":"):
            add(repo, source)
    return found


def classify_base_ref(base_ref: str) -> tuple[str, str | None]:
    """What kind of base_ref this is.

    Returns (kind, detail): "gguf" (a GGUF file path),
    "ollama" (an Ollama tag), "local" (an existing local path),
    or "hf" (a plausible "owner/repo" id). The detail is the
    plain-words description used in errors, or None.
    """
    ref = (base_ref or "").strip()
    if ref.lower().endswith(".gguf"):
        return "gguf", "a GGUF file"
    if ref and Path(ref).expanduser().exists():
        return "local", None
    last = ref.rsplit("/", 1)[-1]
    if ":" in last or "/" not in ref:
        return "ollama", "an Ollama tag, not a Hugging Face repo"
    return "hf", None


def modelfile_blob_hint(tag: str) -> str | None:
    """The GGUF blob the tag's Modelfile points at, as a hint
    sentence — or None when it cannot be found. A hint only: the
    blob is never weights training can use. (Lazy import:
    requant imports gguf, which imports train — a top-level
    import here would be circular.)"""
    try:
        from .requant import _modelfile_blob

        blob = _modelfile_blob(tag)
    except Exception:
        return None
    if blob is None:
        return None
    return (
        f"Its Modelfile points at the GGUF file {blob.name}, "
        "which is the file Ollama runs, not weights training "
        "can use."
    )


def bridge_error_message(base_ref: str) -> str:
    """The plain-words train refusal for a GGUF or Ollama-tag
    base_ref: what the problem is, what to do, and the bridge
    command. A known tag names its candidate repo; an unknown
    tag says so honestly instead of guessing."""
    kind, _detail = classify_base_ref(base_ref)
    if kind == "gguf":
        return (
            f"Training cannot start from {base_ref!r}: it is a GGUF "
            "file, and training needs Hugging Face transformers "
            "weights, never a GGUF file. Set base_ref to the "
            "Hugging Face repo of the base model (like "
            "'LiquidAI/LFM3-1.7B'), or a local folder of HF weights."
        )
    suggestions = suggest_hf_repos(base_ref)
    lines = [
        f"Training cannot start from {base_ref!r}: it is an Ollama "
        "tag, not a Hugging Face repo. Training needs Hugging Face "
        "transformers weights, never the GGUF file Ollama runs.",
    ]
    if suggestions:
        for candidate in suggestions:
            lines.append(
                f"A likely Hugging Face repo for this model is "
                f"{candidate['repo']} ({candidate['source']}). "
                "Check it is the right one, then set base_ref to it."
            )
    else:
        lines.append(
            "Stella doesn't know this model's Hugging Face repo "
            "yet. Find the model on huggingface.co and set base_ref "
            "to its repo id (like 'owner/model-name'), or point "
            "base_ref at a local folder of HF weights."
        )
    lines.append(f"Run this to see the suggestion again: stella bridge {base_ref}")
    return "\n".join(lines)


def format_bridge_report(tag: str) -> str:
    """The `stella bridge` report for one Ollama tag: its
    candidate Hugging Face repos and how to set base_ref — or
    the honest unknown-tag answer."""
    suggestions = suggest_hf_repos(tag)
    lines = [f"Ollama tag: {tag}"]
    hint = modelfile_blob_hint(tag)
    if hint is not None:
        lines.append(hint)
    if not suggestions:
        lines.append("")
        lines.append(
            "Stella doesn't know this model's Hugging Face repo yet."
        )
        lines.append(
            "Find the model on huggingface.co, then set base_ref to "
            "its repo id with:"
        )
        lines.append("  stella update-profile <profile> --base owner/model-name")
        lines.append(
            "Or point base_ref at a local folder of Hugging Face "
            "weights instead."
        )
        return "\n".join(lines)
    lines.append("")
    lines.append(
        "Training needs Hugging Face weights, not the GGUF file "
        "Ollama runs. Likely Hugging Face repos for this model:"
    )
    for candidate in suggestions:
        lines.append(f"  {candidate['repo']} ({candidate['source']})")
    lines.append("")
    lines.append(
        "Check the repo is the right one, then set base_ref to it with:"
    )
    lines.append(
        f"  stella update-profile <profile> --base {suggestions[0]['repo']}"
    )
    return "\n".join(lines)
