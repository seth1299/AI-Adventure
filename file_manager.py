import os
import sys
import json
import logging
from config import SAVES_DIR
from pathlib import Path

class FileManager:
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
        log_file_path = SAVES_DIR / "Log.log"

        try:
            # Configure the basic logging format. 
            # %#m, %#d, and %#I are Windows-specific directives to omit leading zeroes.
            logging.basicConfig(
                filename=log_file_path,
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s', 
                datefmt='%#m/%#d/%Y at %#I:%M %p',
                filemode='w'
            )

        except Exception as logging_initialization_error:
            # Fallback error handling if the primary log directory is inaccessible
            fallback_error_log_path = Path.cwd() / "Logging_Error.log"
            
            # Using basic file writing for the fallback, as the logging library failed to initialize
            with open(fallback_error_log_path, 'a') as fallback_log_file:
                fallback_log_file.write(
                    f"CRITICAL ERROR: Failed to initialize primary logging at {log_file_path}. "
                    f"Exception details: {str(logging_initialization_error)}\n"
                )
                
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
            save_name (str, optional): The name of the specific save folder. Defaults to None.
        """
        try:
            if save_name:
                save_directory = SAVES_DIR / save_name
                if not save_directory.exists():
                    return
                new_log_path = save_directory / f"{save_name} Log.txt"
            else:
                new_log_path = SAVES_DIR / "Generic Log.txt"

            logger = logging.getLogger()
            for handler in logger.handlers[:]:
                if isinstance(handler, logging.FileHandler):
                    handler.close()
                    logger.removeHandler(handler)

            file_handler = logging.FileHandler(str(new_log_path), mode='w', encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
        except Exception as logger_switch_error:
            logging.error(f"Failed to switch logger path. Exception details: {logger_switch_error}")

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
                logging.info(f"Saved to {path}.")
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
    def save_json_data(path, data):
        """Saves a dictionary to a JSON file."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving JSON {path}: {e}")
            with open("LAST_SAVE_FAILED.txt", "w") as f:
                f.write(f"Failed to save {path}: {e}")