# qt_ui/calendar_dialog.py
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLineEdit, QSpinBox, QLabel, QScrollArea, QWidget, 
    QTextEdit, QTabWidget, QMessageBox
)
from PySide6.QtCore import Qt

class MonthRow(QWidget):
    """A single row representing one month in the calendar."""
    def __init__(self, parent=None, name="", days=30, season=""):
        super().__init__(parent)
        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 5, 0, 5)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Month Name")
        self.name_input.setText(name)
        
        self.days_input = QSpinBox()
        self.days_input.setRange(1, 1000) 
        self.days_input.setValue(days)
        self.days_input.setSuffix(" Days")
        
        self.season_input = QLineEdit()
        self.season_input.setPlaceholderText("Season (e.g. Winter)")
        self.season_input.setText(season)
        
        self.btn_remove = QPushButton("X")
        self.btn_remove.setFixedWidth(30)

        self.row_layout.addWidget(QLabel("Name:"))
        self.row_layout.addWidget(self.name_input, stretch=2)
        self.row_layout.addWidget(QLabel("Length:"))
        self.row_layout.addWidget(self.days_input)
        self.row_layout.addWidget(QLabel("Season:"))
        self.row_layout.addWidget(self.season_input, stretch=2)
        self.row_layout.addWidget(self.btn_remove)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "days": self.days_input.value(),
            "season": self.season_input.text().strip()
        }

class CalendarManagerDialog(QDialog):
    """Dialog to manage custom weekdays and months."""
    def __init__(self, parent=None, existing_calendar=None):
        super().__init__(parent)
        self.setWindowTitle("Manage World Calendar")
        self.setMinimumWidth(550)
        self.setMinimumHeight(400)

        self.main_layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        # --- Tab 1: Weekdays ---
        self.tab_weekdays = QWidget()
        self.week_layout = QVBoxLayout(self.tab_weekdays)
        self.week_layout.addWidget(QLabel("List your days of the week, one per line (Top to Bottom)."))
        
        self.weekdays_text = QTextEdit()
        self.weekdays_text.setPlaceholderText("Monday\nTuesday\nWednesday...")
        self.week_layout.addWidget(self.weekdays_text)
        self.tabs.addTab(self.tab_weekdays, "Days of the Week")

        # --- Tab 2: Months ---
        self.tab_months = QWidget()
        self.months_layout = QVBoxLayout(self.tab_months)
        self.months_layout.addWidget(QLabel("Define the months of your year in order."))
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.scroll_widget)
        self.months_layout.addWidget(self.scroll_area)
        
        self.btn_add_month = QPushButton("+ Add Month")
        self.btn_add_month.clicked.connect(lambda: self.add_month_row())
        self.months_layout.addWidget(self.btn_add_month)
        self.tabs.addTab(self.tab_months, "Months & Seasons")

        # --- Bottom Buttons ---
        self.btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save && Close")
        self.btn_save.clicked.connect(self.save_and_close)
        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_save)
        self.main_layout.addLayout(self.btn_layout)

        self.rows = []

        # Load existing data
        if existing_calendar:
            weekdays = existing_calendar.get("weekdays", [])
            self.weekdays_text.setPlainText("\n".join(weekdays))
            
            for m in existing_calendar.get("months", []):
                self.add_month_row(m.get("name", ""), m.get("days", 30), m.get("season", ""))
        else:
            # Provide standard defaults if completely blank
            self.weekdays_text.setPlainText("Monday\nTuesday\nWednesday\nThursday\nFriday\nSaturday\nSunday")
            self.add_month_row("Month 1", 30, "Spring")

    def add_month_row(self, name="", days=30, season=""):
        row = MonthRow(name=name, days=days, season=season)
        self.rows_layout.addWidget(row)
        self.rows.append(row)
        row.btn_remove.clicked.connect(lambda: self.remove_month_row(row))

    def remove_month_row(self, row):
        self.rows_layout.removeWidget(row)
        self.rows.remove(row)
        row.deleteLater()

    def save_and_close(self):
        """Packages up the data and closes the dialog."""
        raw_weekdays = self.weekdays_text.toPlainText().strip().split("\n")
        final_weekdays = [day.strip() for day in raw_weekdays if day.strip()]
        
        final_months = []
        for row in self.rows:
            data = row.get_data()
            if data["name"]: 
                final_months.append(data)
                
        if not final_weekdays or not final_months:
            QMessageBox.warning(self, "Validation Error", "You must have at least one weekday and one month.")
            return

        self.final_calendar_data = {
            "weekdays": final_weekdays,
            "months": final_months
        }
        self.accept()