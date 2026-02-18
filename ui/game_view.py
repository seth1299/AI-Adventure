import customtkinter as ctk
from .story_tab import StoryTab
from .inventory_tab import InventoryTab
from .skills_tab import SkillsTab
from .processing_tab import ProcessingTab
from .recipes_tab import RecipesTab
from .editor_tab import MarkdownEditorTab

class GameView(ctk.CTkFrame):
    def __init__(self, parent, send_callback, menu_callback):
        super().__init__(parent)
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.grid(row=0, column=0, sticky="nsew")
        
        self.tabs = ["Story", "Inventory", "Skills", "Processing", "Recipes", "Character", "World", "Journal"]
        self.widgets = {}
        
        for tab_name in self.tabs:
            self.tab_view.add(tab_name)
            frame = self.tab_view.tab(tab_name)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

            if tab_name == "Story":
                self.widgets[tab_name] = StoryTab(frame, 
                                          on_send_callback=send_callback,
                                          on_main_menu_callback=menu_callback)
            elif tab_name == "Inventory":
                self.widgets[tab_name] = InventoryTab(frame)
            elif tab_name == "Skills":
                self.widgets[tab_name] = SkillsTab(frame)
            elif tab_name == "Processing":
                self.widgets[tab_name] = ProcessingTab(frame)
            elif tab_name == "Recipes":
                self.widgets[tab_name] = RecipesTab(frame)
            else:
                # Editor tabs: Character, World, Journal
                self.widgets[tab_name] = MarkdownEditorTab(frame, default_text=f"{tab_name}\n")
            
            # Grid the widget within the tab frame
            self.widgets[tab_name].grid(row=0, column=0, sticky="nsew")