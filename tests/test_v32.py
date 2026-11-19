"""STELLA v0.32.0 tests — report cards on a profile.

OST cards are understood (their graded per-template scores drive
the profile's strengths, newest card wins); cards from anywhere
else are stored, not read. Fixtures are built from the REAL OST
formats found on disk 2026-11-18: the per-model summary JSON
(aggregate-results.py output, LFM3's real v16 numbers), a
per-template result file (save_run_file shape), and the OST GUI
report (bench-results shape).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from stella.model import STELLA_VERSION, Store

ROOT = Path(__file__).resolve().parent.parent


def _run_cli_subprocess(home, *args):
    """Run the real `python -m stella.cli` in a subprocess."""
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture()
def window(qapp, seeded, settings):
    """The main window on the seeded store (one profile, one
    project) — the same fixture test_gui.py uses, defined here so
    this file stands alone."""
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    from tests.test_gui import _wait_for_all_workers

    _wait_for_all_workers(win, qapp)
    win.close()


def test_version_is_0_32_0(home):
    """The version is 0.32.0 everywhere the CLI reports it."""
    assert STELLA_VERSION == "0.32.0"
    res = _run_cli_subprocess(home, "--version")
    assert res.returncode == 0
    assert "0.32.0" in res.stdout


def test_window_title_carries_version(window):
    """The window title carries STELLA 0.32.0."""
    assert "0.32.0" in window.windowTitle()


# -- fixtures: the real OST formats ---------------------------------


def _lfm3_templates():
    """LFM3's real OST v16 per-template scores, from
    results-summary-3models.json (tested Nov 16, 2026). Speed
    carries score None in the real file — a template with no
    score must give no evidence."""
    def entry(name, capability, score, passed, total, ts):
        return {
            "name": name, "capability": capability, "score": score,
            "passed": passed, "total": total, "not_run": 0,
            "budget_stopped": 0, "time_budget_reached": False,
            "avg_decode_tok_s": 1.0, "timestamp": ts,
        }

    return {
        "code_repair": entry(
            "Code Repair", "text", 40.0, 2, 5, "2026-11-16T16:51:50"),
        "coding": entry(
            "Coding", "text", 80.0, 4, 5, "2026-11-16T16:48:33"),
        "grounded_qa": entry(
            "Grounded QA", "text", 100.0, 5, 5, "2026-11-16T16:55:26"),
        "instruction": entry(
            "Instruction", "text", 100.0, 5, 5, "2026-11-16T16:35:50"),
        "knowledge": entry(
            "Knowledge", "text", 80.0, 4, 5, "2026-11-16T16:37:06"),
        "long_context": entry(
            "Long Context", "long_context", 0.0, 0, 5,
            "2026-11-16T17:17:48"),
        "math": entry(
            "Math", "text", 90.0, 9, 10, "2026-11-16T16:40:18"),
        "multi_turn": entry(
            "Multi-turn", "text", 60.0, 3, 5, "2026-11-16T17:01:57"),
        "planning": entry(
            "Planning", "text", 0.0, 0, 5, "2026-11-16T16:45:21"),
        "reasoning": entry(
            "Reasoning", "text", 60.0, 3, 5, "2026-11-16T16:42:40"),
        "refusal": entry(
            "Refusal", "text", 100.0, 5, 5, "2026-11-16T17:07:46"),
        "role_following": entry(
            "Role Following", "text", 40.0, 2, 5,
            "2026-11-16T17:04:40"),
        "speed": entry(
            "Speed", "text", None, None, 3, "2026-11-16T17:11:40"),
        "structured_output": entry(
            "Structured Output", "text", 100.0, 5, 5,
            "2026-11-16T16:53:18"),
        "summarization": entry(
            "Summarization", "text", 100.0, 5, 5,
            "2026-11-16T16:57:48"),
        "tool_calling": entry(
            "Tool Calling", "tools", 100.0, 5, 5,
            "2026-11-16T16:54:19"),
    }


def _lfm3_summary_block():
    """One per-model summary block, aggregate-results.py shape."""
    return {
        "model": "lfm3:1.7b",
        "slug": "lfm3_1.7b",
        "templates_scored": 15,
        "overall_score": 70.0,
        "mean_decode_tok_s": 9.7,
        "templates": _lfm3_templates(),
    }


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _write_card(tmp_path, name, data):
    return _write_json(tmp_path / name, data)


# -- the OST parser --------------------------------------------------


def test_parse_single_model_summary(tmp_path):
    """A one-model summary JSON parses: overall, per-template
    scores, and the tested date from the newest timestamp."""
    from stella.report_cards import parse_ost_card

    path = _write_card(tmp_path, "lfm3.json", _lfm3_summary_block())
    parsed = parse_ost_card(path, tag_hint="lfm3:1.7b")
    assert parsed is not None
    assert parsed["model"] == "lfm3:1.7b"
    assert parsed["overall"] == 70.0
    assert parsed["templates"]["tool_calling"][0] == 100.0
    assert parsed["templates"]["long_context"][0] == 0.0
    # Speed had no score in the real file: no evidence, not a crash.
    assert "speed" not in parsed["templates"]
    assert parsed["tested"].strftime("%b %Y") == "Nov 2026"


def test_parse_multi_model_summary_picks_matching_tag(tmp_path):
    """A multi-model summary (the real results-summary-*.json
    shape) picks the entry for the profile's tag."""
    from stella.report_cards import parse_ost_card

    bonsai = {
        "model": "eriktonon/bonsai-2-uncensored:2b",
        "slug": "eriktonon_bonsai-2-uncensored_2b",
        "templates_scored": 1,
        "overall_score": 73.1,
        "mean_decode_tok_s": 1.0,
        "templates": {
            "coding": {
                "name": "Coding", "capability": "text", "score": 100.0,
                "passed": 5, "total": 5, "not_run": 0,
                "budget_stopped": 0, "time_budget_reached": False,
                "avg_decode_tok_s": 0.9,
                "timestamp": "2026-11-15T11:08:44",
            },
        },
    }
    path = _write_card(
        tmp_path, "summary.json",
        {
            "eriktonon_bonsai-2-uncensored_2b": bonsai,
            "lfm3_1.7b": _lfm3_summary_block(),
        },
    )
    parsed = parse_ost_card(path, tag_hint="lfm3:1.7b")
    assert parsed is not None
    assert parsed["model"] == "lfm3:1.7b"
    assert parsed["overall"] == 70.0


def test_parse_multi_model_summary_no_match_is_none(tmp_path):
    """A multi-model summary with no entry for the tag is not
    guessed: None, so the card is stored, not understood."""
    from stella.report_cards import parse_ost_card

    other = dict(_lfm3_summary_block())
    other["model"] = "qwen3.5:4b"
    path = _write_card(
        tmp_path, "summary.json",
        {"lfm3_1.7b": _lfm3_summary_block(), "qwen3.5_4b": other},
    )
    assert parse_ost_card(path, tag_hint="granite:3b") is None


def test_parse_single_model_file_used_as_is(tmp_path):
    """A file holding ONE model is used as-is, even when its
    model differs from the tag hint: attaching it to this
    profile was the user's choice."""
    from stella.report_cards import parse_ost_card

    path = _write_card(tmp_path, "one.json", _lfm3_summary_block())
    parsed = parse_ost_card(path, tag_hint="granite:3b")
    assert parsed is not None
    assert parsed["model"] == "lfm3:1.7b"


def test_parse_per_template_result_file(tmp_path):
    """One per-template result file (save_run_file shape) parses
    as a one-template card."""
    from stella.report_cards import parse_ost_card

    run = {
        "avg_decode_tok_s": 0.68, "budget_stopped": 0,
        "capability": "tools", "model": "lfm3:1.7b",
        "model_slug": "lfm3_1.7b", "not_run": 0, "passed": 5,
        "provider": "ollama", "template": "tool_calling",
        "template_name": "Tool Calling", "template_score": 100.0,
        "time_budget_reached": False,
        "timestamp": "2026-11-16T16:54:19", "total": 5,
        "tasks": [],
    }
    path = _write_card(tmp_path, "run.json", run)
    parsed = parse_ost_card(path, tag_hint="lfm3:1.7b")
    assert parsed is not None
    assert parsed["overall"] is None
    assert parsed["templates"] == {
        "tool_calling": (100.0, 5, parsed["tested"])
    }


def test_parse_gui_report_list(tmp_path):
    """An OST GUI report (bench-results shape: {"generated",
    "models": [...]}) parses the matching model."""
    from stella.report_cards import parse_ost_card

    report = {
        "generated": "2026-11-16T18:00:00",
        "machine": "CPU-only (no GPU)",
        "ollama": "http://127.0.0.1:11434",
        "warmup_prompt": "Say hello in one sentence.",
        "temperature": 0,
        "models": [
            {
                "name": "lfm3:1.7b", "status": "done",
                "overall_score": 70.0,
                "templates": {
                    "tool_calling": {
                        "template": "tool_calling",
                        "template_name": "Tool Calling",
                        "template_score": 100.0, "passed": 5,
                        "total": 5,
                        "timestamp": "2026-11-16T16:54:19",
                    },
                    "planning": {
                        "template": "planning",
                        "template_name": "Planning",
                        "template_score": 0.0, "passed": 0, "total": 5,
                        "timestamp": "2026-11-16T16:45:21",
                    },
                },
            },
        ],
    }
    path = _write_card(tmp_path, "bench.json", report)
    parsed = parse_ost_card(path, tag_hint="lfm3:1.7b")
    assert parsed is not None
    assert parsed["overall"] == 70.0
    assert parsed["templates"]["tool_calling"][0] == 100.0
    assert parsed["templates"]["planning"][0] == 0.0


def test_parse_list_of_template_results(tmp_path):
    """A JSON list of per-template result files merges, newest
    run per template winning."""
    from stella.report_cards import parse_ost_card

    def run(template, score, ts):
        return {
            "template": template, "template_score": score,
            "passed": 5, "total": 5, "model": "lfm3:1.7b",
            "timestamp": ts,
        }

    path = _write_card(
        tmp_path, "runs.json",
        [
            run("coding", 20.0, "2026-11-10T10:00:00"),
            run("coding", 80.0, "2026-11-16T10:00:00"),
            run("math", 90.0, "2026-11-16T11:00:00"),
        ],
    )
    parsed = parse_ost_card(path)
    assert parsed is not None
    assert parsed["templates"]["coding"][0] == 80.0
    assert parsed["templates"]["math"][0] == 90.0


def test_parse_non_ost_and_broken_files_are_none(tmp_path):
    """Not OST-shaped, broken JSON, and unreadable bytes all
    parse to None — never a crash."""
    from stella.report_cards import parse_ost_card

    plain = tmp_path / "notes.txt"
    plain.write_text("just some words", encoding="utf-8")
    assert parse_ost_card(plain) is None
    other_json = tmp_path / "other.json"
    other_json.write_text('{"hello": "world"}', encoding="utf-8")
    assert parse_ost_card(other_json) is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert parse_ost_card(broken) is None
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\x00\xff\x00\xff not utf-8")
    assert parse_ost_card(binary) is None
    assert parse_ost_card(tmp_path / "missing.json") is None


def test_parse_template_with_no_questions_gives_no_evidence(tmp_path):
    """A template with total 0 is skipped when strengths are
    derived, even at a perfect score."""
    from stella.report_cards import parse_ost_card, strengths_from_cards

    block = _lfm3_summary_block()
    block["templates"] = {
        "coding": {
            "name": "Coding", "capability": "text", "score": 100.0,
            "passed": 0, "total": 0, "not_run": 5,
            "budget_stopped": 0, "time_budget_reached": False,
            "avg_decode_tok_s": 0.0,
            "timestamp": "2026-11-16T16:48:33",
        },
    }
    path = _write_card(tmp_path, "empty.json", block)
    parsed = parse_ost_card(path, tag_hint="lfm3:1.7b")
    assert parsed is not None
    assert parsed["templates"]["coding"][1] == 0
    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    from stella.report_cards import add_report_card

    add_report_card(store, "lfm3-tool", path)
    entry = strengths_from_cards(store, "lfm3-tool")
    assert entry is not None
    assert entry["good"] == []
    assert entry["not_good"] == []


# -- attach / list / remove ------------------------------------------


def test_attach_ost_card_updates_strengths(tmp_path):
    """Attaching LFM3's real OST card makes the card's strengths
    win over the built-in table — including where the card
    contradicts it (the table says LFM3 is good at reading long
    documents; the card scored Long Context 0%)."""
    from stella.report_cards import (
        add_report_card,
        list_report_cards,
        strengths_from_cards,
    )

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    path = _write_card(tmp_path, "lfm3.json", _lfm3_summary_block())
    card = add_report_card(store, "lfm3-tool", path)
    assert card["kind"] == "ost"
    assert card["date"] == "Nov 2026"
    assert "70 out of 100" in card["line"]
    entry = strengths_from_cards(store, "lfm3-tool")
    assert entry is not None
    assert entry["source"] == "From its OST report card, Nov 2026."
    assert entry["overall"] == 70.0
    # Best first: the 100s, then maths (90), then the 80s.
    assert entry["good"][:6] == [
        "answering from given text", "following instructions",
        "saying no to bad requests", "summing up", "using tools",
        "writing in a set format",
    ]
    assert entry["good"][6] == "maths"
    assert entry["good"][7:] == ["knowledge questions", "writing code"]
    # Worst first: the 0s, then the 40s. The middle scores
    # (multi-turn, reasoning at 60) say nothing.
    assert entry["not_good"] == [
        "making plans", "reading long documents",
        "fixing code", "staying in character",
    ]
    assert "long conversations" not in entry["good"]
    assert "long conversations" not in entry["not_good"]
    assert len(list_report_cards(store, "lfm3-tool")) == 1


def test_attach_copies_the_file(tmp_path):
    """The original may move or be deleted: the card is a copy
    in the profile's own folder."""
    from stella.report_cards import add_report_card, list_report_cards

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    src = tmp_path / "card.pdf"
    src.write_bytes(b"%PDF-1.4 fake card")
    add_report_card(store, "lfm3-tool", src)
    src.unlink()
    cards = list_report_cards(store, "lfm3-tool")
    assert len(cards) == 1
    assert cards[0]["kind"] == "other"
    assert Path(cards[0]["path"]).read_bytes() == b"%PDF-1.4 fake card"


def test_attach_same_name_twice_keeps_both(tmp_path):
    """A same-named card is kept as \"name (2)\", never
    overwritten."""
    from stella.report_cards import add_report_card, list_report_cards

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    first = tmp_path / "a"
    first.mkdir()
    second = tmp_path / "b"
    second.mkdir()
    (first / "card.json").write_text("{}", encoding="utf-8")
    (second / "card.json").write_text("{}", encoding="utf-8")
    add_report_card(store, "lfm3-tool", first / "card.json")
    add_report_card(store, "lfm3-tool", second / "card.json")
    names = [c["name"] for c in list_report_cards(store, "lfm3-tool")]
    assert sorted(names) == ["card (2).json", "card.json"]


def test_attach_oversize_file_refused_plainly(tmp_path):
    """A file over the 10 MB cap is refused in plain words,
    and nothing is copied."""
    from stella.model import StellaError
    from stella.report_cards import add_report_card, list_report_cards

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    big = tmp_path / "big.json"
    with open(big, "wb") as handle:
        handle.write(b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(StellaError, match="too big"):
        add_report_card(store, "lfm3-tool", big)
    assert list_report_cards(store, "lfm3-tool") == []


def test_attach_missing_file_and_folder_refused_plainly(tmp_path):
    """A missing file and a folder are both refused in plain
    words, with no traceback."""
    from stella.model import StellaError
    from stella.report_cards import add_report_card

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    with pytest.raises(StellaError, match="could not find"):
        add_report_card(store, "lfm3-tool", tmp_path / "gone.json")
    folder = tmp_path / "a-folder"
    folder.mkdir()
    with pytest.raises(StellaError, match="a folder"):
        add_report_card(store, "lfm3-tool", folder)


def test_generic_card_is_stored_not_understood(tmp_path):
    """A PDF or text card from anywhere else is listed with its
    name and date, and the strengths stay on the table."""
    from stella.report_cards import (
        add_report_card,
        list_report_cards,
        strengths_from_cards,
    )
    from stella.strengths import strengths_for_tag

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    note = tmp_path / "someone-elses-notes.txt"
    note.write_text("great model, trust me", encoding="utf-8")
    add_report_card(store, "lfm3-tool", note)
    cards = list_report_cards(store, "lfm3-tool")
    assert len(cards) == 1
    assert cards[0]["kind"] == "other"
    assert cards[0]["line"] == "Stored here. Stella does not read it."
    assert strengths_from_cards(store, "lfm3-tool") is None
    assert strengths_for_tag("lfm3:1.7b") is not None


def test_ost_card_for_another_model_is_flagged(tmp_path):
    """An OST card for a different model is listed as such, and
    the strengths stay on the table."""
    from stella.report_cards import (
        add_report_card,
        list_report_cards,
        strengths_from_cards,
    )

    store = Store(tmp_path / "home")
    store.create_profile("granite", ollama_tag="granite:3b")
    other = dict(_lfm3_summary_block())
    other["model"] = "qwen3.5:4b"
    path = _write_card(
        tmp_path, "two-models.json",
        {"lfm3_1.7b": _lfm3_summary_block(), "qwen3.5_4b": other},
    )
    add_report_card(store, "granite", path)
    cards = list_report_cards(store, "granite")
    assert cards[0]["kind"] == "ost-other"
    assert cards[0]["line"] == (
        "An OST report card, but not for this model."
    )
    assert strengths_from_cards(store, "granite") is None


def test_newest_card_wins_then_falls_back(tmp_path):
    """Newest OST card wins; removing it falls back to the older
    card, then to the built-in table."""
    from stella.report_cards import (
        add_report_card,
        list_report_cards,
        remove_report_card,
        strengths_from_cards,
    )

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    old = _lfm3_summary_block()
    for entry in old["templates"].values():
        entry["timestamp"] = "2026-11-10T10:00:00"
        entry["score"] = 100.0
    old["overall_score"] = 100.0
    old_path = _write_card(tmp_path, "old.json", old)
    new_path = _write_card(tmp_path, "new.json", _lfm3_summary_block())
    add_report_card(store, "lfm3-tool", old_path)
    add_report_card(store, "lfm3-tool", new_path)
    entry = strengths_from_cards(store, "lfm3-tool")
    assert entry["overall"] == 70.0  # the Nov 16 card, not Nov 10
    assert "reading long documents" in entry["not_good"]
    remove_report_card(store, "lfm3-tool", "new.json")
    entry = strengths_from_cards(store, "lfm3-tool")
    assert entry["overall"] == 100.0  # the older card now
    assert entry["not_good"] == []
    remove_report_card(store, "lfm3-tool", "old.json")
    assert strengths_from_cards(store, "lfm3-tool") is None
    assert list_report_cards(store, "lfm3-tool") == []


def test_remove_refuses_bad_names_and_missing_cards(tmp_path):
    """Removing a card that is not there, or a name with a path
    in it, is refused in plain words."""
    from stella.model import StellaError
    from stella.report_cards import remove_report_card

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    with pytest.raises(StellaError, match="not there anymore"):
        remove_report_card(store, "lfm3-tool", "nope.json")
    with pytest.raises(StellaError, match="not a report card name"):
        remove_report_card(store, "lfm3-tool", "../profile.json")
    with pytest.raises(StellaError, match="not a report card name"):
        remove_report_card(store, "lfm3-tool", "..")


def test_malformed_card_on_disk_never_breaks_listing(tmp_path):
    """Garbage bytes dropped into the cards folder are listed as
    stored files; listing and strengths never raise."""
    from stella.report_cards import (
        list_report_cards,
        strengths_from_cards,
    )

    store = Store(tmp_path / "home")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    folder = (
        store.profile_dir("lfm3-tool") / "report-cards"
    )
    folder.mkdir(parents=True)
    (folder / "garbage.json").write_bytes(b"\x00\xff\x00\xff")
    (folder / "half.json").write_text("{not json", encoding="utf-8")
    cards = list_report_cards(store, "lfm3-tool")
    assert len(cards) == 2
    assert {c["kind"] for c in cards} == {"other"}
    assert strengths_from_cards(store, "lfm3-tool") is None


def test_unknown_profile_lists_nothing(tmp_path):
    """Listing cards for a profile that does not exist gives []."""
    from stella.report_cards import list_report_cards, strengths_from_cards

    store = Store(tmp_path / "home")
    assert list_report_cards(store, "nope") == []
    assert strengths_from_cards(store, "nope") is None


# -- export / import -----------------------------------------------


def test_profile_export_carries_cards_and_import_restores_them(tmp_path):
    """A profile export carries report-cards/, and an import
    into a fresh home brings the cards back — still understood."""
    from stella import export as export_mod
    from stella.report_cards import (
        add_report_card,
        list_report_cards,
        strengths_from_cards,
    )

    src = Store(tmp_path / "src-home")
    src.create_profile("solo", ollama_tag="lfm3:1.7b")
    card_path = _write_card(
        tmp_path, "lfm3.json", _lfm3_summary_block()
    )
    add_report_card(src, "solo", card_path)
    note = tmp_path / "notes.txt"
    note.write_text("from elsewhere", encoding="utf-8")
    add_report_card(src, "solo", note)
    out = export_mod.export_profile(src, "solo", tmp_path)
    assert (out / "report-cards" / "lfm3.json").is_file()
    assert (out / "report-cards" / "notes.txt").is_file()
    fresh = Store(tmp_path / "fresh-home")
    export_mod.import_export(fresh, out)
    cards = list_report_cards(fresh, "solo")
    assert sorted(c["name"] for c in cards) == [
        "lfm3.json", "notes.txt",
    ]
    entry = strengths_from_cards(fresh, "solo")
    assert entry is not None
    assert entry["overall"] == 70.0
    assert "using tools" in entry["good"]


def test_profile_export_without_cards_has_no_cards_dir(tmp_path):
    """A profile with no cards exports no report-cards dir —
    absent cards stay absent, not an empty folder."""
    from stella import export as export_mod

    src = Store(tmp_path / "src-home")
    src.create_profile("solo", ollama_tag="lfm3:1.7b")
    out = export_mod.export_profile(src, "solo", tmp_path)
    assert not (out / "report-cards").exists()


def test_profile_import_keeps_local_cards_when_profile_exists(tmp_path):
    """Importing a profile package over an existing profile
    never overwrites the local cards with the package's — the
    same rule as the profile notes."""
    from stella import export as export_mod
    from stella.report_cards import add_report_card, list_report_cards

    src = Store(tmp_path / "src-home")
    src.create_profile("solo", ollama_tag="lfm3:1.7b")
    pkg_card = _write_card(
        tmp_path, "pkg.json", _lfm3_summary_block()
    )
    add_report_card(src, "solo", pkg_card)
    out = export_mod.export_profile(src, "solo", tmp_path)
    local = Store(tmp_path / "local-home")
    local.create_profile("solo", ollama_tag="lfm3:1.7b")
    mine = tmp_path / "mine.txt"
    mine.write_text("my own card", encoding="utf-8")
    add_report_card(local, "solo", mine)
    export_mod.import_export(local, out)
    names = [c["name"] for c in list_report_cards(local, "solo")]
    assert names == ["mine.txt"]


def test_profile_export_size_counts_cards(tmp_path):
    """The export size estimate counts the report cards, so the
    disk check is honest."""
    from stella import export as export_mod
    from stella.report_cards import add_report_card

    src = Store(tmp_path / "src-home")
    src.create_profile("solo", ollama_tag="lfm3:1.7b")
    before = export_mod.estimate_profile_export_size(src, "solo")
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"x" * 4096)
    add_report_card(src, "solo", blob)
    after = export_mod.estimate_profile_export_size(src, "solo")
    assert after - before == 4096


# -- the profile window ----------------------------------------------


def test_profile_window_shows_report_cards_section(
    window, seeded, qapp
):
    """The simple view has a Report cards section with the add
    button, and an empty profile says so."""
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert win.cards_list.isVisible() is False
    assert win.cards_empty_label.isVisible() is True
    assert win.cards_empty_label.text() == "No report cards yet."
    assert win.card_add_btn.text() == "Add a report card"
    assert win.card_open_btn.isEnabled() is False
    assert win.card_remove_btn.isEnabled() is False
    win.close()


def test_profile_window_add_card_changes_strengths(
    window, seeded, qapp, tmp_path, monkeypatch
):
    """Adding an OST card through the window changes the
    strengths at once, with the source line."""
    from PySide6.QtWidgets import QFileDialog

    path = _write_card(tmp_path, "lfm3.json", _lfm3_summary_block())
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *a, **k: (str(path), ""),
    )
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert "reading long documents" in win.strengths_label.text()
    assert "Good at: using tools" in win.strengths_label.text()
    win.card_add_btn.click()
    qapp.processEvents()
    assert win.cards_list.count() == 1
    assert "lfm3.json - Nov 2026" in win.cards_list.item(0).text()
    text = win.strengths_label.text()
    # The card beats the table: long documents moved to not good.
    assert "Not good at: making plans, reading long documents" in text
    assert "From its OST report card, Nov 2026." in text
    win.close()


def test_profile_window_remove_card_falls_back_to_table(
    window, seeded, qapp, tmp_path, monkeypatch
):
    """Removing the only OST card falls back to the built-in
    table strengths at once."""
    from PySide6.QtWidgets import QMessageBox

    from stella.report_cards import add_report_card

    path = _write_card(tmp_path, "lfm3.json", _lfm3_summary_block())
    add_report_card(seeded, "lfm3-tool", path)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.Yes,
    )
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert "From its OST report card" in win.strengths_label.text()
    win.cards_list.setCurrentRow(0)
    qapp.processEvents()
    assert win.card_remove_btn.isEnabled() is True
    win.card_remove_btn.click()
    qapp.processEvents()
    assert win.cards_list.count() == 0
    assert win.cards_empty_label.isVisible() is True
    text = win.strengths_label.text()
    assert "From its OST report card" not in text
    assert "Good at: using tools" in text
    win.close()


def test_profile_window_remove_card_cancel_keeps_it(
    window, seeded, qapp, tmp_path, monkeypatch
):
    """Answering No on the remove confirm keeps the card."""
    from PySide6.QtWidgets import QMessageBox

    from stella.report_cards import add_report_card

    path = _write_card(tmp_path, "lfm3.json", _lfm3_summary_block())
    add_report_card(seeded, "lfm3-tool", path)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.No,
    )
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    win.cards_list.setCurrentRow(0)
    win.card_remove_btn.click()
    qapp.processEvents()
    assert win.cards_list.count() == 1
    win.close()


def test_profile_window_open_card_uses_desktop(
    window, seeded, qapp, tmp_path, monkeypatch
):
    """Open hands the card's file to the desktop opener."""
    from PySide6.QtGui import QDesktopServices

    from stella.report_cards import add_report_card

    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    path = _write_card(tmp_path, "lfm3.json", _lfm3_summary_block())
    add_report_card(seeded, "lfm3-tool", path)
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    win.cards_list.setCurrentRow(0)
    qapp.processEvents()
    assert win.cards_detail_label.text().startswith(
        "OST tested this model"
    )
    win.card_open_btn.click()
    assert len(opened) == 1
    assert "lfm3.json" in opened[0]
    win.close()


def test_profile_window_with_malformed_card_still_opens(
    window, seeded, qapp
):
    """A garbage card file on disk never breaks the window: it
    opens, lists the card as stored, and shows table strengths."""
    folder = (
        seeded.profile_dir("lfm3-tool") / "report-cards"
    )
    folder.mkdir(parents=True)
    (folder / "garbage.json").write_bytes(b"\x00\xff\x00\xff")
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert win.cards_list.count() == 1
    win.cards_list.setCurrentRow(0)
    qapp.processEvents()
    assert win.cards_detail_label.text() == (
        "Stored here. Stella does not read it."
    )
    assert "Good at: using tools" in win.strengths_label.text()
    win.close()


def test_profile_window_cards_section_has_no_jargon(
    window, seeded, qapp, tmp_path
):
    """The Report cards section adds no jargon to the simple
    view — no JSON, no benchmark words, no eval words."""
    from tests.test_v31 import _visible_window_texts

    from stella.report_cards import add_report_card

    path = _write_card(tmp_path, "lfm3.json", _lfm3_summary_block())
    add_report_card(seeded, "lfm3-tool", path)
    note = tmp_path / "notes.txt"
    note.write_text("from elsewhere", encoding="utf-8")
    add_report_card(seeded, "lfm3-tool", note)
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert not win.details_section.is_expanded()
    banned = (
        "JSON", "eval", "benchmark", "artifact", "payload",
        "quant", "Base ref", "Governing seat",
    )
    bad = [
        t for t in _visible_window_texts(win)
        for word in banned
        if word in t
    ]
    assert bad == []
    win.close()


# -- the Granite bridge entry (v0.32.0 addition) ---------------------


def test_bridge_granite_tag_maps_to_ibm_base():
    """Granite 4.1 maps to its IBM base, verified on the Hub
    2026-11-18 — exact tag, and the version-stripped fallback."""
    from stella.ollama_bridge import suggest_hf_repos

    assert suggest_hf_repos("huihui_ai/granite4.1-abliterated:3b") == [
        {"repo": "ibm-granite/granite-4.1-3b-base",
         "source": "the base model this Ollama tag is tuned from"}
    ]
    assert suggest_hf_repos("huihui_ai/granite4.1-abliterated") == [
        {"repo": "ibm-granite/granite-4.1-3b-base",
         "source": "the base model this Ollama tag is tuned from"}
    ]


def test_bridge_reviewer_and_bonsai_stay_unknown():
    """The reviewer (unverified) and bonsai-2 (proven to have no
    2B transformers repo on the Hub) stay unknown — never a
    fabricated guess."""
    from stella.ollama_bridge import suggest_hf_repos

    assert suggest_hf_repos("dolphinlabs/qwen3.5-uncensored:latest") == []
    assert suggest_hf_repos("eriktonon/bonsai-2-uncensored:2b") == []


def test_guard_catches_lfm3_repo_on_granite_profile(
    window, monkeypatch
):
    """Joshua's actual case: his Granite profile had LFM3's repo
    typed in (the old jargon message's example). The mismatch
    guard now catches it — the warning names both repos, and the
    switch stores the Granite base and downloads it."""
    from tests.test_v30 import (
        _click_box_button,
        _guard_profile,
        _mock_download,
    )

    _guard_profile(
        window, "granite", "huihui_ai/granite4.1-abliterated:3b",
        "LiquidAI/LFM3-1.7B",
    )
    seen = []
    _click_box_button(monkeypatch, "Use ", seen)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("granite")
    assert len(seen) == 1
    assert "LiquidAI/LFM3-1.7B" in seen[0]
    assert "ibm-granite/granite-4.1-3b-base" in seen[0]
    assert window.store.get_profile("granite")["base_ref"] == (
        "ibm-granite/granite-4.1-3b-base"
    )
    assert started == ["ibm-granite/granite-4.1-3b-base"]
