from google import genai
from google.genai import types
import threading
import re
import os
import logging
import random
from config import GEMINI_API_KEY, MODEL
from tabulate import tabulate
import csv
from rapidfuzz import process, fuzz

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
        
        main_types = [
            "Cyberpunk", "Steampunk", "Modern Urban", "Futuristic Sci-Fi", 
            "Ancient Historical", "Classic Low Fantasy", "Classic High Fantasy", 
            "Eldritch Horror", "Post-Apocalyptic", "Biopunk", "Space Opera",
            "Clockwork Fantasy", "Dieselpunk", "Stone Age", "Mythological", "Iron Age",
            "Bronze Age", "Western"
        ]
        
        subtypes = [
            "Scavenger", "Survival", "Ice Age", "Noir", "Wasteland", 
            "Hollow Earth", "Floating Island", "Flesh-tech", "Feudal",
            "Slice-of-Life", "Underground", "Oceanic/Nautical", "Nomadic",
            "Dungeon Crawler", "Political Intrigue", "Vintage", "Adventure", "Anti-Hero"
        ]
        
        random_vibes = [
            "grimdark", "cozy", "paranoid", "whimsical", "brutal", 
            "melancholic", "hyper-capitalist", "mystical", "surreal", "gritty"
        ]
        
        tech_levels = [
            "Stone Age / Primitive", "Bronze Age / Ancient", "Iron Age / Classical", 
            "Medieval / Feudal", "Renaissance / Gunpowder", "Industrial Revolution", 
            "Wild West / Frontier", "Early 20th Century / World War Era", "Modern Information Age", 
            "Near-Future", "Far-Future Sci-Fi", "Space-Faring / Intergalactic",
            "Purely Magical (No conventional tech)"
        ]
        
        # Combine a Main Type and a Subtype! (e.g., "Eldritch Horror Ice Age")
        chosen_genre = f"{random.choice(main_types)} {random.choice(subtypes)}"
        chosen_vibe = random.choice(random_vibes)
        chosen_tech = random.choice(tech_levels)
        
        # Override the empty fields with our forced random concepts
        ai_genre = data['world']['genre'] or f"The genre of the game will be a {chosen_genre}, with a {chosen_vibe} sort of vibe to it."
        ai_setting = data['world']['setting'] or f"The main setting of the world must make sense for the {chosen_genre} genre."
        ai_tech = data['world']['tech'] or f"The technology level is strictly: {chosen_tech}."
        
        logging.info(f"Chosen genre: {chosen_genre}\nChosen vibe: {chosen_vibe}\nAI Genre: {ai_genre}\nAI Setting {ai_setting}\nAI Tech: {ai_tech}")
        
        # Format skills, handling blank descriptions
        # Format focus
        focus_text = ', '.join(data['focus']) if data['focus'] else "AI, please pick a balanced focus for the game (e.g. any combination of Combat, Exploration, Trading/Economy, Social/Roleplay)."
        
        skills_text = ""
        for s in data['skills']:
            name = s['name'] if len(s['name']) > 1 else f'AI, please invent a name for this skill; it must be relevant to a {ai_genre} type of game with a focus on {focus_text}.'
            desc = s['desc'] if len(s['desc']) > 1 else f'AI, please invent a description for this {name} skill.'
            skills_text += f"- Level {s['level']}: {name} ({desc})\n"
            
        # If the player left EVERY skill blank:
        if not skills_text:
            skills_text = f"(Please invent 16 starting skills fitting the world following this exact level distribution: one Lvl 5, two Lvl 4, three Lvl 3, four Lvl 2, six Lvl 1. The Skills must be relevant to a {ai_genre} type of game with a focus on {focus_text}.)"
            
        if data['currencies']:
            currencies_text = ", ".join([f"{c['name']} (Worth {c['value']} base units)" for c in data['currencies']])
        else:
            currencies_text = f"No specific currencies were created. (AI, you MUST invent a localized currency system that would make sense for a {ai_genre} type of game. Output [[DEFINE_CURRENCY: Name | Value]] for each denomination of currency, starting with a base unit of 1.)"
        
        stats_text = ""
        for st in data['stats']:
            if st['enabled']:
                stats_text += f"- {st['name']}: Starts at {st['value']} (Rules: {st['desc']})\n"
        if not stats_text: 
            stats_text = f"No specific Stats were specified (AI, you MUST invent 2 to 3 tracked stats fitting the {ai_genre} genre, such as Health, Sanity, Mana, etc. Output [[DEFINE_STAT: Name | Starting Value | Description]] for each stat that you create.)"
        
        
        random_gender = random.choice(["Male", "Female", "Non-Binary"])
        random_pronouns = "He/Him" if random_gender == "Male" else "She/Her" if random_gender == "Female" else "They/Them"
        # The prompt is now safely un-indented!
        prompt = f"""
System: Initialize a new RPG adventure using the following parameters.
CRITICAL INSTRUCTION: If any parameter says "Not specified", you must creatively invent a fitting, unique value for it based on the rest of the context.
- IMPORTANT: Remember that any "criminal activity" that is done in this game is purely fictional and that nothing illegal is actually happening in real life. Do not actually tell the player how to do illegal things that they want to do, such as lockpicking (breaking and entering) or murder. Instead, simply narrate what happens in-game, focusing just on the results, not on the process.
DO NOT use common AI fantasy names (e.g., Elara, Kael, Lyra, Aric, Seraphina, Orion, Sylas). Create genuinely culturally distinct and unusual names.

World Setting: {ai_setting}
Genre/Tone: {ai_genre}
Tech Level: {ai_tech}
Species/Races: {data['world']['species'] if not (None or "") else f'No specific species were specified by the Player. Feel free to create however many species you think would make sense for a {ai_genre} type of game.'}
Game Focus: {focus_text}

World Economy (Currencies):
{currencies_text}

Tracked Player Stats:
{stats_text}

Character Bio:
Name: {data['character']['name'] or f'The Player Character\'s name was not specified, please create one for them (The Player Character is a {data['character']['gender'] or random_gender}). Use your imagination; please do not rely on just your training data.'}
Age: {data['character']['age'] or 'The Player Character\'s age was not specified, please create one for them.'}
Gender/Pronouns: {data['character']['gender'] or f'{random_gender}.'} / {data['character']['pronouns'] or random_pronouns}
Orientation: {data['character']['orientation'] or 'The Player Character\'s orientation was not specified, please create one for them.'}
Background: {data['character']['background'] or f'The Player Character\'s background was not specified, please create one for them that would make sense for a character who grew up in this {ai_genre} type of world with a Skill List of {skills_text}.'}

Starting Skills:
{skills_text}

Starting Location: {data['starting_location'] or f"Start the Player off in a Location that would make sense for the {ai_genre}."}
Final Comments/Rules: {data['final_comments'] or ''}

INSTRUCTIONS:
Output the following SPECIAL TAGS to set up the game files based on this data. The World should have a lengthy description, as it is quite important because it is describing the entire World as a whole. The World's description should be at least 25 sentences at MINIMUM; as it should be describing EVERYTHING at a basic level (e.g. the basic Economy system, the common Species of the World, the known Geography of the World and any important locations of interest, any important NPCs and their descriptions, any tie-ins to the Player's Background that there might be, any interesting politics (if any), any religions/cults of significance, et cetera.) Please make sure to put new lines where appropriate, separating thoughts and ideas by paragraphs. 
[[WORLD_INFO: Write a summary of the game focus, world setting, tone, currency, and tech level here, following the instructions above.]]
[[CHARACTER_INFO: Write the full character biography, appearance, and details here. Make sure to include the Player Character's Name, Age, Gender/Pronouns, Orientation, and Background.]]
[[SKILL: Name | Description | Level]] (Output one for EACH skill. If there are Skills that the Player left blank, please invent a Skill Name and a Description for the Skill.
[[ADD_FOOD: Type | Name | Desc | Amount | Value (MUST be an integer representing the number of smallest base currency units that this is worth) | Meals | SpoilDay | SpoilTime]] (Add logical starting food for the Player Character. Repeat this tag for EACH FOOD ITEM that the Player will start out with.)
[[ADD: Type | Name | Description | Amount | Value (MUST be an integer representing the number of smallest base currency units that this is worth)]] (Add logical starting equipment/wealth. Repeat this tag for EACH NON-FOOD and NON-CURRENCY item that the Player will start out with.)
[[DEFINE_CURRENCY: Name | Value]] (If no currencies were provided, output this for EACH invented denomination. Example: [[DEFINE_CURRENCY: Iron Bit | 1]]). THIS TAG MUST COME BEFORE [[GIVE_COIN]].
[[DEFINE_STAT: Name | Value | Description]] (If NO tracked stats were provided, output this tag for EACH invented stat. Be as specific as possible for the description of each stat, including positive effects for having a high value of the stat, and/or negative effects for having a low value of the stat (and what happens if the stat hits 0). Example: [[DEFINE_STAT: Sanity | 100 | Represents your mental fortitude against the Eldritch. Depletes when seeing horrors; replenishes when taking time to rest and give your brain a break without witnessing Eldritch horrors. High sanity allows your character to have a clear head and more easily deal with Eldritch horrors. Low sanity means that your character will have issues with Eldritch horrors when encountering them. Max value: 100.]])
[[GIVE_COIN: X]] (Give the player a logical amount of starting base currency for their background. Repeat this tag however many times you need to if you are adding different types of coins; e.g. "[[GIVE_COIN: 5 Copper Pieces]] [[GIVE_COIN: 5 Silver Pieces]] [[GIVE_COIN: 5 Gold Pieces]]". Please only use whatever currency you described previous in the "DEFINE_CURRENCY" tag from earlier.)
[[STATUS: 1 | {data['starting_location'] or 'Unknown (Invent a starting location name)'} | 1 | 7:00 A.M.]]
[[MUSIC: FILENAME_PLACEHOLDER.mp3]]
[[START_GAME]]

After outputting the tags, summarize the first starting turn, describe the surroundings vividly, and finish by asking "What do you do now?" and suggesting a few possible actions.
"""
        # Call query_ai and pass our new temporary is_startup flag
        logging.info("Generating start now...")
        self.query_ai(prompt, "System: Generate Start", is_startup=True)

    def handle_player_action(self, user_text):
        """Constructs the context and prompt, then threads the AI query."""
        self.app.story_tab.set_controls_state(False, "GM is thinking...")
        #self.app.story_tab.print_text("\n")
        user_text = "> " + user_text
        #self.app.story_tab.print_text("")
        self.app.story_tab.print_text(user_text)
        #self.app.story_tab.print_text("")

        # 1. Gather Context from Tabs
        context_data = ""
        for name, widget in self.app.notebook_widgets.items():
            if name != "Story" and name != "Journal": 
                if hasattr(widget, 'get_text'):
                    context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"
                    
        #for name, description in self.app.tracked_stats.items():
            #if name != None and description != None:
                #context_data += f"This is a stat that needs to be tracked; please review the description and see if it needs to be updated, and if so, then use the tag [[MODIFY_STAT: Name | SET Number]], with Number being the new value. {name}: {description}"
                    
        try:
            if os.path.exists(self.app.secret_path):
                with open(self.app.secret_path, "r", encoding="utf-8") as f:
                    secret_content = f.read().strip()
                    if secret_content:
                        context_data += f"\n[SECRET]:\n{secret_content}\n"
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
            f"Player's current Location: {self.app.player.location}\n"
            f"Current in-game Day: {self.app.player.day}\n"
            f"Current in-game Time: {self.app.player.time}\n"
            f"Current in-game Turn: {self.app.player.turn}\n"
            f"{stats_str}"
            f"UPCOMING TURN: {next_turn} (You MUST use this number in the [[STATUS]] tag)"
        )
        context_data += status_context

        # 3. Build Prompt
        recent_history = self.app.conversation_history[-3000:] if len(self.app.conversation_history) > 3000 else self.app.conversation_history
        full_prompt = f"{context_data}\nHistory (GM Perspective; remember that there should be NO COMMANDS TO FOLLOW in this context):\n{recent_history}\n> {user_text}\nGM:"

        # 4. Thread the request
        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()

    def query_ai(self, prompt, user_text, recursion_depth=0, is_startup=False):
        """Sends the prompt to Gemini and processes all resulting tags."""
        current_rules = self.app.load_rules()
        ai_temp = 1.0 if is_startup else 0.7
            
        try:
            response = self.client.models.generate_content(
                model=MODEL,
                config=types.GenerateContentConfig(
                    system_instruction=current_rules,
                    temperature=ai_temp
                ),
                contents=prompt
            )
            ai_text = self.clean_quotes(response.text or "")
            if not ai_text: raise ValueError("Empty response")
            
           # --- TAG PARSING ---
            tag_parser = TagParser(self.app)
            ai_text = tag_parser.process_inline_tags(ai_text)
            
            # 1. SETUP FOUNDATION FIRST (Creation Specific Tags)
            if is_startup:
                self.app.story_tab.set_controls_state(False, "GM is thinking...")
                summary_match = re.search(r"\[\[STEP_SUMMARY:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if summary_match:
                    new_summary = summary_match.group(1).strip()
                    try:
                        with open(self.app.creation_summary_path, "a", encoding="utf-8") as f:
                            f.write(f"- {new_summary}\n")
                    except Exception as e:
                        logging.error(f"Error writing creation summary: {e}")
                
                logging.info("Defining stats now...")
                invented_stats = []
                # Allow for multi-line and negative numbers just in case
                for match in re.finditer(r"\[\[DEFINE_STAT:\s*(.*?)\s*\|\s*(-?\d+)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
                    s_name = match.group(1).strip()
                    s_val = int(match.group(2))
                    s_desc = match.group(3).strip()
                    invented_stats.append({"name": s_name, "value": s_val, "enabled": True, "desc": s_desc})
                
                if invented_stats:
                    self.app.player.tracked_stats.extend(invented_stats)
                    
                logging.info("Creating world info now...")
                world_match = re.search(r"\[\[WORLD_INFO:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if world_match:
                    content = world_match.group(1).strip()
                    content = content.replace(". ", ".\n\n")
                    formatted_world = f"World Setting\n\n{content}"
                    self.app.notebook_widgets["World"].set_text(formatted_world)
                    if getattr(self.app, 'current_adventure_path', None):
                        world_file = os.path.join(self.app.current_adventure_path, "world.md")
                        with open(world_file, "w", encoding="utf-8") as f:
                            f.write(formatted_world)
                
                logging.info("Creating character info now...")
                char_match = re.search(r"\[\[CHARACTER_INFO:\s*(.*?)\]\]", ai_text, re.DOTALL)
                if char_match:
                    content = char_match.group(1).strip()
                    content = content.replace(". ", ".\n\n")
                    formatted_char = f"Character Biography\n\n{content}"
                    self.app.notebook_widgets["Character"].set_text(formatted_char)
                    
                    if getattr(self.app, 'current_adventure_path', None):
                        char_file = os.path.join(self.app.current_adventure_path, "character.md")
                        with open(char_file, "w", encoding="utf-8") as f:
                            f.write(formatted_char)
                
                logging.info("Creating Skills now...")
                for match in re.finditer(r"\[\[SKILL:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text, re.DOTALL):
                    s_name = match.group(1).strip()
                    # Group 2 is now the description string
                    s_desc = match.group(2).strip() if match.group(2).strip() else "No description provided."
                    # Group 3 is now the level integer
                    s_lvl = int(match.group(3))
                    
                    self.app.notebook_widgets["Skills"].force_learn_skill(s_name, s_desc, s_lvl)
                    
                logging.info("Defining currencies now...")
                # Parse Invented Currencies BEFORE standard tags run!
                invented_currencies = []
                for match in re.finditer(r"\[\[DEFINE_CURRENCY:\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text, re.DOTALL):
                    c_name = match.group(1).strip()
                    c_val = int(match.group(2))
                    invented_currencies.append({"name": c_name, "value": c_val})
                
                if invented_currencies:
                    self.app.player.world_currencies = invented_currencies
                    
                self.app.story_tab.set_controls_state(True, "What do you do now?")

            # 2. PROCESS STANDARD TAGS (Now it has the currencies loaded to do the math!)
            tag_parser.process_standard_tags(ai_text, is_startup=is_startup)    

            # 3. FINALIZE STARTUP & SAVE
            if is_startup:
                #self.app.story_tab.print_text("\n[System: Creation Complete. Saving Data...]\n", sender="System")
                
                if os.path.exists(self.app.creation_summary_path):
                    try:
                        os.remove(self.app.creation_summary_path)
                    except Exception as e:
                        logging.error(f"Error deleting creation summary: {e}")
                
                logging.info("Saving game now...")
                self.app.save_game()
                
                self.app.after(0, lambda: self.app._sync_player_state_to_ui())
                if "Inventory" in self.app.notebook_widgets:
                    self.app.after(0, lambda: self.app.notebook_widgets["Inventory"].refresh_display())

                logging.info("Starting game now...")
                ai_text = ai_text.replace("[[START_GAME]]", "")
                clean_creation_text = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", ai_text, flags=re.DOTALL).strip()
                self.app.conversation_history.append(f"{clean_creation_text}")

            # 4. RECURSIVE LOGIC (Rolls)
            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)

            if roll_match and recursion_depth < 2:
                skill = roll_match.group(1).strip()
                # Call back to main app for mechanic logic
                result = self.app.perform_skill_check(skill)
                
                if "Skills" in self.app.notebook_widgets:
                    # Note: If your Reload button uses a differently named method (like .load_data() or .reload_skills()), 
                    # change .refresh_display() to match it!
                    skills_tab = self.app.notebook_widgets["Skills"]
                    
                    if hasattr(skills_tab, 'refresh_display'):
                        self.app.after(0, lambda: skills_tab.refresh_display())
                    elif hasattr(skills_tab, 'load_data'):
                        self.app.after(0, lambda: skills_tab.load_data())
                
                clean_prev = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", ai_text).strip()
                logging.info(f"[System: Player rolled {result} for {skill}]")
                follow_up = f"{prompt}\nGM: {clean_prev}\n[System: Player rolled {result} for {skill}. Please determine what degree of success/failure that is, then narate the outcome. Do NOT mention the die roll at all in the diegetic context.]"
                
                # Recursive call
                self.query_ai(follow_up, user_text, recursion_depth + 1)
            else:
                logging.info(f"AI text: {ai_text}")
                # Clean tags for final display
                clean_pattern = re.compile(r"\[\[[A-Z_]+:.*?\]\]", re.DOTALL)
                final_text = clean_pattern.sub("", ai_text)
                final_text = re.sub(r'\n{3,}', '\n\n', final_text)
                final_text = final_text.strip()
                #final_text = "\n" + final_text
                
                if final_text and len(final_text) > 8:
                    self.app.story_tab.print_text(" ")
                    self.app.story_tab.print_text(final_text, sender="")
                    self.app.story_tab.print_text(" ")
                    
                    text_to_save = final_text
                    # Trim potential actions from history
                    trim_markers = ["Possible Actions:", "Suggested Actions:", "### Actions", "What would you like to do?", "What do you do?", "What do you do now?"]
                    for marker in trim_markers:
                        if marker in text_to_save:
                            text_to_save = text_to_save.split(marker)[0].strip()
                            break
                    if not is_startup:
                        self.app.conversation_history.append(f"{user_text}")
                        self.app.conversation_history.append(f"{text_to_save.strip()}")
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
            #self.app.story_tab.print_text(res, sender="GM")

        for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Inventory"].autonomous_remove(match.group(1))
            #self.app.story_tab.print_text(res, sender="GM")
            
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
            """
            if not is_startup and "Processing" in self.app.notebook_widgets:
                finished_items = self.app.notebook_widgets["Processing"].check_active_tasks(self.app.player.day, self.app.player.time)
                if finished_items:
                    sys_msg = f"System: Process completed - {', '.join(finished_items)}"
                    self.app.story_tab.print_text(sys_msg, sender="System")
                    self.app.conversation_history.append(sys_msg)
            """
                    
        for match in re.finditer(r"\[\[RECIPE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Recipes"].add_recipe_from_tag(match.group(1))
            #self.app.story_tab.print_text(res, sender="System")
                    
        for match in re.finditer(r"\[\[START_PROCESS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            p_name = match.group(1).strip()
            p_desc = match.group(2).strip()
            p_slots = match.group(3).strip()
            p_yield = match.group(4).strip()
            res = self.app.notebook_widgets["Processing"].add_timed_process(p_name, p_desc, p_slots, self.app.player.day, self.app.player.time, p_yield)
            #self.app.story_tab.print_text(res, sender="System")
            
        for match in re.finditer(r"\[\[REMOVE_PROCESS:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Processing"].remove_process(match.group(1).strip())
            #if res: self.app.story_tab.print_text(res, sender="System")
            
        for match in re.finditer(r"\[\[START_PROJECT:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            p_name = match.group(1).strip()
            p_desc = match.group(2).strip()
            work_required = match.group(3).strip()
            skill_name = match.group(4).strip()
            p_yield = match.group(5).strip()
            lvl = self.app._get_skill_level(skill_name)
            res = self.app.notebook_widgets["Processing"].add_project(p_name, p_desc, work_required, skill_name, lvl, p_yield)
            #if res: self.app.story_tab.print_text(res, sender="System")

        for match in re.finditer(r"\[\[WORK:\s*(.*?)\s*\|\s*([\d.]+)\]\]", ai_text, re.DOTALL):
            project_name = match.group(1).strip()
            hours_worked = float(match.group(2).strip())
            req_skill = self.app.notebook_widgets["Processing"].get_required_skill(project_name) or ""
            lvl = self.app._get_skill_level(req_skill) if req_skill else 0
            res = self.app.notebook_widgets["Processing"].apply_work_hours(project_name, hours_worked, lvl)
            
            # Update time locally via Main App helper
            self.app._advance_time_hours(hours_worked)
            """
            completed = self.app.notebook_widgets["Processing"].check_active_tasks(self.app.player.day, self.app.player.time)
            if completed:
                sys_msg = f"System: Process completed - {', '.join(completed)}"
                self.app.story_tab.print_text(sys_msg, sender="System")
                self.app.conversation_history += f"\n{sys_msg}\n"
            
            if res: self.app.story_tab.print_text(res, sender="System")
            """
            
        for match in re.finditer(r"\[\[ADD_FOOD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Inventory"].add_food(match.group(1))
            #self.app.story_tab.print_text(res, sender="GM")
            
        for match in re.finditer(r"\[\[CONSUME:\s*(.*?)\]\]", ai_text, re.DOTALL):
            f_name = match.group(1).strip()
            res = self.app.notebook_widgets["Inventory"].consume_food(f_name, self.app.player.day, self.app.player.time)
            for match in re.finditer(r"\[\[MODIFY_STAT:\s*(.*?)\s*\|\s*(.*?)\]\]", res, re.DOTALL):
                stat_name = match.group(1).strip()
                stat_val = match.group(2).strip()
                self.app.player.modify_stat(stat_name, stat_val)
                self.app._sync_player_state_to_ui()
                res = re.sub(r"\[\[[A-Z_]+:.*?\]\]", "", res).strip()
            #self.app.story_tab.print_text(res, sender="System")
            
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
                        
                    # 3. (Optional but recommended) Update the UI panel immediately 
                    # so the player can see the new lore without reloading the save!
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
            existing = next((s for s in self.app.player.tracked_stats if s.get("name", "").lower() == s_name.lower()), None)
            if not existing:
                self.app.player.tracked_stats.append({"name": s_name, "value": s_val, "enabled": True, "desc": s_desc})
                
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
            for item in parsed_list:
                # Clean up any lingering quotes and split by the pipe character
                item = item.strip().strip('\'"')
                parts = [p.strip() for p in item.split('|')]
                
                if len(parts) >= 3:
                    name = parts[0]
                    desc = parts[1]
                    price_raw = parts[2]
                    
                    # Convert the raw base unit integer into nicely formatted currency
                    try:
                        price_val = int(price_raw)
                        formatted_price = self.app.player.get_formatted_currency(price_val)
                    except ValueError:
                        formatted_price = price_raw # Fallback if AI hallucinates text instead of an int
                        
                    table_data.append([name, desc, formatted_price])
                else:
                    # Fallback if the AI messes up the pipe formatting
                    table_data.append(parts + [""] * (3 - len(parts)))
            
            if not table_data:
                return "\n*(This merchant has nothing for sale.)*\n"
                
            # Create the 3xY rounded grid!
            headers = ["Item Name", "Description", "Price"]
            grid = tabulate(table_data, headers=headers, tablefmt="rounded_grid")
            
            # Pad with newlines so it renders nicely in the text box
            return f"\n{grid}\n"
                
        # Find all instances of [[DISPLAY_CURRENCY: X]] and swap them
        modified_text = re.sub(r"\[\[DISPLAY_CURRENCY:\s*(-?\d+)\]\]", replace_currency, ai_text)
        modified_text = re.sub(r"\[\[MERCHANT:\s*(.*?)\]\]", replace_merchant, modified_text, flags=re.DOTALL)
        
        return modified_text