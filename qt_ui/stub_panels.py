# qt_ui/stub_panels.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class StubPanel(QWidget):
    """Placeholder widget used while we migrate each CTk tab into Qt."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        lbl = QLabel(title)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lbl.setWordWrap(True)

        hint = QLabel(
            "This panel is a stub.\n\n"
            "Next steps:\n"
            "- Replace this with a real Qt panel for this feature.\n"
            "- Wire it into the same save/load paths used by the current CTk version."
        )
        hint.setWordWrap(True)

        layout.addWidget(lbl)
        layout.addWidget(hint)
        layout.addStretch(1)