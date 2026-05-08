# config.py
from __future__ import annotations
from typing import Final
import logging
import os
import platform
import sys
from functools import cached_property
from pathlib import Path
from dotenv import find_dotenv
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DOTENV_PATH: Final[str | None] = find_dotenv(usecwd=True) or None

class AppSettings(BaseSettings):
    """
    Type-safe application settings loaded from environment variables or a .env file.

    Pydantic validates these values at startup, so missing required values or
    invalid path-like values fail early instead of creating hard-to-debug runtime bugs.
    """

    model_config = SettingsConfigDict(
        env_file=DOTENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_name: str = Field(
        default="AI_RPG_ADVENTURE",
        validation_alias="AI_ADVENTURE_APP_NAME",
        min_length=1,
    )

    gemini_api_key: str = Field(
    default="",
    validation_alias="GEMINI_API_KEY",
    )

    model: str = Field(
        default="gemini-3-flash-preview",
        validation_alias="GEMINI_MODEL",
        min_length=1,
    )

    sounds_source_directory: Path | None = Field(
        default=None,
        validation_alias="AI_ADVENTURE_SOUNDS_DIR",
    )

    app_data_directory: Path | None = Field(
        default=None,
        validation_alias="AI_ADVENTURE_DATA_DIR",
    )

    @field_validator("sounds_source_directory", "app_data_directory", mode="before")
    @classmethod
    def _normalize_optional_path(cls, value: object) -> Path | None:
        """
        Converts blank optional path values to None and expands user paths.

        This lets the .env file contain:
            AI_ADVENTURE_DATA_DIR=
        without accidentally treating it as the current directory.
        """
        if value is None:
            return None

        raw_value = str(value).strip()
        if not raw_value:
            return None

        return Path(raw_value).expanduser()
    
    @field_validator("gemini_api_key")
    @classmethod
    def _validate_gemini_api_key(cls, value: str) -> str:
        """
        Ensures the Gemini API key is actually configured.

        A blank API key should fail during application startup instead of causing
        delayed Gemini client failures later.
        """
        cleaned_value = value.strip()

        if not cleaned_value:
            raise ValueError(
                "GEMINI_API_KEY is missing. Add it to your .env file or environment variables."
            )

        if cleaned_value.upper().startswith("INVALID"):
            raise ValueError(
                "GEMINI_API_KEY still contains the placeholder value."
            )

        return cleaned_value


class Configuration:
    """Centralized runtime configuration for AI Adventure.

    Handles environment loading, platform-specific directories, prompt template
    loading, and sound-file discovery.
    """

    def __init__(self) -> None:
        try:
            self.settings = AppSettings()
        except ValidationError as error:
            logging.exception("Invalid application configuration: %s", error)
            raise RuntimeError(
                "Application configuration is invalid. Check your .env file or environment variables."
            ) from error

        self._initialize_directories()

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
        
    @cached_property
    def creative_ideas(self) -> str:
        """Loads the default GM rules prompt from a Markdown template."""
        template_path = self._resource_path("prompt_templates/creative_ideas.md")

        try:
            if template_path.exists() and template_path.is_file():
                creative_ideas = template_path.read_text(encoding="utf-8").strip()
                if creative_ideas:
                    return creative_ideas

            raise FileNotFoundError(f"Creative ideas template not found or empty: {template_path}")

        except Exception as error:
            logging.exception("Failed to read creative ideas template: %s", error)
            raise RuntimeError("Creative ideas template could not be loaded.") from error

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
CREATIVE_IDEAS: Final[str] = configuration.creative_ideas
VALID_SOUND_FILE_NAMES: Final[list[str]] = configuration.get_valid_sound_file_names()