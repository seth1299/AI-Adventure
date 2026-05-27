import os, re
import sys
import json
import logging
from config import SAVES_DIR, APP_NAME
from pathlib import Path

class FileManager:
    LOG_FILE_NAME = f"{APP_NAME}.log"

    @staticmethod
    def _configure_single_log_file(log_file_path: Path, *, mode: str = "a") -> None:
        """
        Routes all application logging output to one active .log file.

        Args:
            log_file_path: Destination log file path.
            mode: File open mode. Use "w" for a fresh startup log and "a" when
                redirecting to a save-specific log so existing entries are preserved.
        """
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        clean_mode = str(mode or "a").strip().lower()
        if clean_mode not in {"a", "w"}:
            clean_mode = "a"

        logger = logging.getLogger()
        logger.setLevel(logging.INFO)

        for handler in logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                handler.flush()
                handler.close()
                logger.removeHandler(handler)

        file_handler = logging.FileHandler(
            str(log_file_path),
            mode=clean_mode,
            encoding="utf-8",
        )

        formatter = logging.Formatter(
            "%(levelname)s | %(asctime)s | %(filename)s | %(funcName)s | line %(lineno)d:\n"
            "%(message)s\n",
            datefmt="%m/%d/%Y at %I:%M %p",
        )

        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        logging.getLogger("phonemizer").setLevel(logging.ERROR)
        
    @staticmethod
    def _build_log_file_name(save_name: str | None = None) -> str:
        """
        Builds a safe log filename.

        Args:
            save_name: Optional save-folder name. When provided, this becomes
                the base log filename.

        Returns:
            A safe .log filename.
        """
        raw_name = str(save_name or "").strip()

        if not raw_name:
            return FileManager.LOG_FILE_NAME

        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_name).strip("_")

        if not safe_name:
            logging.warning("Save name %r produced an empty log filename. Using app log name.", save_name)
            return FileManager.LOG_FILE_NAME

        return f"{safe_name}.log"

    @staticmethod
    def resource_path(relative_path):
        """Get absolute path to resource, works for dev and for PyInstaller"""
        base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
        return os.path.join(base_path, relative_path)

    @staticmethod
    def setup_initial_logging() -> None:
        """
        Sets up the basic logger on startup with a user-friendly timestamp format.
        Omits leading zeroes for the month, day, and hour, and excludes seconds.
        """
        log_file_path = SAVES_DIR / FileManager.LOG_FILE_NAME

        try:
            FileManager._configure_single_log_file(log_file_path, mode = "w")
            logging.info("Logging initialized at %s", log_file_path)
        except Exception as logging_initialization_error:
            fallback_error_log_path = Path.cwd() / FileManager.LOG_FILE_NAME
            try:
                FileManager._configure_single_log_file(fallback_error_log_path)
                logging.exception(
                    "Failed to initialize primary logging at %s. Using fallback log file at %s.",
                    log_file_path,
                    fallback_error_log_path,
                )
            except Exception:
                raise RuntimeError(
                    f"Failed to initialize logging at {log_file_path} or {fallback_error_log_path}."
                ) from logging_initialization_error
                
    @staticmethod
    def create_file_if_not_exists(file_path: str, default_content: str = "") -> None:
        """
        Checks if a file exists at the specified path, and creates it with default content if it does not.
        Utilizes the class's internal write method to maintain consistent error handling and logging.

        Args:
            file_path (str): The absolute or relative path to the file.
            default_content (str): The initial text content to write if the file is created. Defaults to an empty string.
        """
        try:
            if not os.path.exists(file_path):
                # Encapsulating the write operation by calling the existing write_text_file method
                FileManager.write_text_file(file_path, default_content)
                logging.info(f"Initialized missing file at: {file_path}")
        except Exception as file_creation_error:
            logging.error(f"Failed to check or create file at {file_path}. Exception details: {file_creation_error}")

    @staticmethod
    def update_logger_path(save_name: str = "") -> None:
        """
        Switches the logging output to a specific save folder.

        Args:
            save_name: The name of the specific save folder. If blank, the
                app-level log file is used in the saves directory.
        """
        try:
            clean_save_name = str(save_name or "").strip()
            save_directory = SAVES_DIR / clean_save_name if clean_save_name else SAVES_DIR
            save_directory.mkdir(parents=True, exist_ok=True)

            log_file_name = FileManager._build_log_file_name(clean_save_name)
            new_log_path = save_directory / log_file_name

            FileManager._configure_single_log_file(new_log_path, mode="a")
            logging.info("Logging redirected to %s", new_log_path)

        except Exception as logger_switch_error:
            logging.exception(
                "Failed to switch logger path. Exception details: %s",
                logger_switch_error,
            )

    # --- RAW I/O METHODS ---

    @staticmethod
    def read_text_file(path):
        """Reads a text file safely. Returns empty string on failure."""
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logging.error(f"Error reading file {path}: {e}")
            return ""

    @staticmethod
    def write_text_file(path, content):
        """Writes content to a text file."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
                #logging.info(f"Saved to {path}.")
        except Exception as e:
            logging.error(f"Error writing file {path}: {e}")

    @staticmethod
    def load_json_data(path):
        """Loads a JSON file and returns the dictionary. Returns None on error."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading JSON {path}: {e}")
            return None

    @staticmethod
    def save_json_data(path: str | Path, data: object) -> None:
        """Saves JSON data atomically to reduce save-file corruption risk."""
        target_path = Path(path)

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = target_path.with_suffix(target_path.suffix + ".tmp")

            with temp_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
                file.flush()
                os.fsync(file.fileno())

            temp_path.replace(target_path)

        except Exception as error:
            logging.exception("Error saving JSON %s: %s", target_path, error)

            try:
                failure_path = target_path.parent / "LAST_SAVE_FAILED.txt"
                failure_path.write_text(
                    f"Failed to save {target_path}: {error}",
                    encoding="utf-8",
                )
            except Exception:
                logging.exception("Failed to write LAST_SAVE_FAILED.txt")