from google import genai
from google.genai import types
import threading, re, os, logging, csv, json
from config import GEMINI_API_KEY, MODEL
from tabulate import tabulate
from pathlib import Path
from typing import Any, ClassVar
from creative_sampler import CreativeCategory, CreativeSampleRequest

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
            
        resolved_calendar_settings = self._resolve_calendar_settings_from_wizard(data)
        self.app.player.calendar_settings = resolved_calendar_settings

        calendar_data = data.get("calendar", {}) if isinstance(data.get("calendar"), dict) else {}
        calendar_mode = str(calendar_data.get("mode", "gregorian") or "gregorian")

        data["calendar"] = {
            "mode": "custom" if calendar_mode == "ai_generate" else calendar_mode,
            "settings": resolved_calendar_settings,
            "ai_notes": str(calendar_data.get("ai_notes", "") or ""),
        }
        
        spellcasting_data = self._normalize_starting_spellcasting_data(data.get("spellcasting", {}))
        data["spellcasting"] = spellcasting_data
        self._save_starting_spellcasting(spellcasting_data)

        self._save_resolved_creation_settings(data)
            
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

        # 6. Refresh the UI, but do not create the final save yet.
        self.app._sync_player_state_to_ui()
        
        # 7. Build the prompt
        valid_sound_names = self.app.sound_manager.get_valid_track_names()
        valid_sounds_str = ", ".join(valid_sound_names) if valid_sound_names else "No music available."
        focus_text = ', '.join(data['focus']) if data['focus'] else "Balanced (Combat, Exploration, Trading/Economy, Social/Roleplay)"
        currency_prompt_text = self._build_starting_currency_prompt(data.get("currencies", []))
        stat_prompt_text = self._build_starting_stat_prompt(data.get("stats", []))
        calendar_prompt_text = self._build_starting_calendar_prompt(self.app.player.calendar_settings)
        
        spellcasting_prompt_text = self._build_starting_spellcasting_prompt(data.get("spellcasting", {}))
        
        creative_ideas = ""

        creative_bank = getattr(self.app, "creative_idea_bank", None)
        if creative_bank is not None:
            creative_ideas = creative_bank.build_prompt_fragment(
                CreativeSampleRequest(
                    categories=(
                        CreativeCategory.MALE_NAMES,
                        CreativeCategory.FEMALE_NAMES,
                        CreativeCategory.SETTLEMENT_NAMES,
                        CreativeCategory.REGION_NAMES,
                        CreativeCategory.RELIGION_NAMES,
                        CreativeCategory.SPECIES_NAMES,
                    ),
                    samples_per_category=10,
                    banned_terms=(
                        "Kaelan",
                        "Bram",
                        "Elara",
                        "Oakhaven",
                        "Ravenswood",
                        "Silverbrook",
                    ),
                )
            )
        else:
            logging.warning("Creative idea bank is unavailable.")
        
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

Provided Calendar Information:
{calendar_prompt_text}

Provided Starting Spellcasting:
{spellcasting_prompt_text}

Starting Location: {data['starting_location'] or 'Unknown Starting Location'}
Final Comments/Rules: {data['final_comments'] or 'N/A'}

{f"Use these compact creative inspiration samples when inventing missing names, places, factions, species, religions, or world details:\n\n{creative_ideas}" if creative_ideas else ""}

---

CRITICAL FINAL INSTRUCTIONS:
Output the following tags to set up the starting gameplay state:
[[WORLD_PROFILE: 
### World Setting

- **Genre:** (Filled value)

- **Setting:** (Filled value)

- **Technology Level:** (Filled value)

- **Species:** (Filled value)

- **Focus:** (Filled value)

\n **Description:** (Filled value; this must be at most six paragraphs, but it should include the basics of the world, including as much detail as possible from the user's input, if there was any input. In general, the Description of the World should include at the very least, the World's basic societal structure, main religions/pantheons, basic geography/topography, important locations, important NPCs, important factions or politics, interspecies relations [if any], descriptions of races/species [if any that are non-human], and anything else that you think would be important if you were writing a story based on this world.)
]] (You must output this tag. Output the exact Markdown formatting shown inside this tag, replacing the "(Filled value)" text with creative and/or logical values based off of the \"Provided World Information\" section above, remembering to ONLY change the information if it is \"Unknown\".).

[[CHARACTER_PROFILE: 
### Character Biography

- **Name:** (Filled value)

- **Age:** (Filled value)

- **Gender:** (Filled value)

- **Orientation:** (Filled value)

- **Background:** (Filled value)
]] (You must output this tag. Output the exact Markdown formatting shown inside this tag, replacing the "(Filled value)" text with creative and/or logical values based off of the \"Provided Character Information\" section above, remembering to ONLY change the information if it is \"Unknown\".).

[[SKILL: Name | Description | Level]] (Output this tag for EACH skill listed in the "Provided Starting Skills" section. If the Name or Description is "Unknown", creatively invent a fitting one based on the character's background. Keep the Level exactly as provided, remembering that the higher the level is for a Skill, the better the Player is at that Skill, so please reserve the higher level Skills for things that the Player Character may be good at, depending on their background.)
[[DEFINE_CURRENCY: Name | Base Unit Value]] (Output this tag for each starting currency ONLY if no valid currencies were provided by the player. The smallest/base currency must have value 1.)
[[DEFINE_STAT: Name | Starting Value | Description]] (Output this tag for each starting tracked stat ONLY if no valid stats were provided by the player and tracked stats are useful for this campaign.)
[[CHANGE_CURRENCY: X]] where X is a single integer number of base currency units. Do not include coin names. Do not split denominations.
[[ADD: Type | Name | Description | Amount]] (Add logical starting equipment. Repeat this tag for each item that the Player will start out with.)
[[STATUS: {data['starting_location'] or 'Unknown'} | AUTO | AUTO]]
[[MUSIC: FILENAME_PLACEHOLDER]] (You MUST output this tag to set the starting music. Replace FILENAME_PLACEHOLDER with exactly one of these options: {valid_sounds_str})
[[SPELL: Name | Level | School | Description]] (You MUST output this tag only if Spellcasting exists in the World, and if the Player specifies that they wish to start with Spells known.)


After outputting all tags, summarize the first starting turn, describe the surroundings vividly, and finish by asking "What do you do now?" and suggesting a few possible actions.
"""
        logging.info(f"Generating start now...\n\nWorld Creation Prompt: {prompt}\n\n")
        self.query_ai(prompt, "System: Generate Start", is_startup=True)

    def handle_player_action(self, user_text: str) -> None:
        """Constructs the context and prompt, then threads the AI query."""
        self.app.story_tab.set_controls_state(False, "GM is thinking...")
        user_text = "> " + user_text
        self.app.story_tab.print_text(user_text)
        
        creative_reminder = (
            "\n[CREATIVE STYLE REMINDER]\n"
            "When inventing a new NPC, location, faction, item, spell, tavern, or landmark, "
            "avoid generic fantasy defaults and avoid reusing names from recent history unless it is the same entity.\n"
        )

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
                    context_data += (
                        "\n[GM-ONLY SECRET CONTEXT]\n"
                        "The following facts are available only to the Game Master for continuity, causality, and future setup.\n"
                        "They are NOT known by the player character and are NOT known by NPCs unless a specific visible reason exists.\n"
                        "Do not reveal these facts in narration, dialogue, UPDATE_WORLD, QUEST, or visible summaries unless the player discovers them in the current scene.\n\n"
                        f"{secret_content}\n"
                    )
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
        context_data += creative_reminder
        
        # 3. Build history context early so creative sampling can inspect the latest scene.
        history_text = ""
        if "History" in self.app.notebook_widgets:
            history_text = self.app.notebook_widgets["History"].get_text().strip()

        recent_history = history_text[-6000:] if len(history_text) > 6000 else history_text

        # Always include these. They are small and protect against name reuse and
        # player-facing hidden-knowledge leakage.
        context_data += self._build_creative_guardrails()
        context_data += self._build_npc_knowledge_firewall()

        if self._needs_creative_samples(user_text, recent_history=recent_history):
            creative_bank = getattr(self.app, "creative_idea_bank", None)
            if creative_bank is not None:
                creative_fragment = creative_bank.build_prompt_fragment(
                    CreativeSampleRequest(
                        categories=(
                            CreativeCategory.SETTLEMENT_NAMES,
                            CreativeCategory.REGION_NAMES,
                            CreativeCategory.MALE_NAMES,
                            CreativeCategory.FEMALE_NAMES,
                            CreativeCategory.TAVERN_DRINK_NAMES,
                            CreativeCategory.ALCHEMY_INGREDIENTS,
                            CreativeCategory.MAGIC_TYPES,
                        ),
                        samples_per_category=5,
                        banned_terms=self.BANNED_CREATIVE_TERMS,
                    )
                )

                if creative_fragment:
                    context_data += f"\n[CREATIVE SAMPLES]\n{creative_fragment}\n"
            else:
                logging.warning("Creative idea bank is unavailable.")

        full_prompt = (
            f"\nPast Conversation History:\n{recent_history}\n"
            f"Please remember to consider the following in your response: {context_data}\n\n"
            f"===\n"
            f"YOUR FINAL END GOAL: Using all of the above context and information, "
            f"here is the user's actual prompt: \"{user_text}\""
        )
        
        # 4. Thread the request
        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()
        
    def _build_npc_knowledge_firewall(self) -> str:
        """
        Builds prompt rules that separate Game Master knowledge from NPC knowledge.

        Returns:
            A compact prompt fragment that prevents NPCs from speaking with
            information they have no visible reason to know.
        """
        return (
            "\n[NPC KNOWLEDGE FIREWALL]\n"
            "- The Game Master may know all context, including GM-only secrets, but NPCs do not.\n"
            "- Before writing any NPC dialogue, silently check what that NPC could know from visible evidence, prior conversation, public reputation, their job, location, faction, or direct observation.\n"
            "- NPCs must not mention the player character's name, destination, employer, party, deadline, recent private conversations, purchases, class, profession, abilities, secrets, or plans unless the player told them, they directly witnessed it, or the provided context explicitly says they know it.\n"
            "- If an NPC is guessing, phrase it as a guess, rumor, sales tactic, or inference, not certainty.\n"
            "- If an NPC lacks a reason to know a fact, replace the line with a question, a cautious assumption, or an observable comment.\n"
            "- Shopkeepers may infer likely needs from requested goods, but they may not know private expedition details unless told.\n"
            "- Never let NPC dialogue expose GM-only secrets.\n"
        )
    
    def _build_starting_spellcasting_prompt(self, spellcasting_data: dict[str, Any] | None) -> str:
        """
        Builds the startup prompt block for spellcasting.

        Args:
            spellcasting_data: Normalized spellcasting wizard data.

        Returns:
            Prompt text describing starting spellcasting setup.
        """
        if not isinstance(spellcasting_data, dict) or not spellcasting_data.get("enabled", False):
            return (
                "Spellcasting is disabled for this save unless the player explicitly changes it later. "
                "Do not invent starting spells for the Player Character."
            )

        lines: list[str] = [
            "Spellcasting is enabled for this save.",
            "The Spellcasting panel has already been initialized directly from the player's wizard choices.",
            "Do not consume, restore, prepare, or unprepare spell slots automatically.",
        ]

        magic_rules = str(spellcasting_data.get("magic_rules", "") or "").strip()
        if magic_rules:
            lines.append(f"World spellcasting rules: {magic_rules}")

        prepared_limit = self._safe_nonnegative_int(spellcasting_data.get("prepared_limit"), default=0)
        prepared_limit_text = "Unlimited" if prepared_limit == 0 else str(prepared_limit)
        lines.append(f"Prepared spell limit: {prepared_limit_text}.")

        slot_levels = spellcasting_data.get("slot_levels", {})
        if isinstance(slot_levels, dict):
            active_slot_lines: list[str] = []

            for level in range(1, 10):
                slot_data = slot_levels.get(str(level), {})
                if not isinstance(slot_data, dict):
                    continue

                max_slots = self._safe_nonnegative_int(slot_data.get("max"), default=0)
                if max_slots > 0:
                    active_slot_lines.append(f"- Level {level}: {max_slots} slots")

            if active_slot_lines:
                lines.append("Starting spell slots:")
                lines.extend(active_slot_lines)

        spells = spellcasting_data.get("spells", {})
        if not isinstance(spells, dict) or not spells:
            lines.append("Known starting spells: none.")
            return "\n".join(lines)

        lines.append("Known starting spells:")

        for spell_name, spell in sorted(spells.items(), key=lambda item: str(item[0]).lower()):
            if not isinstance(spell, dict):
                continue

            level = self._safe_nonnegative_int(spell.get("level"), default=0)
            school = str(spell.get("school", "") or "").strip() or "Unknown School"
            description = str(spell.get("description", "") or "").strip() or "Unknown Spell Description"
            prepared = "Prepared" if spell.get("prepared", False) else "Not prepared"

            lines.append(
                f"- Name: {spell_name} | Level: {level} | School: {school} | "
                f"Description: {description} | {prepared}"
            )

        lines.append(
            "If any starting spell has an Unknown description or Unknown school, output "
            "[[SPELL: Name | Level | School | Description]] for that spell to refine it. "
            "Otherwise, do not re-output existing starting spells."
        )

        return "\n".join(lines)


    def _safe_nonnegative_int(self, value: Any, *, default: int = 0) -> int:
        """
        Safely converts a value to a nonnegative integer.

        Args:
            value: Raw value to convert.
            default: Fallback value.

        Returns:
            Nonnegative integer.
        """
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            logging.exception("Invalid nonnegative integer value: %r", value)
            return default
        
    def _normalize_starting_spellcasting_data(self, spellcasting_data: Any) -> dict[str, Any]:
        """
        Normalizes wizard spellcasting data before writing it to spellcasting.json.

        Args:
            spellcasting_data: Raw spellcasting data from the creation wizard.

        Returns:
            Normalized spellcasting dictionary.
        """
        try:
            from qt_ui.dialogs import CreationTemplateStore

            return CreationTemplateStore.normalize_spellcasting_data(spellcasting_data)
        except Exception as error:
            logging.exception("Failed to normalize starting spellcasting data: %s", error)

        return {
            "enabled": False,
            "magic_rules": "",
            "prepared_limit": 0,
            "slot_levels": {
                str(level): {"max": 0, "used": 0}
                for level in range(1, 10)
            },
            "spells": {},
        }


    def _save_starting_spellcasting(self, spellcasting_data: dict[str, Any]) -> None:
        """
        Writes starting spellcasting data directly to the Spellcasting panel.

        Args:
            spellcasting_data: Normalized spellcasting data.
        """
        spellcasting_panel = self.app.notebook_widgets.get("Spellcasting")

        if spellcasting_panel is None:
            logging.warning("Cannot save starting spellcasting data because the Spellcasting panel is missing.")
            return

        try:
            if hasattr(spellcasting_panel, "save_data"):
                spellcasting_panel.save_data(spellcasting_data)
                return

            logging.warning("Spellcasting panel does not expose save_data().")

        except Exception as error:
            logging.exception("Failed to save starting spellcasting data: %s", error)

    def _get_default_gregorian_calendar(self) -> dict[str, Any]:
        """Returns the fallback Gregorian calendar."""

        return {
            "weekdays": [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ],
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
                {"name": "December", "days": 31, "season": "Winter"},
            ],
        }

    def _normalize_calendar_settings(self, raw_settings: Any) -> dict[str, Any]:
        """Validates and normalizes calendar data before storing it on Player."""

        fallback = self._get_default_gregorian_calendar()

        if not isinstance(raw_settings, dict):
            logging.warning("Calendar settings were not a dict. Falling back to Gregorian.")
            return fallback

        raw_weekdays = raw_settings.get("weekdays", [])
        weekdays = [
            str(day).strip()
            for day in raw_weekdays
            if str(day).strip()
        ] if isinstance(raw_weekdays, list) else []

        if not weekdays:
            weekdays = fallback["weekdays"]

        raw_months = raw_settings.get("months", [])
        months: list[dict[str, Any]] = []

        if isinstance(raw_months, list):
            for index, raw_month in enumerate(raw_months):
                if not isinstance(raw_month, dict):
                    logging.warning("Skipped malformed generated calendar month: %r", raw_month)
                    continue

                fallback_month = fallback["months"][index % len(fallback["months"])]

                name = str(raw_month.get("name", "") or fallback_month["name"]).strip()
                season = str(raw_month.get("season", "") or fallback_month["season"]).strip()

                try:
                    days = max(1, int(raw_month.get("days", fallback_month["days"])))
                except (TypeError, ValueError):
                    logging.exception("Invalid generated month length: %r", raw_month)
                    days = int(fallback_month["days"])

                if not name:
                    continue

                months.append(
                    {
                        "name": name,
                        "days": days,
                        "season": season or "Unknown Season",
                    }
                )

        if not months:
            months = fallback["months"]

        return {
            "weekdays": weekdays,
            "months": months,
        }

    def _resolve_calendar_settings_from_wizard(self, data: dict[str, Any]) -> dict[str, Any]:
        """Gets the final calendar settings from wizard data."""

        calendar_data = data.get("calendar", {}) if isinstance(data.get("calendar"), dict) else {}
        mode = str(calendar_data.get("mode", "gregorian") or "gregorian")

        if mode == "ai_generate":
            generated_calendar = self._generate_calendar_settings(data)
            if generated_calendar:
                return self._normalize_calendar_settings(generated_calendar)

            logging.warning("AI calendar generation failed. Falling back to Gregorian.")
            return self._get_default_gregorian_calendar()

        raw_settings = calendar_data.get("settings", {})
        return self._normalize_calendar_settings(raw_settings)

    BANNED_CREATIVE_TERMS: ClassVar[tuple[str, ...]] = (
        "Kaelan",
        "Bram",
        "Elara",
        "Oakhaven",
        "Ravenswood",
        "Silverbrook",
    )

    _CREATIVE_DIRECT_TRIGGERS: ClassVar[tuple[str, ...]] = (
        "new town",
        "new city",
        "new npc",
        "random npc",
        "name",
        "named",
        "introduce",
        "invent",
        "create",
        "tavern",
        "shop",
        "merchant",
        "spell",
        "alchemy",
        "ingredient",
        "religion",
        "temple",
        "faction",
        "guild",
        "region",
        "country",
    )

    _CREATIVE_ACTION_TRIGGERS: ClassVar[tuple[str, ...]] = (
        "approach",
        "ask",
        "talk",
        "speak",
        "introduce",
        "meet",
        "head to",
        "head towards",
        "head over to",
        "head over towards",
        "go",
        "enter",
        "leave",
        "travel",
        "follow",
        "inspect",
        "check",
        "look",
        "observe",
        "search",
        "explore",
        "read",
        "listen",
        "join",
        "hire",
        "negotiate",
        "investigate",
    )

    _UNNAMED_ENTITY_HINTS: ClassVar[tuple[str, ...]] = (
        " a dwarf",
        " the dwarf",
        " a woman",
        " the woman",
        " a man",
        " the man",
        " a clerk",
        " the clerk",
        " a guard",
        " the guard",
        " a group",
        " the group",
        " adventuring group",
        " coterie",
        " mercenaries",
        " scouts",
        " mages",
        " crowd",
        " corkboard",
        " notice",
        " contract",
        " map",
        " guild members",
    )
    
    def _contains_any(self, text: str | None, terms: tuple[str, ...]) -> bool:
        """
        Checks whether any configured term appears in text.

        Args:
            text: Text to inspect.
            terms: Lowercase trigger terms.

        Returns:
            True if any term is present.
        """
        if text is None:
            logging.warning("AIManager._contains_any called with None text.")
            return False

        lowered_text = str(text).lower()
        return any(term in lowered_text for term in terms)


    def _build_creative_guardrails(self) -> str:
        """
        Builds always-on naming and player-knowledge rules.

        These rules are intentionally small enough to include every turn. They are not
        the same thing as creative samples; they protect against stale names and
        hidden-knowledge leakage even when samples are not needed.

        Returns:
            Prompt text for creative naming and player-facing lore safety.
        """
        banned_terms = ", ".join(self.BANNED_CREATIVE_TERMS)

        return (
            "\n[CREATIVE AND KNOWLEDGE SAFETY RULES]\n"
            f"- Do not invent or reuse these names unless they already refer to the same existing entity: {banned_terms}.\n"
            "- When inventing new names, avoid common generic fantasy defaults.\n"
            "- World.md is player-facing knowledge. Only use [[UPDATE_WORLD: ...]] for facts the player has actually learned in visible narration.\n"
            "- If an NPC's true name, motive, allegiance, secret, or identity has not been revealed to the player, do not put that hidden information in [[UPDATE_WORLD: ...]].\n"
            "- You may use [[UPDATE_WORLD: ...]] if it is reasonable for the Player to believe the information that they just learned. "
            "For example, if an NPC says that their name is Gregor, and the Player has not learned any information to the contrary, "
            "you may use the [[UPDATE_WORLD: ...]] tag for that. If you do, also output a [[SECRET: ...]] tag if that NPC has a different true name.\n"
            "- For unrevealed NPCs, use visible public descriptors such as 'the scarred dwarf clerk', 'the armored woman at the map table', or 'the hooded courier'.\n"
            "- Use [[SECRET: ...]] for GM-only facts that the player has not learned yet.\n"
        )
    
    def _needs_creative_samples(
        self,
        user_text: str,
        *,
        recent_history: str = "",
    ) -> bool:
        """
        Returns True when the next GM response is likely to invent or name content.

        This intentionally favors false positives over false negatives. A few sampled
        names cost far fewer tokens than sending the full creative_ideas.md file, and
        missing the sample can cause stale-name reuse.

        Args:
            user_text: The player's current action.
            recent_history: Recent visible/hidden history used to detect nearby
                unnamed entities.

        Returns:
            True if creative samples should be added to the prompt.
        """
        clean_user_text = str(user_text or "").strip()
        if not clean_user_text:
            logging.warning("AIManager._needs_creative_samples called with blank user_text.")
            return False

        if self._contains_any(clean_user_text, self._CREATIVE_DIRECT_TRIGGERS):
            return True

        # Player actions like "approach the dwarf" or "ask the clerk" often cause
        # the model to name an NPC even if the user did not explicitly request a name.
        action_likely_advances_scene = self._contains_any(
            clean_user_text,
            self._CREATIVE_ACTION_TRIGGERS,
        )

        if not action_likely_advances_scene:
            return False

        nearby_context = f"{clean_user_text}\n{str(recent_history or '')[-3000:]}"

        return self._contains_any(nearby_context, self._UNNAMED_ENTITY_HINTS)
    
    def _generate_calendar_settings(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Uses Gemini to generate a calendar JSON object during new-game creation."""

        if self.client is None:
            logging.warning("Cannot generate calendar because Gemini client is unavailable.")
            return None

        calendar_data = data.get("calendar", {}) if isinstance(data.get("calendar"), dict) else {}
        ai_notes = str(calendar_data.get("ai_notes", "") or "").strip()

        world = data.get("world", {}) if isinstance(data.get("world"), dict) else {}

        prompt = (
            "Generate a fictional RPG world calendar as JSON only.\n"
            "Do not include Markdown. Do not include commentary. Return one JSON object.\n\n"
            "Required schema:\n"
            "{\n"
            '  "weekdays": ["Day Name", "Day Name"],\n'
            '  "months": [\n'
            '    {"name": "Month Name", "days": 30, "season": "Season Name"}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Use 4 to 10 weekdays.\n"
            "- Use 4 to 16 months.\n"
            "- Month days must be positive integers.\n"
            "- Seasons should be useful for weather and temperature logic.\n"
            "- Avoid real-world month names unless Gregorian or Earth-like realism is requested.\n\n"
            f"World genre: {world.get('genre', '')}\n"
            f"World setting: {world.get('setting', '')}\n"
            f"Technology level: {world.get('tech', '')}\n"
            f"Species/races: {world.get('species', '')}\n"
            f"User calendar notes: {ai_notes or 'None provided.'}\n"
        )

        try:
            response = self.client.models.generate_content(
                model=MODEL,
                config=types.GenerateContentConfig(
                    temperature=1.0,
                    response_mime_type="application/json",
                ),
                contents=prompt,
            )

            raw_text = self.clean_quotes(response.text or "")
            if not raw_text.strip():
                logging.warning("AI calendar generation returned empty text.")
                return None

            return self._load_json_object_from_text(raw_text)

        except Exception as error:
            logging.exception("Failed to generate calendar settings: %s", error)
            return None

    def _load_json_object_from_text(self, raw_text: str) -> dict[str, Any] | None:
        """Parses a JSON object from model output."""

        try:
            parsed = json.loads(raw_text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        try:
            start_index = raw_text.find("{")
            end_index = raw_text.rfind("}")

            if start_index < 0 or end_index <= start_index:
                logging.warning("No JSON object found in calendar response: %s", raw_text)
                return None

            parsed = json.loads(raw_text[start_index:end_index + 1])
            return parsed if isinstance(parsed, dict) else None

        except Exception as error:
            logging.exception("Failed to parse generated calendar JSON: %s", error)
            return None

    def _save_resolved_creation_settings(self, data: dict[str, Any]) -> None:
        """
        Saves resolved wizard data into the currently active adventure folder.

        During new-game creation, current_adventure_path points at the temporary
        staging folder. When startup succeeds, that staged folder is moved into the
        final save folder.
        """
        save_directory = getattr(self.app, "current_adventure_path", None)
        if not save_directory:
            logging.warning("Cannot save resolved creation settings because no save path is active.")
            return

        try:
            from qt_ui.dialogs import CreationTemplateStore

            CreationTemplateStore.save_creation_settings(save_directory, data)

        except Exception as error:
            logging.exception("Failed to save resolved creation settings: %s", error)

    def _build_starting_calendar_prompt(self, calendar_settings: dict[str, Any]) -> str:
        """Builds a compact startup prompt block describing the world calendar."""

        normalized_calendar = self._normalize_calendar_settings(calendar_settings)

        weekdays = ", ".join(normalized_calendar["weekdays"])
        months = ", ".join(
            f"{month.get('name', 'Unknown Month')} ({month.get('days', 30)} days, {month.get('season', 'Unknown Season')})"
            for month in normalized_calendar["months"]
        )

        return (
            "The world calendar is already defined. Use it exactly.\n"
            f"Weekdays in order: {weekdays}\n"
            f"Months in order: {months}\n"
            "Do not use real-world calendar assumptions unless this calendar uses real-world names."
        )
    
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
                    temperature = 1.0,
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
                
                self.query_ai(
                    follow_up,
                    user_text,
                    recursion_depth + 1,
                    is_startup=is_startup,
                )
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
                
                self.query_ai(
                    follow_up,
                    user_text,
                    recursion_depth + 1,
                    is_startup=is_startup,
                )
                return

            # 2. PROCESS STANDARD TAGS
            standard_tag_pattern = re.compile(r"\[\[[A-Z_]+:.*?\]\]", re.DOTALL)
            visible_narrative_for_tag_safety = standard_tag_pattern.sub("", display_ai_text)

            tag_parser.process_standard_tags(
                ai_text,
                is_startup=is_startup,
                visible_narrative_text=visible_narrative_for_tag_safety,
            )

            # 3. FINALIZE AND PRINT
            log_ai_text = self._build_ai_log_text(history_ai_text, ai_text)
            logging.info("AI text: %s", log_ai_text)

            clean_pattern = standard_tag_pattern
            
            final_display_text = clean_pattern.sub("", display_ai_text)
            final_display_text = re.sub(r'\n{2,}', '\n\n', final_display_text).strip()
            
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
                
                # Get rid of the "System: Initialization..." message at game creation.
                if is_startup:
                    user_text = ""
                    
                new_exchange = (
                    f"{user_text}\n\n"
                    f"{history_body_to_save.strip()}\n\n"
                    f"// NEW EXCHANGE\n\n"
                )

                self.app.after(0, lambda ch=current_hist, ne=new_exchange: hist_panel.set_text(ch + ne))
                
            try:
                self.app.save_game()

                if is_startup and hasattr(self.app, "commit_pending_adventure"):
                    self.app.commit_pending_adventure()

            except Exception as error:
                logging.exception("Auto-save or pending-adventure commit failed: %s", error)

                if is_startup and hasattr(self.app, "discard_pending_adventure"):
                    self.app.discard_pending_adventure()

                self.app.story_tab.print_text(
                    "System: New game creation failed before the save could be finalized.",
                    sender="System",
                )
                return

            if is_startup:
                self.app.story_tab.set_controls_state(True, "What do you do now?")

                if getattr(self.app, "win", None) is not None:
                    self.app.after(1500, lambda: self.app.win.open_help_menu())

        except Exception as error:
            logging.exception("AI Error: %s", error)
            
            if is_startup and hasattr(self.app, "discard_pending_adventure"):
                logging.exception("System: New game creation failed. No save file was created.")
                self.app.discard_pending_adventure()
            
        finally:
            self.app.after(0, lambda: self.app.story_tab.set_controls_state(True))
            
    def _build_ai_log_text(self, history_ai_text: str | None, fallback_ai_text: str | None) -> str:
        """
        Builds a compact AI response string for the log file.

        Args:
            history_ai_text: AI text after history-safe inline tag processing.
            fallback_ai_text: Fallback AI text if history-safe text is unavailable.

        Returns:
            AI text suitable for logging without large UI-only tables.
        """
        clean_history_text = str(history_ai_text or "").strip()
        if clean_history_text:
            return clean_history_text

        logging.warning("History-safe AI text was empty. Falling back to display AI text for logging.")
        return str(fallback_ai_text or "").strip()
            
class TagParser:
    def __init__(self, app):
        self.app = app
        
    _POSSIBLE_PROPER_NOUN_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\b[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?)*\b"
    )
    
    _STATIC_IGNORED_UPDATE_WORLD_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "A",
            "An",
            "The",
            "You",
            "He",
            "She",
            "They",
            "It",
            "What",
            "World",
            "Character",
            "Status",
            "System",
            "GM",
            "AUTO",
            "Day",
            "Year",
            "Season",
            "Location",
            "Weather",
        }
    )
    
    def _get_calendar_ignored_update_world_names(self) -> set[str]:
        """
        Returns calendar-specific proper nouns that should not be treated as hidden NPC names.

        The active calendar can be Gregorian, custom, or AI-generated, so weekday,
        month, and season names should come from the current Player state instead of
        being hard-coded.

        Returns:
            A set of calendar terms safe to ignore during UPDATE_WORLD proper-noun checks.
        """
        ignored_names: set[str] = set()

        if self.app is None:
            logging.warning("TagParser has no app context while reading calendar ignored names.")
            return ignored_names

        player = getattr(self.app, "player", None)

        if player is None:
            logging.warning("TagParser could not find player while reading calendar ignored names.")
            return ignored_names

        calendar_settings = getattr(player, "calendar_settings", None)

        if not isinstance(calendar_settings, dict):
            logging.warning(
                "Player calendar_settings was not a dictionary: %r",
                calendar_settings,
            )
            return ignored_names

        weekdays = calendar_settings.get("weekdays", [])
        if isinstance(weekdays, list):
            for weekday in weekdays:
                weekday_name = str(weekday or "").strip()
                if weekday_name:
                    ignored_names.add(weekday_name)

        months = calendar_settings.get("months", [])
        if isinstance(months, list):
            for month in months:
                if not isinstance(month, dict):
                    logging.warning("Skipped malformed calendar month while building ignored names: %r", month)
                    continue

                month_name = str(month.get("name", "") or "").strip()
                season_name = str(month.get("season", "") or "").strip()

                if month_name:
                    ignored_names.add(month_name)

                if season_name:
                    ignored_names.add(season_name)

        return ignored_names
    
    def _find_unrevealed_proper_nouns(
    self,
    lore_text: str,
    *,
    visible_narrative_text: str,
    existing_world_text: str,
) -> list[str]:
        """
        Finds capitalized names in UPDATE_WORLD that were not visible to the player.

        Args:
            lore_text: Proposed UPDATE_WORLD lore.
            visible_narrative_text: The player-facing narration after tag cleanup.
            existing_world_text: Existing World panel text.

        Returns:
            Suspicious proper nouns that should not be written to World.md yet.
        """
        if lore_text is None:
            logging.warning("TagParser._find_unrevealed_proper_nouns called with None lore_text.")
            return []

        known_player_text = f"{visible_narrative_text or ''}\n{existing_world_text or ''}".lower()
        unrevealed_names: list[str] = []

        for match in self._POSSIBLE_PROPER_NOUN_PATTERN.finditer(str(lore_text)):
            candidate = match.group(0).strip()

            ignored_names = (
                set(self._STATIC_IGNORED_UPDATE_WORLD_NAMES)
                | self._get_calendar_ignored_update_world_names()
            )

            # Then inside the loop:
            if not candidate or candidate in ignored_names:
                continue

            # Single title-case sentence starters are the riskiest false positives,
            # but true leaked names are usually also single title-case words.
            # So we allow them only if the player has already seen them.
            if candidate.lower() not in known_player_text:
                unrevealed_names.append(candidate)

        return unrevealed_names
    
    def _sanitize_update_world_lore(
        self,
        lore_text: str,
        *,
        visible_narrative_text: str,
        existing_world_text: str,
    ) -> str:
        """
        Validates UPDATE_WORLD lore before writing it to the player-facing World panel.

        Args:
            lore_text: Proposed lore from the AI tag.
            visible_narrative_text: Player-facing narration for this response.
            existing_world_text: Current World panel contents.

        Returns:
            Safe lore text, or an empty string if the update should be skipped.
        """
        clean_lore = str(lore_text or "").strip()
        if not clean_lore:
            return ""

        unrevealed_names = self._find_unrevealed_proper_nouns(
            clean_lore,
            visible_narrative_text=visible_narrative_text,
            existing_world_text=existing_world_text,
        )

        if unrevealed_names:
            logging.warning(
                "Skipped UPDATE_WORLD because it appears to contain unrevealed proper noun(s): %s. Lore: %r",
                ", ".join(unrevealed_names),
                clean_lore,
            )
            return ""

        return clean_lore
        
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

    def process_standard_tags(
        self,
        ai_text: str,
        is_startup: bool = False,
        visible_narrative_text: str = "",
    ) -> None:
        """Processes typical gameplay tags and applies safe state mutations."""
        
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
            
        for match in re.finditer(r"\[\[SPELL:\s*(.*?)\]\]", ai_text, re.DOTALL):
            raw_parts = [part.strip() for part in match.group(1).split("|")]

            if len(raw_parts) < 4:
                logging.warning(
                    "Invalid SPELL tag. Expected 4 fields, got %s: %s",
                    len(raw_parts),
                    match.group(0),
                )
                continue

            spell_name, spell_level, school, description = raw_parts[:4]

            spellcasting_panel = self.app.notebook_widgets.get("Spellcasting")
            if spellcasting_panel is None:
                logging.warning("SPELL tag ignored because the Spellcasting panel is missing.")
                continue

            try:
                spellcasting_panel.force_learn_spell(
                    spell_name=spell_name,
                    spell_level=spell_level,
                    school=school,
                    description=description,
                )
            except Exception as error:
                logging.exception("Failed to process SPELL tag %s: %s", match.group(0), error)
            
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
                    
                    if mode == "w":
                        secret_file.write("SECRET INFORMATION BELOW (e.g. INFORMATION THAT THE GAME MASTER KNOWS, BUT THE PLAYER DOES NOT NECESSARILY KNOW, UNLESS THAT INFORMATION IS GIVEN ELSEWHERE.)")
                    
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

                safe_world_lore = self._sanitize_update_world_lore(
                    new_world_lore,
                    visible_narrative_text=visible_narrative_text,
                    existing_world_text=current_world_text,
                )

                if not safe_world_lore:
                    continue

                updated_world_text = f"{current_world_text}\n\n{safe_world_lore}\n"

                world_panel.set_text(updated_world_text)
                world_panel.save_now()

            except Exception as world_update_error:
                logging.exception(
                    "Could not update World panel from UPDATE_WORLD tag: %s",
                    world_update_error,
                )
                
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