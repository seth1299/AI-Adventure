import os
import sys
import json
import logging
import threading
from config import SAVES_DIR, SOUNDS_DIR, DEFAULT_RULES

class FileManager:
    @staticmethod
    def resource_path(relative_path):
        """Get absolute path to resource, works for dev and for PyInstaller"""
        base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
        return os.path.join(base_path, relative_path)

    @staticmethod
    def setup_initial_logging():
        """Sets up the basic logger on startup."""
        log_file_path = os.path.join(SAVES_DIR, "error_log.txt")
        logging.basicConfig(
            filename=log_file_path,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s', 
            datefmt='%m/%d/%Y at %I:%M:S %p',
            filemode='w'
        )

    @staticmethod
    def update_logger_path(save_name=None):
        """Switches the logging output to a specific save folder."""
        if save_name:
            save_dir = os.path.join(SAVES_DIR, save_name)
            if not os.path.exists(save_dir):
                return
            new_log_path = os.path.join(save_dir, f"{save_name}_error_log.txt")
        else:
            new_log_path = os.path.join(SAVES_DIR, "generic_text_adventure_error_log.txt")

        logger = logging.getLogger()
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                handler.close()
                logger.removeHandler(handler)

        try:
            file_handler = logging.FileHandler(new_log_path, mode='w', encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logging.info(f"Logger switched to: {new_log_path}")
        except Exception as e:
            print(f"Failed to switch logger: {e}")

    # --- RAW I/O METHODS ---

    @staticmethod
    def read_text_file(path):
        """Reads a text file safely. Returns empty string on failure."""
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logging.error(f"Error reading file {path}: {e}")
            return ""

    @staticmethod
    def write_text_file(path, content):
        """Writes content to a text file."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
                logging.info(f"Saved to {path}.")
        except Exception as e:
            logging.error(f"Error writing file {path}: {e}")

    @staticmethod
    def load_json_data(path):
        """Loads a JSON file and returns the dictionary. Returns None on error."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading JSON {path}: {e}")
            return None

    @staticmethod
    def save_json_data(path, data):
        """Saves a dictionary to a JSON file."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving JSON {path}: {e}")
            with open("LAST_SAVE_FAILED.txt", "w") as f:
                f.write(f"Failed to save {path}: {e}")

    @staticmethod
    def get_rules(adventure_path):
        """Loads local rules.md or returns default."""
        if adventure_path:
            local_rules = os.path.join(adventure_path, "rules.md")
            if os.path.exists(local_rules):
                return FileManager.read_text_file(local_rules)
        return DEFAULT_RULES

    @staticmethod
    def migrate_inventory(adventure_path):
        """Legacy support: Ensures inventory.json is in the new format."""
        if not adventure_path: return
        inv_path = os.path.join(adventure_path, "inventory.json")
        if not os.path.exists(inv_path): return

        try:
            data = FileManager.load_json_data(inv_path)
            if not isinstance(data, dict): return

            changed = False
            for cat, items in list(data.items()):
                if not isinstance(items, list): continue
                new_items = []
                for item in items:
                    if isinstance(item, dict): new_items.append(item)
                    elif isinstance(item, list):
                        name = item[0] if len(item) > 0 else "Unknown"
                        desc = item[1] if len(item) > 1 else "No desc"
                        amt  = item[2] if len(item) > 2 else "1"
                        val  = item[3] if len(item) > 3 else "0"
                        new_items.append({"name": name, "desc": desc, "amount": str(amt), "value": str(val)})
                        changed = True
                    else: changed = True
                data[cat] = new_items

            if changed:
                FileManager.save_json_data(inv_path, data)
        except Exception as e:
            logging.error(f"Inventory migration error: {e}")

    # --- HIGH LEVEL GAME OPERATIONS ---

    @staticmethod
    def save_game(app):
        """Persists all game state to disk."""
        if not app.current_adventure_path or not app.game_loaded_successfully: 
            return

        # 2. Gather History
        history_list = app.conversation_history
        
        # 3. Gather Player & Game Status
        status_data = app.player.get_status_dict()
        
        save_data = {
            "Chat History": history_list, 
            "Status": status_data,
            "karmic_streak": app.player.karmic_streak 
        }
        
        # 4. Write JSON
        history_path = os.path.join(app.current_adventure_path, "savegame.json")
        FileManager.save_json_data(history_path, save_data)
        logging.info(f"Game saved to {app.current_adventure_path}")

    @staticmethod
    def load_game(app, save_name):
        """Loads a game state, populates the app, and switches the UI."""

        app.game_loaded_successfully = False
        app.current_adventure_path = os.path.join(SAVES_DIR, save_name)
        app.current_sounds_path = os.path.join(SOUNDS_DIR, save_name)
        
        # 1. Clear State
        app.story_tab.clear_chat()
        FileManager.update_logger_path(save_name)
        
        # 2. Migration Check
        FileManager.migrate_inventory(app.current_adventure_path)
        
        # 3. Switch UI View
        app.main_menu.grid_forget()
        app.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        app.title(f"{save_name}")

        # 4. Load Tab Content (Inventory, Skills, Markdown)
        for name, widget in app.notebook_widgets.items():
            try:
                if hasattr(widget, 'set_base_path'):
                    widget.set_base_path(app.current_adventure_path)
            except Exception as e:
                logging.error(f"Error loading tab {name}: {e}")

        # 5. Load JSON Data
        history_path = os.path.join(app.current_adventure_path, "savegame.json")
        data = FileManager.load_json_data(history_path)
        
        if data:
            try:
                app.is_creating = bool(data.get("is_creating", False))
                
                # Restore Player
                app.player.karmic_streak = data.get("karmic_streak", 0)
                status_data = data.get("Status", {})
                if status_data:
                    app.player.load_from_dict(status_data)
                    app._sync_player_state_to_ui()

                # Restore History
                hist = data.get("Chat History", [])
                app.conversation_history = hist
                app.generate_local_recap()
            except Exception as e:
                logging.error(f"Error parsing save data: {e}")
        else:
            # New Game
            app.conversation_history = []
            app.story_tab.print_text("System: Initialization Sequence Started...", sender="System")
            threading.Thread(target=app.ai_manager.start_creation_wizard, daemon=True).start()
            
        app.game_loaded_successfully = True