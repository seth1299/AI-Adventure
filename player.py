import logging, random, os
from file_manager import FileManager
import time_utils
from pathlib import Path

class Player:
    def __init__(self):
        self.name = "Unknown"
        self.weather = "Sunny"
        self.karmic_streak = 0
        self.save_path = None
        self.tracked_stats = []
        self.base_currency = 0
        self.world_currencies = []
        self.calendar_settings = {}
        
        # World State (often tied to the player in single-player RPGs)
        self.location = "Unknown"
        self.turn = 1
        self.day = 1
        self.time = "12:00 PM"
        self.temperature = 76
        self.quests = []
        # Dictionary to track equipped items by slot
        self.equipment = {
            "Head": None,
            "Chest": None,
            "Legs": None,
            "Main Hand": None,
            "Off Hand": None,
            "Accessory": None
        }

    def load_from_dict(self, data):
        """Loads state from the Status dictionary in savegame.json."""
        self.location = data.get("location", "Unknown")
        self.turn = int(data.get("turn", 1))
        self.day = data.get("day", 1)
        self.time = data.get("time", "Start")
        self.weather = data.get("weather", "Sunny")
        self.temperature = data.get("temperature", 76)
        self.base_currency = int(data.get("base_currency", 0))
        self.quests = data.get("quests", [])
        
        if "world_currencies" in data:
            self.world_currencies = data["world_currencies"]
            
        if "calendar_settings" in data:
            self.calendar_settings = data["calendar_settings"]
            
        if "tracked_stats" in data:
            self.tracked_stats = data["tracked_stats"]
            
        if "equipment" in data:
            self.equipment = data["equipment"]

    def get_status_dict(self):
        """Returns the dictionary format required for the UI and saving."""
        return {
            "location": self.location,
            "turn": str(self.turn),
            "day": self.day,
            "formatted_date": time_utils.calculate_calendar_date(self.day, self.calendar_settings),
            "time": self.time,
            "weather": self.weather,
            "temperature": self.temperature,
            "base_currency": self.base_currency,
            "tracked_stats": self.tracked_stats,
            "world_currencies": self.world_currencies,
            "calendar_settings": self.calendar_settings,
            "quests": self.quests,
            "equipment": self.equipment
        }
        
    def get_armor_rating(self) -> int:
        """
        Calculates the total armor rating based on currently equipped items.
        It scans the item descriptions for a specific regex pattern like (AR: 5).
        
        Returns:
            int: The total calculated armor value.
        """
        import re
        total_armor = 10
        
        for slot, item in self.equipment.items():
            if item and isinstance(item, dict):
                description = item.get("desc", "")
                # Looks for "(AR: X)" in the item's description, case-insensitive
                match = re.search(r"\(AR:\s*(\d+)\)", description, re.IGNORECASE)
                if match:
                    try:
                        total_armor += int(match.group(1))
                    except ValueError:
                        logging.error(f"Failed to parse Armor Rating from string: {match.group(1)}")
                        
        return total_armor
    
    def get_weapon_stats(self) -> str:
        """
        Scans equipped weapons (Main Hand, Off Hand) for Accuracy (ACC) and Damage (DMG) tags.
        Returns a formatted string to feed into the AI's context block.
        """
        import re
        weapon_info = []

        # Only check the slots that can reasonably hold a weapon
        for slot in ["Main Hand", "Off Hand"]:
            item = self.equipment.get(slot)
            if item and isinstance(item, dict):
                name = item.get("name", "Unknown Weapon")
                desc = item.get("desc", "")
                
                # Look for (ACC: +2) or (ACC: -1) in the description
                acc_match = re.search(r"\(ACC:\s*([+-]?\d+)\)", desc, re.IGNORECASE)
                accuracy = acc_match.group(1) if acc_match else "+0"
                
                # Look for (DMG: 1d8) or (DMG: 15) in the description
                dmg_match = re.search(r"\(DMG:\s*([^)]+)\)", desc, re.IGNORECASE)
                damage = dmg_match.group(1) if dmg_match else "1"
                
                # Look for (RAN: 1d8) or (RAN: 15) in the description
                ran_match = re.search(r"\(RAN:\s*([^)]+)\)", desc, re.IGNORECASE)
                range = ran_match.group(1) if ran_match else "Melee"
                
                # Look for (TYP) in the description
                typ_match = re.search(r"\(TYP:\s*([^)]+)\)", desc, re.IGNORECASE)
                type = typ_match.group(1) if typ_match else "Energy"
                
                if type == "Ballistic":
                    amm_match = re.search(r"\(AMM:\s*([^)]+)\)", desc, re.IGNORECASE)
                    ammo_type = amm_match.group(1) if amm_match else "9mm"
                    
                    mag_match = re.search(r"\(MAG:\s*([^)]+)\)", desc, re.IGNORECASE)
                    mag_size = mag_match.group(1) if mag_match else "6"
                    
                    weapon_info.append(f"{name} (Accuracy: {accuracy}, Damage: {damage}), Range: {range}, Type: {type}, Ammo Type: {ammo_type}, Magazine Size: {mag_size}")
                else:
                    weapon_info.append(f"{name} (Accuracy: {accuracy}, Damage: {damage}), Range: {range}, Type: {type}")

        if not weapon_info:
            return "Unarmed (Accuracy: +0, Damage: 1, Range: Melee, Type: Energy)"
            
        # Join multiple weapons with a pipe for easy reading
        return " | ".join(weapon_info)
    
    def get_world_currencies(self):
        if self.world_currencies: return self.world_currencies
        else: return ""

    def update_world_state(self, location: str, minutes_to_add: int, weather: str) -> None:
        """Updates the tracking variables and automatically rolls over time/days."""
        self.turn += 1

        try:
            old_day = self.day
            old_weather = self.weather
            
            minutes_to_add_ = 0 if str(minutes_to_add).upper() == "AUTO" else int(float(minutes_to_add))
            self.day, self.time = time_utils.advance_time(self.day, self.time, minutes_to_add_)
            #logging.info(f"Time successfully advanced to Day {self.day}, {self.time}")
            
            if location and str(location).strip().upper() != "AUTO": 
                self.location = location
            if weather and str(weather).strip().upper() != "AUTO":
                self.weather = weather
                
            # --- Automated Season & Temperature Logic ---
            # Only randomize the temperature if the weather shifts or a new day dawns
            if self.day != old_day or self.weather != old_weather:
                _, current_season = time_utils.get_month_and_season(self.day, self.calendar_settings)
                self.temperature = time_utils.generate_dynamic_temperature(current_season, self.weather)
                
        except Exception as error:
            logging.error(f"Failed to update world: {error}")

    def modify_stat(self, stat_name, raw_value):
        """
        Handles logic for [[MODIFY_STAT: Stamina | -10]] or [[MODIFY_STAT: Nutrition | SET 50]]
        """
        stat = stat_name.strip()
        raw = raw_value.strip()

        # Find the stat, or dynamically create it if the AI invents one!
        target_stat = next((s for s in self.tracked_stats if s["name"].lower() == stat.lower()), None)
        if not target_stat:
            # Added min and max defaults for dynamically created stats
            target_stat = {
                "name": stat.title(), 
                "value": 100, 
                "min": 0, 
                "max": 100, 
                "enabled": True, 
                "desc": "A dynamically tracked status."
            }
            self.tracked_stats.append(target_stat)

        new_val = target_stat["value"]
        try:
            if raw.upper().startswith("SET "):
                new_val = int(raw.split(None, 1)[1].strip())
            else:
                new_val += int(raw)
        except Exception:
            return
        
        stat_min = target_stat.get("min", 0)
        stat_max = target_stat.get("max", 100)
        
        if new_val < stat_min:
            new_val = stat_min
        elif new_val > stat_max:
            new_val = stat_max

        target_stat["value"] = new_val
        
    def _pluralize_currency(self, name: str, count: int) -> str:
        """A simple heuristic to pluralize currency names if count is not exactly 1."""
        if count == 1: 
            return name
        
        clean_name = name.strip()
        if not clean_name: 
            return name
        
        # Extract the last word to check (e.g., "Gold Piece" -> "Piece")
        parts = clean_name.split()
        last_word = parts[-1]
        last_word_lower = last_word.lower()
        
        # 1. Common irregulars or uncountables that shouldn't change
        no_change = ["fish", "moose", "sheep", "deer", "gold", "silver", "copper", "iron", "dust", "cash", "money", "gear", "scrap"]
        if last_word_lower in no_change:
            return clean_name
            
        # 2. If it already ends in 's', assume it's already pluralized (e.g., "Credits")
        if last_word_lower.endswith("s"):
            return clean_name
            
        # 3. Handle consonant + "y" ending (e.g., "Penny" -> "Pennies")
        if last_word_lower.endswith("y") and len(last_word_lower) > 1 and last_word_lower[-2] not in "aeiou":
            # Replace the 'y' with 'ies'
            parts[-1] = last_word[:-1] + (last_word[-1].replace('y', 'ies').replace('Y', 'IES'))
            return " ".join(parts)
            
        # 4. Handle words ending in 'ch', 'sh', 'x', 'z' (e.g., "Stash" -> "Stashes")
        if last_word_lower.endswith(("ch", "sh", "x", "z")):
            return clean_name + "es"
            
        # 5. Default fallback: just add 's' (e.g., "Piece" -> "Pieces")
        return clean_name + "s"
            
    def get_formatted_currency(self, amount: int | None  = None) -> str:
        """Converts an integer (base currency) into a readable string like '3 Gold, 7 Silver'."""
        if amount is None: amount = self.base_currency
        if amount == 0: return "0 (None)"

        is_negative = amount < 0
        remaining = abs(amount)
        parts = []

        # Sort currencies from highest value to lowest
        sorted_currencies = sorted(self.world_currencies, key=lambda x: int(x.get("value", 1)), reverse=True)
        
        # --- NEW: Get the name of the smallest denomination to replace "Base Units" ---
        lowest_coin_name = sorted_currencies[-1].get("name", "Base Units") if sorted_currencies else "Base Units"

        for cur in sorted_currencies:
            val = int(cur.get("value", 1))
            if val <= 0: continue # Safely avoid zero division
            if remaining >= val:
                count = remaining // val
                remaining %= val
                currency_name = cur.get('name', 'Unit')
                plural_name = self._pluralize_currency(currency_name, count)
                parts.append(f"{count} {plural_name}")

        # NEW: Fallback! If the AI did weird math and there is remainder left over, don't delete it!
        if remaining > 0:
            plural_lowest = self._pluralize_currency(lowest_coin_name, remaining)
            parts.append(f"{remaining} {plural_lowest}")

        result_str = ", ".join(parts)
        return f"-{result_str}" if is_negative else result_str

    def change_currency(self, amount: int):
        """Adds or subtracts currency. Returns a tuple (Success_Bool, Message_String)"""
        if amount < 0 and (self.base_currency + amount) < 0:
            # Player is too poor to buy the item!
            cost_str = self.get_formatted_currency(abs(amount))
            wallet_str = self.get_formatted_currency(self.base_currency)
            return False, f"Failed: Not enough funds. You need {cost_str} but only have {wallet_str}."
        
        # Perform transaction
        self.base_currency += amount
        action = "gained" if amount > 0 else "spent"
        
        formatted_amount = self.get_formatted_currency(abs(amount))
        formatted_total = self.get_formatted_currency(self.base_currency)
        
        return True, f"Currency {action}: {formatted_amount}. (Total wealth: {formatted_total})"
            
    def update_karma(self, die_roll):
        """Updates karmic streak based on the roll."""
        if die_roll < 8:
            if self.karmic_streak > 0: self.karmic_streak = 0
            self.karmic_streak -= 1
        elif die_roll > 13:
            if self.karmic_streak < 0: self.karmic_streak = 0
            self.karmic_streak += 1
        else:
            # Neutral rolls move streak towards zero
            if self.karmic_streak > 0: self.karmic_streak -= 1
            elif self.karmic_streak < 0: self.karmic_streak += 1

    def check_karma_intervention(self, die_roll):
        """Returns a modified roll if Karma intervenes, else returns original."""
        # Bad Luck Intervention
        if self.karmic_streak <= -3:
            new_roll = random.randint(10, 20)
            if new_roll > die_roll:
                self.karmic_streak = -1  # Reset slightly
                return new_roll, True
        
        # Good Luck Intervention (Nudge down if too lucky)
        elif self.karmic_streak >= 6:
            new_roll = random.randint(1, 12)
            if new_roll < die_roll:
                self.karmic_streak = 1 # Reset slightly
                return new_roll, True
                
        return die_roll, False
    
    def set_save_path(self, path: str | Path) -> None:
        """Called by the main app when a game is loaded or created."""
        self.save_path = Path(path) if path else None

    def _skills_json_path(self) -> Path | None:
        """Constructs and returns the Path object for the skills.json file."""
        if not self.save_path: 
            return None
        return self.save_path / "skills.json"

    def load_skills_data(self) -> list:
        """Loads skill data from the JSON file, utilizing pathlib for existence checks."""
        skills_file_path = self._skills_json_path()
        
        # Check for None and verify the file exists on disk
        if not skills_file_path or not skills_file_path.exists(): 
            return []
            
        # We cast the Path object back to a string for the FileManager's compatibility
        data = FileManager.load_json_data(str(skills_file_path))
        return data if isinstance(data, list) else []

    def save_skills_data(self, data: list) -> None:
        """Saves skill data to the JSON file, resolving the path via pathlib."""
        skills_file_path = self._skills_json_path()
        if not skills_file_path: 
            return
            
        try:
            data.sort(key=lambda item: str((item or {}).get("Name", "")).lower())
        except Exception as sorting_error: 
            logging.warning(f"Could not sort skills data. Details: {sorting_error}")
            
        # Cast the Path object back to a string for FileManager compatibility
        FileManager.save_json_data(str(skills_file_path), data)

    def get_skill_level(self, skill_name):
        clean = (skill_name or "").split("(")[0].strip().title()
        for item in self.load_skills_data():
            if str(item.get("Name", "")).lower() == clean.lower():
                return int(item.get("Level", 0) or 0)
        return 0

    def perform_skill_check(self, skill_name):
        """
        Handles rolling, leveling up, and stat modifiers internally.
        """
        clean_name = (skill_name or "").split("(")[0].strip().title()
        data = self.load_skills_data()
        
        skill_entry = next((item for item in data if str(item.get("Name", "")).lower() == clean_name.lower()), None)
        
        if not skill_entry:
            skill_entry = {"Name": clean_name, "Level": 0, "XP": 0, "Threshold": 5}
            data.append(skill_entry)
            #logging.info(f"Learned new skill: {clean_name}!")
            
        name = skill_entry["Name"]
        level = int(skill_entry["Level"])
        xp = int(skill_entry["XP"])
        threshold = int(skill_entry["Threshold"])

        die_roll = random.randint(1, 20)
        try:
            new_roll, intervened = self.check_karma_intervention(die_roll)
            die_roll = int(new_roll)
            if not intervened:
                self.update_karma(die_roll)
        except Exception as e:
            logging.error(f"Error during karma intervention: {e}")
            pass

        # Handle XP & Leveling
        if level < 5:
            skill_entry["XP"] = xp + 1

            if xp >= threshold:
                skill_entry["Level"] = level + 1
                skill_entry["XP"] = 0
                skill_entry["Threshold"] = threshold + 2
                #logging.info(f"Leveled up {name} Skill from level {level} to {skill_entry["Level"]}!")

        self.save_skills_data(data)
        skill_bonus = int(skill_entry.get("Level", 0) or 0)

        total = die_roll + skill_bonus
        return total
        