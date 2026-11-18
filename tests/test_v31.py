"""STELLA v0.31.0 tests — the child-simple Profile window and
derived roles (nobody assigns roles by hand anymore).

The strengths table (grounded in the roster audit + OST's graded
results), the store's role derivation at creation and on tag
change, the simple view with no jargon, the Details flap, the
plain what-it-does line, the readiness button, the projects list,
and the tree role filter still working off derived roles.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from stella.model import STELLA_VERSION

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


@pytest.fixture()
def seed_show():
    """Seed the T165 /api/show cache for one tag, and stop real
    fetches for the test — the same fixture test_gui.py uses."""
    from stella.ollama import SHOW_CACHE

    def _seed(tag, info, ollama_up=True):
        SHOW_CACHE.set_snapshot(tag, info, ollama_up=ollama_up)

    yield _seed
    SHOW_CACHE.reset()


def test_version_is_0_31_0(home):
    """The version is 0.31.0 everywhere the CLI reports it."""
    assert STELLA_VERSION == "0.31.0"
    res = _run_cli_subprocess(home, "--version")
    assert res.returncode == 0
    assert "0.31.0" in res.stdout


def test_window_title_carries_version(window):
    """The window title carries STELLA 0.31.0."""
    assert "0.31.0" in window.windowTitle()


# -- strengths table ------------------------------------------------


def test_strengths_known_tag_returns_role_and_phrases():
    from stella.strengths import strengths_for_tag

    entry = strengths_for_tag("maternion/minicpm5-heretic:2b")
    assert entry is not None
    assert entry["role"] == "driver"
    assert "writing code" in entry["good"]
    assert "using tools" in entry["good"]
    assert "answering quickly" in entry["not_good"]
    assert "it can repeat itself" in entry["not_good"]


def test_strengths_lfm3_from_audit_and_ost_card():
    """LFM3: the audit's tool strength, confirmed by OST's card
    (Tool Calling 100%) — but no derived role: it is a trial
    understudy, not a seat holder, and it is stock."""
    from stella.strengths import derived_role, strengths_for_tag

    entry = strengths_for_tag("lfm3:1.7b")
    assert entry is not None
    assert entry["role"] == ""
    assert "using tools" in entry["good"]
    assert "answering fast" in entry["good"]
    assert "long multi-step jobs" in entry["not_good"]
    assert "it still refuses some ordinary work" in entry["not_good"]
    assert derived_role("lfm3:1.7b") == ""


def test_strengths_unknown_tag_returns_none():
    from stella.strengths import derived_role, strengths_for_tag

    assert strengths_for_tag("someone/unknown-model:9b") is None
    assert strengths_for_tag("") is None
    assert derived_role("someone/unknown-model:9b") == ""


def test_strengths_versionless_fallback():
    from stella.strengths import strengths_for_tag

    assert strengths_for_tag("lfm3")["good"] == strengths_for_tag(
        "lfm3:1.7b"
    )["good"]
    assert strengths_for_tag("qwen3-vl:2b")["role"] == "vision"
    assert strengths_for_tag("bonsai-2")["role"] == ""


def test_strengths_ambiguous_base_returns_none():
    """qwen3.5 bare could be the 2B or the 4B — no guess."""
    from stella.strengths import strengths_for_tag

    assert strengths_for_tag("qwen3.5") is None


def test_strengths_every_entry_is_plain_words():
    """Every phrase a child can read: no em-dash, no bare &,
    no benchmark names, no quant names, no seat jargon. Every
    entry has both a good and a not-good list, and every role is
    canonical or blank."""
    from stella.model import CANONICAL_ROLES
    from stella.strengths import KNOWN_STRENGTHS

    banned = (
        "—", "&", "quant", "Q4", "Q8", "parameters", "BFCL",
        "MMLU", "token", "context", "completion", "abliterat",
        "governing", "seat",
    )
    assert len(KNOWN_STRENGTHS) == 11
    for tag, role, good, not_good in KNOWN_STRENGTHS:
        assert role == "" or role in CANONICAL_ROLES
        assert good and not_good
        for phrase in list(good) + list(not_good):
            for word in banned:
                assert word not in phrase, (tag, phrase, word)


def test_derived_governing_roles_only_for_seat_holders():
    """A governing role is derived only for the three tags that
    actually hold those seats in Forge. Every other entry derives
    a non-governing role or none at all."""
    from stella.model import GOVERNING_SEATS
    from stella.strengths import KNOWN_STRENGTHS, derived_role

    holders = {
        "maternion/minicpm5-heretic:2b": "driver",
        "dolphinlabs/qwen3.5-uncensored:latest": "reviewer",
        "eriktonon/bonsai-2-uncensored:2b": "fast",
    }
    for tag, role, _good, _not_good in KNOWN_STRENGTHS:
        if tag in holders:
            assert derived_role(tag) == holders[tag]
        else:
            assert role not in GOVERNING_SEATS, tag


# -- store derivation -----------------------------------------------


def test_create_profile_derives_role_from_tag(store):
    data = store.create_profile(
        "heretic", ollama_tag="maternion/minicpm5-heretic:2b"
    )
    assert data["role"] == "driver"
    assert store.get_profile("heretic")["role"] == "driver"


def test_create_profile_explicit_role_wins(store):
    data = store.create_profile(
        "p1", ollama_tag="lfm3:1.7b", role="tester"
    )
    assert data["role"] == "tester"


def test_create_profile_unknown_tag_leaves_role_blank(store):
    data = store.create_profile(
        "p1", ollama_tag="someone/unknown-model:9b"
    )
    assert data["role"] == ""


def test_update_profile_rederives_role_on_tag_change(store):
    store.create_profile("p1", ollama_tag="lfm3:1.7b")
    assert store.get_profile("p1")["role"] == ""
    store.update_profile("p1", ollama_tag="qwen3-vl:2b-instruct")
    assert store.get_profile("p1")["role"] == "vision"


def test_update_profile_keeps_deliberate_role_on_tag_change(store):
    """A role set deliberately (from the terminal) stays when the
    tag changes — only a derived or blank role follows the tag."""
    store.create_profile(
        "p1", ollama_tag="lfm3:1.7b", role="tester"
    )
    store.update_profile("p1", ollama_tag="qwen3-vl:2b-instruct")
    assert store.get_profile("p1")["role"] == "tester"


def test_update_profile_explicit_role_in_same_call_wins(store):
    store.create_profile(
        "p1", ollama_tag="maternion/minicpm5-heretic:2b"
    )
    assert store.get_profile("p1")["role"] == "driver"
    store.update_profile(
        "p1", ollama_tag="qwen3-vl:2b-instruct", role="utility"
    )
    assert store.get_profile("p1")["role"] == "utility"


def test_update_profile_tag_change_to_unknown_clears_derived(store):
    store.create_profile(
        "p1", ollama_tag="maternion/minicpm5-heretic:2b"
    )
    assert store.get_profile("p1")["role"] == "driver"
    store.update_profile("p1", ollama_tag="someone/unknown:1b")
    assert store.get_profile("p1")["role"] == ""


# -- plain capabilities ---------------------------------------------


def test_plain_capabilities():
    from stella.gui import _plain_capabilities

    assert _plain_capabilities([]) == (
        "Stella does not know what this model can do yet."
    )
    assert _plain_capabilities(["completion"]) == (
        "It can write and answer."
    )
    assert _plain_capabilities(["completion", "tools"]) == (
        "It can write and answer, and use tools."
    )
    assert _plain_capabilities(
        ["completion", "tools", "vision"]
    ) == "It can write and answer, use tools, and see pictures."
    # An unknown capability is left out, not shown raw.
    assert _plain_capabilities(["completion", "telepathy"]) == (
        "It can write and answer."
    )


# -- the simple window ----------------------------------------------


def _visible_window_texts(win):
    """Every visible string in the profile window: widget text,
    placeholders, and tooltips of widgets that are actually
    showing (Details content is hidden while the flap is
    closed)."""
    from PySide6.QtWidgets import (
        QLabel, QLineEdit, QListWidget, QPushButton, QWidget,
    )

    texts = [win.windowTitle()]
    for widget in win.findChildren(QWidget):
        if not widget.isVisible():
            continue
        if isinstance(widget, (QLabel, QPushButton)):
            texts.append(widget.text())
        if isinstance(widget, QLineEdit):
            texts.append(widget.placeholderText())
        if isinstance(widget, QListWidget):
            for i in range(widget.count()):
                texts.append(widget.item(i).text())
        texts.append(widget.toolTip())
    return texts


def test_profile_window_simple_view_has_no_jargon(
    window, seeded, qapp
):
    """v0.31.0: what opens has no jargon — no quant names, no
    parameter counts, no Ollama tag, no Base ref, no governing
    seat, no JSON, no raw capability words."""
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert not win.details_section.is_expanded()
    banned = (
        "quant", "Q4_K_M", "parameters", "Ollama tag", "Base ref",
        "Governing seat", "JSON", "completion", "can do:",
        "tokens", "context", "Config", "Dependencies",
    )
    bad = [
        t for t in _visible_window_texts(win)
        for word in banned
        if word in t
    ]
    assert bad == []
    win.close()


def test_profile_window_details_closed_then_opens_with_all_fields(
    window, seeded, qapp
):
    """v0.31.0: Details starts closed; opening it shows every
    technical field, still working — a seat set there saves."""
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert not win.details_section.is_expanded()
    assert not win.seat_combo.isVisible()
    win.details_section.set_expanded(True)
    qapp.processEvents()
    assert win.details_section.is_expanded()
    assert win.seat_combo.isVisible()
    assert win.tag_combo.isVisible()
    assert win.base_edit.isVisible()
    assert win.config_edit.isVisible()
    assert win.role_label.text() == "fast"
    win.seat_combo.setCurrentText("driver")
    assert win.save() is True
    assert seeded.get_profile("lfm3-tool")["governing_seat"] == "driver"
    win.close()


def test_profile_window_shows_derived_strengths(window, qapp):
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    text = win.strengths_label.text()
    assert "Good at: using tools" in text
    assert "Not good at: long multi-step jobs" in text
    win.close()


def test_profile_window_unknown_model_says_not_measured(
    window, seeded, qapp
):
    seeded.create_profile(
        "mystery", ollama_tag="someone/unknown-model:9b"
    )
    win = window.open_profile_window("mystery")
    qapp.processEvents()
    assert win.strengths_label.text() == "Not measured yet."
    assert win.role_label.text() == "No role yet"
    win.close()


def test_profile_window_plain_what_it_does_and_size(
    window, seed_show, qapp
):
    """The /api/show facts render twice: plain words up top,
    the technical line in Details."""
    seed_show("lfm3:1.7b", {
        "size_bytes": 2000000000, "quant": "Q4_K_M",
        "context": 131072, "capabilities": ["completion", "tools"],
        "parameter_size": "1.7B", "family": "llama",
    })
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert win.what_label.text() == (
        "It can write and answer, and use tools."
    )
    assert win.size_label.text() == "Size on disk: 1.9 GB."
    assert "Q4_K_M" in win.model_info_label.text()
    assert "completion, tools" in win.model_info_label.text()
    win.close()


def test_profile_window_what_it_does_honest_when_ollama_down(
    window, seed_show, qapp
):
    seed_show("lfm3:1.7b", None, ollama_up=False)
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert win.what_label.text() == (
        "Stella does not know what this model can do yet."
    )
    assert win.size_label.text() == ""
    win.close()


def test_profile_window_readiness_button_starts_download(
    window, monkeypatch, qapp
):
    """The one button calls the main window's download — the
    bridge offer and the progress bar live there."""
    calls = []
    monkeypatch.setattr(
        window, "start_download", lambda slug: calls.append(slug)
    )
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert win.readiness_label.text() == (
        "Training files are not downloaded yet."
    )
    assert win.download_btn.isVisible()
    assert win.download_btn.text() == "Download the training files"
    win.download_btn.click()
    assert calls == ["lfm3-tool"]
    win.close()


def test_profile_window_download_button_hidden_when_ready(
    window, monkeypatch, qapp
):
    import stella.provision as provision_mod

    monkeypatch.setattr(
        provision_mod, "weights_status",
        lambda store, slug: {
            "repo": "LiquidAI/LFM3-1.7B", "state": "ready",
            "size_bytes": 1, "path": "/tmp/x",
        },
    )
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert win.readiness_label.text() == (
        "Training files are downloaded."
    )
    assert not win.download_btn.isVisible()
    win.close()


def test_profile_window_projects_list_and_start_button(
    window, monkeypatch, qapp
):
    """The profile's projects list, with a Start a project
    button that runs the usual flow for this profile."""
    started = []
    monkeypatch.setattr(
        window, "new_project", lambda: started.append(True)
    )
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert win.projects_list.count() == 1
    assert win.projects_list.item(0).text() == "tool-calls"
    assert not win.projects_empty_label.isVisible()
    win.new_project_btn.click()
    assert started == [True]
    assert window._current_profile == "lfm3-tool"
    win.close()


def test_profile_window_double_click_project_opens_it(
    window, monkeypatch, qapp
):
    opened = []
    monkeypatch.setattr(
        window, "open_project_window",
        lambda profile, project: opened.append((profile, project)),
    )
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    item = win.projects_list.item(0)
    win.projects_list.itemDoubleClicked.emit(item)
    assert opened == [("lfm3-tool", "tool-calls")]
    win.close()


def test_profile_window_empty_profile_says_no_projects(
    window, seeded, qapp
):
    seeded.create_profile("empty", ollama_tag="lfm3:1.7b")
    win = window.open_profile_window("empty")
    qapp.processEvents()
    assert win.projects_list.count() == 0
    assert win.projects_empty_label.isVisible()
    assert win.projects_empty_label.text() == "No projects yet."
    win.close()


def test_profile_window_save_never_changes_the_role(
    window, seeded, qapp
):
    """Saving the window cannot assign a role: the stored role
    is untouched by any save."""
    win = window.open_profile_window("lfm3-tool")
    win.display_edit.setText("LFM3 Renamed")
    assert win.save() is True
    assert seeded.get_profile("lfm3-tool")["role"] == "fast"
    win.close()


def test_profile_window_tag_change_rederives_on_save(
    window, seeded, seed_models, qapp
):
    """Change the tag in Details, save, and the role follows
    the new model — the window shows the new role and strengths.
    The profile starts with a derived (blank) role, so the role
    follows the tag; a deliberately set role would stay (see the
    model-level test)."""
    seed_models(["lfm3:1.7b", "qwen3-vl:2b-instruct"])
    seeded.create_profile("plain", ollama_tag="lfm3:1.7b")
    assert seeded.get_profile("plain")["role"] == ""
    win = window.open_profile_window("plain")
    win.details_section.set_expanded(True)
    win.tag_combo.setCurrentText("qwen3-vl:2b-instruct")
    qapp.processEvents()
    assert "seeing pictures" in win.strengths_label.text()
    assert win.save() is True
    assert seeded.get_profile("plain")["role"] == "vision"
    assert win.role_label.text() == "vision"
    win.close()


def test_tree_role_filter_works_off_derived_roles(
    window, seeded, qapp
):
    """The role filter reads derived roles: a profile created
    with no role at all filters by the role Stella worked out."""
    from tests.test_v22 import _visible_tops

    seeded.create_profile(
        "heretic", ollama_tag="maternion/minicpm5-heretic:2b"
    )
    window.refresh_tree()
    qapp.processEvents()
    assert _visible_tops(window) == ["heretic", "lfm3-tool"]
    window.tree_role_filter.setCurrentText("driver")
    qapp.processEvents()
    assert _visible_tops(window) == ["heretic"]
    window.tree_role_filter.setCurrentText("fast")
    qapp.processEvents()
    assert _visible_tops(window) == ["lfm3-tool"]
    window.tree_role_filter.setCurrentText("All roles")
    qapp.processEvents()
    assert _visible_tops(window) == ["heretic", "lfm3-tool"]


def test_governing_seat_warning_still_fires_from_details(
    window, seeded, qapp
):
    """Binding a stock base for a governing seat, from Details,
    still warns before training — the guard did not move."""
    from stella.model import governing_seat_warning

    win = window.open_profile_window("lfm3-tool")
    win.details_section.set_expanded(True)
    win.seat_combo.setCurrentText("driver")
    assert win.save() is True
    prof = seeded.get_profile("lfm3-tool")
    assert prof["governing_seat"] == "driver"
    warning = governing_seat_warning(prof)
    assert warning is not None
    assert "driver" in warning
    win.close()
