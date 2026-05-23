# qt_ui/main_window.py
from __future__ import annotations
from PySide6.QtCore import Qt, QSettings, QByteArray, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QDockWidget,
    QWidget,
    QDialog,
    QTabWidget
)
from ai_manager import AIManager
from config import SAVES_DIR
from file_manager import FileManager
import threading, tempfile
import logging
from pathlib import Path
from .panels import (
    CalendarPanel,
    InventoryPanel,
    MarkdownPanel,
    ProcessingPanel,
    QuestsPanel,
    RecipesPanel,
    SkillsPanel,
    SpellcastingPanel,
    StoryPanel,
    HistoryMarkdownPanel
)
from .dialogs import (
    AudioSettingsDialog,
    CalendarManagerDialog,
    CreationTemplateStore,
    CreationWizard,
    CurrencyManagerDialog,
    HelpDialog,
    MainMenuDialog,
    MerchantDialog,
    MerchantItem,
    MerchantTransactionMode,
    NewGameSourceDialog,
    StatsManagerDialog,
)

class MainWindow(QMainWindow):
    """
    Qt shell for the app.

    Initial design:
    - Use dock widgets for "tabs" so the user can drag/reorder and float panels.
    - Keep the central widget as Story for now (we can change later).
    """
    
    DEFAULT_FLOATING_TAB_ORDER: tuple[str, ...] = (
        "World",
        "Inventory",
        "Calendar",
        "Skills",
        "Spellcasting",
        "Character",
        "Sales Ledger",
        "Recipes",
        "Processing",
        "Journal",
        "Quests",
        "History",
    )

    def __init__(self, app_context=None) -> None:
        super().__init__()
        self.setObjectName("AI_Adventure_Main_Window")
        self.setWindowTitle("AI RPG Adventure")

        # Reasonable default size; user can resize.
        self.resize(1100, 750)

        # Central widget: Story
        self.story_panel = StoryPanel(self)
        self.setCentralWidget(self.story_panel)
        self.app = app_context
        self.ai_manager = AIManager(self.app) if self.app is not None else None

        # Only the send_requested signal remains on the StoryPanel
        self.story_panel.send_requested.connect(self._on_send_requested)

        # Docks (stubs for now)
        self._docks: dict[str, QDockWidget] = {}
        self.world_panel = MarkdownPanel("World")
        self.journal_panel = MarkdownPanel("Journal")
        self.history_panel = HistoryMarkdownPanel()
        self.inventory_panel = InventoryPanel(app_context=self.app)
        self.skills_panel = SkillsPanel()
        self.spellcasting_panel = SpellcastingPanel(app_context=self.app)
        self.processing_panel = ProcessingPanel(app_context=self.app)
        self.recipes_panel = RecipesPanel()
        self.character_panel = MarkdownPanel("Character")
        self.calendar_panel = CalendarPanel(app_context=self.app)
        self.quests_panel = QuestsPanel(app_context=self.app)
        self.sales_ledger_panel = MarkdownPanel("Sales Ledger")
        self._register_panel_docks()

        # Allow docks to tab together when dragged into same area
        self.setDockOptions(
            QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        self._setup_menu_bar()
        
    def open_merchant_dialog(
        self,
        items: list[MerchantItem],
        mode: MerchantTransactionMode = MerchantTransactionMode.BUY,
    ) -> None:
        """
        Opens the merchant shop and applies purchases directly to currency/inventory.

        Args:
            items: Parsed merchant items from a [[MERCHANT: ...]] tag.
        """

        if self.app is None:
            logging.warning("Cannot open merchant dialog because app context is missing.")
            return

        if not items:
            logging.warning("Cannot open merchant dialog with no valid items.")
            return

        dialog = MerchantDialog(
            parent=self,
            items=items,
            player=self.app.player,
            mode=mode,
        )
        dialog.setStyleSheet(self.styleSheet())

        # Gate story input while shop is open, while still allowing outside clicks to unfocus.
        self.story_panel.set_controls_state(False, "Merchant shop open.")

        def finish_dialog(result: int) -> None:
            ai_event_started = False

            try:
                merchant_event_prompt = None

                if result == int(QDialog.DialogCode.Accepted):
                    merchant_event_prompt = self._apply_merchant_result(dialog)

                if self.ai_manager is not None:
                    if merchant_event_prompt:
                        self.ai_manager.handle_merchant_event(
                            merchant_event_prompt,
                            history_note=f"(System merchant event)\n{merchant_event_prompt}",
                        )
                        ai_event_started = True

                    elif dialog.left_without_purchase:
                        leave_prompt = (
                            "The player leaves the merchant without buying anything. "
                            "Return them to the nearby main area."
                        )

                        self.ai_manager.handle_merchant_event(
                            leave_prompt,
                            history_note=f"(System merchant event)\n{leave_prompt}",
                        )
                        ai_event_started = True

            finally:
                if not ai_event_started:
                    self.story_panel.set_controls_state(True)

                dialog.deleteLater()

        dialog.finished.connect(finish_dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        
    def _apply_merchant_result(self, dialog: MerchantDialog) -> str | None:
        """
        Applies completed merchant results to inventory.

        Buying adds items.
        Selling removes items.

        Args:
            dialog: Completed MerchantDialog.
        """

        if self.app is None:
            logging.warning("Cannot apply merchant result because app context is missing.")
            return

        inventory_panel = self.app.notebook_widgets.get("Inventory")
        if inventory_panel is None:
            logging.error("Cannot apply merchant result because Inventory panel is missing.")
            return

        purchases = getattr(dialog, "final_purchases", []) or []
        if not purchases:
            return

        sold_or_bought_summary: list[str] = []

        for purchase in purchases:
            item = purchase.item
            quantity = purchase.quantity

            if quantity <= 0:
                continue

            if dialog.mode == MerchantTransactionMode.SELL:
                try_remove_item = getattr(inventory_panel, "try_remove_item", None)

                if callable(try_remove_item):
                    removed = try_remove_item(item.name, quantity)
                else:
                    logging.warning("Inventory panel has no try_remove_item method. Falling back to autonomous_remove.")
                    inventory_panel.autonomous_remove(f"{item.name} | {quantity}")
                    removed = True

                if not removed:
                    logging.error("Merchant sell failed to remove inventory item: %s x %s", quantity, item.name)
                    continue

                sold_or_bought_summary.append(f"{quantity} x {item.name}")
                continue

            add_payload = f"{item.item_type} | {item.name} | {item.description} | {quantity}"

            try:
                inventory_panel.autonomous_add(add_payload)
                sold_or_bought_summary.append(f"{quantity} x {item.name}")
            except Exception as error:
                logging.exception("Failed to add merchant purchase to inventory: %s", error)

        try:
            inventory_panel.refresh_display()
        except Exception as error:
            logging.exception("Failed to refresh inventory after merchant transaction: %s", error)

        try:
            self.app._sync_player_state_to_ui()
            self.app.save_game()
        except Exception as error:
            logging.exception("Failed to sync/save after merchant transaction: %s", error)

        if not sold_or_bought_summary:
            return

        action_word = "Sold" if dialog.mode == MerchantTransactionMode.SELL else "Purchased"

        self.story_panel.print_text(
            f"{action_word}: {', '.join(sold_or_bought_summary)}.",
            sender="System",
        )
        
        return self._build_merchant_event_prompt(dialog, purchases)
    
    def _build_merchant_event_prompt(
        self,
        dialog: MerchantDialog,
        purchases: list,
    ) -> str:
        """
        Builds the compact AI prompt for a completed merchant transaction.

        Args:
            dialog: Completed merchant dialog.
            purchases: Final purchased or sold item records.

        Returns:
            A compact, deterministic merchant event summary.
        """

        item_lines: list[str] = []
        total_base_units = 0

        for purchase in purchases:
            item = purchase.item
            quantity = max(0, int(purchase.quantity or 0))

            if quantity <= 0:
                continue

            line_total = item.price_base_units * quantity
            total_base_units += line_total

            item_type = str(getattr(item, "item_type", "") or "").strip()
            description = str(getattr(item, "description", "") or "").strip()

            item_text = f"- {quantity} x {item.name}"
            if item_type:
                item_text += f" ({item_type})"

            item_text += f"; {item.price_base_units} base units each"

            if description:
                item_text += f"; {description}"

            item_lines.append(item_text)

        if not item_lines:
            logging.warning("Tried to build merchant event prompt with no valid item lines.")
            return ""

        player = getattr(self.app, "player", None)
        total_text = f"{total_base_units} base units"
        remaining_text = ""

        formatter = getattr(player, "get_formatted_currency", None)
        if callable(formatter):
            try:
                total_text = formatter(total_base_units)
                remaining_text = formatter()
            except Exception as error:
                logging.exception("Failed to format merchant event currency: %s", error)

        if dialog.mode == MerchantTransactionMode.SELL:
            action_sentence = "The player sold the following items to the merchant:"
            total_sentence = f"Total received: {total_text}."
        else:
            action_sentence = "The player purchased the following items from the merchant:"
            total_sentence = f"Total spent: {total_text}."

        remaining_sentence = f"Remaining wealth after the transaction: {remaining_text}." if remaining_text else ""

        return (
            f"{action_sentence}\n"
            f"{chr(10).join(item_lines)}\n"
            f"{total_sentence}\n"
            f"{remaining_sentence}\n"
            "The inventory and currency updates have already been applied by the app. "
            "Do not output inventory or currency tags for this transaction. "
            "Continue from this confirmed result."
        ).strip()
    
    def _setup_menu_bar(self):
        """Creates the native OS-style top-left menu bar."""
        menu_bar = self.menuBar()
    
        # --- NEW: Expanded styling to apply to the Menu Bar AND the Dock Panels ---
        # Note: We apply this to `self` (the whole window) so it cascades down to the docks
        self.setStyleSheet("""
            QTabBar::tab {
                background: #333333;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 4px;
                margin-bottom: 2px; /* Adds a tiny gap between vertical tabs */
            }
            QTabBar::tab:selected {
                background: #4CAF50;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background: #444444;
            }
            QMenuBar {
                background-color: #2b2b2b;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                border-bottom: 2px solid #4CAF50;
                padding: 4px;
            }
            QMenuBar::item {
                spacing: 3px;
                padding: 4px 12px;
                background: transparent;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background: #4CAF50;
                color: white;
            }
            QMenu {
                background-color: #333333;
                color: white;
                border: 1px solid #555555;
                font-weight: normal;
            }
            QMenu::item:selected {
                background-color: #4CAF50;
            }
            
            /* --- NEW: Dock Widget Styling --- */
            QDockWidget {
                border: 2px solid #555555; /* Visible border around the whole dock */
                font-weight: bold;
                color: #ffffff;
            }
            QDockWidget::title {
                background: #333333;
                text-align: center;
                padding: 6px;
            }
            /* Adds a border directly to the contents inside the dock to separate them from the title */
            QDockWidget > QWidget {
                border: 1px solid #444444; 
                background-color: #2b2b2b;
            }
        """)
        
        # 1. Game Menu
        game_menu = menu_bar.addMenu("Game")
        
        action_save = game_menu.addAction("Save / Load Game")
        action_save.triggered.connect(self._on_menu_requested)
        
        action_currencies = game_menu.addAction("Manage Currencies")
        action_currencies.triggered.connect(self.open_currency_menu)
        
        action_stats = game_menu.addAction("Manage Tracked Stats")
        action_stats.triggered.connect(self.open_stats_menu)
        
        action_calendar = game_menu.addAction("Manage Calendar")
        action_calendar.triggered.connect(self.open_calendar_menu)
        
        game_menu.addSeparator()
        
        action_audio = game_menu.addAction("Audio Settings...")
        action_audio.triggered.connect(self.open_audio_menu)
        
        game_menu.addSeparator()
        action_help = game_menu.addAction("Help")
        action_help.triggered.connect(self.open_help_menu)
        # --- 2. View Menu (NEW) ---
        view_menu = menu_bar.addMenu("View")
        action_reset_layout = view_menu.addAction("Reset Layout")
        action_reset_layout.triggered.connect(self.reset_layout_to_default)
        view_menu.addSeparator()
        # Qt's QDockWidget comes with a built-in toggle action that acts as a checkbox!
        for title, dock in self._docks.items():
            view_menu.addAction(dock.toggleViewAction())

    def apply_initial_new_game_layout(self) -> None:
        """
        Applies and saves the default floating tab layout for a newly-created adventure.

        This is deferred by one Qt event-loop tick so dock geometry and tabification
        behave the same way they do when the user clicks View -> Reset Layout.
        """
        def apply_and_save() -> None:
            try:
                self._apply_default_floating_tab_layout()
                self._save_ui_state()
            except Exception as error:
                logging.exception("Failed to apply initial new-game UI layout: %s", error)

        QTimer.singleShot(0, apply_and_save)
    
    def _center_dialog_on_screen(
    self,
    dialog: QDialog,
    *,
    preferred_width: int,
    preferred_height: int,
) -> None:
        """
        Resizes and centers a dialog on the screen used by the main window.

        The requested size is clamped to the available screen area so the dialog
        does not open partially off-screen on smaller displays.
        """
        if dialog is None:
            logging.warning("Tried to center a missing dialog.")
            return

        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()

        if screen is None:
            logging.warning("Could not find an active screen for dialog centering.")
            return

        available_geometry = screen.availableGeometry()

        safe_width = min(
            preferred_width,
            max(600, available_geometry.width() - 120),
        )
        safe_height = min(
            preferred_height,
            max(500, available_geometry.height() - 120),
        )

        dialog.resize(safe_width, safe_height)

        dialog_geometry = dialog.frameGeometry()
        dialog_geometry.moveCenter(available_geometry.center())
        dialog.move(dialog_geometry.topLeft())


    def _exec_centered_creation_dialog(
        self,
        dialog: QDialog,
        *,
        preferred_width: int,
        preferred_height: int,
    ) -> int:
        """
        Executes a creation-flow dialog as an application-modal centered window.

        The dialog is intentionally not parented to the main window, because the
        main window is hidden while character creation is active.
        """
        if dialog is None:
            logging.warning("Cannot execute a missing creation dialog.")
            return int(QDialog.DialogCode.Rejected)

        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setStyleSheet(self.styleSheet())

        # Center after the dialog enters its modal event loop so frame geometry is valid.
        QTimer.singleShot(
            0,
            lambda: self._center_dialog_on_screen(
                dialog,
                preferred_width=preferred_width,
                preferred_height=preferred_height,
            ),
        )

        return int(dialog.exec())
    
    def reset_layout_to_default(self) -> None:
        """
        Resets the current dock layout to the default floating tab window layout.
        """
        try:
            self._apply_default_floating_tab_layout()
            self._save_ui_state()
        except Exception as error:
            logging.exception("Failed to reset UI layout: %s", error)
    
    def _apply_default_floating_tab_layout(self) -> None:
        """
        Groups all secondary panels into one floating tabbed dock window.

        The Story panel remains the central widget. This is intended as the default
        first-launch layout; saved per-adventure layouts can still override it through
        restoreState().
        """
        try:
            docks: list[QDockWidget] = []

            for dock_title in self.DEFAULT_FLOATING_TAB_ORDER:
                dock = self._docks.get(dock_title)

                if dock is None:
                    logging.warning("Default layout skipped missing dock: %s", dock_title)
                    continue

                dock.show()
                dock.setFloating(False)

                # Put every dock in one area first so tabification is stable.
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                docks.append(dock)

            if not docks:
                logging.warning("Default floating layout could not be applied because no docks were found.")
                return

            anchor_dock = docks[0]

            for dock in docks[1:]:
                self.tabifyDockWidget(anchor_dock, dock)

            # Make Inventory the visible tab by default.
            anchor_dock.raise_()

            # Float the whole tabified dock group.
            anchor_dock.setFloating(True)

            screen = self.screen()
            if screen is not None:
                available_geometry = screen.availableGeometry()

                target_width = min(
                    max(900, self.width()),
                    max(500, available_geometry.width() - 80),
                )
                target_height = min(
                    max(650, self.height()),
                    max(450, available_geometry.height() - 120),
                )

                main_geometry = self.frameGeometry()

                target_x = min(
                    main_geometry.x() + 80,
                    available_geometry.right() - target_width,
                )
                target_y = min(
                    main_geometry.y() + 80,
                    available_geometry.bottom() - target_height,
                )

                target_x = max(available_geometry.x(), target_x)
                target_y = max(available_geometry.y(), target_y)

                anchor_dock.resize(target_width, target_height)
                anchor_dock.move(target_x, target_y)
            else:
                anchor_dock.resize(1000, 700)

        except Exception as error:
            logging.exception("Failed to apply default floating tab layout: %s", error)
    
    def _add_dock(
        self,
        title: str,
        widget: QWidget,
        area: Qt.DockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea,
    ) -> QDockWidget:
        """
        Creates a dock widget, registers it with the main window, and stores it.

        The area argument is only the initial staging area. Final placement is handled
        by layout methods or by restoreState().
        """
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setObjectName(f"Dock_{title.replace(' ', '_')}")

        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.addDockWidget(area, dock)
        self._docks[title] = dock

        return dock
        
    def _register_panel_docks(self) -> None:
        """
        Creates and registers all dock widgets with Qt.

        Docks are initially added to one neutral staging area. The real layout is
        applied later by _apply_default_floating_tab_layout() or restored from
        ui_layout.ini when loading an existing save.
        """
        dock_widgets: dict[str, QWidget] = {
            "World": self.world_panel,
            "Inventory": self.inventory_panel,
            "Calendar": self.calendar_panel,
            "Skills": self.skills_panel,
            "Spellcasting": self.spellcasting_panel,
            "Character": self.character_panel,
            "Sales Ledger": self.sales_ledger_panel,
            "Recipes": self.recipes_panel,
            "Processing": self.processing_panel,
            "Journal": self.journal_panel,
            "Quests": self.quests_panel,
            "History": self.history_panel,
        }

        for dock_title in self.DEFAULT_FLOATING_TAB_ORDER:
            widget = dock_widgets.get(dock_title)

            if widget is None:
                logging.warning("Skipped missing dock widget during registration: %s", dock_title)
                continue

            self._add_dock(dock_title, widget)

    def get_dock(self, title: str) -> QDockWidget | None:
        return self._docks.get(title)
    
    # qt_ui/main_window.py

    def closeEvent(self, event):
        """
        Ensures the game state is saved when the window is closed. 
        Logs any errors that occur during the shutdown sequence to prevent silent data loss.
        """
        try:
            if self.app is not None:
                self._save_ui_state()
                self.app.save_game()
        except Exception as error:
            # We catch and log the error, rather than silently passing, 
            # so we can actually debug save-file corruption if it happens on exit.
            logging.error(f"CRITICAL ERROR during application shutdown: {error}")

        super().closeEvent(event)
    
    def _on_send_requested(self, text: str) -> None:
        if self.ai_manager is None:
            self.story_panel.print_text("AI Manager not initialized.", sender="System")
            return
        self.ai_manager.handle_player_action(text)

    def _on_menu_requested(self) -> None:
        if self.app is None:
            self.story_panel.print_text("Menu not available (app context missing).", sender="System")
            return

        try:
            self.app.save_game()
        except Exception:
            pass

        dlg = MainMenuDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.selected_save:
            return

        save_name = dlg.selected_save
        save_path_obj = SAVES_DIR / save_name
        save_path = str(save_path_obj)
        savegame_path = save_path_obj / "savegame.json"

        self.story_panel.set_log_text("")

        if savegame_path.exists():
            FileManager.update_logger_path(save_name)
            self.setWindowTitle(f"AI RPG Adventure - {save_name}")

            self.app.load_savegame_state(save_path)
            self._load_ui_state(save_path)
            self.app.generate_recap()
            return

        # New game flow: do not create the real save folder yet.
        self.app.conversation_history = []

        game_window_was_visible = self.isVisible()

        try:
            if game_window_was_visible:
                self.hide()

            source_dialog = NewGameSourceDialog(None)
            source_result = self._exec_centered_creation_dialog(
                source_dialog,
                preferred_width=700,
                preferred_height=500,
            )

            if source_result != int(QDialog.DialogCode.Accepted):
                self.story_panel.print_text("System: New game creation cancelled.", sender="System")
                return

            template_data = CreationTemplateStore.load_template(source_dialog.selected_template_path)

            wizard = CreationWizard(None, template_data=template_data)
            wizard_result = self._exec_centered_creation_dialog(
                wizard,
                preferred_width=1120,
                preferred_height=820,
            )

            if wizard_result != int(QDialog.DialogCode.Accepted):
                self.story_panel.print_text("System: New game creation cancelled.", sender="System")
                return

            wizard_data = wizard.get_wizard_data()

        finally:
            if game_window_was_visible:
                self.show()
                self.raise_()
                self.activateWindow()

        try:
            staging_path = Path(
                tempfile.mkdtemp(prefix=f"ai_adventure_pending_{save_name}_")
            )

            self.app.begin_pending_adventure(
                final_save_path=save_path_obj,
                staging_save_path=staging_path,
            )
            
            self.apply_initial_new_game_layout()

        except Exception as error:
            logging.exception("Failed to prepare pending adventure: %s", error)
            self.story_panel.print_text(
                "System: Could not prepare the new adventure. Check the log file.",
                sender="System",
            )
            return

        self.app.player.world_currencies = wizard_data["currencies"]
        self.app.player.tracked_stats = wizard_data["stats"]

        calendar_data = wizard_data.get("calendar", {})
        calendar_settings = calendar_data.get("settings", {}) if isinstance(calendar_data, dict) else {}

        if (
            isinstance(calendar_settings, dict)
            and calendar_settings.get("weekdays")
            and calendar_settings.get("months")
        ):
            self.app.player.calendar_settings = calendar_settings

        self.app._sync_player_state_to_ui()
        self.story_panel.print_text("System: Compiling universe parameters...", sender="System")

        if self.ai_manager is not None:
            threading.Thread(
                target=self.ai_manager.start_new_game_from_wizard,
                args=(wizard_data,),
                daemon=True,
            ).start()
        else:
            self.story_panel.print_text("System: New game creation cancelled.", sender="System")
    
    def _save_ui_state(self) -> None:
        """Saves the exact layout, dock positions, window size, and panel visibility."""
        if self.app and getattr(self.app, 'current_adventure_path', None):
            ini_path = Path(self.app.current_adventure_path) / "ui_layout.ini"
            
            # QSettings handles the complex Qt serialization automatically
            settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
            settings.setValue("geometry", self.saveGeometry())
            settings.setValue("windowState", self.saveState())
            settings.setValue("volume_level", self.story_panel.music_volume)
            settings.setValue("narrator_enabled", self.story_panel.narrator_enabled)
            settings.setValue("narrator_volume", self.story_panel.tts_volume)
            settings.setValue("narrator_rate", self.story_panel.tts_rate)
            settings.setValue(
                "skip_load_narration",
                bool(getattr(self.story_panel, "skip_load_narration", True)),
            )
            current_voice = self.story_panel.tts_voice
            if current_voice:
                settings.setValue("narrator_voice", current_voice)

    def _load_ui_state(self, save_path: str) -> None:
        """
        Restores the UI layout (window size, dock positions, and media settings) 
        from the save folder if it exists. 
        
        Includes explicit type-casting for QSettings values to satisfy strict 
        type checkers and prevent runtime crashes from corrupted .ini data.
        """
        ini_file = Path(save_path) / "ui_layout.ini"
        if not ini_file.exists():
            return
            
        try:
            # QSettings requires a string for the file path
            settings = QSettings(str(ini_file), QSettings.Format.IniFormat)
            
            # --- Layout Restoration ---
            raw_geometry = settings.value("geometry")
            raw_state = settings.value("windowState")
            
            # Typecast safely to QByteArray
            if isinstance(raw_geometry, str):
                raw_geometry = raw_geometry.encode('utf-8')
            if isinstance(raw_geometry, bytes):
                raw_geometry = QByteArray(raw_geometry)
                
            if isinstance(raw_state, str):
                raw_state = raw_state.encode('utf-8')
            if isinstance(raw_state, bytes):
                raw_state = QByteArray(raw_state)
            
            # 1. Restore the window geometries and binary state blobs first
            if raw_geometry:
                self.restoreGeometry(raw_geometry)
            if raw_state:
                self.restoreState(raw_state)
                
            # 2. Force the global tab recalculation LAST
            # Using the AllDockWidgetAreas bitmask here ensures Qt redraws the tabs 
            # to the West, permanently overriding whatever was loaded from the .ini blob.
            #self.setTabPosition(
            #    Qt.DockWidgetArea.AllDockWidgetAreas, 
            #    QTabWidget.TabPosition.West
            #)
                
            # --- Settings Restoration ---
            
            # 1. Music Volume
            # We explicitly cast the generic object to a string first. 
            # This proves to the type checker that float() can safely parse it.
            raw_volume = settings.value("volume_level", 100)
            try:
                volume_string = str(raw_volume)
                self.story_panel.set_music_volume(int(float(volume_string)))
            except (ValueError, TypeError) as error:
                logging.error(f"Failed to parse music volume, defaulting to 100. Error: {error}")
                self.story_panel.set_music_volume(100)
                
            # 2. TTS Volume
            raw_tts_volume = settings.value("narrator_volume", 100)
            try:
                tts_volume_string = str(raw_tts_volume)
                self.story_panel.set_tts_volume(int(float(tts_volume_string)))
            except (ValueError, TypeError) as error:
                logging.error(f"Failed to parse TTS volume, defaulting to 100. Error: {error}")
                self.story_panel.set_tts_volume(100)
            
            # 3. TTS Rate
            raw_tts_rate = settings.value("narrator_rate", 0)
            try:
                tts_rate_string = str(raw_tts_rate)
                self.story_panel.set_tts_rate(int(float(tts_rate_string)))
            except (ValueError, TypeError) as error:
                logging.error(f"Failed to parse TTS rate, defaulting to 0. Error: {error}")
                self.story_panel.set_tts_rate(0)
                
            # 4. Narrator Toggle
            raw_narrator_enabled = settings.value("narrator_enabled", False)
            narrator_string = str(raw_narrator_enabled).lower()
            # Safely check if the string representation implies True
            is_narrator_enabled = narrator_string == 'true'
            self.story_panel.set_narrator_enabled(is_narrator_enabled)
            
            raw_skip_load_narration = settings.value("skip_load_narration", True)
            skip_load_narration_string = str(raw_skip_load_narration).strip().lower()
            skip_load_narration = skip_load_narration_string in {"true", "1", "yes", "on"}

            self.story_panel.set_skip_load_narration(skip_load_narration)
            
            # 5. Narrator Voice
            raw_voice_name = settings.value("narrator_voice", "")
            if raw_voice_name:
                self.story_panel.set_voice_by_name(str(raw_voice_name))

        except Exception as general_error:
            logging.error(f"Critical failure while loading UI state from {ini_file}. Details: {general_error}")

    def open_currency_menu(self):
        try:
            if self.app == None: return
            # Pass existing currencies into the dialog so they can be edited!
            dialog = CurrencyManagerDialog(self, existing_currencies=self.app.player.world_currencies)
            
            if dialog.exec(): 
                saved_currencies = dialog.final_currency_data
                
                # 1. Update the player class
                self.app.player.world_currencies = saved_currencies
                
                # 2. Force an immediate save to lock in the new economy
                self.app.save_game()
                
                sorted_for_msg = sorted(saved_currencies, key=lambda x: int(x.get("value", 1)), reverse=True)
                lowest_coin_name = sorted_for_msg[-1].get("name", "base units") if sorted_for_msg else "base units"
                
                # 3. Refresh the inventory UI to use the new math
                if hasattr(self.inventory_panel, "refresh_display"):
                    self.inventory_panel.refresh_display()
                    pass
                
        except Exception as e:
            error_msg = f"Error opening currency menu: {str(e)}"
            logging.exception(error_msg)
            self.story_panel.print_text(error_msg, sender="System Error")
            
    def open_help_menu(self):
        import logging
        try:
            # We don't need to pass data, just open it!
            dialog = HelpDialog(self)
            dialog.exec()
        except Exception as e:
            error_msg = f"Error opening help menu: {str(e)}"
            logging.exception(error_msg)
            self.story_panel.print_text(error_msg, sender="System Error")
            
    def open_calendar_menu(self):
        if not self.app: return
        try:
            dialog = CalendarManagerDialog(self, existing_calendar=self.app.player.calendar_settings)
            if dialog.exec(): 
                self.app.player.calendar_settings = dialog.final_calendar_data
                self.app.save_game()
                self.app._sync_player_state_to_ui()
        except Exception as e:
            error_msg = f"Error opening calendar menu: {str(e)}"
            logging.exception(error_msg)
            self.story_panel.print_text(error_msg, sender="System Error")
            
            
    def open_stats_menu(self):
        if self.app == None: return
        try:
            dialog = StatsManagerDialog(self, existing_stats=self.app.player.tracked_stats)
            if dialog.exec(): 
                saved_stats = dialog.final_stats_data
                self.app.player.tracked_stats = saved_stats
                self.app.save_game()
                self.app._sync_player_state_to_ui()

        except Exception as e:
            error_msg = f"Error opening stats menu: {str(e)}"
            logging.exception(error_msg)
            self.story_panel.print_text(error_msg, sender="System Error")
            
    def open_audio_menu(self):
        if not self.app: return
        dialog = AudioSettingsDialog(self, self.story_panel)
        if dialog.exec(): 
            # Save the new layout values immediately if "OK" is clicked
            self._save_ui_state()