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
)


class StoryPanel(QWidget):
    """
    A Qt version of the Story tab.

    This is intentionally minimal to get the Qt migration rolling:
    - Status line
    - Output log
    - Input line + Send button
    - Menu button (signal only for now)
    """

    send_requested = Signal(str)
    menu_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._status_cache = {
            "turn": "1",
            "location": "Unknown",
            "day": "Day 1",
            "time": "Morning",
            "nutrition": "100",
            "stamina": "100",
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ---- Header (status + menu) ----
        header = QHBoxLayout()
        header.setSpacing(10)

        self.btn_menu = QPushButton("Menu")
        self.btn_menu.setFixedWidth(80)
        self.btn_menu.clicked.connect(self.menu_requested.emit)
        header.addWidget(self.btn_menu, alignment=Qt.AlignmentFlag.AlignLeft)

        self.lbl_status = QLabel(self._format_status_text())
        self.lbl_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self.lbl_status)

        root.addLayout(header)

        # Optional separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        # ---- Output log ----
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        root.addWidget(self.txt_log, stretch=1)

        # ---- Input row ----
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Type your action...")
        self.txt_input.returnPressed.connect(self._emit_send)
        input_row.addWidget(self.txt_input, stretch=1)

        self.btn_send = QPushButton("Send")
        self.btn_send.setFixedWidth(100)
        self.btn_send.clicked.connect(self._emit_send)
        input_row.addWidget(self.btn_send)

        root.addLayout(input_row)

    # ---- Public helpers (mirror-ish of StoryTab capabilities) ----

    def append_text(self, text: str) -> None:
        if not text:
            return
        self.txt_log.append(text)
        self._scroll_to_bottom()

    def set_status(
        self,
        *,
        turn: str | None = None,
        location: str | None = None,
        day: str | None = None,
        time: str | None = None,
        nutrition: str | None = None,
        stamina: str | None = None,
    ) -> None:
        if turn is not None:
            self._status_cache["turn"] = str(turn)
        if location is not None:
            self._status_cache["location"] = str(location)
        if day is not None:
            self._status_cache["day"] = str(day)
        if time is not None:
            self._status_cache["time"] = str(time)
        if nutrition is not None:
            self._status_cache["nutrition"] = str(nutrition)
        if stamina is not None:
            self._status_cache["stamina"] = str(stamina)

        self.lbl_status.setText(self._format_status_text())

    def get_log_text(self) -> str:
        return self.txt_log.toPlainText()

    def set_log_text(self, text: str) -> None:
        self.txt_log.setPlainText(text or "")
        self._scroll_to_bottom()
        
    def set_controls_state(self, enabled: bool, status_text: str | None = None) -> None:
        """Enable/disable input controls. Optionally updates placeholder text."""
        self.txt_input.setEnabled(enabled)
        self.btn_send.setEnabled(enabled)
        self.btn_menu.setEnabled(enabled)

        if status_text is not None:
            if enabled:
                self.txt_input.setPlaceholderText("Type your action...")
            else:
                self.txt_input.setPlaceholderText(status_text)

    def print_text(self, text: str, *, sender: str = "GM") -> None:
        """Convenience helper to mimic the old StoryTab API."""
        if not text:
            return
        prefix = f"{sender}: " if sender else ""
        self.append_text(f"{prefix}{text}")

    # ---- Internals ----

    def _emit_send(self) -> None:
        text = (self.txt_input.text() or "").strip()
        if not text:
            return
        self.txt_input.clear()
        self.send_requested.emit(text)

    def _format_status_text(self) -> str:
        s = self._status_cache
        # Keep it simple for now; we can match your CTk layout later.
        return (
            f"Turn: {s['turn']} | Location: {s['location']} | "
            f"{s['day']} | {s['time']} | Nutrition: {s['nutrition']} | Stamina: {s['stamina']}"
        )

    def _scroll_to_bottom(self) -> None:
        cursor = self.txt_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.txt_log.setTextCursor(cursor)