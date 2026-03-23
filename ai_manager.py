from google import genai
from google.genai import types
import threading
import re
import os
import logging
import random
from config import GEMINI_API_KEY, MODEL

class AIManager:
    def __init__(self, app):
        self.app = app
        try:
            self.client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            logging.error(f"Failed to initialize Gemini Client: {e}")

    def clean_quotes(self, text):
        """Replaces smart quotes (unicode) with standard ASCII quotes."""
        if not text: return ""
        return text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')

    def start_new_game_from_wizard(self, data):
        """Compiles the wizard data into a one-shot prompt to generate the game start."""
        if os.path.exists(self.app.creation_summary_path):
            try:
                os.remove(self.app.creation_summary_path)
            except Exception as e:
                logging.error(f"Error clearing creation summary: {e}")
                
        self.app.player.update_world_state(1, data['starting_location'] or "Unknown", 1, "7:00 A.M.")
        
        # Format skills, handling blank descriptions
        skills_text = ""
        for s in data['skills']:
            name = s['name'] or 'AI, please invent a name for this skill'
            desc = s['desc'] or 'AI, please invent a description for this skill'
            skills_text += f"- Level {s['level']}: {name} ({desc})\n"
            
        # If the player left EVERY skill blank:
        if not skills_text:
            skills_text = "(No skills specified. AI, please invent 16 starting skills fitting the world following this exact level distribution: one Lvl 5, two Lvl 4, three Lvl 3, four Lvl 2, six Lvl 1.)"
            
        if data['currencies']:
            currencies_text = ", ".join([f"{c['name']} (Worth {c['value']} base units)" for c in data['currencies']])
        else:
            currencies_text = "Not specified (AI, you MUST invent a localized currency system. Output [[DEFINE_CURRENCY: Name | Value]] for each denomination, starting with a base unit of 1.)"
        
        stats_text = ""
        for st in data['stats']:
            if st['enabled']:
                stats_text += f"- {st['name']}: Starts at {st['value']} (Rules: {st['desc']})\n"
        if not stats_text: stats_text = "(No tracked stats specified)"
        
        # Format focus
        focus_text = ', '.join(data['focus']) if data['focus'] else "Not specified (AI, pick a balanced focus)"

        # The prompt is now safely un-indented!
        prompt = f"""
System: Initialize a new RPG adventure using the following parameters.
CRITICAL INSTRUCTION: If any parameter says "Not specified", you must creatively invent a fitting, unique value for it based on the rest of the context.
To guarantee absolute randomness, a creative entropy seed has been generated: {random.randint(1000000, 9999999)}. Use this seed to completely randomize the names, geography, and species you invent. 
DO NOT use common AI fantasy names (e.g., Elara, Kael, Lyra, Aric, Seraphina, Orion, Sylas). Create genuinely culturally distinct and unusual names.

World Setting: {data['world']['setting'] or 'Not specified (Generate a highly unique, unpredictable world.)'}
Genre/Tone: {data['world']['genre'] or 'Not specified (Pick a random, uncommon genre.)'}
Tech Level: {data['world']['tech'] or 'Not specified'}
Species/Races: {data['world']['species'] or 'Not specified (Invent at least 3 bizarre, unique original species)'}
Game Focus: {focus_text}

World Economy (Currencies):
{currencies_text}

Tracked Player Stats:
{stats_text}

Character Bio:
Name: {data['character']['name'] or 'Not specified (Invent a unique name)'}
Age: {data['character']['age'] or 'Not specified'}
Gender/Pronouns: {data['character']['gender'] or 'Not specified'} / {data['character']['pronouns'] or 'Not specified'}
Orientation: {data['character']['orientation'] or 'Not specified'}
Background: {data['character']['background'] or 'Not specified'}

Starting Skills:
{skills_text}

Starting Location: {data['starting_location'] or 'Not specified (Invent a vivid, unusual starting location)'}
Final Comments/Rules: {data['final_comments'] or 'None'}

INSTRUCTIONS:
Output the following SPECIAL TAGS to set up the game files based on this data.
[[WORLD_INFO: Write a summary of the game focus, world setting, tone, currency, and tech level here. Include anything the Player specified.]]
[[CHARACTER_INFO: Write the full character biography, appearance, and details here.]]
[[SKILL: Name | Level]] (Output one for EACH skill. If none were provided, output the 16 invented skills here).
[[ADD_FOOD: Type | Name | Desc | Amount | Value (MUST be an integer representing the number of smallest base currency units that this is worth) | Meals | SpoilDay | SpoilTime]] (Add logical starting food for the Player Character. Repeat this tag for EACH FOOD ITEM that the Player will start out with.)
[[ADD: Type | Name | Description | Amount | Value (MUST be an integer representing the number of smallest base currency units that this is worth)]] (Add logical starting equipment/wealth. Repeat this tag for EACH NON-FOOD and NON-CURRENCY item that the Player will start out with.)
[[DEFINE_CURRENCY: Name | Value]] (If no currencies were provided, output this for EACH invented denomination. Example: [[DEFINE_CURRENCY: Iron Bit | 1]]). THIS TAG MUST COME BEFORE CHANGE_CURRENCY.
[[CHANGE_CURRENCY: X]] (Give the player a logical amount of starting base currency for their background)
[[STATUS: 1 | {data['starting_location'] or 'Unknown (Invent a starting location name)'} | 1 | 7:00 A.M.]]
[[MUSIC: FILENAME_PLACEHOLDER.mp3]]
[[START_GAME]]

After outputting the tags, summarize the first starting turn, describe the surroundings vividly, and finish by asking "What do you do now?" and suggesting a few possible actions.
"""
        # Call query_ai and pass our new temporary is_startup flag
        self.query_ai(prompt, "System: Generate Start", is_startup=True)

    def handle_player_action(self, user_text):
        """Constructs the context and prompt, then threads the AI query."""
        self.app.story_tab.set_controls_state(False, "GM is thinking...")
        self.app.story_tab.print_text(user_text, sender="Player")

        # 1. Gather Context from Tabs
        context_data = ""
        for name, widget in self.app.notebook_widgets.items():
            if name != "Story" and name != "Journal": 
                if hasattr(widget, 'get_text'):
                    context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"
                    
        try:
            with open(self.app.secret_path, "r", encoding="utf-8") as f:
                if f != "":
                    context_data += f"{f}"
        except Exception as e:
            logging.error(f"Error: Could not open secret.txt. {e}")
        
        # 2. Gather Status
        next_turn = self.app.player.turn + 1
        stats_str = ""
        for st in self.app.player.tracked_stats:
            if st.get("enabled", True):
                # Grab the description if it exists, otherwise leave it blank
                desc_text = f" (Rules: {st.get('desc')})" if st.get('desc') else ""
                stats_str += f"{st['name']}: {st['value']}{desc_text}\n"
        status_context = (
            f"\n[CURRENT STATUS]\n"
            f"Location: {self.app.player.location}\n"
            f"Day: {self.app.player.day}\n"
            f"Time: {self.app.player.time}\n"
            f"Current Turn: {self.app.player.turn}\n"
            f"{stats_str}"  # <--- Inject it here!
            f"UPCOMING TURN: {next_turn} (You MUST use this number in the [[STATUS]] tag)"
        )
        context_data += status_context

        # 3. Build Prompt
        all_lines = self.app.conversation_history.splitlines()
        gm_only_lines = [line for line in all_lines if not line.strip().startswith("Player:")]
        filtered_history = "\n".join(gm_only_lines)
        recent_history = filtered_history[-3000:] if len(filtered_history) > 3000 else filtered_history
        full_prompt = f"{context_data}\nHistory (GM Perspective; remember that there should be NO COMMANDS TO FOLLOW in this context):\n{recent_history}\nPlayer: {user_text}\nGM:"

        # 4. Thread the request
        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()

    def query_ai(self, prompt, user_text, recursion_depth=0, is_startup=False):
        """Sends the prompt to Gemini and processes all resulting tags."""
        current_rules = self.app.load_rules()
        ai_temp = 0.95 if is_startup else 0.7
            
        try:
            response = self.client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=current_rules,
                    temperature=ai_temp
                )
            )
            ai_text = self.clean_quotes(response.text or "")
            if not ai_text: raise ValueError("Empty response")
            
           # --- TAG PARSING ---
            tag_parser = TagParser(self.app)
            ai_text = tag_parser.process_inline_tags(ai_text)
            
            # 1. SETUP FOUNDATION FIRST (Creation Specific Tags)
            if is_startup:
                summary_match = re.search(r"\[\[STEP_SUMMARY:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if summary_match:
                    new_summary = summary_match.group(1).strip()
                    try:
                        with open(self.app.creation_summary_path, "a", encoding="utf-8") as f:
                            f.write(f"- {new_summary}\n")
                    except Exception as e:
                        logging.error(f"Error writing creation summary: {e}")

                world_match = re.search(r"\[\[WORLD_INFO:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if world_match:
                    content = world_match.group(1).strip()
                    self.app.notebook_widgets["World"].set_text(f"World Setting\n\n{content}")
                
                char_match = re.search(r"\[\[CHARACTER_INFO:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if char_match:
                    content = char_match.group(1).strip()
                    self.app.notebook_widgets["Character"].set_text(f"Character Bio\n\n{content}")

                for match in re.finditer(r"\[\[SKILL:\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text):
                    s_name = match.group(1).strip()
                    s_lvl = int(match.group(2))
                    self.app.notebook_widgets["Skills"].force_learn_skill(s_name, s_lvl)

                # Parse Invented Currencies BEFORE standard tags run!
                invented_currencies = []
                for match in re.finditer(r"\[\[DEFINE_CURRENCY:\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text, re.DOTALL):
                    c_name = match.group(1).strip()
                    c_val = int(match.group(2))
                    invented_currencies.append({"name": c_name, "value": c_val})
                
                if invented_currencies:
                    self.app.player.world_currencies = invented_currencies

            # 2. PROCESS STANDARD TAGS (Now it has the currencies loaded to do the math!)
            tag_parser.process_standard_tags(ai_text, is_startup=is_startup)    

            # 3. FINALIZE STARTUP & SAVE
            if is_startup and "[[START_GAME]]" in ai_text:
                self.app.is_creating = False
                self.app.story_tab.print_text("\n[System: Creation Complete. Saving Data...]\n", sender="System")
                
                if os.path.exists(self.app.creation_summary_path):
                    try:
                        os.remove(self.app.creation_summary_path)
                    except Exception as e:
                        logging.error(f"Error deleting creation summary: {e}")
                        
                self.app.save_game()
                
                self.app.after(0, lambda: self.app._sync_player_state_to_ui())
                if "Inventory" in self.app.notebook_widgets:
                    self.app.after(0, lambda: self.app.notebook_widgets["Inventory"].refresh_display())
                
                ai_text = ai_text.replace("[[START_GAME]]", "")
                clean_creation_text = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
                self.app.conversation_history += f"GM: {clean_creation_text}\n"

            # 4. RECURSIVE LOGIC (Rolls)
            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)

            # 3. Recursive Logic (Rolls)
            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)

            # Recursive Logic (Rolls)
            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
            if roll_match and recursion_depth < 2:
                skill = roll_match.group(1).strip()
                # Call back to main app for mechanic logic
                result = self.app.perform_skill_check(skill)
                clean_prev = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", ai_text).strip()
                follow_up = f"{prompt}\nGM: {clean_prev}\n[System: Player rolled {result} for {skill}. Please determine what degree of success/failure that is, then narate the outcome.]"
                
                # Recursive call
                self.query_ai(follow_up, user_text, recursion_depth + 1)
            else:
                logging.info(f"AI text: {ai_text}")
                # Clean tags for final display
                clean_pattern = re.compile(r"\[\[[A-Z_]+:.*?\]\]", re.DOTALL)
                final_text = clean_pattern.sub("", ai_text)
                final_text = re.sub(r'\n{3,}', '\n\n', final_text)
                final_text = final_text.strip()
                final_text = "\n" + final_text
                
                if final_text and len(final_text) > 8:
                    self.app.story_tab.print_text(final_text, sender="GM")
                    
                    text_to_save = final_text
                    # Trim potential actions from history
                    trim_markers = ["Possible Actions:", "Suggested Actions:", "### Actions", "What would you like to do?", "What do you do?", "What do you do now?"]
                    for marker in trim_markers:
                        if marker in text_to_save:
                            text_to_save = text_to_save.split(marker)[0].strip()
                            break

                    self.app.conversation_history += f"\nPlayer: {user_text}\nGM: {text_to_save}\n"
                    # --- Auto-save after each completed turn (Qt + CTk) ---
                    try:
                        self.app.save_game()
                    except Exception as e:
                        logging.error(f"Auto-save failed: {e}")

        except Exception as e:
            logging.error(f"AI Error: {e}")
        finally:
            self.app.after(0, lambda: self.app.story_tab.set_controls_state(True))
            
class TagParser:
    def __init__(self, app):
        self.app = app

    def process_standard_tags(self, ai_text, is_startup=False):
        """Processes typical gameplay tags and returns the cleaned text."""
        # Inventory
        for match in re.finditer(r"\[\[ADD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Inventory"].autonomous_add(match.group(1))
            self.app.story_tab.print_text(res, sender="GM")

        for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Inventory"].autonomous_remove(match.group(1))
            self.app.story_tab.print_text(res, sender="GM")
            
        for match in re.finditer(r"\[\[MODIFY_STAT:\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text):
            stat_name, stat_val = match.group(1).strip(), match.group(2).strip()
            self.app.player.modify_stat(stat_name, stat_val)
            self.app._sync_player_state_to_ui()
            
        music_match = re.search(r"\[\[MUSIC:\s*(.*?)\]\]", ai_text, re.DOTALL)
        if music_match:
            track = music_match.group(1).strip()
            self.app.after(0, lambda: self.app.sound_manager.play_music(track))

        for match in re.finditer(r"\[\[SOUND:\s*(.*?)\]\]", ai_text, re.DOTALL):
            sfx = match.group(1).strip()
            self.app.after(0, lambda s=sfx: self.app.sound_manager.play_sfx(s))

        status_match = re.search(r"\[\[STATUS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL)
        if status_match:
            self.app.player.update_world_state(
                turn=status_match.group(1).strip(),
                location=status_match.group(2).strip(),
                day=status_match.group(3).strip(),
                time=status_match.group(4).strip()
            )
            self.app._sync_player_state_to_ui()

            if not is_startup and "Processing" in self.app.notebook_widgets:
                finished_items = self.app.notebook_widgets["Processing"].check_active_tasks(self.app.player.day, self.app.player.time)
                if finished_items:
                    sys_msg = f"System: Process completed - {', '.join(finished_items)}"
                    self.app.story_tab.print_text(sys_msg, sender="System")
                    self.app.conversation_history += f"\n{sys_msg}\n"
                    
        for match in re.finditer(r"\[\[RECIPE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Recipes"].add_recipe_from_tag(match.group(1))
            self.app.story_tab.print_text(res, sender="System")
                    
        for match in re.finditer(r"\[\[START_PROCESS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            p_name = match.group(1).strip()
            p_desc = match.group(2).strip()
            p_slots = match.group(3).strip()
            p_yield = match.group(4).strip()
            res = self.app.notebook_widgets["Processing"].add_timed_process(p_name, p_desc, p_slots, self.app.player.day, self.app.player.time, p_yield)
            self.app.story_tab.print_text(res, sender="System")
            
        for match in re.finditer(r"\[\[REMOVE_PROCESS:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Processing"].remove_process(match.group(1).strip())
            if res: self.app.story_tab.print_text(res, sender="System")
            
        for match in re.finditer(r"\[\[START_PROJECT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            p_name = match.group(1).strip()
            p_desc = match.group(2).strip()
            work_required = match.group(3).strip()
            skill_name = match.group(4).strip()
            p_yield = match.group(5).strip()
            lvl = self.app._get_skill_level(skill_name)
            res = self.app.notebook_widgets["Processing"].add_project(p_name, p_desc, work_required, skill_name, lvl, p_yield)
            if res: self.app.story_tab.print_text(res, sender="System")

        for match in re.finditer(r"\[\[WORK:\s*(.*?)\s*\|\s*([\d.]+)\]\]", ai_text, re.DOTALL):
            project_name = match.group(1).strip()
            hours_worked = float(match.group(2).strip())
            req_skill = self.app.notebook_widgets["Processing"].get_required_skill(project_name) or ""
            lvl = self.app._get_skill_level(req_skill) if req_skill else 0
            res = self.app.notebook_widgets["Processing"].apply_work_hours(project_name, hours_worked, lvl)
            
            # Update time locally via Main App helper
            self.app._advance_time_hours(hours_worked)

            completed = self.app.notebook_widgets["Processing"].check_active_tasks(self.app.player.day, self.app.player.time)
            if completed:
                sys_msg = f"System: Process completed - {', '.join(completed)}"
                self.app.story_tab.print_text(sys_msg, sender="System")
                self.app.conversation_history += f"\n{sys_msg}\n"

            if res: self.app.story_tab.print_text(res, sender="System")
            
        for match in re.finditer(r"\[\[ADD_FOOD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Inventory"].add_food(match.group(1))
            self.app.story_tab.print_text(res, sender="GM")
            
        for match in re.finditer(r"\[\[CONSUME:\s*(.*?)\]\]", ai_text, re.DOTALL):
            f_name = match.group(1).strip()
            res = self.app.notebook_widgets["Inventory"].consume_food(f_name, self.app.player.day, self.app.player.time)
            for match in re.finditer(r"\[\[MODIFY_STAT:\s*(.*?)\s*\|\s*(.*?)\]\]", res, re.DOTALL):
                stat_name = match.group(1).strip()
                stat_val = match.group(2).strip()
                self.app.player.modify_stat(stat_name, stat_val)
                self.app._sync_player_state_to_ui()
                res = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", res).strip()
            self.app.story_tab.print_text(res, sender="System")
            
        for match in re.finditer(r"\[\[SECRET:\s*(.*?)\]\]", ai_text, re.DOTALL):
            try:
                if not self.app.secret_path:
                    with open(self.app.secret_path, "w", encoding="utf-8") as f:
                        f.write("")
                else:
                    with open(self.app.secret_path, "a", encoding="utf-8") as f:
                        #f.write(match.group(1).strip())
                        f.write(f"{f}\n")
                        import subprocess
                        subprocess.check_call(["attrib", "+H",self.app.secret_path])
                        logging.info(f"Success! Wrote secret .txt file with path {self.app.secret_path}")
            except Exception as e:
                    logging.error(f"Error writing secret: {e}")
                    
        for match in re.finditer(r"\[\[UPDATE_WORLD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            try:
                if self.app.world_path:
                    with open(self.app.world_path, "a", encoding="utf-8") as f:
                        f.write(f"{f}\n")
                else:
                    with open(self.app.world_path, "w", encoding="utf-8") as f:
                        f.write("")
            except Exception as e:
                logging.error(f"Error: Couldn't update world: {e}")
                
        for match in re.finditer(r"\[\[CHANGE_CURRENCY:\s*(-?\d+)\]\]", ai_text, re.DOTALL):
            amount_str = match.group(1).strip()
            try:
                amount = int(amount_str)
                success, msg = self.app.player.change_currency(amount)
                self.app.story_tab.print_text(msg, sender="System")
                self.app.after(0, lambda: self.app._sync_player_state_to_ui())
                if "Inventory" in self.app.notebook_widgets:
                    self.app.after(0, lambda: self.app.notebook_widgets["Inventory"].refresh_display())

            except ValueError:
                self.app.story_tab.print_text(f"System Error: Invalid currency amount '{amount_str}'", sender="System")
                
    def process_inline_tags(self, ai_text):
        """Processes tags that need to be replaced with actual text before displaying."""
        
        def replace_currency(match):
            try:
                # Extract the integer from the regex match
                amount = int(match.group(1).strip())
                # Ask the player class to format it nicely!
                return self.app.player.get_formatted_currency(amount)
            except ValueError:
                # If the AI hallucinates a non-integer, just leave the tag as-is
                return match.group(0) 
                
        # Find all instances of [[DISPLAY_CURRENCY: X]] and swap them
        modified_text = re.sub(r"\[\[DISPLAY_CURRENCY:\s*(-?\d+)\]\]", replace_currency, ai_text)
        
        return modified_text