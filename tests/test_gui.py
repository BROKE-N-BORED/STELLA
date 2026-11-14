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
    for action in window.menu.actions():
        texts.append(action.text())
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
    assert window.menu_button is not None
    assert window.menu_button.text() == "Menu"
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
    # The tree label is just the project name: no dead mode suffix.
    assert child == "tool-calls"


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


def test_menu_has_expected_actions_in_order(window):
    texts = [
        a.text() for a in window.menu.actions() if not a.isSeparator()
    ]
    assert texts == [
        "Profiles",
        "New profile...",
        "Projects",
        "New project...",
        "Export project...",
        "Import package...",
        "Settings...",
        "How to Use Stella...",
        "Chat...",
    ]
    separators = [a for a in window.menu.actions() if a.isSeparator()]
    assert len(separators) == 3


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
    assert window.train_start_btn.isEnabled()
    assert window.sleep_btn.isEnabled()


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
    assert not window.train_start_btn.isEnabled()
    assert not window.train_resume_btn.isEnabled()
    assert not window.sleep_btn.isEnabled()
    assert not window.train_export_gguf_btn.isEnabled()
    assert not window.train_probe_btn.isEnabled()
    assert not window.download_btn.isEnabled()


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


def test_profile_window_has_download_row(window):
    win = window.open_profile_window("lfm3-tool")
    assert win.download_btn.text() == "Download model"
    assert win.download_cancel_btn is not None
    assert win.download_progress is not None
    # The seeded profile has no base_ref: the status says so.
    assert "No Hugging Face repo set" in win.download_status.text()
    win.close()


def test_project_window_save_writes_through(window, seeded):
    _select_session(window)
    win = window.open_project_window("lfm3-tool", "tool-calls")
    assert win.display_edit.text() == "tool-calls"
    assert win.dataset_edit.text() == "forge-traces.jsonl"
    # No metamorph control: it did nothing, so it gets no control.
    assert not hasattr(win, "metamorph_combo")
    # The fill shows the stored rank (auto-config picked it for
    # this PC when the project was created).
    stored_rank = seeded.get_project("lfm3-tool", "tool-calls")["settings"]["rank"]
    assert win.rank_spin.value() == stored_rank
    win.display_edit.setText("Tool Calls v2")
    win.rank_spin.setValue(16)
    win.notes_edit.setPlainText("raised rank after first look")
    assert win.save() is True
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["display_name"] == "Tool Calls v2"
    assert data["settings"]["rank"] == 16
    # Saving leaves the stored metamorph mode untouched.
    assert data["metamorph"]["mode"] == "both"
    assert seeded.read_notes("lfm3-tool", "tool-calls") == (
        "raised rank after first look"
    )
    win.close()


def test_project_window_rejects_bad_lr(window, seeded, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    # The window stays modified (the bad value was never saved), so
    # closing it prompts (T2) — discard the edits, the test's point
    # is the rejection, not the prompt.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Discard
    )
    win = window.open_project_window("lfm3-tool", "tool-calls")
    win.lr_edit.setText("banana")
    assert win.save() is False
    assert warnings
    assert "Learning rate" in warnings[0]
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["settings"]["learning_rate"] == 0.0002
    win.close()


def test_project_window_full_method_disabled(window):
    _select_session(window)
    win = window.open_project_window("lfm3-tool", "tool-calls")
    assert win.method_combo.itemText(1) == "full"
    assert not win.method_combo.model().item(1).isEnabled()
    win.close()


def test_settings_window_shows_home_and_defaults(window, seeded):
    win = window.open_settings_window()
    assert win.home_label.text() == str(seeded.home)
    assert "localhost" in win.ollama_host.text() or "127.0.0.1" in win.ollama_host.text()
    assert "Status:" in win.ollama_status.text()
    assert win.debug_btn is not None
    assert win.debug_btn.text() == "Write debug report"
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


def test_delete_project_actually_deletes(window, monkeypatch):
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


def test_delete_profile_actually_deletes(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.Yes
    )
    window.delete_profile()
    assert window.store.list_profiles() == []
    assert window._current_profile is None
    assert window.tree.topLevelItemCount() == 0


# -- text rules (U11, U33) ------------------------------------------


def test_no_ampersand_in_visible_labels(window):
    # Qt eats a bare & as a mnemonic marker — forbidden in visible text.
    _select_session(window)
    prof = window.open_profile_window("lfm3-tool")
    proj = window.open_project_window("lfm3-tool", "tool-calls")
    settings_win = window.open_settings_window()
    howto = window.open_howto_window()
    howto.topic_list.setCurrentRow(0)
    bad = [t for t in _visible_texts(window) if "&" in t]
    assert bad == []
    prof.close()
    proj.close()
    settings_win.close()
    howto.close()


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


# -- train / sleep panels -------------------------------------------


def test_train_panel_widgets_exist(window):
    assert window.train_start_btn is not None
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
    assert window.sleep_btn is not None
    assert window.sleep_btn.text() == "Sleep"
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
    assert hasattr(dialog, "model_combo")
    dialog.close()


def test_create_profile_from_hf_repo(window, seeded):
    from PySide6.QtWidgets import QDialog

    from stella.gui import NewProfileDialog

    dialog = NewProfileDialog(window)
    dialog.model_combo.setCurrentText("LiquidAI/LFM3-1.7B")
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
    dialog.model_combo.setCurrentText("qwen3.5:4b")
    window._create_profile_from(dialog)
    data = seeded.get_profile("qwen3-5-4b")
    assert data["ollama_tag"] == "qwen3.5:4b"


def test_create_profile_name_collision_gets_suffix(window, seeded):
    from stella.gui import NewProfileDialog

    for _ in range(2):
        dialog = NewProfileDialog(window)
        dialog.model_combo.setCurrentText("LiquidAI/LFM3-1.7B")
        window._create_profile_from(dialog)
    assert seeded.get_profile("lfm3-1-7b")
    assert seeded.get_profile("lfm3-1-7b-2")


def test_create_profile_empty_model_warns(window, monkeypatch):
    from stella.gui import NewProfileDialog

    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    dialog = NewProfileDialog(window)
    dialog.model_combo.setCurrentText("")
    window._create_profile_from(dialog)
    assert warnings == ["Pick a model first."]
    assert [p["name"] for p in window.store.list_profiles()] == ["lfm3-tool"]


def test_new_profile_enter_creates(window, seeded):
    """Enter in the model field creates the profile (T11: Enter works)."""
    from stella.gui import NewProfileDialog

    dialog = NewProfileDialog(window)
    assert dialog.create_btn.isDefault()
    dialog.create_btn.clicked.connect(lambda: window._create_profile_from(dialog))
    dialog.model_combo.setCurrentText("qwen3.5:4b")
    dialog.model_combo.lineEdit().returnPressed.emit()
    assert seeded.get_profile("qwen3-5-4b")


# -- chat window ------------------------------------------------------


class FakeChatAgent:
    """A stand-in for ChatAgent: instant replies, records cancel."""

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

    def set_callbacks(self, on_narration=None, on_progress=None):
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
    assert "lfm3:1.7b" in chat.messages.toPlainText()
    chat.input.setText("lfm3:1.7b")
    chat.send_btn.click()
    qapp.processEvents()
    assert window.chat_model == "lfm3:1.7b"
    assert "I will chat with lfm3:1.7b" in chat.messages.toPlainText()
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


def test_project_window_bad_rank_falls_back(window, seeded, qapp):
    _corrupt_project_json(
        seeded, "lfm3-tool", "tool-calls",
        lambda d: d["settings"].update(rank="high"),
    )
    win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert win.rank_spin.value() == 8
    assert "stored value was invalid" in win._load_note.text()
    assert win._load_note.isVisible()
    # The rest of the panel still filled from THIS project.
    assert win.display_edit.text() == "tool-calls"
    assert win.dataset_edit.text() == "forge-traces.jsonl"
    # Save writes the good default, not the bad stored value.
    assert win.save() is True
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["settings"]["rank"] == 8
    assert isinstance(data["settings"]["rank"], int)
    win.close()


@pytest.mark.parametrize(
    "mutate, check",
    [
        (lambda d: d["settings"].update(learning_rate="banana"),
         lambda w: w.lr_edit.text() == "0.0002"),
        (lambda d: d["settings"].update(epochs="many"),
         lambda w: w.epochs_spin.value() == 3),
        (lambda d: d["settings"].update(batch_size="lots"),
         lambda w: w.batch_spin.value() == 1),
        (lambda d: d["settings"].update(max_seq_len="long"),
         lambda w: w.seq_spin.value() == 1024),
        (lambda d: d["settings"].update(method="warp"),
         lambda w: w.method_combo.currentText() == "lora"),
        (lambda d: d["settings"].update(rank=999),
         lambda w: w.rank_spin.value() == 8),
        (lambda d: d.update(settings="all of it"),
         lambda w: w.rank_spin.value() == 8),
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


def test_project_window_clean_fill_shows_no_note(window, seeded, qapp):
    win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    assert win._load_note.text() == ""
    assert not win._load_note.isVisible()
    win.close()


def test_project_window_retarget_never_mixes_projects(window, seeded, qapp):
    # Project A holds rank 16; project B has a corrupt rank. Opening
    # A then retargeting to B must show B (default rank + note),
    # never A's values under B's name.
    seeded.create_project("lfm3-tool", "second", settings={"rank": 16})
    _corrupt_project_json(
        seeded, "lfm3-tool", "tool-calls",
        lambda d: d["settings"].update(rank="high"),
    )
    win = window.open_project_window("lfm3-tool", "second")
    qapp.processEvents()
    assert win.rank_spin.value() == 16
    win.retarget("tool-calls")
    qapp.processEvents()
    assert win.rank_spin.value() == 8
    assert win.display_edit.text() == "tool-calls"
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
    # The good project lists normally, with no warning.
    assert any(r == "tool-calls" for r in rows)


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


# -- T44 (pin): Train panel above the fold at 1100x680 ---------------


def test_train_panel_above_fold_at_default_size(window, qapp):
    from PySide6.QtWidgets import QScrollArea

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
    for widget in (window.train_start_btn, window.train_progress):
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


def test_no_project_session_has_no_settings(window, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window.set_session("lfm3-tool", None)
    qapp.processEvents()
    summary = window.session_summary.text()
    assert "rank" not in summary.lower()
    assert "learning rate" not in summary.lower()
    assert "epochs" not in summary.lower()
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
    assert child.text(0) == "tool-calls"
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
    assert proj_win.notes_label.text() == "Notes"
    proj_win.notes_edit.setPlainText("just the notes")
    proj_win.display_edit.setText("Renamed in the form")
    assert proj_win.notes_label.text() == "Notes (modified)"
    assert proj_win.save_notes() is True
    assert proj_win.notes_label.text() == "Notes"
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


def test_start_training_refused_on_bad_lr_in_open_window(
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    proj_win = window.open_project_window("lfm3-tool", "tool-calls")
    qapp.processEvents()
    proj_win.lr_edit.setText("abc")
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: warnings.append(a[2])
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Save
    )
    window.start_training()
    qapp.processEvents()
    # The warning appeared and no worker started: nothing trains on
    # stale settings behind an error.
    assert warnings == ["Learning rate must be a number, like 0.0002."]
    assert window._train_worker is None
    assert "Starting training" not in window.train_log.toPlainText()
    # The form still holds the bad value, for the user to fix.
    assert proj_win.lr_edit.text() == "abc"
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
    proj_win.rank_spin.setValue(16)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Save
    )
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(window, "_weights_offer", lambda profile: True)
    monkeypatch.setattr(gui_mod.TrainWorker, "run", lambda self: None)
    window.start_training()
    qapp.processEvents()
    # The edits were saved first, then the worker started on them.
    assert seeded.get_project("lfm3-tool", "tool-calls")["settings"]["rank"] == 16
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
    dialog.model_combo.setCurrentText("not-a-real-model:99")
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
    dialog.model_combo.setCurrentText("not-a-real-model:99")
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
    dialog.model_combo.setCurrentText("lfm3:1.7b")
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
    dialog.model_combo.setCurrentText("qwen3.5:4b")
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


def test_start_training_on_trained_project_asks_first(
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    seeded.update_project("lfm3-tool", "tool-calls", status="trained")
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


def test_start_training_on_trained_project_yes_forces(
    window, seeded, monkeypatch, qapp
):
    from PySide6.QtWidgets import QMessageBox

    _select_session(window)
    seeded.update_project("lfm3-tool", "tool-calls", status="trained")
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
    assert seeded.get_project("lfm3-tool", "tool-calls")["status"] != "trained"
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
