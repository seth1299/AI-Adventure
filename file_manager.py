import os
import sys
import logging
from config import SAVES_DIR

class FileManager:
    @staticmethod
    def resource_path(relative_path):
        """Get absolute path to resource, works for dev and for PyInstaller"""
        base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
        return os.path.join(base_path, relative_path)

    @staticmethod
    def setup_initial_logging():
        """Sets up the basic logger on startup."""
        log_file_path = os.path.join(SAVES_DIR, "error_log.txt")
        logging.basicConfig(
            filename=log_file_path,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s', 
            datefmt='%m/%d/%Y at %I:%M:S %p',
            filemode='w'
        )

    @staticmethod
    def update_logger_path(save_name=None):
        """Switches the logging output to a specific save folder."""
        if save_name:
            save_dir = os.path.join(SAVES_DIR, save_name)
            if not os.path.exists(save_dir):
                return
            new_log_path = os.path.join(save_dir, f"{save_name}_error_log.txt")
        else:
            new_log_path = os.path.join(SAVES_DIR, "generic_text_adventure_error_log.txt")

        logger = logging.getLogger()
        # Remove existing handlers
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                handler.close()
                logger.removeHandler(handler)

        try:
            file_handler = logging.FileHandler(new_log_path, mode='w', encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logging.info(f"Logger switched to: {new_log_path}")
        except Exception as e:
            print(f"Failed to switch logger: {e}")