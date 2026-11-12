"""STELLA window — native Qt, one window, three panes.

Left: profiles (friendly role names, Ollama tag stays the identifier).
Middle: the selected profile's projects.
Right: detail — profile settings on top, project settings + notes below.

No web UI, no network beyond localhost Ollama. No "&" in any visible
label — Qt eats a bare & as a mnemonic marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import export as export_mod
from .model import METAMORPH_MODES, STELLA_VERSION, StellaError, Store
from .ollama import list_models

ROLE_SUGGESTIONS = [
    "driver",
    "reviewer",
    "vision",
    "fast",
    "all-rounder",
    "generalist",
    "utility",
    "tester",
]


class NewProfileDialog(QWidget):
    """Small inline form used by the New Profile flow (kept a QWidget so
    tests can drive it without a modal loop)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New profile")
        layout = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("lfm3-tool (lowercase, dashes ok)")
        self.display_edit = QLineEdit()
        self.role_combo = QComboBox()
        self.role_combo.setEditable(True)
        self.role_combo.addItems([""] + ROLE_SUGGESTIONS)
        self.tag_combo = QComboBox()
        self.tag_combo.setEditable(True)
        models = list_models()
        if models:
            self.tag_combo.addItems(models)
        else:
            self.tag_combo.addItem("")
        self.tag_note = QLabel(
            "Ollama is not answering — type the tag by hand."
            if not models
            else "Installed on this PC — pick one, or type a tag."
        )
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("Same as the tag, unless the base lives elsewhere")
        layout.addRow("Name", self.name_edit)
        layout.addRow("Display name", self.display_edit)
        layout.addRow("Role", self.role_combo)
        layout.addRow("Ollama tag", self.tag_combo)
        layout.addRow("", self.tag_note)
        layout.addRow("Base ref", self.base_edit)
        buttons = QHBoxLayout()
        self.create_btn = QPushButton("Create profile")
        self.cancel_btn = QPushButton("Cancel")
        buttons.addWidget(self.create_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addRow("", buttons)


class MainWindow(QMainWindow):
    def __init__(self, store: Store | None = None):
        super().__init__()
        self.store = store or Store()
        self.setWindowTitle(f"STELLA {STELLA_VERSION} — fine-tune models on your PC")
        self.resize(1100, 680)
        self.setMinimumSize(900, 540)
        self._current_profile: str | None = None
        self._current_project: str | None = None
        self._building = False
        self._build_ui()
        self.refresh_profiles()

    # -- layout -----------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        header = QLabel("STELLA  —  shape a base model into its proper job")
        header.setStyleSheet("font-size: 16px; font-weight: bold; padding: 6px 2px;")
        outer.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, 1)

        # Left pane: profiles.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Profiles"))
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.profile_list, 1)
        prof_btns = QHBoxLayout()
        self.new_profile_btn = QPushButton("New profile")
        self.new_profile_btn.clicked.connect(self.new_profile)
        self.rename_profile_btn = QPushButton("Rename")
        self.rename_profile_btn.clicked.connect(self.rename_profile)
        self.delete_profile_btn = QPushButton("Delete")
        self.delete_profile_btn.clicked.connect(self.delete_profile)
        prof_btns.addWidget(self.new_profile_btn)
        prof_btns.addWidget(self.rename_profile_btn)
        prof_btns.addWidget(self.delete_profile_btn)
        left_layout.addLayout(prof_btns)
        splitter.addWidget(left)

        # Middle pane: projects.
        mid = QWidget()
        mid_layout = QVBoxLayout(mid)
        mid_layout.addWidget(QLabel("Projects"))
        self.project_list = QListWidget()
        self.project_list.currentItemChanged.connect(self._on_project_selected)
        mid_layout.addWidget(self.project_list, 1)
        proj_btns = QHBoxLayout()
        self.new_project_btn = QPushButton("New project")
        self.new_project_btn.clicked.connect(self.new_project)
        self.rename_project_btn = QPushButton("Rename")
        self.rename_project_btn.clicked.connect(self.rename_project)
        self.delete_project_btn = QPushButton("Delete")
        self.delete_project_btn.clicked.connect(self.delete_project)
        proj_btns.addWidget(self.new_project_btn)
        proj_btns.addWidget(self.rename_project_btn)
        proj_btns.addWidget(self.delete_project_btn)
        mid_layout.addLayout(proj_btns)
        splitter.addWidget(mid)

        # Right pane: detail (scrollable).
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        detail = QWidget()
        self.detail_layout = QVBoxLayout(detail)
        self.detail_scroll.setWidget(detail)
        self._build_detail()
        splitter.addWidget(self.detail_scroll)
        splitter.setSizes([260, 200, 640])

        # Bottom bar: export / import.
        bottom = QHBoxLayout()
        self.export_btn = QPushButton("Export project")
        self.export_btn.clicked.connect(self.export_project)
        self.import_btn = QPushButton("Import package")
        self.import_btn.clicked.connect(self.import_package)
        bottom.addWidget(self.export_btn)
        bottom.addWidget(self.import_btn)
        bottom.addStretch(1)
        outer.addLayout(bottom)
        self.statusBar().showMessage("Stella ready.")

    def _build_detail(self):
        self.detail_layout.addWidget(QLabel("Profile"))
        prof_form = QFormLayout()
        self.prof_display = QLineEdit()
        self.prof_role = QLineEdit()
        self.prof_role.setPlaceholderText("driver, reviewer, vision...")
        self.prof_tag = QComboBox()
        self.prof_tag.setEditable(True)
        self.prof_base = QLineEdit()
        self.prof_processor = QLineEdit()
        prof_form.addRow("Display name", self.prof_display)
        prof_form.addRow("Role", self.prof_role)
        prof_form.addRow("Ollama tag", self.prof_tag)
        prof_form.addRow("Base ref", self.prof_base)
        prof_form.addRow("Processor", self.prof_processor)
        self.detail_layout.addLayout(prof_form)
        self.save_profile_btn = QPushButton("Save profile")
        self.save_profile_btn.clicked.connect(self.save_profile)
        self.detail_layout.addWidget(self.save_profile_btn)

        self.detail_layout.addWidget(QLabel("Project"))
        proj_form = QFormLayout()
        self.proj_display = QLineEdit()
        self.proj_dataset = QLineEdit()
        self.proj_dataset.setPlaceholderText("path or name of the training data")
        self.proj_method = QComboBox()
        self.proj_method.addItems(["lora", "full"])
        self.proj_rank = QSpinBox()
        self.proj_rank.setRange(1, 64)
        self.proj_lr = QLineEdit()
        self.proj_epochs = QSpinBox()
        self.proj_epochs.setRange(1, 100)
        self.proj_batch = QSpinBox()
        self.proj_batch.setRange(1, 32)
        self.proj_seq = QSpinBox()
        self.proj_seq.setRange(128, 32768)
        self.proj_metamorph = QComboBox()
        self.proj_metamorph.addItems(list(METAMORPH_MODES))
        self.proj_metamorph.setToolTip(
            "MetaMorphAi: morph turns the base into variants, "
            "compress shrinks how the fine-tune is stored, both does both."
        )
        proj_form.addRow("Display name", self.proj_display)
        proj_form.addRow("Dataset", self.proj_dataset)
        proj_form.addRow("Method", self.proj_method)
        proj_form.addRow("LoRA rank", self.proj_rank)
        proj_form.addRow("Learning rate", self.proj_lr)
        proj_form.addRow("Epochs", self.proj_epochs)
        proj_form.addRow("Batch size", self.proj_batch)
        proj_form.addRow("Max seq len", self.proj_seq)
        proj_form.addRow("MetaMorphAi", self.proj_metamorph)
        self.detail_layout.addLayout(proj_form)
        self.save_project_btn = QPushButton("Save project")
        self.save_project_btn.clicked.connect(self.save_project)
        self.detail_layout.addWidget(self.save_project_btn)
        self.detail_layout.addWidget(QLabel("Notes"))
        self.proj_notes = QPlainTextEdit()
        self.proj_notes.setMinimumHeight(120)
        self.detail_layout.addWidget(self.proj_notes)
        self.detail_layout.addStretch(1)

    # -- helpers ----------------------------------------------------
    def _say(self, text: str):
        # Single status surface: the window status bar. (An earlier
        # duplicate QLabel in the bottom bar showed the same text
        # twice — removed, see test_status_bar_is_the_only_status.)
        self.statusBar().showMessage(text)

    def _warn(self, text: str):
        QMessageBox.warning(self, "Stella", text)

    def _selected_profile(self) -> str | None:
        item = self.profile_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _selected_project(self) -> str | None:
        item = self.project_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    # -- refresh ----------------------------------------------------
    def refresh_profiles(self):
        self._building = True
        keep = self._current_profile
        self.profile_list.clear()
        for p in self.store.list_profiles():
            role = p.get("role") or ""
            tag = p.get("ollama_tag") or p.get("base_ref") or ""
            label = p.get("display_name") or p["name"]
            if role:
                label += f"  [{role}]"
            if tag:
                label += f"  — {tag}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, p["name"])
            self.profile_list.addItem(item)
        self._building = False
        if keep:
            for i in range(self.profile_list.count()):
                if self.profile_list.item(i).data(Qt.UserRole) == keep:
                    self.profile_list.setCurrentRow(i)
                    return
        if self.profile_list.count():
            self.profile_list.setCurrentRow(0)
        else:
            self._current_profile = None
            self.refresh_projects()

    def refresh_projects(self):
        self._building = True
        keep = self._current_project
        self.project_list.clear()
        profile = self._current_profile
        if profile:
            for p in self.store.list_projects(profile):
                label = p.get("display_name") or p["name"]
                mode = (p.get("metamorph") or {}).get("mode", "morph")
                label += f"  — {mode}"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, p["name"])
                self.project_list.addItem(item)
        self._building = False
        if keep:
            for i in range(self.project_list.count()):
                if self.project_list.item(i).data(Qt.UserRole) == keep:
                    self.project_list.setCurrentRow(i)
                    return
        if self.project_list.count():
            self.project_list.setCurrentRow(0)
        else:
            self._current_project = None
            self._show_project_detail()

    # -- selection --------------------------------------------------
    def _on_profile_selected(self, current, _previous):
        if self._building:
            return
        self._current_profile = current.data(Qt.UserRole) if current else None
        self._current_project = None
        self._show_profile_detail()
        self.refresh_projects()

    def _on_project_selected(self, current, _previous):
        if self._building:
            return
        self._current_project = current.data(Qt.UserRole) if current else None
        self._show_project_detail()

    def _show_profile_detail(self):
        self.prof_tag.clear()
        models = list_models()
        if models:
            self.prof_tag.addItems(models)
        if not self._current_profile:
            for w in (self.prof_display, self.prof_role, self.prof_base,
                      self.prof_processor):
                w.setText("")
            self.prof_tag.setCurrentText("")
            return
        try:
            p = self.store.get_profile(self._current_profile)
        except StellaError as exc:
            self._say(str(exc))
            return
        self.prof_display.setText(p.get("display_name", ""))
        self.prof_role.setText(p.get("role", ""))
        tag = p.get("ollama_tag", "")
        if tag and tag not in models:
            self.prof_tag.addItem(tag)
        self.prof_tag.setCurrentText(tag)
        self.prof_base.setText(p.get("base_ref", ""))
        self.prof_processor.setText(p.get("processor", ""))

    def _show_project_detail(self):
        if not self._current_profile or not self._current_project:
            for w in (self.proj_display, self.proj_dataset, self.proj_lr):
                w.setText("")
            self.proj_notes.setPlainText("")
            if self._current_profile:
                self._say(f"Profile: {self._current_profile} — no project yet.")
            else:
                self._say("Pick a profile to begin.")
            return
        try:
            p = self.store.get_project(self._current_profile, self._current_project)
            notes = self.store.read_notes(self._current_profile, self._current_project)
        except StellaError as exc:
            self._say(str(exc))
            return
        self.proj_display.setText(p.get("display_name", ""))
        self.proj_dataset.setText(p.get("dataset_ref", ""))
        settings = p.get("settings", {})
        method = settings.get("method", "lora")
        idx = self.proj_method.findText(method)
        self.proj_method.setCurrentIndex(idx if idx >= 0 else 0)
        self.proj_rank.setValue(int(settings.get("rank", 8)))
        self.proj_lr.setText(str(settings.get("learning_rate", 0.0002)))
        self.proj_epochs.setValue(int(settings.get("epochs", 3)))
        self.proj_batch.setValue(int(settings.get("batch_size", 1)))
        self.proj_seq.setValue(int(settings.get("max_seq_len", 1024)))
        mode = (p.get("metamorph") or {}).get("mode", "morph")
        idx = self.proj_metamorph.findText(mode)
        self.proj_metamorph.setCurrentIndex(idx if idx >= 0 else 0)
        self.proj_notes.setPlainText(notes)
        self._say(f"Profile: {self._current_profile} — project: {self._current_project}.")

    # -- save -------------------------------------------------------
    def save_profile(self):
        if not self._current_profile:
            return
        try:
            self.store.update_profile(
                self._current_profile,
                display_name=self.prof_display.text().strip(),
                role=self.prof_role.text().strip(),
                ollama_tag=self.prof_tag.currentText().strip(),
                base_ref=self.prof_base.text().strip(),
                processor=self.prof_processor.text().strip(),
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.refresh_profiles()
        self._say(f"Saved profile {self._current_profile}.")

    def save_project(self):
        if not self._current_profile or not self._current_project:
            return
        try:
            lr = float(self.proj_lr.text().strip() or "0.0002")
        except ValueError:
            self._warn("Learning rate must be a number, like 0.0002.")
            return
        try:
            self.store.update_project(
                self._current_profile,
                self._current_project,
                display_name=self.proj_display.text().strip(),
                dataset_ref=self.proj_dataset.text().strip(),
                settings={
                    "method": self.proj_method.currentText(),
                    "rank": self.proj_rank.value(),
                    "learning_rate": lr,
                    "epochs": self.proj_epochs.value(),
                    "batch_size": self.proj_batch.value(),
                    "max_seq_len": self.proj_seq.value(),
                },
                metamorph={"mode": self.proj_metamorph.currentText()},
            )
            self.store.write_notes(
                self._current_profile,
                self._current_project,
                self.proj_notes.toPlainText(),
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        self.refresh_projects()
        self._say(f"Saved project {self._current_project}.")

    # -- profile actions --------------------------------------------
    def new_profile(self):
        dialog = NewProfileDialog(self)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.create_btn.clicked.connect(lambda: self._create_profile_from(dialog))
        dialog.cancel_btn.clicked.connect(dialog.close)
        dialog.resize(420, 320)
        dialog.show()
        self._profile_dialog = dialog

    def _create_profile_from(self, dialog: NewProfileDialog):
        name = dialog.name_edit.text()
        try:
            self.store.create_profile(
                name,
                ollama_tag=dialog.tag_combo.currentText().strip(),
                role=dialog.role_combo.currentText().strip(),
                display_name=dialog.display_edit.text().strip(),
                base_ref=dialog.base_edit.text().strip(),
            )
        except StellaError as exc:
            self._warn(str(exc))
            return
        dialog.close()
        self._current_profile = name.strip().lower()
        self._say(f"Created profile {self._current_profile}.")
        self.refresh_profiles()

    def rename_profile(self):
        slug = self._selected_profile()
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
        self._current_profile = data["name"]
        self.refresh_profiles()

    def delete_profile(self):
        slug = self._selected_profile()
        if not slug:
            return
        answer = QMessageBox.question(
            self, "Delete profile",
            f"Delete profile {slug!r} and all its projects? This cannot be undone.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.store.delete_profile(slug)
        except StellaError as exc:
            self._warn(str(exc))
            return
        self._current_profile = None
        self._current_project = None
        self.refresh_profiles()

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
        self._say(f"Created project {self._current_project}.")
        self.refresh_projects()

    def rename_project(self):
        profile = self._selected_profile()
        project = self._selected_project()
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
        self._current_project = data["name"]
        self.refresh_projects()

    def delete_project(self):
        profile = self._selected_profile()
        project = self._selected_project()
        if not profile or not project:
            return
        answer = QMessageBox.question(
            self, "Delete project",
            f"Delete project {project!r}? This cannot be undone.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.store.delete_project(profile, project)
        except StellaError as exc:
            self._warn(str(exc))
            return
        self._current_project = None
        self.refresh_projects()

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
        self._current_profile = result["profile"]
        self._current_project = result["project"]
        self._say(f"Imported {result['project']} into {result['profile']}.")
        self.refresh_profiles()


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("Stella")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
