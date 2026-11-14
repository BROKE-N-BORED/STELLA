"""GUI tests — offscreen. Drive the real window, check the menu,
the tree, the session, and the dedicated windows."""
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
    yield win
    win.close()


def _select_session(window):
    """Pick the seeded project in the tree (sets the session)."""
    window.set_session("lfm3-tool", "tool-calls")


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
    # The tree label is the project name plus its status (T53);
    # the dead metamorph-mode suffix is still gone.
    assert child == "tool-calls (draft)"


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
            "Import package...",
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
    assert window._howto_window.topic_list.count() == 13


# -- session --------------------------------------------------------


def test_click_project_sets_session(window, settings):
    child = window.tree.topLevelItem(0).child(0)
    window.tree.setCurrentItem(child)
    assert window._current_profile == "lfm3-tool"
    assert window._current_project == "tool-calls"
    assert "LFM3 Tool Seat" in window.session_title.text()
    assert "tool-calls" in window.session_title.text()
    assert "forge-traces.jsonl" in window.session_summary.text()
    assert window.statusBar().currentMessage() == (
        "Profile: lfm3-tool, project: tool-calls."
    )
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
    assert win.role_edit.text() == "fast"
    assert win.tag_combo.currentText() == "lfm3:1.7b"
    win.role_edit.setText("reviewer")
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
    assert win.topic_list.count() == 13
    assert win.topic_list.item(0).text() == "Getting started"
    win.topic_list.setCurrentRow(0)
    assert "Stella" in win.content.toPlainText()
    win.topic_list.setCurrentRow(5)
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


def test_start_training_without_deps_logs_hint(window, monkeypatch):
    import stella.train as train_mod

    _select_session(window)
    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch", "peft"]
    )
    window.start_training()
    assert "install-training.sh" in window.train_log.toPlainText()
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


def test_start_sleep_without_deps_logs_hint(window, monkeypatch):
    import stella.train as train_mod

    _select_session(window)
    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch", "peft"]
    )
    window.start_sleep()
    assert "install-training.sh" in window.train_log.toPlainText()
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


def test_create_profile_from_ollama_tag(window, seeded):
    from stella.gui import NewProfileDialog

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


def test_new_profile_enter_creates(window, seeded):
    """Enter in the model field creates the profile (T11: Enter works)."""
    from stella.gui import NewProfileDialog

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


def test_chat_window_asks_for_model_when_none_picked(window, monkeypatch, qapp):
    """T76: no typing needed to pick a chat model — clickable
    buttons, one per installed model."""
    import stella.gui as gui_mod

    from stella.gui import ChatWindow

    monkeypatch.setattr(
        gui_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:2b"]
    )
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


def test_chat_window_rejects_unknown_model_name(window, monkeypatch, qapp):
    import stella.gui as gui_mod

    from stella.gui import ChatWindow

    monkeypatch.setattr(gui_mod, "list_models", lambda: ["lfm3:1.7b"])
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    chat.input.setText("not-a-model")
    chat.send_btn.click()
    qapp.processEvents()
    assert window.chat_model == ""
    assert "did not find that model" in chat.messages.toPlainText()
    chat.close()


def test_settings_window_chat_model_picker(window, monkeypatch):
    import stella.gui as gui_mod

    monkeypatch.setattr(
        gui_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:2b"]
    )
    settings_win = window.open_settings_window()
    # Nothing selected by default. The list is grouped: an Ollama
    # header + 2 models, a Groq header + 3, a Gemini header + 3.
    # No key saved, so the cloud models are greyed out.
    assert settings_win.chat_combo.currentIndex() == -1
    assert settings_win.chat_combo.count() == 11
    combo = settings_win.chat_combo
    assert combo.itemText(0) == "On this PC (Ollama)"
    assert not combo.model().item(0).isEnabled()
    assert combo.itemData(1) == "ollama|lfm3:1.7b"
    assert combo.model().item(1).isEnabled()
    assert combo.itemText(3) == "Groq"
    assert combo.itemData(4) == "groq|llama-3.3-70b-versatile"
    assert not combo.model().item(4).isEnabled()
    assert combo.itemText(7) == "Gemini"
    combo.setCurrentText("qwen3.5:2b")
    assert window.chat_model == "qwen3.5:2b"
    assert window.chat_provider == "ollama"
    settings_win.close()
    # Reopening restores the saved pick.
    again = window.open_settings_window()
    assert again.chat_combo.currentText() == "qwen3.5:2b"
    again.close()


def test_settings_providers_save_and_remove(window, monkeypatch):
    import stella.gui as gui_mod
    from stella.providers import get_key, has_key

    monkeypatch.setattr(gui_mod, "list_models", lambda: [])
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
    groq_index = combo.findData("groq|llama-3.3-70b-versatile")
    assert groq_index >= 0
    assert combo.model().item(groq_index).isEnabled()
    settings_win._provider_buttons["groq"]["remove"].click()
    assert not has_key(window.store.home, "groq")
    assert settings_win._key_status["groq"].text() == "No key saved."
    settings_win.close()


def test_settings_providers_save_empty_key_asks(window, monkeypatch):
    import stella.gui as gui_mod

    monkeypatch.setattr(gui_mod, "list_models", lambda: [])
    settings_win = window.open_settings_window()
    settings_win._provider_buttons["gemini"]["save"].click()
    assert settings_win._key_status["gemini"].text() == "Paste a key first."
    settings_win.close()


def test_settings_providers_test_shows_result(window, monkeypatch, qapp):
    import time

    import stella.gui as gui_mod
    from stella.providers import save_key

    monkeypatch.setattr(gui_mod, "list_models", lambda: [])
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


def test_settings_providers_custom_row(window, monkeypatch):
    import stella.gui as gui_mod
    from stella.providers import get_custom_config, get_key

    monkeypatch.setattr(gui_mod, "list_models", lambda: [])
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


def test_chat_window_matches_cloud_model_name(window, monkeypatch, qapp):
    import stella.gui as gui_mod
    from stella.gui import ChatWindow
    from stella.providers import save_key

    monkeypatch.setattr(gui_mod, "list_models", lambda: ["lfm3:1.7b"])
    save_key(window.store.home, "groq", "test-key-123")
    assert window.chat_model == ""
    chat = ChatWindow(window)
    chat.show()
    qapp.processEvents()
    chat.input.setText("llama-3.3-70b-versatile")
    chat.send_btn.click()
    qapp.processEvents()
    assert window.chat_model == "llama-3.3-70b-versatile"
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
    assert any(r == "tool-calls (draft)" for r in rows)


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
    qapp.processEvents()
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
    monkeypatch.setattr(
        gui_mod.export_mod, "import_export",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    window.import_package()  # must not raise out of the handler
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
    prof_win.role_edit.setText("reviewer")
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
    assert proj_win.notes_section.title == "Notes"
    proj_win.notes_edit.setPlainText("just the notes")
    proj_win.display_edit.setText("Renamed in the form")
    assert proj_win.notes_section.title == "Notes (modified)"
    assert proj_win.save_notes() is True
    assert proj_win.notes_section.title == "Notes"
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
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QMessageBox

    import stella.gui as gui_mod
    import stella.train as train_mod

    _select_session(window)
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    proj_win.dataset_edit.setText("new-data.jsonl")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Save
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


def test_create_profile_warns_on_uninstalled_tag(window, seeded, monkeypatch):
    import stella.gui as gui_mod
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    monkeypatch.setattr(gui_mod, "list_models", lambda: ["lfm3:1.7b"])
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
    window, seeded, monkeypatch
):
    import stella.gui as gui_mod
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    monkeypatch.setattr(gui_mod, "list_models", lambda: ["lfm3:1.7b"])
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )
    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("not-a-real-model:99")
    window._create_profile_from(dialog)
    assert [p["name"] for p in seeded.list_profiles()] == ["lfm3-tool"]


def test_create_profile_duplicate_tag_note(window, seeded, monkeypatch):
    import stella.gui as gui_mod
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    monkeypatch.setattr(gui_mod, "list_models", lambda: ["lfm3:1.7b"])
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


def test_create_profile_installed_tag_no_warning(window, seeded, monkeypatch):
    import stella.gui as gui_mod
    from PySide6.QtWidgets import QMessageBox

    from stella.gui import NewProfileDialog

    monkeypatch.setattr(
        gui_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:4b"]
    )

    def _no_prompt(*a, **k):
        raise AssertionError("no warning for an installed, unused tag")

    monkeypatch.setattr(QMessageBox, "question", _no_prompt)
    dialog = NewProfileDialog(window)
    dialog.type_edit.setText("qwen3.5:4b")
    window._create_profile_from(dialog)
    assert seeded.get_profile("qwen3-5-4b")["ollama_tag"] == "qwen3.5:4b"


def test_profile_save_warns_on_uninstalled_tag(window, seeded, monkeypatch, qapp):
    import stella.gui as gui_mod
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(gui_mod, "list_models", lambda: ["lfm3:1.7b"])
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
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    _start_training_ready(window, monkeypatch)
    window.start_training()
    qapp.processEvents()
    assert window._train_worker is not None
    assert window._train_worker._force is True


def test_start_training_on_draft_project_does_not_ask(
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    assert seeded.get_project("lfm3-tool", "tool-calls")["status"] != "done"
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
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(window, "_weights_offer", lambda profile: True)
    monkeypatch.setattr(gui_mod.TrainWorker, "run", lambda self: None)
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


def test_go_with_no_project_asks_for_name_inline(window, seeded, qapp):
    """T15 + T113: project creation is part of the pick — an inline
    name row, not a second window."""
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
    # the sandbox has no training packages, so it logs the hint.
    assert "install-training.sh" in window.train_log.toPlainText()


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


def test_distill_dialog_needs_teacher_and_prompts(window, monkeypatch):
    import stella.gui as gui_mod
    from PySide6.QtWidgets import QFileDialog

    from stella.gui import DistillDialog

    monkeypatch.setattr(
        gui_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:4b"]
    )
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
    win.check_steps[2][1].click()
    qapp.processEvents()
    # The tiny first training is a real run: a real project with
    # the sample dataset, and training started on it.
    data = store.get_project("lfm3-tool", "first-steps")
    assert data["dataset_ref"] == "sample-tool-calls.jsonl"
    assert win._current_project == "first-steps"
    assert "install-training.sh" in win.train_log.toPlainText()
    win.close()


# -- T18: model picker with fit guidance ------------------------------


def _patched_dialog(window, monkeypatch):
    """A NewProfileDialog with two known models on a known PC."""
    import stella.gui as gui_mod

    from stella.gui import NewProfileDialog

    monkeypatch.setattr(
        gui_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:8b"]
    )
    monkeypatch.setattr(
        gui_mod, "list_model_sizes",
        lambda: {"lfm3:1.7b": 2_000_000_000, "qwen3.5:8b": 5_000_000_000},
    )
    monkeypatch.setattr(
        gui_mod, "measure_pc", lambda: {"ram_available_gb": 8.0}
    )
    return NewProfileDialog(window)


def test_new_profile_dialog_opens_with_no_selection(window, monkeypatch):
    dialog = _patched_dialog(window, monkeypatch)
    assert dialog.model_list.currentRow() == -1
    assert dialog.model_list.currentItem() is None
    assert dialog.name_note.text() == ""
    assert not dialog.details_label.isVisible()
    assert dialog.type_edit.text() == ""
    assert not dialog.picked_model()
    dialog.close()


def test_new_profile_dialog_rows_show_what_and_fit(window, monkeypatch):
    dialog = _patched_dialog(window, monkeypatch)
    assert dialog.model_list.count() == 2
    first = dialog.model_list.item(0).text()
    assert first.startswith("lfm3:1.7b\n")
    assert "Liquid AI" in first  # what it does
    assert "Fits this PC." in first  # fit verdict
    second = dialog.model_list.item(1).text()
    assert second.startswith("qwen3.5:8b\n")
    assert "Too big for this PC." in second
    dialog.close()


def test_new_profile_tap_shows_details(window, monkeypatch, qapp):
    dialog = _patched_dialog(window, monkeypatch)
    dialog.show()
    qapp.processEvents()
    dialog.model_list.setCurrentRow(0)
    assert dialog.details_label.isVisible()
    details = dialog.details_label.text()
    assert "6.4 GB" in details  # RAM to train
    assert "1.9 GB" in details  # download size
    assert dialog.name_note.text() == "Profile name: lfm3-1-7b"
    dialog.close()


def test_new_profile_enter_with_no_pick_does_nothing(
    window, seeded, monkeypatch
):
    """T18: Enter with nothing picked does nothing — no profile,
    no warning, no dialog accepted."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    dialog = _patched_dialog(window, monkeypatch)
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
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
    assert child.toolTip(0) == "tool-calls (draft)"


def test_profile_row_shows_health_badge(window, monkeypatch, qapp):
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
        monkeypatch.setattr(gui_mod, "reachable", lambda url=None: ollama_up)
        window._ollama_checked_at = 0
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
    assert child.text(0) == "tool-calls (ready)"
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
    assert child.text(0) == "tool-calls (draft)"
    seeded.update_project("lfm3-tool", "tool-calls", status="done")
    window.refresh_tree()
    child = window.tree.topLevelItem(0).child(0)
    assert child.text(0) == "tool-calls (done)"


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
    a fixed size clamps setGeometry and the dip never shows."""
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
        # Sample through the dip: the width must go below the
        # original at some point (the 97% bottom is brief, so a
        # single sample can miss it).
        min_width = original.width()
        deadline = 0
        while button in dips._animations:
            QTest.qWait(20)
            min_width = min(min_width, button.geometry().width())
            deadline += 20
            assert deadline < 5000
        assert min_width < original.width(), min_width
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
    assert window._menu_action_chat.shortcut().toString() == "F2"


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
    from PySide6.QtWidgets import QFileDialog

    pkg = _source_package(tmp_path)
    _clear_seeded_project(window, seeded)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(pkg))
    window.import_package()
    qapp.processEvents()
    message = window.statusBar().currentMessage()
    assert "Imported tool-calls into lfm3-tool." in message
    assert "The profile already existed." in message
    assert "now uses" not in message


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
    window.import_package()
    qapp.processEvents()
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

    def click_take():
        dlg = QApplication.activeModalWidget()
        assert dlg is not None
        dlg._stella_take_button.click()

    QTimer.singleShot(100, click_take)
    window.import_package()
    qapp.processEvents()
    prof = seeded.get_profile("lfm3-tool")
    assert (prof["ollama_tag"], prof["role"], prof["base_ref"]) == (
        "lfm3:1.7b", "fast", "lfm3:1.7b")
    message = window.statusBar().currentMessage()
    assert "The profile already existed." in message
    assert "The profile now uses the package's tag, role and base." in message
