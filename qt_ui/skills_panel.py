# qt_ui/skills_panel.py

# IMPORTS
from __future__ import annotations
import logging, os, textwrap
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
from tabulate import tabulate
from file_manager import FileManager

# SkillsPanel class
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

        self.display = QTextBrowser()
        self.display.setFont(QFont("Consolas", 11))
        root.addWidget(self.display, stretch=1)
        self._set_state("No save loaded")

    def set_base_path(self, save_folder: str) -> None:
        """Sets the directory path for the save folder.

        Args:
            save_folder (str): The name of the folder that the save should be stored in.
        """
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
        return self.display.toMarkdown()

    def load_data(self) -> list[dict]:
        """Loads the Skills dictionary / skills.json file.

        Returns:
            list[dict]: The skills.json file.
        """
        if not self.data_path or not os.path.exists(self.data_path):
            return []
        try:
            data = FileManager.load_json_data(self.data_path)
            return data if isinstance(data, list) else []
        except Exception as e:
            logging.error(f"SkillsPanel: load failed: {e}")
            return []

    def save_data(self, data: list[dict]) -> None:
        """Saves a specified dictionary to the disk.

        Args:
            data (list[dict]): The dictionary that is stored to the Player's Skills.json document.
        """
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
        """Saves the current data to the disk.
        
        """
        self.save_data(self.load_data())

    def refresh_display(self) -> None:
        """Refreshes the display of the Skills Panel, e.g. what text is actually displayed to the player (not the actual stored data).
        
        """
        if not self.data_path:
            self.display.setMarkdown("(No save loaded)")
            return

        data = self.load_data()
        if not data:
            self.display.setMarkdown("### SKILLS\n\n*(None)*")
            self._set_state("")
            return

        headers = ["Skill Name", "Skill Description", "Level (Bonus)", "XP", "Next Level"]
        rows = []
        for skill in data:
            try:
                name = skill.get("Name", "UNKNOWN")
                level = int(skill.get("Level", 0) or 0)
                level_string = "+5 (MAX LEVEL)" if level == 5 else f"+{level}" if level >= 0 else str(level)
                description = "\n".join(textwrap.wrap(skill.get("Description", ""), width=35))
                xp = skill.get("XP", 0)
                threshold = skill.get("Threshold", 0)
                
            except Exception:
                level = 0
                level_string = "+0"
                description = "UNKNOWN DESCRIPTION"
                xp = 0
                threshold = 3

            rows.append(
                [
                    name,
                    description,
                    level_string,
                    xp,
                    threshold,
                ]
            )

        # Generate the rounded grid
        grid = tabulate(rows, headers, tablefmt="rounded_grid")
        
        # Combine the Markdown header and the code-block wrapped grid
        panel_display = f"### SKILLS\n\n```text\n{grid}\n```\n"
        
        self.display.setMarkdown(panel_display)
        self._set_state("")

    def _set_state(self, text: str) -> None:
        """Sets the state of the Skills Panel.

        Args:
            text (str): The state to set the Skills Panel as.
        """
        self.lbl_state.setText(text or "")

    # ---- AIManager helpers ----

    def force_learn_skill(self, skill_name: str, skill_description: str, level: int):
        """Forcibly adds a new skill to the Player's Skills.json document.

        Args:
            skill_name (str): The name of the Skill to learn.
            skill_description (str): The description of the Skill to learn.
            level (int): The level of the Skill to learn.
        """
        clean_name = (skill_name or "").split("(")[0].strip().title()
        clean_decription = (skill_description or "").split("(")[0].strip().title()
        data = self.load_data()

        found = False
        for item in data:
            if str(item.get("Name", "")).lower() == clean_name.lower():
                item["Level"] = int(level)
                if clean_decription: item["Description"] = clean_decription
                item["XP"] = 0
                item["Threshold"] = 5 + (int(level) * 2)
                found = True
                break

        if not found:
            data.append(
                {
                    "Name": clean_name,
                    "Description": clean_decription,
                    "Level": int(level),
                    "XP": 0,
                    "Threshold": 5 + (int(level) * 2),
                }
            )

        self.save_data(data)