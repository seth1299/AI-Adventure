# qt_ui/main_window.py
from __future__ import annotations
from qt_ui.currency_dialog import CurrencyManagerDialog
from qt_ui.stats_dialog import StatsManagerDialog
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QMainWindow,
    QDockWidget,
    QWidget,
    QDialog,
    QMenuBar
)
from .markdown_panel import MarkdownPanel
from .story_panel import StoryPanel
from ai_manager import AIManager
from .main_menu_dialog import MainMenuDialog
from config import SAVES_DIR
from file_manager import FileManager
import os
import threading
from .inventory_panel import InventoryPanel
from .skills_panel import SkillsPanel
from .processing_panel import ProcessingPanel
from .recipes_panel import RecipesPanel
import logging
from qt_ui.help_dialog import HelpDialog
from PySide6.QtGui import QActionGroup

class MainWindow(QMainWindow):
    """
    Qt shell for the app.

    Initial design:
    - Use dock widgets for "tabs" so the user can drag/reorder and float panels.
    - Keep the central widget as Story for now (we can change later).
    """

    def __init__(self, app_context=None) -> None:
        super().__init__()
        self.setObjectName("AI_Adventure_Main_Window")
        self.setWindowTitle("AI RPG Adventure")

        # Reasonable default size; user can resize.
        self.resize(1100, 750)

        # Central widget: Story
        self.story_panel = StoryPanel(self)
        self.setCentralWidget(self.story_panel)
        self.app = app_context
        self.ai_manager = AIManager(self.app) if self.app is not None else None

        # Only the send_requested signal remains on the StoryPanel
        self.story_panel.send_requested.connect(self._on_send_requested)

        # Docks (stubs for now)
        self._docks: dict[str, QDockWidget] = {}
        self.world_panel = MarkdownPanel("World")
        self.journal_panel = MarkdownPanel("Journal")
        self.inventory_panel = InventoryPanel(app_context=self.app)
        self.skills_panel = SkillsPanel()
        self.processing_panel = ProcessingPanel()
        self.recipes_panel = RecipesPanel()
        self.character_panel = MarkdownPanel("Character")
        self._add_dock("World", self.world_panel, area=Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("Journal", self.journal_panel, area=Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("Inventory", self.inventory_panel, area=Qt.DockWidgetArea.RightDockWidgetArea)
        self._add_dock("Skills", self.skills_panel, area=Qt.DockWidgetArea.RightDockWidgetArea)
        self._add_dock("Processing", self.processing_panel, area=Qt.DockWidgetArea.BottomDockWidgetArea)
        self._add_dock("Recipes", self.recipes_panel, area=Qt.DockWidgetArea.BottomDockWidgetArea)
        self._add_dock("Character", self.character_panel, area=Qt.DockWidgetArea.LeftDockWidgetArea)

        # Allow docks to tab together when dragged into same area
        self.setDockOptions(
            QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        
        self._setup_menu_bar()
        
    def _setup_menu_bar(self):
        """Creates the native OS-style top-left menu bar."""
        menu_bar = self.menuBar()
        
        # --- NEW: Expanded styling to apply to the Menu Bar AND the Dock Panels ---
        # Note: We apply this to `self` (the whole window) so it cascades down to the docks
        self.setStyleSheet("""
            QMenuBar {
                background-color: #2b2b2b;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                border-bottom: 2px solid #4CAF50;
                padding: 4px;
            }
            QMenuBar::item {
                spacing: 3px;
                padding: 4px 12px;
                background: transparent;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background: #4CAF50;
                color: white;
            }
            QMenu {
                background-color: #333333;
                color: white;
                border: 1px solid #555555;
                font-weight: normal;
            }
            QMenu::item:selected {
                background-color: #4CAF50;
            }
            
            /* --- NEW: Dock Widget Styling --- */
            QDockWidget {
                border: 2px solid #555555; /* Visible border around the whole dock */
                font-weight: bold;
                color: #ffffff;
            }
            QDockWidget::title {
                background: #333333;
                text-align: center;
                padding: 6px;
            }
            /* Adds a border directly to the contents inside the dock to separate them from the title */
            QDockWidget > QWidget {
                border: 1px solid #444444; 
                background-color: #2b2b2b;
            }
        """)
        
        # 1. Game Menu
        game_menu = menu_bar.addMenu("Game")
        
        action_save = game_menu.addAction("Save / Load Game")
        action_save.triggered.connect(self._on_menu_requested)
        
        action_currencies = game_menu.addAction("Manage Currencies")
        action_currencies.triggered.connect(self.open_currency_menu)
        
        action_stats = game_menu.addAction("Manage Tracked Stats")
        action_stats.triggered.connect(self.open_stats_menu)
        
        game_menu.addSeparator()
        
        self.narrator_menu = game_menu.addMenu("Narrator Voices")
        self._populate_narrator_menu()
        
        action_help = game_menu.addAction("Help")
        action_help.triggered.connect(self.open_help_menu)

        # --- 2. View Menu (NEW) ---
        view_menu = menu_bar.addMenu("View")
        
        # Qt's QDockWidget comes with a built-in toggle action that acts as a checkbox!
        for title, dock in self._docks.items():
            view_menu.addAction(dock.toggleViewAction())
            
    def _populate_narrator_menu(self):
        """
        Dynamically populates the Narrator sub-menu with available system voices.
        Uses a QActionGroup to make them mutually exclusive (like radio buttons).
        """
        available_voices = self.story_panel.get_available_voices()
        
        # Fallback if the user's OS has no TTS engines installed
        if not available_voices:
            empty_action = self.narrator_menu.addAction("No voices found on OS")
            empty_action.setEnabled(False)
            return

        # QActionGroup ensures only one voice can be "checked" at a time
        self.voice_action_group = QActionGroup(self)
        self.voice_action_group.setExclusive(True)

        current_voice = self.story_panel.tts.voice()
        current_voice_name = current_voice.name() if current_voice else ""

        for voice in available_voices:
            voice_name = voice.name()
            action = self.narrator_menu.addAction(voice_name)
            action.setCheckable(True)
            
            # Check the item if it matches our currently active engine
            if voice_name == current_voice_name:
                action.setChecked(True)
                
            self.voice_action_group.addAction(action)
            
            # We use a lambda to "bind" the specific voice_name to this iteration of the loop
            action.triggered.connect(lambda checked=False, name=voice_name: self._on_voice_selected(name))

    def _on_voice_selected(self, voice_name: str):
        """
        Triggered when a user clicks a voice in the dropdown menu.
        Changes the engine voice, plays a sample, and saves the new setting.
        """
        self.story_panel.set_voice_by_name(voice_name)
        self.story_panel.play_voice_sample()
        
        # Save immediately so the choice persists even if the game crashes
        self._save_ui_state()

    def _add_dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> None:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setObjectName(f"Dock_{title.replace(' ', '_')}")

        # Float / move / close supported.
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.addDockWidget(area, dock)
        self._docks[title] = dock

    def get_dock(self, title: str) -> QDockWidget | None:
        return self._docks.get(title)
    
    def closeEvent(self, event):
        """Ensure game state is saved when the window is closed."""
        try:
            if self.app is not None:
                self._save_ui_state()
                self.app.save_game()
        except Exception:
            pass

        super().closeEvent(event)
    
    def _on_send_requested(self, text: str) -> None:
        if self.ai_manager is None:
            self.story_panel.print_text("AI Manager not initialized.", sender="System")
            return
        self.ai_manager.handle_player_action(text)

    def _on_menu_requested(self) -> None:
        if self.app is None:
            self.story_panel.print_text("Menu not available (app context missing).", sender="System")
            return

        try:
            self.app.save_game()
        except Exception:
            pass

        dlg = MainMenuDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected_save:
            return

        save_name = dlg.selected_save
        save_path = os.path.join(SAVES_DIR, save_name)
        savegame_path = os.path.join(save_path, "savegame.json")

        FileManager.update_logger_path(save_name)
        self.setWindowTitle(f"AI RPG Adventure (Qt) - {save_name}")
        self.story_panel.set_log_text("")

        if os.path.exists(savegame_path):
            self.app.load_savegame_state(save_path)
            self._load_ui_state(save_path)
            self.app.generate_recap()
            return

        # New game flow
        self.app.current_adventure_path = save_path
        self.app.conversation_history = []
        try:
            for w in self.app.notebook_widgets.values():
                w.set_base_path(save_path)
        except Exception:
            pass

        # --- LAUNCH THE WIZARD POPUP ---
        from qt_ui.creation_wizard import CreationWizard
        wizard = CreationWizard(self)
        
        if wizard.exec() == QDialog.DialogCode.Accepted:
            wizard_data = wizard.get_wizard_data()
            
            # Assign Currencies and Stats to Player
            self.app.player.world_currencies = wizard_data["currencies"]
            self.app.player.tracked_stats = wizard_data["stats"]
            
            self.app._sync_player_state_to_ui()
            self.story_panel.print_text("System: Compiling universe parameters...", sender="System")
            
            if self.ai_manager is not None:
                threading.Thread(
                    target=self.ai_manager.start_new_game_from_wizard, 
                    args=(wizard_data,), 
                    daemon=True
                ).start()
        else:
            self.story_panel.print_text("System: New game creation cancelled.", sender="System")
            
    from qt_ui.currency_dialog import CurrencyManagerDialog
    
    def _save_ui_state(self) -> None:
        """Saves the exact layout, dock positions, window size, and panel visibility."""
        if self.app and getattr(self.app, 'current_adventure_path', None):
            ini_path = os.path.join(self.app.current_adventure_path, "ui_layout.ini")
            
            # QSettings handles the complex Qt serialization automatically
            settings = QSettings(ini_path, QSettings.Format.IniFormat)
            settings.setValue("geometry", self.saveGeometry())
            settings.setValue("windowState", self.saveState())
            settings.setValue("volume_level", self.story_panel.slider_volume.value())
            settings.setValue("narrator_enabled", self.story_panel.chk_narrator.isChecked())
            settings.setValue("narrator_volume", self.story_panel.slider_tts_volume.value())
            current_voice = self.story_panel.tts.voice()
            if current_voice:
                settings.setValue("narrator_voice", current_voice.name())

    def _load_ui_state(self, save_path: str) -> None:
        """Restores the UI layout from the save folder if it exists."""
        ini_path = os.path.join(save_path, "ui_layout.ini")
        if os.path.exists(ini_path):
            settings = QSettings(ini_path, QSettings.Format.IniFormat)
            
            geometry = settings.value("geometry")
            state = settings.value("windowState")
            
            # Safely restore both the overall window size and the internal panel layout
            if geometry:
                self.restoreGeometry(geometry)
            if state:
                self.restoreState(state)
                
            try:
                raw_volume = settings.value("volume_level", 100)
                
                # Prove to the type checker that this is a valid number/string
                if isinstance(raw_volume, (int, float, str)):
                    # float() inside int() ensures it doesn't crash if the setting saved as "100.0"
                    volume = int(float(raw_volume)) 
                    self.story_panel.slider_volume.setValue(volume)
            except (ValueError, TypeError) as e:
                logging.error(f"Error enabling narrator: {e}")
            
            narrator_val = settings.value("narrator_enabled", False)
            
            # Handle PySide6 QSettings quirk where booleans are sometimes returned as lowercase strings
            if isinstance(narrator_val, str):
                narrator_bool = narrator_val.lower() == 'true'
            else:
                narrator_bool = bool(narrator_val)
                
            try:
                saved_voice_name = settings.value("narrator_voice", "", type=str)
                if saved_voice_name and isinstance(saved_voice_name, str):
                    # This safely ignores the request if the voice doesn't exist on the new PC
                    self.story_panel.set_voice_by_name(saved_voice_name)
                    
                    # Instead of trusting the saved string, ask the engine what voice it is ACTUALLY using
                    # (This handles the fallback perfectly if the saved voice was missing)
                    if hasattr(self, 'voice_action_group'):
                        actual_voice = self.story_panel.tts.voice()
                        if actual_voice:
                            actual_voice_name = actual_voice.name()
                            for action in self.voice_action_group.actions():
                                if action.text() == actual_voice_name:
                                    action.setChecked(True)
                                    break
            except (ValueError, TypeError):
                pass
                
            # Same here, setChecked will trigger _toggle_narrator automatically
            self.story_panel.chk_narrator.setChecked(narrator_bool)

    def open_currency_menu(self):
        try:
            if self.app == None: return
            # Pass existing currencies into the dialog so they can be edited!
            dialog = CurrencyManagerDialog(self, existing_currencies=self.app.player.world_currencies)
            
            if dialog.exec(): 
                saved_currencies = dialog.final_currency_data
                
                # 1. Update the player class
                self.app.player.world_currencies = saved_currencies
                
                # 2. Force an immediate save to lock in the new economy
                self.app.save_game()
                
                sorted_for_msg = sorted(saved_currencies, key=lambda x: int(x.get("value", 1)), reverse=True)
                lowest_coin_name = sorted_for_msg[-1].get("name", "base units") if sorted_for_msg else "base units"
                
                #msg = f"Currencies successfully updated ({len(saved_currencies)} total):\n"
                #for cur in saved_currencies:
                #    msg += f" • {cur['name']} (Worth: {cur['value']} {lowest_coin_name})\n"
                
                #self.story_panel.print_text(msg, sender="System")
                
                # 3. Refresh the inventory UI to use the new math
                if hasattr(self.inventory_panel, "refresh_display"):
                    self.inventory_panel.refresh_display()
                    pass
                
        except Exception as e:
            error_msg = f"Error opening currency menu: {str(e)}"
            logging.exception(error_msg)
            self.story_panel.print_text(error_msg, sender="System Error")
            
    def open_help_menu(self):
        import logging
        try:
            # We don't need to pass data, just open it!
            dialog = HelpDialog(self)
            dialog.exec()
        except Exception as e:
            error_msg = f"Error opening help menu: {str(e)}"
            logging.exception(error_msg)
            self.story_panel.print_text(error_msg, sender="System Error")
            
            
    def open_stats_menu(self):
        if self.app == None: return
        try:
            dialog = StatsManagerDialog(self, existing_stats=self.app.player.tracked_stats)
            if dialog.exec(): 
                saved_stats = dialog.final_stats_data
                
                # Update player and save
                self.app.player.tracked_stats = saved_stats
                self.app.save_game()
                self.app._sync_player_state_to_ui()
                
                # Feedback loop
                """
                msg = f"Tracked Stats successfully updated:\n"
                for st in saved_stats:
                    status = "Enabled" if st['enabled'] else "Disabled"
                    msg += f" • {st['name']} ({status}): {st['value']}\n"
                
                self.story_panel.print_text(msg, sender="System")
                """
        except Exception as e:
            error_msg = f"Error opening stats menu: {str(e)}"
            logging.exception(error_msg)
            self.story_panel.print_text(error_msg, sender="System Error")