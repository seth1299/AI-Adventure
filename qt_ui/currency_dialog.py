# qt_ui/currency_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLineEdit, QSpinBox, QLabel, QScrollArea, QWidget, QMessageBox
)
from PySide6.QtCore import Qt

class CurrencyRow(QWidget):
    """A single row representing one currency type."""
    def __init__(self, parent=None, name="", value=1):
        super().__init__(parent)
        if self == None: 
            return
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 5, 0, 5)

        # Currency Name Input
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Gold Piece")
        self.name_input.setText(name)
        
        # Currency Value Input (Using QSpinBox to enforce integers)
        self.value_input = QSpinBox()
        self.value_input.setRange(1, 1000000) # Prevents 0 or negative values
        self.value_input.setValue(value)
        self.value_input.setSuffix(" Base Units")
        
        # Remove Button
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(30)
        # We will connect this click event in the main dialog

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

        # Main Layout
        self.main_layout = QVBoxLayout(self)
        
        # Helper Text
        info_label = QLabel(
            "Define your currencies relative to your cheapest coin.\n"
            "For example, if a Copper is your lowest, set its worth to 1.\n"
            "If a Silver is worth 10 Coppers, set its worth to 10."
        )
        info_label.setWordWrap(True)
        self.main_layout.addWidget(info_label)

        # Scrollable Area (In case they add a lot of currencies)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        
        self.main_layout.addWidget(self.scroll_area)

        # Buttons Layout
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

        # Load existing currencies or provide a default starting row
        if existing_currencies:
            for cur in existing_currencies:
                self.add_currency_row(cur.get("name"), cur.get("value"))
        else:
            self.add_currency_row("Copper Piece", 1) # Default baseline
            self.add_currency_row("Silver Piece", 10)

    def add_currency_row(self, name="", value=1):
        """Adds a new currency row to the UI."""
        # Optional: Cap it at 9 if you still want to enforce a limit
        if len(self.rows) >= 9:
            QMessageBox.warning(self, "Limit Reached", "You can only have up to 9 currencies.")
            return

        row = CurrencyRow(name=name, value=value)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        
        # Connect the remove button to delete this specific row
        row.btn_remove.clicked.connect(lambda: self.remove_currency_row(row))

    def remove_currency_row(self, row):
        """Removes a row from the UI and the tracking list."""
        if len(self.rows) <= 1:
            QMessageBox.warning(self, "Cannot Remove", "You must have at least one currency!")
            return
            
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

    def save_and_close(self):
        """Packages up the data and closes the dialog."""
        self.final_currency_data = []
        for row in self.rows:
            data = row.get_data()
            if data["name"]:  # Only save rows that have a name typed in
                self.final_currency_data.append(data)
                
        # Sort them by value so they are mathematically ordered
        self.final_currency_data.sort(key=lambda x: x["value"])
        
        self.accept() # Built-in QDialog method to close with "Accepted" status