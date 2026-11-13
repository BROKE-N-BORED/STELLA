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
