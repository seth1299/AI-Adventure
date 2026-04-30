# qt_ui/processing_panel.py
from __future__ import annotations

import logging, os, time_utils

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
)

from tabulate import tabulate

from file_manager import FileManager

class ProcessingPanel(QWidget):
    """Qt Processing panel (processes + projects) backed by processing.json."""

    def __init__(self, parent: QWidget | None = None, app_context=None) -> None:
        super().__init__(parent)
        self.data_path: str = ""
        self.app = app_context
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        

        self.lbl_title = QLabel("Processing")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_title.hide()
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

        self._set_state("No save loaded")
        
    def _get_player(self):
        """Safely locate the Player object."""
        if not self.app: return None
        if hasattr(self.app, 'player'): return self.app.player
        if hasattr(self.app, 'app') and hasattr(self.app.app, 'player'): return self.app.app.player
        return None

    def set_base_path(self, save_folder: str) -> None:
        if not save_folder:
            return
        try:
            os.makedirs(save_folder, exist_ok=True)
        except Exception:
            logging.exception("Failed to ensure save folder exists")

        self.data_path = os.path.join(save_folder, "processing.json")
        if not os.path.exists(self.data_path):
            FileManager.save_json_data(self.data_path, [])
        self.refresh_display()

    def get_text(self) -> str:
        """Returns the Markdown formatted text of the inventory."""
        return self.display.toMarkdown()

    def load_data(self) -> list[dict]:
        if not self.data_path or not os.path.exists(self.data_path):
            return []
        try:
            data = FileManager.load_json_data(self.data_path)
            return data if isinstance(data, list) else []
        except Exception as e:
            logging.error(f"ProcessingPanel: load failed: {e}")
            return []

    def save_data(self, data: list[dict]) -> None:
        if not self.data_path:
            return
        try:
            FileManager.save_json_data(self.data_path, data)
            self._set_state("Saved")
        except Exception:
            logging.exception("ProcessingPanel: save failed")
        self.refresh_display()

    def _save_current(self) -> None:
        self.save_data(self.load_data())

    # ---- AI helpers (mirrors ProcessingTab API) ----

    def add_timed_process(self, name, description, duration_minutes, current_day, current_time_str, expected_yield):
        """Adds a process with a calculated target day and target time."""
        data = self.load_data()
        
        # Safely advance the time using our clean utility
        from time_utils import advance_time
        target_day, target_time_str = advance_time(current_day, current_time_str, duration_minutes)

        entry = {
            "name": name,
            "desc": description,
            "type": "process",
            "yield": expected_yield,
            "status": "In Progress",
            "ready_on_day": target_day,    # Track the day separately
            "ready_on_time": target_time_str # Track the string representation
        }
        data.append(entry)
        self.save_data(data)

    def check_active_tasks(self, current_day, current_time_str):
        """Checks if ongoing tasks have passed their target completion time."""
        data = self.load_data()
        if not data:
            logging.warning("No data to load for check_active_tasks in processing_panel.py.")
            return []
        logging.info(f"Successfully loaded processing panel data! Data: {data}")

        completed = []
        changed = False

        from time_utils import is_time_passed

        for item in data:
            if item.get("status") != "In Progress" or item.get("type") != "process":
                continue
            
            # Grab the targets from the dictionary we made in add_timed_process
            target_day = item.get("ready_on_day", 1)
            target_time_str = item.get("ready_on_time", "12:00 A.M.")
            has_time_passed = is_time_passed(current_day, current_time_str, target_day, target_time_str)
            logging.info(f"Target day: {target_day}; Target Time: {target_time_str}; has the time passed? {has_time_passed}")
            # Use our utility to see if the current time is greater than or equal to the target time
            if has_time_passed:
                item["status"] = "COMPLETED"
                expected_yield = item.get("yield", "Unknown")
                completed.append(f"{item.get('name', 'Unknown')} (Yield: {expected_yield})")
                changed = True

        if changed:
            self.save_data(data)
            self.refresh_display()

        return completed

    def add_project(self, name, desc, work_required, skill_name, skill_level_at_start, expected_yield):
        data = self.load_data()

        try:
            req = float(work_required)
        except Exception as e:
            logging.error(f"ProcessingPanel.add_project: bad work_required: {e}")
            req = 0.0
        req = max(0.0, req)

        try:
            lvl = int(skill_level_at_start)
        except Exception as e:
            logging.error(f"ProcessingPanel.add_project: bad level: {e}")
            lvl = 0
        lvl = max(0, lvl)

        entry = {
            "name": name,
            "desc": desc,
            "type": "project",
            "yield": expected_yield,
            "status": "In Progress",
            "skill": skill_name,
            "skill_level_at_start": lvl,
            "work_required": req, # Now tracks base minutes!
            "work_done": 0.0,
        }
        data.append(entry)
        self.save_data(data)

        # Base multiplier is 1.0. Each skill level adds 50% speed.
        speed_multiplier = 1.0 + (0.5 * lvl)
        est = "Unknown"
        if speed_multiplier > 0:
            est_minutes = req / speed_multiplier
            if est_minutes >= 60:
                est = f"~{est_minutes/60:.1f} hrs"
            else:
                est = f"~{int(est_minutes)} mins"

        return f"(Started Project: {name} (Skill: {skill_name}). Base Time: {req} mins. Yields: {expected_yield}. Est. Player Time: {est}.)"

    def apply_work_minutes(self, name, minutes_worked, skill_level):
        """Applies labor to a project, using skill level as a speed multiplier."""
        data = self.load_data()

        try:
            mins = float(minutes_worked)
        except Exception as e:
            logging.error(f"ProcessingPanel.apply_work_minutes: bad mins: {e}")
            mins = 0.0
        mins = max(0.0, mins)

        try:
            lvl = int(skill_level)
        except Exception as e:
            logging.error(f"ProcessingPanel.apply_work_minutes: bad lvl: {e}")
            lvl = 0
        lvl = max(0, lvl)

        # Level 0 = 1x speed. Level 2 = 2x speed.
        speed_multiplier = 1.0 + (0.5 * lvl)
        completed_amt = speed_multiplier * mins

        for item in data:
            if str(item.get("name", "")).lower() == str(name).lower() and item.get("type") == "project":
                if item.get("status") != "In Progress":
                    return f"System: {name} is already done."

                req = float(item.get("work_required", 0.0) or 0.0)
                done = float(item.get("work_done", 0.0) or 0.0)
                done += completed_amt
                item["work_done"] = done

                if req <= 0 or done >= req:
                    item["status"] = "COMPLETED"
                    self.save_data(data)
                    return f"(Work Complete! {name} is finished. Yield: {item.get('yield', 'Unknown')})"

                remaining_base_mins = max(0.0, req - done)
                self.save_data(data)
                
                # Format a nice string to let the AI know how close it is
                if remaining_base_mins >= 60:
                    rem_str = f"{remaining_base_mins/60:.1f} hrs"
                else:
                    rem_str = f"{int(remaining_base_mins)} mins"
                    
                return f"(Worked on {name} for {mins:g} mins. Remaining Base Labor: {rem_str}.)"

        return f"System: Could not find project '{name}'."

    def refresh_display(self) -> None:
        if not self.data_path:
            self.display.setMarkdown("(No save loaded)")
            return

        data = self.load_data()
        if not data:
            self.display.setMarkdown("### ONGOING TASKS\n\n(None)")
            self._set_state("")
            return
        
        player = self._get_player()
        cal_settings = player.calendar_settings if player else {}

        rows = []
        headers = ["Name", "Type", "Status", "Due/Progress", "Yield", "Description"]
        for item in data:
            t = item.get("type", "process")
            status = item.get("status", "Unknown")
            y = item.get("yield", "N/A")
            desc = item.get("desc", "")

            if t == "process":
                if status == "COMPLETED":
                    prog = "DONE (collect)"
                else:
                    target_day = item.get("ready_on_day", "Unknown")
                    target_time = item.get("ready_on_time", "Unknown")
                    if target_day != "Unknown":
                        rich_target_date = time_utils.calculate_calendar_date(int(target_day), cal_settings)
                        #logging.info(f"Rich target date: {rich_target_date}")
                        prog = f"Due: {rich_target_date} at {target_time}"
                        #logging.info(f"Prog: {prog}")
                    else:
                        prog = f"Due: Day {target_day} at {target_time}"
                        #logging.info("Target day is unknown.")
                rows.append([item.get("name", ""), "PROCESS", status, prog, y, desc])
            else:
                req = float(item.get("work_required", 0.0) or 0.0)
                done = float(item.get("work_done", 0.0) or 0.0)
                skill = item.get("skill", "")
                if status == "COMPLETED":
                    prog = "DONE (collect)"
                else:
                    remaining = max(0.0, req - done)
                    lvl = int(item.get("skill_level_at_start", 0) or 0)
                    
                    speed_multiplier = 1.0 + (0.5 * lvl)
                    mins_left = (remaining / speed_multiplier) if speed_multiplier > 0 else 0.0
                    
                    # Convert raw minutes into a readable hours/minutes string for the UI table
                    if mins_left >= 60:
                        time_str = f"~{mins_left/60:.1f} hrs left"
                    else:
                        time_str = f"~{int(mins_left)} mins left"
                        
                    prog = f"{done:.0f}/{req:.0f} Mins (Skill: {skill}) {time_str}"
                    
                rows.append([item.get("name", ""), "PROJECT", status, prog, y, desc])
                
        # 1. Generate the raw ASCII grid by itself
        grid = tabulate(rows, headers, tablefmt="rounded_grid")
        
        # 2. Wrap ONLY the grid in the <pre> tag (with padding to prevent top clipping!)
        safe_table_html = (
            f"<pre style=\"font-family: Consolas, 'Courier New', monospace; "
            f"line-height: 1.0; padding: 6px;\">\n\n{grid}\n</pre>\n"
        )
        
        # 3. Combine the Markdown header with the HTML table
        panel_display = f"### ONGOING TASKS\n\n\n\n\n{safe_table_html}"
        
        # 4. Use setMarkdown() to completely replace the display text
        self.display.setMarkdown(panel_display)
        self._set_state("")

    def remove_process(self, name):
        data = self.load_data()
        for i, item in enumerate(list(data)):
            if str(item.get("name", "")).lower() == str(name).lower():
                data.pop(i)
                self.save_data(data)
                return None
        return None

    def get_required_skill(self, name):
        data = self.load_data()
        for item in data:
            if str(item.get("name", "")).lower() == str(name).lower() and item.get("type") == "project":
                return item.get("skill")
        return None

    def _set_state(self, text: str) -> None:
        self.lbl_state.setText(text or "")