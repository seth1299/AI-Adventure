import customtkinter as ctk
import os
from config import SAVES_DIR

class MainMenu(ctk.CTkFrame):
    """The startup screen to select a save file."""
    def __init__(self, parent, on_load_callback):
        super().__init__(parent)
        self.on_load = on_load_callback

        # Title
        ctk.CTkLabel(self, text="ADVENTURES", font=("Consolas", 32, "bold")).pack(pady=(40, 20))

        # Scrollable list of games
        self.scroll_frame = ctk.CTkScrollableFrame(self, width=400, height=300)
        self.scroll_frame.pack(pady=10)

        # New Game Button
        ctk.CTkButton(self, text="+ New Adventure", fg_color="green", height=40, width=200, 
                      command=self.open_new_game_dialog).pack(pady=20)

        self.refresh_list()

    def refresh_list(self):
        # Clear list
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        # Ensure saves folder exists
        if not os.path.exists(SAVES_DIR):
            os.makedirs(SAVES_DIR)

        # List folders
        saves = [d for d in os.listdir(SAVES_DIR) if os.path.isdir(os.path.join(SAVES_DIR, d))]
        
        if not saves:
            ctk.CTkLabel(self.scroll_frame, text="No saved games found.").pack(pady=20)
            return

        for save_name in saves:
            btn = ctk.CTkButton(self.scroll_frame, text=save_name, height=40,
                                command=lambda s=save_name: self.on_load(s))
            btn.pack(fill="x", padx=5, pady=5)

    def open_new_game_dialog(self):
        dialog = ctk.CTkInputDialog(text="Name your adventure:", title="New Adventure")
        name = dialog.get_input()
        if name:
            # Sanitize name
            clean_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
            if clean_name:
                full_path = os.path.join(SAVES_DIR, clean_name)
                if not os.path.exists(full_path):
                    os.makedirs(full_path)
                    # Trigger load immediately
                    self.on_load(clean_name)