# qt_ui/recipes_panel.py
from __future__ import annotations
import csv, logging, os
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
)
from tabulate import tabulate


class RecipesPanel(QWidget):
    """Qt Recipes panel backed by recipes.csv.

    Minimal migration goal:
    - Load recipes.csv and show them as a table
    - Support [[RECIPE: ...]] tags via add_recipe_from_tag
    """

    COLUMNS = [
        "recipe_name",
        "ingredient_1",
        "ingredient_1_amount",
        "ingredient_2",
        "ingredient_2_amount",
        "ingredient_3",
        "ingredient_3_amount"
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.base_path: str | None = None
        self.csv_path: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.lbl_title = QLabel("Recipes")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_title.hide()
        bar.addWidget(self.lbl_title, stretch=1)

        self.lbl_state = QLabel("")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        bar.addWidget(self.lbl_state)

        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setFixedWidth(90)
        self.btn_reload.clicked.connect(self.refresh_display)
        bar.addWidget(self.btn_reload)

        self.btn_save = QPushButton("Save")
        self.btn_save.setFixedWidth(90)
        self.btn_save.clicked.connect(self._touch_save)
        bar.addWidget(self.btn_save)

        root.addLayout(bar)

        self.display = QPlainTextEdit()
        self.display.setReadOnly(True)
        self.display.setFont(QFont("Consolas", 11))
        self.display.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self.display, stretch=1)

        self._set_state("No save loaded")

    def set_base_path(self, save_folder: str) -> None:
        if not save_folder:
            return
        try:
            os.makedirs(save_folder, exist_ok=True)
        except Exception:
            logging.exception("Failed to ensure save folder exists")

        self.base_path = save_folder
        self.csv_path = os.path.join(save_folder, "recipes.csv")
        self._ensure_csv_exists()
        self.refresh_display()

    def get_text(self) -> str:
        # For AI context, return a readable list rather than the whole table.
        if not self.csv_path or not os.path.exists(self.csv_path):
            return "No known recipes."

        rows = self._read_rows()
        if not rows:
            return "No known recipes."

        out = []
        for r in rows:
            name = (r.get("recipe_name") or "Unknown").strip()
            ings = []
            for i in range(1, 4):
                ing = (r.get(f"ingredient_{i}") or "").strip()
                amt = (r.get(f"ingredient_{i}_amount") or "").strip()
                if ing:
                    ings.append(f"{ing} (x{amt or '1'})")
            out.append(f"- {name}: {', '.join(ings)}")
        return "\n".join(out)

    def refresh_display(self) -> None:
        if not self.csv_path:
            self.display.setPlainText("(No save loaded)")
            return
        
        try:
            self._ensure_csv_exists()
            rows = self._read_rows()
            if not rows:
                self.display.setPlainText("RECIPES\n\n(None)\n")
                self._set_state("")
                return

            headers = ["Recipe", "Ingredients"]
            table_rows = []
            for r in rows:
                name = (r.get("recipe_name") or "Unknown").strip()
                ing_parts = []
                for i in range(1, 4):
                    ing = (r.get(f"ingredient_{i}") or "").strip()
                    amt = (r.get(f"ingredient_{i}_amount") or "").strip()
                    if ing:
                        ing_parts.append(f"{ing}: {amt or '1'}")
                table_rows.append([name, ", ".join(ing_parts)])

            txt = "RECIPES\n" + tabulate(table_rows, headers, tablefmt="rounded_grid") + "\n"
            self.display.setPlainText(txt)
            self._set_state("")
        except Exception as e:
            logging.exception(f"Critical error during refreshing recipes panel display: {e}")

    def _ensure_csv_exists(self) -> None:
        if not self.csv_path:
            return
        if os.path.exists(self.csv_path):
            return
        try:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=self.COLUMNS)
                w.writeheader()
        except Exception:
            logging.exception("RecipesPanel: failed to create recipes.csv")

    def _read_rows(self) -> list[dict]:
        if not self.csv_path or not os.path.exists(self.csv_path):
            return []
        try:
            with open(self.csv_path, "r", newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                rows = [dict(row) for row in r]
        except Exception as e:
            logging.error(f"RecipesPanel: failed to read CSV: {e}")
            return []

        # Normalize missing cols
        for row in rows:
            for c in self.COLUMNS:
                row.setdefault(c, "")
        return rows

    def _write_rows(self, rows: list[dict]) -> None:
        if not self.csv_path:
            return
        try:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=self.COLUMNS)
                w.writeheader()
                for row in rows:
                    clean = {c: (row.get(c, "") or "") for c in self.COLUMNS}
                    w.writerow(clean)
            self._set_state("Saved")
        except Exception:
            logging.exception("RecipesPanel: failed to write CSV")
        self.refresh_display()

    def _touch_save(self) -> None:
        # Manual Save button doesn't have an editor yet; it just marks saved.
        self._set_state("Saved")

    def _set_state(self, text: str) -> None:
        self.lbl_state.setText(text or "")

    # ---- AI tag helper ----

    def add_recipe_from_tag(self, tag_content: str):
        """Parses: "Name | Ing1: 5, Ing2: 2" """
        if not self.csv_path:
            return "Invalid csv path."

        try:
            parts = [p.strip() for p in (tag_content or "").split("|")]
            if len(parts) < 2:
                return "System: Invalid Recipe Tag Format."

            r_name = parts[0]
            ing_string = parts[1]

            # Parse ingredients
            ing_list: list[tuple[str, str]] = []
            for raw in (ing_string or "").split(","):
                raw = raw.strip()
                if not raw:
                    continue
                if ":" in raw:
                    i_name, i_amt = raw.split(":", 1)
                    ing_list.append((i_name.strip(), i_amt.strip() or "1"))
                else:
                    ing_list.append((raw.strip(), "1"))

            # Load
            rows = self._read_rows()
            if any((row.get("recipe_name") or "").strip().lower() == r_name.lower() for row in rows):
                return f"System: Recipe '{r_name}' already known."
            new_row = {c: "" for c in self.COLUMNS}
            new_row["recipe_name"] = r_name
            for i, (n, a) in enumerate(ing_list[:len(ing_list)], start=1):
                new_row[f"ingredient_{i}"] = n
                new_row[f"ingredient_{i}_amount"] = a

            rows.append(new_row)
            self._write_rows(rows)
            return f"System: Learned recipe for {r_name}."
        except Exception as e:
            logging.error(f"RecipesPanel.add_recipe_from_tag failed: {e}")
            return f"System: Error learning recipe ({e})"