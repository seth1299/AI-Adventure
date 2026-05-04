# qt_ui/equipment_dialog.py (New File)
import logging, re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QPushButton, QTextBrowser, QGroupBox, QMessageBox
)
from PySide6.QtCore import Qt

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