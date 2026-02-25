# qt_ui/main_window.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QDockWidget,
    QWidget,
)

from .story_panel import StoryPanel
from .stub_panels import StubPanel
from ai_manager import AIManager


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
        self._add_dock("Inventory", StubPanel("Inventory (stub)"), area=Qt.DockWidgetArea.RightDockWidgetArea)
        self._add_dock("Skills", StubPanel("Skills (stub)"), area=Qt.DockWidgetArea.RightDockWidgetArea)
        self._add_dock("Processing", StubPanel("Processing (stub)"), area=Qt.DockWidgetArea.BottomDockWidgetArea)
        self._add_dock("Recipes", StubPanel("Recipes (stub)"), area=Qt.DockWidgetArea.BottomDockWidgetArea)
        self._add_dock("Character", StubPanel("Character (stub)"), area=Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("World", StubPanel("World (stub)"), area=Qt.DockWidgetArea.LeftDockWidgetArea)
        self._add_dock("Journal", StubPanel("Journal (stub)"), area=Qt.DockWidgetArea.LeftDockWidgetArea)

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
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
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
        # Placeholder for later (menu dialog / view swap)
        self.story_panel.print_text("Menu clicked (not wired yet).", sender="System")