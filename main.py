from google import genai
from google.genai import types
import threading
import json
import sys
import os
import customtkinter as ctk
import random
import re
from dotenv import load_dotenv

# Import Config and UI
from config import GEMINI_API_KEY, MODEL, SAVES_DIR, DEFAULT_RULES
from ui import MainMenu, InventoryTab, SkillsTab, MarkdownEditorTab, StoryTab, ProcessingTab

# --- Configuration ---
load_dotenv()
client = genai.Client(api_key=GEMINI_API_KEY)

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    # getattr(object, name, default) tries to get the attribute, 
    # and returns the default (current path) if it doesn't exist.
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

class GameApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.is_creating = False
        self.game_loaded_successfully = False
        self.title("AI RPG Adventure")
        self.geometry("1000x700")
        ctk.set_appearance_mode("Dark")
        # Use the helper to find the icon inside the EXE
        icon_path = resource_path("game_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                print(f"Icon error: {e}")

        self.current_adventure_path = None
        self.conversation_history = ""

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- VIEW 1: Main Menu ---
        self.main_menu = MainMenu(self, on_load_callback=self.load_adventure)
        self.main_menu.grid(row=0, column=0, sticky="nsew")

        # --- VIEW 2: Game Tabs (Hidden initially) ---
        self.tab_view = ctk.CTkTabview(self)
        self.tabs = ["Story", "Inventory", "Skills", "Processing", "Character", "World", "Journal"]
        self.notebook_widgets = {} 

        for tab_name in self.tabs:
            self.tab_view.add(tab_name)
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

            if tab_name == "Story":
                # Initialize StoryTab with a callback to our 'handle_player_action' method
                self.story_tab = StoryTab(frame, 
                                          on_send_callback=self.handle_player_action,
                                          on_main_menu_callback=self.return_to_menu)
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
                
            elif tab_name == "Processing":
                proc = ProcessingTab(frame)
                proc.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = proc
            
            else:
                editor = MarkdownEditorTab(frame, default_text=f"{tab_name}\n")
                editor.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = editor

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def return_to_menu(self):
        """Saves game and goes back to main menu."""
        self.save_game()
        self.current_adventure_path = None
        self.is_creating = False
        
        # Hide Game Tabs
        self.tab_view.grid_forget()
        self.title("AI RPG Adventure")
        
        # Show Main Menu
        self.main_menu.refresh_list()
        self.main_menu.grid(row=0, column=0, sticky="nsew")

    def load_adventure(self, save_name):
        self.game_loaded_successfully = False
        self.current_adventure_path = os.path.join(SAVES_DIR, save_name)
        
        self.story_tab.clear_chat()
        
        # UI Switch
        self.main_menu.grid_forget()
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.title(f"AI RPG Adventure - {save_name}")

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
            
    def start_creation_wizard(self):
        """Sends the initial system prompt to start the interview."""
        # Use config.py's CREATION_RULES specifically for this
        from config import CREATION_RULES 
        
        prompt = "System: Begin the Step 1 of the Character Creation process."
        
        try:
            # We send this with the CREATION_RULES as system instruction
            resp = client.models.generate_content(
                model=MODEL, 
                contents=prompt, 
                config=types.GenerateContentConfig(system_instruction=CREATION_RULES)
            )
            self.story_tab.print_text(resp.text, sender="GM")
            self.conversation_history += f"GM: {resp.text}\n"
        except Exception as e:
            self.story_tab.print_text(f"Creation Error: {e}", sender="System")

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
            f"Day: {current_status['day']}\n"
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
            msg += f"\n🎉 **LEVEL UP!** {clean_name} is now Level {skill_entry['Level']}! {skill_entry["Threshold"]} XP required until level {skill_entry["Level"] + 1}."
        else:
            msg += f"\n{clean_name}: {skill_entry["XP"]} / {skill_entry["Threshold"]} XP towards next level up."
            
        self.story_tab.print_text(msg, sender="System")
        return total

    def query_ai(self, prompt, user_text, recursion_depth=0):
        from config import CREATION_RULES
        
        if self.is_creating:
            current_rules = CREATION_RULES
        else:
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
            ai_text = response.text or ""
            if not ai_text: raise ValueError("Empty response")
            
            # --- PARSE CREATION TAGS (Only if creating) ---
            if self.is_creating:
                # 1. World Info -> World Tab
                world_match = re.search(r"\[\[WORLD_INFO:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if world_match:
                    content = world_match.group(1).strip()
                    self.notebook_widgets["World"].set_text(f"World Setting\n\n{content}")
                
                # 2. Character Info -> Character Tab
                char_match = re.search(r"\[\[CHARACTER_INFO:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if char_match:
                    content = char_match.group(1).strip()
                    self.notebook_widgets["Character"].set_text(f"Character Bio\n\n{content}")

                # 3. Skills -> Force Learn
                # Format: [[SKILL: Name | Level]]
                for match in re.finditer(r"\[\[SKILL:\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text):
                    s_name = match.group(1).strip()
                    s_lvl = int(match.group(2))
                    self.notebook_widgets["Skills"].force_learn_skill(s_name, s_lvl)

                # 4. Start Game Trigger
                if "[[START_GAME]]" in ai_text:
                    self.is_creating = False
                    self.story_tab.print_text("\n[System: Creation Complete. Saving Data...]\n", sender="System")
                    self.save_game()
                    # Clean the tag out of the text so player doesn't see it
                    ai_text = ai_text.replace("[[START_GAME]]", "")
                    self.conversation_history += response.text or ""
                    self.handle_player_action("We have completed character creation. Please describe the starting scene, updating the location and time values as necessary.")
                    return
                    
            
            # 1. Add/Remove Items
            for match in re.finditer(r"\[\[ADD:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].autonomous_add(match.group(1))
                self.story_tab.print_text(res, sender="GM")
                self.conversation_history += res

            for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].autonomous_remove(match.group(1))
                self.story_tab.print_text(res, sender="GM")
                self.conversation_history += res
            
            # 2. Status Update
            status_match = re.search(r"\[\[STATUS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text)
            if status_match:
                turn = status_match.group(1).strip()
                location = status_match.group(2).strip()
                day = status_match.group(3).strip()
                time = status_match.group(4).strip()
                self.after(0, lambda: self.story_tab.update_status(turn, location, day, time))
                
                # Check Processing Tab (Only if NOT creating)
                if not self.is_creating and "Processing" in self.notebook_widgets:
                    finished_items = self.notebook_widgets["Processing"].check_active_tasks(day, time)
                    if finished_items:
                        sys_msg = f"System: Process completed - {', '.join(finished_items)}"
                        self.story_tab.print_text(sys_msg, sender="System")
                        self.conversation_history += f"\n{sys_msg}\n"
                        
            # Tag: [[START_PROCESS: Name | Description | Time_Slots]]
            # We need the CURRENT status to calculate the target time.
            current_status = self.story_tab.get_status_data() # Gets current UI values
            
            for match in re.finditer(r"\[\[START_PROCESS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text):
                p_name = match.group(1).strip()
                p_desc = match.group(2).strip()
                p_slots = match.group(3).strip()
                
                # Pass current Day/Time to calculate target
                res = self.notebook_widgets["Processing"].add_process(
                    p_name, p_desc, p_slots, 
                    current_status['day'], current_status['time']
                )
                self.story_tab.print_text(res, sender="System")
                
            # --- REMOVE PROCESS TAG (Same as before) ---
            for match in re.finditer(r"\[\[REMOVE_PROCESS:\s*(.*?)\]\]", ai_text):
                p_name = match.group(1).strip()
                res = self.notebook_widgets["Processing"].remove_process(p_name)
                if res: self.story_tab.print_text(res, sender="System")
                
            # Tag: [[START_PROJECT: Name | Desc | Total_Slots]]
            # This creates a "Manual" task that requires work.
            for match in re.finditer(r"\[\[START_PROJECT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text):
                p_name = match.group(1).strip()
                p_desc = match.group(2).strip()
                p_slots = match.group(3).strip()
                current_status = self.story_tab.get_status_data()
                
                # We pass mode="manual" here
                res = self.notebook_widgets["Processing"].add_process(
                    p_name, p_desc, p_slots, 
                    current_status['day'], current_status['time'], 
                    mode="manual"
                )
                if res: self.story_tab.print_text(res, sender="System")

            # Tag: [[WORK: Name | Slots]]
            # This applies progress to a manual task.
            for match in re.finditer(r"\[\[WORK:\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text):
                p_name = match.group(1).strip()
                p_slots = match.group(2).strip()
                res = self.notebook_widgets["Processing"].progress_manual_task(p_name, p_slots)
                if res: self.story_tab.print_text(res, sender="System")
                
            # Tag: [[ADD_FOOD: Type | Name | Desc | Amount | Value | Meals | SpoilDay | SpoilTime]]
            for match in re.finditer(r"\[\[ADD_FOOD:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].add_food(match.group(1))
                self.story_tab.print_text(res, sender="GM")
                
            # Tag: [[CONSUME: FoodName]]
            for match in re.finditer(r"\[\[CONSUME:\s*(.*?)\]\]", ai_text):
                f_name = match.group(1).strip()
                # Get current time to check spoilage
                status = self.story_tab.get_status_data()
                res = self.notebook_widgets["Inventory"].consume_food(f_name, status['day'], status['time'])
                self.story_tab.print_text(res, sender="System")

            # 3. Rolls & Recursion
            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
            
            if roll_match and recursion_depth < 2:
                skill = roll_match.group(1).strip()
                result = self.perform_skill_check(skill)
                clean_prev = re.sub(r"\[\[(ADD|REMOVE):.*?\]\]", "", ai_text).strip()
                follow_up = f"{prompt}\nGM: {clean_prev}\n[System: Player rolled {result} for {skill}.]"
                self.query_ai(follow_up, user_text, recursion_depth + 1)
            else:
                clean_pattern = re.compile(r"\[\[(WORLD_INFO|CHARACTER_INFO|SKILL|ADD|REMOVE|STATUS|ROLL|START_GAME|XP|START_PROCESS|REMOVE_PROCESS|START_PROJECT|WORK|ADD_FOOD|CONSUME).*?\]\]", re.DOTALL)
                final_text = clean_pattern.sub("", ai_text)
                #final_text = re.sub(r"\[\[.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
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

    def generate_recap(self, history, context_data):
        self.after(0, lambda: self.story_tab.set_controls_state(False, "Recapping..."))
        try:
            # We feed the AI the full Context (Inventory, World, Status) PLUS the (possibly empty) History.
            prompt = f"Context Data:\n{context_data}\n\nRecent Chat History:\n{history}\n\nTask: Summarize the current situation in a single paragraph based on the Context and Status provided above. Do not output anything that starts with \"[[\". End by asking 'What do you do?'"
            
            resp = client.models.generate_content(
                model=MODEL, 
                contents=prompt, 
                config=types.GenerateContentConfig(system_instruction=self.load_rules())
            )
            ai_text = resp.text or ""
            
            # 1. Remove Tags (The AI might try to reprint the status, we strip that)
            clean_text = re.sub(r"\[\[.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
            
            # 2. Fix Whitespace
            clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
            
            if clean_text:
                self.story_tab.print_text(f"RECAP: {clean_text}", sender="GM")
        except Exception as e:
            self.story_tab.print_text(f"Recap Error: {e}", sender="System")
        finally:
            self.after(0, lambda: self.story_tab.set_controls_state(True))

    def save_game(self):
        if not self.current_adventure_path or not self.game_loaded_successfully: 
            return

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
                json.dump({"Chat History": history_list, "Status": status_data, "is_creating": self.is_creating}, f, indent=4)
            print(f"Game saved to {self.current_adventure_path}")
        except Exception as e:
            print(f"Save failed: {e}")

    def on_close(self):
        self.save_game()
        self.destroy()

if __name__ == "__main__":
    app = GameApp()
    app.mainloop()