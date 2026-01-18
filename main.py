import requests
import threading
import json
import os
import customtkinter as ctk
import random
import re
import ctypes

# pyinstaller --noconsole --onefile --icon=game_icon.ico --add-data "game_icon.ico;." --name "Text Adventure" main.py

# --- Configuration ---
MODEL_NAME = "mistral"  # Ensure you have this model pulled in Ollama
OLLAMA_API_URL = "http://localhost:11434/api/generate"
SAVE_FILE = "savegame.json"

# --- System Prompt ---
# This tells the AI how to behave.
SYSTEM_PROMPT = (
    "You are a Dungeon Master for a text-based RPG. "
    "Describe the environment vividly. React to the player's actions realistically. "
    "Keep responses concise (under 3-4 sentences) unless describing a major event. "
    "Do not break character."
    "IMPORTANT - SKILL CHECKS: "
    "If the player attempts a difficult action (fighting, climbing, lying, etc), "
    "DO NOT narrate the outcome yet. Instead, output ONLY this tag: "
    "[[ROLL: SkillName]] "
    "(Example: [[ROLL: Strength]] or [[ROLL: Deception]]). "
    "Wait for the system to provide the dice result before you continue the story."
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
        
        self.tabs = ["Story", "Inventory", "Quests", "Journal", "Skills", "Character"]
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
            tb.insert("0.0", f"--- {tab_name} ---\n")
            
            # Store it so we can read/save it later
            self.notebook_widgets[tab_name] = tb

        # --- Save/Load System ---
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.conversation_history = "" # To keep context for the AI
        self.load_game()

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

        context_block = (
            f"\n[CURRENT INVENTORY]:\n{inventory_text}\n"
            f"\n[ACTIVE QUESTS]:\n{quest_text}\n"
            f"\n[CHARACTER]:\n{character_text}\n"
            f"\n[SKILLS]:\n{skills_text}\n"
        )

        full_prompt = (
            f"{SYSTEM_PROMPT}\n"
            f"{context_block}\n"
            f"History:\n{self.conversation_history}\n"
            f"Player: {user_text}\n"
            f"GM:"
        )

        # 4. Run AI
        threading.Thread(target=self.query_ollama, args=(full_prompt, user_text)).start()

    def perform_skill_check(self, skill_name):
        """
        Calculates the roll based on the Skills tab and returns a text result.
        """
        # 1. Roll the die
        die_roll = random.randint(1, 20)
        
        # 2. Find bonus in Skills tab
        bonus = 0
        skills_text = self.notebook_widgets["Skills"].get("0.0", "end")
        
        # Regex to find "Skill: +X"
        match = re.search(f"{skill_name}.*?([+-]\\d+)", skills_text, re.IGNORECASE)
        if match:
            bonus = int(match.group(1))
            
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
                json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
                timeout=120
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
                        f"[System: Player rolled {roll_result} for {skill_needed}. Describe the outcome.]"
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
        data = {
            "history": self.conversation_history,
            "tabs": {name: widget.get("0.0", "end") for name, widget in self.notebook_widgets.items()}
        }
        with open(SAVE_FILE, "w") as f:
            json.dump(data, f)
        print("Game Saved.")

    def load_game(self):
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, "r") as f:
                    data = json.load(f)
                    self.conversation_history = data.get("history", "")
                    
                    # Restore tab content
                    saved_tabs = data.get("tabs", {})
                    for name, content in saved_tabs.items():
                        if name in self.notebook_widgets:
                            self.notebook_widgets[name].delete("0.0", "end")
                            self.notebook_widgets[name].insert("0.0", content)
                            
                self.print_to_story("System: Game Loaded.", sender="System")
                
                # --- NEW: Trigger the Recap ---
                # We do this in a thread so the GUI doesn't freeze while Ollama thinks
                threading.Thread(target=self.generate_recap).start()

            except Exception as e:
                self.print_to_story(f"Save file corrupted: {e}", sender="System")
        else:
            self.print_to_story("Welcome, adventurer. What is your name?", sender="GM")

    def generate_recap(self):
        self.toggle_controls(enable=False, status_text="Reading Journal...")
        """Asks Ollama to summarize the game state based on the Journal."""
        journal_text = self.notebook_widgets["Journal"].get("0.0", "end").strip()
        
        # If the journal is empty, we skip this to avoid confusion
        if len(journal_text) < 20: 
            self.print_to_story("Write in your Journal to get a recap next time you load!", sender="System")
            return

        recap_prompt = (
            f"{SYSTEM_PROMPT}\n"
            f"The player has just loaded the game after a break. "
            f"Here are the player's personal notes from their Journal:\n"
            f"--- JOURNAL START ---\n{journal_text}\n--- JOURNAL END ---\n"
            f"Based ONLY on these notes, write a 2-sentence dramatic summary "
            f"reminding the player where they are and what they were doing. "
            f"End by asking 'What do you do next?'"
        )

        try:
            response = requests.post(
                OLLAMA_API_URL, 
                json={"model": MODEL_NAME, "prompt": recap_prompt, "stream": False},
                timeout=30
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