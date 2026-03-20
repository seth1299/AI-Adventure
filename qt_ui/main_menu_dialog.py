# qt_ui/main_menu_dialog.py
from __future__ import annotations

import os
import shutil
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QMessageBox,
    QInputDialog,
)

from config import SAVES_DIR


class MainMenuDialog(QDialog):
    """Simple startup menu for the Qt build."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI RPG Adventure - Main Menu")
        self.resize(520, 420)
        self._selected_save: str | None = None

        root = QVBoxLayout(self)

        title = QLabel("Adventures")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        root.addWidget(title)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _it: self._load_selected())
        root.addWidget(self.list, stretch=1)

        btn_row = QHBoxLayout()

        self.btn_load = QPushButton("Load")
        self.btn_new = QPushButton("New")
        self.btn_rename = QPushButton("Rename")
        self.btn_delete = QPushButton("Delete")
        self.btn_quit = QPushButton("Quit")

        self.btn_load.clicked.connect(self._load_selected)
        self.btn_new.clicked.connect(self._new_adventure)
        self.btn_rename.clicked.connect(self._rename_selected)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_quit.clicked.connect(self.reject)

        for b in (self.btn_load, self.btn_new, self.btn_rename, self.btn_delete, self.btn_quit):
            btn_row.addWidget(b)

        root.addLayout(btn_row)

        self.refresh_list()

    @property
    def selected_save(self) -> str | None:
        return self._selected_save

    def refresh_list(self) -> None:
        try:
            os.makedirs(SAVES_DIR, exist_ok=True)
        except Exception:
            logging.exception("Failed to ensure saves dir exists")
            return

        self.list.clear()

        try:
            saves = [
                d
                for d in os.listdir(SAVES_DIR)
                if os.path.isdir(os.path.join(SAVES_DIR, d))
            ]
            saves.sort(key=lambda s: s.lower())
        except Exception:
            logging.exception("Failed to list saves")
            saves = []

        if not saves:
            self.list.addItem("(No saved adventures yet)")
            self.list.setEnabled(False)
        else:
            self.list.setEnabled(True)
            for s in saves:
                self.list.addItem(s)

    def _current_selection(self) -> str | None:
        if not self.list.isEnabled():
            return None
        item = self.list.currentItem()
        return item.text() if item else None

    def _sanitize_name(self, raw: str) -> str:
        raw = (raw or "").strip()
        return "".join(c for c in raw if c.isalnum() or c in (" ", "_", "-")).strip()

    def _load_selected(self) -> None:
        name = self._current_selection()
        if not name:
            QMessageBox.information(self, "Load", "Select an adventure first.")
            return
        self._selected_save = name
        self.accept()

    def _new_adventure(self) -> None:
        text, ok = QInputDialog.getText(self, "New Adventure", "Name your adventure:")
        if not ok:
            return

        name = self._sanitize_name(text)
        if not name:
            return

        full = os.path.join(SAVES_DIR, name)
        if os.path.exists(full):
            QMessageBox.warning(self, "New Adventure", "That adventure already exists.")
            return

        try:
            os.makedirs(full, exist_ok=True)
        except Exception:
            logging.exception("Failed to create new save folder")
            QMessageBox.critical(self, "New Adventure", "Failed to create the save folder (see logs).")
            return

        self._selected_save = name
        self.accept()

    def _rename_selected(self) -> None:
        old = self._current_selection()
        if not old:
            QMessageBox.information(self, "Rename", "Select an adventure first.")
            return

        text, ok = QInputDialog.getText(self, "Rename Adventure", f"Rename '{old}' to:")
        if not ok:
            return

        new = self._sanitize_name(text)
        if not new or new == old:
            return

        old_path = os.path.join(SAVES_DIR, old)
        new_path = os.path.join(SAVES_DIR, new)
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Rename", "That name is already taken.")
            return

        try:
            os.rename(old_path, new_path)
            self.refresh_list()
        except Exception:
            logging.exception("Failed to rename adventure")
            QMessageBox.critical(self, "Rename", "Rename failed (see logs).")

    def _delete_selected(self) -> None:
        name = self._current_selection()
        if not name:
            QMessageBox.information(self, "Delete", "Select an adventure first.")
            return

        text, ok = QInputDialog.getText(
            self,
            "Delete Adventure",
            f"Type DELETE to confirm deleting '{name}':",
        )
        if not ok:
            return

        if (text or "").strip() != "DELETE":
            return

        full = os.path.join(SAVES_DIR, name)
        try:
            shutil.rmtree(full)
            self.refresh_list()
        except Exception:
            logging.exception("Failed to delete adventure")
            QMessageBox.critical(self, "Delete", "Delete failed (see logs).")