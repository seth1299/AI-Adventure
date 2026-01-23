import customtkinter as ctk
import json
import os
from tabulate import tabulate

# --- Configuration (Must match main.py) ---
ctk.set_appearance_mode("Dark")

INVENTORY_FILE = "inventory.json"

INVENTORY_SCHEMA = {
    "Backpack": ["Name", "Description", "Amount"],
    "Weapons":  ["Name", "Range", "To-Hit", "Damage", "Ammo"],
    "Currency": ["Coin Type", "Description", "Amount"],
    "Clothes":  ["Body Part", "Equipment Name"]
}

AMMO_TYPES = ["None", "Arrow", "Bolt", "Bullet", "Stone"]

COIN_DESCRIPTIONS = {
    "Gold": "The largest denomination of coin. Used for large purchases.",
    "Silver": "The second-largest denomination. 10 Silver equals 1 Gold.",
    "Copper": "The lowest denomination. Used for common goods. 10 Copper equals 1 Silver."
}

class InventoryManager(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Inventory Manager (Standalone)")
        self.geometry("800x600")
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1) 
        self.grid_rowconfigure(1, weight=0)
        
        # 1. Read-Only Display
        self.display = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="none", state="disabled")
        self.display.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        # 2. Control Panel
        self.controls = ctk.CTkFrame(self)
        self.controls.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        
        self.btn_add = ctk.CTkButton(self.controls, text="+ Add Item", fg_color="green", command=self.open_add_dialog)
        self.btn_add.pack(side="left", padx=5, pady=5)
        
        self.btn_remove = ctk.CTkButton(self.controls, text="- Remove Item", fg_color="red", command=self.open_remove_dialog)
        self.btn_remove.pack(side="left", padx=5, pady=5)
        
        self.refresh_display()

    def load_data(self):
        if not os.path.exists(INVENTORY_FILE):
            return {}
        try:
            with open(INVENTORY_FILE, "r") as f:
                return json.load(f)
        except:
            return {}

    def save_data(self, data):
        with open(INVENTORY_FILE, "w") as f:
            json.dump(data, f, indent=4)
        self.refresh_display()

    def refresh_display(self):
        data = self.load_data()
        full_text = ""
        
        for category, items in data.items():
            if items:
                headers = INVENTORY_SCHEMA.get(category, [])
                full_text += f"\n{category}\n"
                full_text += tabulate(items, headers, tablefmt="rounded_grid")
                full_text += "\n"
        
        self.display.configure(state="normal")
        self.display.delete("0.0", "end")
        self.display.insert("0.0", full_text)
        self.display.configure(state="disabled")

    def open_add_dialog(self):
        # (This is identical to the one in main.py)
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add Item")
        dialog.geometry("450x600")
        dialog.attributes("-topmost", True)
        
        ctk.CTkLabel(dialog, text="Category:").pack(pady=5)
        cat_var = ctk.StringVar(value="Backpack")
        cat_dropdown = ctk.CTkOptionMenu(dialog, variable=cat_var, values=list(INVENTORY_SCHEMA.keys()))
        cat_dropdown.pack(pady=5)

        fields_frame = ctk.CTkFrame(dialog)
        fields_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        error_label = ctk.CTkLabel(dialog, text="", text_color="red")
        error_label.pack(pady=5)

        self.value_getters = {} 

        def update_fields(choice):
            for widget in fields_frame.winfo_children():
                widget.destroy()
            self.value_getters.clear()
            error_label.configure(text="")
            
            headers = INVENTORY_SCHEMA.get(choice, [])
            
            for h in headers:
                if choice == "Currency" and h == "Description": continue

                ctk.CTkLabel(fields_frame, text=h).pack(anchor="w")

                if choice == "Currency" and h == "Coin Type":
                    coin_var = ctk.StringVar(value="Gold")
                    cmb = ctk.CTkOptionMenu(fields_frame, variable=coin_var, values=["Gold", "Silver", "Copper"])
                    cmb.pack(fill="x", pady=(0, 10))
                    self.value_getters[h] = lambda v=coin_var: v.get()

                elif choice == "Weapons" and h == "Damage":
                    dmg_frame = ctk.CTkFrame(fields_frame, fg_color="transparent")
                    dmg_frame.pack(fill="x", pady=(0, 10))
                    num_entry = ctk.CTkEntry(dmg_frame, width=50, placeholder_text="1")
                    num_entry.pack(side="left", padx=(0, 5))
                    ctk.CTkLabel(dmg_frame, text="d").pack(side="left")
                    die_var = ctk.StringVar(value="6")
                    die_menu = ctk.CTkOptionMenu(dmg_frame, variable=die_var, values=["4", "6", "8", "10", "12"], width=70)
                    die_menu.pack(side="left", padx=(5, 0))
                    
                    def get_damage_str(e=num_entry, d=die_var):
                        val = e.get().strip()
                        if not val: return "" 
                        return f"{val}d{d.get()}"
                    self.value_getters[h] = get_damage_str

                elif choice == "Weapons" and h == "Ammo":
                    ammo_var = ctk.StringVar(value="None")
                    ammo_menu = ctk.CTkOptionMenu(fields_frame, variable=ammo_var, values=AMMO_TYPES)
                    ammo_menu.pack(fill="x", pady=(0, 10))
                    self.value_getters[h] = lambda v=ammo_var: v.get()

                else:
                    entry = ctk.CTkEntry(fields_frame)
                    entry.pack(fill="x", pady=(0, 10))
                    self.value_getters[h] = lambda e=entry: e.get()

        cat_dropdown.configure(command=update_fields)
        update_fields("Backpack") 

        def validate_and_submit():
            category = cat_var.get()
            headers = INVENTORY_SCHEMA.get(category, [])
            row_data = []
            
            try:
                for h in headers:
                    if category == "Currency" and h == "Description":
                        coin_type = self.value_getters["Coin Type"]()
                        row_data.append(COIN_DESCRIPTIONS.get(coin_type, "Unknown Coin"))
                        continue

                    raw_val = self.value_getters[h]()
                    if not raw_val or raw_val.strip() == "":
                        raise ValueError(f"'{h}' cannot be empty.")

                    if h == "Amount":
                        if not raw_val.isdigit() or int(raw_val) <= 0:
                            raise ValueError(f"Amount must be a positive integer.")
                    
                    if category == "Weapons":
                        if h == "Range":
                            if not raw_val.isdigit() or int(raw_val) < 5:
                                raise ValueError("Range must be an integer >= 5.")
                        if h == "To-Hit":
                            try: int(raw_val)
                            except: raise ValueError("To-Hit must be an integer.")
                        if h == "Damage":
                            parts = raw_val.split('d')
                            if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) <= 0:
                                raise ValueError("Invalid damage.")

                    row_data.append(raw_val)

                data = self.load_data()
                if category not in data: data[category] = []
                data[category].append(row_data)
                
                self.save_data(data)
                dialog.destroy()

            except ValueError as ve:
                error_label.configure(text=str(ve))
            except Exception as e:
                error_label.configure(text=f"Error: {str(e)}")

        ctk.CTkButton(dialog, text="Save", command=validate_and_submit).pack(pady=10)

    # --- UPDATED REMOVE DIALOG WITH DROPDOWN ---
    def open_remove_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Remove Item")
        dialog.geometry("350x250")
        dialog.attributes("-topmost", True)

        # 1. Flatten inventory into a list of strings for the dropdown
        # Format: "Item Name (Category)"
        data = self.load_data()
        item_list = []
        # Mapping to help us find the item later: "ItemName (Category)" -> (Category, Index, ActualName)
        item_map = {} 

        for cat, rows in data.items():
            for idx, row in enumerate(rows):
                name = row[0] # Name is always index 0
                display_str = f"{name} ({cat})"
                item_list.append(display_str)
                item_map[display_str] = (cat, idx, name)

        if not item_list:
            ctk.CTkLabel(dialog, text="Inventory is empty.").pack(pady=20)
            return

        ctk.CTkLabel(dialog, text="Select Item:").pack(pady=5)
        
        # Dropdown
        selected_item_var = ctk.StringVar(value=item_list[0])
        dropdown = ctk.CTkOptionMenu(dialog, variable=selected_item_var, values=item_list)
        dropdown.pack(pady=5)

        ctk.CTkLabel(dialog, text="Amount to remove (0 = All):").pack(pady=5)
        amount_entry = ctk.CTkEntry(dialog)
        amount_entry.insert(0, "1")
        amount_entry.pack(pady=5)

        def submit_remove():
            selection = selected_item_var.get()
            if selection not in item_map: return

            cat, idx, name = item_map[selection]
            
            try:
                amount_to_remove = int(amount_entry.get())
            except:
                amount_to_remove = 1

            # Reload data fresh in case it changed
            curr_data = self.load_data()
            items = curr_data.get(cat, [])
            
            # Find the item again by index (safest) or name
            # Since lists shift when you delete, we need to be careful.
            # However, since this dialog blocks interaction, index *should* be safe 
            # UNLESS you open two remove dialogs at once. 
            # Safer to search by name again to be robust.
            
            target_idx = -1
            for i, row in enumerate(items):
                if row[0] == name:
                    target_idx = i
                    break
            
            if target_idx != -1:
                item_row = items[target_idx]
                headers = INVENTORY_SCHEMA.get(cat, [])
                
                if "Amount" in headers:
                    amt_idx = headers.index("Amount")
                    try:
                        current_amt = int(item_row[amt_idx])
                        if amount_to_remove == 0:
                            new_amt = 0 # Trigger full delete
                        else:
                            new_amt = current_amt - amount_to_remove
                        
                        if new_amt <= 0:
                            items.pop(target_idx)
                        else:
                            item_row[amt_idx] = str(new_amt)
                    except:
                        items.pop(target_idx) # If amount is corrupt, just delete
                else:
                    # No amount column (e.g. Clothes), just delete
                    items.pop(target_idx)

                self.save_data(curr_data)
                dialog.destroy()

        ctk.CTkButton(dialog, text="Remove", fg_color="red", command=submit_remove).pack(pady=10)

if __name__ == "__main__":
    app = InventoryManager()
    app.mainloop()