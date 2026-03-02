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
import random, re
from qt_ui.main_menu_dialog import MainMenuDialog
import threading
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import QTimer, QObject, Signal, Slot, Qt, QThread
from queue import Queue

class _NullWidget:
    """Safe no-op widget used during the Qt migration."""
    def get_text(self) -> str:
        return ""

    def set_text(self, _text: str) -> None:
        return
    
    def set_base_path(self, *_a, **_k) -> None:
        return

    def save_now(self, *_a, **_k) -> None:
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

    def print_text(self, text: str, sender: str = "GM") -> None:
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
        world = QtPanelAdapter(getattr(win, "world_panel", null), self.ui)
        journal = QtPanelAdapter(getattr(win, "journal_panel", null), self.ui)
        inventory = QtPanelAdapter(getattr(win, "inventory_panel", null), self.ui)
        skills = QtPanelAdapter(getattr(win, "skills_panel", null), self.ui)
        recipes = QtPanelAdapter(getattr(win, "recipes_panel", null), self.ui)
        character = QtPanelAdapter(getattr(win, "character_panel", null), self.ui)
        processing = QtPanelAdapter(getattr(win, "processing_panel", null), self.ui)

        self.notebook_widgets = {
            "Inventory": inventory,
            "Skills": skills,
            "Processing": processing,
            "Recipes": recipes,
            "Character": character,
            "World": world,
            "Journal": journal,
        }

        self._sync_player_state_to_ui()

    def after(self, ms: int, func) -> None:
        self.ui.run_later.emit(int(ms), func)

    def load_rules(self) -> str:
        return FileManager.get_rules(self.current_adventure_path)

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
            history_list = [line for line in (self.conversation_history or "").split("\n") if line.strip()]
            status_data = self.player.get_status_dict()
            save_data = {
                "Chat History": history_list,
                "Status": status_data,
                "is_creating": bool(self.is_creating),
                "karmic_streak": int(getattr(self.player, "karmic_streak", 0) or 0),
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
        except Exception:
            logging.exception("Failed to resolve save path for recap")
            return None
        
    def load_savegame_state(self, save_path: str) -> dict:
        """Load savegame.json and hydrate Player + app flags, then sync status UI."""
        self.current_adventure_path = save_path

        sg_path = os.path.join(save_path, "savegame.json")
        data = FileManager.load_json_data(sg_path) or {}

        # Basic flags
        self.is_creating = bool(data.get("is_creating", False))

        # Player meta
        try:
            self.player.karmic_streak = int(data.get("karmic_streak", 0) or 0)
        except Exception:
            self.player.karmic_streak = 0

        # Player status
        status_data = data.get("Status") or {}
        if isinstance(status_data, dict) and status_data:
            self.player.load_from_dict(status_data)

        # History (keep around for later panels)
        hist = data.get("Chat History") or []
        if isinstance(hist, list):
            self.conversation_history = "\n".join([h for h in hist if isinstance(h, str)])
        elif isinstance(hist, str):
            self.conversation_history = hist
        else:
            self.conversation_history = ""
            
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

            last_gm: str | None = None
            if isinstance(history, list):
                for line in reversed(history):
                    if isinstance(line, str) and line.strip().startswith("GM:"):
                        last_gm = line.strip()[len("GM:"):].strip()
                        break

            if not last_gm:
                self.story_tab.print_text("No GM message found in savegame.json.", sender="System")
                return

            self.story_tab.print_text(last_gm, sender="GM")
        except Exception:
            logging.exception("Generate recap failed")
            self.story_tab.print_text("Recap failed (see logs).", sender="System")

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
    
    def _skills_json_path(self) -> str | None:
        """Return <save>/skills.json if we have a loaded save."""
        if not self.current_adventure_path:
            return None
        return os.path.join(self.current_adventure_path, "skills.json")

    def _load_skills_data(self) -> list[dict]:
        path = self._skills_json_path()
        if not path or not os.path.exists(path):
            return []
        data = FileManager.load_json_data(path)
        return data if isinstance(data, list) else []

    def _save_skills_data(self, data: list[dict]) -> None:
        path = self._skills_json_path()
        if not path:
            return
        try:
            data.sort(key=lambda x: str((x or {}).get("Name", "")).lower())
        except Exception:
            pass
        FileManager.save_json_data(path, data)

    def _get_skill_level(self, skill_name: str) -> int:
        clean = (skill_name or "").split("(")[0].strip().title()
        try:
            data = self._load_skills_data()
            for item in data:
                if str(item.get("Name", "")).lower() == clean.lower():
                    return int(item.get("Level", 0) or 0)
        except Exception as e:
            logging.error(f"Get skill level error: {e}")
        return 0

    def perform_skill_check(self, skill_name: str) -> int:
        """Rolls 1d20 + skill level + nutrition/stamina modifiers, then updates skills.json."""
        clean_name = (skill_name or "").split("(")[0].strip().title()

        data = self._load_skills_data()
        skill_entry = None
        for item in data:
            if str(item.get("Name", "")).lower() == clean_name.lower():
                skill_entry = item
                break

        if not skill_entry:
            skill_entry = {"Name": clean_name, "Level": 0, "XP": 0, "Threshold": 5}
            data.append(skill_entry)
            self.story_tab.print_text(f"Learned new skill: {clean_name}!", sender="System")

        die_roll = random.randint(1, 20)

        # Karma system (same logic as Tk build)
        try:
            new_roll, intervened = self.player.check_karma_intervention(die_roll)
            die_roll = int(new_roll)
            if not intervened:
                self.player.update_karma(die_roll)
        except Exception:
            # If anything goes wrong, just keep the raw roll.
            pass

        # XP + level up
        try:
            skill_entry["XP"] = int(skill_entry.get("XP", 0) or 0) + 1
        except Exception:
            skill_entry["XP"] = 1

        leveled_up = False
        try:
            xp = int(skill_entry.get("XP", 0) or 0)
            th = int(skill_entry.get("Threshold", 5) or 5)
        except Exception:
            xp, th = 0, 5

        if xp >= th:
            try:
                skill_entry["Level"] = int(skill_entry.get("Level", 0) or 0) + 1
            except Exception:
                skill_entry["Level"] = 1
            skill_entry["XP"] = 0
            try:
                skill_entry["Threshold"] = int(skill_entry.get("Threshold", 5) or 5) + 2
            except Exception:
                skill_entry["Threshold"] = 7
            leveled_up = True

        self._save_skills_data(data)

        # Modifiers
        bonus_from_nutrition = 0
        try:
            if self.player.nutrition >= 85:
                bonus_from_nutrition = 1
            elif self.player.nutrition <= 40:
                bonus_from_nutrition = -3
        except Exception:
            pass

        bonus_from_stamina = 0
        try:
            if self.player.stamina >= 85:
                bonus_from_stamina = 1
            elif self.player.stamina <= 40:
                bonus_from_stamina = -3
        except Exception:
            pass

        try:
            skill_bonus = int(skill_entry.get("Level", 0) or 0)
        except Exception:
            skill_bonus = 0

        total = int(die_roll) + int(skill_bonus) + int(bonus_from_nutrition) + int(bonus_from_stamina)

        # Message
        bonus_from_skill_message = f"{skill_bonus} (from Skill level)"
        bonus_from_nutrition_message = (
            f" +{bonus_from_nutrition} (bonus from high nutrition)"
            if bonus_from_nutrition > 0
            else f" {bonus_from_nutrition} (penalty from low nutrition)"
            if bonus_from_nutrition < 0
            else ""
        )
        bonus_from_stamina_message = (
            f" +{bonus_from_stamina} (bonus from high stamina)"
            if bonus_from_stamina > 0
            else f" {bonus_from_stamina} (penalty from low stamina)"
            if bonus_from_stamina < 0
            else ""
        )

        msg = (
            f"Rolling {clean_name}: {die_roll} + ("
            f"{bonus_from_skill_message}{bonus_from_nutrition_message}{bonus_from_stamina_message}"
            f") = {total}"
        )

        if leveled_up:
            msg += f"\nLEVEL UP! {clean_name} is now Level {skill_entry.get('Level', 0)}!"
        else:
            msg += f"\n{clean_name}: {skill_entry.get('XP', 0)} / {skill_entry.get('Threshold', 0)} XP towards next level up."

        self.story_tab.print_text(msg, sender="System")
        return total

    def _advance_time_hours(self, _hours: float) -> None:
        return

    def _sync_player_state_to_ui(self) -> None:
        """Thread-safe push of Player status into the Qt status header."""
        s = self.player.get_status_dict()

        def _apply():
            self.win.story_panel.set_status(
                turn=s.get("turn"),
                location=s.get("location"),
                day=f"Day {s.get('day')}",
                time=s.get("time"),
                nutrition=str(s.get("nutrition")),
                stamina=str(s.get("stamina")),
            )

        # AIManager calls this from worker threads; dispatch to UI thread.
        self.ui.run_now.emit(_apply)

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
    win.ai_manager = AIManager(app_ctx)
    win.setWindowTitle(f"AI RPG Adventure (Qt) - {save_name}")
    win.show()

    def _boot_selected_save() -> None:
        FileManager.update_logger_path(save_name)

        savegame_path = os.path.join(save_path, "savegame.json")
        if os.path.exists(savegame_path):
            app_ctx.load_savegame_state(save_path)
            app_ctx.generate_recap()
            return

        # New game flow
        app_ctx.current_adventure_path = save_path
        app_ctx.is_creating = True
        app_ctx.conversation_history = ""
        try:
            for w in app_ctx.notebook_widgets.values():
                w.set_base_path(save_path)
        except Exception:
            logging.exception("Failed to set base path for panels")

        app_ctx._sync_player_state_to_ui()
        app_ctx.story_tab.print_text("System: Initialization Sequence Started...", sender="System")
        if win.ai_manager != None:
            threading.Thread(target=win.ai_manager.start_creation_wizard, daemon=True).start()
    
    QTimer.singleShot(0, _boot_selected_save)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())