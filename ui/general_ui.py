# general_ui.py
import customtkinter as ctk
import os, sys
from main import GameApp
from ui import MainMenu, StoryTab, InventoryTab, SkillsTab, ProcessingTab, MarkdownEditorTab
from file_io import FileIO
import main

def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)

class GeneralUI:
    def apply(self, app: ctk.CTk):
        ctk.set_appearance_mode("Dark")
        app.title("AI RPG Adventure")
        app.geometry("1000x700")
        icon_path = resource_path("game_icon.ico")
        if os.path.exists(icon_path):
            try:
                app.iconbitmap(icon_path)
            except Exception as e:
                print(f"Icon error: {e}")
        app.grid_columnconfigure(0, weight=1)
        app.grid_rowconfigure(0, weight=1)
        
        # --- VIEW 1: Main Menu ---
        self.main_menu = MainMenu(self, on_load_callback=FileIO.load_adventure)
        self.main_menu.grid(row=0, column=0, sticky="nsew")

        # --- VIEW 2: Game Tabs (Hidden initially) ---
        self.tab_view = ctk.CTkTabview(self)
        self.tabs = ["Story", "Inventory", "Skills", "Processing", "Character", "World", "Journal"]
        self.notebook_widgets = {} 
        
        for tab_name in self.tabs:
            self.tab_view.add(tab_name)
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

            if tab_name == "Story":
                # Initialize StoryTab with a callback to our 'handle_player_action' method
                self.story_tab = StoryTab(frame, 
                                          on_send_callback=GameApp.handle_player_action,
                                          on_main_menu_callback=GameApp.return_to_menu)
                self.story_tab.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = self.story_tab
            
            elif tab_name == "Inventory":
                inv = InventoryTab(frame)
                inv.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = inv
            
            elif tab_name == "Skills":
                skl = SkillsTab(frame)
                skl.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = skl
                
            elif tab_name == "Processing":
                proc = ProcessingTab(frame)
                proc.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = proc
            
            else:
                editor = MarkdownEditorTab(frame, default_text=f"{tab_name}\n")
                editor.grid(row=0, column=0, sticky="nsew")
                self.notebook_widgets[tab_name] = editor

        app.protocol("WM_DELETE_WINDOW")
        
    def on_close(self, app: ctk.CTk):
        FileIO.save_game()
        app.destroy()
        
    def get_notebook_widgets(self):
        return self.notebook_widgets
    
    def get_main_menu(self):
        return self.main_menu
    
    def get_tab_view(self):
        return self.tab_view
    
    def get_title(self, app: ctk.CTk):
        return app.title
    
    def set_title(self, app: ctk.CTk, newTitle=""):
        app.title(newTitle)