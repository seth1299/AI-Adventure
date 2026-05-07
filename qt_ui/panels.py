"""Centralized Qt panel classes for AI RPG Adventure.

This module replaces the individual ``*_panel.py`` files. It keeps each panel as
its own class while sharing common toolbar, player-context, file-path, and table
formatting behavior through inheritance.
"""

from __future__ import annotations

import asyncio
import copy
import csv
import logging
import os
import re
import tempfile
import textwrap
import threading
import uuid
from pathlib import Path
from typing import Any, ClassVar

import edge_tts
import markdown
import pygame
import time_utils
from file_manager import FileManager
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from tabulate import tabulate


class BasePanel(QWidget):
    """Shared base class for dockable application panels.

    The subclasses keep their own data behavior, but this base class centralizes
    the common toolbar, root layout, state label, player lookup, and table HTML
    formatting that had been repeated across several panel files.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        app_context: Any = None,
        *,
        show_reload_button: bool = True,
        show_save_button: bool = True,
        show_title: bool = False,
    ) -> None:
        super().__init__(parent)
        self.app = app_context
        self.data_path: Path | None = None

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 10, 10, 10)
        self.root_layout.setSpacing(8)

        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setSpacing(8)

        self.lbl_title = QLabel(title)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if not show_title:
            self.lbl_title.hide()
        self.toolbar_layout.addWidget(self.lbl_title, stretch=1)

        self.lbl_state = QLabel("")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.toolbar_layout.addWidget(self.lbl_state)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setFixedWidth(90)
        self.btn_reload.clicked.connect(self.refresh_display)
        if not show_reload_button:
            self.btn_reload.hide()
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
        """Updates the panel's toolbar status text."""
        self.lbl_state.setText(text or "")

    def _get_player(self) -> Any | None:
        """Safely returns the active Player object from either app-context shape."""
        if self.app is None:
            logging.warning("%s: app context is not available.", self.__class__.__name__)
            return None

        player = getattr(self.app, "player", None)
        if player is not None:
            return player

        nested_app = getattr(self.app, "app", None)
        nested_player = getattr(nested_app, "player", None) if nested_app is not None else None
        if nested_player is not None:
            return nested_player

        logging.warning("%s: player object is not available from app context.", self.__class__.__name__)
        return None

    def _format_table_html(self, grid_text: str) -> str:
        """Wraps tabulated text in an HTML block suitable for QTextBrowser."""
        return (
            "<pre style=\"font-family: Consolas, 'Courier New', monospace; "
            f"line-height: 1.0; padding: 6px;\">\n\n{grid_text}\n</pre>\n\n"
        )

    def _ensure_save_directory(self, save_folder: str | Path) -> Path | None:
        """Creates and returns a save directory Path, logging failures."""
        if not save_folder:
            logging.warning("%s: save folder was not provided.", self.__class__.__name__)
            return None

        save_directory = Path(save_folder)
        try:
            save_directory.mkdir(parents=True, exist_ok=True)
            return save_directory
        except Exception as directory_creation_error:
            logging.exception(f"Failed to ensure save folder exists: {directory_creation_error}")
            return None

    def set_base_path(self, save_folder: str | Path) -> None:
        """Resolves this panel's save-file location."""
        raise NotImplementedError("Subclasses must implement set_base_path().")

    def refresh_display(self) -> None:
        """Reloads data and redraws the panel."""
        raise NotImplementedError("Subclasses must implement refresh_display().")

    def get_text(self) -> str:
        """Returns context text for AIManager."""
        raise NotImplementedError("Subclasses must implement get_text().")
    
    def get_ai_context(self) -> str:
        """
        Returns plain text intended for AI prompt context.

        Subclasses that render decorative tables should override this method so
        the AI receives compact structured data instead of UI formatting.
        """
        try:
            return self.get_text()
        except Exception as error:
            logging.exception(
                "%s failed to provide AI context: %s",
                self.__class__.__name__,
                error,
            )
            return ""

    def _save_current(self) -> None:
        """Handles the toolbar Save button."""
        pass


class JsonFilePanel(BasePanel):
    """Base class for panels backed by a single JSON file."""

    DATA_FILENAME: ClassVar[str] = ""
    DEFAULT_DATA: ClassVar[Any] = []
    EXPECTED_TYPE: ClassVar[type] = list

    def set_base_path(self, save_folder: str | Path) -> None:
        """Sets this panel's JSON file path and initializes missing data."""
        save_directory = self._ensure_save_directory(save_folder)
        if save_directory is None:
            return

        if not self.DATA_FILENAME:
            logging.error("%s: DATA_FILENAME is not configured.", self.__class__.__name__)
            return

        self.data_path = save_directory / self.DATA_FILENAME
        if not self.data_path.exists():
            FileManager.save_json_data(str(self.data_path), self._default_data())
        self.refresh_display()

    def _default_data(self) -> Any:
        """Returns a new default data object for this panel."""
        return copy.deepcopy(self.DEFAULT_DATA)

    def _coerce_data(self, data: Any) -> Any:
        """Normalizes data loaded from disk to the subclass's expected type."""
        return data if isinstance(data, self.EXPECTED_TYPE) else self._default_data()

    def load_data(self) -> Any:
        """Loads and validates this panel's JSON data."""
        if self.data_path is None or not self.data_path.exists():
            return self._default_data()

        try:
            return self._coerce_data(FileManager.load_json_data(str(self.data_path)))
        except Exception as load_error:
            logging.error(f"{self.__class__.__name__}: load failed: {load_error}")
            return self._default_data()

    def save_data(self, data: Any) -> None:
        """Writes this panel's JSON data and refreshes the display."""
        if self.data_path is None:
            logging.warning("%s: cannot save because data_path is not set.", self.__class__.__name__)
            return

        try:
            FileManager.save_json_data(str(self.data_path), data)
            self._set_state("Saved")
        except Exception as save_error:
            logging.exception(f"{self.__class__.__name__}: save failed: {save_error}")
        self.refresh_display()

    def _save_current(self) -> None:
        """Rewrites the current JSON data from disk."""
        self.save_data(self.load_data())


class MarkdownPanel(BasePanel):
    """Editable Markdown panel for World, Journal, Character, History, etc."""

    def __init__(self, name: str, parent: QWidget | None = None, app_context: Any = None) -> None:
        self.name = name
        self.filename: str = ""
        self._dirty = False
        self._loading = False

        super().__init__(title=name, parent=parent, app_context=app_context, show_save_button=True)

        self.btn_reload.clicked.disconnect()
        self.btn_reload.clicked.connect(self.reload_from_disk)
        self.btn_save.clicked.disconnect()
        self.btn_save.clicked.connect(self.save_now)

        self.editor = QTextEdit()
        font_metrics = self.editor.fontMetrics()
        self.editor.setTabStopDistance(4 * font_metrics.horizontalAdvance(" "))
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.textChanged.connect(self._on_text_changed)
        self.root_layout.addWidget(self.editor, stretch=1)

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(800)
        self._autosave.timeout.connect(self._save_if_dirty)

        self._update_state_label()

    def get_text(self) -> str:
        """Returns editor contents as cleaned Markdown."""
        try:
            raw_markdown = self.editor.toMarkdown()
            raw_markdown = raw_markdown.replace("`", "")
            return raw_markdown
        except Exception as error:
            logging.error(f"Error retrieving Markdown text: {error}")
            return ""

    def set_text(self, markdown_string: str) -> None:
        """Sets editor contents from a Markdown string."""
        self._loading = True
        try:
            self.editor.blockSignals(True)
            self.editor.setMarkdown(markdown_string or "")
        except Exception as error:
            logging.error(f"Error setting Markdown text: {error}")
        finally:
            self.editor.blockSignals(False)
            self._loading = False

        self._mark_dirty()

    def set_base_path(self, save_folder: str | Path, is_first_load: bool = False) -> None:
        """Points this panel at ``<save_folder>/<name>.md`` and loads it."""
        save_directory = self._ensure_save_directory(save_folder)
        if save_directory is None:
            return

        self.filename = str(save_directory / f"{self.name}.md")
        self.reload_from_disk(force=True)

    def refresh_display(self) -> None:
        """Reloads from disk, preserving the old toolbar behavior."""
        self.reload_from_disk(force=True)

    def reload_from_disk(self, force: bool = False, is_first_load: bool = False) -> None:
        """Reloads Markdown from disk, optionally prompting before discarding edits."""
        if not self.filename:
            return

        if self._dirty and not force:
            response = QMessageBox.question(
                self,
                "Discard changes?",
                f"{self.name} has unsaved changes. Reloading will discard them. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                return

        content = FileManager.read_text_file(self.filename)
        if not content.strip():
            content = f"# {self.name}\n\n"

        self._loading = True
        try:
            self.editor.blockSignals(True)
            self.editor.setMarkdown(content)
        except Exception as error:
            logging.error(f"Error reloading Markdown from disk: {error}")
        finally:
            self.editor.blockSignals(False)
            self._loading = False

        self._dirty = False
        self._autosave.stop()
        self._update_state_label()

    def save_now(self) -> None:
        """Writes the current Markdown to disk."""
        if not self.filename:
            logging.warning("MarkdownPanel[%s]: cannot save because filename is not set.", self.name)
            return

        try:
            FileManager.write_text_file(self.filename, self.get_text())
            self._dirty = False
            self._autosave.stop()
            self._update_state_label(saved=True)
        except Exception:
            logging.exception("MarkdownPanel save failed")

    def _save_current(self) -> None:
        """Toolbar save action."""
        self.save_now()

    def _on_text_changed(self) -> None:
        """Marks the document dirty after user edits."""
        if self._loading:
            return
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        """Marks the document dirty and restarts the idle autosave timer."""
        self._dirty = True
        self._update_state_label()
        self._autosave.start()

    def _save_if_dirty(self) -> None:
        """Runs autosave when pending edits exist."""
        if self._dirty:
            self.save_now()

    def _update_state_label(self, saved: bool = False) -> None:
        """Updates this panel's save-state label."""
        if saved:
            self._set_state("Saved")
            return

        if not self.filename:
            self._set_state("No save loaded")
        elif self._dirty:
            self._set_state("Unsaved...")
        else:
            self._set_state("")

class HistoryMarkdownPanel(MarkdownPanel):
    """
    Markdown panel for History.md.

    Stores the raw History.md text, including internal exchange markers, while
    displaying a cleaned version in the UI.
    """

    EXCHANGE_MARKER: ClassVar[str] = "// NEW EXCHANGE"
    PLAYER_TEXT_MARKER: ClassVar[str] = ">"
    _MARKER_LINE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?m)^[ \t]*// NEW EXCHANGE[ \t]*(?:\r?\n)?"
    )
    _PLAYER_TEXT_LINE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^[ \t]*>[ \t]?(.*)$"
    )

    def __init__(self, parent: QWidget | None = None, app_context: Any = None) -> None:
        self._raw_markdown_text = ""
        super().__init__("History", parent=parent, app_context=app_context)

        # The History panel is an automatically-managed log. Keeping it read-only
        # prevents visible edits from desyncing from the hidden raw markers.
        self.editor.setReadOnly(True)
        self.editor.setToolTip(
            "History is managed automatically. Internal exchange markers are saved "
            "to History.md but hidden in this view."
        )

    def get_text(self) -> str:
        """
        Returns the raw History.md text.

        This intentionally includes // NEW EXCHANGE so AIManager, recap generation,
        and History.md saving can still use the exchange boundary marker.
        """
        return self._raw_markdown_text

    def set_text(self, markdown_string: str) -> None:
        """
        Stores raw History.md text while showing a marker-free display version.
        """
        raw_text = str(markdown_string or "")
        self._raw_markdown_text = raw_text

        self._loading = True
        try:
            self.editor.blockSignals(True)
            self.editor.setMarkdown(self._to_visible_markdown(raw_text))
        except Exception as error:
            logging.exception("HistoryMarkdownPanel: failed to set text: %s", error)
        finally:
            self.editor.blockSignals(False)
            self._loading = False

        self._mark_dirty()
        
    def _collapse_and_escape_player_response_blocks(self, markdown_text: str | None) -> str:
        """
        Collapses consecutive Markdown quote lines into one visible player response.

        This converts raw History.md blocks like:

            > First part of the player action
            > second part of the player action
            > third part of the player action

        into display Markdown like:

            \\> First part of the player action second part of the player action third part of the player action

        Args:
            markdown_text: Markdown text intended for UI display.

        Returns:
            Markdown text where player quote blocks are shown as literal '> ' text
            instead of Markdown block quotes.
        """
        if markdown_text is None:
            logging.warning("HistoryMarkdownPanel._collapse_and_escape_player_response_blocks called with None.")
            return ""

        output_lines: list[str] = []
        player_response_lines: list[str] = []

        def flush_player_response() -> None:
            """
            Writes the currently buffered player response into output_lines.
            """
            if not player_response_lines:
                return

            collapsed_response = " ".join(
                line.strip()
                for line in player_response_lines
                if line.strip()
            ).strip()

            if collapsed_response:
                output_lines.append(f"\\> {collapsed_response}")
            else:
                output_lines.append("\\>")

            player_response_lines.clear()

        for line in str(markdown_text).splitlines():
            player_line_match = self._PLAYER_TEXT_LINE_PATTERN.match(line)

            if player_line_match:
                player_response_lines.append(player_line_match.group(1))
                continue

            flush_player_response()
            output_lines.append(line)

        flush_player_response()

        return "\n".join(output_lines)
        
    def _escape_player_prompt_markers(self, markdown_text: str) -> str:
        """
        Escapes leading player prompt markers so Markdown displays them as literal
        '> ' text instead of rendering them as block quotes.

        Args:
            markdown_text: Markdown text intended for UI display.

        Returns:
            Markdown text with leading player prompt markers escaped.
        """
        if markdown_text is None:
            logging.warning("HistoryMarkdownPanel._escape_player_prompt_markers called with None.")
            return ""

        def replace_prompt_marker(match: re.Match[str]) -> str:
            leading_whitespace = match.group(1) or ""
            return f"{leading_whitespace}\\> "

        return self._PLAYER_TEXT_LINE_PATTERN.sub(replace_prompt_marker, markdown_text)

    def append_raw_markdown(self, markdown_string: str | None) -> None:
        """
        Appends raw Markdown to the history log.

        Args:
            markdown_string: Raw Markdown to append. May contain internal exchange markers.
        """
        if markdown_string is None:
            logging.warning("HistoryMarkdownPanel.append_raw_markdown called with None.")
            return

        self.set_text(self._raw_markdown_text + str(markdown_string))

    def reload_from_disk(self, force: bool = False, is_first_load: bool = False) -> None:
        """
        Reloads History.md from disk.

        The raw file keeps // NEW EXCHANGE, but the editor displays a cleaned version.
        """
        if not self.filename:
            return

        if self._dirty and not force:
            response = QMessageBox.question(
                self,
                "Discard changes?",
                f"{self.name} has unsaved changes. Reloading will discard them. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                return

        raw_content = FileManager.read_text_file(self.filename)
        if not raw_content.strip():
            raw_content = "# History\n\n"

        self._raw_markdown_text = raw_content

        self._loading = True
        try:
            self.editor.blockSignals(True)
            self.editor.setMarkdown(self._to_visible_markdown(raw_content))
        except Exception as error:
            logging.exception("HistoryMarkdownPanel: failed to reload Markdown: %s", error)
        finally:
            self.editor.blockSignals(False)
            self._loading = False

        self._dirty = False
        self._autosave.stop()
        self._update_state_label()

    def save_now(self) -> None:
        """
        Saves the raw History.md text, including hidden exchange markers.
        """
        if not self.filename:
            logging.warning("HistoryMarkdownPanel: cannot save because filename is not set.")
            return

        try:
            raw_text = self._raw_markdown_text or "# History\n\n"
            FileManager.write_text_file(self.filename, raw_text)
            self._dirty = False
            self._autosave.stop()
            self._update_state_label(saved=True)
        except Exception as error:
            logging.exception("HistoryMarkdownPanel save failed: %s", error)

    def _to_visible_markdown(self, raw_markdown: str | None) -> str:
        """
        Converts raw History.md into UI-facing Markdown.

        Args:
            raw_markdown: Raw History.md text.

        Returns:
            Markdown text with internal exchange marker lines converted into
            visible separators and player response quote blocks displayed as
            literal '> ' text.
        """
        raw_text = str(raw_markdown or "")

        # Convert hidden exchange markers into visible horizontal rules.
        visible_markdown = self._MARKER_LINE_PATTERN.sub("\n\n***\n\n", raw_text)

        # Convert one or more consecutive '> ' lines into one escaped player line.
        visible_markdown = self._collapse_and_escape_player_response_blocks(visible_markdown)

        visible_markdown = re.sub(r"[ \t]+\n", "\n", visible_markdown)
        visible_markdown = re.sub(r"\n{3,}", "\n\n", visible_markdown).strip()

        return visible_markdown or "# History\n\n"
    
class InventoryPanel(JsonFilePanel):
    """Inventory panel backed by ``inventory.json``."""

    DATA_FILENAME = "inventory.json"
    DEFAULT_DATA: ClassVar[dict[str, list[dict[str, Any]]]] = {}
    EXPECTED_TYPE = dict

    def __init__(self, parent: QWidget | None = None, app_context: Any = None) -> None:
        super().__init__(title="Inventory", parent=parent, app_context=app_context, show_save_button=True)
        self.display = QTextBrowser()
        self.display.setFont(QFont("Consolas", 11))
        self.root_layout.addWidget(self.display, stretch=1)

    def get_text(self) -> str:
        """Returns the current inventory display as Markdown for AI context."""
        return self.display.toMarkdown()
    
    def get_ai_context(self) -> str:
        """
        Returns inventory data as compact plain text for the AI prompt.

        This intentionally avoids the QTextBrowser display output so the model does
        not receive decorative table borders or wrapped UI text.
        """
        lines: list[str] = ["### INVENTORY"]

        try:
            data = self.load_data()
            player = self._get_player()

            if player is not None:
                try:
                    base_currency = int(getattr(player, "base_currency", 0) or 0)
                except (TypeError, ValueError) as error:
                    logging.exception("InventoryPanel: invalid base currency for context: %s", error)
                    base_currency = 0

                formatted_currency = str(base_currency)
                if hasattr(player, "get_formatted_currency"):
                    try:
                        formatted_currency = player.get_formatted_currency(base_currency)
                    except Exception as error:
                        logging.exception("InventoryPanel: failed to format currency: %s", error)

                lines.append(f"Wealth: {base_currency} base units ({formatted_currency}).")

                world_currencies = getattr(player, "world_currencies", []) or []
                if isinstance(world_currencies, list) and world_currencies:
                    lines.append("Currency denominations:")
                    clean_currencies = [
                        currency
                        for currency in world_currencies
                        if isinstance(currency, dict)
                    ]

                    for currency in sorted(
                        clean_currencies,
                        key=lambda item: self._safe_positive_int(item.get("value"), default=1),
                    ):
                        currency_name = str(currency.get("name", "Unknown Coin")).strip() or "Unknown Coin"
                        currency_value = self._safe_positive_int(currency.get("value"), default=1)
                        lines.append(f"- {currency_name}: {currency_value} base units.")

            if not isinstance(data, dict) or not data:
                lines.append("Inventory items: none.")
                return "\n".join(lines)

            lines.append("Inventory items:")

            for category, items in sorted(data.items(), key=lambda pair: str(pair[0]).lower()):
                category_name = str(category).strip() or "Uncategorized"

                if not isinstance(items, list):
                    logging.warning("InventoryPanel: skipped malformed category %s.", category_name)
                    continue

                for item in items:
                    if isinstance(item, dict):
                        item_name = str(item.get("name", "Unknown Item")).strip() or "Unknown Item"
                        item_description = str(item.get("desc", "No description.")).strip() or "No description."
                        item_amount = str(item.get("amount", "1")).strip() or "1"
                    elif isinstance(item, list):
                        item_name = str(item[0]).strip() if len(item) > 0 else "Unknown Item"
                        item_description = str(item[1]).strip() if len(item) > 1 else "No description."
                        item_amount = str(item[2]).strip() if len(item) > 2 else "1"
                    else:
                        logging.warning("InventoryPanel: skipped malformed inventory item: %r", item)
                        continue

                    lines.append(
                        f"- Category: {category_name}; "
                        f"Name: {item_name}; "
                        f"Amount: {item_amount}; "
                        f"Description: {item_description}"
                    )

        except Exception as error:
            logging.exception("InventoryPanel.get_ai_context failed: %s", error)
            lines.append("Inventory context unavailable due to an internal error.")

        return "\n".join(lines)

    def refresh_display(self) -> None:
        """Redraws currency and inventory item tables."""
        if self.data_path is None:
            self.display.setMarkdown("(No save loaded)")
            return

        data = self.load_data()
        player = self._get_player()
        base_currency = getattr(player, "base_currency", 0) if player else 0
        world_currencies = getattr(player, "world_currencies", []) if player else []

        if not data and not world_currencies:
            self.display.setMarkdown("### INVENTORY\n\n*(Empty)*")
            self._set_state("")
            return

        wealth_str = player.get_formatted_currency() if player else "0 (None)"
        parts: list[str] = ["### INVENTORY\n\n", f"**Wealth:** {wealth_str}\n\n"]

        if world_currencies:
            parts.append(self._render_currency_table(base_currency, world_currencies))

        item_headers = ["Name", "Description", "Amount"]
        for category in sorted(data.keys(), key=lambda category_name: str(category_name).lower()):
            items = data.get(category) or []
            if not isinstance(items, list) or not items:
                continue

            items_sorted = sorted(
                items,
                key=lambda item: str(item.get("name", "")).lower()
                if isinstance(item, dict)
                else str(item[0]).lower(),
            )

            rows: list[list[str]] = []
            for item in items_sorted:
                if isinstance(item, dict):
                    rows.append([
                        str(item.get("name", "Unknown")),
                        str(item.get("desc", "No desc")),
                        str(item.get("amount", "1")),
                    ])
                elif isinstance(item, list):
                    rows.append([
                        str(item[0]) if len(item) > 0 else "Unknown",
                        str(item[1]) if len(item) > 1 else "No desc",
                        str(item[2]) if len(item) > 2 else "1",
                    ])

            parts.append(f"#### {category}\n\n")
            parts.append(self._format_table_html(tabulate(rows, item_headers, tablefmt="rounded_grid")))

        self.display.setMarkdown("".join(parts).rstrip() + "\n")
        self._set_state("")

    def _render_currency_table(self, base_currency: int, world_currencies: list[dict[str, Any]]) -> str:
        """Builds the dynamic currency table for the inventory display."""
        try:
            remaining = abs(int(base_currency or 0))
        except (TypeError, ValueError):
            logging.exception("InventoryPanel: invalid base currency value %r", base_currency)
            remaining = 0

        clean_currencies = [currency for currency in world_currencies if isinstance(currency, dict)]
        sorted_currencies = sorted(
            clean_currencies,
            key=lambda item: self._safe_positive_int(item.get("value"), default=1),
            reverse=True,
        )
        lowest_coin_name = sorted_currencies[-1].get("name", "Base Units") if sorted_currencies else "Base Units"

        rows: list[list[str]] = []
        for currency in sorted_currencies:
            value = self._safe_positive_int(currency.get("value"), default=1)
            if value <= 0:
                continue

            count = remaining // value
            remaining %= value
            amount_text = str(-count) if base_currency < 0 and count > 0 else str(count)
            rows.append([currency.get("name", "Unknown Coin"), "Legal Tender", amount_text, f"{value} {lowest_coin_name}"])

        if remaining > 0:
            loose_text = str(-remaining) if base_currency < 0 else str(remaining)
            rows.append(["Loose Change", "Base Units", loose_text, "1 base unit"])

        if not rows:
            return ""

        grid = tabulate(rows, ["Name", "Description", "Amount", "Value"], tablefmt="rounded_grid")
        return "#### Wealth / Currencies\n\n" + self._format_table_html(grid)

    def _safe_positive_int(self, value: Any, *, default: int = 1) -> int:
        """Safely converts currency metadata to a positive integer."""
        try:
            return max(1, int(value or default))
        except (TypeError, ValueError):
            logging.exception("InventoryPanel: invalid positive integer value %r", value)
            return default

    def modify_item(self, raw_args: str) -> str | None:
        """Parses ``[[MODIFY_ITEM:]]`` and edits an existing inventory item."""
        try:
            parts = [part.strip() for part in (raw_args or "").split("|")]
            if len(parts) < 1:
                return "Error: Missing Target Name."

            target_name = parts[0]

            def should_update(index: int) -> bool:
                if len(parts) <= index:
                    return False
                value = (parts[index] or "").strip().upper()
                return value not in ("SAME", "SKIP", "", "N/A")

            new_name = parts[1] if should_update(1) else None
            new_description = parts[2] if should_update(2) else None
            new_amount = parts[3] if should_update(3) else None

            data = self.load_data()
            found = False

            for _category, items in data.items():
                if not isinstance(items, list):
                    continue

                for item in items:
                    current_name = ""
                    if isinstance(item, dict):
                        current_name = str(item.get("name", ""))
                    elif isinstance(item, list) and item:
                        current_name = str(item[0])

                    if current_name.lower() != str(target_name).lower():
                        continue

                    if isinstance(item, dict):
                        if new_name:
                            item["name"] = new_name
                        if new_description:
                            item["desc"] = new_description
                        if new_amount:
                            try:
                                item["amount"] = int(new_amount)
                            except ValueError:
                                logging.error(f"modify_item: Invalid integer amount '{new_amount}'. Skipping amount update.")
                    else:
                        if new_name:
                            item[0] = new_name
                        if new_description:
                            item[1] = new_description
                        if new_amount:
                            try:
                                item[2] = int(new_amount)
                            except ValueError:
                                logging.error(f"modify_item: Invalid integer amount '{new_amount}'. Skipping amount update.")

                    found = True
                    break

                if found:
                    break

            if found:
                self.save_data(data)
            else:
                logging.warning(f"modify_item: Could not find item '{target_name}' to modify.")
        except Exception as error:
            logging.exception(f"InventoryPanel.modify_item failed for arguments {raw_args}: {error}")

        self.refresh_display()
        return None

    def autonomous_add(self, raw_args: str) -> str | None:
        """Parses ``[[ADD:]]`` and safely adds or stacks an inventory item."""
        try:
            parts = [part.strip() for part in (raw_args or "").split("|")]
            if len(parts) < 2:
                return "Error: Data missing."

            category = parts[0].title()
            name = parts[1]
            description = parts[2] if len(parts) > 2 else "No description."

            try:
                amount_to_add = int(parts[3]) if len(parts) > 3 else 1
            except ValueError:
                amount_to_add = 1

            data = self.load_data()
            if category not in data or not isinstance(data.get(category), list):
                data[category] = []

            found = False
            for item in data[category]:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name", "")).lower() == str(name).lower() and "meta" not in item:
                    try:
                        item["amount"] = int(item.get("amount", 0)) + amount_to_add
                        found = True
                    except Exception as stack_error:
                        logging.error(f"InventoryPanel.autonomous_add: stacking failed: {stack_error}")
                    break

            if not found:
                data[category].append({"name": name, "desc": description, "amount": amount_to_add})
                logging.info(f"Successfully added {amount_to_add}x {name} to the Player's inventory.")

            self.save_data(data)
        except Exception as error:
            logging.error(f"InventoryPanel.autonomous_add failed: {error}")

        self.refresh_display()
        return None

    def autonomous_remove(self, raw_args: str) -> str | None:
        """Parses ``[[REMOVE:]]`` and decreases or removes an inventory item."""
        try:
            parts = [part.strip() for part in (raw_args or "").split("|")]
            target_name = parts[0] if parts else (raw_args or "UNKNOWN ITEM").strip()

            try:
                amount_to_remove = int(parts[1]) if len(parts) > 1 else 1
            except ValueError:
                amount_to_remove = 1

            data = self.load_data()
            removed = False

            for _category, items in data.items():
                if not isinstance(items, list):
                    continue

                for index, item in enumerate(list(items)):
                    if not isinstance(item, dict):
                        continue

                    item_name = str(item.get("name", "UNKNOWN NAME"))
                    if str(target_name).lower() not in item_name.lower():
                        continue

                    try:
                        current_amount = int(item.get("amount", 1))
                    except ValueError:
                        current_amount = 1

                    new_amount = current_amount - amount_to_remove
                    if new_amount <= 0:
                        items.pop(index)
                    else:
                        item["amount"] = new_amount

                    removed = True
                    break

                if removed:
                    break

            if removed:
                self.save_data(data)
                logging.info(f"(Player lost {amount_to_remove}x {target_name}.)")
            else:
                logging.error(f"Error: Could not find '{target_name}' to remove.")
        except Exception as error:
            logging.error(f"InventoryPanel.autonomous_remove failed: {error}")

        self.refresh_display()
        return None


class SkillsPanel(JsonFilePanel):
    """Skills panel backed by ``skills.json``."""

    DATA_FILENAME = "skills.json"
    DEFAULT_DATA: ClassVar[list[dict[str, Any]]] = []
    EXPECTED_TYPE = list

    def __init__(self, parent: QWidget | None = None, app_context: Any = None) -> None:
        super().__init__(title="Skills", parent=parent, app_context=app_context, show_save_button=True)
        self.display = QTextBrowser()
        self.display.setFont(QFont("Consolas", 11))
        self.root_layout.addWidget(self.display, stretch=1)

    def get_text(self) -> str:
        """Returns the current skills display as Markdown for AI context."""
        return self.display.toMarkdown()
    
    def get_ai_context(self) -> str:
        """
        Returns skills as compact plain text for the AI prompt.

        This preserves full names, descriptions, levels, XP, and thresholds without
        sending decorative UI table formatting to the model.
        """
        lines: list[str] = ["### SKILLS"]

        try:
            data = self.load_data()

            if not isinstance(data, list) or not data:
                lines.append("No known skills.")
                return "\n".join(lines)

            for skill in sorted(
                data,
                key=lambda item: str(item.get("Name", "")).lower() if isinstance(item, dict) else "",
            ):
                if not isinstance(skill, dict):
                    logging.warning("SkillsPanel: skipped malformed skill entry: %r", skill)
                    continue

                name = str(skill.get("Name", "Unknown Skill")).strip() or "Unknown Skill"
                description = str(skill.get("Description", "No description.")).strip() or "No description."

                try:
                    level = int(skill.get("Level", 0) or 0)
                except (TypeError, ValueError) as error:
                    logging.exception("SkillsPanel: invalid skill level for %s: %s", name, error)
                    level = 0

                try:
                    xp = int(skill.get("XP", 0) or 0)
                except (TypeError, ValueError) as error:
                    logging.exception("SkillsPanel: invalid skill XP for %s: %s", name, error)
                    xp = 0

                try:
                    threshold = int(skill.get("Threshold", 0) or 0)
                except (TypeError, ValueError) as error:
                    logging.exception("SkillsPanel: invalid skill threshold for %s: %s", name, error)
                    threshold = 0

                if level >= 5:
                    progression_text = "MAX LEVEL"
                else:
                    progression_text = f"XP {xp}/{threshold}"

                lines.append(
                    f"- {name}: Level bonus +{level}; "
                    f"{progression_text}; "
                    f"Description: {description}"
                )

        except Exception as error:
            logging.exception("SkillsPanel.get_ai_context failed: %s", error)
            lines.append("Skills context unavailable due to an internal error.")

        return "\n".join(lines)

    def save_data(self, data: list[dict[str, Any]]) -> None:
        """Sorts skills before writing them to disk."""
        try:
            data.sort(key=lambda item: str(item.get("Name", "")).lower())
        except Exception as sort_error:
            logging.error(f"SkillsPanel: sort failed: {sort_error}")
        super().save_data(data)

    def add_xp(self, skill_name: str, xp_amount: int) -> None:
        """Adds XP to a skill and handles level-up thresholds."""
        data = self.load_data()
        found = False
        clean_skill_name = (skill_name or "").strip()
        if not clean_skill_name:
            logging.warning("SkillsPanel.add_xp called without a skill name.")
            return

        try:
            for skill in data:
                if not isinstance(skill, dict):
                    logging.warning("SkillsPanel.add_xp skipped non-dict skill entry: %r", skill)
                    continue
                if str(skill.get("Name", "")).lower() != clean_skill_name.lower():
                    continue

                if int(skill.get("Level", 0)) >= 5:
                    return
                
                # Resetting a Skill to zero XP is intentional design; otherwise, it would only take the Player two Skill Checks per level to level up the skill.
                skill["XP"] = int(skill.get("XP", 0)) + int(xp_amount)
                threshold = int(skill.get("Threshold", 3))
                if threshold <= int(skill["XP"]):
                    skill["Level"] = int(skill.get("Level", 0)) + 1
                    skill["XP"] = 0
                    skill["Threshold"] = threshold + 2

                found = True
                break

            if found:
                logging.info(f"Successfully added {xp_amount} xp to {clean_skill_name} skill.")
                self.save_data(data)
        except Exception as error:
            logging.exception(f"Error adding XP: {error}")
        finally:
            self.refresh_display()

    def refresh_display(self) -> None:
        """Redraws the skills table."""
        if self.data_path is None:
            self.display.setMarkdown("(No save loaded)")
            return

        data = self.load_data()
        if not data:
            self.display.setMarkdown("### SKILLS\n\n*(None)*")
            self._set_state("")
            return

        rows = []
        for skill in data:
            try:
                name = skill.get("Name", "UNKNOWN")
                level = int(skill.get("Level", 0) or 0)
                level_string = "+5 (MAX LEVEL)" if level == 5 else f"+{level}" if level >= 0 else str(level)
                description = "\n".join(textwrap.wrap(skill.get("Description", ""), width=35))
                xp = skill.get("XP", 0)
                xp_string = str(xp) if level < 5 else "(MAX LEVEL)"
                threshold = skill.get("Threshold", 0)
                threshold_string = str(threshold) if level < 5 else "(MAX LEVEL)"
            except Exception as error:
                logging.exception("SkillsPanel: malformed skill row %r: %s", skill, error)
                name = "UNKNOWN"
                level_string = "+0"
                description = "UNKNOWN DESCRIPTION"
                xp_string = "0"
                threshold_string = "3"

            rows.append([name, description, level_string, xp_string, threshold_string])

        grid = tabulate(rows, ["Skill Name", "Skill Description", "Level (Bonus)", "XP", "Next Level"], tablefmt="rounded_grid")
        self.display.setMarkdown(f"### SKILLS\n\n{self._format_table_html(grid)}")
        self._set_state("")

    def force_learn_skill(self, skill_name: str, skill_description: str, level: int) -> None:
        """Adds or updates a skill from an AI-generated ``[[SKILL:]]`` tag."""
        clean_name = (skill_name or "").split("(")[0].strip().title()
        clean_description = (skill_description or "").split("(")[0].strip().title()
        data = self.load_data()
        try:
            clean_level = max(1, int(level))
        except (TypeError, ValueError):
            logging.exception("SkillsPanel.force_learn_skill received invalid level %r", level)
            clean_level = 1

        found = False
        for item in data:
            if not isinstance(item, dict):
                logging.warning("SkillsPanel.force_learn_skill skipped non-dict skill entry: %r", item)
                continue
            if str(item.get("Name", "")).lower() == clean_name.lower():
                item["Level"] = clean_level
                if clean_description:
                    item["Description"] = clean_description
                item["XP"] = 0
                item["Threshold"] = 5 + (clean_level * 2)
                found = True
                break

        if not found:
            data.append(
                {
                    "Name": clean_name,
                    "Description": clean_description,
                    "Level": clean_level,
                    "XP": 0,
                    "Threshold": 5 + (clean_level * 2),
                }
            )

        self.save_data(data)


class ProcessingPanel(JsonFilePanel):
    """Processing panel for passive processes and active projects."""

    DATA_FILENAME = "processing.json"
    DEFAULT_DATA: ClassVar[list[dict[str, Any]]] = []
    EXPECTED_TYPE = list

    def __init__(self, parent: QWidget | None = None, app_context: Any = None) -> None:
        super().__init__(title="Processing", parent=parent, app_context=app_context, show_save_button=True)
        self.display = QTextBrowser()
        self.display.setFont(QFont("Consolas", 11))
        self.root_layout.addWidget(self.display, stretch=1)

    def get_text(self) -> str:
        """Returns ongoing task information as Markdown for AI context."""
        return self.display.toMarkdown()
    
    def get_ai_context(self) -> str:
        """
        Returns active processes and projects as compact plain text for the AI prompt.
        """
        lines: list[str] = ["### ONGOING TASKS"]

        try:
            data = self.load_data()

            if not isinstance(data, list) or not data:
                lines.append("No active processes or projects.")
                return "\n".join(lines)

            for item in data:
                if not isinstance(item, dict):
                    logging.warning("ProcessingPanel: skipped malformed task entry: %r", item)
                    continue

                name = str(item.get("name", "Unknown Task")).strip() or "Unknown Task"
                task_type = str(item.get("type", "process")).strip() or "process"
                status = str(item.get("status", "Unknown")).strip() or "Unknown"
                description = str(item.get("desc", "No description.")).strip() or "No description."
                expected_yield = str(item.get("yield", "Unknown")).strip() or "Unknown"

                if task_type == "process":
                    ready_day = str(item.get("ready_on_day", "Unknown")).strip() or "Unknown"
                    ready_time = str(item.get("ready_on_time", "Unknown")).strip() or "Unknown"

                    lines.append(
                        f"- {name}: Type: process; "
                        f"Status: {status}; "
                        f"Ready on day: {ready_day}; "
                        f"Ready at time: {ready_time}; "
                        f"Yield: {expected_yield}; "
                        f"Description: {description}"
                    )
                    continue

                skill = str(item.get("skill", "Unknown Skill")).strip() or "Unknown Skill"

                try:
                    work_required = float(item.get("work_required", 0.0) or 0.0)
                except (TypeError, ValueError) as error:
                    logging.exception("ProcessingPanel: invalid work_required for %s: %s", name, error)
                    work_required = 0.0

                try:
                    work_done = float(item.get("work_done", 0.0) or 0.0)
                except (TypeError, ValueError) as error:
                    logging.exception("ProcessingPanel: invalid work_done for %s: %s", name, error)
                    work_done = 0.0

                try:
                    skill_level = int(item.get("skill_level_at_start", 0) or 0)
                except (TypeError, ValueError) as error:
                    logging.exception("ProcessingPanel: invalid skill level for %s: %s", name, error)
                    skill_level = 0

                lines.append(
                    f"- {name}: Type: project; "
                    f"Status: {status}; "
                    f"Skill: {skill}; "
                    f"Skill level at start: {skill_level}; "
                    f"Work done: {work_done:g}/{work_required:g} minutes; "
                    f"Yield: {expected_yield}; "
                    f"Description: {description}"
                )

        except Exception as error:
            logging.exception("ProcessingPanel.get_ai_context failed: %s", error)
            lines.append("Processing context unavailable due to an internal error.")

        return "\n".join(lines)

    def add_timed_process(
        self,
        name: str,
        description: str,
        duration_minutes: int,
        current_day: int,
        current_time_str: str,
        expected_yield: str,
    ) -> None:
        """Adds a passive process with a calculated completion time."""
        data = self.load_data()
        target_day, target_time_str = time_utils.advance_time(current_day, current_time_str, duration_minutes)

        data.append(
            {
                "name": name,
                "desc": description,
                "type": "process",
                "yield": expected_yield,
                "status": "In Progress",
                "ready_on_day": target_day,
                "ready_on_time": target_time_str,
            }
        )
        self.save_data(data)

    def check_active_tasks(self, current_day: int, current_time_str: str) -> list[str]:
        """Marks ready passive processes as complete."""
        data = self.load_data()
        if not data:
            logging.warning("No data to load for check_active_tasks in ProcessingPanel.")
            return []

        completed: list[str] = []
        changed = False

        for item in data:
            if item.get("status") != "In Progress" or item.get("type") != "process":
                continue

            target_day = item.get("ready_on_day", 1)
            target_time_str = item.get("ready_on_time", "12:00 A.M.")
            if time_utils.is_time_passed(current_day, current_time_str, target_day, target_time_str):
                item["status"] = "COMPLETED"
                expected_yield = item.get("yield", "Unknown")
                completed.append(f"{item.get('name', 'Unknown')} (Yield: {expected_yield})")
                changed = True

        if changed:
            self.save_data(data)

        return completed

    def add_project(
        self,
        name: str,
        desc: str,
        work_required: float,
        skill_name: str,
        skill_level_at_start: int,
        expected_yield: str,
    ) -> str:
        """Starts an active project that can be worked over multiple turns."""
        data = self.load_data()

        try:
            required_minutes = max(0.0, float(work_required))
        except Exception as error:
            logging.error(f"ProcessingPanel.add_project: bad work_required: {error}")
            required_minutes = 0.0

        try:
            level = max(0, int(skill_level_at_start))
        except Exception as error:
            logging.error(f"ProcessingPanel.add_project: bad level: {error}")
            level = 0

        data.append(
            {
                "name": name,
                "desc": desc,
                "type": "project",
                "yield": expected_yield,
                "status": "In Progress",
                "skill": skill_name,
                "skill_level_at_start": level,
                "work_required": required_minutes,
                "work_done": 0.0,
            }
        )
        self.save_data(data)

        speed_multiplier = 1.0 + (0.5 * level)
        estimated_minutes = required_minutes / speed_multiplier if speed_multiplier > 0 else 0.0
        estimate = f"~{estimated_minutes / 60:.1f} hrs" if estimated_minutes >= 60 else f"~{int(estimated_minutes)} mins"

        return (
            f"(Started Project: {name} (Skill: {skill_name}). Base Time: {required_minutes} mins. "
            f"Yields: {expected_yield}. Est. Player Time: {estimate}.)"
        )

    def apply_work_minutes(self, name: str, minutes_worked: float, skill_level: int) -> str:
        """Applies labor to a project using skill level as a speed multiplier."""
        data = self.load_data()

        try:
            minutes = max(0.0, float(minutes_worked))
        except Exception as error:
            logging.error(f"ProcessingPanel.apply_work_minutes: bad mins: {error}")
            minutes = 0.0

        try:
            level = max(0, int(skill_level))
        except Exception as error:
            logging.error(f"ProcessingPanel.apply_work_minutes: bad lvl: {error}")
            level = 0

        completed_amount = (1.0 + (0.5 * level)) * minutes

        for item in data:
            if str(item.get("name", "")).lower() != str(name).lower() or item.get("type") != "project":
                continue

            if item.get("status") != "In Progress":
                return f"System: {name} is already done."

            required_minutes = float(item.get("work_required", 0.0) or 0.0)
            done = float(item.get("work_done", 0.0) or 0.0) + completed_amount
            item["work_done"] = done

            if required_minutes <= 0 or done >= required_minutes:
                item["status"] = "COMPLETED"
                self.save_data(data)
                return f"(Work Complete! {name} is finished. Yield: {item.get('yield', 'Unknown')})"

            remaining_base_minutes = max(0.0, required_minutes - done)
            self.save_data(data)
            remaining_text = f"{remaining_base_minutes / 60:.1f} hrs" if remaining_base_minutes >= 60 else f"{int(remaining_base_minutes)} mins"
            return f"(Worked on {name} for {minutes:g} mins. Remaining Base Labor: {remaining_text}.)"

        return f"System: Could not find project '{name}'."

    def refresh_display(self) -> None:
        """Redraws the tasks table."""
        if self.data_path is None:
            self.display.setMarkdown("(No save loaded)")
            return

        data = self.load_data()
        if not data:
            self.display.setMarkdown("### ONGOING TASKS\n\n(None)")
            self._set_state("")
            return

        player = self._get_player()
        calendar_settings = getattr(player, "calendar_settings", {}) if player is not None else {}
        rows: list[list[str]] = []

        for item in data:
            task_type = item.get("type", "process")
            status = item.get("status", "Unknown")
            expected_yield = item.get("yield", "N/A")
            description = item.get("desc", "")

            if task_type == "process":
                if status == "COMPLETED":
                    progress = "DONE (collect)"
                else:
                    target_day = item.get("ready_on_day", "Unknown")
                    target_time = item.get("ready_on_time", "Unknown")
                    try:
                        target_day_int = int(target_day)
                    except (TypeError, ValueError):
                        logging.exception("ProcessingPanel: invalid target day %r", target_day)
                        target_day_int = 1

                    if target_day != "Unknown":
                        rich_target_date = time_utils.calculate_calendar_date(target_day_int, calendar_settings)
                        progress = f"Due: {rich_target_date} at {target_time}"
                    else:
                        progress = f"Due: Day {target_day} at {target_time}"
                rows.append([item.get("name", ""), "PROCESS", status, progress, expected_yield, description])
                continue

            required_minutes = float(item.get("work_required", 0.0) or 0.0)
            done = float(item.get("work_done", 0.0) or 0.0)
            skill = item.get("skill", "")
            if status == "COMPLETED":
                progress = "DONE (collect)"
            else:
                remaining = max(0.0, required_minutes - done)
                level = int(item.get("skill_level_at_start", 0) or 0)
                speed_multiplier = 1.0 + (0.5 * level)
                minutes_left = remaining / speed_multiplier if speed_multiplier > 0 else 0.0
                time_text = f"~{minutes_left / 60:.1f} hrs left" if minutes_left >= 60 else f"~{int(minutes_left)} mins left"
                progress = f"{done:.0f}/{required_minutes:.0f} Mins (Skill: {skill}) {time_text}"

            rows.append([item.get("name", ""), "PROJECT", status, progress, expected_yield, description])

        headers = ["Name", "Type", "Status", "Due/Progress", "Yield", "Description"]
        grid = tabulate(rows, headers, tablefmt="rounded_grid")
        self.display.setMarkdown(f"### ONGOING TASKS\n\n{self._format_table_html(grid)}")
        self._set_state("")

    def remove_process(self, name: str) -> None:
        """Removes a process or project by name."""
        data = self.load_data()
        for index, item in enumerate(list(data)):
            if str(item.get("name", "")).lower() == str(name).lower():
                data.pop(index)
                self.save_data(data)
                return None
        return None

    def get_required_skill(self, name: str) -> str | None:
        """Returns the skill required by a named project."""
        data = self.load_data()
        for item in data:
            if str(item.get("name", "")).lower() == str(name).lower() and item.get("type") == "project":
                return item.get("skill")
        return None


class RecipesPanel(BasePanel):
    """Recipes panel backed by ``recipes.csv``."""

    COLUMNS: ClassVar[list[str]] = [
        "recipe_name",
        "ingredient_1",
        "ingredient_1_amount",
        "ingredient_2",
        "ingredient_2_amount",
        "ingredient_3",
        "ingredient_3_amount",
    ]

    def __init__(self, parent: QWidget | None = None, app_context: Any = None) -> None:
        super().__init__(title="Recipes", parent=parent, app_context=app_context, show_save_button=True)
        self.base_path: Path | None = None
        self.csv_path: Path | None = None

        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setFont(QFont("Consolas", 11))
        self.display.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.root_layout.addWidget(self.display, stretch=1)

    def set_base_path(self, save_folder: str | Path) -> None:
        """Points this panel at ``recipes.csv`` in the current save folder."""
        save_directory = self._ensure_save_directory(save_folder)
        if save_directory is None:
            return

        self.base_path = save_directory
        self.csv_path = save_directory / "recipes.csv"
        self._ensure_csv_exists()
        self.refresh_display()

    def get_text(self) -> str:
        """Returns known recipes as a compact Markdown list for AI context."""
        if self.csv_path is None or not self.csv_path.exists():
            return "No known recipes."

        rows = self._read_rows()
        if not rows:
            return "No known recipes."

        output: list[str] = []
        for row in rows:
            name = (row.get("recipe_name") or "Unknown").strip()
            ingredients: list[str] = []
            for index in range(1, 4):
                ingredient = (row.get(f"ingredient_{index}") or "").strip()
                amount = (row.get(f"ingredient_{index}_amount") or "").strip()
                if ingredient:
                    ingredients.append(f"{ingredient} (x{amount or '1'})")
            output.append(f"- {name}: {', '.join(ingredients)}")
        return "\n".join(output)

    def refresh_display(self) -> None:
        """Redraws the recipe table."""
        if self.csv_path is None:
            self.display.setPlainText("(No save loaded)")
            return

        try:
            self._ensure_csv_exists()
            rows = self._read_rows()
            if not rows:
                self.display.setPlainText("RECIPES\n\n(None)\n")
                self._set_state("")
                return

            table_rows: list[list[str]] = []
            for row in rows:
                name = (row.get("recipe_name") or "Unknown").strip()
                ingredient_parts: list[str] = []
                for index in range(1, 4):
                    ingredient = (row.get(f"ingredient_{index}") or "").strip()
                    amount = (row.get(f"ingredient_{index}_amount") or "").strip()
                    if ingredient:
                        ingredient_parts.append(f"{ingredient}: {amount or '1'}")
                table_rows.append([name, ", ".join(ingredient_parts)])

            display_text = "RECIPES\n" + tabulate(table_rows, ["Recipe", "Ingredients"], tablefmt="rounded_grid") + "\n"
            self.display.setPlainText(display_text)
            self._set_state("")
        except Exception as error:
            logging.exception(f"Critical error during refreshing recipes panel display: {error}")

    def _ensure_csv_exists(self) -> None:
        """Creates recipes.csv with headers if missing."""
        if self.csv_path is None or self.csv_path.exists():
            return

        try:
            with self.csv_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=self.COLUMNS)
                writer.writeheader()
        except Exception:
            logging.exception("RecipesPanel: failed to create recipes.csv")

    def _read_rows(self) -> list[dict[str, str]]:
        """Reads recipes.csv and normalizes missing columns."""
        if self.csv_path is None or not self.csv_path.exists():
            return []

        try:
            with self.csv_path.open("r", newline="", encoding="utf-8") as file:
                rows = [dict(row) for row in csv.DictReader(file)]
        except Exception as error:
            logging.error(f"RecipesPanel: failed to read CSV: {error}")
            return []

        for row in rows:
            for column in self.COLUMNS:
                row.setdefault(column, "")
        return rows

    def _write_rows(self, rows: list[dict[str, str]]) -> None:
        """Writes recipe rows back to recipes.csv."""
        if self.csv_path is None:
            return

        try:
            with self.csv_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=self.COLUMNS)
                writer.writeheader()
                for row in rows:
                    writer.writerow({column: (row.get(column, "") or "") for column in self.COLUMNS})
            self._set_state("Saved")
        except Exception:
            logging.exception("RecipesPanel: failed to write CSV")
        self.refresh_display()

    def _save_current(self) -> None:
        """Manual save button action for the read-only recipe table."""
        self._set_state("Saved")

    def add_recipe_from_tag(self, tag_content: str) -> str:
        """Parses ``[[RECIPE: Name | Ing1: 5, Ing2: 2]]`` and stores it."""
        if self.csv_path is None:
            return "Invalid csv path."

        try:
            parts = [part.strip() for part in (tag_content or "").split("|")]
            if len(parts) < 2:
                return "System: Invalid Recipe Tag Format."

            recipe_name = parts[0]
            ingredient_string = parts[1]
            ingredient_list: list[tuple[str, str]] = []

            for raw_ingredient in (ingredient_string or "").split(","):
                raw_ingredient = raw_ingredient.strip()
                if not raw_ingredient:
                    continue
                if ":" in raw_ingredient:
                    ingredient_name, ingredient_amount = raw_ingredient.split(":", 1)
                    ingredient_list.append((ingredient_name.strip(), ingredient_amount.strip() or "1"))
                else:
                    ingredient_list.append((raw_ingredient.strip(), "1"))

            rows = self._read_rows()
            if any((row.get("recipe_name") or "").strip().lower() == recipe_name.lower() for row in rows):
                return f"System: Recipe '{recipe_name}' already known."

            new_row = {column: "" for column in self.COLUMNS}
            new_row["recipe_name"] = recipe_name
            for index, (ingredient_name, ingredient_amount) in enumerate(ingredient_list[:3], start=1):
                new_row[f"ingredient_{index}"] = ingredient_name
                new_row[f"ingredient_{index}_amount"] = ingredient_amount

            rows.append(new_row)
            self._write_rows(rows)
            return f"System: Learned recipe for {recipe_name}."
        except Exception as error:
            logging.error(f"RecipesPanel.add_recipe_from_tag failed: {error}")
            return f"System: Error learning recipe ({error})"


class CalendarPanel(BasePanel):
    """Read-only visual panel that renders the current in-game month."""

    def __init__(self, parent: QWidget | None = None, app_context: Any = None) -> None:
        super().__init__(
            title="Calendar",
            parent=parent,
            app_context=app_context,
            show_save_button=False,
            show_title=True,
        )
        self.btn_reload.setText("Refresh")

        self.display = QTextBrowser()
        self.display.setFont(QFont("Arial", 11))
        self.root_layout.addWidget(self.display, stretch=1)

    def set_base_path(self, save_folder: str | Path) -> None:
        """Calendar is derived from player state, so no save file is needed."""
        self.refresh_display()

    def refresh_display(self) -> None:
        """Builds an HTML calendar grid from the current player date."""
        player = self._get_player()
        calendar_settings = getattr(player, "calendar_settings", {}) if player is not None else {}
        if not player or not calendar_settings:
            self.display.setHtml("<p><i>(No calendar configured. Use the Game Menu to set one up.)</i></p>")
            return

        current_day = getattr(player, "day", 1) or 1
        try:
            grid_data = time_utils.get_calendar_grid_data(int(current_day), calendar_settings)
        except Exception as error:
            logging.exception("CalendarPanel: calendar grid calculation failed: %s", error)
            self.display.setHtml("<p><i>(Calendar calculation error.)</i></p>")
            return
        if not grid_data:
            self.display.setHtml("<p><i>(Calendar calculation error.)</i></p>")
            return

        weekdays = grid_data["weekdays"]
        columns = len(weekdays)
        html = [
            f"<h2 style='text-align: center; color: #4CAF50; margin-bottom: 2px;'>{grid_data['month_name']}</h2>",
            f"<h4 style='text-align: center; color: #aaaaaa; margin-top: 0px;'>Year {grid_data['year']} - {grid_data['season']}</h4>",
            "<table width='100%' border='1' cellspacing='0' cellpadding='8' style='border-collapse: collapse; border: 1px solid #555;'>",
            "<tr>",
        ]

        for day_name in weekdays:
            html.append(f"<th style='background-color: #333; color: white;'>{day_name}</th>")
        html.append("</tr><tr>")

        current_column = 0
        for _ in range(grid_data["start_offset"]):
            html.append("<td style='background-color: #222;'></td>")
            current_column += 1

        for day_number in range(1, grid_data["month_total_days"] + 1):
            if current_column >= columns:
                html.append("</tr><tr>")
                current_column = 0

            if day_number == grid_data["current_day"]:
                html.append(f"<td align='center' style='background-color: #4CAF50; color: white; font-weight: bold;'>{day_number}</td>")
            else:
                html.append(f"<td align='center'>{day_number}</td>")
            current_column += 1

        while current_column < columns:
            html.append("<td style='background-color: #222;'></td>")
            current_column += 1

        html.append("</tr></table>")
        self.display.setHtml("".join(html))

    def get_text(self) -> str:
        """Returns a plain-text date summary for AI context."""
        player = self._get_player()
        calendar_settings = getattr(player, "calendar_settings", {}) if player is not None else {}
        if player and calendar_settings:
            current_day = getattr(player, "day", 1) or 1
            current_date = time_utils.calculate_calendar_date(int(current_day), calendar_settings)
            return f"The current in-game date is: {current_date}"
        return "No calendar configured."


class QuestsPanel(BasePanel):
    """Read-only panel that displays active quests from player state."""

    def __init__(self, parent: QWidget | None = None, app_context: Any = None) -> None:
        super().__init__(title="Quests", parent=parent, app_context=app_context, show_save_button=False)
        self.display = QTextBrowser()
        self.display.setFont(QFont("Consolas", 10))
        self.display.setOpenExternalLinks(False)
        self.root_layout.addWidget(self.display, stretch=1)

        # Compatibility alias for older code that referenced text_display directly.
        self.text_display = self.display

    def set_base_path(self, save_folder: str | Path) -> None:
        """Quests are stored on the Player object, so no panel file is needed."""
        self.refresh_display()

    def refresh_display(self) -> None:
        """Reads player quests and renders them as vertical tables."""
        player = self._get_player()
        if player is None:
            self.display.setMarkdown("*(No player loaded.)*")
            return

        try:
            quests = getattr(player, "quests", []) or []
            if not isinstance(quests, list):
                logging.warning("QuestsPanel: player.quests is not a list: %r", quests)
                self.display.setMarkdown("*(Quest data is malformed. See log.)*")
                return

            if not quests:
                self.display.setMarkdown("*You currently have no active quests.*")
                return

            display_text = ""
            for quest in quests:
                if not isinstance(quest, dict):
                    logging.warning("QuestsPanel: skipped malformed quest entry: %r", quest)
                    continue

                name = quest.get("name", "Unknown Quest")
                table_data = [
                    ["Quest Giver", quest.get("giver", "Unknown")],
                    ["Date Received", quest.get("date_received", "Unknown")],
                    ["Description", quest.get("description", "No description provided.")],
                    ["How to Complete", quest.get("turn_in", "Unknown")],
                    ["Reward", quest.get("reward", "Unknown")],
                ]
                grid = tabulate(table_data, tablefmt="rounded_grid")
                display_text += f"### {name}\n\n{self._format_table_html(grid)}\n"

            self.display.setMarkdown(display_text.strip() or "*You currently have no active quests.*")
        except Exception as error:
            logging.exception(f"Critical error during refreshing quest panel display: {error}")

    def add_quest(self, name: str, giver: str, description: str, turn_in: str, reward: str) -> None:
        """Adds a quest to the player's log if it does not already exist."""
        player = self._get_player()
        if player is None:
            logging.warning("QuestsPanel.add_quest called without a player object.")
            return

        if not hasattr(player, "quests") or not isinstance(getattr(player, "quests", None), list):
            logging.warning("QuestsPanel: initialized missing or malformed player.quests list.")
            player.quests = []

        try:
            clean_name = (name or "Unknown Quest").strip()
            for quest in player.quests:
                if isinstance(quest, dict) and quest.get("name", "").lower() == clean_name.lower():
                    return

            current_date = time_utils.calculate_calendar_date(
                int(getattr(player, "day", 1) or 1),
                getattr(player, "calendar_settings", {}) or {},
            )

            player.quests.append(
                {
                    "name": clean_name,
                    "giver": giver or "Unknown",
                    "description": description or "No description provided.",
                    "turn_in": turn_in or "Unknown",
                    "reward": reward or "Unknown",
                    "date_received": current_date,
                }
            )
            self.refresh_display()
        except Exception as error:
            logging.exception(f"Critical error when adding quest: {error}")

    def complete_quest(self, name: str) -> None:
        """Removes a quest from the active quest log by exact case-insensitive name."""
        player = self._get_player()
        quests = getattr(player, "quests", None) if player is not None else None
        if not isinstance(quests, list):
            logging.warning("QuestsPanel.complete_quest called without a valid quest list.")
            return

        try:
            clean_name = (name or "").strip().lower()
            initial_count = len(quests)
            for quest in list(quests):
                if isinstance(quest, dict) and quest.get("name", "").lower() == clean_name:
                    quests.remove(quest)

            if len(quests) < initial_count:
                self.refresh_display()
        except Exception as error:
            logging.exception(f"Critical error when completing quest: {error}")

    def get_text(self) -> str:
        """Returns active quest text for AI context."""
        return self.display.toPlainText()
    
    def get_ai_context(self) -> str:
        """
        Returns quest data as compact plain text for the AI prompt.
        """
        lines: list[str] = ["### QUESTS"]

        try:
            player = self._get_player()
            if player is None:
                lines.append("No player loaded.")
                return "\n".join(lines)

            quests = getattr(player, "quests", []) or []
            if not isinstance(quests, list) or not quests:
                lines.append("No active quests.")
                return "\n".join(lines)

            for quest in quests:
                if not isinstance(quest, dict):
                    logging.warning("QuestsPanel: skipped malformed quest entry: %r", quest)
                    continue

                name = str(quest.get("name", "Unknown Quest")).strip() or "Unknown Quest"
                giver = str(quest.get("giver", "Unknown")).strip() or "Unknown"
                date_received = str(quest.get("date_received", "Unknown")).strip() or "Unknown"
                description = str(quest.get("description", "No description provided.")).strip()
                turn_in = str(quest.get("turn_in", "Unknown")).strip() or "Unknown"
                reward = str(quest.get("reward", "Unknown")).strip() or "Unknown"

                lines.append(
                    f"- {name}: "
                    f"Giver: {giver}; "
                    f"Date received: {date_received}; "
                    f"Description: {description}; "
                    f"How to complete: {turn_in}; "
                    f"Reward: {reward}"
                )

        except Exception as error:
            logging.exception("QuestsPanel.get_ai_context failed: %s", error)
            lines.append("Quest context unavailable due to an internal error.")

        return "\n".join(lines)


class StoryPanel(QWidget):
    """Main interactive story panel with status display, text input, and optional TTS."""

    send_requested = Signal(str)
    volume_changed = Signal(float)
    text_ready_signal = Signal(str)

    AVAILABLE_VOICES: ClassVar[dict[str, str]] = {
        "Aria (Female, US)": "en-US-AriaNeural",
        "Guy (Male, US)": "en-US-GuyNeural",
        "Jenny (Female, US)": "en-US-JennyNeural",
        "Christopher (Male, US)": "en-US-ChristopherNeural",
        "Sonia (Female, UK)": "en-GB-SoniaNeural",
        "Ryan (Male, UK)": "en-GB-RyanNeural",
        "Natasha (Female, AU)": "en-AU-NatashaNeural",
        "William (Male, AU)": "en-AU-WilliamNeural",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._status_cache = {
            "turn": "1",
            "location": "Unknown",
            "day": "Day 1",
            "time": "Morning",
            "weather": "Sunny",
            "temperature": "76",
            "dynamic_stats": [],
        }

        self.narrator_enabled = False
        self.music_volume = 100
        self.tts_volume = 100
        self.tts_rate = 0
        self.tts_voice = "en-US-AriaNeural"
        self.temp_dir = tempfile.gettempdir()
        self._unlock_queued = False
        self.text_ready_signal.connect(self.append_text)

        self._tts_check_timer = QTimer(self)
        self._tts_check_timer.setInterval(250)
        self._tts_check_timer.timeout.connect(self._check_tts_finished)
        self._tts_check_timer.start()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.header_layout = QVBoxLayout()
        self.header_layout.setSpacing(4)

        self.lbl_base_status = QLabel()
        self.lbl_base_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_base_status.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
        self.header_layout.addWidget(self.lbl_base_status)

        self.stats_layout = QVBoxLayout()
        self.stats_layout.setSpacing(2)
        self.header_layout.addLayout(self.stats_layout, stretch=1)
        root.addLayout(self.header_layout)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.txt_log.setStyleSheet(
            """
            QTextEdit {
                font-family: Consolas, 'Courier New', monospace;
                font-size: 14px;
            }
            """
        )
        root.addWidget(self.txt_log, stretch=1)

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
        self._update_status_ui()

    def _emit_volume(self, val: int) -> None:
        """Emits music volume as pygame's expected 0.0-1.0 value."""
        self.volume_changed.emit(val / 100.0)

    def _check_tts_finished(self) -> None:
        """Unlocks controls after queued narrator audio has finished."""
        if self._unlock_queued:
            try:
                if pygame.mixer.get_init() and not pygame.mixer.Channel(1).get_busy():
                    self._unlock_queued = False
                    self.set_controls_state(True, force_unlock=True)
            except Exception as error:
                logging.error(f"Error checking TTS channel status: {error}")
                self._unlock_queued = False
                self.set_controls_state(True, force_unlock=True)

    def append_text(self, markdown_string: str) -> None:
        """Converts Markdown to HTML and appends it to the story log."""
        markdown_string = (markdown_string or "").strip()
        if not markdown_string:
            return

        try:
            rendered_html = markdown.markdown(markdown_string)
            cursor = self.txt_log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)

            if not self.txt_log.document().isEmpty():
                cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
                cursor.insertHtml("<br>")

            cursor.insertHtml(rendered_html)
            self.txt_log.setTextCursor(cursor)
        except Exception as error:
            logging.error(f"Failed to append Markdown/HTML text: {error}")
            self.txt_log.append(markdown_string)

        self._scroll_to_bottom()

    def set_status(
        self,
        *,
        turn: Any = None,
        location: Any = None,
        day: Any = None,
        time: Any = None,
        weather: Any = None,
        temperature: Any = None,
        dynamic_stats: list[dict[str, Any]] | None = None,
    ) -> None:
        """Updates cached status values and redraws the status header."""
        if turn is not None:
            self._status_cache["turn"] = str(turn)
        if location is not None:
            self._status_cache["location"] = str(location)
        if day is not None:
            self._status_cache["day"] = str(day)
        if time is not None:
            self._status_cache["time"] = str(time)
        if weather is not None:
            self._status_cache["weather"] = str(weather)
        if temperature is not None:
            self._status_cache["temperature"] = str(temperature)
        if dynamic_stats is not None:
            self._status_cache["dynamic_stats"] = dynamic_stats

        self._update_status_ui()

    def _update_status_ui(self) -> None:
        """Rebuilds the status text and dynamic stat progress bars."""
        status = self._status_cache
        base_text = (
            f"Turn: {status['turn']} \n"
            f"Location: {status['location']} \n"
            f"Date: {status['day']} \n"
            f"Time: {status['time']} \n"
            f"Weather: {status['weather']} ({status['temperature']}°F)"
        )
        self.lbl_base_status.setText(base_text)
        self.lbl_base_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        while self.stats_layout.count():
            child = self.stats_layout.takeAt(0)
            widget_to_delete = child.widget() if child is not None else None

            if widget_to_delete is not None:
                widget_to_delete.deleteLater()

        stats = status.get("dynamic_stats", [])
        if not isinstance(stats, list):
            logging.warning("StoryPanel: dynamic_stats is not a list: %r", stats)
            stats = []

        for stat in stats:
            if not isinstance(stat, dict):
                logging.warning("StoryPanel: skipped malformed stat entry: %r", stat)
                continue
            if not stat.get("enabled", True):
                continue

            stat_row_layout = QHBoxLayout()
            stat_row_layout.setContentsMargins(0, 0, 0, 0)

            name_label = QLabel(f"{stat.get('name', 'Stat')}:")
            name_label.setFixedWidth(80)
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            progress_bar = QProgressBar()
            progress_bar.setMinimum(self._safe_int(stat.get("min"), default=0))
            progress_bar.setMaximum(self._safe_int(stat.get("max"), default=100))
            progress_bar.setValue(self._safe_int(stat.get("value"), default=0))
            progress_bar.setTextVisible(True)
            progress_bar.setFormat("%v / %m")
            progress_bar.setStyleSheet(
                """
                QProgressBar {
                    border: 1px solid #555;
                    border-radius: 3px;
                    text-align: center;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #4CAF50;
                }
                """
            )

            stat_row_layout.addWidget(name_label)
            stat_row_layout.addWidget(progress_bar)

            stat_wrapper = QWidget()
            stat_wrapper.setLayout(stat_row_layout)
            self.stats_layout.addWidget(stat_wrapper)

    def _safe_int(self, value: Any, *, default: int = 0) -> int:
        """Safely converts UI stat values to integers."""
        try:
            return int(value if value is not None else default)
        except (TypeError, ValueError):
            logging.exception("StoryPanel: invalid integer stat value %r", value)
            return default

    def get_log_text(self) -> str:
        """Returns the story log as plain text."""
        return self.txt_log.toPlainText()

    def set_log_text(self, text: str) -> None:
        """Replaces the story log text."""
        self.txt_log.setPlainText(text or "")
        self._scroll_to_bottom()

    def set_controls_state(self, is_enabled: bool, status_text: str | None = None, force_unlock: bool = False) -> None:
        """Enables/disables text controls, respecting queued TTS playback."""
        if is_enabled and not force_unlock:
            try:
                if pygame.mixer.get_init() and pygame.mixer.Channel(1).get_busy():
                    self._unlock_queued = True
                    return
            except Exception as error:
                logging.error(f"Error checking TTS channel status: {error}")

        self._unlock_queued = False
        self.txt_input.setEnabled(is_enabled)
        self.btn_send.setEnabled(is_enabled)

        if is_enabled:
            self.txt_input.setPlaceholderText("What do you do next?")
            self.txt_input.setFocus()
        elif status_text is not None:
            self.txt_input.setPlaceholderText(status_text)

    def _apply_phonetic_fixes(self, text: str) -> str:
        """Applies regex substitutions for common TTS mispronunciations."""
        replacements = {
            r"\btear into\b": "tare into",
            r"\btear off\b": "tare off",
            r"\btears off\b": "tares off",
            r"\btearing\b": "tare-ing",
            r"\bbow and arrow\b": "boe and arrow",
            r"\btake a bow\b": "take a bough",
            r"\bwind blows\b": "winned blows",
            r"\bwind up\b": "wined up",
            r"\blead pipe\b": "led pipe",
            r"\blead the way\b": "leed the way",
        }

        fixed_text = text
        try:
            for pattern, replacement in replacements.items():
                fixed_text = re.sub(pattern, replacement, fixed_text, flags=re.IGNORECASE)
        except Exception as error:
            logging.error(f"Error applying phonetic fixes to TTS: {error}")

        return fixed_text

    def print_text(self, text: str, *, sender: str = "GM") -> None:
        """Prints text to the story window and optionally reads it with TTS."""
        text = (text or "").strip()
        if not text:
            return

        if self.narrator_enabled and not text.startswith("> "):
            clean_text = re.sub(r"<pre.*?>.*?</pre>", "", text, flags=re.DOTALL)
            clean_text = re.sub(r"[*_~`#]", "", clean_text, re.DOTALL)
            clean_text = clean_text.replace("--", ", ").replace("-", " ")
            clean_text = clean_text.replace("\n", " ").replace("\r", "")
            clean_text = self._apply_phonetic_fixes(clean_text)
            self._generate_and_play_tts(clean_text, original_text=text)
        else:
            if text.startswith("> "):
                text = "\\" + text
            self.append_text("\n" + text)

    def _emit_send(self) -> None:
        """Emits the player's submitted command."""
        text = (self.txt_input.text() or "").strip()
        if not text:
            return
        if self.narrator_enabled:
            self.stop_tts()
        self.txt_input.clear()
        self.send_requested.emit(text)

    def _generate_and_play_tts(self, text: str, original_text: str | None = None) -> None:
        """Generates Edge TTS audio without blocking the UI thread."""

        def run_async() -> None:
            unique_filename = f"ai_adventure_tts_{uuid.uuid4().hex}.mp3"
            dynamic_tts_file = os.path.join(self.temp_dir, unique_filename)
            rate_str = f"{self.tts_rate * 5}%"
            if self.tts_rate >= 0:
                rate_str = f"+{rate_str}"

            try:
                communicate = edge_tts.Communicate(text, self.tts_voice, rate=rate_str)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(communicate.save(dynamic_tts_file))
                loop.close()

                self._play_generated_tts(dynamic_tts_file)
                if original_text is not None:
                    self.text_ready_signal.emit(original_text)
            except Exception as error:
                logging.exception("Edge TTS generation failed: %s", error)
                if original_text is not None:
                    self.text_ready_signal.emit(original_text)

        threading.Thread(target=run_async, daemon=True).start()

    def _play_generated_tts(self, filepath: str) -> None:
        """Plays a generated TTS audio file on the reserved narrator channel."""
        try:
            if pygame.mixer.get_init():
                channel = pygame.mixer.Channel(1)
                sound = pygame.mixer.Sound(filepath)
                channel.set_volume(self.tts_volume / 100.0)
                channel.play(sound)
        except Exception as error:
            logging.exception("TTS audio playback failed: %s", error)

    def stop_tts(self) -> None:
        """Stops active TTS playback and releases any queued UI unlock."""
        try:
            if pygame.mixer.get_init():
                pygame.mixer.Channel(1).stop()
        except Exception as error:
            logging.error(f"Error stopping TTS playback: {error}")

        if self._unlock_queued:
            self.set_controls_state(True, force_unlock=True)

    def play_voice_sample(self) -> None:
        """Plays a short narrator preview without printing text to the story log."""
        self.stop_tts()
        original_state = self.narrator_enabled
        self.narrator_enabled = True
        self._generate_and_play_tts("This is a sample of my voice. How do I sound?")
        self.narrator_enabled = original_state

    def set_voice_by_name(self, voice_id: str) -> None:
        """Sets the Edge TTS voice identifier."""
        self.tts_voice = voice_id

    def set_music_volume(self, val: int) -> None:
        """Updates music volume and notifies listeners."""
        self.music_volume = val
        self.volume_changed.emit(val / 100.0)

    def set_tts_volume(self, val: int) -> None:
        """Updates narrator volume, including active playback when available."""
        self.tts_volume = val
        try:
            if pygame.mixer.get_init():
                pygame.mixer.Channel(1).set_volume(val / 100.0)
        except Exception as error:
            logging.exception("Failed to update active TTS volume: %s", error)

    def set_narrator_enabled(self, enabled: bool) -> None:
        """Toggles narrator playback."""
        self.narrator_enabled = enabled
        if not enabled:
            self.stop_tts()

    def set_tts_rate(self, val: int) -> None:
        """Sets narrator speaking rate slider value."""
        self.tts_rate = val

    def _scroll_to_bottom(self) -> None:
        """Scrolls the story log to the newest text."""
        cursor = self.txt_log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.txt_log.setTextCursor(cursor)


__all__ = [
    "BasePanel",
    "JsonFilePanel",
    "MarkdownPanel",
    "InventoryPanel",
    "HistoryMarkdownPanel",
    "SkillsPanel",
    "ProcessingPanel",
    "RecipesPanel",
    "CalendarPanel",
    "QuestsPanel",
    "StoryPanel",
]
