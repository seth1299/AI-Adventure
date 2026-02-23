# ui/recipes_tab.py
import customtkinter as ctk
import pandas as pd
import os, shutil, sys
import logging
import json
from rapidfuzz import process, fuzz
import re

class RecipesTab(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.base_path = None
        self.csv_path = None
        
        # Headers matching your CSV structure
        self.columns = [
            "recipe_name", 
            "ingredient_1", "ingredient_1_amount",
            "ingredient_2", "ingredient_2_amount",
            "ingredient_3", "ingredient_3_amount",
            "value"
        ]

        # UI Header
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(self.header_frame, text="KNOWN RECIPES", font=("Consolas", 20, "bold")).pack(pady=10)
        
        self.crafting_summary_label = ctk.CTkLabel(
            self.header_frame, 
            text="Analysis: ...", 
            font=("Consolas", 12), 
            text_color="#A8D0E6",  # Light blue for info
            justify="left"
        )
        self.crafting_summary_label.pack(pady=5)

        # Scrollable Area
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)

    def set_base_path(self, path):
        """Called by main.py when a game is loaded."""
        self.base_path = path
        self.csv_path = os.path.join(self.base_path, "recipes.csv")
        self.refresh_display()

    def refresh_display(self):
        """Aliases load_recipes for clarity."""
        self.load_recipes()
        
    def _get_inventory_map(self):
        """Reads inventory.json and flattens it into { 'name_lower': count }."""
        if not self.base_path: return {}
        inv_path = os.path.join(self.base_path, "inventory.json")
        if not os.path.exists(inv_path): return {}
        
        try:
            with open(inv_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            counts = {}
            for cat, items in data.items():
                for item in items:
                    name = ""
                    amt = 0
                    
                    # Handle Dict vs List format safely
                    if isinstance(item, dict):
                        name = item.get("name", "").strip().lower()
                        try: amt = int(item.get("amount", 0))
                        except: amt = 1
                    elif isinstance(item, list) and len(item) > 2:
                        name = item[0].strip().lower()
                        try: amt = int(item[2])
                        except: amt = 1
                    
                    if name:
                        counts[name] = counts.get(name, 0) + amt
            return counts
        except Exception as e:
            logging.error(f"Error reading inventory for recipes: {e}")
            return {}

    def load_recipes(self):
        # Clear list
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        if not self.csv_path: 
            self.crafting_summary_label.configure(text="No Save Loaded.")
            return

        # --- Logic: Copy Master File safely ---
        if not os.path.exists(self.csv_path):
            logging.info("Created empty .csv file.")
            df = pd.DataFrame(columns=self.columns)
            df.to_csv(self.csv_path, index=False)
            
        # -------------------------------------------------------------
        
        try:
            df = pd.read_csv(self.csv_path)
            # --- FIX: Strip whitespace from column headers ---
            df.columns = df.columns.str.strip()
            # -------------------------------------------------
            
            # --- [NEW] Calculate Craftable Amounts ---
            inventory = self._get_inventory_map()
            craftable_list = []
            
            for _, row in df.iterrows():
                r_name = row.get("recipe_name", "Unknown")
                
                # We track the "Max Limit" for this specific recipe
                # Start infinite, then clamp down based on each ingredient
                max_craft = float('inf') 
                limiting_item = "None"
                has_ingredients = False
                
                limits = [] # List of tuples: (max_possible_with_this_ing, ing_name)

                for i in range(1, 4):
                    ing_name = row.get(f"ingredient_{i}") or "UNKNOWN"
                    ing_req_raw = row.get(f"ingredient_{i}_amount") or 1
                    
                    # If this column has an ingredient
                    if pd.notna(ing_name) and str(ing_name).strip():
                        has_ingredients = True
                        ing_name_clean = str(ing_name).strip()
                        try: req = int(ing_req_raw)
                        except: req = 1
                        
                        # How many do we have?
                        # Using lower() to match the map we built
                        target_name = ing_name_clean.lower()
                        avail = inventory.get(ing_name_clean.lower(), 0)
                        
                        if avail == 0 and inventory:
                            # score_cutoff=80 prevents "Iron Ore" matching "Iron Sword"
                            # WRatio handles "Dandelion" vs "Dandelion Flower" nicely
                            match_result = process.extractOne(target_name, inventory.keys(), scorer=fuzz.WRatio, score_cutoff=80)
                            
                            if match_result:
                                # extractOne returns (match_key, score, index)
                                best_key = match_result[0]
                                score = match_result[1]
                                avail = inventory[best_key]
                                # Optional debug log to see what it matched
                                # logging.info(f"Fuzzy Matched: '{target_name}' -> '{best_key}' (Score: {score})")
                        
                        # Math: available // required
                        can_make_with_this = int(avail // req)
                        limits.append((can_make_with_this, ing_name_clean))
                
                if has_ingredients and limits:
                    # The ACTUAL limit is the lowest number in our list
                    limits.sort(key=lambda x: x[0]) 
                    max_craft = limits[0][0]
                    limiting_item = limits[0][1]
                    
                    if max_craft > 0:
                        craftable_list.append(f"• {r_name}: Can craft {max_craft} (Limited by {limiting_item})")
                
            # Update the Label
            if craftable_list:
                summary_text = "--- Craftable Now ---\n" + "\n".join(craftable_list)
                self.crafting_summary_label.configure(text=summary_text, text_color="#A8D0E6")
            else:
                self.crafting_summary_label.configure(text="--- No Craftable Recipes (Check Inventory) ---", text_color="gray")

            # -------------------------------------------------

            # Display each row
            for _, row in df.iterrows():
                self._create_recipe_card(row)
        except Exception as e:
            logging.error(f"Error loading recipes CSV: {e}")
            ctk.CTkLabel(self.scroll_frame, text=f"Error loading recipes: {e}").pack()
            
    def get_text(self):
        """Returns a string representation of all recipes for the AI to read."""
        if not self.csv_path or not os.path.exists(self.csv_path):
            return "No known recipes."
        
        try:
            df = pd.read_csv(self.csv_path)
            # --- FIX: Strip whitespace ---
            df.columns = df.columns.str.strip()
            
            if df.empty:
                return "No known recipes."
            
            text_output = []
            for _, row in df.iterrows():
                name = row.get("recipe_name", "Unknown")
                ingredients = []
                
                for i in range(1, 4):
                    ing_name = row.get(f"ingredient_{i}")
                    ing_amt = row.get(f"ingredient_{i}_amount")
                    
                    if pd.notna(ing_name) and str(ing_name).strip():
                        amt = int(ing_amt) if pd.notna(ing_amt) else 1
                        ingredients.append(f"{ing_name} (x{amt:.0f})")
                
                ing_str = ", ".join(ingredients)
                text_output.append(f"- {name}: {ing_str}")
            
            return "\n".join(text_output)
            
        except Exception as e:
            return f"Error reading recipes: {e}"

    def _create_recipe_card(self, row):
        card = ctk.CTkFrame(self.scroll_frame, fg_color=("gray85", "gray25"))
        card.pack(fill="x", pady=1, padx=1)
        
        # Left Side: Name and Value
        left_col = ctk.CTkFrame(card, fg_color="transparent")
        left_col.pack(side="left", padx=10, pady=5)
        
        name = str(row.get("recipe_name", "Unknown"))
        name = name.strip()
        
        # Helper to get value or N/A
        def get_val(key):
            val = row.get(key)
            # Check for NaN (Pandas uses float('nan') for empty cells)
            return val if pd.notna(val) else "N/A"
        
        def fmt_amount(raw):
            """Safely format ingredient amount (CSV may store it as str)."""
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                return "1"

            s = str(raw).strip()
            if not s or s.upper() in ("N/A", "NA", "NONE"):
                return "1"

            # Try direct numeric parse
            try:
                return str(int(float(s)))
            except Exception:
                pass

            # Fallback: pull first number out of strings like "3.8 ounces"
            match = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
            if match:
                try:
                    return str(int(float(match.group(0))))
                except Exception:
                    return match.group(0)

            return s

        # Safe getters using the stripped keys
        ingredient_1 = str(get_val("ingredient_1")).strip()
        ingredient_1_amount = get_val("ingredient_1_amount")
        ingredient_2 = str(get_val("ingredient_2")).strip()
        ingredient_2_amount = get_val("ingredient_2_amount")
        ingredient_3 = str(get_val("ingredient_3")).strip()
        ingredient_3_amount = get_val("ingredient_3_amount")
        val = str(get_val("value")).strip()
        
        ctk.CTkLabel(left_col, text=name, font=("Arial", 16, "bold"), anchor="w").pack(fill="x")
        
        # Only show ingredient if it is not N/A
        if ingredient_1 != "N/A":
            ctk.CTkLabel(left_col, text=f"{ingredient_1}: x{fmt_amount(ingredient_1_amount)}", font=("Arial", 12), text_color="gold", anchor="w").pack(fill="x")
        if ingredient_2 != "N/A":
            ctk.CTkLabel(left_col, text=f"{ingredient_2}: x{fmt_amount(ingredient_2_amount)}", font=("Arial", 12), text_color="gold", anchor="w").pack(fill="x")
        if ingredient_3 != "N/A":
            ctk.CTkLabel(left_col, text=f"{ingredient_3}: x{fmt_amount(ingredient_3_amount)}", font=("Arial", 12), text_color="gold", anchor="w").pack(fill="x")
            
        ctk.CTkLabel(left_col, text=f"Value: {val}", font=("Arial", 12), text_color="gold", anchor="w").pack(fill="x")

        # Right Side: Ingredients List (Clean Display)
        right_col = ctk.CTkFrame(card, fg_color="transparent")
        right_col.pack(side="right", padx=10, pady=5, fill="x", expand=True)

    def add_recipe_from_tag(self, tag_content: str):
        """
        Parses: "Name | Ing1: 5, Ing2: 2 | 50 Gold"
        """
        if self.csv_path is None:
            logging.error(f"Invalid csv path.")
            return f"Invalid csv path."
            
        try:
            parts = tag_content.split("|")
            if len(parts) < 3:
                return "System: Invalid Recipe Tag Format."

            r_name = parts[0].strip()
            ing_string = parts[1].strip()
            r_val = parts[2].strip()

            # 1. Parse Ingredients
            ing_list = []
            raw_ings = ing_string.split(",")
            for raw in raw_ings:
                if ":" in raw:
                    i_name, i_amt = raw.split(":", 1)
                    ing_list.append((i_name.strip(), i_amt.strip()))
                else:
                    ing_list.append((raw.strip(), "1"))

            # 2. Construct Row
            new_row = {
                "recipe_name": r_name,
                "value": r_val,
                "ingredient_1": "", "ingredient_1_amount": "",
                "ingredient_2": "", "ingredient_2_amount": "",
                "ingredient_3": "", "ingredient_3_amount": ""
            }

            for i, (name, amt) in enumerate(ing_list):
                if i < 3:
                    new_row[f"ingredient_{i+1}"] = name
                    new_row[f"ingredient_{i+1}_amount"] = amt

            # 3. Load, Append, Save
            if os.path.exists(self.csv_path):
                df = pd.read_csv(self.csv_path)
                # --- FIX: Strip whitespace ---
                df.columns = df.columns.str.strip()
            else:
                df = pd.DataFrame(columns=self.columns)

            if r_name in df['recipe_name'].values:
                return f"System: Recipe '{r_name}' already known."

            new_df = pd.DataFrame([new_row])
            df = pd.concat([df, new_df], ignore_index=True)
            
            df.to_csv(self.csv_path, index=False)
            
            self.refresh_display()
            return f"System: Learned recipe for {r_name}."

        except Exception as e:
            logging.error(f"Error adding recipe: {e}")
            return f"System: Error learning recipe ({e})"