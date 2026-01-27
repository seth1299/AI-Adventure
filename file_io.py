import sys, os
from config import SAVES_DIR, DEFAULT_RULES
from ui import StoryTab as story_tab
import json, threading
from ui import MarkdownEditorTab, GeneralUI

class FileIO():
    current_adventure_path = os.path.join(SAVES_DIR, save_name)
    
    def __init__(self):
        pass
    
def save_game():
    if not self.current_adventure_path or not self.game_loaded_successfully: 
        return

    # Save Markdown Tabs
    for name, widget in GeneralUI.get_notebook_widgets.items():
        if isinstance(widget, MarkdownEditorTab):
            try:
                with open(widget.filename, "w", encoding="utf-8") as f:
                    f.write(widget.get_text())
            except: pass

    # Save History & Status
    history_path = os.path.join(self.current_adventure_path, "savegame.json")
    history_list = [line for line in self.conversation_history.split("\n") if line.strip()]
        
    # Get Status from StoryTab
    status_data = self.story_tab.get_status_data()
        
    try:
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump({"Chat History": history_list, "Status": status_data, "is_creating": self.is_creating}, f, indent=4)
        print(f"Game saved to {self.current_adventure_path}")
    except Exception as e:
        print(f"Save failed: {e}")
    
    def load_adventure(self, save_name=""):
        self.game_loaded_successfully = False
        self.current_adventure_path = os.path.join(SAVES_DIR, save_name)
        story_tab.clear_chat()
        # Migrate legacy inventory format (old list items -> dict items)
        self._migrate_inventory_legacy_format()
        
        # UI Switch
        GeneralUI.get_main_menu.grid_forget()
        GeneralUI.get_tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        GeneralUI.set_title(f"AI RPG Adventure - {save_name}")

        # Propagate Path (Now with Error Handling)
        for name, widget in self.notebook_widgets.items():
            try:
                if hasattr(widget, 'set_base_path'):
                    widget.set_base_path(self.current_adventure_path)
                elif isinstance(widget, MarkdownEditorTab):
                    widget.filename = os.path.join(self.current_adventure_path, f"{name}.md")
                    if os.path.exists(widget.filename):
                        with open(widget.filename, "r", encoding="utf-8") as f:
                            widget.set_text(f.read())
                    else: widget.set_text(f"{name}\n")
            except Exception as e:
                # This prevents the "Silent Freeze" if a tab crashes
                print(f"Error loading tab {name}: {e}")
                self.story_tab.print_text(f"[System Error loading {name}: {e}]", sender="System")

        # Load History & Status
        history_path = os.path.join(self.current_adventure_path, "savegame.json")
        if os.path.exists(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.is_creating = bool(data.get("is_creating", False))
                    hist = data.get("Chat History", [])
                    self.conversation_history = "\n".join(hist) if isinstance(hist, list) else hist
                    
                    # Update StoryTab Status
                    status = data.get("Status", {})
                    if status:
                        self.story_tab.update_status(
                            status.get("turn", "1"),
                            status.get("location", "Unknown"),
                            status.get("day", "1"),
                            status.get("time", "Start")
                        )
                
                self.story_tab.print_text(f"System: Loaded '{save_name}'.", sender="System")
                if self.is_creating:
                    # If we are mid-creation, DO NOT generate a recap (hallucination risk).
                    # Instead, find the last thing the GM said and repeat it so the player knows what to answer.
                    last_gm_msg = "Resuming character creation..."
                    for line in reversed(self.conversation_history.split('\n')):
                        if line.startswith("GM:"):
                            last_gm_msg = line.replace("GM:", "").strip()
                            break
                    self.story_tab.print_text(last_gm_msg, sender="GM")
                else:
                    # Normal game: Generate Recap
                    recent = self.conversation_history[-3000:]
                    # We grab the text from Inventory, World, Character, etc. NOW, 
                    # because accessing these widgets inside the thread later might crash Tkinter.
                    context_data = ""
                    for name, widget in self.notebook_widgets.items():
                        if name != "Story": 
                            if hasattr(widget, 'get_text'):
                                context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"
                    curr_stat = self.story_tab.get_status_data()
                    context_data += f"\n[STATUS]\nLocation: {curr_stat['location']}\nDay: {curr_stat['day']}\nTime: {curr_stat['time']}\n"
                    threading.Thread(target=self.generate_recap, args=(recent,context_data), daemon=True).start()
            except Exception as e:
                self.story_tab.print_text(f"Error loading history: {e}", sender="System")
        else:
            self.conversation_history = ""
            self.is_creating = True
            self.story_tab.print_text("System: Initialization Sequence Started...", sender="System")
            threading.Thread(target=self.start_creation_wizard, daemon=True).start()
            
        self.game_loaded_successfully = True
        
    def load_rules(self):
        if self.current_adventure_path:
            local_rules = os.path.join(self.current_adventure_path, "rules.md")
            if os.path.exists(local_rules):
                try:
                    with open(local_rules, "r") as f: return f.read()
                except: pass
        return DEFAULT_RULES