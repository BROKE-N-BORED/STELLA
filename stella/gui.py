"""STELLA window — native Qt, menu bar + tree + bento main screen.

The main window is deliberately uncluttered: a real menu bar
(File, View, Help), a collapsible profile tree on the left (each
profile expands to show its projects), and the bento main screen
on the right. One hero tile holds the whole flow: pick a model,
pick a job, press go. Small tiles carry the glanceable numbers
(RAM, speed, progress, the loss curve) once a job runs. The train
details (dataset, checkpoints, log, export, probe, sleep cycles)
live below, in the scroll.

Everything else lives in its own window, reached from the menu or
by double-clicking a tree row: Profile window, Project window,
Settings window, How to Use window. Nothing is crammed into one
window.

Clicking a project in the tree SETS THE TRAINING SESSION (current
profile + project). The session is remembered across restarts via
QSettings — that is the user's own pick coming back, not a default:
on first run nothing is selected at all.

No web UI. Network: localhost Ollama, the Hugging Face download,
and any cloud chat provider the user adds a key for (Groq, Gemini,
or a custom service). No "&" in any visible label — Qt eats a bare
& as a mnemonic marker. No em-dashes in any visible text. No
training settings anywhere on screen — the backend measures the PC
and picks them (see autoconfig.py); the user never sees them.

Training, sleep, and model downloads run off the GUI thread (worker
threads / a subprocess) so the window stays responsive; they only
talk to the window through Qt signals.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QSettings,
    Qt,
    QThread,
    QUrl,
    Signal,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import export as export_mod
from . import provision
from .autoconfig import measure_pc, ram_usage_gb
from .chat_agent import ChatAgent
from .debug_log import DebugLogger, check_ollama
from .howto import topic_text, topic_titles
from .model import (
    STELLA_VERSION,
    StellaError,
    Store,
    metamorph_problem,
    slug_from_model,
)
from .model_info import describe_model, fit_verdict, fits_this_pc
from .ollama import list_model_sizes, list_models, ollama_url
from .providers import (
    PROVIDERS,
    get_custom_config,
    has_key,
    load_providers,
    provider_presence,
    remove_key,
    save_key,
    test_connection,
)
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


def _tag_warnings(store, tag, *, exclude_slug=None):
    """Plain-words problems with an Ollama tag (T12): not installed
    locally, or already used by another profile. Empty list = no
    problem. An empty tag is not a problem, and neither is an Ollama
    that is not answering — with no installed list there is nothing
    to check against, so a tag is never warned about on a guess."""
    warnings = []
    if not tag:
        return warnings
    installed = list_models()
    if installed and tag not in installed:
        warnings.append(f"{tag!r} is not installed locally")
    for p in store.list_profiles():
        if p.get("_damaged"):
            continue
        if p.get("name") == exclude_slug:
            continue
        if p.get("ollama_tag") == tag:
            warnings.append(f"profile {p['name']!r} already uses this tag")
            break
    return warnings


def _confirm_tag(parent, warnings):
    """One Proceed / Cancel dialog for tag warnings (T12). A
    deliberate entry — a tag about to be pulled — must never be
    blocked, so the choice is always the user's. True = proceed."""
    text = ". ".join(warnings) + ". Use this tag anyway?"
    return (
        QMessageBox.question(
            parent, "Stella", text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        == QMessageBox.Yes
    )


def _friendly_log_line(line: str) -> str:
    """One train_log.jsonl record as the friendly line the live log
    showed ("step 3/4 loss 2.1000"), never raw JSON (T13). A record
    without a total (written before v0.10) renders without it; a
    line that is not a record passes through untouched."""
    try:
        record = json.loads(line)
    except ValueError:
        return line
    if not isinstance(record, dict):
        return line
    if "val_loss" in record:
        try:
            return (
                f"epoch {record.get('epoch', '?')} validation loss "
                f"{float(record['val_loss']):.4f}"
            )
        except (TypeError, ValueError):
            return line
    if "loss" in record and "step" in record:
        try:
            loss = float(record["loss"])
        except (TypeError, ValueError):
            return line
        total = record.get("total_steps")
        if total:
            return f"step {record['step']}/{total} loss {loss:.4f}"
        return f"step {record['step']} loss {loss:.4f}"
    return line


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

    The pick itself (T18): a list of the models installed on this PC,
    one row each — the tag, one plain line for what it does, and
    whether it fits this PC (size plus RAM, from the backend's PC
    measurement). Details beyond that appear on tap, not up front.
    Nothing is selected when the dialog opens (U6: select nothing by
    default, ever), the profile-name note appears only after a pick,
    and Enter with no pick does nothing. A model can also be typed
    by hand (a Hugging Face repo, or any tag) — typing clears the
    list pick, so there is ever one pick at a time.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New profile")
        self.installed_models = list_models()
        sizes = list_model_sizes()
        measurement = measure_pc()
        ram_free = measurement.get("ram_available_gb")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Pick a model: that is all it takes."))
        self.model_list = QListWidget()
        self.model_list.setMinimumWidth(520)
        self.model_list.setMinimumHeight(180)
        for tag in self.installed_models:
            fits = fits_this_pc(tag, ram_free)
            if fits is True:
                verdict = "Fits this PC."
            elif fits is False:
                verdict = "Too big for this PC."
            else:
                verdict = "Fit unknown. Stella will check."
            item = QListWidgetItem(
                f"{tag}\n{describe_model(tag)} {verdict}"
            )
            item.setData(Qt.UserRole, tag)
            self.model_list.addItem(item)
        self.model_list.setCurrentRow(-1)
        layout.addWidget(self.model_list)
        self._sizes = sizes
        self._ram_free = ram_free
        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        self.details_label.setVisible(False)
        layout.addWidget(self.details_label)
        if not self.installed_models:
            layout.addWidget(
                QLabel("Ollama is not answering. Type the model by hand.")
            )
        self.type_edit = QLineEdit()
        self.type_edit.setPlaceholderText(
            "Or type a model name or Hugging Face repo, "
            "like LiquidAI/LFM3-1.7B"
        )
        layout.addWidget(self.type_edit)
        self.name_note = QLabel("")
        layout.addWidget(self.name_note)
        self.model_list.currentItemChanged.connect(self._on_row_picked)
        self.model_list.itemActivated.connect(lambda _i: self._maybe_create())
        self.type_edit.textChanged.connect(self._on_typed)
        # Enter in the type field creates only when there is a pick:
        # Enter with no pick does nothing (T18).
        self.type_edit.returnPressed.connect(self._maybe_create)
        buttons = QHBoxLayout()
        self.create_btn = QPushButton("Create profile")
        self.create_btn.setDefault(True)
        self.cancel_btn = QPushButton("Cancel")
        buttons.addWidget(self.create_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

    def picked_model(self) -> str:
        """The picked model: the tapped row, or the typed text."""
        current = self.model_list.currentItem()
        if current is not None:
            return str(current.data(Qt.UserRole) or "").strip()
        return self.type_edit.text().strip()

    def _on_row_picked(self, current, _previous):
        if current is None:
            self.details_label.setText("")
            self.details_label.setVisible(False)
        else:
            tag = str(current.data(Qt.UserRole) or "")
            self.details_label.setText(
                fit_verdict(tag, self._sizes.get(tag), self._ram_free)
            )
            self.details_label.setVisible(True)
            if self.type_edit.text():
                self.type_edit.blockSignals(True)
                self.type_edit.setText("")
                self.type_edit.blockSignals(False)
        self._update_name_note()

    def _on_typed(self):
        if self.type_edit.text().strip():
            self.model_list.setCurrentRow(-1)
        self._update_name_note()

    def _maybe_create(self):
        """Enter (or a double-tap on a row) creates only when a model
        is picked. With no pick it does nothing at all — no warning,
        no create (T18)."""
        if self.picked_model():
            self.create_btn.click()

    def keyPressEvent(self, event):
        # Enter with no pick does nothing — not even the default
        # button. (The type field eats its own Return, so this is
        # the list-focus path; _maybe_create covers the rest.)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not self.picked_model():
                event.accept()
                return
        super().keyPressEvent(event)

    def _update_name_note(self):
        model = self.picked_model()
        if model:
            self.name_note.setText(
                f"Profile name: {slug_from_model(model)}"
            )
        else:
            self.name_note.setText("")


class TrainWorker(QThread):
    """Runs train_project off the GUI thread. Only talks to the
    window through signals — never touches a widget directly."""

    progress = Signal(int, int, float, int)  # step, total, loss, epoch
    log = Signal(str)
    finished = Signal(bool, str)  # ok, message

    def __init__(self, store, profile, project, resume=False, force=False,
                 parent=None):
        super().__init__(parent)
        self._store = store
        self._profile = profile
        self._project = project
        self._resume = resume
        self._force = force
        self._controller = TrainController()

    def request_stop(self):
        self._controller.request_stop()

    def _event(self, event: dict):
        kind = event.get("type")
        if kind == "started":
            self.progress.emit(0, event["total_steps"], 0.0, 0)
            self.log.emit(
                f"Training: {event['total_steps']} steps."
            )
        elif kind == "step":
            self.progress.emit(
                event["step"], event["total_steps"], float(event["loss"]),
                int(event.get("epoch") or 0),
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
        elif kind == "warning":
            # A run warning (T99: over-long examples cut short) goes
            # to the log like any other run line.
            self.log.emit(f"Warning: {event.get('message', '')}")
        elif kind == "extending":
            # A resume on a project that already finished training
            # extends it past the original run (T25).
            self.log.emit(
                f"This project already finished training "
                f"({event['trained_steps']} steps). Resuming extends "
                f"it to {event['new_total']} total steps."
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
                force=self._force,
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

    progress = Signal(int, int, float, int)  # step, total, loss, epoch
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
                event["step"], event["total_steps"], float(event["loss"]),
                int(event.get("epoch") or 0),
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
        elif kind == "warning":
            self.log.emit(f"Warning: {event.get('message', '')}")
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


class LossCurveWidget(QWidget):
    """The loss curve (T20): a plain QPainter line chart, middle-
    school science software feel. Redrawn on new points only —
    set_points / append_point call update(), and nothing repaints
    per frame. The last run's curve stays drawn after the run
    finishes; an empty series draws a plain hint line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self._points: list[tuple[int, float]] = []
        self._total = 0

    @property
    def points(self):
        return list(self._points)

    def set_points(self, points, total=0):
        """Replace the whole series (a project switch rebuilds it
        from the run log)."""
        self._points = list(points)
        self._total = total
        self.update()

    def append_point(self, step: int, loss: float, total: int = 0):
        """One live point from the worker's progress signal. A step
        at or below the last step means a new run started: the old
        curve goes away and the new one begins."""
        if self._points and step <= self._points[-1][0]:
            self._points = []
        self._points.append((step, loss))
        if total:
            self._total = total
        # Cap the series so a very long run never grows the paint
        # list without bound: keep every second point past 1000.
        if len(self._points) > 1000:
            self._points = self._points[::2]
        self.update()

    def clear(self):
        self._points = []
        self._total = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            rect = self.rect()
            painter.fillRect(rect, QColor("#fafafa"))
            if not self._points:
                painter.setPen(QPen(QColor("#888888")))
                painter.drawText(
                    rect, Qt.AlignCenter,
                    "No run yet. The loss curve draws here while a job runs.",
                )
                return
            left, right = 44, rect.width() - 10
            top, bottom = 10, rect.height() - 22
            if right <= left or bottom <= top:
                return
            steps = [p[0] for p in self._points]
            losses = [p[1] for p in self._points]
            max_step = max(self._total, steps[-1], 1)
            low, high = min(losses), max(losses)
            if high - low < 1e-9:
                high = low + 1.0
            # Axes.
            painter.setPen(QPen(QColor("#bbbbbb")))
            painter.drawLine(left, top, left, bottom)
            painter.drawLine(left, bottom, right, bottom)
            painter.setPen(QPen(QColor("#888888")))
            painter.drawText(2, top + 4, f"{high:.2f}")
            painter.drawText(2, bottom + 4, f"{low:.2f}")
            painter.drawText(left, rect.height() - 6, "step 0")
            end_label = f"step {max_step}"
            painter.drawText(
                right - painter.fontMetrics().horizontalAdvance(end_label),
                rect.height() - 6,
                end_label,
            )
            # The curve.
            painter.setPen(QPen(QColor("#2e7d32"), 2))
            prev = None
            for step, loss in self._points:
                x = left + (right - left) * step / max_step
                y = bottom - (bottom - top) * (loss - low) / (high - low)
                point = (int(x), int(y))
                if prev is not None:
                    painter.drawLine(prev[0], prev[1], point[0], point[1])
                prev = point
            # The latest point, marked.
            if prev is not None:
                painter.setPen(QPen(QColor("#2e7d32"), 4))
                painter.drawPoint(prev[0], prev[1])
        finally:
            painter.end()


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

        # Dirty tracking (T2): a snapshot of the loaded values, so
        # an edit can be told apart from a save. _loading is set
        # while _load fills the widgets, so the fill itself never
        # counts as an edit.
        self._snapshot = None
        self._loading = False
        for widget, signal in (
            (self.display_edit, self.display_edit.textChanged),
            (self.role_edit, self.role_edit.textChanged),
            (self.tag_combo, self.tag_combo.currentTextChanged),
            (self.base_edit, self.base_edit.textChanged),
        ):
            signal.connect(self._on_edited)
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

    def _current_values(self):
        return {
            "display": self.display_edit.text(),
            "role": self.role_edit.text(),
            "tag": self.tag_combo.currentText(),
            "base": self.base_edit.text(),
        }

    def _capture_snapshot(self):
        self._snapshot = self._current_values()

    def is_modified(self):
        """True when the form differs from what was last loaded or
        saved (T2)."""
        if self._snapshot is None:
            return False
        return self._current_values() != self._snapshot

    def _on_edited(self, *args):
        if self._loading:
            return
        self._update_title()

    def _update_title(self):
        title = f"Profile: {self._slug}"
        if self.is_modified():
            title += " *"
        self.setWindowTitle(title)

    def maybe_save(self):
        """Prompt when there are unsaved edits (T2). True means it
        is fine to go on: nothing to save, saved, or discarded.
        False means the user said wait — stay here."""
        if not self.is_modified():
            return True
        answer = QMessageBox.question(
            self, "Stella",
            f"Save changes to profile {self._slug}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Save:
            return self.save()
        if answer == QMessageBox.Discard:
            return True
        return False

    def closeEvent(self, event):
        if not self.maybe_save():
            event.ignore()
        else:
            super().closeEvent(event)

    def _load(self):
        self._loading = True
        try:
            self._load_inner()
        finally:
            self._loading = False
            self._capture_snapshot()
            self._update_title()

    def _load_inner(self):
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
        """Save the profile form. Returns True on success, False
        when nothing was saved (T2: the prompt needs the answer)."""
        # Soft tag check (T12): warn when the tag is not installed
        # or already used by another profile, and let the user
        # proceed anyway. Cancelling saves nothing.
        tag = self.tag_combo.currentText().strip()
        warnings = _tag_warnings(
            self._main.store, tag, exclude_slug=self._slug
        )
        if warnings and not _confirm_tag(self, warnings):
            return False
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
            return False
        self._main.refresh_tree()
        self._main.refresh_session()
        self.refresh_download_status()
        self._main._say(f"Saved profile {self._slug}.")
        self._capture_snapshot()
        self._update_title()
        return True

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
    """One project's details, in its own window.

    Reached from the menu (Projects) or by double-clicking a project
    row in the tree. Every field explains itself in plain words
    underneath. Name, dataset, and notes stay here; the training
    settings used to live here too, and they don't anymore (T16):
    the backend measures the PC and picks them, so the user never
    sees them. Saving here is what training reads: there is no
    project form in the main window anymore.
    """

    def __init__(self, main, profile, project, parent=None):
        super().__init__(parent)
        self._main = main
        self._profile = profile
        self._project = project
        self.setWindowTitle(f"Project: {profile} / {project}")
        self.setMinimumWidth(480)
        self.resize(520, 480)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll)

        # Shown when a stored value was invalid and a blank is
        # displayed instead (T21). Hidden on a clean fill.
        self._load_note = QLabel("")
        self._load_note.setWordWrap(True)
        self._load_note.setVisible(False)
        layout.addWidget(self._load_note)

        form = QFormLayout()
        self.display_edit = QLineEdit()
        self.dataset_edit = QLineEdit()
        self.dataset_edit.setPlaceholderText("path or name of the training data")
        form.addRow("Display name", self.display_edit)
        form.addRow("", _help_label("Just a label for the project list."))
        form.addRow("Dataset", self.dataset_edit)
        form.addRow(
            "",
            _help_label(
                "The training data: a .jsonl file of examples. "
                "The main screen has a sample to try."
            ),
        )
        layout.addLayout(form)

        self.notes_label = QLabel("Notes")
        layout.addWidget(self.notes_label)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(100)
        layout.addWidget(self.notes_edit)
        layout.addWidget(
            _help_label("Anything you want to remember about this fine-tune.")
        )
        # The notes area has its own save control (T2): notes can be
        # saved without hunting for the project Save button, and the
        # label says when the notes are edited but unsaved.
        self.save_notes_btn = QPushButton("Save notes")
        self.save_notes_btn.clicked.connect(self.save_notes)
        layout.addWidget(self.save_notes_btn)

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

        # Dirty tracking (T2): same pattern as ProfileWindow — a
        # snapshot of the loaded values, an asterisk on the title
        # when the form differs, and a Save / Discard / Cancel
        # prompt on close instead of silently dropping edits.
        self._snapshot = None
        self._loading = False
        for signal in (
            self.display_edit.textChanged,
            self.dataset_edit.textChanged,
            self.notes_edit.textChanged,
        ):
            signal.connect(self._on_edited)
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

    def _current_values(self):
        return {
            "display": self.display_edit.text(),
            "dataset": self.dataset_edit.text(),
            "notes": self.notes_edit.toPlainText(),
        }

    def _capture_snapshot(self):
        self._snapshot = self._current_values()

    def is_modified(self):
        """True when the form differs from what was last loaded or
        saved (T2)."""
        if self._snapshot is None:
            return False
        return self._current_values() != self._snapshot

    def _notes_modified(self):
        """True when the notes alone are edited but unsaved (T2)."""
        if self._snapshot is None:
            return False
        return self.notes_edit.toPlainText() != self._snapshot["notes"]

    def _on_edited(self, *args):
        if self._loading:
            return
        self._update_title()

    def _update_title(self):
        title = f"Project: {self._profile} / {self._project}"
        if self.is_modified():
            title += " *"
        self.setWindowTitle(title)
        self.notes_label.setText(
            "Notes (modified)" if self._notes_modified() else "Notes"
        )

    def maybe_save(self):
        """Prompt when there are unsaved edits (T2). True means it
        is fine to go on: nothing to save, saved, or discarded.
        False means the user said wait — stay here."""
        if not self.is_modified():
            return True
        answer = QMessageBox.question(
            self, "Stella",
            f"Save changes to project {self._project}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Save:
            return self.save()
        if answer == QMessageBox.Discard:
            return True
        return False

    def closeEvent(self, event):
        if not self.maybe_save():
            event.ignore()
        else:
            super().closeEvent(event)

    def save_notes(self) -> bool:
        """Save only the notes (T2): the notes area has its own save
        control. Returns True on success."""
        try:
            self._main.store.write_notes(
                self._profile,
                self._project,
                self.notes_edit.toPlainText(),
            )
        except StellaError as exc:
            QMessageBox.warning(self, "Stella", str(exc))
            return False
        if self._snapshot is not None:
            self._snapshot["notes"] = self.notes_edit.toPlainText()
        self._update_title()
        self._main._say(f"Saved notes for {self._project}.")
        return True

    def _load(self):
        """Fill the form from the stored project, defensively (T21).

        A value of the wrong type falls back to blank and the panel
        says so — the fill never aborts mid-way, so the panel can
        never show another project's values mixed with this one's.
        The stored training settings are not shown here at all
        (T16): the backend picks them, and Save never touches them.
        """
        self._loading = True
        try:
            self._load_inner()
        finally:
            self._loading = False
            self._capture_snapshot()
            self._update_title()

    def _load_inner(self):
        try:
            p = self._main.store.get_project(self._profile, self._project)
            notes = self._main.store.read_notes(self._profile, self._project)
        except StellaError:
            return
        bad = []
        display = p.get("display_name", "")
        if not isinstance(display, str):
            display = ""
            bad.append("display name")
        self.display_edit.setText(display)
        dataset = p.get("dataset_ref", "")
        if not isinstance(dataset, str):
            dataset = ""
            bad.append("dataset")
        self.dataset_edit.setText(dataset)
        if not isinstance(notes, str):
            notes = ""
            bad.append("notes")
        self.notes_edit.setPlainText(notes)
        if bad:
            self._load_note.setText(
                "A stored value was invalid, so a blank is shown "
                "instead. Saving keeps the blank."
            )
            self._load_note.setVisible(True)
        else:
            self._load_note.setText("")
            self._load_note.setVisible(False)

    def save(self) -> bool:
        """Save the project form. Returns True on success, False when
        nothing was saved (store error). The stored training
        settings are untouched: the backend owns them (T16)."""
        try:
            self._main.store.update_project(
                self._profile,
                self._project,
                display_name=self.display_edit.text().strip(),
                dataset_ref=self.dataset_edit.text().strip(),
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
        self._capture_snapshot()
        self._update_title()
        return True


class SettingsWindow(QDialog):
    """Settings, in its own window. Only settings that exist are
    shown: where Stella keeps its files, whether Ollama is answering,
    the chat model, and the AI providers. Training settings are not
    here (T16): the backend measures the PC and picks them, so the
    user never sees them."""

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        # The settings no longer fit a 768 px tall screen, so the
        # content scrolls and Close stays pinned underneath. Without
        # the scroll area the form rows overlap when the dialog is
        # squeezed to the screen height.
        self.resize(560, 680)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

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

        layout.addWidget(QLabel("Chat model"))
        self.chat_combo = QComboBox()
        self.chat_combo.setPlaceholderText("Pick a model for chat")
        self.chat_combo.currentIndexChanged.connect(self._on_chat_model_changed)
        layout.addWidget(self.chat_combo)
        layout.addWidget(
            _help_label(
                "The model the Chat window talks to. Models on this PC "
                "run through Ollama. Groq and Gemini models need a key, "
                "added below under AI providers: greyed out models need "
                "a key first. Nothing is picked until you pick one."
            )
        )
        self._load_chat_models()

        layout.addWidget(QLabel("AI providers"))
        self._key_fields: dict[str, QLineEdit] = {}
        self._key_status: dict[str, QLabel] = {}
        self._provider_buttons: dict[str, dict[str, QPushButton]] = {}
        self._test_workers: dict[str, JobWorker] = {}
        self._custom_base = QLineEdit()
        self._custom_model = QLineEdit()
        self._build_provider_rows(layout)
        layout.addWidget(
            _help_label(
                "Your keys stay on this PC in a private file. They only "
                "leave the PC to talk to that provider, and never appear "
                "in a debug report."
            )
        )

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
        outer.addWidget(close_btn)
        layout.addStretch(1)

        self.refresh_ollama_status()

    def _build_provider_rows(self, layout):
        """One row per keyed provider: a password-style key field,
        Save, Test, Remove, and a status line. Custom adds a base
        URL and a model name, since any OpenAI-compatible service
        can live there. The key field is always blank: it only ever
        takes a NEW key, never shows the saved one."""
        home = self._main.store.home
        for pid in ("groq", "gemini"):
            display = PROVIDERS[pid]["display"]
            layout.addWidget(QLabel(display))
            field = QLineEdit()
            field.setEchoMode(QLineEdit.Password)
            field.setPlaceholderText(f"Paste your {display} key here")
            layout.addWidget(field)
            self._key_fields[pid] = field
            self._add_provider_buttons(layout, pid)
        custom = get_custom_config(home)
        layout.addWidget(QLabel("Custom (any OpenAI-compatible service)"))
        self._custom_base.setPlaceholderText(
            "Address, for example https://example.com/v1"
        )
        self._custom_base.setText(custom.get("base_url", ""))
        layout.addWidget(self._custom_base)
        layout.addWidget(
            _help_label("The service address, without /chat/completions.")
        )
        self._custom_model.setPlaceholderText("Model name")
        self._custom_model.setText(custom.get("model", ""))
        layout.addWidget(self._custom_model)
        layout.addWidget(
            _help_label("The model name that service knows.")
        )
        field = QLineEdit()
        field.setEchoMode(QLineEdit.Password)
        field.setPlaceholderText("Paste your key for this service here")
        layout.addWidget(field)
        self._key_fields["custom"] = field
        self._add_provider_buttons(layout, "custom")

    def _add_provider_buttons(self, layout, pid):
        row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(lambda: self._on_provider_save(pid))
        row.addWidget(save_btn)
        test_btn = QPushButton("Test")
        test_btn.clicked.connect(lambda: self._on_provider_test(pid))
        row.addWidget(test_btn)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: self._on_provider_remove(pid))
        row.addWidget(remove_btn)
        layout.addLayout(row)
        self._provider_buttons[pid] = {
            "save": save_btn,
            "test": test_btn,
            "remove": remove_btn,
        }
        status = QLabel(
            "Key saved." if has_key(self._main.store.home, pid)
            else "No key saved."
        )
        status.setWordWrap(True)
        layout.addWidget(status)
        self._key_status[pid] = status

    def _on_provider_save(self, pid):
        key = self._key_fields[pid].text().strip()
        status = self._key_status[pid]
        if not key:
            status.setText("Paste a key first.")
            return
        try:
            if pid == "custom":
                save_key(
                    self._main.store.home,
                    pid,
                    key,
                    base_url=self._custom_base.text(),
                    model=self._custom_model.text(),
                )
            else:
                save_key(self._main.store.home, pid, key)
        except StellaError as exc:
            status.setText(f"That did not save: {exc}")
            return
        self._key_fields[pid].clear()
        status.setText("Saved.")
        self._load_chat_models()

    def _on_provider_test(self, pid):
        status = self._key_status[pid]
        status.setText("Testing...")
        home = self._main.store.home

        def _run(log):
            _ok, message = test_connection(pid, home=home)
            return message

        worker = JobWorker(_run, parent=self)
        worker.finished.connect(lambda _ok, msg: status.setText(msg))
        self._test_workers[pid] = worker
        worker.start()

    def _on_provider_remove(self, pid):
        remove_key(self._main.store.home, pid)
        self._key_fields[pid].clear()
        self._key_status[pid].setText("No key saved.")
        self._load_chat_models()

    def refresh_ollama_status(self):
        self.ollama_status.setText(f"Status: {check_ollama(ollama_url())}")
        self._load_chat_models()

    def _load_chat_models(self):
        """Fill the chat-model list, grouped by provider: models on
        this PC (Ollama) first, then Groq, Gemini, and Custom. A
        provider with no key saved shows its models greyed out.
        Nothing is selected by default: the saved pick is restored,
        or the box stays blank until the user picks one."""
        saved_provider = self._main.chat_provider or "ollama"
        saved_model = self._main.chat_model
        home = self._main.store.home
        self.chat_combo.blockSignals(True)
        try:
            self.chat_combo.clear()
            model = self.chat_combo.model()

            def add_header(text):
                self.chat_combo.addItem(text)
                item = model.item(self.chat_combo.count() - 1)
                item.setEnabled(False)

            def add_model(provider, name, enabled=True):
                # One string as the item data: Qt mangles tuples
                # stored as user data, so provider and model ride
                # together separated by "|".
                self.chat_combo.addItem(name, f"{provider}|{name}")
                item = model.item(self.chat_combo.count() - 1)
                item.setEnabled(enabled)

            add_header("On this PC (Ollama)")
            for name in list_models():
                add_model("ollama", name)
            for pid in ("groq", "gemini"):
                add_header(PROVIDERS[pid]["display"])
                enabled = has_key(home, pid)
                for name in PROVIDERS[pid]["models"]:
                    add_model(pid, name, enabled)
            custom = load_providers(home).get("custom", {})
            if isinstance(custom, dict) and custom.get("model"):
                add_header("Custom")
                add_model(
                    "custom",
                    custom["model"],
                    bool(custom.get("api_key")),
                )
            index = self.chat_combo.findData(
                f"{saved_provider}|{saved_model}"
            )
            if index >= 0:
                self.chat_combo.setCurrentIndex(index)
            else:
                self.chat_combo.setCurrentIndex(-1)
        finally:
            self.chat_combo.blockSignals(False)

    def _on_chat_model_changed(self, index):
        if index < 0:
            return
        data = self.chat_combo.itemData(index)
        if isinstance(data, str) and "|" in data:
            provider, _sep, model = data.partition("|")
            self._main.set_chat_provider(provider)
            self._main.set_chat_model(model)

    def _on_debug_report(self):
        try:
            self._main.debug_log.set_setting(
                "chat_providers", provider_presence(self._main.store.home)
            )
            path = self._main.debug_log.generate_report()
        except Exception as exc:  # noqa: BLE001 - show it, don't crash
            QMessageBox.warning(
                self, "Stella", f"Could not write the debug report: {exc}"
            )
            return
        QMessageBox.information(
            self, "Stella", f"Debug report written to:\n{path}"
        )

    def closeEvent(self, event):
        # A key test still running when the window closes must finish
        # first: a QThread destroyed while running aborts the app.
        for worker in list(self._test_workers.values()):
            if worker.isRunning():
                worker.wait(30000)
        super().closeEvent(event)


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
    to the chat provider (up to 120 s per call) and may start
    training, so it must never run on the UI thread. Only talks to
    the window through signals."""

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

    The chat model comes from Settings (chat/provider + chat/model).
    If none is picked yet, the window asks the user which installed
    model to use instead of failing: the first message just names
    the model.
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
                "The chat talks to the model you pick in Settings: a "
                "model on this PC through Ollama, or Groq or Gemini "
                "with your key. It can set up and run training for "
                "you. Say just do it and it runs the whole thing."
            )
        )
        self._append(
            "Stella",
            "Hi. Tell me what you want to train, and I will set it up "
            "and run it for you. Or say just do it and I will run the "
            "whole thing.",
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
                "Settings. You can also add a Groq or Gemini key in "
                "Settings under AI providers and chat with one of those.",
            )
            return
        self._awaiting_model = True
        self._append(
            "Stella",
            "Which model should I chat with? Type one of these:\n"
            + "\n".join(f"- {name}" for name in models)
            + "\n\nYou can also pick a Groq or Gemini model in "
            "Settings, under AI providers.",
        )

    def _match_model(self, text: str) -> tuple[str, str] | None:
        """The user's reply, matched against the models the chat can
        use: installed Ollama models first, then cloud models with a
        saved key. Returns (provider, model), or None."""
        cleaned = text.strip().lower()
        models = list_models()
        for name in models:
            if cleaned == name.lower():
                return ("ollama", name)
        hits = [name for name in models if cleaned in name.lower()]
        if len(hits) == 1:
            return ("ollama", hits[0])
        home = self._main.store.home
        for pid in ("groq", "gemini"):
            if not has_key(home, pid):
                continue
            for name in PROVIDERS[pid]["models"]:
                if cleaned == name.lower():
                    return (pid, name)
        custom = get_custom_config(home)
        if custom.get("model") and has_key(home, "custom"):
            if cleaned == custom["model"].lower():
                return ("custom", custom["model"])
        return None

    # -- sending ----------------------------------------------------
    def _make_agent(self):
        if self._agent_factory is not None:
            return self._agent_factory()
        return ChatAgent(
            self._main.store,
            self._main.chat_model,
            provider=self._main.chat_provider or "ollama",
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
            provider, model = match
            self._main.set_chat_provider(provider)
            self._main.set_chat_model(model)
            self._append(
                "Stella",
                f"Got it, I will chat with {model}. What do you want "
                "to train?",
            )
            return
        agent = self._ensure_agent()
        agent.set_provider(
            self._main.chat_provider or "ollama", self._main.chat_model
        )
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


class DistillDialog(QDialog):
    """Teach a small model (T15): pick a teacher from the installed
    models and pick a prompts file. No typing: a combo pick and a
    file pick. Start stays disabled until both are picked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Teach a small model")
        self._prompts_path: str | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "A teacher model answers your prompts, and its "
                "answers become this project's examples."
            )
        )
        layout.addWidget(QLabel("Teacher"))
        self.teacher_combo = QComboBox()
        self.teacher_combo.setPlaceholderText("Pick a teacher model")
        models = list_models()
        if models:
            self.teacher_combo.addItems(models)
        self.teacher_combo.setCurrentIndex(-1)
        self.teacher_combo.currentIndexChanged.connect(self._refresh_start)
        layout.addWidget(self.teacher_combo)
        layout.addWidget(
            _help_label(
                "The teacher should be a bigger model than the "
                "student. Its answers are only as good as it is."
            )
        )
        layout.addWidget(QLabel("Prompts"))
        pick_row = QHBoxLayout()
        self.prompts_btn = QPushButton("Pick a prompts file")
        self.prompts_btn.clicked.connect(self._pick_prompts)
        pick_row.addWidget(self.prompts_btn)
        self.prompts_label = QLabel("No file picked.")
        self.prompts_label.setWordWrap(True)
        pick_row.addWidget(self.prompts_label, 1)
        layout.addLayout(pick_row)
        layout.addWidget(
            _help_label(
                "A plain text file, one prompt per line: the jobs "
                "you want the small model to learn."
            )
        )
        buttons = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setDefault(True)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

    def teacher(self) -> str:
        return self.teacher_combo.currentText().strip()

    def prompts_path(self) -> str | None:
        return self._prompts_path

    def _refresh_start(self):
        self.start_btn.setEnabled(
            self.teacher_combo.currentIndex() >= 0
            and self._prompts_path is not None
        )

    def _pick_prompts(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a prompts file", str(Path.home()),
            "Text files (*.txt);;All files (*)",
        )
        if path:
            self._prompts_path = path
            self.prompts_label.setText(path)
            self._refresh_start()


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
        # Live-run stats for the glanceable card (T20): when the
        # current run's first live point arrived, and which step it
        # was, so speed and time left are measured, not guessed.
        self._run_started_at: float | None = None
        self._run_start_step = 0
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
        # A damaged row (T3) is never restored as the session: its
        # manifest cannot be read, so there is nothing to show.
        saved_damaged = (
            saved_profile in self._tree_profiles
            and self._tree_profiles[saved_profile].data(0, Qt.UserRole + 1)
        )
        if saved_profile and saved_profile in self._tree_profiles and not saved_damaged:
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

        self._build_menu_bar()

        header_row = QHBoxLayout()
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

    def _build_menu_bar(self):
        """A real menu bar (T19, U38): File, View, Help. The Menu
        button is gone. Actions that need a selection start disabled
        and are refreshed by _refresh_menu_state; nothing answers
        with a "pick one first" modal anymore."""
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        self._menu_action_new_profile = file_menu.addAction(
            "New profile...", self.new_profile
        )
        self._menu_action_new_project = file_menu.addAction(
            "New project...", self.new_project
        )
        self._menu_action_export = file_menu.addAction(
            "Export project...", self.export_project
        )
        self._menu_action_import = file_menu.addAction(
            "Import package...", self.import_package
        )
        file_menu.addSeparator()
        self._menu_action_settings = file_menu.addAction(
            "Settings...", self.open_settings_window
        )
        view_menu = bar.addMenu("View")
        self._menu_action_profiles = view_menu.addAction(
            "Profiles", self.open_current_profile_window
        )
        self._menu_action_projects = view_menu.addAction(
            "Projects", self.open_current_project_window
        )
        help_menu = bar.addMenu("Help")
        self._menu_action_howto = help_menu.addAction(
            "How to Use Stella...", self.open_howto_window
        )
        self._menu_action_chat = help_menu.addAction(
            "Chat...", self.open_chat_window
        )

    def _refresh_menu_state(self):
        """Grey out the actions that cannot work yet (T19): New
        project and Profiles need a profile; Export and Projects
        need a project. The rest always work."""
        has_profile = bool(self._current_profile)
        has_session = bool(self._current_profile and self._current_project)
        self._menu_action_new_project.setEnabled(has_profile)
        self._menu_action_profiles.setEnabled(has_profile)
        self._menu_action_export.setEnabled(has_session)
        self._menu_action_projects.setEnabled(has_session)

    def _build_session(self):
        """The main area holds two pages (T15, T17): the first-run
        checklist and the bento main screen. Only one is visible at
        a time; _refresh_checklist picks. The bento is one hero tile
        (pick a model, pick a job, press go), the glanceable card
        (loss curve, speed, RAM, time left, epoch — T20), and the
        train details below, in the scroll."""
        self._build_checklist()
        self._build_bento()

    def _build_checklist(self):
        """The first-run setup checklist (T17): three steps, each a
        button that does the step; a finished step ticks. Shown
        instead of the bento while the first setup is incomplete.
        Dismissible, and dismissal is forever (QSettings)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("First steps")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)
        layout.addWidget(
            QLabel("Three steps and Stella is running. Each step is one button.")
        )
        self.check_steps: list[tuple[QLabel, QPushButton]] = []
        steps = [
            ("1. Pick a model", self.new_profile),
            ("2. Get its weights", self._checklist_download),
            ("3. Run a tiny first training", self._checklist_run_tiny),
        ]
        for text, slot in steps:
            row = QHBoxLayout()
            tick = QLabel("")
            tick.setMinimumWidth(20)
            row.addWidget(tick)
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            row.addWidget(btn, 1)
            layout.addLayout(row)
            self.check_steps.append((tick, btn))
        layout.addWidget(
            _help_label(
                "The tiny first training uses the 20-example sample "
                "dataset: a real run, not a setup wizard."
            )
        )
        self.check_dismiss_btn = QPushButton("Not now")
        self.check_dismiss_btn.clicked.connect(self._checklist_dismiss)
        layout.addWidget(self.check_dismiss_btn)
        layout.addStretch(1)
        self.checklist_widget = page
        self.session_layout.addWidget(page)

    def _build_bento(self):
        """The bento main screen (T15): hero tile, glanceable card,
        train details."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self.session_title = QLabel("No training session yet.")
        self.session_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.session_title)
        self.session_summary = QLabel("")
        self.session_summary.setWordWrap(True)
        layout.addWidget(self.session_summary)

        # -- hero tile: pick a model, pick a job, press go ---------
        hero = QFrame()
        hero.setFrameShape(QFrame.StyledPanel)
        hero_layout = QVBoxLayout(hero)

        hero_layout.addWidget(QLabel("1. Pick a model"))
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setPlaceholderText("Pick a model")
        self.model_combo.currentIndexChanged.connect(
            self._on_model_combo_changed
        )
        model_row.addWidget(self.model_combo, 1)
        self.new_model_btn = QPushButton("New model...")
        self.new_model_btn.clicked.connect(self.new_profile)
        model_row.addWidget(self.new_model_btn)
        hero_layout.addLayout(model_row)

        # The picked model's weights: state, progress, download.
        self.download_status_label = QLabel("")
        self.download_status_label.setWordWrap(True)
        hero_layout.addWidget(self.download_status_label)
        self.download_progress = QProgressBar()
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(0)
        hero_layout.addWidget(self.download_progress)
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
        hero_layout.addLayout(dl_btns)
        hero_layout.addWidget(
            _help_label(
                "Downloads the base weights from Hugging Face. If it "
                "stops, press Download again: it picks up where it left "
                "off, nothing is downloaded twice."
            )
        )

        hero_layout.addWidget(QLabel("2. Pick a job"))
        job_row = QHBoxLayout()
        self._job_group = QButtonGroup(self)
        self._job_group.setExclusive(True)
        self.job_buttons: dict[str, QPushButton] = {}
        for key, text in (
            ("train", "Train"),
            ("sleep", "Sleep"),
            ("requant", "Make smaller"),
            ("distill", "Teach a small model"),
        ):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setProperty("job", key)
            self._job_group.addButton(btn)
            job_row.addWidget(btn)
            self.job_buttons[key] = btn
        self._job_group.buttonClicked.connect(lambda _b: self._refresh_go())
        hero_layout.addLayout(job_row)
        self.project_label = QLabel("No project yet.")
        self.project_label.setWordWrap(True)
        hero_layout.addWidget(self.project_label)

        hero_layout.addWidget(QLabel("3. Press go"))
        self.go_btn = QPushButton("Go")
        self.go_btn.setMinimumHeight(40)
        self.go_btn.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.go_btn.clicked.connect(self._on_go)
        self.go_btn.setEnabled(False)
        hero_layout.addWidget(self.go_btn)

        # Inline project naming (T15 supersedes T113: the job picker
        # is project creation now, and the name becomes part of the
        # pick). Shown only when Go is pressed with no project —
        # no second window.
        self.project_name_row = QWidget()
        name_row = QHBoxLayout(self.project_name_row)
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addWidget(QLabel("Name this job:"))
        self.project_name_edit = QLineEdit()
        self.project_name_edit.setPlaceholderText("my-first-training")
        self.project_name_edit.returnPressed.connect(self._on_go)
        name_row.addWidget(self.project_name_edit, 1)
        self.project_name_row.setVisible(False)
        hero_layout.addWidget(self.project_name_row)

        # Inline dataset prompt: Train and Sleep need examples. When
        # Go is pressed with no dataset, this row offers the sample
        # or a file pick, in place — no modal, no failure.
        self.dataset_prompt_row = QWidget()
        ds_row = QHBoxLayout(self.dataset_prompt_row)
        ds_row.setContentsMargins(0, 0, 0, 0)
        ds_row.addWidget(QLabel("No examples yet."))
        self.dataset_sample_btn = QPushButton("Use the sample")
        self.dataset_sample_btn.clicked.connect(
            self._dataset_prompt_use_sample
        )
        ds_row.addWidget(self.dataset_sample_btn)
        self.dataset_pick_btn = QPushButton("Pick a file")
        self.dataset_pick_btn.clicked.connect(self._dataset_prompt_pick)
        ds_row.addWidget(self.dataset_pick_btn)
        ds_row.addStretch(1)
        self.dataset_prompt_row.setVisible(False)
        hero_layout.addWidget(self.dataset_prompt_row)

        layout.addWidget(hero)

        # -- glanceable card: the loss curve and the live numbers --
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(QLabel("How it is going"))
        self.loss_curve = LossCurveWidget()
        card_layout.addWidget(self.loss_curve)
        stats_row = QHBoxLayout()
        self.stat_speed = QLabel("Speed: not started")
        self.stat_ram = QLabel("RAM: not started")
        self.stat_time_left = QLabel("Time left: not started")
        self.stat_epoch = QLabel("Epoch: not started")
        for label in (
            self.stat_speed, self.stat_ram,
            self.stat_time_left, self.stat_epoch,
        ):
            label.setWordWrap(True)
            stats_row.addWidget(label)
        card_layout.addLayout(stats_row)
        self.train_progress = QProgressBar()
        self.train_progress.setValue(0)
        card_layout.addWidget(self.train_progress)
        self.train_loss = QLabel("Not started.")
        card_layout.addWidget(self.train_loss)
        run_btns = QHBoxLayout()
        self.train_pause_btn = QPushButton("Pause")
        self.train_pause_btn.clicked.connect(self.pause_training)
        self.train_pause_btn.setEnabled(False)
        self.train_resume_btn = QPushButton("Resume")
        self.train_resume_btn.clicked.connect(
            lambda: self.start_training(resume=True)
        )
        run_btns.addWidget(self.train_pause_btn)
        run_btns.addWidget(self.train_resume_btn)
        run_btns.addStretch(1)
        card_layout.addLayout(run_btns)
        layout.addWidget(card)

        # -- train details, below, in the scroll --------------------
        layout.addWidget(QLabel("Dataset"))
        dataset_btns = QHBoxLayout()
        self.train_pick_dataset_btn = QPushButton("Pick dataset file")
        self.train_pick_dataset_btn.clicked.connect(self.pick_dataset)
        self.train_sample_btn = QPushButton("Use sample dataset")
        self.train_sample_btn.clicked.connect(self.use_sample_dataset)
        dataset_btns.addWidget(self.train_pick_dataset_btn)
        dataset_btns.addWidget(self.train_sample_btn)
        dataset_btns.addStretch(1)
        layout.addLayout(dataset_btns)
        layout.addWidget(QLabel("Checkpoints"))
        self.train_checkpoints = QListWidget()
        self.train_checkpoints.setMaximumHeight(90)
        layout.addWidget(self.train_checkpoints)
        export_btns = QHBoxLayout()
        self.train_export_gguf_btn = QPushButton("Export GGUF")
        self.train_export_gguf_btn.clicked.connect(self.export_gguf_gui)
        self.train_probe_btn = QPushButton("Run refusal probe")
        self.train_probe_btn.clicked.connect(self.run_probe_gui)
        export_btns.addWidget(self.train_export_gguf_btn)
        export_btns.addWidget(self.train_probe_btn)
        export_btns.addStretch(1)
        layout.addLayout(export_btns)
        layout.addWidget(QLabel("Training log"))
        self.train_log = QPlainTextEdit()
        self.train_log.setReadOnly(True)
        self.train_log.setMinimumHeight(120)
        layout.addWidget(self.train_log)

        # Sleep keeps its dream switch and its cycles list here; the
        # Sleep button itself is gone — Go starts it, like every job.
        dream_row = QHBoxLayout()
        self.sleep_dream_check = QCheckBox("Dream first")
        self.sleep_dream_check.setToolTip(
            "Dream synthetic practice rows from the local Ollama model "
            "before consolidating (best effort: sleep still runs on "
            "real rows if Ollama is down)."
        )
        dream_row.addWidget(self.sleep_dream_check)
        dream_row.addStretch(1)
        layout.addLayout(dream_row)
        layout.addWidget(
            QLabel("Sleep cycles (click one to see its report)")
        )
        self.sleep_cycles = QListWidget()
        self.sleep_cycles.setMaximumHeight(90)
        self.sleep_cycles.itemClicked.connect(self._on_sleep_cycle_clicked)
        layout.addWidget(self.sleep_cycles)
        layout.addStretch(1)

        self.bento_widget = page
        self.session_layout.addWidget(page)

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
        label = p.get("display_name") or p.get("name") or "(unnamed project)"
        # A broken metamorph block shows as a warning row (T39),
        # read through the shared reader — not a crash, not silent
        # normal. Every other project lists as usual.
        if metamorph_problem(p) is not None:
            label += " (warning: metamorph setting is broken)"
        return label

    @staticmethod
    def _set_tree_row(item, label, damaged):
        """One tree row's text + look. A damaged row (T3) is greyed
        and italic with its error in the label; a healed row goes
        back to plain text. The damaged flag lives in UserRole + 1
        so clicks can tell the row apart from a healthy one."""
        item.setText(0, label)
        item.setData(0, Qt.UserRole + 1, bool(damaged))
        font = item.font(0)
        font.setItalic(bool(damaged))
        item.setFont(0, font)
        if damaged:
            item.setForeground(0, QBrush(QColor("#888888")))
        else:
            item.setForeground(0, QBrush())

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
            damaged = bool(p.get("_damaged"))
            if damaged:
                label = f"{slug} (damaged: {p.get('_error', 'bad file')})"
            else:
                label = self._profile_label(p)
            item = self._tree_profiles.get(slug)
            if item is None:
                item = QTreeWidgetItem(self.tree, [label])
                item.setData(0, Qt.UserRole, (slug, None))
                self._tree_profiles[slug] = item
            self._set_tree_row(item, label, damaged)
            projects = {
                pr["name"]: pr for pr in self.store.list_projects(slug)
            }
            for key in list(self._tree_projects):
                if key[0] == slug and key[1] not in projects:
                    item.removeChild(self._tree_projects.pop(key))
            for pname, pr in projects.items():
                key = (slug, pname)
                pr_damaged = bool(pr.get("_damaged"))
                if pr_damaged:
                    pr_label = (
                        f"{pname} (damaged: {pr.get('_error', 'bad file')})"
                    )
                else:
                    pr_label = self._project_label(pr)
                child = self._tree_projects.get(key)
                if child is None:
                    child = QTreeWidgetItem(item, [pr_label])
                    child.setData(0, Qt.UserRole, key)
                    self._tree_projects[key] = child
                self._set_tree_row(child, pr_label, pr_damaged)
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
        if current.data(0, Qt.UserRole + 1):
            # A damaged row (T3) is not a session: it says what is
            # wrong and waits for a repair, it does not set anything.
            self._say(
                "That file is damaged. Double-click the row to open "
                "it and fix it."
            )
            return
        profile, project = data
        self.set_session(profile, project)

    def _on_tree_double_clicked(self, item, _column):
        data = item.data(0, Qt.UserRole)
        if data is None:
            return
        if item.data(0, Qt.UserRole + 1):
            self._repair_damaged(data[0], data[1])
            return
        profile, project = data
        if project is None:
            self.open_profile_window(profile)
        else:
            self.open_project_window(profile, project)

    def _repair_damaged(self, profile, project):
        """Repair for a damaged row (T3): open the broken manifest
        in the text editor so it can be fixed by hand. The folder
        is untouched; fixing the file and refreshing the list brings
        the normal row back."""
        if project is None:
            path = self.store.profile_dir(profile) / "profile.json"
        else:
            path = self.store.project_dir(profile, project) / "project.json"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self._say(f"Opened {path.name} to fix. Save it and the row comes back.")

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
            model = (
                prof.get("ollama_tag") or prof.get("base_ref") or "not set"
            )
            dataset = proj.get("dataset_ref") or "not set yet"
            # No training settings here (T16): the backend picks
            # them, and the user never sees them.
            self.session_summary.setText(
                f"Model: {model}\n"
                f"Dataset: {dataset}\n"
                f"Status: {proj.get('status', 'draft')}."
            )
            self.project_label.setText(
                f"Project: {proj.get('display_name') or self._current_project}"
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
                "Pick a project on the left, or pick a job and press "
                "Go: Stella asks for the project name as part of the job."
            )
            self.project_label.setText(
                "No project yet. Pick one on the left, or press Go "
                "and name one."
            )
            self._say(f"Profile: {self._current_profile}, no project yet.")
        else:
            self.session_title.setText("No training session yet.")
            self.session_summary.setText("Pick a model to begin.")
            self.project_label.setText("No project yet.")
            self._say("Pick a profile to begin.")
        # The model combo mirrors the session (and stays blank with
        # no session: nothing is selected by default, ever).
        self.model_combo.blockSignals(True)
        try:
            self.model_combo.clear()
            for p in self.store.list_profiles():
                if p.get("_damaged"):
                    continue
                self.model_combo.addItem(
                    p.get("display_name") or p["name"], p["name"]
                )
            index = (
                self.model_combo.findData(self._current_profile)
                if self._current_profile
                else -1
            )
            self.model_combo.setCurrentIndex(index)
        finally:
            self.model_combo.blockSignals(False)
        for w in (
            self.train_pick_dataset_btn,
            self.train_sample_btn,
            self.train_export_gguf_btn,
            self.train_probe_btn,
        ):
            w.setEnabled(has_session)
        self.train_resume_btn.setEnabled(
            has_session
            and not self._training_running()
            and not self._sleep_running()
        )
        self.download_btn.setEnabled(
            has_profile and not self.download_manager.is_running()
        )
        self.download_cancel_btn.setEnabled(
            self.download_manager.is_running()
        )
        self._refresh_download_row()
        self._refresh_go()
        self._refresh_menu_state()
        self.refresh_train_panel()
        self._refresh_checklist()

    def _refresh_download_row(self):
        if not self._current_profile:
            self.download_status_label.setText("Pick a profile first.")
            self.download_progress.setVisible(False)
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
        # The bar only earns its space while downloading or when the
        # weights are ready (100%): an idle 0% bar is a dead grey
        # box, and the hero is tall enough already.
        ready = status["state"] == "ready"
        self.download_progress.setVisible(ready)
        self.download_progress.setMaximum(100)
        self.download_progress.setValue(100 if ready else 0)

    # -- hero: pick a model, pick a job, press go -------------------
    def _on_model_combo_changed(self, index):
        """Picking a model in the hero sets the session profile, the
        same as clicking it in the tree."""
        if index < 0:
            return
        slug = self.model_combo.itemData(index)
        if slug and slug != self._current_profile:
            self.set_session(slug, None)

    def _picked_job(self) -> str | None:
        """The picked job key (train, sleep, requant, distill), or
        None when no job is picked."""
        checked = self._job_group.checkedButton()
        if checked is None:
            return None
        return checked.property("job")

    def _job_running(self) -> bool:
        return (
            self._training_running()
            or self._sleep_running()
            or (self._job_worker is not None and self._job_worker.isRunning())
        )

    def _refresh_go(self):
        """Go is live when a model and a job are picked and nothing
        is running. A project is NOT required: Go makes one (the
        name becomes part of the pick)."""
        self.go_btn.setEnabled(
            bool(self._current_profile)
            and self._picked_job() is not None
            and not self._job_running()
        )

    def _on_go(self):
        """Press go: run the picked job on the picked model."""
        job = self._picked_job()
        profile = self._current_profile
        if not job or not profile:
            return
        if self._job_running():
            self._say("A job is already running.")
            return
        if job == "requant":
            self._start_requant()
            return
        if not self._current_project:
            # No project yet: the name becomes part of the pick
            # (T15 supersedes T113). Ask inline, in the hero — no
            # second window. A second press of Go, with a name
            # typed, makes the project and runs the job.
            name = self.project_name_edit.text().strip()
            if not name:
                self.project_name_row.setVisible(True)
                self.project_name_edit.setFocus()
                self._say("Name this job, then press Go again.")
                return
            try:
                data = self.store.create_project(profile, name)
            except StellaError as exc:
                self._warn(str(exc))
                return
            self.project_name_row.setVisible(False)
            self.project_name_edit.setText("")
            self.debug_log.action(
                f"project created: {profile}/{data['name']}"
            )
            self.set_session(profile, data["name"])
            self._say(f"Created project {data['name']}.")
        if job == "train":
            self._go_train()
        elif job == "sleep":
            self._go_sleep()
        elif job == "distill":
            self._start_distill()

    def _go_train(self):
        """Train, after the dataset check: a job with no examples
        offers the sample or a file pick, in place."""
        try:
            proj = self.store.get_project(
                self._current_profile, self._current_project
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        if not (proj.get("dataset_ref") or "").strip():
            self.dataset_prompt_row.setVisible(True)
            self._say("This job needs examples to learn from.")
            return
        self.start_training()

    def _go_sleep(self):
        """Sleep, after the same dataset check as Train."""
        try:
            proj = self.store.get_project(
                self._current_profile, self._current_project
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        if not (proj.get("dataset_ref") or "").strip():
            self.dataset_prompt_row.setVisible(True)
            self._say("This job needs examples to learn from.")
            return
        self.start_sleep()

    def _dataset_prompt_use_sample(self):
        """The inline dataset prompt: use the sample, then Go again
        (the dataset is set now, so the job starts)."""
        self.dataset_prompt_row.setVisible(False)
        self.use_sample_dataset()
        self._on_go()

    def _dataset_prompt_pick(self):
        """The inline dataset prompt: pick a file, then Go again if
        one was picked."""
        self.dataset_prompt_row.setVisible(False)
        self.pick_dataset()
        try:
            proj = self.store.get_project(
                self._current_profile, self._current_project
            )
        except StellaError:
            return
        if (proj.get("dataset_ref") or "").strip():
            self._on_go()

    def _start_requant(self):
        """Make smaller: re-quantize the picked model's Ollama copy
        to Q4_K_M under a new name. No typing needed — the quant
        and the new name are the usual ones (R8 gives this job the
        full card flow later; it runs as a job with log lines
        today, like GGUF export)."""
        profile = self._current_profile
        try:
            prof = self.store.get_profile(profile)
        except StellaError as exc:
            self._warn(str(exc))
            return
        tag = (prof.get("ollama_tag") or "").strip()
        if not tag:
            self._warn(
                "This profile has no Ollama model to make smaller. "
                "Pick a profile that came from an installed model."
            )
            return
        from .requant import requant_model

        def job(log):
            report = requant_model(tag)
            return (
                f"Made a smaller copy: {report['new_tag']} "
                f"({provision.format_size(report['output_bytes'])}, "
                f"was {provision.format_size(report['source_bytes'])}). "
                f"Run it with: {report['ollama_run']}"
            )

        self._job_worker = JobWorker(job)
        self._job_worker.log.connect(self._train_log_line)
        self._job_worker.finished.connect(self._on_job_finished)
        self._set_activity("job", "Working: making a smaller copy...")
        self._train_log_line(f"Making a smaller copy of {tag}...")
        self._job_worker.start()
        self._refresh_go()
        self._refresh_checklist()

    def _start_distill(self):
        """Teach a small model: ask a teacher model the prompts in a
        file, save the answers as this project's dataset. The
        teacher and the prompts file come from one small dialog —
        a combo pick and a file pick, no typing."""
        profile = self._current_profile
        project = self._current_project
        dialog = DistillDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        teacher = dialog.teacher()
        prompts = dialog.prompts_path()
        if not teacher or not prompts:
            return
        from .distill import distill_dataset

        def job(log):
            report = distill_dataset(
                self.store, profile, project, teacher, prompts
            )
            return (
                f"Distilled {report['rows']} examples from {teacher} "
                f"into this project's dataset. Look at the dataset, "
                "then train when ready."
            )

        self._job_worker = JobWorker(job)
        self._job_worker.log.connect(self._train_log_line)
        self._job_worker.finished.connect(self._on_job_finished)
        self._set_activity("job", "Working: asking the teacher...")
        self._train_log_line(f"Asking {teacher} the prompts...")
        self._job_worker.start()
        self._refresh_go()
        self._refresh_checklist()

    # -- first-run checklist ----------------------------------------
    def _checklist_state(self) -> tuple[bool, bool, bool]:
        """(picked a model, got its weights, ran a tiny training).
        Step 2 reads the current profile's weights, or the first
        profile's when nothing is picked yet. Step 3 ticks when any
        project in the store finished training."""
        profiles = [
            p for p in self.store.list_profiles() if not p.get("_damaged")
        ]
        step1 = bool(profiles)
        step2 = False
        if profiles:
            slug = self._current_profile or profiles[0]["name"]
            try:
                status = provision.weights_status(self.store, slug)
                step2 = status["state"] == "ready"
            except StellaError:
                step2 = False
        step3 = False
        for p in profiles:
            for proj in self.store.list_projects(p["name"]):
                if proj.get("status") == "trained":
                    step3 = True
                    break
            if step3:
                break
        return step1, step2, step3

    def _refresh_checklist(self):
        """Pick the visible page: the checklist while the first setup
        is incomplete, the bento otherwise. Dismissed or finished
        never comes back; a running job always shows the bento, so
        the user can watch the run."""
        if self.settings.value("checklist/dismissed", False) in (True, "true"):
            self.checklist_widget.setVisible(False)
            self.bento_widget.setVisible(True)
            return
        if self.settings.value("checklist/done", False) in (True, "true"):
            self.checklist_widget.setVisible(False)
            self.bento_widget.setVisible(True)
            return
        step1, step2, step3 = self._checklist_state()
        if step1 and step2 and step3:
            self.settings.setValue("checklist/done", True)
            self.checklist_widget.setVisible(False)
            self.bento_widget.setVisible(True)
            return
        if self._job_running():
            self.checklist_widget.setVisible(False)
            self.bento_widget.setVisible(True)
            return
        for (tick, _btn), done in zip(self.check_steps, (step1, step2, step3)):
            tick.setText("\u2713" if done else "")
        # Steps unlock in order: one thing at a time.
        self.check_steps[0][1].setEnabled(True)
        self.check_steps[1][1].setEnabled(step1)
        self.check_steps[2][1].setEnabled(step2)
        self.checklist_widget.setVisible(True)
        self.bento_widget.setVisible(False)

    def _checklist_download(self):
        """Checklist step 2: get the weights of the picked model
        (or the first profile, when nothing is picked yet)."""
        slug = self._current_profile
        if not slug:
            profiles = [
                p for p in self.store.list_profiles()
                if not p.get("_damaged")
            ]
            slug = profiles[0]["name"] if profiles else None
        if slug:
            self.start_download(slug)

    def _checklist_run_tiny(self):
        """Checklist step 3: a real tiny first training on the
        20-example sample dataset. Makes a project called
        "first-steps" when the profile has none, sets the sample
        dataset, and starts training."""
        slug = self._current_profile
        if not slug:
            profiles = [
                p for p in self.store.list_profiles()
                if not p.get("_damaged")
            ]
            slug = profiles[0]["name"] if profiles else None
        if not slug:
            return
        project = self._current_project
        if not project:
            projects = self.store.list_projects(slug)
            healthy = [p for p in projects if not p.get("_damaged")]
            if healthy:
                project = healthy[0]["name"]
            else:
                try:
                    data = self.store.create_project(
                        slug, "first-steps",
                        dataset_ref="sample-tool-calls.jsonl",
                    )
                except StellaError as exc:
                    self._warn(str(exc))
                    return
                project = data["name"]
        self.set_session(slug, project)
        try:
            proj = self.store.get_project(slug, project)
        except StellaError as exc:
            self._warn(str(exc))
            return
        if not (proj.get("dataset_ref") or "").strip():
            self.use_sample_dataset()
        self.start_training()

    def _checklist_dismiss(self):
        """Dismiss the checklist. It never comes back."""
        self.settings.setValue("checklist/dismissed", True)
        self._refresh_checklist()

    # -- glanceable card --------------------------------------------
    def _last_run_curve(self, profile: str, project: str):
        """The last run's loss curve for one project, rebuilt from
        its train_log.jsonl (the per-project run history, T20).
        Returns ([(step, loss), ...], total_steps). A step that goes
        down starts a new run, so only the last run's points come
        back; validation records carry no loss and are skipped."""
        log_path = self.store.project_dir(profile, project) / "train_log.jsonl"
        points: list[tuple[int, float]] = []
        total = 0
        if not log_path.is_file():
            return points, total
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return points, total
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if "loss" not in record or "step" not in record:
                continue
            try:
                step = int(record["step"])
                loss = float(record["loss"])
            except (TypeError, ValueError):
                continue
            if points and step <= points[-1][0]:
                points = []
            points.append((step, loss))
            try:
                total = int(record.get("total_steps") or total)
            except (TypeError, ValueError):
                pass
        return points, total

    def _reset_run_stats(self):
        """The card's live numbers, back to their resting state."""
        self._run_started_at = None
        self._run_start_step = 0
        self.stat_speed.setText("Speed: not started")
        self.stat_ram.setText("RAM: not started")
        self.stat_time_left.setText("Time left: not started")
        self.stat_epoch.setText("Epoch: not started")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Seconds as plain words: 40 seconds, 3 minutes,
        1 hour 5 minutes."""
        total = int(max(0, seconds))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minutes"
        if minutes:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        return f"{secs} second{'s' if secs != 1 else ''}"

    def _update_run_stats(self, step: int, total: int, epoch: int):
        """Speed, RAM, time left, epoch — from the live progress
        signal and the PC's own RAM reading (T20)."""
        if self._run_started_at is None:
            self._run_started_at = time.monotonic()
            self._run_start_step = step
        elapsed = time.monotonic() - self._run_started_at
        done = step - self._run_start_step
        if elapsed > 0 and done > 0:
            per_minute = done / (elapsed / 60.0)
            self.stat_speed.setText(
                f"Speed: {per_minute:.1f} steps a minute"
            )
            remaining = total - step
            if remaining > 0:
                secs_left = remaining / (done / elapsed)
                self.stat_time_left.setText(
                    "Time left: about "
                    f"{self._format_duration(secs_left)}"
                )
            else:
                self.stat_time_left.setText("Time left: done")
        else:
            self.stat_speed.setText("Speed: warming up")
            self.stat_time_left.setText("Time left: not known yet")
        used, total_ram = ram_usage_gb()
        if used is not None and total_ram is not None:
            self.stat_ram.setText(
                f"RAM: {used:.1f} of {total_ram:.1f} GB used"
            )
        else:
            self.stat_ram.setText("RAM: unknown")
        if epoch:
            self.stat_epoch.setText(f"Epoch {epoch}")
        else:
            self.stat_epoch.setText("Epoch: not started")

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
        self.download_progress.setVisible(True)
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

    @property
    def chat_provider(self) -> str:
        """The chat provider the user picked in Settings, or "".
        Blank means Ollama, the local provider."""
        return self.settings.value("chat/provider", "") or ""

    def set_chat_provider(self, provider: str):
        self.settings.setValue("chat/provider", provider or "")

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
        dialog.resize(560, 520)
        center = self.geometry().center()
        dialog.move(center.x() - dialog.width() // 2,
                    center.y() - dialog.height() // 2)
        dialog.exec()
        self._profile_dialog = dialog

    def _create_profile_from(self, dialog: NewProfileDialog):
        model = dialog.picked_model()
        if not model:
            self._warn("Pick a model first.")
            return
        # An installed model — or a bare tag — is an Ollama tag; a
        # namespaced id that isn't installed is a Hugging Face repo.
        if model in dialog.installed_models or "/" not in model:
            tag, ref = model, ""
        else:
            tag, ref = "", model
        # Soft tag check (T12): warn when the tag is not installed
        # or already used, and let the user proceed anyway.
        warnings = _tag_warnings(self.store, tag)
        if warnings and not _confirm_tag(self, warnings):
            return
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
        # A rename retargets the open windows and reloads them (T2):
        # ask about unsaved edits BEFORE the store rename, while
        # Save can still write to the old name.
        win = self._profile_windows.get(slug)
        if win is not None and not win.maybe_save():
            return
        for key in list(self._project_windows):
            if key[0] == slug:
                proj_win = self._project_windows[key]
                if not proj_win.maybe_save():
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
        # A rename retargets the open window and reloads it (T2):
        # ask about unsaved edits BEFORE the store rename, while
        # Save can still write to the old name.
        win = self._project_windows.get((profile, project))
        if win is not None and not win.maybe_save():
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
            self.refresh_tree()
            self.refresh_session()
            return
        except Exception as exc:
            # Last-resort catch (T1): an unexpected failure still
            # surfaces as a readable error, never a raw crash — and
            # the lists refresh so the window matches the disk even
            # when the import fails.
            message = str(exc).strip() or f"unexpected {type(exc).__name__}"
            self._warn(f"Import failed: {message}")
            self.refresh_tree()
            self.refresh_session()
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
        """Checkpoints list + log tail + last run's curve for the
        selected project."""
        self.train_checkpoints.clear()
        self.sleep_cycles.clear()
        if not self._current_profile or not self._current_project:
            self.train_loss.setText("Pick a project to train.")
            self._train_panel_project = None
            self.loss_curve.clear()
            self._reset_run_stats()
            return
        # A new project gets a fresh loss line; the same project
        # keeps its last progress (a finished run's final step/loss
        # must survive the refresh that follows it).
        key = (self._current_profile, self._current_project)
        switched = self._train_panel_project != key
        if switched:
            self._train_panel_project = key
            if not self._training_running() and not self._sleep_running():
                self.train_loss.setText("Not started.")
            # The last run's curve comes back with the project
            # (T20): rebuilt from its own run log.
            points, total = self._last_run_curve(*key)
            self.loss_curve.set_points(points, total)
            self._reset_run_stats()
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
        if not switched:
            # Same project: keep the lines the user watched (T13).
            # The finish refresh used to overwrite them with the raw
            # JSONL file, or blank them when there was no file at all.
            return
        log_path = (
            self.store.project_dir(self._current_profile, self._current_project)
            / "train_log.jsonl"
        )
        if log_path.is_file():
            lines = log_path.read_text(encoding="utf-8").splitlines()[-30:]
            self.train_log.setPlainText(
                "\n".join(_friendly_log_line(line) for line in lines)
            )
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
        # An open Project window may hold unsaved edits (T8): the
        # run trains on the STORED dataset, so edits sitting unsaved
        # in the form must stop the start, not train on stale data
        # behind a warning. Save / Discard / Cancel, the same prompt
        # as closing the window (T2).
        proj_win = self._project_windows.get((profile, project))
        if proj_win is not None and proj_win.is_modified():
            if not proj_win.maybe_save():
                self._say(
                    "Training not started: the project has unsaved changes."
                )
                return
        # Re-training a trained project replaces the finished
        # adapter (T25): ask first. A "yes" passes force through
        # to the worker; a "no" stops here. Resume never asks —
        # it extends, and the loop announces that instead.
        force = False
        if not resume:
            status = self.store.get_project(profile, project).get("status")
            if status == "trained":
                answer = QMessageBox.question(
                    self,
                    "Train again?",
                    "This project already finished training. Train it "
                    "again from the start? The current adapter will "
                    "be replaced.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    self._say("Training not started.")
                    return
                force = True
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
            self.store, profile, project, resume=resume, force=force
        )
        self._train_worker.progress.connect(self._on_train_progress)
        self._train_worker.log.connect(self._train_log_line)
        self._train_worker.finished.connect(self._on_train_finished)
        self._run_started_at = None
        self.go_btn.setEnabled(False)
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
        self._refresh_checklist()

    def pause_training(self):
        if self._train_worker is not None:
            self._train_worker.request_stop()
            self._train_log_line(
                "Pausing after this step (checkpoint will save)..."
            )

    def _on_train_progress(self, step: int, total: int, loss: float,
                           epoch: int = 0):
        self.train_progress.setMaximum(max(1, total))
        self.train_progress.setValue(step)
        self.train_loss.setText(f"Step {step} / {total}, loss {loss:.4f}")
        if step > 0:
            # Step 0 is the "started" marker, not a real point.
            self.loss_curve.append_point(step, loss, total)
            self._update_run_stats(step, total, epoch)
        if self._sleep_running():
            self._set_activity("sleep", f"Sleep: step {step} / {total}")
        else:
            self._set_activity("training", f"Training: step {step} / {total}")

    def _on_train_finished(self, ok: bool, message: str):
        self.train_pause_btn.setEnabled(False)
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        self.debug_log.action(f"training finished: ok={ok}: {message}")
        self._say(message.splitlines()[0] if message else "Training done.")
        # The finished run's curve and summary stay visible (T20):
        # the curve keeps its points, the loss line keeps its final
        # step, and the card says done. refresh_session re-enables
        # Go and Resume; it must not wipe the card (same project,
        # so refresh_train_panel leaves both alone).
        self.stat_time_left.setText("Time left: done")
        self.refresh_tree()
        self.refresh_session()

    def _on_job_finished(self, ok: bool, message: str):
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        self._say(message.splitlines()[0] if message else "Done.")
        self._refresh_go()
        self.refresh_train_panel()
        self._refresh_checklist()

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
        self._run_started_at = None
        self.go_btn.setEnabled(False)
        self._set_activity("sleep", "Sleep: starting...")
        self._train_log_line("Starting sleep cycle...")
        self.debug_log.action(f"sleep started: {profile}/{project}")
        self._sleep_worker.start()
        self._refresh_checklist()

    def _on_sleep_finished(self, ok: bool, message: str):
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        self.debug_log.action(f"sleep finished: ok={ok}: {message}")
        self._say(message.splitlines()[0] if message else "Sleep done.")
        # The finished cycle's curve and summary stay visible (T20),
        # like a finished training run.
        self.stat_time_left.setText("Time left: done")
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
            f"Steps: {report['steps']}",
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
            result = export_gguf(
                self.store, profile, project, dest,
                on_warning=log,  # T31: converter warning, before the merge
            )
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
        self._refresh_go()
        self._refresh_checklist()

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
        self._refresh_go()
        self._refresh_checklist()

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
