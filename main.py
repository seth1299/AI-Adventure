from google import genai
from google.genai import types
import threading
import json
import os
import tkinter as tk
import customtkinter as ctk
import random
import re
import markdown
from tkhtmlview import HTMLLabel
from dotenv import load_dotenv
from tabulate import tabulate

# Build the project
# pyinstaller --noconsole --onefile --add-data "game_icon.ico;." --icon=game_icon.ico --name "Text Adventure" main.py

# --- Configuration ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-2.5-flash" 

client = genai.Client(api_key=GEMINI_API_KEY)

SAVE_FILE = "savegame.json"
RULES_FILE = "rules.md"
INVENTORY_FILE = "Inventory.md"

DEFAULT_RULES = (
    "You are a Dungeon Master for a text-based RPG.\n"
    "1. Describe the environment vividly but concisely.\n"
    "2. Output [[ROLL: SkillName]] for checks.\n"
)

INVENTORY_SCHEMA = {
    "Backpack": ["Name", "Description", "Amount"],
    "Weapons":  ["Name", "Range", "To-Hit", "Damage", "Ammo"],
    "Currency": ["Coin Type", "Description", "Amount"],
    "Clothes":  ["Body Part", "Equipment Name"]
}

AMMO_TYPES = ["None", "Arrow", "Bolt", "Dart", "Stone"]

COIN_DESCRIPTIONS = {
    "Gold": "The largest denomination of coin. Used for large purchases.",
    "Silver": "The second-largest denomination. 10 Silver equals 1 Gold.",
    "Copper": "The lowest denomination. Used for common goods. 10 Copper equals 1 Silver."
}

class MarkdownEditorTab(ctk.CTkFrame):
    """A Frame that holds both a raw Textbox and an HTML Preview."""
    def __init__(self, parent, default_text="# New Tab\n"):
        super().__init__(parent)
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1) # Row 1 is the content
        
        # --- Toolbar ---
        self.toolbar = ctk.CTkFrame(self, height=30)
        self.toolbar.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        
        self.mode_btn = ctk.CTkButton(self.toolbar, text="👁️ Preview", width=80, height=24, command=self.toggle_view)
        self.mode_btn.pack(side="right", padx=5)

        # --- Raw Editor (Visible by default) ---
        self.editor = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="word")
        self.editor.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.editor.insert("0.0", default_text)
        
        # --- HTML Preview (Hidden by default) ---
        self.preview_frame = ctk.CTkFrame(self, fg_color="transparent")
        
        # We set the background match the dark theme, but we also need inline HTML styles for text
        self.html_view = HTMLLabel(
            self.preview_frame, 
            html="<h1>Preview</h1>", 
            background="#2b2b2b", 
            foreground="#e0e0e0"
        )
        self.html_view.pack(expand=True, fill="both")

        self.is_preview_active = False

    def get_text(self):
        """Returns the raw markdown text."""
        return self.editor.get("0.0", "end")
    
    def get_inventory_text(self):
        """
        Generates a beautiful ASCII table for the inventory.
        """
        # 1. Define your data (You would normally load this from your JSON or class)
        headers = ["Item Name", "Description", "Amount"]
        data = [
            ["Arrow", "A basic arrow used as ammunition.", "20"],
            ["Backpack", "A nice leather backpack.", "1"],
            ["Torch", "A standard torch.", "10"],
            ["Bone Whistle", "An odd whistle made out of bone.", "1"]
        ]

        # 2. Generate the table
        # "github" format looks like standard Markdown
        # "presto" or "grid" looks like a cool RPG menu
        table_str = tabulate(data, headers, tablefmt="grid")
        
        return table_str

    def set_text(self, text):
        self.editor.delete("0.0", "end")
        self.editor.insert("0.0", text)

    def toggle_view(self):
        if not self.is_preview_active:
             # Just show the text in a monospaced font!
             formatted_table = self.get_inventory_text()
             
             self.editor.grid_forget()
             
             # Create a simple text box for the preview
             self.preview_box = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="none")
             self.preview_box.insert("0.0", formatted_table)
             self.preview_box.configure(state="disabled") # Read-only
             self.preview_box.grid(row=1, column=0, sticky="nsew")
             
             self.is_preview_active = True

class InventoryTab(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1) 
        self.grid_rowconfigure(1, weight=0)
        
        # 1. Read-Only Display
        self.display = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="none", state="disabled")
        self.display.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # 2. Control Panel
        self.controls = ctk.CTkFrame(self)
        self.controls.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        
        self.btn_add = ctk.CTkButton(self.controls, text="➕ Add Item", fg_color="green", command=self.open_add_dialog)
        self.btn_add.pack(side="left", padx=5, pady=5)
        
        self.btn_remove = ctk.CTkButton(self.controls, text="➖ Remove Item", fg_color="red", command=self.open_remove_dialog)
        self.btn_remove.pack(side="left", padx=5, pady=5)

        self.filename = "inventory.json"
        self.refresh_display()

    def get_text(self):
        return self.display.get("0.0", "end")

    def load_data(self):
        if not os.path.exists(self.filename):
            return {}
        try:
            with open(self.filename, "r") as f:
                return json.load(f)
        except:
            return {}

    def save_data(self, data):
        with open(self.filename, "w") as f:
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
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add Item")
        dialog.geometry("450x600")
        dialog.attributes("-topmost", True)
        
        # --- Category Selector ---
        ctk.CTkLabel(dialog, text="Category:").pack(pady=5)
        cat_var = ctk.StringVar(value="Backpack")
        cat_dropdown = ctk.CTkOptionMenu(dialog, variable=cat_var, values=list(INVENTORY_SCHEMA.keys()))
        cat_dropdown.pack(pady=5)

        # Container for dynamic fields
        fields_frame = ctk.CTkFrame(dialog)
        fields_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Error Label
        error_label = ctk.CTkLabel(dialog, text="", text_color="red")
        error_label.pack(pady=5)

        # Dictionary to store functions that retrieve values from the generated widgets
        # Format: { "HeaderName": lambda: widget.get() }
        self.value_getters = {} 

        def update_fields(choice):
            # 1. Clear old fields
            for widget in fields_frame.winfo_children():
                widget.destroy()
            self.value_getters.clear()
            error_label.configure(text="")
            
            headers = INVENTORY_SCHEMA.get(choice, [])
            
            for h in headers:
                # --- Skip "Description" for Currency (Auto-filled) ---
                if choice == "Currency" and h == "Description":
                    continue

                ctk.CTkLabel(fields_frame, text=h).pack(anchor="w")

                # --- SPECIAL WIDGET: CURRENCY TYPE ---
                if choice == "Currency" and h == "Coin Type":
                    coin_var = ctk.StringVar(value="Gold")
                    cmb = ctk.CTkOptionMenu(fields_frame, variable=coin_var, values=["Gold", "Silver", "Copper"])
                    cmb.pack(fill="x", pady=(0, 10))
                    self.value_getters[h] = lambda v=coin_var: v.get()

                # --- SPECIAL WIDGET: DAMAGE (Composite) ---
                elif choice == "Weapons" and h == "Damage":
                    dmg_frame = ctk.CTkFrame(fields_frame, fg_color="transparent")
                    dmg_frame.pack(fill="x", pady=(0, 10))
                    
                    # Number of dice
                    num_entry = ctk.CTkEntry(dmg_frame, width=50, placeholder_text="1")
                    num_entry.pack(side="left", padx=(0, 5))
                    
                    lbl_d = ctk.CTkLabel(dmg_frame, text="d")
                    lbl_d.pack(side="left")
                    
                    # Die Type
                    die_var = ctk.StringVar(value="6")
                    die_menu = ctk.CTkOptionMenu(dmg_frame, variable=die_var, values=["4", "6", "8", "10", "12"], width=70)
                    die_menu.pack(side="left", padx=(5, 0))
                    
                    # Getter combines them: "2" + "d" + "6" -> "2d6"
                    def get_damage_str(e=num_entry, d=die_var):
                        val = e.get().strip()
                        if not val: return "" # validation will catch empty
                        return f"{val}d{d.get()}"
                        
                    self.value_getters[h] = get_damage_str

                # --- SPECIAL WIDGET: AMMO ---
                elif choice == "Weapons" and h == "Ammo":
                    ammo_var = ctk.StringVar(value="None")
                    ammo_menu = ctk.CTkOptionMenu(fields_frame, variable=ammo_var, values=AMMO_TYPES)
                    ammo_menu.pack(fill="x", pady=(0, 10))
                    self.value_getters[h] = lambda v=ammo_var: v.get()

                # --- STANDARD ENTRY (With Validation Hooks) ---
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
            
            error_msg = None

            try:
                for h in headers:
                    # 1. Handle Auto-Generated Description for Currency
                    if category == "Currency" and h == "Description":
                        coin_type = self.value_getters["Coin Type"]()
                        row_data.append(COIN_DESCRIPTIONS.get(coin_type, "Unknown Coin"))
                        continue

                    # 2. Get Raw Value
                    raw_val = self.value_getters[h]()
                    
                    # 3. Check Not Empty
                    if not raw_val or raw_val.strip() == "":
                        raise ValueError(f"'{h}' cannot be empty.")

                    # 4. Specific Validations
                    if h == "Amount":
                        if not raw_val.isdigit() or int(raw_val) <= 0:
                            raise ValueError(f"Amount must be a positive integer (got '{raw_val}').")
                    
                    if category == "Weapons":
                        if h == "Range":
                            if not raw_val.isdigit() or int(raw_val) < 5:
                                raise ValueError("Range must be an integer >= 5.")
                        
                        if h == "To-Hit":
                            # Allow negative numbers (e.g. -1)
                            # isdigit() fails on negative, so we try int() casting
                            try:
                                int(raw_val)
                            except:
                                raise ValueError("To-Hit must be an integer.")

                        if h == "Damage":
                            # raw_val comes in as "XdY" e.g. "2d6"
                            parts = raw_val.split('d')
                            if len(parts) != 2: raise ValueError("Invalid damage format.")
                            dice_count = parts[0]
                            if not dice_count.isdigit() or int(dice_count) <= 0:
                                raise ValueError("Damage dice count must be > 0.")

                    row_data.append(raw_val)

                # If we get here, all validations passed
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

class GameApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("AI RPG Adventure")
        self.geometry("1000x700")
        ctk.set_appearance_mode("Dark")
        
        try:
            self.iconbitmap("game_icon.ico")
        except:
            pass

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.tabs = ["Story", "Inventory", "Quests", "Journal", "Skills", "Character", "World"]
        self.notebook_widgets = {} # Stores our MarkdownEditorTab instances

        for tab_name in self.tabs:
            self.tab_view.add(tab_name)
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

            if tab_name == "Story":
                # Story is unique (Chat history)
                self.setup_story_tab(frame)
            elif tab_name == "Inventory":
                # --- CHANGE HERE ---
                # Use the new specialized InventoryTab
                inv_editor = InventoryTab(frame)
                inv_editor.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = inv_editor 
                # Note: InventoryTab doesn't have .get_text(), 
                # so if your AI query uses .get_text(), you might need a small adapter.
            else:
                # All other tabs use our new MarkdownEditor
                editor = MarkdownEditorTab(frame, default_text=f"# {tab_name}\n")
                editor.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = editor

        # Save/Load
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.conversation_history = "" 
        self.load_game()

    def setup_story_tab(self, frame):
        self.chat_display = ctk.CTkTextbox(frame, state="disabled", wrap="word", font=("Consolas", 14))
        self.chat_display.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")

        self.input_entry = ctk.CTkEntry(frame, placeholder_text="What do you do?")
        self.input_entry.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="ew")
        self.input_entry.bind("<Return>", self.send_message)

        self.send_btn = ctk.CTkButton(frame, text="Act", command=self.send_message)
        self.send_btn.grid(row=1, column=1, padx=10, pady=(5, 10))
        
        self.status_label = ctk.CTkLabel(frame, text="", text_color="gray")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=10)

    def load_rules(self):
        if os.path.exists(RULES_FILE):
            try:
                with open(RULES_FILE, "r", encoding="utf-8") as f:
                    return f.read()
            except:
                return DEFAULT_RULES
        return DEFAULT_RULES

    def print_to_story(self, text, sender="System"):
        self.chat_display.configure(state="normal")
        if sender == "Player":
            self.chat_display.insert("end", f"\n> {text}\n")
        elif sender == "GM":
            self.chat_display.insert("end", f"\n{text}\n")
        else:
            self.chat_display.insert("end", f"\n[{text}]\n")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def toggle_controls(self, enable, status_text=""):
        state = "normal" if enable else "disabled"
        self.after(0, lambda: self.input_entry.configure(state=state))
        self.after(0, lambda: self.send_btn.configure(state=state))
        self.after(0, lambda: self.status_label.configure(text=status_text))
        
        if enable:
            self.after(0, lambda: self.input_entry.focus()) # Fix cursor focus

    def send_message(self, event=None):
        user_text = self.input_entry.get()
        if not user_text.strip(): return
        
        self.toggle_controls(enable=False, status_text="GM is thinking...") 
        self.print_to_story(user_text, sender="Player")
        self.input_entry.delete(0, "end")

        # Gather Context from our new Editor classes
        context_data = ""
        for name, widget in self.notebook_widgets.items():
            # If the user left it in "Preview" mode, we still grab the raw text safely
            context_data += f"\n[{name.upper()}]:\n{widget.get_text().strip()}\n"

        recent_history = self.conversation_history[-3000:] if len(self.conversation_history) > 3000 else self.conversation_history

        full_prompt = f"{context_data}\nHistory:\n{recent_history}\nPlayer: {user_text}\nGM:"

        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()

    def perform_skill_check(self, skill_name):
        # 1. Clean up the skill name (e.g., remove parens if "Stealth (Dex)" is passed)
        clean_name = skill_name.split('(')[0].strip()
        safe_skill = re.escape(clean_name)
        
        # 2. Roll the D20
        die_roll = random.randint(1, 20)
        
        # 3. Get the Raw Text from the Skills Tab
        # We use .get_text() because we are using the new MarkdownEditorTab class
        skills_text = self.notebook_widgets["Skills"].get_text()
        
        bonus = 0

        # --- REGEX EXPLANATION for your Skills.md ---
        # We are looking for a table row that looks like this:
        # | Skill Name | Description | Level | ...
        #
        # 1. \|\s*{safe_skill}\s*\|  -> Match the Skill Name column
        # 2. [^|]*\|                 -> Skip the entire Description column (everything until the next pipe)
        # 3. \s*(\d+)                -> Capture the Digits in the Level column
        
        pattern = rf"\|\s*{safe_skill}\s*\|[^|]*\|\s*(\d+)"
        
        match = re.search(pattern, skills_text, re.IGNORECASE)
        
        if match:
            try:
                bonus = int(match.group(1))
            except ValueError:
                bonus = 0
        else:
            pass
            # Fallback: If we can't find it in the table, check if the AI hallucinated 
            # a skill not on the sheet. We'll default to 0 bonus.
            #print(f"System Warning: Could not find skill '{clean_name}' in Skills tab.")

        total = die_roll + bonus
        
        # Log to the story
        self.print_to_story(f"🎲 Rolling {clean_name}: {die_roll} + ({bonus}) = {total}", sender="System")
        
        return total

    def query_ai(self, prompt, user_text, recursion_depth=0):
        current_rules = self.load_rules()
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=current_rules,
                    temperature=0.7
                )
            )
            ai_text = response.text
            if not ai_text: raise ValueError("Empty response")

            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
            
            if roll_match and recursion_depth < 2:
                skill = roll_match.group(1).strip()
                result = self.perform_skill_check(skill)
                follow_up = f"{prompt}\nGM: {ai_text}\n[System: Player rolled {result} for {skill}.]"
                self.query_ai(follow_up, user_text, recursion_depth + 1)
            else:
                final_text = re.sub(r"\[\[ROLL:.*?\]\]", "", ai_text).strip() if recursion_depth >= 2 else ai_text
                self.print_to_story(final_text, sender="GM")
                self.conversation_history += f"Player: {user_text}\nGM: {final_text}\n"

        except Exception as e:
            self.print_to_story(f"AI Error: {e}", sender="System")
        finally:
            self.toggle_controls(enable=True)

    def save_game(self):
        # Save individual markdown files
        for name, widget in self.notebook_widgets.items():
            try:
                with open(f"{name}.md", "w", encoding="utf-8") as f:
                    f.write(widget.get_text())
            except Exception as e:
                print(f"Error saving {name}: {e}")

        # Save history
        history_list = [line for line in self.conversation_history.split("\n") if line.strip()]
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump({"Chat History": history_list}, f, indent=4)
        print("Game Saved.")

    def load_game(self):
        # Load markdown files
        for name, widget in self.notebook_widgets.items():
            if os.path.exists(f"{name}.md"):
                try:
                    with open(f"{name}.md", "r", encoding="utf-8") as f:
                        widget.set_text(f.read())
                except Exception as e:
                    print(f"Error loading {name}: {e}")

        # Load history
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    hist = data.get("Chat History", [])
                    self.conversation_history = "\n".join(hist) if isinstance(hist, list) else hist
                self.print_to_story("System: Game Loaded.", sender="System")
                
                # Generate Recap logic
                recent = self.conversation_history[-3000:]
                threading.Thread(target=self.generate_recap, args=(recent,), daemon=True).start()
            except Exception as e:
                self.print_to_story(f"Save Corrupt: {e}")
        else:
            self.print_to_story("Welcome. What is your name?", sender="GM")

    def generate_recap(self, history):
        self.toggle_controls(False, "Recapping...")
        try:
            prompt = f"History:\n{history}\nSummarize situation in 2 sentences. Ask 'What do you do?'"
            resp = client.models.generate_content(
                model=MODEL, 
                contents=prompt, 
                config=types.GenerateContentConfig(system_instruction=self.load_rules())
            )
            self.print_to_story(f"📝 RECAP: {resp.text}", sender="GM")
        except:
            pass
        finally:
            self.toggle_controls(True)

    def on_close(self):
        self.save_game()
        self.destroy()

if __name__ == "__main__":
    app = GameApp()
    app.mainloop()