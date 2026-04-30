# qt_ui/calendar_panel.py
from __future__ import annotations
import logging
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
import time_utils

class CalendarPanel(QWidget):
    """
    A read-only visual panel that renders the current in-game month as an HTML grid.
    """

    def __init__(self, parent: QWidget | None = None, app_context=None) -> None:
        super().__init__(parent)
        self.app = app_context

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ---- Toolbar ----
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.lbl_title = QLabel("Calendar")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        bar.addWidget(self.lbl_title, stretch=1)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setFixedWidth(90)
        self.btn_refresh.clicked.connect(self.refresh_display)
        bar.addWidget(self.btn_refresh)

        root.addLayout(bar)

        # ---- Display ----
        self.display = QTextBrowser()
        # Consolas is great for standard text, but Arial/sans-serif looks cleaner for HTML grids
        self.display.setFont(QFont("Arial", 11)) 
        root.addWidget(self.display, stretch=1)
        
    def _get_player(self):
        """Safely locate the Player object."""
        if not self.app: return None
        if hasattr(self.app, 'player'): return self.app.player
        if hasattr(self.app, 'app') and hasattr(self.app.app, 'player'): return self.app.app.player
        return None

    def refresh_display(self) -> None:
        """Constructs the HTML calendar grid based on current time."""
        player = self._get_player()
        if not player or not player.calendar_settings:
            self.display.setHtml("<p><i>(No calendar configured. Use the Game Menu to set one up.)</i></p>")
            return

        grid_data = time_utils.get_calendar_grid_data(player.day, player.calendar_settings)
        if not grid_data:
            self.display.setHtml("<p><i>(Calendar calculation error.)</i></p>")
            return

        weekdays = grid_data["weekdays"]
        columns = len(weekdays)

        # --- HTML Building ---
        html = [
            f"<h2 style='text-align: center; color: #4CAF50; margin-bottom: 2px;'>{grid_data['month_name']}</h2>",
            f"<h4 style='text-align: center; color: #aaaaaa; margin-top: 0px;'>Year {grid_data['year']} — {grid_data['season']}</h4>",
            "<table width='100%' border='1' cellspacing='0' cellpadding='8' style='border-collapse: collapse; border: 1px solid #555;'>",
            "<tr>"
        ]

        # 1. Header Row (Days of the week)
        for day_name in weekdays:
            # Truncate long names to keep the grid clean (e.g., "Wednesday" -> "Wed")
            #short_name = day_name[:3] if len(day_name) > 3 else day_name
            html.append(f"<th style='background-color: #333; color: white;'>{day_name}</th>")
        html.append("</tr><tr>")

        # 2. Empty padding for the start of the month
        current_col = 0
        for _ in range(grid_data["start_offset"]):
            html.append("<td style='background-color: #222;'></td>")
            current_col += 1

        # 3. Fill in the days
        for day_num in range(1, grid_data["month_total_days"] + 1):
            # Wrap to a new row if we hit the end of the week
            if current_col >= columns:
                html.append("</tr><tr>")
                current_col = 0

            # Highlight the current day!
            if day_num == grid_data["current_day"]:
                html.append(f"<td align='center' style='background-color: #4CAF50; color: white; font-weight: bold;'>{day_num}</td>")
            else:
                html.append(f"<td align='center'>{day_num}</td>")
                
            current_col += 1

        # 4. Empty padding for the end of the month
        while current_col < columns:
            html.append("<td style='background-color: #222;'></td>")
            current_col += 1

        html.append("</tr></table>")

        self.display.setHtml("".join(html))

    def set_base_path(self, base_path: str) -> None:
        """Dummy method to satisfy QtPanelAdapter expectations."""
        self.refresh_display()
        
    def get_text(self) -> str:
        """
        Returns a plain-text summary of the calendar.
        Provides the AI with contextual awareness of the date without needing 
        to read the complex HTML grid structure.
        """
        player = self._get_player()
        
        if player and player.calendar_settings:
            current_date = time_utils.calculate_calendar_date(player.day, player.calendar_settings)
            return f"The current in-game date is: {current_date}"
            
        return "No calendar configured."