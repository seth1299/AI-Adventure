import customtkinter as ctk
import os
import json
from tabulate import tabulate
from config import INVENTORY_SCHEMA, COIN_DESCRIPTIONS # Import from your config file

class InventoryTab(ctk.CTkFrame):
    """Displays Inventory.json using Tabulate. Hidden control logic."""
    def __init__(self, parent):
        super().__init__(parent)
        self.data_path = ""
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1) 
        
        # Read-Only Display
        self.display = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="none", state="disabled")
        self.display.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # Note: Buttons removed as requested. AI handles adds/removes.

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

    def refresh_display(self):
        data = self.load_data()
        full_text = "INVENTORY\n"
        
        for category, items in data.items():
            if items:
                headers = INVENTORY_SCHEMA.get(category, [])
                visible_items = [row[:len(headers)] for row in items]
                full_text += f"\n{category}\n"
                full_text += tabulate(visible_items, headers, tablefmt="simple_grid")
                full_text += "\n"
        
        self.display.configure(state="normal")
        self.display.delete("0.0", "end")
        self.display.insert("0.0", full_text)
        self._apply_styles(data.keys())
        self.display.configure(state="disabled")
        
    def _apply_styles(self, categories):
        """Searches for Markdown headers and applies visual tags."""
        # Access the underlying Tkinter text widget
        txt = self.display._textbox
        
        # 1. Define Styles (Tags)
        # H1: Gold, Large, Bold (For "# INVENTORY")
        txt.tag_config("h1", font=("Consolas", 24, "bold"), foreground="#FFD700", spacing3=10)
        # H2: White, Medium, Bold (For "## Backpack")
        txt.tag_config("h2", font=("Consolas", 18, "bold"), foreground="#FFFFFF", spacing3=5)

        # 2. Apply H1 Styles (Search for lines starting with "# ")
        start_pos = "1.0"
        pos = txt.search("INVENTORY", start_pos, stopindex="end")
        if pos:
            txt.tag_add("h1", pos, f"{pos} lineend")
        # 2. Apply H2 to Category Names
        for cat in categories:
            start_pos = "1.0"
            while True:
                # Search for the category name
                pos = txt.search(cat, start_pos, stopindex="end")
                if not pos: break
                
                # Validation: Ensure it's a Header line, not just the word appearing in a description
                # Check 1: Must be at the start of the line
                if txt.compare(pos, "!=", f"{pos} linestart"):
                    start_pos = f"{pos} + 1c"
                    continue
                
                # Check 2: The line must ONLY contain the category name (and whitespace)
                line_text = txt.get(pos, f"{pos} lineend").strip()
                if line_text == cat:
                    txt.tag_add("h2", pos, f"{pos} lineend")
                
                start_pos = f"{pos} + 1c"

    def autonomous_add(self, raw_args):
        try:
            if "|" in raw_args:
                parts = [p.strip() for p in raw_args.split("|")]
            else:
                parts = [p.strip() for p in raw_args.split(",")]

            if len(parts) < 2: return "Error: Data missing."

            category = parts[0].strip()
            # Normalize Category
            valid_cats = {k.lower(): k for k in INVENTORY_SCHEMA.keys()}
            real_cat = valid_cats.get(category.lower(), "Backpack")

            name = parts[1]
            desc = parts[2] if len(parts) > 2 else "Item"
            amount = parts[3] if len(parts) > 3 else "1"
            
            row_data = []

            if real_cat == "Backpack":
                row_data = [name, desc, amount]
            elif real_cat == "Currency":
                coin_type = name.capitalize()
                if coin_type not in ["Gold", "Silver", "Copper"]: coin_type = "Gold"
                auto_desc = COIN_DESCRIPTIONS.get(coin_type, "Coin")
                final_amt = parts[2] if len(parts) == 3 else amount
                row_data = [coin_type, auto_desc, final_amt]
            elif real_cat == "Weapons":
                # Fallback defaults if AI omits stats
                row_data = [name, "5 ft", "+0", "1d4", "None"] 
            else:
                row_data = [name, desc, amount]

            data = self.load_data()
            if real_cat not in data: data[real_cat] = []
            data[real_cat].append(row_data)
            self.save_data(data)
            
            return f"System: Added {amount}x {name} to {real_cat}."
        except Exception as e:
            return f"System: Failed to add item ({e})."

    def autonomous_remove(self, raw_args):
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
            
            for cat, items in data.items():
                for i in range(len(items) - 1, -1, -1):
                    if target_name.lower() in items[i][0].lower():
                        headers = INVENTORY_SCHEMA.get(cat, [])
                        if "Amount" in headers:
                            amt_idx = headers.index("Amount")
                            try:
                                curr = int(items[i][amt_idx])
                                new_val = curr - amount
                                if new_val <= 0:
                                    items.pop(i)
                                else:
                                    items[i][amt_idx] = str(new_val)
                                removed = True
                            except:
                                items.pop(i)
                                removed = True
                        else:
                            items.pop(i)
                            removed = True
                        if removed: break
                if removed: break
            
            if removed:
                self.save_data(data)
                return f"System: Removed {amount}x {target_name}."
            else:
                return f"System: Could not find {target_name}."
        except Exception as e:
            return f"System Error: {e}"