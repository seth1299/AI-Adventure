import logging, random

class Player:
    def __init__(self):
        self.name = "Unknown"
        self.nutrition = 100
        self.stamina = 100
        self.karmic_streak = 0
        
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

    def get_status_dict(self):
        """Returns the dictionary format required for the UI and saving."""
        return {
            "nutrition": self.nutrition,
            "stamina": self.stamina,
            "location": self.location,
            "turn": str(self.turn),
            "day": str(self.day),
            "time": self.time
        }

    def update_world_state(self, turn, location, day, time):
        """Updates the tracking variables."""
        if turn is not None: self.turn = turn
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