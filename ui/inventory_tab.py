import customtkinter as ctk
import os
import json
from tabulate import tabulate
from config import TIME_ORDER

class InventoryTab(ctk.CTkFrame):
    """Displays Inventory dynamically based on Item Types."""
    def __init__(self, parent):
        super().__init__(parent)
        self.data_path = ""
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1) 
        
        self.display = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="none", state="disabled")
        self.display.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    def set_base_path(self, folder_path):
        self.data_path = os.path.join(folder_path, "inventory.json")
        self.refresh_display()

    def get_text(self):
        return self.display.get("0.0", "end")

    def load_data(self):
        if not self.data_path or not os.path.exists(self.data_path):
            return {}
        try:
            with open(self.data_path, "r") as f:
                return json.load(f)
        except:
            return {}

    def save_data(self, data):
        if not self.data_path: return
        with open(self.data_path, "w") as f:
            json.dump(data, f, indent=4)
        self.refresh_display()
        
    # --- Time Helper ---
    def _get_ticks(self, day, time_str):
        """Converts Day/Time to an integer for comparison."""
        try:
            d = int(''.join(filter(str.isdigit, str(day))))
        except: d = 1
        
        t_idx = 0
        t_clean = time_str.lower().strip()
        for i, val in enumerate(TIME_ORDER):
            if val.lower() in t_clean: 
                t_idx = i
                break
        return (d * len(TIME_ORDER)) + t_idx

    def refresh_display(self):
        data = self.load_data()
        headers = ["Name", "Description", "Amount", "Value (each)"]
        full_text = "INVENTORY\n"
        display_map = {}
        
        for category in sorted(data.keys()):
            items = data[category]
            if items:
                display_cat = self._make_plural(category)
                display_map[category] = display_cat
                full_text += f"\n{category}\n"
                
                table_rows = []
                for item in items:
                    # --- SAFETY CHECK: Handle both Dicts and Lists ---
                    if isinstance(item, dict):
                        # New Format
                        name = item.get("name", "Unknown")
                        desc = item.get("desc", "No desc")
                        amt = item.get("amount", "1")
                        val = item.get("value", "0")
                        
                        # Handle Metadata
                        if "meta" in item:
                            meta = item["meta"]
                            if "meals" in meta:
                                extra_info = f" [Meals: {meta['meals']}"
                                if "spoil_day" in meta:
                                    extra_info += f", Spoils: {meta['spoil_day']} {meta['spoil_time']}"
                                extra_info += "]"
                                desc += extra_info
                    
                    elif isinstance(item, list):
                        # Old Format (Legacy Support)
                        # [Name, Desc, Amount, Value]
                        name = item[0] if len(item) > 0 else "Unknown"
                        desc = item[1] if len(item) > 1 else "No desc"
                        amt = item[2] if len(item) > 2 else "1"
                        val = item[3] if len(item) > 3 else "0"
                    
                    else:
                        continue # Skip broken items

                    table_rows.append([name, desc, amt, val])

                full_text += tabulate(table_rows, headers, tablefmt="simple_grid")
                full_text += "\n"
        
        self.display.configure(state="normal")
        self.display.delete("0.0", "end")
        self.display.insert("0.0", full_text)
        self._apply_styles(display_map.values())
        self.display.configure(state="disabled")

    def _apply_styles(self, categories):
        """Applies visual tags to specific words."""
        txt = self.display._textbox
        
        # Define Styles
        txt.tag_config("h1", font=("Consolas", 24, "bold"), foreground="#FFD700", spacing3=10)

        # 1. Main Title
        start_pos = "1.0"
        pos = txt.search("INVENTORY", start_pos, stopindex="end")
        if pos:
            txt.tag_add("h1", pos, f"{pos} lineend")
            
    def modify_item(self, raw_args):
        # Format: TargetName | NewName | NewDesc | NewAmount | NewValue
        # Use "SAME" or "SKIP" to keep the current value for that field
        try:
            parts = [p.strip() for p in raw_args.split("|")]
            if len(parts) < 1: return "Error: Missing Target Name."
            
            target = parts[0]
            # Helper to check if we should update a field
            def should_update(idx):
                if len(parts) <= idx: return False
                val = parts[idx].upper()
                return val not in ["SAME", "SKIP", "", "N/A"]

            new_name = parts[1] if should_update(1) else None
            new_desc = parts[2] if should_update(2) else None
            new_amt  = parts[3] if should_update(3) else None
            new_val  = parts[4] if should_update(4) else None
            
            data = self.load_data()
            found = False
            
            for cat, items in data.items():
                for item in items:
                    # check name (handle both dict and list format for safety)
                    if isinstance(item, dict):
                        current_name = item.get("name", "Unknown")
                    else:
                        current_name = item[0] if item else "Unknown"
                    
                    if current_name.lower() == target.lower():
                        # Found it! Update in place.
                        if isinstance(item, dict):
                            if new_name: item["name"] = new_name
                            if new_desc: item["desc"] = new_desc
                            if new_amt:  item["amount"] = new_amt
                            if new_val:  item["value"] = new_val
                        else:
                            # Legacy List Support
                            if new_name: item[0] = new_name
                            if new_desc: item[1] = new_desc
                            if new_amt:  item[2] = new_amt
                            if new_val:  item[3] = new_val
                        found = True
                        break
                if found: break
            
            if found:
                self.save_data(data)
                changes = []
                if new_name: changes.append(f"Name->{new_name}")
                if new_desc: changes.append("Description updated")
                if new_val:  changes.append("Value updated")
                return f"(Updated {target}: {', '.join(changes)})"
            else:
                return f"System: Could not find item '{target}' to modify."
        except Exception as e:
            return f"Error modifying item: {e}"
            
    def autonomous_add(self, raw_args):
        # UPDATED FORMAT: Type | Name | Description | Amount
        try:
            if "|" in raw_args:
                parts = [p.strip() for p in raw_args.split("|")]
            else:
                parts = [p.strip() for p in raw_args.split(",")]

            if len(parts) < 2: return "Error: Data missing."

            # 1. Type (Category) comes first now
            category = parts[0].title()
            
            # 2. Name comes second
            name = parts[1]
            
            # 3. Description comes third (Optional default)
            desc = parts[2] if len(parts) > 2 else "No description."

            # 4. Amount (Optional default)
            amount = parts[3] if len(parts) > 3 else "1"
            
            # 5. Value
            value = parts[4] if len(parts) > 4 else "N/A"

            # NEW: Dictionary Structure
            new_item = {
                "name": name,
                "desc": desc,
                "amount": amount,
                "value": value
            }

            data = self.load_data()
            if category not in data: data[category] = []
            
            # Stack Logic (using dict keys)
            found = False
            for item in data[category]:
                if item["name"].lower() == name.lower() and "meta" not in item:
                    try:
                        cur_amt = int(item["amount"])
                        add_amt = int(amount)
                        item["amount"] = str(cur_amt + add_amt)
                        found = True
                    except: pass
                    break
            
            if not found:
                data[category].append(new_item)

            self.save_data(data)
            return f"(Added {amount}x {name} to inventory as \"{category}\"!)."

        except Exception as e:
            return f"System: Failed to add item ({e})."
        
    # --- NEW: Food Add ---
    def add_food(self, raw_args):
        # Format: Type | Name | Desc | Amount | Value | Meals | SpoilDay | SpoilTime
        try:
            parts = [p.strip() for p in raw_args.split("|")]
            if len(parts) < 6: return "Error: Missing Food Data."

            category = parts[0].title() # Likely "Food"
            name = parts[1]
            desc = parts[2]
            amount = parts[3] # "1" usually (Container count)
            value = parts[4]
            meals = parts[5]
            spoil_day = parts[6] if len(parts) > 6 else "Day 99"
            spoil_time = parts[7] if len(parts) > 7 else "Midnight"

            # Metadata Dict
            meta = {
                "type": "food",
                "meals": int(meals),
                "spoil_day": spoil_day,
                "spoil_time": spoil_time
            }
            
            # NEW: Dictionary Structure with 'meta' key
            new_item = {
                "name": name,
                "desc": desc,
                "amount": amount,
                "value": value,
                "meta": meta
            }

            data = self.load_data()
            if category not in data: data[category] = []
            
            # We do NOT stack food items with metadata to preserve specific spoilage dates
            data[category].append(new_item)

            self.save_data(data)
            return f"(Added {name} [Meals: {meals}, Spoils: {spoil_day} {spoil_time}])."

        except Exception as e:
            return f"System Error adding food: {e}"
        
    # --- NEW: Consume Logic ---
    def consume_food(self, name, current_day, current_time):
        data = self.load_data()
        current_ticks = self._get_ticks(current_day, current_time)
        
        for category, items in data.items():
            for i, item in enumerate(items):
                if item["name"].lower() == name.lower():
                    # Check if it has Metadata
                    if "meta" in item:
                        meta = item["meta"]
                        
                        # 1. Spoilage Check
                        spoil_ticks = self._get_ticks(meta.get("spoil_day", "Day 99"), meta.get("spoil_time", "Midnight"))
                        
                        if current_ticks >= spoil_ticks:
                            return f"System: You cannot eat {name}. It smells rotten (Spoiled {meta.get('spoil_day')} {meta.get('spoil_time')})."

                        # 2. Consumption Logic
                        meta["meals"] -= 1
                        remaining = meta["meals"]
                        msg = ""
                        if remaining <= 0:
                            # Finished
                            items.pop(i)
                            msg = f"(Ate the last of {name}. It is finished.)"
                        else:
                            # Edited in place
                            msg = f"(Ate a meal of {name}. {remaining} meals remaining.)"
                        
                        self.save_data(data)
                        return msg
                    
                    else:
                        # Fallback for old/simple food items (just remove 1 count)
                        return self.autonomous_remove(f"{name}|1")

        return f"System: Could not find food '{name}'."

    def autonomous_remove(self, raw_args):
        # Format: Item Name | Amount
        try:
            if "|" in raw_args:
                parts = [p.strip() for p in raw_args.split("|")]
                target_name = parts[0]
                amount = int(parts[1]) if len(parts) > 1 else 1
            else:
                target_name = raw_args.strip()
                amount = 1

            data = self.load_data()
            removed = False
            
            # Search through every category (Weapons, Potions, etc.)
            for cat, items in data.items():
                for i in range(len(items) - 1, -1, -1):
                    # NEW: Access by Key
                    if target_name.lower() in items[i]["name"].lower():
                        try:
                            curr = int(items[i]["amount"]) 
                            new_val = curr - amount
                            if new_val <= 0: items.pop(i)
                            else: items[i]["amount"] = str(new_val)
                            removed = True
                        except:
                            items.pop(i)
                            removed = True
                        if removed: break
                if removed: break
            
            if removed:
                self.save_data(data)
                return f"(Lost {amount}x {target_name})."
            else:
                return f"System: Could not find {target_name}."

        except Exception as e:
            return f"System Error: {e}"
        
    def _make_plural(self, word):
        """Simple logic to pluralize headers."""
        lower = word.lower()
        # Exceptions that shouldn't change
        if lower in ["currency", "armor", "equipment", "goods", "information", "food"]:
            return word
        if lower.endswith("y"):
            return word[:-1] + "ies"
        if lower.endswith("s"):
            return word
        return word + "s"