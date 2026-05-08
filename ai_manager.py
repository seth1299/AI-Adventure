from google import genai
from google.genai import types
import threading, re, os, logging, csv
from config import GEMINI_API_KEY, MODEL
from tabulate import tabulate
from pathlib import Path

class AIManager:
    def __init__(self, app) -> None:
        """Initializes the Gemini API client used by the AI manager."""
        self.app = app
        self.client: genai.Client | None = None
        
        try:
            self.client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as error:
            logging.exception("Failed to initialize Gemini Client: %s", error)

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

        for stat in data.get("stats", []):
            if not stat.get("enabled", True):
                continue

            try:
                stat_value = int(stat.get("value", 100))
                stat_min = int(stat.get("min", 0))
                stat_max = int(stat.get("max", 100))
            except (TypeError, ValueError) as error:
                logging.exception("Invalid wizard stat value: %s", error)
                stat_value = 100
                stat_min = 0
                stat_max = 100

            self.app.player.tracked_stats.append(
                {
                    "name": stat.get("name", "Unknown Stat"),
                    "value": max(stat_min, min(stat_max, stat_value)),
                    "min": stat_min,
                    "max": stat_max,
                    "enabled": True,
                    "description": stat.get("description", ""),
                }
    )
                
        # 3. Inject Currencies directly
        self.app.player.world_currencies = []
        for c in data['currencies']:
            self.app.player.world_currencies.append({"name": c['name'], "value": c['value']})
            
        self.app.player.calendar_settings = {
            "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "months": [
                {"name": "January", "days": 31, "season": "Winter"},
                {"name": "February", "days": 28, "season": "Winter"},
                {"name": "March", "days": 31, "season": "Spring"},
                {"name": "April", "days": 30, "season": "Spring"},
                {"name": "May", "days": 31, "season": "Spring"},
                {"name": "June", "days": 30, "season": "Summer"},
                {"name": "July", "days": 31, "season": "Summer"},
                {"name": "August", "days": 31, "season": "Summer"},
                {"name": "September", "days": 30, "season": "Fall"},
                {"name": "October", "days": 31, "season": "Fall"},
                {"name": "November", "days": 30, "season": "Fall"},
                {"name": "December", "days": 31, "season": "Winter"}
            ]
        }
            
        # 4. Process Skills for the AI Prompt (Do NOT inject them directly yet!)
        skills_prompt_text = ""
        for s in data['skills']:
            s_name = s['name'].strip()
            s_desc = s['desc'].strip()
            s_lvl = s['level']
            
            # We removed the 'continue' statement here so it processes all 16 slots!
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
        valid_sound_names = self.app.sound_manager.get_valid_track_names()
        valid_sounds_str = ", ".join(valid_sound_names) if valid_sound_names else "No music available."
        focus_text = ', '.join(data['focus']) if data['focus'] else "Balanced (Combat, Exploration, Trading/Economy, Social/Roleplay)"
        currency_prompt_text = self._build_starting_currency_prompt(data.get("currencies", []))
        stat_prompt_text = self._build_starting_stat_prompt(data.get("stats", []))
        
        creative_ideas = self.app.load_creative_ideas()
        
        prompt = f"""
Initialize a new RPG adventure using the following parameters.
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

Provided Starting Currencies:
{currency_prompt_text}

Provided Tracked Stats:
{stat_prompt_text}

Starting Location: {data['starting_location'] or 'Unknown Starting Location'}
Final Comments/Rules: {data['final_comments'] or 'N/A'}

{f"Please use the following data to help you compile all of the information about the world and such. You do NOT need to limit yourself to only using names from this list, but please consider all of the names and use them when creating your response: \n\n{creative_ideas}" if creative_ideas else ""}

---

CRITICAL FINAL INSTRUCTIONS:
Output the following tags to set up the starting gameplay state:
[[WORLD_PROFILE: 
### World Setting

**Genre:** (Filled value)

**Setting:** (Filled value)

**Technology Level:** (Filled value)

**Species:** (Filled value)

**Focus:** (Filled value)

**Description:** (Filled value; this must be at most six paragraphs, but it should include the basics of the world, including as much detail as possible from the user's input, if there was any input. In general, the Description of the World should include at the very least, the World's basic societal structure, main religions/pantheons, basic geography/topography, important locations, important NPCs, important factions or politics, interspecies relations [if any], descriptions of races/species [if any that are non-human], and anything else that you think would be important if you were writing a story based on this world.)
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
[[DEFINE_CURRENCY: Name | Base Unit Value]] (Output this tag for each starting currency ONLY if no valid currencies were provided by the player. The smallest/base currency must have value 1.)
[[DEFINE_STAT: Name | Starting Value | Description]] (Output this tag for each starting tracked stat ONLY if no valid stats were provided by the player and tracked stats are useful for this campaign.)
[[CHANGE_CURRENCY: X]] where X is a single integer number of base currency units. Do not include coin names. Do not split denominations.
[[ADD: Type | Name | Description | Amount]] (Add logical starting equipment. Repeat this tag for each item that the Player will start out with.)
[[STATUS: {data['starting_location'] or 'Unknown'} | AUTO | AUTO]]
[[MUSIC: FILENAME_PLACEHOLDER]] (You MUST output this tag to set the starting music. Replace FILENAME_PLACEHOLDER with exactly one of these options: {valid_sounds_str})

After outputting all tags, summarize the first starting turn, describe the surroundings vividly, and finish by asking "What do you do now?" and suggesting a few possible actions.
"""
        logging.info(f"Generating start now...\n\nWorld Creation Prompt: {prompt}\n\n")
        self.query_ai(prompt, "System: Generate Start", is_startup=True)

    def handle_player_action(self, user_text: str) -> None:
        """Constructs the context and prompt, then threads the AI query."""
        self.app.story_tab.set_controls_state(False, "GM is thinking...")
        user_text = "> " + user_text
        self.app.story_tab.print_text(user_text)

        # 1. Gather Context from Tabs
        context_data = ""
        for name, widget in self.app.notebook_widgets.items():
            if name in ["Story", "Journal", "History"]:
                continue

            try:
                panel_context = ""

                if hasattr(widget, "get_ai_context"):
                    panel_context = widget.get_ai_context().strip()
                elif hasattr(widget, "get_text"):
                    panel_context = widget.get_text().strip()

                if panel_context:
                    context_data += f"\n[{name.upper()}]:\n{panel_context}\n"

            except Exception as error:
                logging.exception("Failed to gather AI context from %s panel: %s", name, error)
                    
        try:
            # Convert the string path to a Path object to check existence
            secret_file_path = Path(self.app.secret_path)
            if secret_file_path.exists() and secret_file_path.is_file():
                # Use Path's built-in read_text method for cleaner file I/O
                secret_content = secret_file_path.read_text(encoding="utf-8").strip()
                if secret_content:
                    context_data += f"\n[SECRET]:\n{secret_content}\n"
        except Exception as secret_read_error:
            logging.error(f"Error: Could not open secret.txt. Details: {secret_read_error}")
        
        # 2. Gather Status
        stats_str = ""
        for stat in self.app.player.tracked_stats:
            if stat.get("enabled", True):
                # Grab the description if it exists, otherwise leave it blank
                desc_text = f" (Rules: {stat.get('description')})" if stat.get('description') else ""
                stats_str += f"{stat['name']}: {stat['value']}{desc_text}\n"
        status_dict = self.app.player.get_status_dict()
        rich_date = status_dict.get("formatted_date", f"Day {status_dict.get('day')}")
        calendar_context = ""
        cal_settings = status_dict.get("calendar_settings", {})
        if cal_settings and cal_settings.get("weekdays") and cal_settings.get("months"):
            weekdays_str = ", ".join(cal_settings["weekdays"])
            # Format: "MonthName (30 days), OtherMonth (20 days)"
            months_str = ", ".join([f"{m.get('name')} ({m.get('days')} days)" for m in cal_settings["months"]])
            calendar_context = f"\nWorld Calendar Rules -> Weekdays in order: [{weekdays_str}]. Months in order: [{months_str}]. DO NOT USE REAL-WORLD CALENDAR INFORMATION UNLESS THAT IS WHAT WAS JUST GIVEN TO YOU."
        stats_block = stats_str.strip() if stats_str.strip() else "None"
        calendar_block = f"{calendar_context}\n" if calendar_context else ""
        status_context = (
            f"\n[CURRENT STATUS]\n"
            f"Player's current Location: {self.app.player.location}\n"
            f"Current in-game Date: {rich_date}\n"
            f"Current in-game Time: {self.app.player.time}\n"
            f"Current in-game Turn: {self.app.player.turn}\n"
            f"Here are the Player's 'Stats' that you MUST track using the provided Rules for EACH stat provided: {stats_block}"
            f"{calendar_block}"
        )
        context_data += status_context

        # 3. Build Prompt
        history_text = ""
        if "History" in self.app.notebook_widgets:
            history_text = self.app.notebook_widgets["History"].get_text().strip()
        recent_history = history_text[-6000:] if len(history_text) > 6000 else history_text
        full_prompt = f"\nPast Conversation History:\n{recent_history}\nPlease remember to consider the following in your response: {context_data}\n\n===\nYOUR FINAL END GOAL: Using all of the above context and information, here is the user's actual prompt: \"{user_text}\""
        
        # 4. Thread the request
        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()

    def _build_starting_currency_prompt(self, currencies: list[dict] | None) -> str:
        """
        Builds the startup currency instruction block for Gemini.

        If the player provided currencies in the wizard, those are treated as fixed.
        If they provided none, Gemini must define a logical currency system using
        DEFINE_CURRENCY tags.
        """
        if not currencies:
            return (
                "No starting currencies were provided by the player.\n"
                "You MUST invent a logical currency system for this world.\n"
                "Output [[DEFINE_CURRENCY: Name | Base Unit Value]] once for each denomination.\n"
                "At minimum, define one base currency with value 1.\n"
                "For fantasy worlds, a normal example would be Copper Piece = 1, Silver Piece = 10, Gold Piece = 100.\n"
                "For modern or sci-fi worlds, use genre-appropriate currency names."
            )

        rows: list[str] = []
        for currency in currencies:
            if not isinstance(currency, dict):
                logging.warning("Skipped malformed currency row during startup prompt: %r", currency)
                continue

            name = str(currency.get("name", "")).strip()
            if not name:
                continue

            try:
                value = max(1, int(currency.get("value", 1)))
            except (TypeError, ValueError):
                logging.exception("Invalid currency value during startup prompt: %r", currency)
                value = 1

            rows.append(f"- {name} | Base Unit Value: {value}")

        if not rows:
            return (
                "No valid starting currencies were provided by the player.\n"
                "You MUST invent a logical currency system using [[DEFINE_CURRENCY: Name | Base Unit Value]]."
            )

        return (
            "The player already defined these currencies. Do NOT redefine them unless explicitly told to later.\n"
            + "\n".join(rows)
        )

    def _build_starting_stat_prompt(self, stats: list[dict] | None) -> str:
        """
        Builds the startup tracked-stat instruction block for Gemini.

        If the player provided tracked stats, those are treated as fixed.
        If they provided none, Gemini may define appropriate starting stats using
        DEFINE_STAT tags.
        """
        if not stats:
            return (
                "No tracked stats were provided by the player.\n"
                "If this genre benefits from tracked stats, you SHOULD define a small useful set using "
                "[[DEFINE_STAT: Name | Starting Value | Description]].\n"
                "Examples: Health, Stamina, Hunger, Sanity, Reputation, Heat, Morale.\n"
                "Only define stats that will actually matter for this campaign."
            )

        rows: list[str] = []
        for stat in stats:
            if not isinstance(stat, dict):
                logging.warning("Skipped malformed stat row during startup prompt: %r", stat)
                continue

            name = str(stat.get("name", "")).strip()
            if not name:
                continue

            try:
                value = int(stat.get("value", 100))
                minimum = int(stat.get("min", 0))
                maximum = int(stat.get("max", 100))
            except (TypeError, ValueError):
                logging.exception("Invalid stat values during startup prompt: %r", stat)
                value = 100
                minimum = 0
                maximum = 100

            description = str(stat.get("description", "")).strip() or "No description provided."
            rows.append(
                f"- {name} | Current Value: {value} | Min: {minimum} | Max: {maximum} | Rules: {description}"
            )

        if not rows:
            return (
                "No valid tracked stats were provided by the player.\n"
                "If this genre benefits from tracked stats, define them using [[DEFINE_STAT: Name | Starting Value | Description]]."
            )

        return (
            "The player already defined these tracked stats. Do NOT redefine them unless explicitly told to later.\n"
            + "\n".join(rows)
        )
        
    def _log_token_usage(self, prompt: str | None, user_text: str | None, ai_text: str | None) -> None:
        """
        Logs approximate token usage for the prompt, user text, and AI response.

        Token logging is diagnostic only. Failures here must never interrupt
        gameplay, tag parsing, saving, or UI updates.
        """
        if self.client is None:
            logging.warning("Skipped token counting because Gemini client is unavailable.")
            return

        try:
            token_source = "\n".join(
                part
                for part in (
                    str(prompt or ""),
                    str(user_text or ""),
                    str(ai_text or ""),
                )
                if part
            )

            if not token_source.strip():
                logging.warning("Skipped token counting because token source was empty.")
                return

            token_response = self.client.models.count_tokens(
                model=MODEL,
                contents=token_source,
            )

            total_tokens = getattr(token_response, "total_tokens", None)

            if total_tokens is None:
                logging.info("Gemini token usage response: %s", token_response)
                return

            logging.info("Tokens used during the last prompt/response cycle: %s", total_tokens)

        except Exception as error:
            logging.exception("Failed to count Gemini tokens: %s", error)
    
    def query_ai(self, prompt, user_text, recursion_depth=0, is_startup=False):
        """Sends the prompt to Gemini and processes all resulting tags."""
        current_rules = self.app.load_rules()
            
        try:
            """Sends the prompt to Gemini and processes all resulting tags."""
            if self.client is None:
                logging.error("Gemini Client is unavailable; query skipped.")
                self.app.after(0, lambda: self.app.story_tab.set_controls_state(True))
                self.app.story_tab.print_text(
                    "Gemini client failed to initialize. Check your API key and log file.",
                    sender="System",
                )
                return
        
            if is_startup:
                self.app.story_tab.set_controls_state(False, "GM is thinking...")
                
            response = self.client.models.generate_content(
                model=MODEL,
                config=types.GenerateContentConfig(
                    system_instruction=current_rules,
                    temperature = 1.0 if not is_startup else 1.1,
                    thinking_config = types.ThinkingConfig(thinking_budget = -1),
                    tools=[],
                    safety_settings=[types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE)]
                ),
                contents=prompt                
            )
            
            ai_text = self.clean_quotes(response.text or "")
            if not ai_text: raise ValueError("Empty response")
            
            self._log_token_usage(prompt, user_text, ai_text)
            
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
                self.app.after(1500, lambda: self.app.win.open_help_menu())

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
                
                #logging.info(f"[System: Calculated project estimate for '{project_name}' at {estimated_minutes:g} minutes]")
                
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
            
            if "Processing" in self.app.notebook_widgets:
                processing_tab = self.app.notebook_widgets["Processing"]
                if hasattr(processing_tab, 'get_text'):
                    self.app.after(0, lambda: processing_tab.check_active_tasks(self.app.get_day(), self.app.get_time()))
                else: logging.warning("Processing tab does not have attribute 'check_active_tasks'.")
                if hasattr(processing_tab, 'refresh_display'):
                    self.app.after(0, lambda: processing_tab.refresh_display())
                else: logging.warning("Processing tab does not have attribute 'refresh_display'.")
            else: logging.warning(f"No processing tab in notebook widgets. Existing notebook widgets: {self.app.notebook_widgets}")
            
            trim_markers = ["Possible Actions:", "Suggested Actions:", "### Actions", "What would you like to do?", "What do you do?", "What do you do now?"]
            text_to_save = final_display_text
            
            for marker in trim_markers:
                if marker in final_display_text:
                    parts = final_display_text.split(marker, 1)
                    main_body = parts[0].strip()
                    options_string = parts[1].strip()
                    text_to_save = main_body
                    
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
                
            if final_display_text and len(final_display_text.strip()) > 8:
                self.app.story_tab.print_text(final_display_text, sender="")
            else:
                logging.warning("AI response contained no displayable narrative after tag cleanup.")
                
            final_history_text = clean_pattern.sub("", history_ai_text)
            final_history_text = re.sub(r"\n{3,}", "\n\n", final_history_text).strip()

            history_body_to_save = final_history_text

            for marker in trim_markers:
                if marker in history_body_to_save:
                    history_body_to_save = history_body_to_save.split(marker, 1)[0].strip()
                    break

            if "History" in self.app.notebook_widgets:
                hist_panel = self.app.notebook_widgets["History"]
                current_hist = hist_panel.get_text()

                if is_startup:
                    new_exchange = (
                        f"**System: Start of Game**\n\n"
                        f"**GM:** {history_body_to_save.strip()}\n\n"
                        f"// NEW EXCHANGE\n\n"
                    )
                else:
                    new_exchange = (
                        f"{user_text}\n\n"
                        f"{history_body_to_save.strip()}\n\n"
                        f"// NEW EXCHANGE\n\n"
                    )

                self.app.after(0, lambda ch=current_hist, ne=new_exchange: hist_panel.set_text(ch + ne))
                
            try:
                self.app.save_game()
            except Exception as e:
                logging.error(f"Auto-save failed: {e}")

        except Exception as error:
            logging.exception("AI Error: %s", error)
        finally:
            self.app.after(0, lambda: self.app.story_tab.set_controls_state(True))
            
class TagParser:
    def __init__(self, app):
        self.app = app
        
    def _strip_currency_transaction_tags(self, ai_text: str) -> str:
        """
        Removes currency transaction tags after they have already been processed.

        This prevents later parsing stages from accidentally re-processing or
        misinterpreting currency transaction tags while preserving other tags like
        DEFINE_CURRENCY.
        """
        if not ai_text:
            return ""

        return re.sub(
            r"\[\[CHANGE_CURRENCY:\s*-?\d+\s*\]\]",
            "",
            ai_text,
            flags=re.DOTALL,
        )


    def _process_inventory_tags(self, ai_text: str) -> None:
        """
        Processes inventory mutation tags exactly once.

        This method should only be called after CHANGE_CURRENCY has been processed,
        because failed payments may need to block inventory changes.
        """
        if not ai_text:
            logging.warning("TagParser._process_inventory_tags called with empty text.")
            return

        inventory_panel = self.app.notebook_widgets.get("Inventory")

        if inventory_panel is None:
            logging.error("Inventory tags ignored because the Inventory panel is missing.")
            return

        for match in re.finditer(r"\[\[ADD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            inventory_panel.autonomous_add(match.group(1))

        for match in re.finditer(r"\[\[REMOVE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            inventory_panel.autonomous_remove(match.group(1))

        for match in re.finditer(r"\[\[MODIFY_ITEM:\s*(.*?)\]\]", ai_text, re.DOTALL):
            inventory_panel.modify_item(match.group(1))

    def process_standard_tags(self, ai_text, is_startup: bool = False) -> None:
        """Processes typical gameplay tags and returns the cleaned text."""
        
        if not ai_text:
            logging.warning("TagParser.process_standard_tags called with empty text.")
            return

        inventory_mutations_allowed = self._process_currency_tags(ai_text)
        ai_text_without_currency_transactions = self._strip_currency_transaction_tags(ai_text)

        if inventory_mutations_allowed:
            self._process_inventory_tags(ai_text_without_currency_transactions)
        else:
            logging.warning("Skipped inventory mutations because a currency transaction failed.")

        # Continue processing non-inventory tags using the text with CHANGE_CURRENCY removed.
        ai_text = ai_text_without_currency_transactions
        
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
                #logging.info(f"Added quest: {q_name}")
                
        # Complete/Remove quests
        for match in re.finditer(r"\[\[COMPLETE_QUEST:\s*(.*?)\]\]", ai_text, re.DOTALL):
            q_name = match.group(1).strip()
            
            if "Quests" in self.app.notebook_widgets:
                self.app.notebook_widgets["Quests"].complete_quest(q_name)
                #logging.info(f"Completed quest: {q_name}")

        status_match = re.search(r"\[\[STATUS:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\]\]", ai_text)
        if status_match:
            loc = status_match.group(1).strip()
            mins_str = status_match.group(2).strip()
            weather = status_match.group(3).strip()
            
            try:
                mins_to_add = 0 if mins_str.upper() == "AUTO" else int(float(mins_str))
            except ValueError:
                logging.error(f"AI passed invalid minutes: {mins_str}")
                mins_to_add = 0
                
            # The system handles temperature and season generation automatically now
            self.app.player.update_world_state(
                location=loc,
                minutes_to_add=mins_to_add,
                weather=weather
            )
                    
            self.app._sync_player_state_to_ui()
                    
        for match in re.finditer(r"\[\[RECIPE:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Recipes"].add_recipe_from_tag(match.group(1))
            #if res: logging.info(res)
            
        for match in re.finditer(r"\[\[ADD_XP:\s*(.*?)\]\]", ai_text, re.DOTALL):
            parts = [p.strip() for p in match.group(1).split("|")]
            if len(parts) == 2:
                skill_name, xp_amount = parts[0], parts[1]
                try:
                    xp_amount_to_int = int(xp_amount)
                    self.app.notebook_widgets["Skills"].add_xp(skill_name, xp_amount_to_int)
                except Exception as e:
                    logging.exception(f"Error in [[ADD_XP]] tag: {e}")
            else:
                logging.warning(f"[[ADD_XP]] tag had invalid number of arguments. Expected 2 arguments, but got {len(parts)}. Argument: {match}.")
                    
        for match in re.finditer(r"\[\[START_PROCESS:\s*(.*?)\]\]", ai_text, re.DOTALL):
            # Capture the inside of the tag and split it manually
            parts = [p.strip() for p in match.group(1).split("|")]
            
            # Failsafe: Ensure the AI provided all 4 parts
            if len(parts) >= 4:
                p_name, p_desc, p_time, p_yield = parts[0], parts[1], parts[2], parts[3]
            elif len(parts) == 3:
                # Failsafe: If the AI forgot the yield, default to 1 instead of crashing/bleeding
                p_name, p_desc, p_time, p_yield = parts[0], parts[1], parts[2], "1"
            else:
                logging.error(f"Malformed START_PROCESS tag ignored: {match.group(0)}")
                continue
                
            try:
                p_slots = int(float(p_time))
            except ValueError:
                logging.error(f"AI passed invalid time for process: {p_time}")
                p_slots = 60 # Fallback to 1 hour
                
            res = self.app.notebook_widgets["Processing"].add_timed_process(p_name, p_desc, p_slots, self.app.player.day, self.app.player.time, p_yield)
            #(res)
            
        for match in re.finditer(r"\[\[REMOVE_PROCESS:\s*(.*?)\]\]", ai_text, re.DOTALL):
            res = self.app.notebook_widgets["Processing"].remove_process(match.group(1).strip())
            #if res: logging.info(res)
            
        for match in re.finditer(r"\[\[START_PROJECT:\s*(.*?)\]\]", ai_text, re.DOTALL):
            parts = [p.strip() for p in match.group(1).split("|")]
            
            if len(parts) >= 5:
                p_name, p_desc, work_required, skill_name, p_yield = parts[0], parts[1], parts[2], parts[3], parts[4]
            else:
                logging.error(f"Malformed START_PROJECT tag ignored: {match.group(0)}")
                continue
                
            lvl = self.app._get_skill_level(skill_name)
            res = self.app.notebook_widgets["Processing"].add_project(p_name, p_desc, work_required, skill_name, lvl, p_yield)
            #if res: logging.info(res)

        for match in re.finditer(r"\[\[WORK:\s*(.*?)\s*\|\s*([\d.]+)\]\]", ai_text, re.DOTALL):
            project_name = match.group(1).strip()
            # Changed variable name to reflect minutes
            minutes_worked = float(match.group(2).strip())
            req_skill = self.app.notebook_widgets["Processing"].get_required_skill(project_name) or ""
            lvl = self.app._get_skill_level(req_skill) if req_skill else 0
            
            # Call the newly renamed method
            res = self.app.notebook_widgets["Processing"].apply_work_minutes(project_name, minutes_worked, lvl)
            #if res: logging.info(res)
            
        for match in re.finditer(r"\[\[SECRET:\s*(.*?)\]\]", ai_text, re.DOTALL):
            try:
                new_secret = match.group(1).strip()
                
                if self.app.secret_path:
                    secret_file_path = Path(self.app.secret_path)
                    
                    # Check if the file physically exists on the disk
                    mode = "a" if secret_file_path.exists() else "w"
                    
                    with secret_file_path.open(mode, encoding="utf-8") as secret_file:
                        secret_file.write(f"\n{new_secret}\n")
                        
                    # Safely apply the hidden attribute only if the user is on Windows
                    if os.name == 'nt':
                        import subprocess
                        # Cast Path back to string for the subprocess argument
                        subprocess.check_call(["attrib", "+H", str(secret_file_path)])
                        
            except Exception as secret_write_error:
                    logging.error(f"Error writing secret: {secret_write_error}")
                    
        for match in re.finditer(r"\[\[UPDATE_WORLD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            new_world_lore = match.group(1).strip()

            if not new_world_lore:
                continue

            try:
                world_panel = self.app.notebook_widgets.get("World")
                if world_panel is None:
                    logging.error("UPDATE_WORLD ignored because the World panel is missing.")
                    continue

                current_world_text = world_panel.get_text().rstrip()
                updated_world_text = f"{current_world_text}\n\n{new_world_lore}\n"

                world_panel.set_text(updated_world_text)
                world_panel.save_now()

            except Exception as world_update_error:
                logging.exception("Could not update World panel from UPDATE_WORLD tag: %s", world_update_error)
                
        for match in re.finditer(r"\[\[DEFINE_CURRENCY:\s*(.*?)\s*\|\s*(\d+)\]\]", ai_text, re.DOTALL):
            c_name = match.group(1).strip()
            c_val = int(match.group(2))
            
            # Check if currency already exists before appending to prevent double-parsing
            existing = next((c for c in self.app.player.world_currencies if c.get("name", "").lower() == c_name.lower()), None)
            if not existing:
                self.app.player.world_currencies.append({"name": c_name, "value": c_val})
                self.app.after(0, lambda: self.app._sync_player_state_to_ui())
                if "Inventory" in self.app.notebook_widgets:
                    self.app.after(0, lambda: self.app.notebook_widgets["Inventory"].refresh_display())
                
        # Allow for multi-line and negative numbers just in case
        for match in re.finditer(r"\[\[DEFINE_STAT:\s*(.*?)\s*\|\s*(-?\d+)\s*\|\s*(.*?)\]\]", ai_text, re.DOTALL):
            s_name = match.group(1).strip()
            s_val = int(match.group(2))
            s_desc = match.group(3).strip()
            
            # Check if stat already exists before appending to prevent double-parsing
            existing = next((stat for stat in self.app.player.tracked_stats if stat.get("name", "").lower() == s_name.lower()), None)
            if not existing:
                self.app.player.tracked_stats.append(
                    {
                        "name": s_name,
                        "value": s_val,
                        "min": 0,
                        "max": 100,
                        "enabled": True,
                        "description": s_desc,
                    }
                )
                self.app.after(0, lambda: self.app._sync_player_state_to_ui())
                
    def _process_currency_tags(self, ai_text: str) -> bool:
        """
        Processes currency tags before inventory mutations.

        Returns:
            bool: True if inventory-changing tags may safely continue.
                False if a failed payment should block item changes.
        """
        inventory_mutations_allowed = True

        for match in re.finditer(r"\[\[CHANGE_CURRENCY:\s*(-?\d+)\]\]", ai_text, re.DOTALL):
            amount_str = match.group(1).strip()

            try:
                amount = int(amount_str)
            except ValueError:
                logging.error("Invalid CHANGE_CURRENCY amount: %r", amount_str)
                continue

            success, message = self.app.player.change_currency(amount)

            if not success and amount < 0:
                inventory_mutations_allowed = False
                logging.warning("Currency transaction blocked: %s", message)

                if getattr(self.app, "story_tab", None) is not None:
                    self.app.story_tab.print_text(f"System: {message}", sender="System")

            self.app.after(0, lambda: self.app._sync_player_state_to_ui())

            if "Inventory" in self.app.notebook_widgets:
                self.app.after(0, lambda: self.app.notebook_widgets["Inventory"].refresh_display())

        return inventory_mutations_allowed
    
    
    
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
            """
            Converts a [[MERCHANT: ...]] tag into a readable merchant table.

            Merchant entry format:
                "Item Name | Description | PriceBaseUnits | Quantity"

            PriceBaseUnits must be a plain non-negative integer measured in the
            world's base currency unit. Natural-language prices like "5 Copper Pieces"
            are rejected and logged instead of being displayed.
            """
            raw_data = match.group(1).strip()
            if not raw_data:
                return ""

            raw_lines = [line.strip() for line in raw_data.split("\n") if line.strip()]

            parsed_items: list[str] = []

            for line in raw_lines:
                try:
                    items_in_line = list(csv.reader([line], skipinitialspace=True))[0]

                    for item in items_in_line:
                        clean_item = item.strip().strip("'\"")
                        if clean_item:
                            parsed_items.append(clean_item)

                except Exception as error:
                    logging.exception("Failed to parse line in MERCHANT tag: %s", error)

                    clean_line = line.strip().strip("'\"")
                    if clean_line:
                        parsed_items.append(clean_line)

            table_data: list[list[str]] = []
            history_items: list[str] = []

            headers = ["Item Name", "Description", "Price", "Quantity / Stock"]
            max_cols = len(headers)

            for item in parsed_items:
                parts = [part.strip() for part in item.split("|")]

                if len(parts) < 3:
                    logging.warning(
                        "Skipped malformed MERCHANT entry. Expected at least 3 fields: %r",
                        item,
                    )
                    continue

                name = parts[0]
                description = parts[1]
                price_raw = parts[2]

                if not name or not description:
                    logging.warning(
                        "Skipped MERCHANT entry with blank name or description: %r",
                        item,
                    )
                    continue

                # Strictly accept only unsigned base-unit integers: 0, 1, 25, 100, etc.
                # Rejects: "-5", "+5", "5.0", "5 Copper Pieces", "Free", "AUTO".
                if re.fullmatch(r"\d+", price_raw) is None:
                    logging.warning(
                        "Skipped MERCHANT entry with invalid price %r. Price must be a non-negative integer in base currency units. Entry: %r",
                        price_raw,
                        item,
                    )
                    continue

                try:
                    price_value = int(price_raw)
                except (TypeError, ValueError) as error:
                    logging.exception(
                        "Skipped MERCHANT entry because price could not be converted to int. Price: %r. Error: %s",
                        price_raw,
                        error,
                    )
                    continue

                formatted_price = (
                    "Free"
                    if price_value == 0
                    else self.app.player.get_formatted_currency(price_value)
                )

                quantity = parts[3] if len(parts) > 3 else ""

                row_data = [name, description, formatted_price, quantity]

                if len(parts) > 4:
                    row_data.extend(parts[4:])
                    max_cols = max(max_cols, len(row_data))

                table_data.append(row_data)
                history_items.append(f"'{name}' - {description} ({formatted_price})")

            if not table_data:
                logging.warning("MERCHANT tag contained no valid merchant entries: %r", raw_data)
                return "\n*(Merchant table omitted because no valid merchant entries were provided.)*\n"

            for row in table_data:
                while len(row) < max_cols:
                    row.append("")

            while len(headers) < max_cols:
                headers.append("Extra Info")

            if is_history:
                items_str = ", ".join(history_items)
                return f"\n*(OOG: A merchant table is listed detailing the following items: {items_str}.)*\n"

            grid = tabulate(table_data, headers=headers, tablefmt="rounded_grid")
            formatted_html = (
                "<pre style=\"font-family: Consolas, 'Courier New', monospace; "
                f"line-height: 1.0; padding: 6px;\">\n\n{grid}\n</pre>\n\n"
            )

            return f"\n{formatted_html}\n"
                
        # Find all instances of [[DISPLAY_CURRENCY: X]] and swap them
        modified_text = re.sub(r"\[\[DISPLAY_CURRENCY:\s*(-?\d+)\]\]", replace_currency, ai_text)
        modified_text = re.sub(r"\[\[MERCHANT:\s*(.*?)\]\]", replace_merchant, modified_text, flags=re.DOTALL)
        
        return modified_text