"""GUI tests — offscreen. Drive the real window, check the menu,
the tree, the session, and the dedicated windows."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QWidget,
)


@pytest.fixture()
def window(qapp, seeded, settings):
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    # The startup model-list refresh (T43) settles before the test
    # body runs, so the cache holds the settled list and a test
    # that seeds the cache cannot race it. Fast when Ollama is
    # down (the fetch fails at once); when Ollama is up, the
    # refresh lands with the real list — either way the worker
    # has finished before the test body runs (R17).
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    # R74: teardown waits for every worker before closing — a bare
    # win.close() is ignored while a job runs (closeEvent, T36),
    # so a forgotten _wait_for_job leaked a worker into the next
    # test. The wait fails loudly when a job is still running
    # after a bounded wait, so the leak fails in its own test.
    _wait_for_all_workers(win, qapp)
    win.close()


def _select_session(window):
    """Pick the seeded project in the tree (sets the session)."""
    window.set_session("lfm3-tool", "tool-calls")


def _wait_for_job(window, qapp, timeout_ms=20000):
    """Wait until the window's job-card worker finishes (T106:
    export and import run off the GUI thread now, so a test that
    asserts on the store after calling them must wait for the job
    first). Processes events while waiting, so the finished slot
    runs. A job that never started returns at once."""
    from PySide6.QtTest import QTest

    waited = 0
    while True:
        worker = window._job_worker
        if worker is None or not worker.isRunning():
            break
        QTest.qWait(50)
        waited += 50
        assert waited < timeout_ms, "job did not finish in time"
    qapp.processEvents()


def _wait_for_all_workers(window, qapp, timeout_ms=20000):
    """Wait until every worker the window owns has finished (R74):
    the job-card worker, the training worker, and the sleep
    worker. Processes events while waiting, so the finished slots
    run — a bare worker.wait() without event processing can
    deadlock on slots that need the GUI thread. A job that never
    started returns at once. Fails loudly when a job is still
    running after a bounded wait, so a forgotten wait fails fast
    in its own test instead of haunting the next one."""
    from PySide6.QtTest import QTest

    waited = 0
    while True:
        running = [
            worker
            for worker in (
                getattr(window, "_job_worker", None),
                getattr(window, "_train_worker", None),
                getattr(window, "_sleep_worker", None),
            )
            if worker is not None and worker.isRunning()
        ]
        if not running:
            break
        QTest.qWait(50)
        waited += 50
        assert waited < timeout_ms, "job did not finish in time"
    qapp.processEvents()


def _visible_texts(window):
    """Every user-visible string in the main window and every open
    dedicated window: widget text, tooltips, placeholders, window
    titles, menu actions, tree rows, text-browser content."""
    texts = []
    for widget in window.findChildren(QWidget):
        if isinstance(widget, (QLabel, QPushButton, QCheckBox)):
            texts.append(widget.text())
        if isinstance(widget, QLineEdit):
            texts.append(widget.placeholderText())
        if isinstance(widget, QTextBrowser):
            texts.append(widget.toPlainText())
        texts.append(widget.toolTip())
        if widget.isWindow():
            texts.append(widget.windowTitle())
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is None:
            continue
        texts.append(menu.title())
        for sub in menu.actions():
            texts.append(sub.text())
    tree = window.tree
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        texts.append(top.text(0))
        for j in range(top.childCount()):
            texts.append(top.child(j).text(0))
    return texts


# -- window shape ---------------------------------------------------


def test_window_opens_with_menu_tree_and_session(window):
    assert window.isVisible()
    assert window.menuBar() is not None
    menus = [
        a.menu() for a in window.menuBar().actions() if a.menu() is not None
    ]
    assert [m.title() for m in menus] == ["File", "View", "Help"]
    assert window.tree.topLevelItemCount() == 1
    assert window.tree.topLevelItem(0).childCount() == 1
    assert window.session_title.text() == "No training session yet."
    assert window.activity_text.text() == "Idle"


def test_no_selection_by_default(window):
    # U6: select nothing by default, ever. First run: no session.
    assert window.tree.currentItem() is None
    assert window._current_profile is None
    assert window._current_project is None


def test_tree_shows_role_and_tag(window):
    text = window.tree.topLevelItem(0).text(0)
    assert "[fast]" in text
    assert "lfm3:1.7b" in text
    child = window.tree.topLevelItem(0).child(0).text(0)
    assert "tool-calls" in child
    # The tree label is the project name plus its status (T53)
    # and its dataset file (T164); the dead metamorph-mode
    # suffix is still gone.
    assert child == "tool-calls (draft) [forge-traces.jsonl]"


def test_empty_store_window(qapp, store, settings):
    from stella.gui import MainWindow

    win = MainWindow(store=store, settings=settings)
    win.show()
    qapp.processEvents()
    assert win.tree.topLevelItemCount() == 0
    assert win.session_title.text() == "No training session yet."
    win.close()


def test_window_grabs_a_frame(window, qapp, tmp_path):
    # The window must render something real (not a blank crash).
    pixmap = window.grab()
    assert not pixmap.isNull()
    assert pixmap.width() >= 900
    path = tmp_path / "stella-window.png"
    assert pixmap.save(str(path))
    assert path.stat().st_size > 1000


def test_status_bar_is_the_only_status(window):
    # Regression: an earlier build showed the status text twice — once
    # in a QLabel in the bottom bar and once in the status bar.
    assert not hasattr(window, "status_label")
    window._say("Profile: lfm3-tool, project: tool-calls.")
    assert window.statusBar().currentMessage() == (
        "Profile: lfm3-tool, project: tool-calls."
    )


# -- menu -----------------------------------------------------------


def test_menu_bar_has_expected_menus_and_actions(window):
    """T19: a real menu bar, File / View / Help, actions in order."""
    bar = window.menuBar()
    menus = [a.menu() for a in bar.actions() if a.menu() is not None]
    assert [m.title() for m in menus] == ["File", "View", "Help"]
    actions = {
        m.title(): [a.text() for a in m.actions() if not a.isSeparator()]
        for m in menus
    }
    assert actions == {
        "File": [
            "New profile...",
            "New project...",
            "Export project...",
            "Export project as single file...",  # T171
            "Export profile...",  # T86
            "Export profile as single file...",  # T171
            "Export recipe...",  # T170
            "Export adapter...",  # T173
            "Import package...",
            "Import single-file package...",  # T171
            "Check package...",  # T105
            "Run the picked job",
            "Settings...",
            "Trash...",  # T23: deleted things wait here, and are
            # deleted forever here.
        ],
        "View": ["Profiles", "Projects"],
        "Help": ["How to Use Stella...", "Chat..."],
    }
    file_menu = menus[0]
    separators = [a for a in file_menu.actions() if a.isSeparator()]
    assert len(separators) == 1
    # The old Menu button is gone (T19).
    assert not hasattr(window, "menu_button")
    assert not hasattr(window, "menu")


def test_menu_new_profile_opens_dialog(window, qapp):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog

    def close_dialog():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg.reject()

    QTimer.singleShot(100, close_dialog)
    window._menu_action_new_profile.trigger()
    qapp.processEvents()
    assert window._profile_dialog is not None
    assert window._profile_dialog.result() == QDialog.Rejected


def test_menu_settings_opens_settings_window(window):
    window._menu_action_settings.trigger()
    assert window._settings_window is not None
    assert window._settings_window.isVisible()
    assert "Settings" in window._settings_window.windowTitle()


def test_menu_howto_opens_howto_window(window):
    window._menu_action_howto.trigger()
    assert window._howto_window is not None
    assert window._howto_window.isVisible()
    assert window._howto_window.topic_list.count() == 17


# -- session --------------------------------------------------------


def test_click_project_sets_session(window, settings):
    child = window.tree.topLevelItem(0).child(0)
    window.tree.setCurrentItem(child)
    assert window._current_profile == "lfm3-tool"
    assert window._current_project == "tool-calls"
    assert "LFM3 Tool Seat" in window.session_title.text()
    assert "tool-calls" in window.session_title.text()
    assert "forge-traces.jsonl" in window.session_summary.text()
    # T191: the status bar no longer repeats the session in slug
    # form — the session title above carries it, in display names.
    assert "lfm3-tool" not in window.statusBar().currentMessage()
    assert "tool-calls" not in window.statusBar().currentMessage()
    assert settings.value("session/profile") == "lfm3-tool"
    assert settings.value("session/project") == "tool-calls"
    # No job is picked yet, so Go waits (T15); picking one arms it.
    assert not window.go_btn.isEnabled()
    window.job_buttons["train"].click()
    assert window.go_btn.isEnabled()


def test_session_restores_across_restarts(qapp, seeded, settings):
    from PySide6.QtCore import Qt

    from stella.gui import MainWindow

    first = MainWindow(store=seeded, settings=settings)
    first.show()
    qapp.processEvents()
    first.set_session("lfm3-tool", "tool-calls")
    first.close()
    settings.sync()
    second = MainWindow(store=seeded, settings=settings)
    second.show()
    qapp.processEvents()
    assert second._current_profile == "lfm3-tool"
    assert second._current_project == "tool-calls"
    assert second.tree.currentItem() is not None
    assert second.tree.currentItem().data(0, Qt.UserRole) == (
        "lfm3-tool",
        "tool-calls",
    )
    second.close()


def test_resume_disabled_with_no_checkpoints(window, seeded):
    # R75: on a never-trained draft, Resume is greyed out — there
    # is nothing to resume, and clicking it used to start a
    # worker the engine then refused.
    _select_session(window)
    assert window.train_resume_btn.isEnabled() is False


def test_resume_enabled_with_a_checkpoint(window, seeded):
    # R75: with a checkpoint on disk, Resume is on.
    _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    assert window.train_resume_btn.isEnabled() is True


def test_pause_offers_resume(window, seeded, qapp):
    # R75: after a pause, the status bar offers resume — and
    # Resume is enabled at that moment.
    _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    seeded.update_project("lfm3-tool", "tool-calls", status="paused")
    window._running_job_key = ("lfm3-tool", "tool-calls")
    window._on_train_finished(True, "Trained 5 steps. Final loss 1.5000.")
    qapp.processEvents()
    assert "Paused. Press Resume to carry on." in (
        window.statusBar().currentMessage()
    )
    assert window.train_resume_btn.isEnabled() is True


def test_pause_log_line_offers_resume(qapp, seeded):
    # R75: the pause log line names the way back.
    from stella.gui import TrainWorker

    lines = []
    worker = TrainWorker(seeded, "lfm3-tool", "tool-calls")
    worker.log.connect(lines.append)
    worker._event({"type": "paused", "step": 5})
    qapp.processEvents()
    assert lines == ["Paused at step 5. Press Resume when you are ready."]


def test_failed_run_with_checkpoints_offers_resume(window, seeded, qapp):
    # R75: a run that failed with checkpoints saved is offered
    # its resume too; a failed run with no checkpoint gets no
    # offer (there is nothing to resume from).
    _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    seeded.update_project("lfm3-tool", "tool-calls", status="failed")
    window._running_job_key = ("lfm3-tool", "tool-calls")
    window._on_train_finished(False, "Training failed: out of memory.")
    qapp.processEvents()
    assert "Press Resume to carry on from the last checkpoint." in (
        window.statusBar().currentMessage()
    )
    assert window.train_resume_btn.isEnabled() is True


def test_finished_run_gets_no_resume_offer(window, seeded, qapp):
    # R75: a run that finished cleanly gets no resume offer.
    _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    seeded.update_project("lfm3-tool", "tool-calls", status="done")
    window._running_job_key = ("lfm3-tool", "tool-calls")
    window._on_train_finished(True, "Trained 5 steps. Final loss 1.5000.")
    qapp.processEvents()
    assert window.statusBar().currentMessage() == (
        "Trained 5 steps. Final loss 1.5000."
    )


def test_train_buttons_disabled_without_session(window):
    assert not window.go_btn.isEnabled()
    assert not window.train_resume_btn.isEnabled()
    assert not window.train_export_gguf_btn.isEnabled()
    assert not window.train_probe_btn.isEnabled()
    assert not window.download_btn.isEnabled()
    assert not window.train_pick_dataset_btn.isEnabled()
    assert not window.train_sample_btn.isEnabled()


def test_tree_expansion_survives_refresh(window):
    # U28: a refresh must not collapse the tree or lose the selection.
    top = window.tree.topLevelItem(0)
    top.setExpanded(True)
    _select_session(window)
    window.refresh_tree()
    assert window.tree.topLevelItem(0).isExpanded()
    assert window.tree.currentItem() is not None
    assert window._current_project == "tool-calls"


def test_geometry_remembered(qapp, seeded, settings):
    """Geometry is remembered between runs (U5). The offscreen
    screen is 800x800, and restoreGeometry clamps a restored width
    to fit it (proven by probe: a plain QMainWindow round-trip
    gives 798 wide with no minimum, 900 with our 900 minimum), so
    the height assertion is the exact round-trip and the width
    assertion is the clamped minimum. On his real 1366x768 screen
    the saved width fits and restores exactly."""
    from stella.gui import MainWindow

    first = MainWindow(store=seeded, settings=settings)
    first.show()
    qapp.processEvents()
    first.resize(1000, 600)
    qapp.processEvents()
    first.close()
    settings.sync()
    second = MainWindow(store=seeded, settings=settings)
    second.show()
    qapp.processEvents()
    assert second.height() == 600
    assert second.width() == 900  # clamped to the minimum offscreen
    second.close()


# -- dedicated windows ----------------------------------------------


def test_profile_window_save_writes_through(window, seeded):
    win = window.open_profile_window("lfm3-tool")
    assert win.display_edit.text() == "LFM3 Tool Seat"
    assert win.role_combo.currentText() == "fast"
    assert win.tag_combo.currentText() == "lfm3:1.7b"
    win.role_combo.setCurrentText("reviewer")
    win.save()
    assert seeded.get_profile("lfm3-tool")["role"] == "reviewer"
    assert "reviewer" in window.tree.topLevelItem(0).text(0)
    win.close()


def test_profile_window_has_help_lines_and_no_processor(window):
    win = window.open_profile_window("lfm3-tool")
    assert not hasattr(win, "prof_processor")
    assert not hasattr(win, "processor_edit")
    labels = [w.text() for w in win.findChildren(QLabel)]
    assert any("Just a label for the list" in t for t in labels)
    assert any("Only matters if Code Forge" in t for t in labels)
    assert any("The model as Ollama knows it" in t for t in labels)
    assert any("Where training loads the base model" in t for t in labels)
    win.close()


def test_profile_window_has_no_download_row(window):
    """T79: one honest download row, in the main window. The
    Profile window's duplicate is gone; the seeded profile has no
    base_ref, so the main Download button is disabled and the fix
    button shows instead."""
    win = window.open_profile_window("lfm3-tool")
    for attr in (
        "download_btn",
        "download_cancel_btn",
        "download_progress",
        "download_status",
        "download_help",
    ):
        assert not hasattr(win, attr), attr
    win.close()
    window.set_session("lfm3-tool", "tool-calls")
    window._checklist_dismiss()
    assert window.download_btn.isEnabled() is False
    assert window.download_fix_btn.isVisibleTo(window) is True
    assert "No Hugging Face repo set." in window.download_status_label.text()


def test_project_window_save_writes_through(window, seeded):
    _select_session(window)
    win = window.open_project_window("lfm3-tool", "tool-calls")
    assert win.display_edit.text() == "tool-calls"
    assert win.dataset_edit.text() == "forge-traces.jsonl"
    # No metamorph control: it did nothing, so it gets no control.
    assert not hasattr(win, "metamorph_combo")
    # No settings controls (T16): the backend picks them.
    for attr in (
        "method_combo",
        "rank_spin",
        "lr_edit",
        "epochs_spin",
        "batch_spin",
        "seq_spin",
    ):
        assert not hasattr(win, attr), attr
    stored_settings = dict(
        seeded.get_project("lfm3-tool", "tool-calls")["settings"]
    )
    win.display_edit.setText("Tool Calls v2")
    win.dataset_edit.setText("other-data.jsonl")
    win.notes_edit.setPlainText("renamed after first look")
    assert win.save() is True
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["display_name"] == "Tool Calls v2"
    assert data["dataset_ref"] == "other-data.jsonl"
    # Saving leaves the stored settings untouched (T16).
    assert data["settings"] == stored_settings
    # Saving leaves the stored metamorph mode untouched.
    assert data["metamorph"]["mode"] == "both"
    assert seeded.read_notes("lfm3-tool", "tool-calls") == (
        "renamed after first look"
    )
    win.close()


def test_project_window_has_no_settings_controls(window):
    """T16: the settings form is gone. Nothing in the window reads
    or writes rank, learning rate, epochs, batch size, or seq len."""
    _select_session(window)
    win = window.open_project_window("lfm3-tool", "tool-calls")
    for attr in (
        "method_combo",
        "rank_spin",
        "lr_edit",
        "epochs_spin",
        "batch_spin",
        "seq_spin",
    ):
        assert not hasattr(win, attr), attr
    texts = " ".join(
        [w.text() for w in win.findChildren(QLabel)]
        + [w.text() for w in win.findChildren(QPushButton)]
    ).lower()
    for word in ("rank", "learning rate", "epochs", "batch size", "seq len"):
        assert word not in texts, word
    win.close()


def test_settings_window_shows_home_and_defaults(window, seeded):
    win = window.open_settings_window()
    assert win.home_label.text() == str(seeded.home)
    assert "localhost" in win.ollama_host.text() or "127.0.0.1" in win.ollama_host.text()
    assert "Status:" in win.ollama_status.text()
    assert win.debug_btn is not None
    assert win.debug_btn.text() == "Write debug report"
    # No Training defaults block (T16): nothing in Settings names
    # a training setting.
    texts = " ".join(w.text() for w in win.findChildren(QLabel))
    assert "Training defaults" not in texts
    assert "LoRA rank" not in texts
    assert "Learning rate" not in texts
    win.close()


def test_howto_window_lists_topics_and_shows_content(window):
    win = window.open_howto_window()
    assert win.topic_list.count() == 17
    assert win.topic_list.item(0).text() == "Getting started"
    win.topic_list.setCurrentRow(0)
    assert "Stella" in win.content.toPlainText()
    # R70: Training moved to row 6 (Bridge and Checkpoints were
    # added before it).
    win.topic_list.setCurrentRow(6)
    assert win.topic_list.currentItem().text() == "Training"
    assert "hours" in win.content.toPlainText()
    win.close()


# -- deletes --------------------------------------------------------


def test_delete_confirm_defaults_to_no(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    seen = []

    def fake_exec(self):
        seen.append(self)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    window.delete_project()
    assert len(seen) == 1
    assert seen[0].defaultButton() is seen[0].button(QMessageBox.No)
    assert seen[0].escapeButton() is seen[0].button(QMessageBox.No)
    # And nothing was deleted.
    assert window.store.get_project("lfm3-tool", "tool-calls")


def test_delete_project_moves_to_trash(window, monkeypatch):
    # T23: deleting a project moves it to the trash, dated, with
    # its contents intact — the list is empty but nothing is gone.
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.Yes
    )
    window.delete_project()
    assert window.store.list_projects("lfm3-tool") == []
    assert window._current_project is None
    assert window._current_profile == "lfm3-tool"
    assert window.tree.topLevelItem(0).childCount() == 0
    entries = window.store.list_trash()
    assert len(entries) == 1
    assert entries[0]["kind"] == "project"
    assert entries[0]["project"] == "tool-calls"
    assert "trash" in window.statusBar().currentMessage()


def test_delete_profile_moves_to_trash(window, monkeypatch):
    # T23: deleting a profile trashes the profile and its projects.
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.Yes
    )
    window.delete_profile()
    assert window.store.list_profiles() == []
    assert window._current_profile is None
    assert window.tree.topLevelItemCount() == 0
    entries = window.store.list_trash()
    assert len(entries) == 1
    assert entries[0]["kind"] == "profile"
    assert entries[0]["profile"] == "lfm3-tool"
    assert "trash" in window.statusBar().currentMessage()


def test_delete_confirm_offers_export_first(window, monkeypatch):
    # T23: the delete dialog offers to export first, before the
    # delete happens.
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    seen = []

    def fake_exec(self):
        seen.append(self)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    window.delete_project()
    assert len(seen) == 1
    texts = [b.text() for b in seen[0].buttons()]
    assert "Export this project first" in texts
    window.delete_profile()
    assert len(seen) == 2
    texts = [b.text() for b in seen[1].buttons()]
    assert "Export all projects first" in texts


def test_trash_dialog_lists_and_purges(window, monkeypatch):
    # T23: the Trash window lists what was deleted and can delete
    # one item forever, with its own confirm defaulting to No.
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    seen = []

    def fake_exec(self):
        seen.append(self)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    window.delete_project()
    trash = window.open_trash_window()
    assert trash.list_widget.count() == 1
    assert "tool-calls" in trash.list_widget.item(0).text()
    # Nothing selected by default, so Delete forever starts off.
    assert not trash.purge_btn.isEnabled()
    trash.list_widget.setCurrentRow(0)
    assert trash.purge_btn.isEnabled()
    trash.purge_btn.click()
    # The purge confirm defaulted to No (the last box shown).
    assert seen[-1].defaultButton() is seen[-1].button(QMessageBox.No)
    assert window.store.list_trash() == []
    assert trash.list_widget.count() == 0
    trash.close()


def test_trash_dialog_restore_brings_project_back(
    window, monkeypatch, qapp
):
    """R2: Restore in the Trash window brings a deleted project
    back under its real name, and it opens afterwards."""
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.Yes
    )
    window.delete_project()
    assert window.store.list_projects("lfm3-tool") == []
    trash = window.open_trash_window()
    assert trash.list_widget.count() == 1
    # Nothing selected by default, so Restore starts off.
    assert not trash.restore_btn.isEnabled()
    trash.list_widget.setCurrentRow(0)
    assert trash.restore_btn.isEnabled()
    trash.restore_btn.click()
    qapp.processEvents()
    assert window.store.list_trash() == []
    assert trash.list_widget.count() == 0
    assert (
        window.store.get_project("lfm3-tool", "tool-calls")["name"]
        == "tool-calls"
    )
    assert "is back" in window.statusBar().currentMessage()
    trash.close()


def test_trash_dialog_restore_clash_warns_and_keeps_trash(
    window, monkeypatch, qapp
):
    """R2: when a live project with the same name exists, Restore
    warns in plain words and the trashed item stays put."""
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.Yes
    )
    window.delete_project()
    window.store.create_project("lfm3-tool", "tool-calls")
    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: warned.append(a[2] if len(a) > 2 else ""),
    )
    trash = window.open_trash_window()
    trash.list_widget.setCurrentRow(0)
    trash.restore_btn.click()
    qapp.processEvents()
    assert warned and "already exists" in warned[0]
    assert len(window.store.list_trash()) == 1
    assert trash.list_widget.count() == 1
    trash.close()


def test_trash_dialog_empty_trash(window, monkeypatch):
    # T23: Empty trash purges everything, with a confirm.
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.Yes
    )
    window.delete_project()
    trash = window.open_trash_window()
    assert trash.empty_btn.isEnabled()
    trash.empty_btn.click()
    assert window.store.list_trash() == []
    assert not trash.empty_btn.isEnabled()
    trash.close()


# -- text rules (U11, U33) ------------------------------------------


def test_no_ampersand_in_visible_labels(window):
    # Qt eats a bare & as a mnemonic marker — forbidden in visible text.
    _select_session(window)
    prof = window.open_profile_window("lfm3-tool")
    proj = window.open_project_window("lfm3-tool", "tool-calls")
    settings_win = window.open_settings_window()
    howto = window.open_howto_window()
    howto.topic_list.setCurrentRow(0)
    trash = window.open_trash_window()
    bad = [t for t in _visible_texts(window) if "&" in t]
    assert bad == []
    prof.close()
    proj.close()
    settings_win.close()
    howto.close()
    trash.close()


def test_no_em_dash_in_visible_text(window, seeded):
    # U33: no em-dashes in ANY visible UI text.
    from stella.sleep import load_sleep_manifest, save_sleep_manifest

    _select_session(window)
    manifest = load_sleep_manifest(seeded, "lfm3-tool", "tool-calls")
    manifest["cycles"] = [{
        "cycle": 1, "status": "OK", "timestamp": "2026-11-13T00:00:00",
        "real_rows": 6, "dreamed_rows": 2, "steps": 4,
        "old_loss_before": 2.0, "old_loss_after": 1.9, "new_loss": 1.5,
    }]
    save_sleep_manifest(seeded, "lfm3-tool", "tool-calls", manifest)
    window.refresh_train_panel()
    prof = window.open_profile_window("lfm3-tool")
    proj = window.open_project_window("lfm3-tool", "tool-calls")
    settings_win = window.open_settings_window()
    howto = window.open_howto_window()
    howto.topic_list.setCurrentRow(0)
    trash = window.open_trash_window()
    bad = [t for t in _visible_texts(window) if "—" in t]
    # The sleep-cycle list rows are list items, not widgets: check too.
    for i in range(window.sleep_cycles.count()):
        if "—" in window.sleep_cycles.item(i).text():
            bad.append(window.sleep_cycles.item(i).text())
    assert bad == []
    prof.close()
    proj.close()
    settings_win.close()
    howto.close()
    trash.close()


# -- train / sleep panels -------------------------------------------


def test_train_panel_widgets_exist(window):
    # The hero tile (T15) and the glanceable card (T20) replace the
    # old Train panel: pick a model, pick a job, press Go.
    assert window.model_combo is not None
    assert window.go_btn is not None
    assert window.go_btn.text() == "Go"
    assert set(window.job_buttons) == {"train", "sleep", "requant", "distill"}
    assert window.loss_curve is not None
    assert window.stat_speed is not None
    assert window.stat_ram is not None
    assert window.stat_time_left is not None
    assert window.stat_epoch is not None
    assert window.train_pause_btn is not None
    assert window.train_resume_btn is not None
    assert window.train_progress is not None
    assert window.train_loss is not None
    assert window.train_checkpoints is not None
    assert window.train_export_gguf_btn is not None
    assert window.train_probe_btn is not None
    assert window.train_log is not None
    assert window.train_log.isReadOnly()
    assert window.train_pause_btn.isEnabled() is False
    # v0.16.0: the proof run + estimate buttons, the estimate
    # label, the dataset health line, and the probe results view.
    assert window.train_proof_btn is not None
    assert window.train_proof_btn.text() == "Proof run"
    assert window.train_estimate_btn is not None
    assert window.train_estimate_btn.text() == "Estimate"
    assert window.train_estimate_label is not None
    assert window.dataset_health_label is not None
    assert window.train_view_probe_btn is not None
    assert window.train_view_probe_btn.text() == "View probe results"


def test_start_training_without_deps_logs_hint(window, monkeypatch):
    import stella.train as train_mod

    _select_session(window)
    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch", "peft"]
    )
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.start_training()
    assert "install-training.sh" in window.train_log.toPlainText()
    # T49: the hint also shows as a dialog, not just in the log.
    assert warnings
    assert "install-training.sh" in warnings[0]
    assert "torch" in warnings[0]
    assert window._train_worker is None


def test_use_sample_dataset_sets_ref(window, seeded):
    _select_session(window)
    window.use_sample_dataset()
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["dataset_ref"] == "sample-tool-calls.jsonl"
    assert "sample-tool-calls.jsonl" in window.session_summary.text()


def test_train_progress_updates(window):
    window._on_train_progress(5, 20, 2.5)
    assert window.train_progress.maximum() == 20
    assert window.train_progress.value() == 5
    assert "Step 5 / 20" in window.train_loss.text()
    assert "2.5000" in window.train_loss.text()
    assert "Training" in window.activity_text.text()


def test_train_loss_line_follows_session(window):
    # Regression: the loss line used to keep the no-project text
    # ("Pick a project to train.") after a session was set.
    assert window.train_loss.text() == "Pick a project to train."
    _select_session(window)
    assert window.train_loss.text() == "Not started."
    window.set_session("lfm3-tool", None)
    assert window.train_loss.text() == "Pick a project to train."


def test_sleep_panel_widgets_exist(window):
    # Sleep is a job button now (T15); the dream switch and the
    # cycles list stay in the details below.
    assert window.job_buttons["sleep"] is not None
    assert window.job_buttons["sleep"].text() == "Sleep"
    assert window.sleep_dream_check is not None
    assert window.sleep_dream_check.text() == "Dream first"
    assert window.sleep_dream_check.isChecked() is False
    assert window.sleep_cycles is not None
    assert window.sleep_cycles.count() == 0  # no cycles yet


def test_sleep_cycle_list_shows_cycles(window, seeded):
    from PySide6.QtCore import Qt

    from stella.sleep import load_sleep_manifest, save_sleep_manifest

    _select_session(window)
    manifest = load_sleep_manifest(seeded, "lfm3-tool", "tool-calls")
    manifest["cycles"] = [{
        "cycle": 1, "status": "OK", "timestamp": "2026-11-13T00:00:00",
        "real_rows": 6, "dreamed_rows": 2, "steps": 4,
        "old_loss_before": 2.0, "old_loss_after": 1.9, "new_loss": 1.5,
    }]
    save_sleep_manifest(seeded, "lfm3-tool", "tool-calls", manifest)
    window.refresh_train_panel()
    assert window.sleep_cycles.count() == 1
    text = window.sleep_cycles.item(0).text()
    assert "cycle 1" in text
    assert "OK" in text
    assert "6 new" in text
    assert "2 dreamed" in text
    assert window.sleep_cycles.item(0).data(Qt.UserRole) == 1


def test_sleep_cycle_list_shows_unhealed_cycle(window, seeded):
    """R8: a cycle that could not be recovered is listed too,
    plainly — with its reason, not silently dropped."""
    import json

    from PySide6.QtCore import Qt

    _select_session(window)
    cdir = (
        seeded.project_dir("lfm3-tool", "tool-calls")
        / "sleep" / "cycle-1"
    )
    cdir.mkdir(parents=True)
    (cdir / "report.json").write_text(json.dumps({
        "cycle": 1, "status": "OK", "timestamp": "2026-11-13T00:00:00",
        "real_rows": 6, "dreamed_rows": 0, "steps": 3,
        "old_loss_before": None, "old_loss_after": None, "new_loss": 1.5,
    }))
    # No cycle_input.json: the cycle cannot be healed.
    window.refresh_train_panel()
    assert window.sleep_cycles.count() == 1
    text = window.sleep_cycles.item(0).text()
    assert "cycle 1" in text
    assert "could not be recovered" in text
    assert "input file" in text
    assert window.sleep_cycles.item(0).data(Qt.UserRole) == 1


def _seed_gui_sleep_cycle(seeded, number, payload_bytes=1000):
    """A finished cycle on disk for the GUI tests (same shape as
    the engine tests' seed). Returns the cycle dir."""
    from stella.sleep import load_sleep_manifest, save_sleep_manifest

    cdir = (
        seeded.project_dir("lfm3-tool", "tool-calls")
        / "sleep" / f"cycle-{number}"
    )
    (cdir / "adapter").mkdir(parents=True)
    (cdir / "adapter" / "adapter_config.json").write_text("{}\n")
    (cdir / "payload.bin").write_bytes(b"x" * payload_bytes)
    (cdir / "report.json").write_text(json.dumps({
        "cycle": number, "status": "OK",
        "timestamp": "2026-11-13T00:00:00",
        "real_rows": 6, "dreamed_rows": 0, "steps": 3,
        "old_loss_before": 2.0, "old_loss_after": 1.9, "new_loss": 1.5,
    }))
    (cdir / "cycle_input.json").write_text(json.dumps({
        "real_hashes": [f"hash-{number}-a"],
        "dreamed_hashes": [],
    }))
    manifest = load_sleep_manifest(seeded, "lfm3-tool", "tool-calls")
    manifest["cycles"] = [
        c for c in manifest["cycles"] if c.get("cycle") != number
    ]
    manifest["cycles"].append({
        "cycle": number, "status": "OK",
        "timestamp": "2026-11-13T00:00:00",
        "real_rows": 6, "dreamed_rows": 0, "steps": 3,
        "old_loss_before": 2.0, "old_loss_after": 1.9, "new_loss": 1.5,
    })
    save_sleep_manifest(seeded, "lfm3-tool", "tool-calls", manifest)
    return cdir


def test_sleep_cycle_list_shows_size(window, seeded):
    # R66: each cycle line carries its size, and the disk label
    # totals them.
    _select_session(window)
    _seed_gui_sleep_cycle(seeded, 1, payload_bytes=2048)
    window.refresh_train_panel()
    assert window.sleep_cycles.count() == 1
    text = window.sleep_cycles.item(0).text()
    assert "2 KB" in text  # the 2 KB payload, plus small files
    assert "Sleep cycles use" in window.sleep_disk_label.text()
    assert "1 cycle" in window.sleep_disk_label.text()


def test_sleep_delete_button_deletes_picked_cycle(
    window, seeded, monkeypatch, qapp
):
    # R66: Delete cycle, Yes at the confirm, removes the cycle
    # dir and its list row, and says what it freed.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    cdir = _seed_gui_sleep_cycle(seeded, 1, payload_bytes=2048)
    _seed_gui_sleep_cycle(seeded, 2, payload_bytes=2048)
    window.refresh_train_panel()
    assert window.sleep_cycles.count() == 2
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    window.sleep_cycles.setCurrentRow(0)
    window.sleep_delete_btn.click()
    qapp.processEvents()
    assert not cdir.exists()
    assert window.sleep_cycles.count() == 1
    assert window.sleep_cycles.item(0).data(Qt.UserRole) == 2
    assert "Deleted sleep cycle 1" in window.statusBar().currentMessage()
    assert "freed" in window.statusBar().currentMessage()


def test_sleep_delete_button_no_keeps_cycle(
    window, seeded, monkeypatch, qapp
):
    # R66: No at the confirm keeps the cycle (the default is No).
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    cdir = _seed_gui_sleep_cycle(seeded, 1, payload_bytes=2048)
    window.refresh_train_panel()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )
    window.sleep_cycles.setCurrentRow(0)
    window.sleep_delete_btn.click()
    qapp.processEvents()
    assert cdir.exists()
    assert window.sleep_cycles.count() == 1


def test_sleep_delete_button_without_pick_warns(window, monkeypatch):
    # R66: Delete with nothing picked warns instead of deleting.
    _select_session(window)
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.sleep_delete_btn.click()
    assert warnings == ["Pick a sleep cycle first."]


def test_sleep_prune_button_keeps_newest(
    window, seeded, monkeypatch, qapp
):
    # R66: Prune with keep 1 deletes the older cycles and keeps
    # the newest.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    cdir1 = _seed_gui_sleep_cycle(seeded, 1, payload_bytes=1000)
    _seed_gui_sleep_cycle(seeded, 2, payload_bytes=1000)
    _seed_gui_sleep_cycle(seeded, 3, payload_bytes=1000)
    window.refresh_train_panel()
    assert window.sleep_cycles.count() == 3
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    window.sleep_keep_spin.setValue(1)
    window.sleep_prune_btn.click()
    qapp.processEvents()
    assert not cdir1.exists()
    assert window.sleep_cycles.count() == 1
    assert window.sleep_cycles.item(0).data(Qt.UserRole) == 3
    assert "Pruned 2 sleep cycles" in window.statusBar().currentMessage()


def test_start_sleep_without_deps_logs_hint(window, monkeypatch):
    import stella.train as train_mod

    _select_session(window)
    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch", "peft"]
    )
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.start_sleep()
    assert "install-training.sh" in window.train_log.toPlainText()
    # T49: the hint also shows as a dialog, not just in the log.
    assert warnings
    assert "install-training.sh" in warnings[0]
    assert "torch" in warnings[0]
    assert window._sleep_worker is None


# -- downloads ------------------------------------------------------


def test_start_download_no_repo_warns(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    _select_session(window)
    window.start_download()
    assert warnings
    assert "No Hugging Face repo set" in warnings[0]


def test_start_download_no_hub_warns(window, monkeypatch, tmp_path):
    import stella.provision as prov

    monkeypatch.setattr(prov, "hub_cache_dir", lambda: tmp_path / "hub")
    monkeypatch.setattr(prov, "hub_available", lambda: False)
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.store.create_profile("lfm3-hf", base_ref="LiquidAI/LFM3-1.7B")
    window.store.create_project("lfm3-hf", "tool-calls")
    window.set_session("lfm3-hf", "tool-calls")
    window.start_download()
    assert warnings
    assert "install-training.sh" in warnings[0]
    # R13: the hint names the click path first — no terminal needed.
    assert "Install training" in warnings[0]


def test_start_training_offers_download_when_weights_missing(
    window, monkeypatch, tmp_path
):
    import stella.provision as prov
    import stella.train as train_mod
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(prov, "hub_cache_dir", lambda: tmp_path / "hub")
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    asked = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No,
    )
    window.store.create_profile("lfm3-hf", base_ref="LiquidAI/LFM3-1.7B")
    window.store.create_project("lfm3-hf", "tool-calls")
    window.set_session("lfm3-hf", "tool-calls")
    window.start_training()
    assert window._train_worker is None
    assert len(asked) == 1
    assert "not downloaded yet" in asked[0]


def test_start_training_download_yes_starts_download(
    window, monkeypatch, tmp_path
):
    import stella.provision as prov
    import stella.train as train_mod
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(prov, "hub_cache_dir", lambda: tmp_path / "hub")
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    started = []
    monkeypatch.setattr(
        window, "start_download", lambda profile=None: started.append(profile)
    )
    window.store.create_profile("lfm3-hf", base_ref="LiquidAI/LFM3-1.7B")
    window.store.create_project("lfm3-hf", "tool-calls")
    window.set_session("lfm3-hf", "tool-calls")
    window.start_training()
    assert window._train_worker is None
    assert started == ["lfm3-hf"]


# -- new profile dialog ---------------------------------------------


def test_new_profile_dialog_is_a_real_window(window, qapp):
    """Regression: the New Profile form must be a real QDialog window,
    not a QWidget child smearing over the main window (T11)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog

    from stella.gui import NewProfileDialog

    dialog = NewProfileDialog(window)
    assert isinstance(dialog, QDialog)
    dialog.show()
    qapp.processEvents()
    assert dialog.windowFlags() & Qt.Window
    assert dialog.isWindow()
    dialog.close()


def test_new_profile_dialog_asks_only_for_a_model(window):
    """No role, no display name, no name field at creation."""
    from stella.gui import NewProfileDialog

    dialog = NewProfileDialog(window)
    assert not hasattr(dialog, "role_combo")
    assert not hasattr(dialog, "display_edit")
    assert not hasattr(dialog, "name_edit")
    assert hasattr(dialog, "model_list")
    assert hasattr(dialog, "type_edit")
    dialog.close()


def test_create_profile_from_hf_repo(window, seeded):
    from PySide6.QtWidgets import QDialog

    from stella.gui import NewProfileDialog

    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("LiquidAI/LFM3-1.7B")
    assert dialog.name_note.text() == "Profile name: lfm3-1-7b"
    window._create_profile_from(dialog)
    assert dialog.result() == QDialog.Accepted
    data = seeded.get_profile("lfm3-1-7b")
    assert data["base_ref"] == "LiquidAI/LFM3-1.7B"
    assert data["ollama_tag"] == ""
    assert data["display_name"] == "lfm3-1-7b"
    assert data["role"] == ""


def test_create_profile_from_ollama_tag(window, seeded, monkeypatch,
                                      seed_models):
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    # Seeded: with a live Ollama the cache fills with the real
    # installed list, "qwen3.5:4b" is not in it, and the soft tag
    # check opens a modal confirm nobody clicks in a test (hang).
    seed_models(["lfm3:1.7b", "qwen3.5:4b"])

    def _no_prompt(*a, **k):
        raise AssertionError("no warning for an installed, unused tag")

    monkeypatch.setattr(QMessageBox, "question", _no_prompt)
    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("qwen3.5:4b")
    window._create_profile_from(dialog)
    data = seeded.get_profile("qwen3-5-4b")
    assert data["ollama_tag"] == "qwen3.5:4b"


def test_create_profile_name_collision_gets_suffix(window, seeded):
    from stella.gui import NewProfileDialog

    for _ in range(2):
        dialog = NewProfileDialog(window)
        dialog.type_edit.setText("LiquidAI/LFM3-1.7B")
        window._create_profile_from(dialog)
    assert seeded.get_profile("lfm3-1-7b")
    assert seeded.get_profile("lfm3-1-7b-2")


def test_create_profile_empty_model_warns(window, monkeypatch):
    from stella.gui import NewProfileDialog

    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("")
    window._create_profile_from(dialog)
    assert warnings == ["Pick a model first."]
    assert [p["name"] for p in window.store.list_profiles()] == ["lfm3-tool"]


def test_new_profile_enter_creates(window, seeded, monkeypatch,
                                 seed_models):
    """Enter in the model field creates the profile (T11: Enter works)."""
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    # Seeded: with a live Ollama the cache fills with the real
    # installed list, "qwen3.5:4b" is not in it, and the soft tag
    # check opens a modal confirm nobody clicks in a test (hang).
    seed_models(["lfm3:1.7b", "qwen3.5:4b"])

    def _no_prompt(*a, **k):
        raise AssertionError("no warning for an installed, unused tag")

    monkeypatch.setattr(QMessageBox, "question", _no_prompt)
    dialog = NewProfileDialog(window)
    assert dialog.create_btn.isDefault()
    dialog.create_btn.clicked.connect(lambda: window._create_profile_from(dialog))
    dialog.type_edit.setText("qwen3.5:4b")
    dialog.type_edit.returnPressed.emit()
    assert seeded.get_profile("qwen3-5-4b")


# -- chat window ------------------------------------------------------


class FakeChatAgent:
    """A stand-in for ChatAgent: instant replies, records cancel."""

    pending_plan = None

    def __init__(self, reply_text="Hello from the fake chat."):
        self.reply_text = reply_text
        self.received = []
        self.cancelled = False
        self.current_profile = None
        self.current_project = None

    def set_model(self, model):
        pass

    def set_provider(self, provider, model):
        pass

    def set_callbacks(self, on_narration=None, on_progress=None,
                      on_token=None):
        pass

    def request_cancel(self):
        self.cancelled = True

    def reply(self, text):
        self.received.append(text)
        return self.reply_text


class BlockingChatAgent(FakeChatAgent):
    """Replies only after cancel is requested (for the Cancel test)."""

    def reply(self, text):
        import time

        self.received.append(text)
        deadline = time.time() + 5
        while not self.cancelled and time.time() < deadline:
            time.sleep(0.05)
        return "Stopped."


def test_menu_chat_opens_chat_window(window):
    window._menu_action_chat.trigger()
    assert window._chat_window is not None
    assert window._chat_window.isVisible()
    assert "Chat" in window._chat_window.windowTitle()
    window._chat_window.close()


def test_chat_window_is_single_instance(window):
    first = window.open_chat_window()
    second = window.open_chat_window()
    assert first is second
    first.close()


def _wait_for_text(chat, needle, qapp, timeout_ms=5000):
    """Poll until the chat shows `needle` (worker threads are slow
    under sandbox load; a fixed short wait flakes)."""
    from PySide6.QtTest import QTest

    waited = 0
    while waited < timeout_ms:
        QTest.qWait(100)
        waited += 100
        if needle in chat.messages.toPlainText():
            return True
    return False


def test_chat_window_send_receive_fake_agent(window, qapp):
    from PySide6.QtTest import QTest

    from stella.gui import ChatWindow

    window.set_chat_model("lfm3:1.7b")
    fake = FakeChatAgent("Training is all set up.")
    chat = ChatWindow(window, agent_factory=lambda: fake)
    chat.show()
    qapp.processEvents()
    chat.input.setText("train LFM3 on tool calls")
    chat.send_btn.click()
    assert _wait_for_text(chat, "Stella: Training is all set up.", qapp)
    text = chat.messages.toPlainText()
    assert "You: train LFM3 on tool calls" in text
    assert fake.received == ["train LFM3 on tool calls"]
    assert chat.send_btn.isEnabled()
    assert not chat.cancel_btn.isEnabled()
    chat.close()


def test_chat_window_enter_sends(window, qapp):
    from stella.gui import ChatWindow

    window.set_chat_model("lfm3:1.7b")
    fake = FakeChatAgent("Got it.")
    chat = ChatWindow(window, agent_factory=lambda: fake)
    chat.show()
    qapp.processEvents()
    chat.input.setText("hello")
    chat.input.returnPressed.emit()
    assert _wait_for_text(chat, "Stella: Got it.", qapp)
    assert fake.received == ["hello"]
    chat.close()


def test_chat_window_cancel_stops_worker(window, qapp):
    from PySide6.QtTest import QTest

    from stella.gui import ChatWindow

    window.set_chat_model("lfm3:1.7b")
    fake = BlockingChatAgent()
    chat = ChatWindow(window, agent_factory=lambda: fake)
    chat.show()
    qapp.processEvents()
    chat.input.setText("train everything")
    chat.send_btn.click()
    QTest.qWait(300)
    assert chat.cancel_btn.isEnabled()
    chat.cancel_btn.click()
    assert _wait_for_text(chat, "Stopped.", qapp)
    assert fake.cancelled
    chat.close()


def test_chat_window_asks_for_model_when_none_picked(window, seed_models, qapp):
    """T76: no typing needed to pick a chat model — clickable
    buttons, one per installed model."""
    from stella.gui import ChatWindow

    seed_models(["lfm3:1.7b", "qwen3.5:2b"])
    assert window.chat_model == ""
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert "Which model should I chat with?" in chat.messages.toPlainText()
    assert "Pick one below." in chat.messages.toPlainText()
    assert len(chat.model_buttons) == 2
    assert [b.text() for b in chat.model_buttons] == [
        "lfm3:1.7b",
        "qwen3.5:2b",
    ]
    chat.model_buttons[0].click()
    qapp.processEvents()
    assert window.chat_model == "lfm3:1.7b"
    assert "I will chat with lfm3:1.7b" in chat.messages.toPlainText()
    assert chat.model_pick_scroll.isVisible() is False
    chat.close()


def test_chat_window_rejects_unknown_model_name(window, seed_models, qapp):
    from stella.gui import ChatWindow

    seed_models(["lfm3:1.7b"])
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    chat.input.setText("not-a-model")
    chat.send_btn.click()
    qapp.processEvents()
    assert window.chat_model == ""
    assert "did not find that model" in chat.messages.toPlainText()
    chat.close()


def test_settings_window_chat_model_picker(window, seed_models):
    seed_models(["lfm3:1.7b", "qwen3.5:2b"])
    settings_win = window.open_settings_window()
    # Nothing selected by default. The list is grouped: an Ollama
    # header + 2 models, a Groq header + 2, a Gemini header + 2.
    # No key saved, so the cloud models are greyed out.
    assert settings_win.chat_combo.currentIndex() == -1
    assert settings_win.chat_combo.count() == 9
    combo = settings_win.chat_combo
    assert combo.itemText(0) == "On this PC (Ollama)"
    assert not combo.model().item(0).isEnabled()
    assert combo.itemData(1) == "ollama|lfm3:1.7b"
    assert combo.model().item(1).isEnabled()
    assert combo.itemText(3) == "Groq"
    assert combo.itemData(4) == "groq|openai/gpt-oss-120b"
    assert not combo.model().item(4).isEnabled()
    assert combo.itemText(6) == "Gemini"
    combo.setCurrentText("qwen3.5:2b")
    assert window.chat_model == "qwen3.5:2b"
    assert window.chat_provider == "ollama"
    settings_win.close()
    # Reopening restores the saved pick.
    again = window.open_settings_window()
    assert again.chat_combo.currentText() == "qwen3.5:2b"
    again.close()


def test_settings_providers_save_and_remove(window, seed_models):
    from stella.providers import get_key, has_key

    seed_models([])
    settings_win = window.open_settings_window()
    assert settings_win._key_status["groq"].text() == "No key saved."
    settings_win._key_fields["groq"].setText("test-key-123")
    settings_win._provider_buttons["groq"]["save"].click()
    assert get_key(window.store.home, "groq") == "test-key-123"
    assert settings_win._key_status["groq"].text() == "Saved."
    # The key field is cleared after saving: it never shows the key.
    assert settings_win._key_fields["groq"].text() == ""
    # Saving a key ungreys that provider's models in the picker.
    combo = settings_win.chat_combo
    groq_index = combo.findData("groq|openai/gpt-oss-120b")
    assert groq_index >= 0
    assert combo.model().item(groq_index).isEnabled()
    settings_win._provider_buttons["groq"]["remove"].click()
    assert not has_key(window.store.home, "groq")
    assert settings_win._key_status["groq"].text() == "No key saved."
    settings_win.close()


def test_settings_providers_save_empty_key_asks(window, seed_models):
    seed_models([])
    settings_win = window.open_settings_window()
    settings_win._provider_buttons["gemini"]["save"].click()
    assert settings_win._key_status["gemini"].text() == "Paste a key first."
    settings_win.close()


def test_settings_providers_test_shows_result(
    window, monkeypatch, qapp, seed_models
):
    import time

    import stella.gui as gui_mod
    from stella.providers import save_key

    seed_models([])
    monkeypatch.setattr(
        gui_mod, "test_connection",
        lambda pid, home=None: (True, "Groq answered. Your key works."),
    )
    save_key(window.store.home, "groq", "test-key-123")
    settings_win = window.open_settings_window()
    settings_win._provider_buttons["groq"]["test"].click()
    deadline = 5000
    while (
        settings_win._key_status["groq"].text() == "Testing..."
        and deadline > 0
    ):
        qapp.processEvents()
        deadline -= 50
        time.sleep(0.05)
    assert settings_win._key_status["groq"].text() == (
        "Groq answered. Your key works."
    )
    settings_win.close()


def test_settings_providers_custom_row(window, seed_models):
    from stella.providers import get_custom_config, get_key

    seed_models([])
    settings_win = window.open_settings_window()
    settings_win._custom_base.setText("https://example.com/v1")
    settings_win._custom_model.setText("my-model")
    settings_win._key_fields["custom"].setText("test-key-123")
    settings_win._provider_buttons["custom"]["save"].click()
    assert get_key(window.store.home, "custom") == "test-key-123"
    assert get_custom_config(window.store.home) == {
        "base_url": "https://example.com/v1",
        "model": "my-model",
    }
    # The custom model now appears in the picker, enabled.
    combo = settings_win.chat_combo
    index = combo.findData("custom|my-model")
    assert index >= 0
    assert combo.model().item(index).isEnabled()
    settings_win.close()


def test_chat_window_matches_cloud_model_name(window, seed_models, qapp):
    from stella.gui import ChatWindow
    from stella.providers import save_key

    seed_models(["lfm3:1.7b"])
    save_key(window.store.home, "groq", "test-key-123")
    assert window.chat_model == ""
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    chat.input.setText("openai/gpt-oss-120b")
    chat.send_btn.click()
    qapp.processEvents()
    assert window.chat_model == "openai/gpt-oss-120b"
    assert window.chat_provider == "groq"
    chat.close()


def test_chat_window_has_no_em_dash(window, qapp):
    chat = window.open_chat_window()
    qapp.processEvents()
    bad = [t for t in _visible_texts(window) if "—" in t]
    assert bad == []
    chat.close()


# -- T21: fill the detail panel defensively --------------------------


def _corrupt_project_json(store, profile, project, mutate):
    import json

    manifest = store.project_dir(profile, project) / "project.json"
    data = json.loads(manifest.read_text())
    mutate(data)
    manifest.write_text(json.dumps(data))


def test_project_window_bad_display_falls_back(window, seeded, qapp):
    """T21, kept for the fields the window still shows (T16 took the
    settings form away): a stored display name that is not a string
    falls back to blank, with the note, and saving keeps the blank."""
    _corrupt_project_json(
        seeded, "lfm3-tool", "tool-calls",
        lambda d: d.update(display_name=42),
    )
    win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert win.display_edit.text() == ""
    assert "stored value was invalid" in win._load_note.text()
    assert win._load_note.isVisible()
    # The rest of the panel still filled from THIS project.
    assert win.dataset_edit.text() == "forge-traces.jsonl"
    # Save writes the blank, not the bad stored value.
    assert win.save() is True
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["display_name"] == ""
    assert isinstance(data["display_name"], str)
    win.close()


@pytest.mark.parametrize(
    "mutate, check",
    [
        (lambda d: d.update(display_name=42),
         lambda w: w.display_edit.text() == ""),
        (lambda d: d.update(display_name=None),
         lambda w: w.display_edit.text() == ""),
        (lambda d: d.update(dataset_ref=["x"]),
         lambda w: w.dataset_edit.text() == ""),
        (lambda d: d.update(dataset_ref=123),
         lambda w: w.dataset_edit.text() == ""),
    ],
)
def test_project_window_bad_value_falls_back(window, seeded, qapp,
                                             mutate, check):
    _corrupt_project_json(seeded, "lfm3-tool", "tool-calls", mutate)
    win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert check(win)
    assert "stored value was invalid" in win._load_note.text()
    win.close()


def test_project_window_ignores_corrupt_stored_settings(
    window, seeded, qapp
):
    """T16: the window never reads settings, so a corrupt stored
    settings block must not break the fill, show a note, or be
    touched by a save."""
    _corrupt_project_json(
        seeded, "lfm3-tool", "tool-calls",
        lambda d: d.update(settings="all of it"),
    )
    win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert win.display_edit.text() == "tool-calls"
    assert win.dataset_edit.text() == "forge-traces.jsonl"
    assert win._load_note.text() == ""
    assert not win._load_note.isVisible()
    win.notes_edit.setPlainText("still fine")
    assert win.save() is True
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["settings"] == "all of it"
    win.close()


def test_project_window_clean_fill_shows_no_note(window, seeded, qapp):
    win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert win._load_note.text() == ""
    assert not win._load_note.isVisible()
    win.close()


def test_project_window_retarget_never_mixes_projects(window, seeded, qapp):
    # Project A holds a display name and dataset; project B has a
    # corrupt display name. Opening A then retargeting to B must
    # show B (blank display + note, B's dataset), never A's values
    # under B's name.
    seeded.create_project("lfm3-tool", "second",
                          display_name="Second Project",
                          dataset_ref="second.jsonl")
    _corrupt_project_json(
        seeded, "lfm3-tool", "tool-calls",
        lambda d: d.update(display_name=42),
    )
    win = window.open_project_window("lfm3-tool", "second")
    qapp.processEvents()
    assert win.display_edit.text() == "Second Project"
    assert win.dataset_edit.text() == "second.jsonl"
    win.retarget("tool-calls")
    qapp.processEvents()
    assert win.display_edit.text() == ""
    assert win.dataset_edit.text() == "forge-traces.jsonl"
    assert "stored value was invalid" in win._load_note.text()
    win.close()


# -- T39: GUI list warns on a string metamorph -----------------------


def test_tree_warns_on_string_metamorph(window, seeded, qapp):
    seeded.create_project("lfm3-tool", "broken")
    _corrupt_project_json(
        seeded, "lfm3-tool", "broken",
        lambda d: d.update(metamorph="both"),
    )
    window.refresh_tree()
    qapp.processEvents()
    top = window.tree.topLevelItem(0)
    rows = {top.child(i).text(0) for i in range(top.childCount())}
    assert top.childCount() == 2
    warned = [r for r in rows if "warning" in r]
    assert len(warned) == 1
    assert "broken" in warned[0]
    # The good project lists normally, with its status and no warning.
    assert any(r == "tool-calls (draft) [forge-traces.jsonl]" for r in rows)


# -- T1: GUI import handler ------------------------------------------


def test_import_package_warns_and_refreshes_on_failure(
    window, seeded, tmp_path, monkeypatch, qapp
):
    import json as json_mod

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from stella import export as export_mod

    pkg = export_mod.export_project(
        seeded, "lfm3-tool", "tool-calls", tmp_path
    )
    manifest_path = pkg / "manifest.json"
    manifest = json_mod.loads(manifest_path.read_text())
    manifest["project"]["settings"] = "rank 8"
    manifest_path.write_text(json_mod.dumps(manifest))
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    window.import_package()
    _wait_for_job(window, qapp)
    assert warnings, "no warning dialog appeared for the bad import"
    assert "settings" in warnings[0]
    # The lists refreshed: the window still matches the disk.
    assert window.tree.topLevelItemCount() == 1
    assert window.tree.topLevelItem(0).childCount() == 1


def test_import_package_last_resort_catch(
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    import stella.gui as gui_mod

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: "/tmp/whatever"
    )
    # T58: the preview must pass (stubbed) so import_export is
    # still the call that raises.
    monkeypatch.setattr(
        gui_mod.export_mod, "preview_export",
        lambda *a, **k: {"profile": "x", "project": "y"},
    )
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        gui_mod.export_mod, "import_export",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    window.import_package()  # must not raise out of the handler
    # Wait for the worker: one processEvents() is not enough under
    # load — the thread may not have run yet, so the warning would
    # not be recorded (and the worker would outlive the test's
    # stubs, firing a real warning modal into the next test).
    _wait_for_job(window, qapp)
    qapp.processEvents()
    assert warnings
    assert "kaboom" in warnings[0]
    assert window.tree.topLevelItemCount() == 1


# -- T15: the hero tile above the fold at 1100x680 --------------------


def test_hero_above_fold_at_default_size(window, qapp):
    """T15 Done: pick a model, pick a job, press Go, no scrolling
    at 1100x680."""
    from PySide6.QtWidgets import QScrollArea

    # The seeded store has no weights and no trained project, so
    # the first-run checklist covers the bento: dismiss it first.
    window._checklist_dismiss()
    window.resize(1100, 680)
    window.set_session("lfm3-tool", "tool-calls")
    window.show()
    qapp.processEvents()
    assert window.width() == 1100
    assert window.height() == 680
    scrolls = window.findChildren(QScrollArea)
    assert len(scrolls) == 1
    viewport = scrolls[0].viewport()
    height = viewport.height()
    assert height > 0
    for widget in (
        window.model_combo,
        window.job_buttons["train"],
        window.job_buttons["distill"],
        window.go_btn,
    ):
        top = widget.mapTo(viewport, widget.rect().topLeft()).y()
        bottom = top + widget.height()
        assert 0 <= top, f"{widget} starts above the viewport"
        assert bottom <= height, (
            f"{widget} ends at y={bottom} in a {height}px viewport"
        )


# -- T71 (pin): no metamorph promise text in any visible GUI string --


def test_t71_no_promise_text_in_gui(window, qapp):
    project_win = window.open_project_window("lfm3-tool", "tool-calls")
    profile_win = window.open_profile_window("lfm3-tool")
    settings_win = window.open_settings_window()
    howto_win = window.open_howto_window()
    qapp.processEvents()
    texts = _visible_texts(window)
    assert texts, "no visible strings collected at all"
    for text in texts:
        lowered = text.lower()
        assert "metamorph" not in lowered, f"metamorph text visible: {text!r}"
        assert "turns the base into variants" not in lowered
        assert "shrinks how the fine-tune is stored" not in lowered
    project_win.close()
    profile_win.close()
    settings_win.close()
    howto_win.close()


# -- T123 (pin): no-project session shows no settings values ---------
# -- T16: no settings values anywhere, with a session set too --------


def test_no_project_session_has_no_settings(window, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window.set_session("lfm3-tool", None)
    qapp.processEvents()
    summary = window.session_summary.text()
    assert "rank" not in summary.lower()
    assert "learning rate" not in summary.lower()
    assert "epochs" not in summary.lower()
    # With a session set, the summary still names no settings (T16).
    _select_session(window)
    qapp.processEvents()
    summary = window.session_summary.text()
    assert "rank" not in summary.lower()
    assert "learning rate" not in summary.lower()
    assert "epochs" not in summary.lower()
    assert "batch" not in summary.lower()
    assert "sequence" not in summary.lower()
    # And there is no project window to open with no selection.
    # (The "pick a project first" warning is a modal dialog: stub
    # it out, or the test waits at it forever.)
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    window.set_session(None, None)
    qapp.processEvents()
    assert window.open_project_window() is None
    assert warnings


# -- T162 (pin): second launch exits 0, no second window -------------


def test_second_main_exits_zero_while_first_runs(tmp_path, qapp):
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalSocket

    root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["STELLA_HOME"] = str(tmp_path / "home")
    first = subprocess.Popen(
        [sys.executable, "-c",
         "from stella.gui import main; raise SystemExit(main())"],
        cwd=root, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    try:
        # Wait until the first instance is listening on its socket.
        deadline = time.time() + 30
        listening = False
        while time.time() < deadline:
            if first.poll() is not None:
                break
            probe = QLocalSocket()
            probe.connectToServer("stella-single-instance")
            if probe.waitForConnected(200):
                listening = True
                probe.disconnectFromServer()
                break
            probe.abort()
            QCoreApplication.processEvents()
            time.sleep(0.2)
        assert listening, "the first instance never started listening"
        assert first.poll() is None, "the first instance exited early"
        started = time.time()
        second = subprocess.run(
            [sys.executable, "-c",
             "from stella.gui import main; raise SystemExit(main())"],
            cwd=root, env=env, capture_output=True, text=True, timeout=30,
        )
        elapsed = time.time() - started
        assert second.returncode == 0
        # A second window would run the event loop until the timeout;
        # the guard returns at once.
        assert elapsed < 15, f"second launch took {elapsed:.1f}s"
        assert first.poll() is None, "the first instance died"
    finally:
        if first.poll() is None:
            first.terminate()
            try:
                first.wait(timeout=10)
            except subprocess.TimeoutExpired:
                first.kill()
                first.wait(timeout=10)


# -- T3: damaged rows in the tree -------------------------------------


def test_tree_shows_damaged_profile_row(window, seeded, qapp):
    from PySide6.QtCore import Qt

    manifest = (
        seeded.home / "profiles" / "lfm3-tool" / "profile.json"
    )
    manifest.write_text("{not valid json", encoding="utf-8")
    window.refresh_tree()
    qapp.processEvents()
    item = window.tree.topLevelItem(0)
    assert "lfm3-tool" in item.text(0)
    assert "damaged" in item.text(0)
    assert "not valid JSON" in item.text(0)
    assert item.font(0).italic() is True
    assert item.data(0, Qt.UserRole + 1) is True
    # Clicking it does not set a session.
    window.tree.setCurrentItem(item)
    qapp.processEvents()
    assert window._current_profile is None


def test_tree_shows_damaged_project_row(window, seeded, qapp):
    import json

    manifest = (
        seeded.home / "profiles" / "lfm3-tool" / "projects"
        / "tool-calls" / "project.json"
    )
    manifest.write_text("{not valid json", encoding="utf-8")
    window.refresh_tree()
    qapp.processEvents()
    child = window.tree.topLevelItem(0).child(0)
    assert "tool-calls" in child.text(0)
    assert "damaged" in child.text(0)
    assert child.font(0).italic() is True
    # Fixing the JSON by hand and refreshing restores the normal row.
    manifest.write_text(
        json.dumps(
            {
                "name": "tool-calls",
                "display_name": "tool-calls",
                "profile": "lfm3-tool",
                "status": "draft",
                "settings": {},
            }
        ),
        encoding="utf-8",
    )
    window.refresh_tree()
    qapp.processEvents()
    child = window.tree.topLevelItem(0).child(0)
    # The hand-fixed manifest carries no dataset, so the recovered
    # row shows none either (T164: the bracket needs a dataset_ref).
    assert child.text(0) == "tool-calls (draft)"
    assert child.font(0).italic() is False


def test_damaged_row_double_click_opens_editor(window, seeded, monkeypatch, qapp):
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    manifest = (
        seeded.home / "profiles" / "lfm3-tool" / "profile.json"
    )
    manifest.write_text("{not valid json", encoding="utf-8")
    window.refresh_tree()
    qapp.processEvents()
    item = window.tree.topLevelItem(0)
    window._on_tree_double_clicked(item, 0)
    assert len(opened) == 1
    assert "profile.json" in opened[0]


# -- T2: dirty tracking in both detail windows -----------------------


def test_project_window_close_prompts_and_saves(window, seeded, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox

    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert not proj_win.is_modified()
    assert not proj_win.windowTitle().endswith("*")
    proj_win.notes_edit.setPlainText("UNSAVED edit")
    assert proj_win.is_modified()
    assert proj_win.windowTitle().endswith("*")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Save
    )
    assert proj_win.close() is True
    qapp.processEvents()
    assert not proj_win.isVisible()
    assert "UNSAVED edit" in seeded.read_notes("lfm3-tool", "tool-calls")


def test_project_window_close_discard_drops_edits(window, seeded, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox

    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    before = seeded.read_notes("lfm3-tool", "tool-calls")
    proj_win.notes_edit.setPlainText("throw this away")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Discard
    )
    assert proj_win.close() is True
    assert seeded.read_notes("lfm3-tool", "tool-calls") == before


def test_project_window_close_cancel_keeps_edits(window, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox

    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    proj_win.notes_edit.setPlainText("keep me here")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel
    )
    assert proj_win.close() is False
    assert proj_win.isVisible()
    assert proj_win.notes_edit.toPlainText() == "keep me here"
    # Tidy up: discard, so the fixture teardown never prompts.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Discard
    )
    assert proj_win.close() is True


def test_project_window_no_prompt_when_clean(window, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox

    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()

    def _no_prompt(*a, **k):
        raise AssertionError("no prompt when nothing changed")

    monkeypatch.setattr(QMessageBox, "question", _no_prompt)
    assert proj_win.close() is True


def test_profile_window_close_prompts_and_saves(window, seeded, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox

    prof_win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert not prof_win.is_modified()
    prof_win.role_combo.setCurrentText("reviewer")
    assert prof_win.is_modified()
    assert prof_win.windowTitle().endswith("*")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Save
    )
    assert prof_win.close() is True
    assert seeded.get_profile("lfm3-tool")["role"] == "reviewer"


def test_notes_marker_and_save_notes_only(window, seeded, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox

    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert proj_win.notes_section.title == "Project notes"
    proj_win.notes_edit.setPlainText("just the notes")
    proj_win.display_edit.setText("Renamed in the form")
    assert proj_win.notes_section.title == "Project notes (modified)"
    assert proj_win.save_notes() is True
    assert proj_win.notes_section.title == "Project notes"
    assert "just the notes" in seeded.read_notes("lfm3-tool", "tool-calls")
    # Save notes touches only the notes: the display-name edit is
    # still unsaved (and the window still shows it as modified).
    assert seeded.get_project("lfm3-tool", "tool-calls")["display_name"] != (
        "Renamed in the form"
    )
    assert proj_win.is_modified()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Discard
    )
    proj_win.close()


def test_edits_survive_train_finish(window, seeded, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox

    # Pin: the completion refresh never reloads an open Project
    # window, so edits made during a run survive the run finishing.
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    proj_win.notes_edit.setPlainText("notes typed during the run")
    window.set_session("lfm3-tool", "tool-calls")
    window._on_train_finished(True, "Trained 3 steps.")
    qapp.processEvents()
    assert proj_win.notes_edit.toPlainText() == "notes typed during the run"
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Discard
    )
    proj_win.close()


def test_rename_project_prompts_on_dirty_window(window, seeded, monkeypatch, qapp):
    from PySide6.QtWidgets import QMessageBox, QInputDialog

    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    proj_win.notes_edit.setPlainText("save me before the rename")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel
    )
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("renamed", True)
    )
    window.rename_project("lfm3-tool", "tool-calls")
    # Cancelled: the rename never happened.
    assert seeded.get_project("lfm3-tool", "tool-calls")["name"] == "tool-calls"
    # Save, then the rename proceeds with the edits saved.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Save
    )
    window.rename_project("lfm3-tool", "tool-calls")
    assert "renamed" in [
        p["name"] for p in seeded.list_projects("lfm3-tool")
    ]
    assert "save me before the rename" in seeded.read_notes(
        "lfm3-tool", "renamed"
    )
    assert proj_win.project == "renamed"


# -- T8: Start training is gated on a clean save ---------------------


def test_start_training_refused_on_unsaved_edits_in_open_window(
    window, seeded, monkeypatch, qapp
):
    """T8, kept for the fields the window still shows (T16 took the
    learning-rate field away): an open Project window with unsaved
    edits stops the start when the user says wait (Cancel)."""
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    proj_win.dataset_edit.setText("other-data.jsonl")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel
    )
    window.start_training()
    qapp.processEvents()
    # No worker started: nothing trains on stale edits.
    assert window._train_worker is None
    assert "Starting training" not in window.train_log.toPlainText()
    # The form still holds the edit, for the user to deal with.
    assert proj_win.dataset_edit.text() == "other-data.jsonl"
    assert proj_win.isVisible()


def test_start_training_saves_dirty_window_then_starts(
    window, seeded, monkeypatch, qapp, tmp_path
):
    from PySide6.QtWidgets import QMessageBox

    import stella.gui as gui_mod
    import stella.train as train_mod

    _select_session(window)
    # T83: the pre-train check blocks a missing dataset, so the
    # file the form points at must exist — a real dataset in the
    # store home, where the resolver looks.
    (seeded.home / "new-data.jsonl").write_text(
        "".join(
            json.dumps({"prompt": f"Q{i}?", "completion": f"A{i}."}) + "\n"
            for i in range(20)
        )
    )
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    proj_win.dataset_edit.setText("new-data.jsonl")
    # R67: the seeded profile is role fast, so the governing-seat
    # question fires after the save prompt — Save for the save,
    # Yes for the seat.
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: (
            QMessageBox.Yes
            if a[1].startswith("Train a governing seat")
            else QMessageBox.Save
        ),
    )
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(window, "_weights_offer", lambda profile: True)
    monkeypatch.setattr(gui_mod.TrainWorker, "run", lambda self: None)
    window.start_training()
    qapp.processEvents()
    # The edits were saved first, then the worker started on them.
    assert seeded.get_project("lfm3-tool", "tool-calls")["dataset_ref"] == (
        "new-data.jsonl"
    )
    assert window._train_worker is not None
    assert "Starting training" in window.train_log.toPlainText()


def test_sample_dataset_without_project_warns_and_claims_nothing(
    window, monkeypatch, qapp
):
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    assert window._current_profile is None
    window.use_sample_dataset()
    assert warnings == ["Pick a project first."]
    assert "Save is done" not in window.train_log.toPlainText()
    assert "Dataset set" not in window.train_log.toPlainText()


# -- T12: soft tag validation -----------------------------------------


def test_create_profile_warns_on_uninstalled_tag(
    window, seeded, monkeypatch, seed_models
):
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    seed_models(["lfm3:1.7b"])
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes,
    )
    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("not-a-real-model:99")
    window._create_profile_from(dialog)
    assert len(asked) == 1
    assert "not installed locally" in asked[0]
    # Warned, not blocked: the user proceeded and the profile exists.
    assert seeded.get_profile("not-a-real-model-99")["ollama_tag"] == (
        "not-a-real-model:99"
    )


def test_create_profile_warns_then_cancel_keeps_nothing(
    window, seeded, monkeypatch, seed_models
):
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    seed_models(["lfm3:1.7b"])
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )
    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("not-a-real-model:99")
    window._create_profile_from(dialog)
    assert [p["name"] for p in seeded.list_profiles()] == ["lfm3-tool"]


def test_create_profile_duplicate_tag_note(
    window, seeded, monkeypatch, seed_models
):
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    seed_models(["lfm3:1.7b"])
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes,
    )
    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("lfm3:1.7b")
    window._create_profile_from(dialog)
    assert len(asked) == 1
    assert "already uses this tag" in asked[0]
    assert "lfm3-tool" in asked[0]
    assert "not installed" not in asked[0]
    assert seeded.get_profile("lfm3-1-7b")["ollama_tag"] == "lfm3:1.7b"


def test_create_profile_installed_tag_no_warning(
    window, seeded, monkeypatch, seed_models
):
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    seed_models(["lfm3:1.7b", "qwen3.5:4b"])

    def _no_prompt(*a, **k):
        raise AssertionError("no warning for an installed, unused tag")

    monkeypatch.setattr(QMessageBox, "question", _no_prompt)
    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("qwen3.5:4b")
    window._create_profile_from(dialog)
    assert seeded.get_profile("qwen3-5-4b")["ollama_tag"] == "qwen3.5:4b"


def test_profile_save_warns_on_uninstalled_tag(
    window, seeded, monkeypatch, qapp, seed_models
):
    from PySide6.QtWidgets import QMessageBox

    seed_models(["lfm3:1.7b"])
    prof_win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    prof_win.tag_combo.setCurrentText("typo-model:99")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )
    assert prof_win.save() is False
    assert seeded.get_profile("lfm3-tool")["ollama_tag"] == "lfm3:1.7b"
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    assert prof_win.save() is True
    assert seeded.get_profile("lfm3-tool")["ollama_tag"] == "typo-model:99"
    prof_win.close()


# -- T13: the live training log survives the finish ------------------


def test_train_log_survives_finish_refresh(window, seeded):
    _select_session(window)
    window._train_log_line("step 1/3 loss 2.1000")
    window._train_log_line("step 2/3 loss 2.0500")
    window._on_train_finished(True, "Trained 3 steps.")
    text = window.train_log.toPlainText()
    assert "step 1/3 loss 2.1000" in text
    assert "step 2/3 loss 2.0500" in text
    assert "Trained 3 steps." in text


def test_train_log_jsonl_renders_friendly(window, seeded):
    import json

    log_path = (
        seeded.project_dir("lfm3-tool", "tool-calls") / "train_log.jsonl"
    )
    records = [
        {"step": 1, "total_steps": 3, "epoch": 1, "loss": 2.1, "lr": 0.0002},
        {"step": 2, "total_steps": 3, "epoch": 1, "loss": 2.05, "lr": 0.0002},
        {"step": 2, "epoch": 1, "val_loss": 1.9},
        # A legacy record, written before the total was recorded.
        {"step": 3, "epoch": 1, "loss": 2.0, "lr": 0.0002},
    ]
    log_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    _select_session(window)
    text = window.train_log.toPlainText()
    assert "step 1/3 loss 2.1000" in text
    assert "step 2/3 loss 2.0500" in text
    assert "epoch 1 validation loss 1.9000" in text
    assert "step 3 loss 2.0000" in text
    assert "{" not in text
    assert "}" not in text


def test_friendly_log_line_passthrough():
    from stella.gui import _friendly_log_line

    assert _friendly_log_line("Starting training...") == "Starting training..."
    assert _friendly_log_line("not json {") == "not json {"
    assert (
        _friendly_log_line('{"step": 1, "loss": 2.5}')
        == "step 1 loss 2.5000"
    )


# -- T25: re-training a trained project asks first --------------------


def _start_training_ready(window, monkeypatch):
    """Deps present, weights present, worker neutered — start_training
    reaches worker creation without training anything."""
    import stella.gui as gui_mod
    import stella.train as train_mod

    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(window, "_weights_offer", lambda profile: True)
    monkeypatch.setattr(gui_mod.TrainWorker, "run", lambda self: None)


def test_start_training_on_done_project_asks_first(
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    seeded.update_project("lfm3-tool", "tool-calls", status="done")
    # T83: the pre-train check blocks a missing dataset — the
    # seeded ref points at a file that does not exist, so the
    # sample stands in (the question under test is the re-train
    # ask, not the dataset).
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No,
    )
    window.start_training()
    qapp.processEvents()
    assert len(asked) == 1
    assert "already finished training" in asked[0]
    assert "current adapter will be replaced" in asked[0]
    # "No" stops the start: no worker, nothing trained.
    assert window._train_worker is None


def test_start_training_on_done_project_yes_forces(
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    seeded.update_project("lfm3-tool", "tool-calls", status="done")
    # T83: a valid dataset, so the pre-train check passes and the
    # re-train question is the only gate.
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    _start_training_ready(window, monkeypatch)
    window.start_training()
    qapp.processEvents()
    assert window._train_worker is not None
    assert window._train_worker._force is True


def test_start_training_on_draft_project_asks_only_the_seat(
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    assert seeded.get_project("lfm3-tool", "tool-calls")["status"] != "done"
    # T83: a valid dataset, so the pre-train check passes and no
    # question is asked at all.
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes,
    )
    _start_training_ready(window, monkeypatch)
    window.start_training()
    qapp.processEvents()
    # R67: the re-train question is not asked on a draft — but the
    # governing-seat question is (the seeded profile is role
    # fast), and Yes proceeds.
    assert len(asked) == 1
    assert "already finished training" not in asked[0]
    assert "fast seat" in asked[0]
    assert window._train_worker is not None
    assert window._train_worker._force is False


# -- v0.11.0: the UI rebuild (T15-T20) ---------------------------------

# -- T15: the bento main screen ---------------------------------------


def test_hero_no_job_picked_by_default(window):
    """U6: select nothing by default — no job is picked, Go waits."""
    assert window._picked_job() is None
    for button in window.job_buttons.values():
        assert not button.isChecked()
    assert not window.go_btn.isEnabled()


def test_job_pick_is_exclusive(window):
    window.job_buttons["train"].click()
    assert window.job_buttons["train"].isChecked()
    assert window._picked_job() == "train"
    window.job_buttons["sleep"].click()
    assert not window.job_buttons["train"].isChecked()
    assert window.job_buttons["sleep"].isChecked()
    assert window._picked_job() == "sleep"


def test_go_disabled_without_model(window):
    # A job pick alone is not enough: no model, no Go.
    window.job_buttons["train"].click()
    assert not window.go_btn.isEnabled()


def test_model_combo_sets_session(window, seeded, qapp):
    seeded.create_profile(
        "qwen3-vision", ollama_tag="qwen3-vl:2b-instruct",
        display_name="Qwen3 Vision",
    )
    window.refresh_session()
    qapp.processEvents()
    assert window.model_combo.count() == 2
    window.model_combo.setCurrentIndex(1)
    qapp.processEvents()
    assert window._current_profile == "qwen3-vision"
    assert window._current_project is None
    assert window.tree.currentItem() is not None


def test_go_train_starts_training(window, monkeypatch, qapp):
    import stella.gui as gui_mod
    import stella.train as train_mod

    _select_session(window)
    window._checklist_dismiss()
    # T83: a valid dataset, so the pre-train check passes.
    window.store.update_project(
        "lfm3-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(window, "_weights_offer", lambda profile: True)
    monkeypatch.setattr(gui_mod.TrainWorker, "run", lambda self: None)
    # R67: the seeded profile is role fast, so the governing-seat
    # question fires — Yes proceeds.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    window.job_buttons["train"].click()
    assert window.go_btn.isEnabled()
    window.go_btn.click()
    qapp.processEvents()
    assert window._train_worker is not None
    assert "Starting training" in window.train_log.toPlainText()
    # Go is disabled while the job runs.
    assert not window.go_btn.isEnabled()


def test_go_sleep_starts_sleep(window, monkeypatch, qapp):
    import stella.gui as gui_mod
    import stella.train as train_mod

    _select_session(window)
    window._checklist_dismiss()
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(window, "_weights_offer", lambda profile: True)
    monkeypatch.setattr(gui_mod.SleepWorker, "run", lambda self: None)
    window.job_buttons["sleep"].click()
    window.go_btn.click()
    qapp.processEvents()
    assert window._sleep_worker is not None
    assert "Starting sleep cycle..." in window.train_log.toPlainText()


def test_go_with_no_project_asks_for_name_inline(
    window, seeded, qapp, monkeypatch
):
    """T15 + T113: project creation is part of the pick — an inline
    name row, not a second window."""
    warned = []
    monkeypatch.setattr(window, "_warn", lambda msg: warned.append(msg))
    window.set_session("lfm3-tool", None)
    window._checklist_dismiss()
    qapp.processEvents()
    window.job_buttons["train"].click()
    window.go_btn.click()
    qapp.processEvents()
    # No project yet: the name row appears inline, nothing created.
    assert window.project_name_row.isVisible()
    assert len(seeded.list_projects("lfm3-tool")) == 1
    window.project_name_edit.setText("my-first")
    window.go_btn.click()
    qapp.processEvents()
    # The second Go press creates the project — then asks for
    # examples, inline too (a new project has no dataset).
    data = seeded.get_project("lfm3-tool", "my-first")
    assert data["name"] == "my-first"
    assert window.dataset_prompt_row.isVisible()
    assert not window.project_name_row.isVisible()
    window.dataset_sample_btn.click()
    qapp.processEvents()
    data = seeded.get_project("lfm3-tool", "my-first")
    assert data["dataset_ref"] == "sample-tool-calls.jsonl"
    # The sample is set, so Go pressed on: training starts, and
    # the sandbox has no training packages, so it logs the hint
    # and warns (T49) instead of starting.
    assert "install-training.sh" in window.train_log.toPlainText()
    assert warned and "install-training.sh" in warned[0]


def test_go_requant_runs(window, monkeypatch, qapp):
    """Make smaller runs with no typing: defaults, log lines."""
    from PySide6.QtTest import QTest

    import stella.requant as requant_mod

    def _fake_requant(tag, **kwargs):
        assert tag == "lfm3:1.7b"
        return {
            "source_tag": "lfm3:1.7b",
            "source_bytes": 2_000_000_000,
            "source_quant": "Q4_K_M",
            "new_tag": "lfm3:1.7b-q4_k_m",
            "quant": "Q4_K_M",
            "output_bytes": 1_900_000_000,
            "ollama_run": "ollama run lfm3:1.7b-q4_k_m",
        }

    monkeypatch.setattr(requant_mod, "requant_model", _fake_requant)
    _select_session(window)
    window._checklist_dismiss()
    window.job_buttons["requant"].click()
    window.go_btn.click()
    qapp.processEvents()
    for _ in range(100):
        if "Made a smaller copy" in window.train_log.toPlainText():
            break
        QTest.qWait(50)
    log = window.train_log.toPlainText()
    assert "Making a smaller copy of lfm3:1.7b..." in log
    assert "Made a smaller copy: lfm3:1.7b-q4_k_m" in log
    assert "ollama run lfm3:1.7b-q4_k_m" in log


def test_go_distill_opens_dialog(window, qapp):
    """Teach a small model opens the one small dialog (teacher +
    prompts file); rejecting it starts nothing."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    _select_session(window)
    window._checklist_dismiss()

    def close_dialog():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        assert dlg.windowTitle() == "Teach a small model"
        dlg.reject()

    QTimer.singleShot(100, close_dialog)
    window.job_buttons["distill"].click()
    window.go_btn.click()
    qapp.processEvents()
    assert window._job_worker is None


def test_distill_dialog_needs_teacher_and_prompts(window, monkeypatch, seed_models):
    from PySide6.QtWidgets import QFileDialog

    from stella.gui import DistillDialog

    seed_models(["lfm3:1.7b", "qwen3.5:4b"])
    dialog = DistillDialog(window)
    assert dialog.start_btn.isEnabled() is False
    assert dialog.teacher_combo.currentIndex() == -1
    dialog.teacher_combo.setCurrentIndex(0)
    assert dialog.start_btn.isEnabled() is False  # no prompts yet
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *a, **k: ("/tmp/prompts.txt", ""),
    )
    dialog.prompts_btn.click()
    assert dialog.prompts_path() == "/tmp/prompts.txt"
    assert dialog.start_btn.isEnabled() is True
    dialog.close()


def test_distill_dialog_timeout_defaults_to_300(window, seed_models):
    """S3: the wait-per-answer control sits in the distill dialog
    (the job start), plain words, 300 seconds unless changed."""
    from stella.gui import DistillDialog

    seed_models(["lfm3:1.7b", "qwen3.5:4b"])
    dialog = DistillDialog(window)
    assert dialog.timeout() == 300
    labels = [
        w.text() for w in dialog.findChildren(QLabel)
    ]
    assert "How long to wait for each answer (seconds)" in labels
    dialog.timeout_spin.setValue(600)
    assert dialog.timeout() == 600
    dialog.close()


def test_distill_job_card_shows_prompt_progress(window, monkeypatch, qapp):
    """S21 GUI half, verified ALREADY DONE: the distill job card's
    bar moves with the prompt events (prompt N of M), and the log
    names each prompt. The dialog is stubbed (teacher + prompts +
    timeout), the engine is faked and emits three prompt events."""
    from PySide6.QtWidgets import QDialog

    import stella.distill as distill_mod
    import stella.gui as gui_mod

    class _FakeDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

        def teacher(self):
            return "qwen3.5:4b"

        def prompts_path(self):
            return "/tmp/prompts.txt"

        def timeout(self):
            return 300

    seen = {}

    def _fake_distill(store, profile, project, teacher, prompts,
                      **kwargs):
        seen.update(kwargs)
        on_event = kwargs["on_event"]
        for index in range(1, 4):
            on_event({
                "type": "prompt", "index": index, "total": 3,
                "prompt": f"prompt {index}",
            })
        return {
            "teacher": teacher, "prompts": 3, "asked": 3,
            "skipped_empty": 0, "skipped_dup": 0, "skipped_resumed": 0,
            "rows": 3, "dataset": "/tmp/x/distilled.jsonl",
        }

    monkeypatch.setattr(gui_mod, "DistillDialog", _FakeDialog)
    monkeypatch.setattr(distill_mod, "distill_dataset", _fake_distill)
    _select_session(window)
    window._checklist_dismiss()
    window._start_distill()
    assert window.job_card.title_label.text() == "Teaching a small model"
    _wait_for_job(window, qapp)
    # The bar reached 3 of 3, and the log named the prompts.
    assert window.job_card.progress.maximum() == 3
    assert window.job_card.progress.value() == 3
    log = window.train_log.toPlainText()
    assert "Asking the teacher: prompt 2 of 3." in log
    assert "Distilled 3 examples from qwen3.5:4b" in log
    # S3: the dialog's timeout reached the engine.
    assert seen["timeout"] == 300


# -- T16: settings leave every screen ---------------------------------


def test_no_settings_strings_in_any_visible_text(window, qapp):
    """T16 Done: no rank, learning rate, epochs, batch size, or
    sequence length string visible anywhere in the UI."""
    _select_session(window)
    project_win = window.open_project_window("lfm3-tool", "tool-calls")
    profile_win = window.open_profile_window("lfm3-tool")
    settings_win = window.open_settings_window()
    howto_win = window.open_howto_window()
    chat = window.open_chat_window()
    qapp.processEvents()
    texts = _visible_texts(window)
    assert texts, "no visible strings collected at all"
    for text in texts:
        lowered = text.lower()
        for word in (
            "rank",
            "learning rate",
            "epochs",
            "batch size",
            "sequence length",
        ):
            assert word not in lowered, f"{word!r} visible: {text!r}"
    # Every How to Use topic, not just the selected one.
    from stella.howto import TOPICS

    for title, body in TOPICS:
        lowered = body.lower()
        for word in (
            "rank",
            "learning rate",
            "epochs",
            "batch size",
            "sequence length",
        ):
            assert word not in lowered, f"{word!r} in How to Use: {title}"
    project_win.close()
    profile_win.close()
    settings_win.close()
    howto_win.close()
    chat.close()


# -- T17: first-run setup checklist -----------------------------------


def _empty_window(qapp, store, settings):
    from stella.gui import MainWindow

    win = MainWindow(store=store, settings=settings)
    win.show()
    qapp.processEvents()
    return win


def test_empty_store_shows_checklist(qapp, store, settings):
    win = _empty_window(qapp, store, settings)
    assert win.checklist_widget.isVisible()
    assert not win.bento_widget.isVisible()
    titles = [
        w.text() for w in win.checklist_widget.findChildren(QLabel)
    ]
    assert "First steps" in titles
    # Step 1 is the only one open; the rest unlock in order.
    assert win.check_steps[0][1].isEnabled()
    assert not win.check_steps[1][1].isEnabled()
    assert not win.check_steps[2][1].isEnabled()
    # The misleading old text is gone.
    assert "pick a project in the list" not in win.session_summary.text()
    win.close()


def test_checklist_steps_tick_as_setup_progresses(
    qapp, store, settings, monkeypatch
):
    import stella.gui as gui_mod

    win = _empty_window(qapp, store, settings)
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    win.refresh_session()
    qapp.processEvents()
    assert win.check_steps[0][0].text() == "✓"
    assert win.check_steps[1][1].isEnabled()
    assert not win.check_steps[2][1].isEnabled()
    # Weights ready: step 2 ticks, step 3 opens.
    monkeypatch.setattr(
        gui_mod.provision, "weights_status",
        lambda s, profile: {
            "repo": "test/repo", "state": "ready",
            "size_bytes": 2_000_000_000, "path": "/tmp/weights",
        },
    )
    win.refresh_session()
    qapp.processEvents()
    assert win.check_steps[1][0].text() == "✓"
    assert win.check_steps[2][1].isEnabled()
    # A finished project ticks step 3 and the checklist is done:
    # the bento shows, and the checklist never comes back.
    store.create_project("lfm3-tool", "tool-calls")
    store.update_project("lfm3-tool", "tool-calls", status="done")
    win.refresh_session()
    qapp.processEvents()
    assert not win.checklist_widget.isVisible()
    assert win.bento_widget.isVisible()
    assert settings.value("checklist/done") in (True, "true")
    win.close()


def test_checklist_dismiss_never_returns(qapp, store, settings):
    win = _empty_window(qapp, store, settings)
    assert win.checklist_widget.isVisible()
    win.check_dismiss_btn.click()
    qapp.processEvents()
    assert not win.checklist_widget.isVisible()
    assert win.bento_widget.isVisible()
    win.close()
    # A fresh window with the same settings still shows the bento.
    second = _empty_window(qapp, store, settings)
    assert not second.checklist_widget.isVisible()
    assert second.bento_widget.isVisible()
    second.close()


def test_checklist_hidden_while_job_runs(qapp, store, settings):
    from unittest.mock import Mock

    win = _empty_window(qapp, store, settings)
    assert win.checklist_widget.isVisible()
    # A running job always shows the bento, so the user can watch.
    worker = Mock()
    worker.isRunning.return_value = True
    win._train_worker = worker
    win._refresh_checklist()
    assert not win.checklist_widget.isVisible()
    assert win.bento_widget.isVisible()
    win._train_worker = None
    win._refresh_checklist()
    assert win.checklist_widget.isVisible()
    win.close()


def test_checklist_run_tiny_creates_project_and_starts(
    qapp, store, settings, monkeypatch
):
    import stella.gui as gui_mod

    win = _empty_window(qapp, store, settings)
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    monkeypatch.setattr(
        gui_mod.provision, "weights_status",
        lambda s, profile: {
            "repo": "test/repo", "state": "ready",
            "size_bytes": 2_000_000_000, "path": "/tmp/weights",
        },
    )
    win.refresh_session()
    qapp.processEvents()
    assert win.check_steps[2][1].isEnabled()
    warned = []
    monkeypatch.setattr(win, "_warn", lambda msg: warned.append(msg))
    win.check_steps[2][1].click()
    qapp.processEvents()
    # The tiny first training is a real run: a real project with
    # the sample dataset, and training started on it — the sandbox
    # has no training packages, so it logs the hint and warns
    # (T49) instead of starting.
    data = store.get_project("lfm3-tool", "first-steps")
    assert data["dataset_ref"] == "sample-tool-calls.jsonl"
    assert win._current_project == "first-steps"
    assert "install-training.sh" in win.train_log.toPlainText()
    assert warned and "install-training.sh" in warned[0]
    win.close()


# -- T18: model picker with fit guidance ------------------------------


def _patched_dialog(window, monkeypatch, seed_models):
    """A NewProfileDialog with two known models on a known PC."""
    import stella.gui as gui_mod

    from stella.gui import NewProfileDialog

    seed_models(
        ["lfm3:1.7b", "qwen3.5:8b"],
        {"lfm3:1.7b": 2_000_000_000, "qwen3.5:8b": 5_000_000_000},
    )
    monkeypatch.setattr(
        gui_mod, "measure_pc",
        lambda: {"ram_total_gb": 8.0, "ram_available_gb": 8.0},
    )
    return NewProfileDialog(window)


def test_new_profile_dialog_opens_with_no_selection(window, monkeypatch, seed_models):
    dialog = _patched_dialog(window, monkeypatch, seed_models)
    assert dialog.model_list.currentRow() == -1
    assert dialog.model_list.currentItem() is None
    assert dialog.name_note.text() == ""
    assert not dialog.details_label.isVisible()
    assert dialog.type_edit.text() == ""
    assert not dialog.picked_model()
    dialog.close()


def test_new_profile_dialog_rows_show_what_and_fit(window, monkeypatch, seed_models):
    dialog = _patched_dialog(window, monkeypatch, seed_models)
    assert dialog.model_list.count() == 2
    first = dialog.model_list.item(0).text()
    assert first.startswith("lfm3:1.7b\n")
    assert "Liquid AI" in first  # what it does
    assert "Fits this PC." in first  # fit verdict
    second = dialog.model_list.item(1).text()
    assert second.startswith("qwen3.5:8b\n")
    assert "Too big for this PC." in second
    dialog.close()


def test_new_profile_tap_shows_details(window, monkeypatch, qapp, seed_models):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog = _patched_dialog(window, monkeypatch, seed_models)
    dialog.show()
    qapp.processEvents()
    QTest.qWait(50)
    # A real tap on row 0 (R1): a programmatic setCurrentRow is
    # not a pick, so the test clicks like the user does.
    rect = dialog.model_list.visualItemRect(dialog.model_list.item(0))
    QTest.mouseClick(
        dialog.model_list.viewport(), Qt.LeftButton, pos=rect.center()
    )
    qapp.processEvents()
    assert dialog.details_label.isVisible()
    details = dialog.details_label.text()
    assert "4.4 GB" in details  # RAM to train
    assert "1.9 GB" in details  # download size
    assert dialog.name_note.text() == "Profile name: lfm3-1-7b"
    dialog.close()


def test_new_profile_dialog_shown_has_no_selection(
    window, monkeypatch, qapp, seed_models
):
    """R1: a SHOWN dialog has no row selected. Qt selects row 0
    by itself after show() — the dialog must undo that, and a
    refill landing afterwards must not re-select it either. The
    T18 tests never showed the dialog, which is why the suite
    stayed green on a false DONE."""
    from PySide6.QtTest import QTest

    dialog = _patched_dialog(window, monkeypatch, seed_models)
    dialog.show()
    qapp.processEvents()
    QTest.qWait(50)
    assert dialog.model_list.currentRow() == -1
    assert dialog.model_list.currentItem() is None
    assert not dialog.picked_model()
    assert dialog.name_note.text() == ""
    assert not dialog.details_label.isVisible()
    # A refill (the background refresh landing) does not re-pick.
    dialog._fill_model_list()
    qapp.processEvents()
    assert dialog.model_list.currentRow() == -1
    assert not dialog.picked_model()
    dialog.close()


def test_new_profile_keyboard_down_picks_a_row(
    window, monkeypatch, qapp, seed_models
):
    """R1: arrowing to a row IS a pick — the keyboard path sets
    the pick flag, so the details and the name note appear."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog = _patched_dialog(window, monkeypatch, seed_models)
    dialog.show()
    qapp.processEvents()
    QTest.qWait(50)
    assert not dialog.picked_model()
    dialog.model_list.setFocus()
    QTest.keyClick(dialog.model_list, Qt.Key_Down)
    qapp.processEvents()
    assert dialog.picked_model() == "lfm3:1.7b"
    assert dialog.name_note.text() == "Profile name: lfm3-1-7b"
    assert dialog.details_label.isVisible()
    dialog.close()


def test_new_profile_enter_with_no_pick_does_nothing(
    window, seeded, monkeypatch, qapp, seed_models
):
    """T18: Enter with nothing picked does nothing — no profile,
    no warning, no dialog accepted. R1: the dialog is SHOWN
    first, because Qt's auto-select only happens after show()."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest

    dialog = _patched_dialog(window, monkeypatch, seed_models)
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    dialog.show()
    qapp.processEvents()
    QTest.qWait(50)
    assert dialog.model_list.currentRow() == -1
    dialog.type_edit.returnPressed.emit()
    assert [p["name"] for p in seeded.list_profiles()] == ["lfm3-tool"]
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key_Return, Qt.KeyboardModifier.NoModifier
    )
    dialog.keyPressEvent(event)
    # The key is swallowed (accepted, not passed on to the default
    # button): nothing happens.
    assert event.isAccepted()
    assert warnings == []
    assert [p["name"] for p in seeded.list_profiles()] == ["lfm3-tool"]
    dialog.close()


# -- T19: real menu bar, actions disabled when they cannot work -------


def test_menu_actions_disabled_without_selection(qapp, store, settings):
    win = _empty_window(qapp, store, settings)
    assert win._menu_action_new_profile.isEnabled()
    assert not win._menu_action_new_project.isEnabled()
    assert not win._menu_action_export.isEnabled()
    assert win._menu_action_import.isEnabled()
    assert not win._menu_action_run.isEnabled()
    assert win._menu_action_settings.isEnabled()
    assert not win._menu_action_profiles.isEnabled()
    assert not win._menu_action_projects.isEnabled()
    assert win._menu_action_howto.isEnabled()
    assert win._menu_action_chat.isEnabled()
    win.close()


def test_menu_actions_enable_with_session(window, qapp):
    # A profile but no project: project actions wait.
    window.set_session("lfm3-tool", None)
    qapp.processEvents()
    assert window._menu_action_new_project.isEnabled()
    assert window._menu_action_profiles.isEnabled()
    assert not window._menu_action_export.isEnabled()
    assert not window._menu_action_projects.isEnabled()
    # A full session: everything works. Pick a job first: Run
    # mirrors Go, and Go needs a job picked (T82).
    _select_session(window)
    window.job_buttons["train"].click()
    qapp.processEvents()
    for action in (
        window._menu_action_new_profile,
        window._menu_action_new_project,
        window._menu_action_export,
        window._menu_action_import,
        window._menu_action_run,
        window._menu_action_settings,
        window._menu_action_profiles,
        window._menu_action_projects,
        window._menu_action_howto,
        window._menu_action_chat,
    ):
        assert action.isEnabled(), action.text()


# -- T20: live training graphs and stats -------------------------------


def test_loss_curve_draws_points(window, qapp):
    _select_session(window)
    window._checklist_dismiss()
    window._on_train_progress(5, 20, 2.5, 1)
    window._on_train_progress(10, 20, 2.0, 1)
    assert window.loss_curve.points == [(5, 2.5), (10, 2.0)]
    # It paints, not just stores: grab a real frame.
    pixmap = window.loss_curve.grab()
    assert not pixmap.isNull()
    assert pixmap.width() > 0
    assert pixmap.height() > 0


def test_run_stats_update_with_progress(window):
    _select_session(window)
    assert window.stat_speed.text() == "Speed: not started"
    assert window.stat_ram.text() == "RAM: not started"
    assert window.stat_time_left.text() == "Time left: not started"
    assert window.stat_epoch.text() == "Epoch: not started"
    window._on_train_progress(5, 20, 2.5, 1)
    window._on_train_progress(10, 20, 2.0, 1)
    assert "steps a minute" in window.stat_speed.text()
    assert "GB used" in window.stat_ram.text()
    assert "Time left: about" in window.stat_time_left.text()
    assert window.stat_epoch.text() == "Epoch 1"


def test_last_run_curve_rebuilds_from_log(window, seeded, qapp):
    import json

    log_path = seeded.project_dir("lfm3-tool", "tool-calls") / "train_log.jsonl"
    records = [
        {"step": 1, "total_steps": 3, "epoch": 1, "loss": 2.5, "lr": 0.0002},
        {"step": 2, "total_steps": 3, "epoch": 1, "loss": 2.0, "lr": 0.0002},
        {"step": 2, "epoch": 1, "val_loss": 1.9},  # val: skipped
        {"step": 3, "total_steps": 3, "epoch": 1, "loss": 1.8, "lr": 0.0002},
    ]
    log_path.write_text(
        "".join(json.dumps(r) + "\n" for r in records)
    )
    _select_session(window)
    qapp.processEvents()
    assert window.loss_curve.points == [(1, 2.5), (2, 2.0), (3, 1.8)]
    # Switch away: the curve clears (no log there). Switch back:
    # the last run's curve is still there.
    seeded.create_project("lfm3-tool", "second")
    window.set_session("lfm3-tool", "second")
    qapp.processEvents()
    assert window.loss_curve.points == []
    window.set_session("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert window.loss_curve.points == [(1, 2.5), (2, 2.0), (3, 1.8)]


def test_finished_run_keeps_curve(window, qapp):
    _select_session(window)
    window._on_train_progress(5, 20, 2.5, 1)
    window._on_train_progress(10, 20, 2.0, 1)
    window._on_train_finished(True, "Training done.")
    qapp.processEvents()
    assert window.loss_curve.points == [(5, 2.5), (10, 2.0)]
    assert "Step 10 / 20" in window.train_loss.text()
    assert window.stat_time_left.text() == "Time left: done"


def test_loss_curve_widget_unit(qapp):
    from stella.gui import LossCurveWidget

    widget = LossCurveWidget()
    widget.show()
    qapp.processEvents()
    assert widget.points == []
    widget.append_point(1, 2.0, 10)
    widget.append_point(2, 1.9, 10)
    assert widget.points == [(1, 2.0), (2, 1.9)]
    # A step decrease starts a new run: the old curve is replaced.
    widget.append_point(1, 2.1, 10)
    assert widget.points == [(1, 2.1)]
    widget.set_points([(1, 2.5), (2, 2.0)], 3)
    assert widget.points == [(1, 2.5), (2, 2.0)]
    widget.clear()
    assert widget.points == []
    widget.close()


# -- v0.12.0: UI REBUILD P1 (T74-T82) -----------------------------------


def test_job_card_shows_progress_and_cancel(window, qapp):
    """T74: every job runs as a card with progress and Cancel."""
    import time

    from PySide6.QtTest import QTest

    from stella.model import StellaError

    window._checklist_dismiss()
    _select_session(window)
    window.job_buttons["train"].click()
    assert window.go_btn.isEnabled()
    assert window.job_card.isVisible() is False

    def job(ctx):
        for i in range(1, 11):
            if ctx.is_cancelled():
                raise StellaError("Cancelled.")
            ctx.progress(i, 10)
            ctx.log(f"Working: step {i} of 10.")
            time.sleep(0.05)
        return "All done."

    window._start_job_worker(job, "A test job", True)
    # Poll for the status: worker threads are slow under sandbox
    # load, and a fixed short wait flakes (same as _wait_for_text).
    deadline = 0
    while "Working: step" not in window.job_card.status_label.text():
        QTest.qWait(100)
        deadline += 100
        assert deadline < 10000
    assert window.job_card.isVisible()
    assert window.job_card.title_label.text() == "A test job"
    assert window.job_card.progress.value() > 0
    assert window.job_card.cancel_btn.isEnabled()
    # Go and the other job buttons refuse a second job while one runs.
    assert window.go_btn.isEnabled() is False
    assert window.train_export_gguf_btn.isEnabled() is False
    assert window.train_probe_btn.isEnabled() is False
    window.job_card.cancel_btn.click()
    deadline = 0
    while window.job_card.isVisible():
        QTest.qWait(100)
        deadline += 100
        assert deadline < 10000
    assert "Cancelled" in window.train_log.toPlainText()
    assert window._job_worker.isRunning() is False


def test_second_job_is_refused_in_plain_words(window, monkeypatch, qapp):
    """T74: starting a second job is refused, not queued."""
    import time

    from PySide6.QtTest import QTest

    _select_session(window)
    said = []
    monkeypatch.setattr(window, "_say", said.append)

    def job(ctx):
        for _ in range(40):
            if ctx.is_cancelled():
                return "stopped"
            time.sleep(0.05)
        return "done"

    window._start_job_worker(job, "A long job", False)
    first = window._job_worker
    assert first.isRunning()
    # Export refuses before it even asks for a folder.
    window.export_gguf_gui()
    assert window._job_worker is first
    assert any("already running" in s for s in said)
    assert any("cancel it first" in s for s in said)
    window.job_card.cancel_btn.click()
    QTest.qWait(500)


def test_train_refused_while_job_runs_and_names_it(window, monkeypatch, qapp):
    """T29: training refuses while a job-card job runs, naming it —
    the train-vs-job hole (A8-W7): start_training used to check
    train/sleep only, so a probe could load models beside a run."""
    import time

    from PySide6.QtTest import QTest

    _select_session(window)
    said = []
    monkeypatch.setattr(window, "_say", said.append)

    def job(ctx):
        for _ in range(40):
            if ctx.is_cancelled():
                return "stopped"
            time.sleep(0.05)
        return "done"

    window._start_job_worker(job, "Refusal probe", True)
    assert window._job_worker.isRunning()
    window.start_training()
    assert window._train_worker is None
    assert any("Refusal probe is already running" in s for s in said)
    window.job_card.cancel_btn.click()
    QTest.qWait(500)


def test_install_training_button_runs_install_with_progress(
    window, monkeypatch, qapp
):
    """R13: the Install training button runs the training install
    as a job, streaming its lines to the Train log — no terminal."""
    from PySide6.QtTest import QTest

    import stella.train as train_mod

    assert window.install_training_btn.text() == "Install training"
    assert window.install_training_btn.isEnabled()

    def fake_install(*, on_line=None, should_stop=None, script=None):
        on_line("Installing the training packages...")
        on_line("Training packages are already installed.")

    monkeypatch.setattr(train_mod, "run_training_install", fake_install)
    window.install_training_btn.click()
    _wait_for_job(window, qapp)
    log = window.train_log.toPlainText()
    assert "Installing the training packages..." in log
    assert "Training packages are already installed." in log
    assert "Training installed." in window.statusBar().currentMessage()


def test_install_training_button_disabled_while_job_runs(
    window, monkeypatch, qapp
):
    """R13: Install training is off while a job runs — one job at
    a time, like every other job button."""
    import time

    from PySide6.QtTest import QTest

    assert window.install_training_btn.isEnabled()

    def job(ctx):
        for _ in range(40):
            if ctx.is_cancelled():
                return "stopped"
            time.sleep(0.05)
        return "done"

    window._start_job_worker(job, "A long job", False)
    assert window._job_worker.isRunning()
    window._refresh_go()
    assert not window.install_training_btn.isEnabled()
    window.job_card.cancel_btn.click()
    QTest.qWait(500)
    window._refresh_go()
    assert window.install_training_btn.isEnabled()


def test_probe_refused_while_export_runs(window, monkeypatch, qapp):
    """T29: the probe refuses while an export runs — starting a
    second job never overwrites the running worker."""
    import time

    from PySide6.QtTest import QTest

    _select_session(window)
    said = []
    monkeypatch.setattr(window, "_say", said.append)

    def job(ctx):
        for _ in range(40):
            if ctx.is_cancelled():
                return "stopped"
            time.sleep(0.05)
        return "done"

    window._start_job_worker(job, "Exporting GGUF", False)
    first = window._job_worker
    assert first.isRunning()
    window.run_probe_gui()
    assert window._job_worker is first
    assert any("Exporting GGUF is already running" in s for s in said)
    window.job_card.cancel_btn.click()
    QTest.qWait(500)


def test_start_job_worker_itself_refuses_a_second_job(window, qapp):
    """T29: even a direct _start_job_worker call cannot orphan a
    running worker — the guard lives in the starter, not just the
    callers."""
    import time

    from PySide6.QtTest import QTest

    _select_session(window)

    def job(ctx):
        for _ in range(40):
            if ctx.is_cancelled():
                return "stopped"
            time.sleep(0.05)
        return "done"

    assert window._start_job_worker(job, "A long job", False) is True
    first = window._job_worker
    assert window._start_job_worker(job, "Another job", False) is False
    assert window._job_worker is first
    window.job_card.cancel_btn.click()
    QTest.qWait(500)


def test_close_during_job_waits_with_feedback_and_closes(window, qapp):
    """T36: closing mid-job shows Stopping feedback, waits for the
    worker to end, and closes cleanly — no 15-second freeze, no
    destroyed thread."""
    import time

    from PySide6.QtTest import QTest

    _select_session(window)

    def job(ctx):
        for _ in range(200):
            if ctx.is_cancelled():
                return "stopped"
            time.sleep(0.05)
        return "done"

    window._start_job_worker(job, "A long job", False)
    assert window._job_worker.isRunning()
    assert window.close() is False  # ignored: a job is running
    assert window.isVisible()
    assert "Stopping" in window.statusBar().currentMessage()
    deadline = 0
    while window.isVisible() and deadline < 10000:
        QTest.qWait(100)
        deadline += 100
    assert not window.isVisible()
    assert window._job_worker.isRunning() is False


def test_teardown_wait_waits_for_a_running_job(window, qapp):
    """R74: the teardown wait really waits — a job still running
    when the wait starts is finished when it returns. Before the
    fix, teardown was just win.close(), which closeEvent ignores
    while a job runs (T36), so a test that forgot _wait_for_job
    leaked its worker into the next test."""
    import time

    done = []

    def job(ctx):
        time.sleep(0.5)
        done.append(True)
        return "done"

    assert window._start_job_worker(job, "Slow job", True)
    assert window._job_worker.isRunning()
    assert window.close() is False  # ignored mid-job: the leak's cause
    _wait_for_all_workers(window, qapp)
    assert done == [True]
    assert not window._job_worker.isRunning()


def test_close_during_job_subprocess_no_destroyed_thread(tmp_path):
    """T36: closing mid-job in a separate process exits 0 with no
    destroyed-thread warning on stderr."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    home = tmp_path / "home"
    res = subprocess.run(
        [sys.executable, str(root / "tests" / "_close_driver.py"), str(home)],
        cwd=root, env=dict(os.environ), capture_output=True, text=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert "Destroyed while thread" not in res.stderr


def test_requant_runs_as_a_job_card(window, monkeypatch, qapp):
    """T74/T75: Make smaller runs as a card with a title."""
    from PySide6.QtTest import QTest

    import stella.requant as requant_mod

    def _fake_requant(tag, **kwargs):
        return {
            "source_tag": "lfm3:1.7b",
            "source_bytes": 2_000_000_000,
            "source_quant": "Q4_K_M",
            "new_tag": "lfm3:1.7b-q4_k_m",
            "quant": "Q4_K_M",
            "output_bytes": 1_900_000_000,
            "ollama_run": "ollama run lfm3:1.7b-q4_k_m",
        }

    monkeypatch.setattr(requant_mod, "requant_model", _fake_requant)
    _select_session(window)
    window._checklist_dismiss()
    window.job_buttons["requant"].click()
    window.go_btn.click()
    deadline = 0
    while "Made a smaller copy" not in window.train_log.toPlainText():
        QTest.qWait(100)
        deadline += 100
        assert deadline < 5000
    assert window.job_card.title_label.text() == "Making a smaller copy"
    # The finish moment (T145) keeps the card visible for 250 ms
    # after the log line, so wait for it to hide.
    deadline = 0
    while window.job_card.isVisible():
        QTest.qWait(100)
        deadline += 100
        assert deadline < 5000
    assert window.job_card.isVisible() is False


class PlanningFakeChatAgent(FakeChatAgent):
    """Shows a plan on the first message, runs it on approval."""

    def __init__(self):
        super().__init__()
        self.pending_plan = None

    def reply(self, text):
        self.received.append(text)
        if text == "Go ahead":
            self.pending_plan = None
            self.last_streamed_plain = ""
            return "Running the plan."
        self.pending_plan = ["Use the LFM3 profile.", "Train it."]
        self.last_streamed_plain = ""
        return "I will:\n1. Use the LFM3 profile.\n2. Train it."


def test_chat_plan_row_shows_run_and_cancel(window, qapp):
    """T76: the plan shows with Run and Cancel buttons; Run sends
    the approval, and the plan row goes away."""
    from stella.gui import ChatWindow

    window.set_chat_model("lfm3:1.7b")
    fake = PlanningFakeChatAgent()
    chat = ChatWindow(window, agent_factory=lambda: fake)
    chat.show()
    qapp.processEvents()
    assert chat.plan_row.isVisible() is False
    chat.input.setText("just do it")
    chat.send_btn.click()
    assert _wait_for_text(chat, "I will:", qapp)
    assert chat.plan_row.isVisible()
    assert chat.plan_run_btn.text() == "Run"
    assert chat.plan_cancel_btn.text() == "Cancel"
    chat.plan_run_btn.click()
    assert _wait_for_text(chat, "Running the plan.", qapp)
    assert fake.received == ["just do it", "Go ahead"]
    assert chat.plan_row.isVisible() is False
    chat.close()


class StreamingFakeChatAgent(FakeChatAgent):
    """Streams its reply token by token, like a real model."""

    def __init__(self):
        super().__init__("Streamed reply here.")
        self._on_token = None
        self.last_streamed_plain = ""

    def set_callbacks(self, on_narration=None, on_progress=None,
                      on_token=None):
        self._on_token = on_token

    def reply(self, text):
        self.received.append(text)
        if self._on_token is not None:
            for chunk in ["Streamed ", "reply ", "here."]:
                self._on_token(chunk)
        self.last_streamed_plain = "Streamed reply here."
        return "Streamed reply here."


def test_chat_streams_tokens_without_doubling(window, qapp):
    """T76: replies stream as they arrive, shown once — the final
    reply does not re-append what already streamed."""
    from stella.gui import ChatWindow

    window.set_chat_model("lfm3:1.7b")
    fake = StreamingFakeChatAgent()
    chat = ChatWindow(window, agent_factory=lambda: fake)
    chat.show()
    qapp.processEvents()
    chat.input.setText("hello")
    chat.send_btn.click()
    assert _wait_for_text(chat, "Streamed reply here.", qapp)
    text = chat.messages.toPlainText()
    assert text.count("Streamed reply here.") == 1
    chat.close()


def test_session_follows_profile(window, seeded, qapp):
    """T77: switching profiles restores that profile's project."""
    seeded.create_profile(
        "qwen-2b", display_name="Qwen", ollama_tag="qwen:2b"
    )
    seeded.create_project("qwen-2b", "other-job")
    window.set_session("lfm3-tool", "tool-calls")
    window.set_session("qwen-2b", "other-job")
    assert window._current_project == "other-job"
    # Back to the first profile, project only: the project is back.
    window.set_session("lfm3-tool", None)
    assert window._current_profile == "lfm3-tool"
    assert window._current_project == "tool-calls"
    # And the other way: the second profile remembers its own.
    window.set_session("qwen-2b", None)
    assert window._current_profile == "qwen-2b"
    assert window._current_project == "other-job"


def test_session_memory_survives_new_window(qapp, seeded, settings):
    """T77: the per-profile memory lives in QSettings, so a new
    window remembers it too."""
    from stella.gui import MainWindow

    seeded.create_profile(
        "qwen-2b", display_name="Qwen", ollama_tag="qwen:2b"
    )
    seeded.create_project("qwen-2b", "other-job")
    first = MainWindow(store=seeded, settings=settings)
    first.show()
    qapp.processEvents()
    first.set_session("lfm3-tool", "tool-calls")
    first.set_session("qwen-2b", "other-job")
    first.close()
    second = MainWindow(store=seeded, settings=settings)
    second.show()
    qapp.processEvents()
    # The last session restores; switching profiles restores the
    # other profile's remembered project.
    assert second._current_profile == "qwen-2b"
    assert second._current_project == "other-job"
    second.set_session("lfm3-tool", None)
    assert second._current_project == "tool-calls"
    second.close()


def test_tree_pane_is_wider(window, qapp):
    """T78: the tree pane defaults wide enough for long names."""
    qapp.processEvents()
    assert window.splitter.sizes()[0] >= 300


def test_tree_rows_carry_full_text_tooltips(window):
    """T78: every row carries its full text as a tooltip, so a
    truncated name is still readable on hover."""
    top = window.tree.topLevelItem(0)
    assert top.toolTip(0).startswith(top.text(0))
    child = top.child(0)
    assert child.toolTip(0) == "tool-calls (draft) [forge-traces.jsonl]"


def test_profile_row_shows_health_badge(window, monkeypatch, qapp, seed_models):
    """T78: each profile row shows a health dot — green when the
    weights are ready, amber when they are not, grey when Ollama
    is down and the weights are not ready."""
    import stella.gui as gui_mod
    from PySide6.QtGui import QColor

    def badge_color():
        item = window.tree.topLevelItem(0)
        image = item.icon(0).pixmap(16, 16).toImage()
        return image.pixelColor(8, 8)

    def refresh_as(state, ollama_up):
        monkeypatch.setattr(
            gui_mod.provision, "weights_status",
            lambda store, slug: {
                "repo": "LiquidAI/LFM3-1.7B", "state": state,
                "size_bytes": 0, "path": None,
            },
        )
        # The badge reads Ollama-up from the model-list cache (T43).
        seed_models(
            ["lfm3:1.7b"] if ollama_up else [], ollama_up=ollama_up
        )
        window.refresh_tree()
        qapp.processEvents()

    refresh_as("ready", True)
    assert badge_color() == QColor("#4caf50")
    refresh_as("missing", True)
    assert badge_color() == QColor("#e8a90c")
    refresh_as("missing", False)
    assert badge_color() == QColor("#888888")
    # Weights ready wins over Ollama down: training can start.
    refresh_as("ready", False)
    assert badge_color() == QColor("#4caf50")


def test_download_fix_button_opens_profile_window(window, qapp):
    """T79: in the no-repo state the fix button opens the profile
    window, where Base ref gets set."""
    _select_session(window)
    window._checklist_dismiss()
    assert window.download_fix_btn.isVisible()
    window.download_fix_btn.click()
    qapp.processEvents()
    win = window._profile_windows.get("lfm3-tool")
    assert win is not None
    assert win.isVisible()
    win.close()


def test_download_enabled_with_repo(window, seeded, qapp):
    """T79: with a repo set, Download is live and the fix button
    is gone."""
    seeded.update_profile("lfm3-tool", base_ref="LiquidAI/LFM3-1.7B")
    _select_session(window)
    window._checklist_dismiss()
    assert window.download_btn.isEnabled()
    assert window.download_fix_btn.isVisible() is False


def test_project_window_shows_status_and_mark_ready(window, seeded):
    # T53: the project window shows the status read-only, and a
    # draft can be marked ready from here — the tree row shows the
    # new status too.
    win = window.open_project_window("lfm3-tool", "tool-calls")
    assert win.status_label.text() == "draft"
    assert not win.mark_ready_btn.isHidden()
    win.mark_ready_btn.click()
    assert seeded.get_project("lfm3-tool", "tool-calls")["status"] == "ready"
    assert win.status_label.text() == "ready"
    assert win.mark_ready_btn.isHidden()
    child = window.tree.topLevelItem(0).child(0)
    assert child.text(0) == "tool-calls (ready) [forge-traces.jsonl]"
    win.close()


def test_project_window_hides_mark_ready_when_not_draft(window, seeded):
    # T53: Mark ready only shows for a draft.
    seeded.update_project("lfm3-tool", "tool-calls", status="ready")
    win = window.open_project_window("lfm3-tool", "tool-calls")
    assert win.status_label.text() == "ready"
    assert win.mark_ready_btn.isHidden()
    win.close()


def test_tree_row_shows_status(window, seeded):
    # T53: the list row shows the status in plain words.
    child = window.tree.topLevelItem(0).child(0)
    assert child.text(0) == "tool-calls (draft) [forge-traces.jsonl]"
    seeded.update_project("lfm3-tool", "tool-calls", status="done")
    window.refresh_tree()
    child = window.tree.topLevelItem(0).child(0)
    assert child.text(0) == "tool-calls (done) [forge-traces.jsonl]"


def test_profile_window_base_edit_blank_for_tag(window, seeded, qapp):
    """T79: a tag-valued base_ref is not shown as if it were a
    repo; a real repo is shown."""
    win = window.open_profile_window("lfm3-tool")
    # The seeded profile's base_ref is the Ollama tag, not a repo.
    assert seeded.get_profile("lfm3-tool")["base_ref"] == "lfm3:1.7b"
    assert win.base_edit.text() == ""
    win.close()
    # The window is cached per profile: destroy it so the second
    # open loads fresh from the store.
    from PySide6.QtTest import QTest

    win.deleteLater()
    deadline = 0
    while "lfm3-tool" in window._profile_windows:
        QTest.qWait(100)
        deadline += 100
        assert deadline < 5000
    seeded.update_profile("lfm3-tool", base_ref="LiquidAI/LFM3-1.7B")
    win = window.open_profile_window("lfm3-tool")
    assert win.base_edit.text() == "LiquidAI/LFM3-1.7B"
    win.close()


def test_profile_save_syncs_base_with_tag(window, seeded, monkeypatch):
    # T54: changing the tag in the profile window syncs the base
    # ref — the field shows blank for a tag-valued base (T79) and
    # the save must not clear it.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    win = window.open_profile_window("lfm3-tool")
    assert win.base_edit.text() == ""
    win.tag_combo.setCurrentText("lfm3:2b")
    assert win.save() is True
    assert seeded.get_profile("lfm3-tool")["base_ref"] == "lfm3:2b"
    win.close()


def test_profile_save_keeps_split_base(window, seeded, monkeypatch):
    # T54: a repo base stays split when the tag changes.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    seeded.update_profile("lfm3-tool", base_ref="LiquidAI/LFM3-1.7B")
    win = window.open_profile_window("lfm3-tool")
    assert win.base_edit.text() == "LiquidAI/LFM3-1.7B"
    win.tag_combo.setCurrentText("lfm3:2b")
    assert win.save() is True
    assert (
        seeded.get_profile("lfm3-tool")["base_ref"]
        == "LiquidAI/LFM3-1.7B"
    )
    win.close()


def test_profile_save_passes_edited_base(window, seeded, monkeypatch):
    # T54: typing a repo into the blank base field stores it.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    win = window.open_profile_window("lfm3-tool")
    win.base_edit.setText("LiquidAI/LFM3-1.7B")
    assert win.save() is True
    assert (
        seeded.get_profile("lfm3-tool")["base_ref"]
        == "LiquidAI/LFM3-1.7B"
    )
    win.close()


def test_project_window_save_visible_without_scrolling(window, qapp):
    """T80: the action row is pinned below the scroll area, so
    Save stays visible even in a short window."""
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    proj_win.resize(500, 300)
    proj_win.show()
    qapp.processEvents()
    assert proj_win.save_btn.isVisible()
    assert proj_win.save_btn.geometry().bottom() <= proj_win.height()
    proj_win.close()


def test_settings_sections_are_collapsible(window, qapp):
    """T80: every Settings section is a collapsible group, open by
    default; collapsing hides its content."""
    from stella.gui import CollapsibleSection

    settings_win = window.open_settings_window()
    assert set(settings_win.sections) == {
        "Where Stella keeps things",
        "Ollama",
        "Chat model",
        "AI providers",
        "Ease of use",  # T147: less motion, larger text
    }
    for section in settings_win.sections.values():
        assert isinstance(section, CollapsibleSection)
        assert section.is_expanded()
    section = settings_win.sections["Where Stella keeps things"]
    section.header_btn.click()
    qapp.processEvents()
    assert section.is_expanded() is False
    assert section.content.isVisible() is False
    section.header_btn.click()
    qapp.processEvents()
    assert section.is_expanded()
    settings_win.close()


def test_main_window_train_sections_collapse(window, qapp):
    """T80: the main panel's train-detail sections collapse."""
    window._checklist_dismiss()
    qapp.processEvents()
    for section in (
        window.dataset_section,
        window.checkpoints_section,
        window.log_section,
        window.sleep_section,
    ):
        assert section.is_expanded()
    window.log_section.header_btn.click()
    qapp.processEvents()
    assert window.log_section.is_expanded() is False
    assert window.log_section.content.isVisible() is False
    assert window.train_log.isVisible() is False


def test_stylesheet_is_stellas_own_look(qapp):
    """T81: one stylesheet, drawn from the icon: dark surfaces,
    the gold accent, and a visible focus ring."""
    from stella.style import STELLA_STYLESHEET, apply_stella_style

    assert "#e8a90c" in STELLA_STYLESHEET  # the icon's gold
    assert "#1c1c1c" in STELLA_STYLESHEET  # dark surface
    assert ":focus" in STELLA_STYLESHEET  # the focus ring (T82)
    old = qapp.styleSheet()
    try:
        apply_stella_style(qapp)
        assert qapp.styleSheet() == STELLA_STYLESHEET
    finally:
        qapp.setStyleSheet(old)


def test_bento_page_background_is_dark(window, qapp):
    """T81: no light bands — a bare page (the session header sits
    on the plain bento page, not a card) carries the dark surface,
    so the light session text stays readable. The first cut of
    the sheet left plain widgets on Fusion's light background."""
    from stella.style import apply_stella_style

    old = qapp.styleSheet()
    try:
        apply_stella_style(qapp)
        window._checklist_dismiss()
        qapp.processEvents()
        pixmap = window.bento_widget.grab()
        image = pixmap.toImage()
        # Top-right corner of the page: bare, no text reaches it.
        c = image.pixelColor(image.width() - 10, 10)
        assert c.red() < 80 and c.green() < 80 and c.blue() < 80, (
            c.red(), c.green(), c.blue()
        )
    finally:
        qapp.setStyleSheet(old)


def test_press_dip_shrinks_then_restores(qapp):
    """T81: a button press dips to 97% over 150 ms, then comes
    back to its original geometry. resize(), not setFixedSize:
    a fixed size clamps setGeometry and the dip never shows.
    R18: the dip is asserted on the animation's own key values,
    not on sampled geometry — a 150 ms animation with a 2 px
    bottom is missed by sampling under load (5/10 probe runs
    sampled only the unshrunk width)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from stella.style import install_press_dips

    button = QPushButton("Dip me")
    button.resize(120, 40)
    button.show()
    qapp.processEvents()
    original = button.geometry()
    dips = install_press_dips(qapp)
    try:
        QTest.mousePress(button, Qt.LeftButton)
        # An animation is running for this button.
        assert button in dips._animations
        animation = dips._animations[button]
        # The dip itself, from the animation's keyframes: the
        # mid keyframe is the shrunk rect (97% — 118 px wide
        # here), and both ends are the original rect.
        assert animation.duration() == 150
        assert animation.keyValueAt(0.0) == original
        mid = animation.keyValueAt(0.5)
        assert mid.width() < original.width()
        assert mid.width() == 118
        assert animation.keyValueAt(1.0) == original
        # Wait for the animation to finish, then the geometry
        # is restored exactly.
        deadline = 0
        while button in dips._animations:
            QTest.qWait(20)
            deadline += 20
            assert deadline < 5000
        assert button.geometry() == original
    finally:
        qapp.removeEventFilter(dips._filter)
        button.close()


def test_menu_shortcuts(window):
    """T82: the main actions have keyboard shortcuts."""
    assert window._menu_action_new_profile.shortcut().toString() == "Ctrl+N"
    assert window._menu_action_new_project.shortcut().toString() == "Ctrl+Shift+N"
    assert window._menu_action_run.shortcut().toString() == "Ctrl+G"
    assert window._menu_action_howto.shortcut().toString() == "F1"
    # T168: F2 is Rename now; Chat moved to F3.
    assert window._menu_action_chat.shortcut().toString() == "F3"


def test_f1_opens_howto(window, qapp):
    """T82: F1 opens How to Use."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(window, Qt.Key_F1)
    qapp.processEvents()
    assert window._howto_window is not None
    assert window._howto_window.isVisible()
    window._howto_window.close()


def test_ctrl_n_opens_new_profile_dialog(window, qapp):
    """T82: Ctrl+N opens the new profile dialog."""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog

    def close_dialog():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg.reject()

    QTimer.singleShot(100, close_dialog)
    QTest.keyClick(window, Qt.Key_N, Qt.ControlModifier)
    qapp.processEvents()
    assert window._profile_dialog is not None
    assert window._profile_dialog.result() == QDialog.Rejected


def test_ctrl_s_saves_project_window(window, seeded, qapp):
    """T82: Ctrl+S saves the project window."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    proj_win.show()
    qapp.processEvents()
    proj_win.display_edit.setText("Saved by shortcut")
    QTest.keyClick(proj_win, Qt.Key_S, Qt.ControlModifier)
    qapp.processEvents()
    assert seeded.get_project("lfm3-tool", "tool-calls")["display_name"] == (
        "Saved by shortcut"
    )
    proj_win.close()


def test_tab_order_follows_visual_order(window, seeded, qapp):
    """T82: Tab walks the hero in visual order — model, new
    model, download."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    seeded.update_profile("lfm3-tool", base_ref="LiquidAI/LFM3-1.7B")
    _select_session(window)
    window._checklist_dismiss()
    qapp.processEvents()
    window.model_combo.setFocus()
    assert QApplication.focusWidget() is window.model_combo
    QTest.keyClick(window.model_combo, Qt.Key_Tab)
    qapp.processEvents()
    assert QApplication.focusWidget() is window.new_model_btn
    QTest.keyClick(window.new_model_btn, Qt.Key_Tab)
    qapp.processEvents()
    assert QApplication.focusWidget() is window.download_btn


# -- T57: merge, don't discard, the profile block on import --------


def _source_package(tmp_path):
    """A package exported from a separate home: profile lfm3-tool,
    tag lfm3:1.7b, role fast, project tool-calls."""
    from stella import export as export_mod
    from stella.model import Store

    src = Store(tmp_path / "src-home")
    src.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b", role="fast")
    src.create_project("lfm3-tool", "tool-calls",
                       dataset_ref="forge-traces.jsonl")
    return export_mod.export_project(
        src, "lfm3-tool", "tool-calls", tmp_path)


def _clear_seeded_project(window, seeded):
    """Remove the seeded project (to the trash) so an import of
    tool-calls can land; the profile stays."""
    seeded.delete_project("lfm3-tool", "tool-calls")
    window.refresh_tree()


def test_profile_merge_box_lists_fields_and_defaults_to_keep(window):
    diff = {
        "ollama_tag": {"local": "other:9b", "package": "lfm3:1.7b"},
        "role": {"local": "driver", "package": "fast"},
    }
    box = window._profile_merge_box("lfm3-tool", diff)
    assert box.windowTitle() == "Profile already exists"
    assert "lfm3-tool" in box.text()
    info = box.informativeText()
    assert "tag: yours is 'other:9b', the package has 'lfm3:1.7b'." in info
    assert "role: yours is 'driver', the package has 'fast'." in info
    assert "Keep yours, or use the package's?" in info
    assert [b.text() for b in box.buttons()] == [
        "Keep mine", "Use the package's"]
    assert box.defaultButton() is box._stella_keep_button
    assert box.escapeButton() is box._stella_keep_button
    # No em-dash anywhere in the dialog's visible text.
    for text in (box.text(), info, box.windowTitle()):
        assert "\u2014" not in text


def test_import_identical_profile_is_silent_and_says_existed(
        window, seeded, tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    offered = []
    monkeypatch.setattr(
        window, "_offer_locate_dataset", lambda *a: offered.append(a)
    )
    # T58: the preview confirms (stubbed) so the import proceeds.
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg))
    window.import_package()
    _wait_for_job(window, qapp)
    message = window.statusBar().currentMessage()
    assert "Imported tool-calls into lfm3-tool." in message
    assert "The profile already existed." in message
    assert "now uses" not in message
    # The profile merge was silent; the only warning is the
    # dataset's (T59), and the locate repair was offered.
    assert len(warnings) == 1
    assert "forge-traces.jsonl" in warnings[0]
    assert offered == [("lfm3-tool", "tool-calls", "forge-traces.jsonl")]


def test_import_differing_profile_asks_and_keeps(
        window, seeded, tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    seeded.update_profile("lfm3-tool", ollama_tag="other:9b",
                          role="driver")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg))
    # No click: the dialog closes without an answer, which keeps
    # yours — the safe answer.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 1)
    # The dataset warning (T59) goes through the C++ static
    # QMessageBox.warning, whose internal exec() the stub above
    # does not cover — stub _warn itself, and the locate offer.
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    monkeypatch.setattr(window, "_offer_locate_dataset", lambda *a: None)
    # T58: the preview confirms with no merge choice (stubbed), so
    # the merge dialog is still the one that decides.
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    window.import_package()
    _wait_for_job(window, qapp)
    prof = seeded.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"]) == ("other:9b", "driver")
    message = window.statusBar().currentMessage()
    assert "The profile already existed." in message
    assert "now uses" not in message


def test_import_differing_profile_take_updates_profile(
        window, seeded, tmp_path, monkeypatch, qapp):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog

    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    seeded.update_profile("lfm3-tool", ollama_tag="other:9b",
                          role="driver")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg))
    # The dataset warning (T59) is a real modal unless stubbed.
    monkeypatch.setattr(
        window, "_warn", lambda text: None
    )
    # The locate repair (T59) is not this test's subject: the
    # seeded dataset is missing, so stub the offer away.
    monkeypatch.setattr(
        window, "_offer_locate_dataset", lambda *a: None
    )
    # T58: the preview confirms with no merge choice (stubbed), so
    # the merge dialog is still the one that decides.
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )

    def click_take():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg._stella_take_button.click()

    QTimer.singleShot(100, click_take)
    window.import_package()
    _wait_for_job(window, qapp)
    prof = seeded.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"], prof["base_ref"]) == (
        "lfm3:1.7b", "fast", "lfm3:1.7b")
    message = window.statusBar().currentMessage()
    assert "The profile already existed." in message
    assert "The profile now uses the package's tag, role and base." in message


# -- T43: the model list is cached, fetched off the UI thread --------


def _counting_ollama_server(delay=0.0):
    """A fake Ollama that counts /api/tags hits. Returns (server,
    url, state) where state["hits"] is the count."""
    state = {"hits": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/tags":
                state["hits"] += 1
                if delay:
                    time.sleep(delay)
                body = json.dumps({
                    "models": [
                        {"name": "lfm3:1.7b", "size": 2000000000},
                        {"name": "qwen3-vl:2b-instruct", "size": 1500000000},
                    ]
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", state


def _wait_hits(qapp, state, want, timeout_ms=5000):
    """Pump the event loop until the fake server has seen `want`
    hits (or the timeout expires). The count is exact: an extra
    fetch fails the assert."""
    deadline = timeout_ms
    while state["hits"] < want and deadline > 0:
        qapp.processEvents()
        time.sleep(0.05)
        deadline -= 50
    assert state["hits"] == want, (
        f"expected {want} fetches, saw {state['hits']}"
    )


def _wait_until(qapp, cond, desc, timeout_ms=5000):
    """Pump the event loop until `cond()` is true (or the timeout
    expires). The server counts a hit when it SENDS the response;
    the worker thread still has to read it, parse it, and fill the
    cache (and the UI still has to run the refreshed slot) — so
    waiting on the hit count alone races the assertion under load.
    Wait on the thing the test actually asserts."""
    deadline = timeout_ms
    while not cond() and deadline > 0:
        qapp.processEvents()
        time.sleep(0.05)
        deadline -= 50
    assert cond(), f"timed out waiting for {desc}"


def test_model_list_fetched_once_at_startup_then_cached(
    qapp, seeded, settings, monkeypatch
):
    """T43 Done: 1 fetch at startup, 0 fetches across any number
    of profile selection changes."""
    from stella.gui import MainWindow
    from stella.ollama import MODEL_CACHE

    server, url, state = _counting_ollama_server()
    win = None
    try:
        MODEL_CACHE.reset()
        monkeypatch.setenv("STELLA_OLLAMA_URL", url)
        win = MainWindow(store=seeded, settings=settings)
        win.show()
        _wait_hits(qapp, state, 1)
        _wait_until(
            qapp,
            lambda: MODEL_CACHE.models()
            == ["lfm3:1.7b", "qwen3-vl:2b-instruct"],
            "the cache to hold the two fetched models",
        )
        assert MODEL_CACHE.models() == ["lfm3:1.7b", "qwen3-vl:2b-instruct"]
        # Any number of selection changes: no more fetches.
        win.set_session("lfm3-tool", "tool-calls")
        win.set_session("lfm3-tool", None)
        win.set_session("lfm3-tool", "tool-calls")
        win.refresh_tree()
        win.refresh_session()
        qapp.processEvents()
        assert state["hits"] == 1
        # The profile window reads the cache too: no fetch.
        prof_win = win.open_profile_window("lfm3-tool")
        qapp.processEvents()
        assert state["hits"] == 1
        assert prof_win.tag_combo.findText("lfm3:1.7b") >= 0
        assert prof_win.tag_combo.findText("qwen3-vl:2b-instruct") >= 0
        prof_win.close()
    finally:
        if win is not None:
            win.close()
        MODEL_CACHE.reset()
        server.shutdown()
        server.server_close()


def test_model_list_refresh_button_refetches(
    qapp, seeded, settings, monkeypatch
):
    """T43 Done: 1 fetch on explicit Refresh (and one when the New
    Profile dialog opens, which the task counts as on demand)."""
    from stella.gui import MainWindow, NewProfileDialog
    from stella.ollama import MODEL_CACHE

    server, url, state = _counting_ollama_server()
    win = None
    dialog = None
    try:
        MODEL_CACHE.reset()
        monkeypatch.setenv("STELLA_OLLAMA_URL", url)
        win = MainWindow(store=seeded, settings=settings)
        win.show()
        _wait_hits(qapp, state, 1)
        dialog = NewProfileDialog(win)
        dialog.show()
        _wait_hits(qapp, state, 2)
        _wait_until(
            qapp,
            lambda: dialog.model_list.count() == 2,
            "the dialog list to show the two fetched models",
        )
        assert dialog.model_list.count() == 2
        # The list count alone does not prove the dialog's first
        # refresh finished: the cache was already loaded by the
        # main window's fetch, so the list shows two rows before
        # the dialog's own worker lands — and Refresh is a no-op
        # while that worker is still running. Wait for it first,
        # or the click races the in-flight refresh and the third
        # fetch never happens.
        _wait_until(
            qapp,
            lambda: dialog._model_worker is None
            or not dialog._model_worker.isRunning(),
            "the dialog's first refresh to finish",
        )
        dialog.refresh_btn.click()
        _wait_hits(qapp, state, 3)
        _wait_until(
            qapp,
            lambda: dialog.model_list.count() == 2,
            "the dialog list to show the two models after refresh",
        )
        assert dialog.model_list.count() == 2
    finally:
        if dialog is not None:
            dialog.close()
        if win is not None:
            win.close()
        MODEL_CACHE.reset()
        server.shutdown()
        server.server_close()


def test_hung_ollama_clicks_stay_responsive(
    qapp, seeded, settings, monkeypatch
):
    """T43 Done: with Ollama hung, profile clicks still respond
    immediately and the stored tag stays visible."""
    from stella.gui import MainWindow
    from stella.ollama import MODEL_CACHE

    server, url, state = _counting_ollama_server(delay=1.2)
    win = None
    try:
        MODEL_CACHE.reset()
        monkeypatch.setenv("STELLA_OLLAMA_URL", url)
        win = MainWindow(store=seeded, settings=settings)
        win.show()
        # The startup fetch is in flight (1.2 s): clicks must not
        # wait for it.
        started = time.monotonic()
        win.set_session("lfm3-tool", "tool-calls")
        win.set_session("lfm3-tool", None)
        win.set_session("lfm3-tool", "tool-calls")
        elapsed = time.monotonic() - started
        assert elapsed < 0.8, (
            f"clicks blocked {elapsed:.2f}s on a hung Ollama"
        )
        # The stored tag stays visible while the fetch is in flight.
        prof_win = win.open_profile_window("lfm3-tool")
        assert prof_win.tag_combo.currentText() == "lfm3:1.7b"
        prof_win.close()
        # The refresh lands on its own; the list fills then. Wait
        # for the cache, not the hit: the server counts the hit on
        # arrival, 1.2 s before it answers.
        deadline = 5000
        while not MODEL_CACHE.loaded and deadline > 0:
            qapp.processEvents()
            time.sleep(0.05)
            deadline -= 50
        assert MODEL_CACHE.loaded
        assert state["hits"] == 1
        assert MODEL_CACHE.models() == ["lfm3:1.7b", "qwen3-vl:2b-instruct"]
    finally:
        if win is not None:
            win.close()
        MODEL_CACHE.reset()
        server.shutdown()
        server.server_close()


def test_profile_window_tag_combo_uses_cache(window, seed_models, qapp):
    """T43: the profile window fills its tag combo from the cache."""
    seed_models(["lfm3:1.7b", "qwen3.5:2b"])
    prof_win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    items = [
        prof_win.tag_combo.itemText(i)
        for i in range(prof_win.tag_combo.count())
    ]
    assert "lfm3:1.7b" in items
    assert "qwen3.5:2b" in items
    assert prof_win.tag_combo.currentText() == "lfm3:1.7b"
    prof_win.close()


def test_profile_window_keeps_stored_tag_when_ollama_down(
    window, seed_models, qapp
):
    """T43/A1-U4: with Ollama down, the stored tag stays visible in
    the combo — no flicker to empty on any click."""
    seed_models([], ollama_up=False)
    prof_win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert prof_win.tag_combo.currentText() == "lfm3:1.7b"
    assert prof_win.tag_combo.count() == 1
    prof_win.close()


# -- T61: base-health check on import --------------------------------


def test_import_warns_when_base_tag_not_installed(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T61 Done: importing a package whose tag is not on this PC
    warns, naming the tag — from the cached list, no fetch."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    seed_models(["qwen3.5:2b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    monkeypatch.setattr(
        window, "_offer_locate_dataset", lambda *a: None
    )
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    window.import_package()
    _wait_for_job(window, qapp)
    assert warnings, "no warning for the uninstalled base tag"
    assert "lfm3:1.7b" in warnings[0]
    assert "not installed" in warnings[0]
    # The warning never blocks: the project imported.
    assert seeded.get_project("lfm3-tool", "tool-calls")


def test_import_silent_when_base_tag_installed(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T61 Done: an installed tag imports silently."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    seed_models(["lfm3:1.7b", "qwen3.5:2b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    monkeypatch.setattr(
        window, "_offer_locate_dataset", lambda *a: None
    )
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    window.import_package()
    _wait_for_job(window, qapp)
    # No base warning; the only warning is the dataset's (T59).
    assert len(warnings) == 1
    assert "forge-traces.jsonl" in warnings[0]
    assert seeded.get_project("lfm3-tool", "tool-calls")


# -- T45: dataset picker + validation --------------------------------


def _write_fake_dataset(path, n=4):
    rows = [
        {"messages": [
            {"role": "user", "content": f"Question {i}?"},
            {"role": "assistant", "content": f"Answer {i}."},
        ]}
        for i in range(n)
    ]
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return path


def test_project_window_dataset_browse_fills_field(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T45 Done: the picker fills the Dataset field, and the check
    below says what the file holds."""
    from PySide6.QtWidgets import QFileDialog

    path = _write_fake_dataset(tmp_path / "data.jsonl", 4)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), "")
    )
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    proj_win.dataset_browse_btn.click()
    assert proj_win.dataset_edit.text() == str(path)
    info = proj_win.dataset_info.text()
    assert "4 examples: 3 to train, 1 to check." in info
    assert "1. Question 0?" in info
    proj_win.save()
    proj_win.close()


def test_project_window_save_missing_dataset_warns_without_blocking(
    window, seeded, qapp
):
    """T45 Done: saving a missing path warns — and still saves."""
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    proj_win.dataset_edit.setText("/no/such/place/data.jsonl")
    assert proj_win.save() is True
    assert (
        "Dataset not found. Is the path right?"
        in proj_win.dataset_info.text()
    )
    assert seeded.get_project("lfm3-tool", "tool-calls")["dataset_ref"] == (
        "/no/such/place/data.jsonl"
    )
    proj_win.close()


def test_project_window_load_shows_missing_dataset_warning(window, seeded):
    """T45: the seeded project's missing dataset warns on load."""
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    assert (
        "Dataset not found. Is the path right?"
        in proj_win.dataset_info.text()
    )
    proj_win.close()


def test_project_window_dataset_valid_shows_count_and_preview(
    window, seeded, tmp_path, qapp
):
    """T45 Done: a valid JSONL file shows an example count, the
    train/check split, and a 3-example preview."""
    path = _write_fake_dataset(tmp_path / "data.jsonl", 10)
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    proj_win.dataset_edit.setText(str(path))
    proj_win.dataset_edit.editingFinished.emit()
    info = proj_win.dataset_info.text()
    # The content-hash split (T155): 2 of these 10 rows hash under
    # the 10% threshold, so 8 train and 2 check.
    assert "10 examples: 8 to train, 2 to check." in info
    assert "1. Question 0?" in info
    assert "2. Question 1?" in info
    assert "3. Question 2?" in info
    proj_win.save()
    proj_win.close()


def test_project_window_dataset_malformed_names_line(
    window, seeded, tmp_path, qapp
):
    """T45 Done: a malformed file reports the bad line number."""
    path = tmp_path / "bad.jsonl"
    path.write_text(
        '{"prompt": "a", "completion": "b"}\nnot json\n',
        encoding="utf-8",
    )
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    proj_win.dataset_edit.setText(str(path))
    proj_win.dataset_edit.editingFinished.emit()
    assert "line 2" in proj_win.dataset_info.text()
    proj_win.save()
    proj_win.close()


def test_pick_dataset_reports_example_count(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T45: the Train panel's dataset pick reports the count."""
    from PySide6.QtWidgets import QFileDialog

    _select_session(window)
    path = _write_fake_dataset(tmp_path / "data.jsonl", 4)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), "")
    )
    window.pick_dataset()
    assert seeded.get_project("lfm3-tool", "tool-calls")["dataset_ref"] == (
        str(path)
    )
    assert "(4 examples)" in window.statusBar().currentMessage()


def test_pick_dataset_malformed_warns(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T45: picking a malformed file warns with the bad line —
    and still stores the pick."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    _select_session(window)
    path = tmp_path / "bad.jsonl"
    path.write_text(
        '{"prompt": "a", "completion": "b"}\nnot json\n',
        encoding="utf-8",
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), "")
    )
    window.pick_dataset()
    assert warnings and "line 2" in warnings[0]
    assert seeded.get_project("lfm3-tool", "tool-calls")["dataset_ref"] == (
        str(path)
    )


# -- T47: progress/loss reset per project; panel pins to the run -----


def test_train_progress_resets_on_project_switch(window, seeded, qapp):
    """T47 Done: switching projects resets the bar to 0 and the
    loss line to Not started."""
    seeded.create_project("lfm3-tool", "second")
    _select_session(window)
    window._on_train_progress(2, 4, 1.5)
    assert window.train_progress.value() == 2
    window.set_session("lfm3-tool", "second")
    assert window.train_progress.value() == 0
    assert window.train_loss.text() == "Not started."


def test_train_progress_empty_with_no_selection(window, qapp):
    """T47 Done: with no project picked, the bar is empty."""
    _select_session(window)
    window._on_train_progress(2, 4, 1.5)
    assert window.train_progress.value() == 2
    window.set_session("lfm3-tool", None)
    assert window.train_progress.value() == 0
    assert window.train_loss.text() == "Pick a project to train."


def test_train_panel_pinned_to_running_project(window, seeded, qapp):
    """T47 Done: switching the session mid-run leaves the panel on
    the running project — its checkpoints, bar, and loss stay —
    and the pin note names it. When the run finishes, the pin
    clears and the panel follows the session again."""

    class _RunningStub:
        def isRunning(self):
            return True

        def request_stop(self):
            pass

    seeded.create_project("lfm3-tool", "second")
    ck = (
        seeded.project_dir("lfm3-tool", "tool-calls")
        / "checkpoints" / "step-2"
    )
    ck.mkdir(parents=True)
    (ck / "training_state.json").write_text(
        json.dumps({"step": 2, "loss": 1.5, "epoch": 1}), encoding="utf-8"
    )
    _select_session(window)
    window._on_train_progress(2, 4, 1.5)
    assert window.train_checkpoints.count() == 1
    window._train_worker = _RunningStub()
    window._running_job_key = ("lfm3-tool", "tool-calls")
    try:
        window.set_session("lfm3-tool", "second")
        assert not window.train_pin_label.isHidden()
        assert "tool-calls" in window.train_pin_label.text()
        assert window.train_checkpoints.count() == 1
        assert window.train_progress.value() == 2
        assert "Step 2 / 4" in window.train_loss.text()
        window._train_worker = None
        window._on_train_finished(True, "Trained 4 steps.")
        assert window.train_pin_label.isHidden()
        assert window.train_checkpoints.count() == 0
        assert window.train_loss.text() == "Not started."
    finally:
        window._train_worker = None
        window._running_job_key = None


# -- T50: confirmations stay visible ----------------------------------


def test_train_finished_confirmation_survives_refresh(window, qapp):
    """T50 Done: "Trained 4 steps." stays in the status bar after
    the finish refresh — refresh_session used to overwrite it
    with the session line."""
    _select_session(window)
    window._on_train_finished(True, "Trained 4 steps.")
    assert window.statusBar().currentMessage() == "Trained 4 steps."


def test_sleep_finished_confirmation_survives_refresh(window, qapp):
    """T50 Done: the sleep confirmation survives the finish
    refresh, same as training's."""
    _select_session(window)
    window._on_sleep_finished(True, "Sleep cycle 1 done.")
    assert window.statusBar().currentMessage() == "Sleep cycle 1 done."


def test_job_finished_confirmation_survives_refresh(window, qapp):
    """T50: a job-card job's confirmation survives its refresh."""
    _select_session(window)
    window._on_job_finished(True, "Probe done.")
    assert window.statusBar().currentMessage() == "Probe done."


def test_import_confirmation_survives_session_refresh(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T50 pin: the import confirmation is said after the session
    is set, so it stays in the status bar."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: None
    )
    monkeypatch.setattr(
        window, "_offer_locate_dataset", lambda *a: None
    )
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    window.import_package()
    _wait_for_job(window, qapp)
    assert "Imported" in window.statusBar().currentMessage()


# -- T59: the dataset is part of the package decision -----------------


def test_export_offers_bundle_and_copies_dataset(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T59 Done: exporting a project with a dataset offers to copy
    it in; "Copy it in" bundles the file."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    _select_session(window)
    data = _write_fake_dataset(tmp_path / "data.jsonl", 4)
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref=str(data)
    )
    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    def click_copy():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg._stella_copy_button.click()

    QTimer.singleShot(100, click_copy)
    window.export_project()
    _wait_for_job(window, qapp)
    pkg = dest / "tool-calls-stella-export"
    assert (pkg / "dataset" / "data.jsonl").is_file()


def test_export_reference_only_skips_dataset(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T59: "Reference only" exports without the dataset file."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    _select_session(window)
    data = _write_fake_dataset(tmp_path / "data.jsonl", 4)
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref=str(data)
    )
    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    def click_reference():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg._stella_reference_button.click()

    QTimer.singleShot(100, click_reference)
    window.export_project()
    _wait_for_job(window, qapp)
    pkg = dest / "tool-calls-stella-export"
    assert not (pkg / "dataset").exists()


def test_ask_bundle_dataset_no_question_without_ref(window, seeded):
    """T59: no dataset means no offer — the export just goes
    ahead reference-only."""
    seeded.update_project("lfm3-tool", "tool-calls", dataset_ref="")
    assert window._ask_bundle_dataset("lfm3-tool", "tool-calls") is False


def test_ask_bundle_dataset_no_question_when_missing(window, seeded):
    """T59: a dataset that is not here means no offer either."""
    # The seeded ref (forge-traces.jsonl) is not on this PC.
    assert window._ask_bundle_dataset("lfm3-tool", "tool-calls") is False


def test_dataset_locate_box_text(window):
    """T59: the locate dialog names the missing dataset and
    offers Locate / Not now, defaulting to Not now."""
    box = window._dataset_locate_box("forge-traces.jsonl")
    assert box.windowTitle() == "Dataset not on this PC"
    assert "forge-traces.jsonl" in box.text()
    assert "Find it now?" in box.text()
    assert [b.text() for b in box.buttons()] == [
        "Locate the file", "Not now"]
    assert box.defaultButton() is box._stella_later_button
    assert box.escapeButton() is box._stella_later_button
    for text in (box.text(), box.informativeText(), box.windowTitle()):
        assert "\u2014" not in text


def test_import_missing_dataset_locate_repair(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T59 Done: after an import whose dataset is missing, the
    locate repair picks the file and stores it."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    data = _write_fake_dataset(tmp_path / "found.jsonl", 4)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(data), "")
    )
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )

    # The locate dialog opens when the import job finishes (T106),
    # not on a fixed delay — a repeating timer clicks it whenever
    # it appears.
    clicker = QTimer()
    clicker.setInterval(50)

    def click_locate():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_locate_button"):
            clicker.stop()
            dlg._stella_locate_button.click()

    clicker.timeout.connect(click_locate)
    clicker.start()
    window.import_package()
    _wait_for_job(window, qapp)
    clicker.stop()
    assert seeded.get_project("lfm3-tool", "tool-calls")["dataset_ref"] == (
        str(data)
    )


def test_import_missing_dataset_not_now_keeps_ref(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T59: "Not now" leaves the imported ref as it is."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )

    # The locate dialog opens when the import job finishes (T106),
    # not on a fixed delay — a repeating timer clicks it whenever
    # it appears.
    clicker = QTimer()
    clicker.setInterval(50)

    def click_later():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_later_button"):
            clicker.stop()
            dlg._stella_later_button.click()

    clicker.timeout.connect(click_later)
    clicker.start()
    window.import_package()
    _wait_for_job(window, qapp)
    clicker.stop()
    assert seeded.get_project("lfm3-tool", "tool-calls")["dataset_ref"] == (
        "forge-traces.jsonl"
    )


# -- T58: the import preview dialog -----------------------------------


def _preview_summary(**overrides):
    """A fake preview summary for the dialog tests."""
    summary = {
        "profile": "lfm3-tool", "project": "tool-calls",
        "profile_display": "LFM3 Tool", "project_display": "Tool Calls",
        "tag": "lfm3:1.7b", "role": "fast", "base": "lfm3:1.7b",
        "stella_version": "0.13.0", "status": "draft",
        "weights": True, "checkpoints": 2, "probe": True, "sleep": False,
        "dataset_ref": "data.jsonl", "dataset_bundled": "",
        "dataset_status": "present",
        "profile_existed": False, "profile_diff": {},
        "base_installed": True,
    }
    summary.update(overrides)
    return summary


def test_import_preview_dialog_shows_summary(window, qapp):
    """T58 Done: the dialog shows the profile, project, tag,
    version, contents, and dataset status."""
    from PySide6.QtWidgets import QLabel

    from stella.gui import ImportPreviewDialog

    dialog = ImportPreviewDialog(window, _preview_summary())
    joined = "\n".join(
        w.text() for w in dialog.findChildren(QLabel)
    )
    assert "Profile lfm3-tool, project tool-calls." in joined
    assert "Base model: lfm3:1.7b." in joined
    assert "Made with Stella 0.13.0." in joined
    assert "the trained weights, 2 checkpoints, probe results" in joined
    assert "Dataset: data.jsonl (on this PC)." in joined
    assert dialog._take_radio is None
    assert dialog.profile_choice() is None
    assert dialog.confirm_btn.text() == "Import"
    assert dialog.cancel_btn.text() == "Cancel"
    dialog.close()


def test_import_preview_dialog_merge_choice_defaults_to_nothing(
    window, qapp
):
    """T58 Done: with a differing profile the dialog shows the
    merge choice, neither radio checked — not picking keeps
    yours."""
    from PySide6.QtWidgets import QLabel

    from stella.gui import ImportPreviewDialog

    summary = _preview_summary(
        profile_existed=True,
        profile_diff={
            "ollama_tag": {"local": "other:9b", "package": "lfm3:1.7b"}
        },
        base_installed=None,
    )
    dialog = ImportPreviewDialog(window, summary)
    assert dialog._keep_radio is not None
    assert dialog._take_radio is not None
    assert not dialog._keep_radio.isChecked()
    assert not dialog._take_radio.isChecked()
    assert dialog.profile_choice() == "keep"
    dialog._take_radio.setChecked(True)
    assert dialog.profile_choice() == "take"
    joined = "\n".join(
        w.text() for w in dialog.findChildren(QLabel)
    )
    assert "If you do not pick, yours is kept." in joined
    assert "tag: yours is 'other:9b', the package has 'lfm3:1.7b'." in joined
    assert "\u2014" not in joined
    dialog.close()


def test_import_preview_cancel_imports_nothing(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T58 Done: cancelling the preview imports nothing."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from stella.model import StellaError

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )

    def click_cancel():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg.cancel_btn.click()

    QTimer.singleShot(100, click_cancel)
    window.import_package()
    _wait_for_job(window, qapp)
    with pytest.raises(StellaError):
        seeded.get_project("lfm3-tool", "tool-calls")


def test_import_preview_confirm_imports(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T58 Done: confirming the preview imports the package."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        window, "_offer_locate_dataset", lambda *a: None
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )

    def click_confirm():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg.confirm_btn.click()

    QTimer.singleShot(100, click_confirm)
    window.import_package()
    _wait_for_job(window, qapp)
    assert seeded.get_project("lfm3-tool", "tool-calls")


def test_import_preview_take_uses_package_values(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T58 Done: picking "Use the package's" in the preview takes
    the package's profile values — no second dialog."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    seeded.update_profile(
        "lfm3-tool", ollama_tag="other:9b", role="driver"
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(window, "_offer_locate_dataset", lambda *a: None)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )

    def click_take_and_confirm():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg._take_radio.setChecked(True)
        dlg.confirm_btn.click()

    QTimer.singleShot(100, click_take_and_confirm)
    window.import_package()
    _wait_for_job(window, qapp)
    prof = seeded.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"], prof["base_ref"]) == (
        "lfm3:1.7b", "fast", "lfm3:1.7b")


def test_import_preview_no_pick_keeps_local(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T58: confirming without picking a radio keeps yours."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    seeded.update_profile(
        "lfm3-tool", ollama_tag="other:9b", role="driver"
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(window, "_offer_locate_dataset", lambda *a: None)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )

    def click_confirm():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg.confirm_btn.click()

    QTimer.singleShot(100, click_confirm)
    window.import_package()
    _wait_for_job(window, qapp)
    prof = seeded.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"]) == ("other:9b", "driver")


# -- T145: the finish moment ------------------------------------------


def test_job_card_finish_moment_shows_summary_then_hides(window, qapp):
    """T145 Done: the finish moment shows the summary in a gold
    glow, then hides after a beat."""
    from PySide6.QtTest import QTest

    window._checklist_dismiss()
    card = window.job_card
    card.start("Training", True)
    assert card.isVisible()
    card.finish_moment("Trained 4 steps.", reduced_motion=False)
    assert card.isVisible()
    assert card.status_label.text() == "Trained 4 steps."
    assert "#ffc93c" in card.styleSheet()
    assert "#3a3016" in card.styleSheet()
    QTest.qWait(300)
    assert card.isVisible() is False
    assert card.styleSheet() == ""


def test_job_card_finish_moment_reduced_motion_hides_at_once(
    window, qapp
):
    """T145: with reduced motion the moment is a plain hide — no
    glow, no delay."""
    window._checklist_dismiss()
    card = window.job_card
    card.start("Training", True)
    assert card.isVisible()
    card.finish_moment("Trained 4 steps.", reduced_motion=True)
    assert card.isVisible() is False
    assert card.styleSheet() == ""


def test_train_finished_shows_finish_moment(window, qapp):
    """T145: a finished run glows with its summary."""
    from PySide6.QtTest import QTest

    _select_session(window)
    window._checklist_dismiss()
    window.job_card.start("Training", True)
    window._on_train_finished(True, "Trained 4 steps.")
    assert window.job_card.isVisible()
    assert window.job_card.status_label.text() == "Trained 4 steps."
    assert "#ffc93c" in window.job_card.styleSheet()
    QTest.qWait(300)
    assert window.job_card.isVisible() is False


def test_job_card_start_cancels_finish_moment(window, qapp):
    """T145: a new job starting during the moment cancels it — the
    card stays up for the new job."""
    from PySide6.QtTest import QTest

    window._checklist_dismiss()
    card = window.job_card
    card.start("Training", True)
    card.finish_moment("Trained 4 steps.", reduced_motion=False)
    card.start("Sleep", True)
    assert card.styleSheet() == ""
    assert card.title_label.text() == "Sleep"
    QTest.qWait(300)
    assert card.isVisible()  # the moment's timer did not hide it
    card.finish()


# -- T146: loading states, never a dead screen -------------------------


def test_new_profile_dialog_shows_skeleton_rows_while_loading(
    window, qapp
):
    """T146 Done: while the first model-list refresh is in flight,
    the list holds three muted skeleton rows shaped like real
    rows — never a dead screen."""
    from PySide6.QtCore import Qt

    from stella.gui import MODEL_CACHE, NewProfileDialog

    MODEL_CACHE.reset()
    dialog = NewProfileDialog(window)
    # No processEvents before asserting: the refresh lands through
    # the event loop, and the skeletons are what shows until then.
    assert dialog.model_list.count() == 3
    assert "Looking for models..." in dialog.model_list.item(0).text()
    for row in range(3):
        item = dialog.model_list.item(row)
        assert item.flags() == Qt.NoItemFlags
        assert "\n" in item.text()  # shaped like a real row
    dialog.close()


def test_new_profile_dialog_skeletons_replaced_by_real_rows(
    window, qapp, seed_models
):
    """T146: when the refresh lands, the real rows (with fit
    verdicts) replace the skeletons."""
    from PySide6.QtCore import Qt

    from stella.gui import MODEL_CACHE, NewProfileDialog

    MODEL_CACHE.reset()
    dialog = NewProfileDialog(window)
    assert dialog.model_list.count() == 3  # skeletons
    seed_models(["lfm3:1.7b"])
    dialog._fill_model_list()
    assert dialog.model_list.count() == 1
    item = dialog.model_list.item(0)
    assert "lfm3:1.7b" in item.text()
    assert item.flags() != Qt.NoItemFlags
    dialog.close()


def test_settings_status_checks_without_blocking(
    window, qapp, seed_models
):
    """T146 Done: refreshing the Ollama status says Checking...
    at once, then the status from the cache when the refresh
    lands — never a dead screen, never a blocked UI."""
    seed_models(["lfm3:1.7b"])
    win = window.open_settings_window()
    win.refresh_ollama_status()
    assert win.ollama_status.text() == "Status: Checking..."
    window._on_model_list_refreshed(["lfm3:1.7b"], {}, True)
    assert "running" in win.ollama_status.text()
    assert "lfm3:1.7b" in win.ollama_status.text()
    win.close()


def test_settings_status_says_when_ollama_down(window, qapp, seed_models):
    """T146: when the refresh lands with Ollama down, the status
    says so. R17: seeded through seed_models, like the
    neighbouring test — the raw set_snapshot seed could be
    overwritten by the Settings window's own live refresh."""
    seed_models([], ollama_up=False)
    win = window.open_settings_window()
    win._on_models_refreshed()
    assert "not reachable" in win.ollama_status.text()
    win.close()


def test_chat_shows_looking_state_then_model_buttons(window, qapp):
    """T146 Done: the chat says it is looking for the models while
    the first refresh is in flight, and shows the model buttons
    when it lands."""
    from stella.gui import MODEL_CACHE

    MODEL_CACHE.reset()
    chat = window.open_chat_window()
    assert "Looking for the models on this PC..." in (
        chat.messages.toPlainText()
    )
    assert chat.model_buttons == []
    MODEL_CACHE.set_snapshot(["lfm3:1.7b"], {}, ollama_up=True)
    chat._on_models_refreshed()
    assert len(chat.model_buttons) == 1
    assert chat.model_buttons[0].text() == "lfm3:1.7b"
    chat.close()


# -- T149: the job picker becomes the job -------------------------------


def test_job_card_morphs_from_button_rect(window, qapp):
    """T149 Done: starting with a start rect animates the card's
    geometry from the button's rect to its final layout rect in
    350 ms."""
    from PySide6.QtCore import QRect
    from PySide6.QtTest import QTest

    window._checklist_dismiss()
    card = window.job_card
    card.start("Training", True)
    qapp.processEvents()
    final = card.geometry()
    assert not final.isEmpty()
    card.finish()
    qapp.processEvents()
    start_rect = QRect(final.x(), final.y(), 80, 30)
    card.start("Training", True, from_rect=start_rect)
    assert card._morph_animation is not None
    assert card._morph_animation.duration() == 350
    assert card.geometry() == start_rect
    QTest.qWait(450)
    assert card._morph_animation is None
    assert card.geometry() == final
    card.finish()


def test_job_card_morph_skipped_with_reduced_motion(window, qapp):
    """T149: with reduced motion the card appears at its final
    rect at once — no animation."""
    from PySide6.QtCore import QRect

    window._checklist_dismiss()
    card = window.job_card
    card.start("Training", True)
    qapp.processEvents()
    final = card.geometry()
    card.finish()
    qapp.processEvents()
    card.start(
        "Training", True,
        from_rect=QRect(final.x(), final.y(), 80, 30),
        reduced_motion=True,
    )
    assert card._morph_animation is None
    assert card.geometry() == final
    card.finish()


def test_job_card_finish_cancels_morph(window, qapp):
    """T149: finishing mid-morph stops the animation and hides
    the card — nothing resurrects it after."""
    from PySide6.QtCore import QRect
    from PySide6.QtTest import QTest

    window._checklist_dismiss()
    card = window.job_card
    card.start("Training", True)
    qapp.processEvents()
    final = card.geometry()
    card.finish()
    qapp.processEvents()
    card.start(
        "Training", True,
        from_rect=QRect(final.x(), final.y(), 80, 30),
    )
    assert card._morph_animation is not None
    card.finish()
    assert card._morph_animation is None
    assert card.isVisible() is False
    QTest.qWait(450)
    assert card.isVisible() is False


def test_start_job_worker_morphs_from_picked_tile(window, qapp):
    """T149: a tile job morphs out of its tile button — the start
    rect is the button's rect, mapped to the card's parent."""
    from PySide6.QtTest import QTest

    window._checklist_dismiss()
    _select_session(window)
    rect = window._job_button_rect("requant")
    assert rect is not None
    btn = window.job_buttons["requant"]
    assert rect.size() == btn.rect().size()

    def job(ctx):
        return "done"

    window._start_job_worker(job, "Test job", True, from_job="requant")
    assert window.job_card._morph_animation is not None
    window.job_card.finish()
    QTest.qWait(200)


def test_start_training_morphs_from_train_tile(
    window, monkeypatch, qapp
):
    """T149: training morphs out of the Train tile."""
    window._checklist_dismiss()
    _select_session(window)
    # T83: a valid dataset, so the pre-train check passes.
    window.store.update_project(
        "lfm3-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    _start_training_ready(window, monkeypatch)
    # R67: the seeded profile is role fast, so the governing-seat
    # question fires — Yes proceeds.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    window.start_training()
    assert window.job_card._morph_animation is not None
    window.job_card.finish()


# -- T147: reduced-motion and larger-text presets ----------------------


def test_settings_ease_of_use_checkboxes(window, qapp):
    """T147 Done: Settings has the two Ease of use presets, in
    plain words, both off by default."""
    win = window.open_settings_window()
    assert "Ease of use" in win.sections
    assert win.reduced_motion_check.text() == (
        "Less motion: buttons and cards change at once, "
        "with no animation."
    )
    assert win.larger_text_check.text() == (
        "Larger text: bigger words everywhere."
    )
    assert win.reduced_motion_check.isChecked() is False
    assert win.larger_text_check.isChecked() is False
    win.close()


def test_reduced_motion_disables_press_dip(window, qapp):
    """T147 Done: the Less motion preset stops the button press
    dip; turning it off brings the dip back."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QPushButton

    from stella import style as style_mod

    filt = style_mod.PressDipFilter(qapp)
    btn = QPushButton("Test")
    btn.resize(100, 30)
    press = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(10, 10),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    try:
        style_mod.set_reduced_motion(False)
        filt._filter.eventFilter(btn, press)
        assert btn in filt._animations
        style_mod.set_reduced_motion(True)
        filt._animations.clear()
        filt._filter.eventFilter(btn, press)
        assert btn not in filt._animations
    finally:
        style_mod.set_reduced_motion(False)


def test_larger_text_grows_app_font(window, qapp):
    """T147 Done: the Larger text preset grows the app font by 3
    points, idempotently, and turning it off restores it."""
    from stella import style as style_mod

    base = qapp.font().pointSize()
    assert base > 0
    try:
        style_mod.apply_text_size(qapp, True)
        assert qapp.font().pointSize() == base + 3
        style_mod.apply_text_size(qapp, True)
        assert qapp.font().pointSize() == base + 3  # idempotent
    finally:
        style_mod.apply_text_size(qapp, False)
    assert qapp.font().pointSize() == base


def test_accessibility_presets_persist(
    window, seeded, settings, qapp
):
    """T147 Done: the presets are saved in QSettings, applied
    live, and picked up by a new window."""
    from stella import style as style_mod
    from stella.gui import MainWindow

    base = qapp.font().pointSize()
    win = window.open_settings_window()
    try:
        win.reduced_motion_check.setChecked(True)
        win.larger_text_check.setChecked(True)
        assert settings.value(
            "accessibility/reduced_motion", type=bool
        ) is True
        assert settings.value(
            "accessibility/larger_text", type=bool
        ) is True
        assert style_mod.reduced_motion() is True
        assert qapp.font().pointSize() == base + 3
        # A new window applies them at once.
        win2 = MainWindow(store=seeded, settings=settings)
        try:
            assert style_mod.reduced_motion() is True
            assert qapp.font().pointSize() == base + 3
        finally:
            win2.close()
    finally:
        win.close()
        style_mod.set_reduced_motion(False)
        style_mod.apply_text_size(qapp, False)
    assert qapp.font().pointSize() == base


# -- v0.16.0: pre-train estimates + probe cluster ----------------------


def _write_dataset(path, n=20):
    """A valid prompt/completion JSONL dataset with n rows."""
    path.write_text(
        "".join(
            json.dumps({"prompt": f"Question {i}?", "completion": f"Answer {i}."})
            + "\n"
            for i in range(n)
        ),
        encoding="utf-8",
    )
    return path


def _fake_model_dir(path, total_size=3_460_000_000):
    """A local HF folder with a config + a weight-size index — no
    real weights, so the metadata read is fast and offline."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps({
        "hidden_size": 2048, "num_hidden_layers": 24,
        "intermediate_size": 8192, "torch_dtype": "bfloat16",
    }))
    (path / "model.safetensors.index.json").write_text(json.dumps({
        "metadata": {"total_size": total_size},
    }))
    return path


def _probe_result(mode="gate", rising=True):
    """A canned probe result: 2 prompts, refusals flat or rising."""
    before = {
        "total": 2, "refusals": 0, "empty": 0, "rate": 0.0,
        "details": [
            {
                "prompt": "Write a Python function that adds two numbers.",
                "reply": "Here is the function.",
                "refused": False, "empty": False,
            },
            {
                "prompt": "What is the capital of France?",
                "reply": "The capital of France is Paris.",
                "refused": False, "empty": False,
            },
        ],
    }
    after = {
        "total": 2, "refusals": 1 if rising else 0, "empty": 0,
        "rate": 0.5 if rising else 0.0,
        "details": [
            {
                "prompt": "Write a Python function that adds two numbers.",
                "reply": "Here is the function.",
                "refused": False, "empty": False,
            },
            {
                "prompt": "What is the capital of France?",
                "reply": "I'm sorry, I can't help with that.",
                "refused": True, "empty": False,
            },
        ],
    }
    if not rising:
        after["details"][1] = {
            "prompt": "What is the capital of France?",
            "reply": "The capital of France is Paris.",
            "refused": False, "empty": False,
        }
    return {
        "profile": "lfm3-tool", "project": "tool-calls",
        "before": before, "after": after,
        "delta": 0.5 if rising else 0.0,
        "timestamp": "2026-11-14T00:00:00+00:00",
        "base_ref": "test/tiny-model",
        "adapter": "/tmp/fake/adapter",
        "max_new_tokens": 64,
        "prompts_version": 2,
        "mode": mode,
    }


# -- T83: dataset health before training ------------------------------


def test_dataset_health_label_shows_row_count_and_format(window, seeded):
    # T83: a healthy dataset shows its row count and format.
    _select_session(window)
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    window.refresh_train_panel()
    text = window.dataset_health_label.text()
    assert "20 examples" in text
    assert "messages format" in text
    assert "tokens" in text
    assert "to train on" in text


def test_dataset_health_label_shows_error_for_malformed(
    window, seeded, tmp_path
):
    # T83: a malformed dataset names the bad line in the panel.
    _select_session(window)
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"prompt": "a", "completion": "b"}\nnot json\n')
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref=str(bad)
    )
    window.refresh_train_panel()
    text = window.dataset_health_label.text()
    assert "Dataset problem" in text
    assert "line 2" in text


def test_dataset_health_label_marks_tiny_dataset(window, seeded, tmp_path):
    # T83: a tiny dataset says so outright in the panel.
    _select_session(window)
    tiny = _write_dataset(tmp_path / "tiny.jsonl", 3)
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref=str(tiny)
    )
    window.refresh_train_panel()
    text = window.dataset_health_label.text()
    assert "3 examples" in text
    assert "Only a few examples" in text


def test_start_training_refuses_malformed_dataset(
    window, seeded, monkeypatch, tmp_path
):
    # T83: starting a run with a malformed dataset is refused
    # with the bad line numbers — no worker starts.
    _select_session(window)
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"prompt": "a", "completion": "b"}\nnot json\n')
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref=str(bad)
    )
    _start_training_ready(window, monkeypatch)
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.start_training()
    assert window._train_worker is None
    assert warnings
    assert "line 2" in warnings[0]
    assert "line 2" in window.train_log.toPlainText()


def test_start_training_refuses_missing_dataset(window, seeded, monkeypatch):
    # T83: the seeded ref points at a file that does not exist —
    # the run is refused, not started into a worker failure.
    _select_session(window)
    _start_training_ready(window, monkeypatch)
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.start_training()
    assert window._train_worker is None
    assert warnings
    assert "not found" in warnings[0]


def test_start_training_tiny_dataset_asks_first(
    window, seeded, monkeypatch, tmp_path
):
    # T83: a 3-example dataset asks to proceed — No stops the
    # start, Yes starts it.
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    tiny = _write_dataset(tmp_path / "tiny.jsonl", 3)
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref=str(tiny)
    )
    _start_training_ready(window, monkeypatch)
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No,
    )
    window.start_training()
    assert window._train_worker is None
    assert len(asked) == 1
    assert "only 3 examples" in asked[0]
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    window.start_training()
    assert window._train_worker is not None


# -- T84: RAM/time estimate in the Train panel ------------------------


def _estimable_session(window, seeded, tmp_path, total_size=3_460_000_000):
    """A session on a local fake model with the sample dataset —
    the estimate computes offline against it."""
    model_dir = _fake_model_dir(tmp_path / "model", total_size)
    seeded.create_profile("local-model", base_ref=str(model_dir))
    seeded.create_project(
        "local-model", "proj", dataset_ref="sample-tool-calls.jsonl"
    )
    window.set_session("local-model", "proj")
    return window


def test_estimate_label_shows_fit_for_small_model(
    window, seeded, tmp_path, qapp, monkeypatch
):
    # T84: the defaults on an LFM3-shaped base show "fits".
    # S6: the estimate judges against free RAM, so the test pins
    # a box with plenty free.
    import stella.train as train_mod

    monkeypatch.setattr(
        train_mod, "available_ram_bytes", lambda: 8 * 1024**3
    )
    _estimable_session(window, seeded, tmp_path)
    qapp.processEvents()
    text = window.train_estimate_label.text()
    assert text.startswith("Fits in 8 GB")
    assert "9 steps" in text
    # T16: no settings on screen.
    assert "rank" not in text
    assert "seq" not in text


def test_estimate_label_shows_will_not_fit_for_huge_model(
    window, seeded, tmp_path, qapp
):
    # T84: a 100 GB base shows "will not fit".
    _estimable_session(
        window, seeded, tmp_path, total_size=100_000_000_000
    )
    qapp.processEvents()
    assert window.train_estimate_label.text().startswith("Will not fit")


def test_estimate_label_updates_when_project_changes(
    window, seeded, tmp_path, qapp, monkeypatch
):
    # T84: the estimate updates when the selection changes.
    # S6: the estimate judges against free RAM, so the test pins
    # a box with plenty free.
    import stella.train as train_mod

    monkeypatch.setattr(
        train_mod, "available_ram_bytes", lambda: 8 * 1024**3
    )
    _estimable_session(window, seeded, tmp_path)
    qapp.processEvents()
    assert "Fits in 8 GB" in window.train_estimate_label.text()
    big = _fake_model_dir(tmp_path / "big", 100_000_000_000)
    seeded.create_profile("big-model", base_ref=str(big))
    seeded.create_project(
        "big-model", "proj", dataset_ref="sample-tool-calls.jsonl"
    )
    window.set_session("big-model", "proj")
    qapp.processEvents()
    assert "Will not fit" in window.train_estimate_label.text()
    window.set_session("local-model", "proj")
    qapp.processEvents()
    assert "Fits in 8 GB" in window.train_estimate_label.text()


def test_estimate_label_unavailable_without_base_ref(window, qapp):
    # T84: the seeded profile has no base ref — the label says
    # unavailable instead of guessing or fetching.
    _select_session(window)
    qapp.processEvents()
    assert window.train_estimate_label.text() == "Estimate unavailable."


# -- T85: dry-run estimate button -------------------------------------


def test_estimate_button_shows_dry_run_in_log(
    window, seeded, tmp_path, qapp, monkeypatch
):
    # T85: the Estimate button shows RAM fit, step count, and
    # disk needed in the log — without loading the model.
    import stella.train as train_mod

    _estimable_session(window, seeded, tmp_path)
    qapp.processEvents()
    # The no-load proof, at the GUI level: the loader is rigged
    # to fail, and the button still answers.
    monkeypatch.setattr(
        train_mod, "load_base_model",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("the dry run loaded the model")
        ),
    )
    window.train_estimate_btn.click()
    qapp.processEvents()
    log = window.train_log.toPlainText()
    assert "Dry run (no model loaded)" in log
    assert "RAM: about" in log
    assert "Steps: 9" in log
    assert "Disk: about" in log


def test_estimate_button_without_model_warns(window, monkeypatch, qapp):
    # T85: with no base ref the button warns plainly instead of
    # crashing or hanging on a fetch.
    _select_session(window)
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.train_estimate_btn.click()
    qapp.processEvents()
    assert warnings
    assert "base_ref" in warnings[0]


# -- T95: proof-run button --------------------------------------------


def test_proof_run_button_starts_capped_run(window, seeded, monkeypatch, qapp):
    # T95: the Proof run button starts training with the 5-step
    # cap passed through as max_steps.
    from stella.gui import PROOF_RUN_STEPS

    _select_session(window)
    seeded.update_project(
        "lfm3-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    _start_training_ready(window, monkeypatch)
    # R67: the seeded profile is role fast, so the governing-seat
    # question fires — Yes proceeds.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    assert window.train_proof_btn.text() == "Proof run"
    assert window.train_proof_btn.isEnabled()
    window.train_proof_btn.click()
    qapp.processEvents()
    assert window._train_worker is not None
    assert window._train_worker._max_steps == PROOF_RUN_STEPS == 5
    assert "Starting proof run (5 steps)" in window.train_log.toPlainText()


def test_proof_run_button_disabled_without_session(window):
    # T95/U6: no session, no proof run.
    assert not window.train_proof_btn.isEnabled()


# -- T96: val loss in the run summary ---------------------------------


def test_train_finished_shows_val_loss_in_summary_line(window, qapp):
    # T96: a finished run's summary line shows the final val loss
    # next to the training loss.
    _select_session(window)
    window._on_train_finished(
        True,
        "Trained 12 steps. Final loss 1.2345. Validation loss 1.1000.",
    )
    qapp.processEvents()
    assert "Validation loss 1.1000" in window.train_loss.text()
    assert "Final loss 1.2345" in window.train_loss.text()


def test_train_worker_finished_message_carries_val_loss(monkeypatch):
    # T96: the worker's finish message carries the val loss from
    # the run summary.
    import stella.gui as gui_mod
    import stella.train as train_mod

    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 12, "final_loss": 1.2345, "final_val_loss": 1.1,
            "stopped": False, "checkpoint": "/tmp/fake/step-12",
        },
    )
    seen = []
    worker = gui_mod.TrainWorker(None, "p1", "proj")
    worker.finished.connect(lambda ok, msg: seen.append((ok, msg)))
    worker.run()
    assert len(seen) == 1
    ok, message = seen[0]
    assert ok is True
    assert message == (
        "Trained 12 steps. Final loss 1.2345. Validation loss 1.1000."
    )


def test_train_worker_finished_message_without_val_loss(monkeypatch):
    # T96: a run that never validated (stopped mid-first-epoch)
    # omits the val half instead of printing a fake number.
    import stella.gui as gui_mod
    import stella.train as train_mod

    monkeypatch.setattr(
        train_mod, "train_project",
        lambda *a, **k: {
            "steps": 2, "final_loss": 2.5, "final_val_loss": None,
            "stopped": True, "checkpoint": "/tmp/fake/step-2",
        },
    )
    seen = []
    worker = gui_mod.TrainWorker(None, "p1", "proj")
    worker.finished.connect(lambda ok, msg: seen.append((ok, msg)))
    worker.run()
    assert seen[0][1] == "Trained 2 steps. Final loss 2.5000."
    assert "Validation loss" not in seen[0][1]


# -- T94: the probe results dialog ------------------------------------


def test_probe_results_dialog_shows_replies_side_by_side(window, qapp):
    # T94: per-prompt reply + refused flag, before and after side
    # by side, with the gate verdict.
    from PySide6.QtWidgets import QDialog

    from stella.gui import ProbeResultsDialog

    dialog = ProbeResultsDialog(window, _probe_result())
    assert dialog.windowTitle() == "Refusal probe results"
    assert "0/2 before" in dialog.counts_label.text()
    assert "1/2 after" in dialog.counts_label.text()
    assert "gate failed" in dialog.verdict_label.text()
    assert dialog.table.rowCount() == 2
    assert dialog.table.columnCount() == 5
    assert (
        dialog.table.item(0, 0).text()
        == "Write a Python function that adds two numbers."
    )
    assert dialog.table.item(0, 1).text() == "Here is the function."
    assert dialog.table.item(0, 2).text() == "Answered"
    assert dialog.table.item(1, 3).text() == "I'm sorry, I can't help with that."
    assert dialog.table.item(1, 4).text() == "Refused"
    assert dialog.close_btn.text() == "Close"
    dialog.show()
    qapp.processEvents()
    assert dialog.isVisible()
    dialog.close()
    assert isinstance(dialog, QDialog)


def test_probe_results_dialog_informational_has_no_verdict(window, qapp):
    # T90/T94: an informational run shows no gate verdict in the
    # dialog — only the counts and the change.
    from stella.gui import ProbeResultsDialog

    dialog = ProbeResultsDialog(window, _probe_result(mode="informational"))
    assert "Informational only" in dialog.verdict_label.text()
    assert "Gate" not in dialog.verdict_label.text()
    dialog.close()


def test_probe_results_dialog_names_silent_prompts(window, qapp):
    # T30/T94: a prompt that got no answer shows "(no answer)",
    # not a blank cell.
    from stella.gui import ProbeResultsDialog

    result = _probe_result()
    result["before"]["details"][0] = {
        "prompt": "Write a Python function that adds two numbers.",
        "reply": "", "refused": False, "empty": True,
    }
    dialog = ProbeResultsDialog(window, result)
    assert dialog.table.item(0, 1).text() == "(no answer)"
    assert dialog.table.item(0, 2).text() == "No answer"
    dialog.close()


def test_probe_results_dialog_export_mode_buttons(window, qapp):
    # T148: export mode swaps Close for Export / Go back.
    from stella.gui import ProbeResultsDialog

    dialog = ProbeResultsDialog(window, _probe_result(), export_mode=True)
    assert dialog.windowTitle().startswith("Before you export")
    assert dialog.export_btn.text() == "Export"
    assert dialog.go_back_btn.text() == "Go back"
    assert not hasattr(dialog, "close_btn")
    dialog.close()


# -- T90: informational probe in the window ---------------------------


def _run_probe_with_fake_engine(window, seeded, monkeypatch, qapp, role):
    """Run the GUI probe against a fake probe_project that writes
    a rising result file; returns (log_text, dialog_opened)."""
    from PySide6.QtTest import QTest

    import stella.probe as probe_mod
    from stella.gui import ProbeResultsDialog

    seeded.create_profile("probe-seat", role=role, base_ref="test/tiny-model")
    seeded.create_project("probe-seat", "proj")
    window.set_session("probe-seat", "proj")
    qapp.processEvents()
    opened = []

    def fake_probe(store, profile, project, **kwargs):
        result = _probe_result(
            mode="informational" if kwargs.get("informational") else "gate"
        )
        result["profile"] = profile
        result["project"] = project
        (
            store.project_dir(profile, project) / "probe_results.json"
        ).write_text(json.dumps(result))
        return result

    monkeypatch.setattr(probe_mod, "probe_project", fake_probe)
    monkeypatch.setattr(
        ProbeResultsDialog, "exec",
        lambda self: opened.append(self) or 0,
    )
    window.run_probe_gui()
    # The fake job finishes at once; wait for the worker + the
    # queued finish slots (the dialog open is one of them).
    for _ in range(50):
        qapp.processEvents()
        QTest.qWait(20)
        if window._job_worker is not None and not window._job_worker.isRunning():
            qapp.processEvents()
            break
    qapp.processEvents()
    return window.train_log.toPlainText(), opened


def test_probe_gui_informational_for_non_governing_profile(
    window, seeded, monkeypatch, qapp
):
    # T90: a "vision" profile probes informationally — counts and
    # change, no verdict — and the dialog opens with no verdict.
    log, opened = _run_probe_with_fake_engine(
        window, seeded, monkeypatch, qapp, role="vision"
    )
    assert "0/2 refusals before, 1/2 after" in log
    assert "Informational only" in log
    assert "Gate failed" not in log
    assert "Gate passed" not in log
    assert len(opened) == 1
    assert "Informational only" in opened[0].verdict_label.text()


def test_probe_gui_gate_for_governing_profile(
    window, seeded, monkeypatch, qapp
):
    # T90: a driver seat gets the gate — the verdict is in the log
    # and in the dialog.
    log, opened = _run_probe_with_fake_engine(
        window, seeded, monkeypatch, qapp, role="driver"
    )
    assert "0/2 refusals before, 1/2 after" in log
    assert "gate failed" in log
    assert len(opened) == 1
    assert "gate failed" in opened[0].verdict_label.text()


def test_view_probe_results_opens_saved_results(
    window, seeded, monkeypatch, qapp
):
    # T94: View probe results re-opens the saved evidence after
    # the run.
    from stella.gui import ProbeResultsDialog

    _select_session(window)
    (
        seeded.project_dir("lfm3-tool", "tool-calls") / "probe_results.json"
    ).write_text(json.dumps(_probe_result()))
    opened = []
    monkeypatch.setattr(
        ProbeResultsDialog, "exec",
        lambda self: opened.append(self) or 0,
    )
    window.train_view_probe_btn.click()
    qapp.processEvents()
    assert len(opened) == 1
    assert opened[0].table.rowCount() == 2


def test_view_probe_results_without_results_warns(window, monkeypatch, qapp):
    # T94: with no probe run yet, the button says so instead of
    # opening an empty dialog.
    _select_session(window)
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.train_view_probe_btn.click()
    qapp.processEvents()
    assert warnings
    assert "No probe results yet" in warnings[0]


# -- T148: before/after preview before export -------------------------


def test_export_offers_preview_and_go_back_cancels(
    window, seeded, monkeypatch, qapp
):
    # T148: with probe results, Export shows the preview — Go back
    # cancels before any folder is picked.
    from PySide6.QtWidgets import QDialog, QFileDialog

    from stella.gui import ProbeResultsDialog

    _select_session(window)
    # R4: the probe must PASS the gate for the preview to open —
    # a rising (failed-gate) result on this governing profile
    # would refuse the export before the preview.
    (
        seeded.project_dir("lfm3-tool", "tool-calls") / "probe_results.json"
    ).write_text(json.dumps(_probe_result(rising=False)))
    opened = []
    monkeypatch.setattr(
        ProbeResultsDialog, "exec",
        lambda self: opened.append(self) or QDialog.Rejected,
    )
    picked = []
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: picked.append(True) or "",
    )
    window.export_gguf_gui()
    qapp.processEvents()
    assert len(opened) == 1
    assert hasattr(opened[0], "export_btn")
    assert picked == []
    assert window._job_worker is None
    assert window.statusBar().currentMessage() == "Export cancelled."


def test_export_preview_export_goes_ahead(window, seeded, monkeypatch, qapp):
    # T148: Export in the preview goes ahead to the folder pick
    # and starts the export job.
    from PySide6.QtWidgets import QDialog, QFileDialog

    import stella.gguf as gguf_mod
    from stella.gui import ProbeResultsDialog

    _select_session(window)
    # R4: the probe must PASS the gate for the preview to open —
    # see test_export_offers_preview_and_go_back_cancels.
    (
        seeded.project_dir("lfm3-tool", "tool-calls") / "probe_results.json"
    ).write_text(json.dumps(_probe_result(rising=False)))
    opened = []
    monkeypatch.setattr(
        ProbeResultsDialog, "exec",
        lambda self: opened.append(self) or QDialog.Accepted,
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: "/tmp/fake-export",
    )
    monkeypatch.setattr(
        gguf_mod, "export_gguf",
        lambda *a, **k: {
            "gguf": "/tmp/fake-export/model.gguf", "gguf_bytes": 123,
            "ollama_create": "ollama create x -f /tmp/fake-export/Modelfile",
        },
    )
    window.export_gguf_gui()
    qapp.processEvents()
    assert len(opened) == 1
    assert window._job_worker is not None
    window._job_worker.wait(5000)
    qapp.processEvents()


def test_export_without_probe_results_skips_preview(
    window, seeded, monkeypatch, qapp
):
    # T148: with no probe results there is nothing to preview —
    # the export proceeds straight to the folder pick. R4: the
    # profile is non-governing here — a governing profile with no
    # probe is refused outright (see the R4 tests below).
    from PySide6.QtWidgets import QFileDialog

    import stella.gguf as gguf_mod
    from stella.gui import ProbeResultsDialog

    seeded.update_profile("lfm3-tool", role="utility")
    _select_session(window)
    monkeypatch.setattr(
        ProbeResultsDialog, "exec",
        lambda self: (_ for _ in ()).throw(
            AssertionError("preview opened with no results")
        ),
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: "/tmp/fake-export",
    )
    monkeypatch.setattr(
        gguf_mod, "export_gguf",
        lambda *a, **k: {
            "gguf": "/tmp/fake-export/model.gguf", "gguf_bytes": 123,
            "ollama_create": "ollama create x -f /tmp/fake-export/Modelfile",
        },
    )
    window.export_gguf_gui()
    qapp.processEvents()
    assert window._job_worker is not None
    window._job_worker.wait(5000)
    qapp.processEvents()


def test_export_governing_without_probe_is_refused(
    window, seeded, monkeypatch, qapp
):
    """R4: a governing profile with no probe result cannot export
    from the window — it warns in plain words, never asks for a
    folder, and starts no job."""
    from PySide6.QtWidgets import QFileDialog

    from stella.gui import ProbeResultsDialog

    _select_session(window)
    warned = []
    monkeypatch.setattr(window, "_warn", warned.append)
    monkeypatch.setattr(
        ProbeResultsDialog, "exec",
        lambda self: (_ for _ in ()).throw(
            AssertionError("preview opened on a refused export")
        ),
    )
    picked = []
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: picked.append(True) or "/tmp/fake-export",
    )
    window.export_gguf_gui()
    qapp.processEvents()
    assert warned and "refusal probe" in warned[0]
    assert picked == []
    assert window._job_worker is None


def test_export_governing_failed_gate_is_refused(
    window, seeded, monkeypatch, qapp
):
    """R4: a governing profile whose probe FAILED cannot export —
    the preview never opens, because there is nothing to go ahead
    with."""
    from PySide6.QtWidgets import QFileDialog

    from stella.gui import ProbeResultsDialog

    _select_session(window)
    (
        seeded.project_dir("lfm3-tool", "tool-calls") / "probe_results.json"
    ).write_text(json.dumps(_probe_result(rising=True)))
    warned = []
    monkeypatch.setattr(window, "_warn", warned.append)
    monkeypatch.setattr(
        ProbeResultsDialog, "exec",
        lambda self: (_ for _ in ()).throw(
            AssertionError("preview opened on a refused export")
        ),
    )
    picked = []
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: picked.append(True) or "/tmp/fake-export",
    )
    window.export_gguf_gui()
    qapp.processEvents()
    assert warned and "did not pass" in warned[0]
    assert picked == []
    assert window._job_worker is None


# -- T141: corrupt-block tests for the GUI list + detail fill + save --


@pytest.mark.parametrize(
    "mutate, warns",
    [
        (lambda d: d.update(metamorph=None), True),
        (lambda d: d.pop("metamorph"), False),
        (lambda d: d.update(metamorph="both"), True),
    ],
)
def test_tree_survives_corrupt_metamorph(
    window, seeded, qapp, mutate, warns
):
    # T141: null / missing-key / wrong-type metamorph in
    # project.json — the tree shows the row, warns when the block
    # is broken (a missing key just means the default), and never
    # crashes.
    seeded.create_project("lfm3-tool", "broken")
    _corrupt_project_json(seeded, "lfm3-tool", "broken", mutate)
    window.refresh_tree()
    qapp.processEvents()
    top = window.tree.topLevelItem(0)
    rows = {top.child(i).text(0) for i in range(top.childCount())}
    assert top.childCount() == 2
    assert any(r.startswith("broken") for r in rows)
    warned = [r for r in rows if "warning" in r]
    if warns:
        assert len(warned) == 1
        assert "broken" in warned[0]
    else:
        assert warned == []
    # The good project lists normally, with its status and no warning.
    assert any(r == "tool-calls (draft) [forge-traces.jsonl]" for r in rows)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(metamorph=None),
        lambda d: d.pop("metamorph"),
        lambda d: d.update(metamorph="both"),
    ],
)
def test_project_window_survives_corrupt_metamorph(
    window, seeded, qapp, mutate
):
    # T141: null / missing-key / wrong-type metamorph — the detail
    # fill reads through the defensive reader (the window shows no
    # metamorph control, so there is no note and nothing to fill
    # wrong), and saving heals the block to the default on disk.
    _corrupt_project_json(seeded, "lfm3-tool", "tool-calls", mutate)
    win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert win.display_edit.text() == "tool-calls"
    assert win.dataset_edit.text() == "forge-traces.jsonl"
    assert win._load_note.text() == ""
    assert not win._load_note.isVisible()
    assert win.save() is True
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["metamorph"]["mode"] == "morph"
    win.close()

# -- v0.18.0: export/import/clone --------------------------------------


def test_export_runs_on_job_card_with_progress(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T106 Done: the menu export runs on the job card with a
    determinate progress bar, and the package lands."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    import stella.export as export_mod

    _select_session(window)
    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    # A slow copy, so the card is visible mid-job.
    real_copy = export_mod._copy_file_counted

    def slow_copy(src, dst, progress):
        import time as time_mod

        time_mod.sleep(0.3)
        return real_copy(src, dst, progress)

    monkeypatch.setattr(export_mod, "_copy_file_counted", slow_copy)
    window.export_project()
    # The job card is visible mid-job, and the worker's progress
    # signal reports real bytes (done > 0, total > 0).
    seen = []
    window._job_worker.progress.connect(
        lambda done, total: seen.append((done, total))
    )
    assert window.job_card.isVisible()
    assert window.job_card.title_label.text() == "Exporting project"
    _wait_for_job(window, qapp)
    assert (dest / "tool-calls-stella-export" / "manifest.json").is_file()
    assert seen, "the export job never reported progress"
    assert any(done > 0 and total > 0 for done, total in seen), seen
    assert seen[-1][0] == seen[-1][1], "the bar never reached the end"


def test_export_cancel_leaves_no_package(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T106 Done: cancelling an export leaves no partial package."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    import stella.export as export_mod

    _select_session(window)
    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    # The cancelled job warns on its finish path — a real modal
    # would hang the test with nobody to click it.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    real_copy = export_mod._copy_file_counted

    def slow_copy(src, dst, progress):
        import time as time_mod

        time_mod.sleep(0.5)
        # Cancel deterministically mid-export: the main thread's
        # cancel below races the worker under load. Requesting the
        # cancel here, from the worker itself, guarantees it is
        # in flight while the export still has checks ahead of
        # it. The GUI cancel below still runs (idempotently).
        if window._job_worker is not None:
            window._job_worker.request_cancel()
        return real_copy(src, dst, progress)

    monkeypatch.setattr(export_mod, "_copy_file_counted", slow_copy)
    window.export_project()
    # Cancel once the worker is actually running: a fixed-delay
    # timer can fire before the thread starts under load, and the
    # cancel would be lost. The slow copy keeps the job alive
    # long after the worker starts.
    for _ in range(100):
        if window._job_worker is not None and window._job_worker.isRunning():
            break
        QTest.qWait(20)
    assert window._job_worker is not None and window._job_worker.isRunning()
    window._cancel_current_job()
    _wait_for_job(window, qapp)
    assert not (dest / "tool-calls-stella-export").exists()
    assert list(dest.iterdir()) == []
    assert "Cancelled" in window.train_log.toPlainText()


def test_import_cancel_leaves_home_untouched(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T106 Done: cancelling an import leaves the home as it was."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    import stella.export as export_mod
    from stella.model import StellaError

    seed_models(["lfm3:1.7b"])
    # A checkpoint in the package, so the import has a real file
    # copy to slow down: notes restore through write_notes, not
    # the counted copy, and a payload-free package imports faster
    # than the cancel timer.
    ckpt = (
        seeded.project_dir("lfm3-tool", "tool-calls")
        / "checkpoints" / "step-10"
    )
    ckpt.mkdir(parents=True)
    (ckpt / "training_state.json").write_text(
        json.dumps({"step": 10, "epoch": 1, "loss": 0.5})
    )
    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(window, "_offer_locate_dataset", lambda *a: None)
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    real_copy = export_mod._copy_file_counted

    def slow_copy(src, dst, progress):
        import time as time_mod

        time_mod.sleep(0.5)
        # Cancel deterministically mid-import: the main thread's
        # cancel below races the worker under load, and a cancel
        # that lands after the import's last check point goes
        # unnoticed — the import reports success. Requesting the
        # cancel here, from the worker itself, guarantees it is
        # in flight while the import still has checks ahead of
        # it. The GUI cancel below still runs (idempotently).
        if window._job_worker is not None:
            window._job_worker.request_cancel()
        return real_copy(src, dst, progress)

    monkeypatch.setattr(export_mod, "_copy_file_counted", slow_copy)
    window.import_package()
    # Cancel once the worker is actually running: a fixed-delay
    # timer can fire before the thread starts under load, and the
    # cancel would be lost. The slow copy keeps the job alive
    # long after the worker starts.
    for _ in range(100):
        if window._job_worker is not None and window._job_worker.isRunning():
            break
        QTest.qWait(20)
    assert window._job_worker is not None and window._job_worker.isRunning()
    window._cancel_current_job()
    _wait_for_job(window, qapp)
    with pytest.raises(StellaError):
        seeded.get_project("lfm3-tool", "tool-calls")
    assert "Cancelled" in window.train_log.toPlainText()


def test_export_failure_refreshes_lists(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T106 Done: a failed export warns and the window still
    matches the disk."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    import stella.export as export_mod
    from stella.model import StellaError

    _select_session(window)
    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    monkeypatch.setattr(
        export_mod, "export_project",
        lambda *a, **k: (_ for _ in ()).throw(
            StellaError("disk full (test)")
        ),
    )
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.export_project()
    _wait_for_job(window, qapp)
    assert warnings
    assert "disk full (test)" in warnings[0]
    assert window.tree.topLevelItemCount() == 1
    assert window.tree.topLevelItem(0).childCount() == 1


def test_export_overwrite_prompt_overwrites(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T117 Done: exporting over an existing package asks first;
    Overwrite replaces it."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QMessageBox,
    )

    _select_session(window)
    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window.export_project()
    _wait_for_job(window, qapp)
    pkg = dest / "tool-calls-stella-export"
    marker = pkg / "marker.txt"
    marker.write_text("old package")
    clicker = QTimer()
    clicker.setInterval(50)

    def click_overwrite():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_overwrite_button"):
            clicker.stop()
            dlg._stella_overwrite_button.click()

    clicker.timeout.connect(click_overwrite)
    clicker.start()
    window.export_project()
    _wait_for_job(window, qapp)
    clicker.stop()
    assert (pkg / "manifest.json").is_file()
    assert not marker.exists(), "the old package was not replaced"


def test_export_overwrite_prompt_cancel_keeps_old(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T117 Done: cancelling the overwrite prompt keeps the old
    package and starts no job."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QMessageBox,
    )

    _select_session(window)
    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window.export_project()
    _wait_for_job(window, qapp)
    pkg = dest / "tool-calls-stella-export"
    marker = pkg / "marker.txt"
    marker.write_text("old package")
    clicker = QTimer()
    clicker.setInterval(50)

    def click_cancel():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_cancel_button"):
            clicker.stop()
            dlg._stella_cancel_button.click()

    clicker.timeout.connect(click_cancel)
    clicker.start()
    window.export_project()
    qapp.processEvents()
    clicker.stop()
    assert marker.read_text() == "old package"
    assert "cancelled" in window.statusBar().currentMessage().lower()


def test_import_collision_copy(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T117 Done: importing a project that already exists offers
    a copy; choosing it lands under a new slug."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QMessageBox,
    )

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    # The seeded project is still here: a collision.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(window, "_offer_locate_dataset", lambda *a: None)
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    clicker = QTimer()
    clicker.setInterval(50)

    def click_copy():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_copy_button"):
            clicker.stop()
            dlg._stella_copy_button.click()

    clicker.timeout.connect(click_copy)
    clicker.start()
    window.import_package()
    _wait_for_job(window, qapp)
    clicker.stop()
    assert seeded.get_project("lfm3-tool", "tool-calls-copy")
    assert "copy of 'tool-calls'" in window.statusBar().currentMessage()


def test_import_collision_replace_moves_old_to_trash(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T117 Done: Replace moves the old project to the trash."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QMessageBox,
    )

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(window, "_offer_locate_dataset", lambda *a: None)
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    clicker = QTimer()
    clicker.setInterval(50)

    def click_replace():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_replace_button"):
            clicker.stop()
            dlg._stella_replace_button.click()

    clicker.timeout.connect(click_replace)
    clicker.start()
    window.import_package()
    _wait_for_job(window, qapp)
    clicker.stop()
    assert seeded.get_project("lfm3-tool", "tool-calls")
    assert seeded.list_trash()
    assert "went to the trash" in window.statusBar().currentMessage()


def test_import_collision_cancel_imports_nothing(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T117 Done: cancelling the collision dialog imports
    nothing and starts no job."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QMessageBox,
    )

    from stella.model import StellaError

    seed_models(["lfm3:1.7b"])
    pkg = _source_package(tmp_path)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    clicker = QTimer()
    clicker.setInterval(50)

    def click_cancel():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_cancel_button"):
            clicker.stop()
            dlg._stella_cancel_button.click()

    clicker.timeout.connect(click_cancel)
    clicker.start()
    window.import_package()
    qapp.processEvents()
    clicker.stop()
    assert window._job_worker is None
    with pytest.raises(StellaError):
        seeded.get_project("lfm3-tool", "tool-calls-copy")
    assert "cancelled" in window.statusBar().currentMessage().lower()


def test_export_profile_menu_includes_projects(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T86 Done: Export profile with "Include projects" writes a
    profile package carrying the project."""
    import json as json_mod

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QApplication, QFileDialog, QMessageBox,
    )

    _select_session(window)
    assert window._menu_action_export_profile.isEnabled()
    dest = tmp_path / "exports"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    clicker = QTimer()
    clicker.setInterval(50)

    def click_include():
        dlg = QApplication.activeModalWidget()
        if dlg is not None and hasattr(dlg, "_stella_include_button"):
            clicker.stop()
            dlg._stella_include_button.click()

    clicker.timeout.connect(click_include)
    clicker.start()
    window.export_profile()
    _wait_for_job(window, qapp)
    clicker.stop()
    pkg = dest / "lfm3-tool-stella-profile-export"
    manifest = json_mod.loads((pkg / "manifest.json").read_text())
    assert manifest["kind"] == "stella-profile-export"
    assert [p["name"] for p in manifest["projects"]] == ["tool-calls"]
    assert (pkg / "projects" / "tool-calls").is_dir()


def test_import_profile_package_via_gui(
    window, seeded, tmp_path, monkeypatch, qapp, seed_models
):
    """T86 Done: importing a profile package through the window
    lands the profile and its projects."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    import stella.export as export_mod

    seed_models(["lfm3:1.7b"])
    pkg = export_mod.export_profile(
        seeded, "lfm3-tool", tmp_path / "exports",
        include_projects=True,
    )
    seeded._destroy_profile("lfm3-tool")
    window.refresh_tree()
    window.set_session(None, None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(window, "_offer_locate_dataset", lambda *a: None)
    monkeypatch.setattr(
        window, "_confirm_import_preview", lambda *a: (True, None)
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    window.import_package()
    _wait_for_job(window, qapp)
    assert seeded.get_profile("lfm3-tool")
    assert seeded.get_project("lfm3-tool", "tool-calls")
    assert "Imported profile lfm3-tool" in (
        window.statusBar().currentMessage()
    )


def test_check_package_reports_good_and_bad(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T105 Done: Check package reports the checks and imports
    nothing."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    import stella.export as export_mod

    pkg = export_mod.export_project(
        seeded, "lfm3-tool", "tool-calls", tmp_path / "exports"
    )
    seen = []
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda self: seen.append(
            (self.text(), self.informativeText())
        ) or 0,
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg)
    )
    window.check_package()
    qapp.processEvents()
    assert len(seen) == 1
    assert "All checks passed" in seen[0][0]
    assert "OK: Manifest present" in seen[0][1]
    (pkg / "notes.md").write_bytes(b"tampered")
    window.check_package()
    qapp.processEvents()
    assert len(seen) == 2
    assert "A check failed" in seen[1][0]
    assert "FAIL: Files match their checksums" in seen[1][1]
    assert "notes.md" in seen[1][1]


def test_clone_button_copies_project(
    window, seeded, monkeypatch, qapp
):
    """T112 Done: the Clone button in the project window copies
    the settings and dataset, no checkpoints, and the session
    moves to the clone."""
    from PySide6.QtWidgets import QInputDialog

    _select_session(window)
    win = window.open_project_window()
    qapp.processEvents()
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("cloned-one", True)
    )
    clone_btn = next(
        b for b in win.findChildren(QPushButton) if b.text() == "Clone"
    )
    clone_btn.click()
    qapp.processEvents()
    clone = seeded.get_project("lfm3-tool", "cloned-one")
    assert clone["settings"] == seeded.get_project(
        "lfm3-tool", "tool-calls"
    )["settings"]
    assert window._current_project == "cloned-one"
    assert "Cloned tool-calls as cloned-one." in (
        window.statusBar().currentMessage()
    )
    win.close()


def test_new_project_template_picker(
    window, seeded, monkeypatch, qapp
):
    """T112 Done: the New Project dialog's template picker starts
    a project from the LFM3 tool-format template — and shows no
    training settings (T16)."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog

    from stella.model import metamorph_mode

    _select_session(window)

    def fill_and_accept():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        assert dlg.template_combo.itemText(0).startswith("No template")
        # No settings anywhere in the picker: names and plain
        # words only.
        texts = [
            dlg.template_combo.itemText(i)
            for i in range(dlg.template_combo.count())
        ]
        assert not any(
            "rank" in t or "learning" in t for t in texts
        )
        dlg.name_edit.setText("tool-try")
        index = dlg.template_combo.findData("lfm3-tool-format")
        assert index > 0
        dlg.template_combo.setCurrentIndex(index)
        assert "tool call" in dlg.description_label.text().lower()
        dlg.accept()

    QTimer.singleShot(100, fill_and_accept)
    window.new_project()
    qapp.processEvents()
    proj = seeded.get_project("lfm3-tool", "tool-try")
    assert proj["dataset_ref"] == "sample-tool-calls.jsonl"
    assert metamorph_mode(proj) == "both"
    assert proj["settings"]["rank"] == 8


def test_new_project_blank_start_still_works(
    window, seeded, monkeypatch, qapp
):
    """T112: "No template: start blank" creates a plain project,
    as before."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    _select_session(window)

    def fill_and_accept():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        assert dlg.template_combo.currentData() is None
        dlg.name_edit.setText("blank-one")
        dlg.accept()

    QTimer.singleShot(100, fill_and_accept)
    window.new_project()
    qapp.processEvents()
    proj = seeded.get_project("lfm3-tool", "blank-one")
    assert proj["dataset_ref"] == ""


def test_gguf_job_shows_phase_progress(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T107 Done: the GGUF job's bar moves per phase (merge 1 of
    3, convert 2 of 3, quantize 3 of 3)."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFileDialog

    import stella.gguf as gguf_mod

    # R4: a governing profile with no probe is refused before the
    # job starts — this test is about the job's bar, so the
    # profile is non-governing here.
    seeded.update_profile("lfm3-tool", role="utility")
    _select_session(window)
    dest = tmp_path / "gguf"
    dest.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest)
    )
    seen = []

    def fake_export(store, profile, project, out, **kwargs):
        import time as time_mod

        on_event = kwargs.get("on_event")
        for phase in ("merge", "convert", "quantize"):
            on_event(
                {"type": "phase", "phase": phase,
                 "message": f"{phase}..."}
            )
            time_mod.sleep(0.2)
        return {
            "gguf": str(dest / "model.gguf"), "gguf_bytes": 123,
            "ollama_create": "ollama create x -f Modelfile",
        }

    monkeypatch.setattr(gguf_mod, "export_gguf", fake_export)
    window.export_gguf_gui()
    for _ in range(100):
        QTest.qWait(50)
        value = window.job_card.progress.value()
        if value and value not in seen:
            seen.append(value)
        if window._job_worker is not None and not window._job_worker.isRunning():
            break
    _wait_for_job(window, qapp)
    assert window.job_card.progress.maximum() == 3
    assert 1 in seen and 2 in seen and 3 in seen, seen


def test_probe_job_shows_per_prompt_progress(
    window, seeded, monkeypatch, qapp
):
    """T107 Done: the probe job's bar moves per prompt."""
    from PySide6.QtTest import QTest

    import stella.probe as probe_mod
    from stella.gui import ProbeResultsDialog

    seeded.create_profile("probe-seat", role="vision",
                          base_ref="test/tiny-model")
    seeded.create_project("probe-seat", "proj")
    window.set_session("probe-seat", "proj")
    qapp.processEvents()
    monkeypatch.setattr(
        ProbeResultsDialog, "exec", lambda self: 0
    )

    def fake_probe(store, profile, project, **kwargs):
        import time as time_mod

        on_event = kwargs.get("on_event")
        for phase in ("before", "after"):
            for done in (1, 2):
                on_event(
                    {"type": "prompt", "phase": phase,
                     "done": done, "total": 2}
                )
                time_mod.sleep(0.15)
        result = _probe_result(mode="informational")
        result["profile"] = profile
        result["project"] = project
        return result

    monkeypatch.setattr(probe_mod, "probe_project", fake_probe)
    window.run_probe_gui()
    seen = []
    for _ in range(100):
        QTest.qWait(50)
        value = window.job_card.progress.value()
        if value and value not in seen:
            seen.append(value)
        if window._job_worker is not None and not window._job_worker.isRunning():
            break
    _wait_for_job(window, qapp)
    assert seen, "the probe job never moved the bar"


def test_create_in_ollama_button(
    window, seeded, tmp_path, monkeypatch, qapp
):
    """T89 Done: Create in Ollama is greyed out with no export,
    live with one, and runs `ollama create` on the job card."""
    import json as json_mod

    from PySide6.QtWidgets import QFileDialog

    import stella.gguf as gguf_mod

    _select_session(window)
    window._refresh_go()
    assert window.train_create_ollama_btn.isEnabled() is False
    modelfile = tmp_path / "Modelfile"
    modelfile.write_text("FROM /tmp/model.gguf\n")
    (
        seeded.project_dir("lfm3-tool", "tool-calls") / "gguf-export.json"
    ).write_text(json_mod.dumps({
        "ollama_name": "lfm3-tool-tool-calls",
        "modelfile": str(modelfile),
    }))
    window._refresh_go()
    assert window.train_create_ollama_btn.isEnabled() is True
    seen = []
    monkeypatch.setattr(
        gguf_mod, "create_in_ollama",
        lambda name, mf, **k: seen.append((name, str(mf))) or "created",
    )
    window.train_create_ollama_btn.click()
    _wait_for_job(window, qapp)
    assert seen == [("lfm3-tool-tool-calls", str(modelfile))]
    assert "Created in Ollama as lfm3-tool-tool-calls." in (
        window.statusBar().currentMessage()
    )


# -- v0.19.0: T114, T115, T116, T120, T121, T122, T124, T126, T127 ---


def test_project_window_metamorph_notes_save_through(window, seeded):
    """T114 Done: the Why this mode notes are editable in the
    project window and persist; the stored mode shows as a label
    (no mode picker — the word stays out of visible text, T71)."""
    win = window.open_project_window("lfm3-tool", "tool-calls")
    assert win.metamorph_mode_label.text() == "both"
    assert win.metamorph_notes_edit.toPlainText() == ""
    assert win.notes_section.title == "Project notes"
    win.metamorph_notes_edit.setPlainText("both, the traces compress well")
    assert win.save() is True
    proj = seeded.get_project("lfm3-tool", "tool-calls")
    assert proj["metamorph"]["notes"] == "both, the traces compress well"
    assert proj["metamorph"]["mode"] == "both"
    win.close()
    win2 = window.open_project_window("lfm3-tool", "tool-calls")
    assert win2.metamorph_notes_edit.toPlainText() == (
        "both, the traces compress well"
    )
    assert win2.metamorph_mode_label.text() == "both"
    win2.close()


def test_profile_window_config_save_through(window, seeded):
    """T115 Done: edit config JSON in the profile window, save,
    reopen — the values persist."""
    win = window.open_profile_window("lfm3-tool")
    assert win.config_edit.toPlainText() == ""
    win.config_edit.setPlainText('{"key": "value", "n": 3}')
    assert win.save() is True
    assert seeded.get_profile("lfm3-tool")["config"] == {
        "key": "value", "n": 3,
    }
    win.close()
    win2 = window.open_profile_window("lfm3-tool")
    assert '"key": "value"' in win2.config_edit.toPlainText()
    win2.close()


def test_profile_window_config_bad_json_refused(
    window, seeded, monkeypatch
):
    """T115 Done: invalid JSON is refused with a readable error
    and the old values stay — nothing is written."""
    from PySide6.QtWidgets import QMessageBox

    seeded.update_profile("lfm3-tool", config={"keep": True})
    win = window.open_profile_window("lfm3-tool")
    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warned.append(a[2])
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Discard
    )
    win.config_edit.setPlainText('{"key": ')
    assert win.save() is False
    assert warned and "not valid JSON" in warned[0]
    assert seeded.get_profile("lfm3-tool")["config"] == {"keep": True}
    win.close()


def test_profile_window_dependencies_editable(window, seeded):
    """T115: the dependency list adds and removes rows, and
    saves through."""
    win = window.open_profile_window("lfm3-tool")
    win.dep_add_edit.setText("torch")
    win._add_dependency()
    win.dep_add_edit.setText("transformers")
    win._add_dependency()
    assert win._deps_values() == ["torch", "transformers"]
    # A duplicate is ignored, not added twice.
    win.dep_add_edit.setText("torch")
    win._add_dependency()
    assert win._deps_values() == ["torch", "transformers"]
    assert win.save() is True
    assert seeded.get_profile("lfm3-tool")["dependencies"] == [
        "torch", "transformers",
    ]
    win.deps_list.setCurrentRow(0)
    win._remove_dependency()
    assert win.save() is True
    assert seeded.get_profile("lfm3-tool")["dependencies"] == [
        "transformers",
    ]
    win.close()


def test_profile_window_role_combo_offers_canonical_list(window):
    """T116/T122 Done: the detail panel's role field is an
    editable combo offering the canonical list."""
    from stella.model import CANONICAL_ROLES

    win = window.open_profile_window("lfm3-tool")
    items = [
        win.role_combo.itemText(i) for i in range(win.role_combo.count())
    ]
    assert items == list(CANONICAL_ROLES)
    assert win.role_combo.isEditable()
    assert win.role_combo.currentText() == "fast"
    win.close()


def test_profile_window_custom_role_flagged(window, qapp):
    """T116 Done: a role outside the canonical list is kept and
    visibly marked custom."""
    win = window.open_profile_window("lfm3-tool")
    assert not win.custom_role_note.isVisible()
    win.role_combo.setCurrentText("drvier")
    qapp.processEvents()
    assert win.custom_role_note.isVisible()
    assert "Custom role" in win.custom_role_note.text()
    win.role_combo.setCurrentText("driver")
    assert not win.custom_role_note.isVisible()
    win.role_combo.setCurrentText("fast")
    win.close()


def test_profile_window_governing_seat_saves(window, seeded):
    """T116: the governing-seat marker is set in the profile
    window and persists."""
    win = window.open_profile_window("lfm3-tool")
    assert win.seat_combo.currentText() == "(not bound)"
    win.seat_combo.setCurrentText("driver")
    assert win.save() is True
    assert seeded.get_profile("lfm3-tool")["governing_seat"] == "driver"
    win.close()
    win2 = window.open_profile_window("lfm3-tool")
    assert win2.seat_combo.currentText() == "driver"
    win2.close()


def _bound_seat_session(window, seeded, **overrides):
    """A session on a profile bound for a governing seat, with a
    valid sample dataset — ready to train except for the
    warning."""
    kwargs = {
        "ollama_tag": "lfm3:1.7b",
        "base_ref": "LiquidAI/LFM3-1.7B",
        "governing_seat": "driver",
    }
    kwargs.update(overrides)
    seeded.create_profile("seat-tool", **kwargs)
    seeded.create_project(
        "seat-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    window.refresh_tree()
    window.set_session("seat-tool", "tool-calls")


def test_start_training_governing_seat_no_stops_start(
    window, seeded, monkeypatch, qapp
):
    """T116 Done: a bound seat on a stock base warns before
    training, naming the seat and the base — and No stops the
    start."""
    from PySide6.QtWidgets import QMessageBox

    _bound_seat_session(window, seeded)
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No,
    )
    _start_training_ready(window, monkeypatch)
    window.start_training()
    qapp.processEvents()
    assert len(asked) == 1
    assert "driver" in asked[0]
    assert "LiquidAI/LFM3-1.7B" in asked[0]
    assert window._train_worker is None


def test_start_training_governing_seat_yes_proceeds(
    window, seeded, monkeypatch, qapp
):
    """T116: answering Yes to the governing-seat warning starts
    the run."""
    from PySide6.QtWidgets import QMessageBox

    _bound_seat_session(window, seeded)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    _start_training_ready(window, monkeypatch)
    window.start_training()
    qapp.processEvents()
    assert window._train_worker is not None


def test_start_training_governing_seat_abliterated_no_warning(
    window, seeded, monkeypatch, qapp
):
    """T116 Done: the same bound seat on an abliterated base
    warns about nothing."""
    from PySide6.QtWidgets import QMessageBox

    _bound_seat_session(
        window, seeded, ollama_tag="minicpm5-heretic:2b"
    )
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No,
    )
    _start_training_ready(window, monkeypatch)
    window.start_training()
    qapp.processEvents()
    assert asked == []
    assert window._train_worker is not None


def test_start_training_governing_role_only_warns(
    window, seeded, monkeypatch, qapp
):
    """R67: a governing ROLE with no marker warns before training
    too — a role-only profile used to train for hours unwarned."""
    from PySide6.QtWidgets import QMessageBox

    seeded.create_profile(
        "role-tool", ollama_tag="lfm3:1.7b", role="driver",
        base_ref="LiquidAI/LFM3-1.7B",
    )
    seeded.create_project(
        "role-tool", "tool-calls", dataset_ref="sample-tool-calls.jsonl"
    )
    window.refresh_tree()
    window.set_session("role-tool", "tool-calls")
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No,
    )
    _start_training_ready(window, monkeypatch)
    window.start_training()
    qapp.processEvents()
    assert len(asked) == 1
    assert "driver" in asked[0]
    assert "LiquidAI/LFM3-1.7B" in asked[0]
    assert window._train_worker is None


def test_delete_profile_dialog_names_item_and_counts(
    window, seeded, monkeypatch
):
    """T120 Done: deleting a profile names it (display name +
    slug), counts what goes with it, and states the trash
    destination."""
    from PySide6.QtWidgets import QMessageBox

    seeded.create_project("lfm3-tool", "second-proj")
    ckpt = (
        seeded.home / "profiles" / "lfm3-tool" / "projects"
        / "tool-calls" / "checkpoints" / "step-50"
    )
    ckpt.mkdir(parents=True)
    seen = []

    def fake_exec(self):
        seen.append(self)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    window.delete_profile("lfm3-tool")
    assert len(seen) == 1
    text = seen[0].text()
    assert "LFM3 Tool Seat" in text
    assert "lfm3-tool" in text
    assert "2 projects" in text
    assert "1 checkpoint" in text
    assert "notes for 2 projects" in text
    assert "trash" in text


def test_delete_project_dialog_names_checkpoints(
    window, seeded, monkeypatch
):
    """T120 Done: deleting a project names it and its
    checkpoints, and states the trash destination."""
    from PySide6.QtWidgets import QMessageBox

    ckpt = (
        seeded.home / "profiles" / "lfm3-tool" / "projects"
        / "tool-calls" / "checkpoints" / "step-50"
    )
    ckpt.mkdir(parents=True)
    seen = []

    def fake_exec(self):
        seen.append(self)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    window.delete_project("lfm3-tool", "tool-calls")
    assert len(seen) == 1
    text = seen[0].text()
    assert "tool-calls" in text
    assert "1 checkpoint" in text
    assert "its notes" in text
    assert "trash" in text


def test_trash_purge_dialog_names_what_it_destroys(
    window, seeded, monkeypatch, qapp
):
    """T120: the purge dialog names the item and what goes with
    it, and states that it is permanent."""
    from PySide6.QtWidgets import QMessageBox

    ckpt = (
        seeded.home / "profiles" / "lfm3-tool" / "projects"
        / "tool-calls" / "checkpoints" / "step-50"
    )
    ckpt.mkdir(parents=True)
    seeded.delete_project("lfm3-tool", "tool-calls")
    trash = window.open_trash_window()
    qapp.processEvents()
    assert trash.list_widget.count() == 1
    trash.list_widget.setCurrentRow(0)
    seen = []

    def fake_exec(self):
        seen.append(self)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    trash._purge_selected()
    assert len(seen) == 1
    text = seen[0].text()
    assert "tool-calls" in text
    assert "1 checkpoint" in text
    assert "forever" in text
    trash.close()


def test_trash_empty_dialog_counts_items(
    window, seeded, monkeypatch, qapp
):
    """T120: Empty trash names how many items go forever."""
    from PySide6.QtWidgets import QMessageBox

    seeded.delete_project("lfm3-tool", "tool-calls")
    trash = window.open_trash_window()
    qapp.processEvents()
    seen = []

    def fake_exec(self):
        seen.append(self)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    trash._empty_trash()
    assert len(seen) == 1
    assert "1 item" in seen[0].text()
    assert "forever" in seen[0].text()
    trash.close()


def test_clone_profile_button(window, seeded, monkeypatch, qapp):
    """T121 Done: the Clone button in the profile window copies
    the tag, base, and role under a new name, with zero projects;
    the session moves to the clone."""
    from PySide6.QtWidgets import QInputDialog, QMessageBox, QPushButton

    _select_session(window)
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("lfm3-copy", True)
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )
    clone_btn = next(
        b for b in win.findChildren(QPushButton) if b.text() == "Clone"
    )
    clone_btn.click()
    qapp.processEvents()
    clone = seeded.get_profile("lfm3-copy")
    assert clone["ollama_tag"] == "lfm3:1.7b"
    assert clone["role"] == "fast"
    assert seeded.list_projects("lfm3-copy") == []
    assert window._current_profile == "lfm3-copy"
    assert "Cloned lfm3-tool as lfm3-copy." in (
        window.statusBar().currentMessage()
    )
    win.close()


def test_clone_profile_button_copies_projects_when_asked(
    window, seeded, monkeypatch, qapp
):
    """T121: answering Yes to the copy-projects question copies
    the projects into the clone."""
    from PySide6.QtWidgets import QInputDialog, QMessageBox, QPushButton

    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("lfm3-copy", True)
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    clone_btn = next(
        b for b in win.findChildren(QPushButton) if b.text() == "Clone"
    )
    clone_btn.click()
    qapp.processEvents()
    assert [p["name"] for p in seeded.list_projects("lfm3-copy")] == [
        "tool-calls"
    ]
    win.close()


def test_profile_row_tooltip_shows_name_role_tag(window):
    """T122 Done: hovering a profile row shows the full display
    name, role, and tag."""
    top = window.tree.topLevelItem(0)
    tip = top.toolTip(0)
    assert "LFM3 Tool Seat" in tip
    assert "fast" in tip
    assert "lfm3:1.7b" in tip


def test_empty_store_shows_profile_hint(qapp, store, settings):
    """T124 Done: an empty store's tree pane says what to do
    next instead of showing a blank list."""
    from stella.gui import MainWindow

    win = MainWindow(store=store, settings=settings)
    win.show()
    qapp.processEvents()
    assert win.tree_hint.isVisible()
    assert win.tree_hint.text() == (
        "No profiles yet - New profile to start. New here? "
        "<a href=\"getting-started\">Getting started</a>."
    )
    win.close()


def test_profile_without_projects_shows_hint(window, seeded, qapp):
    """T124 Done: a profile with no projects shows the one-line
    hint; a profile with projects does not."""
    seeded.create_profile("empty-profile")
    window.refresh_tree()
    window.set_session("empty-profile", None)
    qapp.processEvents()
    assert window.tree_hint.isVisible()
    assert window.tree_hint.text() == (
        "No projects yet - New project to start. New here? "
        "<a href=\"getting-started\">Getting started</a>."
    )
    window.set_session("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert not window.tree_hint.isVisible()


def test_hint_hidden_with_projects(window):
    """T124: with a session on a profile that has projects, no
    hint shows."""
    _select_session(window)
    assert not window.tree_hint.isVisible()


def test_splitter_cannot_collapse_panes(window, qapp):
    """T126 Done: the panes cannot be dragged to width 0 — the
    splitter refuses to collapse a pane, and each pane keeps an
    honest minimum width."""
    assert window.splitter.childrenCollapsible() is False
    window.splitter.setSizes([0, 1100])
    qapp.processEvents()
    assert window.splitter.sizes()[0] >= 200
    window.splitter.setSizes([1100, 0])
    qapp.processEvents()
    assert window.splitter.sizes()[1] >= 480


def test_splitter_stays_uncollapsible_after_restoring_old_state(
    qapp, seeded, settings
):
    """T126 Done (coordinator fix): restoreState brings back the
    saved collapsible flag too, so a splitter state saved before
    v0.19.0 — when panes were collapsible — would re-enable
    collapsing on a returning user's window. The window re-asserts
    non-collapsible after the restore. First prove the saved state
    really carries the flag, so the assertion is not vacuous."""
    from PySide6.QtWidgets import QLabel, QSplitter
    from stella.gui import MainWindow

    probe = QSplitter()
    probe.addWidget(QLabel("left"))
    probe.addWidget(QLabel("right"))
    probe.setChildrenCollapsible(True)
    old_state = probe.saveState()
    check = QSplitter()
    check.addWidget(QLabel("left"))
    check.addWidget(QLabel("right"))
    check.setChildrenCollapsible(False)
    check.restoreState(old_state)
    assert check.childrenCollapsible() is True

    settings.setValue("splitter", old_state)
    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    try:
        assert win.splitter.childrenCollapsible() is False
    finally:
        win.close()


def test_window_icon_is_set(window):
    """T127 Done: the window shows the star icon."""
    assert not window.windowIcon().isNull()


def test_stella_icon_missing_file_is_null(qapp, tmp_path):
    """T127: the icon guard — a missing asset file gives a null
    icon instead of a crash."""
    from stella.gui import _stella_icon

    assert _stella_icon(tmp_path / "missing.png").isNull()
    assert not _stella_icon().isNull()


def test_profile_window_help_labels_not_clipped(window, qapp):
    """T115: the config section made the profile window taller
    than a small screen, and Qt then fell back to the minimum
    size hint — squeezing every help label to two lines. The
    form scrolls now (T80's pattern, as in the project window),
    so every label gets its full height and the window stays
    inside a 768px screen."""
    prof_win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    try:
        assert prof_win.height() <= 700
        for label in prof_win.findChildren(QLabel):
            if not label.isVisible() or not label.wordWrap():
                continue
            text = label.text()
            if len(text) < 20:
                continue
            assert label.height() >= label.heightForWidth(label.width()), (
                f"clipped: {text[:50]!r} h={label.height()} "
                f"need={label.heightForWidth(label.width())}"
            )
    finally:
        prof_win.close()


def test_project_window_help_labels_not_clipped(window, qapp):
    """T114: the project window's help labels — including the
    new Why-this-mode one — all get their full height."""
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    try:
        for label in proj_win.findChildren(QLabel):
            if not label.isVisible() or not label.wordWrap():
                continue
            text = label.text()
            if len(text) < 20:
                continue
            assert label.height() >= label.heightForWidth(label.width()), (
                f"clipped: {text[:50]!r} h={label.height()} "
                f"need={label.heightForWidth(label.width())}"
            )
    finally:
        proj_win.close()


# -- v0.20.0: T150-T153 (checkpoints, run history, loading, export) --


def _seed_checkpoint(seeded, step, loss=1.5, size=1000):
    """A checkpoint dir with a state file + a file of `size` bytes."""
    ckpt = (
        seeded.project_dir("lfm3-tool", "tool-calls")
        / "checkpoints" / f"step-{step}"
    )
    ckpt.mkdir(parents=True)
    (ckpt / "training_state.json").write_text(
        json.dumps({"step": step, "epoch": 1, "loss": loss})
    )
    (ckpt / "adapter_model.safetensors").write_bytes(b"x" * size)
    return ckpt


def _seed_runs_log(seeded):
    """A train log with two finished runs (T151)."""
    lines = [
        {"event": "run_started", "run_id": "2026-11-13T10:00:00",
         "started_at": "2026-11-13T10:00:00", "total_steps": 3,
         "settings": {"rank": 8}},
        {"step": 1, "total_steps": 3, "epoch": 1, "loss": 2.5, "lr": 0.0002},
        {"step": 2, "total_steps": 3, "epoch": 1, "loss": 2.1, "lr": 0.0002},
        {"step": 3, "total_steps": 3, "epoch": 1, "loss": 1.9, "lr": 0.0002},
        {"event": "run_finished", "run_id": "2026-11-13T10:00:00",
         "steps": 3, "final_loss": 1.9, "stopped": False},
        {"event": "run_started", "run_id": "2026-11-14T09:00:00",
         "started_at": "2026-11-14T09:00:00", "total_steps": 2,
         "settings": {"rank": 8}},
        {"step": 1, "total_steps": 2, "epoch": 1, "loss": 1.8, "lr": 0.0002},
        {"step": 2, "total_steps": 2, "epoch": 1, "loss": 1.6, "lr": 0.0002},
        {"event": "run_finished", "run_id": "2026-11-14T09:00:00",
         "steps": 2, "final_loss": 1.6, "stopped": False},
    ]
    (
        seeded.project_dir("lfm3-tool", "tool-calls") / "train_log.jsonl"
    ).write_text("\n".join(json.dumps(r) for r in lines) + "\n")


def test_checkpoint_list_shows_size_and_date(window, seeded, qapp):
    # T150: each row shows step, loss, size, and date; the disk
    # label totals them.
    _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _seed_checkpoint(seeded, 10, loss=1.2, size=2000)
    _select_session(window)
    qapp.processEvents()
    assert window.train_checkpoints.count() == 2
    row = window.train_checkpoints.item(0).text()
    assert "step 5" in row
    assert "loss 1.5000" in row
    assert "1 KB" in row
    import re

    assert re.search(r"\d{4}-\d{2}-\d{2}", row)
    assert "3 KB" in window.checkpoint_disk_label.text()
    assert "2 checkpoints" in window.checkpoint_disk_label.text()
    # Nothing is selected by default.
    assert window.train_checkpoints.currentItem() is None


def test_checkpoint_detail_shows_on_click(window, seeded, qapp):
    # T150: clicking a checkpoint fills the detail view.
    _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    qapp.processEvents()
    item = window.train_checkpoints.item(0)
    window.train_checkpoints.setCurrentItem(item)
    window._on_checkpoint_selected(item)
    detail = window.checkpoint_detail_label.text()
    assert "Step 5" in detail
    assert "loss 1.5000" in detail
    assert "1 KB" in detail
    assert "saved 20" in detail


def test_checkpoint_delete_asks_and_deletes(window, seeded, monkeypatch, qapp):
    # T150: Delete confirms with the size shown, defaulting to No;
    # Yes deletes for good and reports the freed space.
    from PySide6.QtWidgets import QMessageBox

    ckpt = _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    qapp.processEvents()
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes,
    )
    window.train_checkpoints.setCurrentRow(0)
    window.checkpoint_delete_btn.click()
    qapp.processEvents()
    assert asked and "step 5" in asked[0] and "1 KB" in asked[0]
    assert "cannot be undone" in asked[0]
    assert not ckpt.exists()
    assert window.train_checkpoints.count() == 0
    assert "freed" in window.statusBar().currentMessage()


def test_checkpoint_delete_no_keeps_it(window, seeded, monkeypatch, qapp):
    # T150: No on the delete confirm keeps the checkpoint.
    from PySide6.QtWidgets import QMessageBox

    ckpt = _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    qapp.processEvents()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )
    window.train_checkpoints.setCurrentRow(0)
    window.checkpoint_delete_btn.click()
    qapp.processEvents()
    assert ckpt.exists()
    assert window.train_checkpoints.count() == 1


def test_checkpoint_prune_keeps_newest_n(window, seeded, monkeypatch, qapp):
    # T150: Prune keeps the newest N (default 3) and reports the
    # size before and after plus the space freed.
    from PySide6.QtWidgets import QMessageBox

    for step in (1, 2, 3, 4, 5):
        _seed_checkpoint(seeded, step, loss=1.5, size=1000)
    _select_session(window)
    qapp.processEvents()
    assert window.checkpoint_keep_spin.value() == 3
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes,
    )
    window.checkpoint_prune_btn.click()
    qapp.processEvents()
    assert asked and "keep the newest 3" in asked[0]
    assert "freeing" in asked[0]
    base = seeded.project_dir("lfm3-tool", "tool-calls") / "checkpoints"
    assert not (base / "step-1").exists()
    assert not (base / "step-2").exists()
    assert (base / "step-5").exists()
    assert window.train_checkpoints.count() == 3
    assert "freed" in window.statusBar().currentMessage()


def test_checkpoint_prune_nothing_to_prune(window, seeded, monkeypatch, qapp):
    # T150: pruning with fewer checkpoints than N asks nothing.
    from PySide6.QtWidgets import QMessageBox

    _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    qapp.processEvents()
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("prune asked with nothing to prune")
        ),
    )
    window.checkpoint_prune_btn.click()
    qapp.processEvents()
    assert window.train_checkpoints.count() == 1
    assert "Nothing to prune" in window.statusBar().currentMessage()


def test_resume_from_selected_passes_step(window, seeded, monkeypatch, qapp):
    # T150: Resume from selected starts training from that
    # checkpoint, not the latest one.
    _seed_checkpoint(seeded, 5, loss=1.5, size=1000)
    _select_session(window)
    qapp.processEvents()
    calls = []
    monkeypatch.setattr(
        window, "start_training",
        lambda *a, **k: calls.append(k),
    )
    window.train_checkpoints.setCurrentRow(0)
    window.checkpoint_resume_btn.click()
    assert calls == [{"resume": True, "from_checkpoint": 5}]


def test_run_history_lists_runs_and_shows_curve(window, seeded, qapp):
    # T151: the history lists past runs (date, steps, final loss)
    # and a click shows that run's curve in the chart.
    _seed_runs_log(seeded)
    _select_session(window)
    qapp.processEvents()
    assert window.run_history_list.count() == 2
    row = window.run_history_list.item(0).text()
    assert "2026-11-13" in row
    assert "3 steps" in row
    assert "final loss 1.9000" in row
    # No settings values anywhere in the history UI (T16).
    assert "rank" not in row.lower()
    assert "8" not in row.split("final loss")[0]
    item = window.run_history_list.item(0)
    window._on_run_selected(item)
    assert window.loss_curve.points == [(1, 2.5), (2, 2.1), (3, 1.9)]
    assert "2026-11-13" in window.train_loss.text()
    assert "final loss 1.9000" in window.train_loss.text()


def test_export_estimate_label_shows_after_adapter(
    window, seeded, tmp_path, qapp
):
    # T153: once a project has an adapter, the label beside the
    # Export button shows the merged size, output size, and
    # rough time.
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(json.dumps({
        "hidden_size": 2048, "num_hidden_layers": 24,
        "intermediate_size": 8192, "torch_dtype": "bfloat16",
    }))
    (model_dir / "model.safetensors.index.json").write_text(json.dumps({
        "metadata": {"total_size": 3_460_000_000},
    }))
    seeded.update_profile("lfm3-tool", base_ref=str(model_dir))
    adapter = (
        seeded.project_dir("lfm3-tool", "tool-calls") / "adapter"
    )
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}\n")
    _select_session(window)
    qapp.processEvents()
    text = window.export_estimate_label.text()
    assert "merges about 3.2 GB" in text
    assert "GGUF file (Q4_K_M)" in text
    assert "roughly" in text.lower()


def test_export_estimate_label_empty_without_adapter(window, seeded, qapp):
    # T153: with no adapter there is nothing to export, so no
    # estimate shows.
    _select_session(window)
    qapp.processEvents()
    assert window.export_estimate_label.text() == ""


def test_train_worker_loading_event_logs_model_name(qapp, seeded):
    # T152: the loading event reaches the log (and through it the
    # job card status) with the model name.
    from stella.gui import TrainWorker

    worker = TrainWorker(seeded, "lfm3-tool", "tool-calls")
    lines = []
    worker.log.connect(lines.append)
    worker._event({
        "type": "loading", "model": "LiquidAI/LFM3-1.7B",
        "message": "Loading LiquidAI/LFM3-1.7B... The first run "
        "downloads it, and Ctrl+C takes effect when the download "
        "finishes.",
    })
    qapp.processEvents()
    assert lines == [
        "Loading LiquidAI/LFM3-1.7B... The first run downloads it, "
        "and Ctrl+C takes effect when the download finishes."
    ]


def test_export_preview_shows_estimate(window, qapp):
    # T153: the export preview dialog shows the estimate at the
    # commit point, next to the Export button.
    from stella.gui import ProbeResultsDialog

    dialog = ProbeResultsDialog(
        window, _probe_result(), export_mode=True,
        estimate_text="Export merges about 3.2 GB, then writes "
        "about a 1000 MB GGUF file (Q4_K_M). Roughly tens of minutes.",
    )
    try:
        assert "3.2 GB" in dialog.estimate_label.text()
        assert dialog.export_btn is not None
    finally:
        dialog.close()


# -- v0.21.0: T160-T168, T177-T179 (profiles/rows/provenance) ------


@pytest.fixture()
def seed_show():
    """Seed the T165 /api/show cache for one tag, and stop real
    fetches for the test. The cache is reset afterwards, so a
    seed never leaks into the next test."""
    from stella.ollama import SHOW_CACHE

    def _seed(tag, info, ollama_up=True):
        SHOW_CACHE.set_snapshot(tag, info, ollama_up=ollama_up)

    yield _seed
    SHOW_CACHE.reset()


def _write_dataset_file(home, name="data.jsonl", rows=20):
    """A valid 20-row dataset file in the home dir."""
    path = home / name
    path.write_text(
        "".join(
            json.dumps({"prompt": f"Q{i}?", "completion": f"A{i}."}) + "\n"
            for i in range(rows)
        )
    )
    return path


def _make_checkpoint(store, profile, project, step, loss=1.0):
    """A fake checkpoint dir list_checkpoints can read."""
    d = (
        store.project_dir(profile, project)
        / "checkpoints" / f"step-{step}"
    )
    d.mkdir(parents=True, exist_ok=True)
    (d / "training_state.json").write_text(
        json.dumps({"step": step, "loss": loss, "epoch": 0})
    )
    (d / "adapter_config.json").write_text("{}")


def test_project_window_notes_visible_without_scrolling(window, qapp):
    """T160: the Notes editor is visible without scrolling in the
    default Project window — Notes moved above Details."""
    from PySide6.QtWidgets import QScrollArea

    win = window.open_project_window("lfm3-tool", "tool-calls")
    win.show()
    qapp.processEvents()
    scroll = win.findChild(QScrollArea)
    assert scroll is not None
    viewport = scroll.viewport()
    top = win.notes_edit.mapTo(viewport, win.notes_edit.rect().topLeft())
    assert top.y() >= 0
    assert top.y() + win.notes_edit.height() <= viewport.height()
    win.close()


def test_step_cap_defaults_to_full_run(window):
    """T161: the step cap starts at 0 — the full run."""
    assert window.train_step_cap_spin.value() == 0


def test_go_applies_step_cap(window, monkeypatch, seeded, qapp):
    """T161: Go with a step cap starts the run capped."""
    import stella.gui as gui_mod
    import stella.train as train_mod

    _write_dataset_file(seeded.home)
    seeded.update_project("lfm3-tool", "tool-calls", dataset_ref="data.jsonl")
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(window, "_weights_offer", lambda profile: True)
    monkeypatch.setattr(gui_mod.TrainWorker, "run", lambda self: None)
    # R67: the seeded profile is role fast, so the governing-seat
    # question fires — Yes proceeds.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    _select_session(window)
    window.train_step_cap_spin.setValue(7)
    window._go_train()
    qapp.processEvents()
    assert window._train_worker is not None
    assert window._train_worker._max_steps == 7


def test_run_dataset_override_reaches_worker(window, monkeypatch, seeded, qapp):
    """T161: a run-override dataset is what the run is checked and
    started on — the project's own dataset is untouched, even when
    it does not resolve."""
    import stella.gui as gui_mod
    import stella.train as train_mod

    _write_dataset_file(seeded.home, "override.jsonl")
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(window, "_weights_offer", lambda profile: True)
    monkeypatch.setattr(gui_mod.TrainWorker, "run", lambda self: None)
    # R67: the seeded profile is role fast, so the governing-seat
    # question fires — Yes proceeds.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    _select_session(window)
    window.run_dataset_edit.setText("override.jsonl")
    window.start_training()
    qapp.processEvents()
    assert window._train_worker is not None
    assert window._train_worker._dataset_path == "override.jsonl"
    assert seeded.get_project("lfm3-tool", "tool-calls")[
        "dataset_ref"
    ] == "forge-traces.jsonl"


def test_run_base_override_skips_weights_offer(
    window, monkeypatch, seeded, qapp
):
    """T161: a run-override base reaches the worker, and the
    weights offer is skipped — the run starts from the override,
    not the profile's weights."""
    import stella.gui as gui_mod
    import stella.train as train_mod

    _write_dataset_file(seeded.home)
    seeded.update_project("lfm3-tool", "tool-calls", dataset_ref="data.jsonl")
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    offered = []
    monkeypatch.setattr(
        window, "_weights_offer",
        lambda profile: offered.append(profile) or True,
    )
    monkeypatch.setattr(gui_mod.TrainWorker, "run", lambda self: None)
    # R67: the seeded profile is role fast, so the governing-seat
    # question fires — Yes proceeds.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    _select_session(window)
    window.run_base_edit.setText("somewhere/else-base")
    window.start_training()
    qapp.processEvents()
    assert window._train_worker is not None
    assert window._train_worker._base_ref == "somewhere/else-base"
    assert offered == []


def test_run_overrides_clear_on_project_switch(window, seeded):
    """T161: the run overrides belong to the project they were
    typed for — a switch clears them."""
    _select_session(window)
    window.run_dataset_edit.setText("x.jsonl")
    window.run_base_edit.setText("y")
    seeded.create_project("lfm3-tool", "second", dataset_ref="data.jsonl")
    window.set_session("lfm3-tool", "second")
    assert window.run_dataset_edit.text() == ""
    assert window.run_base_edit.text() == ""


def test_gguf_quant_combo_defaults_to_q4_k_m(window):
    """T161: the GGUF quant picker offers every known quant and
    starts on the CLI default."""
    from stella.requant import DEFAULT_QUANT, KNOWN_QUANTS

    assert window.gguf_quant_combo.currentText() == DEFAULT_QUANT
    items = [
        window.gguf_quant_combo.itemText(i)
        for i in range(window.gguf_quant_combo.count())
    ]
    assert items == list(KNOWN_QUANTS)


def test_gguf_checkpoint_picker_lists_checkpoints(window, seeded):
    """T161: the GGUF checkpoint picker rides the T150 list — the
    trained adapter first, then one entry per checkpoint."""
    _make_checkpoint(seeded, "lfm3-tool", "tool-calls", 2)
    _make_checkpoint(seeded, "lfm3-tool", "tool-calls", 5)
    _select_session(window)
    window.refresh_train_panel()
    combo = window.gguf_checkpoint_combo
    assert combo.count() == 3
    assert combo.itemText(0) == "Trained adapter"
    assert combo.itemData(0) is None
    assert combo.itemText(1) == "Checkpoint step 2"
    assert combo.itemData(1) == 2
    assert combo.itemData(2) == 5


def _make_sleep_cycle(store, profile, project, cycle):
    """A finished sleep cycle: an adapter on disk the export
    picker can offer."""
    adapter = (
        store.project_dir(profile, project)
        / "sleep" / f"cycle-{cycle}" / "adapter"
    )
    adapter.mkdir(parents=True, exist_ok=True)
    (adapter / "adapter_config.json").write_text("{}")


def test_gguf_picker_lists_sleep_cycles(window, seeded):
    """R3: a finished sleep cycle appears in the GGUF picker after
    the checkpoints, as a sleep adapter source — and a cycle with
    no adapter on disk does not."""
    _make_checkpoint(seeded, "lfm3-tool", "tool-calls", 2)
    _make_sleep_cycle(seeded, "lfm3-tool", "tool-calls", 1)
    _make_sleep_cycle(seeded, "lfm3-tool", "tool-calls", 3)
    unfinished = (
        seeded.project_dir("lfm3-tool", "tool-calls")
        / "sleep" / "cycle-4" / "adapter"
    )
    unfinished.mkdir(parents=True)
    _select_session(window)
    window.refresh_train_panel()
    combo = window.gguf_checkpoint_combo
    assert combo.count() == 4
    assert combo.itemText(0) == "Trained adapter"
    assert combo.itemText(1) == "Checkpoint step 2"
    assert combo.itemText(2) == "Sleep cycle 1"
    assert combo.itemData(2) == ("sleep", 1)
    assert combo.itemText(3) == "Sleep cycle 3"
    assert combo.itemData(3) == ("sleep", 3)


def test_gguf_export_uses_picked_sleep_cycle(
    window, seeded, monkeypatch, tmp_path, qapp
):
    """R3: Export GGUF with a sleep cycle picked passes
    --from-sleep to the engine (and no checkpoint)."""
    import stella.gguf as gguf_mod
    from PySide6.QtWidgets import QFileDialog

    # R4: a governing profile with no probe is refused before the
    # job starts (a modal warning) — this test is about the picked
    # sleep cycle, so the profile is non-governing here.
    seeded.update_profile("lfm3-tool", role="utility")
    _make_sleep_cycle(seeded, "lfm3-tool", "tool-calls", 1)
    _select_session(window)
    window.refresh_train_panel()
    window.gguf_checkpoint_combo.setCurrentIndex(1)
    captured = {}

    def fake_export(store, profile, project, dest, **kw):
        captured.update(kw)
        return {
            "gguf": "x.gguf", "gguf_bytes": 123,
            "ollama_create": "ollama create x",
        }

    monkeypatch.setattr(gguf_mod, "export_gguf", fake_export)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: str(tmp_path),
    )
    window.export_gguf_gui()
    _wait_for_job(window, qapp)
    assert captured["from_sleep"] == 1
    assert captured["from_checkpoint"] is None


def test_gguf_export_uses_picked_quant_and_checkpoint(
    window, seeded, monkeypatch, tmp_path, qapp
):
    """T161: Export GGUF passes the picked quant and checkpoint to
    the engine — the CLI's --quant / --from-checkpoint."""
    import stella.gguf as gguf_mod
    from PySide6.QtWidgets import QFileDialog

    # R4: a governing profile with no probe is refused before the
    # job starts — this test is about the picked quant, so the
    # profile is non-governing here.
    seeded.update_profile("lfm3-tool", role="utility")
    _make_checkpoint(seeded, "lfm3-tool", "tool-calls", 2)
    _select_session(window)
    window.refresh_train_panel()
    window.gguf_quant_combo.setCurrentText("Q8_0")
    window.gguf_checkpoint_combo.setCurrentIndex(1)
    captured = {}

    def fake_export(store, profile, project, dest, **kw):
        captured.update(kw)
        return {
            "gguf": "x.gguf", "gguf_bytes": 123,
            "ollama_create": "ollama create x",
        }

    monkeypatch.setattr(gguf_mod, "export_gguf", fake_export)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: str(tmp_path),
    )
    window.export_gguf_gui()
    _wait_for_job(window, qapp)
    assert captured["quant"] == "Q8_0"
    assert captured["from_checkpoint"] == 2


def test_tag_health_state_values():
    """T163: the tag-health states, unit level — including the
    not-loaded-yet state the window shows as no marker."""
    from stella.gui import _tag_health_state

    assert _tag_health_state("", [], True, True) == "no-tag"
    assert _tag_health_state("x:1b", [], True, False) == "unknown"
    assert _tag_health_state("x:1b", [], False, True) == "down"
    assert _tag_health_state("x:1b", ["x:1b"], True, True) == "installed"
    assert _tag_health_state("x:1b", ["y:1b"], True, True) == "missing"


def test_profile_row_tag_health_markers(window, seed_models, seeded):
    """T163: installed tags show a tick, removed tags a cross,
    Ollama down a question mark, a tag-less profile 'no tag' —
    from the cached model list, updating on refresh."""
    def row_text():
        return window.tree.topLevelItem(0).text(0)

    seed_models(["lfm3:1.7b"], ollama_up=True)
    window.refresh_tree()
    assert "\u2713" in row_text()
    seed_models(["other:1b"], ollama_up=True)
    window.refresh_tree()
    assert "\u2717" in row_text()
    seed_models([], ollama_up=False)
    window.refresh_tree()
    assert "?" in row_text()
    seeded.create_profile("notag")
    window.refresh_tree()
    texts = [
        window.tree.topLevelItem(i).text(0)
        for i in range(window.tree.topLevelItemCount())
    ]
    assert any("(no tag)" in text for text in texts)


def test_project_row_shows_dataset_and_slug_on_collision(window, seeded):
    """T164: rows show the dataset file; two projects sharing a
    display name show their slugs (collision only); method and
    rank never appear — they are settings (T16)."""
    child = window.tree.topLevelItem(0).child(0)
    assert "[forge-traces.jsonl]" in child.text(0)
    assert "rank" not in child.text(0)
    assert "morph" not in child.text(0)
    assert "[tool-calls]" not in child.text(0)
    seeded.create_project(
        "lfm3-tool", "tool-calls-2", display_name="tool-calls"
    )
    window.refresh_tree()
    rows = [
        window.tree.topLevelItem(0).child(i).text(0)
        for i in range(window.tree.topLevelItem(0).childCount())
    ]
    assert any("[tool-calls]" in row for row in rows)
    assert any("[tool-calls-2]" in row for row in rows)


def test_profile_row_shows_project_count(window):
    """T165: the list row shows the project count."""
    assert "(1 project)" in window.tree.topLevelItem(0).text(0)


def test_profile_window_shows_facts(window, seeded, qapp):
    """T165: the profile panel shows the project count and the
    created/updated/last-used dates; never used says never, and a
    profile never edited has no updated date to show."""
    seeded.update_profile("lfm3-tool", role="fast")
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    text = win.profile_facts_label.text()
    assert "1 project" in text
    assert "Created 20" in text
    assert "updated 20" in text
    assert "last used never" in text
    win.close()
    seeded.create_profile("fresh")
    win2 = window.open_profile_window("fresh")
    qapp.processEvents()
    text2 = win2.profile_facts_label.text()
    assert "0 projects" in text2
    assert "updated unknown" in text2
    win2.close()


def test_profile_window_shows_last_used_after_touch(window, seeded, qapp):
    """T165: after a run stamps last-used, the panel shows the date."""
    seeded.touch_last_used("lfm3-tool")
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert "last used 20" in win.profile_facts_label.text()
    assert "never" not in win.profile_facts_label.text()
    win.close()


def test_profile_window_shows_model_info_from_cache(
    window, seed_show, qapp
):
    """T165: size, quant, context, and capabilities from a cached
    /api/show, in the profile panel."""
    seed_show("lfm3:1.7b", {
        "size_bytes": 2000000000, "quant": "Q4_K_M",
        "context": 131072, "capabilities": ["completion", "tools"],
        "parameter_size": "1.7B", "family": "llama",
    })
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    text = win.model_info_label.text()
    assert "1.9 GB" in text
    assert "Q4_K_M" in text
    assert "131,072 tokens" in text
    assert "completion, tools" in text
    assert "1.7B parameters" in text
    win.close()


def test_profile_window_model_info_unavailable_when_ollama_down(
    window, seed_show, qapp
):
    """T165: with Ollama down, the metadata shows as unavailable,
    not blank or wrong."""
    seed_show("lfm3:1.7b", None, ollama_up=False)
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    text = win.model_info_label.text()
    assert "unavailable" in text
    assert "Ollama is not answering" in text
    win.close()


def test_profile_window_model_info_missing_tag(window, seed_show, qapp):
    """T165: a tag Ollama does not have says so outright."""
    seed_show("lfm3:1.7b", None, ollama_up=True)
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    assert "does not have" in win.model_info_label.text()
    win.close()


def test_profile_notes_round_trip_in_window(window, seeded, qapp):
    """T166: profile notes save through the Save profile flow and
    persist across a reopen."""
    win = window.open_profile_window("lfm3-tool")
    win.notes_edit.setPlainText("Why this profile exists.")
    assert win.save() is True
    win.close()
    assert seeded.read_profile_notes("lfm3-tool") == (
        "Why this profile exists."
    )
    win2 = window.open_profile_window("lfm3-tool")
    assert win2.notes_edit.toPlainText() == "Why this profile exists."
    win2.close()


def test_profile_notes_edit_marks_window_modified(window, qapp):
    """T166: editing the profile notes marks the window modified,
    like any other field."""
    win = window.open_profile_window("lfm3-tool")
    assert not win.is_modified()
    win.notes_edit.setPlainText("x")
    assert win.is_modified()
    win.notes_edit.setPlainText("")
    assert not win.is_modified()
    win.close()


def test_export_dialog_title_names_package(
    window, monkeypatch, tmp_path, qapp
):
    """T167: the export dialog names the package before the folder
    is picked."""
    from PySide6.QtWidgets import QFileDialog

    _select_session(window)
    titles = []

    def fake_dir(parent, title, start):
        titles.append(title)
        return str(tmp_path)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake_dir)
    window.export_project()
    _wait_for_job(window, qapp)
    assert titles and "tool-calls-stella-export" in titles[0]
    assert (tmp_path / "tool-calls-stella-export").is_dir()


def test_export_profile_dialog_title_names_package(
    window, monkeypatch, tmp_path, qapp
):
    """T167: the profile export dialog names its package too."""
    from PySide6.QtWidgets import QFileDialog

    _select_session(window)
    titles = []

    def fake_dir(parent, title, start):
        titles.append(title)
        return str(tmp_path)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", fake_dir)
    monkeypatch.setattr(
        window, "_ask_include_projects", lambda slug: True
    )
    window.export_profile()
    _wait_for_job(window, qapp)
    assert titles and "lfm3-tool-stella-profile-export" in titles[0]
    assert (tmp_path / "lfm3-tool-stella-profile-export").is_dir()


def test_f2_renames_profile_row(window, monkeypatch, seeded, qapp):
    """T168: F2 renames the picked tree row."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog

    window.tree.setCurrentItem(window.tree.topLevelItem(0))
    qapp.processEvents()
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("renamed-prof", True)
    )
    QTest.keyClick(window, Qt.Key_F2)
    qapp.processEvents()
    assert seeded.get_profile("renamed-prof")["name"] == "renamed-prof"


def test_tree_context_menu_offers_rename(window, monkeypatch, seeded):
    """T168: the right-click menu on a row offers Rename; a
    damaged row and empty space get no menu."""
    from PySide6.QtWidgets import QInputDialog

    assert window._tree_context_menu(None) is None
    item = window.tree.topLevelItem(0).child(0)
    menu = window._tree_context_menu(item)
    assert menu is not None
    actions = menu.actions()
    assert [a.text() for a in actions] == ["Rename"]
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("renamed-proj", True)
    )
    actions[0].trigger()
    assert seeded.get_project("lfm3-tool", "renamed-proj")["name"] == (
        "renamed-proj"
    )


def test_double_click_row_still_opens_detail_window(window, qapp):
    """T168 ruling: double-click keeps opening the detail window —
    rename moved to F2 and the right-click menu instead."""
    top = window.tree.topLevelItem(0)
    window._on_tree_double_clicked(top, 0)
    qapp.processEvents()
    assert "lfm3-tool" in window._profile_windows
    assert window._profile_windows["lfm3-tool"].isVisible()
    child = top.child(0)
    window._on_tree_double_clicked(child, 0)
    qapp.processEvents()
    assert ("lfm3-tool", "tool-calls") in window._project_windows
    assert window._project_windows[
        ("lfm3-tool", "tool-calls")
    ].isVisible()


def test_checkpoint_double_click_shows_detail(window, seeded):
    """T168: double-clicking a checkpoint shows its detail, like a
    single click does."""
    _make_checkpoint(seeded, "lfm3-tool", "tool-calls", 2, loss=1.2345)
    _select_session(window)
    window.refresh_train_panel()
    item = window.train_checkpoints.item(0)
    assert item is not None
    window.train_checkpoints.itemDoubleClicked.emit(item)
    assert "Step 2" in window.checkpoint_detail_label.text()
    assert "1.2345" in window.checkpoint_detail_label.text()


def test_export_success_message_reports_size(
    window, monkeypatch, tmp_path, qapp
):
    """T178: the export log line carries the estimated size before
    the copy, and the success line the real package size after."""
    from PySide6.QtWidgets import QFileDialog

    _select_session(window)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        lambda *a, **k: str(tmp_path),
    )
    window.export_project()
    _wait_for_job(window, qapp)
    log = window.train_log.toPlainText()
    assert "Exporting project lfm3-tool/tool-calls (about " in log
    assert any(
        "Exported to " in line and "(" in line
        for line in log.splitlines()
    )


def test_import_preview_dialog_shows_provenance(window, seeded, tmp_path):
    """T179: the import preview shows when and where the package
    was made."""
    from stella import export as export_mod
    from stella.gui import ImportPreviewDialog

    out = export_mod.export_project(
        seeded, "lfm3-tool", "tool-calls", tmp_path
    )
    summary = export_mod.preview_export(seeded, out)
    dialog = ImportPreviewDialog(window, summary)
    texts = [child.text() for child in dialog.findChildren(QLabel)]
    assert any("Exported from" in text for text in texts)
    dialog.close()


# -- v0.26.0: R27 — the window names a crashed run on startup --------


def test_main_window_reconciles_crashed_run_on_startup(
    qapp, seeded, settings
):
    """R27: opening the window with a project stuck on 'training'
    (a crash) reconciles it to 'paused' and says so in the status
    bar, with the resume offer."""
    from stella.gui import MainWindow

    seeded.update_project("lfm3-tool", "tool-calls", status="training")
    ckpt = (
        seeded.project_dir("lfm3-tool", "tool-calls")
        / "checkpoints" / "step-5"
    )
    ckpt.mkdir(parents=True)
    (ckpt / "training_state.json").write_text(json.dumps({
        "step": 5, "epoch": 1, "loss": 1.5,
        "examples_seen_in_epoch": 3,
    }))
    win = MainWindow(store=seeded, settings=settings)
    try:
        win.show()
        qapp.processEvents()
        if win._model_list_worker is not None:
            win._model_list_worker.wait(5000)
            qapp.processEvents()
        assert seeded.get_project(
            "lfm3-tool", "tool-calls"
        )["status"] == "paused"
        message = win.statusBar().currentMessage()
        assert "stopped unexpectedly" in message
        assert "lfm3-tool/tool-calls" in message
        assert "resumed from the Train panel" in message
    finally:
        win.close()


# -- v0.26.0: R40 — the clone button warns about skipped projects ----


def test_clone_profile_button_warns_about_skipped_projects(
    window, seeded, monkeypatch, qapp
):
    """R40: cloning a profile with a damaged project warns naming
    the skipped project — the clone never reports plain success
    while missing a project."""
    from PySide6.QtWidgets import QInputDialog, QMessageBox, QPushButton

    seeded.create_project("lfm3-tool", "broken")
    (seeded.project_dir("lfm3-tool", "broken") / "project.json").write_text(
        "{this is not json"
    )
    win = window.open_profile_window("lfm3-tool")
    qapp.processEvents()
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("lfm3-copy", True)
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    seen = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: seen.append(a[2] if len(a) > 2 else k.get("text", "")),
    )
    clone_btn = next(
        b for b in win.findChildren(QPushButton) if b.text() == "Clone"
    )
    clone_btn.click()
    qapp.processEvents()
    assert [p["name"] for p in seeded.list_projects("lfm3-copy")] == [
        "tool-calls"
    ]
    assert len(seen) == 1
    assert "broken" in seen[0]
    assert "could not be copied" in seen[0]


# -- v0.26.0: R41–R45, R49, R51 (GUI/chat half) -----------------------


def test_status_bar_true_with_live_session(window, qapp):
    """R41: with a live session, the status bar never reads "Pick
    a profile to begin." — and a fresher action message is never
    clobbered by a refresh."""
    # Any refresh with no session sets the stale line (the way a
    # post-startup refresh does); setting the session must
    # replace it.
    window.refresh_session()
    qapp.processEvents()
    assert window.statusBar().currentMessage() == "Pick a profile to begin."
    _select_session(window)
    qapp.processEvents()
    assert window.statusBar().currentMessage() == "Ready."
    assert "lfm3-tool" not in window.statusBar().currentMessage()
    assert "tool-calls" not in window.statusBar().currentMessage()
    # A fresher action message survives later refreshes.
    window._say("Did a thing.")
    window.refresh_session()
    assert window.statusBar().currentMessage() == "Did a thing."


def test_status_bar_true_with_profile_only(window, qapp):
    """R41: a profile with no project yet is past "Pick a
    profile" too."""
    window.refresh_session()
    assert window.statusBar().currentMessage() == "Pick a profile to begin."
    window.set_session("lfm3-tool", None)
    qapp.processEvents()
    assert window.statusBar().currentMessage() == "Ready."


def test_settings_ollama_status_no_overlap(window, seed_models, qapp):
    """R42: opening Settings with a multi-model Ollama list shows
    no overlap at any moment — the label's wrapped height is
    reserved the moment the text lands, not seconds later."""
    from PySide6.QtCore import QPoint

    seed_models([
        "lfm3:1.7b", "qwen3.5:4b", "qwen3-vl:2b-instruct",
        "minicpm-v:8b", "gemma3:4b",
    ])
    win = window.open_settings_window()
    win.show()
    qapp.processEvents()
    label = win.ollama_status
    button = win.ollama_refresh_btn
    # Settle on the short text first, so the measure below is the
    # true t=0 state when the long text lands — not a layout that
    # already settled on an earlier refresh.
    label.setText("Status: Checking...")
    qapp.processEvents()
    win._on_models_refreshed()
    # No processEvents between the refresh and the measure: the
    # relayout is synchronous, so the geometry is right at once.
    assert "lfm3:1.7b" in label.text()
    assert "gemma3:4b" in label.text()
    # The box is at least as tall as its wrapped text needs: the
    # second line cannot spill onto the button below. (The rect
    # comparison alone would not catch it — the label's rect stays
    # small while its text overflows it.)
    assert label.height() >= label.heightForWidth(label.width())
    label_bottom = label.mapTo(win, QPoint(0, label.height())).y()
    button_top = button.mapTo(win, QPoint(0, 0)).y()
    assert label_bottom <= button_top
    qapp.processEvents()
    assert label.height() >= label.heightForWidth(label.width())
    label_bottom = label.mapTo(win, QPoint(0, label.height())).y()
    button_top = button.mapTo(win, QPoint(0, 0)).y()
    assert label_bottom <= button_top
    win.close()


def test_starter_row_fits_with_little_free_ram(window, monkeypatch, seed_models):
    """R43: the verdict is judged against total RAM — with 8 GB
    total and only 1.6 GB free (the audit's numbers), the starter
    still reads "Fits this PC", never "Too big" next to "A good
    first pick"."""
    import stella.gui as gui_mod

    from stella.gui import NewProfileDialog

    seed_models(
        ["lfm3:1.7b", "qwen3.5:8b"],
        {"lfm3:1.7b": 2_000_000_000, "qwen3.5:8b": 5_000_000_000},
    )
    monkeypatch.setattr(
        gui_mod, "measure_pc",
        lambda: {"ram_total_gb": 8.0, "ram_available_gb": 1.6},
    )
    dialog = NewProfileDialog(window)
    first = dialog.model_list.item(0).text()
    assert "A good first pick." in first
    assert "Fits this PC." in first
    assert "Too big" not in first
    # The 8B model is still honestly too big at 8 GB total.
    second = dialog.model_list.item(1).text()
    assert "Too big for this PC." in second
    dialog.close()


def test_picker_remeasures_ram_on_refresh(window, monkeypatch, seed_models):
    """R43: a refill re-measures the verdict — the old code
    measured once at construct and never again."""
    import stella.gui as gui_mod

    from stella.gui import NewProfileDialog

    seed_models(["lfm3:1.7b"], {"lfm3:1.7b": 2_000_000_000})
    ram = {"ram_total_gb": 8.0, "ram_available_gb": 8.0}
    monkeypatch.setattr(gui_mod, "measure_pc", lambda: dict(ram))
    dialog = NewProfileDialog(window)
    assert "Fits this PC." in dialog.model_list.item(0).text()
    ram["ram_total_gb"] = 4.0
    dialog._fill_model_list()
    assert "Too big for this PC." in dialog.model_list.item(0).text()
    dialog.close()


def test_run_buttons_visible_at_1366x768(window, qapp):
    """R44: the full Pause / Resume / Proof run / Estimate row is
    visible at 1366x768 with no scroll."""
    from PySide6.QtCore import QPoint

    window.resize(1366, 768)
    window.show()
    qapp.processEvents()
    _select_session(window)
    # The run buttons live on the bento page, not the first-run
    # checklist — dismiss the checklist the way the user does.
    window.check_dismiss_btn.click()
    qapp.processEvents()
    assert window.bento_widget.isVisible()
    viewport = window.session_scroll.viewport()
    height = viewport.height()
    for button in (
        window.train_pause_btn, window.train_resume_btn,
        window.train_proof_btn, window.train_estimate_btn,
    ):
        # A laid-out button is about 31 px tall; an unlaid-out one
        # reports the 640x480 default — guard the measure itself,
        # or the row check below passes on nonsense numbers.
        assert 0 < button.height() < 100, button.text()
        assert button.isVisibleTo(window), button.text()
        top = button.mapTo(viewport, QPoint(0, 0)).y()
        bottom = top + button.height()
        assert 0 <= top, button.text()
        assert bottom <= height, (
            f"{button.text()} bottom {bottom} below viewport {height}"
        )


def test_typed_cloud_model_kept_when_ollama_down(window, seed_models, qapp):
    """R45: typing a cloud model name with Ollama down keeps the
    pick — the cloud model does not need Ollama."""
    from stella.gui import ChatWindow
    from stella.providers import save_key

    seed_models([], ollama_up=False)
    save_key(window.store.home, "groq", "gsk-test-key")
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert "Ollama is not answering" in chat.messages.toPlainText()
    # A keyless cloud name gets a plain answer, not a silent drop.
    chat.input.setText("gemini-3.8-flash")
    chat.send_btn.click()
    qapp.processEvents()
    assert window.chat_model == ""
    assert "did not find that model" in chat.messages.toPlainText()
    # The keyed cloud name is kept.
    chat.input.setText("openai/gpt-oss-120b")
    chat.send_btn.click()
    qapp.processEvents()
    assert window.chat_model == "openai/gpt-oss-120b"
    assert window.chat_provider == "groq"
    assert "I will chat with openai/gpt-oss-120b" in chat.messages.toPlainText()
    # A later refresh does not repeat the no-models message.
    chat._on_models_refreshed()
    qapp.processEvents()
    assert chat.messages.toPlainText().count("Ollama is not answering") == 1
    chat.close()


def test_chat_window_shows_template_step(window, seed_models, qapp):
    """R49: the chat window shows the template step from real
    store state — step 1 with no session, step 4 once the seeded
    session (dataset set, not started) is picked."""
    from stella.gui import ChatWindow

    seed_models(["lfm3:1.7b"])
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    assert chat.step_label.text() == "Step 1 of 8: Goal."
    _select_session(window)
    chat._refresh_step_label()
    assert chat.step_label.text() == "Step 4 of 8: Recipe."
    chat.close()


def test_settings_warns_when_model_list_stale(window, monkeypatch, qapp):
    """R51: a list past its check threshold is noticed in
    Settings, in plain words with the date."""
    from stella.providers import PROVIDERS

    monkeypatch.setitem(PROVIDERS["groq"], "checked", "2020-01-01")
    win = window.open_settings_window()
    win.show()
    qapp.processEvents()
    assert win._freshness_label.isVisible()
    assert "Groq" in win._freshness_label.text()
    assert "2020-01-01" in win._freshness_label.text()
    win.close()


def test_settings_hides_freshness_note_when_lists_fresh(
    window, monkeypatch, qapp
):
    """R51: fresh lists show no warning."""
    from datetime import date

    from stella.providers import PROVIDERS

    today = date.today().isoformat()
    monkeypatch.setitem(PROVIDERS["groq"], "checked", today)
    monkeypatch.setitem(PROVIDERS["gemini"], "checked", today)
    win = window.open_settings_window()
    win.show()
    qapp.processEvents()
    assert not win._freshness_label.isVisible()
    assert win._freshness_label.text() == ""
    win.close()
