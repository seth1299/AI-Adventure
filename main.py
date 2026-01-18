import requests
import threading
import json
import os
import tkinter as tk
import customtkinter as ctk
import random
import re
import ctypes

# pyinstaller --noconsole --onefile --add-data "game_icon.ico;." --icon=game_icon.ico --name "Text Adventure" main.py

# --- Configuration ---
MODEL_NAME = "mistral"  # Ensure you have this model pulled in Ollama
OLLAMA_API_URL = "http://localhost:11434/api/generate"
SAVE_FILE = "savegame.json"

# --- System Prompt ---
# This tells the AI how to behave.
SYSTEM_PROMPT = (
    "You are a Dungeon Master for a text-based RPG. "
    "Describe the environment vividly. React to the player's actions realistically. "
    "Keep responses concise (under 2-3 sentences) unless describing a major event. "
    "Do not break character."
    "IMPORTANT - SKILL CHECKS: "
    "If the player attempts a difficult action (fighting, climbing, lying, etc), "
    "DO NOT narrate the outcome yet. Instead, output ONLY this tag: "
    "[[ROLL: SkillName]] "
    "(Example: [[ROLL: Strength]] or [[ROLL: Deception]]). "
    "Wait for the system to provide the dice result before you continue the story."
    "Do not display to the Player the numerical result of the dice roll, or if it succeeded/failed. Simply narrate the result of the player's action."
    "If a player succeeds in a Skill Check, award them 1 XP towards that Skill and let the Player know in the chat so that they may update their sheet."
    "If the player has done something enough times to warrant learning a new Skill, let the Player know."
    "Remember that the player only has access to items that are in their 'Inventory' or that are located somewhere in the current scene (that the player is also aware of and can access)."
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

        # Chat History (Read Only)
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
        # We make it small and gray so it looks like system info
        self.status_label = ctk.CTkLabel(self.story_frame, text="", text_color="gray")
        self.status_label.grid(row=2, column=0, columnspan=3, sticky="w", padx=10)

        # --- OTHER TABS (Editable Notes) ---
        self.notebook_widgets = {} 
        # We loop through ALL tabs, but skip 'Story' because it has special controls
        for tab_name in self.tabs:
            if tab_name == "Story":
                continue
            
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)
            
            # Editable text box
            tb = ctk.CTkTextbox(frame, font=("Consolas", 12))
            tb.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
            
            # Add a default header
            tb.insert("0.0", f"# {tab_name} \n")
            
            # Store it so we can read/save it later
            self.notebook_widgets[tab_name] = tb
            
            tb.bind("<KeyRelease>", lambda event, w=tb: self.apply_markdown_style(w))

        # --- Save/Load System ---
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.conversation_history = "" # To keep context for the AI
        self.load_game()
        #self.load_world_file()

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
        """
        Scans the text widget and applies formatting tags (Bold, Headers, etc.)
        without deleting the symbols (preserving file integrity).
        """
        # Access the underlying Tkinter widget to use advanced tagging
        tk_text = widget._textbox
        
        # 1. Define Fonts (You can tweak sizes here)
        # We use the widget's current font family as a base
        base_font = ctk.CTkFont(family="Consolas", size=12)
        h1_font = ctk.CTkFont(family="Consolas", size=20, weight="bold")
        h2_font = ctk.CTkFont(family="Consolas", size=16, weight="bold")
        bold_font = ctk.CTkFont(family="Consolas", size=12, weight="bold")
        
        # 2. Configure Tags
        # foreground="..." sets the color. Let's use Gold for headers!
        tk_text.tag_config("h1", font=h1_font, foreground="#FFD700") 
        tk_text.tag_config("h2", font=h2_font, foreground="#FFD700")
        tk_text.tag_config("bold", font=bold_font, foreground="#FFFFFF")
        
        # 3. Clear old tags (Reset formatting)
        tk_text.tag_remove("h1", "1.0", "end")
        tk_text.tag_remove("h2", "1.0", "end")
        tk_text.tag_remove("bold", "1.0", "end")
        
        # 4. Apply Tags via Regex Pattern Matching
        # Header 1 (^# Text)
        self.highlight_pattern(tk_text, r"^# .*", "h1")
        # Header 2 (^## Text)
        self.highlight_pattern(tk_text, r"^## .*", "h2")
        # Bold (**Text**)
        self.highlight_pattern(tk_text, r"\*\*.*?\*\*", "bold")
        # Bullets (- Item or * Item) - Optional: Color them slightly
        # self.highlight_pattern(tk_text, r"^[-*] .*", "bold")

    def highlight_pattern(self, tk_text, pattern, tag):
        """Helper to find and tag all occurrences of a regex pattern."""
        start = "1.0"
        count_var = tk.IntVar()
        
        while True:
            # Search for the pattern
            pos = tk_text.search(pattern, start, stopindex="end", count=count_var, regexp=True)
            if not pos:
                break
                
            # Calculate end position based on match length
            end = f"{pos}+{count_var.get()}c"
            
            # Apply tag
            tk_text.tag_add(tag, pos, end)
            
            # Move to next
            start = end
        
    def toggle_controls(self, enable, status_text=""):
        state = "normal" if enable else "disabled"
        
        # We use .after(0, ...) to ensure this runs safely on the main GUI thread
        # even if called from the background AI thread.
        self.after(0, lambda: self.input_entry.configure(state=state))
        self.after(0, lambda: self.send_btn.configure(state=state))
        
        self.after(0, lambda: self.status_label.configure(text=status_text))
        
        # Optional: Change cursor to watch/arrow
        if not enable:
            self.after(0, lambda: self.input_entry.configure(placeholder_text="GM is thinking..."))
        else:
            self.after(0, lambda: self.input_entry.configure(placeholder_text="What do you do?"))

    def send_message(self, event=None):
        user_text = self.input_entry.get()
        if not user_text.strip():
            return
        
        # 1. Lock UI and set Status Message
        self.toggle_controls(enable=False, status_text="GM is thinking...") 

        # 2. Print User text ONLY once
        self.print_to_story(user_text, sender="Player")
        self.input_entry.delete(0, "end")

        # 3. Build Context (Inventory/Quests)
        inventory_text = self.notebook_widgets["Inventory"].get("0.0", "end").strip()
        quest_text = self.notebook_widgets["Quests"].get("0.0", "end").strip()
        character_text = self.notebook_widgets["Character"].get("0.0", "end").strip()
        skills_text = self.notebook_widgets["Skills"].get("0.0", "end").strip()
        world_text = self.notebook_widgets["World"].get("0.0", "end").strip()
        
        recent_history = self.conversation_history
        if len(recent_history) > 3000:
            recent_history = "..." + recent_history[-3000:]

        context_block = (
            f"\n[WORLD SETTING & LORE]:\n{world_text}\n"
            f"\n[CURRENT INVENTORY]:\n{inventory_text}\n"
            f"\n[ACTIVE QUESTS]:\n{quest_text}\n"
            f"\n[CHARACTER]:\n{character_text}\n"
            f"\n[SKILLS]:\n{skills_text}\n"
        )

        full_prompt = (
            f"{SYSTEM_PROMPT}\n"
            f"{context_block}\n"
            f"History:\n{recent_history}\n"
            f"Player: {user_text}\n"
            f"GM:"
        )

        # 4. Run AI
        threading.Thread(target=self.query_ollama, args=(full_prompt, user_text), daemon=True).start()

    def perform_skill_check(self, skill_name):
        """
        Calculates the roll based on the Skills tab and returns a text result.
        """
        # 1. Roll the die
        die_roll = random.randint(1, 20)
        
        # 2. Find bonus in Skills tab
        bonus = 0
        skills_text = self.notebook_widgets["Skills"].get("0.0", "end")
        safe_skill = re.escape(skill_name)
        
        table_match = re.search(rf"\|\s*{safe_skill}\s*\|[^|]*\|\s*(\d+)\s*\|", skills_text, re.IGNORECASE)
        simple_match = re.search(rf"{safe_skill}.*?([+-]\d+)", skills_text, re.IGNORECASE)
        
        if table_match:
            bonus = int(table_match.group(1))
        elif simple_match:
            bonus = int(simple_match.group(1))
            
        total = die_roll + bonus
        
        # Log it to the chat so the player sees the math
        self.print_to_story(f"🎲 Rolling {skill_name}: {die_roll} + ({bonus}) = {total}", sender="System")
        
        return total

    def query_ollama(self, prompt, user_text, is_follow_up=False):
        """
        is_follow_up: True if this is the second step of a dice roll (sending the result back).
        """
        try:
            if not is_follow_up:
                self.print_to_story("...", sender="System")
            
            response = requests.post(
                OLLAMA_API_URL, 
                json={
                    "model": MODEL_NAME, 
                    "prompt": prompt, 
                    "stream": False,
                    "options": {
                        "num_ctx": 8192
                    }
                },
                timeout=180
            )
            
            if response.status_code == 200:
                ai_text = response.json()['response']
                
                # --- CHECK FOR ROLL REQUEST ---
                # We look for [[ROLL: SkillName]]
                roll_match = re.search(r"\[\[ROLL:\s*(.*?)\]\]", ai_text)
                
                if roll_match:
                    # 1. The AI wants a roll! Extract skill name.
                    skill_needed = roll_match.group(1).strip()
                    
                    # 2. Perform the roll in Python
                    roll_result = self.perform_skill_check(skill_needed)
                    
                    # 3. Send the result back to the AI immediately (The Recursive Step)
                    # We tell the AI: "The player rolled X. Now describe what happens."
                    follow_up_prompt = (
                        f"{prompt}\n"
                        f"GM: {ai_text}\n" # Include the AI's request for the roll in history
                        f"[System: Player rolled {roll_result} for {skill_needed}. Describe the outcome, determining a fair Difficulty Rating that the Player needs to have met or exceeded.]"
                    )
                    
                    # Call this function again with the new info
                    self.query_ollama(follow_up_prompt, user_text, is_follow_up=True)
                    
                else:
                    # No roll needed, just normal story
                    # (Optional: Process other tags like ADD_ITEM here if you kept that code)
                    self.print_to_story(ai_text, sender="GM")
                    
                    # Only update history if it's a "Done" response
                    if not is_follow_up:
                        self.conversation_history += f"Player: {user_text}\nGM: {ai_text}\n"
                    else:
                        # If this was a follow-up, we append the whole sequence
                        # Note: Simplifying history management for this example
                        self.conversation_history += f"Player: {user_text}\nGM: {ai_text}\n"

            else:
                self.print_to_story(f"Error: {response.status_code}", sender="System")
                
        except Exception as e:
            self.print_to_story(f"Connection Error: {e}", sender="System")
            
        finally:
            # CRITICAL: This runs no matter what, re-enabling your game
            if not is_follow_up: # Only unlock if we are fully done (not in the middle of a roll)
                self.toggle_controls(enable=True, status_text="")

    def save_game(self):
        # --- PART 1: Save Tabs to individual .md files ---
        # We loop through every tab (Inventory, Quests, Journal, etc.)
        for tab_name, widget in self.notebook_widgets.items():
            # Get the text
            content = widget.get("0.0", "end").strip()
                
            # Create a filename like "Inventory.md" or "Journal.md"
            filename = f"{tab_name}.md"
                
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                print(f"Error saving {filename}: {e}")

        # --- PART 2: Save History to JSON (As a List) ---
        # 1. Split the massive string into a list of lines
        # This makes the JSON format it nicely with one line per string
        history_as_list = self.conversation_history.strip().split("\n")
        
        # Filter out empty strings to keep it clean
        history_as_list = [line for line in history_as_list if line.strip()]

        data = {
            "Chat History": history_as_list
        }

        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            # indent=4 makes it pretty
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        print("Game Saved.")

    def load_game(self):
        # --- PART 1: Load Tabs from .md files ---
        for tab_name, widget in self.notebook_widgets.items():
            filename = f"{tab_name}.md"
            
            if os.path.exists(filename):
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    # 1. Force Unlock (We know "World" might be locked, others are normal)
                    widget.configure(state="normal")
                    
                    # 2. Update Content
                    widget.delete("0.0", "end")
                    widget.insert("0.0", content)
                    
                    self.apply_markdown_style(widget)
                    
                    # 3. Relock ONLY if it is the World tab
                    if tab_name == "World":
                        widget.configure(state="disabled")
                    # (We leave everything else "normal" so you can edit it)

                except Exception as e:
                    self.print_to_story(f"Error loading {filename}: {e}", sender="System")

        # --- PART 2: Load History from JSON & Trigger Recap ---
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                    # Handle both List format (New) and String format (Old)
                    history_data = data.get("Chat History", [])
                    if isinstance(history_data, list):
                        self.conversation_history = "\n".join(history_data)
                    else:
                        self.conversation_history = history_data

                self.print_to_story("System: Game Loaded.", sender="System")
                
                # --- NEW: Send recent history to the Recap generator ---
                # We grab the last 5000 characters so the AI summarizes "What just happened"
                recent_history = self.conversation_history[-5000:]
                
                threading.Thread(target=self.generate_recap, args=(recent_history,), daemon=True).start()

            except Exception as e:
                self.print_to_story(f"Save file corrupted: {e}", sender="System")
        else:
            self.print_to_story("Welcome, adventurer. What is your name?", sender="GM")

    def generate_recap(self, history_text):
        self.toggle_controls(enable=False, status_text="Picking up where we left off...")
        
        # If history is too short, no need for a recap
        if len(history_text) < 100: 
            self.toggle_controls(enable=True, status_text="")
            return

        recap_prompt = (
            f"{SYSTEM_PROMPT}\n"
            f"The player has just loaded the game. Below is the recent conversation history.\n"
            f"--- HISTORY START ---\n{history_text}\n--- HISTORY END ---\n"
            f"Write a brief, dramatic 2-sentence summary of the current situation to remind the player "
            f"what is happening. End by asking 'What do you do next?'"
        )

        try:
            response = requests.post(
                OLLAMA_API_URL, 
                json={
                    "model": MODEL_NAME, 
                    "prompt": recap_prompt, 
                    "stream": False,
                    "options": {
                        "num_ctx": 8192
                    }
                },
                timeout=180
            )
            if response.status_code == 200:
                recap_text = response.json()['response']
                self.print_to_story(f"📝 RECAP: {recap_text}", sender="GM")
        except Exception as e:
            print(f"Recap failed: {e}")
        finally:
            # Unlock when done
            self.toggle_controls(enable=True, status_text="")

    def on_close(self):
        self.save_game()
        self.destroy()

if __name__ == "__main__":
    app = GameApp()
    app.mainloop()