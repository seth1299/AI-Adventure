import customtkinter as ctk
from tqdm import tqdm

class StoryTab(ctk.CTkFrame):
    def __init__(self, parent, on_send_callback, on_main_menu_callback):
        super().__init__(parent)
        self.on_send_callback = on_send_callback
        self.on_main_menu_callback = on_main_menu_callback
        
        # --- DATA CACHE ---
        self.status_cache = {
            "turn": "1",
            "location": "Unknown",
            "day": "Day 1",
            "time": "Morning",
            "nutrition": 100,
            "stamina": 100
        }

        # --- Layout ---
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0) # Status
        self.grid_rowconfigure(1, weight=1) # Chat
        self.grid_rowconfigure(2, weight=0) # Input

        # 1. Status Header
        self.status_frame = ctk.CTkFrame(self, height=50, fg_color="transparent")
        self.status_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(5,0))
        
        # Row 1 of Header: Basic Info
        self.top_row = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.top_row.pack(fill="x", pady=2)

        self.btn_menu = ctk.CTkButton(self.top_row, text="🏠 Menu", width=60, height=24, 
                                      fg_color="gray", command=self.on_main_menu_callback)
        self.btn_menu.pack(side="left", padx=(0, 10))
        
        self.lbl_turn = ctk.CTkLabel(self.top_row, text="Turn: 1", font=("Consolas", 12, "bold"), text_color="#FFD700")
        self.lbl_turn.pack(side="left", padx=10)
        
        self.lbl_day = ctk.CTkLabel(self.top_row, text="Day: 1", font=("Consolas", 12))
        self.lbl_day.pack(side="right", padx=10)
        
        self.lbl_time = ctk.CTkLabel(self.top_row, text="Time: Start", font=("Consolas", 12))
        self.lbl_time.pack(side="right", padx=10)
        
        self.lbl_location = ctk.CTkLabel(self.top_row, text="Loc: Unknown", font=("Consolas", 12))
        self.lbl_location.pack(side="right", padx=10)

        # Row 2 of Header: Stats (Nutrition/Stamina)
        self.stat_row = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        self.stat_row.pack(fill="x", pady=2)

        self.lbl_nutrition = ctk.CTkLabel(self.stat_row, text="Nut: [||||||||||] 100%", font=("Consolas", 11), text_color="#4CAF50")
        self.lbl_nutrition.pack(side="right", padx=10)

        self.lbl_stamina = ctk.CTkLabel(self.stat_row, text="Sta: [||||||||||] 100%", font=("Consolas", 11), text_color="#2196F3")
        self.lbl_stamina.pack(side="right", padx=10)

        # 2. Chat Display
        self.chat_display = ctk.CTkTextbox(self, state="disabled", wrap="word", font=("Consolas", 14))
        self.chat_display.grid(row=1, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="nsew")

        # 3. Input Controls
        self.input_entry = ctk.CTkEntry(self, placeholder_text="What do you do?")
        self.input_entry.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="ew")
        self.input_entry.bind("<Return>", self.trigger_send)

        self.send_btn = ctk.CTkButton(self, text="Act", command=self.trigger_send)
        self.send_btn.grid(row=2, column=1, padx=10, pady=(5, 10), sticky="ew")
        
        self.status_label = ctk.CTkLabel(self, text="", text_color="gray", font=("Consolas", 12))
        self.status_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 5))
        
    def clear_chat(self):
        self.chat_display.configure(state="normal")
        self.chat_display.delete("0.0", "end")
        self.chat_display.configure(state="disabled")

    def trigger_send(self, event=None):
        user_text = self.input_entry.get()
        if user_text.strip():
            self.input_entry.delete(0, "end")
            self.on_send_callback(user_text)

    def print_text(self, text, sender="System"):
        self.after(0, lambda: self._internal_print(text, sender))

    def _internal_print(self, text, sender):
        self.chat_display.configure(state="normal")
        if sender == "Player":
            self.chat_display.insert("end", f"\n> {text}\n")
        elif sender == "GM":
            self.chat_display.insert("end", f"\n{text}\n")
        else:
            self.chat_display.insert("end", f"\n[{text}]\n")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def _render_bar(self, current, total=100, color="green"):
        """Creates a TQDM bar string."""
        bar_str = tqdm.format_meter(
            n=current, total=total, elapsed=0, ncols=10, 
            bar_format='{bar}', ascii=False
        ).strip('|')
        return f"{bar_str} {current}%"

    def update_status(self, turn, location, day, time, nutrition=100, stamina=100):
        """Updates the status cache AND the UI labels."""
        try:
            nut_val = max(0, min(100, int(nutrition)))
            sta_val = max(0, min(100, int(stamina)))

        except:
            nut_val = 100
            sta_val = 100

        self.status_cache = {
            "turn": str(turn),
            "location": location,
            "day": day,
            "time": time,
            "nutrition": nut_val,
            "stamina": sta_val
        }
        
        # UI Update
        try:
            self.lbl_turn.configure(text=f"Turn: {turn}")
            self.lbl_location.configure(text=f"Location: {location}")
            self.lbl_day.configure(text=f"Day: {day}")
            self.lbl_time.configure(text=f"Time: {time}")
            
            # Update Bars
            self.lbl_nutrition.configure(text=f"Nutrition: {self._render_bar(nut_val)}")
            self.lbl_stamina.configure(text=f"Stamina:   {self._render_bar(sta_val)}")
            
            # Color Coded Warnings
            if nut_val < 40: self.lbl_nutrition.configure(text_color="#FF5252") # Red
            elif nut_val < 60: self.lbl_nutrition.configure(text_color="#FFC107") # Orange
            else: self.lbl_nutrition.configure(text_color="#4CAF50") # Green

            if sta_val < 40: self.lbl_stamina.configure(text_color="#FF5252")
            elif sta_val < 60: self.lbl_stamina.configure(text_color="#FFC107")
            else: self.lbl_stamina.configure(text_color="#2196F3")

        except Exception as e:
            print(f"UI Update Error: {e}")

    def get_status_data(self):
        return self.status_cache

    def set_controls_state(self, enable, status_text=""):
        state = "normal" if enable else "disabled"
        self.input_entry.configure(state=state)
        self.send_btn.configure(state=state)
        self.status_label.configure(text=status_text)
        if enable:
            self.input_entry.focus()