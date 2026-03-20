import os, random, re
import customtkinter as ctk
from dotenv import load_dotenv
from sound_manager import SoundManager
import logging
import shutil

# Import Config and UI
from config import SAVES_DIR, SOUNDS_DIR, BASE_SOUNDS_DIR, VALID_SOUND_FILE_NAMES
# [CHANGED] Simplified imports
from ui import MainMenu, GameView

# Managers
from file_manager import FileManager
from player import Player
from ai_manager import AIManager

load_dotenv()
FileManager.setup_initial_logging()

class GameApp(ctk.CTk):
    
    def __init__(self):
        super().__init__()
        self.is_creating = False
        self.game_loaded_successfully = False
        self.title("AI RPG Adventure")
        self.geometry("1000x700")
        
        self.sound_manager = SoundManager(SOUNDS_DIR)
        self.player = Player()
        self.ai_manager = AIManager(self)
        
        ctk.set_appearance_mode("Dark")
        
        icon_path = FileManager.resource_path("game_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                logging.error(f"Icon error: {e}")

        self.current_adventure_path = None
        self.creation_summary_path = os.path.join(SAVES_DIR, "creation_summary.txt")
        self.conversation_history = ""
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- VIEW 1: Main Menu ---
        self.main_menu = MainMenu(self, on_load_callback=self.load_game)
        self.main_menu.grid(row=0, column=0, sticky="nsew")

        # --- VIEW 2: Game View (Tabs) ---
        # [CHANGED] Replaced manual tab construction with GameView
        self.game_view = GameView(self, 
                                  send_callback=self.ai_manager.handle_player_action,
                                  menu_callback=self.return_to_menu)
        # Note: We do not grid it yet; load_game handles that.

        # Ensure sounds are present
        for sound in VALID_SOUND_FILE_NAMES:
            current_path = os.path.join(BASE_SOUNDS_DIR, sound)
            destination_path = os.path.join(SOUNDS_DIR, sound)
            if not os.path.exists(destination_path):
                 shutil.copyfile(current_path, destination_path)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
    # --- COMPATIBILITY PROPERTIES ---
    # These allow AIManager and FileManager to access widgets 
    # without needing to rewrite those files.
    
    @property
    def notebook_widgets(self):
        """Facade for accessing widgets inside GameView."""
        return self.game_view.widgets

    @property
    def story_tab(self):
        """Facade for accessing the StoryTab."""
        return self.game_view.widgets["Story"]

    @property
    def tab_view(self):
        """Facade for FileManager to toggle visibility."""
        return self.game_view

    # --- GAME LOGIC ---

    def _get_skill_level(self, skill_name: str) -> int:
        clean = (skill_name or "").split('(')[0].strip().title()
        try:
            skills_tab = self.notebook_widgets["Skills"]
            data = skills_tab.load_data()
            for item in data:
                if item.get("Name", "").lower() == clean.lower():
                    return int(item.get("Level", 0) or 0)
        except Exception as e:
            logging.error("Get skill level error: {e}")
        return 0

    def _advance_time_hours(self, hours: float):
        from time_utils import add_hours 
        gt = add_hours(str(self.player.day), self.player.time, hours)
        self.player.day = gt.as_day_string()
        self.player.time = gt.as_time_string()
        self._sync_player_state_to_ui()

    def _sync_player_state_to_ui(self):
        """Push player state to the StoryTab UI."""
        self.after(0, lambda: self.story_tab.update_status(
            self.player.turn,
            self.player.location,
            self.player.day,
            self.player.time,
            nutrition=self.player.nutrition,
            stamina=self.player.stamina
        ))

    def return_to_menu(self):
        self.save_game()
        self.current_adventure_path = None
        self.is_creating = False
        FileManager.update_logger_path(None)
        
        self.game_view.grid_forget()
        self.title("AI RPG Adventure")
        self.main_menu.refresh_list()
        self.main_menu.grid(row=0, column=0, sticky="nsew")

    def load_game(self, save_name):
        FileManager.load_game(self, save_name)
        
    def _format_recap_text(self, text):
        if not text: return ""
        
        # 1. Split text into sentences (Lookbehind for punctuation [.!?] followed by whitespace)
        # This keeps the punctuation attached to the sentence.
        sentences = re.split(r'(?<=[.!?])\s+', text)
        #logging.info(f"Sentences:\n{sentences}")
        
        _index = 0
        _text_to_return = ""
        for sentence in sentences:
            if _index % 2 == 0 and _index != 0:
                _text_to_return += "\n\n"
            _text_to_return += sentence + " "
            _index += 1
        logging.info(f"Text to return: {_text_to_return}")
        return _text_to_return
    
    def generate_local_recap(self):
        try:
            self._attempt_local_music_restore()
            last_gm_msg = None
            if self.conversation_history:
                last_gm_index = self.conversation_history.rfind("GM:")
                if last_gm_index != -1:
                    text_chunk = self.conversation_history[last_gm_index:]
                    text_chunk = text_chunk.replace("GM:", "", 1).strip()
                    if "Player:" in text_chunk:
                         text_chunk = text_chunk.split("Player:")[0].strip()
                    last_gm_msg = text_chunk
            
            if last_gm_msg:
                last_gm_msg = self._format_recap_text(last_gm_msg)
                self.story_tab.print_text(f"{last_gm_msg}", sender="GM")
                self.story_tab.print_text("What do you do now?", sender="GM")
            else:
                self.story_tab.print_text("System: No recent history found to recap.", sender="System")
        except Exception as e:
            logging.error(f"Local Recap Error: {e}")

    def _attempt_local_music_restore(self):
        try:
            from rapidfuzz import process, fuzz
            location = self.player.location
            if not location or not VALID_SOUND_FILE_NAMES: return
            logging.info(f"Location: {location}")
            logging.info(f"Valid sound file names: {VALID_SOUND_FILE_NAMES}")

            match_tuple = process.extractOne(
                location, 
                VALID_SOUND_FILE_NAMES, 
                scorer=fuzz.WRatio,
                score_cutoff=20 
            )
            
            logging.info(f"Match Tuple for music restore: \n{match_tuple}")
            
            if match_tuple:
                self.sound_manager.play_music(match_tuple[0])
            else:
                self.sound_manager.play_music("main_menu.mp3")
        except ImportError:
            pass 
        except Exception as e:
            logging.error(f"Music restore error: {e}")

    def load_rules(self):
        return FileManager.get_rules(self.current_adventure_path)

    def perform_skill_check(self, skill_name):
        clean_name = skill_name.split('(')[0].strip().title()
        skills_tab = self.notebook_widgets["Skills"]
        data = skills_tab.load_data()
        
        skill_entry = None
        for item in data:
            if item["Name"].lower() == clean_name.lower():
                skill_entry = item
                break
        
        if not skill_entry:
            skill_entry = {"Name": clean_name, "Level": 0, "XP": 0, "Threshold": 5}
            data.append(skill_entry)
            self.story_tab.print_text(f"Learned new skill: {clean_name}!", sender="System")
            
        die_roll = random.randint(1, 20)
        
        new_roll, intervened = self.player.check_karma_intervention(die_roll)
        die_roll = new_roll
        
        if not intervened:
            self.player.update_karma(die_roll)

        skill_entry["XP"] += 1
        leveled_up = False
        if skill_entry["XP"] >= skill_entry["Threshold"]:
            skill_entry["Level"] += 1
            skill_entry["XP"] = 0
            skill_entry["Threshold"] += 2
            leveled_up = True
            
        skills_tab.save_data(data)
        
        bonus_from_nutrition = 0
        if self.player.nutrition >= 85: bonus_from_nutrition = 1
        elif self.player.nutrition <= 40: bonus_from_nutrition = -3 
        
        bonus_from_stamina = 0
        if self.player.stamina >= 85: bonus_from_stamina = 1
        elif self.player.stamina <= 40: bonus_from_stamina = -3

        skill_bonus = skill_entry["Level"]
        total = die_roll + skill_bonus + bonus_from_nutrition + bonus_from_stamina
        
        bonus_from_skill_message = f"{skill_bonus} (from Skill level)"
        bonus_from_nutrition_message = f" +{bonus_from_nutrition} (bonus from high nutrition)" if bonus_from_nutrition > 0 else f"{bonus_from_nutrition} (penalty from low nutrition)" if bonus_from_nutrition < 0 else ""
        bonus_from_stamina_message = f" +{bonus_from_stamina} (bonus from high stamina)" if bonus_from_stamina > 0 else f"{bonus_from_stamina} (penalty from low stamina)" if bonus_from_stamina < 0 else ""
        
        msg = f"Rolling {clean_name}: {die_roll} + ({bonus_from_skill_message}{bonus_from_nutrition_message}{bonus_from_stamina_message}) = {total}"
        if leveled_up:
            msg += f"\n**LEVEL UP!** {clean_name} is now Level {skill_entry['Level']}!"
        else:
            msg += f"\n{clean_name}: {skill_entry['XP']} / {skill_entry['Threshold']} XP towards next level up."

        self.story_tab.print_text(msg, sender="System")
        return total

    def save_game(self):
        FileManager.save_game(self)

    def on_close(self):
        self.save_game()
        self.destroy()

if __name__ == "__main__":
    app = GameApp()
    app.mainloop()