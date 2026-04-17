# qt_ui/quests_panel.py

import logging
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextBrowser
from PySide6.QtGui import QFont
from tabulate import tabulate

class QuestsPanel(QWidget):
    """
    A read-only UI panel that displays active quests in a rounded grid format.
    """
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Using a QTextBrowser to display pre-formatted plain text grids
        self.text_display = QTextBrowser()
        self.text_display.setFont(QFont("Consolas", 10)) # Monospace font is required for Tabulate grids!
        self.text_display.setOpenExternalLinks(False)
        layout.addWidget(self.text_display)
        
    def refresh_display(self):
        """Reads the player's current quests and updates the text display with generated tables."""
        quests = getattr(self.app.player, 'quests', [])
        
        if not quests:
            self.text_display.setPlainText("You currently have no active quests.")
            return
            
        display_text = ""
        
        for quest in quests:
            name = quest.get("name", "Unknown Quest")
            giver = quest.get("giver", "Unknown")
            description = quest.get("description", "No description provided.")
            turn_in = quest.get("turn_in", "Unknown")
            reward = quest.get("reward", "Unknown")
            
            # Using a 2-column vertical table format so long descriptions don't cause horizontal overflow
            table_data = [
                ["Quest Giver", giver],
                ["Description", description],
                ["How to Complete", turn_in],
                ["Reward", reward]
            ]
            
            grid = tabulate(table_data, tablefmt="rounded_grid")
            display_text += f"### {name} ###\n{grid}\n\n"
            
        self.text_display.setPlainText(display_text.strip())
        
    def add_quest(self, name, giver, description, turn_in, reward):
        """Adds a quest to the player's log if it doesn't exist already."""
        # Ensure the player object has a quests list
        if not hasattr(self.app.player, 'quests'):
            self.app.player.quests = []
            
        # Check for duplicates so the AI doesn't give us the exact same quest twice
        for q in self.app.player.quests:
            if q.get("name", "").lower() == name.lower():
                return 
                
        self.app.player.quests.append({
            "name": name,
            "giver": giver,
            "description": description,
            "turn_in": turn_in,
            "reward": reward
        })
        self.refresh_display()
        
    def complete_quest(self, name):
        """Removes a quest from the active quest log by its exact name."""
        if not hasattr(self.app.player, 'quests'):
            return
            
        initial_count = len(self.app.player.quests)
        
        # Filter out the quest with the matching name
        self.app.player.quests = [q for q in self.app.player.quests if q.get("name", "").lower() != name.lower()]
        
        # Only refresh if a quest was actually removed
        if len(self.app.player.quests) < initial_count:
            self.refresh_display()
            
    def get_text(self):
        """
        Returns the raw text of the active quests from the display.
        This allows ai_manager.py to automatically fetch it for the context window!
        """
        return self.text_display.toPlainText()