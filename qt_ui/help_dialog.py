# qt_ui/help_dialog.py
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton
from PySide6.QtCore import Qt

class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Game Help & Manual")
        self.resize(600, 500) # Nice and readable size

        layout = QVBoxLayout(self)

        # Text Browser for formatted, scrollable text
        self.text_browser = QTextBrowser()
        layout.addWidget(self.text_browser)

        # Close Button
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(100)
        self.btn_close.clicked.connect(self.accept)
        layout.addWidget(self.btn_close, alignment=Qt.AlignmentFlag.AlignCenter)

        self._load_help_text()

    def _load_help_text(self):
        """You can customize this HTML string to be whatever you want!"""
        help_content = """
        <h2 style='color: #2e6c80;'>Welcome to AI RPG Adventure!</h2>
        <p>Here is a quick guide to understanding the game interface and mechanics:</p>

        <h3>Interface Tabs</h3>
        <ul>
            <li><b>Story:</b> The main console. Type your actions here to interact with the GM.</li>
            <li><b>Inventory:</b> Displays your items, dynamic wealth, and food reserves.</li>
            <li><b>Skills:</b> Shows your current skills (e.g. what your character is good at). Using them successfully in the story grants XP and levels them up, making them even stronger.</li>
            <li><b>Journal:</b> Keep track of your notes here. The A.I. will never read this tab, so you can write whatever you want in here without worrying about the A.I. "hallucinating" from anything written in here.</li>
            <li><b>Processing / Recipes:</b> Manage crafting, building, and long-term tasks. This is important for the A.I. to "remember" things between continuous hours of play.</li>
            
            <li><b>World & Character:</b> Your reference documents built during play.</li>
        </ul>

        <h3>Gameplay Tips</h3>
        <p>• You can add, edit, or remove custom stats (like Health or Sanity) using the <b>Menu -> Manage Tracked Stats</b> button. Make sure to include a description as specific as possible for each stat, even if it seems obvious to you, it can be worth it to explicitly tell the A.I. EXACTLY what you are envisioning for the Stat to do.</p>
        <p>• You can click "Menu" -> "Manage Currencies" to make your own system of currency for the game! You can add or remove however many units of currency you want, and as long as you correctly set how much each unit of currency is worth, the A.I. should be able to keep track of all of the currencies automatically for you.</p>
        <p>• Simply type what your character does or says naturally! The AI GM will figure out the rest.</p>
        <p>• You can type whatever you want into the "World" tab, but do keep in mind that whatever you put into the World tab, the A.I. will take as complete fact, so that can make the game as easy or as difficult as you want it to be.</p>
        """
        self.text_browser.setHtml(help_content)