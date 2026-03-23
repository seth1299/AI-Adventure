# qt_ui/inventory_panel.py
from __future__ import annotations

import json
import logging
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
)

from tabulate import tabulate

from file_manager import FileManager
from time_utils import to_abs_minutes


class InventoryPanel(QWidget):
    """Qt Inventory panel that reads/writes inventory.json and renders a readable table.

    Mirrors the data behavior of the old CTk InventoryTab:
    - JSON storage: { "Category": [ {name, desc, amount, value, ...}, ... ] }
    - Methods used by AIManager tags: autonomous_add/remove, add_food, consume_food, modify_item
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
        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setFont(QFont("Consolas", 11))
        self.display.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
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
        return self.display.toPlainText()

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
            self.display.setPlainText("(No save loaded)")
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
            self.display.setPlainText("INVENTORY\n\n(Empty)")
            self._set_state("")
            return

        headers = ["Name", "Description", "Amount", "Value (each)"]
        
        wealth_str = "0 (None)"
        if player:
            wealth_str = player.get_formatted_currency()
        else:
            logging.error("Cannot find Player object.")
            
        parts: list[str] = ["INVENTORY\n", f"Wealth: {wealth_str}\n"]

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
                parts.append("\nWealth / Currencies\n")
                parts.append(tabulate(currency_rows, headers, tablefmt="rounded_grid"))
                parts.append("\n")

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
                    val = int(item.get("value", 0))

                    # Expand food metadata into description
                    meta = item.get("meta") if isinstance(item.get("meta"), dict) else None
                    if meta and "meals" in meta:
                        meals = meta.get("meals")
                        spoil_day = str(meta.get("spoil_day", ""))
                        spoil_time = str(meta.get("spoil_time", ""))
                        nut = meta.get("nutrition_restored")

                        spoil_prefix = "" if "day" in spoil_day.lower() else "Day "
                        extra = f" [Meals: {meals}"
                        if spoil_day and spoil_time:
                            extra += f", Spoils: {spoil_prefix}{spoil_day} at {spoil_time}"
                        if nut is not None:
                            extra += f", Nutrition Value: {nut}"
                        extra += "]"
                        desc += extra
                elif isinstance(item, list):
                    name = str(item[0]) if len(item) > 0 else "Unknown"
                    desc = str(item[1]) if len(item) > 1 else "No desc"
                    amt = str(item[2]) if len(item) > 2 else "1"
                    val = int(item[3]) if len(item) > 3 else 0
                else:
                    continue

                rows.append([name, desc, amt, val])

            parts.append(f"\n{category}\n")
            parts.append(tabulate(rows, headers, tablefmt="rounded_grid"))
            parts.append("\n")

        self.display.setPlainText("".join(parts).rstrip() + "\n")
        self._set_state("")

    def _set_state(self, text: str) -> None:
        self.lbl_state.setText(text or "")

    # ---- Time helper ----

    def _get_ticks(self, day, time_str) -> int:
        return int(to_abs_minutes(day, time_str))
    
    def _safe_int(self, value, default: int = 0) -> int:
        """Safely extract first integer from a value. Returns default if none found."""
        if value is None:
            return default
        try:
            match = re.search(r"-?\d+", str(value))
            return int(match.group(0)) if match else default
        except Exception:
            return default

    # ---- AIManager tag helpers ----

    def modify_item(self, raw_args: str):
        try:
            parts = [p.strip() for p in (raw_args or "").split("|")]
            if len(parts) < 1:
                return "Error: Missing Target Name."

            target = parts[0]

            def should_update(idx: int) -> bool:
                if len(parts) <= idx:
                    return False
                val = (parts[idx] or "").strip().upper()
                return val not in ("SAME", "SKIP", "", "N/A")

            new_name = parts[1] if should_update(1) else None
            new_desc = parts[2] if should_update(2) else None
            new_amt = parts[3] if should_update(3) else None
            new_val = parts[4] if should_update(4) else None

            data = self.load_data()
            found = False

            for _cat, items in data.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    current_name = ""
                    if isinstance(item, dict):
                        current_name = str(item.get("name", ""))
                    elif isinstance(item, list) and item:
                        current_name = str(item[0])
                    if current_name.lower() != str(target).lower():
                        continue

                    if isinstance(item, dict):
                        if new_name:
                            item["name"] = new_name
                        if new_desc:
                            item["desc"] = new_desc
                        if new_amt:
                            item["amount"] = new_amt
                        if new_val:
                            item["value"] = new_val
                    else:
                        if new_name:
                            item[0] = new_name
                        if new_desc:
                            item[1] = new_desc
                        if new_amt:
                            item[2] = new_amt
                        if new_val:
                            item[3] = new_val

                    found = True
                    break
                if found:
                    break

            if found:
                self.save_data(data)
                changes = []
                if new_name:
                    changes.append(f"Name->{new_name}")
                if new_desc:
                    changes.append("Description updated")
                if new_val:
                    changes.append("Value updated")
                return f""
            return f"System: Could not find item '{target}' to modify."
        except Exception as e:
            logging.exception(f"InventoryPanel.modify_item failed for arguments {raw_args}: {e}")

    def autonomous_add(self, raw_args: str):
        try:
            parts = [p.strip() for p in (raw_args or "").split("|")]
            if len(parts) < 2:
                return "Error: Data missing."

            category = parts[0].title()
            name = parts[1]
            desc = parts[2] if len(parts) > 2 else "No description."
            amount = parts[3] if len(parts) > 3 else "1"
            value = parts[4] if len(parts) > 4 else "N/A"

            new_item = {"name": name, "desc": desc, "amount": amount, "value": value}

            data = self.load_data()
            if category not in data or not isinstance(data.get(category), list):
                data[category] = []

            # Stack logic (only for non-meta items)
            found = False
            for item in data[category]:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name", "")).lower() == str(name).lower() and "meta" not in item:
                    try:
                        cur_amt = self._safe_int(item.get("amount", 0), 0)
                        add_amt = self._safe_int(amount, 0)
                        item["amount"] = str(cur_amt + add_amt)
                        found = True
                    except Exception as e:
                        logging.error(f"InventoryPanel.autonomous_add: stacking failed: {e}")
                    break

            if not found:
                data[category].append(new_item)

            self.save_data(data)
            return f"(Added {amount}x {name} to inventory as \"{category}\"!)."
        except Exception:
            logging.exception("InventoryPanel.autonomous_add failed")
            return f"Sorry, I had trouble adding '{raw_args}' to your inventory."

    def autonomous_remove(self, raw_args: str):
        try:
            parts = [p.strip() for p in (raw_args or "").split("|")]
            target_name = parts[0] if parts else (raw_args or "").strip()
            amount = self._safe_int(parts[1], 1) if len(parts) > 1 else 1

            data = self.load_data()
            removed = False

            for _cat, items in data.items():
                if not isinstance(items, list):
                    continue
                for i in range(len(items) - 1, -1, -1):
                    it = items[i]
                    it_name = ""
                    it_amt = "1"
                    if isinstance(it, dict):
                        it_name = str(it.get("name", ""))
                        it_amt = str(it.get("amount", "1"))
                    elif isinstance(it, list) and it:
                        it_name = str(it[0])
                        it_amt = str(it[2]) if len(it) > 2 else "1"
                    else:
                        continue

                    if str(target_name).lower() not in it_name.lower():
                        continue

                    try:
                        curr = self._safe_int(it_amt, 0)
                        new_val = curr - amount
                        if new_val <= 0:
                            items.pop(i)
                        else:
                            if isinstance(it, dict):
                                it["amount"] = str(new_val)
                            else:
                                it[2] = str(new_val)
                        removed = True
                    except Exception:
                        items.pop(i)
                        removed = True
                    break
                if removed:
                    break

            if removed:
                self.save_data(data)
                return f"(Lost {amount}x {target_name})."
            return f"System: Could not find {target_name}."
        except Exception:
            logging.exception("InventoryPanel.autonomous_remove failed")
            return f"Sorry, I had trouble finding {raw_args}."

    def add_food(self, raw_args: str):
        # Format: Type | Name | Desc | Amount | Value | Meals | SpoilDay | SpoilTime | Nutrition_Restored
        try:
            parts = [p.strip() for p in (raw_args or "").split("|")]
            if len(parts) < 6:
                return "Error: Missing Food Data."

            category = parts[0].title()  # usually Food
            name = parts[1]
            desc = parts[2]
            amount = parts[3]
            value = parts[4]
            meals = self._safe_int(parts[5] if len(parts) > 4 else 1)
            spoil_day = parts[6] if len(parts) > 6 else "Day 99"
            spoil_time = parts[7] if len(parts) > 7 else "11:59 PM"
            nutrition_restored = parts[8] if len(parts) > 8 else 15

            meta = {
                "type": "food",
                "meals": meals,
                "spoil_day": spoil_day,
                "spoil_time": spoil_time,
                "nutrition_restored": nutrition_restored,
            }
            new_item = {"name": name, "desc": desc, "amount": amount, "value": value, "meta": meta}

            data = self.load_data()
            if category not in data or not isinstance(data.get(category), list):
                data[category] = []
            data[category].append(new_item)

            self.save_data(data)
            return f"(Added {name} [Meals: {meals}, Spoils: {spoil_day} at {spoil_time}, Nutrition Restored: {nutrition_restored}])."
        except Exception:
            logging.exception("InventoryPanel.add_food failed")
            return f"System Error adding food: {raw_args}"

    def consume_food(self, name: str, current_day, current_time):
        try:
            data = self.load_data()
            current_ticks = self._get_ticks(current_day, current_time)

            for _category, items in data.items():
                if not isinstance(items, list):
                    continue
                for i, item in enumerate(list(items)):
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("name", "")).lower() != str(name).lower():
                        continue

                    meta = item.get("meta") if isinstance(item.get("meta"), dict) else None
                    if not meta:
                        return self.autonomous_remove(f"{name}|1")

                    spoil_ticks = self._get_ticks(meta.get("spoil_day", "Day 99"), meta.get("spoil_time", "12:00 AM"))
                    nutrition_restored = meta.get("nutrition_restored", 15)

                    if current_ticks >= spoil_ticks:
                        items.pop(i)
                        self.save_data(data)
                        return (
                            f"You cannot eat {name}. It smells rotten "
                            f"(Spoiled on {meta.get('spoil_day')} at {meta.get('spoil_time')}. "
                            f"You decide it's best to get rid of it.)[[REMOVE: {name} | 1]]."
                        )

                    # Consume one meal
                    meta["meals"] = int(meta.get("meals", 1)) - 1
                    remaining = int(meta.get("meals", 0))

                    if remaining <= 0:
                        items.pop(i)
                        msg = f"(Ate the last of {name}. It is finished.)"
                    else:
                        msg = f"(Ate a meal of {name}. {remaining} meals remaining.)"

                    # Apply nutrition stat change via existing tag logic
                    try:
                        n = int(nutrition_restored)
                    except Exception:
                        n = 0
                    sign = "+" if n > 0 else ""
                    msg += f"[[MODIFY_STAT: NUTRITION | {sign}{n}]]"

                    self.save_data(data)
                    return msg

            return f"System: Could not find food '{name}'."
        except Exception:
            logging.exception("InventoryPanel.consume_food failed")
            return f"System: Could not consume '{name}'."