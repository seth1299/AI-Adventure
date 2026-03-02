# qt_ui/main_window.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QDockWidget,
    QWidget,
)
from .markdown_panel import MarkdownPanel
from .story_panel import StoryPanel
from .stub_panels import StubPanel
from ai_manager import AIManager
from PySide6.QtWidgets import QDialog
from .main_menu_dialog import MainMenuDialog
from config import SAVES_DIR
from file_manager import FileManager
import os
import threading


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

        # Docks (stubs for now)
        self._docks: dict[str, QDockWidget] = {}
        #self._add_dock("Inventory", StubPanel("Inventory (stub)"), area=Qt.DockWidgetArea.RightDockWidgetArea)
        #self._add_dock("Skills", StubPanel("Skills (stub)"), area=Qt.DockWidgetArea.RightDockWidgetArea)
        #self._add_dock("Processing", StubPanel("Processing (stub)"), area=Qt.DockWidgetArea.BottomDockWidgetArea)
        #self._add_dock("Recipes", StubPanel("Recipes (stub)"), area=Qt.DockWidgetArea.BottomDockWidgetArea)
        #self._add_dock("Character", StubPanel("Character (stub)"), area=Qt.DockWidgetArea.LeftDockWidgetArea)
        self.world_panel = MarkdownPanel("World")
        self.journal_panel = MarkdownPanel("Journal")
        self.inventory_panel = MarkdownPanel("Inventory")
        self.skills_panel = MarkdownPanel("Skills")
        self.processing_panel = MarkdownPanel("Processing")
        self.recipes_panel = MarkdownPanel("Recipes")
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

        # You can connect StoryPanel signals here later:
        # self.story_panel.send_requested.connect(self._on_send_requested)
        # self.story_panel.menu_requested.connect(self._on_menu_requested)

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