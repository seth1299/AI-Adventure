# qt_ui/main_window.py
from __future__ import annotations
from qt_ui.currency_dialog import CurrencyManagerDialog
from qt_ui.stats_dialog import StatsManagerDialog
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QDockWidget,
    QWidget,
)
from .markdown_panel import MarkdownPanel
from .story_panel import StoryPanel
from ai_manager import AIManager
from PySide6.QtWidgets import QDialog
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


class MainWindow(QMainWindow):
    """
    Qt shell for the app.

    Initial design:
    - Use dock widgets for "tabs" so the user can drag/reorder and float panels.
    - Keep the central widget as Story for now (we can change later).
    """

    def __init__(self, app_context=None) -> None:
        super().__init__()
        self.setWindowTitle("AI RPG Adventure (Qt)")

        # Reasonable default size; user can resize.
        self.resize(1100, 750)

        # Central widget: Story
        self.story_panel = StoryPanel(self)
        self.setCentralWidget(self.story_panel)
        self.app = app_context
        self.ai_manager = AIManager(self.app) if self.app is not None else None

        self.story_panel.send_requested.connect(self._on_send_requested)
        self.story_panel.menu_requested.connect(self._on_menu_requested)
        self.story_panel.currency_requested.connect(self.open_currency_menu)
        self.story_panel.stats_requested.connect(self.open_stats_menu)
        self.story_panel.help_requested.connect(self.open_help_menu)

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

    def _add_dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> None:
        dock = QDockWidget(title, self)
        dock.setWidget(widget)

        # Float / move / close supported.
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        self.addDockWidget(area, dock)
        self._docks[title] = dock

    def get_dock(self, title: str) -> QDockWidget | None:
        return self._docks.get(title)
    
    def closeEvent(self, event):
        """Ensure game state is saved when the window is closed."""
        try:
            if self.app is not None:
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
            self.app.generate_recap()
            return

        # New game flow
        self.app.current_adventure_path = save_path
        self.app.is_creating = True
        self.app.conversation_history = ""
        try:
            for w in self.app.notebook_widgets.values():
                w.set_base_path(save_path)
        except Exception:
            pass

        self.app._sync_player_state_to_ui()
        self.story_panel.print_text("System: Initialization Sequence Started...", sender="System")
        if self.ai_manager is not None:
            threading.Thread(target=self.ai_manager.start_creation_wizard, daemon=True).start()
            
    from qt_ui.currency_dialog import CurrencyManagerDialog

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
                
                msg = f"Currencies successfully updated ({len(saved_currencies)} total):\n"
                for cur in saved_currencies:
                    msg += f" • {cur['name']} (Worth: {cur['value']} base units)\n"
                
                self.story_panel.print_text(msg, sender="System")
                
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
                msg = f"Tracked Stats successfully updated:\n"
                for st in saved_stats:
                    status = "Enabled" if st['enabled'] else "Disabled"
                    msg += f" • {st['name']} ({status}): {st['value']}\n"
                
                self.story_panel.print_text(msg, sender="System")
        except Exception as e:
            error_msg = f"Error opening stats menu: {str(e)}"
            logging.exception(error_msg)
            self.story_panel.print_text(error_msg, sender="System Error")