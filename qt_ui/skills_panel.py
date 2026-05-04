from __future__ import annotations
import logging, os, textwrap
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
from tabulate import tabulate
from file_manager import FileManager
from qt_ui.base_panel import BasePanel
from pathlib import Path

# SkillsPanel class
class SkillsPanel(BasePanel):
    """Qt Skills panel that reads/writes skills.json and renders a simple table."""

    def __init__(self, parent: QWidget | None = None, app_context=None) -> None:
        super().__init__(title="Skills", parent=parent, app_context=app_context, show_save_button=True)
        
        self.display = QTextBrowser()
        self.display.setFont(QFont("Consolas", 11))
        self.root_layout.addWidget(self.display, stretch=1)
        self._set_state("No save loaded")

    def set_base_path(self, save_folder: str | Path) -> None:
        """Sets the directory path for the save folder.

        Args:
            save_folder (str): The name of the folder that the save should be stored in.
        """
        if not save_folder:
            return
            
        save_directory = Path(save_folder)
        try:
            save_directory.mkdir(parents=True, exist_ok=True)
        except Exception as directory_creation_error:
            logging.exception(f"Failed to ensure save folder exists: {directory_creation_error}")

        self.data_path = save_directory / "skills.json"
        
        if not self.data_path.exists():
            FileManager.save_json_data(str(self.data_path), [])
            
        self.refresh_display()

    def get_text(self) -> str:
        return self.display.toMarkdown()
    
    def add_xp(self, skill_name: str, xp_amount: int):
        """Adds an amount of xp to a skill.

        Args:
            skill_name (str): The name of the Skill to add the xp to.
            xp_amount (int): The amount of xp to add to the Skill.
        """
        data = self.load_data()
        found = False
        try:
            if data:
                for skill in data:
                    if str(skill.get("Name", "")).lower() == skill_name.lower():
                        if skill["Level"] >= 5: return
                        
                        skill["XP"] += xp_amount
                        
                        if skill["Threshold"] <= skill["XP"]:
                            skill["Level"] += 1
                            skill["XP"] = 0
                            skill["Threshold"] += 2
                            
                        # FIX 1: Move this OUTSIDE the level-up if-statement!
                        found = True 
                        break    
                        
                if found: 
                    logging.info(f"Successfully added {xp_amount} xp to {skill_name} skill.")
                    # FIX 2: Actually save the modified data to the disk!
                    self.save_data(data)
                    
        except Exception as e:
            logging.exception(f"Error adding XP: {e}")
        finally:
            self.refresh_display()

    def load_data(self) -> list[dict]:
        """Loads the Skills dictionary / skills.json file.

        Returns:
            list[dict]: The skills.json file.
        """
        # Check existence safely via Path object
        if not self.data_path or not self.data_path.exists():
            return []
        try:
            # Cast Path to string for FileManager compatibility
            data = FileManager.load_json_data(str(self.data_path))
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
            # Cast Path to string for FileManager compatibility
            FileManager.save_json_data(str(self.data_path), data)
            self._set_state("Saved")
        except Exception as save_error:
            logging.exception(f"SkillsPanel: save failed: {save_error}")
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
                xp_string = str(xp) if level < 5 else "(MAX LEVEL)"
                threshold = skill.get("Threshold", 0) 
                threshold_string = str(threshold) if level < 5 else "(MAX LEVEL)"
                
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
                    xp_string,
                    threshold_string,
                ]
            )

        # Generate the rounded grid
        grid = tabulate(rows, headers, tablefmt="rounded_grid")
        
        safe_table_html = self._format_table_html(grid)
        panel_display = f"### SKILLS\n\n{safe_table_html}"
        
        self.display.setMarkdown(panel_display)
        self._set_state("")
        
    def _format_table_html(self, grid_text: str) -> str:
        """
        Wraps the tabulated skill text in an HTML <pre> block with protective styling.
        
        Ensures that the top border of the ASCII grid is not visually clipped by 
        the QTextBrowser's default rendering behavior.
        
        Args:
            grid_text (str): The raw text output generated by the tabulate library.
            
        Returns:
            str: A formatted HTML string.
        """
        try:
            formatted_html = (
                f"<pre style=\"font-family: Consolas, 'Courier New', monospace; "
                f"line-height: 1.0; padding: 6px;\">\n\n{grid_text}\n</pre>\n"
            )
            return formatted_html
            
        except Exception as error:
            logging.error(f"SkillsPanel: Failed to format table HTML. Returning raw grid. Details: {error}")
            return f"\n{grid_text}\n"

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