import requests
import threading
import json
import os
import customtkinter as ctk

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
)

class GameApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title("AI RPG Adventure")
        self.geometry("900x600")
        ctk.set_appearance_mode("Dark")

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Tabs
        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.tabs = ["Story", "Inventory", "Quests", "Journal"]
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

        # --- OTHER TABS (Editable Notes) ---
        # We store references to these text boxes to save them later
        self.notebook_widgets = {} 
        for tab_name in ["Inventory", "Quests", "Journal"]:
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)
            
            # Editable text box for the user to track their own progress
            tb = ctk.CTkTextbox(frame, font=("Consolas", 12))
            tb.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
            tb.insert("0.0", f"--- {tab_name} ---\n")
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

    def send_message(self, event=None):
        user_text = self.input_entry.get()
        if not user_text.strip():
            return

        self.print_to_story(user_text, sender="Player")
        self.input_entry.delete(0, "end")

        # --- NEW CODE STARTS HERE ---
        # 1. Grab text from Inventory and Quests
        inventory_text = self.notebook_widgets["Inventory"].get("0.0", "end").strip()
        quest_text = self.notebook_widgets["Quests"].get("0.0", "end").strip()

        # 2. Build a "Context Block" to show the AI the current state
        # We tell the AI: "Here is what the player currently has."
        context_block = (
            f"\n[CURRENT INVENTORY]:\n{inventory_text}\n"
            f"\n[ACTIVE QUESTS]:\n{quest_text}\n"
        )

        # 3. Add this context to the prompt
        full_prompt = (
            f"{SYSTEM_PROMPT}\n"
            f"{context_block}\n"  # <--- The AI now sees your tabs!
            f"History:\n{self.conversation_history}\n"
            f"Player: {user_text}\n"
            f"GM:"
        )
        # --- NEW CODE ENDS HERE ---

        # Run AI in a separate thread
        threading.Thread(target=self.query_ollama, args=(full_prompt, user_text)).start()

    def query_ollama(self, prompt, user_text):
        try:
            self.print_to_story("...", sender="System")
            
            # Call Ollama API
            response = requests.post(
                OLLAMA_API_URL, 
                json={"model": MODEL_NAME, "prompt": prompt, "stream": False},
                timeout=30
            )
            
            if response.status_code == 200:
                ai_text = response.json()['response']
                
                # Remove the "..." placeholder (simple backspace logic not shown, just appending for simplicity)
                self.print_to_story(ai_text, sender="GM")
                
                # Update history memory
                self.conversation_history += f"Player: {user_text}\nGM: {ai_text}\n"
            else:
                self.print_to_story(f"Error: {response.status_code}", sender="System")
                
        except Exception as e:
            self.print_to_story(f"Connection Error. Is Ollama running?\n{e}", sender="System")

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
                            
                self.print_to_story("Game Loaded successfully.", sender="System")
            except Exception as e:
                self.print_to_story(f"Save file corrupted: {e}", sender="System")
        else:
            self.print_to_story("Welcome, adventurer. What is your name?", sender="GM")

    def on_close(self):
        self.save_game()
        self.destroy()

if __name__ == "__main__":
    app = GameApp()
    app.mainloop()