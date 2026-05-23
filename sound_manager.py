# sound_manager.py
from __future__ import annotations

import logging
from pathlib import Path

import pygame


class SoundManager:
    """Manages music and sound effects from a configured audio directory."""

    SUPPORTED_EXTENSIONS = {".mp3", ".ogg", ".wav"}

    def __init__(self, sounds_directory: str | Path) -> None:
        self.sounds_directory = Path(sounds_directory).expanduser()
        self.current_music: str | None = None
        self.music_volume: float = 0.1
        self.sfx_volume: float = 1.0
        self._initialized = False
        self._track_cache: dict[str, Path] = {}

        self._initialize_audio()
        self.refresh_tracks()

    def _initialize_audio(self) -> None:
        """Initializes pygame audio safely."""

        try:
            pygame.mixer.init()
            self._initialized = True
        except Exception as error:
            self._initialized = False
            logging.exception("Failed to initialize pygame mixer: %s", error)
            
    def set_volume(self, volume: float | int | None) -> None:
        """
        Sets the background music volume.

        Accepts either:
        - 0.0 to 1.0, which is what pygame expects
        - 0 to 100, as a future-proof fallback for percent-based callers
        """
        self.set_music_volume(volume)

    def set_music_volume(self, volume: float | int | None) -> None:
        """
        Sets and applies the current background music volume.

        Args:
            volume: Volume as either a normalized float from 0.0 to 1.0,
                    or a percentage from 0 to 100.
        """
        if volume is None:
            logging.warning("SoundManager.set_music_volume called with None.")
            return

        try:
            parsed_volume = float(volume)

            # Future-proofing: accept either 0.75 or 75.
            if parsed_volume > 1.0:
                parsed_volume = parsed_volume / 100.0

            self.music_volume = max(0.0, min(1.0, parsed_volume))

            if not self._initialized:
                logging.warning("Stored music volume, but pygame mixer is not initialized.")
                return

            pygame.mixer.music.set_volume(self.music_volume)

        except (TypeError, ValueError) as error:
            logging.exception("Invalid music volume value %r: %s", volume, error)

    def set_sfx_volume(self, volume: float | int | None) -> None:
        """
        Sets the volume used for newly played one-shot sound effects.

        Args:
            volume: Volume as either a normalized float from 0.0 to 1.0,
                    or a percentage from 0 to 100.
        """
        if volume is None:
            logging.warning("SoundManager.set_sfx_volume called with None.")
            return

        try:
            parsed_volume = float(volume)

            if parsed_volume > 1.0:
                parsed_volume = parsed_volume / 100.0

            self.sfx_volume = max(0.0, min(1.0, parsed_volume))
            logging.info("SFX volume set to %.2f", self.sfx_volume)

        except (TypeError, ValueError) as error:
            logging.exception("Invalid SFX volume value %r: %s", volume, error)

    def refresh_tracks(self) -> None:
        """Refreshes the known audio-file cache."""

        self._track_cache.clear()

        try:
            if not self.sounds_directory.exists():
                logging.warning("Sound directory does not exist: %s", self.sounds_directory)
                return

            if not self.sounds_directory.is_dir():
                logging.warning("Sound path is not a directory: %s", self.sounds_directory)
                return

            for file_path in self.sounds_directory.iterdir():
                if not file_path.is_file():
                    continue

                if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                    continue

                self._track_cache[file_path.name.lower()] = file_path
        except Exception as error:
            logging.exception("Failed to refresh sound files: %s", error)

    def get_valid_track_names(self) -> list[str]:
        """Returns known playable audio filenames."""

        self.refresh_tracks()
        return sorted(path.name for path in self._track_cache.values())

    def _resolve_track_path(self, track_name_or_path: str | Path | None) -> Path | None:
        """Resolves either a filename or full path to a playable audio file."""

        if not track_name_or_path:
            logging.warning("No track name/path was provided.")
            return None

        raw_path = Path(str(track_name_or_path)).expanduser()

        if raw_path.exists() and raw_path.is_file():
            return raw_path

        self.refresh_tracks()
        cached_path = self._track_cache.get(raw_path.name.lower())

        if cached_path is None:
            logging.warning("Audio track not found: %s", track_name_or_path)
            return None

        return cached_path

    def play_music(self, track_name_or_path: str | Path | None) -> None:
        """Plays background music, replacing the currently playing track."""

        if not self._initialized:
            logging.warning("Cannot play music because pygame mixer is not initialized.")
            return

        track_path = self._resolve_track_path(track_name_or_path)
        if track_path is None:
            return

        try:
            if self.current_music == track_path.name and pygame.mixer.music.get_busy():
                return

            pygame.mixer.music.stop()
            pygame.mixer.music.load(str(track_path))
            pygame.mixer.music.set_volume(self.music_volume)
            pygame.mixer.music.play(-1)
            self.current_music = track_path.name
            logging.info("Playing music: %s", track_path.name)
        except Exception as error:
            logging.exception("Failed to play music %s: %s", track_path, error)

    def play_sfx(self, sound_name_or_path: str | Path | None) -> None:
        """Plays a one-shot sound effect."""

        if not self._initialized:
            logging.warning("Cannot play SFX because pygame mixer is not initialized.")
            return

        sound_path = self._resolve_track_path(sound_name_or_path)
        if sound_path is None:
            return

        try:
            sound = pygame.mixer.Sound(str(sound_path))
            sound.set_volume(self.sfx_volume)
            sound.play()
            logging.info("Playing SFX: %s", sound_path.name)
        except Exception as error:
            logging.exception("Failed to play SFX %s: %s", sound_path, error)

    def stop_music(self) -> None:
        """Stops currently playing background music."""

        if not self._initialized:
            return

        try:
            pygame.mixer.music.stop()
            self.current_music = None
        except Exception as error:
            logging.exception("Failed to stop music: %s", error)