# qt_ui/currency_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLineEdit, QSpinBox, QLabel, QScrollArea, QWidget, QMessageBox
)
from PySide6.QtCore import Qt

class CurrencyRow(QWidget):
    """A single row representing one currency type."""
    def __init__(self, parent=None, name="", value=1, is_baseline=False):
        super().__init__(parent)
        self.is_baseline = is_baseline
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 5, 0, 5)

        # Currency Name Input
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Copper Piece")
        self.name_input.setText(name)
        
        # Currency Value Input
        self.value_input = QSpinBox()
        self.value_input.setRange(1, 1000000) 
        self.value_input.setValue(value)
        self.value_input.setSuffix(" Base Units")
        
        # Remove Button
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(30)

        # --- NEW: Lock down the baseline row ---
        if self.is_baseline:
            self.value_input.setEnabled(False)      # Lock the value at 1
            self.btn_remove.setEnabled(False)       # Disable the remove button
            # Optional: Make it visually obvious it's the base unit
            self.value_input.setToolTip("The Base Unit must always be worth 1.")

        self.row_layout.addWidget(QLabel("Name:"))
        self.row_layout.addWidget(self.name_input, stretch=2)
        self.row_layout.addWidget(QLabel(" Worth:"))
        self.row_layout.addWidget(self.value_input, stretch=1)
        self.row_layout.addWidget(self.btn_remove)

    def get_data(self):
        """Returns the data for this specific row."""
        return {
            "name": self.name_input.text().strip(),
            "value": self.value_input.value()
        }

class CurrencyManagerDialog(QDialog):
    """The pop-up sub-menu for managing world currencies."""
    def __init__(self, parent=None, existing_currencies=None):
        super().__init__(parent)
        self.setWindowTitle("Manage World Currency")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)

        self.main_layout = QVBoxLayout(self)
        
        info_label = QLabel(
            "Define your currencies relative to your cheapest coin.\n"
            "For example, if a Copper is your lowest, type \"Copper\" into the \"1 base unit\" row.\n"
            "If a Silver is worth 10 Coppers, type \"Silver\" followed by \"10 base units\"."
        )
        info_label.setWordWrap(True)
        self.main_layout.addWidget(info_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        self.main_layout.addWidget(self.scroll_area)

        self.btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Currency")
        self.btn_add.clicked.connect(self.add_currency_row)
        
        self.btn_save = QPushButton("Save && Close")
        self.btn_save.clicked.connect(self.save_and_close)
        
        self.btn_layout.addWidget(self.btn_add)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_save)
        self.main_layout.addLayout(self.btn_layout)

        self.rows = []

        # Load existing currencies or provide default starting rows
        if existing_currencies:
            has_baseline = False
            for cur in existing_currencies:
                val = cur.get("value", 1)
                
                # The first currency with a value of 1 becomes our baseline
                is_base = (val == 1) and not has_baseline
                if is_base: has_baseline = True
                
                self.add_currency_row(cur.get("name", ""), val, is_baseline=is_base)
                
            # Fallback just in case they somehow loaded a file without a baseline
            if not has_baseline:
                self.add_currency_row("Base Coin", 1, is_baseline=True)
        else:
            self.add_currency_row("Copper Piece", 1, is_baseline=True) # First one is locked
            self.add_currency_row("Silver Piece", 10)

    def add_currency_row(self, name="", value=1, is_baseline=False):
        """Adds a new currency row to the UI."""
        if len(self.rows) >= 9:
            QMessageBox.warning(self, "Limit Reached", "You can only have up to 9 currencies.")
            return

        row = CurrencyRow(name=name, value=value, is_baseline=is_baseline)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        
        row.btn_remove.clicked.connect(lambda: self.remove_currency_row(row))

    def remove_currency_row(self, row):
        """Removes a row from the UI and the tracking list."""
        if row.is_baseline:
            return # Extra safeguard: Do not remove baseline rows!
            
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

    def save_and_close(self):
        """Packages up the data and closes the dialog."""
        self.final_currency_data = []
        for row in self.rows:
            data = row.get_data()
            
            # --- NEW: Prevent the baseline unit from having a blank name ---
            if row.is_baseline and not data["name"]:
                QMessageBox.warning(self, "Validation Error", "The Base Unit (Value 1) cannot have a blank name!")
                return # Stops the save process and keeps the dialog open
                
            if data["name"]:  # Only save rows that have a name typed in
                self.final_currency_data.append(data)
                
        # Sort them by value so they are mathematically ordered
        self.final_currency_data.sort(key=lambda x: x["value"])
        self.accept()