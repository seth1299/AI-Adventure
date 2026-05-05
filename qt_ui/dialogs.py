"""Centralized Qt dialog and wizard classes for AI RPG Adventure.

This module replaces the individual ``*_dialog.py`` files and keeps related
row widgets plus the new-game wizard in one import location.
"""

from __future__ import annotations

import logging
import os
import re
import shutil

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
)

from config import SAVES_DIR

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

# ---- Merged from qt_ui/equipment_dialog.py ----
class EquipmentManagerDialog(QDialog):
    """
    A pop-out dialog that allows the player to manage their equipped items 
    without requiring an AI API call. It pulls available items directly from the inventory.
    """
    def __init__(self, parent, app_context):
        super().__init__(parent)
        self.setWindowTitle("Manage Equipment")
        self.setMinimumSize(500, 450)
        self.app = app_context
        
        # Load the player's current equipment and inventory
        self.current_equipment = self.app.player.equipment.copy()
        self.inventory_data = self._fetch_inventory_data()
        
        # Dictionary to store the ComboBoxes for easy reference
        self.dropdowns = {}
        
        self._setup_ui()
        
    def _fetch_inventory_data(self) -> dict:
        """Safely fetches the JSON data from the InventoryPanel."""
        try:
            if "Inventory" in self.app.notebook_widgets:
                return self.app.notebook_widgets["Inventory"].load_data()
        except Exception as error:
            logging.error(f"EquipmentDialog failed to load inventory: {error}")
        return {}

    def _setup_ui(self):
        """Builds the dropdowns and description viewer."""
        layout = QVBoxLayout(self)
        
        self.lbl_total_ar = QLabel("<b>Total Armor Rating:</b> 0")
        self.lbl_total_ar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_total_ar.setStyleSheet("font-size: 14px; padding: 5px;")
        layout.addWidget(self.lbl_total_ar)
        
        # Group Box for the Dropdowns
        form_group = QGroupBox("Equipped Gear")
        form_layout = QVBoxLayout()
        
        # Define which inventory categories map to which slots to keep the dropdowns clean
        slot_filters = {
            "Head": ["Armor", "Apparel", "Clothing", "Headgear"],
            "Chest": ["Armor", "Apparel", "Clothing", "Chestpiece"],
            "Legs": ["Armor", "Apparel", "Clothing", "Legwear"],
            "Main Hand": ["Weapon", "Weapons", "Tool", "Shield"],
            "Off Hand": ["Weapon", "Weapons", "Tool", "Shield"],
            "Accessory": ["Accessory", "Jewelry", "Ring", "Amulet"]
        }
        
        for slot in self.current_equipment.keys():
            row_layout = QHBoxLayout()
            
            lbl_slot = QLabel(f"{slot}:")
            lbl_slot.setFixedWidth(80)
            
            dropdown = QComboBox()
            # Add an empty option to unequip items
            dropdown.addItem("-- Empty --", userData=None)

            btn_inspect = QPushButton("?")
            btn_inspect.setFixedWidth(30)
            btn_inspect.setToolTip(f"Inspect the item equipped in the {slot} slot.")
            btn_inspect.clicked.connect(lambda checked=False, cb=dropdown: self._force_preview(cb))
            # Populate the dropdown with items from the inventory
            valid_categories = slot_filters.get(slot, [])
            for category, items in self.inventory_data.items():
                # We do a loose match to catch things like "Weapons" vs "Weapon"
                if any(valid.lower() in category.lower() for valid in valid_categories):
                    for item in items:
                        if isinstance(item, dict):
                            item_name = item.get("name", "Unknown Item")
                            # We store the entire item dictionary in the ComboBox's userData!
                            dropdown.addItem(item_name, userData=item)
            
            # Set the dropdown to the currently equipped item, if any
            current_item = self.current_equipment.get(slot)
            if current_item:
                current_name = current_item.get("name")
                index = dropdown.findText(current_name)
                if index >= 0:
                    dropdown.setCurrentIndex(index)
                    
            dropdown.currentIndexChanged.connect(self._on_dropdown_changed)
                    
            # Connect the dropdown change event to our description updater
            dropdown.currentIndexChanged.connect(self._update_description_preview)
            
            row_layout.addWidget(lbl_slot)
            row_layout.addWidget(dropdown, stretch=1)
            row_layout.addWidget(btn_inspect)
            form_layout.addLayout(row_layout)
            
            self.dropdowns[slot] = dropdown
            
        form_group.setLayout(form_layout)
        layout.addWidget(form_group)
        
        # Group Box for the Item Description Preview
        preview_group = QGroupBox("Item Details")
        preview_layout = QVBoxLayout()
        self.txt_description = QTextBrowser()
        self.txt_description.setPlaceholderText("Select an item to view its details and stats...")
        self.txt_description.setMaximumHeight(100)
        preview_layout.addWidget(self.txt_description)
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Equip / Save")
        btn_save.clicked.connect(self.accept) # Triggers QDialog's accepted signal
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)        
        layout.addLayout(btn_layout)
        
        self._recalculate_stats()
        
        if self.dropdowns:
            first_dropdown = list(self.dropdowns.values())[0]
            self._force_preview(first_dropdown)
        
        # Initialize preview with whatever is currently selected in the top box
        self._update_description_preview()
        
    def _on_dropdown_changed(self):
        """Validates the item quantities, then updates the UI if valid."""
        sender = self.sender()
        if not isinstance(sender, QComboBox):
            return
            
        item_data = sender.currentData()
        if item_data and isinstance(item_data, dict):
            item_name = item_data.get("name")
            
            # Check how many of this item the player actually owns
            try:
                max_amount = int(item_data.get("amount", 1))
            except ValueError:
                max_amount = 1
                
            # Count how many times this item is currently selected in our dropdowns
            equipped_count = 0
            for dropdown in self.dropdowns.values():
                data = dropdown.currentData()
                if data and isinstance(data, dict) and data.get("name") == item_name:
                    equipped_count += 1
                    
            # If they equipped more than they own, reject the change!
            if equipped_count > max_amount:
                QMessageBox.warning(
                    self, 
                    "Not Enough Items", 
                    f"You only own {max_amount}x '{item_name}'. You cannot equip it in multiple slots."
                )
                
                # Block signals so reverting the index doesn't trigger an infinite loop
                sender.blockSignals(True)
                sender.setCurrentIndex(0) # Revert to "-- Empty --"
                sender.blockSignals(False)

        # Update the text box preview for the dropdown that was just interacted with
        self._force_preview(sender)
        
        # Recalculate AR
        self._recalculate_stats()

    def _update_description_preview(self):
        """Updates the text browser with the description of the currently highlighted combobox item."""
        sender = self.sender()
        if not isinstance(sender, QComboBox):
            # Guard clause to prevent IndexError if no dropdowns exist
            if not self.dropdowns:
                self.txt_description.clear()
                return
            sender = list(self.dropdowns.values())[0]
            
        item_data = sender.currentData()
        if item_data and isinstance(item_data, dict):
            nice_text = self._format_item_details(item_data)
            self.txt_description.setMarkdown(nice_text)
        else:
            self.txt_description.clear()

    def get_final_equipment(self) -> dict:
        """Extracts the selected items from the dropdowns to be saved to the player."""
        final_equipment = {}
        for slot, dropdown in self.dropdowns.items():
            final_equipment[slot] = dropdown.currentData()
        return final_equipment
    
    def _format_item_details(self, item_data: dict) -> str:
        """
        Extracts raw AI tags (like (ACC: +1)) from the description, 
        removes them, and formats them into a clean UI stat block.
        """
        name = item_data.get("name", "Unknown")
        desc = item_data.get("desc", "No description available.")
        
        # 1. Extract the stats
        ar_match = re.search(r"\(AR:\s*(\d+)\)", desc, re.IGNORECASE)
        acc_match = re.search(r"\(ACC:\s*([+-]?\d+)\)", desc, re.IGNORECASE)
        dmg_match = re.search(r"\(DMG:\s*([^)]+)\)", desc, re.IGNORECASE)
        ran_match = re.search(r"\(RAN:\s*([^)]+)\)", desc, re.IGNORECASE)
        typ_match = re.search(r"\(TYP:\s*([^)]+)\)", desc, re.IGNORECASE)
        amm_match = re.search(r"\(AMM:\s*([^)]+)\)", desc, re.IGNORECASE)
        mag_match = re.search(r"\(MAG:\s*([^)]+)\)", desc, re.IGNORECASE)
        
        # 2. Strip all the raw tags out of the description
        clean_desc = re.sub(r"\((AR|ACC|DMG|RAN|TYP|AMM|MAG):\s*[^)]+\)", "", desc, flags=re.IGNORECASE).strip()
        
        # 3. Build the neat stat block
        stats = []
        if ar_match: stats.append(f"**AR:** {ar_match.group(1)}")
        if acc_match: stats.append(f"**ACC:** {acc_match.group(1)}")
        if dmg_match: stats.append(f"**DMG:** {dmg_match.group(1)}")
        if ran_match: stats.append(f"**Range:** {ran_match.group(1)}")
        if typ_match: stats.append(f"**Type:** {typ_match.group(1)}")
        if amm_match: stats.append(f"**Ammo:** {amm_match.group(1)}")
        if mag_match: stats.append(f"**Mag:** {mag_match.group(1)}")
        
        stat_string = " | ".join(stats)
        
        # 4. Return the formatted Markdown
        if stat_string:
            return f"**{name}**\n\n*{clean_desc}*\n\n{stat_string}"
        else:
            return f"**{name}**\n\n{clean_desc}"
    
    def _force_preview(self, combobox: QComboBox):
        """Forces the text browser to show the details of the specific combobox clicked."""
        item_data = combobox.currentData()
        if item_data and isinstance(item_data, dict):
            # Use our new formatter!
            nice_text = self._format_item_details(item_data)
            self.txt_description.setMarkdown(nice_text)
        else:
            self.txt_description.setMarkdown("*(Slot is empty)*")

    def _recalculate_stats(self):
        """Scans all selected items in the dropdowns and dynamically sums up the Armor Rating."""
        total_armor = 0
        for dropdown in self.dropdowns.values():
            item_data = dropdown.currentData()
            if item_data and isinstance(item_data, dict):
                desc = item_data.get("desc", "")
                match = re.search(r"\(AR:\s*(\d+)\)", desc, re.IGNORECASE)
                if match:
                    try:
                        total_armor += int(match.group(1))
                    except ValueError:
                        pass
                        
        self.lbl_total_ar.setText(f"<b>Total Armor Rating:</b> {total_armor}")

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
        try:
            os.makedirs(SAVES_DIR, exist_ok=True)
        except Exception:
            logging.exception("Failed to ensure saves dir exists")
            return

        self.list.clear()

        try:
            saves = [
                d
                for d in os.listdir(SAVES_DIR)
                if os.path.isdir(os.path.join(SAVES_DIR, d))
            ]
            saves.sort(key=lambda s: s.lower())
        except Exception:
            logging.exception("Failed to list saves")
            saves = []

        if not saves:
            self.list.addItem("(No saved adventures yet)")
            self.list.setEnabled(False)
        else:
            self.list.setEnabled(True)
            for s in saves:
                self.list.addItem(s)

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
        text, ok = QInputDialog.getText(self, "New Adventure", "Name your adventure:")
        if not ok:
            return

        name = self._sanitize_name(text)
        if not name:
            return

        full = os.path.join(SAVES_DIR, name)
        if os.path.exists(full):
            QMessageBox.warning(self, "New Adventure", "That adventure already exists.")
            return

        try:
            os.makedirs(full, exist_ok=True)
        except Exception:
            logging.exception("Failed to create new save folder")
            QMessageBox.critical(self, "New Adventure", "Failed to create the save folder (see logs).")
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
        self.setTitle("Step 5: Character Bio")
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
        self.setTitle("Step 6: Skills")
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
        self.setTitle("Step 7: Final Details")
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

    def remove_row(self, row):
        if row.is_baseline: return
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()
        
    # Notice we completely removed the validatePage() function!


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

    def add_row(self, name="", value=100, enabled=True, desc=""):
        row = StatRow(name=name, value=value, enabled=enabled, desc=desc)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_row(row))

    def remove_row(self, row):
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

class CreationWizard(QWizard):
    def __init__(self, parent=None):
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
        self.char_page = CharacterPage()
        self.skills_page = SkillsPage()
        self.final_page = FinalPage()
        
        self.addPage(self.world_page)
        self.addPage(self.pillars_page)
        self.addPage(self.currency_page)
        self.addPage(self.stats_page)
        self.addPage(self.char_page)
        self.addPage(self.skills_page)
        self.addPage(self.final_page)

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

        return {
            "world": {
                "setting": self.world_page.setting_input.toPlainText().strip(),
                "genre": self.world_page.genre_input.text().strip(),
                "tech": self.world_page.tech_input.text().strip(),
                "species": self.world_page.species_input.toPlainText().strip(),
            },
            "focus": pillars,
            "currencies": currencies,
            "stats": stats,
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
            "final_comments": self.final_page.comments_input.toPlainText().strip()
        }

