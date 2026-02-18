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

# Import Config and UI
from config import GEMINI_API_KEY, MODEL, SAVES_DIR, DEFAULT_RULES, SOUNDS_DIR, BASE_SOUNDS_DIR, VALID_SOUND_FILE_NAMES, APP_NAME
from ui import MainMenu, InventoryTab, SkillsTab, MarkdownEditorTab, StoryTab, ProcessingTab
from ui.recipes_tab import RecipesTab

# --- Configuration ---
load_dotenv()
client = genai.Client(api_key=GEMINI_API_KEY)

# Configure logging to write to a file; currently not working how I am intending it to.
log_file_path = os.path.join(SAVES_DIR, f"error_log.txt")
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%m/%d/%Y at %I:%M:S %p',
    filemode='w' # 'a' means Append mode (add to end of file), 'w' would overwrite each time
)

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
        self.sound_manager = SoundManager(SOUNDS_DIR)
        self.creation_summary_path = os.path.join(SAVES_DIR, "creation_summary.txt")
        ctk.set_appearance_mode("Dark")
        # Use the helper to find the icon inside the EXE
        icon_path = resource_path("game_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                logging.error(f"Icon error: {e}")

        self.current_adventure_path = None
        self.conversation_history = ""
        self.karmic_streak = 0
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
                
            elif tab_name == "Recipes":
                rec = RecipesTab(frame)
                rec.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = rec
            
            else:
                editor = MarkdownEditorTab(frame, default_text=f"{tab_name}\n")
                editor.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = editor
                

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def update_logger(self, save_name=None):
        """
        Switches logging to the specific save folder, or back to global if None.
        """
        # 1. Determine the new path
        if save_name:
            # Path: saves/MySave/MySave_error_log.txt
            save_dir = os.path.join(SAVES_DIR, save_name)
            # Ensure folder exists (just in case)
            if not os.path.exists(save_dir):
                return
            new_log_path = os.path.join(save_dir, f"{save_name}_error_log.txt")
        else:
            # Path: saves/error_log.txt (Global Fallback)
            new_log_path = os.path.join(SAVES_DIR, "generic_text_adventure_error_log.txt")

        # 2. Get the Root Logger
        logger = logging.getLogger()

        # 3. Remove existing FileHandlers (Close the old file)
        # We iterate over a copy [:] so we can remove items while looping
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                handler.close() # Release the file lock on the previous log
                logger.removeHandler(handler)

        # 4. Add the New Handler
        try:
            # Create new file handler
            file_handler = logging.FileHandler(new_log_path, mode='w', encoding='utf-8')
            
            # Apply the same format we used in basicConfig
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            
            # Attach it
            logger.addHandler(file_handler)
            
            logging.info(f"Logger switched to: {new_log_path}")
        except Exception as e:
            print(f"Failed to switch logger: {e}")
        
    def clean_quotes(self, text):
        """Replaces smart quotes (unicode) with standard ASCII quotes."""
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
        cur = self.story_tab.get_status_data()
        gt = add_hours(cur.get("day", "Day 1"), cur.get("time", "12:00 AM"), hours)

        turn = cur.get("turn", "1")
        location = cur.get("location", "Unknown")
        nutrition = int(cur.get("nutrition", 100))
        stamina = int(cur.get("stamina", 100))

        self.after(0, lambda: self.story_tab.update_status(
            turn, location, gt.as_day_string(), gt.as_time_string(),
            nutrition=nutrition, stamina=stamina
        ))

        
    def return_to_menu(self):
        """Saves game and goes back to main menu."""
        self.save_game()
        self.current_adventure_path = None
        self.is_creating = False
        self.update_logger(None)
        
        # Hide Game Tabs
        self.tab_view.grid_forget()
        self.title("AI RPG Adventure")
        
        # Show Main Menu
        self.main_menu.refresh_list()
        self.main_menu.grid(row=0, column=0, sticky="nsew")

    def load_adventure(self, save_name):
        self.game_loaded_successfully = False
        self.current_adventure_path = os.path.join(SAVES_DIR, save_name)
        self.current_sounds_path = os.path.join(SOUNDS_DIR, save_name)
        self.story_tab.clear_chat()
        self.update_logger(save_name)
        
        # Migrate legacy inventory format (old list items -> dict items)
        self._migrate_inventory_legacy_format()
        
        # UI Switch
        self.main_menu.grid_forget()
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.title(f"{save_name}")

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
                logging.error(f"Error loading tab {name}: {e}")

        # Load History & Status
        history_path = os.path.join(self.current_adventure_path, "savegame.json")
        if os.path.exists(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.is_creating = bool(data.get("is_creating", False))
                    self.karmic_streak = data.get("karmic_streak", 0)
                    hist = data.get("Chat History", [])
                    self.conversation_history = "\n".join(hist) if isinstance(hist, list) else hist
                    
                    # Update StoryTab Status
                    status = data.get("Status", {})
                    if status:
                        self.story_tab.update_status(
                            status.get("turn", "1"),
                            status.get("location", "Unknown"),
                            status.get("day", "1"),
                            status.get("time", "Start"),
                            status.get("nutrition", 100),
                            status.get("stamina", 100)
                        )
                
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
                    recent = self.conversation_history[-2000:]
                    # We grab the text from Inventory, World, Character, etc. NOW, 
                    # because accessing these widgets inside the thread later might crash Tkinter.
                    context_data = ""
                    for name, widget in self.notebook_widgets.items():
                        # Skip unnecessessary tabs such as inventory, skills, and processing, and only pass in relevant context for the purposes of a recap, e.g. the last bit of the conversation history.
                        if name != "Story" and name != "Inventory" and name != "Skills" and name != "Processing": 
                            if hasattr(widget, 'get_text'):
                                context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"
                    curr_stat = self.story_tab.get_status_data()
                    context_data += f"\n[STATUS]\nLocation: {curr_stat['location']}\nDay: {curr_stat['day']}\nTime: {curr_stat['time']}\n"
                    threading.Thread(target=self.generate_recap, args=(recent,context_data), daemon=True).start()
            except Exception as e:
                logging.error(f"Error loading history: {e}")
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
        if os.path.exists(self.creation_summary_path):
            try:
                os.remove(self.creation_summary_path)
            except Exception as e:
                logging.error(f"Error clearing creation summary: {e}")
        prompt = "System: Begin the Step 1 of the Character Creation process."
        
        try:
            # We send this with the CREATION_RULES as system instruction
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
    
        # --- Legacy Migration Helpers ---

    def _migrate_inventory_legacy_format(self):
        """
        Converts old inventory item lists:
          [Name, Desc, Amount, Value]
        into the new dict format:
          {"name":..., "desc":..., "amount":..., "value":...}
        """
        if not self.current_adventure_path:
            return

        inv_path = os.path.join(self.current_adventure_path, "inventory.json")
        if not os.path.exists(inv_path):
            return

        try:
            with open(inv_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.error(f"Json load error: {e}")
            return

        if not isinstance(data, dict):
            return

        changed = False
        for cat, items in list(data.items()):
            if not isinstance(items, list):
                continue

            new_items = []
            for item in items:
                if isinstance(item, dict):
                    # Already new format
                    new_items.append(item)
                elif isinstance(item, list):
                    # Legacy format
                    name = item[0] if len(item) > 0 else "Unknown"
                    desc = item[1] if len(item) > 1 else "No desc"
                    amt  = item[2] if len(item) > 2 else "1"
                    val  = item[3] if len(item) > 3 else "0"
                    new_items.append({"name": name, "desc": desc, "amount": str(amt), "value": str(val)})
                    changed = True
                else:
                    # Skip broken entries
                    changed = True

            data[cat] = new_items

        if changed:
            try:
                with open(inv_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                logging.error(f"Inventory loading error: {e}")
                pass

    # --- Stat Helpers ---

    def _apply_modify_stat(self, stat_name: str, raw_value: str):
        """
        Supports:
          [[MODIFY_STAT: Stamina | -10]]  (delta)
          [[MODIFY_STAT: Nutrition | +5]] (delta)
          [[MODIFY_STAT: Stamina | 80]]   (sets absolute if no + or -)
          [[MODIFY_STAT: Nutrition | SET 60]] (sets absolute)
        Clamps 0..100.
        """
        stat = (stat_name).strip().lower() or "UNKNOWN"
        raw = (raw_value).strip() or "UNKNOWN"
        logging.info(f"Stat: {stat}, Raw: {raw}")

        if stat not in ("stamina", "nutrition"):
           logging.error(f"System: Unknown stat '{stat}'.")

        cur = self.story_tab.get_status_data()
        
        nutrition = int(cur.get("nutrition", 100))
        stamina = int(cur.get("stamina", 100))

        # Parse set vs delta
        raw_upper = raw.upper()
        try:
            if raw_upper.startswith("SET "):
                if stat == "stamina":
                    stamina = int(raw.split(None, 1)[1].strip())
                else:
                    nutrition = int(raw.split(None, 1)[1].strip())
            else:
                # plain number => set
                
                if stat == "stamina":
                    logging.info(f"\nAttempting to add {raw} to stamina...")
                    logging.info(f"\nOld stamina value: {stamina}")
                    stamina += int(raw)
                    logging.info(f"\nNew stamina value: {stamina}")
                else:
                    logging.info(f"\nAttempting to add {raw} to nutrition...")
                    logging.info(f"\nOld nutrition value: {nutrition}")
                    nutrition += int(raw)
                    logging.info(f"\nNew nutrition value: {nutrition}")
                
        except Exception:
            logging.error(f"System: Bad MODIFY_STAT value '{raw_value}'.")

        # Preserve current time/location/turn/day; only change the stat
        turn = cur.get("turn", "1")
        location = cur.get("location", "Unknown")
        day = cur.get("day", "Day 1")
        time = cur.get("time", "Morning")
        self.after(0, lambda: self.story_tab.update_status(turn, location, day, time, nutrition=nutrition, stamina=stamina))


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
        if self.is_creating:
            # During creation, we prioritize the Summary over the raw history.
            # We reduce raw history to 1500 chars to save space for the summary.
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
            skill_entry = {"Name": clean_name, "Level": 1, "XP": 0, "Threshold": 3}
            data.append(skill_entry)
            self.story_tab.print_text(f"Learned new skill: {clean_name}!", sender="System")
            
        # 1. Roll the base die
        die_roll = random.randint(1, 20)
        karmic_streak_triggered = False

        # 2. Check for intervention
        # If we have had 3 or more bad rolls recently, force a better roll
        if self.karmic_streak <= -3:
            # Reroll, but ensure it's at least a 10
            new_roll = random.randint(10, 20)
            if new_roll > die_roll:
                die_roll = new_roll
                karmic_streak_triggered = True

        # If we have had 6 or more high rolls recently, nudge it down (optional, but fair)
        elif self.karmic_streak >= 6:
            new_roll = random.randint(1, 12)
            if new_roll < die_roll:
                die_roll = new_roll
                karmic_streak_triggered = True
                
        # 3. Update the Streak for next time
        if karmic_streak_triggered:
            self.karmic_streak = 0
        else:
            if die_roll < 8:
                self.karmic_streak -= 1
            elif die_roll > 13:
                self.karmic_streak += 1
            else: pass # Do not adjust the streak if the result is "normal" (e.g. between 8 and 13)
            
        # XP Logic
        skill_entry["XP"] += 1
        leveled_up = False
        if skill_entry["XP"] >= skill_entry["Threshold"]:
            skill_entry["Level"] += 1
            skill_entry["XP"] = 0
            skill_entry["Threshold"] += 2
            leveled_up = True
            
        skills_tab.save_data(data)
        bonus_from_nutrition = self.story_tab.get_status_data().get("nutrition", 100)
        bonus_from_stamina = self.story_tab.get_status_data().get("stamina", 100)
        if bonus_from_nutrition >= 85:
            bonus_from_nutrition = 1
        elif bonus_from_nutrition >= 61 and bonus_from_nutrition <= 84:
            bonus_from_nutrition = 0
        elif bonus_from_nutrition >= 40 and bonus_from_nutrition <= 60:
            bonus_from_nutrition = -1
        else:
            bonus_from_nutrition = -3
            
        if bonus_from_stamina >= 85:
            bonus_from_stamina = 1
        elif bonus_from_stamina >= 61 and bonus_from_stamina <= 84:
            bonus_from_stamina = 0
        elif bonus_from_stamina >= 40 and bonus_from_stamina <= 60:
            bonus_from_stamina = -1
        else:
            bonus_from_stamina = -3
            
        skill_bonus = skill_entry["Level"]
        total = die_roll + skill_bonus + bonus_from_nutrition + bonus_from_stamina
        bonus_from_skill_message = f"{skill_bonus} (from Skill level)"
        bonus_from_nutrition_message = f" +{bonus_from_nutrition} (bonus from high nutrition)" if bonus_from_nutrition > 0 else f"{bonus_from_nutrition} (penalty from low nutrition)" if bonus_from_nutrition < 0 else ""
        bonus_from_stamina_message = f" +{bonus_from_stamina} (bonus from high stamina)" if bonus_from_stamina > 0 else f"{bonus_from_stamina} (penalty from low stamina)" if bonus_from_stamina < 0 else ""
        
        msg = f"Rolling {clean_name}: {die_roll} + ({bonus_from_skill_message}{bonus_from_nutrition_message}{bonus_from_stamina_message}) = {total}"
        
        if leveled_up:
            msg += (
                f"\n**LEVEL UP!** {clean_name} is now Level {skill_entry['Level']}! "
                f"{skill_entry['Threshold']} XP required until level {skill_entry['Level'] + 1}."
            )
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
                    system_instruction=current_rules
                )
            )
            ai_text = response.text or ""
            if not ai_text: raise ValueError("Empty response")
            else: ai_text = self.clean_quotes(ai_text)
            
            # --- PARSE CREATION TAGS (Only if creating) ---
            if self.is_creating:
                summary_match = re.search(r"\[\[STEP_SUMMARY:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if summary_match:
                    new_summary = summary_match.group(1).strip()
                    try:
                        # Append to the file
                        with open(self.creation_summary_path, "a", encoding="utf-8") as f:
                            f.write(f"- {new_summary}\n")
                    except Exception as e:
                        logging.error(f"Error writing creation summary: {e}")
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
                    if os.path.exists(self.creation_summary_path):
                        try:
                            os.remove(self.creation_summary_path)
                        except Exception as e:
                            logging.error(f"Error deleting creation summary: {e}")
                    self.save_game()
                    # Clean the tag out of the text so player doesn't see it
                    ai_text = ai_text.replace("[[START_GAME]]", "")
                    self.conversation_history += response.text or ""
                    #return
                    
            
            # 1. Add/Remove Items
            for match in re.finditer(r"\[\[ADD:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].autonomous_add(match.group(1))
                self.story_tab.print_text(res, sender="GM")

            for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text):
                res = self.notebook_widgets["Inventory"].autonomous_remove(match.group(1))
                self.story_tab.print_text(res, sender="GM")
                
            # 1.5 Modify Items
            for match in re.finditer(r"\[\[MODIFY_ITEM:\s*(.*?)\]\]", ai_text, re.DOTALL):
                res = self.notebook_widgets["Inventory"].modify_item(match.group(1).strip())
                if res:
                    self.story_tab.print_text(res, sender="System")

            # 1.6 Modify Stats
            for match in re.finditer(r"\[\[MODIFY_STAT:\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text):
                stat_name = match.group(1).strip()
                stat_val = match.group(2).strip()
                self._apply_modify_stat(stat_name, stat_val)
                #if res:
                    #self.story_tab.print_text(res, sender="System")
                    #self.conversation_history += f"\n{res}\n"
                    
            music_match = re.search(r"\[\[MUSIC:\s*(.*?)\]\]", ai_text)
            if music_match:
                track = music_match.group(1).strip()
                #self.sound_manager.play_music(track, True)
                # Run on main thread to be safe, though mixer is usually thread-safe
                self.after(0, lambda: self.sound_manager.play_music(track))

            # 2. SFX Tags: [[SOUND: filename]]
            for match in re.finditer(r"\[\[SOUND:\s*(.*?)\]\]", ai_text):
                sfx = match.group(1).strip()
                #self.sound_manager.play_sfx(sfx)
                self.after(0, lambda s=sfx: self.sound_manager.play_sfx(s))

            
            # 2. Status Update
            status_match = re.search(r"\[\[STATUS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text)
            if status_match:
                turn = status_match.group(1).strip()
                location = status_match.group(2).strip()
                day = status_match.group(3).strip()
                time = status_match.group(4).strip()
                cur_stats = self.story_tab.get_status_data()
                nut = cur_stats.get("nutrition", 100)
                sta = cur_stats.get("stamina", 100)
                self.after(0, lambda: self.story_tab.update_status(turn, location, day, time, nutrition=nut, stamina=sta))

                
                # Check Processing Tab (Only if NOT creating)
                if not self.is_creating and "Processing" in self.notebook_widgets:
                    finished_items = self.notebook_widgets["Processing"].check_active_tasks(day, time)
                    if finished_items:
                        sys_msg = f"System: Process completed - {', '.join(finished_items)}"
                        self.story_tab.print_text(sys_msg, sender="System")
                        self.conversation_history += f"\n{sys_msg}\n"
                        
            # Tag: [[RECIPE: Name | Ingredients | Value]]
            # Regex captures the content inside the tag
            for match in re.finditer(r"\[\[RECIPE:\s*(.*?)\]\]", ai_text):
                tag_content = match.group(1)
                # Call the method in the new tab
                res = self.notebook_widgets["Recipes"].add_recipe_from_tag(tag_content)
                self.story_tab.print_text(res, sender="System")
                        
            # Tag: [[START_PROCESS: Name | Description | Time_Slots | Yield]]
            # We need the CURRENT status to calculate the target time.
            current_status = self.story_tab.get_status_data() # Gets current UI values
            
            for match in re.finditer(r"\[\[START_PROCESS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\]\]", ai_text):
                p_name = match.group(1).strip()
                p_desc = match.group(2).strip()
                p_slots = match.group(3).strip()
                p_yield = match.group(4).strip()
                
                # Pass current Day/Time to calculate target
                res = self.notebook_widgets["Processing"].add_timed_process(
                    p_name,
                    p_desc,
                    p_slots,
                    current_status["day"],
                    current_status["time"],
                    p_yield
                )
                self.story_tab.print_text(res, sender="System")
                
            # --- REMOVE PROCESS TAG (Same as before) ---
            for match in re.finditer(r"\[\[REMOVE_PROCESS:\s*(.*?)\]\]", ai_text):
                p_name = match.group(1).strip()
                res = self.notebook_widgets["Processing"].remove_process(p_name)
                if res: self.story_tab.print_text(res, sender="System")
                
            # Tag: [[START_PROJECT: Name | Desc | Total_Slots | Yield]]
            # This creates a "Manual" task that requires work.
            # Tag: [[START_PROJECT: Name | Desc | Work_Amount | SkillName | Expected_Yield]]
            for match in re.finditer(
                r"\[\[START_PROJECT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]",
                ai_text
            ):
                p_name = match.group(1).strip()
                p_desc = match.group(2).strip()
                work_required = match.group(3).strip()     # Work Amount
                skill_name = match.group(4).strip()        # SkillName (this was missing)
                p_yield = match.group(5).strip()           # Expected_Yield

                lvl = self._get_skill_level(skill_name)

                # ProcessingTab.add_project(name, desc, work_required, skill_name, skill_level_at_start, expected_yield)
                res = self.notebook_widgets["Processing"].add_project(
                    p_name,
                    p_desc,
                    work_required,
                    skill_name,
                    lvl,
                    p_yield
                )
                if res:
                    self.story_tab.print_text(res, sender="System")

            # Tag: [[WORK: Name | Slots]]
            # This applies progress to a manual task.
            # Tag: [[WORK: ProjectName | Hours_Worked]]
            for match in re.finditer(r"\[\[WORK:\s*(.*?)\s*\|\s*([\d.]+)\]\]", ai_text):
                project_name = match.group(1).strip()
                hours_worked = float(match.group(2).strip())

                # Look up what skill this project uses, then get the player's level in that skill
                req_skill = self.notebook_widgets["Processing"].get_required_skill(project_name) or ""
                lvl = self._get_skill_level(req_skill) if req_skill else 0

                # Apply progress + advance time
                res = self.notebook_widgets["Processing"].apply_work_hours(project_name, hours_worked, lvl)
                self._advance_time_hours(hours_worked)

                # After time advances, check if any passive processes finished
                status_now = self.story_tab.get_status_data()
                completed = self.notebook_widgets["Processing"].check_active_tasks(status_now["day"], status_now["time"])
                if completed:
                    sys_msg = f"System: Process completed - {', '.join(completed)}"
                    self.story_tab.print_text(sys_msg, sender="System")
                    self.conversation_history += f"\n{sys_msg}\n"

                if res:
                    self.story_tab.print_text(res, sender="System")

                
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
                follow_up = f"{prompt}\nGM: {clean_prev}\n[[System: Player rolled {result} for {skill}. Please determine if, based on the context of the story and the Player's Skill set and Inventory, if that is a success or a failure, and narrate the result accordingly.]]"
                self.query_ai(follow_up, user_text, recursion_depth + 1)
            else:
                logging.info(f"AI text: {ai_text}")
                clean_pattern = re.compile(r"\[\[[A-Z_]+:.*?\]\]", re.DOTALL)
                final_text = clean_pattern.sub("", ai_text)
                #final_text = re.sub(r"\[\[.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
                # Replace 3 or more newlines with just 2 (Standard paragraph break)
                final_text = re.sub(r'\n{3,}', '\n\n', final_text)
                # Strip leading/trailing whitespace completely
                final_text = final_text.strip()
                # Only print if there is actually text left
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

    def generate_recap(self, history, context_data):
        self.after(0, lambda: self.story_tab.set_controls_state(False, "Recapping..."))
        try:
            # We feed the AI the full Context (Inventory, World, Status) PLUS the (possibly empty) History.
            prompt = f"Context Data:\n{context_data}\n\nRecent Chat History:\n{history}\n\nMANDATORY TASK: Summarize the current situation in a single paragraph based on the Context and Status provided above. \n\nMANDATORY TASK: Look through the names in this list: {VALID_SOUND_FILE_NAMES}, and choose one that sounds like it would be a good fit for the Player's current situation, and then output a '[[MUSIC: file_name_placeholder.mp3]]' tag, replacing file_name_placeholder.mp3 with one of the strings from that List. \n\nMANDATORY TASK: Do NOT use the [[STATUS]] tag. \n\nMANDATORY TASK: End by asking 'What do you do now?'"
            resp = client.models.generate_content(
                model=MODEL, 
                contents=prompt, 
                config=types.GenerateContentConfig(system_instruction=self.load_rules())
            )
            ai_text = resp.text or ""
            if ai_text: ai_text = self.clean_quotes(ai_text)
            music_match = re.search(r"\[\[MUSIC:\s*(.*?)\]\]", ai_text)
            if music_match:
                track = music_match.group(1).strip()
                #self.sound_manager.play_music(track, True)
                # Run on main thread to be safe, though mixer is usually thread-safe
                self.after(0, lambda: self.sound_manager.play_music(track))

            # 2. SFX Tags: [[SOUND: filename]]
            for match in re.finditer(r"\[\[SOUND:\s*(.*?)\]\]", ai_text):
                sfx = match.group(1).strip()
                #self.sound_manager.play_sfx(sfx)
                self.after(0, lambda s=sfx: self.sound_manager.play_sfx(s))
            
            # 1. Remove Tags (The AI might try to reprint the status, we strip that)
            clean_text = re.sub(r"\[\[.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
            
            # 2. Fix Whitespace
            clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
            
            if clean_text:
                self.story_tab.print_text(f"RECAP: {clean_text}", sender="GM")
        except Exception as e:
            logging.error(f"Recap Error: {e}")
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
                except Exception as e: logging.error(f"Error saving {name}: e")

        # Save History & Status
        history_path = os.path.join(self.current_adventure_path, "savegame.json")
        history_list = [line for line in self.conversation_history.split("\n") if line.strip()]
        
        # Get Status from StoryTab
        status_data = self.story_tab.get_status_data()
        
        try:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump({"Chat History": history_list, "Status": status_data, "is_creating": self.is_creating, "karmic_streak": self.karmic_streak}, f, indent=4)
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