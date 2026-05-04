# qt_ui/creation_wizard.py
from PySide6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QFormLayout, 
    QLabel, QLineEdit, QTextEdit, QCheckBox, 
    QScrollArea, QWidget, QGroupBox, QHBoxLayout, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt
from qt_ui.currency_dialog import CurrencyRow
from qt_ui.stats_dialog import StatRow

class WorldPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 1: World Setting")
        self.setSubTitle("Define the parameters of the world you will be exploring. Leave blank for the A.I. to decide.")
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("World Setting (e.g., A dark fantasy continent shattered by a magical cataclysm):"))
        self.setting_input = QTextEdit()
        self.setting_input.setTabChangesFocus(True) # Fixes the Tab key issue
        layout.addWidget(self.setting_input)
        
        layout.addWidget(QLabel("Genre/Tone (e.g., Grimdark Fantasy, Sci-Fi Cyberpunk, Cozy Slice-of-Life):"))
        self.genre_input = QLineEdit()
        layout.addWidget(self.genre_input)
        
        layout.addWidget(QLabel("Tech Level (e.g., Iron Age, Steampunk, Futuristic Sci-Fi):"))
        self.tech_input = QLineEdit()
        layout.addWidget(self.tech_input)
        
        layout.addWidget(QLabel("Species/Races (e.g., Humans, Elves, Dwarves, and half-dragon hybrids):"))
        self.species_input = QTextEdit()
        self.species_input.setTabChangesFocus(True)
        layout.addWidget(self.species_input)

class PillarsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 2: Game Focus")
        self.setSubTitle("Select the main pillars you want this adventure to focus on.")
        
        layout = QVBoxLayout(self)
        
        self.combat_cb = QCheckBox("Combat")
        self.exploration_cb = QCheckBox("Exploration")
        self.trading_cb = QCheckBox("Trading / Economy")
        self.social_cb = QCheckBox("Social / Roleplay")
        
        layout.addWidget(self.combat_cb)
        layout.addWidget(self.exploration_cb)
        layout.addWidget(self.trading_cb)
        layout.addWidget(self.social_cb)

class CharacterPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 5: Character Bio")
        self.setSubTitle("Tell me about your character. Leave blank for the AI to decide.")
        
        layout = QVBoxLayout(self)
        
        # Using a horizontal layout just for the short fields to save vertical space
        short_fields_layout = QFormLayout()
        
        self.name_input = QLineEdit()
        self.age_input = QLineEdit()
        self.gender_input = QLineEdit()
        self.pronouns_input = QLineEdit()
        self.orientation_input = QLineEdit()
        
        short_fields_layout.addRow("Name:", self.name_input)
        short_fields_layout.addRow("Age:", self.age_input)
        short_fields_layout.addRow("Gender:", self.gender_input)
        short_fields_layout.addRow("Pronouns:", self.pronouns_input)
        short_fields_layout.addRow("Orientation:", self.orientation_input)
        
        layout.addLayout(short_fields_layout)
        
        layout.addWidget(QLabel("\nBackground (Brief history, backstory, or important NPCs):"))
        self.background_input = QTextEdit()
        self.background_input.setTabChangesFocus(True)
        layout.addWidget(self.background_input)

class SkillsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 6: Skills")
        self.setSubTitle("Define your starting skills. Leave descriptions blank to let the AI decide.")
        
        # We need a scroll area because there are 16 skills
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        content = QWidget()
        self.scroll_layout = QVBoxLayout(content)
        
        self.skill_inputs = [] # Will store tuples of (level, name_widget, desc_widget)

        # Helper to generate the skill boxes
        def add_skill_section(level, count, title):
            group = QGroupBox(f"Level {level} - {title} ({count} Skills)")
            g_layout = QFormLayout(group)
            for i in range(count):
                row_layout = QHBoxLayout()
                name_input = QLineEdit()
                name_input.setPlaceholderText(f"Skill Name")
                desc_input = QLineEdit()
                desc_input.setPlaceholderText(f"Optional Description")
                
                row_layout.addWidget(name_input, stretch=1)
                row_layout.addWidget(desc_input, stretch=2)
                g_layout.addRow(f"Skill {i+1}:", row_layout)
                
                self.skill_inputs.append((level, name_input, desc_input))
            self.scroll_layout.addWidget(group)

        add_skill_section(5, 1, "Master")
        add_skill_section(4, 2, "Excellent")
        add_skill_section(3, 3, "Very Good")
        add_skill_section(2, 4, "Good")
        add_skill_section(1, 6, "Decent")
        
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

class FinalPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 7: Final Details")
        self.setSubTitle("Where do you begin, and do you have any final rules?")
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Starting Location (e.g., A dingy tavern in the lower rings of the city):"))
        self.location_input = QLineEdit()
        layout.addWidget(self.location_input)
        
        layout.addWidget(QLabel("\nFinal Comments/Rules (e.g., Magic is strictly illegal. I have a pet dog named Barnaby):"))
        self.comments_input = QTextEdit()
        self.comments_input.setTabChangesFocus(True)
        layout.addWidget(self.comments_input)
        
class CurrencyPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 3: World Currencies")
        self.setSubTitle("Define your currencies relative to your cheapest coin. Leave blank for AI generation.")
        
        layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.rows_layout = QVBoxLayout(content)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        
        self.rows = []
        
        btn_add = QPushButton("+ Add Currency")
        btn_add.clicked.connect(lambda: self.add_row())
        layout.addWidget(btn_add)
        layout.addWidget(scroll)
        
        # Default starting row (Blank, allowing the AI to take over if left alone)
        self.add_row("", 1, is_baseline=True)

    def add_row(self, name="", value=1, is_baseline=False):
        if len(self.rows) >= 9:
            QMessageBox.warning(self, "Limit Reached", "You can only have up to 9 currencies.")
            return

        row = CurrencyRow(name=name, value=value, is_baseline=is_baseline)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_row(row))

    def remove_row(self, row):
        if row.is_baseline: return
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()
        
    # Notice we completely removed the validatePage() function!


class StatsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Step 4: Tracked Stats")
        self.setSubTitle("Add, remove, or toggle tracked statuses (e.g. Health, AC). Leave blank for AI generation.")
        
        layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.rows_layout = QVBoxLayout(content)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        
        self.rows = []
        
        btn_add = QPushButton("+ Add Stat")
        btn_add.clicked.connect(lambda: self.add_row())
        layout.addWidget(btn_add)
        layout.addWidget(scroll)
        
        # Default starting rows

    def add_row(self, name="", value=100, enabled=True, desc=""):
        row = StatRow(name=name, value=value, enabled=enabled, desc=desc)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_row(row))

    def remove_row(self, row):
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

class CreationWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setWindowTitle("New Adventure Setup")
        self.resize(700, 600)
        
        # --- ROBUST DARK THEME STYLESHEET ---
        self.setStyleSheet("""
            QWizard, QWizardPage {
                background-color: #202124;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-weight: bold;
                margin-top: 5px;
            }
            QLineEdit, QTextEdit {
                background-color: #171717;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px;
            }
            /* Explicitly style the placeholder tooltips so they are visible */
            QLineEdit::placeholder, QTextEdit::placeholder {
                color: #8a8a8a;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #3a8ccf;
                background-color: #252525;
            }
        """)
        
        self.world_page = WorldPage()
        self.pillars_page = PillarsPage()
        self.currency_page = CurrencyPage()
        self.stats_page = StatsPage()
        self.char_page = CharacterPage()
        self.skills_page = SkillsPage()
        self.final_page = FinalPage()
        
        self.addPage(self.world_page)
        self.addPage(self.pillars_page)
        self.addPage(self.currency_page)
        self.addPage(self.stats_page)
        self.addPage(self.char_page)
        self.addPage(self.skills_page)
        self.addPage(self.final_page)

    def get_wizard_data(self) -> dict:
        """Extracts all data from the wizard pages into a neat dictionary."""
        
        # Gather focus pillars
        pillars = []
        if self.pillars_page.combat_cb.isChecked(): pillars.append("Combat")
        if self.pillars_page.exploration_cb.isChecked(): pillars.append("Exploration")
        if self.pillars_page.trading_cb.isChecked(): pillars.append("Trading/Economy")
        if self.pillars_page.social_cb.isChecked(): pillars.append("Social/Roleplay")
        
        currencies = [r.get_data() for r in self.currency_page.rows if r.get_data()["name"].strip()]
        currencies.sort(key=lambda x: x["value"]) # Sort mathematically
        
        stats = [r.get_data() for r in self.stats_page.rows if r.get_data()["name"].strip()]

        # Gather skills
        skills = []
        for level, name_w, desc_w in self.skills_page.skill_inputs:
            # If the user leaves it blank, we pass "Unknown Skill Name" to force the AI to invent one
            s_name = name_w.text().strip() or "Unknown Skill Name"
            skills.append({
                "level": level,
                "name": s_name,
                "desc": desc_w.text().strip() or "Unknown Skill Description"
            })

        return {
            "world": {
                "setting": self.world_page.setting_input.toPlainText().strip(),
                "genre": self.world_page.genre_input.text().strip(),
                "tech": self.world_page.tech_input.text().strip(),
                "species": self.world_page.species_input.toPlainText().strip(),
            },
            "focus": pillars,
            "currencies": currencies,
            "stats": stats,
            "character": {
                "name": self.char_page.name_input.text().strip(),
                "age": self.char_page.age_input.text().strip(),
                "gender": self.char_page.gender_input.text().strip(),
                "pronouns": self.char_page.pronouns_input.text().strip(),
                "orientation": self.char_page.orientation_input.text().strip(),
                "background": self.char_page.background_input.toPlainText().strip(),
            },
            "skills": skills,
            "starting_location": self.final_page.location_input.text().strip(),
            "final_comments": self.final_page.comments_input.toPlainText().strip()
        }