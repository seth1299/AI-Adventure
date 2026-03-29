# qt_ui/story_panel.py
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QSizePolicy,
    QFrame,
    QProgressBar # Added for visual stats
    # QMenu removed as it's now handled by MainWindow
)

class StoryPanel(QWidget):
    send_requested = Signal(str)
    # Menu signals removed as MainWindow handles them via its MenuBar natively

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._status_cache = {
            "turn": "1",
            "location": "Unknown",
            "day": "Day 1",
            "time": "Morning",
            "dynamic_stats": []
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ---- Header (Status + Progress Bars on newlines) ----
        self.header_layout = QVBoxLayout()
        self.header_layout.setSpacing(4)

        # Base Status text (Turn, Location, Time)
        self.lbl_base_status = QLabel()
        self.lbl_base_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Style it to stand out slightly from the progress bars below it
        self.lbl_base_status.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
        self.header_layout.addWidget(self.lbl_base_status)

        # Container for the dynamically generated progress bars
        self.stats_layout = QVBoxLayout()
        self.stats_layout.setSpacing(2)
        self.header_layout.addLayout(self.stats_layout)

        root.addLayout(self.header_layout)

        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        # ---- Output log ----
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.txt_log.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, 'Courier New', monospace;
                font-size: 14px; /* Adjust size to your preference */
            }
        """)
        root.addWidget(self.txt_log, stretch=1)

        # ---- Input row ----
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("What do you do next?")
        self.txt_input.returnPressed.connect(self._emit_send)
        input_row.addWidget(self.txt_input, stretch=1)

        self.btn_send = QPushButton("Send")
        self.btn_send.setFixedWidth(100)
        self.btn_send.clicked.connect(self._emit_send)
        input_row.addWidget(self.btn_send)

        root.addLayout(input_row)

        # Initial UI render
        self._update_status_ui()

    def append_text(self, text: str) -> None:
        #if not text:
        #    return
        self.txt_log.append(text)
        self._scroll_to_bottom()

    def set_status(self, *, turn=None, location=None, day=None, time=None, dynamic_stats=None):
        if turn is not None: self._status_cache["turn"] = str(turn)
        if location is not None: self._status_cache["location"] = str(location)
        if day is not None: self._status_cache["day"] = str(day)
        if time is not None: self._status_cache["time"] = str(time)
        if dynamic_stats is not None: self._status_cache["dynamic_stats"] = dynamic_stats 
        
        self._update_status_ui()

    def _update_status_ui(self) -> None:
        """Rebuilds the status text and dynamically creates progress bars for stats."""
        s = self._status_cache
        if not "Day" in s['day']: s['day'] = "Day: " + s['day']
        
        # 1. Update the top standard text
        base_str = f"Turn: {s['turn']} \nLocation: {s['location']} \n{s['day']} \n{s['time']}"
        self.lbl_base_status.setText(base_str)
        
        # 2. Safely clear old progress bars
        while self.stats_layout.count() > 0:
            item = self.stats_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                
        # 3. Create new progress bars for each enabled stat
        for st in s.get("dynamic_stats", []):
            if st.get("enabled", True):
                pb = QProgressBar()
                pb.setRange(0, 100) # Assumes stats are max 100 as per your previous design
                
                # Safely parse the value
                try:
                    val = int(st['value'])
                except ValueError:
                    val = 0
                    
                pb.setValue(val)
                # Formats text as: "Stat Name: 75%" 
                pb.setFormat(f"{st['name']}: %p%") 
                pb.setTextVisible(True)
                pb.setFixedHeight(18) # Keeps the bars sleek
                
                if val > 50:
                    bar_color = "#4CAF50" # Green
                elif val > 25:
                    bar_color = "#FF9800" # Orange/Yellow
                else:
                    bar_color = "#F44336" # Red
                    
                # Apply a custom stylesheet to this specific progress bar
                pb.setStyleSheet(f"""
                    QProgressBar {{
                        border: 1px solid #555;
                        border-radius: 4px;
                        text-align: center;
                        background-color: #333; /* Dark background for the empty track */
                        color: white; /* Text color */
                        font-weight: bold;
                    }}
                    QProgressBar::chunk {{
                        background-color: {bar_color};
                        border-radius: 3px;
                    }}
                """)
                
                self.stats_layout.addWidget(pb)

    def get_log_text(self) -> str:
        return self.txt_log.toPlainText()

    def set_log_text(self, text: str) -> None:
        self.txt_log.setPlainText(text or "")
        self._scroll_to_bottom()
        
    def set_controls_state(self, enabled: bool, status_text: str | None = None) -> None:
        """Enable/disable input controls. Optionally updates placeholder text."""
        self.txt_input.setEnabled(enabled)
        self.btn_send.setEnabled(enabled)
        # self.btn_menu removed

        if enabled:
            self.txt_input.setPlaceholderText("What do you do next?")
        else:
            if status_text is not None:
                self.txt_input.setPlaceholderText(status_text)

    def print_text(self, text: str, *, sender: str = "GM") -> None:
        #if not text or text == "":
        #    return
        #prefix = f"{sender}: " if sender else ""
        self.append_text(f"{text}")

    def _emit_send(self) -> None:
        text = (self.txt_input.text() or "").strip()
        if not text:
            return
        self.txt_input.clear()
        self.send_requested.emit(text)

    def _scroll_to_bottom(self) -> None:
        cursor = self.txt_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.txt_log.setTextCursor(cursor)