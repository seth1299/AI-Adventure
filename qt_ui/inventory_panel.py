# qt_ui/inventory_panel.py
from __future__ import annotations
import logging, os
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
from tabulate import tabulate
from file_manager import FileManager

class InventoryPanel(QWidget):
    """Qt Inventory panel that reads/writes inventory.json and renders a readable table.

    """

    def __init__(self, parent: QWidget | None = None, app_context=None) -> None:
        super().__init__(parent)
        self.data_path: str = ""
        self.app = app_context

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ---- Toolbar ----
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.lbl_title = QLabel("Inventory")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.lbl_title, stretch=1)

        self.lbl_state = QLabel("")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.lbl_state)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setFixedWidth(90)
        self.btn_reload.clicked.connect(self.refresh_display)
        bar.addWidget(self.btn_reload)

        self.btn_save = QPushButton("Save")
        self.btn_save.setFixedWidth(90)
        self.btn_save.clicked.connect(self._save_current)
        bar.addWidget(self.btn_save)

        root.addLayout(bar)

        # ---- Display ----
        self.display = QTextBrowser()
        self.display.setFont(QFont("Consolas", 11))
        root.addWidget(self.display, stretch=1)
        self._set_state("No save loaded")

    # ---- Wiring ----

    def set_base_path(self, save_folder: str) -> None:
        if not save_folder:
            return
        try:
            os.makedirs(save_folder, exist_ok=True)
        except Exception:
            logging.exception("Failed to ensure save folder exists")

        self.data_path = os.path.join(save_folder, "inventory.json")
        if not os.path.exists(self.data_path):
            FileManager.save_json_data(self.data_path, {})
        self.refresh_display()

    def get_text(self) -> str:
        """Returns the Markdown formatted text of the inventory."""
        return self.display.toMarkdown()

    # ---- Data I/O ----

    def load_data(self) -> dict:
        if not self.data_path or not os.path.exists(self.data_path):
            return {}
        try:
            data = FileManager.load_json_data(self.data_path)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logging.error(f"InventoryPanel: load failed: {e}")
            return {}

    def save_data(self, data: dict) -> None:
        if not self.data_path:
            return
        try:
            FileManager.save_json_data(self.data_path, data)
            self._set_state("Saved")
        except Exception:
            logging.exception("InventoryPanel: save failed")
        self.refresh_display()

    def _save_current(self) -> None:
        """Manual Save button; rewrites the JSON file with whatever is currently on disk."""
        self.save_data(self.load_data())

    # ---- Rendering ----
    
    def _get_player(self):
        """Safely locate the Player object regardless of how the app context was injected."""
        if not self.app: return None
        if hasattr(self.app, 'player'): return self.app.player
        if hasattr(self.app, 'app') and hasattr(self.app.app, 'player'): return self.app.app.player
        return None

    def refresh_display(self) -> None:
        if not self.data_path:
            self.display.setMarkdown("(No save loaded)")
            return

        data = self.load_data()
        player = self._get_player()
        base_currency = 0
        world_currencies = []
        if player:
            base_currency = player.base_currency
            world_currencies = getattr(player, 'world_currencies', [])

        # Only display Empty if there are NO items AND NO currencies defined
        if not data and not world_currencies:
            self.display.setMarkdown("### INVENTORY\n\n*(Empty)*")
            self._set_state("")
            return

        headers = ["Name", "Description", "Amount", "Value"]
        
        wealth_str = "0 (None)"
        if player:
            wealth_str = player.get_formatted_currency()
        else:
            logging.error("Cannot find Player object.")
            
        parts: list[str] = ["### INVENTORY\n\n", f"**Wealth:** {wealth_str}\n\n"]

        # --- DYNAMIC CURRENCY TABLE ---
        if world_currencies:
            remaining = abs(base_currency)
            sorted_currencies = sorted(world_currencies, key=lambda x: int(x.get("value", 1)), reverse=True)
            lowest_coin_name = sorted_currencies[-1].get("name", "Base Units") if sorted_currencies else "Base Units"
            
            currency_rows = []
            for cur in sorted_currencies:
                val = int(cur.get("value", 1))
                if val <= 0: continue
                
                # Calculate how many of this coin we have
                count = remaining // val
                remaining %= val
                name = cur.get("name", "Unknown Coin")
                
                # Format negative debts correctly
                amt_str = str(-count) if base_currency < 0 and count > 0 else str(count)
                
                # ALWAYS append the row, even if count is 0!
                currency_rows.append([name, "Legal Tender", amt_str, f"{val} {lowest_coin_name}"])
            
            # If there's weird loose change left over from bad AI math, show it
            if remaining > 0:
                loose_str = str(-remaining) if base_currency < 0 else str(remaining)
                currency_rows.append(["Loose Change", "Base Units", loose_str, "1 base unit"])
                
            if currency_rows:
                parts.append("#### Wealth / Currencies\n\n")
                # Generate the rounded grid
                grid = tabulate(currency_rows, headers, tablefmt="rounded_grid")
                # Wrap it in a Markdown code block (```) to preserve the grid shape
                parts.append(f"```text\n{grid}\n```\n\n")

        # --- REGULAR ITEMS ---
        for category in sorted(data.keys(), key=lambda s: str(s).lower()):
            items = data.get(category) or []
            if not isinstance(items, list) or not items:
                continue

            # Sort by item name for stability
            items_sorted = sorted(
                items,
                key=lambda it: str(it.get("name", "")).lower() if isinstance(it, dict) else str(it[0]).lower(),
            )

            rows = []
            for item in items_sorted:
                if isinstance(item, dict):
                    name = str(item.get("name", "Unknown"))
                    desc = str(item.get("desc", "No desc"))
                    amt = str(item.get("amount", "1"))

                elif isinstance(item, list):
                    name = str(item[0]) if len(item) > 0 else "Unknown"
                    desc = str(item[1]) if len(item) > 1 else "No desc"
                    amt = str(item[2]) if len(item) > 2 else "1"
                else:
                    continue

                rows.append([name, desc, amt])

            parts.append(f"#### {category}\n\n")
            # Change tablefmt to "pipe"
            parts.append(tabulate(rows, headers, tablefmt="pipe"))
            parts.append(f"```text\n{grid}\n```\n\n")

        self.display.setMarkdown("".join(parts).rstrip() + "\n")
        self._set_state("")

    def _set_state(self, text: str) -> None:
        self.lbl_state.setText(text or "")

    # ---- AIManager tag helpers ----

    def modify_item(self, raw_args: str):
        """
        Parses a [[MODIFY_ITEM:]] tag to alter an existing item's name, description, or amount.
        Ensures that the 'amount' field is stored strictly as an integer in the JSON data.
        """
        try:
            parts = [p.strip() for p in (raw_args or "").split("|")]
            if len(parts) < 1:
                return "Error: Missing Target Name."

            target_name = parts[0]

            # Helper function to determine if the AI actually wants to change this parameter
            def should_update(idx: int) -> bool:
                if len(parts) <= idx:
                    return False
                val = (parts[idx] or "").strip().upper()
                return val not in ("SAME", "SKIP", "", "N/A")

            new_name = parts[1] if should_update(1) else None
            new_description = parts[2] if should_update(2) else None
            new_amount = parts[3] if should_update(3) else None

            data = self.load_data()
            found = False

            for category, items in data.items():
                if not isinstance(items, list):
                    continue
                    
                for item in items:
                    current_name = ""
                    if isinstance(item, dict):
                        current_name = str(item.get("name", ""))
                    elif isinstance(item, list) and item:
                        current_name = str(item[0])
                        
                    # Skip if this isn't the item we are looking for
                    if current_name.lower() != str(target_name).lower():
                        continue

                    # Apply modifications to standard Dictionary items
                    if isinstance(item, dict):
                        if new_name:
                            item["name"] = new_name
                        if new_description:
                            item["desc"] = new_description
                        if new_amount:
                            try:
                                # Explicitly cast and store as an integer
                                item["amount"] = int(new_amount)
                            except ValueError:
                                logging.error(f"modify_item: Invalid integer amount '{new_amount}'. Skipping amount update.")
                    
                    # Fallback for older array-style items, if any still exist
                    else:
                        if new_name:
                            item[0] = new_name
                        if new_description:
                            item[1] = new_description
                        if new_amount:
                            try:
                                item[2] = int(new_amount)
                            except ValueError:
                                logging.error(f"modify_item: Invalid integer amount '{new_amount}'. Skipping amount update.")

                    found = True
                    break
                    
                if found:
                    break

            if found:
                self.save_data(data)
            else:
                logging.warning(f"modify_item: Could not find item '{target_name}' to modify.")
                    
        except Exception as e:
            logging.exception(f"InventoryPanel.modify_item failed for arguments {raw_args}: {e}")
            
        self.refresh_display()

    def autonomous_add(self, raw_args: str):
        """
        Parses an [[ADD:]] tag to safely add a new item or stack onto an existing one.
        Saves the amount strictly as an integer in the JSON file.
        """
        try:
            parts = [p.strip() for p in (raw_args or "").split("|")]
            if len(parts) < 2:
                return "Error: Data missing."

            category = parts[0].title()
            name = parts[1]
            description = parts[2] if len(parts) > 2 else "No description."
            
            # Safely parse the incoming amount to add as an integer
            try:
                amount_to_add = int(parts[3]) if len(parts) > 3 else 1
            except ValueError:
                amount_to_add = 1

            # Store the amount directly as an int, not a string
            new_item = {"name": name, "desc": description, "amount": amount_to_add}

            data = self.load_data()
            if category not in data or not isinstance(data.get(category), list):
                data[category] = []

            # Check if we should stack the item
            found = False
            for item in data[category]:
                if not isinstance(item, dict):
                    continue
                
                if str(item.get("name", "")).lower() == str(name).lower() and "meta" not in item:
                    try:
                        # Parse the current amount safely, then store the new sum directly as an int
                        current_amount = int(item.get("amount", 0))
                        item["amount"] = current_amount + amount_to_add
                        found = True
                        
                    except Exception as e:
                        logging.error(f"InventoryPanel.autonomous_add: stacking failed: {e}")
                    break

            # If it's a brand new item, append it to the category
            if not found:
                data[category].append(new_item)
                logging.info(f"Successfully added {amount_to_add}x {name} to the Player's inventory.")

            self.save_data(data)
        except Exception as e:
            logging.error(f"InventoryPanel.autonomous_add failed: {e}")
            
        self.refresh_display()

    def autonomous_remove(self, raw_args: str):
        """
        Parses a [[REMOVE:]] tag to decrease an item's amount or remove it completely.
        Ensures the remaining amount is saved strictly as an integer.
        """
        try:
            parts = [p.strip() for p in (raw_args or "").split("|")]
            target_name = parts[0] if parts else (raw_args or "UNKNOWN ITEM").strip()
            
            # Safely cast the amount to remove to an integer
            try:
                amount_to_remove = int(parts[1]) if len(parts) > 1 else 1
            except ValueError:
                amount_to_remove = 1
                
            data = self.load_data()
            removed = False

            for _category, items in data.items():
                if not isinstance(items, list):
                    continue
                
                # Loop using index so we can safely pop the item if it hits 0
                for index in range(len(items)):
                    item = items[index]
                    if not isinstance(item, dict): 
                        continue
                        
                    item_name = str(item.get("name", "UNKNOWN NAME"))

                    # Case-insensitive matching
                    if str(target_name).lower() not in item_name.lower():
                        continue

                    # Safely cast current item amount to an int
                    try:
                        current_amount = int(item.get("amount", 1))
                    except ValueError:
                        current_amount = 1

                    try:
                        new_amount = current_amount - amount_to_remove
                        if new_amount <= 0:
                            items.pop(index) 
                        else:
                            # Store the resulting amount directly as an int
                            item["amount"] = new_amount 
                        removed = True
                    except Exception as e: 
                        logging.error(f"Error removing item: {e}")

                    break # Break inner loop
                
                if removed:
                    break # Break outer loop

            if removed:
                self.save_data(data)
                logging.info(f"(Player lost {amount_to_remove}x {target_name}).")
            else: 
                logging.error(f"Error: Could not find '{target_name}' to remove.")
                
        except Exception as e:
            logging.error(f"InventoryPanel.autonomous_remove failed: {e}")
            
        self.refresh_display()