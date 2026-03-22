# qt_ui/stats_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLineEdit, QSpinBox, QLabel, QScrollArea, QWidget, QCheckBox
)
from PySide6.QtCore import Qt

class StatRow(QWidget):
    def __init__(self, parent=None, name="", value=100, enabled=True):
        super().__init__(parent)
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 5, 0, 5)

        # Toggle Checkbox
        self.cb_enabled = QCheckBox()
        self.cb_enabled.setChecked(enabled)
        self.cb_enabled.setToolTip("Track this stat in the UI and AI Context?")

        # Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Health, Mana, Sanity")
        self.name_input.setText(name)
        
        # Value (Allows negatives just in case you want to track things like 'Corruption')
        self.value_input = QSpinBox()
        self.value_input.setRange(-10000, 10000) 
        self.value_input.setValue(value)
        
        # Remove
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(30)

        self.row_layout.addWidget(self.cb_enabled)
        self.row_layout.addWidget(QLabel("Name:"))
        self.row_layout.addWidget(self.name_input, stretch=2)
        self.row_layout.addWidget(QLabel("Value:"))
        self.row_layout.addWidget(self.value_input, stretch=1)
        self.row_layout.addWidget(self.btn_remove)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "value": self.value_input.value(),
            "enabled": self.cb_enabled.isChecked()
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
        self.btn_add.clicked.connect(self.add_stat_row)
        
        self.btn_save = QPushButton("Save && Close")
        self.btn_save.clicked.connect(self.save_and_close)
        
        self.btn_layout.addWidget(self.btn_add)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_save)
        self.main_layout.addLayout(self.btn_layout)

        self.rows = []

        if existing_stats:
            for stat in existing_stats:
                self.add_stat_row(stat.get("name", ""), stat.get("value", 100), stat.get("enabled", True))
        else:
            self.add_stat_row("Nutrition", 100, True)
            self.add_stat_row("Stamina", 100, True)

    def add_stat_row(self, name="", value=100, enabled=True):
        row = StatRow(name=name, value=value, enabled=enabled)
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