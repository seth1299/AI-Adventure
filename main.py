# qt_main.py
import sys
import os
import logging
from file_manager import FileManager
from qt_ui.main_window import MainWindow
from player import Player
from sound_manager import SoundManager
from config import Configuration, get_configuration
from qt_ui.dialogs import (
    CreationTemplateStore,
    CreationWizard,
    MainMenuDialog,
    NewGameSourceDialog,
)
import threading
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QTimer, QObject, Signal, Slot, Qt, QThread
from queue import Queue
from pathlib import Path

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
        """
        Safely retrieves the text from the underlying panel.
        If the panel does not have a get_text method, it catches the missing attribute 
        and returns an empty string to prevent silent UI thread crashes.
        """
        if not hasattr(self._panel, "get_text"):
            return ""
            
        try:
            return str(self._ui.call_blocking(lambda: self._panel.get_text()))
        except Exception as error:
            logging.error(f"Failed to retrieve text from panel: {error}")
            return ""
        
    def get_ai_context(self) -> str:
        """
        Safely retrieves model-facing plain text from the underlying panel.

        Falls back to get_text() for panels that do not need a separate AI-context
        formatter.
        """
        if self._panel is None:
            logging.warning("QtPanelAdapter.get_ai_context called with no panel.")
            return ""

        context_getter = getattr(self._panel, "get_ai_context", None)

        if not callable(context_getter):
            context_getter = getattr(self._panel, "get_text", None)

        if not callable(context_getter):
            logging.warning(
                "Panel %s has neither get_ai_context() nor get_text().",
                self._panel.__class__.__name__,
            )
            return ""

        try:
            return str(self._ui.call_blocking(lambda: context_getter()))
        except Exception as error:
            logging.exception("Failed to retrieve AI context from panel: %s", error)
            return ""

    def set_text(self, text: str) -> None:
        self._ui.call_blocking(lambda t=text: self._panel.set_text(t))

    def set_base_path(self, base_path: str) -> None:
        self._ui.call_blocking(lambda p=base_path: self._panel.set_base_path(p))

    def save_now(self) -> None:
        if self._panel is not None and hasattr(self._panel, "save_now"): 
            self._ui.call_blocking(self._panel.save_now)

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

    def __init__(self, win, configuration: Configuration | None = None):
        self.win = win
        self.configuration = configuration or get_configuration()
        self.ui = _UiDispatcher(win)

        self.current_adventure_path: str | None = None

        self.secret_path = str(self.configuration.saves_directory / "secret.txt")
        self.world_path = str(self.configuration.saves_directory / "world.md")
        self.conversation_history: list[str] = []

        self.player = Player()
        self.sound_manager = SoundManager(str(self.configuration.base_sounds_directory))

        # API surface AIManager expects
        self.story_tab = QtStoryTabAdapter(win.story_panel, self.ui)
        try:
            if win.history_panel is None:
                logging.warning("History panel UI is missing.")
            if win.quests_panel is None:
                logging.warning("Quests panel UI is missing.")
            if win.quests_panel: pass
            else: logging.exception("NO QUESTS PANEL UI.")
        except Exception as e:
            logging.exception(f"CRITICAL ERROR WHILE LOADING: {e}")

        self.notebook_widgets = {
                "Inventory": QtPanelAdapter(win.inventory_panel, self.ui),
                "Skills": QtPanelAdapter(win.skills_panel, self.ui),
                "Processing": QtPanelAdapter(win.processing_panel, self.ui),
                "Recipes": QtPanelAdapter(win.recipes_panel, self.ui),
                "Character": QtPanelAdapter(win.character_panel, self.ui),
                "World": QtPanelAdapter(win.world_panel, self.ui),
                "Journal": QtPanelAdapter(win.journal_panel, self.ui),
                "History": QtPanelAdapter(win.history_panel, self.ui),
                "Quests": QtPanelAdapter(win.quests_panel, self.ui),
                "Sales Ledger": QtPanelAdapter(win.sales_ledger_panel, self.ui),
                "Calendar": QtPanelAdapter(win.calendar_panel, self.ui)
            }

        self._sync_player_state_to_ui()
        
    def set_adventure_paths(self, save_path: str | Path) -> None:
        """
        Updates save-specific file paths used outside panel-managed files.

        Args:
            save_path: The active adventure save directory.
        """
        save_directory = Path(save_path)

        self.current_adventure_path = str(save_directory)
        self.secret_path = str(save_directory / "secret.txt")
        self.world_path = str(save_directory / "World.md")
        self.sales_ledger_path = str(save_directory / "Sales Ledger.md")
        
    def _reconstruct_merchant_tables(self, text: str) -> str:
        """
        Parses the token-saving OOG merchant summaries back into readable UI grids.
        Handles multi-line markdown strings by utilizing the re.DOTALL flag.
        
        Args:
            text (str): The raw markdown text to parse.
            
        Returns:
            str: The modified string with HTML grids injected where the OOG text was.
        """
        if not text: return text
        
        import re
        from tabulate import tabulate
        
        # The pattern remains the same, but we will apply the DOTALL flag when searching
        pattern = r"\\?\*?\(OOG: A merchant table is listed detailing the following items:\s*(.*?)\.\)\\?\*?"
        
        # Added flags=re.DOTALL so the search can span across the hard line breaks in the Markdown file
        #logging.info(f"Regex matches for the merchant table pattern: {re.search(pattern, text, flags=re.DOTALL)}")
        
        def replace_with_grid(match):
            """
            Callback function for re.sub to process each matched merchant table.
            """
            raw_items_string = match.group(1)
            clean_items_string = raw_items_string.replace('\n', ' ').replace('\r', '')
            
            table_data = []
            
            # --- SAFER REGEX ---
            # Group 1: Name (Allows internal apostrophes via backtracking)
            # Group 2: Description (Optional)
            # Group 3: Price (Optional)
            pattern = r"'(.+?)'(?:\s*-\s*(.*?)\s*\(([^)]+)\))?(?=\s*,|\s*$)"
            
            for item_match in re.finditer(pattern, clean_items_string):
                item_name = item_match.group(1).strip()
                
                # Safely assign description and price only if the regex actually found them
                item_description = item_match.group(2).strip() if item_match.group(2) else ""
                item_price = item_match.group(3).strip() if item_match.group(3) else ""
                
                table_data.append([item_name, item_description, item_price])
                
            if table_data:
                headers = ["Item Name", "Description", "Price"]
                grid = tabulate(table_data, headers=headers, tablefmt="rounded_grid")
                
                formatted_html = (
                f"<pre style=\"font-family: Consolas, 'Courier New', monospace; "
                f"line-height: 1.0; padding: 6px;\">\n\n{grid}\n</pre>\n\n"
                )
                return f"{formatted_html}"
            else: 
                logging.error(f"Failed to parse individual items from merchant table. Raw string: {clean_items_string}")
                return match.group(0)
            
        # IMPORTANT: Apply flags=re.DOTALL here as well so the substitution catches the multi-line match
        return re.sub(pattern, replace_with_grid, text, flags=re.DOTALL)

    def after(self, ms: int, func) -> None:
        self.ui.run_later.emit(int(ms), func)

    def load_rules(self) -> str:
        """
        Loads the GM rules template and injects current runtime values.

        Returns:
            str: The finalized system-instruction text for Gemini.
        """
        formatted_rules = self.configuration.default_rules or ""

        if not formatted_rules.strip():
            logging.error("DEFAULT_RULES is empty. Check prompt_templates/default_rules.md.")
            return ""

        currency_list = self.player.get_world_currencies()
        stats_list = self.player.get_status_dict().get("tracked_stats", [])
        sounds_list = self.sound_manager.get_valid_track_names()

        if currency_list:
            currency_names = ", ".join(
                f"{currency.get('name', 'Unit')} (Value: {currency.get('value', 1)})"
                for currency in currency_list
                if isinstance(currency, dict)
            )
        else:
            currency_names = "No currencies defined yet."

        if stats_list:
            stats_names = ", ".join(
                stat.get("name", "UNKNOWN STAT")
                for stat in stats_list
                if isinstance(stat, dict)
            )
        else:
            stats_names = "No stats defined yet."

        if sounds_list:
            sounds_names = ", ".join(sounds_list)
        else:
            sounds_names = "No sounds defined yet."

        formatted_rules = formatted_rules.replace("{DYNAMIC_CURRENCIES}", currency_names)
        formatted_rules = formatted_rules.replace("{DYNAMIC_STATS}", stats_names)
        formatted_rules = formatted_rules.replace("{VALID_SOUND_FILE_NAMES}", sounds_names)

        return formatted_rules
    
    def load_creative_ideas(self) -> str:
        creative_ideas = self.configuration.creative_ideas or ""
        
        if not creative_ideas.strip():
            logging.warning("No creative ideas document found.")
            return ""
        else:
            return creative_ideas

    def save_game(self) -> None:
        """
        Saves all markdown tabs and the current game state to JSON.
        No longer saves Chat History to the JSON to avoid data duplication.
        """
        if not self.current_adventure_path:
            logging.warning("Warning: No valid save path.")
            return

        # Save Markdown tabs (This will safely save history.md via the History panel)
        try:
            for widget_name in self.notebook_widgets:
                widget_instance = self.notebook_widgets.get(widget_name)
                if widget_instance is not None and hasattr(widget_instance, "save_now"):
                    widget_instance.save_now()
        except Exception as error:
            logging.error(f"Qt save error: markdown save failed. Details: {error}")

        # Save JSON state (excluding the deprecated Chat History)
        try:
            status_data = self.player.get_status_dict()
            save_data = {
                "Status": status_data,
                "karmic_streak": int(getattr(self.player, "karmic_streak", 0) or 0),
                "current_music": self.sound_manager.current_music
            }
            history_path = os.path.join(self.current_adventure_path, "savegame.json")
            #logging.info(f"Saved to {history_path}.")
            FileManager.save_json_data(history_path, save_data)
        except Exception as error:
            logging.error(f"Qt save error: savegame.json write failed. Details: {error}")
    
    def _resolve_save_path_for_recap(self) -> str | None:
        """
        Pick a save folder to read savegame.json from.
        - Prefer current_adventure_path if set.
        - Otherwise, pick the most recently modified save folder containing savegame.json.
        Utilizes pathlib for directory iteration and stat checking.
        """
        if self.current_adventure_path:
            return self.current_adventure_path
        
        saves_directory = self.configuration.saves_directory
        
        if not saves_directory.exists():
            logging.warning("Saves directory does not exist: %s", saves_directory)
            return None

        if not saves_directory.is_dir():
            logging.warning("Saves path is not a directory: %s", saves_directory)
            return None

        try:
            best_path: str | None = None
            best_mtime = -1.0
            
            # Iterate over the items in the SAVES_DIR Path object
            for save_directory in saves_directory.iterdir():
                if not save_directory.is_dir():
                    continue

                savegame_file = save_directory / "savegame.json"
                if not savegame_file.exists():
                    continue

                modification_time = savegame_file.stat().st_mtime
                if modification_time > best_mtime:
                    best_mtime = modification_time
                    best_path = str(save_directory)

            return best_path

        except Exception as recap_resolution_error:
            logging.exception(
                "Failed to resolve save path for recap. Exception details: %s",
                recap_resolution_error,
            )
            return None
        
    first_loaded_game_history = ""    
        
    def load_savegame_state(self, save_path: str) -> dict:
        """
        Loads savegame.json, hydrates the Player object, and syncs UI.
        No longer overwrites conversation_history from JSON.
        """
        self.set_adventure_paths(save_path)
        self.player.set_save_path(save_path)

        savegame_path = os.path.join(save_path, "savegame.json")
        save_data = FileManager.load_json_data(savegame_path) or {}

        # Player meta
        try:
            self.player.karmic_streak = int(save_data.get("karmic_streak", 0) or 0)
        except Exception as error:
            logging.error(f"Failed to load karmic streak: {error}")
            self.player.karmic_streak = 0
            
        saved_music = save_data.get("current_music")
        if saved_music:
            self.sound_manager.play_music(saved_music)
            
        currencies = save_data.get("Currencies", [{}])
        if currencies:
            self.player.world_currencies = currencies
        else:
            # Default fallback if missing
            self.player.world_currencies = [{"name": "Copper Piece", "value": 1}, {"name": "Silver Piece", "value": 10}]

        # Player status
        status_data = save_data.get("Status") or {}

        if isinstance(status_data, dict) and status_data:
            self.player.load_from_dict(status_data)

        legacy_currencies = save_data.get("Currencies")
        if not self.player.world_currencies and isinstance(legacy_currencies, list):
            self.player.world_currencies = legacy_currencies

        if not self.player.world_currencies:
            self.player.world_currencies = [
                {"name": "Copper Piece", "value": 1},
                {"name": "Silver Piece", "value": 10},
                {"name": "Gold Piece", "value": 100}
            ]
            
        try:
            for widget_name in self.notebook_widgets:
                if "History" in widget_name:
                    self.notebook_widgets[widget_name].set_base_path(save_path)
                    self.first_loaded_game_history = self.notebook_widgets[widget_name].get_text()
                else:
                    self.notebook_widgets[widget_name].set_base_path(save_path)
        except Exception as error:
            logging.error(f"Failed to load widget base paths: {error}")

        self._sync_player_state_to_ui()
        return save_data

    def generate_recap(self) -> None:
        """
        Loads the most recent save, syncs status, and prints a recap.
        Extracts the recap directly from the History panel's loaded text,
        sanitizing it for PySide6 rendering.
        """
        try:
            save_path = self._resolve_save_path_for_recap()
            if not save_path:
                self.story_tab.print_text("No save found to recap from.", sender="System")
                return

            # This triggers set_base_path for all panels, which loads history.md naturally
            self.load_savegame_state(save_path)
            
            last_gm_message = ""
            
            # Extract the last GM response directly from the History tab's markdown
            if "History" in self.notebook_widgets:
                # Replace \r to prevent Qt from applying weird spacing/fallback fonts
                if self.first_loaded_game_history != "":
                    history_text = self.notebook_widgets["History"].get_text().replace('\r', '').strip()
                else:
                    history_text = self.first_loaded_game_history
                
                if history_text:
                    # Split exchanges using the established divider
                    exchanges = [exchange.strip() for exchange in history_text.split("// NEW EXCHANGE") if exchange.strip()]
                    if exchanges:
                        last_exchange = exchanges[-1]
                        exchange_lines = last_exchange.split('\n')
                        gm_response_lines = []
                        
                        for line in exchange_lines:
                            # Filter out the player's prompt and system messages
                            if line.startswith("> ") or line.startswith("**System:"):
                                continue
                                
                            # Clean up the hardcoded **GM:** if it happens to be the very first startup exchange
                            if line.startswith("**GM:**"):
                                line = line.replace("**GM:**", "", 1).strip()
                                
                            gm_response_lines.append(line)
                        
                        # Join the sanitized lines back together
                        last_gm_message = "\n".join(gm_response_lines).strip()
                
            if last_gm_message:
                #logging.info("There is a last gm message, reconstructing merchant tables now!")
                last_gm_message = self._reconstruct_merchant_tables(last_gm_message)
                self.story_tab.print_text(last_gm_message + "\n\nWhat do you do now?", sender="")
            else:
                #logging.info("There is NOT a last gm message!")
                self.story_tab.print_text(f"What do you do now?\n")
            
        except Exception as error:
            logging.error(f"Generate recap failed: {error}")
            self.story_tab.print_text("Recap failed (see logs).", sender="System")
            
        self.first_loaded_game_history = ""
            
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
    
    def get_day(self) -> int: return self.player.day
    
    def get_time(self) -> str: return self.player.time

    def _sync_player_state_to_ui(self) -> None:
        """Thread-safe push of Player status into the Qt status header."""
        s = self.player.get_status_dict()

        def _apply():
            try: 
                self.win.story_panel.set_status(
                    turn=s.get("turn") or 1,
                    location=s.get("location") or "Character Creation",
                    day=s.get("formatted_date", f"Day {s.get('day')}"), # Pass the rich date here!
                    time=s.get("time") or "12:00 A.M.",
                    weather=s.get("weather") or "Sunny",
                    temperature=s.get("temperature") or 76,
                    dynamic_stats=s.get("tracked_stats", [])
                )
            except Exception as e:
                logging.exception(f"Could not set story panel status: {e}")
            
        for widget_name in ("Quests", "Calendar"):
            widget = self.notebook_widgets.get(widget_name)
            if widget is not None and hasattr(widget, "refresh_display"):
                try:
                    widget.refresh_display()
                except Exception as error:
                    logging.exception("Failed to refresh %s panel: %s", widget_name, error)

        # AIManager calls this from worker threads; dispatch to UI thread.
        try:
            self.ui.run_now.emit(_apply)
        except Exception as e:
            logging.exception(f"Could not call ui.run_now.emit: {e}")

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

    configuration = get_configuration()

    save_name = menu.selected_save
    save_path_obj = configuration.saves_directory / save_name
    save_path = str(save_path_obj)

    win = MainWindow()
    app_ctx = QtAppContext(win, configuration)

    from ai_manager import AIManager
    win.app = app_ctx
    for panel in (
    win.inventory_panel,
    win.skills_panel,
    win.processing_panel,
    win.recipes_panel,
    win.character_panel,
    win.world_panel,
    win.journal_panel,
    win.history_panel,
    win.quests_panel,
    win.sales_ledger_panel,
    win.calendar_panel,
    ):
        panel.app = app_ctx
    win.ai_manager = AIManager(app_ctx)
    win.setWindowTitle(f"{save_name}")
    win.show()
    
    win.story_panel.volume_changed.connect(app_ctx.sound_manager.set_volume)

    def _boot_selected_save() -> None:
        FileManager.update_logger_path(save_name)
        app_ctx.player.set_save_path(save_path)

        # Utilize pathlib to construct subsequent paths cleanly
        save_directory_path = Path(save_path)
        savegame_path = str(save_directory_path / "savegame.json")
        secret_path = str(save_directory_path / "secret.txt")
        world_path = str(save_directory_path / "world.md")
        sales_ledger_path = str(save_directory_path / "sales_ledger.md")
        
        try:
            if os.path.exists(savegame_path):
                app_ctx.load_savegame_state(save_path)
                win._load_ui_state(save_path)
                app_ctx.generate_recap()
                return
            else: 
                logging.warning("No save game path exists.")
            app_ctx.set_adventure_paths(save_path)

            FileManager.create_file_if_not_exists(app_ctx.secret_path)
            FileManager.create_file_if_not_exists(app_ctx.world_path, "# World\n\n")
            FileManager.create_file_if_not_exists(app_ctx.sales_ledger_path, "# Sales Ledger\n\n")
                
        except Exception as boot_sequence_error:
            logging.exception(f"Could not boot selected save. Exception details: {boot_sequence_error}")

        app_ctx.current_adventure_path = save_path
        app_ctx.conversation_history = []
        try:
            for w in app_ctx.notebook_widgets.values():
                w.set_base_path(save_path)
        except Exception:
            logging.exception("Failed to set base path for panels")

        source_dialog = NewGameSourceDialog(win)
        if source_dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)

        template_data = CreationTemplateStore.load_template(source_dialog.selected_template_path)

        wizard = CreationWizard(win, template_data=template_data)
        if wizard.exec() == QDialog.DialogCode.Accepted:
            wizard_data = wizard.get_wizard_data()
            CreationTemplateStore.save_creation_settings(save_directory_path, wizard_data)
            app_ctx.player.world_currencies = wizard_data["currencies"]
            app_ctx.player.tracked_stats = wizard_data["stats"]
            app_ctx._sync_player_state_to_ui()
            
            if win.ai_manager != None:
                threading.Thread(target=win.ai_manager.start_new_game_from_wizard, args=(wizard_data,), daemon=True).start()
        else:
            # If the user closes the wizard without finishing, exit or return to menu
            sys.exit(0)
    
    QTimer.singleShot(0, _boot_selected_save)
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        logging.exception(f"Error: {e}")