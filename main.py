from google import genai
from google.genai import types
import threading
import json
import sys
import os
import customtkinter as ctk
import random
import re
from time_utils import add_hours, normalize_day_time
from dotenv import load_dotenv
from sound_manager import SoundManager
import logging
import shutil
import random

# Import Config and UI
from config import GEMINI_API_KEY, MODEL, SAVES_DIR, DEFAULT_RULES, SOUNDS_DIR, BASE_SOUNDS_DIR, VALID_SOUND_FILE_NAMES, APP_NAME
from ui import MainMenu, InventoryTab, SkillsTab, MarkdownEditorTab, StoryTab, ProcessingTab
from ui.recipes_tab import RecipesTab

# [NEW] Imports
try:
    from rapidfuzz import process, fuzz
except ImportError:
    pass # Handled in logic
from file_manager import FileManager
from player import Player

# --- Configuration ---
load_dotenv()
client = genai.Client(api_key=GEMINI_API_KEY)

# Setup initial logging via the new FileManager
FileManager.setup_initial_logging()

class GameApp(ctk.CTk):
    
    def __init__(self):
        super().__init__()
        self.is_creating = False
        self.game_loaded_successfully = False
        self.title("AI RPG Adventure")
        self.geometry("1000x700")
        self.sound_manager = SoundManager(SOUNDS_DIR)
        
        # [NEW] Initialize Player
        self.player = Player()
        
        ctk.set_appearance_mode("Dark")
        
        # [UPDATED] Use FileManager
        icon_path = FileManager.resource_path("game_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                logging.error(f"Icon error: {e}")

        self.current_adventure_path = None
        self.creation_summary_path = os.path.join(SAVES_DIR, "creation_summary.txt")
        self.conversation_history = ""
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- VIEW 1: Main Menu ---
        self.main_menu = MainMenu(self, on_load_callback=self.load_adventure)
        self.main_menu.grid(row=0, column=0, sticky="nsew")

        # --- VIEW 2: Game Tabs (Hidden initially) ---
        self.tab_view = ctk.CTkTabview(self)
        self.tabs = ["Story", "Inventory", "Skills", "Processing", "Recipes", "Character", "World", "Journal"]
        self.notebook_widgets = {}
        for sound in VALID_SOUND_FILE_NAMES:
            current_path = os.path.join(BASE_SOUNDS_DIR, sound)
            destination_path = os.path.join(SOUNDS_DIR, sound)
            if os.path.exists(destination_path): pass
            else: shutil.copyfile(current_path, destination_path)
        
        for tab_name in self.tabs:
            self.tab_view.add(tab_name)
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

            if tab_name == "Story":
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
            elif tab_name == "Recipes":
                rec = RecipesTab(frame)
                rec.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = rec
            else:
                editor = MarkdownEditorTab(frame, default_text=f"{tab_name}\n")
                editor.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = editor

        self.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def clean_quotes(self, text):
        if not text: return ""
        return text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
        
    def _get_skill_level(self, skill_name: str) -> int:
        clean = (skill_name or "").split('(')[0].strip().title()
        try:
            skills_tab = self.notebook_widgets["Skills"]
            data = skills_tab.load_data()
            for item in data:
                if item.get("Name", "").lower() == clean.lower():
                    return int(item.get("Level", 0) or 0)
        except Exception as e:
            logging.error("Get skill level error: {e}")
        return 0

    def _advance_time_hours(self, hours: float):
        # [UPDATED] Use Player state
        gt = add_hours(str(self.player.day), self.player.time, hours)
        
        # Update Player State
        self.player.day = gt.as_day_string()
        self.player.time = gt.as_time_string()
        
        # Update UI
        self._sync_player_state_to_ui()

    def _sync_player_state_to_ui(self):
        """Push player state to the StoryTab UI."""
        self.after(0, lambda: self.story_tab.update_status(
            self.player.turn,
            self.player.location,
            self.player.day,
            self.player.time,
            nutrition=self.player.nutrition,
            stamina=self.player.stamina
        ))

    def return_to_menu(self):
        self.save_game()
        self.current_adventure_path = None
        self.is_creating = False
        FileManager.update_logger_path(None)
        
        self.tab_view.grid_forget()
        self.title("AI RPG Adventure")
        self.main_menu.refresh_list()
        self.main_menu.grid(row=0, column=0, sticky="nsew")

    def load_adventure(self, save_name):
        self.game_loaded_successfully = False
        self.current_adventure_path = os.path.join(SAVES_DIR, save_name)
        self.current_sounds_path = os.path.join(SOUNDS_DIR, save_name)
        self.story_tab.clear_chat()
        
        # [UPDATED] Use FileManager
        FileManager.update_logger_path(save_name)
        
        self._migrate_inventory_legacy_format()
        
        self.main_menu.grid_forget()
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.title(f"{save_name}")

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
                logging.error(f"Error loading tab {name}: {e}")

        history_path = os.path.join(self.current_adventure_path, "savegame.json")
        if os.path.exists(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.is_creating = bool(data.get("is_creating", False))
                    
                    # [UPDATED] Load Player State
                    self.player.karmic_streak = data.get("karmic_streak", 0)
                    status_data = data.get("Status", {})
                    if status_data:
                        self.player.load_from_dict(status_data)
                        self._sync_player_state_to_ui()

                    hist = data.get("Chat History", [])
                    self.conversation_history = "\n".join(hist) if isinstance(hist, list) else hist
                
                self.story_tab.print_text(f"System: Loaded '{save_name}'.", sender="System")
                
                if self.is_creating:
                    last_gm_msg = "Resuming character creation..."
                    for line in reversed(self.conversation_history.split('\n')):
                        if line.startswith("GM:"):
                            last_gm_msg = line.replace("GM:", "").strip()
                            break
                    self.story_tab.print_text(last_gm_msg, sender="GM")
                else:
                    self.generate_local_recap()
                    
            except Exception as e:
                logging.error(f"Error loading history: {e}")
        else:
            self.conversation_history = ""
            self.is_creating = True
            self.story_tab.print_text("System: Initialization Sequence Started...", sender="System")
            threading.Thread(target=self.start_creation_wizard, daemon=True).start()
            
        self.game_loaded_successfully = True

    def generate_local_recap(self):
        try:
            self._attempt_local_music_restore()
            last_gm_msg = None
            if self.conversation_history:
                last_gm_index = self.conversation_history.rfind("GM:")
                if last_gm_index != -1:
                    text_chunk = self.conversation_history[last_gm_index:]
                    text_chunk = text_chunk.replace("GM:", "", 1).strip()
                    if "Player:" in text_chunk:
                         text_chunk = text_chunk.split("Player:")[0].strip()
                    last_gm_msg = text_chunk
            
            if last_gm_msg:
                self.story_tab.print_text(f"RECAP: {last_gm_msg}", sender="GM")
                self.story_tab.print_text("\n[System: It is your turn. What do you do?]", sender="System")
            else:
                self.story_tab.print_text("System: No recent history found to recap.", sender="System")
        except Exception as e:
            logging.error(f"Local Recap Error: {e}")

    def _attempt_local_music_restore(self):
        try:
            # [UPDATED] Use Player location
            location = self.player.location
            if not location or not VALID_SOUND_FILE_NAMES: return

            match_tuple = process.extractOne(
                location, 
                VALID_SOUND_FILE_NAMES, 
                scorer=fuzz.WRatio,
                score_cutoff=55 
            )
            
            if match_tuple:
                self.sound_manager.play_music(match_tuple[0])
            else:
                self.sound_manager.play_music("main_menu.mp3")
        except Exception as e:
            logging.error(f"Music restore error: {e}")

    def start_creation_wizard(self):
        from config import CREATION_RULES 
        if os.path.exists(self.creation_summary_path):
            try:
                os.remove(self.creation_summary_path)
            except Exception as e:
                logging.error(f"Error clearing creation summary: {e}")
        
        prompt = "System: Begin the Step 1 of the Character Creation process."
        try:
            resp = client.models.generate_content(
                model=MODEL, 
                contents=prompt, 
                config=types.GenerateContentConfig(system_instruction=CREATION_RULES)
            )
            raw_text = self.clean_quotes(resp.text)
            clean_text = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", raw_text, flags=re.DOTALL).strip()
            self.story_tab.print_text(clean_text, sender="GM")
            self.conversation_history += f"GM: {clean_text}\n"
        except Exception as e:
            logging.error(f"Creation Error: {e}")

    def load_rules(self):
        if self.current_adventure_path:
            local_rules = os.path.join(self.current_adventure_path, "rules.md")
            if os.path.exists(local_rules):
                try:
                    with open(local_rules, "r") as f: return f.read()
                except: pass
        return DEFAULT_RULES
    
    def _migrate_inventory_legacy_format(self):
        if not self.current_adventure_path: return
        inv_path = os.path.join(self.current_adventure_path, "inventory.json")
        if not os.path.exists(inv_path): return
        try:
            with open(inv_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.error(f"Json load error: {e}")
            return
        if not isinstance(data, dict): return
        changed = False
        for cat, items in list(data.items()):
            if not isinstance(items, list): continue
            new_items = []
            for item in items:
                if isinstance(item, dict): new_items.append(item)
                elif isinstance(item, list):
                    name = item[0] if len(item) > 0 else "Unknown"
                    desc = item[1] if len(item) > 1 else "No desc"
                    amt  = item[2] if len(item) > 2 else "1"
                    val  = item[3] if len(item) > 3 else "0"
                    new_items.append({"name": name, "desc": desc, "amount": str(amt), "value": str(val)})
                    changed = True
                else: changed = True
            data[cat] = new_items
        if changed:
            try:
                with open(inv_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                pass

    def handle_player_action(self, user_text):
        self.story_tab.set_controls_state(False, "GM is thinking...")
        self.story_tab.print_text(user_text, sender="Player")

        context_data = ""
        for name, widget in self.notebook_widgets.items():
            if name != "Story": 
                if hasattr(widget, 'get_text'):
                    context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"
        
        # [UPDATED] Use Player state
        next_turn = self.player.turn + 1
        status_context = (
            f"\n[CURRENT STATUS]\n"
            f"Location: {self.player.location}\n"
            f"Day: {self.player.day}\n"
            f"Time: {self.player.time}\n"
            f"Current Turn: {self.player.turn}\n"
            f"UPCOMING TURN: {next_turn} (You MUST use this number in the [[STATUS]] tag)"
        )
        context_data += status_context

        if self.is_creating:
            recent_history = self.conversation_history[-1500:] if len(self.conversation_history) > 1500 else self.conversation_history
            creation_memory = ""
            if os.path.exists(self.creation_summary_path):
                try:
                    with open(self.creation_summary_path, "r", encoding="utf-8") as f:
                        summaries = f.read()
                    creation_memory = f"\n[CREATION_HISTORY_SUMMARY (DO NOT IGNORE)]:\n{summaries}\n"
                except Exception as e:
                    logging.error(f"Error reading creation summary: {e}")
            full_prompt = f"{context_data}\n{creation_memory}\nRecent Chat:\n{recent_history}\nPlayer: {user_text}\nGM:"
        else:
            recent_history = self.conversation_history[-3000:] if len(self.conversation_history) > 3000 else self.conversation_history
            full_prompt = f"{context_data}\nHistory:\n{recent_history}\nPlayer: {user_text}\nGM:"

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
            self.story_tab.print_text(f"Learned new skill: {clean_name}!", sender="System")
            
        die_roll = random.randint(1, 20)
        new_roll, intervened = self.player.check_karma_intervention(die_roll)
        die_roll = new_roll
        
        # [UPDATED] Update Karma
        if not intervened:
            self.player.update_karma(die_roll)

        skill_entry["XP"] += 1
        leveled_up = False
        if skill_entry["XP"] >= skill_entry["Threshold"]:
            skill_entry["Level"] += 1
            skill_entry["XP"] = 0
            skill_entry["Threshold"] += 2
            leveled_up = True
            
        skills_tab.save_data(data)
        
        # [UPDATED] Use Player stats for bonuses
        bonus_from_nutrition = 0
        if self.player.nutrition >= 85: bonus_from_nutrition = 1
        elif self.player.nutrition <= 40: bonus_from_nutrition = -3 # Simplified for example
        
        bonus_from_stamina = 0
        if self.player.stamina >= 85: bonus_from_stamina = 1
        elif self.player.stamina <= 40: bonus_from_stamina = -3

        skill_bonus = skill_entry["Level"]
        total = die_roll + skill_bonus + bonus_from_nutrition + bonus_from_stamina
        
        msg = f"軸 Rolling {clean_name}: {die_roll} + ({skill_bonus}) = {total}"
        if leveled_up:
            msg += f"\n脂 **LEVEL UP!** {clean_name} is now Level {skill_entry['Level']}!"
        else:
            msg += f"\n{clean_name}: {skill_entry['XP']} / {skill_entry['Threshold']} XP towards next level up."

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
            ai_text = self.clean_quotes(response.text or "")
            if not ai_text: raise ValueError("Empty response")
            
            if self.is_creating:
                summary_match = re.search(r"\[\[STEP_SUMMARY:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if summary_match:
                    new_summary = summary_match.group(1).strip()
                    try:
                        with open(self.creation_summary_path, "a", encoding="utf-8") as f:
                            f.write(f"- {new_summary}\n")
                    except Exception as e:
                        logging.error(f"Error writing creation summary: {e}")

                world_match = re.search(r"\[\[WORLD_INFO:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if world_match:
                    content = world_match.group(1).strip()
                    self.notebook_widgets["World"].set_text(f"World Setting\n\n{content}")
                
                char_match = re.search(r"\[\[CHARACTER_INFO:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if char_match:
                    content = char_match.group(1).strip()
                    self.notebook_widgets["Character"].set_text(f"Character Bio\n\n{content}")

                for match in re.finditer(r"\[\[SKILL:\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text):
                    s_name = match.group(1).strip()
                    s_lvl = int(match.group(2))
                    self.notebook_widgets["Skills"].force_learn_skill(s_name, s_lvl)

                if "[[START_GAME]]" in ai_text:
                    self.is_creating = False
                    self.story_tab.print_text("\n[System: Creation Complete. Saving Data...]\n", sender="System")
                    if os.path.exists(self.creation_summary_path):
                        try:
                            os.remove(self.creation_summary_path)
                        except Exception as e:
                            logging.error(f"Error deleting creation summary: {e}")
                    self.save_game()
                    ai_text = ai_text.replace("[[START_GAME]]", "")
                    clean_creation_text = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
                    self.conversation_history += f"GM: {clean_creation_text}\n"

            for match in re.finditer(r"\[\[ADD:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].autonomous_add(match.group(1))
                self.story_tab.print_text(res, sender="GM")

            for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].autonomous_remove(match.group(1))
                self.story_tab.print_text(res, sender="GM")
                
            for match in re.finditer(r"\[\[MODIFY_ITEM:\s*(.*?)\]\]", ai_text, re.DOTALL):
                res = self.notebook_widgets["Inventory"].modify_item(match.group(1).strip())
                if res: self.story_tab.print_text(res, sender="System")

            # [UPDATED] Use Player.modify_stat
            for match in re.finditer(r"\[\[MODIFY_STAT:\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text):
                stat_name = match.group(1).strip()
                stat_val = match.group(2).strip()
                self.player.modify_stat(stat_name, stat_val)
                self._sync_player_state_to_ui()
                    
            music_match = re.search(r"\[\[MUSIC:\s*(.*?)\]\]", ai_text)
            if music_match:
                track = music_match.group(1).strip()
                self.after(0, lambda: self.sound_manager.play_music(track))

            for match in re.finditer(r"\[\[SOUND:\s*(.*?)\]\]", ai_text):
                sfx = match.group(1).strip()
                self.after(0, lambda s=sfx: self.sound_manager.play_sfx(s))

            status_match = re.search(r"\[\[STATUS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text)
            if status_match:
                # [UPDATED] Update Player State
                self.player.update_world_state(
                    turn=status_match.group(1).strip(),
                    location=status_match.group(2).strip(),
                    day=status_match.group(3).strip(),
                    time=status_match.group(4).strip()
                )
                self._sync_player_state_to_ui()

                if not self.is_creating and "Processing" in self.notebook_widgets:
                    finished_items = self.notebook_widgets["Processing"].check_active_tasks(self.player.day, self.player.time)
                    if finished_items:
                        sys_msg = f"System: Process completed - {', '.join(finished_items)}"
                        self.story_tab.print_text(sys_msg, sender="System")
                        self.conversation_history += f"\n{sys_msg}\n"
                        
            for match in re.finditer(r"\[\[RECIPE:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Recipes"].add_recipe_from_tag(match.group(1))
                self.story_tab.print_text(res, sender="System")
                        
            for match in re.finditer(r"\[\[START_PROCESS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\]\]", ai_text):
                p_name = match.group(1).strip()
                p_desc = match.group(2).strip()
                p_slots = match.group(3).strip()
                p_yield = match.group(4).strip()
                res = self.notebook_widgets["Processing"].add_timed_process(p_name, p_desc, p_slots, self.player.day, self.player.time, p_yield)
                self.story_tab.print_text(res, sender="System")
                
            for match in re.finditer(r"\[\[REMOVE_PROCESS:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Processing"].remove_process(match.group(1).strip())
                if res: self.story_tab.print_text(res, sender="System")
                
            for match in re.finditer(r"\[\[START_PROJECT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text):
                p_name = match.group(1).strip()
                p_desc = match.group(2).strip()
                work_required = match.group(3).strip()
                skill_name = match.group(4).strip()
                p_yield = match.group(5).strip()
                lvl = self._get_skill_level(skill_name)
                res = self.notebook_widgets["Processing"].add_project(p_name, p_desc, work_required, skill_name, lvl, p_yield)
                if res: self.story_tab.print_text(res, sender="System")

            for match in re.finditer(r"\[\[WORK:\s*(.*?)\s*\|\s*([\d.]+)\]\]", ai_text):
                project_name = match.group(1).strip()
                hours_worked = float(match.group(2).strip())
                req_skill = self.notebook_widgets["Processing"].get_required_skill(project_name) or ""
                lvl = self._get_skill_level(req_skill) if req_skill else 0
                res = self.notebook_widgets["Processing"].apply_work_hours(project_name, hours_worked, lvl)
                
                self._advance_time_hours(hours_worked)

                completed = self.notebook_widgets["Processing"].check_active_tasks(self.player.day, self.player.time)
                if completed:
                    sys_msg = f"System: Process completed - {', '.join(completed)}"
                    self.story_tab.print_text(sys_msg, sender="System")
                    self.conversation_history += f"\n{sys_msg}\n"

                if res: self.story_tab.print_text(res, sender="System")
                
            for match in re.finditer(r"\[\[ADD_FOOD:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].add_food(match.group(1))
                self.story_tab.print_text(res, sender="GM")
                
            for match in re.finditer(r"\[\[CONSUME:\s*(.*?)\]\]", ai_text):
                f_name = match.group(1).strip()
                res = self.notebook_widgets["Inventory"].consume_food(f_name, self.player.day, self.player.time)
                self.story_tab.print_text(res, sender="System")

            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
            if roll_match and recursion_depth < 2:
                skill = roll_match.group(1).strip()
                result = self.perform_skill_check(skill)
                clean_prev = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", ai_text).strip()
                follow_up = f"{prompt}\nGM: {clean_prev}\n[System: Player rolled {result} for {skill}.]"
                self.query_ai(follow_up, user_text, recursion_depth + 1)
            else:
                logging.info(f"AI text: {ai_text}")
                clean_pattern = re.compile(r"\[\[[A-Z_]+:.*?\]\]", re.DOTALL)
                final_text = clean_pattern.sub("", ai_text)
                final_text = re.sub(r'\n{3,}', '\n\n', final_text)
                final_text = final_text.strip()
                
                if final_text:
                    self.story_tab.print_text(final_text, sender="GM")
                    text_to_save = final_text
                    trim_markers = ["Possible Actions:", "Suggested Actions:", "### Actions", "What would you like to do?", "What do you do?", "What do you do now?"]
                    for marker in trim_markers:
                        if marker in text_to_save:
                            text_to_save = text_to_save.split(marker)[0].strip()
                            break

                    self.conversation_history += f"Player: {user_text}\nGM: {text_to_save}\n"

        except Exception as e:
            logging.error(f"AI Error: {e}")
        finally:
            self.after(0, lambda: self.story_tab.set_controls_state(True))

    def save_game(self):
        if not self.current_adventure_path or not self.game_loaded_successfully: 
            return

        for name, widget in self.notebook_widgets.items():
            if isinstance(widget, MarkdownEditorTab):
                try:
                    with open(widget.filename, "w", encoding="utf-8") as f:
                        f.write(widget.get_text())
                except Exception as e: logging.error(f"Error saving {name}: e")

        history_path = os.path.join(self.current_adventure_path, "savegame.json")
        history_list = [line for line in self.conversation_history.split("\n") if line.strip()]
        
        # [UPDATED] Get status from Player object
        status_data = self.player.get_status_dict()
        
        try:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump({
                    "Chat History": history_list, 
                    "Status": status_data, 
                    "is_creating": self.is_creating, 
                    "karmic_streak": self.player.karmic_streak 
                }, f, indent=4)
            logging.info(f"Game saved to {self.current_adventure_path}")
        except Exception as e:
            logging.error(f"Save failed for {self.current_adventure_path}: {e}")
            with open("LAST_SAVE_FAILED.txt", "w") as f:
                logging.error(f"Save failed: {e}")

    def on_close(self):
        self.save_game()
        self.destroy()

if __name__ == "__main__":
    app = GameApp()
    app.mainloop()