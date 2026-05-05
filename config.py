# config.py
from __future__ import annotations
from typing import Final
import logging
import os
import platform
import sys
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class AppSettings:
    """Typed application settings loaded from environment variables."""

    app_name: str
    gemini_api_key: str
    model: str
    sounds_source_directory: Path | None = None
    app_data_directory: Path | None = None


class Configuration:
    """Centralized runtime configuration for AI Adventure.

    Handles environment loading, platform-specific directories, prompt template
    loading, and sound-file discovery.
    """

    def __init__(self) -> None:
        dotenv_path = find_dotenv(usecwd=True)
        load_dotenv(dotenv_path)

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY not found. Add it to your .env file or environment variables."
            )

        sounds_dir = self._optional_path_from_env("AI_ADVENTURE_SOUNDS_DIR")
        app_data_dir = self._optional_path_from_env("AI_ADVENTURE_DATA_DIR")

        self.settings = AppSettings(
            app_name=os.getenv("AI_ADVENTURE_APP_NAME", "AI_RPG_ADVENTURE"),
            gemini_api_key=api_key,
            model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
            sounds_source_directory=sounds_dir,
            app_data_directory=app_data_dir,
        )

        self._initialize_directories()

    @staticmethod
    def _optional_path_from_env(variable_name: str) -> Path | None:
        """Returns a Path from an environment variable, or None if unset."""

        raw_value = os.getenv(variable_name)
        if not raw_value:
            return None

        try:
            return Path(raw_value).expanduser()
        except Exception as error:
            logging.exception("Invalid path in %s: %s", variable_name, error)
            return None

    @cached_property
    def base_directory(self) -> Path:
        """Returns the root application-data directory."""

        if self.settings.app_data_directory is not None:
            return self.settings.app_data_directory

        if platform.system() == "Windows":
            app_data_path = os.getenv("APPDATA")
            if app_data_path:
                return Path(app_data_path)

        return Path.home() / ".local" / "share"

    @cached_property
    def saves_directory(self) -> Path:
        """Returns the directory where save folders are stored."""

        return self.base_directory / self.settings.app_name / "saves"

    @cached_property
    def sounds_directory(self) -> Path:
        """Returns the app-managed sounds directory."""

        return self.base_directory / self.settings.app_name / "sounds"

    @cached_property
    def base_sounds_directory(self) -> Path:
        """Returns the source directory used for available audio files."""

        if self.settings.sounds_source_directory is not None:
            return self.settings.sounds_source_directory

        bundled_sounds_directory = self._resource_path("sounds")
        if bundled_sounds_directory.exists() and bundled_sounds_directory.is_dir():
            return bundled_sounds_directory

        return self.sounds_directory

    @cached_property
    def default_rules(self) -> str:
        """Loads the default GM rules prompt from a Markdown template."""
        template_path = self._resource_path("prompt_templates/default_rules.md")

        try:
            if template_path.exists() and template_path.is_file():
                rules = template_path.read_text(encoding="utf-8").strip()
                if rules:
                    return rules

            raise FileNotFoundError(f"Default rules template not found or empty: {template_path}")

        except Exception as error:
            logging.exception("Failed to read default rules template: %s", error)
            raise RuntimeError("Default rules template could not be loaded.") from error

    def _resource_path(self, relative_path: str) -> Path:
        """Gets a resource path that works in development and PyInstaller builds."""

        base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return base_path / relative_path

    def _initialize_directories(self) -> None:
        """Creates required app directories if they do not already exist."""

        for directory in (self.saves_directory, self.sounds_directory):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except Exception as error:
                logging.exception("Failed to create directory at %s: %s", directory, error)

    def get_valid_sound_file_names(self) -> list[str]:
        """Returns valid sound file names from the configured sound source directory."""

        try:
            if not self.base_sounds_directory.exists():
                logging.warning("Sound directory does not exist: %s", self.base_sounds_directory)
                return []

            if not self.base_sounds_directory.is_dir():
                logging.warning("Sound path is not a directory: %s", self.base_sounds_directory)
                return []

            return [
                file_path.name
                for file_path in self.base_sounds_directory.iterdir()
                if file_path.is_file()
            ]
        except Exception as error:
            logging.exception("Failed to read sound files: %s", error)
            return []

_configuration: Configuration | None = None


def get_configuration() -> Configuration:
    """Returns the application configuration, initializing it once."""
    global _configuration

    if _configuration is None:
        _configuration = Configuration()

    return _configuration


# Backward-compatible singleton instance.
configuration: Final[Configuration] = get_configuration()

# Backward-compatible globals.
GEMINI_API_KEY: Final[str] = configuration.settings.gemini_api_key
MODEL: Final[str] = configuration.settings.model
APP_NAME: Final[str] = configuration.settings.app_name

SAVES_DIR: Final[Path] = configuration.saves_directory
SOUNDS_DIR: Final[Path] = configuration.sounds_directory
BASE_SOUNDS_DIR: Final[Path] = configuration.base_sounds_directory

DEFAULT_RULES: Final[str] = configuration.default_rules
VALID_SOUND_FILE_NAMES: Final[list[str]] = configuration.get_valid_sound_file_names()