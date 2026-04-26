from google import genai
from google.genai import types
import threading, re, os, logging, csv
from config import GEMINI_API_KEY, MODEL, VALID_SOUND_FILE_NAMES
from tabulate import tabulate
from rapidfuzz import process, fuzz

class AIManager:
    def __init__(self, app):
        self.app = app
        try:
            self.client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            logging.error(f"Failed to initialize Gemini Client: {e}")

    def clean_quotes(self, text):
        """Replaces smart quotes and unicode dashes with standard ASCII equivalents."""
        if not text: return ""
        
        return (text.replace("‘", "'")
                    .replace("’", "'")
                    .replace("“", '"')
                    .replace("”", '"')
                    .replace("—", "--")  # Replaces the Em Dash (\u2014) with a double-hyphen
                    .replace("–", "-"))  # Replaces the En Dash (\u2013) with a single-hyphen

    def start_new_game_from_wizard(self, data):
        """Unpacks the wizard data directly into the game state and generates the start prompt."""                
        
        # 1. Setup Base State directly
        self.app.player.location = data['starting_location'] or "Unknown"
        self.app.player.day = 1
        self.app.player.time = "7:00 A.M."
        self.app.player.turn = 0
        
        # 2. Inject Stats directly
        self.app.player.tracked_stats = []
        for stat in data['stats']:
            if stat['enabled']:
                self.app.player.tracked_stats.append({
                    "name": stat['name'],
                    "value": stat['value'],
                    "enabled": True,
                    "description": stat['description']
                })
                
        # 3. Inject Currencies directly
        self.app.player.world_currencies = []
        for c in data['currencies']:
            self.app.player.world_currencies.append({"name": c['name'], "value": c['value']})
            
        # 4. Process Skills for the AI Prompt (Do NOT inject them directly yet!)
        skills_prompt_text = ""
        for s in data['skills']:
            s_name = s['name'].strip() or "Unknown Skill Name"
            s_desc = s['desc'].strip() or "Unknown Skill Description"
            s_lvl = s['level']
            # We skip entirely empty skill slots
            if s_name == "Unknown Skill Name" and s_desc == "Unknown Skill Description" and s_lvl == 1:
                continue
            skills_prompt_text += f"- Name: {s_name} | Description: {s_desc} | Level: {s_lvl}\n"
            
        if not skills_prompt_text:
            skills_prompt_text = "No Skills provided."
        
        # 5. Set UI to a loading state while we wait for the AI to fill in the blanks
        self.app.notebook_widgets["World"].set_text("*(Generating World Profile...)*")
        self.app.notebook_widgets["Character"].set_text("*(Generating Character Biography...)*")

        # 6. Save initial state instantly so UI panels refresh
        self.app.save_game()
        self.app._sync_player_state_to_ui()
        
        # 7. Build the prompt
        valid_sounds_str = ", ".join(VALID_SOUND_FILE_NAMES) if VALID_SOUND_FILE_NAMES else "No music available."
        focus_text = ', '.join(data['focus']) if data['focus'] else "Balanced (Combat, Exploration, Trading/Economy, Social/Roleplay)"
        
        prompt = f"""
System: Initialize a new RPG adventure using the following parameters.
CRITICAL INSTRUCTION: If any parameter below starts with "Unknown" or "None provided", you must creatively invent a fitting value for it. DO NOT use common AI fantasy names. Keep any parameters that are already provided by the player EXACTLY as they are.

Provided World Information:
- Genre: {data['world']['genre'] or 'Unknown Genre'}
- Setting: {data['world']['setting'] or 'Unknown Setting'}
- Tech Level: {data['world']['tech'] or 'Unknown Tech Level'}
- Species: {data['world']['species'] or 'Unknown Species'}
- Game Focus: {focus_text}

Provided Character Information:
- Name: {data['character']['name'] or 'Unknown Character Name'}
- Age: {data['character']['age'] or 'Unknown Character Age'}
- Gender/Pronouns: {data['character']['gender'] or 'Unknown Character Gender'} / {data['character']['pronouns'] or 'Unknown Character Pronouns'}
- Orientation: {data['character']['orientation'] or 'Unknown Character Orientation'}
- Background: {data['character']['background'] or 'Unknown Character Background'}

Provided Starting Skills:
{skills_prompt_text}

Starting Location: {data['starting_location'] or 'Unknown Starting Location'}
Final Comments/Rules: {data['final_comments'] or 'N/A'}

INSTRUCTIONS:
Output the following tags to set up the starting gameplay state:
[[WORLD_PROFILE: 
### World Setting

**Genre:** (Filled value)

**Setting:** (Filled value)

**Technology Level:** (Filled value)

**Species:** (Filled value)

**Focus:** (Filled value)
]] (You must output this tag. Output the exact Markdown formatting shown inside this tag, replacing the "(Filled value)" text with creative and/or logical values based off of the \"Provided World Information\" section above, remembering to ONLY change the information if it is \"Unknown\".).

[[CHARACTER_PROFILE: 
### Character Biography

**Name:** (Filled value)

**Age:** (Filled value)

**Gender:** (Filled value)

**Orientation:** (Filled value)

**Background:** (Filled value)
]] (You must output this tag. Output the exact Markdown formatting shown inside this tag, replacing the "(Filled value)" text with creative and/or logical values based off of the \"Provided Character Information\" section above, remembering to ONLY change the information if it is \"Unknown\".).

[[SKILL: Name | Description | Level]] (Output this tag for EACH skill listed in the "Provided Starting Skills" section. If the Name or Description is "Unknown", creatively invent a fitting one based on the character's background. Keep the Level exactly as provided, remembering that the higher the level is for a Skill, the better the Player is at that Skill, so please reserve the higher level Skills for things that the Player Character may be good at, depending on their background.)
[[ADD: Type | Name | Description | Amount]] (Add logical starting equipment. Repeat this tag for each item that the Player will start out with.)
[[GIVE_COIN: X]] (Give the player a logical amount of starting base currency for their background. Repeat this tag if you are adding different types of coins.)
[[STATUS: {data['starting_location'] or 'Unknown'} | AUTO]]
[[MUSIC: FILENAME_PLACEHOLDER]] (You MUST output this tag to set the starting music. Replace FILENAME_PLACEHOLDER with exactly one of these options: {valid_sounds_str})

After outputting all tags, summarize the first starting turn, describe the surroundings vividly, and finish by asking "What do you do now?" and suggesting a few possible actions.
"""
        logging.info("Generating start now...")
        self.query_ai(prompt, "System: Generate Start", is_startup=True)

    def handle_player_action(self, user_text):
        """Constructs the context and prompt, then threads the AI query."""
        self.app.story_tab.set_controls_state(False, "GM is thinking...")
        user_text = "> " + user_text
        self.app.story_tab.print_text(user_text)

        # 1. Gather Context from Tabs
        context_data = ""
        for name, widget in self.app.notebook_widgets.items():
            if name not in ["Story", "Journal", "History"]:
                if hasattr(widget, 'get_text'):
                    context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"
                    
        try:
            if os.path.exists(self.app.secret_path):
                with open(self.app.secret_path, "r", encoding="utf-8") as f:
                    secret_content = f.read().strip()
                    if secret_content:
                        context_data += f"\n[SECRET]:\n{secret_content}\n"
        except Exception as e:
            logging.error(f"Error: Could not open secret.txt. {e}")
        
        # 2. Gather Status
        self.app.player.turn += 1
        stats_str = ""
        for stat in self.app.player.tracked_stats:
            if stat.get("enabled", True):
                # Grab the description if it exists, otherwise leave it blank
                desc_text = f" (Rules: {stat.get('description')})" if stat.get('description') else ""
                stats_str += f"{stat['name']}: {stat['value']}{desc_text}\n"
        status_context = (
            f"\n[CURRENT STATUS]\n"
            f"Player's current Location: {self.app.player.location}\n"
            f"Current in-game Day: {self.app.player.day}\n"
            f"Current in-game Time: {self.app.player.time}\n"
            f"Current in-game Turn: {self.app.player.turn}\n"
            f"Stats: {stats_str}"
        )
        context_data += status_context

        # 3. Build Prompt
        history_text = ""
        if "History" in self.app.notebook_widgets:
            history_text = self.app.notebook_widgets["History"].get_text().strip()
        recent_history = history_text[-6000:] if len(history_text) > 6000 else history_text
        full_prompt = f"\nPast Conversation History:\n{recent_history}\nUser's request: {user_text}\nPlease remember to consider the following in your response: {context_data}"

        # 4. Thread the request
        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()

    def query_ai(self, prompt, user_text, recursion_depth=0, is_startup=False):
        """Sends the prompt to Gemini and processes all resulting tags."""
        current_rules = self.app.load_rules()
            
        try:
            if is_startup:
                self.app.story_tab.set_controls_state(False, "GM is thinking...")
                
            response = self.client.models.generate_content(
                model=MODEL,
                config=types.GenerateContentConfig(
                    system_instruction=current_rules,
                    temperature=0.9
                ),
                contents=prompt
            )
            ai_text = self.clean_quotes(response.text or "")
            if not ai_text: raise ValueError("Empty response")
            # --- Save the completely raw text ---
            # We must store the raw text so we can pass it back to the AI during 
            # recursive recursive drafts (like skill rolls). If we pass the parsed 
            # history text, the AI will hallucinate UI elements into the narrative.
            raw_ai_text = ai_text
            
            # --- TAG PARSING ---
            tag_parser = TagParser(self.app)
            display_ai_text = tag_parser.process_inline_tags(ai_text, is_history=False)
            history_ai_text = tag_parser.process_inline_tags(ai_text, is_history=True)
            ai_text = display_ai_text
            
            if is_startup:
                self.app.story_tab.set_controls_state(True, "What do you do now?")

            # 1. RECURSIVE LOGIC (Rolls & Projects)
            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
            project_match = re.search(r"\[\[START_PROJECT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL)

            if roll_match and recursion_depth < 2:
                skill = roll_match.group(1).strip()
                result = self.app.perform_skill_check(skill)
                
                if "Skills" in self.app.notebook_widgets:
                    skills_tab = self.app.notebook_widgets["Skills"]
                    if hasattr(skills_tab, 'refresh_display'):
                        self.app.after(0, lambda: skills_tab.refresh_display())
                    elif hasattr(skills_tab, 'load_data'):
                        self.app.after(0, lambda: skills_tab.load_data())
                
                logging.info(f"[System: Player rolled {result} for {skill}]")
                
                draft_with_tags = raw_ai_text.strip()
                draft_with_tags = re.sub(r"\[\[ROLL:\s*.*?\]\]", "", draft_with_tags).strip()
                
                follow_up = (
                    f"{prompt}\nGM (Draft): {draft_with_tags}\n"
                    f"[System: Player rolled {result} for {skill}. Please rewrite your response to incorporate the success/failure of this roll, "
                    f"then narrate the outcome. Do NOT mention the die roll at all in the diegetic context. "
                    f"CRITICAL: The tags from your draft were NOT executed yet. You MUST output ALL necessary tags (like [[STATUS:]], [[REMOVE:]], [[ADD:]], etc.) again in this final response!]"
                )
                
                self.query_ai(follow_up, user_text, recursion_depth + 1)
                return 
            
            if project_match and recursion_depth < 2:
                project_name = project_match.group(1).strip()
                skill_name = project_match.group(4).strip()
                
                try:
                    work_required = float(project_match.group(3).strip())
                except ValueError:
                    work_required = 0.0
                    
                skill_level = self.app._get_skill_level(skill_name)
                speed_multiplier = 1.0 + (0.5 * skill_level)
                estimated_minutes = (work_required / speed_multiplier) if speed_multiplier > 0 else 0.0
                
                logging.info(f"[System: Calculated project estimate for '{project_name}' at {estimated_minutes:g} minutes]")
                
                draft_with_tags = raw_ai_text.strip()
                draft_with_tags = re.sub(r"\[\[START_PROJECT:\s*.*?\]\]", "", draft_with_tags, flags=re.DOTALL).strip()
                
                follow_up = (
                    f"{prompt}\nGM (Draft): {draft_with_tags}\n"
                    f"[System: The exact estimated player time to complete the project '{project_name}' is {estimated_minutes:g} minutes (based on their Level {skill_level} {skill_name} skill). "
                    f"Please rewrite your response to accurately reflect this time cost in your [[WORK:]] and [[STATUS:]] tags if the player works on it. "
                    f"CRITICAL: The tags from your draft were NOT executed yet. You MUST output ALL necessary tags again in this final response!]"
                )
                
                self.query_ai(follow_up, user_text, recursion_depth + 1)
                return

            # 2. PROCESS STANDARD TAGS
            tag_parser.process_standard_tags(ai_text, is_startup=is_startup)

            # 3. FINALIZE AND PRINT
            logging.info(f"AI text: {ai_text}")
            clean_pattern = re.compile(r"\[\[[A-Z_]+:.*?\]\]", re.DOTALL)
            
            final_display_text = clean_pattern.sub("", display_ai_text)
            final_display_text = re.sub(r'\n{3,}', '\n\n', final_display_text).strip()
            
            
            trim_markers = ["Possible Actions:", "Suggested Actions:", "### Actions", "What would you like to do?", "What do you do?", "What do you do now?"]
            
            for marker in trim_markers:
                if marker in final_display_text:
                    parts = final_display_text.split(marker, 1)
                    main_body = parts[0].strip()
                    options_string = parts[1].strip()
                    
                    # Convert inline hyphens or asterisks into proper markdown newlines
                    # This targets spaces followed by a dash/asterisk (e.g., " - " becomes "\n- ")
                    options_string = options_string.replace(" - ", "\n- ").replace(" * ", "\n* ")
                    
                    # Failsafe: Ensure the very first option has a space after the hyphen if the AI forgot
                    if options_string.startswith("-") and not options_string.startswith("- "):
                        options_string = "- " + options_string[1:].lstrip()
                    elif options_string.startswith("*") and not options_string.startswith("* "):
                        options_string = "* " + options_string[1:].lstrip()
                    
                    # Reconstruct the string with bolding for the question and proper list spacing
                    final_display_text = f"{main_body}\n\n**{marker}**\n\n{options_string.strip()}"
                    break
            final_history_text = clean_pattern.sub("", history_ai_text)
            final_history_text = re.sub(r'\n{3,}', '\n\n', final_history_text).strip()
            if final_display_text and len(final_display_text) > 8:
                self.app.story_tab.print_text(final_display_text, sender="")
                text_to_save = final_history_text
            else: text_to_save = ""
                
                
            if "History" in self.app.notebook_widgets:
                hist_panel = self.app.notebook_widgets["History"]
                current_hist = hist_panel.get_text()
                    
                # If this is the first turn, we don't want to log "**Player:** System: Generate Start"
                if is_startup:
                    new_exchange = f"**System: Start of Game**\n\n**GM:** {text_to_save.strip()}\n\n// NEW EXCHANGE\n\n"
                else:
                    new_exchange = f"{user_text}\n\n{text_to_save.strip()}\n\n// NEW EXCHANGE\n\n"
                    
                self.app.after(0, lambda ch=current_hist, ne=new_exchange: hist_panel.set_text(ch + ne))
                
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
        
        # --- Initial World and Character Profile Generation ---
        for match in re.finditer(r"\[\[WORLD_PROFILE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            new_world_md = match.group(1).strip()
            if "World" in self.app.notebook_widgets:
                world_panel = self.app.notebook_widgets["World"]
                world_panel.set_text(new_world_md)
                # Instantly write the properly formatted Markdown file to disk
                self.app.after(0, lambda p=world_panel: p.save_now())

        for match in re.finditer(r"\[\[CHARACTER_PROFILE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            new_char_md = match.group(1).strip()
            if "Character" in self.app.notebook_widgets:
                char_panel = self.app.notebook_widgets["Character"]
                char_panel.set_text(new_char_md)
                # Instantly write the properly formatted Markdown file to disk
                self.app.after(0, lambda p=char_panel: p.save_now())
        
        # Inventory
        for match in re.finditer(r"\[\[ADD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Inventory"].autonomous_add(match.group(1))
            #self.app.story_tab.print_text(res, sender="GM")

        for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Inventory"].autonomous_remove(match.group(1))
            #self.app.story_tab.print_text(res, sender="GM")
            
        for match in re.finditer(r"\[\[MODIFY_ITEM:\s*(.*?)\]\]", ai_text, re.DOTALL):
            if "Inventory" in self.app.notebook_widgets:
                self.app.notebook_widgets["Inventory"].modify_item(match.group(1))
            
        for match in re.finditer(r"\[\[MODIFY_STAT:\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text):
            stat_name, stat_val = match.group(1).strip(), match.group(2).strip()
            self.app.player.modify_stat(stat_name, stat_val)
            self.app._sync_player_state_to_ui()
            
        for match in re.finditer(r"\[\[SKILL:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text, re.DOTALL):
            s_name = match.group(1).strip()
            s_desc = match.group(2).strip() if match.group(2).strip() else "No description provided."
            s_lvl = int(match.group(3))
            self.app.notebook_widgets["Skills"].force_learn_skill(s_name, s_desc, s_lvl)
            
        music_match = re.search(r"\[\[MUSIC:\s*(.*?)\]\]", ai_text, re.DOTALL)
        if music_match:
            track = music_match.group(1).strip()
            self.app.after(0, lambda: self.app.sound_manager.play_music(track))

        for match in re.finditer(r"\[\[SOUND:\s*(.*?)\]\]", ai_text, re.DOTALL):
            sfx = match.group(1).strip()
            self.app.after(0, lambda s=sfx: self.app.sound_manager.play_sfx(s))
            
        # Add quests
        for match in re.finditer(r"\[\[QUEST:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            q_name = match.group(1).strip()
            q_giver = match.group(2).strip()
            q_desc = match.group(3).strip()
            q_turn_in = match.group(4).strip()
            q_reward = match.group(5).strip()
            
            if "Quests" in self.app.notebook_widgets:
                self.app.notebook_widgets["Quests"].add_quest(q_name, q_giver, q_desc, q_turn_in, q_reward)
                logging.info(f"Added quest: {q_name}")
                
        # Complete/Remove quests
        for match in re.finditer(r"\[\[COMPLETE_QUEST:\s*(.*?)\]\]", ai_text, re.DOTALL):
            q_name = match.group(1).strip()
            
            if "Quests" in self.app.notebook_widgets:
                self.app.notebook_widgets["Quests"].complete_quest(q_name)
                logging.info(f"Completed quest: {q_name}")

        status_match = re.search(r"\[\[STATUS:\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL)
        if status_match:
            loc = status_match.group(1).strip()
            mins_str = status_match.group(2).strip()
            
            try:
                mins_to_add = 0 if mins_str.upper() == "AUTO" else int(float(mins_str))
            except ValueError:
                logging.error(f"AI passed invalid minutes: {mins_str}")
                mins_to_add = 0
                
            self.app.player.update_world_state(
                location=loc,
                minutes_to_add=mins_to_add
            )
                    
            self.app._sync_player_state_to_ui()
                    
        for match in re.finditer(r"\[\[RECIPE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Recipes"].add_recipe_from_tag(match.group(1))
            if res: logging.info(res)
                    
        for match in re.finditer(r"\[\[START_PROCESS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            p_name = match.group(1).strip()
            p_desc = match.group(2).strip()
            
            try:
                p_slots = int(float(match.group(3).strip()))
            except ValueError:
                logging.error(f"AI passed invalid time for process: {match.group(3)}")
                p_slots = 60 # Fallback to 1 hour
                
            p_yield = match.group(4).strip()
            res = self.app.notebook_widgets["Processing"].add_timed_process(p_name, p_desc, p_slots, self.app.player.day, self.app.player.time, p_yield)
            if res: logging.info(res)
            
        for match in re.finditer(r"\[\[REMOVE_PROCESS:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Processing"].remove_process(match.group(1).strip())
            if res: logging.info(res)
            
        for match in re.finditer(r"\[\[START_PROJECT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            p_name = match.group(1).strip()
            p_desc = match.group(2).strip()
            work_required = match.group(3).strip()
            skill_name = match.group(4).strip()
            p_yield = match.group(5).strip()
            lvl = self.app._get_skill_level(skill_name)
            res = self.app.notebook_widgets["Processing"].add_project(p_name, p_desc, work_required, skill_name, lvl, p_yield)
            if res: logging.info(res)

        for match in re.finditer(r"\[\[WORK:\s*(.*?)\s*\|\s*([\d.]+)\]\]", ai_text, re.DOTALL):
            project_name = match.group(1).strip()
            # Changed variable name to reflect minutes
            minutes_worked = float(match.group(2).strip())
            req_skill = self.app.notebook_widgets["Processing"].get_required_skill(project_name) or ""
            lvl = self.app._get_skill_level(req_skill) if req_skill else 0
            
            # Call the newly renamed method
            res = self.app.notebook_widgets["Processing"].apply_work_minutes(project_name, minutes_worked, lvl)
            if res: logging.info(res)
            
        for match in re.finditer(r"\[\[SECRET:\s*(.*?)\]\]", ai_text, re.DOTALL):
            try:
                # --- FIXED: Extract the actual text generated by the AI ---
                new_secret = match.group(1).strip()
                
                if not self.app.secret_path:
                    with open(self.app.secret_path, "w", encoding="utf-8") as f:
                        f.write("")
                else:
                    with open(self.app.secret_path, "a", encoding="utf-8") as f:
                        f.write(f"\n{new_secret}\n")
                        import subprocess
                        subprocess.check_call(["attrib", "+H", self.app.secret_path])
                        logging.info(f"Success! Wrote secret .txt file with path {self.app.secret_path}")
            except Exception as e:
                    logging.error(f"Error writing secret: {e}")
                    
        for match in re.finditer(r"\[\[UPDATE_WORLD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            # 1. Extract the actual text generated by the AI
            new_world_lore = match.group(1).strip()
            
            try:
                if self.app.world_path:
                    # 2. Append the new lore to the Markdown file
                    with open(self.app.world_path, "a", encoding="utf-8") as f:
                        f.write(f"\n{new_world_lore}\n")
                        
                    # 3. Update the UI panel immediately so the player can see the new lore without reloading the save!
                    if "World" in self.app.notebook_widgets:
                        current_text = self.app.notebook_widgets["World"].get_text()
                        # Append the new text to whatever is already in the World tab
                        self.app.notebook_widgets["World"].set_text(f"{current_text}\n\n{new_world_lore}")
                else:
                    logging.error("Error: self.app.world_path is None.")
            except Exception as e:
                logging.error(f"Error: Couldn't update world: {e}")
                
        for match in re.finditer(r"\[\[DEFINE_CURRENCY:\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text, re.DOTALL):
            c_name = match.group(1).strip()
            c_val = int(match.group(2))
            
            # Check if currency already exists before appending to prevent double-parsing
            existing = next((c for c in self.app.player.world_currencies if c.get("name", "").lower() == c_name.lower()), None)
            if not existing:
                self.app.player.world_currencies.append({"name": c_name, "value": c_val})

                
        for match in re.finditer(r"\[\[CHANGE_CURRENCY:\s*(-?\d+)\]\]", ai_text, re.DOTALL):
            amount_str = match.group(1).strip()
            try:
                amount = int(amount_str)
                success, msg = self.app.player.change_currency(amount)
                #self.app.story_tab.print_text(msg, sender="System")
                self.app.after(0, lambda: self.app._sync_player_state_to_ui())
                if "Inventory" in self.app.notebook_widgets:
                    self.app.after(0, lambda: self.app.notebook_widgets["Inventory"].refresh_display())

            except ValueError:
                logging.error(f"System Error: Invalid currency amount: {amount_str}")
                
        for match in re.finditer(r"\[\[GIVE_COIN:\s*(.*?)\s*\|\s*(-?\d+)\]\]", ai_text, re.DOTALL):
            ai_coin_name = match.group(1).strip()
            try:
                coin_amount = int(match.group(2).strip())
                coin_value = 1 # Default fallback to base units
                
                if self.app.player.world_currencies:
                    # 1. Create a simple list of valid currency names to check against
                    valid_names = [cur.get("name", "") for cur in self.app.player.world_currencies]
                    
                    # 2. Use RapidFuzz to find the closest match
                    # extractOne returns a tuple: (best_match_string, score_out_of_100, original_index)
                    best_match = process.extractOne(ai_coin_name, valid_names, scorer=fuzz.WRatio)
                    
                    # 3. Check if the match is "close enough" (70% is usually a good threshold)
                    if best_match and best_match[1] >= 70:
                        matched_index = best_match[2]
                        matched_coin_dict = self.app.player.world_currencies[matched_index]
                        coin_value = int(matched_coin_dict.get("value", 1))
                        logging.info(f"Fuzzy matched AI coin '{ai_coin_name}' to '{best_match[0]}' with score {best_match[1]}")
                    else:
                        logging.warning(f"Could not fuzzy match AI coin '{ai_coin_name}'. Defaulting to base unit 1.")
                        
                # 4. Let Python do the math safely
                total_base_change = coin_amount * coin_value
                success, msg = self.app.player.change_currency(total_base_change)
                
                # 5. Sync the UI
                self.app.after(0, lambda: self.app._sync_player_state_to_ui())
                if "Inventory" in self.app.notebook_widgets:
                    self.app.after(0, lambda: self.app.notebook_widgets["Inventory"].refresh_display())
                    
            except ValueError:
                logging.error(f"System Error: Invalid coin amount for GIVE_COIN tag.")
                
        # Allow for multi-line and negative numbers just in case
        for match in re.finditer(r"\[\[DEFINE_STAT:\s*(.*?)\s*\|\s*(-?\d+)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            s_name = match.group(1).strip()
            s_val = int(match.group(2))
            s_desc = match.group(3).strip()
            
            # Check if stat already exists before appending to prevent double-parsing
            existing = next((stat for stat in self.app.player.tracked_stats if stat.get("name", "").lower() == s_name.lower()), None)
            if not existing:
                self.app.player.tracked_stats.append({"name": s_name, "value": s_val, "enabled": True, "description": s_desc})
                
    def process_inline_tags(self, ai_text, is_history=False):
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
            
        def replace_merchant(match):
            raw_data = match.group(1).strip()
            if not raw_data:
                return ""
            
            try:
                # csv.reader safely splits by commas while ignoring commas inside quotes
                parsed_list = list(csv.reader([raw_data], skipinitialspace=True))[0]
            except Exception as e:
                logging.error(f"Failed to parse MERCHANT tag: {e}")
                return "(Merchant inventory is unreadable)"

            table_data = []
            history_items = []
            for item in parsed_list:
                # Clean up any lingering quotes and split by the pipe character
                item = item.strip().strip('\'"')
                parts = [p.strip() for p in item.split('|')]
                
                if len(parts) >= 3:
                    name = parts[0]
                    description = parts[1]
                    price_raw = parts[2]
                    
                    # Convert the raw base unit integer into nicely formatted currency
                    try:
                        price_val = int(price_raw)
                        formatted_price = self.app.player.get_formatted_currency(price_val)
                    except ValueError:
                        formatted_price = price_raw # Fallback if AI hallucinates text instead of an int
                        
                    table_data.append([name, description, formatted_price])
                    
                    # --- Include the description in the history summary! ---
                    # We wrap the name in single quotes and use a hyphen to cleanly separate the description.
                    history_items.append(f"'{name}' - {description} ({formatted_price})") 
                else:
                    # Fallback if the AI messes up the pipe formatting
                    table_data.append(parts + [""] * (3 - len(parts)))
                    if len(parts) > 0:
                        history_items.append(f"'{parts[0]}'")
            
            if not table_data:
                return "\n*(This merchant has nothing for sale.)*\n"
                
            if is_history:
                items_str = ", ".join(history_items)
                return f"\n*(OOG: A merchant table is listed detailing the following items: {items_str}.)*\n"
            else:
                # Create the 3xY rounded grid!
                headers = ["Item Name", "Description", "Price"]
                grid = tabulate(table_data, headers=headers, tablefmt="rounded_grid")
                formatted_html = (
                f"<pre style=\"font-family: Consolas, 'Courier New', monospace; "
                f"line-height: 1.0; padding: 6px;\">\n\n{grid}\n</pre>\n\n"
                )
                # Pad with newlines so it renders nicely in the text box
                return f"\n{formatted_html}\n"
                
        # Find all instances of [[DISPLAY_CURRENCY: X]] and swap them
        modified_text = re.sub(r"\[\[DISPLAY_CURRENCY:\s*(-?\d+)\]\]", replace_currency, ai_text)
        modified_text = re.sub(r"\[\[MERCHANT:\s*(.*?)\]\]", replace_merchant, modified_text, flags=re.DOTALL)
        
        return modified_text