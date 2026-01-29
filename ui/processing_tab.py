import customtkinter as ctk
import os
import json
from tabulate import tabulate
from tqdm import tqdm

from time_utils import to_abs_minutes, from_abs_minutes


class ProcessingTab(ctk.CTkFrame):
    """
    Tracks two kinds of tasks:

    1) Timed Processes (passive)
       - type: "process"
       - duration_hours, start_abs_minutes, target_abs_minutes

    2) Projects (active work)
       - type: "project"
       - work_required (float), work_done (float)
       - skill (string), skill_level_at_start (int)

    Work speed per hour = 10 + (10 * relevant skill level)
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.data_path = ""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.display = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="none", state="disabled")
        self.display.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    def set_base_path(self, folder_path):
        self.data_path = os.path.join(folder_path, "processing.json")
        self.refresh_display()

    def load_data(self):
        if not self.data_path or not os.path.exists(self.data_path):
            return []
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def save_data(self, data):
        if not self.data_path:
            return
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        self.refresh_display()

    # ---------- Add ----------

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
        except Exception:
            req = 0.0
        req = max(0.0, req)

        try:
            lvl = int(skill_level_at_start)
        except Exception:
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

    # ---------- Query helpers ----------

    def get_required_skill(self, name):
        """Returns the required skill name for a project, or None."""
        data = self.load_data()
        for item in data:
            if str(item.get("name", "")).lower() == str(name).lower() and item.get("type") == "project":
                return item.get("skill")
        return None

    # ---------- Completion / Progress ----------

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
        except Exception:
            hrs = 0.0
        hrs = max(0.0, hrs)

        try:
            lvl = int(skill_level)
        except Exception:
            lvl = 0
        lvl = max(0, lvl)

        speed = 10 + (10 * lvl)
        completed = speed * hrs

        for item in data:
            if str(item.get("name", "")).lower() == str(name).lower() and item.get("type") == "project":
                if item.get("status") != "In Progress":
                    return f"System: {name} is already done."

                req = float(item.get("work_required", 0.0) or 0.0)
                done = float(item.get("work_done", 0.0) or 0.0)
                done += completed
                item["work_done"] = done

                if req <= 0 or done >= req:
                    item["status"] = "COMPLETED"
                    self.save_data(data)
                    return f"(Work Complete! {name} is finished. Yield: {item.get('yield', 'Unknown')})"

                remaining = max(0.0, req - done)
                self.save_data(data)
                return f"(Worked on {name} for {hrs:g} hrs. Remaining Work Amount: {remaining:.1f}.)"

        return f"System: Could not find project '{name}'."

    # ---------- Context / UI ----------

    def get_text(self):
        data = self.load_data()
        if not data:
            return "No active processes."

        txt = "ACTIVE TASKS:\n"
        for item in data:
            y = item.get("yield", "Unknown")
            status = item.get("status", "Unknown")

            if item.get("type") == "process":
                if status == "COMPLETED":
                    state = f"READY TO COLLECT (Yield: {y})"
                else:
                    tgt = from_abs_minutes(int(item.get("target_abs_minutes", 0)))
                    state = f"Finishes {tgt.as_day_string()}, {tgt.as_time_string()} (Yield: {y})"
                txt += f"- {item.get('name','Unknown')}: {item.get('desc','')} [{state}]\n"
            else:
                skill = item.get("skill", "Unknown Skill")
                req = float(item.get("work_required", 0.0) or 0.0)
                done = float(item.get("work_done", 0.0) or 0.0)
                if status == "COMPLETED":
                    state = f"READY TO COLLECT (Yield: {y})"
                else:
                    state = f"Progress: {done:.1f}/{req:.1f} WA (Skill: {skill}) (Yield: {y})"
                txt += f"- {item.get('name','Unknown')}: {item.get('desc','')} [{state}]\n"

        return txt

    def refresh_display(self):
        data = self.load_data()
        headers = ["Activity", "Type", "Progress", "Yield", "Status", "Description"]
        rows = []

        for item in data:
            t = item.get("type", "process")
            y = item.get("yield", "N/A")
            status = item.get("status", "Unknown")
            description = item.get("desc", "Unknown")

            if t == "process":
                if status == "COMPLETED":
                    bar = tqdm.format_meter(n=100, total=100, elapsed=0, ncols=12, bar_format='{bar}', ascii=False).strip('|')
                    prog = bar
                    stat = "DONE"
                else:
                    tgt = from_abs_minutes(int(item.get("target_abs_minutes", 0)))
                    prog = f"Due: {tgt.as_day_string()}, {tgt.as_time_string()}"
                    stat = "Waiting..."
                rows.append([item.get("name",""), "PROCESS", prog, y, stat, description])
            else:
                req = float(item.get("work_required", 0.0) or 0.0)
                done = float(item.get("work_done", 0.0) or 0.0)

                if status == "COMPLETED":
                    bar = tqdm.format_meter(n=100, total=100, elapsed=0, ncols=12, bar_format='{bar}', ascii=False).strip('|')
                    prog = bar
                    stat = "DONE"
                else:
                    bar_str = tqdm.format_meter(n=done, total=max(req, 1.0), elapsed=0, ncols=12, bar_format='{bar}', ascii=False).strip('|')
                    lvl = int(item.get("skill_level_at_start", 0) or 0)
                    speed = 10 + (10 * lvl)
                    remaining = max(0.0, req - done)
                    hrs_left = (remaining / speed) if speed > 0 else 0.0
                    prog = f"{bar_str} ~{hrs_left:.1f} hrs left"
                    stat = "In Progress"

                rows.append([item.get("name",""), "PROJECT", prog, y, stat, description])

        full_text = "ONGOING TASKS\n" + tabulate(rows, headers, tablefmt="simple_grid")

        self.display.configure(state="normal")
        self.display.delete("0.0", "end")
        self.display.insert("0.0", full_text)

        txt = self.display._textbox
        txt.tag_config("h1", font=("Consolas", 24, "bold"), foreground="#FFD700")
        pos = txt.search("ONGOING TASKS", "1.0", stopindex="end")
        if pos:
            txt.tag_add("h1", pos, f"{pos} lineend")

        self.display.configure(state="disabled")
