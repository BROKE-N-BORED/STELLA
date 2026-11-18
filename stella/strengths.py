"""STELLA model strengths (v0.31.0).

Nobody assigns roles by hand anymore. A profile's role — the job
its model does — is worked out by Stella from what the model is
good at, and shown in plain words in the profile window:
"Good at: ..." / "Not good at: ...". Where Stella has no evidence
about a model, it says "Not measured yet" instead of guessing.

The table is keyed by Ollama tag and grounded ONLY in:

- the Code Forge roster audit
  (docs/audit-forge-roster-2026-11-12.md) — per-model strengths
  and weaknesses from the sweeps and Forge's own trials, and
- OST's graded results where they exist (the LFM3 card confirms
  its tool-calling strength: Tool Calling 100%, Structured Output
  100%, Instruction 100%).

Every phrase is plain words a child can read: no benchmark names,
no quant names, no seat jargon. A strength that is only a trial
or an expectation is left out — the table carries what is known,
not what is hoped for.

The derived role is the Forge seat vocabulary (model.
CANONICAL_ROLES), and it is deliberately conservative: a
governing role (driver, reviewer, tester, fast) is derived ONLY
for the three tags that actually hold those seats in Forge
(minicpm5-heretic, dolphin reviewer, bonsai-2-uncensored). A model
on trial for a seat, a control model, or a cut model derives no
role ("") — its strengths still show, but it is not marked as a
seat holder it is not. That keeps the governing-seat warning and
the refusal-probe gate honest: they fire for real seat holders,
never for a trial model that merely looks fast.

Matching mirrors ollama_bridge: an exact tag match wins; a tag
without its version falls back to the model name, but only when
exactly ONE entry matches — an ambiguous base ("qwen3.5" could
be the 2B or the 4B) returns None rather than a guess.
"""

from __future__ import annotations

# (Ollama tag, derived role, good at, not good at). The role is ""
# when the model holds no Forge seat — trial, control, or cut.
# Audit section numbers refer to docs/audit-forge-roster-2026-11-12.md.
KNOWN_STRENGTHS: tuple[
    tuple[str, str, tuple[str, ...], tuple[str, ...]], ...
] = (
    # §1: best 2B coding numbers published, strong tool scores,
    # strong reasoning — but the Q8_0 file is the slowest kind on
    # this CPU, and it can repeat itself under default settings.
    ("maternion/minicpm5-heretic:2b", "driver",
     ("writing code", "using tools", "hard maths and reasoning"),
     ("answering quickly", "it can repeat itself")),
    # §2: the council second opinion — but text only, and it
    # overthinks unless told not to.
    ("dolphinlabs/qwen3.5-uncensored:latest", "reviewer",
     ("giving a second opinion", "general questions"),
     ("seeing pictures", "keeping answers short")),
    # §3: the smallest and fastest on the roster, good with tools
    # and short code — but weak on hard knowledge questions and
    # on reading text in pictures.
    ("eriktonon/bonsai-2-uncensored:2b", "fast",
     ("answering fast", "using tools", "short code"),
     ("hard knowledge questions", "reading text in pictures")),
    # §4: stock control model, strong coding family — but it still
    # refuses ordinary work, so it holds no seat.
    ("bonsai-2:4b", "",
     ("writing code",),
     ("it still refuses some ordinary work",)),
    # §5 + the OST LFM3 card: the best small-model tool scores
    # (OST: Tool Calling 100%), fast on weak CPUs, reads long
    # documents without slowing down much — but Liquid's own card
    # says it is not for long multi-step jobs, and it is stock.
    ("lfm3:1.7b", "",
     ("using tools", "answering fast", "reading long documents"),
     ("long multi-step jobs",
      "it still refuses some ordinary work")),
    # §6: built for tool calling and strong at code — but a dense
    # 3B is slower than every 2B here. On trial for a reviewer
    # seat it has not earned, so no role is derived.
    ("huihui_ai/granite4.1-abliterated:3b", "",
     ("using tools", "writing code"),
     ("answering quickly",)),
    # §7: good short snippets, very fast — but it collapses on
    # big multi-file jobs and failed as a driver.
    ("huihui_ai/qwen2.5-coder-abliterate:1.5b", "utility",
     ("short code snippets", "answering fast"),
     ("big coding jobs", "running a whole job on its own")),
    # §8: genuinely good reasoning per size — but too slow to use
    # on this PC, and stock. Cut from the roster; kept here so a
    # profile for it still tells the truth.
    ("phi4-mini", "",
     ("reasoning and maths",),
     ("answering in usable time on this PC",
      "it still refuses some ordinary work")),
    # Gaps/Vision: the vision seat — but budget minutes per
    # picture on this PC.
    ("qwen3-vl:2b-instruct", "vision",
     ("seeing pictures", "answering questions about pictures"),
     ("answering quickly with pictures",)),
    # Gaps/All-rounder: general questions plus pictures — but
    # stock, so it still refuses some ordinary work.
    ("qwen3.5:2b-q4_K_M", "all-rounder",
     ("general questions", "seeing pictures"),
     ("it still refuses some ordinary work",)),
    # Gaps/4B generalist: the strongest general scores on the
    # roster — but a 4B answers slowly on this PC, it is stock,
    # and it has not earned a seat yet, so no role is derived.
    ("qwen3.5:4b", "",
     ("general questions", "reasoning and maths"),
     ("answering quickly",
      "it still refuses some ordinary work")),
)


def _normalize(tag: str) -> str:
    return (tag or "").strip().lower()


def strengths_for_tag(tag: str) -> dict | None:
    """What this model is good and not good at, or None when
    Stella has no evidence about it. Returns {"role": ...,
    "good": [...], "not_good": [...]} — the role is "" when the
    model holds no Forge seat. An exact tag match wins; a tag
    without its version falls back to the model name only when
    exactly one entry matches (an ambiguous base returns None
    rather than a guess)."""
    wanted = _normalize(tag)
    if not wanted:
        return None
    for known_tag, role, good, not_good in KNOWN_STRENGTHS:
        if known_tag == wanted:
            return {
                "role": role,
                "good": list(good),
                "not_good": list(not_good),
            }
    # No exact match: try the model name without its version.
    last = wanted.rsplit("/", 1)[-1]
    base = wanted if ":" not in last else wanted.rsplit(":", 1)[0]
    found = []
    for known_tag, role, good, not_good in KNOWN_STRENGTHS:
        if known_tag == base or known_tag.startswith(base + ":"):
            found.append((role, good, not_good))
    if len(found) != 1:
        return None
    role, good, not_good = found[0]
    return {"role": role, "good": list(good), "not_good": list(not_good)}


def derived_role(tag: str) -> str:
    """The role Stella works out for this model: its Forge seat,
    or "" when it holds none (trial, control, cut, or unknown).
    Never typed by the user — the profile window shows it
    read-only, and the store derives it at creation and when the
    tag changes."""
    entry = strengths_for_tag(tag)
    return entry["role"] if entry is not None else ""
