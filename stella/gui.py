"""STELLA window — native Qt, menu + tree + session.

The main window is deliberately uncluttered: a menu button top-left,
a collapsible profile tree on the left (each profile expands to show
its projects), and the current training session on the right (profile
and project summary, model download, Train panel, Sleep panel).

Everything else lives in its own window, reached from the menu or by
double-clicking a tree row: Profile window, Project window, Settings
window, How to Use window. Nothing is crammed into one window.

Clicking a project in the tree SETS THE TRAINING SESSION (current
profile + project). The session is remembered across restarts via
QSettings — that is the user's own pick coming back, not a default:
on first run nothing is selected at all.

No web UI, no network beyond localhost Ollama and the Hugging Face
download. No "&" in any visible label — Qt eats a bare & as a
mnemonic marker. No em-dashes in any visible text.

Training, sleep, and model downloads run off the GUI thread (worker
threads / a subprocess) so the window stays responsive; they only
talk to the window through Qt signals.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QSettings,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import export as export_mod
from . import provision
from .chat_agent import ChatAgent
from .debug_log import DebugLogger, check_ollama
from .howto import topic_text, topic_titles
from .model import (
    DEFAULT_SETTINGS,
    METAMORPH_MODES,
    STELLA_VERSION,
    StellaError,
    Store,
    slug_from_model,
)
from .ollama import list_models, ollama_url
from .train import TrainController


def _help_label(text):
    """A small grey plain-words line under a field."""
    label = QLabel(text)
    label.setStyleSheet("color: #9a9a9a; font-size: 11px;")
    label.setWordWrap(True)
    return label


def _weights_label(status):
    """A weights_status dict as one plain-words line."""
    state = status["state"]
    if state == "no-repo":
        return "No Hugging Face repo set. Set Base ref in the profile window."
    if state == "missing":
        return "Not downloaded yet."
    if state == "partial":
        return (
            "Partly downloaded "
            f"({provision.format_size(status['size_bytes'])} so far)."
        )
    return f"Ready: {provision.format_size(status['size_bytes'])} on disk."


class NewProfileDialog(QDialog):
    """The New Profile form, as a real window: pick a model, done.

    It used to be a plain QWidget shown as a child of the main window,
    which rendered as a frameless smear over the main window on a real
    PC (the New Profile fields overlapped the profile list). A QDialog
    gets its own window frame and title bar, and exec() makes it modal,
    so the form is always readable and the main window waits for it.

    And it used to demand a role, a display name, and a base ref up
    front. It doesn't anymore: the profile's name comes from the model,
    and role/display/base can be changed later in the profile window.
    One pick, one button.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New profile")
        self.installed_models = list_models()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Pick a model: that is all it takes."))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        if self.installed_models:
            self.model_combo.addItems(self.installed_models)
        self.model_combo.setPlaceholderText(
            "Pick an installed model, or type a Hugging Face repo "
            "like LiquidAI/LFM3-1.7B"
        )
        self.model_combo.setMinimumWidth(420)
        layout.addWidget(self.model_combo)
        if not self.installed_models:
            layout.addWidget(
                QLabel("Ollama is not answering. Type the model by hand.")
            )
        self.name_note = QLabel("")
        layout.addWidget(self.name_note)
        self.model_combo.currentTextChanged.connect(self._update_name_note)
        self._update_name_note()
        buttons = QHBoxLayout()
        self.create_btn = QPushButton("Create profile")
        self.create_btn.setDefault(True)
        # Enter in the model field must create too: the combo's line
        # edit eats Return, so the default button alone won't fire.
        self.model_combo.lineEdit().returnPressed.connect(
            self.create_btn.click
        )
        self.cancel_btn = QPushButton("Cancel")
        buttons.addWidget(self.create_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

    def _update_name_note(self):
        model = self.model_combo.currentText().strip()
        if model:
            self.name_note.setText(
                f"Profile name: {slug_from_model(model)}"
            )
        else:
            self.name_note.setText("")


class TrainWorker(QThread):
    """Runs train_project off the GUI thread. Only talks to the
    window through signals — never touches a widget directly."""

    progress = Signal(int, int, float)  # step, total, loss
    log = Signal(str)
    finished = Signal(bool, str)  # ok, message

    def __init__(self, store, profile, project, resume=False, parent=None):
        super().__init__(parent)
        self._store = store
        self._profile = profile
        self._project = project
        self._resume = resume
        self._controller = TrainController()

    def request_stop(self):
        self._controller.request_stop()

    def _event(self, event: dict):
        kind = event.get("type")
        if kind == "started":
            self.progress.emit(0, event["total_steps"], 0.0)
            self.log.emit(
                f"Training: {event['total_steps']} steps, "
                f"LoRA rank {event['rank']}."
            )
        elif kind == "step":
            self.progress.emit(
                event["step"], event["total_steps"], float(event["loss"])
            )
            self.log.emit(
                f"step {event['step']}/{event['total_steps']} "
                f"loss {event['loss']:.4f}"
            )
        elif kind == "checkpoint":
            self.log.emit(f"checkpoint saved: step {event['step']}")
        elif kind == "val":
            self.log.emit(
                f"epoch {event['epoch']} validation loss "
                f"{event['loss']:.4f}"
            )
        elif kind == "paused":
            self.log.emit(f"Paused at step {event['step']}.")
        elif kind == "done":
            self.log.emit(f"Done. Adapter saved to {event['adapter']}")

    def run(self):
        from .train import train_project

        try:
            summary = train_project(
                self._store,
                self._profile,
                self._project,
                resume=self._resume,
                on_event=self._event,
                controller=self._controller,
            )
        except StellaError as exc:
            self.finished.emit(False, str(exc))
            return
        except Exception as exc:  # keep the window alive on a crash
            self.finished.emit(False, f"Training failed: {exc}")
            return
        self.finished.emit(True, f"Trained {summary['steps']} steps.")


class SleepWorker(QThread):
    """Runs sleep_project off the GUI thread. Same signal pattern
    as TrainWorker — progress goes to the shared bar, everything
    else to the log."""

    progress = Signal(int, int, float)  # step, total, loss
    log = Signal(str)
    finished = Signal(bool, str)  # ok, message

    def __init__(self, store, profile, project, dream=False, parent=None):
        super().__init__(parent)
        self._store = store
        self._profile = profile
        self._project = project
        self._dream = dream
        self._controller = TrainController()

    def request_stop(self):
        self._controller.request_stop()

    def _event(self, event: dict):
        kind = event.get("type")
        if kind == "started":
            self.log.emit(
                f"Sleep cycle {event['cycle']}: {event['new_rows']} new rows"
                + (
                    f", {event['dreamed_rows']} dreamed"
                    if event.get("dreamed_rows")
                    else ""
                )
                + (", resuming" if event.get("resumed") else "")
                + "."
            )
        elif kind == "dream":
            self.log.emit(f"Dreamed {event['kept']} practice rows.")
        elif kind == "dream_skipped":
            self.log.emit(f"Dreaming skipped: {event['reason']}")
        elif kind == "step":
            self.progress.emit(
                event["step"], event["total_steps"], float(event["loss"])
            )
            self.log.emit(
                f"step {event['step']}/{event['total_steps']} "
                f"loss {event['loss']:.4f}"
            )
        elif kind == "checkpoint":
            self.log.emit(f"checkpoint saved: step {event['step']}")
        elif kind == "val":
            self.log.emit(
                f"epoch {event['epoch']} validation loss "
                f"{event['loss']:.4f}"
            )
        elif kind == "replay":
            self.log.emit("Replay check: old rows vs new adapter...")
        elif kind == "replay_done":
            before = event["old_loss_before"]
            after = event["old_loss_after"]
            new = event["new_loss"]
            fmt = lambda v: f"{v:.4f}" if v is not None else "n/a"
            self.log.emit(
                f"old loss {fmt(before)} -> {fmt(after)}, "
                f"new loss {fmt(new)}, {event['status']}"
            )
        elif kind == "paused":
            self.log.emit(
                f"Paused at step {event['step']}. Run sleep again to resume."
            )
        elif kind == "done":
            self.log.emit(
                f"Sleep cycle {event['cycle']} done: {event['status']}."
            )

    def run(self):
        from .sleep import sleep_project

        try:
            report = sleep_project(
                self._store,
                self._profile,
                self._project,
                dream=self._dream,
                on_event=self._event,
                controller=self._controller,
            )
        except StellaError as exc:
            self.finished.emit(False, str(exc))
            return
        except Exception as exc:  # keep the window alive on a crash
            self.finished.emit(False, f"Sleep failed: {exc}")
            return
        if report.get("status") == "paused":
            self.finished.emit(
                True,
                f"Sleep paused at step {report['steps']}. "
                "Run sleep again to resume.",
            )
            return
        self.finished.emit(
            True,
            f"Sleep cycle {report['cycle']} done: {report['status']}.",
        )


class JobWorker(QThread):
    """Generic off-thread job (GGUF export, refusal probe). The job
    function takes a log callable and returns its finish message."""

    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            message = self._fn(self.log.emit)
        except StellaError as exc:
            self.finished.emit(False, str(exc))
            return
        except Exception as exc:
            self.finished.emit(False, f"Failed: {exc}")
            return
        self.finished.emit(True, message)


class DownloadManager(QObject):
    """Downloads base weights in a separate process.

    The download runs as `python -m stella.provision download <repo>`
    in a QProcess, so a big multi-GB download can never block the
    window, and cancelling it just kills the process: the Hugging
    Face hub resumes an interrupted download on the next run, so a
    cancelled download never loses what it already fetched.

    The subprocess prints PROGRESS / DONE / ERROR lines on stdout;
    this manager parses them into signals. `command` overrides the
    subprocess for tests: [program, *args].
    """

    progress = Signal(int, int)  # downloaded bytes, total bytes (0 unknown)
    finished = Signal(bool, str)  # ok, message

    def __init__(self, parent=None, command=None):
        super().__init__(parent)
        self._command = command
        self._process: QProcess | None = None
        self._cancelled = False
        self._buffer = ""
        self._done_path: str | None = None
        self._error: str | None = None

    def is_running(self):
        return (
            self._process is not None
            and self._process.state() != QProcess.NotRunning
        )

    def was_cancelled(self):
        return self._cancelled

    def start(self, repo_id):
        if self.is_running():
            return False
        self._cancelled = False
        self._buffer = ""
        self._done_path = None
        self._error = None
        proc = QProcess(self)
        proc.readyReadStandardOutput.connect(self._on_ready_read)
        proc.finished.connect(self._on_finished)
        if self._command is not None:
            program, args = self._command[0], list(self._command[1:])
        else:
            program = sys.executable
            args = ["-m", "stella.provision", "download", repo_id]
            # The child must find the stella package even when the
            # window was launched from another folder.
            env = QProcessEnvironment.systemEnvironment()
            parent_dir = str(Path(__file__).resolve().parent.parent)
            existing = env.value("PYTHONPATH", "")
            env.insert(
                "PYTHONPATH",
                parent_dir + (os.pathsep + existing if existing else ""),
            )
            proc.setProcessEnvironment(env)
        self._process = proc
        proc.start(program, args)
        return True

    def cancel(self):
        if self.is_running():
            self._cancelled = True
            self._process.kill()

    def wait_for_finished(self, msecs=5000):
        if self._process is not None:
            self._process.waitForFinished(msecs)

    def _on_ready_read(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput()).decode(
            "utf-8", "replace"
        )
        self._buffer += data
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line.strip())

    def _handle_line(self, line):
        if line.startswith("PROGRESS "):
            try:
                _, down, total = line.split()
                self.progress.emit(int(down), int(total))
            except ValueError:
                pass
        elif line.startswith("DONE "):
            self._done_path = line[5:].strip()
        elif line.startswith("ERROR "):
            self._error = line[6:].strip()

    def _on_finished(self, exit_code, _status):
        # readyRead may not have fired for the tail: drain it, so a
        # DONE/ERROR line printed just before exit is not lost.
        if self._process is not None:
            rest = bytes(self._process.readAllStandardOutput()).decode(
                "utf-8", "replace"
            )
            self._buffer += rest
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._handle_line(line.strip())
            if self._buffer.strip():
                self._handle_line(self._buffer.strip())
            self._buffer = ""
        self._process = None
        if self._cancelled:
            self.finished.emit(
                False,
                "Download stopped. It will pick up where it left off.",
            )
        elif self._error is not None:
            self.finished.emit(False, self._error)
        elif exit_code == 0 and self._done_path:
            self.finished.emit(True, self._done_path)
        elif exit_code == 0:
            self.finished.emit(True, "")
        else:
            self.finished.emit(
                False, "The download stopped unexpectedly. Try again."
            )


# ---------------------------------------------------------------- windows


class ProfileWindow(QDialog):
    """One profile's settings, in its own window.

    Reached from the menu (Profiles) or by double-clicking a profile
    row in the tree. Every field explains itself in plain words
    underneath. Also the home of the Download model button: the base
    weights for this profile, with progress and cancel.
    """

    def __init__(self, main, slug, parent=None):
        super().__init__(parent)
        self._main = main
        self._slug = slug
        self.setWindowTitle(f"Profile: {slug}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.display_edit = QLineEdit()
        self.role_edit = QLineEdit()
        self.role_edit.setPlaceholderText("driver, reviewer, vision...")
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        self.base_edit = QLineEdit()
        form.addRow("Display name", self.display_edit)
        form.addRow(
            "",
            _help_label(
                "Just a label for the list. It already says the model's name."
            ),
        )
        form.addRow("Role", self.role_edit)
        form.addRow(
            "",
            _help_label(
                "Only matters if Code Forge uses this profile as a seat "
                "(driver, reviewer...). Leave blank otherwise."
            ),
        )
        form.addRow("Ollama tag", self.tag_combo)
        form.addRow(
            "",
            _help_label(
                "The model as Ollama knows it on this PC. "
                "Used for dreaming and the refusal probe."
            ),
        )
        form.addRow("Base ref", self.base_edit)
        form.addRow(
            "",
            _help_label(
                "Where training loads the base model from: a Hugging Face "
                "repo like LiquidAI/LFM3-1.7B. Needed before you train."
            ),
        )
        # No Processor row: the stored field exists but nothing in
        # Stella reads it — showing it only asked a question nobody
        # could answer. It stays in profile.json for compatibility.
        layout.addLayout(form)

        save_btn = QPushButton("Save profile")
        save_btn.clicked.connect(self.save)
        layout.addWidget(save_btn)

        layout.addWidget(QLabel("Model weights"))
        self.download_status = QLabel("")
        self.download_status.setWordWrap(True)
        layout.addWidget(self.download_status)
        self.download_progress = QProgressBar()
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(0)
        layout.addWidget(self.download_progress)
        dl_btns = QHBoxLayout()
        self.download_btn = QPushButton("Download model")
        self.download_btn.clicked.connect(
            lambda: self._main.start_download(self._slug)
        )
        self.download_cancel_btn = QPushButton("Cancel")
        self.download_cancel_btn.clicked.connect(self._main.cancel_download)
        self.download_cancel_btn.setEnabled(False)
        dl_btns.addWidget(self.download_btn)
        dl_btns.addWidget(self.download_cancel_btn)
        dl_btns.addStretch(1)
        layout.addLayout(dl_btns)
        layout.addWidget(
            _help_label(
                "Downloads the base weights from Hugging Face. If it "
                "stops, press Download again: it picks up where it left "
                "off, nothing is downloaded twice."
            )
        )

        btns = QHBoxLayout()
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(lambda: self._main.rename_profile(self._slug))
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(lambda: self._main.delete_profile(self._slug))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(rename_btn)
        btns.addWidget(delete_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        layout.addLayout(btns)
        layout.addStretch(1)

        self._load()
        self.refresh_download_status()

    @property
    def slug(self):
        return self._slug

    def retarget(self, new_slug):
        """The profile was renamed: follow it to the new name."""
        self._slug = new_slug
        self.setWindowTitle(f"Profile: {new_slug}")
        self._load()
        self.refresh_download_status()

    def _load(self):
        self.tag_combo.clear()
        models = list_models()
        if models:
            self.tag_combo.addItems(models)
        try:
            p = self._main.store.get_profile(self._slug)
        except StellaError:
            self.display_edit.setText("")
            self.role_edit.setText("")
            self.base_edit.setText("")
            return
        self.display_edit.setText(p.get("display_name", ""))
        self.role_edit.setText(p.get("role", ""))
        tag = p.get("ollama_tag", "")
        if tag and tag not in models:
            self.tag_combo.addItem(tag)
        self.tag_combo.setCurrentText(tag)
        self.base_edit.setText(p.get("base_ref", ""))

    def save(self):
        try:
            self._main.store.update_profile(
                self._slug,
                display_name=self.display_edit.text().strip(),
                role=self.role_edit.text().strip(),
                ollama_tag=self.tag_combo.currentText().strip(),
                base_ref=self.base_edit.text().strip(),
            )
        except StellaError as exc:
            QMessageBox.warning(self, "Stella", str(exc))
            return
        self._main.refresh_tree()
        self._main.refresh_session()
        self.refresh_download_status()
        self._main._say(f"Saved profile {self._slug}.")

    def refresh_download_status(self):
        """Re-read the weights state from disk (called after a
        download finishes and whenever the window opens)."""
        manager = self._main.download_manager
        running_here = (
            manager.is_running()
            and self._main.download_profile == self._slug
        )
        self.download_btn.setEnabled(not running_here)
        self.download_cancel_btn.setEnabled(running_here)
        try:
            status = provision.weights_status(self._main.store, self._slug)
        except StellaError:
            self.download_status.setText("Profile not found.")
            return
        self.download_status.setText(_weights_label(status))
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(
            100 if status["state"] == "ready" else 0
        )

    def on_download_progress(self, downloaded, total):
        if total > 0:
            pct = downloaded * 100 // total
            self.download_progress.setMaximum(100)
            self.download_progress.setValue(pct)
            self.download_status.setText(
                f"Downloading: {pct}% "
                f"({provision.format_size(downloaded)} of "
                f"{provision.format_size(total)})"
            )
        else:
            self.download_progress.setMaximum(0)
            self.download_status.setText(
                "Downloading: "
                f"{provision.format_size(downloaded)} so far"
            )


class ProjectWindow(QDialog):
    """One project's settings, in its own window.

    Reached from the menu (Projects) or by double-clicking a project
    row in the tree. Every field explains itself in plain words
    underneath. Saving here is what training reads: there is no
    project form in the main window anymore.
    """

    def __init__(self, main, profile, project, parent=None):
        super().__init__(parent)
        self._main = main
        self._profile = profile
        self._project = project
        self.setWindowTitle(f"Project: {profile} / {project}")
        self.setMinimumWidth(480)
        self.resize(520, 640)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)

        form = QFormLayout()
        self.display_edit = QLineEdit()
        self.dataset_edit = QLineEdit()
        self.dataset_edit.setPlaceholderText("path or name of the training data")
        self.method_combo = QComboBox()
        self.method_combo.addItems(["lora", "full"])
        # "full" is not feasible on this PC (and train.py never reads
        # the setting anyway — it always trains LoRA). Keep it listed
        # so old projects still show it, but nobody new can pick it.
        self.method_combo.model().item(1).setEnabled(False)
        self.rank_spin = QSpinBox()
        self.rank_spin.setRange(1, 64)
        self.lr_edit = QLineEdit()
        self.epochs_spin = QSpinBox()
        self.epochs_spin.setRange(1, 100)
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 32)
        self.seq_spin = QSpinBox()
        self.seq_spin.setRange(128, 32768)
        self.metamorph_combo = QComboBox()
        self.metamorph_combo.addItems(list(METAMORPH_MODES))
        self.metamorph_combo.setToolTip(
            "MetaMorphAi modes are not wired up yet. This is stored "
            "but training ignores it."
        )
        form.addRow("Display name", self.display_edit)
        form.addRow("", _help_label("Just a label for the project list."))
        form.addRow("Dataset", self.dataset_edit)
        form.addRow(
            "",
            _help_label(
                "The training data: a .jsonl file of examples. "
                "The Train panel has a sample to try."
            ),
        )
        form.addRow("Method", self.method_combo)
        form.addRow(
            "",
            _help_label(
                "lora trains a small adapter on top of the base: the "
                "only way that fits this PC."
            ),
        )
        form.addRow("LoRA rank", self.rank_spin)
        form.addRow(
            "",
            _help_label(
                "How big the adapter is. 8 is the usual. Bigger learns "
                "more but uses more RAM."
            ),
        )
        form.addRow("Learning rate", self.lr_edit)
        form.addRow(
            "",
            _help_label(
                "How big each training step is. 0.0002 is the usual. "
                "Bigger learns faster but can wreck the model."
            ),
        )
        form.addRow("Epochs", self.epochs_spin)
        form.addRow(
            "", _help_label("How many full passes over the data. 3 is the usual.")
        )
        form.addRow("Batch size", self.batch_spin)
        form.addRow(
            "", _help_label("Examples per training step. 1 fits this PC. Leave it.")
        )
        form.addRow("Max seq len", self.seq_spin)
        form.addRow(
            "", _help_label("Longest example, in tokens. 1024 is the usual.")
        )
        form.addRow("MetaMorphAi", self.metamorph_combo)
        form.addRow(
            "",
            _help_label(
                "Does nothing yet. The modes are not wired to training. "
                "Leave it alone for now."
            ),
        )
        layout.addLayout(form)

        layout.addWidget(QLabel("Notes"))
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(100)
        layout.addWidget(self.notes_edit)
        layout.addWidget(
            _help_label("Anything you want to remember about this fine-tune.")
        )

        save_btn = QPushButton("Save project")
        save_btn.clicked.connect(self.save)
        layout.addWidget(save_btn)

        btns = QHBoxLayout()
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(
            lambda: self._main.rename_project(self._profile, self._project)
        )
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(
            lambda: self._main.delete_project(self._profile, self._project)
        )
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(rename_btn)
        btns.addWidget(delete_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        layout.addLayout(btns)
        layout.addStretch(1)

        self._load()

    @property
    def profile(self):
        return self._profile

    @property
    def project(self):
        return self._project

    def retarget(self, new_project):
        """The project was renamed: follow it to the new name."""
        self._project = new_project
        self.setWindowTitle(f"Project: {self._profile} / {new_project}")
        self._load()

    def retarget_profile(self, new_profile):
        """The profile was renamed: follow it to the new name."""
        self._profile = new_profile
        self.setWindowTitle(f"Project: {new_profile} / {self._project}")
        self._load()

    def _load(self):
        try:
            p = self._main.store.get_project(self._profile, self._project)
            notes = self._main.store.read_notes(self._profile, self._project)
        except StellaError:
            return
        self.display_edit.setText(p.get("display_name", ""))
        self.dataset_edit.setText(p.get("dataset_ref", ""))
        settings = p.get("settings", {})
        method = settings.get("method", "lora")
        idx = self.method_combo.findText(method)
        self.method_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.rank_spin.setValue(int(settings.get("rank", 8)))
        self.lr_edit.setText(str(settings.get("learning_rate", 0.0002)))
        self.epochs_spin.setValue(int(settings.get("epochs", 3)))
        self.batch_spin.setValue(int(settings.get("batch_size", 1)))
        self.seq_spin.setValue(int(settings.get("max_seq_len", 1024)))
        mode = (p.get("metamorph") or {}).get("mode", "morph")
        idx = self.metamorph_combo.findText(mode)
        self.metamorph_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.notes_edit.setPlainText(notes)

    def save(self) -> bool:
        """Save the project form. Returns True on success, False when
        nothing was saved (bad learning rate, store error)."""
        try:
            lr = float(self.lr_edit.text().strip() or "0.0002")
        except ValueError:
            QMessageBox.warning(
                self, "Stella", "Learning rate must be a number, like 0.0002."
            )
            return False
        try:
            self._main.store.update_project(
                self._profile,
                self._project,
                display_name=self.display_edit.text().strip(),
                dataset_ref=self.dataset_edit.text().strip(),
                settings={
                    "method": self.method_combo.currentText(),
                    "rank": self.rank_spin.value(),
                    "learning_rate": lr,
                    "epochs": self.epochs_spin.value(),
                    "batch_size": self.batch_spin.value(),
                    "max_seq_len": self.seq_spin.value(),
                },
                metamorph={"mode": self.metamorph_combo.currentText()},
            )
            self._main.store.write_notes(
                self._profile,
                self._project,
                self.notes_edit.toPlainText(),
            )
        except StellaError as exc:
            QMessageBox.warning(self, "Stella", str(exc))
            return False
        self._main.refresh_tree()
        self._main.refresh_session()
        self._main._say(f"Saved project {self._project}.")
        return True


class SettingsWindow(QDialog):
    """Settings, in its own window. Only settings that exist are
    shown: where Stella keeps its files, whether Ollama is answering,
    and the defaults new projects start with. Nothing invented."""

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Where Stella keeps things"))
        self.home_label = QLabel(str(main.store.home))
        self.home_label.setWordWrap(True)
        self.home_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.home_label)
        layout.addWidget(
            _help_label("Your profiles and projects live here.")
        )

        layout.addWidget(QLabel("Ollama"))
        self.ollama_host = QLabel(f"Host: {ollama_url()}")
        self.ollama_host.setWordWrap(True)
        layout.addWidget(self.ollama_host)
        self.ollama_status = QLabel("")
        self.ollama_status.setWordWrap(True)
        layout.addWidget(self.ollama_status)
        refresh_btn = QPushButton("Refresh Ollama status")
        refresh_btn.clicked.connect(self.refresh_ollama_status)
        layout.addWidget(refresh_btn)
        layout.addWidget(
            _help_label(
                "Ollama runs the models on this PC. Stella uses it for "
                "dreaming and the refusal probe, not for training."
            )
        )

        layout.addWidget(QLabel("Training defaults"))
        form = QFormLayout()
        form.addRow("LoRA rank", QLabel(str(DEFAULT_SETTINGS["rank"])))
        form.addRow(
            "Learning rate", QLabel(str(DEFAULT_SETTINGS["learning_rate"]))
        )
        form.addRow("Epochs", QLabel(str(DEFAULT_SETTINGS["epochs"])))
        form.addRow("Batch size", QLabel(str(DEFAULT_SETTINGS["batch_size"])))
        form.addRow(
            "Max seq len", QLabel(str(DEFAULT_SETTINGS["max_seq_len"]))
        )
        layout.addLayout(form)
        layout.addWidget(
            _help_label(
                "New projects start with these. Change them per project "
                "in the project window."
            )
        )

        layout.addWidget(QLabel("Chat model"))
        self.chat_combo = QComboBox()
        self.chat_combo.setPlaceholderText("Pick a model for chat")
        self.chat_combo.currentTextChanged.connect(self._on_chat_model_changed)
        layout.addWidget(self.chat_combo)
        layout.addWidget(
            _help_label(
                "The model the Chat window talks to. It runs on your PC "
                "through Ollama. A bigger model answers better but "
                "slower. Nothing is picked until you pick one."
            )
        )
        self._load_chat_models()

        layout.addWidget(QLabel("Debug report"))
        self.debug_btn = QPushButton("Write debug report")
        self.debug_btn.clicked.connect(self._on_debug_report)
        layout.addWidget(self.debug_btn)
        layout.addWidget(
            _help_label(
                "Writes a report file with the recent log and the app "
                "state. Secrets are scrubbed out."
            )
        )

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        layout.addStretch(1)

        self.refresh_ollama_status()

    def refresh_ollama_status(self):
        self.ollama_status.setText(f"Status: {check_ollama(ollama_url())}")
        self._load_chat_models()

    def _load_chat_models(self):
        """Fill the chat-model list from Ollama. Nothing is selected
        by default: the saved pick is restored, or the box stays
        blank until the user picks one."""
        saved = self._main.chat_model
        self.chat_combo.blockSignals(True)
        try:
            self.chat_combo.clear()
            models = list_models()
            if models:
                self.chat_combo.addItems(models)
            if saved and saved in models:
                self.chat_combo.setCurrentText(saved)
            else:
                self.chat_combo.setCurrentIndex(-1)
        finally:
            self.chat_combo.blockSignals(False)

    def _on_chat_model_changed(self, text):
        if text:
            self._main.set_chat_model(text)

    def _on_debug_report(self):
        try:
            path = self._main.debug_log.generate_report()
        except Exception as exc:  # noqa: BLE001 - show it, don't crash
            QMessageBox.warning(
                self, "Stella", f"Could not write the debug report: {exc}"
            )
            return
        QMessageBox.information(
            self, "Stella", f"Debug report written to:\n{path}"
        )


class HowToUseWindow(QDialog):
    """The built-in guide: topics on the left, plain-words content
    on the right. Nothing is selected at first: pick a topic."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How to Use Stella")
        self.resize(900, 600)
        layout = QHBoxLayout(self)
        self.topic_list = QListWidget()
        self.topic_list.addItems(topic_titles())
        self.topic_list.currentItemChanged.connect(self._on_topic)
        layout.addWidget(self.topic_list, 1)
        self.content = QTextBrowser()
        self.content.setPlainText(
            "Pick a topic on the left to read how it works."
        )
        layout.addWidget(self.content, 2)

    def _on_topic(self, current, _previous):
        if current is None:
            return
        text = topic_text(current.text())
        if text is not None:
            self.content.setPlainText(text)


class ChatWorker(QThread):
    """Runs one ChatAgent.reply off the GUI thread. The agent talks
    to Ollama (up to 120 s per call) and may start training, so it
    must never run on the UI thread. Only talks to the window
    through signals."""

    narration = Signal(str)
    progress = Signal(str)
    reply = Signal(str)

    def __init__(self, agent, text, parent=None):
        super().__init__(parent)
        self._agent = agent
        self._text = text

    def request_stop(self):
        self._agent.request_cancel()

    def run(self):
        self._agent.set_callbacks(
            on_narration=self.narration.emit,
            on_progress=self.progress.emit,
        )
        try:
            answer = self._agent.reply(self._text)
        except Exception as exc:  # keep the window alive on a crash
            answer = f"The chat hit a problem: {exc}"
        self.reply.emit(answer)


class ChatWindow(QDialog):
    """Talk to Stella instead of filling in forms.

    One window, one chat: the user types what they want ("train LFM3
    to write short replies"), the chat agent asks only for what it
    needs and does the rest. The agent runs in a worker thread; the
    window only shows messages and sends input.

    The chat model comes from Settings (chat/model). If none is
    picked yet, the window asks the user which installed model to
    use instead of failing: the first message just names the model.
    """

    def __init__(self, main, parent=None, agent_factory=None):
        super().__init__(parent)
        self._main = main
        self._agent_factory = agent_factory
        self._agent = None
        self._worker: ChatWorker | None = None
        self._awaiting_model = False
        self.setWindowTitle("Chat with Stella")
        self.resize(700, 520)
        layout = QVBoxLayout(self)

        activity = QHBoxLayout()
        self.activity_dot = QLabel("\u25cf")
        self.activity_dot.setStyleSheet("color: #888888; font-size: 14px;")
        activity.addWidget(self.activity_dot)
        self.activity_text = QLabel("Idle")
        activity.addWidget(self.activity_text, 1)
        layout.addLayout(activity)

        self.messages = QTextBrowser()
        self.messages.setReadOnly(True)
        layout.addWidget(self.messages, 1)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Say what you want, for example: train LFM3 to write short replies"
        )
        self.input.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input, 1)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.send_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        input_row.addWidget(self.cancel_btn)
        layout.addLayout(input_row)
        layout.addWidget(
            _help_label(
                "The chat talks to a model on your PC through Ollama. "
                "It can set up and run training for you. Say just do "
                "it and it runs the whole thing."
            )
        )
        self._append(
            "Stella",
            "Hi. Tell me what you want to train, and I will set it up "
            "and run it for you. Or say just do it and I will run the "
            "whole thing with the usual settings.",
        )
        if not self._main.chat_model:
            self._ask_for_model()

    # -- messages ---------------------------------------------------
    def _append(self, who: str, text: str):
        self.messages.append(f"{who}: {text}")
        self.messages.append("")

    def _append_plain(self, text: str):
        self.messages.append(text)

    def _set_activity(self, busy: bool, text: str):
        color = "#4caf50" if busy else "#888888"
        self.activity_dot.setStyleSheet(
            f"color: {color}; font-size: 14px;"
        )
        self.activity_text.setText(text)

    # -- chat model -------------------------------------------------
    def _ask_for_model(self):
        models = list_models()
        if not models:
            self._append(
                "Stella",
                "Ollama is not answering, so I cannot see which models "
                "are installed. Start Ollama, then pick a chat model in "
                "Settings.",
            )
            return
        self._awaiting_model = True
        self._append(
            "Stella",
            "Which model should I chat with? Type one of these:\n"
            + "\n".join(f"- {name}" for name in models),
        )

    def _match_model(self, text: str) -> str | None:
        """The user's reply, matched against the installed models."""
        models = list_models()
        cleaned = text.strip().lower()
        for name in models:
            if cleaned == name.lower():
                return name
        hits = [name for name in models if cleaned in name.lower()]
        if len(hits) == 1:
            return hits[0]
        return None

    # -- sending ----------------------------------------------------
    def _make_agent(self):
        if self._agent_factory is not None:
            return self._agent_factory()
        return ChatAgent(
            self._main.store,
            self._main.chat_model,
            profile=self._main._current_profile,
            project=self._main._current_project,
        )

    def _ensure_agent(self):
        if self._agent is None:
            self._agent = self._make_agent()
        return self._agent

    def _on_send(self):
        text = self.input.text().strip()
        if not text:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.input.clear()
        self._append("You", text)
        # No chat model yet: this message names the model.
        if not self._main.chat_model:
            if not self._awaiting_model:
                self._ask_for_model()
                return
            match = self._match_model(text)
            if match is None:
                self._append(
                    "Stella",
                    "I did not find that model. Type one of the names "
                    "from the list above.",
                )
                return
            self._awaiting_model = False
            self._main.set_chat_model(match)
            self._append(
                "Stella",
                f"Got it, I will chat with {match}. What do you want "
                "to train?",
            )
            return
        agent = self._ensure_agent()
        agent.set_model(self._main.chat_model)
        # Follow the main window's session when it has one: clicking
        # a project in the tree steers the chat too.
        if self._main._current_profile:
            agent.current_profile = self._main._current_profile
            agent.current_project = self._main._current_project
        self._worker = ChatWorker(agent, text, parent=self)
        self._worker.narration.connect(self._append_plain)
        self._worker.progress.connect(self._append_plain)
        self._worker.reply.connect(self._on_reply)
        self.send_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._set_activity(True, "Thinking...")
        self._worker.start()

    def _on_reply(self, text: str):
        self._append("Stella", text)
        self.send_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._set_activity(False, "Idle")
        self._worker = None
        # Tools may have made profiles or projects: the tree and the
        # session follow the chat's session.
        if self._agent is not None and self._agent.current_profile:
            self._main.set_session(
                self._agent.current_profile, self._agent.current_project
            )
        else:
            self._main.refresh_tree()
            self._main.refresh_session()

    def _on_cancel(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self.cancel_btn.setEnabled(False)
            self._set_activity(True, "Stopping...")

    def stop_worker(self):
        """Cancel any running reply and wait for it (close path)."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(15000)

    def closeEvent(self, event):
        self.stop_worker()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, store: Store | None = None, settings=None):
        super().__init__()
        self.store = store or Store()
        # Tests pass a QSettings on a temp file; the real app uses
        # the shared BrokeNBored/Stella settings.
        self.settings = settings or QSettings("BrokeNBored", "Stella")
        self.setWindowTitle(
            f"STELLA {STELLA_VERSION}: fine-tune models on your PC"
        )
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "stella.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1100, 680)
        self.setMinimumSize(900, 540)
        self._current_profile: str | None = None
        self._current_project: str | None = None
        self._train_panel_project: tuple | None = None
        self._building = False
        self._train_worker: TrainWorker | None = None
        self._sleep_worker: SleepWorker | None = None
        self._job_worker: JobWorker | None = None
        self._profile_windows: dict[str, ProfileWindow] = {}
        self._project_windows: dict[tuple, ProjectWindow] = {}
        self._settings_window: SettingsWindow | None = None
        self._howto_window: HowToUseWindow | None = None
        self._chat_window: ChatWindow | None = None
        self._tree_profiles: dict[str, QTreeWidgetItem] = {}
        self._tree_projects: dict[tuple, QTreeWidgetItem] = {}
        self._download_profile: str | None = None

        # Debug log layer (U12): rotating log under the Stella home,
        # ring buffer, scrubbed report on demand from Settings.
        self.debug_log = DebugLogger(
            "stella", STELLA_VERSION, log_dir=str(self.store.home / "logs")
        )
        self.debug_log.set_setting("home", str(self.store.home))
        self.debug_log.register_service(
            "ollama", lambda: check_ollama(ollama_url())
        )
        for dep in (
            "PySide6",
            "torch",
            "transformers",
            "peft",
            "huggingface_hub",
        ):
            self.debug_log.register_dependency(dep)

        self.download_manager = DownloadManager(self)
        self.download_manager.progress.connect(self._on_download_progress)
        self.download_manager.finished.connect(self._on_download_finished)

        self._build_ui()
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("splitter")
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)
        self.refresh_tree()
        # Restore the last session (the user's own pick, not a
        # default) and the tree expansion, if they still exist.
        expanded = self.settings.value("tree/expanded", [])
        if isinstance(expanded, str):
            expanded = [expanded]
        for slug in expanded or []:
            item = self._tree_profiles.get(slug)
            if item is not None:
                item.setExpanded(True)
        saved_profile = self.settings.value("session/profile") or None
        saved_project = self.settings.value("session/project") or None
        if saved_profile and saved_profile in self._tree_profiles:
            if saved_project and (saved_profile, saved_project) in (
                self._tree_projects
            ):
                self.set_session(saved_profile, saved_project)
            else:
                self.set_session(saved_profile, None)
        else:
            self.refresh_session()

    # -- layout -----------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        header_row = QHBoxLayout()
        self.menu_button = QPushButton("Menu")
        self.menu_button.setMenu(self._build_menu())
        header_row.addWidget(self.menu_button)
        header = QLabel("STELLA: shape a base model into its proper job")
        header.setStyleSheet("font-size: 16px; font-weight: bold; padding: 6px 2px;")
        header_row.addWidget(header, 1)
        # Activity indicator (U16): a light plus small status text,
        # so the user never wonders whether anything is happening.
        self.activity_dot = QLabel("\u25cf")
        self.activity_dot.setStyleSheet("color: #888888; font-size: 16px;")
        header_row.addWidget(self.activity_dot)
        self.activity_text = QLabel("Idle")
        header_row.addWidget(self.activity_text)
        outer.addLayout(header_row)

        self.splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(self.splitter, 1)

        # Left panel: the collapsible profile menu.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Profiles"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.currentItemChanged.connect(self._on_tree_current_changed)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_clicked)
        left_layout.addWidget(self.tree, 1)
        self.splitter.addWidget(left)

        # Main area: the current training session (scrollable).
        self.session_scroll = QScrollArea()
        self.session_scroll.setWidgetResizable(True)
        session = QWidget()
        self.session_layout = QVBoxLayout(session)
        self.session_scroll.setWidget(session)
        self._build_session()
        self.splitter.addWidget(self.session_scroll)
        self.splitter.setSizes([260, 840])
        self.statusBar().showMessage("Stella ready.")

    def _build_menu(self):
        menu = QMenu(self)
        self.menu = menu
        self._menu_action_profiles = menu.addAction(
            "Profiles", self.open_current_profile_window
        )
        self._menu_action_new_profile = menu.addAction(
            "New profile...", self.new_profile
        )
        menu.addSeparator()
        self._menu_action_projects = menu.addAction(
            "Projects", self.open_current_project_window
        )
        self._menu_action_new_project = menu.addAction(
            "New project...", self.new_project
        )
        menu.addSeparator()
        self._menu_action_export = menu.addAction(
            "Export project...", self.export_project
        )
        self._menu_action_import = menu.addAction(
            "Import package...", self.import_package
        )
        menu.addSeparator()
        self._menu_action_settings = menu.addAction(
            "Settings...", self.open_settings_window
        )
        self._menu_action_howto = menu.addAction(
            "How to Use Stella...", self.open_howto_window
        )
        self._menu_action_chat = menu.addAction(
            "Chat...", self.open_chat_window
        )
        return menu

    def _build_session(self):
        self.session_title = QLabel("No training session yet.")
        self.session_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.session_layout.addWidget(self.session_title)
        self.session_summary = QLabel("")
        self.session_summary.setWordWrap(True)
        self.session_layout.addWidget(self.session_summary)

        # Model download row.
        self.session_layout.addWidget(QLabel("Model weights"))
        self.download_status_label = QLabel("")
        self.download_status_label.setWordWrap(True)
        self.session_layout.addWidget(self.download_status_label)
        self.download_progress = QProgressBar()
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(0)
        self.session_layout.addWidget(self.download_progress)
        dl_btns = QHBoxLayout()
        self.download_btn = QPushButton("Download model")
        self.download_btn.clicked.connect(
            lambda: self.start_download(self._current_profile)
        )
        self.download_cancel_btn = QPushButton("Cancel")
        self.download_cancel_btn.clicked.connect(self.cancel_download)
        self.download_cancel_btn.setEnabled(False)
        dl_btns.addWidget(self.download_btn)
        dl_btns.addWidget(self.download_cancel_btn)
        dl_btns.addStretch(1)
        self.session_layout.addLayout(dl_btns)
        self.session_layout.addWidget(
            _help_label(
                "Downloads the base weights from Hugging Face. If it "
                "stops, press Download again: it picks up where it left "
                "off, nothing is downloaded twice."
            )
        )

        # Train panel: dataset, Start / Pause / Resume, progress,
        # checkpoints, GGUF export, refusal probe, log.
        self.session_layout.addWidget(QLabel("Train"))
        dataset_btns = QHBoxLayout()
        self.train_pick_dataset_btn = QPushButton("Pick dataset file")
        self.train_pick_dataset_btn.clicked.connect(self.pick_dataset)
        self.train_sample_btn = QPushButton("Use sample dataset")
        self.train_sample_btn.clicked.connect(self.use_sample_dataset)
        dataset_btns.addWidget(self.train_pick_dataset_btn)
        dataset_btns.addWidget(self.train_sample_btn)
        self.session_layout.addLayout(dataset_btns)
        train_btns = QHBoxLayout()
        self.train_start_btn = QPushButton("Start training")
        self.train_start_btn.clicked.connect(
            lambda: self.start_training(resume=False)
        )
        self.train_pause_btn = QPushButton("Pause")
        self.train_pause_btn.clicked.connect(self.pause_training)
        self.train_pause_btn.setEnabled(False)
        self.train_resume_btn = QPushButton("Resume")
        self.train_resume_btn.clicked.connect(
            lambda: self.start_training(resume=True)
        )
        train_btns.addWidget(self.train_start_btn)
        train_btns.addWidget(self.train_pause_btn)
        train_btns.addWidget(self.train_resume_btn)
        self.session_layout.addLayout(train_btns)
        self.train_progress = QProgressBar()
        self.train_progress.setValue(0)
        self.session_layout.addWidget(self.train_progress)
        self.train_loss = QLabel("Not started.")
        self.session_layout.addWidget(self.train_loss)
        self.session_layout.addWidget(QLabel("Checkpoints"))
        self.train_checkpoints = QListWidget()
        self.train_checkpoints.setMaximumHeight(90)
        self.session_layout.addWidget(self.train_checkpoints)
        export_btns = QHBoxLayout()
        self.train_export_gguf_btn = QPushButton("Export GGUF")
        self.train_export_gguf_btn.clicked.connect(self.export_gguf_gui)
        self.train_probe_btn = QPushButton("Run refusal probe")
        self.train_probe_btn.clicked.connect(self.run_probe_gui)
        export_btns.addWidget(self.train_export_gguf_btn)
        export_btns.addWidget(self.train_probe_btn)
        self.session_layout.addLayout(export_btns)
        self.session_layout.addWidget(QLabel("Training log"))
        self.train_log = QPlainTextEdit()
        self.train_log.setReadOnly(True)
        self.train_log.setMinimumHeight(120)
        self.session_layout.addWidget(self.train_log)

        # Sleep panel: run a sleep cycle, dream synthetic rows
        # first, and see every cycle's replay verdict.
        self.session_layout.addWidget(QLabel("Sleep"))
        sleep_btns = QHBoxLayout()
        self.sleep_btn = QPushButton("Sleep")
        self.sleep_btn.clicked.connect(self.start_sleep)
        self.sleep_dream_check = QCheckBox("Dream first")
        self.sleep_dream_check.setToolTip(
            "Dream synthetic practice rows from the local Ollama model "
            "before consolidating (best effort: sleep still runs on "
            "real rows if Ollama is down)."
        )
        sleep_btns.addWidget(self.sleep_btn)
        sleep_btns.addWidget(self.sleep_dream_check)
        sleep_btns.addStretch(1)
        self.session_layout.addLayout(sleep_btns)
        self.session_layout.addWidget(
            QLabel("Sleep cycles (click one to see its report)")
        )
        self.sleep_cycles = QListWidget()
        self.sleep_cycles.setMaximumHeight(90)
        self.sleep_cycles.itemClicked.connect(self._on_sleep_cycle_clicked)
        self.session_layout.addWidget(self.sleep_cycles)
        self.session_layout.addStretch(1)

    # -- helpers ----------------------------------------------------
    def _say(self, text: str):
        # Single status surface: the window status bar. (An earlier
        # duplicate QLabel in the bottom bar showed the same text
        # twice — removed, see test_status_bar_is_the_only_status.)
        self.statusBar().showMessage(text)

    def _warn(self, text: str):
        QMessageBox.warning(self, "Stella", text)

    def _set_activity(self, state: str, text: str):
        """The activity light + text (U16). States: idle,
        downloading, training, sleep, job."""
        colors = {
            "idle": "#888888",
            "downloading": "#e8a90c",
            "training": "#4caf50",
            "sleep": "#4caf50",
            "job": "#e8a90c",
        }
        self.activity_dot.setStyleSheet(
            f"color: {colors.get(state, '#888888')}; font-size: 16px;"
        )
        self.activity_text.setText(text)

    def _selected_profile(self) -> str | None:
        return self._current_profile

    def _selected_project(self) -> str | None:
        return self._current_project

    @property
    def download_profile(self) -> str | None:
        """The profile whose weights are downloading, if any."""
        return self._download_profile


    # -- tree -------------------------------------------------------
    @staticmethod
    def _profile_label(p):
        label = p.get("display_name") or p["name"]
        role = p.get("role") or ""
        tag = p.get("ollama_tag") or p.get("base_ref") or ""
        if role:
            label += f" [{role}]"
        if tag:
            label += f" ({tag})"
        return label

    @staticmethod
    def _project_label(p):
        label = p.get("display_name") or p["name"]
        mode = (p.get("metamorph") or {}).get("mode", "morph")
        return f"{label} ({mode})"

    def refresh_tree(self):
        """Sync the tree with the store WITHOUT rebuilding it (U28):
        add missing rows, remove stale ones, relabel in place.
        Expansion, scroll position, and selection survive."""
        expanded = {
            slug for slug, item in self._tree_profiles.items()
            if item.isExpanded()
        }
        vbar = self.tree.verticalScrollBar()
        scroll = vbar.value() if vbar is not None else 0
        profiles = {p["name"]: p for p in self.store.list_profiles()}
        for slug in list(self._tree_profiles):
            if slug not in profiles:
                item = self._tree_profiles.pop(slug)
                for key in list(self._tree_projects):
                    if key[0] == slug:
                        del self._tree_projects[key]
                self.tree.takeTopLevelItem(
                    self.tree.indexOfTopLevelItem(item)
                )
        for slug, p in profiles.items():
            item = self._tree_profiles.get(slug)
            if item is None:
                item = QTreeWidgetItem(self.tree, [self._profile_label(p)])
                item.setData(0, Qt.UserRole, (slug, None))
                self._tree_profiles[slug] = item
            else:
                item.setText(0, self._profile_label(p))
            projects = {
                pr["name"]: pr for pr in self.store.list_projects(slug)
            }
            for key in list(self._tree_projects):
                if key[0] == slug and key[1] not in projects:
                    item.removeChild(self._tree_projects.pop(key))
            for pname, pr in projects.items():
                key = (slug, pname)
                child = self._tree_projects.get(key)
                if child is None:
                    child = QTreeWidgetItem(item, [self._project_label(pr)])
                    child.setData(0, Qt.UserRole, key)
                    self._tree_projects[key] = child
                else:
                    child.setText(0, self._project_label(pr))
        self.tree.sortItems(0, Qt.AscendingOrder)
        for slug, item in self._tree_profiles.items():
            item.setExpanded(slug in expanded)
        if vbar is not None:
            vbar.setValue(scroll)
        self._sync_tree_selection()

    def _sync_tree_selection(self):
        """Select the tree row matching the current session (or
        nothing, when there is no session). Guarded so the program
        move does not re-enter set_session."""
        self._building = True
        try:
            if self._current_profile and self._current_project:
                item = self._tree_projects.get(
                    (self._current_profile, self._current_project)
                )
            elif self._current_profile:
                item = self._tree_profiles.get(self._current_profile)
            else:
                item = None
            if item is not None:
                self.tree.setCurrentItem(item)
            else:
                self.tree.setCurrentItem(None)
        finally:
            self._building = False

    def _on_tree_current_changed(self, current, _previous):
        if self._building or current is None:
            return
        data = current.data(0, Qt.UserRole)
        if data is None:
            return
        profile, project = data
        self.set_session(profile, project)

    def _on_tree_double_clicked(self, item, _column):
        data = item.data(0, Qt.UserRole)
        if data is None:
            return
        profile, project = data
        if project is None:
            self.open_profile_window(profile)
        else:
            self.open_project_window(profile, project)

    # -- session ----------------------------------------------------
    def set_session(self, profile, project):
        """Clicking a project in the tree sets the training session.
        The session is remembered across restarts (QSettings)."""
        self._current_profile = profile
        self._current_project = project
        self.settings.setValue("session/profile", profile or "")
        self.settings.setValue("session/project", project or "")
        self.refresh_tree()
        self.refresh_session()

    def refresh_session(self):
        """The main area follows the current session."""
        has_profile = bool(self._current_profile)
        has_session = bool(self._current_profile and self._current_project)
        if has_session:
            try:
                prof = self.store.get_profile(self._current_profile)
                proj = self.store.get_project(
                    self._current_profile, self._current_project
                )
            except StellaError as exc:
                self._say(str(exc))
                return
            self.session_title.setText(
                f"{prof.get('display_name') or self._current_profile} / "
                f"{proj.get('display_name') or self._current_project}"
            )
            settings = proj.get("settings", {})
            model = (
                prof.get("ollama_tag") or prof.get("base_ref") or "not set"
            )
            dataset = proj.get("dataset_ref") or "not set yet"
            self.session_summary.setText(
                f"Model: {model}\n"
                f"Dataset: {dataset}\n"
                f"LoRA rank {settings.get('rank', 8)}, learning rate "
                f"{settings.get('learning_rate', 0.0002)}, "
                f"{settings.get('epochs', 3)} epochs. "
                f"Status: {proj.get('status', 'draft')}."
            )
            self._say(
                f"Profile: {self._current_profile}, "
                f"project: {self._current_project}."
            )
        elif has_profile:
            try:
                prof = self.store.get_profile(self._current_profile)
                name = prof.get("display_name") or self._current_profile
            except StellaError:
                name = self._current_profile
            self.session_title.setText(name)
            self.session_summary.setText(
                "Pick a project on the left to set the training session, "
                "or make one from the menu: New project."
            )
            self._say(f"Profile: {self._current_profile}, no project yet.")
        else:
            self.session_title.setText("No training session yet.")
            self.session_summary.setText(
                "Pick a project in the list on the left. That sets the "
                "training session: the model and the fine-tune you are "
                "working on."
            )
            self._say("Pick a profile to begin.")
        for w in (
            self.train_pick_dataset_btn,
            self.train_sample_btn,
            self.train_start_btn,
            self.train_resume_btn,
            self.sleep_btn,
            self.train_export_gguf_btn,
            self.train_probe_btn,
        ):
            w.setEnabled(has_session)
        self.download_btn.setEnabled(
            has_profile and not self.download_manager.is_running()
        )
        self.download_cancel_btn.setEnabled(
            self.download_manager.is_running()
        )
        self._refresh_download_row()
        self.refresh_train_panel()

    def _refresh_download_row(self):
        if not self._current_profile:
            self.download_status_label.setText("Pick a profile first.")
            self.download_progress.setMaximum(100)
            self.download_progress.setValue(0)
            return
        try:
            status = provision.weights_status(
                self.store, self._current_profile
            )
        except StellaError:
            self.download_status_label.setText("Profile not found.")
            return
        if self.download_manager.is_running():
            return  # progress updates own the label while downloading
        self.download_status_label.setText(_weights_label(status))
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(
            100 if status["state"] == "ready" else 0
        )

    # -- downloads --------------------------------------------------
    def start_download(self, profile=None):
        slug = profile or self._current_profile
        if not slug:
            self._warn("Pick a profile first.")
            return
        if self.download_manager.is_running():
            self._say("A download is already running.")
            return
        try:
            status = provision.weights_status(self.store, slug)
        except StellaError as exc:
            self._warn(str(exc))
            return
        if status["state"] == "ready":
            self._say("Model already downloaded.")
            self._refresh_download_row()
            return
        if status["state"] == "no-repo":
            self._warn(
                "No Hugging Face repo set for this profile. Open the "
                "profile and set Base ref to a repo like "
                "LiquidAI/LFM3-1.7B."
            )
            return
        if not provision.hub_available():
            self._warn(
                "The download tool is not installed. Run this once in "
                "the Stella folder: bash install-training.sh"
            )
            return
        repo = status["repo"]
        self._download_profile = slug
        self.download_manager.start(repo)
        self._set_activity("downloading", "Downloading model: 0%")
        self.download_btn.setEnabled(False)
        self.download_cancel_btn.setEnabled(True)
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(0)
        self.download_status_label.setText("Downloading: 0%")
        win = self._profile_windows.get(slug)
        if win is not None:
            win.refresh_download_status()
        self._say(f"Downloading {repo}...")
        self.debug_log.action(f"download started: {repo} ({slug})")

    def cancel_download(self):
        self.download_manager.cancel()

    def _on_download_progress(self, downloaded, total):
        if total > 0:
            pct = downloaded * 100 // total
            self.download_progress.setMaximum(100)
            self.download_progress.setValue(pct)
            self._set_activity("downloading", f"Downloading model: {pct}%")
            self.download_status_label.setText(
                f"Downloading: {pct}% "
                f"({provision.format_size(downloaded)} of "
                f"{provision.format_size(total)})"
            )
        else:
            self.download_progress.setMaximum(0)
            self._set_activity("downloading", "Downloading model...")
            self.download_status_label.setText(
                "Downloading: "
                f"{provision.format_size(downloaded)} so far"
            )
        win = (
            self._profile_windows.get(self._download_profile)
            if self._download_profile
            else None
        )
        if win is not None:
            win.on_download_progress(downloaded, total)

    def _on_download_finished(self, ok, message):
        slug = self._download_profile
        self._download_profile = None
        self._set_activity("idle", "Idle")
        self.download_btn.setEnabled(bool(self._current_profile))
        self.download_cancel_btn.setEnabled(False)
        self.download_progress.setMaximum(100)
        if ok:
            self.download_progress.setValue(100)
            self._say("Model ready.")
            self.debug_log.action(f"download finished: {slug}")
        else:
            self.download_progress.setValue(0)
            if self.download_manager.was_cancelled():
                self._say(
                    "Download stopped. It will pick up where it left off."
                )
            else:
                self._say("Download failed.")
                self._warn(message)
                self.debug_log.action(f"download failed: {slug}: {message}")
        self._refresh_download_row()
        if slug:
            win = self._profile_windows.get(slug)
            if win is not None:
                win.refresh_download_status()

    def _weights_offer(self, profile) -> bool:
        """True when training may start. When the weights are
        missing, offer the download first instead of failing
        cryptically in the training thread."""
        try:
            status = provision.weights_status(self.store, profile)
        except StellaError as exc:
            self._warn(str(exc))
            return False
        if status["state"] == "ready":
            return True
        if status["state"] == "no-repo":
            self._warn(
                "This profile has no Hugging Face repo set. Open the "
                "profile and set Base ref to a repo like "
                "LiquidAI/LFM3-1.7B, then download the model."
            )
            return False
        answer = QMessageBox.question(
            self,
            "Download the model first?",
            "The base weights for this profile are not downloaded yet "
            f"({_weights_label(status).lower()}). Download them now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.start_download(profile)
        return False

    # -- dedicated windows ------------------------------------------
    def open_profile_window(self, slug=None):
        slug = slug or self._current_profile
        if not slug:
            self._warn("Pick a profile first.")
            return None
        win = self._profile_windows.get(slug)
        if win is None:
            win = ProfileWindow(self, slug, parent=self)
            win.destroyed.connect(
                lambda _obj, s=slug: self._profile_windows.pop(s, None)
            )
            self._profile_windows[slug] = win
        win.show()
        win.raise_()
        win.activateWindow()
        return win

    def open_current_profile_window(self):
        self.open_profile_window()

    def open_project_window(self, profile=None, project=None):
        profile = profile or self._current_profile
        project = project or self._current_project
        if not profile or not project:
            self._warn("Pick a project first.")
            return None
        key = (profile, project)
        win = self._project_windows.get(key)
        if win is None:
            win = ProjectWindow(self, profile, project, parent=self)
            win.destroyed.connect(
                lambda _obj, k=key: self._project_windows.pop(k, None)
            )
            self._project_windows[key] = win
        win.show()
        win.raise_()
        win.activateWindow()
        return win

    def open_current_project_window(self):
        self.open_project_window()

    def open_settings_window(self):
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self, parent=self)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()
        return self._settings_window

    def open_howto_window(self):
        if self._howto_window is None:
            self._howto_window = HowToUseWindow(parent=self)
        self._howto_window.show()
        self._howto_window.raise_()
        self._howto_window.activateWindow()
        return self._howto_window

    @property
    def chat_model(self) -> str:
        """The chat model the user picked in Settings, or ""."""
        return self.settings.value("chat/model", "") or ""

    def set_chat_model(self, tag: str):
        self.settings.setValue("chat/model", tag)

    def open_chat_window(self):
        if self._chat_window is None:
            self._chat_window = ChatWindow(self, parent=self)
        self._chat_window.show()
        self._chat_window.raise_()
        self._chat_window.activateWindow()
        return self._chat_window

    # -- profile actions --------------------------------------------
    def new_profile(self):
        dialog = NewProfileDialog(self)
        dialog.create_btn.clicked.connect(lambda: self._create_profile_from(dialog))
        dialog.cancel_btn.clicked.connect(dialog.reject)
        dialog.resize(460, 200)
        center = self.geometry().center()
        dialog.move(center.x() - dialog.width() // 2,
                    center.y() - dialog.height() // 2)
        dialog.exec()
        self._profile_dialog = dialog

    def _create_profile_from(self, dialog: NewProfileDialog):
        model = dialog.model_combo.currentText().strip()
        if not model:
            self._warn("Pick a model first.")
            return
        # An installed model — or a bare tag — is an Ollama tag; a
        # namespaced id that isn't installed is a Hugging Face repo.
        if model in dialog.installed_models or "/" not in model:
            tag, ref = model, ""
        else:
            tag, ref = "", model
        slug = slug_from_model(model)
        base = slug
        i = 2
        while (self.store.profile_dir(slug) / "profile.json").exists():
            slug = f"{base}-{i}"
            i += 1
        try:
            self.store.create_profile(slug, ollama_tag=tag, base_ref=ref)
        except StellaError as exc:
            self._warn(str(exc))
            return
        dialog.accept()
        self.debug_log.action(f"profile created: {slug} (from {model})")
        self.set_session(slug, None)
        self._say(f"Created profile {slug}.")

    def rename_profile(self, slug=None):
        slug = slug or self._current_profile
        if not slug:
            return
        text, ok = QInputDialog.getText(self, "Rename profile", "New name:", text=slug)
        if not ok or not text.strip():
            return
        try:
            data = self.store.rename_profile(slug, text.strip())
        except StellaError as exc:
            self._warn(str(exc))
            return
        new = data["name"]
        win = self._profile_windows.pop(slug, None)
        if win is not None:
            win.retarget(new)
            self._profile_windows[new] = win
        for key in list(self._project_windows):
            if key[0] == slug:
                proj_win = self._project_windows.pop(key)
                proj_win.retarget_profile(new)
                self._project_windows[(new, key[1])] = proj_win
        if self._current_profile == slug:
            self.set_session(new, self._current_project)
        else:
            self.refresh_tree()

    def _delete_confirm(self, title, text):
        """A destructive confirmation that defaults to No, and where
        Escape leaves things untouched (U23/U31)."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Warning)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setEscapeButton(QMessageBox.No)
        return box.exec()

    def delete_profile(self, slug=None):
        slug = slug or self._current_profile
        if not slug:
            return
        answer = self._delete_confirm(
            "Delete profile",
            f"Delete profile {slug!r} and all its projects? This cannot be undone.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.store.delete_profile(slug)
        except StellaError as exc:
            self._warn(str(exc))
            return
        win = self._profile_windows.pop(slug, None)
        if win is not None:
            win.close()
        for key in list(self._project_windows):
            if key[0] == slug:
                self._project_windows.pop(key).close()
        self.debug_log.action(f"profile deleted: {slug}")
        if self._current_profile == slug:
            self.set_session(None, None)
        else:
            self.refresh_tree()

    # -- project actions --------------------------------------------
    def new_project(self):
        profile = self._selected_profile()
        if not profile:
            self._warn("Pick a profile first, then add a project to it.")
            return
        text, ok = QInputDialog.getText(
            self, "New project", "Project name (lowercase, dashes ok):"
        )
        if not ok or not text.strip():
            return
        try:
            self.store.create_project(profile, text.strip())
        except StellaError as exc:
            self._warn(str(exc))
            return
        self._current_project = text.strip().lower()
        self.debug_log.action(
            f"project created: {profile}/{self._current_project}"
        )
        self.set_session(profile, self._current_project)
        self._say(f"Created project {self._current_project}.")

    def rename_project(self, profile=None, project=None):
        profile = profile or self._selected_profile()
        project = project or self._selected_project()
        if not profile or not project:
            return
        text, ok = QInputDialog.getText(
            self, "Rename project", "New name:", text=project
        )
        if not ok or not text.strip():
            return
        try:
            data = self.store.rename_project(profile, project, text.strip())
        except StellaError as exc:
            self._warn(str(exc))
            return
        new = data["name"]
        win = self._project_windows.pop((profile, project), None)
        if win is not None:
            win.retarget(new)
            self._project_windows[(profile, new)] = win
        if (
            self._current_profile == profile
            and self._current_project == project
        ):
            self.set_session(profile, new)
        else:
            self.refresh_tree()

    def delete_project(self, profile=None, project=None):
        profile = profile or self._selected_profile()
        project = project or self._selected_project()
        if not profile or not project:
            return
        answer = self._delete_confirm(
            "Delete project",
            f"Delete project {project!r}? This cannot be undone.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.store.delete_project(profile, project)
        except StellaError as exc:
            self._warn(str(exc))
            return
        win = self._project_windows.pop((profile, project), None)
        if win is not None:
            win.close()
        self.debug_log.action(f"project deleted: {profile}/{project}")
        if (
            self._current_profile == profile
            and self._current_project == project
        ):
            self.set_session(profile, None)
        else:
            self.refresh_tree()

    # -- export / import --------------------------------------------
    def export_project(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to export.")
            return
        dest = QFileDialog.getExistingDirectory(
            self, "Export project to folder", str(Path.home())
        )
        if not dest:
            return
        try:
            out = export_mod.export_project(self.store, profile, project, dest)
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.debug_log.action(f"project exported: {profile}/{project} to {out}")
        self._say(f"Exported to {out}.")
        QMessageBox.information(self, "Stella", f"Exported project to:\n{out}")

    def import_package(self):
        path = QFileDialog.getExistingDirectory(
            self, "Pick an export package folder", str(Path.home())
        )
        if not path:
            return
        try:
            result = export_mod.import_export(self.store, path)
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.debug_log.action(
            f"project imported: {result['profile']}/{result['project']}"
        )
        self.set_session(result["profile"], result["project"])
        self._say(f"Imported {result['project']} into {result['profile']}.")

    # -- training ---------------------------------------------------
    def _train_log_line(self, text: str):
        self.train_log.appendPlainText(text)

    def _training_running(self) -> bool:
        return (
            self._train_worker is not None and self._train_worker.isRunning()
        )

    def _sleep_running(self) -> bool:
        return (
            self._sleep_worker is not None and self._sleep_worker.isRunning()
        )

    def refresh_train_panel(self):
        """Checkpoints list + log tail for the selected project."""
        self.train_checkpoints.clear()
        self.sleep_cycles.clear()
        if not self._current_profile or not self._current_project:
            self.train_loss.setText("Pick a project to train.")
            self._train_panel_project = None
            return
        # A new project gets a fresh loss line; the same project
        # keeps its last progress (a finished run's final step/loss
        # must survive the refresh that follows it).
        key = (self._current_profile, self._current_project)
        if self._train_panel_project != key:
            self._train_panel_project = key
            if not self._training_running() and not self._sleep_running():
                self.train_loss.setText("Not started.")
        from .train import list_checkpoints

        for ck in list_checkpoints(
            self.store, self._current_profile, self._current_project
        ):
            loss = ck.get("loss")
            label = f"step {ck['step']}"
            if loss is not None:
                label += f"  loss {loss:.4f}"
            self.train_checkpoints.addItem(label)
        from .sleep import list_sleep_cycles

        for c in list_sleep_cycles(
            self.store, self._current_profile, self._current_project
        ):
            before = c.get("old_loss_before")
            after = c.get("old_loss_after")
            delta = None
            if before is not None and after is not None and before > 0:
                delta = (after - before) / before
            delta_text = f"{delta:+.1%}" if delta is not None else "n/a"
            label = (
                f"cycle {c['cycle']}: {c['status']}, "
                f"{c['real_rows']} new, {c['dreamed_rows']} dreamed, "
                f"old-loss {delta_text}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, c["cycle"])
            self.sleep_cycles.addItem(item)
        if self._training_running():
            return  # never wipe the live log mid-run
        log_path = (
            self.store.project_dir(self._current_profile, self._current_project)
            / "train_log.jsonl"
        )
        if log_path.is_file():
            lines = log_path.read_text(encoding="utf-8").splitlines()[-30:]
            self.train_log.setPlainText("\n".join(lines))
        else:
            self.train_log.setPlainText("")

    def pick_dataset(self):
        if not self._current_profile or not self._current_project:
            self._warn("Pick a project first.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a dataset file", str(Path.home()),
            "JSONL datasets (*.jsonl);;All files (*)",
        )
        if not path:
            return
        try:
            self.store.update_project(
                self._current_profile, self._current_project,
                dataset_ref=path,
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.refresh_session()
        self._say(f"Dataset set to {path}.")

    def use_sample_dataset(self):
        if not self._current_profile or not self._current_project:
            self._warn("Pick a project first.")
            return
        try:
            self.store.update_project(
                self._current_profile, self._current_project,
                dataset_ref="sample-tool-calls.jsonl",
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.refresh_session()
        self._train_log_line(
            "Dataset set to the bundled sample (20 synthetic tool-call "
            "examples). Start training when ready."
        )

    def start_training(self, resume: bool = False):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to train.")
            return
        if self._training_running():
            self._say("Training is already running.")
            return
        if self._sleep_running():
            # Training and sleep each load the base model — running
            # both at once would blow the 8 GB ceiling.
            self._say("Sleep is already running.")
            return
        from .train import training_deps_missing

        missing = training_deps_missing()
        if missing:
            hint = (
                "Training packages missing: " + ", ".join(missing) + ". "
                "Run this once in the Stella folder: bash install-training.sh"
            )
            self._train_log_line(hint)
            self._say("Training packages missing. See the Train log.")
            return
        # Settings live in the store now (the project window saves
        # them); there is no form left to save from here. But the
        # weights may still be missing: offer the download first.
        if not self._weights_offer(profile):
            return
        self._train_worker = TrainWorker(
            self.store, profile, project, resume=resume
        )
        self._train_worker.progress.connect(self._on_train_progress)
        self._train_worker.log.connect(self._train_log_line)
        self._train_worker.finished.connect(self._on_train_finished)
        self.train_start_btn.setEnabled(False)
        self.train_resume_btn.setEnabled(False)
        self.train_pause_btn.setEnabled(True)
        self._set_activity(
            "training", "Resuming training..." if resume else "Training..."
        )
        self._train_log_line(
            "Resuming training..." if resume else "Starting training..."
        )
        self.debug_log.action(
            f"training started: {profile}/{project} (resume={resume})"
        )
        self._train_worker.start()

    def pause_training(self):
        if self._train_worker is not None:
            self._train_worker.request_stop()
            self._train_log_line(
                "Pausing after this step (checkpoint will save)..."
            )

    def _on_train_progress(self, step: int, total: int, loss: float):
        self.train_progress.setMaximum(max(1, total))
        self.train_progress.setValue(step)
        self.train_loss.setText(f"Step {step} / {total}, loss {loss:.4f}")
        if self._sleep_running():
            self._set_activity("sleep", f"Sleep: step {step} / {total}")
        else:
            self._set_activity("training", f"Training: step {step} / {total}")

    def _on_train_finished(self, ok: bool, message: str):
        self.train_start_btn.setEnabled(True)
        self.train_resume_btn.setEnabled(True)
        self.train_pause_btn.setEnabled(False)
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        self.debug_log.action(f"training finished: ok={ok}: {message}")
        self._say(message.splitlines()[0] if message else "Training done.")
        self.refresh_tree()
        self.refresh_session()

    def _on_job_finished(self, ok: bool, message: str):
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        self._say(message.splitlines()[0] if message else "Done.")
        self.refresh_train_panel()

    # -- sleep ------------------------------------------------------
    def start_sleep(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to sleep.")
            return
        if self._training_running():
            self._say("Training is already running.")
            return
        if self._sleep_running():
            self._say("Sleep is already running.")
            return
        from .train import training_deps_missing

        missing = training_deps_missing()
        if missing:
            hint = (
                "Training packages missing: " + ", ".join(missing) + ". "
                "Run this once in the Stella folder: bash install-training.sh"
            )
            self._train_log_line(hint)
            self._say("Training packages missing. See the Train log.")
            return
        if not self._weights_offer(profile):
            return
        self._sleep_worker = SleepWorker(
            self.store, profile, project,
            dream=self.sleep_dream_check.isChecked(),
        )
        self._sleep_worker.progress.connect(self._on_train_progress)
        self._sleep_worker.log.connect(self._train_log_line)
        self._sleep_worker.finished.connect(self._on_sleep_finished)
        self.sleep_btn.setEnabled(False)
        self._set_activity("sleep", "Sleep: starting...")
        self._train_log_line("Starting sleep cycle...")
        self.debug_log.action(f"sleep started: {profile}/{project}")
        self._sleep_worker.start()

    def _on_sleep_finished(self, ok: bool, message: str):
        self.sleep_btn.setEnabled(True)
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        self.debug_log.action(f"sleep finished: ok={ok}: {message}")
        self._say(message.splitlines()[0] if message else "Sleep done.")
        self.refresh_tree()
        self.refresh_session()

    def _on_sleep_cycle_clicked(self, item):
        cycle = item.data(Qt.UserRole)
        if cycle is None:
            return
        from .sleep import read_cycle_report

        try:
            report = read_cycle_report(
                self.store, self._current_profile, self._current_project, cycle
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        fmt = lambda v: f"{v:.4f}" if v is not None else "n/a"
        delta = report.get("old_delta_relative")
        delta_text = f"{delta:+.1%}" if delta is not None else "n/a"
        lines = [
            f"Sleep cycle {report['cycle']}: {report['status']}",
            f"Finished: {report.get('timestamp', '')}",
            f"Rows: {report['real_rows']} new, {report['dreamed_rows']} dreamed",
            f"Steps: {report['steps']}, LoRA rank {report.get('rank', '')}",
            f"Old loss: {fmt(report.get('old_loss_before'))} -> "
            f"{fmt(report.get('old_loss_after'))} ({delta_text})",
            f"New loss: {fmt(report.get('new_loss'))}",
            f"Threshold: {report.get('threshold', '')} "
            f"({'in-sample new val' if report.get('new_val_in_sample') else 'held-out new val'})",
        ]
        QMessageBox.information(
            self, f"Sleep cycle {cycle}", "\n".join(lines)
        )

    def export_gguf_gui(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to export.")
            return
        dest = QFileDialog.getExistingDirectory(
            self, "Export GGUF to folder", str(Path.home())
        )
        if not dest:
            return
        from .gguf import export_gguf

        def job(log):
            result = export_gguf(self.store, profile, project, dest)
            return (
                f"GGUF ready: {result['gguf']} "
                f"({result['gguf_bytes']:,} bytes).\n"
                f"Run: {result['ollama_create']}"
            )

        self._job_worker = JobWorker(job)
        self._job_worker.log.connect(self._train_log_line)
        self._job_worker.finished.connect(self._on_job_finished)
        self._set_activity("job", "Working: exporting GGUF...")
        self._train_log_line("Exporting GGUF (merge, convert, quantize)...")
        self._job_worker.start()

    def run_probe_gui(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to probe.")
            return
        from .probe import probe_gate, probe_project

        def job(log):
            result = probe_project(self.store, profile, project)
            _passed, verdict = probe_gate(result)
            before = result["before"]
            after = result["after"]
            return (
                f"Refusal probe: {before['refusals']}/{before['total']} "
                f"refusals before, {after['refusals']}/{after['total']} "
                f"after.\n{verdict}"
            )

        self._job_worker = JobWorker(job)
        self._job_worker.log.connect(self._train_log_line)
        self._job_worker.finished.connect(self._on_job_finished)
        self._set_activity("job", "Working: running refusal probe...")
        self._train_log_line("Running refusal probe (before vs after)...")
        self._job_worker.start()

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("session/profile", self._current_profile or "")
        self.settings.setValue("session/project", self._current_project or "")
        self.settings.setValue(
            "tree/expanded",
            [
                slug
                for slug, item in self._tree_profiles.items()
                if item.isExpanded()
            ],
        )
        if self._training_running():
            self._train_worker.request_stop()
            self._train_worker.wait(15000)
        if self._sleep_running():
            self._sleep_worker.request_stop()
            self._sleep_worker.wait(15000)
        if self._chat_window is not None:
            self._chat_window.stop_worker()
        if self.download_manager.is_running():
            self.download_manager.cancel()
            self.download_manager.wait_for_finished(5000)
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("Stella")
    app.setOrganizationName("BrokeNBored")

    # Single instance (U27): re-clicking the icon focuses the running
    # app instead of starting a second copy.
    server_name = "stella-single-instance"
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(500):
        probe.write(b"raise")
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return 0
    # A crashed run leaves its socket behind: clear it before
    # listening, or listen fails "Address in use". Safe: a live
    # instance would already have answered the probe above, so any
    # socket file here is stale.
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    if not server.listen(server_name):
        # Best effort: run without the guard rather than not at all.
        server = None

    window = MainWindow()
    if server is not None:
        def _on_new_connection():
            while server.hasPendingConnections():
                sock = server.nextPendingConnection()
                if sock is not None:
                    sock.disconnectFromServer()
            window.show()
            window.raise_()
            window.activateWindow()

        server.newConnection.connect(_on_new_connection)

    # The crash handler writes a debug report on an unhandled
    # exception. Installed here (the real app entry), never in tests.
    window.debug_log.install_crash_handler()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
