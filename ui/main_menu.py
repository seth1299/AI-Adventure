import customtkinter as ctk
import os
import shutil
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

        # Create rows for each save
        for i, save_name in enumerate(saves):
            # Row container
            row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row.pack(fill="x", padx=5, pady=5)
            
            # Load Button (Takes up most space)
            btn_load = ctk.CTkButton(row, text=f"📂 {save_name}", height=40,
                                     command=lambda s=save_name: self.on_load(s))
            btn_load.pack(side="left", fill="x", expand=True, padx=(0, 5))
            
            # Rename Button (Middle, Teal)
            btn_rename = ctk.CTkButton(row, text="✏️", width=40, height=40, fg_color="teal", hover_color="#00695C",
                                       command=lambda s=save_name: self.rename_adventure(s))
            btn_rename.pack(side="right", padx=(0, 5))
            
            # Delete Button (Small, Red)
            btn_del = ctk.CTkButton(row, text="❌", width=40, height=40, fg_color="red", hover_color="darkred",
                                    command=lambda s=save_name: self.confirm_delete(s))
            btn_del.pack(side="right")
            
    def rename_adventure(self, old_name):
        dialog = ctk.CTkInputDialog(text=f"Rename '{old_name}' to:", title="Rename Adventure")
        new_name = dialog.get_input()
        
        if new_name:
            # Sanitize the new name
            clean_name = "".join(c for c in new_name if c.isalnum() or c in (' ', '_', '-')).strip()
            
            # Only proceed if name is valid and actually different
            if clean_name and clean_name != old_name:
                old_path = os.path.join(SAVES_DIR, old_name)
                new_path = os.path.join(SAVES_DIR, clean_name)

                # Prevent overwriting an existing folder
                if os.path.exists(new_path):
                    print("Error: A game with that name already exists.")
                    return

                try:
                    os.rename(old_path, new_path)
                    self.refresh_list() # Refresh to show new name
                except Exception as e:
                    print(f"Error renaming: {e}")
            
    def confirm_delete(self, save_name):
        dialog = ctk.CTkInputDialog(text=f"Type 'DELETE' to confirm deleting '{save_name}':", title="Delete Adventure")
        response = dialog.get_input()
        
        if response and response.strip() == "DELETE":
            full_path = os.path.join(SAVES_DIR, save_name)
            try:
                shutil.rmtree(full_path)
                self.refresh_list()
            except Exception as e:
                print(f"Error deleting: {e}")

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