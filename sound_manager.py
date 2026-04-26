# sound_manager.py
import pygame, os, logging

class SoundManager:
    def __init__(self, sounds_dir):
        self.sounds_dir = sounds_dir
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
        
        track_path = os.path.join(self.sounds_dir, filename)
        
        # Don't restart if it's already playing
        if self.current_music == filename and pygame.mixer.music.get_busy():
            return

        if os.path.exists(track_path):
            try:
                # Fade out old track over 1 second
                pygame.mixer.music.fadeout(1000)
                pygame.mixer.music.load(track_path)
                # -1 means loop forever, 0 means play once
                loops = -1 if loop else 0
                pygame.mixer.music.play(loops=loops, fade_ms=1000)
                self.current_music = filename
            except Exception as e:
                logging.exception(f"Error playing music: {e}")
        else:
            logging.error(f"Music file not found: {track_path}")

    def play_sfx(self, filename):
        """Plays a sound effect. Multiple SFX can overlap."""
        if self.is_muted: return
        
        sfx_path = os.path.join(self.sounds_dir, filename)
        if os.path.exists(sfx_path):
            try:
                sound = pygame.mixer.Sound(sfx_path)
                sound.play()
            except Exception as e:
                logging.error(f"Error playing SFX: {e}")
        else:
            logging.error(f"SFX file not found: {sfx_path}")

    def stop_music(self):
        pygame.mixer.music.fadeout(1000)
        self.current_music = None

    def set_volume(self, volume: float):
        """0.0 to 1.0"""
        pygame.mixer.music.set_volume(volume)