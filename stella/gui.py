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
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QPropertyAnimation,
    QRect,
    QSettings,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
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
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
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
    CANONICAL_ROLES,
    GOVERNING_SEATS,
    STELLA_VERSION,
    StellaError,
    Store,
    governing_seat_warning,
    is_custom_role,
    metamorph_mode,
    metamorph_problem,
    slug_from_model,
)
from .model_info import describe_model, fit_verdict, fits_this_pc
from .ollama import MODEL_CACHE, SHOW_CACHE, ollama_url
from .requant import DEFAULT_QUANT, KNOWN_QUANTS
from .provision import is_hf_repo_id
from .style import (
    DISABLED,
    apply_stella_style,
    apply_text_size,
    install_press_dips,
    reduced_motion,
    set_reduced_motion,
)
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

# The proof run's step cap (T95): a short smoke test before an
# hours-long run — 5 optimizer steps is enough to prove the data,
# the model, and the loop all work, and short enough to finish in
# minutes on this PC. Passed through as max_steps (T56 made the
# cap real); reaching it is completion, not a pause.
PROOF_RUN_STEPS = 5


def _help_label(text):
    """A small grey plain-words line under a field."""
    label = QLabel(text)
    label.setStyleSheet("color: #9a9a9a; font-size: 11px;")
    label.setWordWrap(True)
    return label


def _displayed_name(display, slug):
    """A profile/project name for a dialog (T120): the display
    name plus the slug when they differ, just the slug when they
    are the same."""
    if display and display != slug:
        return f"{display!r} ({slug})"
    return f"{slug!r}"


def _weights_label(status):
    """A weights_status dict as one plain-words line."""
    state = status["state"]
    if state == "no-repo":
        # Just the fact (T79): the fix is a button next to it, not
        # an instruction to go to the window the user is already in.
        return "No Hugging Face repo set."
    if state == "missing":
        return "Not downloaded yet."
    if state == "partial":
        return (
            "Partly downloaded "
            f"({provision.format_size(status['size_bytes'])} so far)."
        )
    return f"Ready: {provision.format_size(status['size_bytes'])} on disk."


def _chain_tab_order(widgets):
    """Tab walks the widgets in the given (visual) order (T82)."""
    for first, second in zip(widgets, widgets[1:]):
        QWidget.setTabOrder(first, second)


_HEALTH_ICONS: dict[str, QIcon] = {}


def _health_icon(state: str) -> QIcon:
    """A small health dot for a tree row (T78): green = weights
    ready, amber = weights not ready, grey = Ollama down. Drawn
    once and cached; 16 px, no files needed."""
    icon = _HEALTH_ICONS.get(state)
    if icon is not None:
        return icon
    colors = {
        "ready": "#4caf50",
        "missing": "#e8a90c",
        "ollama-down": "#888888",
    }
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(colors.get(state, "#888888"))))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(3, 3, 10, 10)
    finally:
        painter.end()
    icon = QIcon(pixmap)
    _HEALTH_ICONS[state] = icon
    return icon


# The tag-health marker on a profile row (T163): whether the
# profile's Ollama tag is actually installed, from the cached
# model list (T43) — never a fetch. This is the TAG side of row
# health; the dot (T78) is the WEIGHTS side, and both stay: a
# row can have its weights ready while its tag is gone from
# Ollama, and the two facts answer different questions.
_TAG_HEALTH_MARKERS = {
    "installed": " \u2713",  # the tag is installed
    "missing": " \u2717",  # the tag was removed from Ollama
    "down": " ?",  # Ollama is down, so the tag cannot be checked
    "no-tag": " (no tag)",  # the profile names no tag at all
    "unknown": "",  # the list has not loaded yet; the refresh fills it in
}


def _tag_health_state(tag, models, ollama_up, loaded) -> str:
    """One profile tag's health state (T163): "installed",
    "missing", "down", "no-tag", or "unknown". `models` is the
    cached installed list, `ollama_up` / `loaded` the cache's own
    flags — the badge never fetches. A tag-less profile is its
    own state, not a missing one: nothing was ever pointed at."""
    if not tag:
        return "no-tag"
    if not loaded:
        return "unknown"
    if not ollama_up:
        return "down"
    return "installed" if tag in models else "missing"


def _tag_warnings(store, tag, *, exclude_slug=None):
    """Plain-words problems with an Ollama tag (T12): not installed
    locally, or already used by another profile. Empty list = no
    problem. An empty tag is not a problem, and neither is an Ollama
    that is not answering — with no installed list there is nothing
    to check against, so a tag is never warned about on a guess."""
    warnings = []
    if not tag:
        return warnings
    # The cached list (T43): a tag check never fetches. With no
    # cached list there is nothing to check against, so a tag is
    # never warned about on a guess.
    installed = MODEL_CACHE.models()
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


def _fmt_bytes(n: int) -> str:
    """Bytes as plain words (T150/T153): 81 MB, 3.4 GB."""
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.0f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n:,} bytes"


def _fmt_date(timestamp: float) -> str:
    """A Unix timestamp as a plain date (T150): 2026-11-14."""
    try:
        return datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return "unknown date"


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
    if record.get("event") == "warning":
        # A resume warning (T98: changed settings, missing
        # optimizer) renders as its message, not raw JSON.
        return f"Warning: {record.get('message', '')}"
    if record.get("event") == "run_started":
        # A run boundary (T151): the run's total, not raw JSON.
        total = record.get("total_steps")
        if total:
            return f"Run started: {total} steps."
        return "Run started."
    if record.get("event") == "run_finished":
        # A run's finish line (T151): steps + final loss, or the
        # pause it stopped at.
        steps = record.get("steps")
        final = record.get("final_loss")
        if record.get("stopped"):
            return f"Run paused at step {steps}."
        if final is not None:
            try:
                return (
                    f"Run finished: {steps} steps, "
                    f"final loss {float(final):.4f}."
                )
            except (TypeError, ValueError):
                pass
        return f"Run finished: {steps} steps."
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
        # The model list comes from the cache (T43): no fetch on
        # this thread, ever. The list fills from the last good
        # list at once, and a background refresh (started below)
        # refills it when it lands.
        self._model_worker: ModelListWorker | None = None
        measurement = measure_pc()
        ram_free = measurement.get("ram_available_gb")
        self._ram_free = ram_free
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Pick a model: that is all it takes."))
        self.model_list = QListWidget()
        self.model_list.setMinimumWidth(520)
        self.model_list.setMinimumHeight(180)
        self.model_list.setCurrentRow(-1)
        layout.addWidget(self.model_list)
        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        self.details_label.setVisible(False)
        layout.addWidget(self.details_label)
        self.offline_label = QLabel(
            "Ollama is not answering. Type the model by hand."
        )
        self.offline_label.setWordWrap(True)
        self.offline_label.setVisible(False)
        layout.addWidget(self.offline_label)
        self.refresh_btn = QPushButton("Refresh list")
        self.refresh_btn.clicked.connect(self._refresh_models)
        layout.addWidget(self.refresh_btn)
        self._fill_model_list()
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
        _chain_tab_order([
            self.model_list, self.type_edit,
            self.create_btn, self.cancel_btn,
        ])
        # The dialog-open refresh (T43): the list already shows the
        # last good list; the refresh runs behind it and refills
        # when it lands, so the dialog never waits on Ollama.
        self._refresh_models()

    def _fill_model_list(self):
        """Fill the list from the cached model list (T43): no
        fetch, so this is instant. A pick the user already made
        survives a refill; the stored tag stays visible even when
        Ollama does not list it. While the first refresh is still
        in flight the list holds three muted skeleton rows shaped
        like real rows (T146), so it never looks dead — the real
        rows replace them when the refresh lands."""
        models, sizes, loaded, _up, _at = MODEL_CACHE.snapshot()
        self.installed_models = models
        self._sizes = sizes
        # The row pick survives a refill (the typed text is in its
        # own field and is untouched). Read the row directly: this
        # also runs from __init__, before the type field exists.
        current = self.model_list.currentItem()
        picked = (
            str(current.data(Qt.UserRole) or "")
            if current is not None else ""
        )
        self.model_list.clear()
        self.details_label.setText("")
        self.details_label.setVisible(False)
        if not loaded:
            # Skeleton rows (T146): the first says what is
            # happening, the other two hold the shape of the rows
            # to come. All muted and unpickable.
            first = QListWidgetItem("Looking for models...\nOne moment.")
            first.setFlags(Qt.NoItemFlags)
            first.setForeground(QColor(DISABLED))
            self.model_list.addItem(first)
            for _ in range(2):
                item = QListWidgetItem("\u2026\n\u2026")
                item.setFlags(Qt.NoItemFlags)
                item.setForeground(QColor(DISABLED))
                self.model_list.addItem(item)
            self.offline_label.setVisible(False)
            return
        for tag in models:
            fits = fits_this_pc(tag, self._ram_free)
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
        if picked:
            for row in range(self.model_list.count()):
                row_item = self.model_list.item(row)
                if str(row_item.data(Qt.UserRole) or "") == picked:
                    self.model_list.setCurrentRow(row)
                    break
        self.offline_label.setVisible(not models)

    def _refresh_models(self):
        """A background refresh of the cached list (T43): the list
        refills when it lands; nothing blocks meanwhile. A refresh
        already in flight is enough — the cache makes one fetch of
        overlapping refreshes anyway."""
        if self._model_worker is not None and self._model_worker.isRunning():
            return
        worker = ModelListWorker(self)
        worker.refreshed.connect(lambda *_a: self._fill_model_list())
        worker.finished.connect(self._on_model_worker_finished)
        self._model_worker = worker
        worker.start()

    def _on_model_worker_finished(self):
        if self._model_worker is self.sender():
            self._model_worker = None

    def closeEvent(self, event):
        # A refresh still running when the dialog closes must finish
        # first: a QThread destroyed while running aborts the app.
        if self._model_worker is not None and self._model_worker.isRunning():
            self._model_worker.wait(5000)
        super().closeEvent(event)

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


class ModelListWorker(QThread):
    """Fetch the installed-model list off the UI thread (T43).

    One refresh() call on the shared cache; the result arrives on
    the refreshed signal, on the UI thread. The cache dedupes
    simultaneous refreshes, so overlapping workers make one fetch
    between them. The Ollama URL is captured at construction: a
    worker that starts late still fetches the URL that was
    current when the refresh was triggered."""

    refreshed = Signal(list, dict, bool)  # models, sizes, ollama_up

    def __init__(self, parent=None):
        super().__init__(parent)
        self._url = ollama_url()

    def run(self):
        models, sizes, _loaded, ollama_up, _at = MODEL_CACHE.refresh(
            self._url
        )
        self.refreshed.emit(models, sizes, ollama_up)


class ModelShowWorker(QThread):
    """Fetch one tag's /api/show info off the UI thread (T165).

    One refresh() call on the shared show cache; the result
    arrives on the show_ready signal, on the UI thread. The tag
    rides the signal so a window that retargeted while the fetch
    was in flight can ignore a stale answer."""

    show_ready = Signal(str, dict, bool)  # tag, info-or-empty, ollama_up

    def __init__(self, tag, parent=None):
        super().__init__(parent)
        self._tag = tag
        self._url = ollama_url()

    def run(self):
        info, ollama_up = SHOW_CACHE.refresh(self._tag, self._url)
        self.show_ready.emit(self._tag, info or {}, ollama_up)


class TrainWorker(QThread):
    """Runs train_project off the GUI thread. Only talks to the
    window through signals — never touches a widget directly."""

    progress = Signal(int, int, float, int)  # step, total, loss, epoch
    log = Signal(str)
    finished = Signal(bool, str)  # ok, message

    def __init__(self, store, profile, project, resume=False, force=False,
                 max_steps=None, from_checkpoint=None, parent=None,
                 dataset_path=None, base_ref=None):
        super().__init__(parent)
        self._store = store
        self._profile = profile
        self._project = project
        self._resume = resume
        self._force = force
        self._max_steps = max_steps
        self._from_checkpoint = from_checkpoint
        # T161: per-run overrides — a dataset / base for this run
        # only, never written back to the project or profile.
        self._dataset_path = dataset_path
        self._base_ref = base_ref
        self._controller = TrainController()

    def request_stop(self):
        self._controller.request_stop()

    def _event(self, event: dict):
        kind = event.get("type")
        if kind == "loading":
            # T108: the base load (a first run downloads it) is
            # said before it starts, so the wait is not a mystery.
            # T152: the message names the model, and the log line
            # reaches the job card's status (the log signal feeds
            # it), so the window shows "Loading <base>..." from
            # Start until the first step.
            self.log.emit(event.get("message", "Loading the base model."))
        elif kind == "started":
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
                max_steps=self._max_steps,
                from_checkpoint=self._from_checkpoint,
                dataset_path=self._dataset_path,
                base_ref=self._base_ref,
                on_event=self._event,
                controller=self._controller,
            )
        except StellaError as exc:
            self.finished.emit(False, str(exc))
            return
        except Exception as exc:  # keep the window alive on a crash
            self.finished.emit(False, f"Training failed: {exc}")
            return
        # T96: the finish line carries the val loss next to the
        # training loss — it is the number that says whether the
        # tune generalized. A run stopped before its first epoch
        # end never validated, so the val half is left out rather
        # than printed as a fake number.
        message = f"Trained {summary['steps']} steps."
        final_loss = summary.get("final_loss")
        if final_loss is not None:
            message += f" Final loss {final_loss:.4f}."
        val_loss = summary.get("final_val_loss")
        if val_loss is not None:
            message += f" Validation loss {val_loss:.4f}."
        self.finished.emit(True, message)


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
        if kind == "loading":
            # T108: the base load is said before it starts, so the
            # wait is not a mystery (sleep forwards train events).
            self.log.emit(event.get("message", "Loading the base model."))
        elif kind == "started":
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


class JobContext:
    """What a JobWorker job gets: a log line, a progress report,
    and a cancel check. The job runs in the worker thread; all
    three are signal-safe."""

    def __init__(self, worker: "JobWorker"):
        self._worker = worker

    def log(self, text: str) -> None:
        self._worker.log.emit(text)

    def progress(self, done: int, total: int) -> None:
        """Report progress: done of total (total 0 = busy, no count)."""
        self._worker.progress.emit(done, total)

    def is_cancelled(self) -> bool:
        return self._worker.cancelled


class JobWorker(QThread):
    """Generic off-thread job (GGUF export, refusal probe,
    re-quantize, distill). The job function takes a JobContext and
    returns its finish message. It reports progress and honors
    cancel (T74): the job card's Cancel button sets the flag, and
    the engine checks it between steps (and kills a running
    subprocess when it flips)."""

    log = Signal(str)
    progress = Signal(int, int)  # done, total (total 0 = busy)
    finished = Signal(bool, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def request_cancel(self) -> None:
        """Cancel the job (T74). The engine stops at the next check
        point; a running subprocess is killed."""
        self._cancelled = True

    def run(self):
        ctx = JobContext(self)
        try:
            message = self._fn(ctx)
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
            # Dark card colors (T81): the curve lives on a dark
            # surface now, so the axes and labels are light and the
            # curve is a bright green that reads on dark.
            painter.fillRect(rect, QColor("#232323"))
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
            painter.setPen(QPen(QColor("#555555")))
            painter.drawLine(left, top, left, bottom)
            painter.drawLine(left, bottom, right, bottom)
            painter.setPen(QPen(QColor("#9a9a9a")))
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
            painter.setPen(QPen(QColor("#66bb6a"), 2))
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
                painter.setPen(QPen(QColor("#66bb6a"), 4))
                painter.drawPoint(prev[0], prev[1])
        finally:
            painter.end()


class JobCard(QFrame):
    """One running job (T74, entry 021): a title, a live status
    line, a progress bar, and a Cancel button. Every job — Train,
    Sleep, GGUF export, refusal probe, re-quantize, distill — runs
    as one of these. Hidden at rest (the main screen is calm when
    nothing runs); shown while a job runs, right under the hero,
    so no job is ever below the fold while it runs."""

    cancel_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        top_row = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setStyleSheet(
            "font-size: 14px; font-weight: bold;"
        )
        top_row.addWidget(self.title_label, 1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)
        top_row.addWidget(self.cancel_btn)
        layout.addLayout(top_row)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.setVisible(False)
        # The finish-moment timer (T145): a real timer, not a
        # singleShot, so start()/finish() can cancel a moment that
        # is still showing when a new job starts.
        self._moment_timer = QTimer(self)
        self._moment_timer.setSingleShot(True)
        self._moment_timer.timeout.connect(self._end_finish_moment)
        self._morph_animation = None

    def start(
        self, title: str, determinate: bool,
        from_rect: QRect | None = None,
        reduced_motion: bool = False,
    ) -> None:
        """Show the card for a new job, with fresh state.

        With `from_rect` (T149) the card morphs out of the picked
        job button: a 350 ms geometry animation from the button's
        rect to the card's final layout rect. The layout must
        settle first, or the final rect is wrong — show, pump,
        record, then animate. Reduced motion (or no start rect)
        is an instant swap, as before. Any morph still running is
        stopped: a new start always wins."""
        self._stop_morph()
        self._moment_timer.stop()
        self.setStyleSheet("")
        self.title_label.setText(title)
        self.status_label.setText("Starting...")
        self.cancel_btn.setEnabled(True)
        if determinate:
            self.progress.setMaximum(100)
            self.progress.setValue(0)
        else:
            # No count to show: a busy bar, not a lying 0%.
            self.progress.setMaximum(0)
        self.setVisible(True)
        if from_rect is None or reduced_motion:
            return
        QApplication.processEvents()
        final = self.geometry()
        if final.isEmpty() or final == from_rect:
            return
        self.setGeometry(from_rect)
        animation = QPropertyAnimation(self, b"geometry")
        animation.setDuration(350)
        animation.setStartValue(from_rect)
        animation.setEndValue(final)
        animation.finished.connect(self._on_morph_finished)
        self._morph_animation = animation
        animation.start()

    def _stop_morph(self) -> None:
        """Stop a morph still running (T149): finish(),
        finish_moment(), and a new start all cancel it, so the
        card never keeps animating after the job is gone."""
        if self._morph_animation is not None:
            self._morph_animation.stop()
            self._morph_animation = None

    def _on_morph_finished(self) -> None:
        self._morph_animation = None

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_progress(self, done: int, total: int) -> None:
        """done of total; total 0 switches to the busy bar."""
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(done)
        else:
            self.progress.setMaximum(0)

    def finish(self) -> None:
        self._stop_morph()
        self._moment_timer.stop()
        self.setStyleSheet("")
        self.setVisible(False)

    def finish_moment(self, summary: str, reduced_motion: bool = False) -> None:
        """The finish moment (T145): the card shows the summary in
        a gold glow for a beat, then hides — the job's end is a
        moment, not a vanishing. With reduced motion the card just
        hides: the summary is already in the log and the status
        bar, so nothing is lost. A morph still running stops first
        (T149)."""
        self._stop_morph()
        if reduced_motion:
            self.finish()
            return
        self._moment_timer.stop()
        self.cancel_btn.setEnabled(False)
        self.status_label.setText(summary)
        self.setStyleSheet(
            "QFrame#card { border: 2px solid #ffc93c; "
            "background-color: #3a3016; }"
        )
        self.setVisible(True)
        self._moment_timer.start(250)

    def _end_finish_moment(self) -> None:
        self.setStyleSheet("")
        self.setVisible(False)


class CollapsibleSection(QWidget):
    """A section with a header that collapses it (T80, entry 012).

    The header is a flat button with an arrow: down when open, right
    when closed. Sections start open — collapsing is the user's
    choice, nothing is hidden by default. Content goes in
    `content_layout`."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.header_btn = QPushButton(f"\u25be {title}")
        self.header_btn.setObjectName("sectionHeader")
        self.header_btn.setFlat(True)
        self.header_btn.setCheckable(True)
        self.header_btn.setChecked(True)
        self.header_btn.toggled.connect(self._on_toggled)
        layout.addWidget(self.header_btn)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        layout.addWidget(self.content)

    @property
    def title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        """Rename the section (the Notes section marks itself
        "(modified)" this way)."""
        self._title = title
        arrow = "\u25be" if self.header_btn.isChecked() else "\u25b8"
        self.header_btn.setText(f"{arrow} {title}")

    def is_expanded(self) -> bool:
        return self.content.isVisible()

    def set_expanded(self, expanded: bool) -> None:
        self.header_btn.setChecked(expanded)

    def _on_toggled(self, checked: bool) -> None:
        self.content.setVisible(checked)
        arrow = "\u25be" if checked else "\u25b8"
        self.header_btn.setText(f"{arrow} {self._title}")


# ---------------------------------------------------------------- windows


class ProfileWindow(QDialog):
    """One profile's settings, in its own window.

    Reached from the menu (Profiles) or by double-clicking a profile
    row in the tree. Every field explains itself in plain words
    underneath. The download row lives only in the main window now
    (T79): one honest download row, not a duplicate here.
    """

    def __init__(self, main, slug, parent=None):
        super().__init__(parent)
        self._main = main
        self._slug = slug
        self.setWindowTitle(f"Profile: {slug}")
        self.setMinimumWidth(480)
        self.resize(480, 680)

        # The form scrolls and the action row stays pinned under
        # it (T80's pattern, as in the project window): with the
        # config section the form is taller than a small screen,
        # and a dialog taller than the screen falls back to its
        # minimum size hint — which squeezes every help label to
        # two lines. The scroll area keeps every label whole.
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        form = QFormLayout()
        self.display_edit = QLineEdit()
        # Role (T116/T122): an editable combo offering the
        # canonical seats, with custom entry still allowed — a
        # typed role outside the list is kept, and flagged as
        # custom underneath. Nothing is selected by default:
        # the combo starts blank and only the load fills it.
        self.role_combo = QComboBox()
        self.role_combo.setEditable(True)
        self.role_combo.addItems(list(CANONICAL_ROLES))
        self.role_combo.setCurrentIndex(-1)
        self.role_combo.lineEdit().setPlaceholderText(
            "driver, reviewer, vision..."
        )
        self.custom_role_note = _help_label(
            "Custom role: not one of the canonical seats."
        )
        self.custom_role_note.setVisible(False)
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("LiquidAI/LFM3-1.7B")
        # Governing seat (T116): the seat this profile is bound
        # for, when set. Only the four governing seats are
        # offered; "(not bound)" is the unset state.
        self.seat_combo = QComboBox()
        self.seat_combo.addItem("(not bound)")
        self.seat_combo.addItems(list(GOVERNING_SEATS))
        form.addRow("Display name", self.display_edit)
        form.addRow(
            "",
            _help_label(
                "Just a label for the list. It already says the model's name."
            ),
        )
        form.addRow("Role", self.role_combo)
        form.addRow("", self.custom_role_note)
        form.addRow(
            "",
            _help_label(
                "Only matters if Code Forge uses this profile as a seat "
                "(driver, reviewer...). Leave blank otherwise."
            ),
        )
        form.addRow("Governing seat", self.seat_combo)
        form.addRow(
            "",
            _help_label(
                "Set only when this model will fill a Forge "
                "governing seat. A bound profile warns before "
                "training on a stock base."
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
                "repo like LiquidAI/LFM3-1.7B. Needed before you train. "
                "It usually follows the tag above; it only differs when "
                "the training weights live somewhere else."
            ),
        )
        # No Processor row: the stored field exists but nothing in
        # Stella reads it — showing it only asked a question nobody
        # could answer. It stays in profile.json for compatibility.
        layout.addLayout(form)

        # What the profile points at (T165): the model's size,
        # quant, context, and capabilities from a cached /api/show,
        # plus the project count and the dates. The info loads in
        # the background; until it lands the label says so, and
        # with Ollama down it says unavailable, never blank.
        self.model_info_label = QLabel("")
        self.model_info_label.setWordWrap(True)
        layout.addWidget(self.model_info_label)
        self.profile_facts_label = QLabel("")
        self.profile_facts_label.setWordWrap(True)
        layout.addWidget(self.profile_facts_label)

        # Config and dependencies (T115): the first step toward
        # the profile's own clean environment — the values are
        # editable here and through update-profile, and
        # show-profile prints them. Full environment management
        # is T182, not this: nothing here installs or runs
        # anything.
        config_section = CollapsibleSection("Config and dependencies")
        config_section.content_layout.addWidget(QLabel("Config (JSON)"))
        self.config_edit = QPlainTextEdit()
        self.config_edit.setMinimumHeight(80)
        self.config_edit.setPlaceholderText('{\n  "key": "value"\n}')
        config_section.content_layout.addWidget(self.config_edit)
        config_section.content_layout.addWidget(
            _help_label(
                "Training config for this profile, as a JSON object. "
                "Bad JSON is refused on save, with the error named."
            )
        )
        config_section.content_layout.addWidget(QLabel("Dependencies"))
        self.deps_list = QListWidget()
        self.deps_list.setMinimumHeight(70)
        config_section.content_layout.addWidget(self.deps_list)
        dep_row = QHBoxLayout()
        self.dep_add_edit = QLineEdit()
        self.dep_add_edit.setPlaceholderText("package name")
        self.dep_add_edit.returnPressed.connect(self._add_dependency)
        dep_row.addWidget(self.dep_add_edit, 1)
        self.dep_add_btn = QPushButton("Add")
        self.dep_add_btn.setToolTip(
            "Add the package named in the box to this profile."
        )
        self.dep_add_btn.clicked.connect(self._add_dependency)
        dep_row.addWidget(self.dep_add_btn)
        self.dep_remove_btn = QPushButton("Remove")
        self.dep_remove_btn.setToolTip(
            "Remove the selected dependency from this profile."
        )
        self.dep_remove_btn.clicked.connect(self._remove_dependency)
        self.dep_remove_btn.setEnabled(False)
        dep_row.addWidget(self.dep_remove_btn)
        config_section.content_layout.addLayout(dep_row)
        config_section.content_layout.addWidget(
            _help_label("One package per row. Nothing is installed from here.")
        )
        layout.addWidget(config_section)
        self.config_section = config_section

        # Profile notes (T166): why this profile exists, what it
        # is for, what was learned about its base. They save with
        # the profile below — one Save path, not two.
        notes_section = CollapsibleSection("Profile notes")
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(80)
        notes_section.content_layout.addWidget(self.notes_edit)
        notes_section.content_layout.addWidget(
            _help_label(
                "Why this profile exists, and what you learned "
                "about its base model."
            )
        )
        layout.addWidget(notes_section)
        self.notes_section = notes_section

        self.save_btn = QPushButton("Save profile")
        self.save_btn.clicked.connect(self.save)
        outer.addWidget(self.save_btn)

        btns = QHBoxLayout()
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(lambda: self._main.rename_profile(self._slug))
        clone_btn = QPushButton("Clone")
        clone_btn.clicked.connect(lambda: self._main.clone_profile(self._slug))
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(lambda: self._main.delete_profile(self._slug))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(rename_btn)
        btns.addWidget(clone_btn)
        btns.addWidget(delete_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        outer.addLayout(btns)
        layout.addStretch(1)

        # Dirty tracking (T2): a snapshot of the loaded values, so
        # an edit can be told apart from a save. _loading is set
        # while _load fills the widgets, so the fill itself never
        # counts as an edit. _loaded_base (T54) is the base value
        # the field SHOWED at load — save only passes base_ref when
        # the user changed it, so the store's sync rule decides
        # otherwise.
        self._snapshot = None
        self._loaded_base = ""
        self._loading = False
        # The /api/show fetch worker (T165): one fetch at a time,
        # tracked so close waits for it.
        self._show_worker: ModelShowWorker | None = None
        for widget, signal in (
            (self.display_edit, self.display_edit.textChanged),
            (self.role_combo, self.role_combo.currentTextChanged),
            (self.tag_combo, self.tag_combo.currentTextChanged),
            (self.base_edit, self.base_edit.textChanged),
            (self.seat_combo, self.seat_combo.currentTextChanged),
            (self.config_edit, self.config_edit.textChanged),
            (self.notes_edit, self.notes_edit.textChanged),
        ):
            signal.connect(self._on_edited)
        # The custom-role flag follows the role text (T116), and
        # Remove follows the dependency selection (T115).
        self.role_combo.currentTextChanged.connect(
            self._refresh_custom_role_note
        )
        self.deps_list.currentItemChanged.connect(
            lambda *_a: self.dep_remove_btn.setEnabled(
                self.deps_list.currentItem() is not None
            )
        )
        self._load()
        # Ctrl+S saves here (T82); Tab walks the form in visual order.
        QShortcut(QKeySequence("Ctrl+S"), self, self.save)
        _chain_tab_order([
            self.display_edit, self.role_combo, self.seat_combo,
            self.tag_combo, self.base_edit, self.config_edit,
            self.deps_list, self.dep_add_edit, self.dep_add_btn,
            self.dep_remove_btn, self.notes_edit, self.save_btn,
            rename_btn, clone_btn, delete_btn, close_btn,
        ])

    @property
    def slug(self):
        return self._slug

    def retarget(self, new_slug):
        """The profile was renamed: follow it to the new name."""
        self._slug = new_slug
        self.setWindowTitle(f"Profile: {new_slug}")
        self._load()

    def _current_values(self):
        return {
            "display": self.display_edit.text(),
            "role": self.role_combo.currentText(),
            "tag": self.tag_combo.currentText(),
            "base": self.base_edit.text(),
            "seat": self._seat_value(),
            "config": self.config_edit.toPlainText(),
            "deps": self._deps_values(),
            "notes": self.notes_edit.toPlainText(),
        }

    def _seat_value(self) -> str:
        """The governing-seat marker as stored (T116): "" when the
        combo shows "(not bound)", else the seat name."""
        text = self.seat_combo.currentText()
        return "" if text == "(not bound)" else text

    def _deps_values(self) -> list:
        """The dependency rows as a plain list (T115)."""
        return [
            self.deps_list.item(i).text()
            for i in range(self.deps_list.count())
        ]

    def _refresh_custom_role_note(self):
        """The custom-role flag (T116): a role outside the
        canonical list is kept, and visibly marked custom."""
        self.custom_role_note.setVisible(
            is_custom_role(self.role_combo.currentText())
        )

    def _add_dependency(self):
        """Add one dependency row (T115): a blank or duplicate
        name is ignored, not added twice."""
        name = self.dep_add_edit.text().strip()
        if not name or name in self._deps_values():
            return
        self.deps_list.addItem(name)
        self.dep_add_edit.setText("")
        self._on_edited()

    def _remove_dependency(self):
        """Remove the selected dependency row (T115)."""
        item = self.deps_list.currentItem()
        if item is None:
            return
        self.deps_list.takeItem(self.deps_list.row(item))
        self._on_edited()

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
            # A QThread destroyed while running aborts the app:
            # wait for the show fetch (its timeout bounds it).
            if (
                self._show_worker is not None
                and self._show_worker.isRunning()
            ):
                self._show_worker.wait(5000)
            super().closeEvent(event)

    def _load(self):
        self._loading = True
        try:
            self._load_inner()
        finally:
            self._loading = False
            self._capture_snapshot()
            self._update_title()
        # A combo filled from an unloaded cache fills for real when
        # the refresh lands: the main window refills open profile
        # windows from its refreshed handler (T43).
        if not MODEL_CACHE.loaded:
            self._main.refresh_model_list()

    def _fill_tag_combo(self, prefer_current: bool = False):
        """Fill the tag combo from the cached model list (T43): no
        fetch, so this is instant and the stored tag never flickers
        away while Ollama answers. The stored tag is always listed,
        even when Ollama does not have it. A refresh refill keeps
        what the user typed (prefer_current); a load shows the
        stored tag."""
        models = MODEL_CACHE.models()
        current = self.tag_combo.currentText()
        try:
            stored = self._main.store.get_profile(self._slug).get(
                "ollama_tag", ""
            )
        except StellaError:
            stored = ""
        self.tag_combo.blockSignals(True)
        try:
            self.tag_combo.clear()
            if models:
                self.tag_combo.addItems(models)
            if stored and stored not in models:
                self.tag_combo.addItem(stored)
            if prefer_current and current:
                self.tag_combo.setCurrentText(current)
            else:
                self.tag_combo.setCurrentText(stored)
        finally:
            self.tag_combo.blockSignals(False)

    def _refresh_facts(self, p):
        """The profile facts (T165): project count, created /
        updated / last-used dates. Dates show the day only — the
        full stamp lives in profile.json. A profile never trained
        says "last used never", not a blank."""
        try:
            count = len(self._main.store.list_projects(self._slug))
        except StellaError:
            count = 0

        def day(value):
            return (value or "")[:10] or "unknown"

        last = (p.get("last_used") or "")[:10]
        self.profile_facts_label.setText(
            f"{count} project{'s' if count != 1 else ''}. "
            f"Created {day(p.get('created'))}, "
            f"updated {day(p.get('updated'))}, "
            f"last used {last if last else 'never'}."
        )

    def _refresh_model_info(self):
        """The model info line (T165) for the current tag: from
        the show cache when it has the tag, a background fetch
        when it does not. Called on load, on save (the tag may
        have changed), and when the model-list refresh lands —
        never per keystroke, never on the UI thread."""
        tag = self.tag_combo.currentText().strip()
        if not tag:
            self.model_info_label.setText(
                "No tag set, so there is no model info to show."
            )
            return
        if SHOW_CACHE.loaded(tag):
            self._show_model_info(tag)
            return
        self.model_info_label.setText("Loading model info...")
        if (
            self._show_worker is not None
            and self._show_worker.isRunning()
        ):
            return
        worker = ModelShowWorker(tag, self)
        worker.show_ready.connect(self._on_show_ready)
        worker.finished.connect(self._on_show_worker_finished)
        self._show_worker = worker
        worker.start()

    def _on_show_worker_finished(self):
        if self._show_worker is self.sender():
            self._show_worker = None

    def _on_show_ready(self, tag, _info, _ollama_up):
        # A stale answer (the tag changed mid-fetch) is ignored;
        # the render reads the cache, so it always shows the
        # newest stored info for the tag.
        if tag != self.tag_combo.currentText().strip():
            return
        self._show_model_info(tag)

    def _show_model_info(self, tag):
        """Render the cached /api/show info for a tag (T165):
        size, quant, context length, capabilities. Ollama down
        shows as unavailable, never blank or wrong; a tag Ollama
        does not have says so outright."""
        if not SHOW_CACHE.loaded(tag):
            self.model_info_label.setText("Loading model info...")
            return
        if not SHOW_CACHE.ollama_up(tag):
            self.model_info_label.setText(
                "Model info unavailable: Ollama is not answering."
            )
            return
        info = SHOW_CACHE.info(tag)
        if info is None:
            self.model_info_label.setText(
                f"Model info unavailable: Ollama does not have "
                f"{tag!r} installed."
            )
            return
        parts = []
        size = info.get("size_bytes")
        if size is not None:
            parts.append(f"Size {_fmt_bytes(size)}")
        quant = info.get("quant") or ""
        if quant:
            parts.append(f"quant {quant}")
        context = info.get("context")
        if context is not None:
            parts.append(f"context {context:,} tokens")
        params = info.get("parameter_size") or ""
        if params:
            parts.append(f"{params} parameters")
        caps = info.get("capabilities") or []
        if caps:
            parts.append("can do: " + ", ".join(caps))
        if not parts:
            self.model_info_label.setText(
                "Ollama has this model, but gave no details about it."
            )
            return
        self.model_info_label.setText(", ".join(parts) + ".")

    def _load_inner(self):
        self._fill_tag_combo()
        try:
            p = self._main.store.get_profile(self._slug)
        except StellaError:
            self.display_edit.setText("")
            self.role_combo.setCurrentText("")
            self.seat_combo.setCurrentText("(not bound)")
            self.base_edit.setText("")
            self.config_edit.setPlainText("")
            self.deps_list.clear()
            self.notes_edit.setPlainText("")
            self.model_info_label.setText("")
            self.profile_facts_label.setText("")
            return
        self.display_edit.setText(p.get("display_name", ""))
        self.role_combo.setCurrentText(p.get("role", ""))
        self._refresh_custom_role_note()
        seat = p.get("governing_seat", "") or ""
        self.seat_combo.setCurrentText(seat if seat else "(not bound)")
        # Config (T115): pretty JSON when there is any, blank
        # when there is none — blank saves back as {}.
        config = p.get("config") or {}
        self.config_edit.setPlainText(
            json.dumps(config, indent=2, sort_keys=True) if config else ""
        )
        self.deps_list.clear()
        for dep in p.get("dependencies") or []:
            self.deps_list.addItem(str(dep))
        self.dep_remove_btn.setEnabled(False)
        # The Base ref field shows a repo, never a tag as if it
        # were one (T79): a stored value that is not a Hugging
        # Face repo id (no slash) shows blank, with the placeholder
        # saying what belongs here. Saving passes base_ref only
        # when the field changed (T54) — a blank field the user
        # never touched leaves the stored value to the sync rule,
        # so a tag-valued base follows the tag instead of being
        # cleared by the save.
        base = p.get("base_ref", "")
        self._loaded_base = base if is_hf_repo_id(base) else ""
        self.base_edit.setText(self._loaded_base)
        # T165: the facts and the model info for this profile's
        # tag. T166: the profile notes, loaded with the form.
        self._refresh_facts(p)
        self.notes_edit.setPlainText(
            self._main.store.read_profile_notes(self._slug)
        )
        self._refresh_model_info()

    def save(self):
        """Save the profile form. Returns True on success, False
        when nothing was saved (T2: the prompt needs the answer)."""
        # Config first (T115): bad JSON is refused with the parse
        # error and NOTHING is written — the parse happens before
        # the store call, so a bad config cannot half-save the
        # form. Blank means an empty config.
        config_text = self.config_edit.toPlainText().strip()
        if not config_text:
            config = {}
        else:
            try:
                config = json.loads(config_text)
            except json.JSONDecodeError as exc:
                QMessageBox.warning(
                    self, "Stella", f"Config is not valid JSON: {exc}"
                )
                return False
            if not isinstance(config, dict):
                QMessageBox.warning(
                    self, "Stella",
                    "Config must be a JSON object, not a list or a value.",
                )
                return False
        # Soft tag check (T12): warn when the tag is not installed
        # or already used by another profile, and let the user
        # proceed anyway. Cancelling saves nothing.
        tag = self.tag_combo.currentText().strip()
        warnings = _tag_warnings(
            self._main.store, tag, exclude_slug=self._slug
        )
        if warnings and not _confirm_tag(self, warnings):
            return False
        fields = {
            "display_name": self.display_edit.text().strip(),
            "role": self.role_combo.currentText().strip(),
            "ollama_tag": self.tag_combo.currentText().strip(),
            "config": config,
            "dependencies": self._deps_values(),
            "governing_seat": self._seat_value(),
        }
        # T54: only pass base_ref when the user changed what the
        # field showed — otherwise the store's sync rule decides:
        # a base that followed the old tag follows the new one, and
        # a deliberately split base stays split. Passing the field
        # unconditionally would clear a tag-valued base (the field
        # shows blank for those, T79) and break the sync.
        if self.base_edit.text().strip() != self._loaded_base:
            fields["base_ref"] = self.base_edit.text().strip()
        try:
            self._main.store.update_profile(self._slug, **fields)
        except StellaError as exc:
            QMessageBox.warning(self, "Stella", str(exc))
            return False
        # T166: the profile notes save through the same Save path.
        # A notes failure after a profile save says so plainly —
        # the profile is saved, the notes are not — and the save
        # reports False so the prompt can offer to try again.
        try:
            self._main.store.write_profile_notes(
                self._slug, self.notes_edit.toPlainText()
            )
        except StellaError as exc:
            QMessageBox.warning(
                self, "Stella",
                f"Profile saved, but the notes did not save: {exc}",
            )
            return False
        self._main.refresh_tree()
        self._main.refresh_session()
        self._main._say(f"Saved profile {self._slug}.")
        # T165: the tag may have changed — the model info follows
        # it — and the save stamped a new updated date.
        self._refresh_model_info()
        try:
            self._refresh_facts(
                self._main.store.get_profile(self._slug)
            )
        except StellaError:
            pass
        self._capture_snapshot()
        self._update_title()
        return True


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

        # The action row (Save, Close) stays pinned under the scroll
        # (T80): Save project is visible without scrolling, however
        # long the form gets.
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # Shown when a stored value was invalid and a blank is
        # displayed instead (T21). Hidden on a clean fill.
        self._load_note = QLabel("")
        self._load_note.setWordWrap(True)
        self._load_note.setVisible(False)
        layout.addWidget(self._load_note)

        # Details and Notes are collapsible sections (T80, entry
        # 012). Notes comes FIRST (T160): the running log is the
        # field touched most during a fine-tune, and under the
        # form it needed a scroll on every visit — at the top it
        # is visible without scrolling in the default window.
        notes_section = CollapsibleSection("Project notes")
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMinimumHeight(100)
        notes_section.content_layout.addWidget(self.notes_edit)
        notes_section.content_layout.addWidget(
            _help_label("Anything you want to remember about this fine-tune.")
        )
        # The notes area has its own save control (T2): notes can be
        # saved without hunting for the project Save button, and the
        # label says when the notes are edited but unsaved.
        self.save_notes_btn = QPushButton("Save notes")
        self.save_notes_btn.clicked.connect(self.save_notes)
        notes_section.content_layout.addWidget(self.save_notes_btn)
        layout.addWidget(notes_section)
        self.notes_section = notes_section

        details = CollapsibleSection("Details")
        form = QFormLayout()
        self.display_edit = QLineEdit()
        self.dataset_edit = QLineEdit()
        self.dataset_edit.setPlaceholderText("path or name of the training data")
        self.dataset_browse_btn = QPushButton("Browse...")
        self.dataset_browse_btn.clicked.connect(self._browse_dataset)
        dataset_row = QWidget()
        dataset_layout = QHBoxLayout(dataset_row)
        dataset_layout.setContentsMargins(0, 0, 0, 0)
        dataset_layout.addWidget(self.dataset_edit, 1)
        dataset_layout.addWidget(self.dataset_browse_btn)
        form.addRow("Display name", self.display_edit)
        form.addRow("", _help_label("Just a label for the project list."))
        form.addRow("Dataset", dataset_row)
        form.addRow(
            "",
            _help_label(
                "The training data: a .jsonl file of examples. "
                "The main screen has a sample to try."
            ),
        )
        # What the dataset holds (T45): count, train/check split,
        # and a 3-example preview when it is valid; a warning when
        # it is missing or malformed. Hidden until there is a ref.
        self.dataset_info = QLabel("")
        self.dataset_info.setWordWrap(True)
        self.dataset_info.setVisible(False)
        form.addRow("", self.dataset_info)
        # Why this mode (T114): the metamorph notes — why this
        # morph/compress choice. The mode itself is shown, not
        # picked here: the mode picker was deliberately removed
        # in v0.8 (a control that does nothing gets no control),
        # and the mode is set at creation or by update-project.
        # The row says "Mode", not "MetaMorph mode" (T71: the word
        # "metamorph" never appears in a visible string — the
        # codec does not exist yet, so the window makes no
        # metamorph promise). The running log of the fine-tune
        # lives in Project notes below; these notes say why the
        # mode was picked.
        self.metamorph_mode_label = QLabel("")
        form.addRow("Mode", self.metamorph_mode_label)
        self.metamorph_notes_edit = QPlainTextEdit()
        self.metamorph_notes_edit.setMinimumHeight(60)
        form.addRow("Why this mode", self.metamorph_notes_edit)
        form.addRow(
            "",
            _help_label(
                "Why this mode was picked for this project. The "
                "running log lives in Project notes above."
            ),
        )
        # Status (T53): read-only — training moves it on its own
        # (training, paused, done, failed), GGUF export sets
        # exported, and Mark ready is the one move the user makes
        # (draft -> ready). The button only shows for a draft.
        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel("")
        self.mark_ready_btn = QPushButton("Mark ready")
        self.mark_ready_btn.setToolTip(
            "Mark this project ready to train."
        )
        self.mark_ready_btn.clicked.connect(self.mark_ready)
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.mark_ready_btn)
        status_layout.addStretch(1)
        form.addRow("Status", status_row)
        form.addRow(
            "",
            _help_label(
                "Where this project is: draft, ready, training, "
                "paused, done, failed, or exported."
            ),
        )
        details.content_layout.addLayout(form)
        layout.addWidget(details)
        self.details_section = details

        layout.addStretch(1)

        action_row = QHBoxLayout()
        self.save_btn = QPushButton("Save project")
        self.save_btn.clicked.connect(self.save)
        action_row.addWidget(self.save_btn)
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(
            lambda: self._main.rename_project(self._profile, self._project)
        )
        clone_btn = QPushButton("Clone")
        clone_btn.clicked.connect(
            lambda: self._main.clone_project(self._profile, self._project)
        )
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(
            lambda: self._main.delete_project(self._profile, self._project)
        )
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        action_row.addWidget(rename_btn)
        action_row.addWidget(clone_btn)
        action_row.addWidget(delete_btn)
        action_row.addStretch(1)
        action_row.addWidget(close_btn)
        outer.addLayout(action_row)

        # Dirty tracking (T2): same pattern as ProfileWindow — a
        # snapshot of the loaded values, an asterisk on the title
        # when the form differs, and a Save / Discard / Cancel
        # prompt on close instead of silently dropping edits.
        self._snapshot = None
        self._loading = False
        for signal in (
            self.display_edit.textChanged,
            self.dataset_edit.textChanged,
            self.metamorph_notes_edit.textChanged,
            self.notes_edit.textChanged,
        ):
            signal.connect(self._on_edited)
        # The dataset check runs when the field is left (T45) —
        # never per keystroke: a big file parses once per edit,
        # not once per letter.
        self.dataset_edit.editingFinished.connect(
            self._check_dataset_display
        )
        self._load()
        # Ctrl+S saves here (T82); Tab walks the form in visual order.
        QShortcut(QKeySequence("Ctrl+S"), self, self.save)
        _chain_tab_order([
            self.notes_edit, self.save_notes_btn,
            self.display_edit, self.dataset_edit, self.dataset_browse_btn,
            self.metamorph_notes_edit, self.mark_ready_btn,
            self.save_btn, rename_btn, clone_btn,
            delete_btn, close_btn,
        ])

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
            "metamorph_notes": self.metamorph_notes_edit.toPlainText(),
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
        # The Project notes section header marks unsaved notes (T2).
        self.notes_section.set_title(
            "Project notes (modified)" if self._notes_modified()
            else "Project notes"
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
        # Why this mode (T114): the stored mode as a label, and
        # the metamorph notes — why this mode was picked. A
        # non-text notes value falls back to blank like the rest.
        self.metamorph_mode_label.setText(metamorph_mode(p))
        block = p.get("metamorph")
        mm_notes = block.get("notes", "") if isinstance(block, dict) else ""
        if not isinstance(mm_notes, str):
            mm_notes = ""
            bad.append("why this mode")
        self.metamorph_notes_edit.setPlainText(mm_notes)
        # Status (T53): read-only label, from the stored project;
        # Mark ready only shows for a draft.
        status = p.get("status", "draft")
        self.status_label.setText(status)
        self.mark_ready_btn.setVisible(status == "draft")
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
        self._check_dataset_display()

    def _browse_dataset(self):
        """Pick a dataset file (T45): the picker fills the field,
        and the check below says what the file holds."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a dataset file", str(Path.home()),
            "JSONL datasets (*.jsonl);;All files (*)",
        )
        if not path:
            return
        self.dataset_edit.setText(path)
        self._check_dataset_display()

    def _check_dataset_display(self):
        """Validate the Dataset field and say what it holds (T45):
        a valid file shows its example count, the train/check
        split, and a 3-example preview; a missing file warns
        without blocking; a malformed file names the bad line.
        Runs on load, on browse, when the field is left, and on
        save."""
        from .train import check_dataset

        check = check_dataset(
            self._main.store, self._profile, self._project,
            self.dataset_edit.text(),
        )
        status = check["status"]
        if status == "unset":
            self.dataset_info.setText("")
            self.dataset_info.setVisible(False)
        elif status == "ok":
            lines = [
                f"{check['count']} examples: {check['train']} to train, "
                f"{check['val']} to check.",
            ]
            for i, line in enumerate(check["preview"], 1):
                lines.append(f"{i}. {line}")
            self.dataset_info.setText("\n".join(lines))
            self.dataset_info.setVisible(True)
        elif status == "missing":
            self.dataset_info.setText(
                "Dataset not found. Is the path right?"
            )
            self.dataset_info.setVisible(True)
        else:  # invalid
            self.dataset_info.setText(
                check["error"] or "Not a valid dataset."
            )
            self.dataset_info.setVisible(True)

    def mark_ready(self):
        """Draft -> ready (T53): the only user-driven transition.
        A ready project is one the user says is set to train. The
        form itself is not reloaded, so unsaved edits in it stay
        put — only the status label and button change."""
        try:
            self._main.store.update_project(
                self._profile, self._project, status="ready"
            )
        except StellaError as exc:
            QMessageBox.warning(self, "Stella", str(exc))
            return
        self.status_label.setText("ready")
        self.mark_ready_btn.setVisible(False)
        self._main.refresh_tree()
        self._main.refresh_session()
        self._main._say(f"Project {self._project} is ready to train.")

    def save(self) -> bool:
        """Save the project form. Returns True on success, False when
        nothing was saved (store error). The stored training
        settings are untouched: the backend owns them (T16). A
        missing or malformed dataset warns in the info line (T45)
        but never blocks the save — the file may be created or
        pulled later."""
        self._check_dataset_display()
        try:
            self._main.store.update_project(
                self._profile,
                self._project,
                display_name=self.display_edit.text().strip(),
                dataset_ref=self.dataset_edit.text().strip(),
                # T114: the metamorph notes save with the project.
                # The mode is not passed, so update_project keeps
                # the stored mode — only the notes change.
                metamorph={
                    "notes": self.metamorph_notes_edit.toPlainText(),
                },
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


class TrashDialog(QDialog):
    """Deleted profiles and projects, with the purge action (T23).

    Deleting moves a folder to the trash, dated, with everything
    inside intact — so a misclick is recoverable by moving the
    folder back. This window is where things are deleted FOREVER:
    pick an item and press Delete forever (with its own confirm,
    defaulting to No), or Empty trash for all of them. Nothing is
    selected by default.
    """

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self.setWindowTitle("Trash")
        self.setMinimumWidth(520)
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(
            _help_label(
                "Deleted profiles and projects live here, with "
                "everything inside them. To get one back, move its "
                f"folder back out of {main.store.trash_dir}. "
                "Delete forever removes it for good."
            )
        )
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.list_widget, 1)
        self.empty_label = QLabel("The trash is empty.")
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)

        btns = QHBoxLayout()
        self.purge_btn = QPushButton("Delete forever")
        self.purge_btn.setEnabled(False)
        self.purge_btn.clicked.connect(self._purge_selected)
        self.empty_btn = QPushButton("Empty trash")
        self.empty_btn.clicked.connect(self._empty_trash)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(self.purge_btn)
        btns.addWidget(self.empty_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        layout.addLayout(btns)
        self._refresh()

    def _refresh(self):
        """Rebuild the list from the store. Nothing selected."""
        self.list_widget.clear()
        entries = self._main.store.list_trash()
        for entry in entries:
            if entry["kind"] == "profile":
                what = f"profile {entry['profile']}"
            elif entry["kind"] == "project":
                what = (
                    f"project {entry['project']} "
                    f"(in profile {entry['profile']})"
                )
            else:
                what = entry["name"]
            label = what
            if entry["trashed"]:
                label += f", deleted {entry['trashed']}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry["name"])
            self.list_widget.addItem(item)
        self.empty_label.setVisible(not entries)
        self.list_widget.setVisible(bool(entries))
        self.empty_btn.setEnabled(bool(entries))
        self.purge_btn.setEnabled(False)

    def _on_selection(self):
        self.purge_btn.setEnabled(
            self.list_widget.currentItem() is not None
        )

    def _confirm_purge(self, text: str) -> bool:
        """A destructive confirmation that defaults to No (U23/U31),
        like the delete confirms."""
        box = QMessageBox(self)
        box.setWindowTitle("Delete forever")
        box.setText(text)
        box.setIcon(QMessageBox.Warning)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setEscapeButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def _purge_counts(self, name):
        """What a trashed item holds (T120): (projects,
        checkpoints, noted) counted from the folder, so the purge
        dialog names what is about to be destroyed forever. A
        trashed project counts as one project; a trashed profile
        counts every project inside it."""
        folder = self._main.store.trash_dir / name
        projects = 0
        checkpoints = 0
        noted = 0
        if not folder.is_dir():
            return projects, checkpoints, noted
        for manifest in folder.rglob("project.json"):
            projects += 1
            pdir = manifest.parent
            ckpts = pdir / "checkpoints"
            if ckpts.is_dir():
                checkpoints += sum(
                    1 for d in ckpts.iterdir() if d.is_dir()
                )
            if (pdir / "notes.md").is_file():
                noted += 1
        return projects, checkpoints, noted

    def _purge_selected(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        name = item.data(Qt.UserRole)
        label = item.text()
        projects, checkpoints, noted = self._purge_counts(name)
        goes = []
        if projects > 1:
            goes.append(f"{projects} projects")
        if checkpoints:
            goes.append(
                f"{checkpoints} checkpoint"
                f"{'s' if checkpoints != 1 else ''}"
            )
        if noted:
            goes.append(
                "notes"
                if noted == 1
                else f"notes for {noted} projects"
            )
        detail = f" That destroys {', '.join(goes)}." if goes else ""
        if not self._confirm_purge(
            f"Delete {label} forever?{detail} This cannot be undone."
        ):
            return
        try:
            self._main.store.purge_trash(name)
        except StellaError as exc:
            QMessageBox.warning(self, "Stella", str(exc))
            return
        self._main.debug_log.action(f"trash purged: {name}")
        self._refresh()

    def _empty_trash(self):
        count = len(self._main.store.list_trash())
        if not self._confirm_purge(
            f"Delete everything in the trash forever "
            f"({count} item{'s' if count != 1 else ''})? "
            "This cannot be undone."
        ):
            return
        count = self._main.store.empty_trash()
        self._main.debug_log.action(f"trash emptied: {count} items")
        self._refresh()


class SettingsWindow(QDialog):
    """Settings, in its own window. Only settings that exist are
    shown: where Stella keeps its files, whether Ollama is answering,
    the chat model, the AI providers, and ease of use (less motion,
    larger text). Training settings are not here (T16): the backend
    measures the PC and picks them, so the user never sees them."""

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        # Every section is a collapsible group (T80, entry 012), so
        # the 1,165 px wall becomes five headers the user opens as
        # needed. The action row (Debug report, Close) stays pinned
        # underneath, reachable without scrolling the whole form.
        self.resize(560, 680)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.sections: dict[str, CollapsibleSection] = {}

        def section(title: str) -> QVBoxLayout:
            part = CollapsibleSection(title)
            self.sections[title] = part
            layout.addWidget(part)
            return part.content_layout

        home = section("Where Stella keeps things")
        self.home_label = QLabel(str(main.store.home))
        self.home_label.setWordWrap(True)
        self.home_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        home.addWidget(self.home_label)
        home.addWidget(
            _help_label("Your profiles and projects live here.")
        )

        ollama = section("Ollama")
        self.ollama_host = QLabel(f"Host: {ollama_url()}")
        self.ollama_host.setWordWrap(True)
        ollama.addWidget(self.ollama_host)
        self.ollama_status = QLabel("")
        self.ollama_status.setWordWrap(True)
        ollama.addWidget(self.ollama_status)
        refresh_btn = QPushButton("Refresh Ollama status")
        refresh_btn.clicked.connect(self.refresh_ollama_status)
        ollama.addWidget(refresh_btn)
        ollama.addWidget(
            _help_label(
                "Ollama runs the models on this PC. Stella uses it for "
                "dreaming and the refusal probe, not for training."
            )
        )

        chat = section("Chat model")
        self.chat_combo = QComboBox()
        self.chat_combo.setPlaceholderText("Pick a model for chat")
        self.chat_combo.currentIndexChanged.connect(self._on_chat_model_changed)
        chat.addWidget(self.chat_combo)
        chat.addWidget(
            _help_label(
                "The model the Chat window talks to. Models on this PC "
                "run through Ollama. Groq and Gemini models need a key, "
                "added below under AI providers: greyed out models need "
                "a key first. Nothing is picked until you pick one."
            )
        )
        self._load_chat_models()

        providers = section("AI providers")
        self._key_fields: dict[str, QLineEdit] = {}
        self._key_status: dict[str, QLabel] = {}
        self._provider_buttons: dict[str, dict[str, QPushButton]] = {}
        self._test_workers: dict[str, JobWorker] = {}
        self._custom_base = QLineEdit()
        self._custom_model = QLineEdit()
        self._build_provider_rows(providers)
        providers.addWidget(
            _help_label(
                "Your keys stay on this PC in a private file. They only "
                "leave the PC to talk to that provider, and never appear "
                "in a debug report."
            )
        )

        # Ease of use (T147): less motion, larger text. Plain words,
        # saved in QSettings, applied at once.
        ease = section("Ease of use")
        self.reduced_motion_check = QCheckBox(
            "Less motion: buttons and cards change at once, "
            "with no animation."
        )
        self.reduced_motion_check.setChecked(
            self._main.settings.value(
                "accessibility/reduced_motion", False, type=bool
            )
        )
        self.reduced_motion_check.toggled.connect(
            self._on_reduced_motion_toggled
        )
        ease.addWidget(self.reduced_motion_check)
        self.larger_text_check = QCheckBox(
            "Larger text: bigger words everywhere."
        )
        self.larger_text_check.setChecked(
            self._main.settings.value(
                "accessibility/larger_text", False, type=bool
            )
        )
        self.larger_text_check.toggled.connect(
            self._on_larger_text_toggled
        )
        ease.addWidget(self.larger_text_check)
        layout.addStretch(1)

        action_row = QHBoxLayout()
        self.debug_btn = QPushButton("Write debug report")
        self.debug_btn.setToolTip(
            "Writes a report file with the recent log and the app "
            "state. Secrets are scrubbed out."
        )
        self.debug_btn.clicked.connect(self._on_debug_report)
        action_row.addWidget(self.debug_btn)
        action_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        action_row.addWidget(close_btn)
        outer.addLayout(action_row)

        # Tab walks the window in visual order (T82).
        chain: list = [
            refresh_btn, self.chat_combo,
        ]
        for pid in ("groq", "gemini"):
            chain.append(self._key_fields[pid])
            buttons = self._provider_buttons[pid]
            chain += [buttons["save"], buttons["test"], buttons["remove"]]
        chain += [
            self._custom_base, self._custom_model,
            self._key_fields["custom"],
        ]
        custom_buttons = self._provider_buttons["custom"]
        chain += [
            custom_buttons["save"], custom_buttons["test"],
            custom_buttons["remove"],
            self.reduced_motion_check, self.larger_text_check,
            self.debug_btn, close_btn,
        ]
        _chain_tab_order(chain)

        self.refresh_ollama_status()

    def _on_reduced_motion_toggled(self, checked: bool):
        """The Less motion preset (T147): writes the setting and
        applies it at once — the dip, the morph, and the finish
        moment all read the flag live."""
        self._main.settings.setValue("accessibility/reduced_motion", checked)
        set_reduced_motion(checked)

    def _on_larger_text_toggled(self, checked: bool):
        """The Larger text preset (T147): writes the setting and
        applies it at once."""
        self._main.settings.setValue("accessibility/larger_text", checked)
        apply_text_size(QApplication.instance(), checked)

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

        def _run(ctx):
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
        """Refresh the Ollama status, without blocking (T146):
        the label says Checking... at once, and the background
        refresh updates it from the cache when it lands. The old
        version called check_ollama here, on the UI thread — a
        hung Ollama froze Settings for the whole timeout."""
        self.ollama_status.setText("Status: Checking...")
        self._main.refresh_model_list()
        self._load_chat_models()

    def _on_models_refreshed(self):
        """A background model-list refresh landed (T43/T146): the
        status line and the chat list re-read it from the cache.
        The status words match check_ollama's, so the line reads
        the same as it did when it was a blocking call."""
        models, _sizes, _loaded, ollama_up, _at = MODEL_CACHE.snapshot()
        if ollama_up:
            if models:
                status = (
                    f"running ({len(models)} model(s): "
                    f"{', '.join(models)})"
                )
            else:
                status = "running (no models loaded)"
        else:
            status = f"not reachable at {ollama_url()}"
        self.ollama_status.setText(f"Status: {status}")
        self._load_chat_models()

    def _load_chat_models(self):
        """Fill the chat-model list, grouped by provider: models on
        this PC (Ollama) first, then Groq, Gemini, and Custom. A
        provider with no key saved shows its models greyed out.
        Nothing is selected by default: the saved pick is restored,
        or the box stays blank until the user picks one. The Ollama
        rows come from the cache (T43): no fetch, so opening
        Settings never waits on Ollama."""
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
            for name in MODEL_CACHE.models():
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
        # T193: a search box over the topics — thirteen topics in
        # a plain list is a lot to scan. Typing narrows the list
        # by title or body; clearing it shows all of them again.
        # Nothing is selected by default, and filtering never
        # picks a topic for the user.
        left = QVBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search the guide...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search)
        left.addWidget(self.search_box)
        self.topic_list = QListWidget()
        self.topic_list.addItems(topic_titles())
        self.topic_list.currentItemChanged.connect(self._on_topic)
        left.addWidget(self.topic_list, 1)
        layout.addLayout(left, 1)
        self.content = QTextBrowser()
        self.content.setPlainText(
            "Pick a topic on the left to read how it works."
        )
        layout.addWidget(self.content, 2)
        _chain_tab_order([self.search_box, self.topic_list, self.content])

    def _on_search(self, text):
        needle = text.strip().lower()
        for row in range(self.topic_list.count()):
            item = self.topic_list.item(row)
            title = item.text()
            body = topic_text(title) or ""
            match = (
                not needle
                or needle in title.lower()
                or needle in body.lower()
            )
            self.topic_list.setRowHidden(row, not match)

    def show_topic(self, title):
        """Open the guide on one topic (T193): the empty state's
        Getting started link lands here."""
        self.search_box.clear()
        rows = self.topic_list.findItems(title, Qt.MatchExactly)
        if rows:
            self.topic_list.setCurrentRow(self.topic_list.row(rows[0]))

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
    token = Signal(str)
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
            on_token=self.token.emit,
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
        self._streaming = False
        self.setWindowTitle("Chat with Stella")
        # T194: 700x560, not 700x520 — at 520 the help line at the
        # bottom rendered 30px tall against a 45px need, clipped
        # by a line. The extra 40px gives it room.
        self.resize(700, 560)
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

        # Click-to-pick model buttons (T76): when no chat model is
        # picked, the installed models appear as buttons here — no
        # typing a tag by hand. Hidden once a model is picked.
        self.model_pick_scroll = QScrollArea()
        self.model_pick_scroll.setWidgetResizable(True)
        self.model_pick_scroll.setMaximumHeight(180)
        model_pick_body = QWidget()
        self.model_pick_layout = QVBoxLayout(model_pick_body)
        self.model_pick_scroll.setWidget(model_pick_body)
        self.model_pick_scroll.setVisible(False)
        layout.addWidget(self.model_pick_scroll)
        self.model_buttons: list[QPushButton] = []

        # The plan row (T76): when the agent shows a plan, Run and
        # Cancel sit here. Run sends "go ahead", Cancel sends
        # "cancel" — the same words the user could type.
        self.plan_row = QWidget()
        plan_layout = QHBoxLayout(self.plan_row)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        self.plan_run_btn = QPushButton("Run")
        self.plan_run_btn.setToolTip("Run the plan Stella showed.")
        self.plan_run_btn.clicked.connect(self._on_plan_run)
        self.plan_cancel_btn = QPushButton("Cancel")
        self.plan_cancel_btn.clicked.connect(self._on_plan_cancel)
        plan_layout.addWidget(self.plan_run_btn)
        plan_layout.addWidget(self.plan_cancel_btn)
        plan_layout.addStretch(1)
        self.plan_row.setVisible(False)
        layout.addWidget(self.plan_row)

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
        # T194: the help line, shortened to two sentences (the
        # greeting above already says the chat sets up and runs
        # training) so it fits its two lines at the default size.
        self.help_label = _help_label(
            "The chat talks to the model you pick in Settings: a "
            "model on this PC through Ollama, or Groq or Gemini "
            "with your key. Say just do it and it shows the plan "
            "first, then runs it when you say go ahead."
        )
        layout.addWidget(self.help_label)
        _chain_tab_order([self.messages, self.input, self.send_btn,
                          self.cancel_btn])
        self._append(
            "Stella",
            "Hi. Tell me what you want to train, and I will set it up "
            "and run it for you. Or say just do it and I will show "
            "you the plan first, then run the whole thing when you "
            "say go ahead.",
        )
        if not self._main.chat_model:
            self._ask_for_model()

    # -- messages ---------------------------------------------------
    def _append(self, who: str, text: str):
        self._streaming = False
        self.messages.append(f"{who}: {text}")
        self.messages.append("")

    def _append_plain(self, text: str):
        self._streaming = False
        self.messages.append(text)

    def _append_token(self, text: str):
        """One streamed piece of a reply (T76, entry 010): it lands
        in the live "Stella: ..." paragraph as it arrives, instead
        of waiting for the whole reply."""
        cursor = self.messages.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self._streaming:
            self._streaming = True
            if cursor.block().text().strip():
                cursor.insertBlock()
            cursor.insertText("Stella: ")
        cursor.insertText(text)
        self.messages.setTextCursor(cursor)
        self.messages.ensureCursorVisible()

    def _set_activity(self, busy: bool, text: str):
        color = "#4caf50" if busy else "#888888"
        self.activity_dot.setStyleSheet(
            f"color: {color}; font-size: 14px;"
        )
        self.activity_text.setText(text)

    # -- chat model -------------------------------------------------
    def _ask_for_model(self):
        models, _sizes, loaded, _up, _at = MODEL_CACHE.snapshot()
        if not loaded:
            # The first refresh is still in flight: say so, and the
            # buttons arrive when it lands (T43/T146).
            self._awaiting_model = True
            self._append(
                "Stella", "Looking for the models on this PC..."
            )
            self._main.refresh_model_list()
            return
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
            "Which model should I chat with? Pick one below.\n\n"
            "You can also pick a Groq or Gemini model in "
            "Settings, under AI providers.",
        )
        self._show_model_buttons(models)

    def _on_models_refreshed(self):
        """A background model-list refresh landed (T43): if the chat
        was still looking for models, show them now (or say Ollama
        is not answering). A refresh landing after the buttons are
        already up changes nothing."""
        if self._awaiting_model and not self.model_buttons:
            self._ask_for_model()

    def _show_model_buttons(self, models):
        """One button per installed model (T76): click to pick, no
        typing a tag by hand. Any old buttons go first, so asking
        twice never doubles the list."""
        for btn in self.model_buttons:
            self.model_pick_layout.removeWidget(btn)
            btn.deleteLater()
        self.model_buttons = []
        for name in models:
            btn = QPushButton(name)
            btn.clicked.connect(
                lambda _checked=False, n=name: self._pick_chat_model(n)
            )
            self.model_pick_layout.addWidget(btn)
            self.model_buttons.append(btn)
        self.model_pick_scroll.setVisible(True)
        if self.model_buttons:
            _chain_tab_order(
                [*self.model_buttons, self.input]
            )

    def _pick_chat_model(self, name: str):
        """A model button was clicked: chat with that model."""
        self._awaiting_model = False
        self.model_pick_scroll.setVisible(False)
        self._main.set_chat_provider("ollama")
        self._main.set_chat_model(name)
        self._append(
            "Stella",
            f"Got it, I will chat with {name}. What do you want "
            "to train?",
        )

    def _match_model(self, text: str) -> tuple[str, str] | None:
        """The user's reply, matched against the models the chat can
        use: installed Ollama models first, then cloud models with a
        saved key. Returns (provider, model), or None."""
        cleaned = text.strip().lower()
        # The cached list (T43): matching typed text never fetches.
        models = MODEL_CACHE.models()
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
                    "I did not find that model. Pick one of the "
                    "buttons above, or type one of the names.",
                )
                return
            self._awaiting_model = False
            self.model_pick_scroll.setVisible(False)
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
        self._worker.token.connect(self._append_token)
        self._worker.reply.connect(self._on_reply)
        self.send_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._set_activity(True, "Thinking...")
        self._worker.start()

    def _on_plan_run(self):
        """Run the shown plan: the same words as typing go ahead."""
        if self._worker is not None and self._worker.isRunning():
            return
        self.input.setText("Go ahead")
        self._on_send()

    def _on_plan_cancel(self):
        """Cancel the shown plan: the same words as typing cancel."""
        if self._worker is not None and self._worker.isRunning():
            return
        self.input.setText("Cancel")
        self._on_send()

    def _on_reply(self, text: str):
        # A reply that already streamed in live is on screen: just
        # close its paragraph instead of showing it twice (T76).
        streamed = getattr(self._agent, "last_streamed_plain", "") or ""
        if self._streaming and streamed and streamed == text.strip():
            self.messages.append("")
        else:
            self._append("Stella", text)
        self._streaming = False
        self.send_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._set_activity(False, "Idle")
        self._worker = None
        # A pending plan shows its Run and Cancel buttons (T76).
        pending = getattr(self._agent, "pending_plan", None)
        self.plan_row.setVisible(pending is not None)
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
        self._model_worker: ModelListWorker | None = None
        self._fill_teacher_combo()
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
        self.start_btn.setToolTip(
            "Start teaching: the teacher answers your prompts, "
            "and its answers become the examples."
        )
        self.start_btn.setDefault(True)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)
        _chain_tab_order([
            self.teacher_combo, self.prompts_btn,
            self.start_btn, self.cancel_btn,
        ])

    def _fill_teacher_combo(self):
        """Fill the teacher combo from the cached model list (T43):
        no fetch. When the cache has not loaded yet, a background
        refresh fills it when it lands."""
        models = MODEL_CACHE.models()
        current = self.teacher_combo.currentText()
        self.teacher_combo.blockSignals(True)
        try:
            self.teacher_combo.clear()
            if models:
                self.teacher_combo.addItems(models)
            if current:
                self.teacher_combo.setCurrentText(current)
        finally:
            self.teacher_combo.blockSignals(False)
        if not MODEL_CACHE.loaded:
            self._refresh_models()

    def _refresh_models(self):
        """A background refresh of the cached list (T43): the combo
        refills when it lands; nothing blocks meanwhile."""
        if self._model_worker is not None and self._model_worker.isRunning():
            return
        worker = ModelListWorker(self)
        worker.refreshed.connect(lambda *_a: self._fill_teacher_combo())
        worker.finished.connect(self._on_model_worker_finished)
        self._model_worker = worker
        worker.start()

    def _on_model_worker_finished(self):
        if self._model_worker is self.sender():
            self._model_worker = None

    def closeEvent(self, event):
        # A refresh still running when the dialog closes must finish
        # first: a QThread destroyed while running aborts the app.
        if self._model_worker is not None and self._model_worker.isRunning():
            self._model_worker.wait(5000)
        super().closeEvent(event)

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


class ImportPreviewDialog(QDialog):
    """The import preview (T58): what the package is, what it
    carries, and what would change here — before anything is
    imported. Import goes ahead; Cancel imports nothing. When the
    profile already exists and differs, the merge choice is here
    too: neither radio is checked by default, and not picking
    keeps yours. T173: an adapter package also offers importing
    into the current project (into_option) instead of a new
    one."""

    def __init__(self, parent, summary: dict, into_option=None):
        super().__init__(parent)
        self.setWindowTitle("Import this package?")
        self._summary = summary
        layout = QVBoxLayout(self)
        summary_label = QLabel(export_mod.format_preview(summary))
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)
        self._into_checkbox = None
        self._into_option = into_option
        if into_option is not None:
            profile, project = into_option
            self._into_checkbox = QCheckBox(
                f"Import into the current project '{project}' "
                "instead of a new one."
            )
            layout.addWidget(self._into_checkbox)
        self._keep_radio = None
        self._take_radio = None
        if summary.get("profile_diff"):
            layout.addWidget(QLabel("Keep yours, or use the package's?"))
            self._keep_radio = QRadioButton("Keep mine")
            self._take_radio = QRadioButton("Use the package's")
            layout.addWidget(self._keep_radio)
            layout.addWidget(self._take_radio)
            layout.addWidget(QLabel("If you do not pick, yours is kept."))
        row = QHBoxLayout()
        self.confirm_btn = QPushButton("Import")
        self.confirm_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(self.confirm_btn)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)
        self.resize(520, 320)

    def profile_choice(self):
        """The merge choice: "take" only when the take radio is
        checked; "keep" when the radios were shown and take was
        not picked; None when there was no diff to choose over —
        so the import's own conflict callback still stands as the
        backstop."""
        if self._take_radio is None:
            return None
        return "take" if self._take_radio.isChecked() else "keep"

    def into_project(self):
        """The adapter import's into-current-project choice
        (T173): the (profile, project) tuple when the checkbox
        was offered and ticked, else None."""
        if (
            self._into_checkbox is not None
            and self._into_checkbox.isChecked()
        ):
            return self._into_option
        return None


class ProbeResultsDialog(QDialog):
    """The probe evidence (T94): every prompt's reply + refused
    flag, before and after side by side, with the gate verdict —
    the numbers behind the one-line summary, one click away. The
    before/after preview before export (T148) REUSES this dialog
    instead of building a second side-by-side view: export mode
    swaps the Close button for Export / Go back.

    The mode comes from the saved result (T90): a "gate" run shows
    the gate verdict; an "informational" run shows no verdict at
    all, only the counts and the change. A result saved before
    v0.16 has no mode key and reads as a gate run — every probe
    before v0.16 was one."""

    def __init__(self, parent, result: dict, *, export_mode: bool = False,
                 estimate_text: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(
            "Before you export: what the tune changed"
            if export_mode
            else "Refusal probe results"
        )
        self._result = result
        before = result.get("before") or {}
        after = result.get("after") or {}
        layout = QVBoxLayout(self)
        self.counts_label = QLabel(
            f"Refusals: {before.get('refusals', 0)}/"
            f"{before.get('total', 0)} before, "
            f"{after.get('refusals', 0)}/{after.get('total', 0)} after "
            f"(change {result.get('delta', 0):+.0%})."
        )
        self.counts_label.setWordWrap(True)
        layout.addWidget(self.counts_label)
        self.set_label = None
        if result.get("probe_set"):
            # T174: which probe set ran (the profile's role set,
            # or the default set when it had none).
            self.set_label = QLabel(
                f"Probe set: {result['probe_set']} "
                f"({before.get('total', 0)} prompts)."
            )
            self.set_label.setWordWrap(True)
            layout.addWidget(self.set_label)
        if result.get("mode", "gate") == "informational":
            verdict_text = (
                "Informational only: this probe does not pass or "
                "fail anything. Read the counts as a signal."
            )
        else:
            from .probe import probe_gate

            _passed, verdict_text = probe_gate(result)
        self.verdict_label = QLabel(verdict_text)
        self.verdict_label.setWordWrap(True)
        layout.addWidget(self.verdict_label)
        if export_mode:
            note = QLabel(
                "Read what changed, then export or go back. "
                "Exporting does not run the probe again."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            if estimate_text:
                # The export estimate (T153), at the commit point:
                # what the export will cost, next to the Export
                # button itself.
                self.estimate_label = QLabel(estimate_text)
                self.estimate_label.setWordWrap(True)
                layout.addWidget(self.estimate_label)
        before_details = before.get("details") or []
        after_details = after.get("details") or []
        rows = max(len(before_details), len(after_details))
        self.table = QTableWidget(rows, 5)
        self.table.setHorizontalHeaderLabels([
            "Prompt", "Before", "Refused", "After", "Refused",
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self.table.setWordWrap(True)
        for i in range(rows):
            b = before_details[i] if i < len(before_details) else {}
            a = after_details[i] if i < len(after_details) else {}
            prompt = b.get("prompt") or a.get("prompt") or ""
            self.table.setItem(i, 0, QTableWidgetItem(prompt))
            self.table.setItem(
                i, 1, QTableWidgetItem(self._reply_text(b))
            )
            self.table.setItem(
                i, 2, QTableWidgetItem(self._flag_text(b))
            )
            self.table.setItem(
                i, 3, QTableWidgetItem(self._reply_text(a))
            )
            self.table.setItem(
                i, 4, QTableWidgetItem(self._flag_text(a))
            )
        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        if export_mode:
            self.export_btn = QPushButton("Export")
            self.export_btn.clicked.connect(self.accept)
            self.go_back_btn = QPushButton("Go back")
            self.go_back_btn.clicked.connect(self.reject)
            row.addWidget(self.export_btn)
            row.addWidget(self.go_back_btn)
        else:
            self.close_btn = QPushButton("Close")
            self.close_btn.clicked.connect(self.accept)
            row.addWidget(self.close_btn)
        layout.addLayout(row)
        self.resize(900, 540)

    @staticmethod
    def _reply_text(detail: dict) -> str:
        """The reply cell: the reply itself, or "(no answer)" for
        a silent prompt (T30) — a blank cell would read as missing
        data, and a silent model is evidence, not a gap."""
        if detail.get("empty"):
            return "(no answer)"
        return detail.get("reply") or ""

    @staticmethod
    def _flag_text(detail: dict) -> str:
        if detail.get("empty"):
            return "No answer"
        return "Refused" if detail.get("refused") else "Answered"


class NewProjectDialog(QDialog):
    """New project (T112): a name, and a template picker. The
    picker shows template names and plain-words descriptions only
    — never training settings (T16). The first entry is "No
    template: start blank", and nothing is selected by default
    beyond that blank start."""

    def __init__(self, parent, templates):
        super().__init__(parent)
        self.setWindowTitle("New project")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Project name (lowercase, dashes ok):"))
        self.name_edit = QLineEdit()
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("Start from a template (optional):"))
        self.template_combo = QComboBox()
        self.template_combo.addItem("No template: start blank", None)
        self._descriptions = {None: ""}
        for template in templates:
            self.template_combo.addItem(
                template.get("title", template["name"]),
                template["name"],
            )
            self._descriptions[template["name"]] = (
                template.get("description", "")
            )
        self.template_combo.currentIndexChanged.connect(
            self._on_template_changed
        )
        layout.addWidget(self.template_combo)
        self.description_label = QLabel("")
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_template_changed(self, _index):
        self.description_label.setText(
            self._descriptions.get(
                self.template_combo.currentData(), ""
            )
        )

    def project_name(self) -> str:
        return self.name_edit.text().strip()

    def template_name(self):
        return self.template_combo.currentData()


def _import_message(result: dict) -> str:
    """The import confirmation (T57/T86/T117): what landed, whether
    the profile already existed, whether the profile now uses the
    package's values, and what a collision did. One line, said
    last (T50)."""
    if "projects" in result:
        # A profile package (T86).
        names = result["projects"]
        if names:
            message = (
                f"Imported profile {result['profile']} with "
                f"{len(names)} project"
                f"{'s' if len(names) != 1 else ''}: "
                f"{', '.join(names)}."
            )
        else:
            message = (
                f"Imported profile {result['profile']} "
                "(no projects)."
            )
    elif "adapter" in result:
        # An adapter package (T173): into an existing project, or
        # as a new project built around the weights.
        if result.get("into_existing"):
            message = (
                f"Imported adapter {result['adapter']} into "
                f"project {result['project']}."
            )
        else:
            message = (
                f"Imported adapter {result['adapter']} as new "
                f"project {result['project']} in "
                f"{result['profile']}."
            )
            if result.get("copy_of"):
                message += (
                    f" (a copy of {result['copy_of']!r} - the "
                    "name was taken)."
                )
    else:
        message = (
            f"Imported {result['project']} into {result['profile']}."
        )
        if result.get("collision") == "copy":
            message = (
                f"Imported {result['project']} into "
                f"{result['profile']} (a copy of "
                f"{result.get('copy_of', '')!r})."
            )
        elif result.get("collision") == "replace":
            message += " The old project went to the trash."
    if result.get("profile_existed"):
        message += " The profile already existed."
    if result.get("profile_choice") == "take":
        fields = export_mod.describe_profile_diff(
            result.get("profile_diff") or {}
        )
        message += f" The profile now uses the package's {fields}."
    missing = result.get("datasets_missing") or []
    if missing:
        message += (
            f" {len(missing)} project"
            f"{'s' if len(missing) != 1 else ''} "
            "have datasets not on this PC."
        )
    return message


def _stella_icon(path: Path | None = None) -> QIcon:
    """The window icon (T127): the shipped star art, guarded —
    a missing file gives a null icon instead of a crash, so the
    window still opens on a tree without the asset. `path` is a
    test hook for the missing-file branch."""
    icon_path = (
        path
        if path is not None
        else Path(__file__).resolve().parent.parent / "assets" / "stella.png"
    )
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self, store: Store | None = None, settings=None):
        super().__init__()
        self.store = store or Store()
        # Tests pass a QSettings on a temp file; the real app uses
        # the shared BrokeNBored/Stella settings.
        self.settings = settings or QSettings("BrokeNBored", "Stella")
        # Accessibility presets (T147): applied from the saved
        # settings before anything shows, so a returning user gets
        # their less-motion / larger-text window at once.
        set_reduced_motion(
            self.settings.value(
                "accessibility/reduced_motion", False, type=bool
            )
        )
        apply_text_size(
            QApplication.instance(),
            self.settings.value(
                "accessibility/larger_text", False, type=bool
            ),
        )
        self.setWindowTitle(
            f"STELLA {STELLA_VERSION}: fine-tune models on your PC"
        )
        self.setWindowIcon(_stella_icon())
        self.resize(1100, 680)
        self.setMinimumSize(900, 540)
        self._current_profile: str | None = None
        self._current_project: str | None = None
        self._train_panel_project: tuple | None = None
        # The past runs the history list shows (T151): list_runs
        # output for the panel's project, so a click can find its
        # run's curve without re-reading the log.
        self._run_history: list = []
        # The project a train/sleep run belongs to (T47): while a
        # run is live, the Train panel stays pinned to it even when
        # the session moves on. (profile, project), or None.
        self._running_job_key: tuple | None = None
        self._building = False
        # Live-run stats for the glanceable card (T20): when the
        # current run's first live point arrived, and which step it
        # was, so speed and time left are measured, not guessed.
        self._run_started_at: float | None = None
        self._run_start_step = 0
        self._train_worker: TrainWorker | None = None
        self._sleep_worker: SleepWorker | None = None
        self._job_worker: JobWorker | None = None
        # The running probe's job (T90/T94): which project it
        # probed, and whether it was informational — the finish
        # slot opens the results dialog for that project, with or
        # without a gate verdict. Cleared when the dialog opens.
        self._probe_job_key: tuple | None = None
        self._probe_informational: bool = False
        # The estimate label's cache (T84): the last computed
        # text, keyed by what it was computed from. refresh_session
        # runs often; the estimate only recomputes when the model
        # or dataset changed.
        self._estimate_cache_key: tuple | None = None
        self._estimate_cache_text: str = ""
        # The running job worker's card title (T29): the refusal
        # message names the running job, and a title is what the
        # user recognizes ("Refusal probe", not "a job").
        self._job_title: str | None = None
        # Closing while a job runs (T36): the first close asks the
        # workers to stop and waits with feedback; _closing is True
        # until they have ended and the window closes for real.
        self._closing = False
        self._close_timer = None
        self._profile_windows: dict[str, ProfileWindow] = {}
        self._project_windows: dict[tuple, ProjectWindow] = {}
        self._settings_window: SettingsWindow | None = None
        self._howto_window: HowToUseWindow | None = None
        self._chat_window: ChatWindow | None = None
        self._tree_profiles: dict[str, QTreeWidgetItem] = {}
        self._tree_projects: dict[tuple, QTreeWidgetItem] = {}
        self._download_profile: str | None = None
        # The model-list refresh worker (T43): one fetch at startup,
        # then on demand only. The worker is tracked so close waits
        # for it (a QThread destroyed while running aborts the app).
        self._model_list_worker: ModelListWorker | None = None

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
        # T126: restoreState brings back the saved collapsible
        # flag too, so a state saved before v0.19.0 would re-enable
        # collapsing the panes. Re-assert it after the restore.
        self.splitter.setChildrenCollapsible(False)
        # The one startup fetch (T43): the model list loads in the
        # background before the first refresh_tree, so the health
        # badges read the cache instead of making their own fetch.
        self.refresh_model_list()
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
        # Ctrl+S saves any open edit window (T82).
        QShortcut(QKeySequence("Ctrl+S"), self, self._save_open_windows)
        # F2 renames the picked tree row (T168): double-click keeps
        # opening the detail window, so rename lives on F2 and the
        # right-click menu instead.
        QShortcut(QKeySequence("F2"), self, self._rename_current_row)

    # -- layout -----------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        self._build_menu_bar()

        header_row = QHBoxLayout()
        # T190: one tagline everywhere — the header carries the
        # same line as the window title ("fine-tune models on
        # your PC"); the title keeps the version number.
        self.header_label = QLabel("STELLA: fine-tune models on your PC")
        header = self.header_label
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
        # T180: search, filter, and sort for the profile list. The
        # filter box matches display name, slug, role, and tag; the
        # role filter shows only that role; the sort picker orders
        # the list (name is the default — the old filesystem order
        # is gone). Filtering keeps the selection when the selected
        # profile still matches.
        self.tree_filter = QLineEdit()
        self.tree_filter.setPlaceholderText("Filter profiles...")
        self.tree_filter.setClearButtonEnabled(True)
        self.tree_filter.textChanged.connect(self._on_tree_filter_changed)
        left_layout.addWidget(self.tree_filter)
        filter_row = QHBoxLayout()
        self.tree_role_filter = QComboBox()
        self.tree_role_filter.addItem("All roles")
        for role in CANONICAL_ROLES:
            self.tree_role_filter.addItem(role)
        self.tree_role_filter.currentIndexChanged.connect(
            self._on_tree_filter_changed
        )
        filter_row.addWidget(self.tree_role_filter)
        self.tree_sort = QComboBox()
        self.tree_sort.addItems(
            ["Name", "Role", "Recently used", "Project count"]
        )
        self.tree_sort.currentIndexChanged.connect(
            self._on_tree_filter_changed
        )
        filter_row.addWidget(self.tree_sort)
        left_layout.addLayout(filter_row)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        # T181: multi-select (Ctrl/Shift-click) for bulk actions.
        # Single-click selection and the current-item session
        # behave exactly as before — ExtendedSelection only adds
        # the multi-pick.
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.currentItemChanged.connect(self._on_tree_current_changed)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_clicked)
        # Right-click renames the row (T168): the menu is built per
        # row, so a damaged row (which double-click repairs) gets
        # no Rename.
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(
            self._on_tree_context_menu
        )
        left_layout.addWidget(self.tree, 1)
        # The empty-list hint (T124): one line saying what to do
        # next, shown only when the tree has nothing to show —
        # an empty store, or a profile with no projects.
        self.tree_hint = QLabel("")
        self.tree_hint.setWordWrap(True)
        self.tree_hint.setVisible(False)
        # T193: the empty-state hint links to Getting started.
        self.tree_hint.setTextFormat(Qt.RichText)
        self.tree_hint.setOpenExternalLinks(False)
        self.tree_hint.linkActivated.connect(self._on_tree_hint_link)
        left_layout.addWidget(self.tree_hint)
        self.splitter.addWidget(left)

        # Main area: the current training session (scrollable).
        self.session_scroll = QScrollArea()
        self.session_scroll.setWidgetResizable(True)
        session = QWidget()
        self.session_layout = QVBoxLayout(session)
        self.session_scroll.setWidget(session)
        self._build_session()
        self.splitter.addWidget(self.session_scroll)
        self._set_tab_order()
        # A wider tree pane (T78): long model names get more room
        # before they truncate, and every row carries its full text
        # as a tooltip besides.
        self.splitter.setSizes([340, 760])
        # Honest minimums (T126): the panes cannot be dragged
        # away — the tree keeps room for a readable row, the
        # session keeps room for the hero tile — and the splitter
        # refuses to collapse a pane entirely.
        left.setMinimumWidth(200)
        self.session_scroll.setMinimumWidth(480)
        self.splitter.setChildrenCollapsible(False)
        self.statusBar().showMessage("Stella ready.")

    def _build_menu_bar(self):
        """A real menu bar (T19, U38): File, View, Help. The Menu
        button is gone. Actions that need a selection start disabled
        and are refreshed by _refresh_menu_state; nothing answers
        with a "pick one first" modal anymore. Shortcuts (T82) ride
        on the actions, so the menu shows them."""
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        self._menu_action_new_profile = file_menu.addAction(
            "New profile...", self.new_profile
        )
        self._menu_action_new_profile.setShortcut("Ctrl+N")
        self._menu_action_new_project = file_menu.addAction(
            "New project...", self.new_project
        )
        self._menu_action_new_project.setShortcut("Ctrl+Shift+N")
        self._menu_action_export = file_menu.addAction(
            "Export project...", self.export_project
        )
        # T171: the same exports as a single .stella file.
        self._menu_action_export_project_zip = file_menu.addAction(
            "Export project as single file...",
            lambda: self.export_project(as_zip=True),
        )
        # T86: a whole profile (optionally with its projects) exports
        # as one package, and T105 checks a package without
        # importing it.
        self._menu_action_export_profile = file_menu.addAction(
            "Export profile...", self.export_profile
        )
        self._menu_action_export_profile_zip = file_menu.addAction(
            "Export profile as single file...",
            lambda: self.export_profile(as_zip=True),
        )
        # T170: a recipe (settings only, no weights); T173: a bare
        # adapter.
        self._menu_action_export_recipe = file_menu.addAction(
            "Export recipe...", self.export_recipe
        )
        self._menu_action_export_adapter = file_menu.addAction(
            "Export adapter...", self.export_adapter
        )
        self._menu_action_import = file_menu.addAction(
            "Import package...", self.import_package
        )
        self._menu_action_import_zip = file_menu.addAction(
            "Import single-file package...",
            self.import_single_file_package,
        )
        self._menu_action_check = file_menu.addAction(
            "Check package...", self.check_package
        )
        self._menu_action_run = file_menu.addAction(
            "Run the picked job", self._on_go
        )
        self._menu_action_run.setShortcut("Ctrl+G")
        file_menu.addSeparator()
        self._menu_action_settings = file_menu.addAction(
            "Settings...", self.open_settings_window
        )
        # T23: the trash is where deleted things wait, and where
        # they are deleted forever.
        self._menu_action_trash = file_menu.addAction(
            "Trash...", self.open_trash_window
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
        self._menu_action_howto.setShortcut("F1")
        self._menu_action_chat = help_menu.addAction(
            "Chat...", self.open_chat_window
        )
        # F2 is Rename (T168); Chat moved to F3.
        self._menu_action_chat.setShortcut("F3")

    def _refresh_menu_state(self):
        """Grey out the actions that cannot work yet (T19): New
        project and Profiles need a profile; Export and Projects
        need a project. Export profile needs a profile; Check
        package always works. The rest always work."""
        has_profile = bool(self._current_profile)
        has_session = bool(self._current_profile and self._current_project)
        self._menu_action_new_project.setEnabled(has_profile)
        self._menu_action_profiles.setEnabled(has_profile)
        self._menu_action_export.setEnabled(has_session)
        self._menu_action_export_project_zip.setEnabled(has_session)
        self._menu_action_export_profile.setEnabled(has_profile)
        self._menu_action_export_profile_zip.setEnabled(has_profile)
        self._menu_action_export_recipe.setEnabled(has_session)
        self._menu_action_export_adapter.setEnabled(has_session)
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
        hero.setObjectName("card")
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
        # The fix button (T79): when there is no repo to download
        # from, this button — not a label — opens the profile
        # window, where Base ref gets set. Visible only then.
        self.download_fix_btn = QPushButton("Set the model source...")
        self.download_fix_btn.clicked.connect(
            self.open_current_profile_window
        )
        self.download_fix_btn.setVisible(False)
        dl_btns.addWidget(self.download_btn)
        dl_btns.addWidget(self.download_cancel_btn)
        dl_btns.addWidget(self.download_fix_btn)
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
        self.go_btn.setToolTip("Run the picked job.")
        self.go_btn.setObjectName("goButton")
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

        # -- the job card: the running job, with progress + cancel --
        self.job_card = JobCard()
        self.job_card.cancel_clicked.connect(self._cancel_current_job)
        layout.addWidget(self.job_card)

        # -- glanceable card: the loss curve and the live numbers --
        card = QFrame()
        card.setObjectName("card")
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
        # The pin note (T47): while a run is live on another
        # project, the panel says so instead of following the
        # session. Hidden whenever the panel is not pinned.
        self.train_pin_label = QLabel("")
        self.train_pin_label.setWordWrap(True)
        self.train_pin_label.setVisible(False)
        card_layout.addWidget(self.train_pin_label)
        card_layout.addWidget(self.train_progress)
        self.train_loss = QLabel("Not started.")
        card_layout.addWidget(self.train_loss)
        # The pre-train estimate (T84): fit + time for the
        # auto-config recipe — no settings on screen (T16). It
        # updates when the model, dataset, or job selection
        # changes, via refresh_session.
        self.train_estimate_label = QLabel("")
        self.train_estimate_label.setWordWrap(True)
        card_layout.addWidget(self.train_estimate_label)
        run_btns = QHBoxLayout()
        self.train_pause_btn = QPushButton("Pause")
        self.train_pause_btn.clicked.connect(self.pause_training)
        self.train_pause_btn.setEnabled(False)
        self.train_resume_btn = QPushButton("Resume")
        self.train_resume_btn.clicked.connect(
            lambda: self.start_training(resume=True)
        )
        # The proof run (T95): a short capped run, as a button —
        # toy-simple, no settings on screen. It starts the same
        # training with a 5-step cap.
        self.train_proof_btn = QPushButton("Proof run")
        self.train_proof_btn.setToolTip(
            "A short 5-step run to check the setup works."
        )
        self.train_proof_btn.clicked.connect(
            lambda: self.start_training(max_steps=PROOF_RUN_STEPS)
        )
        # The dry run (T85): RAM fit + steps + disk, computed from
        # metadata only — no model load — and shown in the log.
        self.train_estimate_btn = QPushButton("Estimate")
        self.train_estimate_btn.setToolTip(
            "Work out how long this run takes and how much disk "
            "it needs, without loading the model."
        )
        self.train_estimate_btn.clicked.connect(self._on_estimate)
        run_btns.addWidget(self.train_pause_btn)
        run_btns.addWidget(self.train_resume_btn)
        run_btns.addWidget(self.train_proof_btn)
        run_btns.addWidget(self.train_estimate_btn)
        run_btns.addStretch(1)
        card_layout.addLayout(run_btns)
        # The step cap (T161): Go stops the run after this many
        # steps — a proof run with a number the user picks, instead
        # of the fixed 5-step Proof run button. 0 means the full
        # run. It applies to a fresh start only: Resume continues
        # to the run's own total.
        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("Step cap"))
        self.train_step_cap_spin = QSpinBox()
        self.train_step_cap_spin.setRange(0, 100000)
        self.train_step_cap_spin.setValue(0)
        self.train_step_cap_spin.setToolTip(
            "Stop after this many steps. 0 means the full run."
        )
        cap_row.addWidget(self.train_step_cap_spin)
        cap_row.addWidget(
            _help_label("0 means the full run. A cap makes Go a short run.")
        )
        cap_row.addStretch(1)
        card_layout.addLayout(cap_row)
        layout.addWidget(card)

        # -- train details, below, in collapsible sections ---------
        # (T80, entry 012): Dataset, Checkpoints, Training log, and
        # Sleep cycles each collapse to one header, so the scroll
        # shortens to what the user is actually looking at. All
        # start open; the widgets keep their attributes, so the
        # rest of the window does not care that they moved.
        dataset_section = CollapsibleSection("Dataset")
        dataset_btns = QHBoxLayout()
        self.train_pick_dataset_btn = QPushButton("Pick dataset file")
        self.train_pick_dataset_btn.clicked.connect(self.pick_dataset)
        self.train_sample_btn = QPushButton("Use sample dataset")
        self.train_sample_btn.clicked.connect(self.use_sample_dataset)
        dataset_btns.addWidget(self.train_pick_dataset_btn)
        dataset_btns.addWidget(self.train_sample_btn)
        dataset_btns.addStretch(1)
        dataset_section.content_layout.addLayout(dataset_btns)
        # The dataset health line (T83): row count, format, and a
        # rough token count for a healthy dataset; the problem,
        # with line numbers, for a bad one. Refreshed with the
        # panel, so picking a dataset updates it at once.
        self.dataset_health_label = QLabel("")
        self.dataset_health_label.setWordWrap(True)
        dataset_section.content_layout.addWidget(self.dataset_health_label)
        layout.addWidget(dataset_section)
        self.dataset_section = dataset_section

        # Run overrides (T161): a dataset and a base for THIS run
        # only — the CLI's --dataset / --base, in the window. Blank
        # means the project's dataset and the profile's base, and
        # nothing here is ever written back to the project or the
        # profile. The fields clear when the project changes, so a
        # leftover override never follows the session.
        overrides_section = CollapsibleSection("Run overrides")
        override_form = QFormLayout()
        self.run_dataset_edit = QLineEdit()
        self.run_dataset_edit.setPlaceholderText(
            "this run's dataset file (blank: the project's)"
        )
        self.run_dataset_browse_btn = QPushButton("Browse...")
        self.run_dataset_browse_btn.clicked.connect(
            self._browse_run_dataset
        )
        run_dataset_row = QWidget()
        run_dataset_layout = QHBoxLayout(run_dataset_row)
        run_dataset_layout.setContentsMargins(0, 0, 0, 0)
        run_dataset_layout.addWidget(self.run_dataset_edit, 1)
        run_dataset_layout.addWidget(self.run_dataset_browse_btn)
        override_form.addRow("Dataset for this run", run_dataset_row)
        override_form.addRow(
            "",
            _help_label(
                "Only this run trains on this file. The project "
                "keeps its own dataset."
            ),
        )
        self.run_base_edit = QLineEdit()
        self.run_base_edit.setPlaceholderText(
            "this run's base model (blank: the profile's)"
        )
        override_form.addRow("Base for this run", self.run_base_edit)
        override_form.addRow(
            "",
            _help_label(
                "Only this run starts from this base: a Hugging "
                "Face repo or a local folder. The profile keeps "
                "its own base."
            ),
        )
        overrides_section.content_layout.addLayout(override_form)
        layout.addWidget(overrides_section)
        self.overrides_section = overrides_section

        checkpoints_section = CollapsibleSection("Checkpoints")
        self.train_checkpoints = QListWidget()
        self.train_checkpoints.setMaximumHeight(90)
        self.train_checkpoints.itemClicked.connect(
            self._on_checkpoint_selected
        )
        # T168: double-clicking a checkpoint shows its detail too —
        # the same detail a single click shows.
        self.train_checkpoints.itemDoubleClicked.connect(
            self._on_checkpoint_selected
        )
        checkpoints_section.content_layout.addWidget(self.train_checkpoints)
        # The detail view (T150): step, loss, size, date for the
        # picked checkpoint. Nothing is selected by default.
        self.checkpoint_detail_label = QLabel(
            "Pick a checkpoint to see its details."
        )
        self.checkpoint_detail_label.setWordWrap(True)
        checkpoints_section.content_layout.addWidget(
            self.checkpoint_detail_label
        )
        # Disk usage (T150): what all the checkpoints cost.
        self.checkpoint_disk_label = QLabel("")
        self.checkpoint_disk_label.setWordWrap(True)
        checkpoints_section.content_layout.addWidget(
            self.checkpoint_disk_label
        )
        # Checkpoint actions (T150): resume from the picked one,
        # delete it, or prune down to the newest N. Delete and
        # prune are permanent (the point is freeing disk) and
        # both confirm first, defaulting to No.
        ckpt_btns = QHBoxLayout()
        self.checkpoint_resume_btn = QPushButton("Resume from selected")
        self.checkpoint_resume_btn.clicked.connect(
            self._resume_from_checkpoint
        )
        self.checkpoint_delete_btn = QPushButton("Delete checkpoint")
        self.checkpoint_delete_btn.clicked.connect(self._delete_checkpoint)
        ckpt_btns.addWidget(self.checkpoint_resume_btn)
        ckpt_btns.addWidget(self.checkpoint_delete_btn)
        ckpt_btns.addWidget(QLabel("Keep newest"))
        self.checkpoint_keep_spin = QSpinBox()
        self.checkpoint_keep_spin.setRange(1, 99)
        self.checkpoint_keep_spin.setValue(3)
        self.checkpoint_keep_spin.setToolTip(
            "How many of the newest checkpoints pruning keeps. "
            "The rest are deleted for good."
        )
        ckpt_btns.addWidget(self.checkpoint_keep_spin)
        self.checkpoint_prune_btn = QPushButton("Prune")
        self.checkpoint_prune_btn.setToolTip(
            "Delete old checkpoints, keeping the newest ones "
            "you picked. Deleted for good."
        )
        self.checkpoint_prune_btn.clicked.connect(self._prune_checkpoints)
        ckpt_btns.addWidget(self.checkpoint_prune_btn)
        ckpt_btns.addStretch(1)
        checkpoints_section.content_layout.addLayout(ckpt_btns)
        # The GGUF options (T161): the quant, and which checkpoint
        # to export from — the CLI's --quant / --from-checkpoint.
        # The checkpoint picker rides the T150 list above: the
        # trained adapter is the default, a picked checkpoint
        # exports that checkpoint's adapter instead.
        gguf_row = QHBoxLayout()
        gguf_row.addWidget(QLabel("Quant"))
        self.gguf_quant_combo = QComboBox()
        self.gguf_quant_combo.addItems(list(KNOWN_QUANTS))
        self.gguf_quant_combo.setCurrentText(DEFAULT_QUANT)
        self.gguf_quant_combo.setToolTip(
            "How small the GGUF file is. Q4_K_M is the usual "
            "balance of size and quality."
        )
        gguf_row.addWidget(self.gguf_quant_combo)
        gguf_row.addWidget(QLabel("From checkpoint"))
        self.gguf_checkpoint_combo = QComboBox()
        self.gguf_checkpoint_combo.addItem("Trained adapter")
        self.gguf_checkpoint_combo.setToolTip(
            "Export from a checkpoint's adapter instead of the "
            "trained adapter."
        )
        gguf_row.addWidget(self.gguf_checkpoint_combo, 1)
        checkpoints_section.content_layout.addLayout(gguf_row)
        export_btns = QHBoxLayout()
        self.train_export_gguf_btn = QPushButton("Export GGUF")
        self.train_export_gguf_btn.clicked.connect(self.export_gguf_gui)
        # T89: create the last GGUF export in Ollama, one click.
        self.train_create_ollama_btn = QPushButton("Create in Ollama")
        self.train_create_ollama_btn.clicked.connect(
            self.create_in_ollama_gui
        )
        self.train_probe_btn = QPushButton("Run refusal probe")
        self.train_probe_btn.clicked.connect(self.run_probe_gui)
        # The probe evidence (T94), re-openable after the run: the
        # saved results, per prompt, before and after.
        self.train_view_probe_btn = QPushButton("View probe results")
        self.train_view_probe_btn.clicked.connect(self._view_probe_results)
        export_btns.addWidget(self.train_export_gguf_btn)
        export_btns.addWidget(self.train_create_ollama_btn)
        export_btns.addWidget(self.train_probe_btn)
        export_btns.addWidget(self.train_view_probe_btn)
        export_btns.addStretch(1)
        checkpoints_section.content_layout.addLayout(export_btns)
        # The export estimate (T153): what the export will cost,
        # beside the button, before the user commits.
        self.export_estimate_label = QLabel("")
        self.export_estimate_label.setWordWrap(True)
        checkpoints_section.content_layout.addWidget(
            self.export_estimate_label
        )
        layout.addWidget(checkpoints_section)
        self.checkpoints_section = checkpoints_section

        # Past runs (T151): one row per finished (or paused) run —
        # date, steps, final loss. Picking one shows its loss curve
        # in the chart above. No settings anywhere here (T16).
        runs_section = CollapsibleSection("Past runs")
        self.run_history_list = QListWidget()
        self.run_history_list.setMaximumHeight(90)
        self.run_history_list.itemClicked.connect(self._on_run_selected)
        runs_section.content_layout.addWidget(self.run_history_list)
        self.run_history_hint = QLabel(
            "Pick a run to see its loss curve."
        )
        self.run_history_hint.setWordWrap(True)
        runs_section.content_layout.addWidget(self.run_history_hint)
        layout.addWidget(runs_section)
        self.runs_section = runs_section

        log_section = CollapsibleSection("Training log")
        self.train_log = QPlainTextEdit()
        self.train_log.setReadOnly(True)
        self.train_log.setMinimumHeight(120)
        log_section.content_layout.addWidget(self.train_log)
        layout.addWidget(log_section)
        self.log_section = log_section

        # Sleep keeps its dream switch and its cycles list here; the
        # Sleep button itself is gone — Go starts it, like every job.
        sleep_section = CollapsibleSection(
            "Sleep cycles (click one to see its report)"
        )
        dream_row = QHBoxLayout()
        self.sleep_dream_check = QCheckBox("Dream first")
        self.sleep_dream_check.setToolTip(
            "Dream synthetic practice rows from the local Ollama model "
            "before consolidating (best effort: sleep still runs on "
            "real rows if Ollama is down)."
        )
        dream_row.addWidget(self.sleep_dream_check)
        dream_row.addStretch(1)
        sleep_section.content_layout.addLayout(dream_row)
        self.sleep_cycles = QListWidget()
        self.sleep_cycles.setMaximumHeight(90)
        self.sleep_cycles.itemClicked.connect(self._on_sleep_cycle_clicked)
        sleep_section.content_layout.addWidget(self.sleep_cycles)
        layout.addWidget(sleep_section)
        self.sleep_section = sleep_section
        layout.addStretch(1)

        self.bento_widget = page
        self.session_layout.addWidget(page)

    def _set_tab_order(self):
        """Tab walks the main screen in visual order (T82). Runs at
        the end of _build_ui, once every panel is parented into the
        window — setTabOrder refuses pairs in different windows,
        and the session scroll area is still top-level while the
        bento is being built."""
        _chain_tab_order([
            self.tree, self.model_combo, self.new_model_btn,
            self.download_btn, self.download_cancel_btn,
            self.download_fix_btn,
            self.job_buttons["train"], self.job_buttons["sleep"],
            self.job_buttons["requant"], self.job_buttons["distill"],
            self.go_btn, self.project_name_edit,
            self.dataset_sample_btn, self.dataset_pick_btn,
            self.job_card.cancel_btn,
            self.train_pause_btn, self.train_resume_btn,
            self.train_proof_btn, self.train_estimate_btn,
            self.dataset_section.header_btn,
            self.train_pick_dataset_btn, self.train_sample_btn,
            self.checkpoints_section.header_btn,
            self.train_checkpoints,
            self.checkpoint_resume_btn, self.checkpoint_delete_btn,
            self.checkpoint_keep_spin, self.checkpoint_prune_btn,
            self.train_export_gguf_btn,
            self.train_probe_btn, self.train_view_probe_btn,
            self.runs_section.header_btn, self.run_history_list,
            self.log_section.header_btn, self.train_log,
            self.sleep_section.header_btn,
            self.sleep_dream_check, self.sleep_cycles,
        ])

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
    def _profile_label(p, project_count=None, tag_state=None):
        """A profile row: display name, [role], (tag), the project
        count (T165), and the tag-health marker (T163). The count
        and the marker are passed in — the label itself never
        touches the store or the network, so refresh_tree stays
        the one place that reads them."""
        label = p.get("display_name") or p["name"]
        role = p.get("role") or ""
        tag = p.get("ollama_tag") or p.get("base_ref") or ""
        if role:
            label += f" [{role}]"
        if tag:
            label += f" ({tag})"
        if project_count is not None:
            noun = "project" if project_count == 1 else "projects"
            label += f" ({project_count} {noun})"
        if tag_state:
            label += _TAG_HEALTH_MARKERS.get(tag_state, "")
        return label

    @staticmethod
    def _project_label(p, show_slug=False):
        """A project row (T164): display name, status (T53), and
        the dataset file. Method and rank are NOT shown — they are
        settings, and no settings appear on any screen (T16). When
        two projects in one profile share a display name, the slug
        disambiguates (collision only)."""
        label = p.get("display_name") or p.get("name") or "(unnamed project)"
        if show_slug:
            label += f" [{p.get('name', '')}]"
        # The status shows in the list row (T53): "Tool calls
        # (done)". A damaged row has no status to show.
        status = p.get("status")
        if status and not p.get("_damaged"):
            label += f" ({status})"
        # The dataset, by file name: the full ref lives in the
        # Project window, the row just says which file it trains on.
        ref = p.get("dataset_ref") or ""
        if ref and not p.get("_damaged"):
            label += f" [{Path(ref).name or ref}]"
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
        so clicks can tell the row apart from a healthy one. Every
        row carries its full text as a tooltip (T78): long names
        truncate in the pane, and hovering shows the whole row."""
        item.setText(0, label)
        item.setToolTip(0, label)
        item.setData(0, Qt.UserRole + 1, bool(damaged))
        font = item.font(0)
        font.setItalic(bool(damaged))
        item.setFont(0, font)
        if damaged:
            item.setForeground(0, QBrush(QColor("#888888")))
        else:
            item.setForeground(0, QBrush())

    def refresh_model_list(self):
        """Start a background model-list refresh (T43), unless one
        is already running — one in-flight worker is enough, and
        the cache makes one fetch of overlapping refreshes anyway.
        Every surface that shows the list refills from the
        refreshed handler when it lands."""
        if (
            self._model_list_worker is not None
            and self._model_list_worker.isRunning()
        ):
            return
        worker = ModelListWorker(self)
        worker.refreshed.connect(self._on_model_list_refreshed)
        worker.finished.connect(self._on_model_list_worker_finished)
        self._model_list_worker = worker
        worker.start()

    def _on_model_list_worker_finished(self):
        if self._model_list_worker is self.sender():
            self._model_list_worker = None

    def _profile_label_inputs(self, slug, p):
        """(project_count, tag_state) for one profile row: the
        count from the store, the tag state from the cached model
        list (T43) — never a fetch. The health question is about
        the Ollama tag only: a base ref is not a tag, so a profile
        with a base but no tag is "no-tag"."""
        try:
            count = len(self.store.list_projects(slug))
        except StellaError:
            count = 0
        models, _sizes, loaded, ollama_up, _at = MODEL_CACHE.snapshot()
        tag = p.get("ollama_tag") or ""
        return count, _tag_health_state(tag, models, ollama_up, loaded)

    def _on_model_list_refreshed(self, _models, _sizes, _ollama_up):
        """A background model-list refresh landed (T43): every
        surface that shows the list re-reads it from the cache —
        the tree badges, open profile windows, Settings, and the
        chat model buttons."""
        self._refresh_tree_badges()
        for win in list(self._profile_windows.values()):
            win._fill_tag_combo(prefer_current=True)
            # T165: the model info follows the refreshed list too —
            # an Ollama that came back makes the metadata loadable.
            win._refresh_model_info()
        if self._settings_window is not None:
            self._settings_window._on_models_refreshed()
        if self._chat_window is not None:
            self._chat_window._on_models_refreshed()

    def _ollama_up_cached(self) -> bool:
        """Is Ollama answering? From the model-list cache (T43):
        the cache's last refresh already answered that question,
        so the badges never make their own fetch. When the cache
        has never loaded, assume up (the startup refresh corrects
        the badges when it lands); when the last refresh is older
        than 10 s, kick off a background refresh and keep the last
        known answer until it lands."""
        _models, _sizes, loaded, ollama_up, fetched_at = (
            MODEL_CACHE.snapshot()
        )
        if not loaded:
            self.refresh_model_list()
            return True
        if time.monotonic() - fetched_at > 10:
            self.refresh_model_list()
        return ollama_up

    def _refresh_tree_badges(self):
        """The health badge on each profile row (T78): a green dot
        when the weights are ready, amber when they are not, grey
        when Ollama is down and the weights are not ready either
        (the tag side cannot be checked then). Weights ready wins
        over Ollama down: training can start without Ollama. The
        tooltip carries the full row text plus the health line, so
        the badge is never a mystery. Separated from refresh_tree
        so the Ollama check runs once per pass, not once per row.

        The tag-health marker (T163) is relabelled here too, so a
        model-list refresh updates the markers without a full tree
        rebuild: the row text follows the cache the moment the
        refresh lands."""
        ollama_up = self._ollama_up_cached()
        for slug, item in self._tree_profiles.items():
            if item.data(0, Qt.UserRole + 1):
                item.setIcon(0, QIcon())  # damaged: no badge
                continue
            try:
                prof = self.store.get_profile(slug)
            except StellaError:
                prof = None
            if prof is not None:
                count, tag_state = self._profile_label_inputs(slug, prof)
                self._set_tree_row(
                    item,
                    self._profile_label(prof, count, tag_state),
                    False,
                )
            try:
                status = provision.weights_status(self.store, slug)
            except StellaError:
                item.setIcon(0, _health_icon("ollama-down"))
                continue
            if status["state"] == "ready":
                state = "ready"
            elif not ollama_up:
                state = "ollama-down"
            else:
                state = "missing"
            item.setIcon(0, _health_icon(state))
            line = _weights_label(status)
            if state == "ollama-down":
                line += " Ollama is down."
            item.setToolTip(0, f"{item.text(0)}\n{line}")

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
                count, tag_state = self._profile_label_inputs(slug, p)
                label = self._profile_label(p, count, tag_state)
            item = self._tree_profiles.get(slug)
            if item is None:
                item = QTreeWidgetItem(self.tree, [label])
                item.setData(0, Qt.UserRole, (slug, None))
                self._tree_profiles[slug] = item
            self._set_tree_row(item, label, damaged)
            projects = {
                pr["name"]: pr for pr in self.store.list_projects(slug)
            }
            # T164: a display name shared by two projects in this
            # profile is disambiguated by slug, collision only.
            display_counts: dict[str, int] = {}
            for pr in projects.values():
                shown = pr.get("display_name") or pr.get("name") or ""
                display_counts[shown] = display_counts.get(shown, 0) + 1
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
                    shown = pr.get("display_name") or pr.get("name") or ""
                    pr_label = self._project_label(
                        pr, show_slug=display_counts.get(shown, 0) > 1
                    )
                child = self._tree_projects.get(key)
                if child is None:
                    child = QTreeWidgetItem(item, [pr_label])
                    child.setData(0, Qt.UserRole, key)
                    self._tree_projects[key] = child
                self._set_tree_row(child, pr_label, pr_damaged)
        # T180: the filter + sort (name is the default order, not
        # the old filesystem order). Children stay in name order.
        self._apply_tree_filter(profiles)
        for slug, item in self._tree_profiles.items():
            item.setExpanded(slug in expanded)
        if vbar is not None:
            vbar.setValue(scroll)
        self._refresh_tree_badges()
        self._refresh_tree_hint()
        self._sync_tree_selection()

    def _on_tree_filter_changed(self, *args):
        """The filter box, role filter, or sort picker changed
        (T180): re-apply the filter. The tree rows already exist,
        so this is hiding + ordering only — no store re-read, no
        relabel, and the selection survives when the selected
        profile still matches."""
        self._apply_tree_filter()
        self._refresh_tree_hint()

    def _apply_tree_filter(self, profiles: dict | None = None) -> None:
        """Hide the profiles the filter does not match, and order
        the rest by the sort picker (T180). The filter text matches
        display name, slug, role, and tag; the role filter shows
        only that role. Sorts: name (the default), role, recently
        used (last_used, newest first, never-used last), project
        count (most first). Ties break by name. Damaged rows are
        never hidden — a broken row must stay visible so it can be
        repaired. The current item and the multi-selection are
        restored after a reorder, so filtering never loses the
        selection when the selected profile still matches."""
        if profiles is None:
            profiles = {
                p["name"]: p
                for p in self.store.list_profiles()
                if not p.get("_damaged")
            }
        else:
            profiles = {
                slug: p for slug, p in profiles.items()
                if not p.get("_damaged")
            }
        text = ""
        role_filter = ""
        sort_key = "Name"
        if getattr(self, "tree_filter", None) is not None:
            text = (self.tree_filter.text() or "").strip().lower()
        if getattr(self, "tree_role_filter", None) is not None:
            role_filter = self.tree_role_filter.currentText()
            role_filter = "" if role_filter == "All roles" else role_filter.lower()
        if getattr(self, "tree_sort", None) is not None:
            sort_key = self.tree_sort.currentText()
        for slug, item in self._tree_profiles.items():
            p = profiles.get(slug)
            if p is None:
                # A damaged row: never hidden.
                item.setHidden(False)
                continue
            hay = " ".join([
                p.get("display_name") or "",
                p.get("name") or "",
                p.get("role") or "",
                p.get("ollama_tag") or "",
                p.get("base_ref") or "",
            ]).lower()
            match = (not text or text in hay) and (
                not role_filter
                or (p.get("role") or "").lower() == role_filter
            )
            item.setHidden(not match)
        # Order: name first (the tie-break — sorts are stable),
        # then the picked key.
        items = list(self._tree_profiles.items())

        def _name(slug):
            p = profiles.get(slug) or {}
            return (p.get("display_name") or slug).lower()

        items.sort(key=lambda kv: _name(kv[0]))
        if sort_key == "Role":
            items.sort(key=lambda kv: (
                (profiles.get(kv[0]) or {}).get("role") or ""
            ).lower() or "\uffff")
        elif sort_key == "Recently used":
            # Newest first; a blank last_used ("never") sorts last
            # ("" is smaller than any timestamp, so reverse puts
            # it at the end).
            items.sort(
                key=lambda kv: (profiles.get(kv[0]) or {}).get("last_used") or "",
                reverse=True,
            )
        elif sort_key == "Project count":
            items.sort(
                key=lambda kv: sum(
                    1 for key in self._tree_projects if key[0] == kv[0]
                ),
                reverse=True,
            )
        current = self.tree.currentItem()
        selected = self.tree.selectedItems()
        self._building = True
        try:
            for index, (_slug, item) in enumerate(items):
                at = self.tree.indexOfTopLevelItem(item)
                if at != index:
                    self.tree.takeTopLevelItem(at)
                    self.tree.insertTopLevelItem(index, item)
            for item in self._tree_profiles.values():
                item.sortChildren(0, Qt.AscendingOrder)
        finally:
            self._building = False
        # Restore the selection after the reorder: taking an item
        # out drops it from the selection, and the current item
        # with it. Hidden rows keep their selection too — the
        # filter hides rows, it does not unpick them.
        if current is not None:
            self._building = True
            try:
                self.tree.setCurrentItem(current)
            finally:
                self._building = False
        for item in selected:
            item.setSelected(True)

    def _refresh_tree_hint(self):
        """The empty-list hint (T124): one line under the tree
        saying what to do next, when the tree has nothing to
        show — an empty store, or a profile with no projects.
        Hidden the moment there is something to look at. T180: a
        filter that matches nothing says so, so an empty-looking
        list is never mistaken for an empty store."""
        if not self._tree_profiles:
            text = (
                "No profiles yet - New profile to start. New here? "
                "<a href=\"getting-started\">Getting started</a>."
            )
        elif self._current_profile and not any(
            key[0] == self._current_profile
            for key in self._tree_projects
        ):
            text = (
                "No projects yet - New project to start. New here? "
                "<a href=\"getting-started\">Getting started</a>."
            )
        else:
            text = ""
        if not text and self._tree_profiles:
            filtering = False
            if getattr(self, "tree_filter", None) is not None:
                filtering = bool(self.tree_filter.text().strip())
            if (
                not filtering
                and getattr(self, "tree_role_filter", None) is not None
                and self.tree_role_filter.currentText() != "All roles"
            ):
                filtering = True
            if filtering and all(
                item.isHidden()
                for item in self._tree_profiles.values()
            ):
                text = "No profiles match that filter."
        self.tree_hint.setText(text)
        self.tree_hint.setVisible(bool(text))

    def _on_tree_hint_link(self, link):
        # T193: the empty state's Getting started link opens the
        # guide on that topic.
        if link == "getting-started":
            self.open_howto_window(topic="Getting started")

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
        # T168 ruling: double-click KEEPS opening the detail window
        # — it is the established multi-window pattern, and rename
        # moved to F2 and the right-click menu instead.
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

    def _rename_current_row(self):
        """Rename the picked tree row (T168): F2, and the
        right-click menu. A profile row renames the profile, a
        project row renames the project. Nothing picked means
        nothing to rename. A damaged row cannot be renamed — its
        manifest cannot be read, so double-click repairs it first.

        Modal audit: this reaches QInputDialog.getText through the
        existing rename methods — the same dialog the window's
        Rename buttons already open. No new modal; tests stub
        getText as the rename tests already do."""
        item = self.tree.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if data is None or item.data(0, Qt.UserRole + 1):
            return
        profile, project = data
        if project is None:
            self.rename_profile(profile)
        else:
            self.rename_project(profile, project)

    def _tree_context_menu(self, item):
        """The right-click menu for one tree row (T168): Rename,
        for a healthy row. None for a damaged row or no row —
        there is nothing to rename there. Factored out so tests
        can read the menu without showing it. T181: when several
        profiles are selected and the row is one of them, the
        bulk actions join the menu — delete, export, and role
        change for the whole selection. A single selection shows
        Rename only, exactly as before."""
        if item is None or item.data(0, Qt.UserRole + 1):
            return None
        data = item.data(0, Qt.UserRole)
        if data is None:
            return None
        profile, project = data
        menu = QMenu(self.tree)
        rename = menu.addAction("Rename")
        if project is None:
            rename.triggered.connect(
                lambda: self.rename_profile(profile)
            )
        else:
            rename.triggered.connect(
                lambda: self.rename_project(profile, project)
            )
        selected = self._selected_profiles()
        if (
            project is None
            and len(selected) > 1
            and profile in selected
        ):
            menu.addSeparator()
            n = len(selected)
            delete = menu.addAction(f"Delete {n} selected profiles...")
            delete.triggered.connect(
                lambda: self._bulk_delete_profiles(selected)
            )
            export = menu.addAction(
                f"Export {n} selected profiles..."
            )
            export.triggered.connect(
                lambda: self._bulk_export_profiles(selected)
            )
            role = menu.addAction(
                f"Change role for {n} selected profiles..."
            )
            role.triggered.connect(
                lambda: self._bulk_change_role(selected)
            )
        return menu

    def _selected_profiles(self) -> list[str]:
        """The profile slugs in the current tree selection (T181):
        top-level rows only — project rows are not bulk targets.
        Damaged rows are skipped: there is nothing to delete or
        export until they are repaired."""
        slugs = []
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.UserRole)
            if data is None or item.data(0, Qt.UserRole + 1):
                continue
            profile, project = data
            if project is None and profile not in slugs:
                slugs.append(profile)
        return slugs

    def _on_tree_context_menu(self, pos):
        """Right-click on the tree (T168): show the row's menu at
        the click. A click on empty space shows nothing."""
        item = self.tree.itemAt(pos)
        menu = self._tree_context_menu(item)
        if menu is None:
            return
        menu.exec(self.tree.viewport().mapToGlobal(pos))

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
        The session is remembered across restarts (QSettings), and
        the last project is remembered PER PROFILE (T77, entry 022):
        switching profiles restores that profile's project, so the
        session follows the profile. The memory is only written
        when a project is picked (never erased by a profile-only
        click), and only restored on a profile change to a project
        that still exists."""
        if (
            project is None
            and profile is not None
            and profile != self._current_profile
        ):
            remembered = (
                self.settings.value(f"session/by-profile/{profile}", "")
                or None
            )
            if remembered:
                try:
                    self.store.get_project(profile, remembered)
                except StellaError:
                    remembered = None
                else:
                    project = remembered
        self._current_profile = profile
        self._current_project = project
        self.settings.setValue("session/profile", profile or "")
        self.settings.setValue("session/project", project or "")
        if profile and project:
            self.settings.setValue(
                f"session/by-profile/{profile}", project
            )
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
            # T191: the status bar no longer repeats the session
            # in slug form — the session title above carries it,
            # in display names. The status bar keeps whatever the
            # last action said.
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
            # T191: no slug repeat here either — the session title
            # carries the profile name, in display form.
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
        ):
            w.setEnabled(has_session)
        self.train_resume_btn.setEnabled(
            has_session
            and not self._training_running()
            and not self._sleep_running()
        )
        # The proof run and the dry run follow the same rule as
        # Resume: a session, and no run in progress (T95/T85).
        self.train_proof_btn.setEnabled(
            has_session
            and not self._training_running()
            and not self._sleep_running()
        )
        self.train_estimate_btn.setEnabled(has_session)
        # Export and probe follow the job rule in _refresh_go (a
        # second job is refused, T74); the download button follows
        # the weights state in _refresh_download_row (T79).
        self.download_cancel_btn.setEnabled(
            self.download_manager.is_running()
        )
        self._refresh_download_row()
        self._refresh_go()
        self._refresh_menu_state()
        self.refresh_train_panel()
        self._refresh_estimate()
        self._refresh_checklist()
        self._refresh_tree_hint()

    def _refresh_estimate(self):
        """The pre-train estimate label (T84): fit + time for the
        auto-config recipe, no settings on screen (T16). Cached
        by (profile, project, dataset, base ref) — refresh_session
        runs often, and the estimate only recomputes when one of
        those changed.

        The metadata read is gated, not attempted blindly: a
        remote base ref would fetch from the Hub on every
        refresh, so the estimate only computes when the weights
        are already downloaded (the read then hits the local
        cache) or the base is a local folder. Anything else shows
        a plain unavailable line instead of hanging the window on
        a network fetch."""
        if not self._current_profile or not self._current_project:
            self.train_estimate_label.setText("")
            self._estimate_cache_key = None
            self._estimate_cache_text = ""
            return
        try:
            prof = self.store.get_profile(self._current_profile)
            proj = self.store.get_project(
                self._current_profile, self._current_project
            )
        except StellaError:
            self.train_estimate_label.setText("Estimate unavailable.")
            return
        base_ref = (prof.get("base_ref") or "").strip()
        key = self._estimate_key(
            self._current_profile, self._current_project
        )
        if key == self._estimate_cache_key:
            self.train_estimate_label.setText(self._estimate_cache_text)
            return
        text = "Estimate unavailable."
        if base_ref:
            local = Path(base_ref).expanduser().is_dir()
            ready = False
            if not local:
                try:
                    ready = (
                        provision.weights_status(
                            self.store, self._current_profile
                        )["state"]
                        == "ready"
                    )
                except StellaError:
                    ready = False
            if local or ready:
                from .train import estimate_run, format_estimate_short

                try:
                    estimate = estimate_run(
                        self.store,
                        self._current_profile,
                        self._current_project,
                    )
                except StellaError:
                    # The dataset health line already names a bad
                    # dataset; an unreadable model just leaves the
                    # estimate blank.
                    text = "Estimate unavailable."
                else:
                    text = format_estimate_short(estimate)
            elif is_hf_repo_id(base_ref):
                # A real Hub repo whose weights are not downloaded
                # yet: the estimate appears once they are (the
                # read then hits the local cache). A base ref that
                # is not a repo id at all (an Ollama tag, from the
                # T54 sync) stays plain unavailable — downloading
                # would not make it estimable.
                text = (
                    "Estimate available after the model downloads."
                )
        self._estimate_cache_key = key
        self._estimate_cache_text = text
        self.train_estimate_label.setText(text)

    def _refresh_download_row(self):
        if not self._current_profile:
            self.download_status_label.setText("Pick a profile first.")
            self.download_progress.setVisible(False)
            self.download_btn.setEnabled(False)
            self.download_fix_btn.setVisible(False)
            return
        try:
            status = provision.weights_status(
                self.store, self._current_profile
            )
        except StellaError:
            self.download_status_label.setText("Profile not found.")
            self.download_btn.setEnabled(False)
            self.download_fix_btn.setVisible(False)
            return
        running = self.download_manager.is_running()
        # Download is honest (T79): disabled when there is no repo
        # to download from, and the fix button — which opens the
        # profile window, where Base ref gets set — shows instead.
        self.download_btn.setEnabled(
            status["state"] != "no-repo" and not running
        )
        self.download_fix_btn.setVisible(
            status["state"] == "no-repo" and not running
        )
        if running:
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
        name becomes part of the pick). Export and probe follow the
        same rule — a second job is refused (T74) — and the File
        menu's Run action mirrors Go (T82)."""
        running = self._job_running()
        self.go_btn.setEnabled(
            bool(self._current_profile)
            and self._picked_job() is not None
            and not running
        )
        has_session = bool(self._current_profile and self._current_project)
        for w in (
            self.train_export_gguf_btn, self.train_probe_btn,
            self.train_view_probe_btn,
        ):
            w.setEnabled(has_session and not running)
        # T89: Create in Ollama is live only when the project has a
        # GGUF export to create (its record is in the project dir).
        has_export = False
        if has_session and not running:
            try:
                has_export = (
                    self._last_gguf_export(
                        self._current_profile, self._current_project
                    )
                    is not None
                )
            except StellaError:
                has_export = False
        self.train_create_ollama_btn.setEnabled(has_export)
        self._menu_action_run.setEnabled(self.go_btn.isEnabled())

    def _running_job_name(self) -> str | None:
        """The running job's plain-words name, or None when idle
        (T29): the refusal message and the close feedback name the
        job the user is waiting on."""
        if self._training_running():
            return "Training"
        if self._sleep_running():
            return "Sleep"
        if self._job_worker is not None and self._job_worker.isRunning():
            return self._job_title or "A job"
        return None

    def _job_already_running(self) -> bool:
        """True when a job is running, with the plain-words refusal
        said (T29/T74): starting a second job is refused, not
        queued — and the message names the running job."""
        name = self._running_job_name()
        if name is not None:
            self._say(
                f"{name} is already running. Wait for it to finish, "
                "or cancel it first."
            )
            return True
        return False

    def _cancel_current_job(self):
        """The job card's Cancel button (T74): stop the running job.
        Training and sleep stop after the current step and save a
        checkpoint, so the work so far is kept; a GGUF/probe/
        re-quantize/distill job stops at the next check point (a
        running subprocess is killed)."""
        self.job_card.cancel_btn.setEnabled(False)
        if self._training_running():
            self._train_worker.request_stop()
            self.job_card.set_status(
                "Stopping after this step. The work so far is saved."
            )
            self._train_log_line(
                "Cancelling: stopping after this step "
                "(checkpoint will save)..."
            )
        elif self._sleep_running():
            self._sleep_worker.request_stop()
            self.job_card.set_status(
                "Stopping after this step. The work so far is saved."
            )
            self._train_log_line(
                "Cancelling sleep: stopping after this step..."
            )
        elif self._job_worker is not None and self._job_worker.isRunning():
            self._job_worker.request_cancel()
            self.job_card.set_status("Stopping...")

    def _on_go(self):
        """Press go: run the picked job on the picked model."""
        job = self._picked_job()
        profile = self._current_profile
        if not job or not profile:
            return
        if self._job_already_running():
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
        # T161: a run-override dataset counts as having examples —
        # the run trains on it, not on the project's dataset.
        if not (proj.get("dataset_ref") or "").strip():
            if not self.run_dataset_edit.text().strip():
                self.dataset_prompt_row.setVisible(True)
                self._say("This job needs examples to learn from.")
                return
        # T161: the step cap — 0 means the full run.
        cap = self.train_step_cap_spin.value()
        self.start_training(max_steps=cap if cap > 0 else None)

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
        and the new name are the usual ones. Runs as a job card
        (T74/T75), like every other job."""
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

        def job(ctx):
            def on_event(event):
                kind = event.get("type")
                if kind == "found":
                    ctx.log(
                        f"Found {event['source_tag']} "
                        f"({provision.format_size(event['source_bytes'])}). "
                        "Shrinking it..."
                    )
                elif kind == "quantized":
                    ctx.log(
                        "Shrunk to "
                        f"{provision.format_size(event['output_bytes'])}."
                    )
                elif kind == "created":
                    ctx.log(f"Registered as {event['new_tag']}.")

            report = requant_model(
                tag, on_event=on_event,
                should_stop=ctx.is_cancelled,
            )
            return (
                f"Made a smaller copy: {report['new_tag']} "
                f"({provision.format_size(report['output_bytes'])}, "
                f"was {provision.format_size(report['source_bytes'])}). "
                f"Run it with: {report['ollama_run']}"
            )

        self._start_job_worker(job, "Making a smaller copy", False,
                               from_job="requant")
        self._train_log_line(f"Making a smaller copy of {tag}...")

    def _start_distill(self):
        """Teach a small model: ask a teacher model the prompts in a
        file, save the answers as this project's dataset. The
        teacher and the prompts file come from one small dialog —
        a combo pick and a file pick, no typing. Runs as a job card
        (T74/T75), like every other job."""
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

        def job(ctx):
            def on_event(event):
                if event.get("type") == "prompt":
                    ctx.progress(event["index"], event["total"])
                    ctx.log(
                        f"Asking the teacher: prompt {event['index']} "
                        f"of {event['total']}."
                    )

            report = distill_dataset(
                self.store, profile, project, teacher, prompts,
                on_event=on_event, should_stop=ctx.is_cancelled,
            )
            return (
                f"Distilled {report['rows']} examples from {teacher} "
                f"into this project's dataset. Look at the dataset, "
                "then train when ready."
            )

        self._start_job_worker(job, "Teaching a small model", True,
                               from_job="distill")
        self._train_log_line(f"Asking {teacher} the prompts...")

    def _job_button_rect(self, job: str) -> QRect | None:
        """The picked job button's rect, in the job card's parent
        coordinates (T149): the morph's start rect. None when the
        button or the card's parent is missing."""
        btn = self.job_buttons.get(job)
        parent = self.job_card.parentWidget()
        if btn is None or parent is None:
            return None
        top_left = btn.mapTo(parent, btn.rect().topLeft())
        return QRect(top_left, btn.rect().size())

    def _start_job_worker(
        self, job, title: str, determinate: bool,
        from_job: str | None = None,
        on_finished=None,
    ) -> bool:
        """Start a JobWorker job as a job card (T74): the card shows
        the title, the job's log lines become its live status, and
        its progress reports move the bar. One job at a time (T29):
        a second job is refused here too, so no caller can ever
        overwrite a running worker and orphan it. Returns False
        when refused. `from_job` names the picker tile the job came
        from (T149): the card morphs out of it. GGUF export and the
        probe are not picker tiles, so they pass none. `on_finished`
        (T94) is an extra finished slot, connected BEFORE the
        worker starts — a fast job can emit before a caller that
        connects afterwards gets its connection in."""
        if self._job_already_running():
            return False
        self._job_worker = JobWorker(job)
        self._job_title = title
        self._job_worker.log.connect(self._train_log_line)
        self._job_worker.log.connect(self.job_card.set_status)
        self._job_worker.progress.connect(self.job_card.set_progress)
        self._job_worker.finished.connect(self._on_job_finished)
        if on_finished is not None:
            self._job_worker.finished.connect(on_finished)
        self._set_activity("job", f"Working: {title.lower()}...")
        self.job_card.start(
            title, determinate,
            from_rect=(
                self._job_button_rect(from_job) if from_job else None
            ),
            reduced_motion=reduced_motion(),
        )
        self._job_worker.start()
        self._refresh_go()
        self._refresh_checklist()
        return True

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
                if proj.get("status") == "done":
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

    def _on_download_finished(self, ok, message):
        slug = self._download_profile
        self._download_profile = None
        self._set_activity("idle", "Idle")
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

    def _save_open_windows(self):
        """Ctrl+S in the main window (T82): save every open profile
        or project window that has unsaved edits. Says what it did,
        or that there was nothing to save."""
        saved = 0
        for win in list(self._profile_windows.values()):
            if win.is_modified() and win.save():
                saved += 1
        for win in list(self._project_windows.values()):
            if win.is_modified() and win.save():
                saved += 1
        if saved:
            self._say(f"Saved {saved} window(s).")
        else:
            self._say("Nothing to save.")

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

    def open_trash_window(self):
        """Open the Trash window (T23): deleted profiles and
        projects, and the delete-forever action. A fresh window
        each time, so the list is never stale."""
        trash = TrashDialog(self, parent=self)
        trash.show()
        trash.raise_()
        trash.activateWindow()
        return trash

    def open_howto_window(self, topic=None):
        if self._howto_window is None:
            self._howto_window = HowToUseWindow(parent=self)
        self._howto_window.show()
        self._howto_window.raise_()
        self._howto_window.activateWindow()
        if topic is not None:
            self._howto_window.show_topic(topic)
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

    def clone_profile(self, slug=None):
        """Clone a profile (T121): the same tag, base, role,
        processor, config, and dependencies under a new name, no
        projects by default. When the profile has projects, the
        user is asked whether to copy them too (each copy starts
        with no checkpoints and fresh notes, like a project
        clone). The session moves to the clone.

        Modal audit: the copy-projects question only appears when
        the source has projects, and the only caller is the
        Profile window's Clone button — no existing test reaches
        it. The new tests stub the question."""
        slug = slug or self._current_profile
        if not slug:
            return
        text, ok = QInputDialog.getText(
            self, "Clone profile",
            f"Name for the copy of {slug!r} "
            "(lowercase, dashes ok):",
        )
        if not ok or not text.strip():
            return
        copy_projects = False
        if self.store.list_projects(slug):
            answer = QMessageBox.question(
                self,
                "Copy the projects too?",
                f"Profile {slug!r} has projects. Copy them into the "
                "new profile as well? Each copy starts with no "
                "checkpoints and fresh notes.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            copy_projects = answer == QMessageBox.Yes
        try:
            data = self.store.clone_profile(
                slug, text.strip(), copy_projects=copy_projects
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.debug_log.action(
            f"profile cloned: {slug} to {data['name']}"
        )
        self.set_session(data["name"], None)
        self._say(f"Cloned {slug} as {data['name']}.")

    def _delete_confirm_with_export(self, title, text, export_label):
        """A destructive confirmation that defaults to No, and where
        Escape leaves things untouched (U23/U31) — with an "Export
        first" button (T23), so a delete can be a copy-out first.
        Returns "yes", "no", or "export"."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Warning)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setEscapeButton(QMessageBox.No)
        export_btn = box.addButton(export_label, QMessageBox.ActionRole)
        result = box.exec()
        # A stubbed exec (tests) returns a button value with no
        # clicked button; a real click on Export first is read from
        # the button, not the return value.
        if box.clickedButton() is export_btn:
            return "export"
        if result == QMessageBox.Yes:
            return "yes"
        return "no"

    def _project_counts(self, profile, project):
        """What a project carries (T120): (checkpoints, has_notes).
        Checkpoints are the folders under checkpoints/; notes means
        a notes.md file exists."""
        pdir = self.store.project_dir(profile, project)
        ckpts = pdir / "checkpoints"
        count = 0
        if ckpts.is_dir():
            count = sum(1 for d in ckpts.iterdir() if d.is_dir())
        return count, (pdir / "notes.md").is_file()

    def _delete_profile_text(self, slug):
        """The profile delete dialog's text (T120): the item's
        display name + slug, what goes with it (projects,
        checkpoints, notes), and where it goes (the trash)."""
        try:
            prof = self.store.get_profile(slug)
            display = prof.get("display_name") or slug
        except StellaError:
            display = slug
        projects = self.store.list_projects(slug)
        n_projects = len(projects)
        checkpoints = 0
        noted = 0
        for proj in projects:
            count, has_notes = self._project_counts(slug, proj["name"])
            checkpoints += count
            noted += 1 if has_notes else 0
        text = f"Move profile {_displayed_name(display, slug)}"
        if n_projects:
            text += (
                f" and its {n_projects} project"
                f"{'s' if n_projects != 1 else ''}"
            )
        text += " to the trash?"
        goes = []
        if checkpoints:
            goes.append(
                f"{checkpoints} checkpoint"
                f"{'s' if checkpoints != 1 else ''}"
            )
        if noted:
            goes.append(
                f"notes for {noted} project"
                f"{'s' if noted != 1 else ''}"
            )
        if goes:
            text += f" That includes {', '.join(goes)}."
        text += (
            " You can move it back later, or delete it forever from "
            "Trash in the File menu."
        )
        return text

    def _delete_project_text(self, profile, project):
        """The project delete dialog's text (T120): the item's
        display name + slug, what goes with it (checkpoints,
        notes), and where it goes (the trash)."""
        try:
            proj = self.store.get_project(profile, project)
            display = proj.get("display_name") or project
        except StellaError:
            display = project
        count, has_notes = self._project_counts(profile, project)
        text = (
            f"Move project {_displayed_name(display, project)} "
            f"in profile {profile!r} to the trash?"
        )
        goes = []
        if count:
            goes.append(
                f"{count} checkpoint{'s' if count != 1 else ''}"
            )
        if has_notes:
            goes.append("its notes")
        if goes:
            text += f" That includes {', '.join(goes)}."
        text += (
            " You can move it back later, or delete it forever from "
            "Trash in the File menu."
        )
        return text

    def delete_profile(self, slug=None):
        slug = slug or self._current_profile
        if not slug:
            return
        while True:
            answer = self._delete_confirm_with_export(
                "Delete profile",
                self._delete_profile_text(slug),
                "Export all projects first",
            )
            if answer == "export":
                # Export, then ask again: the delete still needs
                # its own Yes after the copy is safe.
                self._export_all_projects(slug)
                continue
            if answer != "yes":
                return
            break
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
        self._say(f"Moved profile {slug} to the trash.")

    # -- T181: bulk operations on the multi-selection --------------
    def _bulk_delete_box(self, slugs):
        """The bulk-delete confirm (T181): ONE dialog naming every
        selected profile, defaulting to No, Escape leaving things
        untouched. Factored out so tests can read the box without
        showing it, like _profile_merge_box.

        Modal audit: this box is reached only from the bulk
        context-menu action — no existing test reaches it, and the
        bulk tests stub QMessageBox.exec."""
        names = []
        for slug in slugs:
            try:
                prof = self.store.get_profile(slug)
                names.append(
                    _displayed_name(
                        prof.get("display_name") or slug, slug
                    )
                )
            except StellaError:
                names.append(slug)
        box = QMessageBox(self)
        box.setWindowTitle("Delete profiles")
        box.setText(
            f"Move {len(slugs)} profiles to the trash?"
        )
        box.setInformativeText(
            "Profiles:\n"
            + "\n".join(f"- {name}" for name in names)
            + "\n\nYou can move them back later, or delete them "
            "forever from Trash in the File menu."
        )
        box.setIcon(QMessageBox.Warning)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setEscapeButton(QMessageBox.No)
        return box

    def _bulk_delete_profiles(self, slugs):
        """Delete several profiles at once (T181): one confirm
        naming them all, each to the trash (T23). A profile that
        fails to delete warns and the rest still go — one bad
        folder must not block the rest."""
        if not slugs:
            return
        box = self._bulk_delete_box(slugs)
        if box.exec() != QMessageBox.Yes:
            return
        moved = []
        for slug in slugs:
            try:
                self.store.delete_profile(slug)
            except StellaError as exc:
                self._warn(str(exc))
                continue
            moved.append(slug)
            win = self._profile_windows.pop(slug, None)
            if win is not None:
                win.close()
            for key in list(self._project_windows):
                if key[0] == slug:
                    self._project_windows.pop(key).close()
            self.debug_log.action(f"profile deleted: {slug}")
        if self._current_profile in moved:
            self.set_session(None, None)
        else:
            self.refresh_tree()
        if moved:
            self._say(
                f"Moved {len(moved)} profiles to the trash."
            )

    def _ask_bulk_include_projects(self, slugs) -> bool | None:
        """The bulk-export question (T181): include the projects
        in each package, or the profiles alone? One question for
        the whole selection, naming the total. Returns True to
        include, False for profiles alone, None when the user
        cancels. No projects anywhere means no question — the
        profiles alone are the only choice.

        Modal audit: reached only from the bulk export action;
        the bulk tests stub it with a QTimer clicker."""
        total = 0
        for slug in slugs:
            total += len([
                p for p in self.store.list_projects(slug)
                if not p.get("_damaged")
            ])
        if total == 0:
            return False
        box = QMessageBox(self)
        box.setWindowTitle("Include the projects?")
        box.setText(
            f"The {len(slugs)} selected profiles have {total} "
            f"project{'s' if total != 1 else ''} between them."
        )
        box.setInformativeText(
            "Include them and each package carries its projects "
            "with their weights, checkpoints, and notes. Profiles "
            "alone carry just the profiles."
        )
        include = box.addButton(
            "Include projects", QMessageBox.ButtonRole.AcceptRole
        )
        alone = box.addButton(
            "Profiles alone", QMessageBox.ButtonRole.AcceptRole
        )
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(include)
        box.setEscapeButton(cancel)
        box._stella_include_button = include
        box._stella_alone_button = alone
        box._stella_cancel_button = cancel
        box.exec()
        if box.clickedButton() is include:
            return True
        if box.clickedButton() is alone:
            return False
        return None

    def _bulk_overwrite_box(self, targets):
        """The bulk-overwrite dialog (T181): some of the packages
        already exist. One question for all of them, naming each.
        Factored out so tests can read the box without showing it.

        Modal audit: reached only from the bulk export action;
        the bulk tests stub it with a QTimer clicker."""
        box = QMessageBox(self)
        box.setWindowTitle("Exports already exist")
        box.setText(
            f"{len(targets)} package"
            f"{'s' if len(targets) != 1 else ''} already exist in "
            "that folder."
        )
        box.setInformativeText(
            "Overwrite them, or cancel and pick another folder?\n"
            + "\n".join(target.name for target in targets)
        )
        over = box.addButton(
            "Overwrite", QMessageBox.ButtonRole.AcceptRole
        )
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box._stella_overwrite_button = over
        box._stella_cancel_button = cancel
        return box

    def _ask_bulk_overwrite(self, targets) -> bool:
        """Ask whether to overwrite the existing bulk-export
        targets. A dialog that closes without a click (or a
        stubbed exec in a test) means do not overwrite — the safe
        answer."""
        box = self._bulk_overwrite_box(targets)
        box.exec()
        return box.clickedButton() is box._stella_overwrite_button

    def _bulk_export_profiles(self, slugs):
        """Export several profiles at once (T181): one package per
        profile, into one folder, on the job card (T106). One
        include-projects question and one overwrite question cover
        the whole selection. A profile that fails to export is
        named in the warning at the end; the rest still land."""
        if not slugs:
            return
        if self._job_already_running():
            return
        include = self._ask_bulk_include_projects(slugs)
        if include is None:
            self._say("Export cancelled.")
            return
        dest = QFileDialog.getExistingDirectory(
            self, "Export selected profiles to folder", str(Path.home())
        )
        if not dest:
            return
        targets = [
            Path(dest) / (slug + export_mod.PROFILE_EXPORT_SUFFIX)
            for slug in slugs
        ]
        force = False
        existing = [t for t in targets if t.exists()]
        if existing:
            if not self._ask_bulk_overwrite(existing):
                self._say("Export cancelled.")
                return
            force = True

        def job(ctx):
            exported = []
            failed = []
            for index, slug in enumerate(slugs):
                ctx.progress(index, len(slugs))
                if ctx.is_cancelled():
                    raise StellaError("Cancelled.")
                try:
                    export_mod.export_profile(
                        self.store, slug, dest,
                        include_projects=include, force=force,
                        should_stop=ctx.is_cancelled,
                    )
                    exported.append(slug)
                except StellaError as exc:
                    failed.append(f"{slug}: {exc}")
            if failed:
                raise StellaError(
                    "Some profiles did not export:\n"
                    + "\n".join(failed)
                )
            return (
                f"Exported {len(exported)} profiles to {dest}."
            )

        def on_finished(ok, message):
            self.refresh_tree()
            self.refresh_session()
            if not ok:
                self._warn(message)
            else:
                self._say(message.splitlines()[0] if message else "Done.")

        if self._start_job_worker(
            job, "Exporting profiles", True, on_finished=on_finished
        ):
            self._train_log_line(
                f"Exporting {len(slugs)} profiles..."
            )
        self.debug_log.action(
            f"bulk profile export started: {len(slugs)} profiles "
            f"to {dest}"
        )

    def _bulk_change_role(self, slugs):
        """Change the role on several profiles at once (T181):
        one role picker, applied to the whole selection. "No role"
        clears the role. A profile that fails to update warns and
        the rest still change.

        Modal audit: QInputDialog.getItem is reached only from
        this action; the bulk tests stub getItem."""
        items = ["No role"] + list(CANONICAL_ROLES)
        choice, ok = QInputDialog.getItem(
            self, "Change role",
            f"New role for the {len(slugs)} selected profiles:",
            items, 0, False,
        )
        if not ok:
            return
        role = "" if choice == "No role" else choice
        changed = 0
        for slug in slugs:
            try:
                self.store.update_profile(slug, role=role)
            except StellaError as exc:
                self._warn(str(exc))
                continue
            changed += 1
        self.refresh_tree()
        self.refresh_session()
        if changed:
            self._say(
                f"Changed the role for {changed} profiles."
            )

    # -- project actions --------------------------------------------
    def new_project(self):
        profile = self._selected_profile()
        if not profile:
            self._warn("Pick a profile first, then add a project to it.")
            return
        from .templates import (
            list_templates, load_template, template_project_kwargs,
        )

        dialog = NewProjectDialog(self, list_templates())
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.project_name()
        if not name:
            return
        kwargs: dict = {}
        template = dialog.template_name()
        if template:
            try:
                kwargs.update(
                    template_project_kwargs(load_template(template))
                )
            except StellaError as exc:
                self._warn(str(exc))
                return
        try:
            self.store.create_project(profile, name, **kwargs)
        except StellaError as exc:
            self._warn(str(exc))
            return
        self._current_project = name.lower()
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

    def clone_project(self, profile=None, project=None):
        """Clone a project (T112): the same dataset, settings, and
        metamorph mode under a new name, no checkpoints, fresh
        notes with a "cloned from" line. The session moves to the
        clone."""
        profile = profile or self._selected_profile()
        project = project or self._selected_project()
        if not profile or not project:
            return
        text, ok = QInputDialog.getText(
            self, "Clone project",
            f"Name for the copy of {project!r} "
            "(lowercase, dashes ok):",
        )
        if not ok or not text.strip():
            return
        try:
            data = self.store.clone_project(
                profile, project, text.strip()
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.debug_log.action(
            f"project cloned: {profile}/{project} to "
            f"{profile}/{data['name']}"
        )
        self.set_session(profile, data["name"])
        self._say(f"Cloned {project} as {data['name']}.")

    def delete_project(self, profile=None, project=None):
        profile = profile or self._selected_profile()
        project = project or self._selected_project()
        if not profile or not project:
            return
        while True:
            answer = self._delete_confirm_with_export(
                "Delete project",
                self._delete_project_text(profile, project),
                "Export this project first",
            )
            if answer == "export":
                # Export, then ask again: the delete still needs
                # its own Yes after the copy is safe.
                self._export_project_to_folder(profile, project)
                continue
            if answer != "yes":
                return
            break
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
        self._say(f"Moved project {project} to the trash.")

    # -- export / import --------------------------------------------
    def _export_project_to_folder(
        self, profile, project, bundle_dataset: bool = False
    ):
        """Pick a folder and export one project into it (T23: the
        project delete dialog's "Export first" shares this).
        Returns the export dir, or None when the user cancelled or
        the export failed (a warning was already shown).
        `bundle_dataset` copies the dataset into the package (T59);
        the delete path leaves it off — deleting a project does not
        delete the dataset file, so the reference still works."""
        # T167: the dialog title names the package before the
        # folder is picked — the user sees what will be created.
        dest = QFileDialog.getExistingDirectory(
            self,
            f"Export project to folder "
            f"(package: {project}{export_mod.EXPORT_SUFFIX})",
            str(Path.home()),
        )
        if not dest:
            return None
        try:
            out = export_mod.export_project(
                self.store, profile, project, dest,
                bundle_dataset=bundle_dataset,
            )
        except StellaError as exc:
            self._warn(str(exc))
            return None
        self.debug_log.action(
            f"project exported: {profile}/{project} to {out}"
        )
        return out

    def _export_all_projects(self, slug):
        """Export every project in a profile (T23: the profile
        delete dialog's "Export all projects first"). Returns True
        when every project exported; False when the user cancelled
        or any export failed (a warning was already shown)."""
        dest = QFileDialog.getExistingDirectory(
            self, "Export all projects to folder", str(Path.home())
        )
        if not dest:
            return False
        projects = [
            p for p in self.store.list_projects(slug)
            if not p.get("_damaged")
        ]
        if not projects:
            self._warn(f"Profile {slug} has no projects to export.")
            return False
        failed = []
        for proj in projects:
            try:
                export_mod.export_project(self.store, slug, proj["name"], dest)
            except StellaError as exc:
                failed.append(f"{proj['name']}: {exc}")
        if failed:
            self._warn(
                "Some projects did not export:\n" + "\n".join(failed)
            )
            return False
        self.debug_log.action(
            f"profile exported: {slug} ({len(projects)} projects) "
            f"to {dest}"
        )
        self._say(f"Exported {len(projects)} projects to {dest}.")
        return True

    # -- T117: the overwrite question (menu exports only) --------
    def _overwrite_box(self, target):
        """The overwrite dialog: the package folder already exists.
        Factored out so tests can read the box without showing it,
        like _profile_merge_box."""
        box = QMessageBox(self)
        box.setWindowTitle("Export already exists")
        box.setText(f"{target.name} already exists in that folder.")
        box.setInformativeText(
            "Overwrite it, or cancel and pick another folder?"
        )
        over = box.addButton(
            "Overwrite", QMessageBox.ButtonRole.AcceptRole
        )
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box._stella_overwrite_button = over
        box._stella_cancel_button = cancel
        return box

    def _ask_overwrite(self, target) -> bool:
        """Ask whether to overwrite an existing export folder.
        A dialog that closes without a click (or a stubbed exec in
        a test) means do not overwrite — the safe answer."""
        box = self._overwrite_box(target)
        box.exec()
        return box.clickedButton() is box._stella_overwrite_button

    def _export_job(self, export_fn, title, log_line):
        """Run an export on the job card (T106): the copy runs off
        the GUI thread with a determinate progress bar and a Cancel
        button, and a cancel leaves no partial package (the engine
        removes the staging dir, T1's atomicity). `export_fn` takes
        (on_progress, should_stop) and returns the output path.
        The lists refresh when the job finishes either way."""

        def job(ctx):
            out = export_fn(
                on_progress=lambda done, total: ctx.progress(
                    done, total
                ),
                should_stop=ctx.is_cancelled,
            )
            # T178: the success message carries the real package
            # size, not just the path.
            return (
                f"Exported to {out} "
                f"({export_mod.format_size(export_mod.package_size(out))})."
            )

        def on_finished(ok, message):
            self.refresh_tree()
            self.refresh_session()
            if not ok:
                self._warn(message)
            # On success _on_job_finished already said the message;
            # refresh_session says the session line after it, so say
            # the confirmation again, last (T50).
            else:
                self._say(message.splitlines()[0] if message else "Done.")

        if self._start_job_worker(job, title, True, on_finished=on_finished):
            self._train_log_line(log_line)

    def export_project(self, as_zip: bool = False):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to export.")
            return
        if self._job_already_running():
            return
        bundle = self._ask_bundle_dataset(profile, project)
        # T167: the dialog title names the package before the
        # folder is picked.
        suffix = export_mod.EXPORT_SUFFIX + (
            export_mod.ZIP_SUFFIX if as_zip else ""
        )
        dest = QFileDialog.getExistingDirectory(
            self,
            f"Export project to folder (package: {project}{suffix})",
            str(Path.home()),
        )
        if not dest:
            return
        target = Path(dest) / (project + suffix)
        force = False
        if target.exists():
            # T117: the folder already holds a package with this
            # name — overwrite, or stop here.
            if not self._ask_overwrite(target):
                self._say("Export cancelled.")
                return
            force = True
        # T178: the log line that starts the job carries the
        # estimated size; the success message carries the real one.
        estimate = export_mod.estimate_export_size(
            self.store, profile, project, bundle_dataset=bundle
        )
        self._export_job(
            lambda on_progress, should_stop: export_mod.export_project(
                self.store, profile, project, dest,
                bundle_dataset=bundle, force=force,
                on_progress=on_progress, should_stop=should_stop,
                as_zip=as_zip,
            ),
            "Exporting project",
            f"Exporting project {profile}/{project} "
            f"(about {export_mod.format_size(estimate)})...",
        )
        self.debug_log.action(
            f"project export started: {profile}/{project} to {dest}"
        )

    # -- T86: export a whole profile -------------------------------
    def _ask_include_projects(self, slug) -> bool | None:
        """The profile-export question (T86): include the profile's
        projects, or the profile alone? Returns True to include,
        False for the profile alone, None when the user cancels.
        No projects means no question — the profile alone is the
        only choice."""
        projects = [
            p for p in self.store.list_projects(slug)
            if not p.get("_damaged")
        ]
        if not projects:
            return False
        box = QMessageBox(self)
        box.setWindowTitle("Include the projects?")
        box.setText(
            f"Profile {slug!r} has {len(projects)} project"
            f"{'s' if len(projects) != 1 else ''}."
        )
        box.setInformativeText(
            "Include them and the package carries each project with "
            "its weights, checkpoints, and notes. Profile alone "
            "carries just the profile."
        )
        include = box.addButton(
            "Include projects", QMessageBox.ButtonRole.AcceptRole
        )
        alone = box.addButton(
            "Profile alone", QMessageBox.ButtonRole.AcceptRole
        )
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(include)
        box.setEscapeButton(cancel)
        box._stella_include_button = include
        box._stella_alone_button = alone
        box._stella_cancel_button = cancel
        box.exec()
        if box.clickedButton() is include:
            return True
        if box.clickedButton() is alone:
            return False
        return None

    def export_profile(self, as_zip: bool = False):
        profile = self._selected_profile()
        if not profile:
            self._warn("Pick a profile to export.")
            return
        if self._job_already_running():
            return
        include = self._ask_include_projects(profile)
        if include is None:
            self._say("Export cancelled.")
            return
        # T167: the dialog title names the package before the
        # folder is picked.
        suffix = export_mod.PROFILE_EXPORT_SUFFIX + (
            export_mod.ZIP_SUFFIX if as_zip else ""
        )
        dest = QFileDialog.getExistingDirectory(
            self,
            f"Export profile to folder (package: {profile}{suffix})",
            str(Path.home()),
        )
        if not dest:
            return
        target = Path(dest) / (profile + suffix)
        force = False
        if target.exists():
            if not self._ask_overwrite(target):
                self._say("Export cancelled.")
                return
            force = True
        # T178: the log line that starts the job carries the
        # estimated size; the success message carries the real one.
        estimate = export_mod.estimate_profile_export_size(
            self.store, profile, include_projects=include
        )
        self._export_job(
            lambda on_progress, should_stop: export_mod.export_profile(
                self.store, profile, dest,
                include_projects=include, force=force,
                on_progress=on_progress, should_stop=should_stop,
                as_zip=as_zip,
            ),
            "Exporting profile",
            f"Exporting profile {profile} "
            f"(about {export_mod.format_size(estimate)})...",
        )
        self.debug_log.action(
            f"profile export started: {profile} to {dest}"
        )

    # -- T170: export a recipe (settings only, no weights) --------
    def export_recipe(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to export a recipe for.")
            return
        if self._job_already_running():
            return
        # T167: the dialog title names the package before the
        # folder is picked.
        dest = QFileDialog.getExistingDirectory(
            self,
            f"Export recipe to folder "
            f"(package: {project}{export_mod.RECIPE_EXPORT_SUFFIX})",
            str(Path.home()),
        )
        if not dest:
            return
        target = Path(dest) / (project + export_mod.RECIPE_EXPORT_SUFFIX)
        force = False
        if target.exists():
            if not self._ask_overwrite(target):
                self._say("Export cancelled.")
                return
            force = True
        # T178: the log line that starts the job carries the
        # estimated size; the success message carries the real one.
        estimate = export_mod.estimate_recipe_export_size(
            self.store, profile, project
        )
        self._export_job(
            lambda on_progress, should_stop: export_mod.export_recipe(
                self.store, profile, project, dest, force=force,
                on_progress=on_progress, should_stop=should_stop,
            ),
            "Exporting recipe",
            f"Exporting recipe {profile}/{project} "
            f"(about {export_mod.format_size(estimate)})...",
        )
        self.debug_log.action(
            f"recipe export started: {profile}/{project} to {dest}"
        )

    # -- T173: export a bare adapter --------------------------------
    def export_adapter(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to export an adapter for.")
            return
        if self._job_already_running():
            return
        adapter_dir = self.store.project_dir(profile, project) / "adapter"
        if not (adapter_dir / "adapter_config.json").is_file():
            self._warn(
                f"Project {project!r} has no trained adapter yet. "
                "Train it first, then export the adapter."
            )
            return
        # T167: the dialog title names the package before the
        # folder is picked.
        dest = QFileDialog.getExistingDirectory(
            self,
            f"Export adapter to folder "
            f"(package: {project}{export_mod.ADAPTER_EXPORT_SUFFIX})",
            str(Path.home()),
        )
        if not dest:
            return
        target = Path(dest) / (project + export_mod.ADAPTER_EXPORT_SUFFIX)
        force = False
        if target.exists():
            if not self._ask_overwrite(target):
                self._say("Export cancelled.")
                return
            force = True
        # T178: the log line that starts the job carries the
        # estimated size; the success message carries the real one.
        estimate = export_mod.estimate_adapter_export_size(
            self.store, profile, project
        )
        self._export_job(
            lambda on_progress, should_stop: export_mod.export_adapter(
                self.store, profile, project, dest, force=force,
                on_progress=on_progress, should_stop=should_stop,
            ),
            "Exporting adapter",
            f"Exporting adapter {profile}/{project} "
            f"(about {export_mod.format_size(estimate)})...",
        )
        self.debug_log.action(
            f"adapter export started: {profile}/{project} to {dest}"
        )

    # -- T105: check a package without importing it -----------------
    def check_package(self):
        path = QFileDialog.getExistingDirectory(
            self, "Pick an export package folder", str(Path.home())
        )
        if not path:
            return
        report = export_mod.check_export(path)
        box = QMessageBox(self)
        box.setWindowTitle("Check package")
        box.setText(
            "All checks passed. Nothing was imported."
            if report["ok"]
            else "A check failed. Nothing was imported."
        )
        box.setInformativeText(
            export_mod.format_check_report(report)
        )
        box.setIcon(
            QMessageBox.Icon.Information if report["ok"]
            else QMessageBox.Icon.Warning
        )
        box.exec()

    def _ask_bundle_dataset(self, profile, project) -> bool:
        """The dataset offer (T59): when the project has a dataset
        that resolves on this PC, ask whether to copy it into the
        package, showing its size. No dataset, or one that does
        not resolve, means no question — the package references
        the dataset as usual. Returns True to bundle. A dialog
        that closes without a click (or a stubbed exec in a test)
        means reference only — the safe answer."""
        from .train import resolve_dataset_ref

        try:
            proj = self.store.get_project(profile, project)
        except StellaError:
            return False
        ref = proj.get("dataset_ref") or ""
        if not ref:
            return False
        try:
            path = resolve_dataset_ref(self.store, profile, project, ref)
        except StellaError:
            return False
        box = QMessageBox(self)
        box.setWindowTitle("Copy the dataset in?")
        box.setText(
            "Copy the dataset into the package? It is "
            f"{provision.format_size(path.stat().st_size)}."
        )
        box.setInformativeText(
            "Copied in, the package trains anywhere. Left out, the "
            "package only names the dataset, and the other PC needs "
            "its own copy."
        )
        copy_btn = box.addButton(
            "Copy it in", QMessageBox.ButtonRole.AcceptRole
        )
        ref_btn = box.addButton(
            "Reference only", QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(ref_btn)
        box.setEscapeButton(ref_btn)
        box._stella_copy_button = copy_btn
        box._stella_reference_button = ref_btn
        box.exec()
        return box.clickedButton() is copy_btn

    # -- T57: the profile already exists, and the package disagrees --
    def _profile_merge_box(self, slug, diff):
        """The merge-choice dialog: one line per differing field, two
        plain-word buttons. Factored out so tests can read the box
        without showing it. Both buttons close the dialog; the
        answer comes from which one was clicked."""
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("Profile already exists")
        box.setText(
            f"The profile {slug!r} is already here, but the package "
            "says something different."
        )
        lines = []
        for field in export_mod.PROFILE_BLOCK_FIELDS:
            if field not in diff:
                continue
            word = export_mod.PROFILE_FIELD_WORDS[field]
            local = diff[field]["local"] or "(blank)"
            package = diff[field]["package"] or "(blank)"
            lines.append(
                f"{word}: yours is {local!r}, the package has "
                f"{package!r}."
            )
        lines.append("")
        lines.append("Keep yours, or use the package's?")
        box.setInformativeText("\n".join(lines))
        keep = box.addButton(
            "Keep mine", QMessageBox.ButtonRole.AcceptRole
        )
        take = box.addButton(
            "Use the package's", QMessageBox.ButtonRole.AcceptRole
        )
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)
        box._stella_keep_button = keep
        box._stella_take_button = take
        return box

    def _ask_profile_merge(self, slug, diff):
        """The on_profile_conflict callback for import: show the
        merge dialog, return "keep" or "take". A dialog that closes
        without a click (or a stubbed exec in a test) keeps yours —
        the safe answer."""
        box = self._profile_merge_box(slug, diff)
        box.exec()
        if box.clickedButton() is box._stella_take_button:
            return "take"
        return "keep"

    def _confirm_import_preview(self, path, summary):
        """Show the import preview dialog (T58). Returns
        (confirmed, profile_choice, into_target): confirmed is
        False when the user cancels (nothing is imported);
        profile_choice is the preview's merge choice, or None
        when there was no diff to choose over; into_target is
        (profile, project) when the user picked the adapter
        import's "into the current project" choice (T173), else
        None. Factored out so tests can stub the dialog and still
        exercise the import. The into-current-project choice is
        offered only when the session project shares the
        adapter's base — importing into a different base is
        refused, so it is never offered."""
        into_option = None
        if summary.get("kind") == export_mod.ADAPTER_PACKAGE_KIND:
            profile = self._current_profile
            project = self._current_project
            if profile and project:
                try:
                    target_prof = self.store.get_profile(profile)
                    self.store.get_project(profile, project)
                    adapter = {"base": summary.get("adapter_base", "")}
                    if export_mod.adapter_base_matches(
                        target_prof, adapter
                    ):
                        into_option = (profile, project)
                except StellaError:
                    into_option = None
        dialog = ImportPreviewDialog(
            self, summary, into_option=into_option
        )
        if dialog.exec() != QDialog.Accepted:
            return False, None, None
        return True, dialog.profile_choice(), dialog.into_project()

    # -- T117: the import collision question -----------------------
    def _import_collision_box(self, slug):
        """The collision dialog: the project already exists here.
        Factored out so tests can read the box without showing it,
        like _profile_merge_box."""
        box = QMessageBox(self)
        box.setWindowTitle("Project already exists")
        box.setText(f"The project {slug!r} is already here.")
        box.setInformativeText(
            "Import it as a copy under a new name, replace the one "
            "here (the old one goes to the trash), or cancel?"
        )
        copy_btn = box.addButton(
            "Import as a copy", QMessageBox.ButtonRole.AcceptRole
        )
        replace_btn = box.addButton(
            "Replace it", QMessageBox.ButtonRole.AcceptRole
        )
        cancel_btn = box.addButton(
            "Cancel", QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(copy_btn)
        box.setEscapeButton(cancel_btn)
        box._stella_copy_button = copy_btn
        box._stella_replace_button = replace_btn
        box._stella_cancel_button = cancel_btn
        return box

    def _ask_import_collision(self, slug):
        """Ask what to do with a project that already exists:
        "copy", "replace", or None when the user cancels. A dialog
        that closes without a click means cancel — the safe
        answer."""
        box = self._import_collision_box(slug)
        box.exec()
        if box.clickedButton() is box._stella_copy_button:
            return "copy"
        if box.clickedButton() is box._stella_replace_button:
            return "replace"
        return None

    def import_package(self):
        path = QFileDialog.getExistingDirectory(
            self, "Pick an export package folder", str(Path.home())
        )
        if not path:
            return
        self._import_package_from(path)

    def import_single_file_package(self):
        """Import a `.stella` single-file package (T171): the same
        import flow as import_package, from a file picker. Any
        kind imports — project, profile, recipe, or adapter."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a Stella package file", str(Path.home()),
            "Stella packages (*.stella);;All files (*)",
        )
        if not path:
            return
        self._import_package_from(path)

    def _import_package_from(self, path):
        """The import flow shared by folder and single-file
        imports (T171): preview, confirm, merge/collision
        choices, then the worker import."""
        if self._job_already_running():
            return
        # The preview (T58): what the package is, before anything
        # is imported. A bad package warns and refreshes, exactly
        # as before — no preview for a package that cannot import.
        try:
            summary = export_mod.preview_export(
                self.store, path,
                installed_models=MODEL_CACHE.models(),
            )
        except StellaError as exc:
            self._warn(str(exc))
            self.refresh_tree()
            self.refresh_session()
            return
        # The real dialog returns (confirmed, choice, into_target);
        # older stubs return (confirmed, choice) — both are
        # accepted here.
        confirmed_result = self._confirm_import_preview(path, summary)
        confirmed, choice = (
            confirmed_result[0], confirmed_result[1]
        )
        into_target = (
            confirmed_result[2]
            if len(confirmed_result) > 2
            else None
        )
        if not confirmed:
            return
        # Every choice is resolved HERE, on the GUI thread, before
        # the worker starts (T106): a modal cannot run in a worker
        # thread. The profile merge (T57) still asks when the
        # preview had no choice to make; the collision (T117) asks
        # when the project already exists. An adapter package
        # (T173) never asks about a collision: a new-project
        # import lands under a copy name on its own, and an
        # into-existing import targets a project that is already
        # there by design.
        if choice is None and summary.get("profile_diff"):
            choice = self._ask_profile_merge(
                summary["profile"], summary["profile_diff"]
            )
        collision = None
        if summary.get("kind") in (
            export_mod.PROJECT_PACKAGE_KIND,
            export_mod.RECIPE_PACKAGE_KIND,
        ):
            if summary.get("project_existed"):
                collision = self._ask_import_collision(
                    summary["project"]
                )
                if collision is None:
                    self._say("Import cancelled.")
                    return
        box: dict = {}

        def job(ctx):
            result = export_mod.import_export(
                self.store, path,
                profile_choice=choice,
                collision=collision,
                # The base-health check (T61) reads the cached
                # model list: an uninstalled tag warns, never blocks.
                installed_models=MODEL_CACHE.models(),
                on_progress=lambda done, total: ctx.progress(
                    done, total
                ),
                should_stop=ctx.is_cancelled,
                into_profile=into_target[0] if into_target else None,
                into_project=into_target[1] if into_target else None,
            )
            box["result"] = result
            return _import_message(result)

        def on_finished(ok, message):
            # The lists refresh on failure too (T106): the window
            # matches the disk even when the import fails.
            self.refresh_tree()
            self.refresh_session()
            if not ok:
                self._warn(message)
                return
            result = box.get("result")
            if result is None:
                return
            if "projects" in result:
                # A profile package (T86): the session lands on its
                # first project, or the profile alone.
                names = result["projects"]
                self.debug_log.action(
                    f"profile imported: {result['profile']} "
                    f"({len(names)} projects)"
                )
                self.set_session(
                    result["profile"],
                    names[0] if names else None,
                )
            else:
                self.debug_log.action(
                    f"project imported: "
                    f"{result['profile']}/{result['project']}"
                )
                self.set_session(result["profile"], result["project"])
            # An import warning (T41: a "done" package with no
            # weights imports as a draft) is shown, not buried: the
            # project the user just imported is not what the package
            # claimed it was.
            for warning in result.get("warnings", []):
                self._warn(warning)
            # A missing dataset (T59): offer to find the file now,
            # so the imported project trains without a trip to its
            # window. A profile import names its missing datasets
            # in the message instead — one dialog per project
            # would stack up.
            if result.get("dataset_missing") and "project" in result:
                self._offer_locate_dataset(
                    result["profile"], result["project"],
                    result.get("dataset_ref", ""),
                )
            # The confirmation goes last (T50): set_session's
            # refresh says the session line, so say the import
            # message again, after it.
            self._say(message.splitlines()[0] if message else "Done.")

        self._start_job_worker(
            job, "Importing package", True, on_finished=on_finished
        )
        self._train_log_line(f"Importing package from {path}...")

    def _dataset_locate_box(self, ref):
        """The missing-dataset repair dialog (T59): one question,
        two plain-word buttons. Factored out so tests can read the
        box without showing it, like _profile_merge_box."""
        box = QMessageBox(self)
        box.setWindowTitle("Dataset not on this PC")
        box.setText(
            f"The dataset {ref!r} is not on this PC. Find it now?"
        )
        box.setInformativeText(
            "Pick the file and the project uses it. Or leave it for "
            "later. The project still opens."
        )
        locate = box.addButton(
            "Locate the file", QMessageBox.ButtonRole.AcceptRole
        )
        later = box.addButton(
            "Not now", QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(later)
        box.setEscapeButton(later)
        box._stella_locate_button = locate
        box._stella_later_button = later
        return box

    def _offer_locate_dataset(self, profile, project, ref):
        """The missing-dataset repair (T59): after an import whose
        dataset is not on this PC, offer to pick the file now. A
        pick stores it as the project's dataset; "Not now" (or a
        dialog that closes without a click) leaves the ref as
        imported."""
        box = self._dataset_locate_box(ref)
        box.exec()
        if box.clickedButton() is not box._stella_locate_button:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Find the dataset file", str(Path.home()),
            "JSONL datasets (*.jsonl);;All files (*)",
        )
        if not path:
            return
        try:
            self.store.update_project(
                profile, project, dataset_ref=path
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.refresh_session()
        self._say(f"Dataset set to {path}.")

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
        selected project.

        While a run is live on a project, the panel stays pinned
        to that project (T47): switching the session away leaves
        the checkpoints, curve, log, and progress untouched, and
        the pin note names the running project. The pin clears
        when the run finishes.
        """
        # Pinned (T47): a live run's project is not the session's.
        running = self._running_job_key
        session = (
            (self._current_profile, self._current_project)
            if self._current_profile and self._current_project
            else None
        )
        # The dataset health line (T83) follows the SESSION, not
        # the pinned project: it is the session's dataset the user
        # is about to train on. Updated on every refresh, not just
        # on a project switch — picking a dataset refreshes the
        # panel for the same project.
        self._refresh_dataset_health()
        if running is not None and running != session:
            job = "Training" if self._training_running() else "Sleep"
            self.train_pin_label.setText(
                f"{job} is running on {running[1]}. This panel stays "
                "with it until it finishes."
            )
            self.train_pin_label.setVisible(True)
            return
        self.train_pin_label.setVisible(False)
        self.train_checkpoints.clear()
        self.run_history_list.clear()
        self.sleep_cycles.clear()
        if not self._current_profile or not self._current_project:
            self.train_loss.setText("Pick a project to train.")
            self._train_panel_project = None
            self.loss_curve.clear()
            self._reset_run_stats()
            self.train_progress.setMaximum(1)
            self.train_progress.setValue(0)
            self.checkpoint_detail_label.setText(
                "Pick a checkpoint to see its details."
            )
            self.checkpoint_disk_label.setText("")
            self.export_estimate_label.setText("")
            # T161: no project, no overrides and no checkpoint
            # picker — both belong to a project.
            self.run_dataset_edit.setText("")
            self.run_base_edit.setText("")
            self.gguf_checkpoint_combo.clear()
            self.gguf_checkpoint_combo.addItem("Trained adapter")
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
                self.train_progress.setMaximum(1)
                self.train_progress.setValue(0)
            # The last run's curve comes back with the project
            # (T20): rebuilt from its own run log.
            points, total = self._last_run_curve(*key)
            self.loss_curve.set_points(points, total)
            self._reset_run_stats()
            # T161: the run overrides belong to the project they
            # were typed for — a switch clears them, so a leftover
            # override never follows the session.
            self.run_dataset_edit.setText("")
            self.run_base_edit.setText("")
        from .train import list_checkpoints, list_runs

        checkpoints = list_checkpoints(
            self.store, self._current_profile, self._current_project
        )
        total_bytes = 0
        for ck in checkpoints:
            loss = ck.get("loss")
            label = f"step {ck['step']}"
            if loss is not None:
                label += f"  loss {loss:.4f}"
            size = ck.get("size_bytes") or 0
            total_bytes += size
            label += f"  {_fmt_bytes(size)}"
            modified = ck.get("modified")
            if modified:
                label += f"  {_fmt_date(modified)}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, ck["step"])
            self.train_checkpoints.addItem(item)
        # Disk usage (T150): what all the checkpoints cost.
        if checkpoints:
            self.checkpoint_disk_label.setText(
                f"Checkpoints use {_fmt_bytes(total_bytes)} on disk "
                f"({len(checkpoints)} checkpoint"
                f"{'s' if len(checkpoints) != 1 else ''})."
            )
        else:
            self.checkpoint_disk_label.setText("No checkpoints yet.")
        # T161: the GGUF checkpoint picker follows the same list —
        # the trained adapter first, then one entry per checkpoint.
        self.gguf_checkpoint_combo.blockSignals(True)
        try:
            self.gguf_checkpoint_combo.clear()
            self.gguf_checkpoint_combo.addItem("Trained adapter")
            for ck in checkpoints:
                self.gguf_checkpoint_combo.addItem(
                    f"Checkpoint step {ck['step']}", ck["step"]
                )
        finally:
            self.gguf_checkpoint_combo.blockSignals(False)
        # The detail label follows the selection; a refresh clears
        # the list, so it goes back to the resting line.
        self.checkpoint_detail_label.setText(
            "Pick a checkpoint to see its details."
        )
        # Past runs (T151): date, steps, final loss per run. The
        # run's curve is shown on click; nothing is selected by
        # default.
        self._run_history = list_runs(
            self.store.project_dir(
                self._current_profile, self._current_project
            )
        )
        for run in self._run_history:
            started = run.get("started_at") or ""
            date = started[:10] if started else "unknown date"
            final = run.get("final_loss")
            if run.get("finished") and not run.get("stopped"):
                state = ""
            elif run.get("stopped"):
                state = ", paused"
            else:
                state = ", unfinished"
            loss_text = (
                f", final loss {final:.4f}"
                if final is not None
                else ", no loss recorded"
            )
            item = QListWidgetItem(
                f"{date}: {run['steps']} steps{loss_text}{state}"
            )
            item.setData(Qt.UserRole, run["run_id"])
            self.run_history_list.addItem(item)
        self._refresh_export_estimate()
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

    def _refresh_dataset_health(self):
        """The dataset health line (T83): row count, format, and a
        rough token count for a healthy dataset; the problem, with
        line numbers, for a bad one. A tiny dataset says so
        outright — the pre-train check asks before starting on
        one, and the label should not hide why."""
        if not self._current_profile or not self._current_project:
            self.dataset_health_label.setText("")
            return
        try:
            proj = self.store.get_project(
                self._current_profile, self._current_project
            )
        except StellaError:
            self.dataset_health_label.setText("")
            return
        ref = proj.get("dataset_ref") or ""
        if not ref.strip():
            self.dataset_health_label.setText(
                "No dataset yet. Pick a file, or use the sample dataset."
            )
            return
        from .train import check_dataset

        check = check_dataset(
            self.store, self._current_profile, self._current_project, ref
        )
        if check["status"] == "ok":
            text = (
                f"{check['count']} examples, {check['format']} format, "
                f"about {check['est_tokens']:,} tokens "
                f"({check['train']} to train on, {check['val']} held "
                "out to validate)."
            )
            if check["tiny"]:
                text += (
                    " Only a few examples: the model will memorize "
                    "these rows, not generalize from them."
                )
            self.dataset_health_label.setText(text)
        elif check["status"] == "missing":
            self.dataset_health_label.setText(
                f"Dataset not found: {ref}. Pick a file that exists, "
                "or use the sample dataset."
            )
        else:  # invalid
            self.dataset_health_label.setText(
                f"Dataset problem: {check['error']}"
            )

    # -- checkpoints (T150) -----------------------------------------

    def _selected_checkpoint_step(self) -> int | None:
        """The checkpoint step picked in the list, or None."""
        item = self.train_checkpoints.currentItem()
        if item is None:
            return None
        step = item.data(Qt.UserRole)
        return int(step) if step is not None else None

    def _on_checkpoint_selected(self, item):
        """A checkpoint click fills the detail view (T150): step,
        loss, size, date — in plain words."""
        step = item.data(Qt.UserRole)
        if step is None:
            return
        from .train import list_checkpoints

        for ck in list_checkpoints(
            self.store, self._current_profile, self._current_project
        ):
            if ck["step"] != step:
                continue
            loss = ck.get("loss")
            loss_text = (
                f"loss {loss:.4f}" if loss is not None else "no loss recorded"
            )
            self.checkpoint_detail_label.setText(
                f"Step {ck['step']}, {loss_text}, "
                f"{_fmt_bytes(ck.get('size_bytes') or 0)}, "
                f"saved {_fmt_date(ck.get('modified') or 0)}."
            )
            return

    def _resume_from_checkpoint(self):
        """Resume training from the picked checkpoint (T150), not
        the latest one."""
        step = self._selected_checkpoint_step()
        if step is None:
            self._warn("Pick a checkpoint first.")
            return
        self.start_training(resume=True, from_checkpoint=step)

    def _delete_checkpoint(self):
        """Delete the picked checkpoint (T150).

        Permanent: the point is freeing disk, and the trash does
        not free disk. Confirms first with the size shown,
        defaulting to No (the T24 destructive-paths rule).
        Modal audit: this confirm opens only from the Delete
        button. No existing test clicks it; the new tests stub
        QMessageBox.question.
        """
        step = self._selected_checkpoint_step()
        if step is None:
            self._warn("Pick a checkpoint first.")
            return
        from .train import delete_checkpoint, list_checkpoints

        size = 0
        for ck in list_checkpoints(
            self.store, self._current_profile, self._current_project
        ):
            if ck["step"] == step:
                size = ck.get("size_bytes") or 0
                break
        answer = QMessageBox.question(
            self,
            "Delete checkpoint?",
            f"Delete checkpoint step {step} ({_fmt_bytes(size)})? "
            "This frees the disk space for good. It cannot be "
            "undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self._say("Checkpoint kept.")
            return
        try:
            result = delete_checkpoint(
                self.store, self._current_profile, self._current_project,
                step,
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self._say(
            f"Deleted checkpoint step {step}, "
            f"freed {_fmt_bytes(result['freed_bytes'])}."
        )
        self.refresh_train_panel()

    def _prune_checkpoints(self):
        """Delete all but the newest N checkpoints (T150).

        N comes from the spinbox (default 3). The confirm shows
        the total size before and after plus the space freed,
        and defaults to No — the deletion is permanent.
        Modal audit: this confirm opens only from the Prune
        button. No existing test clicks it; the new tests stub
        QMessageBox.question.
        """
        keep = self.checkpoint_keep_spin.value()
        from .train import list_checkpoints, prune_checkpoints

        checkpoints = list_checkpoints(
            self.store, self._current_profile, self._current_project
        )
        if len(checkpoints) <= keep:
            self._say(
                f"Nothing to prune: {len(checkpoints)} checkpoint"
                f"{'s' if len(checkpoints) != 1 else ''} kept, "
                f"keeping the newest {keep}."
            )
            return
        doomed = checkpoints[:-keep]
        freed = sum(c.get("size_bytes") or 0 for c in doomed)
        total = sum(c.get("size_bytes") or 0 for c in checkpoints)
        answer = QMessageBox.question(
            self,
            "Prune checkpoints?",
            f"Delete {len(doomed)} older checkpoint"
            f"{'s' if len(doomed) != 1 else ''} and keep the newest "
            f"{keep}? Checkpoints use {_fmt_bytes(total)} now, "
            f"{_fmt_bytes(total - freed)} after, freeing "
            f"{_fmt_bytes(freed)}. This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self._say("Checkpoints kept.")
            return
        try:
            result = prune_checkpoints(
                self.store, self._current_profile, self._current_project,
                keep=keep,
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self._say(
            f"Pruned {len(result['deleted'])} checkpoint"
            f"{'s' if len(result['deleted']) != 1 else ''}, "
            f"freed {_fmt_bytes(result['freed_bytes'])}. "
            f"Checkpoints now use {_fmt_bytes(result['total_after'])}."
        )
        self.refresh_train_panel()

    # -- past runs (T151) -------------------------------------------

    def _on_run_selected(self, item):
        """A past run's click shows its loss curve in the chart
        (T151): the finished run's curve, from the log. No
        settings are shown anywhere here (T16)."""
        run_id = item.data(Qt.UserRole)
        for run in self._run_history:
            if run["run_id"] != run_id:
                continue
            self.loss_curve.set_points(
                run["points"], run.get("total_steps") or 0
            )
            final = run.get("final_loss")
            loss_text = (
                f"final loss {final:.4f}"
                if final is not None
                else "no loss recorded"
            )
            started = run.get("started_at") or ""
            date = started[:10] if started else "unknown date"
            self.train_loss.setText(
                f"Run from {date}: {run['steps']} steps, {loss_text}."
            )
            return

    # -- export estimate (T153) -------------------------------------

    def _refresh_export_estimate(self):
        """The export estimate label (T153): merged size, output
        size, rough time — beside the Export button, before the
        user commits. Same metadata gate as the pre-train
        estimate: a remote base ref never fetches on a refresh,
        so the estimate only computes for a local folder or
        downloaded weights. No adapter yet means no estimate
        (there is nothing to export)."""
        if not self._current_profile or not self._current_project:
            self.export_estimate_label.setText("")
            return
        project_dir = self.store.project_dir(
            self._current_profile, self._current_project
        )
        if not (project_dir / "adapter" / "adapter_config.json").is_file():
            self.export_estimate_label.setText("")
            return
        try:
            prof = self.store.get_profile(self._current_profile)
        except StellaError:
            self.export_estimate_label.setText("")
            return
        base_ref = (prof.get("base_ref") or "").strip()
        if not base_ref:
            self.export_estimate_label.setText("")
            return
        local = Path(base_ref).expanduser().is_dir()
        ready = False
        if not local:
            try:
                ready = (
                    provision.weights_status(
                        self.store, self._current_profile
                    )["state"]
                    == "ready"
                )
            except StellaError:
                ready = False
        if not local and not ready:
            self.export_estimate_label.setText("")
            return
        from .gguf import estimate_export, format_export_estimate

        # T161: the estimate follows the picked quant, not the
        # default — the size is the picked quant's size.
        quant = self.gguf_quant_combo.currentText().strip() or DEFAULT_QUANT
        try:
            estimate = estimate_export(
                self.store, self._current_profile, self._current_project,
                quant=quant,
            )
        except StellaError:
            self.export_estimate_label.setText("")
            return
        self.export_estimate_label.setText(
            format_export_estimate(estimate)
        )

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
        # The pick is validated like the project window's (T45):
        # a valid file reports its example count, a malformed one
        # warns with the bad line. A picked file always exists, so
        # "missing" cannot happen here.
        from .train import check_dataset

        check = check_dataset(
            self.store, self._current_profile, self._current_project,
            path,
        )
        if check["status"] == "ok":
            self._say(
                f"Dataset set to {path} "
                f"({check['count']} examples)."
            )
        elif check["status"] == "invalid":
            self._warn(
                f"Dataset set to {path}, but the file has a problem: "
                f"{check['error']}"
            )
        else:
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

    def _browse_run_dataset(self):
        """Pick the run-override dataset file (T161): a file
        dialog, like the project's Pick dataset file — but this
        choice lives only in the panel, never in the project."""
        path, _selected = QFileDialog.getOpenFileName(
            self, "Pick a dataset file for this run", str(Path.home())
        )
        if path:
            self.run_dataset_edit.setText(path)

    def _dataset_preflight_ok(
        self, profile: str, project: str,
        dataset_ref: str | None = None,
    ) -> bool:
        """The pre-train dataset check (T83): True when the run may
        start. A failing check blocks the run with the errors
        named (a dialog + a log line + the status bar, so the
        reason is visible wherever the user is looking); a tiny
        dataset asks to proceed. The check reuses T45's validator
        (check_dataset) — one rule for what a dataset is,
        wherever it is checked.

        Modal audit: the tiny-dataset question is the only new
        modal on this path, and it only appears when the dataset
        is valid but tiny — every existing test that reaches
        start_training either has no dataset (blocked, no
        question) or a full one. The new tests stub the question.
        """
        try:
            proj = self.store.get_project(profile, project)
        except StellaError as exc:
            self._warn(str(exc))
            return False
        # T161: a run-override dataset is the dataset this run is
        # checked against — the stored ref only when no override
        # was given.
        if dataset_ref is None:
            ref = proj.get("dataset_ref") or ""
        else:
            ref = dataset_ref
        if not ref.strip():
            message = (
                "This project has no dataset set. Pick a dataset "
                "file or use the sample dataset first."
            )
            self._train_log_line(message)
            self._warn(message)
            self._say("Training not started.")
            return False
        from .train import check_dataset

        check = check_dataset(self.store, profile, project, ref)
        if check["status"] != "ok":
            message = f"Dataset problem: {check['error']}"
            self._train_log_line(message)
            self._warn(message)
            self._say("Training not started.")
            return False
        if check["tiny"]:
            answer = QMessageBox.question(
                self,
                "Train on only a few examples?",
                f"This dataset has only {check['count']} examples. "
                "The model will memorize these rows, not learn "
                "from them. Train anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self._say("Training not started.")
                return False
        return True

    def _governing_seat_ok(self, profile: str) -> bool:
        """The governing-seat warning (T116): True when training
        may start. A profile bound for a governing seat whose base
        is not abliterated warns first, naming the seat and the
        base; anything else starts without a word.

        Modal audit: this question only appears when the profile
        carries a governing-seat marker AND a stock base — every
        existing test that reaches start_training uses unmarked
        profiles, so none of them meets it. The new tests stub
        the question."""
        try:
            prof = self.store.get_profile(profile)
        except StellaError:
            return True
        warning = governing_seat_warning(prof)
        if warning is None:
            return True
        answer = QMessageBox.question(
            self,
            "Train a governing seat on a stock base?",
            warning + " Train anyway?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self._say("Training not started.")
            return False
        return True

    def start_training(self, resume: bool = False,
                       max_steps: int | None = None,
                       from_checkpoint: int | None = None,
                       dataset_path: str | None = None,
                       base_ref: str | None = None):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to train.")
            return
        # T161: the run overrides — explicit args win, else the
        # panel fields. Blank means no override: the project's
        # dataset and the profile's base, as before.
        if dataset_path is None:
            dataset_path = self.run_dataset_edit.text().strip() or None
        if base_ref is None:
            base_ref = self.run_base_edit.text().strip() or None
        # One job at a time (T29): training refuses while sleep OR
        # any job-card job runs — a probe loading models beside a
        # training run is the OOM shape the slot exists to stop.
        if self._job_already_running():
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
        # Re-training a finished project replaces the finished
        # adapter (T25): ask first. A "yes" passes force through
        # to the worker; a "no" stops here. Resume never asks —
        # it extends, and the loop announces that instead.
        force = False
        if not resume:
            status = self.store.get_project(profile, project).get("status")
            if status == "done":
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
        from .train import TRAINING_INSTALL_HINT, training_deps_missing

        missing = training_deps_missing()
        if missing:
            # The hint shows as a dialog now (T49): a log line is
            # only visible when the user scrolls to the Train log.
            # The log line stays too — the hint is worth keeping.
            hint = (
                "Training packages missing: " + ", ".join(missing) + ". "
                + TRAINING_INSTALL_HINT
            )
            self._train_log_line(hint)
            self._warn(hint)
            self._say("Training packages missing.")
            return
        # Settings live in the store now (the project window saves
        # them); there is no form left to save from here. But the
        # weights may still be missing: offer the download first.
        # T161: a base override skips the offer — the run starts
        # from the override base, not the profile's weights, so
        # the profile's download state is not the run's business.
        if base_ref is None and not self._weights_offer(profile):
            return
        # The pre-train dataset check (T83), the last gate before
        # the worker starts: a failing check blocks the run with
        # the errors named, a tiny dataset asks to proceed. It
        # runs after the deps and weights checks, so a missing
        # training stack or missing weights is still reported
        # first — the user fixes one thing at a time. T161: the
        # check runs against the override dataset when one is set.
        if not self._dataset_preflight_ok(profile, project, dataset_path):
            return
        # The governing-seat warning (T116), after the dataset
        # check: a profile bound for a governing seat whose base
        # is not abliterated warns, naming the seat and the base.
        # It runs last, so a blocked run never asks a question
        # about a run that cannot start.
        if not self._governing_seat_ok(profile):
            return
        self._train_worker = TrainWorker(
            self.store, profile, project, resume=resume, force=force,
            max_steps=max_steps, from_checkpoint=from_checkpoint,
            dataset_path=dataset_path, base_ref=base_ref,
        )
        self._train_worker.progress.connect(self._on_train_progress)
        self._train_worker.log.connect(self._train_log_line)
        self._train_worker.log.connect(self.job_card.set_status)
        self._train_worker.finished.connect(self._on_train_finished)
        self._run_started_at = None
        self.go_btn.setEnabled(False)
        self.train_resume_btn.setEnabled(False)
        self.train_proof_btn.setEnabled(False)
        self.train_pause_btn.setEnabled(True)
        self._set_activity(
            "training", "Resuming training..." if resume else "Training..."
        )
        # A proof run (T95) says so on the card and in the log, so
        # the short run is never mistaken for a full one that
        # stopped early.
        if max_steps is not None and not resume:
            job_title = f"Proof run ({max_steps} steps)"
            start_line = (
                f"Starting proof run ({max_steps} steps)..."
            )
        else:
            job_title = "Resuming training" if resume else "Training"
            start_line = (
                "Resuming training..." if resume else "Starting training..."
            )
        self.job_card.start(
            job_title, True,
            # The card morphs out of the Train tile (T149).
            from_rect=self._job_button_rect("train"),
            reduced_motion=reduced_motion(),
        )
        self._train_log_line(start_line)
        self.debug_log.action(
            f"training started: {profile}/{project} (resume={resume})"
        )
        # The Train panel pins to this project until the run ends
        # (T47): the session may move on, the panel does not.
        self._running_job_key = (profile, project)
        self._train_worker.start()
        self._refresh_checklist()

    def pause_training(self):
        if self._train_worker is not None:
            self._train_worker.request_stop()
            self._train_log_line(
                "Pausing after this step (checkpoint will save)..."
            )

    def _on_estimate(self):
        """The dry run (T85): RAM fit + steps + disk, computed
        from metadata only — no model load — and shown in the log
        and on the estimate label. An explicit click, so a remote
        base ref may fetch its config here (unlike the automatic
        label refresh, which never fetches). A run that will not
        fit warns in the report itself."""
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project first.")
            return
        from .train import (
            estimate_run,
            format_estimate,
            format_estimate_short,
        )

        try:
            estimate = estimate_run(self.store, profile, project)
        except StellaError as exc:
            self._warn(str(exc))
            return
        report = format_estimate(estimate)
        self._train_log_line("Dry run (no model loaded):")
        for line in report.splitlines():
            self._train_log_line(line)
        short = format_estimate_short(estimate)
        self.train_estimate_label.setText(short)
        # The label refresh keeps the dry-run answer until the
        # model or dataset changes (it would otherwise overwrite
        # it with "unavailable" for a remote base whose weights
        # are not downloaded yet).
        self._estimate_cache_key = self._estimate_key(profile, project)
        self._estimate_cache_text = short
        self._say(short.split(".")[0] + ".")

    def _estimate_key(self, profile: str, project: str) -> tuple | None:
        """The estimate cache key for a session (T84): what the
        estimate was computed from. None when the manifests
        cannot be read."""
        try:
            prof = self.store.get_profile(profile)
            proj = self.store.get_project(profile, project)
        except StellaError:
            return None
        return (
            profile, project,
            proj.get("dataset_ref") or "",
            (prof.get("base_ref") or "").strip(),
        )

    def _on_train_progress(self, step: int, total: int, loss: float,
                           epoch: int = 0):
        self.train_progress.setMaximum(max(1, total))
        self.train_progress.setValue(step)
        self.train_loss.setText(f"Step {step} / {total}, loss {loss:.4f}")
        if self._sleep_running():
            self.job_card.set_progress(step, total)
            self.job_card.set_status(f"Sleep: step {step} / {total}")
        else:
            self.job_card.set_progress(step, total)
            self.job_card.set_status(f"Training: step {step} / {total}")
        if step > 0:
            # Step 0 is the "started" marker, not a real point.
            self.loss_curve.append_point(step, loss, total)
            self._update_run_stats(step, total, epoch)
        if self._sleep_running():
            self._set_activity("sleep", f"Sleep: step {step} / {total}")
        else:
            self._set_activity("training", f"Training: step {step} / {total}")

    def _on_train_finished(self, ok: bool, message: str):
        # Which project just finished (T47): the panel may be
        # showing another project by now, and the finished run's
        # summary belongs to its own project, not this panel's.
        finished_key = self._running_job_key
        self._running_job_key = None  # unpins the Train panel (T47)
        self.train_pause_btn.setEnabled(False)
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        self.debug_log.action(f"training finished: ok={ok}: {message}")
        # The finish moment (T145): the card glows with the summary
        # for a beat, then hides. The summary is the same first
        # line the status bar gets below.
        self.job_card.finish_moment(
            message.splitlines()[0] if message else "Training done.",
            reduced_motion(),
        )
        # The finished run's curve and summary stay visible (T20):
        # the curve keeps its points, the loss line keeps its final
        # step, and the card says done. refresh_session re-enables
        # Go and Resume; it must not wipe the card (same project,
        # so refresh_train_panel leaves both alone).
        self.stat_time_left.setText("Time left: done")
        self.refresh_tree()
        self.refresh_session()
        # T96: the Train panel's summary line keeps the finished
        # run's losses — training and validation — so the number
        # that says whether the tune generalized stays visible
        # after the run, not just in the log. Only when the
        # message carries a val loss (a run that never validated
        # leaves the live line alone — a finished run keeps its
        # final step, T20), and only when the panel shows the
        # finished project (a run on another project must not
        # write its summary into this panel, T47). A missing key
        # (no run was tracked) updates — the panel is the
        # session's own.
        if ok and message and "Validation loss" in message:
            session_key = (self._current_profile, self._current_project)
            if finished_key is None or finished_key == session_key:
                self.train_loss.setText(message.splitlines()[0])
        # The confirmation goes last (T50): refresh_session reports
        # the session in the status bar, and a _say before it would
        # be overwritten before the user ever sees it.
        self._say(message.splitlines()[0] if message else "Training done.")

    def _on_job_finished(self, ok: bool, message: str):
        self._job_title = None
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        # The finish moment (T145), same as the run finishes.
        self.job_card.finish_moment(
            message.splitlines()[0] if message else "Done.",
            reduced_motion(),
        )
        self._refresh_go()
        self.refresh_train_panel()
        self._refresh_checklist()
        # The confirmation goes last (T50), same as the run finishes.
        self._say(message.splitlines()[0] if message else "Done.")

    # -- sleep ------------------------------------------------------
    def start_sleep(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to sleep.")
            return
        # One job at a time (T29): sleep refuses while training OR
        # any job-card job runs, same as training does.
        if self._job_already_running():
            return
        from .train import TRAINING_INSTALL_HINT, training_deps_missing

        missing = training_deps_missing()
        if missing:
            # The hint shows as a dialog now (T49): a log line is
            # only visible when the user scrolls to the Train log.
            # The log line stays too — the hint is worth keeping.
            hint = (
                "Training packages missing: " + ", ".join(missing) + ". "
                + TRAINING_INSTALL_HINT
            )
            self._train_log_line(hint)
            self._warn(hint)
            self._say("Training packages missing.")
            return
        if not self._weights_offer(profile):
            return
        self._sleep_worker = SleepWorker(
            self.store, profile, project,
            dream=self.sleep_dream_check.isChecked(),
        )
        self._sleep_worker.progress.connect(self._on_train_progress)
        self._sleep_worker.log.connect(self._train_log_line)
        self._sleep_worker.log.connect(self.job_card.set_status)
        self._sleep_worker.finished.connect(self._on_sleep_finished)
        self._run_started_at = None
        self.go_btn.setEnabled(False)
        self._set_activity("sleep", "Sleep: starting...")
        self.job_card.start(
            "Sleep", True,
            # The card morphs out of the Sleep tile (T149).
            from_rect=self._job_button_rect("sleep"),
            reduced_motion=reduced_motion(),
        )
        self._train_log_line("Starting sleep cycle...")
        self.debug_log.action(f"sleep started: {profile}/{project}")
        # The Train panel pins to this project until the run ends
        # (T47): the session may move on, the panel does not.
        self._running_job_key = (profile, project)
        self._sleep_worker.start()
        self._refresh_checklist()

    def _on_sleep_finished(self, ok: bool, message: str):
        self._running_job_key = None  # unpins the Train panel (T47)
        self._set_activity("idle", "Idle")
        self._train_log_line(message)
        self.debug_log.action(f"sleep finished: ok={ok}: {message}")
        # The finish moment (T145): the card glows with the summary
        # for a beat, then hides.
        self.job_card.finish_moment(
            message.splitlines()[0] if message else "Sleep done.",
            reduced_motion(),
        )
        # The finished cycle's curve and summary stay visible (T20),
        # like a finished training run.
        self.stat_time_left.setText("Time left: done")
        self.refresh_tree()
        self.refresh_session()
        # The confirmation goes last (T50): refresh_session reports
        # the session in the status bar, and a _say before it would
        # be overwritten before the user ever sees it.
        self._say(message.splitlines()[0] if message else "Sleep done.")

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
        if self._job_already_running():
            return
        # T148: before export, show what the tune changed — the
        # probe's before/after replies, in the same dialog the
        # probe itself opens (T94). Export goes ahead; Go back
        # cancels before any folder is picked or any work starts.
        # With no probe results there is nothing to preview, and
        # the export proceeds as before.
        # Modal audit: this dialog opens only when probe results
        # exist for the project. No existing test has any (the
        # export tests refuse the start or have no results file),
        # so no existing test reaches it; the new tests stub it.
        # T153: the export estimate, best effort — what the export
        # will cost, shown in the preview dialog (when there is
        # one) and in the log line that starts the job. A metadata
        # read that fails just leaves it out; the export itself
        # still runs.
        # T161: the quant and the checkpoint come from the pickers
        # beside the button — the CLI's --quant / --from-checkpoint.
        quant = self.gguf_quant_combo.currentText().strip() or DEFAULT_QUANT
        from_checkpoint = self.gguf_checkpoint_combo.currentData()
        estimate_text = None
        try:
            from .gguf import estimate_export, format_export_estimate

            estimate_text = format_export_estimate(
                estimate_export(
                    self.store, profile, project, quant=quant
                )
            )
        except StellaError:
            estimate_text = None
        probe_result = self._load_probe_results(profile, project)
        if probe_result is not None:
            dialog = ProbeResultsDialog(
                self, probe_result, export_mode=True,
                estimate_text=estimate_text,
            )
            if dialog.exec() != QDialog.Accepted:
                self._say("Export cancelled.")
                return
        dest = QFileDialog.getExistingDirectory(
            self, "Export GGUF to folder", str(Path.home())
        )
        if not dest:
            return
        from .gguf import export_gguf

        def job(ctx):
            # T107: the three phases move a determinate bar
            # (merge 1 of 3, convert 2 of 3, quantize 3 of 3), so
            # the export is not a mystery wait.
            phases = {"merge": 1, "convert": 2, "quantize": 3}

            def on_event(event):
                # T152: the merge's base load is said before it
                # starts, with the model name.
                if event.get("type") == "loading":
                    ctx.log(event.get("message", "Loading the base model."))
                elif event.get("type") == "phase":
                    ctx.progress(phases.get(event["phase"], 0), 3)
                    ctx.log(event["message"])

            result = export_gguf(
                self.store, profile, project, dest,
                quant=quant,
                from_checkpoint=from_checkpoint,
                on_warning=ctx.log,  # T31: converter warning, before the merge
                on_event=on_event,
                should_stop=ctx.is_cancelled,
            )
            return (
                f"GGUF ready: {result['gguf']} "
                f"({result['gguf_bytes']:,} bytes).\n"
                f"Run: {result['ollama_create']}"
            )

        self._start_job_worker(job, "Exporting GGUF", True)
        if estimate_text:
            self._train_log_line(
                f"Exporting GGUF (merge, convert, quantize). "
                f"{estimate_text}"
            )
        else:
            self._train_log_line(
                "Exporting GGUF (merge, convert, quantize)..."
            )

    # -- T89: create the exported model in Ollama -------------------
    def _last_gguf_export(self, profile, project):
        """The last GGUF export record for a project (the export
        writes gguf-export.json into the project dir), or None."""
        import json as json_mod

        record = (
            self.store.project_dir(profile, project) / "gguf-export.json"
        )
        if not record.is_file():
            return None
        try:
            data = json_mod.loads(record.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or "modelfile" not in data:
            return None
        return data

    def create_in_ollama_gui(self):
        """Run `ollama create` for the last GGUF export (T89): the
        model the user just exported becomes usable in Ollama
        without a copy-paste. Runs on the job card, so a slow
        create can be cancelled."""
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project first.")
            return
        if self._job_already_running():
            return
        record = self._last_gguf_export(profile, project)
        if record is None:
            self._warn(
                "No GGUF export yet for this project. Export GGUF "
                "first, then create it in Ollama."
            )
            return
        name = record.get("ollama_name") or f"{profile}-{project}"
        modelfile = record["modelfile"]
        from .gguf import create_in_ollama

        def job(ctx):
            output = create_in_ollama(
                name, modelfile, should_stop=ctx.is_cancelled,
            )
            if output:
                ctx.log(output)
            return f"Created in Ollama as {name}."

        self._start_job_worker(job, "Creating in Ollama", False)
        self._train_log_line(f"Creating {name} in Ollama...")

    def run_probe_gui(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project to probe.")
            return
        if self._job_already_running():
            return
        # T90: the probe is a gate only for governing seats (a
        # fine-tune bound for one must pass the refusal probe).
        # Every other profile probes informationally: counts and
        # change, no verdict. The mode is recorded in the saved
        # result, so the dialog reads it back.
        from .probe import is_governing_profile, probe_gate, probe_project

        try:
            prof = self.store.get_profile(profile)
        except StellaError as exc:
            self._warn(str(exc))
            return
        informational = not is_governing_profile(prof)

        def job(ctx):
            def on_event(event):
                # T152: each base load is said before it starts,
                # with the model name — the probe loads twice.
                if event.get("type") == "loading":
                    ctx.log(event.get("message", "Loading the base model."))
                elif event.get("type") == "prompt":
                    ctx.progress(event["done"], event["total"])
                    phase = (
                        "the base model"
                        if event["phase"] == "before"
                        else "the tuned model"
                    )
                    ctx.log(
                        f"Probing {phase}: prompt {event['done']} "
                        f"of {event['total']}."
                    )

            result = probe_project(
                self.store, profile, project,
                informational=informational,
                on_event=on_event, should_stop=ctx.is_cancelled,
            )
            before = result["before"]
            after = result["after"]
            summary = (
                f"Refusal probe: {before['refusals']}/{before['total']} "
                f"refusals before, {after['refusals']}/{after['total']} "
                f"after."
            )
            # T30: a silent prompt is named, not hidden inside a clean 0.
            silent = before.get("empty", 0) + after.get("empty", 0)
            if silent:
                summary += (
                    f" {silent} prompt"
                    f"{'s' if silent != 1 else ''} got no answer."
                )
            if informational:
                return (
                    f"{summary}\nChange: {result['delta']:+.0%}. "
                    "Informational only: no gate verdict."
                )
            _passed, verdict = probe_gate(result)
            return f"{summary}\n{verdict}"

        self._probe_job_key = (profile, project)
        self._probe_informational = informational
        # T94: when the probe finishes, the evidence opens — the
        # dialog reads the saved results for this project. The
        # slot is connected before the worker starts (see
        # _start_job_worker): a fast job must not beat it.
        started = self._start_job_worker(
            job, "Refusal probe", True,
            on_finished=self._on_probe_finished,
        )
        if not started:
            self._probe_job_key = None
        self._train_log_line("Running refusal probe (before vs after)...")

    def _on_probe_finished(self, ok: bool, _message: str):
        """A finished probe opens its evidence (T94): the results
        dialog for the project that was probed. Only on a finished
        run — a failed probe has no fresh results to show, and
        showing stale ones as if they were fresh would lie. The
        dialog reads the mode from the saved result, so an
        informational run never shows a gate verdict.

        Modal audit: this dialog opens only after a probe job
        finishes. No existing test runs a probe job to completion
        (the probe tests refuse the start), so no existing test
        reaches it; the new probe tests stub the dialog."""
        key = self._probe_job_key
        self._probe_job_key = None
        if not ok or key is None:
            return
        result = self._load_probe_results(*key)
        if result is None:
            return
        dialog = ProbeResultsDialog(self, result)
        dialog.exec()

    def _load_probe_results(
        self, profile: str, project: str
    ) -> dict | None:
        """The saved probe_results.json for a project, or None
        when there is none (or it cannot be read). A missing or
        corrupt file is not an error here — the caller decides
        what to say."""
        path = (
            self.store.project_dir(profile, project) / "probe_results.json"
        )
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _view_probe_results(self):
        """Re-open the saved probe results (T94): the evidence
        stays one click away after the run, not just when it
        finishes."""
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            self._warn("Pick a project first.")
            return
        result = self._load_probe_results(profile, project)
        if result is None:
            self._warn(
                "No probe results yet. Run the refusal probe first."
            )
            return
        dialog = ProbeResultsDialog(self, result)
        dialog.exec()

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
        if self._job_running():
            # Close waits for every worker, without freezing (T36):
            # the old code blocked the UI thread on wait(15000) —
            # a 15-second dead window with no feedback, and a worker
            # that ignored the stop was destroyed anyway (Qt prints
            # "QThread: Destroyed while thread is still running",
            # which can abort the app). Instead: ask the workers to
            # stop, say so in plain words, and close when the last
            # thread has actually ended. The window stays responsive
            # the whole time, and no running thread is ever
            # destroyed. A second close click while stopping just
            # repeats the message.
            name = self._running_job_name() or "A job"
            if self._training_running():
                self._train_worker.request_stop()
            if self._sleep_running():
                self._sleep_worker.request_stop()
            if self._job_worker is not None and self._job_worker.isRunning():
                # The cancel kills a running subprocess; only the
                # in-process merge phase of an export runs to its
                # next check point.
                self._job_worker.request_cancel()
            self._say(f"Stopping {name.lower()}...")
            self.job_card.set_status(f"Stopping {name.lower()}...")
            self._train_log_line(f"Stopping {name.lower()}...")
            if not self._closing:
                self._closing = True
                self._close_timer = QTimer(self)
                self._close_timer.setInterval(250)
                self._close_timer.timeout.connect(self._finish_closing)
                self._close_timer.start()
            event.ignore()
            return
        if self._close_timer is not None:
            self._close_timer.stop()
            self._close_timer = None
        self._closing = False
        if self._chat_window is not None:
            self._chat_window.stop_worker()
        if self.download_manager.is_running():
            self.download_manager.cancel()
            self.download_manager.wait_for_finished(5000)
        # A model-list refresh still running when the window closes
        # must finish first (T43): a QThread destroyed while running
        # aborts the app. The fetch times out in 2 s, so the wait
        # is short.
        if (
            self._model_list_worker is not None
            and self._model_list_worker.isRunning()
        ):
            self._model_list_worker.wait(5000)
        super().closeEvent(event)

    def _finish_closing(self):
        """The close timer's tick (T36): when the last worker has
        ended, close for real. Until then the window stays open
        with the "Stopping..." feedback showing."""
        if not self._closing:
            return
        if self._job_running():
            return
        self._close_timer.stop()
        self._close_timer = None
        self._closing = False
        self.close()


def main(argv: list[str] | None = None) -> int:
    # Silence the library warnings (T110) before anything heavy
    # loads, so a probe or merge loading an adapter does not print
    # peft's notice about the metamorph_mode key (T143) into the
    # window's stderr.
    from .cli import _silence_library_warnings

    _silence_library_warnings()
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("Stella")
    app.setOrganizationName("BrokeNBored")

    # STELLA's own look (T81): one stylesheet, drawn from the icon,
    # applied to the whole application — every window carries it.
    # Plus the button press dip (150 ms to 0.97, entry 001). The
    # filter object must stay alive: it is a local, and main() runs
    # app.exec(), so it lives as long as the app does.
    apply_stella_style(app)
    _press_dips = install_press_dips(app)

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
