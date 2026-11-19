"""STELLA v0.30.0 tests — the Ollama bridge wired into every
"no Hugging Face repo" wall (a real-PC defect Joshua hit on his
Mint PC: First steps "Get its weights" dead-ended with "set Base
ref" jargon). One candidate gets a Yes/No offer that stores the
repo and starts the download at once; several get a pick-one
dialog; an unknown tag gets plain words. The chat tools offer the
same bridge in text form with a confirm round-trip. The words
"Base ref" no longer appear in any user-visible string. A
mismatch guard also warns before a download when the stored repo
is valid but not the bridge's for the profile's model tag.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

import stella.chat_agent as chat_mod
import stella.gui as gui_mod
import stella.provision as prov
from stella.chat_agent import TOOL_HELP, ChatAgent, build_system_prompt
from stella.gui import BridgePickDialog
from stella.howto import topic_text, topic_titles
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
    this file stands alone. Teardown waits for any running job
    before closing, so a worker cannot leak into the next
    test."""
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
def agent(store, monkeypatch):
    monkeypatch.setattr(
        chat_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:2b"]
    )
    return ChatAgent(store, "lfm3:1.7b")


def _select_session(window):
    window.set_session("lfm3-tool", "tool-calls")


def _answer_yes(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )


def _answer_no(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )


def _mock_download(window, monkeypatch, started):
    """Stop the download manager starting a real subprocess."""
    monkeypatch.setattr(prov, "hub_available", lambda: True)
    monkeypatch.setattr(window.download_manager, "start", started.append)


def _wait_for_lookup(window, qapp, timeout_ms=10000):
    """Wait for the window's Hugging Face lookup worker (v0.33.0)
    to finish and its completion slot to run."""
    waited = 0
    while window._hub_lookup_in_flight():
        QTest.qWait(50)
        waited += 50
        assert waited < timeout_ms, "lookup did not finish in time"
    qapp.processEvents()


def _click_box_button(monkeypatch, prefix, seen):
    """Fake QMessageBox.exec: click the first button whose text
    starts with prefix, recording the box text in seen."""
    def fake_exec(self):
        seen.append(self.text())
        for btn in self.buttons():
            if btn.text().startswith(prefix):
                btn.click()
                return QDialog.Accepted
        return QDialog.Rejected
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)


# -- Version --------------------------------------------------------


# NOTE: the version tests moved to test_v33.py (test_version_is_0_33_0,
# test_window_title_carries_version) — the version is 0.33.0 now.


# -- The bridge offer in the download flow --------------------------


def test_start_download_yes_sets_repo_and_starts(
    window, monkeypatch
):
    """One candidate, Yes: the repo is stored on the profile and
    the download starts at once — no second button press."""
    _answer_yes(monkeypatch)
    started = []
    _mock_download(window, monkeypatch, started)
    _select_session(window)
    window.start_download()
    assert window.store.get_profile("lfm3-tool")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )
    assert started == ["LiquidAI/LFM3-1.7B"]


def test_start_download_multi_candidate_pick(window, monkeypatch):
    """Several candidates: the pick-one dialog's choice is stored
    and the download starts with it. The tag qwen3.5:2b-q4_K_M
    strips to the base qwen3.5, matching both the 2B and 4B
    repos."""
    window.store.create_profile(
        "qwen-multi", ollama_tag="qwen3.5:2b-q4_K_M", role="fast"
    )
    seen = {}

    class FakePick:
        def __init__(self, candidates, parent=None):
            seen["candidates"] = [c["repo"] for c in candidates]
            self.chosen = "Qwen/Qwen3.5-4B"

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(gui_mod, "BridgePickDialog", FakePick)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("qwen-multi")
    assert seen["candidates"] == ["Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-4B"]
    assert window.store.get_profile("qwen-multi")["base_ref"] == (
        "Qwen/Qwen3.5-4B"
    )
    assert started == ["Qwen/Qwen3.5-4B"]


def test_start_download_unknown_tag_plain_message(
    window, qapp, monkeypatch
):
    """An unknown tag (bonsai-2 has no verifiable Hub repo by
    design): v0.33.0 looks it up on Hugging Face first — the
    stubbed lookup finds nothing, so the plain-words message
    lands with no jargon, nothing stored, nothing downloaded."""
    window.store.create_profile(
        "bonsai", ollama_tag="bonsai-2:4b", role="fast"
    )
    monkeypatch.setattr(
        gui_mod, "lookup_hf_repos",
        lambda tag, **k: {"state": "none", "candidates": []},
    )
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("bonsai")
    _wait_for_lookup(window, qapp)
    assert warnings
    assert "doesn't know where this model's training files live" in (
        warnings[0]
    )
    assert "Base ref" not in warnings[0]
    assert started == []
    assert window.store.get_profile("bonsai")["base_ref"] == "bonsai-2:4b"


def test_bridge_pick_dialog_click_picks_repo(qapp):
    """The pick dialog: one tap on a candidate picks it, with no
    pre-selection (U6)."""
    dialog = BridgePickDialog(
        [
            {"repo": "Qwen/Qwen3.5-2B", "source": "Qwen's own repo"},
            {"repo": "Qwen/Qwen3.5-4B", "source": "Qwen's own repo"},
        ]
    )
    dialog.show()
    qapp.processEvents()
    assert dialog.chosen is None
    assert len(dialog._buttons) == 2
    QTest.mouseClick(dialog._buttons[1], Qt.LeftButton)
    qapp.processEvents()
    assert dialog.chosen == "Qwen/Qwen3.5-4B"
    assert dialog.result() == QDialog.Accepted
    dialog.close()


def test_bridge_pick_dialog_cancel_picks_nothing(qapp):
    """Cancel picks nothing."""
    dialog = BridgePickDialog(
        [
            {"repo": "Qwen/Qwen3.5-2B", "source": "Qwen's own repo"},
            {"repo": "Qwen/Qwen3.5-4B", "source": "Qwen's own repo"},
        ]
    )
    dialog.show()
    qapp.processEvents()
    cancel = [
        b for b in dialog.findChildren(QPushButton)
        if b.text() == "Cancel"
    ]
    assert len(cancel) == 1
    QTest.mouseClick(cancel[0], Qt.LeftButton)
    qapp.processEvents()
    assert dialog.chosen is None
    assert dialog.result() == QDialog.Rejected
    dialog.close()


# -- The bridge offer in the train pre-check ------------------------


def test_weights_offer_yes_falls_through_to_download_question(
    window, monkeypatch
):
    """Answering Yes to the bridge offer falls through to the
    existing "Download the model first?" question — the download
    logic is not duplicated."""
    _answer_yes(monkeypatch)
    started = []
    monkeypatch.setattr(
        window, "start_download", lambda profile=None: started.append(profile)
    )
    _select_session(window)
    assert window._weights_offer("lfm3-tool") is False
    assert window.store.get_profile("lfm3-tool")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )
    assert started == ["lfm3-tool"]


def test_weights_offer_no_stops(window, monkeypatch):
    """Answering No stops the train pre-check: nothing stored, no
    download question, no training."""
    _answer_no(monkeypatch)
    started = []
    monkeypatch.setattr(
        window, "start_download", lambda profile=None: started.append(profile)
    )
    _select_session(window)
    assert window._weights_offer("lfm3-tool") is False
    assert window.store.get_profile("lfm3-tool")["base_ref"] == "lfm3:1.7b"
    assert started == []


# -- The fix button -------------------------------------------------


def test_fix_button_yes_starts_download(window, qapp, monkeypatch):
    """The "Set the model source..." button offers the bridge repo
    first; Yes stores it and starts the download at once."""
    _answer_yes(monkeypatch)
    started = []
    _mock_download(window, monkeypatch, started)
    _select_session(window)
    window._checklist_dismiss()
    assert window.download_fix_btn.isVisible()
    window.download_fix_btn.click()
    qapp.processEvents()
    assert window.store.get_profile("lfm3-tool")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )
    assert started == ["LiquidAI/LFM3-1.7B"]


# -- The profile window label + the "Base ref" sweep ----------------


def test_profile_window_label_is_hugging_face_repo(window):
    """The profile window's field is labelled "Hugging Face repo",
    not "Base ref" — with the plain-words help line under it."""
    win = window.open_profile_window("lfm3-tool")
    labels = [w.text() for w in win.findChildren(QLabel)]
    assert "Hugging Face repo" in labels
    assert "Base ref" not in labels
    assert any(
        "Where training loads the base model from" in text
        for text in labels
    )
    win.close()


def _visible_texts(widget):
    """Every user-visible string on a widget tree: labels, button
    text, line-edit text + placeholder, combo items, titles."""
    texts = []
    for child in widget.findChildren(QWidget):
        if isinstance(child, QLabel):
            texts.append(child.text())
        elif isinstance(child, QPushButton):
            texts.append(child.text())
        elif isinstance(child, QLineEdit):
            texts.append(child.text())
            texts.append(child.placeholderText())
        elif isinstance(child, QComboBox):
            texts.append(child.currentText())
            for i in range(child.count()):
                texts.append(child.itemText(i))
        texts.append(child.windowTitle())
    return texts


def test_no_base_ref_in_visible_strings(window, agent, store, seeded):
    """The words "Base ref" appear in no user-visible string: not
    in the main or profile windows, not in any How to Use topic,
    not in the chat's tool help or system prompt, and not in the
    chat tools' no-repo answers. (Code identifiers and developer
    docs may keep it — this sweep is the strings the user sees.)"""
    _select_session(window)
    window._checklist_dismiss()
    for text in _visible_texts(window):
        assert "Base ref" not in text, text
    prof = window.open_profile_window("lfm3-tool")
    for text in _visible_texts(prof):
        assert "Base ref" not in text, text
    prof.close()
    for title in topic_titles():
        assert "Base ref" not in topic_text(title), title
    for help_text in TOOL_HELP.values():
        assert "Base ref" not in help_text, help_text
    prompt = build_system_prompt(
        profile="lfm3-tool", project="tool-calls",
        installed_models=["lfm3:1.7b"],
    )
    assert "Base ref" not in prompt
    result = agent.call_tool(
        "download_weights", {"profile": "lfm3-tool"}
    )
    assert "Base ref" not in result


# -- The bridge offer in the chat tools -----------------------------


def test_chat_download_weights_confirm_sets_and_downloads(
    agent, store, seeded, monkeypatch
):
    """Confirm round-trip: the first call names the candidate and
    asks; the call with confirm + repo stores it and the download
    runs."""
    first = agent.call_tool(
        "download_weights", {"profile": "lfm3-tool"}
    )
    assert "LiquidAI/LFM3-1.7B" in first
    assert "Liquid AI's own repo for this model" in first
    assert store.get_profile("lfm3-tool")["base_ref"] == "lfm3:1.7b"
    monkeypatch.setattr(chat_mod, "hub_available", lambda: True)
    monkeypatch.setattr(chat_mod, "run_download", lambda repo, **k: 0)
    second = agent.call_tool(
        "download_weights",
        {
            "profile": "lfm3-tool",
            "confirm": True,
            "repo": "LiquidAI/LFM3-1.7B",
        },
    )
    assert store.get_profile("lfm3-tool")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )
    assert "downloaded and ready" in second


def test_chat_download_weights_confirm_wrong_repo_refused(
    agent, store, seeded
):
    """A confirm naming a repo the bridge did not suggest is
    refused — a made-up name is never silently stored."""
    result = agent.call_tool(
        "download_weights",
        {
            "profile": "lfm3-tool",
            "confirm": True,
            "repo": "SomeoneElse/NotACandidate",
        },
    )
    assert "not one of the repos I suggested" in result
    assert store.get_profile("lfm3-tool")["base_ref"] == "lfm3:1.7b"


def test_chat_download_weights_multi_candidates(
    agent, store, seeded
):
    """Several candidates: the tool lists them all and asks which
    one, instead of guessing."""
    store.create_profile(
        "qwen-multi", ollama_tag="qwen3.5:2b-q4_K_M", role="fast"
    )
    result = agent.call_tool(
        "download_weights", {"profile": "qwen-multi"}
    )
    assert "Qwen/Qwen3.5-2B" in result
    assert "Qwen/Qwen3.5-4B" in result
    assert "Tell me which one" in result
    assert store.get_profile("qwen-multi")["base_ref"] == (
        "qwen3.5:2b-q4_K_M"
    )


def test_chat_download_weights_unknown_tag(
    agent, store, seeded, monkeypatch
):
    """An unknown tag: v0.33.0 looks it up on Hugging Face first —
    the stubbed lookup finds nothing, so the honest plain-words
    answer lands, with no jargon and no offered repo."""
    monkeypatch.setattr(
        chat_mod, "lookup_hf_repos",
        lambda tag, **k: {"state": "none", "candidates": []},
    )
    store.create_profile(
        "bonsai", ollama_tag="bonsai-2:4b", role="fast"
    )
    result = agent.call_tool(
        "download_weights", {"profile": "bonsai"}
    )
    assert "doesn't know where this model's training files live" in (
        result
    )
    assert "Base ref" not in result


def test_chat_start_training_no_repo_suggests(
    agent, store, seeded, monkeypatch
):
    """start_training on a no-repo profile names the candidate and
    asks, instead of telling the user to set a field."""
    monkeypatch.setattr(chat_mod, "training_deps_missing", lambda: [])
    result = agent.call_tool(
        "start_training",
        {"profile": "lfm3-tool", "project": "tool-calls"},
    )
    assert "LiquidAI/LFM3-1.7B" in result
    assert "Base ref" not in result
    assert store.get_profile("lfm3-tool")["base_ref"] == "lfm3:1.7b"


def test_chat_start_training_confirm_sets_then_needs_download(
    agent, store, seeded, monkeypatch
):
    """Confirming the repo in start_training stores it; training
    still needs the weights downloaded first, and says so."""
    monkeypatch.setattr(chat_mod, "training_deps_missing", lambda: [])
    result = agent.call_tool(
        "start_training",
        {
            "profile": "lfm3-tool",
            "project": "tool-calls",
            "confirm": True,
            "repo": "LiquidAI/LFM3-1.7B",
        },
    )
    assert store.get_profile("lfm3-tool")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )
    assert "not downloaded yet" in result


# -- The mismatch guard ---------------------------------------------


def _guard_profile(window, slug, tag, repo):
    window.store.create_profile(
        slug, display_name=slug, base_ref=repo, ollama_tag=tag
    )


def test_guard_mismatch_switch_sets_repo_and_downloads(
    window, monkeypatch
):
    """A stored repo that is valid but not the bridge's for the tag
    warns, names both repos, and the switch stores the bridge repo
    and downloads it."""
    _guard_profile(
        window, "qwen-wrong", "qwen3.5:4b", "LiquidAI/LFM3-1.7B"
    )
    seen = []
    _click_box_button(monkeypatch, "Use ", seen)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("qwen-wrong")
    assert len(seen) == 1
    assert "LiquidAI/LFM3-1.7B" in seen[0]
    assert "Qwen/Qwen3.5-4B" in seen[0]
    assert window.store.get_profile("qwen-wrong")["base_ref"] == (
        "Qwen/Qwen3.5-4B"
    )
    assert started == ["Qwen/Qwen3.5-4B"]


def test_guard_mismatch_keep_proceeds_as_is(window, monkeypatch):
    """Keep: the stored repo stands and the download proceeds with
    it. The guard warns, never blocks — a different repo can be
    legitimate, e.g. an abliterated repo instead of its base."""
    _guard_profile(
        window, "qwen-wrong", "qwen3.5:4b", "LiquidAI/LFM3-1.7B"
    )
    seen = []
    _click_box_button(monkeypatch, "Keep ", seen)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("qwen-wrong")
    assert len(seen) == 1
    assert window.store.get_profile("qwen-wrong")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )
    assert started == ["LiquidAI/LFM3-1.7B"]


def test_guard_dismissed_warning_downloads_nothing(
    window, monkeypatch
):
    """Dismissing the warning (close, Esc) downloads nothing and
    changes nothing."""
    _guard_profile(
        window, "qwen-wrong", "qwen3.5:4b", "LiquidAI/LFM3-1.7B"
    )
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QDialog.Rejected
    )
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("qwen-wrong")
    assert started == []
    assert window.store.get_profile("qwen-wrong")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )


def test_guard_matching_repo_downloads_with_no_warning(
    window, monkeypatch
):
    """The stored repo IS the bridge's for the tag: no dialog at
    all, the download just starts."""
    _guard_profile(
        window, "lfm3-ok", "lfm3:1.7b", "LiquidAI/LFM3-1.7B"
    )

    def _no_dialog(self):
        raise AssertionError("no warning dialog should appear")

    monkeypatch.setattr(QMessageBox, "exec", _no_dialog)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("lfm3-ok")
    assert started == ["LiquidAI/LFM3-1.7B"]


def test_guard_unknown_tag_downloads_with_no_warning(
    window, monkeypatch
):
    """A tag the bridge does not know (the reviewer is not in
    the map — unverified — and must not be added unguessed):
    no warning fires, the download proceeds as today. Granite
    used to be this test's example; it is in the map now
    (v0.32.0, verified), so the guard test for it lives in
    test_v32.py."""
    _guard_profile(
        window, "reviewer", "dolphinlabs/qwen3.5-uncensored:latest",
        "LiquidAI/LFM3-1.7B",
    )

    def _no_dialog(self):
        raise AssertionError("no warning dialog should appear")

    monkeypatch.setattr(QMessageBox, "exec", _no_dialog)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("reviewer")
    assert started == ["LiquidAI/LFM3-1.7B"]


def test_guard_multi_candidate_prefers_tag_size(
    window, monkeypatch
):
    """A quant-suffixed tag matches several candidates; the guard
    offers the one carrying the tag's size, not the first in the
    list (qwen3.5:4b-q4_K_M is a 4B model)."""
    _guard_profile(
        window, "qwen-quant", "qwen3.5:4b-q4_K_M",
        "LiquidAI/LFM3-1.7B",
    )
    seen = []
    _click_box_button(monkeypatch, "Use ", seen)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("qwen-quant")
    assert len(seen) == 1
    assert "Qwen/Qwen3.5-4B" in seen[0]
    assert "Qwen/Qwen3.5-2B" not in seen[0]
    assert window.store.get_profile("qwen-quant")["base_ref"] == (
        "Qwen/Qwen3.5-4B"
    )
    assert started == ["Qwen/Qwen3.5-4B"]
