import customtkinter as ctk
import os
import json
from tabulate import tabulate
from tqdm import tqdm  # <--- NEW IMPORT
from config import TIME_ORDER

class ProcessingTab(ctk.CTkFrame):
    """Tracks tasks. Supports both Time-based (Auto) and Effort-based (Manual) tasks."""
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
            with open(self.data_path, "r") as f:
                return json.load(f)
        except:
            return []

    def save_data(self, data):
        if not self.data_path: return
        with open(self.data_path, "w") as f:
            json.dump(data, f, indent=4)
        self.refresh_display()

    def _time_to_index(self, time_str):
        t = time_str.lower().strip()
        for i, val in enumerate(TIME_ORDER):
            if val.lower() in t: return i
        return 0

    def _get_absolute_ticks(self, day, time_str):
        try:
            d = int(''.join(filter(str.isdigit, str(day))))
        except: d = 1
        return (d * len(TIME_ORDER)) + self._time_to_index(time_str)

    def add_process(self, name, desc, total_slots, current_day, current_time_str, mode="auto"):
        data = self.load_data()
        start_ticks = self._get_absolute_ticks(current_day, current_time_str)
        total_slots = int(total_slots)
        
        entry = {
            "name": name,
            "desc": desc,
            "mode": mode,
            "total_slots": total_slots,
            "progress_slots": 0,             # Slots completed so far
            "start_ticks": start_ticks,      # When it began
            "target_ticks": start_ticks + total_slots if mode == "auto" else 0, # Target (Auto only)
            "status": "In Progress"
        }
        
        data.append(entry)
        self.save_data(data)
        
        if mode == "auto":
            end_ticks = entry["target_ticks"]
            total_days = end_ticks // len(TIME_ORDER)
            finish_time = TIME_ORDER[end_ticks % len(TIME_ORDER)]
            return f"(Started Auto-Process: {name}. Finishes Day {total_days} at {finish_time})."
        else:
            return f"(Started Project: {name}. Requires {total_slots} slots of work)."

    def check_active_tasks(self, current_day, current_time_str):
        data = self.load_data()
        if not data: return []
        
        current_ticks = self._get_absolute_ticks(current_day, current_time_str)
        completed_names = []
        
        for item in data:
            if item["status"] == "In Progress":
                if item.get("mode", "auto") == "auto":
                    if current_ticks >= item["target_ticks"]:
                        item["status"] = "COMPLETED"
                        completed_names.append(item["name"])
        
        if completed_names:
            self.save_data(data)
            
        return completed_names

    def progress_manual_task(self, name, slots_worked):
        data = self.load_data()
        msg = f"System: Could not find project '{name}'."
        
        for item in data:
            if item["name"].lower() == name.lower() and item.get("mode") == "manual":
                if item["status"] != "In Progress":
                    return f"System: {name} is already done."

                worked = int(slots_worked)
                item["progress_slots"] += worked
                
                if item["progress_slots"] >= item["total_slots"]:
                    item["status"] = "COMPLETED"
                    self.save_data(data)
                    return f"(Work Complete! {name} is finished.)"
                else:
                    remaining = item["total_slots"] - item["progress_slots"]
                    self.save_data(data)
                    return f"(Worked on {name}. {remaining} slots remaining.)"
                    
        return msg

    def remove_process(self, name):
        data = self.load_data()
        for i, item in enumerate(data):
            if item["name"].lower() == name.lower():
                data.pop(i)
                self.save_data(data)
                return None
        return None

    def get_text(self):
        """Returns string for AI Context."""
        data = self.load_data()
        if not data: return "No active processes."
        txt = "ACTIVE PROCESSES:\n"
        for item in data:
            if item["status"] == "COMPLETED":
                state = "READY TO COLLECT"
            elif item.get("mode") == "manual":
                p = item["progress_slots"]
                t = item["total_slots"]
                state = f"Progress: {p}/{t} slots"
            else:
                target = item["target_ticks"]
                d = target // len(TIME_ORDER)
                t = TIME_ORDER[target % len(TIME_ORDER)]
                state = f"Finishes Day {d}, {t}"
                
            txt += f"- {item['name']}: {item['desc']} [{state}]\n"
        return txt

    def refresh_display(self):
        """Refreshes the UI table using TQDM for bars."""
        data = self.load_data()
        headers = ["Activity", "Type", "Progress", "Status"]
        table_data = []
        
        for item in data:
            mode = item.get("mode", "auto").upper()
            status = item["status"]
            
            if status == "COMPLETED":
                # Full green bar
                prog_display = tqdm.format_meter(
                    n=100, total=100, elapsed=0, ncols=12, 
                    bar_format='{bar}', ascii=False
                ).strip('|')
                status_str = "DONE"
                
            elif mode == "MANUAL":
                p = item["progress_slots"]
                t = item["total_slots"]
                
                # CALCULATE HOURS REMAINING
                # 1 Slot approx 3 Hours (24hrs / 8 slots)
                remaining_slots = t - p
                hours_left = remaining_slots * 3
                
                # Custom info string
                if hours_left >= 24:
                    # If more than a day, show days (e.g. "1.5 Days")
                    days = round(hours_left / 24, 1)
                    time_str = f"~{days} Days left"
                else:
                    time_str = f"~{hours_left} Hrs left"

                # We inject the time string into the bar format manually
                # ncols=12 keeps the bar compact
                bar_str = tqdm.format_meter(
                    n=p, total=t, elapsed=0, ncols=12, 
                    bar_format='{bar}', ascii=False
                )
                
                # Combine Bar + Time String
                prog_display = f"{bar_str.strip('|')} {time_str}"
                status_str = "In Progress"
            else:
                target = item["target_ticks"]
                d = target // len(TIME_ORDER)
                t = TIME_ORDER[target % len(TIME_ORDER)]
                prog_display = f"Due: Day {d}, {t}"
                status_str = "Waiting..."

            table_data.append([item["name"], mode, prog_display, status_str])
            
        full_text = "ONGOING TASKS\n" + tabulate(table_data, headers, tablefmt="simple_grid")
        
        self.display.configure(state="normal")
        self.display.delete("0.0", "end")
        self.display.insert("0.0", full_text)
        
        txt = self.display._textbox
        txt.tag_config("h1", font=("Consolas", 24, "bold"), foreground="#FFD700")
        pos = txt.search("ONGOING TASKS", "1.0", stopindex="end")
        if pos: txt.tag_add("h1", pos, f"{pos} lineend")
        
        self.display.configure(state="disabled")