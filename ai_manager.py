from google import genai
from google.genai import types
import threading, re, os, logging, csv, json
from config import GEMINI_API_KEY, MODEL
from tabulate import tabulate
from pathlib import Path
from typing import Any, ClassVar
from creative_sampler import CreativeCategory, CreativeSampleRequest
from dataclasses import dataclass
from qt_ui.dialogs import MerchantTagParser

@dataclass(frozen=True)
class ResponseSections:
    """
    Represents the player-facing parts of an AI response after functional tags
    have been removed.

    Args:
        main_body: The actual story narration.
        action_marker: The prompt marker that introduced suggested actions.
        suggested_actions: The optional suggested action list.
    """

    main_body: str
    action_marker: str = ""
    suggested_actions: str = ""

    def rebuild(self) -> str:
        """
        Rebuilds the response from its sections.

        Returns:
            Full player-facing response text.
        """
        clean_main = self.main_body.strip()
        clean_marker = self.action_marker.strip()
        clean_actions = self.suggested_actions.strip()

        if not clean_marker or not clean_actions:
            return clean_main

        return f"{clean_main}\n\n**{clean_marker}**\n\n{clean_actions}"

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
                    banned_terms=self.BANNED_CREATIVE_TERMS,
                )
            )
        else:
            logging.warning("Creative idea bank is unavailable.")
            
        banned_creative_terms_text = ", ".join(self.BANNED_CREATIVE_TERMS)
        
        prompt = f"""
Initialize a new RPG adventure using the following parameters.
CRITICAL INSTRUCTION: If any parameter below starts with "Unknown" or "None provided", you must creatively invent a fitting value for it. DO NOT use common AI fantasy names. Keep any parameters that are already provided by the player EXACTLY as they are.

CRITICAL NAMING BAN:
When inventing new names, do not use any of these names or obvious spelling, spacing, or hyphenation variants unless the player explicitly provided the name:
{banned_creative_terms_text}

When creating proper nouns, strongly prefer the injected creative inspiration samples or altered combinations of those samples.

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
Output the following tags to set up the starting gameplay state (making sure to apply **bold** formatting around the "Key Term" for each bulletpoint, if there is one. For example, describing the economy of a city probably would not start with "**City Economics**:", but rather it would all be a normal bulleted list. However, if there is a "Key Term" for a bulletpoint, make sure that it is bold, for example, "**Poison-Dart Frog**: This frog may be tiny, but its toxins are deadly and can kill an adult human in minutes." ):

[[WORLD_PROFILE:
# World

(Filled description, at most six paragraphs.)

## Culture, Customs, and Laws

- (Filled value)

## Economy

- (Filled value)

## Factions and Organizations

- (Filled value)

## Flora, Fauna, and Climate

- (Filled value)

## History

- (Filled value)

## Locations

- (Filled value)

## Magic and Religion

- (Filled value)

## NPCs

- (Filled value)

## Out-Of-Game Reminders

- **Focus:** (Filled value)
- **Genre:** (Filled value)
- **Setting:** (Filled value)
- **Species:** (Filled value)
- **Technology Level:** (Filled value)

## Rumors and Unconfirmed Information

- (Filled value)

## Uncategorized

- (Filled value)

]]

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
                        "\n[START GM-ONLY SECRET CONTEXT]\n"
                        "The following facts are available only to the Game Master for continuity, causality, and future setup.\n"
                        "They are NOT known by the player character and are NOT known by NPCs unless a specific visible reason exists.\n"
                        "Do not reveal these facts in narration, dialogue, UPDATE_WORLD, QUEST, or visible summaries unless the player discovers them in the current scene.\n\n"
                        f"{secret_content}\n"
                        f"[END GM-ONLY SECRET CONTEXT]\n"
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
    
    SUGGESTED_ACTION_MARKERS: ClassVar[tuple[str, ...]] = (
        "Possible Actions:",
        "Suggested Actions:",
        "### Actions",
        "What would you like to do?",
        "What do you do?",
        "What do you do now?",
    )

    def _split_response_sections(self, text: str | None) -> ResponseSections:
        """
        Splits an AI response into main narration and suggested actions.

        Suggested actions should not be treated as proof that the Player learned
        a fact, because they are model-generated convenience hints rather than
        events that happened in the fiction.

        Args:
            text: AI response text after functional tags have been removed.

        Returns:
            ResponseSections containing main narration and optional action text.
        """
        clean_text = str(text or "").strip()

        if not clean_text:
            logging.warning("AIManager._split_response_sections called with empty text.")
            return ResponseSections(main_body="")

        for marker in self.SUGGESTED_ACTION_MARKERS:
            if marker not in clean_text:
                continue

            main_body, suggested_actions = clean_text.split(marker, 1)
            suggested_actions = suggested_actions.strip()
            suggested_actions = suggested_actions.replace(" - ", "\n- ").replace(" * ", "\n* ")

            if suggested_actions.startswith("-") and not suggested_actions.startswith("- "):
                suggested_actions = "- " + suggested_actions[1:].lstrip()
            elif suggested_actions.startswith("*") and not suggested_actions.startswith("* "):
                suggested_actions = "* " + suggested_actions[1:].lstrip()

            return ResponseSections(
                main_body=main_body.strip(),
                action_marker=marker,
                suggested_actions=suggested_actions.strip(),
            )

        return ResponseSections(main_body=clean_text)

    def _infer_safe_descriptor(self, text: str | None) -> str:
        """
        Infers a safe unnamed descriptor from the current response.

        Args:
            text: Player-facing response text.

        Returns:
            A generic descriptor that does not reveal hidden proper nouns.
        """
        lowered_text = str(text or "").lower()

        descriptor_candidates = (
            "the scribe",
            "the librarian",
            "the clerk",
            "the merchant",
            "the guard",
            "the scout",
            "the caster",
            "the robed figure",
            "the armored woman",
            "the man",
            "the woman",
            "the figure",
        )

        for descriptor in descriptor_candidates:
            if descriptor in lowered_text:
                return descriptor

        return "that person"

    def _sanitize_blocked_player_terms(
        self,
        text: str | None,
        blocked_terms: set[str] | frozenset[str],
    ) -> str:
        """
        Removes unrevealed proper nouns from player-facing output.

        This is a final deterministic safety pass after tag processing. It prevents
        names from leaking through narration or suggested actions when the related
        UPDATE_WORLD or UPSERT_WORLD tag was rejected.

        Args:
            text: Player-facing text after functional tags have been removed.
            blocked_terms: Proper nouns rejected by the world-lore sanitizer.

        Returns:
            Sanitized player-facing text.
        """
        clean_text = str(text or "")

        if not clean_text.strip():
            return ""

        if not blocked_terms:
            return clean_text

        safe_descriptor = self._infer_safe_descriptor(clean_text)
        sanitized_text = clean_text

        for term in sorted(blocked_terms, key=len, reverse=True):
            clean_term = str(term or "").strip()

            if not clean_term:
                continue

            sanitized_text = re.sub(
                rf"\b{re.escape(clean_term)}\b",
                safe_descriptor,
                sanitized_text,
                flags=re.IGNORECASE,
            )

        return sanitized_text
    
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
        "Aethelgard",
        "Whisperwood",
        "Whisper-Wood",
        "Vaelan",
        "Vaelen",
        "Caelan",
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
    
    def _normalize_action_list_markdown(self, actions_text: str | None) -> str:
        """
        Converts suggested action text into a tight Markdown bullet list.

        Args:
            actions_text: Text following an action marker, such as "What do you do now?".

        Returns:
            A cleaned Markdown bullet list with one action per line and no blank
            lines between bullet items.
        """
        clean_text = str(actions_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()

        if not clean_text:
            logging.warning("AIManager._normalize_action_list_markdown received empty action text.")
            return ""

        # Normalize Unicode bullets into Markdown bullets.
        clean_text = re.sub(r"(?m)^[ \t]*[•‣]\s+", "- ", clean_text)
        clean_text = re.sub(r"\s+[•‣]\s+", "\n- ", clean_text)

        # Converts inline bullets like " - Explore - Return" into real Markdown lines.
        clean_text = re.sub(r"\s+([-*+])\s+", r"\n\1 ", clean_text)

        # Remove blank lines between bullet items so Markdown renders a tight list.
        clean_text = re.sub(
            r"(?m)^([ \t]*[-*+][ \t]+[^\n]+)\n[ \t]*\n(?=[ \t]*[-*+][ \t]+)",
            r"\1\n",
            clean_text,
        )

        normalized_lines: list[str] = []

        for raw_line in clean_text.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            if line.startswith(("•", "‣")):
                line = f"- {line[1:].lstrip()}"

            # Fix "-Explore" or "*Explore" if the model forgot the space.
            if line.startswith(("-", "*", "+")) and len(line) > 1 and line[1] != " ":
                line = f"{line[0]} {line[1:].lstrip()}"

            normalized_lines.append(line)

        normalized_text = "\n".join(normalized_lines).strip()

        if not normalized_text:
            logging.warning(
                "Action list normalization produced no display text from: %r",
                actions_text,
            )

        return normalized_text

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

        These rules protect against stale names and hidden-knowledge leakage while
        still encouraging the model to persist durable lore that the player actually
        learned during the visible scene.

        Returns:
            Prompt text for creative naming and player-facing lore safety.
        """
        banned_terms = ", ".join(self.BANNED_CREATIVE_TERMS)

        return (
            "\n[CREATIVE AND KNOWLEDGE SAFETY RULES]\n"
            f"- Do not invent or reuse these names unless they already refer to the same existing entity: {banned_terms}.\n"
            "- When inventing new names, avoid common generic fantasy defaults.\n"
            "- World.md is player-facing knowledge. Use [[UPDATE_WORLD: Section | Text To Add]] for durable facts the player actually learns in visible narration.\n"
            "- Important: partial player-known lore is enough for [[UPDATE_WORLD: ...]]. If the player learns that a named creature, plant, hazard, location, faction, custom, object, spell, or historical event exists and learns at least one useful visible fact about it, output an [[UPDATE_WORLD: ...]] tag.\n"
            "- Do not skip the visible/player-known part of a world update just because other details remain hidden.\n"
            "- If an NPC's true name, motive, allegiance, secret, or identity has not been revealed to the player, do not put that hidden information in [[UPDATE_WORLD: ...]].\n"
            "- If a world fact contains both visible information and GM-only information, split it: put visible information in [[UPDATE_WORLD: ...]] and hidden information in [[SECRET: ...]].\n"
            "- You may use [[UPDATE_WORLD: ...]] if it is reasonable for the Player to believe the information that they just learned. "
            "For example, if an NPC says that their name is Gregor, and the Player has not learned any information to the contrary, "
            "you may use the [[UPDATE_WORLD: ...]] tag for that. If you do, also output a [[SECRET: ...]] tag if that NPC has a different true name.\n"
            "- For unrevealed NPCs, use visible public descriptors such as 'the scarred dwarf clerk', 'the armored woman at the map table', or 'the hooded courier'.\n"
            "- Use [[SECRET: ...]] for GM-only facts that the player has not learned yet.\n"
            "- Before finalizing each response, check whether the player learned any new named world facts. "
            "If yes, output [[UPDATE_WORLD: Section | Text To Add]] for each durable player-known fact before [[STATUS: ...]].\n"
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
            
            threading.Thread(
                target=self._log_token_usage,
                args=(prompt, user_text, ai_text),
                daemon=True,
            ).start()
            
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
            display_without_tags = standard_tag_pattern.sub("", display_ai_text)

            # Only the actual narration should prove player knowledge.
            # Suggested actions must not count as "revealed" information.
            visible_narrative_for_tag_safety = self._split_response_sections(
                display_without_tags
            ).main_body

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
            
            for marker in trim_markers:
                if marker in final_display_text:
                    parts = final_display_text.split(marker, 1)
                    main_body = parts[0].strip()
                    options_string = parts[1].strip()
                    text_to_save = main_body

                    normalized_options = self._normalize_action_list_markdown(options_string)

                    if normalized_options:
                        # Important: two newlines before the list.
                        final_display_text = f"{main_body}\n\n**{marker}**\n\n{normalized_options}"
                    else:
                        final_display_text = f"{main_body}\n\n**{marker}**"

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
        self.world_lore_updater = WorldLoreUpdater()
        self.blocked_player_terms: set[str] = set()
        
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
    
    _GENERIC_WORLD_LORE_SUBTOPIC_WORDS: ClassVar[frozenset[str]] = frozenset(
        {
            "survival",
            "tactics",
            "warning",
            "signs",
            "field",
            "notes",
            "research",
            "uses",
            "behavior",
            "behaviors",
            "habitat",
            "weaknesses",
            "dangers",
            "hazards",
            "methods",
            "techniques",
            "precautions",
        }
    )
    
    _UNREVEALED_NAME_PHRASE_PATTERNS: ClassVar[tuple[str, ...]] = (
        r"\s*,?\s+(?:named|called|known as|going by)\s+{name}\b",
        r"\s*,?\s+whose name is\s+{name}\b",
        r"\s*,?\s+who introduces (?:himself|herself|themself|themselves) as\s+{name}\b",
    )
    
    def _record_blocked_player_terms(self, names: list[str]) -> None:
        """
        Records proper nouns that must not appear in player-facing text this turn.

        Args:
            names: Proper nouns rejected by the World lore sanitizer.
        """
        for name in names:
            clean_name = str(name or "").strip()

            if not clean_name:
                continue

            self.blocked_player_terms.add(clean_name)

            # If "Arch-Scribe Vane" was rejected, "Vane" should also be blocked.
            name_parts = clean_name.split()
            if len(name_parts) > 1:
                self.blocked_player_terms.add(name_parts[-1])
                
    def _is_generic_world_lore_subtopic_phrase(self, candidate: str | None) -> bool:
        """
        Determines whether a Title Case phrase is a generic lore subtopic.

        Args:
            candidate: Potential proper noun phrase found by the sanitizer.

        Returns:
            True if the phrase is likely a generic category, not a hidden name.
        """
        clean_candidate = str(candidate or "").strip()

        if not clean_candidate:
            return False

        words = [
            word.casefold()
            for word in re.split(r"[\s-]+", clean_candidate)
            if word.strip()
        ]

        if len(words) < 2 or len(words) > 4:
            return False

        return all(word in self._GENERIC_WORLD_LORE_SUBTOPIC_WORDS for word in words)
    
    def _process_upsert_world_tags(
        self,
        ai_text: str,
        *,
        visible_narrative_text: str,
    ) -> None:
        """
        Processes [[UPSERT_WORLD: Section | Anchor | Replacement Lore]] tags.

        Backward compatibility:
            [[UPSERT_WORLD: Anchor | Replacement Lore]]
            falls back to the Uncategorized section.

        Args:
            ai_text: Raw AI response text containing functional tags.
            visible_narrative_text: Player-facing narration after tag cleanup.
        """
        if not ai_text:
            logging.warning("TagParser._process_upsert_world_tags called with empty text.")
            return

        for match in re.finditer(r"\[\[UPSERT_WORLD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            raw_args = str(match.group(1) or "").strip()
            parts = [part.strip() for part in raw_args.split("|")]

            if len(parts) >= 3:
                section_name = parts[0]
                anchor = parts[1]
                replacement_lore = "|".join(parts[2:]).strip()
            elif len(parts) == 2:
                section_name = "Uncategorized"
                anchor = parts[0]
                replacement_lore = parts[1]
            else:
                logging.warning("Malformed UPSERT_WORLD tag ignored: %r", match.group(0))
                continue

            if not anchor or not replacement_lore:
                logging.warning("Malformed UPSERT_WORLD tag ignored: %r", match.group(0))
                continue

            try:
                world_panel = self.app.notebook_widgets.get("World")
                if world_panel is None:
                    logging.error("UPSERT_WORLD ignored because the World panel is missing.")
                    continue

                current_world_text = world_panel.get_text().rstrip()
                
                resolved_replacement_lore, replacement_existing_anchor = (
                    self.world_lore_updater.rewrite_lore_to_existing_anchor(
                        current_world_text,
                        replacement_lore,
                    )
                )

                resolved_anchor = (
                    replacement_existing_anchor
                    or self.world_lore_updater.resolve_existing_anchor(current_world_text, anchor)
                    or anchor
                )

                safe_replacement_lore = self._sanitize_update_world_lore(
                    resolved_replacement_lore,
                    visible_narrative_text=visible_narrative_text,
                    existing_world_text=current_world_text,
                )

                if not safe_replacement_lore:
                    logging.warning("UPSERT_WORLD rejected by world-lore sanitizer for anchor %r.", anchor)
                    continue

                updated_world_text = self.world_lore_updater.upsert(
                    current_world_text,
                    WorldUpsertRequest(
                        section_name=section_name,
                        anchor=resolved_anchor,
                        replacement_lore=safe_replacement_lore,
                    ),
                )

                if updated_world_text is None:
                    continue

                world_panel.set_text(updated_world_text)
                world_panel.save_now()

            except Exception as error:
                logging.exception("Could not process UPSERT_WORLD tag: %s", error)
    
    def _replace_internal_base_unit_language(self, text: str) -> str:
        """
        Replaces leaked internal 'base unit' wording with the world's actual base currency name.

        Args:
            text: AI response text.

        Returns:
            Text with player-facing currency wording.
        """
        if not text:
            return ""

        player = getattr(self.app, "player", None)
        if player is None or not hasattr(player, "get_base_currency_name"):
            logging.warning("Could not replace base-unit wording because Player currency helper is unavailable.")
            return text

        singular_name = player.get_base_currency_name(1)
        plural_name = player.get_base_currency_name(2)

        cleaned_text = re.sub(
            r"\b1\s+base unit\b",
            f"1 {singular_name}",
            text,
            flags=re.IGNORECASE,
        )
        cleaned_text = re.sub(
            r"\bone\s+base unit\b",
            f"one {singular_name}",
            cleaned_text,
            flags=re.IGNORECASE,
        )
        cleaned_text = re.sub(
            r"\bbase units\b",
            plural_name,
            cleaned_text,
            flags=re.IGNORECASE,
        )
        cleaned_text = re.sub(
            r"\bbase unit\b",
            singular_name,
            cleaned_text,
            flags=re.IGNORECASE,
        )

        return cleaned_text
    
    def _cleanup_repaired_lore_text(self, lore_text: str) -> str:
        """
        Cleans punctuation and spacing after removing unsafe hidden-name clauses.

        Args:
            lore_text: Lore text after redaction.

        Returns:
            Cleaned lore text.
        """
        repaired_text = str(lore_text or "").strip()

        repaired_text = re.sub(r"\s+([.,;:])", r"\1", repaired_text)
        repaired_text = re.sub(r"\s{2,}", " ", repaired_text)
        repaired_text = re.sub(r"\s+\.", ".", repaired_text)
        repaired_text = re.sub(r",\s*\.", ".", repaired_text)

        return repaired_text.strip()


    def _repair_update_world_lore(
        self,
        lore_text: str,
        unrevealed_names: list[str],
        *,
        visible_narrative_text: str,
        existing_world_text: str,
    ) -> str:
        """
        Attempts to salvage an UPDATE_WORLD tag by removing only unsafe hidden-name clauses.

        Example:
            "The library is managed by a librarian named Orrin."
            becomes:
            "The library is managed by a librarian."

        Args:
            lore_text: Original UPDATE_WORLD text.
            unrevealed_names: Proper nouns that were not visible to the player.
            visible_narrative_text: Player-facing narration for this response.
            existing_world_text: Current World panel contents.

        Returns:
            Repaired lore text, or an empty string if the update is still unsafe.
        """
        repaired_lore = str(lore_text or "").strip()

        if not repaired_lore or not unrevealed_names:
            return ""

        for name in sorted(unrevealed_names, key=len, reverse=True):
            escaped_name = re.escape(name)

            for pattern_template in self._UNREVEALED_NAME_PHRASE_PATTERNS:
                repaired_lore = re.sub(
                    pattern_template.format(name=escaped_name),
                    "",
                    repaired_lore,
                    flags=re.IGNORECASE,
                )

        repaired_lore = self._cleanup_repaired_lore_text(repaired_lore)

        if not repaired_lore or repaired_lore == lore_text.strip():
            return ""

        # Re-run the same safety check. If anything suspicious remains, reject it.
        remaining_unrevealed_names = self._find_unrevealed_proper_nouns(
            repaired_lore,
            visible_narrative_text=visible_narrative_text,
            existing_world_text=existing_world_text,
        )

        if remaining_unrevealed_names:
            logging.warning(
                "Repaired UPDATE_WORLD still contains unrevealed proper noun(s): %s. Lore: %r",
                ", ".join(remaining_unrevealed_names),
                repaired_lore,
            )
            return ""

        if len(repaired_lore) < 20:
            logging.warning("Repaired UPDATE_WORLD became too short to be useful: %r", repaired_lore)
            return ""

        return repaired_lore
    
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
            ignored_names_lower = {name.casefold() for name in ignored_names}

            if (
                not candidate
                or candidate.casefold() in ignored_names_lower
                or self._is_generic_world_lore_subtopic_phrase(candidate)
            ):
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
            self._record_blocked_player_terms(unrevealed_names)
            repaired_lore = self._repair_update_world_lore(
                clean_lore,
                unrevealed_names,
                visible_narrative_text=visible_narrative_text,
                existing_world_text=existing_world_text,
            )

            if repaired_lore:
                logging.warning(
                    "Repaired UPDATE_WORLD by removing unrevealed proper noun(s): %s. Original: %r Repaired: %r",
                    ", ".join(unrevealed_names),
                    clean_lore,
                    repaired_lore,
                )
                return repaired_lore

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

                normalized_world_md = self.world_lore_updater.ensure_world_sections(new_world_md)

                world_panel.set_text(normalized_world_md)
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
                    
        # Process replacement-style world updates before append-only updates.
        self._process_upsert_world_tags(
            ai_text,
            visible_narrative_text=visible_narrative_text,
        )
                    
        for match in re.finditer(r"\[\[UPDATE_WORLD:\s*(.*?)\]\]", ai_text, re.DOTALL):
            raw_args = str(match.group(1) or "").strip()

            if not raw_args:
                continue

            parts = [part.strip() for part in raw_args.split("|", 1)]

            if len(parts) == 2:
                section_name, new_world_lore = parts
            else:
                section_name = "Uncategorized"
                new_world_lore = parts[0]

            if not new_world_lore:
                continue

            try:
                world_panel = self.app.notebook_widgets.get("World")
                if world_panel is None:
                    logging.error("UPDATE_WORLD ignored because the World panel is missing.")
                    continue

                current_world_text = world_panel.get_text().rstrip()

                resolved_world_lore, existing_anchor = (
                    self.world_lore_updater.rewrite_lore_to_existing_anchor(
                        current_world_text,
                        new_world_lore,
                    )
                )

                safe_world_lore = self._sanitize_update_world_lore(
                    resolved_world_lore,
                    visible_narrative_text=visible_narrative_text,
                    existing_world_text=current_world_text,
                )

                if not safe_world_lore:
                    continue

                if existing_anchor:
                    updated_world_text = self.world_lore_updater.upsert(
                        current_world_text,
                        WorldUpsertRequest(
                            section_name=section_name,
                            anchor=existing_anchor,
                            replacement_lore=safe_world_lore,
                        ),
                    )
                else:
                    updated_world_text = self.world_lore_updater.append_to_section(
                        current_world_text,
                        section_name,
                        safe_world_lore,
                    )

                if updated_world_text is None:
                    continue

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
            Opens the structured merchant dialog instead of rendering a text table.

            Merchant entry format:
                "Item Name | Description | PriceBaseUnits | Quantity"
                "Item Name | Description | PriceBaseUnits | Quantity | Optional Item Type"
            """

            raw_data = match.group(1).strip()
            mode, merchant_items = MerchantTagParser.parse(raw_data)

            if not merchant_items:
                logging.warning("MERCHANT tag contained no valid merchant entries: %r", raw_data)
                return "\n*(Merchant shop could not be opened because no valid items were provided.)*\n"

            if is_history:
                item_summary = ", ".join(
                    f"{item.name} ({self.app.player.get_formatted_currency(item.price_base_units)})"
                    for item in merchant_items
                )
                return f"\n*(OOG: A merchant offered: {item_summary}.)*\n"

            def open_shop() -> None:
                try:
                    window = getattr(self.app, "win", None)
                    if window is None or not hasattr(window, "open_merchant_dialog"):
                        logging.error("Cannot open merchant dialog because MainWindow is unavailable.")
                        return

                    window.open_merchant_dialog(merchant_items, mode=mode)

                except Exception as error:
                    logging.exception("Failed to open merchant dialog: %s", error)

            try:
                self.app.after(0, open_shop)
            except Exception as error:
                logging.exception("Failed to schedule merchant dialog: %s", error)

            return "\n*(Merchant shop opened.)*\n"
                
        # Find all instances of [[DISPLAY_CURRENCY: X]] and swap them
        modified_text = re.sub(r"\[\[DISPLAY_CURRENCY:\s*(-?\d+)\]\]", replace_currency, ai_text)
        modified_text = re.sub(r"\[\[MERCHANT:\s*(.*?)\]\]", replace_merchant, modified_text, flags=re.DOTALL)
        modified_text = self._replace_internal_base_unit_language(modified_text)
        
        return modified_text
    


@dataclass(frozen=True)
class WorldUpsertRequest:
    """
    Represents a restricted World.md upsert request.

    Args:
        anchor: Human-readable entity key to find, such as "Bob" or "Dockside Library".
        replacement_lore: Full replacement lore line or paragraph.
    """

    section_name: str
    anchor: str
    replacement_lore: str


class WorldLoreUpdater:
    """
    Applies safe, deterministic World.md lore upserts.

    This class never accepts file paths, regex patterns, or raw write instructions
    from the AI. It only searches existing Markdown text for an entity-style key
    and replaces that one entry, or appends the replacement if no entry exists.
    """

    MAX_ANCHOR_LENGTH: ClassVar[int] = 80
    MAX_REPLACEMENT_LENGTH: ClassVar[int] = 900
    
    WORLD_SECTIONS: ClassVar[tuple[str, ...]] = (
        "NPCs",
        "Locations",
        "Factions and Organizations",
        "History",
        "Culture, Customs, and Laws",
        "Economy",
        "Magic and Religion",
        "Rumors and Unconfirmed Information",
        "Uncategorized",
        "Flora, Fauna, and Climate",
        "Out-Of-Game Reminders"
    )

    SECTION_ALIASES: ClassVar[dict[str, str]] = {
        "npc": "NPCs",
        "npcs": "NPCs",
        "people": "NPCs",
        "person": "NPCs",
        "character": "NPCs",
        "characters": "NPCs",
        "location": "Locations",
        "locations": "Locations",
        "place": "Locations",
        "places": "Locations",
        "shop": "Locations",
        "shops": "Locations",
        "faction": "Factions and Organizations",
        "factions": "Factions and Organizations",
        "organization": "Factions and Organizations",
        "organizations": "Factions and Organizations",
        "guild": "Factions and Organizations",
        "guilds": "Factions and Organizations",
        "history": "History",
        "historical lore": "History",
        "culture": "Culture, Customs, and Laws",
        "customs": "Culture, Customs, and Laws",
        "laws": "Culture, Customs, and Laws",
        "economy": "Economy",
        "currency": "Economy",
        "trade": "Economy",
        "magic": "Magic and Religion",
        "religion": "Magic and Religion",
        "pantheon": "Magic and Religion",
        "rumor": "Rumors and Unconfirmed Information",
        "rumors": "Rumors and Unconfirmed Information",
        "unconfirmed": "Rumors and Unconfirmed Information",
        "uncategorized": "Uncategorized",
        "animal": "Flora, Fauna, and Climate",
        "plant": "Flora, Fauna, and Climate",
        "beast": "Flora, Fauna, and Climate",
        "storm": "Flora, Fauna, and Climate",
        "weather": "Flora, Fauna, and Climate",
        "oog": "Out-Of-Game Reminders",
        "out-of-game": "Out-Of-Game Reminders",
        "out-of-game-reminders": "Out-Of-Game Reminders",
        "out of game reminders": "Out-Of-Game Reminders",
        "out-of-game reminders": "Out-Of-Game Reminders",
        "out of game": "Out-Of-Game Reminders",
    }

    _NESTED_TAG_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\[\[.*?\]\]",
        re.DOTALL,
    )
    
    _LIST_ITEM_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?P<indent>\s*)(?:[-*+]\s+|\d+\.\s+)"
    )

    _HEADING_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^\s*#{1,6}\s+"
    )

    _BULLET_PREFIX_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?P<prefix>\s*(?:[-*+]\s+|\d+\.\s+)?)"
    )

    _MARKDOWN_DECORATION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"[*_`#>\[\]()]"
    )
    
    _KEY_MARKDOWN_DECORATION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"[*_`#>\[\]]"
    )

    _PARENTHETICAL_SUFFIX_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\s*(?:\([^)]{1,80}\)|\[[^\]]{1,80}\])\s*$"
    )
    
    _SECTION_HEADING_LINE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^\s*##\s+(?P<section>.+?)\s*$"
    )

    _EMPTY_SECTION_PLACEHOLDER_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^\s*\\?[-*+]\s+(?:None so far\.?|None\.?|N/A)\s*$",
        re.IGNORECASE,
    )
    
    def _canonical_section_name_or_none(self, section_name: str | None) -> str | None:
        """
        Resolves a Markdown section heading to a canonical World.md section name.

        Args:
            section_name: Raw section heading text.

        Returns:
            Canonical section name when the heading is known, otherwise None.
        """
        clean_section = str(section_name or "").strip()

        if not clean_section:
            logging.warning("Blank World section heading received.")
            return None

        normalized_key = re.sub(r"\s+", " ", clean_section).casefold().strip()
        canonical_section = self.SECTION_ALIASES.get(normalized_key)

        if canonical_section:
            return canonical_section

        for section in self.WORLD_SECTIONS:
            if section.casefold() == normalized_key:
                return section

        return None

    def normalize_section_name(self, section_name: str | None) -> str:
        """
        Resolves an AI-provided section name to a canonical World.md section.

        Args:
            section_name: Raw section name from a world tag.

        Returns:
            Canonical section name, falling back to 'Uncategorized'.
        """
        canonical_section = self._canonical_section_name_or_none(section_name)
        if canonical_section:
            return canonical_section

        if canonical_section:
            return canonical_section
        
        logging.warning("Unknown World section %r. Falling back to Uncategorized.", section_name)
        return "Uncategorized"
    
    def _canonicalize_world_section_headings(self, world_text: str | None) -> str:
        """
        Rewrites known World.md section heading aliases to their canonical names.

        Args:
            world_text: Current World.md text.

        Returns:
            World.md text with recognized section headings normalized.
        """
        text = str(world_text or "")

        if not text.strip():
            logging.warning("Cannot canonicalize empty World.md text.")
            return ""

        output_lines: list[str] = []

        for line in text.splitlines():
            heading_match = self._SECTION_HEADING_LINE_PATTERN.match(line)

            if heading_match is None:
                output_lines.append(line)
                continue

            raw_section = heading_match.group("section").strip()
            canonical_section = self._canonical_section_name_or_none(raw_section)

            if canonical_section is None:
                output_lines.append(line)
                continue

            if canonical_section != raw_section:
                logging.info(
                    "Canonicalized World.md section heading %r to %r.",
                    raw_section,
                    canonical_section,
                )

            output_lines.append(f"## {canonical_section}")

        return "\n".join(output_lines)
    
    def migrate_legacy_world_text(self, world_text: str | None) -> str:
        """
        Wraps old unsectioned World.md text into World Overview, then ensures sections.

        Args:
            world_text: Existing World.md text.

        Returns:
            Sectioned World.md text.
        """
        text = str(world_text or "").strip()

        if not text:
            return self.ensure_world_sections("# World")

        has_level_two_section = re.search(r"(?m)^##\s+", text) is not None
        if has_level_two_section:
            return self.ensure_world_sections(text)

        text = re.sub(r"(?im)^#\s+World\s*$", "", text).strip()

        migrated_text = (
            "# World\n\n"
            f"{text}\n"
        )

        return self.ensure_world_sections(migrated_text)

    def ensure_world_sections(self, world_text: str | None) -> str:
        """
        Ensures World.md has a top-level title and every expected section.

        Args:
            world_text: Current World.md text.

        Returns:
            Markdown text containing all expected sections.
        """
        text = str(world_text or "").strip()

        if not text:
            text = "# World"

        if not re.search(r"(?im)^#\s+World\s*$", text):
            text = f"# World\n\n{text}"

        text = self._canonicalize_world_section_headings(text)

        for section in self.WORLD_SECTIONS:
            section_pattern = re.compile(
                rf"(?im)^##\s+{re.escape(section)}\s*$"
            )

            if section_pattern.search(text) is None:
                text = f"{text.rstrip()}\n\n## {section}\n"

        return text.rstrip() + "\n"


    def append_to_section(
        self,
        world_text: str | None,
        section_name: str | None,
        lore_text: str | None,
    ) -> str | None:
        """
        Appends lore under a canonical World.md section.

        Args:
            world_text: Current World.md text.
            section_name: Target section from the tag.
            lore_text: Player-known lore to append.

        Returns:
            Updated World.md text, or None if lore is blank.
        """
        clean_lore = self._clean_replacement_lore(lore_text)
        if not clean_lore:
            logging.warning("Rejected UPDATE_WORLD because lore was blank or invalid.")
            return None

        canonical_section = self.normalize_section_name(section_name)
        text = self.migrate_legacy_world_text(world_text)

        entry = clean_lore
        if not re.match(r"^\s*(?:[-*+]\s+|\d+\.\s+)", entry):
            entry = f"- {entry}"

        updated_text = self._insert_entry_under_section(text, canonical_section, entry)
        return self.sort_section_entries(updated_text, canonical_section)


    def _insert_entry_under_section(
        self,
        world_text: str,
        section_name: str,
        entry_text: str,
    ) -> str:
        """
        Inserts a single entry beneath a level-2 Markdown heading.

        Args:
            world_text: Normalized World.md text.
            section_name: Canonical section name.
            entry_text: Lore entry to insert.

        Returns:
            Updated World.md text.
        """
        section_pattern = re.compile(
            rf"(?im)^##\s+{re.escape(section_name)}\s*$"
        )

        section_match = section_pattern.search(world_text)
        if section_match is None:
            logging.warning(
                "Section %r missing after section normalization. Appending to Uncategorized.",
                section_name,
            )
            return self._insert_entry_under_section(
                self.ensure_world_sections(world_text),
                "Uncategorized",
                entry_text,
            )

        next_section_match = re.search(
            r"(?m)^##\s+",
            world_text[section_match.end():],
        )

        insert_index = (
            section_match.end() + next_section_match.start()
            if next_section_match is not None
            else len(world_text)
        )

        before = world_text[:insert_index].rstrip()
        after = world_text[insert_index:].lstrip()

        if after:
            return f"{before}\n\n{entry_text.rstrip()}\n\n{after}".rstrip() + "\n"

        return f"{before}\n\n{entry_text.rstrip()}\n"
    
    def upsert(self, world_text: str | None, request: WorldUpsertRequest | None) -> str | None:
        """
        Applies a validated lore upsert to World.md text.

        Args:
            world_text: Current World.md text.
            request: Restricted upsert request from the tag parser.

        Returns:
            Updated World.md text, or None if the request was invalid or made no change.
        """
        if request is None:
            logging.warning("WorldLoreUpdater.upsert called without a request.")
            return None

        anchor = self._clean_anchor(request.anchor)
        replacement_lore = self._clean_replacement_lore(request.replacement_lore)
        canonical_section = self.normalize_section_name(request.section_name)

        if not anchor or not replacement_lore:
            logging.warning(
                "Rejected UPSERT_WORLD because anchor or replacement was blank. Anchor=%r Replacement=%r",
                request.anchor,
                request.replacement_lore,
            )
            return None

        anchor_key = self._normalize_key(anchor)
        if not anchor_key:
            logging.warning("Rejected UPSERT_WORLD because anchor normalized to blank: %r", anchor)
            return None

        current_text = self.ensure_world_sections(world_text)
        lines = current_text.splitlines()

        match_range = self._find_matching_entry_range(lines, anchor_key)

        if match_range is None:
            logging.info("UPSERT_WORLD found no existing entry; appending lore under %s.", canonical_section)
            return self.append_to_section(current_text, canonical_section, replacement_lore)

        start_index, end_index = match_range
        old_entry = "\n".join(lines[start_index:end_index])
        old_first_line = lines[start_index]

        replacement_entry = self._preserve_list_prefix(old_first_line, replacement_lore)
        replacement_lines = replacement_entry.splitlines() or [replacement_entry]

        if old_entry.strip() == "\n".join(replacement_lines).strip():
            logging.info("UPSERT_WORLD made no change for anchor %r.", anchor)
            return None

        lines[start_index:end_index] = replacement_lines

        logging.info(
            "UPSERT_WORLD replaced entry for anchor %r across %s line(s).",
            anchor,
            end_index - start_index,
        )

        updated_text = "\n".join(lines).rstrip() + "\n"
        actual_section = self._find_section_name_for_line_index(lines, start_index)

        return self.sort_section_entries(updated_text, actual_section)

    def _clean_anchor(self, anchor: str | None) -> str:
        """
        Cleans and validates the AI-provided anchor.

        Args:
            anchor: Raw anchor text.

        Returns:
            Safe anchor text, or an empty string if invalid.
        """
        clean_anchor = str(anchor or "").strip()

        if not clean_anchor:
            return ""

        if "\n" in clean_anchor or "\r" in clean_anchor:
            logging.warning("Rejected UPSERT_WORLD anchor containing a newline: %r", anchor)
            return ""

        if len(clean_anchor) > self.MAX_ANCHOR_LENGTH:
            logging.warning("Rejected UPSERT_WORLD anchor that was too long: %r", anchor)
            return ""

        if self._NESTED_TAG_PATTERN.search(clean_anchor):
            logging.warning("Rejected UPSERT_WORLD anchor containing a nested tag: %r", anchor)
            return ""

        return clean_anchor
    
    def sort_section_entries(self, world_text: str | None, section_name: str | None) -> str:
        """
        Alphabetizes top-level bullet entries inside one World.md section.

        Multiline entries are kept together, so wrapped descriptions are not
        separated from their bulletpoint.

        Args:
            world_text: Current World.md text.
            section_name: Section whose entries should be sorted.

        Returns:
            World.md text with the target section alphabetized.
        """
        text = self.ensure_world_sections(world_text)
        canonical_section = self.normalize_section_name(section_name)

        section_pattern = re.compile(
            rf"(?im)^##\s+{re.escape(canonical_section)}\s*$"
        )
        section_match = section_pattern.search(text)

        if section_match is None:
            logging.warning(
                "Could not sort World.md section because it was not found: %s",
                canonical_section,
            )
            return text

        next_section_match = re.search(
            r"(?m)^##\s+",
            text[section_match.end():],
        )

        section_end = (
            section_match.end() + next_section_match.start()
            if next_section_match is not None
            else len(text)
        )

        before_section_body = text[:section_match.end()]
        section_body = text[section_match.end():section_end]
        after_section_body = text[section_end:]

        sorted_body = self._sort_section_body(section_body)

        return (
            f"{before_section_body.rstrip()}\n\n"
            f"{sorted_body.rstrip()}\n\n"
            f"{after_section_body.lstrip()}"
        ).rstrip() + "\n"

    def _sort_section_body(self, section_body: str | None) -> str:
        """
        Sorts bullet entry blocks inside a section body.

        Args:
            section_body: Text between one level-2 heading and the next.

        Returns:
            Sorted section body.
        """
        lines = str(section_body or "").strip("\n").splitlines()

        if not lines:
            return ""

        preamble_lines: list[str] = []
        trailing_lines: list[str] = []
        entry_blocks: list[list[str]] = []

        index = 0
        saw_entry = False

        while index < len(lines):
            line = lines[index]

            if self._LIST_ITEM_PATTERN.match(line or ""):
                saw_entry = True
                end_index = self._find_entry_end_index(lines, index)
                entry_blocks.append(lines[index:end_index])
                index = end_index
                continue

            if saw_entry:
                trailing_lines.append(line)
            else:
                preamble_lines.append(line)

            index += 1

        if not entry_blocks:
            return "\n".join(lines).strip()

        # Remove escaped or real "- None so far." placeholders once real entries exist.
        preamble_lines = [
            line for line in preamble_lines
            if not self._EMPTY_SECTION_PLACEHOLDER_PATTERN.match(line or "")
        ]
        trailing_lines = [
            line for line in trailing_lines
            if not self._EMPTY_SECTION_PLACEHOLDER_PATTERN.match(line or "")
        ]

        sorted_entries = sorted(
            entry_blocks,
            key=self._get_entry_sort_key,
        )

        output_lines: list[str] = []

        output_lines.extend(line for line in preamble_lines if str(line or "").strip())

        if output_lines:
            output_lines.append("")

        for block in sorted_entries:
            clean_block = [line.rstrip() for line in block if line is not None]

            if not clean_block:
                continue

            output_lines.extend(clean_block)
            output_lines.append("")

        output_lines.extend(line for line in trailing_lines if str(line or "").strip())

        return "\n".join(output_lines).strip()

    def _get_entry_sort_key(self, entry_block: list[str]) -> tuple[str, str]:
        """
        Builds a stable alphabetical sort key for one World.md bullet entry.

        Args:
            entry_block: Full Markdown entry block.

        Returns:
            Tuple used by sorted().
        """
        first_line = entry_block[0] if entry_block else ""
        display_key = self._extract_sort_display_key(first_line)

        return self._normalize_key(display_key), "\n".join(entry_block).casefold()

    def _extract_sort_display_key(self, line: str | None) -> str:
        """
        Extracts the visible key used for alphabetical sorting.

        Args:
            line: First line of a Markdown entry.

        Returns:
            Sortable visible key.
        """
        clean_line = str(line or "").strip()

        if not clean_line:
            return ""

        clean_line = re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)", "", clean_line)

        if ":" in clean_line:
            clean_line = clean_line.split(":", 1)[0]

        clean_line = self._MARKDOWN_DECORATION_PATTERN.sub("", clean_line)
        clean_line = re.sub(r"\s+", " ", clean_line)

        return clean_line.strip()

    def _find_section_name_for_line_index(
        self,
        lines: list[str],
        target_index: int,
    ) -> str:
        """
        Finds the nearest World.md section heading above a line index.

        Args:
            lines: World.md split into lines.
            target_index: Line index inside the section.

        Returns:
            Canonical section name.
        """
        safe_index = max(0, min(target_index, len(lines) - 1))

        for index in range(safe_index, -1, -1):
            match = self._SECTION_HEADING_LINE_PATTERN.match(lines[index] or "")

            if match is not None:
                return self.normalize_section_name(match.group("section"))

        logging.warning(
            "Could not determine section for World.md line index %s. Using Uncategorized.",
            target_index,
        )
        return "Uncategorized"

    def _clean_replacement_lore(self, replacement_lore: str | None) -> str:
        """
        Cleans and validates replacement lore.

        Args:
            replacement_lore: Raw replacement lore from the tag.

        Returns:
            Safe replacement lore, or an empty string if invalid.
        """
        clean_lore = str(replacement_lore or "").strip()

        if not clean_lore:
            return ""

        if len(clean_lore) > self.MAX_REPLACEMENT_LENGTH:
            logging.warning("Rejected UPSERT_WORLD replacement that was too long.")
            return ""

        if self._NESTED_TAG_PATTERN.search(clean_lore):
            logging.warning("Rejected UPSERT_WORLD replacement containing a nested tag: %r", clean_lore)
            return ""

        return clean_lore

    def _find_matching_line_index(self, lines: list[str], anchor_key: str) -> int | None:
        """
        Finds the first World.md line whose entity key matches the anchor.

        Args:
            lines: World.md split into lines.
            anchor_key: Normalized anchor key.

        Returns:
            Matching line index, or None.
        """
        for index, line in enumerate(lines):
            line_key = self._extract_line_key(line)
            if line_key == anchor_key:
                return index

        return None
    
    def _find_matching_entry_range(
        self,
        lines: list[str],
        anchor_key: str,
    ) -> tuple[int, int] | None:
        """
        Finds the full Markdown entry range for an anchor.

        This handles World.md entries that QTextEdit.toMarkdown() has wrapped
        across multiple physical lines.

        Args:
            lines: World.md split into physical lines.
            anchor_key: Normalized anchor key.

        Returns:
            A tuple of (start_index, end_index), where end_index is exclusive,
            or None if no matching entry was found.
        """
        if not lines:
            logging.warning("WorldLoreUpdater._find_matching_entry_range received no lines.")
            return None

        if not anchor_key:
            logging.warning("WorldLoreUpdater._find_matching_entry_range received a blank anchor key.")
            return None

        for index, line in enumerate(lines):
            line_key = self._extract_line_key(line)

            if line_key == anchor_key:
                return index, self._find_entry_end_index(lines, index)

        return None

    def _find_entry_end_index(self, lines: list[str], start_index: int) -> int:
        """
        Finds where a Markdown list entry ends.

        Continuation lines are included until the next heading, the next same-level
        list item, or the end of the document.

        Args:
            lines: World.md split into physical lines.
            start_index: Index of the first line of the matched entry.

        Returns:
            Exclusive end index for the entry.
        """
        if start_index < 0 or start_index >= len(lines):
            logging.warning(
                "WorldLoreUpdater._find_entry_end_index received invalid start index: %s",
                start_index,
            )
            return max(0, min(len(lines), start_index + 1))

        start_line = lines[start_index]
        start_match = self._LIST_ITEM_PATTERN.match(start_line or "")

        if start_match:
            start_indent_length = len(start_match.group("indent"))
        else:
            start_indent_length = len(start_line) - len(start_line.lstrip())

        index = start_index + 1

        while index < len(lines):
            current_line = lines[index]

            if self._is_entry_boundary(current_line, start_indent_length):
                return index

            if not str(current_line or "").strip():
                next_index = self._find_next_nonblank_line_index(lines, index + 1)

                if next_index is None:
                    return index

                if self._is_entry_boundary(lines[next_index], start_indent_length):
                    return index

            index += 1

        return index

    def _find_next_nonblank_line_index(
        self,
        lines: list[str],
        start_index: int,
    ) -> int | None:
        """
        Finds the next nonblank line.

        Args:
            lines: World.md split into physical lines.
            start_index: Index to begin searching from.

        Returns:
            The next nonblank line index, or None.
        """
        for index in range(max(0, start_index), len(lines)):
            if str(lines[index] or "").strip():
                return index

        return None

    def _is_entry_boundary(self, line: str | None, start_indent_length: int) -> bool:
        """
        Determines whether a line begins a new Markdown entry or heading.

        Args:
            line: The line to inspect.
            start_indent_length: Indentation of the original matched list item.

        Returns:
            True if the line should end the current entry.
        """
        line_text = str(line or "")

        if self._HEADING_PATTERN.match(line_text):
            return True

        list_match = self._LIST_ITEM_PATTERN.match(line_text)

        if list_match is None:
            return False

        return len(list_match.group("indent")) <= start_indent_length

    def resolve_existing_anchor(self, world_text: str | None, proposed_anchor: str | None) -> str | None:
        """
        Resolves an AI-provided anchor to an existing World.md entry key.

        This catches cases like:
            "Glass-Gales (Survival Tactics)" -> "Glass-Gales"

        Args:
            world_text: Current World.md text.
            proposed_anchor: AI-provided anchor or lore key.

        Returns:
            The existing World.md display key, or None if no safe match exists.
        """
        clean_anchor = self._clean_display_key(proposed_anchor)

        if not clean_anchor:
            return None

        candidate_keys = self._build_anchor_candidate_keys(clean_anchor)
        if not candidate_keys:
            return None

        current_text = self.ensure_world_sections(world_text)
        lines = current_text.splitlines()

        for line in lines:
            existing_key = self._extract_display_line_key(line)
            if not existing_key:
                continue

            existing_normalized = self._normalize_key(existing_key)

            if existing_normalized in candidate_keys:
                return existing_key

        return None

    def rewrite_lore_to_existing_anchor(
        self,
        world_text: str | None,
        lore_text: str | None,
    ) -> tuple[str, str | None]:
        """
        Rewrites the lore entry key to an existing World.md anchor when possible.

        Args:
            world_text: Current World.md text.
            lore_text: AI-provided lore text.

        Returns:
            Tuple of rewritten lore text and resolved anchor. The anchor is None
            if the lore does not match an existing World.md entry.
        """
        clean_lore = str(lore_text or "").strip()

        if not clean_lore:
            return "", None

        lore_key = self._extract_display_line_key(clean_lore)
        if not lore_key:
            return clean_lore, None

        existing_anchor = self.resolve_existing_anchor(world_text, lore_key)
        if existing_anchor is None:
            return clean_lore, None

        return self._replace_lore_key(clean_lore, existing_anchor), existing_anchor

    def _build_anchor_candidate_keys(self, anchor: str | None) -> set[str]:
        """
        Builds normalized candidate keys for matching an AI anchor to World.md.

        Args:
            anchor: Raw or cleaned anchor text.

        Returns:
            Normalized candidate keys.
        """
        clean_anchor = self._clean_display_key(anchor)
        if not clean_anchor:
            return set()

        candidates = {self._normalize_key(clean_anchor)}

        without_suffix = self._strip_contextual_anchor_suffix(clean_anchor)
        if without_suffix:
            candidates.add(self._normalize_key(without_suffix))

        return {candidate for candidate in candidates if candidate}

    def _strip_contextual_anchor_suffix(self, anchor: str | None) -> str:
        """
        Removes parenthetical/bracketed subtopic suffixes from an anchor.

        Args:
            anchor: Anchor text such as "Glass-Gales (Survival Tactics)".

        Returns:
            Anchor without the contextual suffix.
        """
        clean_anchor = self._clean_display_key(anchor)
        if not clean_anchor:
            return ""

        previous_value = None
        current_value = clean_anchor

        while previous_value != current_value:
            previous_value = current_value
            current_value = self._PARENTHETICAL_SUFFIX_PATTERN.sub("", current_value).strip()

        return current_value

    def _extract_display_line_key(self, line: str | None) -> str:
        """
        Extracts the visible key before the first colon in a Markdown entry.

        Args:
            line: Markdown line or lore entry.

        Returns:
            Display key without bullet markers or Markdown decoration.
        """
        clean_line = str(line or "").strip()

        if not clean_line or ":" not in clean_line:
            return ""

        clean_line = re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)", "", clean_line)
        raw_key = clean_line.split(":", 1)[0]

        return self._clean_display_key(raw_key)

    def _clean_display_key(self, value: str | None) -> str:
        """
        Cleans Markdown decoration from a display key.

        Args:
            value: Raw key text.

        Returns:
            Human-readable key text.
        """
        clean_value = str(value or "").strip()
        clean_value = self._KEY_MARKDOWN_DECORATION_PATTERN.sub("", clean_value)
        clean_value = re.sub(r"\s+", " ", clean_value)

        return clean_value.strip(" :")

    def _replace_lore_key(self, lore_text: str, replacement_key: str) -> str:
        """
        Replaces the first lore-entry key with a known existing World.md key.

        Args:
            lore_text: AI-provided lore entry.
            replacement_key: Existing World.md key to use.

        Returns:
            Lore entry using the existing key.
        """
        clean_replacement = self._clean_display_key(replacement_key)
        if not clean_replacement:
            return lore_text

        key_pattern = re.compile(
            r"^(?P<prefix>\s*(?:[-*+]\s+|\d+\.\s+)?)\s*"
            r"(?P<key>[^:\n]+)"
            r"(?P<colon>\s*:)",
            re.MULTILINE,
        )

        return key_pattern.sub(
            lambda match: f"{match.group('prefix')}{clean_replacement}{match.group('colon')}",
            lore_text,
            count=1,
        )
    
    def _extract_line_key(self, line: str | None) -> str:
        """
        Extracts an entity key from a World.md line.

        Examples:
            "Bob: Trusted officer." -> "bob"
            "- Bob: Trusted officer." -> "bob"
            "**Bob:** Trusted officer." -> "bob"

        Args:
            line: Markdown line.

        Returns:
            Normalized entity key, or an empty string if no key exists.
        """
        clean_line = str(line or "").strip()

        if not clean_line or ":" not in clean_line:
            return ""

        clean_line = re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)", "", clean_line)
        raw_key = clean_line.split(":", 1)[0]

        return self._normalize_key(raw_key)

    def _normalize_key(self, value: str | None) -> str:
        """
        Normalizes entity keys for safe comparison.

        Args:
            value: Raw key text.

        Returns:
            Case-insensitive normalized key.
        """
        clean_value = str(value or "").strip()
        clean_value = self._MARKDOWN_DECORATION_PATTERN.sub("", clean_value)
        clean_value = re.sub(r"\s+", " ", clean_value)
        return clean_value.casefold().strip()

    def _preserve_list_prefix(self, old_line: str, replacement_lore: str) -> str:
        """
        Preserves a Markdown list prefix from the old line when replacing it.

        Args:
            old_line: Existing World.md line.
            replacement_lore: New lore text.

        Returns:
            Replacement line with the old bullet or numbered-list prefix retained.
        """
        match = self._BULLET_PREFIX_PATTERN.match(old_line or "")
        prefix = match.group("prefix") if match else ""
        return f"{prefix}{replacement_lore}".rstrip()

    def _append_lore(self, current_text: str, replacement_lore: str) -> str:
        """
        Appends lore when no existing entry matches the anchor.

        Args:
            current_text: Current World.md text.
            replacement_lore: Lore to append.

        Returns:
            Updated World.md text.
        """
        if not current_text.strip():
            return f"# World\n\n{replacement_lore}\n"

        logging.info("UPSERT_WORLD found no existing entry; appended lore instead.")
        return f"{current_text.rstrip()}\n\n{replacement_lore}\n"