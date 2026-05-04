# sound_manager.py
import pygame, os, logging
from pathlib import Path

class SoundManager:
    def __init__(self, sounds_directory: str | Path):
        self.sounds_directory = Path(sounds_directory)
        self.current_music = None
        self.is_muted = False
        
        # Initialize Pygame Mixer (Frequency, Size, Channels, Buffer)
        try:
            pygame.mixer.init(44100, -16, 2, 2048)
            # --- Reserve Channel 1 explicitly for the Narrator ---
            pygame.mixer.set_reserved(1) 
            logging.info("Sound System Initialized.")
        except Exception as e:
            logging.error(f"Error initializing sound: {e}")

    def play_music(self, filename, loop=True):
        """Streams music. Only one music track plays at a time."""
        if self.is_muted: return
        
        track_path = self.sounds_directory / filename
        
        # Don't restart if it's already playing
        if self.current_music == filename and pygame.mixer.music.get_busy():
            return

        # Check existence using the Path object method
        if track_path.exists() and track_path.is_file():
            try:
                pygame.mixer.music.fadeout(1000)
                # Pygame generally accepts strings, so we cast the Path object back to a string here
                pygame.mixer.music.load(str(track_path))
                loops = -1 if loop else 0
                pygame.mixer.music.play(loops=loops, fade_ms=1000)
                self.current_music = filename
            except Exception as music_playback_error:
                logging.exception(f"Error playing music: {music_playback_error}")
        else:
            logging.error(f"Music file not found: {track_path}")

    def play_sfx(self, filename: str) -> None:
        """Plays a sound effect. Multiple SFX can overlap."""
        if self.is_muted: return
        
        # Resolve the path using the pathlib division operator
        sfx_path = self.sounds_directory / filename
        
        if sfx_path.exists() and sfx_path.is_file():
            try:
                # Pygame Sound prefers strings for file paths
                sound = pygame.mixer.Sound(str(sfx_path))
                sound.play()
            except Exception as sfx_playback_error:
                logging.error(f"Error playing SFX: {sfx_playback_error}")
        else:
            logging.error(f"SFX file not found: {sfx_path}")

    def stop_music(self):
        pygame.mixer.music.fadeout(1000)
        self.current_music = None

    def set_volume(self, volume: float):
        """0.0 to 1.0"""
        pygame.mixer.music.set_volume(volume)