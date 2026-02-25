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
from config import SAVES_DIR, SOUNDS_DIR
import random

class _NullWidget:
    """Safe no-op widget used during the Qt migration."""
    def get_text(self) -> str:
        return ""

    def set_text(self, _text: str) -> None:
        return

    # Inventory-ish
    def autonomous_add(self, *_a, **_k): return "[System: Inventory tag ignored in Qt build]"
    def autonomous_remove(self, *_a, **_k): return "[System: Inventory tag ignored in Qt build]"
    def modify_item(self, *_a, **_k): return "[System: Inventory tag ignored in Qt build]"
    def add_food(self, *_a, **_k): return "[System: Food tag ignored in Qt build]"
    def consume_food(self, *_a, **_k): return "[System: Consume tag ignored in Qt build]"

    # Skills-ish
    def force_learn_skill(self, *_a, **_k): return

    # Processing-ish
    def check_active_tasks(self, *_a, **_k): return []
    def add_timed_process(self, *_a, **_k): return "[System: Processing tag ignored in Qt build]"
    def remove_process(self, *_a, **_k): return "[System: Processing tag ignored in Qt build]"
    def add_project(self, *_a, **_k): return "[System: Project tag ignored in Qt build]"
    def get_required_skill(self, *_a, **_k): return ""
    def apply_work_hours(self, *_a, **_k): return "[System: Work tag ignored in Qt build]"

    # Recipes-ish
    def add_recipe_from_tag(self, *_a, **_k): return "[System: Recipe tag ignored in Qt build]"

class _UiDispatcher(QObject):
    run_now = Signal(object)          # callable
    run_later = Signal(int, object)   # ms, callable

    def __init__(self, parent=None):
        super().__init__(parent)
        self.run_now.connect(self._run_now, Qt.ConnectionType.QueuedConnection)
        self.run_later.connect(self._run_later, Qt.ConnectionType.QueuedConnection)

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

    def print_text(self, text: str, sender: str = "GM") -> None:
        self._ui.run_now.emit(lambda: self._panel.print_text(text, sender=sender))

    def set_controls_state(self, enabled: bool, status_text: str | None = None) -> None:
        self._ui.run_now.emit(lambda: self._panel.set_controls_state(enabled, status_text))
        



class QtAppContext:
    """Minimal adapter to let the existing AIManager run under Qt."""

    def __init__(self, win):
        self.win = win
        self.ui = _UiDispatcher(win)

        self.is_creating = False
        self.current_adventure_path = None

        self.creation_summary_path = os.path.join(SAVES_DIR, "creation_summary.txt")
        self.conversation_history = ""

        self.player = Player()
        self.sound_manager = SoundManager(SOUNDS_DIR)

        # API surface AIManager expects
        self.story_tab = QtStoryTabAdapter(win.story_panel, self.ui)

        null = _NullWidget()
        self.notebook_widgets = {
            "Inventory": null,
            "Skills": null,
            "Processing": null,
            "Recipes": null,
            "Character": null,
            "World": null,
            "Journal": null,
        }

        self._sync_player_state_to_ui()

    def after(self, ms: int, func) -> None:
        self.ui.run_later.emit(int(ms), func)

    def load_rules(self) -> str:
        return FileManager.get_rules(self.current_adventure_path)

    def save_game(self) -> None:
        # TODO: wire up saving in the Qt build
        return

    def _get_skill_level(self, _skill_name: str) -> int:
        return 0

    def perform_skill_check(self, _skill_name: str) -> str:
        return str(random.randint(1, 20))

    def _advance_time_hours(self, _hours: float) -> None:
        return

    def _sync_player_state_to_ui(self) -> None:
        s = self.player.get_status_dict()
        self.win.story_panel.set_status(
            turn=s.get("turn"),
            location=s.get("location"),
            day=f"Day {s.get('day')}",
            time=s.get("time"),
            nutrition=str(s.get("nutrition")),
            stamina=str(s.get("stamina")),
        )

def main() -> int:
    FileManager.setup_initial_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("AI RPG Adventure")

    # Optional icon (if you already have game_icon.ico in your bundled resources)
    try:
        from PySide6.QtGui import QIcon
        icon_path = FileManager.resource_path("game_icon.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception as e:
        logging.error(f"Qt icon error: {e}")

    win = MainWindow()
    app_ctx = QtAppContext(win)

    from ai_manager import AIManager
    win.app = app_ctx
    win.ai_manager = AIManager(app_ctx)
    win.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())