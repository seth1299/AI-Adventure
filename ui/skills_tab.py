import customtkinter as ctk
import os
import json
from tabulate import tabulate

class SkillsTab(ctk.CTkFrame):
    """Displays Skills.json using Tabulate. Handles XP Logic."""
    def __init__(self, parent):
        super().__init__(parent)
        self.data_path = ""
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.display = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="none", state="disabled")
        self.display.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    def set_base_path(self, folder_path):
        self.data_path = os.path.join(folder_path, "skills.json")
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
        data.sort(key=lambda x: x["Name"])
        if not self.data_path: return
        with open(self.data_path, "w") as f:
            json.dump(data, f, indent=4)
        self.refresh_display()

    def force_learn_skill(self, skill_name, level):
        clean_name = skill_name.split('(')[0].strip().title()
        data = self.load_data()
        
        found = False
        for item in data:
            if item["Name"] == clean_name:
                item["Level"] = level
                item["XP"] = 0
                item["Threshold"] = 5 + (level * 2)
                found = True
                break
        
        if not found:
            new_skill = {
                "Name": clean_name, 
                "Level": level, 
                "XP": 0, 
                "Threshold": 5 + (level * 2)
            }
            data.append(new_skill)
            
        self.save_data(data)
        return f"System: Set skill {clean_name} to Level {level}."

    def get_text(self):
        return self.display.get("0.0", "end")

    def refresh_display(self):
        data = self.load_data()
        headers = ["Skill Name", "Level (Bonus)", "XP", "Next Level"]
        table_data = []
        
        for s in data:
            lvl_str = f"+{s['Level']}"
            table_data.append([s["Name"], lvl_str, s["XP"], s["Threshold"]])
            
        # Clean Title (No #)
        full_text = "SKILLS\n" + tabulate(table_data, headers, tablefmt="simple_grid")
        
        self.display.configure(state="normal")
        self.display.delete("0.0", "end")
        self.display.insert("0.0", full_text)
        
        # Apply Styles
        self._apply_styles()
        
        self.display.configure(state="disabled")

    def _apply_styles(self):
        """Applies styling to the main Header."""
        txt = self.display._textbox
        txt.tag_config("h1", font=("Consolas", 24, "bold"), foreground="#FFD700", spacing3=10)
        
        start_pos = "1.0"
        pos = txt.search("SKILLS", start_pos, stopindex="end")
        if pos:
            txt.tag_add("h1", pos, f"{pos} lineend")