# qt_main.py
import sys
import os
import logging
from PySide6.QtWidgets import QApplication
from file_manager import FileManager
from qt_ui.main_window import MainWindow
from PySide6.QtCore import QTimer, QObject, Signal, Slot, Qt
from player import Player
from sound_manager import SoundManager
from config import SAVES_DIR, SOUNDS_DIR, BASE_SOUNDS_DIR, VALID_SOUND_FILE_NAMES
import random, re
from qt_ui.main_menu_dialog import MainMenuDialog
import threading
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QTimer, QObject, Signal, Slot, Qt, QThread
from queue import Queue
import time_utils

class _UiDispatcher(QObject):
    run_now = Signal(object)          # callable
    run_later = Signal(int, object)   # ms, callable

    def __init__(self, parent=None):
        super().__init__(parent)
        self.run_now.connect(self._run_now, Qt.ConnectionType.QueuedConnection)
        self.run_later.connect(self._run_later, Qt.ConnectionType.QueuedConnection)

    def is_ui_thread(self) -> bool:
        app = QApplication.instance()
        if app is None:
            return True
        return QThread.currentThread() == app.thread()

    def call_blocking(self, func):
        """
        Run `func` on the UI thread and return its result.
        If we're already on the UI thread, run immediately.
        """
        if self.is_ui_thread():
            return func()

        q: Queue = Queue(maxsize=1)

        def _wrapper():
            try:
                q.put((True, func()))
            except Exception as e:
                q.put((False, e))

        self.run_now.emit(_wrapper)
        ok, payload = q.get()
        if ok:
            return payload
        raise payload

    @Slot(object)
    def _run_now(self, func) -> None:
        try:
            func()
        except Exception:
            logging.exception("UI dispatch error (run_now)")

    @Slot(int, object)
    def _run_later(self, ms: int, func) -> None:
        try:
            QTimer.singleShot(int(ms), func)
        except Exception:
            logging.exception("UI dispatch error (run_later)")
            
class QtStoryTabAdapter:
    def __init__(self, story_panel, dispatcher: _UiDispatcher):
        self._panel = story_panel
        self._ui = dispatcher

    def print_text(self, text: str, sender: str = "") -> None:
        self._ui.run_now.emit(lambda: self._panel.print_text(text, sender=sender))

    def set_controls_state(self, enabled: bool, status_text: str | None = None) -> None:
        self._ui.run_now.emit(lambda: self._panel.set_controls_state(enabled, status_text))
        
class QtPanelAdapter:
    """
    Thread-safe adapter around Qt panels.

    - get_text() is safe from worker threads.
    - set_text(), set_base_path(), save_now() are executed on UI thread.
    - Any other method calls (inventory/skills/processing/recipes helpers)
      are forwarded safely via __getattr__.
    """

    def __init__(self, panel, dispatcher: _UiDispatcher):
        self._panel = panel
        self._ui = dispatcher

    def get_text(self) -> str:
        return str(self._ui.call_blocking(lambda: self._panel.get_text()))

    def set_text(self, text: str) -> None:
        self._ui.call_blocking(lambda t=text: self._panel.set_text(t))

    def set_base_path(self, base_path: str) -> None:
        self._ui.call_blocking(lambda p=base_path: self._panel.set_base_path(p))

    def save_now(self) -> None:
        if self != None and hasattr(self._ui.call_blocking, "save_now"): self._ui.call_blocking(self._panel.save_now)

    def __getattr__(self, name):
        """
        Forward unknown attributes/methods to the underlying panel, safely.
        If it's callable, we call it on the UI thread and return the result.
        """
        attr = getattr(self._panel, name)
        if callable(attr):
            def _wrapped(*args, **kwargs):
                return self._ui.call_blocking(lambda: getattr(self._panel, name)(*args, **kwargs))
            return _wrapped
        return attr


class QtAppContext:
    """Minimal adapter to let the existing AIManager run under Qt."""

    def __init__(self, win):
        self.win = win
        self.ui = _UiDispatcher(win)

        self.current_adventure_path = None

        self.creation_summary_path = os.path.join(SAVES_DIR, "creation_summary.txt")
        self.secret_path = os.path.join(SAVES_DIR, "secret.txt")
        self.world_path = os.path.join(SAVES_DIR, "world.md")
        self.conversation_history = []

        self.player = Player()
        self.sound_manager = SoundManager(BASE_SOUNDS_DIR)

        # API surface AIManager expects
        self.story_tab = QtStoryTabAdapter(win.story_panel, self.ui)

        self.notebook_widgets = {
                "Inventory": QtPanelAdapter(win.inventory_panel, self.ui),
                "Skills": QtPanelAdapter(win.skills_panel, self.ui),
                "Processing": QtPanelAdapter(win.processing_panel, self.ui),
                "Recipes": QtPanelAdapter(win.recipes_panel, self.ui),
                "Character": QtPanelAdapter(win.character_panel, self.ui),
                "World": QtPanelAdapter(win.world_panel, self.ui),
                "Journal": QtPanelAdapter(win.journal_panel, self.ui),
                "History": QtPanelAdapter(win.history_panel, self.ui),
            }

        self._sync_player_state_to_ui()

    def after(self, ms: int, func) -> None:
        self.ui.run_later.emit(int(ms), func)

    def load_rules(self) -> str:
        # 1. Fetch the raw rules string from the file manager
        base_rules = FileManager.get_rules(self.current_adventure_path)
        
        # 2. Get the current currencies
        currency_list = self.player.get_world_currencies()
        stats_list = self.player.get_status_dict().get("tracked_stats", "UNKNOWN STATS")
        sounds_list = VALID_SOUND_FILE_NAMES
        
        # 3. Format and inject them
        if currency_list:
            currency_names = ", ".join([f"{c.get('name', 'Unit')} (Value: {c.get('value', 1)})" for c in currency_list])
            formatted_rules = base_rules.replace("{DYNAMIC_CURRENCIES}", currency_names)
        else:
            formatted_rules = base_rules.replace("{DYNAMIC_CURRENCIES}", "No currencies defined yet.")
            
        if stats_list:
            stats_names = ", ".join([stat.get("name", "UNKNOWN STAT") for stat in stats_list])
            formatted_rules = base_rules.replace("{DYNAMIC_STATS}", stats_names)
        else:
            formatted_rules = base_rules.replace("{DYNAMIC_STATS}", "No stats defined yet.")
            
        if sounds_list:
            sounds_names = ", ".join(sound for sound in sounds_list)
            formatted_rules = base_rules.replace("{VALID_SOUND_FILE_NAMES}", sounds_names)
        else:
            formatted_rules = base_rules.replace("{VALID_SOUND_FILE_NAMES}", "No sounds defined yet.")
            
        return formatted_rules

    def save_game(self) -> None:
        if not self.current_adventure_path:
            logging.warning(f"Warning: No valid save path.")
            return

        # Save Markdown tabs
        try:
            for widget in self.notebook_widgets:
                w = self.notebook_widgets.get(widget)
                if w != None and hasattr(w, "save_now"):
                    w.save_now()
        except Exception:
            logging.exception("Qt save: markdown save failed")

        # Save JSON state (history + status)
        try:
            history_list = self.conversation_history
            status_data = self.player.get_status_dict()
            save_data = {
                "Chat History": history_list,
                "Status": status_data,
                "karmic_streak": int(getattr(self.player, "karmic_streak", 0) or 0),
                "current_music": self.sound_manager.current_music
            }
            history_path = os.path.join(self.current_adventure_path, "savegame.json")
            logging.info(f"Saved to {history_path}.")
            FileManager.save_json_data(history_path, save_data)
        except Exception:
            logging.exception("Qt save: savegame.json write failed")
    
    def _resolve_save_path_for_recap(self) -> str | None:
        """Pick a save folder to read savegame.json from.
        - Prefer current_adventure_path if set.
        - Otherwise, pick the most recently modified save folder containing savegame.json.
        """
        if self.current_adventure_path:
            return self.current_adventure_path

        try:
            best_path: str | None = None
            best_mtime = -1.0
            for name in os.listdir(SAVES_DIR):
                p = os.path.join(SAVES_DIR, name)
                if not os.path.isdir(p):
                    continue
                sg = os.path.join(p, "savegame.json")
                if not os.path.exists(sg):
                    continue
                mtime = os.path.getmtime(sg)
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_path = p
            return best_path
        except Exception as e:
            logging.exception(f"Failed to resolve save path for recap: {e}")
            return None
        
    def load_savegame_state(self, save_path: str) -> dict:
        """Load savegame.json and hydrate Player + app flags, then sync status UI."""
        
        try:
            self.current_adventure_path = save_path
            self.player.set_save_path(save_path)

            sg_path = os.path.join(save_path, "savegame.json")
            data = FileManager.load_json_data(sg_path) or {}
        except Exception as e:
            logging.error(f"Error while attempting to read file save path: {e}")

        # Player meta
        try:
            self.player.karmic_streak = int(data.get("karmic_streak", 0) or 0)
        except Exception:
            self.player.karmic_streak = 0
            
        saved_music = data.get("current_music")
        if saved_music:
            self.sound_manager.play_music(saved_music)
            
        currencies = data.get("Currencies")
        if currencies:
            self.player.world_currencies = currencies
        else:
            # Default fallback if missing
            self.player.world_currencies = [{"name": "Copper Piece", "value": 1}, {"name": "Silver Piece", "value": 10}]

        # Player status
        status_data = data.get("Status") or {}
        if isinstance(status_data, dict) and status_data:
            self.player.load_from_dict(status_data)

        # History (keep around for later panels)
        hist = data.get("Chat History") or []
        self.conversation_history = hist
            
        try:
            for widget in self.notebook_widgets:
                self.notebook_widgets[widget].set_base_path(save_path)
        except Exception:
            logging.exception("Failed to load markdown tabs")

        self._sync_player_state_to_ui()
        return data

    def generate_recap(self) -> None:
        """Load the most recent savegame.json, sync status bar, then print a recap."""
        try:
            save_path = self._resolve_save_path_for_recap()
            if not save_path:
                self.story_tab.print_text("No save found to recap from.", sender="System")
                return

            data = self.load_savegame_state(save_path)
            history = data.get("Chat History") or []
            history_text = ""
            last_gm_message = ""
            for line in history:
                if line == "" or line == None: continue
                # We do not print to story_tab here anymore!
                history_text += line + "\n\n"
                if not line.startswith("> "):
                    last_gm_message = line
                
            if "History" in self.notebook_widgets:
                self.notebook_widgets["History"].set_text(history_text.strip())
                
            if last_gm_message:
                self.story_tab.print_text(last_gm_message + "\n\nWhat do you do now?\n", sender="")
            else:
                self.story_tab.print_text(f"What do you do now?\n")
            
        except Exception as e:
            logging.exception(f"Generate recap failed: {e}")

    def _format_recap_text(self, text):
        if not text: return ""
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        _index = 0
        _text_to_return = ""
        
        for sentence in sentences:
            if _index % 2 == 0 and _index != 0:
                _text_to_return += "\n\n"
            _text_to_return += sentence + " "
            _index += 1
            
        return _text_to_return

    def _get_skill_level(self, skill_name: str) -> int:
        return self.player.get_skill_level(skill_name)

    def perform_skill_check(self, skill_name: str) -> int:
        # Calls the Player class, then routes the output message to the UI
        total = self.player.perform_skill_check(skill_name)
        #self.story_tab.print_text(msg, sender="System")
        return total

    def _advance_time_hours(self, _hours: float) -> None:
        try:
            # 1. Calculate the new time using your existing utility function
            new_game_time = time_utils.add_hours(self.player.day, self.player.time, _hours)
            
            # 2. Update the player's internal state
            self.player.day = new_game_time.as_day_string()
            self.player.time = new_game_time.as_time_string()
            
            # 3. Force the UI status bar to update so the player sees the change immediately
            self._sync_player_state_to_ui()
            
            # 4. Save the game to lock in the time skip
            self.save_game()
            
        except Exception as e:
            logging.error(f"Error advancing time: {e}")

    def _sync_player_state_to_ui(self) -> None:
        """Thread-safe push of Player status into the Qt status header."""
        try:
            s = self.player.get_status_dict()

            def _apply():
                self.win.story_panel.set_status(
                    turn=s.get("turn") or 1,
                    location=s.get("location") or "Character Creation",
                    day=f"{s.get('day')}" or "Day 1",
                    time=s.get("time") or "12:00 A.M.",
                    dynamic_stats=s.get("tracked_stats", [])
                )

            # AIManager calls this from worker threads; dispatch to UI thread.
            self.ui.run_now.emit(_apply)
        except Exception as e:
            logging.error(f"Error syncing state to UI: {e}")

def main() -> int:
    FileManager.setup_initial_logging()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("AI RPG Adventure")

    # Optional icon (if you already have game_icon.ico in your bundled resources)
    try:
        from PySide6.QtGui import QIcon
        icon_path = FileManager.resource_path("game_icon.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception as e:
        logging.error(f"Qt icon error: {e}")

    # ---- Main Menu first ----
    menu = MainMenuDialog()
    if menu.exec() != QDialog.DialogCode.Accepted or not menu.selected_save:
        return 0

    save_name = menu.selected_save
    save_path = os.path.join(SAVES_DIR, save_name)

    win = MainWindow()
    app_ctx = QtAppContext(win)

    from ai_manager import AIManager
    win.app = app_ctx
    win.inventory_panel.app = app_ctx
    win.ai_manager = AIManager(app_ctx)
    win.setWindowTitle(f"{save_name}")
    win.show()
    
    win.story_panel.volume_changed.connect(app_ctx.sound_manager.set_volume)

    def _boot_selected_save() -> None:
        try:
            FileManager.update_logger_path(save_name)
            app_ctx.player.set_save_path(save_path)

            savegame_path = os.path.join(save_path, "savegame.json")
            creation_summary_path = os.path.join(save_path, "creation_summary.txt")
            secret_path = os.path.join(save_path, "secret.txt")
            world_path = os.path.join(save_path, "world.md")
            if os.path.exists(savegame_path):
                app_ctx.load_savegame_state(save_path)
                win._load_ui_state(save_path)
                app_ctx.generate_recap()
                return
            if not os.path.exists(creation_summary_path): 
                with open(creation_summary_path, "w", encoding="utf-8") as f: f.write("")
            if not os.path.exists(secret_path): 
                with open(secret_path, "w", encoding="utf-8") as f: f.write("")
            if not os.path.exists(world_path): 
                with open(world_path, "w", encoding="utf-8") as f: f.write("")

            app_ctx.current_adventure_path = save_path
            app_ctx.conversation_history = []
        except Exception as e:
            logging.error(f"Error booting selected save: {e}")
        try:
            for w in app_ctx.notebook_widgets.values():
                w.set_base_path(save_path)
        except Exception as e:
            logging.exception(f"Failed to set base path for panels: {e}")

        from qt_ui.creation_wizard import CreationWizard
        wizard = CreationWizard(win)
        if wizard.exec() == QDialog.DialogCode.Accepted:
            try:
                wizard_data = wizard.get_wizard_data()
                app_ctx.player.world_currencies = wizard_data["currencies"]
                app_ctx.player.tracked_stats = wizard_data["stats"]
                app_ctx._sync_player_state_to_ui()
            except Exception as e:
                logging.error(f"Error getting wizard data: {e}")
            
            if win.ai_manager != None:
                threading.Thread(target=win.ai_manager.start_new_game_from_wizard, args=(wizard_data,), daemon=True).start()
        else:
            # If the user closes the wizard without finishing, exit or return to menu
            sys.exit(0)
    
    QTimer.singleShot(0, _boot_selected_save)
    return app.exec()


if __name__ == "__main__":
    main()
    pass
    #raise SystemExit(main())