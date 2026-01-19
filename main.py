from google import genai
from google.genai import types
import threading
import json
import os
import tkinter as tk
import customtkinter as ctk
import random
import re
from dotenv import load_dotenv

# Build the project
# pyinstaller --noconsole --onefile --add-data "game_icon.ico;." --icon=game_icon.ico --name "Text Adventure" main.py

load_dotenv()

# --- Configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-2.0-flash" 

# Initialize the Client
client = genai.Client(api_key=GEMINI_API_KEY)

SAVE_FILE = "savegame.json"
RULES_FILE = "rules.md"  # New external rules file

# --- DEFAULT RULES (Fallback if file is missing) ---
DEFAULT_RULES = (
    "You are a Dungeon Master for a text-based RPG.\n"
    "1. Describe the environment vividly but concisely (2-3 paragraphs).\n"
    "2. DO NOT narrate the outcome of difficult actions (fighting, climbing, lying). Instead, output ONLY: [[ROLL: SkillName]].\n"
    "3. STOP generating immediately after outputting a [[ROLL]] tag. Wait for the user to provide the result.\n"
    "4. Manage the player's Inventory and Skills automatically based on the provided context."
)

class GameApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Window Setup
        self.title("AI RPG Adventure")
        self.geometry("900x600")
        
        try:
            self.iconbitmap("game_icon.ico")
        except Exception:
            pass
        
        ctk.set_appearance_mode("Dark")

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Tabs
        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.tabs = ["Story", "Inventory", "Quests", "Journal", "Skills", "Character", "World"]
        for tab in self.tabs:
            self.tab_view.add(tab)

        # --- STORY TAB ---
        self.story_frame = self.tab_view.tab("Story")
        self.story_frame.grid_columnconfigure(0, weight=1)
        self.story_frame.grid_rowconfigure(0, weight=1)

        # Chat History
        self.chat_display = ctk.CTkTextbox(self.story_frame, state="disabled", wrap="word", font=("Consolas", 14))
        self.chat_display.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")

        # Input Area
        self.input_entry = ctk.CTkEntry(self.story_frame, placeholder_text="What do you do?")
        self.input_entry.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="ew")
        self.input_entry.bind("<Return>", self.send_message)

        # Send Button
        self.send_btn = ctk.CTkButton(self.story_frame, text="Act", command=self.send_message)
        self.send_btn.grid(row=1, column=1, padx=10, pady=(5, 10))
        
        # STATUS LABEL
        self.status_label = ctk.CTkLabel(self.story_frame, text="", text_color="gray")
        self.status_label.grid(row=2, column=0, columnspan=3, sticky="w", padx=10)

        # --- OTHER TABS ---
        self.notebook_widgets = {} 
        for tab_name in self.tabs:
            if tab_name == "Story":
                continue
            
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)
            
            tb = ctk.CTkTextbox(frame, font=("Consolas", 12))
            tb.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
            tb.insert("0.0", f"# {tab_name} \n")
            self.notebook_widgets[tab_name] = tb
            tb.bind("<KeyRelease>", lambda event, w=tb: self.apply_markdown_style(w))

        # --- Save/Load System ---
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.conversation_history = "" 
        self.load_game()

    def load_rules(self):
        """Loads rules from the external file or uses default."""
        if os.path.exists(RULES_FILE):
            try:
                with open(RULES_FILE, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return DEFAULT_RULES
        return DEFAULT_RULES

    def print_to_story(self, text, sender="System"):
        self.chat_display.configure(state="normal")
        if sender == "Player":
            self.chat_display.insert("end", f"\n> {text}\n", "player_tag")
        elif sender == "GM":
            self.chat_display.insert("end", f"\n{text}\n")
        else:
            self.chat_display.insert("end", f"\n[{text}]\n")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")
        
    def apply_markdown_style(self, widget):
        # (Same as before - omitted for brevity, keep your existing code here)
        tk_text = widget._textbox
        base_font = ctk.CTkFont(family="Consolas", size=12)
        h1_font = ctk.CTkFont(family="Consolas", size=20, weight="bold")
        h2_font = ctk.CTkFont(family="Consolas", size=16, weight="bold")
        bold_font = ctk.CTkFont(family="Consolas", size=12, weight="bold")
        
        tk_text.tag_config("h1", font=h1_font, foreground="#FFD700") 
        tk_text.tag_config("h2", font=h2_font, foreground="#FFD700")
        tk_text.tag_config("bold", font=bold_font, foreground="#FFFFFF")
        
        tk_text.tag_remove("h1", "1.0", "end")
        tk_text.tag_remove("h2", "1.0", "end")
        tk_text.tag_remove("bold", "1.0", "end")
        
        self.highlight_pattern(tk_text, r"^# .*", "h1")
        self.highlight_pattern(tk_text, r"^## .*", "h2")
        self.highlight_pattern(tk_text, r"\*\*.*?\*\*", "bold")

    def highlight_pattern(self, tk_text, pattern, tag):
        start = "1.0"
        count_var = tk.IntVar()
        while True:
            pos = tk_text.search(pattern, start, stopindex="end", count=count_var, regexp=True)
            if not pos: break
            end = f"{pos}+{count_var.get()}c"
            tk_text.tag_add(tag, pos, end)
            start = end
        
    def toggle_controls(self, enable, status_text=""):
        state = "normal" if enable else "disabled"
        # We use 'after' to ensure thread safety with Tkinter
        self.after(0, lambda: self.input_entry.configure(state=state))
        self.after(0, lambda: self.send_btn.configure(state=state))
        self.after(0, lambda: self.status_label.configure(text=status_text))
        
        if not enable:
            self.after(0, lambda: self.input_entry.configure(placeholder_text="GM is thinking..."))
        else:
            #self.after(0, lambda: self.input_entry.configure(placeholder_text="What do you do?"))
            # --- FIX: FOCUS CURSOR HERE ---
            self.after(0, lambda: self.input_entry.focus()) 

    def send_message(self, event=None):
        user_text = self.input_entry.get()
        if not user_text.strip():
            return
        
        self.toggle_controls(enable=False, status_text="GM is thinking...") 
        self.print_to_story(user_text, sender="Player")
        self.input_entry.delete(0, "end")

        # Gather Tab Context
        inventory_text = self.notebook_widgets["Inventory"].get("0.0", "end").strip()
        quest_text = self.notebook_widgets["Quests"].get("0.0", "end").strip()
        character_text = self.notebook_widgets["Character"].get("0.0", "end").strip()
        skills_text = self.notebook_widgets["Skills"].get("0.0", "end").strip()
        world_text = self.notebook_widgets["World"].get("0.0", "end").strip()
        
        recent_history = self.conversation_history
        if len(recent_history) > 3000:
            recent_history = "..." + recent_history[-3000:]

        # Note: We do NOT put the Rules/System Prompt here anymore.
        # We only put the Dynamic Context here.
        context_block = (
            f"\n[WORLD SETTING & LORE]:\n{world_text}\n"
            f"\n[CURRENT INVENTORY]:\n{inventory_text}\n"
            f"\n[ACTIVE QUESTS]:\n{quest_text}\n"
            f"\n[CHARACTER]:\n{character_text}\n"
            f"\n[SKILLS]:\n{skills_text}\n"
        )

        full_prompt = (
            f"{context_block}\n"
            f"History:\n{recent_history}\n"
            f"Player: {user_text}\n"
            f"GM:"
        )

        threading.Thread(target=self.query_ai, args=(full_prompt, user_text), daemon=True).start()

    def perform_skill_check(self, skill_name):
        clean_name = skill_name.split('(')[0].strip()
        die_roll = random.randint(1, 20)
        
        bonus = 0
        skills_text = self.notebook_widgets["Skills"].get("0.0", "end")
        safe_skill = re.escape(clean_name)
        
        table_match = re.search(rf"\|\s*{safe_skill}\s*\|[^|]*\|\s*(\d+)\s*\|", skills_text, re.IGNORECASE)
        simple_match = re.search(rf"{safe_skill}.*?([+-]\d+)", skills_text, re.IGNORECASE)
        
        if table_match: bonus = int(table_match.group(1))
        elif simple_match: bonus = int(simple_match.group(1))
            
        total = die_roll + bonus
        self.print_to_story(f"🎲 Rolling {clean_name}: {die_roll} + ({bonus}) = {total}", sender="System")
        return total

    def query_ai(self, prompt, user_text, recursion_depth=0):
        response = None
        
        # Load rules freshly every turn so you can edit rules.txt while the app is running
        current_rules = self.load_rules() 

        try:
            if recursion_depth == 0:
                self.print_to_story("...", sender="System")
            
            # --- UPDATED: Pass Rules via system_instruction ---
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=current_rules,
                    temperature=0.7 # Slight creativity
                )
            )
            
            ai_text = response.text
            if not ai_text: raise ValueError("Empty response received")

            roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
            
            if roll_match and recursion_depth < 2:
                skill_needed = roll_match.group(1).strip()
                roll_result = self.perform_skill_check(skill_needed)
                
                follow_up_prompt = (
                    f"{prompt}\n"
                    f"GM: {ai_text}\n"
                    f"[System: Player rolled {roll_result} for {skill_needed}. Describe the outcome.]"
                )
                self.query_ai(follow_up_prompt, user_text, recursion_depth=recursion_depth + 1)
                
            else:
                if recursion_depth >= 2:
                     ai_text = re.sub(r"\[\[ROLL:.*?\]\]", "", ai_text).strip()
                self.print_to_story(ai_text, sender="GM")
                self.conversation_history += f"Player: {user_text}\nGM: {ai_text}\n"

        except Exception as e:
            self.print_to_story(f"AI Error: {e}", sender="System")
            print(f"Detailed Error: {e}")
            
        finally:
            is_rolling = False
            if response and response.text:
                if re.search(r"\[\[ROLL:\s*(.*?)\]\]", response.text) and recursion_depth < 2:
                    is_rolling = True
            if not is_rolling:
                self.toggle_controls(enable=True, status_text="")

    def save_game(self):
        # (Same as before - omitted for brevity, keep your existing code)
        for tab_name, widget in self.notebook_widgets.items():
            content = widget.get("0.0", "end").strip()
            filename = f"{tab_name}.md"
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                print(f"Error saving {filename}: {e}")

        history_as_list = self.conversation_history.strip().split("\n")
        history_as_list = [line for line in history_as_list if line.strip()]

        data = {"Chat History": history_as_list}
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print("Game Saved.")

    def load_game(self):
        # (Same as before - omitted for brevity, keep your existing code)
        for tab_name, widget in self.notebook_widgets.items():
            filename = f"{tab_name}.md"
            if os.path.exists(filename):
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        content = f.read()
                    widget.configure(state="normal")
                    widget.delete("0.0", "end")
                    widget.insert("0.0", content)
                    self.apply_markdown_style(widget)
                    if tab_name == "World": widget.configure(state="disabled")
                except Exception as e:
                    self.print_to_story(f"Error loading {filename}: {e}", sender="System")

        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    history_data = data.get("Chat History", [])
                    if isinstance(history_data, list): self.conversation_history = "\n".join(history_data)
                    else: self.conversation_history = history_data
                self.print_to_story("System: Game Loaded.", sender="System")
                recent_history = self.conversation_history[-5000:]
                threading.Thread(target=self.generate_recap, args=(recent_history,), daemon=True).start()
            except Exception as e:
                self.print_to_story(f"Save file corrupted: {e}", sender="System")
        else:
            self.print_to_story("Welcome, adventurer. What is your name?", sender="GM")

    def generate_recap(self, history_text):
        self.toggle_controls(enable=False, status_text="Picking up where we left off...")
        if len(history_text) < 100: 
            self.toggle_controls(enable=True, status_text="")
            return

        recap_prompt = (
            f"The player has just loaded the game. Below is the recent conversation history.\n"
            f"--- HISTORY START ---\n{history_text}\n--- HISTORY END ---\n"
            f"Write a brief, dramatic 2-sentence summary. End by asking 'What do you do next?'"
        )

        try:
            # We also pass the rules to the recap, just in case
            current_rules = self.load_rules()
            response = client.models.generate_content(
                model=MODEL,
                contents=recap_prompt,
                config=types.GenerateContentConfig(system_instruction=current_rules)
            )
            recap_text = response.text
            self.print_to_story(f"📝 RECAP: {recap_text}", sender="GM")
        except Exception as e:
            self.print_to_story(f"Recap failed: {e}", sender="System")
        finally:
            self.toggle_controls(enable=True, status_text="")

    def on_close(self):
        self.save_game()
        self.destroy()

if __name__ == "__main__":
    app = GameApp()
    app.mainloop()