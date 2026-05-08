"""Centralized Qt dialog and wizard classes for AI RPG Adventure.

This module replaces the individual ``*_dialog.py`` files and keeps related
row widgets plus the new-game wizard in one import location.
"""

from __future__ import annotations

import logging, copy, os, shutil
from pathlib import Path
from typing import Any
from file_manager import FileManager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
    QRadioButton,
)

from config import SAVES_DIR
DEFAULT_GREGORIAN_CALENDAR: dict[str, Any] = {
    "weekdays": [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ],
    "months": [
        {"name": "January", "days": 31, "season": "Winter"},
        {"name": "February", "days": 28, "season": "Winter"},
        {"name": "March", "days": 31, "season": "Spring"},
        {"name": "April", "days": 30, "season": "Spring"},
        {"name": "May", "days": 31, "season": "Spring"},
        {"name": "June", "days": 30, "season": "Summer"},
        {"name": "July", "days": 31, "season": "Summer"},
        {"name": "August", "days": 31, "season": "Summer"},
        {"name": "September", "days": 30, "season": "Fall"},
        {"name": "October", "days": 31, "season": "Fall"},
        {"name": "November", "days": 30, "season": "Fall"},
        {"name": "December", "days": 31, "season": "Winter"},
    ],
}


def get_default_gregorian_calendar() -> dict[str, Any]:
    """Returns a safe copy of the default Gregorian calendar."""

    return copy.deepcopy(DEFAULT_GREGORIAN_CALENDAR)


def normalize_calendar_settings(raw_settings: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normalizes calendar settings while allowing partial custom calendars.

    Blank weekdays fall back to Gregorian weekdays.
    Blank month names or seasons fall back to the matching Gregorian month.
    Missing month data falls back to the Gregorian calendar.
    """

    defaults = get_default_gregorian_calendar()

    if not isinstance(raw_settings, dict):
        logging.warning("Calendar settings were not a dictionary. Falling back to Gregorian calendar.")
        return defaults

    raw_weekdays = raw_settings.get("weekdays", [])
    weekdays = [
        str(day).strip()
        for day in raw_weekdays
        if str(day).strip()
    ] if isinstance(raw_weekdays, list) else []

    if not weekdays:
        weekdays = defaults["weekdays"]

    raw_months = raw_settings.get("months", [])
    months: list[dict[str, Any]] = []

    if isinstance(raw_months, list):
        for index, raw_month in enumerate(raw_months):
            if not isinstance(raw_month, dict):
                logging.warning("Skipped malformed calendar month: %r", raw_month)
                continue

            fallback_month = defaults["months"][index % len(defaults["months"])]

            month_name = str(raw_month.get("name", "") or fallback_month["name"]).strip()
            season_name = str(raw_month.get("season", "") or fallback_month["season"]).strip()

            try:
                month_days = max(1, int(raw_month.get("days", fallback_month["days"])))
            except (TypeError, ValueError):
                logging.exception("Invalid month length in calendar row: %r", raw_month)
                month_days = int(fallback_month["days"])

            if not month_name:
                continue

            months.append(
                {
                    "name": month_name,
                    "days": month_days,
                    "season": season_name or "Unknown Season",
                }
            )

    if not months:
        months = defaults["months"]

    return {
        "weekdays": weekdays,
        "months": months,
    }

# ---- Merged from qt_ui/currency_dialog.py ----
class CurrencyRow(QWidget):
    """A single row representing one currency type."""
    def __init__(self, parent=None, name="", value=1, is_baseline=False):
        super().__init__(parent)
        self.is_baseline = is_baseline
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 5, 0, 5)

        # Currency Name Input
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Copper Piece")
        self.name_input.setText(name)
        
        # Currency Value Input
        self.value_input = QSpinBox()
        self.value_input.setRange(1, 1000000) 
        self.value_input.setValue(value)
        self.value_input.setSuffix(" Base Units")
        
        # Remove Button
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(30)

        # --- NEW: Lock down the baseline row ---
        if self.is_baseline:
            self.value_input.setEnabled(False)      # Lock the value at 1
            self.btn_remove.setEnabled(False)       # Disable the remove button
            # Optional: Make it visually obvious it's the base unit
            self.value_input.setToolTip("The Base Unit must always be worth 1.")

        self.row_layout.addWidget(QLabel("Name:"))
        self.row_layout.addWidget(self.name_input, stretch=2)
        self.row_layout.addWidget(QLabel(" Worth:"))
        self.row_layout.addWidget(self.value_input, stretch=1)
        self.row_layout.addWidget(self.btn_remove)

    def get_data(self):
        """Returns the data for this specific row."""
        return {
            "name": self.name_input.text().strip(),
            "value": self.value_input.value()
        }

class CurrencyManagerDialog(QDialog):
    """The pop-up sub-menu for managing world currencies."""
    def __init__(self, parent=None, existing_currencies=None):
        super().__init__(parent)
        self.setWindowTitle("Manage World Currency")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        self.main_layout = QVBoxLayout(self)
        
        info_label = QLabel(
            "Define your currencies relative to your cheapest coin.\n"
            "For example, if a Copper is your lowest, type \"Copper\" into the \"1 base unit\" row.\n"
            "If a Silver is worth 10 Coppers, type \"Silver\" followed by \"10 base units\"."
        )
        info_label.setWordWrap(True)
        self.main_layout.addWidget(info_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        self.main_layout.addWidget(self.scroll_area)

        self.btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Currency")
        self.btn_add.clicked.connect(self.add_currency_row)
        
        self.btn_save = QPushButton("Save && Close")
        self.btn_save.clicked.connect(self.save_and_close)
        
        self.btn_layout.addWidget(self.btn_add)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_save)
        self.main_layout.addLayout(self.btn_layout)

        self.rows = []

        # Load existing currencies or provide default starting rows
        if existing_currencies:
            has_baseline = False
            for cur in existing_currencies:
                val = cur.get("value", 1)
                
                # The first currency with a value of 1 becomes our baseline
                is_base = (val == 1) and not has_baseline
                if is_base: has_baseline = True
                
                self.add_currency_row(cur.get("name", ""), val, is_baseline=is_base)
                
            # Fallback just in case they somehow loaded a file without a baseline
            if not has_baseline:
                self.add_currency_row("Base Coin", 1, is_baseline=True)
        else:
            self.add_currency_row("Copper Piece", 1, is_baseline=True) # First one is locked
            self.add_currency_row("Silver Piece", 10)

    def add_currency_row(self, name="", value=1, is_baseline=False):
        """Adds a new currency row to the UI."""
        if len(self.rows) >= 9:
            QMessageBox.warning(self, "Limit Reached", "You can only have up to 9 currencies.")
            return

        row = CurrencyRow(name=name, value=value, is_baseline=is_baseline)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        
        row.btn_remove.clicked.connect(lambda: self.remove_currency_row(row))

    def remove_currency_row(self, row):
        """Removes a row from the UI and the tracking list."""
        if row.is_baseline:
            return # Extra safeguard: Do not remove baseline rows!
            
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

    def save_and_close(self):
        """Packages up the data and closes the dialog."""
        self.final_currency_data = []
        for row in self.rows:
            data = row.get_data()
            
            # --- NEW: Prevent the baseline unit from having a blank name ---
            if row.is_baseline and not data["name"]:
                QMessageBox.warning(self, "Validation Error", "The Base Unit (Value 1) cannot have a blank name!")
                return # Stops the save process and keeps the dialog open
                
            if data["name"]:  # Only save rows that have a name typed in
                self.final_currency_data.append(data)
                
        # Sort them by value so they are mathematically ordered
        self.final_currency_data.sort(key=lambda x: x["value"])
        self.accept()

# ---- Merged from qt_ui/stats_dialog.py ----
class StatRow(QFrame):
    # --- NEW: Added desc parameter ---
    def __init__(self, parent=None, name="", value=100, enabled=True, desc="", min_val=0, max_val=100):
        super().__init__(parent)
        
        # Make it look like a distinct card
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)

        # --- Top Row (Name and Value) ---
        self.top_row = QHBoxLayout()

        self.cb_enabled = QCheckBox()
        self.cb_enabled.setChecked(enabled)
        self.cb_enabled.setToolTip("Track this stat in the UI and AI Context?")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Health, Mana, Sanity")
        self.name_input.setText(name)
        
        self.min_input = QSpinBox()
        self.min_input.setRange(-10000, 10000)
        self.min_input.setValue(min_val)
        
        self.max_input = QSpinBox()
        self.max_input.setRange(-10000, 10000)
        self.max_input.setValue(max_val)
        
        self.value_input = QSpinBox()
        # 1. Dynamically set the range of the value input to strictly match the min and max
        # This ensures that when the dialog first loads, the value is instantly clamped.
        self.value_input.setRange(min_val, max_val) 
        self.value_input.setValue(value)
        self.value_input.setReadOnly(True)
        self.value_input.setToolTip("Tracked by AI. Cannot be changed manually.")

        # 2. Connect the min/max boxes so they automatically update the value box's limits in real-time.
        # If the Player lowers the Max below the current Value, Qt will natively clamp the Value down to match!
        self.min_input.valueChanged.connect(self.value_input.setMinimum)
        self.max_input.valueChanged.connect(self.value_input.setMaximum)
        
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(30)

        self.top_row.addWidget(self.cb_enabled)
        self.top_row.addWidget(QLabel("Name:"))
        self.top_row.addWidget(self.name_input, stretch=2)
        self.top_row.addWidget(QLabel("Min:"))
        self.top_row.addWidget(self.min_input)
        self.top_row.addWidget(QLabel("Max:"))
        self.top_row.addWidget(self.max_input)
        self.top_row.addWidget(QLabel("Value:"))
        self.top_row.addWidget(self.value_input)
        self.top_row.addWidget(self.btn_remove)
        # --- Bottom Row (AI Description) ---
        self.bottom_row = QHBoxLayout()
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("AI Rules (e.g. 'Max 100. Decreases when taking damage.') Be as specific as you can be. The more specific you are, the better the A.I. will be at tracking the stat.")
        self.desc_input.setText(desc)
        
        self.bottom_row.addWidget(QLabel("AI Rules:"))
        self.bottom_row.addWidget(self.desc_input, stretch=1)

        # Add both rows to the card
        self.main_layout.addLayout(self.top_row)
        self.main_layout.addLayout(self.bottom_row)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "value": self.value_input.value(),
            "min": self.min_input.value(), # Grab the minimum value
            "max": self.max_input.value(), # Grab the maximum value
            "enabled": self.cb_enabled.isChecked(),
            "description": self.desc_input.text().strip()
        }
class StatsManagerDialog(QDialog):
    def __init__(self, parent=None, existing_stats=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Tracked Stats")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(QLabel("Add, remove, or toggle tracked statuses (e.g. Health, AC, Nutrition)."))

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        self.main_layout.addWidget(self.scroll_area)

        self.btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Stat")
        self.btn_add.clicked.connect(lambda: self.add_stat_row())
        
        self.btn_save = QPushButton("Save && Close")
        self.btn_save.clicked.connect(self.save_and_close)
        
        self.btn_layout.addWidget(self.btn_add)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_save)
        self.main_layout.addLayout(self.btn_layout)

        self.rows = []

        if existing_stats is not None:
            for stat in existing_stats:
                self.add_stat_row(
                    stat.get("name", ""), 
                    stat.get("value", 100), 
                    stat.get("enabled", True),
                    stat.get("description", stat.get("desc", "")),
                    # Load min and max from existing data, falling back to 0 and 100
                    stat.get("min", 0),
                    stat.get("max", 100)
                )

    def add_stat_row(self, name="", value=100, enabled=True, desc="", min_val=0, max_val=100):
        row = StatRow(name=name, value=value, enabled=enabled, desc=desc, min_val=min_val, max_val=max_val)
        row.desc_input.setText(desc)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_stat_row(row))

    def remove_stat_row(self, row):
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

    def save_and_close(self):
        self.final_stats_data = []
        for row in self.rows:
            data = row.get_data()
            if data["name"]: 
                self.final_stats_data.append(data)
        self.accept()

# ---- Merged from qt_ui/calendar_dialog.py ----
class MonthRow(QWidget):
    """A single row representing one month in the calendar."""
    def __init__(self, parent=None, name="", days=30, season=""):
        super().__init__(parent)
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 5, 0, 5)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Month Name")
        self.name_input.setText(name)
        
        self.days_input = QSpinBox()
        self.days_input.setRange(1, 1000) 
        self.days_input.setValue(days)
        self.days_input.setSuffix(" Days")
        
        self.season_input = QLineEdit()
        self.season_input.setPlaceholderText("Season (e.g. Winter)")
        self.season_input.setText(season)
        
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(30)

        self.row_layout.addWidget(QLabel("Name:"))
        self.row_layout.addWidget(self.name_input, stretch=2)
        self.row_layout.addWidget(QLabel("Length:"))
        self.row_layout.addWidget(self.days_input)
        self.row_layout.addWidget(QLabel("Season:"))
        self.row_layout.addWidget(self.season_input, stretch=2)
        self.row_layout.addWidget(self.btn_remove)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "days": self.days_input.value(),
            "season": self.season_input.text().strip()
        }

class CalendarManagerDialog(QDialog):
    """Dialog to manage custom weekdays and months."""
    def __init__(self, parent=None, existing_calendar=None):
        super().__init__(parent)
        self.setWindowTitle("Manage World Calendar")
        self.setMinimumWidth(550)
        self.setMinimumHeight(400)

        self.main_layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        # --- Tab 1: Weekdays ---
        self.tab_weekdays = QWidget()
        self.week_layout = QVBoxLayout(self.tab_weekdays)
        self.week_layout.addWidget(QLabel("List your days of the week, one per line (Top to Bottom)."))
        
        self.weekdays_text = QTextEdit()
        self.weekdays_text.setPlaceholderText("Monday\nTuesday\nWednesday...")
        self.week_layout.addWidget(self.weekdays_text)
        self.tabs.addTab(self.tab_weekdays, "Days of the Week")

        # --- Tab 2: Months ---
        self.tab_months = QWidget()
        self.months_layout = QVBoxLayout(self.tab_months)
        self.months_layout.addWidget(QLabel("Define the months of your year in order."))
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        self.months_layout.addWidget(self.scroll_area)
        
        self.btn_add_month = QPushButton("+ Add Month")
        self.btn_add_month.clicked.connect(lambda: self.add_month_row())
        self.months_layout.addWidget(self.btn_add_month)
        self.tabs.addTab(self.tab_months, "Months & Seasons")

        # --- Bottom Buttons ---
        self.btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save && Close")
        self.btn_save.clicked.connect(self.save_and_close)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_save)
        self.main_layout.addLayout(self.btn_layout)

        self.rows = []

        # Load existing data
        if existing_calendar:
            weekdays = existing_calendar.get("weekdays", [])
            self.weekdays_text.setPlainText("\n".join(weekdays))
            
            for m in existing_calendar.get("months", []):
                self.add_month_row(m.get("name", ""), m.get("days", 30), m.get("season", ""))
        else:
            # Provide standard defaults if completely blank
            self.weekdays_text.setPlainText("Monday\nTuesday\nWednesday\nThursday\nFriday\nSaturday\nSunday")
            self.add_month_row("Month 1", 30, "Spring")

    def add_month_row(self, name="", days=30, season=""):
        row = MonthRow(name=name, days=days, season=season)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_month_row(row))

    def remove_month_row(self, row):
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

    def save_and_close(self):
        """Packages up the data and closes the dialog."""
        raw_weekdays = self.weekdays_text.toPlainText().strip().split("\n")
        final_weekdays = [day.strip() for day in raw_weekdays if day.strip()]
        
        final_months = []
        for row in self.rows:
            data = row.get_data()
            if data["name"]: 
                final_months.append(data)
                
        if not final_weekdays or not final_months:
            QMessageBox.warning(self, "Validation Error", "You must have at least one weekday and one month.")
            return

        self.final_calendar_data = {
            "weekdays": final_weekdays,
            "months": final_months
        }
        self.accept()

# ---- Merged from qt_ui/help_dialog.py ----
class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Game Help & Manual")
        self.resize(600, 500) # Nice and readable size

        layout = QVBoxLayout(self)

        # Text Browser for formatted, scrollable text
        self.text_browser = QTextBrowser()
        layout.addWidget(self.text_browser)

        # Close Button
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(100)
        self.btn_close.clicked.connect(self.accept)
        layout.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignCenter)

        self._load_help_text()

    def _load_help_text(self):
        """You can customize this HTML string to be whatever you want!"""
        help_content = """
        <h2 style='color: #2e6c80;'>Welcome to AI RPG Adventure!</h2>
        <p>Here is a quick guide to understanding the game interface and mechanics:</p>

        <h3>Interface Tabs</h3>
        <ul>
            <li><b>Story:</b> The main console. Type your actions here to interact with the GM.</li>
            <li><b>Inventory:</b> Displays your items, dynamic wealth, and food reserves.</li>
            <li><b>Skills:</b> Shows your current skills (e.g. what your character is good at). Using them successfully in the story grants XP and levels them up, making them even stronger.</li>
            <li><b>Journal:</b> Keep track of your notes here. The A.I. will never read this tab, so you can write whatever you want in here without worrying about the A.I. "hallucinating" from anything written in here.</li>
            <li><b>Processing / Recipes:</b> Manage crafting, building, and long-term tasks. This is important for the A.I. to "remember" things between continuous hours of play.</li>
            
            <li><b>World & Character:</b> Your reference documents built during play.</li>
        </ul>

        <h3>Gameplay Tips</h3>
        <p>• You can add, edit, or remove custom stats (like Health or Sanity) using the <b>Menu -> Manage Tracked Stats</b> button. Make sure to include a description as specific as possible for each stat, even if it seems obvious to you, it can be worth it to explicitly tell the A.I. EXACTLY what you are envisioning for the Stat to do.</p>
        <p>• You can click "Menu" -> "Manage Currencies" to make your own system of currency for the game! You can add or remove however many units of currency you want, and as long as you correctly set how much each unit of currency is worth, the A.I. should be able to keep track of all of the currencies automatically for you.</p>
        <p>• Simply type what your character does or says naturally! The AI GM will figure out the rest.</p>
        <p>• You can type whatever you want into the "World" tab, but do keep in mind that whatever you put into the World tab, the A.I. will take as complete fact, so that can make the game as easy or as difficult as you want it to be.</p>
        """
        self.text_browser.setHtml(help_content)
        
class CreationTemplateStore:
    """
    Handles loading and saving new-game creation templates.

    A completed wizard is always saved into the active save folder as
    creation_settings.json. Reusable templates can live in the global templates
    folder.
    """

    TEMPLATE_FILE_NAME = "creation_settings.json"
    TEMPLATE_SCHEMA_VERSION = 1

    @classmethod
    def templates_directory(cls) -> Path:
        """Returns the app-level directory where reusable templates are stored."""
        return Path(SAVES_DIR).parent / "templates"

    @classmethod
    def save_creation_settings(cls, save_directory: str | Path, wizard_data: dict[str, Any]) -> Path | None:
        """
        Saves the completed new-game wizard data into the active save folder.

        Args:
            save_directory: The current adventure save directory.
            wizard_data: The fully-collected wizard data.

        Returns:
            The saved JSON path, or None if saving failed.
        """
        if not save_directory:
            logging.warning("Cannot save creation settings because save_directory was not provided.")
            return None

        try:
            save_path = Path(save_directory)
            data_to_save = cls.normalize_wizard_data(wizard_data)
            data_to_save["_metadata"] = {
                "schema_version": cls.TEMPLATE_SCHEMA_VERSION,
                "template_type": "ai_adventure_creation_settings",
            }

            output_path = save_path / cls.TEMPLATE_FILE_NAME
            FileManager.save_json_data(output_path, data_to_save)
            logging.info("Saved creation settings to %s", output_path)
            return output_path

        except Exception as error:
            logging.exception("Failed to save creation settings: %s", error)
            return None

    @classmethod
    def load_template(cls, template_path: str | Path | None) -> dict[str, Any] | None:
        """
        Loads a template JSON file safely.

        Args:
            template_path: Path to a template JSON file.

        Returns:
            Normalized wizard data, or None if loading failed.
        """
        if template_path is None:
            return None

        try:
            path = Path(template_path)
            if not path.exists() or not path.is_file():
                logging.warning("Template path does not exist or is not a file: %s", path)
                return None

            raw_data = FileManager.load_json_data(path)
            if not isinstance(raw_data, dict):
                logging.warning("Template file did not contain a JSON object: %s", path)
                return None

            return cls.normalize_wizard_data(raw_data)

        except Exception as error:
            logging.exception("Failed to load template %s: %s", template_path, error)
            return None

    @classmethod
    def list_available_templates(cls) -> list[tuple[str, Path]]:
        """
        Finds reusable templates and previous save-folder creation settings.

        Returns:
            A list of display-name/path pairs.
        """
        templates: list[tuple[str, Path]] = []

        try:
            global_template_dir = cls.templates_directory()
            global_template_dir.mkdir(parents=True, exist_ok=True)

            for template_path in sorted(global_template_dir.glob("*.json"), key=lambda p: p.stem.lower()):
                templates.append((f"Template: {template_path.stem}", template_path))

        except Exception as error:
            logging.exception("Failed to list global templates: %s", error)

        try:
            saves_dir = Path(SAVES_DIR)
            if saves_dir.exists() and saves_dir.is_dir():
                for save_dir in sorted(saves_dir.iterdir(), key=lambda p: p.name.lower()):
                    if not save_dir.is_dir():
                        continue

                    creation_file = save_dir / cls.TEMPLATE_FILE_NAME
                    if creation_file.exists() and creation_file.is_file():
                        templates.append((f"Previous Game: {save_dir.name}", creation_file))

        except Exception as error:
            logging.exception("Failed to list previous-game templates: %s", error)

        return templates

    @classmethod
    def normalize_wizard_data(cls, data: dict[str, Any] | None) -> dict[str, Any]:
        """
        Ensures wizard data always has every expected key.

        This lets templates be partial without crashing the wizard, while still
        saving default values for blank or missing fields.
        """
        source = data if isinstance(data, dict) else {}

        world = source.get("world") if isinstance(source.get("world"), dict) else {}
        character = source.get("character") if isinstance(source.get("character"), dict) else {}

        focus = source.get("focus")
        currencies = source.get("currencies")
        stats = source.get("stats")
        skills = source.get("skills")
        
        calendar = source.get("calendar") if isinstance(source.get("calendar"), dict) else {}

        legacy_calendar_settings = source.get("calendar_settings")
        if not calendar and isinstance(legacy_calendar_settings, dict):
            calendar = {
                "mode": "custom",
                "settings": legacy_calendar_settings,
                "ai_notes": "",
            }
        
        if world is not None and character is not None and source is not None:
            return {
                "world": {
                    "setting": str(world.get("setting", "") or ""),
                    "genre": str(world.get("genre", "") or ""),
                    "tech": str(world.get("tech", "") or ""),
                    "species": str(world.get("species", "") or ""),
                },
                "focus": focus if isinstance(focus, list) else [],
                "currencies": currencies if isinstance(currencies, list) else [],
                "stats": stats if isinstance(stats, list) else [],
                "calendar": cls.normalize_calendar_data(calendar),
                "character": {
                    "name": str(character.get("name", "") or ""),
                    "age": str(character.get("age", "") or ""),
                    "gender": str(character.get("gender", "") or ""),
                    "pronouns": str(character.get("pronouns", "") or ""),
                    "orientation": str(character.get("orientation", "") or ""),
                    "background": str(character.get("background", "") or ""),
                },
                "skills": skills if isinstance(skills, list) else [],
                "starting_location": str(source.get("starting_location", "") or ""),
                "final_comments": str(source.get("final_comments", "") or ""),
            }
        else:
            if world is None:
                logging.exception("COULD NOT FIND WORLD FOR CUSTOM TEMPLATE!")
            if character is None:
                logging.exception("COULD NOT FIND CHARACTER FOR CUSTOM TEMPLATE!")
            if source is None:
                logging.exception("COULD NOT FIND SOURCE FOR CUSTOM TEMPLATE!")
            return {}
        
    @classmethod
    def normalize_calendar_data(cls, calendar_data: dict[str, Any] | None) -> dict[str, Any]:
        """Normalizes calendar template data."""

        if not isinstance(calendar_data, dict):
            return {
                "mode": "gregorian",
                "settings": get_default_gregorian_calendar(),
                "ai_notes": "",
            }

        mode = str(calendar_data.get("mode", "gregorian") or "gregorian").strip()

        if mode not in {"gregorian", "custom", "ai_generate"}:
            logging.warning("Unknown calendar mode %r. Falling back to gregorian.", mode)
            mode = "gregorian"

        raw_settings = calendar_data.get("settings", {})
        has_settings = isinstance(raw_settings, dict) and bool(raw_settings)

        if mode == "ai_generate" and not has_settings:
            settings = {}
        elif mode == "gregorian":
            settings = get_default_gregorian_calendar()
        else:
            settings = normalize_calendar_settings(raw_settings if isinstance(raw_settings, dict) else None)

        return {
            "mode": mode,
            "settings": settings,
            "ai_notes": str(calendar_data.get("ai_notes", "") or ""),
        }

# ---- Merged from qt_ui/main_menu_dialog.py ----
class MainMenuDialog(QDialog):
    """Simple startup menu for the Qt build."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI RPG Adventure - Main Menu")
        self.resize(520, 420)
        self._selected_save: str | None = None

        root = QVBoxLayout(self)

        title = QLabel("Adventures")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        root.addWidget(title)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _it: self._load_selected())
        root.addWidget(self.list, stretch=1)

        btn_row = QHBoxLayout()

        self.btn_load = QPushButton("Load")
        self.btn_new = QPushButton("New")
        self.btn_rename = QPushButton("Rename")
        self.btn_delete = QPushButton("Delete")
        self.btn_quit = QPushButton("Quit")

        self.btn_load.clicked.connect(self._load_selected)
        self.btn_new.clicked.connect(self._new_adventure)
        self.btn_rename.clicked.connect(self._rename_selected)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_quit.clicked.connect(self.reject)

        for b in (self.btn_load, self.btn_new, self.btn_rename, self.btn_delete, self.btn_quit):
            btn_row.addWidget(b)

        root.addLayout(btn_row)

        self.refresh_list()

    @property
    def selected_save(self) -> str | None:
        return self._selected_save

    def refresh_list(self) -> None:
        """Refreshes the visible list of completed adventures only."""
        try:
            saves_directory = Path(SAVES_DIR)
            saves_directory.mkdir(parents=True, exist_ok=True)
        except Exception:
            logging.exception("Failed to ensure saves dir exists")
            return

        self.list.clear()

        try:
            saves = [
                save_dir.name
                for save_dir in saves_directory.iterdir()
                if save_dir.is_dir() and (save_dir / "savegame.json").exists()
            ]
            saves.sort(key=lambda save_name: save_name.lower())
        except Exception:
            logging.exception("Failed to list saves")
            saves = []

        if not saves:
            self.list.addItem("(No saved adventures yet)")
            self.list.setEnabled(False)
        else:
            self.list.setEnabled(True)
            for save_name in saves:
                self.list.addItem(save_name)

    def _current_selection(self) -> str | None:
        if not self.list.isEnabled():
            return None
        item = self.list.currentItem()
        return item.text() if item else None

    def _sanitize_name(self, raw: str) -> str:
        raw = (raw or "").strip()
        return "".join(c for c in raw if c.isalnum() or c in (" ", "_", "-")).strip()

    def _load_selected(self) -> None:
        name = self._current_selection()
        if not name:
            QMessageBox.information(self, "Load", "Select an adventure first.")
            return
        self._selected_save = name
        self.accept()

    def _new_adventure(self) -> None:
        """
        Selects a new adventure name without creating the save folder.

        Completed saves are blocked. Incomplete orphan folders may be removed
        so a cancelled/failed new-game attempt does not permanently reserve a name.
        """
        text, ok = QInputDialog.getText(self, "New Adventure", "Name your adventure:")
        if not ok:
            return

        name = self._sanitize_name(text)
        if not name:
            return

        final_save_path = Path(SAVES_DIR) / name
        savegame_path = final_save_path / "savegame.json"

        if savegame_path.exists():
            QMessageBox.warning(self, "New Adventure", "That adventure already exists.")
            return

        if final_save_path.exists():
            response = QMessageBox.question(
                self,
                "Incomplete Adventure Found",
                (
                    f"An incomplete adventure folder named '{name}' already exists.\n\n"
                    "This usually means new-game creation was cancelled or failed before "
                    "savegame.json was finalized.\n\n"
                    "Remove the incomplete folder and reuse this name?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )

            if response != QMessageBox.StandardButton.Yes:
                return

            try:
                if final_save_path.is_dir():
                    shutil.rmtree(final_save_path)
                else:
                    final_save_path.unlink()

                logging.info("Removed incomplete adventure folder: %s", final_save_path)

            except Exception as error:
                logging.exception("Failed to remove incomplete adventure folder: %s", error)
                QMessageBox.critical(
                    self,
                    "New Adventure",
                    "Could not remove the incomplete adventure folder. Check the log file.",
                )
                return

        self._selected_save = name
        self.accept()

    def _rename_selected(self) -> None:
        old = self._current_selection()
        if not old:
            QMessageBox.information(self, "Rename", "Select an adventure first.")
            return

        text, ok = QInputDialog.getText(self, "Rename Adventure", f"Rename '{old}' to:")
        if not ok:
            return

        new = self._sanitize_name(text)
        if not new or new == old:
            return

        old_path = os.path.join(SAVES_DIR, old)
        new_path = os.path.join(SAVES_DIR, new)
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Rename", "That name is already taken.")
            return

        try:
            os.rename(old_path, new_path)
            self.refresh_list()
        except Exception:
            logging.exception("Failed to rename adventure")
            QMessageBox.critical(self, "Rename", "Rename failed (see logs).")

    def _delete_selected(self) -> None:
        name = self._current_selection()
        if not name:
            QMessageBox.information(self, "Delete", "Select an adventure first.")
            return

        text, ok = QInputDialog.getText(
            self,
            "Delete Adventure",
            f"Type DELETE to confirm deleting '{name}':",
        )
        if not ok:
            return

        if (text or "").strip() != "DELETE":
            return

        full = os.path.join(SAVES_DIR, name)
        try:
            shutil.rmtree(full)
            self.refresh_list()
        except Exception:
            logging.exception("Failed to delete adventure")
            QMessageBox.critical(self, "Delete", "Delete failed (see logs).")

class NewGameSourceDialog(QDialog):
    """
    Lets the player choose whether a new adventure starts from scratch or from
    an existing creation template.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Adventure Source")
        self.setMinimumWidth(500)

        self._templates = CreationTemplateStore.list_available_templates()
        self._selected_template_path: Path | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("How would you like to create this adventure?"))

        self.scratch_radio = QRadioButton("Create a brand-new adventure from scratch")
        self.template_radio = QRadioButton("Start from an existing template or previous adventure setup")
        self.scratch_radio.setChecked(True)

        layout.addWidget(self.scratch_radio)
        layout.addWidget(self.template_radio)

        self.template_list = QListWidget()
        self.template_list.setEnabled(False)
        layout.addWidget(self.template_list)

        if self._templates:
            for display_name, _path in self._templates:
                self.template_list.addItem(display_name)
            self.template_list.setCurrentRow(0)
        else:
            self.template_list.addItem("(No templates or previous setup files found yet)")
            self.template_radio.setEnabled(False)

        self.template_radio.toggled.connect(self.template_list.setEnabled)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_template_path(self) -> Path | None:
        """Returns the selected template path, or None for scratch mode."""
        return self._selected_template_path

    def _accept_selection(self) -> None:
        """Validates and stores the selected source."""
        try:
            if not self.template_radio.isChecked():
                self._selected_template_path = None
                self.accept()
                return

            current_row = self.template_list.currentRow()
            if current_row < 0 or current_row >= len(self._templates):
                QMessageBox.warning(self, "Template", "Select a template first.")
                return

            self._selected_template_path = self._templates[current_row][1]
            self.accept()

        except Exception as error:
            logging.exception("Failed to accept new-game source selection: %s", error)
            QMessageBox.critical(self, "Template", "Failed to select the template. Check the log file.")

# ---- Merged from qt_ui/audio_dialog.py ----
class AudioSettingsDialog(QDialog):
    def __init__(self, parent, story_panel):
        super().__init__(parent)
        self.setWindowTitle("Audio Settings")
        self.setMinimumWidth(350)
        self.story_panel = story_panel

        # Cache original settings in case the user hits "Cancel"
        self.orig_music_vol = story_panel.music_volume
        self.orig_tts_vol = story_panel.tts_volume
        self.orig_tts_rate = story_panel.tts_rate
        self.orig_narrator_enabled = story_panel.narrator_enabled
        self.orig_voice = story_panel.tts_voice

        layout = QVBoxLayout(self)

        # --- 1. Music Section ---
        music_group = QGroupBox("🎵 Music")
        music_layout = QVBoxLayout()
        
        music_row = QHBoxLayout()
        self.lbl_music_val = QLabel(f"{self.orig_music_vol}%")
        self.lbl_music_val.setFixedWidth(35)
        
        self.slider_music = QSlider(Qt.Orientation.Horizontal)
        self.slider_music.setRange(0, 100)
        self.slider_music.setValue(self.orig_music_vol)
        self.slider_music.valueChanged.connect(self._on_music_slider)
        
        music_row.addWidget(QLabel("Volume:"))
        music_row.addWidget(self.slider_music)
        music_row.addWidget(self.lbl_music_val)
        music_layout.addLayout(music_row)
        music_group.setLayout(music_layout)
        layout.addWidget(music_group)

        # --- 2. Narrator Section ---
        self.narrator_group = QGroupBox("🗣️ Narrator")
        narrator_layout = QVBoxLayout()

        self.chk_enable = QCheckBox("Enable Narrator")
        self.chk_enable.setChecked(self.orig_narrator_enabled)
        self.chk_enable.toggled.connect(self._toggle_narrator_ui)
        narrator_layout.addWidget(self.chk_enable)

        tts_row = QHBoxLayout()
        self.lbl_tts_val = QLabel(f"{self.orig_tts_vol}%")
        self.lbl_tts_val.setFixedWidth(35)
        
        self.slider_tts = QSlider(Qt.Orientation.Horizontal)
        self.slider_tts.setRange(0, 100)
        self.slider_tts.setValue(self.orig_tts_vol)
        self.slider_tts.valueChanged.connect(self._on_tts_slider)
        
        self.lbl_tts_label = QLabel("Volume:")
        tts_row.addWidget(self.lbl_tts_label)
        tts_row.addWidget(self.slider_tts)
        tts_row.addWidget(self.lbl_tts_val)
        narrator_layout.addLayout(tts_row)
        speed_row = QHBoxLayout()
        
        init_speed_str = "Normal" if self.orig_tts_rate == 0 else f"{'+' if self.orig_tts_rate > 0 else ''}{self.orig_tts_rate}"
        self.lbl_tts_speed_val = QLabel(init_speed_str)
        self.lbl_tts_speed_val.setFixedWidth(45)
        
        self.slider_tts_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_tts_speed.setRange(-10, 10)
        self.slider_tts_speed.setValue(self.orig_tts_rate)
        self.slider_tts_speed.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_tts_speed.setTickInterval(5)
        self.slider_tts_speed.valueChanged.connect(self._on_tts_speed_slider)
        
        self.lbl_tts_speed_label = QLabel("Speed:")
        speed_row.addWidget(self.lbl_tts_speed_label)
        speed_row.addWidget(self.slider_tts_speed)
        speed_row.addWidget(self.lbl_tts_speed_val)
        narrator_layout.addLayout(speed_row)

        voice_row = QHBoxLayout()
        self.combo_voices = QComboBox()
        for display_name, voice_id in self.story_panel.AVAILABLE_VOICES.items():
            # Add the item: Display Name is shown to user, Voice ID is stored in background data
            self.combo_voices.addItem(display_name, voice_id) 
            if voice_id == self.orig_voice:
                self.combo_voices.setCurrentText(display_name)
                
        self.lbl_voice_label = QLabel("Voice:")
        voice_row.addWidget(self.lbl_voice_label)
        voice_row.addWidget(self.combo_voices, stretch=1)
        narrator_layout.addLayout(voice_row)

        self.btn_test = QPushButton("Play Voice Sample")
        self.btn_test.clicked.connect(self._play_sample)
        narrator_layout.addWidget(self.btn_test)

        self.narrator_group.setLayout(narrator_layout)
        layout.addWidget(self.narrator_group)

        # --- 3. Buttons ---
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Initialize grey-out state based on checkbox
        self._toggle_narrator_ui(self.orig_narrator_enabled)

    def _on_music_slider(self, val):
        self.lbl_music_val.setText(f"{val}%")
        self.story_panel.set_music_volume(val) # Live preview!

    def _on_tts_slider(self, val):
        self.lbl_tts_val.setText(f"{val}%")
        self.story_panel.set_tts_volume(val) # Live preview!

    def _toggle_narrator_ui(self, checked):
        # Greys out all sub-options if disabled
        self.lbl_tts_label.setEnabled(checked)
        self.slider_tts.setEnabled(checked)
        self.lbl_tts_speed_label.setEnabled(checked)
        self.slider_tts_speed.setEnabled(checked)
        self.lbl_tts_speed_val.setEnabled(checked)
        self.lbl_tts_val.setEnabled(checked)
        self.lbl_voice_label.setEnabled(checked)
        self.combo_voices.setEnabled(checked)
        self.btn_test.setEnabled(checked)

    def _play_sample(self):
        # Temporarily lock the voice in and test it
        voice_id = self.combo_voices.currentData()
        self.story_panel.set_voice_by_name(voice_id)
        
        orig = self.story_panel.narrator_enabled
        self.story_panel.narrator_enabled = True
        self.story_panel.play_voice_sample()
        self.story_panel.narrator_enabled = orig

    def reject(self):
        # Revert live-previews if Cancel is clicked
        self.story_panel.set_music_volume(self.orig_music_vol)
        self.story_panel.set_tts_volume(self.orig_tts_vol)
        self.story_panel.set_voice_by_name(self.orig_voice)
        self.story_panel.set_tts_rate(self.orig_tts_rate) 
        super().reject()

    def accept(self):
        # Finalize
        self.story_panel.set_narrator_enabled(self.chk_enable.isChecked())
        self.story_panel.set_voice_by_name(self.combo_voices.currentData())
        super().accept()
        
    def _on_tts_speed_slider(self, val):
        if val == 0: display_str = "Normal"
        elif val > 0: display_str = f"+{val}"
        else: display_str = f"{val}"
        
        self.lbl_tts_speed_val.setText(display_str)
        self.story_panel.set_tts_rate(val) # Live preview!

# ---- Merged from qt_ui/creation_wizard.py ----
class WorldPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 1: World Setting")
        self.setSubTitle("Define the parameters of the world you will be exploring. Leave blank for the A.I. to decide.")
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("World Setting (e.g., A dark fantasy continent shattered by a magical cataclysm):"))
        self.setting_input = QTextEdit()
        self.setting_input.setTabChangesFocus(True) # Fixes the Tab key issue
        layout.addWidget(self.setting_input)
        
        layout.addWidget(QLabel("Genre/Tone (e.g., Grimdark Fantasy, Sci-Fi Cyberpunk, Cozy Slice-of-Life):"))
        self.genre_input = QLineEdit()
        layout.addWidget(self.genre_input)
        
        layout.addWidget(QLabel("Tech Level (e.g., Iron Age, Steampunk, Futuristic Sci-Fi):"))
        self.tech_input = QLineEdit()
        layout.addWidget(self.tech_input)
        
        layout.addWidget(QLabel("Species/Races (e.g., Humans, Elves, Dwarves, and half-dragon hybrids):"))
        self.species_input = QTextEdit()
        self.species_input.setTabChangesFocus(True)
        layout.addWidget(self.species_input)

class PillarsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 2: Game Focus")
        self.setSubTitle("Select the main pillars you want this adventure to focus on.")
        
        layout = QVBoxLayout(self)
        
        self.combat_cb = QCheckBox("Combat")
        self.exploration_cb = QCheckBox("Exploration")
        self.trading_cb = QCheckBox("Trading / Economy")
        self.social_cb = QCheckBox("Social / Roleplay")
        
        layout.addWidget(self.combat_cb)
        layout.addWidget(self.exploration_cb)
        layout.addWidget(self.trading_cb)
        layout.addWidget(self.social_cb)

class CharacterPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 6: Character Bio")
        self.setSubTitle("Tell me about your character. Leave blank for the AI to decide.")
        
        layout = QVBoxLayout(self)
        
        # Using a horizontal layout just for the short fields to save vertical space
        short_fields_layout = QFormLayout()
        
        self.name_input = QLineEdit()
        self.age_input = QLineEdit()
        self.gender_input = QLineEdit()
        self.pronouns_input = QLineEdit()
        self.orientation_input = QLineEdit()
        
        short_fields_layout.addRow("Name:", self.name_input)
        short_fields_layout.addRow("Age:", self.age_input)
        short_fields_layout.addRow("Gender:", self.gender_input)
        short_fields_layout.addRow("Pronouns:", self.pronouns_input)
        short_fields_layout.addRow("Orientation:", self.orientation_input)
        
        layout.addLayout(short_fields_layout)
        
        layout.addWidget(QLabel("\nBackground (Brief history, backstory, or important NPCs):"))
        self.background_input = QTextEdit()
        self.background_input.setTabChangesFocus(True)
        layout.addWidget(self.background_input)

class SkillsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 7: Skills")
        self.setSubTitle("Define your starting skills. Leave descriptions blank to let the AI decide.")
        
        # We need a scroll area because there are 16 skills
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        content = QWidget()
        self.scroll_layout = QVBoxLayout(content)
        
        self.skill_inputs = [] # Will store tuples of (level, name_widget, desc_widget)

        # Helper to generate the skill boxes
        def add_skill_section(level, count, title):
            group = QGroupBox(f"Level {level} - {title} ({count} Skills)")
            g_layout = QFormLayout(group)
            for i in range(count):
                row_layout = QHBoxLayout()
                name_input = QLineEdit()
                name_input.setPlaceholderText(f"Skill Name")
                desc_input = QLineEdit()
                desc_input.setPlaceholderText(f"Optional Description")
                
                row_layout.addWidget(name_input, stretch=1)
                row_layout.addWidget(desc_input, stretch=2)
                g_layout.addRow(f"Skill {i+1}:", row_layout)
                
                self.skill_inputs.append((level, name_input, desc_input))
            self.scroll_layout.addWidget(group)

        add_skill_section(5, 1, "Master")
        add_skill_section(4, 2, "Excellent")
        add_skill_section(3, 3, "Very Good")
        add_skill_section(2, 4, "Good")
        add_skill_section(1, 6, "Decent")
        
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

class FinalPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 8: Final Details")
        self.setSubTitle("Where do you begin, and do you have any final rules?")
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Starting Location (e.g., A dingy tavern in the lower rings of the city):"))
        self.location_input = QLineEdit()
        layout.addWidget(self.location_input)
        
        layout.addWidget(QLabel("\nFinal Comments/Rules (e.g., Magic is strictly illegal. I have a pet dog named Barnaby):"))
        self.comments_input = QTextEdit()
        self.comments_input.setTabChangesFocus(True)
        layout.addWidget(self.comments_input)
        
class CurrencyPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 3: World Currencies")
        self.setSubTitle("Define your currencies relative to your cheapest coin. Leave blank for AI generation.")
        
        layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.rows_layout = QVBoxLayout(content)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        
        self.rows = []
        
        btn_add = QPushButton("+ Add Currency")
        btn_add.clicked.connect(lambda: self.add_row())
        layout.addWidget(btn_add)
        layout.addWidget(scroll)
        
        # Default starting row (Blank, allowing the AI to take over if left alone)
        self.add_row("", 1, is_baseline=True)

    def add_row(self, name="", value=1, is_baseline=False):
        if len(self.rows) >= 9:
            QMessageBox.warning(self, "Limit Reached", "You can only have up to 9 currencies.")
            return

        row = CurrencyRow(name=name, value=value, is_baseline=is_baseline)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_row(row))

    def remove_row(self, row: CurrencyRow | None) -> None:
        """
        Removes a user-removable currency row from the wizard page.

        Baseline rows are intentionally protected because the app requires one
        smallest currency unit worth exactly 1 base unit.
        """
        if row is None:
            logging.warning("CurrencyPage.remove_row called with None.")
            return

        if row.is_baseline:
            return

        self._detach_row(row)


    def clear_rows(self) -> None:
        """
        Removes every currency row from the page.

        This is used when loading a template. It must fully detach old widgets,
        not merely remove them from the layout, otherwise Qt may keep orphaned rows
        visible until a later event-loop cleanup.
        """
        for row in list(self.rows):
            self._detach_row(row)

        self.rows.clear()


    def _detach_row(self, row: CurrencyRow | None) -> None:
        """
        Safely removes a currency row widget from the layout and widget hierarchy.
        """
        if row is None:
            logging.warning("CurrencyPage._detach_row called with None.")
            return

        try:
            self.rows_layout.removeWidget(row)

            if row in self.rows:
                self.rows.remove(row)

            # removeWidget() only removes layout management. It does not hide or
            # destroy the widget, so do both explicitly.
            row.hide()
            row.setParent(None)
            row.deleteLater()

        except Exception as error:
            logging.exception("Failed to detach currency row: %s", error)


class StatsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 4: Tracked Stats")
        self.setSubTitle("Add, remove, or toggle tracked statuses (e.g. Health, AC). Leave blank for AI generation.")
        
        layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.rows_layout = QVBoxLayout(content)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        
        self.rows = []
        
        btn_add = QPushButton("+ Add Stat")
        btn_add.clicked.connect(lambda: self.add_row())
        layout.addWidget(btn_add)
        layout.addWidget(scroll)
        
        # Default starting rows

    def add_row(
    self,
    name: str = "",
    value: int = 100,
    enabled: bool = True,
    desc: str = "",
    min_val: int = 0,
    max_val: int = 100,
) -> None:
        """Adds a stat row to the tracked-stats wizard page."""
        row = StatRow(
            name=name,
            value=value,
            enabled=enabled,
            desc=desc,
            min_val=min_val,
            max_val=max_val,
        )
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_row(row))

    def remove_row(self, row):
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()
        
class CalendarPage(QWizardPage):
    """Wizard page for choosing or defining the starting world calendar."""

    MODE_GREGORIAN = "gregorian"
    MODE_CUSTOM = "custom"
    MODE_AI_GENERATE = "ai_generate"

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Step 5: Calendar")
        self.setSubTitle(
            "Choose the world's calendar. You can keep Gregorian, customize it, "
            "or let the AI generate one from the world setup."
        )

        self.rows: list[MonthRow] = []

        layout = QVBoxLayout(self)

        self.gregorian_radio = QRadioButton("Use the default Gregorian calendar")
        self.custom_radio = QRadioButton("Customize the calendar")
        self.ai_radio = QRadioButton("Let the AI generate the calendar")

        self.gregorian_radio.setChecked(True)

        layout.addWidget(self.gregorian_radio)
        layout.addWidget(self.custom_radio)
        layout.addWidget(self.ai_radio)

        self.custom_group = QGroupBox("Custom Calendar Details")
        custom_layout = QVBoxLayout(self.custom_group)

        custom_layout.addWidget(
            QLabel(
                "Weekdays, one per line. Leave this blank to use the Gregorian weekdays."
            )
        )

        self.weekdays_text = QTextEdit()
        self.weekdays_text.setTabChangesFocus(True)
        self.weekdays_text.setPlaceholderText(
            "Monday\nTuesday\nWednesday\nThursday\nFriday\nSaturday\nSunday"
        )
        custom_layout.addWidget(self.weekdays_text)

        custom_layout.addWidget(
            QLabel(
                "Months are read in order. Blank names or seasons fall back to Gregorian defaults."
            )
        )

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.scroll_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.scroll_widget)
        custom_layout.addWidget(self.scroll_area)

        button_row = QHBoxLayout()

        self.btn_add_month = QPushButton("+ Add Month")
        self.btn_add_month.clicked.connect(lambda: self.add_month_row())

        self.btn_restore_gregorian = QPushButton("Restore Gregorian Months")
        self.btn_restore_gregorian.clicked.connect(self.restore_gregorian_rows)

        button_row.addWidget(self.btn_add_month)
        button_row.addWidget(self.btn_restore_gregorian)
        custom_layout.addLayout(button_row)

        layout.addWidget(self.custom_group, stretch=1)

        layout.addWidget(QLabel("AI Calendar Notes (optional):"))
        self.ai_notes_input = QTextEdit()
        self.ai_notes_input.setTabChangesFocus(True)
        self.ai_notes_input.setPlaceholderText(
            "Example: Use a lunar calendar with short months, religious feast days, "
            "and harsh winter seasons."
        )
        layout.addWidget(self.ai_notes_input)

        self.restore_gregorian_rows()

        self.gregorian_radio.toggled.connect(self._update_enabled_state)
        self.custom_radio.toggled.connect(self._update_enabled_state)
        self.ai_radio.toggled.connect(self._update_enabled_state)
        self._update_enabled_state()

    def _update_enabled_state(self) -> None:
        """Enables only the controls relevant to the selected calendar mode."""

        self.custom_group.setEnabled(self.custom_radio.isChecked())
        self.ai_notes_input.setEnabled(self.ai_radio.isChecked())

    def restore_gregorian_rows(self) -> None:
        """Resets the custom calendar editor to Gregorian defaults."""

        default_calendar = get_default_gregorian_calendar()
        self.weekdays_text.setPlainText("\n".join(default_calendar["weekdays"]))
        self.clear_month_rows()

        for month in default_calendar["months"]:
            self.add_month_row(
                name=str(month.get("name", "")),
                days=int(month.get("days", 30)),
                season=str(month.get("season", "")),
            )

    def add_month_row(self, name: str = "", days: int = 30, season: str = "") -> None:
        """Adds one editable month row."""

        row = MonthRow(name=name, days=days, season=season)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_month_row(row))

    def remove_month_row(self, row: MonthRow | None) -> None:
        """Removes a month row safely."""

        if row is None:
            logging.warning("CalendarPage.remove_month_row called with None.")
            return

        try:
            self.rows_layout.removeWidget(row)

            if row in self.rows:
                self.rows.remove(row)

            row.hide()
            row.setParent(None)
            row.deleteLater()

        except Exception as error:
            logging.exception("Failed to remove calendar month row: %s", error)

    def clear_month_rows(self) -> None:
        """Removes all month rows from the custom calendar editor."""

        for row in list(self.rows):
            self.remove_month_row(row)

        self.rows.clear()

    def _collect_custom_settings(self) -> dict[str, Any]:
        """Collects custom calendar data, using defaults for blank pieces."""

        raw_weekdays = self.weekdays_text.toPlainText().strip().splitlines()
        weekdays = [day.strip() for day in raw_weekdays if day.strip()]

        months = []
        for row in self.rows:
            data = row.get_data()
            months.append(data)

        return normalize_calendar_settings(
            {
                "weekdays": weekdays,
                "months": months,
            }
        )

    def get_data(self) -> dict[str, Any]:
        """Returns calendar wizard data for template saving and game startup."""

        if self.ai_radio.isChecked():
            return {
                "mode": self.MODE_AI_GENERATE,
                "settings": {},
                "ai_notes": self.ai_notes_input.toPlainText().strip(),
            }

        if self.custom_radio.isChecked():
            return {
                "mode": self.MODE_CUSTOM,
                "settings": self._collect_custom_settings(),
                "ai_notes": self.ai_notes_input.toPlainText().strip(),
            }

        return {
            "mode": self.MODE_GREGORIAN,
            "settings": get_default_gregorian_calendar(),
            "ai_notes": "",
        }

    def apply_data(self, calendar_data: dict[str, Any] | None) -> None:
        """Pre-fills the page from a saved creation template."""

        if not isinstance(calendar_data, dict):
            self.gregorian_radio.setChecked(True)
            self.restore_gregorian_rows()
            self._update_enabled_state()
            return

        mode = str(calendar_data.get("mode", self.MODE_GREGORIAN) or self.MODE_GREGORIAN)
        raw_settings = calendar_data.get("settings", {})
        settings = normalize_calendar_settings(raw_settings if isinstance(raw_settings, dict) else None)

        if mode == self.MODE_AI_GENERATE:
            self.ai_radio.setChecked(True)
        elif mode == self.MODE_CUSTOM:
            self.custom_radio.setChecked(True)
        else:
            self.gregorian_radio.setChecked(True)

        self.weekdays_text.setPlainText("\n".join(settings["weekdays"]))
        self.clear_month_rows()

        for month in settings["months"]:
            self.add_month_row(
                name=str(month.get("name", "")),
                days=int(month.get("days", 30)),
                season=str(month.get("season", "")),
            )

        self.ai_notes_input.setPlainText(str(calendar_data.get("ai_notes", "") or ""))
        self._update_enabled_state()

class CreationWizard(QWizard):
    def __init__(self, parent=None, template_data: dict[str, Any] | None = None):
        super().__init__(parent)
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setWindowTitle("New Adventure Setup")
        self.resize(700, 600)
        
        
        # --- ROBUST DARK THEME STYLESHEET ---
        self.setStyleSheet("""
            QWizard, QWizardPage {
                background-color: #202124;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-weight: bold;
                margin-top: 5px;
            }
            QLineEdit, QTextEdit {
                background-color: #171717;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px;
            }
            /* Explicitly style the placeholder tooltips so they are visible */
            QLineEdit::placeholder, QTextEdit::placeholder {
                color: #8a8a8a;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #3a8ccf;
                background-color: #252525;
            }
        """)
        
        self.world_page = WorldPage()
        self.pillars_page = PillarsPage()
        self.currency_page = CurrencyPage()
        self.stats_page = StatsPage()
        self.calendar_page = CalendarPage()
        self.char_page = CharacterPage()
        self.skills_page = SkillsPage()
        self.final_page = FinalPage()
        
        self.addPage(self.world_page)
        self.addPage(self.pillars_page)
        self.addPage(self.currency_page)
        self.addPage(self.stats_page)
        self.addPage(self.calendar_page)
        self.addPage(self.char_page)
        self.addPage(self.skills_page)
        self.addPage(self.final_page)
        
        if template_data is not None:
            self.apply_template_data(template_data)

    def apply_template_data(self, template_data: dict[str, Any] | None) -> None:
        """
        Pre-fills the wizard from saved creation template data.

        Args:
            template_data: Wizard data loaded from creation_settings.json or a
                           reusable template JSON file.
        """
        if template_data is None:
            return

        try:
            data = CreationTemplateStore.normalize_wizard_data(template_data)

            self._apply_world_data(data.get("world", {}))
            self._apply_focus_data(data.get("focus", []))
            self._apply_currency_data(data.get("currencies", []))
            self._apply_stats_data(data.get("stats", []))
            self._apply_character_data(data.get("character", {}))
            self._apply_skills_data(data.get("skills", []))
            self._apply_calendar_data(data.get("calendar", {}))
            self._apply_final_data(data)

        except Exception as error:
            logging.exception("Failed to apply creation template data: %s", error)
            
    def _apply_calendar_data(self, calendar_data: dict[str, Any]) -> None:
        """Applies calendar-related template data."""

        if self.calendar_page is None:
            logging.warning("CreationWizard._apply_calendar_data called before calendar_page exists.")
            return

        self.calendar_page.apply_data(calendar_data)

    def _apply_world_data(self, world: dict[str, Any]) -> None:
        """Applies world-related template data."""
        if not isinstance(world, dict):
            return

        self.world_page.setting_input.setPlainText(str(world.get("setting", "") or ""))
        self.world_page.genre_input.setText(str(world.get("genre", "") or ""))
        self.world_page.tech_input.setText(str(world.get("tech", "") or ""))
        self.world_page.species_input.setPlainText(str(world.get("species", "") or ""))

    def _apply_focus_data(self, focus: list[Any]) -> None:
        """Applies selected gameplay-pillar template data."""
        normalized_focus = {
            str(item).strip().lower().replace(" ", "")
            for item in focus
            if item is not None
        }

        self.pillars_page.combat_cb.setChecked("combat" in normalized_focus)
        self.pillars_page.exploration_cb.setChecked("exploration" in normalized_focus)
        self.pillars_page.trading_cb.setChecked("trading/economy" in normalized_focus)
        self.pillars_page.social_cb.setChecked("social/roleplay" in normalized_focus)

    def _clear_currency_rows(self) -> None:
        """Removes all currency rows from the currency wizard page."""
        if self.currency_page is None:
            logging.warning("CreationWizard._clear_currency_rows called before currency_page exists.")
            return

        self.currency_page.clear_rows()

    def _apply_currency_data(self, currencies: list[Any]) -> None:
        """
        Applies currency template data to the wizard.

        Blank currency names are ignored. A baseline value-1 currency is required,
        so one is added only when the template provides valid currencies but none
        of them are worth 1 base unit.
        """
        self._clear_currency_rows()

        normalized_currencies: list[dict[str, int | str]] = []

        for currency in currencies:
            if not isinstance(currency, dict):
                logging.warning("Skipped malformed currency template row: %r", currency)
                continue

            name = str(currency.get("name", "") or "").strip()
            if not name:
                logging.warning("Skipped blank currency template row: %r", currency)
                continue

            try:
                value = max(1, int(currency.get("value", 1)))
            except (TypeError, ValueError):
                logging.exception("Invalid currency value in template: %r", currency)
                value = 1

            normalized_currencies.append(
                {
                    "name": name,
                    "value": value,
                }
            )

        if not normalized_currencies:
            self.currency_page.add_row("", 1, is_baseline=True)
            return

        normalized_currencies.sort(key=lambda item: int(item["value"]))

        has_baseline = any(int(currency["value"]) == 1 for currency in normalized_currencies)
        if not has_baseline:
            normalized_currencies.insert(
                0,
                {
                    "name": "Base Unit",
                    "value": 1,
                },
            )

        baseline_assigned = False

        for currency in normalized_currencies:
            value = int(currency["value"])
            is_baseline = value == 1 and not baseline_assigned

            if is_baseline:
                baseline_assigned = True

            self.currency_page.add_row(
                name=str(currency["name"]),
                value=value,
                is_baseline=is_baseline,
            )

    def _clear_stat_rows(self) -> None:
        """Removes all stat rows from the stats wizard page."""
        for row in list(self.stats_page.rows):
            try:
                self.stats_page.rows_layout.removeWidget(row)

                if row in self.stats_page.rows:
                    self.stats_page.rows.remove(row)

                row.hide()
                row.setParent(None)
                row.deleteLater()

            except Exception as error:
                logging.exception("Failed to detach stat row: %s", error)

        self.stats_page.rows.clear()

    def _apply_stats_data(self, stats: list[Any]) -> None:
        """Applies tracked-stat template data."""
        self._clear_stat_rows()

        for stat in stats:
            if not isinstance(stat, dict):
                logging.warning("Skipped malformed stat template row: %r", stat)
                continue

            try:
                minimum = int(stat.get("min", 0))
                maximum = int(stat.get("max", 100))
                value = int(stat.get("value", 100))
            except (TypeError, ValueError):
                logging.exception("Invalid stat numeric values in template: %r", stat)
                minimum = 0
                maximum = 100
                value = 100

            if maximum < minimum:
                logging.warning("Template stat max was below min. Swapping values for %r", stat)
                minimum, maximum = maximum, minimum

            value = max(minimum, min(maximum, value))

            self.stats_page.add_row(
                name=str(stat.get("name", "") or ""),
                value=value,
                enabled=bool(stat.get("enabled", True)),
                desc=str(stat.get("description", stat.get("desc", "")) or ""),
                min_val=minimum,
                max_val=maximum,
            )

    def _apply_character_data(self, character: dict[str, Any]) -> None:
        """Applies character-related template data."""
        if not isinstance(character, dict):
            return

        self.char_page.name_input.setText(str(character.get("name", "") or ""))
        self.char_page.age_input.setText(str(character.get("age", "") or ""))
        self.char_page.gender_input.setText(str(character.get("gender", "") or ""))
        self.char_page.pronouns_input.setText(str(character.get("pronouns", "") or ""))
        self.char_page.orientation_input.setText(str(character.get("orientation", "") or ""))
        self.char_page.background_input.setPlainText(str(character.get("background", "") or ""))

    def _apply_skills_data(self, skills: list[Any]) -> None:
        """Applies starting-skill template data."""
        clean_skills = [item for item in skills if isinstance(item, dict)]

        for index, (_level, name_widget, desc_widget) in enumerate(self.skills_page.skill_inputs):
            if index >= len(clean_skills):
                name_widget.setText("")
                desc_widget.setText("")
                continue

            skill = clean_skills[index]
            name_widget.setText(str(skill.get("name", "") or ""))
            desc_widget.setText(str(skill.get("desc", skill.get("description", "")) or ""))

    def _apply_final_data(self, data: dict[str, Any]) -> None:
        """Applies final-page template data."""
        self.final_page.location_input.setText(str(data.get("starting_location", "") or ""))
        self.final_page.comments_input.setPlainText(str(data.get("final_comments", "") or ""))
    
    def get_wizard_data(self) -> dict:
        """Extracts all data from the wizard pages into a neat dictionary."""
        
        # Gather focus pillars
        pillars = []
        if self.pillars_page.combat_cb.isChecked(): pillars.append("Combat")
        if self.pillars_page.exploration_cb.isChecked(): pillars.append("Exploration")
        if self.pillars_page.trading_cb.isChecked(): pillars.append("Trading/Economy")
        if self.pillars_page.social_cb.isChecked(): pillars.append("Social/Roleplay")
        
        currencies = [r.get_data() for r in self.currency_page.rows if r.get_data()["name"].strip()]
        currencies.sort(key=lambda x: x["value"]) # Sort mathematically
        
        stats = [r.get_data() for r in self.stats_page.rows if r.get_data()["name"].strip()]

        # Gather skills
        skills = []
        for level, name_w, desc_w in self.skills_page.skill_inputs:
            # If the user leaves it blank, we pass "Unknown Skill Name" to force the AI to invent one
            s_name = name_w.text().strip() or "Unknown Skill Name"
            skills.append({
                "level": level,
                "name": s_name,
                "desc": desc_w.text().strip() or "Unknown Skill Description"
            })
            
        wizard_data = {
            "world": {
                "setting": self.world_page.setting_input.toPlainText().strip(),
                "genre": self.world_page.genre_input.text().strip(),
                "tech": self.world_page.tech_input.text().strip(),
                "species": self.world_page.species_input.toPlainText().strip(),
            },
            "focus": pillars,
            "currencies": currencies,
            "stats": stats,
            "calendar": self.calendar_page.get_data(),
            "character": {
                "name": self.char_page.name_input.text().strip(),
                "age": self.char_page.age_input.text().strip(),
                "gender": self.char_page.gender_input.text().strip(),
                "pronouns": self.char_page.pronouns_input.text().strip(),
                "orientation": self.char_page.orientation_input.text().strip(),
                "background": self.char_page.background_input.toPlainText().strip(),
            },
            "skills": skills,
            "starting_location": self.final_page.location_input.text().strip(),
            "final_comments": self.final_page.comments_input.toPlainText().strip(),
        }

        return CreationTemplateStore.normalize_wizard_data(wizard_data)
