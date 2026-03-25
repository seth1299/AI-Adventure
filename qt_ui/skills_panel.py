# qt_ui/skills_panel.py
from __future__ import annotations

import logging
import os
import textwrap

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
)

from tabulate import tabulate

from file_manager import FileManager


class SkillsPanel(QWidget):
    """Qt Skills panel that reads/writes skills.json and renders a simple table."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data_path: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.lbl_title = QLabel("Skills")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.lbl_title, stretch=1)

        self.lbl_state = QLabel("")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.lbl_state)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setFixedWidth(90)
        self.btn_reload.clicked.connect(self.refresh_display)
        bar.addWidget(self.btn_reload)

        self.btn_save = QPushButton("Save")
        self.btn_save.setFixedWidth(90)
        self.btn_save.clicked.connect(self._save_current)
        bar.addWidget(self.btn_save)

        root.addLayout(bar)

        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setFont(QFont("Consolas", 11))
        self.display.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self.display, stretch=1)

        self._set_state("No save loaded")

    def set_base_path(self, save_folder: str) -> None:
        if not save_folder:
            return
        try:
            os.makedirs(save_folder, exist_ok=True)
        except Exception:
            logging.exception("Failed to ensure save folder exists")

        self.data_path = os.path.join(save_folder, "skills.json")
        if not os.path.exists(self.data_path):
            FileManager.save_json_data(self.data_path, [])
        self.refresh_display()

    def get_text(self) -> str:
        return self.display.toPlainText()

    def load_data(self) -> list[dict]:
        if not self.data_path or not os.path.exists(self.data_path):
            return []
        try:
            data = FileManager.load_json_data(self.data_path)
            return data if isinstance(data, list) else []
        except Exception as e:
            logging.error(f"SkillsPanel: load failed: {e}")
            return []

    def save_data(self, data: list[dict]) -> None:
        if not self.data_path:
            return
        try:
            data.sort(key=lambda x: str(x.get("Name", "")).lower())
            FileManager.save_json_data(self.data_path, data)
            self._set_state("Saved")
        except Exception:
            logging.exception("SkillsPanel: save failed")
        self.refresh_display()

    def _save_current(self) -> None:
        self.save_data(self.load_data())

    def refresh_display(self) -> None:
        if not self.data_path:
            self.display.setPlainText("(No save loaded)")
            return

        data = self.load_data()
        if not data:
            self.display.setPlainText("SKILLS\n\n(None)")
            self._set_state("")
            return

        headers = ["Skill Name", "Skill Description", "Level (Bonus)", "XP", "Next Level"]
        rows = []
        for s in data:
            try:
                lvl = int(s.get("Level", 0) or 0)
            except Exception:
                lvl = 0
            lvl_str = f"+{lvl}" if lvl >= 0 else str(lvl)
            raw_desc = str(s.get("Desc", ""))
            desc_wrapped = "\n".join(textwrap.wrap(raw_desc, width=35))
            rows.append(
                [
                    str(s.get("Name", "Unknown")),
                    desc_wrapped,
                    lvl_str,
                    str(s.get("XP", 0)),
                    str(s.get("Threshold", 0)),
                ]
            )

        txt = "SKILLS\n" + tabulate(rows, headers, tablefmt="rounded_grid") + "\n"
        self.display.setPlainText(txt)
        self._set_state("")

    def _set_state(self, text: str) -> None:
        self.lbl_state.setText(text or "")

    # ---- AIManager helpers ----

    def force_learn_skill(self, skill_name: str, skill_description: str, level: int):
        clean_name = (skill_name or "").split("(")[0].strip().title()
        data = self.load_data()

        found = False
        for item in data:
            if str(item.get("Name", "")).lower() == clean_name.lower():
                item["Level"] = int(level)
                if skill_description: item["Description"] = skill_description
                item["XP"] = 0
                item["Threshold"] = 5 + (int(level) * 2)
                found = True
                break

        if not found:
            data.append(
                {
                    "Name": clean_name,
                    "Description": skill_description,
                    "Level": int(level),
                    "XP": 0,
                    "Threshold": 5 + (int(level) * 2),
                }
            )

        self.save_data(data)
        return f"System: Set skill {clean_name} to Level {level}."