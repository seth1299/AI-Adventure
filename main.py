from google import genai
from google.genai import types
import threading
import json
import os
import customtkinter as ctk
import random
import re
from dotenv import load_dotenv

# Import Config and UI
from config import GEMINI_API_KEY, MODEL, SAVES_DIR, DEFAULT_RULES
from ui import MainMenu, InventoryTab, SkillsTab, MarkdownEditorTab, StoryTab

# --- Configuration ---
load_dotenv()
client = genai.Client(api_key=GEMINI_API_KEY)

class GameApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("AI RPG Adventure")
        self.geometry("1000x700")
        ctk.set_appearance_mode("Dark")
        try: self.iconbitmap("game_icon.ico")
        except: pass

        self.current_adventure_path = None
        self.conversation_history = ""

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- VIEW 1: Main Menu ---
        self.main_menu = MainMenu(self, on_load_callback=self.load_adventure)
        self.main_menu.grid(row=0, column=0, sticky="nsew")

        # --- VIEW 2: Game Tabs (Hidden initially) ---
        self.tab_view = ctk.CTkTabview(self)
        self.tabs = ["Story", "Inventory", "Skills", "Quests", "Journal", "Character", "World"]
        self.notebook_widgets = {} 

        for tab_name in self.tabs:
            self.tab_view.add(tab_name)
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

            if tab_name == "Story":
                # Initialize StoryTab with a callback to our 'handle_player_action' method
                self.story_tab = StoryTab(frame, on_send_callback=self.handle_player_action)
                self.story_tab.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = self.story_tab
            
            elif tab_name == "Inventory":
                inv = InventoryTab(frame)
                inv.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = inv
            
            elif tab_name == "Skills":
                skl = SkillsTab(frame)
                skl.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = skl
            
            else:
                editor = MarkdownEditorTab(frame, default_text=f"# {tab_name}\n")
                editor.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = editor

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_adventure(self, save_name):
        self.current_adventure_path = os.path.join(SAVES_DIR, save_name)
        
        # UI Switch
        self.main_menu.grid_forget()
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.title(f"AI RPG Adventure - {save_name}")

        # Propagate Path
        for name, widget in self.notebook_widgets.items():
            if hasattr(widget, 'set_base_path'):
                widget.set_base_path(self.current_adventure_path)
            elif isinstance(widget, MarkdownEditorTab):
                widget.filename = os.path.join(self.current_adventure_path, f"{name}.md")
                if os.path.exists(widget.filename):
                    try:
                        with open(widget.filename, "r", encoding="utf-8") as f:
                            widget.set_text(f.read())
                    except: widget.set_text(f"# {name}\n")
                else: widget.set_text(f"# {name}\n")

        # Load History & Status
        history_path = os.path.join(self.current_adventure_path, "savegame.json")
        if os.path.exists(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    hist = data.get("Chat History", [])
                    self.conversation_history = "\n".join(hist) if isinstance(hist, list) else hist
                    
                    # Update StoryTab Status
                    status = data.get("Status", {})
                    if status:
                        self.story_tab.update_status(
                            status.get("turn", "1"),
                            status.get("location", "Unknown"),
                            status.get("time", "Start")
                        )
                
                self.story_tab.print_text(f"System: Loaded '{save_name}'.", sender="System")
                recent = self.conversation_history[-3000:]
                threading.Thread(target=self.generate_recap, args=(recent,), daemon=True).start()
            except Exception as e:
                self.story_tab.print_text(f"Error loading history: {e}", sender="System")
        else:
            self.conversation_history = ""
            self.story_tab.print_text("System: New Adventure Started.", sender="System")
            
            # Init Starter Skills
            self.notebook_widgets["Skills"].force_learn_skill("Survival", 1)
            self.notebook_widgets["Skills"].force_learn_skill("Perception", 1)
            
            self.story_tab.print_text("Welcome. The world awaits. What is your name?", sender="GM")

    def load_rules(self):
        if self.current_adventure_path:
            local_rules = os.path.join(self.current_adventure_path, "rules.md")
            if os.path.exists(local_rules):
                try:
                    with open(local_rules, "r") as f: return f.read()
                except: pass
        return DEFAULT_RULES

    # --- Game Logic ---

    def handle_player_action(self, user_text):
        """Called by StoryTab when user clicks Act."""
        # 1. Update UI
        self.story_tab.set_controls_state(False, "GM is thinking...")
        self.story_tab.print_text(user_text, sender="Player")

        # 2. Gather Context
        context_data = ""
        for name, widget in self.notebook_widgets.items():
            # StoryTab doesn't need to feed into context, other tabs do
            if name != "Story": 
                # Note: Inventory/Skills tabs now have .get_text() methods from previous steps
                if hasattr(widget, 'get_text'):
                    context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"
                    
        current_status = self.story_tab.get_status_data()
        try:
            current_turn_int = int(current_status['turn'])
        except:
            current_turn_int = 1
        
        next_turn_int = current_turn_int + 1
        # We tell the AI exactly what the *Next* turn is.
        status_context = (
            f"\n[CURRENT STATUS]\n"
            f"Location: {current_status['location']}\n"
            f"Time: {current_status['time']}\n"
            f"Current Turn: {current_turn_int}\n"
            f"UPCOMING TURN: {next_turn_int} (You MUST use this number in the [[STATUS]] tag)"
        )
        context_data += status_context

        # 3. Build Prompt
        recent_history = self.conversation_history[-3000:] if len(self.conversation_history) > 3000 else self.conversation_history
        full_prompt = f"{context_data}\nHistory:\n{recent_history}\nPlayer: {user_text}\nGM:"

        # 4. Thread the AI Call
        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()

    def perform_skill_check(self, skill_name):
        clean_name = skill_name.split('(')[0].strip().title()
        skills_tab = self.notebook_widgets["Skills"]
        data = skills_tab.load_data()
        
        skill_entry = None
        for item in data:
            if item["Name"].lower() == clean_name.lower():
                skill_entry = item
                break
        
        if not skill_entry:
            skill_entry = {"Name": clean_name, "Level": 0, "XP": 0, "Threshold": 5}
            data.append(skill_entry)
            self.story_tab.print_text(f"🆕 Learned new skill: {clean_name}!", sender="System")

        # XP Logic
        skill_entry["XP"] += 1
        leveled_up = False
        if skill_entry["XP"] >= skill_entry["Threshold"]:
            skill_entry["Level"] += 1
            skill_entry["XP"] = 0
            skill_entry["Threshold"] += 2
            leveled_up = True
            
        skills_tab.save_data(data)
        
        bonus = skill_entry["Level"]
        die_roll = random.randint(1, 20)
        total = die_roll + bonus
        
        msg = f"🎲 Rolling {clean_name}: {die_roll} + ({bonus}) = {total}"
        if leveled_up:
            msg += f"\n🎉 **LEVEL UP!** {clean_name} is now Level {skill_entry['Level']}!"
            
        self.story_tab.print_text(msg, sender="System")
        return total

    def query_ai(self, prompt, user_text, recursion_depth=0):
        current_rules = self.load_rules()
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=current_rules,
                    temperature=0.7
                )
            )
            ai_text = response.text
            if not ai_text: raise ValueError("Empty response")
            
            # 1. Add/Remove Items
            for match in re.finditer(r"\[\[ADD:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].autonomous_add(match.group(1))
                print(res)

            for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].autonomous_remove(match.group(1))
                print(res)
            
            # 2. Status Update
            status_match = re.search(r"\[\[STATUS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text)
            if status_match:
                turn = status_match.group(1).strip()
                loc = status_match.group(2).strip()
                time = status_match.group(3).strip()
                self.after(0, lambda: self.story_tab.update_status(turn, loc, time))

            # 3. Rolls & Recursion
            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
            
            if roll_match and recursion_depth < 2:
                skill = roll_match.group(1).strip()
                result = self.perform_skill_check(skill)
                clean_prev = re.sub(r"\[\[(ADD|REMOVE):.*?\]\]", "", ai_text).strip()
                follow_up = f"{prompt}\nGM: {clean_prev}\n[System: Player rolled {result} for {skill}.]"
                self.query_ai(follow_up, user_text, recursion_depth + 1)
            else:
                final_text = re.sub(r"\[\[.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
                # Replace 3 or more newlines with just 2 (Standard paragraph break)
                final_text = re.sub(r'\n{3,}', '\n\n', final_text)
                # Strip leading/trailing whitespace completely
                final_text = final_text.strip()
                # Only print if there is actually text left
                if final_text:
                    self.story_tab.print_text(final_text, sender="GM")
                    self.conversation_history += f"Player: {user_text}\nGM: {final_text}\n"

        except Exception as e:
            self.story_tab.print_text(f"AI Error: {e}", sender="System")
        finally:
            self.after(0, lambda: self.story_tab.set_controls_state(True))

    def generate_recap(self, history):
        self.after(0, lambda: self.story_tab.set_controls_state(False, "Recapping..."))
        try:
            prompt = f"History:\n{history}\nSummarize situation in a paragraph. Remember to not output anything that starts with \"[[\". Ask 'What do you do?'"
            resp = client.models.generate_content(
                model=MODEL, 
                contents=prompt, 
                config=types.GenerateContentConfig(system_instruction=self.load_rules())
            )
            ai_text = resp.text or ""
            # 1. Remove Tags (including Status, which causes the leak)
            clean_text = re.sub(r"\[\[.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
            
            # 2. Fix Whitespace
            clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
            
            if clean_text:
                self.story_tab.print_text(f"📝 RECAP: {clean_text}", sender="GM")
        except: pass
        finally:
            self.after(0, lambda: self.story_tab.set_controls_state(True))

    def save_game(self):
        if not self.current_adventure_path: return

        # Save Markdown Tabs
        for name, widget in self.notebook_widgets.items():
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
                json.dump({"Chat History": history_list, "Status": status_data}, f, indent=4)
            print(f"Game saved to {self.current_adventure_path}")
        except Exception as e:
            print(f"Save failed: {e}")

    def on_close(self):
        self.save_game()
        self.destroy()

if __name__ == "__main__":
    app = GameApp()
    app.mainloop()