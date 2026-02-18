from google import genai
from google.genai import types
import threading
import re
import os
import logging
from config import GEMINI_API_KEY, MODEL, CREATION_RULES

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

    def start_creation_wizard(self):
        """Sends the initial system prompt to start the interview."""
        # Ensure summary path is clean
        if os.path.exists(self.app.creation_summary_path):
            try:
                os.remove(self.app.creation_summary_path)
            except Exception as e:
                logging.error(f"Error clearing creation summary: {e}")
        
        prompt = "System: Begin the Step 1 of the Character Creation process."
        
        try:
            resp = self.client.models.generate_content(
                model=MODEL, 
                contents=prompt, 
                config=types.GenerateContentConfig(system_instruction=CREATION_RULES)
            )
            raw_text = self.clean_quotes(resp.text)
            clean_text = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", raw_text, flags=re.DOTALL).strip()
            
            self.app.story_tab.print_text(clean_text, sender="GM")
            self.app.conversation_history += f"GM: {clean_text}\n"
        except Exception as e:
            logging.error(f"Creation Error: {e}")

    def handle_player_action(self, user_text):
        """Constructs the context and prompt, then threads the AI query."""
        self.app.story_tab.set_controls_state(False, "GM is thinking...")
        self.app.story_tab.print_text(user_text, sender="Player")

        # 1. Gather Context from Tabs
        context_data = ""
        for name, widget in self.app.notebook_widgets.items():
            if name != "Story": 
                if hasattr(widget, 'get_text'):
                    context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"
        
        # 2. Gather Status
        next_turn = self.app.player.turn + 1
        status_context = (
            f"\n[CURRENT STATUS]\n"
            f"Location: {self.app.player.location}\n"
            f"Day: {self.app.player.day}\n"
            f"Time: {self.app.player.time}\n"
            f"Current Turn: {self.app.player.turn}\n"
            f"UPCOMING TURN: {next_turn} (You MUST use this number in the [[STATUS]] tag)"
        )
        context_data += status_context

        # 3. Build Prompt
        if self.app.is_creating:
            recent_history = self.app.conversation_history[-1500:] if len(self.app.conversation_history) > 1500 else self.app.conversation_history
            creation_memory = ""
            if os.path.exists(self.app.creation_summary_path):
                try:
                    with open(self.app.creation_summary_path, "r", encoding="utf-8") as f:
                        summaries = f.read()
                    creation_memory = f"\n[CREATION_HISTORY_SUMMARY (DO NOT IGNORE)]:\n{summaries}\n"
                except Exception as e:
                    logging.error(f"Error reading creation summary: {e}")
            full_prompt = f"{context_data}\n{creation_memory}\nRecent Chat:\n{recent_history}\nPlayer: {user_text}\nGM:"
        else:
            recent_history = self.app.conversation_history[-3000:] if len(self.app.conversation_history) > 3000 else self.app.conversation_history
            full_prompt = f"{context_data}\nHistory:\n{recent_history}\nPlayer: {user_text}\nGM:"

        # 4. Thread the request
        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()

    def query_ai(self, prompt, user_text, recursion_depth=0):
        """Sends the prompt to Gemini and processes all resulting tags."""
        if self.app.is_creating:
            current_rules = CREATION_RULES
        else:
            current_rules = self.app.load_rules()
            
        try:
            response = self.client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=current_rules,
                    temperature=0.7
                )
            )
            ai_text = self.clean_quotes(response.text or "")
            if not ai_text: raise ValueError("Empty response")
            
            # --- TAG PARSING ---
            
            # Creation Specific Tags
            if self.app.is_creating:
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

                if "[[START_GAME]]" in ai_text:
                    self.app.is_creating = False
                    self.app.story_tab.print_text("\n[System: Creation Complete. Saving Data...]\n", sender="System")
                    if os.path.exists(self.app.creation_summary_path):
                        try:
                            os.remove(self.app.creation_summary_path)
                        except Exception as e:
                            logging.error(f"Error deleting creation summary: {e}")
                    self.app.save_game()
                    ai_text = ai_text.replace("[[START_GAME]]", "")
                    clean_creation_text = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
                    self.app.conversation_history += f"GM: {clean_creation_text}\n"

            # Standard Game Tags
            for match in re.finditer(r"\[\[ADD:\s*(.*?)\]\]", ai_text):
                res = self.app.notebook_widgets["Inventory"].autonomous_add(match.group(1))
                self.app.story_tab.print_text(res, sender="GM")

            for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text):
                res = self.app.notebook_widgets["Inventory"].autonomous_remove(match.group(1))
                self.app.story_tab.print_text(res, sender="GM")
                
            for match in re.finditer(r"\[\[MODIFY_ITEM:\s*(.*?)\]\]", ai_text, re.DOTALL):
                res = self.app.notebook_widgets["Inventory"].modify_item(match.group(1).strip())
                if res: self.app.story_tab.print_text(res, sender="System")

            for match in re.finditer(r"\[\[MODIFY_STAT:\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text):
                stat_name = match.group(1).strip()
                stat_val = match.group(2).strip()
                self.app.player.modify_stat(stat_name, stat_val)
                self.app._sync_player_state_to_ui()
                    
            music_match = re.search(r"\[\[MUSIC:\s*(.*?)\]\]", ai_text)
            if music_match:
                track = music_match.group(1).strip()
                self.app.after(0, lambda: self.app.sound_manager.play_music(track))

            for match in re.finditer(r"\[\[SOUND:\s*(.*?)\]\]", ai_text):
                sfx = match.group(1).strip()
                self.app.after(0, lambda s=sfx: self.app.sound_manager.play_sfx(s))

            status_match = re.search(r"\[\[STATUS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text)
            if status_match:
                self.app.player.update_world_state(
                    turn=status_match.group(1).strip(),
                    location=status_match.group(2).strip(),
                    day=status_match.group(3).strip(),
                    time=status_match.group(4).strip()
                )
                self.app._sync_player_state_to_ui()

                if not self.app.is_creating and "Processing" in self.app.notebook_widgets:
                    finished_items = self.app.notebook_widgets["Processing"].check_active_tasks(self.app.player.day, self.app.player.time)
                    if finished_items:
                        sys_msg = f"System: Process completed - {', '.join(finished_items)}"
                        self.app.story_tab.print_text(sys_msg, sender="System")
                        self.app.conversation_history += f"\n{sys_msg}\n"
                        
            for match in re.finditer(r"\[\[RECIPE:\s*(.*?)\]\]", ai_text):
                res = self.app.notebook_widgets["Recipes"].add_recipe_from_tag(match.group(1))
                self.app.story_tab.print_text(res, sender="System")
                        
            for match in re.finditer(r"\[\[START_PROCESS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\]\]", ai_text):
                p_name = match.group(1).strip()
                p_desc = match.group(2).strip()
                p_slots = match.group(3).strip()
                p_yield = match.group(4).strip()
                res = self.app.notebook_widgets["Processing"].add_timed_process(p_name, p_desc, p_slots, self.app.player.day, self.app.player.time, p_yield)
                self.app.story_tab.print_text(res, sender="System")
                
            for match in re.finditer(r"\[\[REMOVE_PROCESS:\s*(.*?)\]\]", ai_text):
                res = self.app.notebook_widgets["Processing"].remove_process(match.group(1).strip())
                if res: self.app.story_tab.print_text(res, sender="System")
                
            for match in re.finditer(r"\[\[START_PROJECT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text):
                p_name = match.group(1).strip()
                p_desc = match.group(2).strip()
                work_required = match.group(3).strip()
                skill_name = match.group(4).strip()
                p_yield = match.group(5).strip()
                lvl = self.app._get_skill_level(skill_name)
                res = self.app.notebook_widgets["Processing"].add_project(p_name, p_desc, work_required, skill_name, lvl, p_yield)
                if res: self.app.story_tab.print_text(res, sender="System")

            for match in re.finditer(r"\[\[WORK:\s*(.*?)\s*\|\s*([\d.]+)\]\]", ai_text):
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
                
            for match in re.finditer(r"\[\[ADD_FOOD:\s*(.*?)\]\]", ai_text):
                res = self.app.notebook_widgets["Inventory"].add_food(match.group(1))
                self.app.story_tab.print_text(res, sender="GM")
                
            for match in re.finditer(r"\[\[CONSUME:\s*(.*?)\]\]", ai_text):
                f_name = match.group(1).strip()
                res = self.app.notebook_widgets["Inventory"].consume_food(f_name, self.app.player.day, self.app.player.time)
                self.app.story_tab.print_text(res, sender="System")

            # Recursive Logic (Rolls)
            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
            if roll_match and recursion_depth < 2:
                skill = roll_match.group(1).strip()
                # Call back to main app for mechanic logic
                result = self.app.perform_skill_check(skill)
                clean_prev = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", ai_text).strip()
                follow_up = f"{prompt}\nGM: {clean_prev}\n[System: Player rolled {result} for {skill}.]"
                
                # Recursive call
                self.query_ai(follow_up, user_text, recursion_depth + 1)
            else:
                logging.info(f"AI text: {ai_text}")
                # Clean tags for final display
                clean_pattern = re.compile(r"\[\[[A-Z_]+:.*?\]\]", re.DOTALL)
                final_text = clean_pattern.sub("", ai_text)
                final_text = re.sub(r'\n{3,}', '\n\n', final_text)
                final_text = final_text.strip()
                
                if final_text:
                    self.app.story_tab.print_text(final_text, sender="GM")
                    
                    text_to_save = final_text
                    # Trim potential actions from history
                    trim_markers = ["Possible Actions:", "Suggested Actions:", "### Actions", "What would you like to do?", "What do you do?", "What do you do now?"]
                    for marker in trim_markers:
                        if marker in text_to_save:
                            text_to_save = text_to_save.split(marker)[0].strip()
                            break

                    self.app.conversation_history += f"Player: {user_text}\nGM: {text_to_save}\n"

        except Exception as e:
            logging.error(f"AI Error: {e}")
        finally:
            self.app.after(0, lambda: self.app.story_tab.set_controls_state(True))