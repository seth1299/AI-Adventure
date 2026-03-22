# qt_ui/stats_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLineEdit, QSpinBox, QLabel, QScrollArea, QWidget, QCheckBox, QFrame
)
from PySide6.QtCore import Qt

class StatRow(QFrame):
    # --- NEW: Added desc parameter ---
    def __init__(self, parent=None, name="", value=100, enabled=True, desc=""):
        super().__init__(parent)
        
        # Make it look like a distinct card
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)

        # --- Top Row (Name and Value) ---
        self.top_row = QHBoxLayout()

        self.cb_enabled = QCheckBox()
        self.cb_enabled.setChecked(enabled)
        self.cb_enabled.setToolTip("Track this stat in the UI and AI Context?")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Health, Mana, Sanity")
        self.name_input.setText(name)
        
        self.value_input = QSpinBox()
        self.value_input.setRange(-10000, 10000) 
        self.value_input.setValue(value)
        
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(30)

        self.top_row.addWidget(self.cb_enabled)
        self.top_row.addWidget(QLabel("Name:"))
        self.top_row.addWidget(self.name_input, stretch=2)
        self.top_row.addWidget(QLabel("Value:"))
        self.top_row.addWidget(self.value_input, stretch=1)
        self.top_row.addWidget(self.btn_remove)

        # --- Bottom Row (AI Description) ---
        self.bottom_row = QHBoxLayout()
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("AI Rules (e.g. 'Max 100. Decreases when taking damage.')")
        self.desc_input.setText(desc)
        
        self.bottom_row.addWidget(QLabel("AI Rules:"))
        self.bottom_row.addWidget(self.desc_input, stretch=1)

        # Add both rows to the card
        self.main_layout.addLayout(self.top_row)
        self.main_layout.addLayout(self.bottom_row)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "value": self.value_input.value(),
            "enabled": self.cb_enabled.isChecked(),
            "desc": self.desc_input.text().strip() # <--- NEW: Grab the description
        }
class StatsManagerDialog(QDialog):
    def __init__(self, parent=None, existing_stats=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Tracked Stats")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.addWidget(QLabel("Add, remove, or toggle tracked statuses (e.g. Health, AC, Nutrition)."))

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        self.main_layout.addWidget(self.scroll_area)

        self.btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Stat")
        self.btn_add.clicked.connect(lambda: self.add_stat_row())
        
        self.btn_save = QPushButton("Save && Close")
        self.btn_save.clicked.connect(self.save_and_close)
        
        self.btn_layout.addWidget(self.btn_add)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_save)
        self.main_layout.addLayout(self.btn_layout)

        self.rows = []

        if existing_stats is not None:
            for stat in existing_stats:
                self.add_stat_row(
                    stat.get("name", ""), 
                    stat.get("value", 100), 
                    stat.get("enabled", True),
                    stat.get("desc", "")
                )
        else:
            self.add_stat_row("Nutrition", 100, True, "Represents how well-fed the character is. Max 100.")
            self.add_stat_row("Stamina", 100, True, "Represents physical energy. Depletes from actions. Max 100.")

    def add_stat_row(self, name="", value=100, enabled=True,  desc=""):
        row = StatRow(name=name, value=value, enabled=enabled, desc=desc)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_stat_row(row))

    def remove_stat_row(self, row):
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

    def save_and_close(self):
        self.final_stats_data = []
        for row in self.rows:
            data = row.get_data()
            if data["name"]: 
                self.final_stats_data.append(data)
        self.accept()