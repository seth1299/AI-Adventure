import logging, random, os
from file_manager import FileManager

class Player:
    def __init__(self):
        self.name = "Unknown"
        self.nutrition = 100
        self.stamina = 100
        self.karmic_streak = 0
        self.save_path = None
        self.base_currency = 0
        self.world_currencies = [{"name": "Copper Piece", "value": 1}, {"name": "Silver Piece", "value": 10}]
        
        # World State (often tied to the player in single-player RPGs)
        self.location = "Unknown"
        self.turn = 1
        self.day = "1"
        self.time = "Start"

    def load_from_dict(self, data):
        """Loads state from the Status dictionary in savegame.json."""
        self.nutrition = int(data.get("nutrition", 100))
        self.stamina = int(data.get("stamina", 100))
        self.location = data.get("location", "Unknown")
        self.turn = int(data.get("turn", 1))
        self.day = data.get("day", "1")
        self.time = data.get("time", "Start")
        self.base_currency = int(data.get("base_currency", 0))

    def get_status_dict(self):
        """Returns the dictionary format required for the UI and saving."""
        return {
            "nutrition": self.nutrition,
            "stamina": self.stamina,
            "location": self.location,
            "turn": str(self.turn),
            "day": str(self.day),
            "time": self.time,
            "base_currency": self.base_currency
        }

    def update_world_state(self, turn, location, day, time):
        """Updates the tracking variables."""
        if turn is not None: 
            try:
                self.turn = int(turn)
            except:
                logging.error(f"Error converting turn to integer: {turn}")
                self.turn = -1
        if location: self.location = location
        if day: self.day = day
        if time: self.time = time

    def modify_stat(self, stat_name, raw_value):
        """
        Handles logic for [[MODIFY_STAT: Stamina | -10]] or [[MODIFY_STAT: Nutrition | SET 50]]
        """
        stat = stat_name.strip().lower()
        raw = raw_value.strip()

        if stat not in ("stamina", "nutrition"):
            logging.error(f"Player: Unknown stat '{stat_name}'.")
            return

        current_val = self.stamina if stat == "stamina" else self.nutrition
        new_val = current_val

        try:
            if raw.upper().startswith("SET "):
                # Absolute Set
                new_val = int(raw.split(None, 1)[1].strip())
            else:
                # Relative Delta
                delta = int(raw)
                new_val += delta
        except Exception as e:
            logging.error(f"Player: Bad stat value '{raw_value}': {e}")
            return

        # Clamp between 0 and 100
        new_val = max(0, min(100, new_val))

        if stat == "stamina":
            self.stamina = new_val
        else:
            self.nutrition = new_val
            
    def get_formatted_currency(self, amount: int = 0) -> str:
        """Converts an integer (base currency) into a readable string like '3 Gold, 7 Silver'."""
        if amount is None: amount = self.base_currency
        if amount == 0: return "0 (None)"

        is_negative = amount < 0
        remaining = abs(amount)
        parts = []

        # Sort currencies from highest value to lowest
        sorted_currencies = sorted(self.world_currencies, key=lambda x: int(x.get("value", 1)), reverse=True)

        for cur in sorted_currencies:
            val = int(cur.get("value", 1))
            if remaining >= val:
                count = remaining // val
                remaining %= val
                parts.append(f"{count} {cur.get('name', 'Unit')}")

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
        Returns a tuple: (total_roll, result_message_string)
        """
        clean_name = (skill_name or "").split("(")[0].strip().title()
        data = self.load_skills_data()
        
        skill_entry = next((item for item in data if str(item.get("Name", "")).lower() == clean_name.lower()), None)
        
        msg_lines = []
        if not skill_entry:
            skill_entry = {"Name": clean_name, "Level": 0, "XP": 0, "Threshold": 5}
            data.append(skill_entry)
            msg_lines.append(f"Learned new skill: {clean_name}!")

        die_roll = random.randint(1, 20)
        try:
            new_roll, intervened = self.check_karma_intervention(die_roll)
            die_roll = int(new_roll)
            if not intervened:
                self.update_karma(die_roll)
        except Exception:
            pass

        # Handle XP & Leveling
        leveled_up = False
        if skill_entry["Level"] < 5:
            skill_entry["XP"] = int(skill_entry.get("XP", 0) or 0) + 1
            xp = skill_entry["XP"]
            th = int(skill_entry.get("Threshold", 5) or 5)

            if xp >= th:
                skill_entry["Level"] = int(skill_entry.get("Level", 0) or 0) + 1
                skill_entry["XP"] = 0
                skill_entry["Threshold"] = th + 2
                leveled_up = True

        self.save_skills_data(data)

        # Modifiers rely entirely on native class attributes now!
        bonus_from_nutrition = 1 if self.nutrition >= 85 else (-3 if self.nutrition <= 40 else 0)
        bonus_from_stamina = 1 if self.stamina >= 85 else (-3 if self.stamina <= 40 else 0)
        skill_bonus = int(skill_entry.get("Level", 0) or 0)

        total = die_roll + skill_bonus + bonus_from_nutrition + bonus_from_stamina

        nut_msg = f" +{bonus_from_nutrition} (high nutrition)" if bonus_from_nutrition > 0 else (f" {bonus_from_nutrition} (low nutrition)" if bonus_from_nutrition < 0 else "")
        sta_msg = f" +{bonus_from_stamina} (high stamina)" if bonus_from_stamina > 0 else (f" {bonus_from_stamina} (low stamina)" if bonus_from_stamina < 0 else "")
        
        msg_lines.append(f"Rolling {clean_name}: {die_roll} + ({skill_bonus} (Skill){nut_msg}{sta_msg}) = {total}")
        
        if leveled_up:
            msg_lines.append(f"LEVEL UP! {clean_name} is now Level {skill_entry['Level']}!")
        else:
            msg_lines.append(f"{clean_name}: {skill_entry.get('XP', 0)} / {skill_entry.get('Threshold', 0)} XP towards next level up.")

        return total, "\n".join(msg_lines)