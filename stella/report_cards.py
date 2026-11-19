"""STELLA report cards (v0.32.0).

A report card is a graded test result for a base model — from
OST (the testing home) or from anywhere else — attached to the
model's profile. The file is COPIED into the profile's own
folder (profiles/<slug>/report-cards/), never linked, so the
original may move or be deleted without losing the card.

OST cards are UNDERSTOOD: Stella reads the graded per-template
scores out of them and uses them for the profile's strengths.
Card evidence beats the built-in strengths table (strengths.py):
when a profile has an OST card, the window shows what the card
measured and says where it came from ("From its OST report
card, Nov 2026"). The newest card wins when several are
attached. Cards from anywhere else are STORED, not understood:
listed, openable, removable — Stella shows the name and date
and does not pretend to know what they say.

The OST formats parsed here are the real ones, found on disk
2026-11-18 (see TEST-REPORT.md for the sources):

- one per-template result file, as OST writes it:
  results/<slug>/<system>/<ts>-<template>.json — a dict with
  "template", "template_score", "passed", "total", "timestamp",
  "model" (save_run_file, ollama_system_test.py).
- one per-model summary, as aggregate-results.py builds it:
  a dict keyed by model slug, each value with "model",
  "overall_score", and "templates" mapping template id to
  {"name", "capability", "score", "passed", "total",
  "timestamp"} — or a single model's block on its own.
- one OST GUI report (bench-results-<stamp>.json): a dict
  with "generated" and "models", a LIST of per-model results,
  each with "name", "overall_score", and "templates" mapping
  template id to a full per-template run file.
- a JSON list of per-template result files.

A score of 80 or more means good at that thing; 40 or less
means not good at it; in between, Stella says nothing — a
middle score is not evidence either way. A template with no
questions run gives no evidence. Speed is never a strength:
decode speed depends on how busy the machine was, not on the
model. Unknown template ids are skipped, never guessed into
plain words.

The parser is defensive by design: anything that is not
recognisably OST-shaped, or that cannot be read, is a stored
file, never a crash. A malformed card never breaks the
window — list_report_cards and strengths_from_cards never
raise on a bad file.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .model import StellaError

REPORT_CARDS_DIRNAME = "report-cards"

# The most a single card file may hold (10 MB). A real OST result
# file is kilobytes; a PDF card is a few hundred kilobytes. Above
# this, the file is refused in plain words at attach time.
MAX_CARD_BYTES = 10 * 1024 * 1024

# Good at: 80 or more. Not good at: 40 or less. Between the two,
# silence — a middle score is not evidence either way.
GOOD_AT_SCORE = 80.0
NOT_GOOD_AT_SCORE = 40.0

# OST template id -> plain words. Speed is deliberately absent:
# decode speed depends on how busy the machine was, not on the
# model, so it is never a strength. An id missing here is skipped,
# never guessed into plain words.
TEMPLATE_PHRASES: dict[str, str] = {
    "tool_calling": "using tools",
    "coding": "writing code",
    "code_repair": "fixing code",
    "math": "maths",
    "reasoning": "reasoning",
    "knowledge": "knowledge questions",
    "instruction": "following instructions",
    "structured_output": "writing in a set format",
    "summarization": "summing up",
    "grounded_qa": "answering from given text",
    "long_context": "reading long documents",
    "multi_turn": "long conversations",
    "planning": "making plans",
    "role_following": "staying in character",
    "refusal": "saying no to bad requests",
    "vision": "seeing pictures",
    "audio": "hearing audio",
    "image_generation": "making pictures",
}



def report_cards_dir(store, profile: str) -> Path:
    """The profile's report-cards folder (created on demand by
    the attach path, never here — listing an empty profile
    should not make folders)."""
    return store.profile_dir(profile) / REPORT_CARDS_DIRNAME


def _month_year(when: datetime | None) -> str:
    """'Nov 2026' for a date, or '' when there is none."""
    if when is None:
        return ""
    return when.strftime("%b %Y")


def _parse_stamp(value) -> datetime | None:
    """An OST timestamp ('2026-11-15T11:32:30', or a bare date)
    as a datetime, or None when it does not parse."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _number(value):
    """A JSON number as a float, or None (booleans are not
    numbers here — True would otherwise read as a score of 1)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _template_entry(entry) -> tuple[float, int, datetime | None] | None:
    """One per-template result as (score, total, tested), or
    None when it carries no usable score. Accepts both the run
    file shape ('template_score') and the summary shape
    ('score')."""
    if not isinstance(entry, dict):
        return None
    score = _number(entry.get("template_score"))
    if score is None:
        score = _number(entry.get("score"))
    if score is None:
        return None
    total = entry.get("total")
    if isinstance(total, bool) or not isinstance(total, int):
        total = 0
    return (score, total, _parse_stamp(entry.get("timestamp")))


def _model_block(block) -> dict | None:
    """One per-model block as {'model', 'overall', 'templates'}
    — templates mapping id to (score, total, tested) — or None
    when the block is not a model block. Accepts the summary
    shape ('model' + 'templates' of score entries) and the GUI
    report shape ('name' + 'templates' of run files)."""
    if not isinstance(block, dict):
        return None
    templates = block.get("templates")
    if not isinstance(templates, dict) or not templates:
        return None
    parsed: dict[str, tuple[float, int, datetime | None]] = {}
    for template_id, entry in templates.items():
        got = _template_entry(entry)
        if got is not None and isinstance(template_id, str):
            parsed[template_id] = got
    if not parsed:
        return None
    model = block.get("model") or block.get("name") or ""
    return {
        "model": str(model),
        "overall": _number(block.get("overall_score")),
        "templates": parsed,
    }


def _pick_model(blocks: list[dict], tag_hint: str | None) -> dict | None:
    """The one model block to use: the entry whose model matches
    the profile's tag when one does, else the only entry, else
    None — a multi-model file with no match is not guessed."""
    if not blocks:
        return None
    wanted = (tag_hint or "").strip().lower()
    if wanted:
        for block in blocks:
            if block["model"].strip().lower() == wanted:
                return block
    if len(blocks) == 1:
        return blocks[0]
    return None


def _tested_date(model_block: dict, generated=None) -> datetime | None:
    """When this card's model was tested: the newest template
    timestamp in it, else a top-level stamp, else None."""
    tested = None
    for _score, _total, stamp in model_block["templates"].values():
        if stamp is not None and (tested is None or stamp > tested):
            tested = stamp
    if tested is None:
        tested = _parse_stamp(generated)
    return tested


def parse_ost_card(path, tag_hint: str | None = None) -> dict | None:
    """An OST report card file as {'model', 'overall',
    'templates', 'tested'}, or None when the file is not an OST
    card for this model (not OST-shaped, a multi-model file with
    no matching model, unreadable, or too big to read). Never
    raises on a bad file.

    'templates' maps template id to (score, total, tested).
    'tested' is the newest template timestamp, or None.
    """
    try:
        size = Path(path).stat().st_size
    except OSError:
        return None
    if size > MAX_CARD_BYTES:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    generated = None
    blocks: list[dict] = []
    if isinstance(data, dict):
        # One per-template result file on its own.
        if "template_score" in data and "template" in data:
            got = _template_entry(data)
            if got is not None:
                return {
                    "model": str(data.get("model") or ""),
                    "overall": None,
                    "templates": {str(data["template"]): got},
                    "tested": got[2],
                }
            return None
        # One OST GUI report: {"generated", "models": [...]}.
        if isinstance(data.get("models"), list):
            generated = data.get("generated")
            for item in data["models"]:
                block = _model_block(item)
                if block is not None:
                    blocks.append(block)
        else:
            # One per-model summary block on its own, or a
            # multi-model summary keyed by slug.
            single = _model_block(data)
            if single is not None:
                blocks.append(single)
            else:
                for value in data.values():
                    block = _model_block(value)
                    if block is not None:
                        blocks.append(block)
    elif isinstance(data, list):
        # A list of per-template result files.
        merged: dict[str, tuple[float, int, datetime | None]] = {}
        model = ""
        for item in data:
            if not isinstance(item, dict):
                continue
            got = _template_entry(item)
            template_id = item.get("template")
            if got is None or not isinstance(template_id, str):
                continue
            stamp = got[2]
            old = merged.get(template_id)
            if old is None or (
                stamp is not None
                and (old[2] is None or stamp > old[2])
            ):
                merged[template_id] = got
            if not model and item.get("model"):
                model = str(item["model"])
        if merged:
            blocks.append(
                {"model": model, "overall": None, "templates": merged}
            )
    picked = _pick_model(blocks, tag_hint)
    if picked is None:
        return None
    picked["tested"] = _tested_date(picked, generated)
    return picked


def _looks_ost(path) -> bool:
    """True when the file is OST-shaped at all (any model), so
    the window can say 'an OST card for a different model'
    instead of 'Stella does not read it'. Never raises."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        return False
    if size > MAX_CARD_BYTES:
        return False
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if isinstance(data, dict):
        if "template_score" in data and "template" in data:
            return _template_entry(data) is not None
        if isinstance(data.get("models"), list):
            return any(
                _model_block(item) is not None for item in data["models"]
            )
        if _model_block(data) is not None:
            return True
        return any(
            _model_block(value) is not None for value in data.values()
        )
    if isinstance(data, list):
        return any(
            isinstance(item, dict)
            and _template_entry(item) is not None
            and isinstance(item.get("template"), str)
            for item in data
        )
    return False


def _fmt_score(score: float) -> str:
    """70.0 -> '70', 73.1 -> '73.1'."""
    if score == int(score):
        return str(int(score))
    return str(score)


def _card_line(kind: str, parsed: dict | None) -> str:
    """The one plain-words line for a card in the list."""
    if kind == "ost":
        overall = (parsed or {}).get("overall")
        if overall is not None:
            return (
                "OST tested this model: overall "
                f"{_fmt_score(overall)} out of 100."
            )
        return "OST tested this model."
    if kind == "ost-other":
        return "An OST report card, but not for this model."
    return "Stored here. Stella does not read it."


def list_report_cards(store, profile: str) -> list[dict]:
    """Every card attached to this profile, newest first: each
    {'name', 'path', 'size_bytes', 'date', 'kind', 'line',
    'parsed', 'sort_key'}. 'kind' is 'ost' (understood, for this
    model), 'ost-other' (OST-shaped, for another model), or
    'other' (stored, not read). 'date' is the tested month for
    an OST card, else the month the file was added. A damaged or
    unreadable file is listed as 'other' — it never breaks the
    list. An unknown profile gives []."""
    try:
        profile_data = store.get_profile(profile)
    except StellaError:
        return []
    tag = (profile_data.get("ollama_tag") or "").strip()
    folder = report_cards_dir(store, profile)
    if not folder.is_dir():
        return []
    cards: list[dict] = []
    for item in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_file() or item.name.startswith("."):
            continue
        try:
            size = item.stat().st_size
            mtime = datetime.fromtimestamp(
                item.stat().st_mtime, tz=timezone.utc
            ).replace(tzinfo=None)
        except OSError:
            continue
        parsed = parse_ost_card(item, tag_hint=tag or None)
        if parsed is not None:
            kind = "ost"
            tested = parsed.get("tested") or mtime
        elif _looks_ost(item):
            kind = "ost-other"
            parsed = None
            tested = mtime
        else:
            kind = "other"
            parsed = None
            tested = mtime
        cards.append({
            "name": item.name,
            "path": str(item),
            "size_bytes": size,
            "date": _month_year(tested),
            "kind": kind,
            "line": _card_line(kind, parsed),
            "parsed": parsed,
            "sort_key": (tested, item.name.lower()),
        })
    cards.sort(key=lambda c: c["sort_key"], reverse=True)
    return cards


def _safe_card_name(source: Path) -> str:
    """A filename safe to store: the base name only, with path
    separators and control characters replaced. Never empty."""
    name = source.name.strip()
    cleaned = "".join(
        ch if ch.isprintable() and ch not in "/\\" else "_"
        for ch in name
    ).strip(" .")
    return cleaned or "report-card"


def add_report_card(store, profile: str, source) -> dict:
    """Copy one file into the profile's report cards. Returns
    the new card's record (as list_report_cards returns it).
    The original is never moved or changed. A same-named card
    already attached gets ' (2)', ' (3)' and so on — nothing is
    ever overwritten. Refuses in plain words: a missing or
    unreadable file, a folder, or a file over the size cap."""
    store.get_profile(profile)  # StellaError when unknown.
    src = Path(source).expanduser()
    if not src.exists():
        raise StellaError(
            "Stella could not find that file. It may have been "
            "moved or deleted."
        )
    if not src.is_file():
        raise StellaError(
            "That is a folder, not a file. Pick one report card file."
        )
    try:
        size = src.stat().st_size
    except OSError:
        raise StellaError(
            "Stella could not read that file."
        ) from None
    if size > MAX_CARD_BYTES:
        raise StellaError(
            "That file is too big for a report card (over 10 MB). "
            "Pick a smaller file."
        )
    folder = report_cards_dir(store, profile)
    folder.mkdir(parents=True, exist_ok=True)
    name = _safe_card_name(src)
    stem = Path(name).stem
    suffix = Path(name).suffix
    candidate = name
    n = 2
    while (folder / candidate).exists():
        candidate = f"{stem} ({n}){suffix}"
        n += 1
    try:
        shutil.copyfile(src, folder / candidate)
    except OSError:
        raise StellaError(
            "Stella could not copy that file into the profile."
        ) from None
    for card in list_report_cards(store, profile):
        if card["name"] == candidate:
            return card
    raise StellaError(
        "The report card was copied, but Stella cannot see it."
    )


def remove_report_card(store, profile: str, name: str) -> None:
    """Remove one attached card (the copy in the profile only —
    the original file, if the user still has it, is untouched).
    Refuses in plain words when the name is not a plain filename
    or the card is not there."""
    store.get_profile(profile)  # StellaError when unknown.
    clean = (name or "").strip()
    if (
        not clean
        or clean != Path(clean).name
        or "/" in clean
        or "\\" in clean
    ):
        raise StellaError("That is not a report card name.")
    folder = report_cards_dir(store, profile)
    target = folder / clean
    try:
        target.resolve().relative_to(folder.resolve())
    except (OSError, ValueError):
        raise StellaError("That is not a report card name.") from None
    if not target.is_file():
        raise StellaError(
            "That report card is not there anymore."
        )
    try:
        target.unlink()
    except OSError:
        raise StellaError(
            "Stella could not remove that report card."
        ) from None


def _strengths_from_parsed(parsed: dict) -> tuple[list[str], list[str]]:
    """(good, not good) in plain words from one parsed OST card:
    a template at 80+ is good, at 40 or less is not good, in
    between is silence. Good is best first, not good is worst
    first; ties read alphabetically, so the order is stable."""
    good: list[tuple[float, str]] = []
    not_good: list[tuple[float, str]] = []
    for template_id, (score, total, _stamp) in parsed["templates"].items():
        if total < 1:
            continue
        phrase = TEMPLATE_PHRASES.get(template_id)
        if phrase is None:
            continue
        if score >= GOOD_AT_SCORE:
            good.append((score, phrase))
        elif score <= NOT_GOOD_AT_SCORE:
            not_good.append((score, phrase))
    good.sort(key=lambda item: (-item[0], item[1]))
    not_good.sort(key=lambda item: (item[0], item[1]))
    return ([p for _s, p in good], [p for _s, p in not_good])


def strengths_from_cards(store, profile: str) -> dict | None:
    """What the profile's newest OST report card measured, or
    None when no attached card is an OST card for this model.
    Returns {'good': [...], 'not_good': [...], 'source': ...,
    'overall': ...} — the lists may both be empty when every
    score sat in the middle (measured, but nothing stands out).
    Card evidence beats the built-in strengths table; the window
    falls back to the table when this returns None. Never raises
    on a bad card."""
    cards = list_report_cards(store, profile)
    for card in cards:
        if card["kind"] != "ost" or card["parsed"] is None:
            continue
        good, not_good = _strengths_from_parsed(card["parsed"])
        return {
            "good": good,
            "not_good": not_good,
            "source": (
                "From its OST report card"
                + (f", {card['date']}" if card["date"] else "")
                + "."
            ),
            "overall": card["parsed"].get("overall"),
        }
    return None
