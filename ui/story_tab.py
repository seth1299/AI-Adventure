import customtkinter as ctk

class StoryTab(ctk.CTkFrame):
    def __init__(self, parent, on_send_callback, on_main_menu_callback):
        super().__init__(parent)
        self.on_send_callback = on_send_callback # Function to call when user clicks "Act"
        self.on_main_menu_callback = on_main_menu_callback
        
        # --- DATA CACHE (Thread Safety) ---
        # We store status here so the AI thread can read it without touching the UI
        self.status_cache = {
            "turn": "1",
            "location": "Unknown",
            "day": "Day 1",
            "time": "Morning"
        }

        # --- Layout Configuration ---
        self.grid_columnconfigure(0, weight=3) # Chat area
        self.grid_columnconfigure(1, weight=1) # Button area
        self.grid_rowconfigure(0, weight=0)    # Status Header
        self.grid_rowconfigure(1, weight=1)    # Chat History
        self.grid_rowconfigure(2, weight=0)    # Input Area

        # 1. Status Header
        self.status_frame = ctk.CTkFrame(self, height=40, fg_color="transparent")
        self.status_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(5,0))
        
        self.btn_menu = ctk.CTkButton(self.status_frame, text="🏠 Menu", width=60, height=24, 
                                      fg_color="gray", command=self.on_main_menu_callback)
        self.btn_menu.pack(side="left", padx=(0, 10))
        
        self.lbl_turn = ctk.CTkLabel(self.status_frame, text="Turn: 1", font=("Consolas", 12, "bold"), text_color="#FFD700")
        self.lbl_turn.pack(side="left", padx=10)
        
        self.lbl_day = ctk.CTkLabel(self.status_frame, text="Day: 1", font=("Consolas", 12))
        self.lbl_day.pack(side="right", padx=10)
        
        self.lbl_time = ctk.CTkLabel(self.status_frame, text="Time: Start", font=("Consolas", 12))
        self.lbl_time.pack(side="right", padx=10)
        
        self.lbl_location = ctk.CTkLabel(self.status_frame, text="Loc: Unknown", font=("Consolas", 12))
        self.lbl_location.pack(side="right", padx=10)

        # 2. Chat Display
        self.chat_display = ctk.CTkTextbox(self, state="disabled", wrap="word", font=("Consolas", 14))
        self.chat_display.grid(row=1, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="nsew")

        # 3. Input Controls
        self.input_entry = ctk.CTkEntry(self, placeholder_text="What do you do?")
        self.input_entry.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="ew")
        self.input_entry.bind("<Return>", self.trigger_send)

        self.send_btn = ctk.CTkButton(self, text="Act", command=self.trigger_send)
        self.send_btn.grid(row=2, column=1, padx=10, pady=(5, 10), sticky="ew")
        
        # 4. Footer Status (e.g. "GM is thinking...")
        self.status_label = ctk.CTkLabel(self, text="", text_color="gray", font=("Consolas", 12))
        self.status_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 5))
        
    def clear_chat(self):
        """Clears the chat history from the screen."""
        self.chat_display.configure(state="normal")
        self.chat_display.delete("0.0", "end")
        self.chat_display.configure(state="disabled")

    def trigger_send(self, event=None):
        """Gets text and calls the main app's callback."""
        user_text = self.input_entry.get()
        if user_text.strip():
            self.input_entry.delete(0, "end")
            self.on_send_callback(user_text)
            
    def print_text(self, text, sender="System"):
        """Thread-safe wrapper to print text."""
        # We use self.after to ensure this runs on the main UI thread,
        # preventing lockups when called from the AI thread.
        self.after(0, lambda: self._internal_print(text, sender))

    def _internal_print(self, text, sender):
        """Actual insertion logic (Must run on Main Thread)."""
        self.chat_display.configure(state="normal")
        if sender == "Player":
            self.chat_display.insert("end", f"\n> {text}\n")
        elif sender == "GM":
            self.chat_display.insert("end", f"\n{text}\n")
        else:
            self.chat_display.insert("end", f"\n[{text}]\n")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def update_status(self, turn, location, day, time):
        """Updates the status cache AND the UI labels."""
        # 1. Update Cache (for the AI thread to read safely)
        self.status_cache = {
            "turn": str(turn),
            "location": location,
            "day": day,
            "time": time
        }
        
        # 2. Update UI
        try:
            self.lbl_turn.configure(text=f"Turn: {turn}")
            self.lbl_location.configure(text=f"Location: {location}")
            self.lbl_day.configure(text=f"Day: {day}")
            self.lbl_time.configure(text=f"Time: {time}")
        except Exception as e:
            print(f"UI Update Error: {e}")

    def get_status_data(self):
        """Returns the CACHED status, not the UI label text."""
        # This is now thread-safe because it reads a dict, not a UI widget.
        return self.status_cache

    def set_controls_state(self, enable, status_text=""):
        """Disables/Enables input during AI processing."""
        state = "normal" if enable else "disabled"
        self.input_entry.configure(state=state)
        self.send_btn.configure(state=state)
        self.status_label.configure(text=status_text)
        if enable:
            self.input_entry.focus()