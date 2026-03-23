# qt_ui/processing_panel.py
from __future__ import annotations

import logging
import os

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
from time_utils import to_abs_minutes, from_abs_minutes


class ProcessingPanel(QWidget):
    """Qt Processing panel (processes + projects) backed by processing.json."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data_path: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.lbl_title = QLabel("Processing")
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

        self.data_path = os.path.join(save_folder, "processing.json")
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

    def add_timed_process(self, name, desc, duration_hours, current_day, current_time_str, expected_yield):
        data = self.load_data()

        start_abs = to_abs_minutes(current_day, current_time_str)
        dur_minutes = int(round(float(duration_hours) * 60))
        dur_minutes = max(0, dur_minutes)

        entry = {
            "name": name,
            "desc": desc,
            "type": "process",
            "yield": expected_yield,
            "status": "In Progress",
            "duration_hours": float(duration_hours),
            "start_abs_minutes": start_abs,
            "target_abs_minutes": start_abs + dur_minutes,
        }
        data.append(entry)
        self.save_data(data)

        finish = from_abs_minutes(entry["target_abs_minutes"])
        return f"(Started Process: {name}. Yields: {expected_yield}. Finishes {finish.as_day_string()} at {finish.as_time_string()})"

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
            "work_required": req,
            "work_done": 0.0,
        }
        data.append(entry)
        self.save_data(data)

        speed = 10 + (10 * lvl)
        est = "Unknown"
        if speed > 0:
            est_hours = (req / speed) if req else 0.0
            est = f"~{est_hours:.1f} hrs"

        return f"(Started Project: {name} (Skill: {skill_name}). Work Amount: {req}. Yields: {expected_yield}. Est: {est}.)"

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

    def check_active_tasks(self, current_day, current_time_str):
        data = self.load_data()
        if not data:
            return []

        current_abs = to_abs_minutes(current_day, current_time_str)
        completed = []
        changed = False

        for item in data:
            if item.get("status") != "In Progress":
                continue
            if item.get("type") != "process":
                continue

            tgt = int(item.get("target_abs_minutes", 0))
            if current_abs >= tgt:
                item["status"] = "COMPLETED"
                y = item.get("yield", "Unknown")
                completed.append(f"{item.get('name', 'Unknown')} (Yield: {y})")
                changed = True

        if changed:
            self.save_data(data)

        return completed

    def apply_work_hours(self, name, hours_worked, skill_level):
        data = self.load_data()

        try:
            hrs = float(hours_worked)
        except Exception as e:
            logging.error(f"ProcessingPanel.apply_work_hours: bad hrs: {e}")
            hrs = 0.0
        hrs = max(0.0, hrs)

        try:
            lvl = int(skill_level)
        except Exception as e:
            logging.error(f"ProcessingPanel.apply_work_hours: bad lvl: {e}")
            lvl = 0
        lvl = max(0, lvl)

        speed = 10 + (10 * lvl)
        completed_amt = speed * hrs

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

                remaining = max(0.0, req - done)
                self.save_data(data)
                return f"(Worked on {name} for {hrs:g} hrs. Remaining Work Amount: {remaining:.1f}.)"

        return f"System: Could not find project '{name}'."

    # ---- Display ----

    def refresh_display(self) -> None:
        if not self.data_path:
            self.display.setPlainText("(No save loaded)")
            return

        data = self.load_data()
        if not data:
            self.display.setPlainText("ONGOING TASKS\n\n(None)")
            self._set_state("")
            return

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
                    tgt = from_abs_minutes(int(item.get("target_abs_minutes", 0)))
                    prog = f"Due: Day {tgt.as_day_string()} at {tgt.as_time_string()}"
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
                    speed = 10 + (10 * lvl)
                    hrs_left = (remaining / speed) if speed > 0 else 0.0
                    prog = f"{done:.1f}/{req:.1f} WA (Skill: {skill}) ~{hrs_left:.1f} hrs left"
                rows.append([item.get("name", ""), "PROJECT", status, prog, y, desc])

        txt = "ONGOING TASKS\n" + tabulate(rows, headers, tablefmt="rounded_grid") + "\n"
        self.display.setPlainText(txt)
        self._set_state("")

    def _set_state(self, text: str) -> None:
        self.lbl_state.setText(text or "")