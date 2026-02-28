# qt_ui/markdown_panel.py
from __future__ import annotations

import os
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QMessageBox,
)

from file_manager import FileManager


class MarkdownPanel(QWidget):
    """Simple editable Markdown panel (World, Journal, Character, etc.).

    - Loads/saves from <save_folder>/<Name>.md
    - Auto-saves after a short idle delay
    """

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.filename: str = ""

        self._dirty = False
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ---- Toolbar ----
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.lbl_title = QLabel(f"{name}")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.lbl_title, stretch=1)

        self.lbl_state = QLabel("")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.lbl_state)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setFixedWidth(90)
        self.btn_reload.clicked.connect(self.reload_from_disk)
        bar.addWidget(self.btn_reload)

        self.btn_save = QPushButton("Save")
        self.btn_save.setFixedWidth(90)
        self.btn_save.clicked.connect(self.save_now)
        bar.addWidget(self.btn_save)

        root.addLayout(bar)

        # ---- Editor ----
        self.editor = QPlainTextEdit()
        self.editor.setTabStopDistance(4 * self.editor.fontMetrics().horizontalAdvance(" "))
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.textChanged.connect(self._on_text_changed)
        root.addWidget(self.editor, stretch=1)

        # ---- Autosave ----
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(800)
        self._autosave.timeout.connect(self._save_if_dirty)

        self._update_state_label()

    # ---- Public API used by AIManager ----

    def get_text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, text: str) -> None:
        self._loading = True
        try:
            self.editor.blockSignals(True)
            self.editor.setPlainText(text or "")
        finally:
            self.editor.blockSignals(False)
            self._loading = False

        # Treat programmatic updates as real changes (AI writes, etc.)
        self._mark_dirty()

    # ---- Save/Load wiring ----

    def set_base_path(self, save_folder: str) -> None:
        if not save_folder:
            return

        try:
            os.makedirs(save_folder, exist_ok=True)
        except Exception:
            logging.exception("Failed to ensure save folder exists")

        self.filename = os.path.join(save_folder, f"{self.name}.md")
        self.reload_from_disk(force=True)

    def reload_from_disk(self, force: bool = False) -> None:
        if not self.filename:
            return

        if self._dirty and not force:
            resp = QMessageBox.question(
                self,
                "Discard changes?",
                f"{self.name} has unsaved changes. Reloading will discard them. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return

        content = FileManager.read_text_file(self.filename)
        if not content.strip():
            content = f"{self.name}\n\n"

        self._loading = True
        try:
            self.editor.blockSignals(True)
            self.editor.setPlainText(content)
        finally:
            self.editor.blockSignals(False)
            self._loading = False

        self._dirty = False
        self._autosave.stop()
        self._update_state_label()

    def save_now(self) -> None:
        if not self.filename:
            return

        try:
            FileManager.write_text_file(self.filename, self.get_text())
            self._dirty = False
            self._autosave.stop()
            self._update_state_label(saved=True)
        except Exception:
            logging.exception("MarkdownPanel save failed")

    # ---- Internals ----

    def _on_text_changed(self) -> None:
        if self._loading:
            return
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._update_state_label()
        self._autosave.start()

    def _save_if_dirty(self) -> None:
        if self._dirty:
            self.save_now()

    def _update_state_label(self, saved: bool = False) -> None:
        if saved:
            self.lbl_state.setText("Saved")
            return

        if not self.filename:
            self.lbl_state.setText("No save loaded")
        elif self._dirty:
            self.lbl_state.setText("Unsaved…")
        else:
            self.lbl_state.setText("")