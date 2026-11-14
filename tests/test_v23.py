"""v0.23.0 tests — the final UI polish slice (T189, T190, T191,
T192, T193, T194). T189 is MOOTED by T16 (v0.11.0 deleted the
settings form, Method combo with it) — pinned, not built."""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_cli(home, *args):
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
    win.close()


def _visible_rows(howto):
    """The topic titles the search leaves visible."""
    return [
        howto.topic_list.item(row).text()
        for row in range(howto.topic_list.count())
        if not howto.topic_list.isRowHidden(row)
    ]


def _expected_matches(needle):
    """The topics whose title or body contains the needle — the
    filter's own rule, computed from the content."""
    from stella.howto import topic_text, topic_titles

    needle = needle.strip().lower()
    return [
        title
        for title in topic_titles()
        if not needle
        or needle in title.lower()
        or needle in (topic_text(title) or "").lower()
    ]


# -- T189: the dead "full" method — MOOTED by T16 -------------------


def test_no_full_method_anywhere_in_ui(window, qapp):
    """T189 (MOOTED): T16 deleted the settings form, Method combo
    with it — no combo in the main window, the profile window,
    or the project window offers "full", and no visible label is
    "full". ("0 means the full run" is the step cap's help text,
    not the method — it stays.)"""
    from PySide6.QtWidgets import QComboBox, QLabel

    prof = window.open_profile_window("lfm3-tool")
    proj = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    for parent in (window, prof, proj):
        for combo in parent.findChildren(QComboBox):
            items = [
                combo.itemText(i) for i in range(combo.count())
            ]
            assert "full" not in items, (
                parent.windowTitle(), combo.objectName(), items
            )
        for label in parent.findChildren(QLabel):
            assert label.text().strip() != "full"
    prof.close()
    proj.close()


def test_project_with_stored_full_method_opens_clean(window, qapp):
    """T189 (MOOTED): a project whose stored method is "full"
    still opens — the model enum keeps accepting it (pinned in
    test_model.py's test_valid_settings_still_save), and with no
    Method combo anywhere there is nothing to show blank."""
    window.store.create_project(
        "lfm3-tool", "old-full",
        settings={"method": "full"},
    )
    window.refresh_tree()
    proj = window.open_project_window("lfm3-tool", "old-full")
    qapp.processEvents()
    assert proj.isVisible()
    assert "old-full" in proj.windowTitle()
    data = window.store.get_project("lfm3-tool", "old-full")
    assert data["settings"]["method"] == "full"
    proj.close()


# -- T190: one tagline everywhere -----------------------------------


def test_one_tagline_everywhere(window):
    """T190: the window title and the header carry the same
    tagline — and the title still carries the version."""
    title = window.windowTitle()
    header = window.header_label.text()
    assert "fine-tune models on your PC" in title
    assert header == "STELLA: fine-tune models on your PC"
    assert title == f"STELLA 0.23.0: fine-tune models on your PC"
    # The old header tagline is gone.
    assert "shape a base model" not in header


# -- T191: status bar shows the session once ------------------------


def test_status_bar_does_not_repeat_session(window, qapp):
    """T191: picking a session no longer writes the slugs into
    the status bar — the session title carries the session, in
    display names."""
    window.set_session("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert "LFM3 Tool Seat" in window.session_title.text()
    message = window.statusBar().currentMessage()
    assert "lfm3-tool" not in message
    assert "tool-calls" not in message


def test_status_bar_does_not_repeat_profile_only(window, qapp):
    """T191: the profile-only session leaves the status bar alone
    too — no "Profile: <slug>, no project yet." repeat."""
    window.set_session("lfm3-tool", None)
    qapp.processEvents()
    assert "LFM3 Tool Seat" in window.session_title.text()
    assert "lfm3-tool" not in window.statusBar().currentMessage()


# -- T192: tooltips where they earn their place ---------------------


def test_terse_buttons_carry_tooltips(window):
    """T192: the buttons whose label needs one more word explain
    themselves on hover. (Tree-row tooltips are T78's, pinned by
    test_tree_rows_carry_full_text_tooltips.)"""
    assert window.go_btn.toolTip() == "Run the picked job."
    assert "5-step" in window.train_proof_btn.toolTip()
    assert "how long" in window.train_estimate_btn.toolTip()
    assert "newest" in window.checkpoint_prune_btn.toolTip()


def test_dialog_buttons_carry_tooltips(window, qapp):
    """T192: the terse buttons in the dedicated windows too —
    dependency Add/Remove, Mark ready, the chat plan Run, and
    the distill Start."""
    from stella.gui import ChatWindow, DistillDialog

    prof = window.open_profile_window("lfm3-tool")
    assert "package" in prof.dep_add_btn.toolTip()
    assert "selected" in prof.dep_remove_btn.toolTip()
    proj = window.open_project_window("lfm3-tool", "tool-calls")
    assert "ready to train" in proj.mark_ready_btn.toolTip()
    chat = ChatWindow(window)
    assert "plan" in chat.plan_run_btn.toolTip()
    dialog = DistillDialog(parent=window)
    assert "teacher" in dialog.start_btn.toolTip()
    prof.close()
    proj.close()
    chat.close()
    dialog.close()


# -- T193: How to Use search + empty-state link ---------------------


def test_howto_search_narrows_topics(window, qapp):
    """T193: typing in the search box narrows the topic list to
    the topics whose title or body matches."""
    howto = window.open_howto_window()
    qapp.processEvents()
    howto.search_box.setText("refusal")
    qapp.processEvents()
    assert _visible_rows(howto) == _expected_matches("refusal")
    assert "The refusal probe" in _visible_rows(howto)
    assert len(_visible_rows(howto)) < 13
    howto.close()


def test_howto_search_is_case_insensitive_and_clearable(window, qapp):
    """T193: the search ignores case, and clearing it shows all
    thirteen topics again."""
    howto = window.open_howto_window()
    qapp.processEvents()
    howto.search_box.setText("SLEEP")
    qapp.processEvents()
    assert _visible_rows(howto) == _expected_matches("sleep")
    howto.search_box.clear()
    qapp.processEvents()
    assert len(_visible_rows(howto)) == 13
    howto.close()


def test_howto_search_selects_nothing(window, qapp):
    """T193: filtering never picks a topic — nothing is selected
    by default, before or after a search."""
    howto = window.open_howto_window()
    qapp.processEvents()
    assert howto.topic_list.currentRow() == -1
    howto.search_box.setText("sleep")
    qapp.processEvents()
    assert howto.topic_list.currentRow() == -1
    assert howto.content.toPlainText() == (
        "Pick a topic on the left to read how it works."
    )
    howto.close()


def test_show_topic_opens_that_topic(window, qapp):
    """T193: show_topic lands the guide on the named topic."""
    howto = window.open_howto_window()
    qapp.processEvents()
    howto.show_topic("Getting started")
    qapp.processEvents()
    assert howto.topic_list.currentItem().text() == "Getting started"
    assert "fine-tunes small AI models" in howto.content.toPlainText()
    howto.close()


def test_empty_store_hint_links_to_getting_started(
    qapp, store, settings
):
    """T193: the empty store's hint links to Getting started —
    following the link opens the guide on that topic."""
    from stella.gui import MainWindow

    win = MainWindow(store=store, settings=settings)
    win.show()
    qapp.processEvents()
    assert win.tree_hint.isVisible()
    assert "Getting started" in win.tree_hint.text()
    assert 'href="getting-started"' in win.tree_hint.text()
    win.tree_hint.linkActivated.emit("getting-started")
    qapp.processEvents()
    assert win._howto_window is not None
    assert win._howto_window.isVisible()
    current = win._howto_window.topic_list.currentItem()
    assert current is not None
    assert current.text() == "Getting started"
    win.close()


def test_no_projects_hint_links_to_getting_started(
    window, seeded, qapp
):
    """T193: the profile-with-no-projects hint links to Getting
    started too."""
    seeded.create_profile("empty-profile")
    window.refresh_tree()
    window.set_session("empty-profile", None)
    qapp.processEvents()
    assert window.tree_hint.isVisible()
    assert 'href="getting-started"' in window.tree_hint.text()
    window.tree_hint.linkActivated.emit("getting-started")
    qapp.processEvents()
    current = window._howto_window.topic_list.currentItem()
    assert current is not None
    assert current.text() == "Getting started"


# -- T194: Chat window breathing room -------------------------------


def test_chat_help_label_has_room(window, qapp):
    """T194: the Chat window's help line renders at its full
    height at the default size — measured, not eyeballed. At
    700x520 it rendered 30px against a 45px need."""
    from stella.gui import ChatWindow

    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert chat.size().width() == 700
    assert chat.size().height() == 560
    label = chat.help_label
    need = label.heightForWidth(label.width())
    assert label.height() >= need, (label.height(), need)
    bottom_gap = chat.height() - (
        label.geometry().y() + label.height()
    )
    assert bottom_gap >= 10, bottom_gap
    chat.close()


# -- Version --------------------------------------------------------


def test_version_is_0_23_0(home):
    """The version is 0.23.0 everywhere the CLI reports it."""
    from stella.model import STELLA_VERSION

    assert STELLA_VERSION == "0.23.0"
    res = run_cli(home, "--version")
    assert res.returncode == 0
    assert "0.23.0" in res.stdout


def test_window_title_carries_version(window):
    """The window title carries STELLA 0.23.0."""
    assert "0.23.0" in window.windowTitle()


# -- Text rules: the AST sweep, pinned ------------------------------


def test_no_em_dash_in_source_literals():
    """U33, as an AST sweep over the product package: no em-dash
    in any non-docstring string literal, INCLUDING f-string
    parts (earlier sweeps missed those). Test files are out of
    scope — they contain the "—" literal in the assertions that
    forbid it."""
    for path in sorted((ROOT / "stella").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr) \
                        and isinstance(node.body[0].value, ast.Constant) \
                        and isinstance(node.body[0].value.value, str):
                    docstrings.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) \
                    and isinstance(node.value, str) \
                    and id(node) not in docstrings:
                assert "\u2014" not in node.value, (
                    path, node.lineno, node.value[:60]
                )
            elif isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.Constant) and isinstance(
                            part.value, str):
                        assert "\u2014" not in part.value, (
                            path, part.lineno, part.value[:60]
                        )
