"""GUI smoke tests — offscreen. Drive the real window, check the panes."""
import pytest
from PySide6.QtWidgets import QLabel, QPushButton, QWidget


@pytest.fixture()
def window(qapp, seeded):
    from stella.gui import MainWindow

    win = MainWindow(store=seeded)
    win.show()
    qapp.processEvents()
    yield win
    win.close()


def test_window_opens_with_three_panes(window, qapp):
    assert window.isVisible()
    assert window.profile_list.count() == 1
    assert window.project_list.count() == 1
    assert "lfm3" in window.profile_list.item(0).text().lower()
    assert "tool-calls" in window.project_list.item(0).text()


def test_role_shows_in_profile_list(window):
    text = window.profile_list.item(0).text()
    assert "[fast]" in text
    assert "lfm3:1.7b" in text


def test_detail_fills_from_selection(window):
    assert window.prof_display.text() == "LFM3 Tool Seat"
    assert window.prof_role.text() == "fast"
    assert window.proj_display.text() == "tool-calls"
    assert window.proj_dataset.text() == "forge-traces.jsonl"
    assert window.proj_metamorph.currentText() == "both"
    assert window.proj_rank.value() == 8


def test_save_project_writes_through(window, seeded):
    window.proj_display.setText("Tool Calls v2")
    window.proj_rank.setValue(16)
    window.proj_notes.setPlainText("raised rank after first look")
    window.save_project()
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["display_name"] == "Tool Calls v2"
    assert data["settings"]["rank"] == 16
    assert seeded.read_notes("lfm3-tool", "tool-calls") == "raised rank after first look"


def test_save_profile_writes_through(window, seeded):
    window.prof_role.setText("reviewer")
    window.save_profile()
    assert seeded.get_profile("lfm3-tool")["role"] == "reviewer"


def test_empty_store_window(qapp, store):
    from stella.gui import MainWindow

    win = MainWindow(store=store)
    win.show()
    qapp.processEvents()
    assert win.profile_list.count() == 0
    assert win.project_list.count() == 0
    win.close()


def test_no_ampersand_in_visible_labels(window):
    # Qt eats a bare & as a mnemonic marker — forbidden in visible text.
    bad = []
    for widget in window.findChildren(QWidget):
        text = ""
        if isinstance(widget, (QLabel, QPushButton)):
            text = widget.text()
        if "&" in text:
            bad.append((type(widget).__name__, text))
    assert bad == []


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
    window._say("Profile: lfm3-tool — project: tool-calls")
    assert window.statusBar().currentMessage() == (
        "Profile: lfm3-tool — project: tool-calls"
    )


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

    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch", "peft"]
    )
    window.start_training()
    assert "install-training.sh" in window.train_log.toPlainText()
    assert window._train_worker is None


def test_use_sample_dataset_sets_ref(window, seeded):
    window.use_sample_dataset()
    assert window.proj_dataset.text() == "sample-tool-calls.jsonl"
    data = seeded.get_project("lfm3-tool", "tool-calls")
    assert data["dataset_ref"] == "sample-tool-calls.jsonl"


def test_train_progress_updates(window):
    window._on_train_progress(5, 20, 2.5)
    assert window.train_progress.maximum() == 20
    assert window.train_progress.value() == 5
    assert "Step 5 / 20" in window.train_loss.text()
    assert "2.5000" in window.train_loss.text()


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

    monkeypatch.setattr(
        train_mod, "training_deps_missing", lambda: ["torch", "peft"]
    )
    window.start_sleep()
    assert "install-training.sh" in window.train_log.toPlainText()
    assert window._sleep_worker is None


def test_start_sleep_gated_on_save_failure(window, monkeypatch):
    import stella.train as train_mod

    # Deps present, but the learning rate is not a number — the save
    # fails, and sleep must NOT start on the stale settings.
    monkeypatch.setattr(train_mod, "training_deps_missing", lambda: [])
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    window.proj_lr.setText("banana")
    window.start_sleep()
    assert window._sleep_worker is None
    assert warnings
    assert "Learning rate" in warnings[0]


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


def test_project_form_greyed_out_without_project(window):
    window._current_project = None
    window._show_project_detail()
    assert not window.proj_rank.isEnabled()
    assert not window.save_project_btn.isEnabled()
    # Greyed-out, the panel shows the defaults a new project gets.
    assert window.proj_rank.value() == 8
    assert window.proj_lr.text() == "0.0002"
    assert window.proj_epochs.value() == 3
    assert window.proj_seq.value() == 1024


def test_full_method_cannot_be_picked(window):
    assert window.proj_method.itemText(1) == "full"
    assert not window.proj_method.model().item(1).isEnabled()


def test_profile_panel_has_no_processor_field(window):
    assert not hasattr(window, "prof_processor")


def test_new_profile_enter_creates(window, seeded):
    """Enter in the model field creates the profile (T11: Enter works)."""
    from stella.gui import NewProfileDialog

    dialog = NewProfileDialog(window)
    assert dialog.create_btn.isDefault()
    dialog.create_btn.clicked.connect(lambda: window._create_profile_from(dialog))
    dialog.model_combo.setCurrentText("qwen3.5:4b")
    dialog.model_combo.lineEdit().returnPressed.emit()
    assert seeded.get_profile("qwen3-5-4b")
