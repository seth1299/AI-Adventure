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
        self.grid_rowconfigure(0, weight=1) # Text area
        self.grid_rowconfigure(1, weight=0) # Button area
        
        # 1. Read-Only Display (The Table)
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
                full_text += f"\n## {category}\n"
                full_text += tabulate(items, headers, tablefmt="grid")
                full_text += "\n"
        
        self.display.configure(state="normal")
        self.display.delete("0.0", "end")
        self.display.insert("0.0", full_text)
        self.display.configure(state="disabled")

    def open_add_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add Item")
        dialog.geometry("400x500")
        dialog.attributes("-topmost", True)
        
        # Category Selector
        ctk.CTkLabel(dialog, text="Category:").pack(pady=5)
        cat_var = ctk.StringVar(value="Backpack")
        cat_dropdown = ctk.CTkOptionMenu(dialog, variable=cat_var, values=list(INVENTORY_SCHEMA.keys()))
        cat_dropdown.pack(pady=5)

        # Container for dynamic fields
        fields_frame = ctk.CTkFrame(dialog)
        fields_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.entries = [] # Store entry widgets to retrieve data later

        def update_fields(choice):
            # Clear old fields
            for widget in fields_frame.winfo_children():
                widget.destroy()
            self.entries.clear()
            
            # Create new fields based on Schema
            headers = INVENTORY_SCHEMA.get(choice, [])
            for h in headers:
                ctk.CTkLabel(fields_frame, text=h).pack(anchor="w")
                entry = ctk.CTkEntry(fields_frame)
                entry.pack(fill="x", pady=(0, 10))
                self.entries.append(entry)

        cat_dropdown.configure(command=update_fields)
        update_fields("Backpack") # Initial load

        def submit():
            category = cat_var.get()
            new_row = [e.get() for e in self.entries]
            
            data = self.load_data()
            if category not in data: data[category] = []
            
            data[category].append(new_row)
            self.save_data(data)
            dialog.destroy()

        ctk.CTkButton(dialog, text="Save", command=submit).pack(pady=10)

    def open_remove_dialog(self):
        # A simpler dialog: Ask for Name and Amount
        dialog = ctk.CTkToplevel(self)
        dialog.title("Remove Item")
        dialog.geometry("300x250")
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(dialog, text="Item Name to Remove:").pack(pady=5)
        name_entry = ctk.CTkEntry(dialog)
        name_entry.pack(pady=5)

        ctk.CTkLabel(dialog, text="Amount to remove (0 = All):").pack(pady=5)
        amount_entry = ctk.CTkEntry(dialog)
        amount_entry.insert(0, "1")
        amount_entry.pack(pady=5)

        def submit_remove():
            target_name = name_entry.get().lower()
            try:
                amount_to_remove = int(amount_entry.get())
            except:
                amount_to_remove = 1

            data = self.load_data()
            found = False
            
            for category, items in data.items():
                # We iterate backwards so we can safely delete from the list
                for i in range(len(items) - 1, -1, -1):
                    item_row = items[i]
                    # Assuming Index 0 is always "Name"
                    if target_name in item_row[0].lower():
                        found = True
                        
                        # Check if this item HAS an amount column? 
                        # We look at schema. If 'Amount' is in headers.
                        headers = INVENTORY_SCHEMA.get(category, [])
                        if "Amount" in headers:
                            amt_idx = headers.index("Amount")
                            try:
                                current_amt = int(item_row[amt_idx])
                                new_amt = current_amt - amount_to_remove
                                
                                if new_amt <= 0:
                                    items.pop(i) # Remove completely
                                else:
                                    item_row[amt_idx] = str(new_amt) # Update count
                            except:
                                # If amount isn't a number, just delete it
                                items.pop(i)
                        else:
                            # If item has no amount logic (like clothes), just delete
                            items.pop(i)
                        break # Stop searching this category if found
                if found: break
            
            self.save_data(data)
            dialog.destroy()

        ctk.CTkButton(dialog, text="Remove", fg_color="red", command=submit_remove).pack(pady=10)
        
    def get_text(self):
        """Returns the text currently displayed in the textbox for the AI to read."""
        return self.display.get("0.0", "end")

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