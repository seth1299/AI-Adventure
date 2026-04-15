import logging, random, os
from file_manager import FileManager
import time_utils

class Player:
    def __init__(self):
        self.name = "Unknown"
        self.karmic_streak = 0
        self.save_path = None
        self.tracked_stats = []
        self.base_currency = 0
        self.world_currencies = []
        
        # World State (often tied to the player in single-player RPGs)
        self.location = "Unknown"
        self.turn = 1
        self.day = 1
        self.time = "12:00 PM"

    def load_from_dict(self, data):
        """Loads state from the Status dictionary in savegame.json."""
        self.location = data.get("location", "Unknown")
        self.turn = int(data.get("turn", 1))
        self.day = data.get("day", 1)
        self.time = data.get("time", "Start")
        self.base_currency = int(data.get("base_currency", 0))
        
        if "world_currencies" in data:
            self.world_currencies = data["world_currencies"]
            
        if "tracked_stats" in data:
            self.tracked_stats = data["tracked_stats"]

    def get_status_dict(self):
        """Returns the dictionary format required for the UI and saving."""
        return {
            "location": self.location,
            "turn": str(self.turn),
            "day": self.day,
            "time": self.time,
            "base_currency": self.base_currency,
            "tracked_stats": self.tracked_stats,
            "world_currencies": self.world_currencies
        }
    
    def get_world_currencies(self):
        if self.world_currencies: return self.world_currencies
        else: return ""

    def update_world_state(self, location: str, minutes_to_add: int) -> None:
        """Updates the tracking variables and automatically rolls over time/days."""
        self.turn += 1

        if location and str(location).strip().upper() != "AUTO": 
            self.location = location
        
        import time_utils
        try:
            # Replaces string slicing with our safe 24-hour wrap-around utility
            self.day, self.time = time_utils.advance_time(self.day, self.time, minutes_to_add)
            logging.info(f"Time successfully advanced to Day {self.day}, {self.time}")
        except Exception as error:
            logging.error(f"Failed to update world time: {error}")

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
    
    def set_save_path(self, path):
        """Called by the main app when a game is loaded or created."""
        self.save_path = path

    def _skills_json_path(self):
        if not self.save_path: return None
        return os.path.join(self.save_path, "skills.json")

    def load_skills_data(self):
        path = self._skills_json_path()
        if not path or not os.path.exists(path): return []
        data = FileManager.load_json_data(path)
        return data if isinstance(data, list) else []

    def save_skills_data(self, data):
        path = self._skills_json_path()
        if not path: return
        try:
            data.sort(key=lambda x: str((x or {}).get("Name", "")).lower())
        except Exception: pass
        FileManager.save_json_data(path, data)

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
            logging.info(f"Learned new skill: {clean_name}!")
            
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
                logging.info(f"Leveled up {name} Skill from level {level} to {skill_entry["Level"]}!")

        self.save_skills_data(data)
        skill_bonus = int(skill_entry.get("Level", 0) or 0)

        total = die_roll + skill_bonus
        return total
        