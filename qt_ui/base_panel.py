import logging
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt

class BasePanel(QWidget):
    """
    Abstract base class for application UI panels.
    Encapsulates the standard toolbar layout, state management, and shared helper methods.
    """
    def __init__(self, title: str, parent: QWidget | None = None, app_context=None, show_save_button: bool = True):
        super().__init__(parent)
        self.app = app_context
        self.data_path: Path | None = None
        
        # --- Standard Layout Initialization ---
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 10, 10, 10)
        self.root_layout.setSpacing(8)

        # --- Toolbar ---
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setSpacing(8)

        self.lbl_title = QLabel(title)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_title.hide() 
        self.toolbar_layout.addWidget(self.lbl_title, stretch=1)

        self.lbl_state = QLabel("")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.toolbar_layout.addWidget(self.lbl_state)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setFixedWidth(90)
        self.btn_reload.clicked.connect(self.refresh_display)
        self.toolbar_layout.addWidget(self.btn_reload)

        self.btn_save = QPushButton("Save")
        self.btn_save.setFixedWidth(90)
        self.btn_save.clicked.connect(self._save_current)
        if not show_save_button:
            self.btn_save.hide()
        self.toolbar_layout.addWidget(self.btn_save)

        self.root_layout.addLayout(self.toolbar_layout)
        self._set_state("No save loaded")

    def _set_state(self, text: str) -> None:
        """Updates the status indicator label on the right side of the toolbar."""
        self.lbl_state.setText(text or "")

    def _get_player(self):
        """Safely locates and returns the active Player object from the application context."""
        if not self.app: 
            return None
        if hasattr(self.app, 'player'): 
            return self.app.player
        if hasattr(self.app, 'app') and hasattr(self.app.app, 'player'): 
            return self.app.app.player
        return None

    # --- Abstract Methods ---
    # These raise errors if a child class forgets to implement them.

    def set_base_path(self, save_folder: str | Path) -> None:
        """Resolves the directory for file I/O operations specific to this panel."""
        raise NotImplementedError("Subclasses must implement set_base_path.")

    def refresh_display(self) -> None:
        """Reads current data and redraws the UI components."""
        raise NotImplementedError("Subclasses must implement refresh_display.")

    def get_text(self) -> str:
        """Returns a string representation of the panel's data for the AI Context Manager."""
        raise NotImplementedError("Subclasses must implement get_text.")
        
    def _save_current(self) -> None:
        """Triggered by the manual Save button. Implementations vary by panel data type."""
        pass