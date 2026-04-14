# qt_ui/story_panel.py
from __future__ import annotations
from config import TTS_MODELS_DIR
import re, wave, threading, os, sys, tempfile, pygame, uuid, logging, platform
from piper.voice import PiperVoice
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QFrame,
    QProgressBar
)

class StoryPanel(QWidget):
    send_requested = Signal(str)
    volume_changed = Signal(float)
    start_typing_signal = Signal(str)
    
    AVAILABLE_VOICES = {
        "American Female": os.path.join(TTS_MODELS_DIR,"en_US-hfc_female-medium.onnx")
    }
    # Menu signals removed as MainWindow handles them via its MenuBar natively

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._status_cache = {
            "turn": "1",
            "location": "Unknown",
            "day": "Day 1",
            "time": "Morning",
            "dynamic_stats": []
        }
        
        try:
        
            self.narrator_enabled = False
            self.music_volume = 100
            self.tts_volume = 100
            self.tts_rate = 0
            self.tts_voice = list(self.AVAILABLE_VOICES.values())[0]
            self._piper_voice_cache = None
            self._cached_voice_path = None
            self.temp_dir = tempfile.gettempdir()
            self.typing_timer = QTimer(self)
            self.typing_timer.timeout.connect(self._type_next_word)
            self.typing_buffer = [] 
            self.start_typing_signal.connect(self._start_typing_effect)
            self._unlock_queued = False

            root = QVBoxLayout(self)
            root.setContentsMargins(10, 10, 10, 10)
            root.setSpacing(8)

            # ---- Header (Status + Progress Bars on newlines) ----
            self.header_layout = QVBoxLayout()
            self.header_layout.setSpacing(4)

            # Base Status text (Turn, Location, Time)
            self.lbl_base_status = QLabel()
            self.lbl_base_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            # Style it to stand out slightly from the progress bars below it
            self.lbl_base_status.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
            self.header_layout.addWidget(self.lbl_base_status)

            # Container for the dynamically generated progress bars
            self.stats_layout = QVBoxLayout()
            self.stats_layout.setSpacing(2)
            self.header_layout.addLayout(self.stats_layout)

            root.addLayout(self.header_layout)

            # Separator line
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            root.addWidget(line)
        except Exception as e:
            logging.error(f"Error while creating Story Panel variables: {e}")

        # ---- Output log ----
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.txt_log.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, 'Courier New', monospace;
                font-size: 14px; /* Adjust size to your preference */
            }
        """)
        root.addWidget(self.txt_log, stretch=1)

        # ---- Input row ----
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("What do you do next?")
        self.txt_input.returnPressed.connect(self._emit_send)
        input_row.addWidget(self.txt_input, stretch=1)
        
        self.btn_skip = QPushButton("Skip/Stop")
        self.btn_skip.setFixedWidth(100)
        self.btn_skip.clicked.connect(self.stop_tts)
        self.btn_skip.setVisible(False)
        input_row.addWidget(self.btn_skip)

        self.btn_send = QPushButton("Send")
        self.btn_send.setFixedWidth(100)
        self.btn_send.clicked.connect(self._emit_send)
        input_row.addWidget(self.btn_send)
        
        try:
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 0) 
            self.progress_bar.setTextVisible(False) # Hides the '0%' text
            self.progress_bar.setFixedHeight(4)     # Makes it a thin, modern-looking bar
            self.progress_bar.hide()                # Hidden by default until the AI starts thinking

            # IMPORTANT: You must add self.progress_bar to your layout here!
            # Example: self.main_layout.addWidget(self.progress_bar) 
            # (I recommend putting it right above or below your text input field)
        except Exception as e:
            logging.error(f"Failed to initialize progress bar in StoryPanel: {e}")
            
        input_row.addWidget(self.progress_bar)

        root.addLayout(input_row)

        # Initial UI render
        self._update_status_ui()
        
    def _emit_volume(self, val: int) -> None:
        # Pygame uses 0.0 to 1.0 for volume, so we divide the 0-100 slider value by 100
        self.volume_changed.emit(val / 100.0)

    def append_text(self, text: str) -> None:
        #if not text:
        #    return
        self.txt_log.append(text)
        self._scroll_to_bottom()

    def set_status(self, *, turn=None, location=None, day=None, time=None, dynamic_stats=None):
        if turn is not None: self._status_cache["turn"] = str(turn)
        if location is not None: self._status_cache["location"] = str(location)
        if day is not None: self._status_cache["day"] = str(day)
        if time is not None: self._status_cache["time"] = str(time)
        if dynamic_stats is not None: self._status_cache["dynamic_stats"] = dynamic_stats 
        
        self._update_status_ui()

    def _update_status_ui(self) -> None:
        """Rebuilds the status text and dynamically creates progress bars for stats."""
        try:
            s = self._status_cache
            if not "Day" in s['day']: s['day'] = "Day: " + s['day']
            
            # 1. Update the top standard text
            base_str = f"Turn: {s['turn']} \nLocation: {s['location']} \n{s['day']} \n{s['time']}"
            self.lbl_base_status.setText(base_str)
            
            # 2. Safely clear old progress bars
            while self.stats_layout.count() > 0:
                item = self.stats_layout.takeAt(0)
                if item is not None:
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
                    
            # 3. Create new progress bars for each enabled stat
            for st in s.get("dynamic_stats", []):
                if st.get("enabled", True):
                    pb = QProgressBar()
                    pb.setRange(0, 100) # Assumes stats are max 100 as per your previous design
                    
                    # Safely parse the value
                    try:
                        val = int(st['value'])
                    except ValueError:
                        val = 0
                        
                    pb.setValue(val)
                    # Formats text as: "Stat Name: 75%" 
                    pb.setFormat(f"{st['name']}: %p%") 
                    pb.setTextVisible(True)
                    pb.setFixedHeight(18) # Keeps the bars sleek
                    
                    if val > 50:
                        bar_color = "#4CAF50" # Green
                    elif val > 25:
                        bar_color = "#FF9800" # Orange/Yellow
                    else:
                        bar_color = "#F44336" # Red
                        
                    # Apply a custom stylesheet to this specific progress bar
                    pb.setStyleSheet(f"""
                        QProgressBar {{
                            border: 1px solid #555;
                            border-radius: 4px;
                            text-align: center;
                            background-color: #333; /* Dark background for the empty track */
                            color: white; /* Text color */
                            font-weight: bold;
                        }}
                        QProgressBar::chunk {{
                            background-color: {bar_color};
                            border-radius: 3px;
                        }}
                    """)
                    
                    self.stats_layout.addWidget(pb)
        except Exception as e:
            logging.error(f"Error while updating status UI: {e}")

    def get_log_text(self) -> str:
        return self.txt_log.toPlainText()

    def set_log_text(self, text: str) -> None:
        self.txt_log.setPlainText(text or "")
        self._scroll_to_bottom()
        
    def set_controls_state(self, enabled: bool, status_text: str = "GM is thinking...") -> None:
        """Enable/disable input controls. Optionally updates placeholder text."""
        if enabled and self.typing_timer.isActive():
            self._unlock_queued = True
            return
        self._unlock_queued = False
        self.txt_input.setEnabled(enabled)
        self.btn_send.setEnabled(enabled)
        
        try:
            if not enabled:
                self.txt_input.setPlaceholderText(status_text)
                    
                # Show the animated loading bar
                if hasattr(self, 'progress_bar'):
                    self.progress_bar.show()
            else:
                default_prompt = "What do you do now?"
                self.txt_input.setPlaceholderText(status_text if status_text else default_prompt)
                self.txt_input.setFocus()
                    
                # Hide the loading bar
                if hasattr(self, 'progress_bar'):
                    self.progress_bar.hide()
        except Exception as e:
            logging.error(f"Error updating controls state and progress bar: {e}")
        
        if enabled:
            self.txt_input.setPlaceholderText("What do you do next?")
            self.txt_input.setFocus()
        else:
            if status_text is not None:
                self.txt_input.setPlaceholderText(status_text)

    def print_text(self, text: str, *, sender: str = "GM") -> None:
        """Prints text to the story window, processing TTS and typing effects if enabled."""
        if not text.strip(): 
            return
        
        try:
            # Flush any ongoing typing so it doesn't overlap with a new incoming message
            self._flush_typing_buffer()
            
            if self.narrator_enabled and not text.startswith("> "):
                # Strip markdown formatting for the audio so it doesn't narrate "asterisk"
                clean_text = re.sub(r'[*_~`#]', '', text, re.DOTALL)
                
                # Pass BOTH clean_text (for audio) and original text (for UI display)
                self._generate_and_play_tts(clean_text, original_text=text)
            else:
                self.append_text(f"{text}")
        except Exception as e:
            logging.error(f"Error while flushing typing buffer: {e}")

    def _emit_send(self) -> None:
        try:
            text = (self.txt_input.text() or "").strip()
            if not text:
                return
            if self.narrator_enabled:
                self.stop_tts()
            self.txt_input.clear()
            self.send_requested.emit(text)
        except Exception as e:
            logging.error(f"Error while emitting send: {e}")
        
    def _generate_and_play_tts(self, text: str, original_text: str | None = None) -> None:
        """
        Generates TTS audio using a local Piper ONNX model and plays it asynchronously.
        
        Args:
            text (str): The clean plaintext to be read aloud.
            original_text (str | None): The original text with markdown formatting (used for UI typing).
        """
        def run_tts():
                
            try:
                # Piper TTS generates WAV files natively
                unique_filename = f"ai_adventure_tts_{uuid.uuid4().hex}.wav"
                dynamic_tts_file = os.path.join(self.temp_dir, unique_filename)# Cache the model so we don't reload the large .onnx file on every single message
                if self._piper_voice_cache is None or self._cached_voice_path != self.tts_voice:
                    logging.info(f"Loading Piper TTS model: {self.tts_voice}")
                    if not os.path.exists(self.tts_voice):
                        raise FileNotFoundError(f"Piper model not found at path: {self.tts_voice}")
                    
                    self._piper_voice_cache = PiperVoice.load(self.tts_voice)
                    self._cached_voice_path = self.tts_voice

                # Piper controls speed via length_scale: 1.0 is normal, < 1.0 is faster, > 1.0 is slower.
                # Assuming your UI slider is -10 (slow) to +10 (fast).
                length_scale = 1.0 - (self.tts_rate * 0.02)
                
                # Clamp the scale to prevent the audio from becoming completely distorted/crashing
                length_scale = max(0.6, min(1.5, length_scale)) 
                
                # Update the speed multiplier on the voice's internal config directly
                if hasattr(self._piper_voice_cache, 'config'):
                    self._piper_voice_cache.config.length_scale = length_scale
                
                # Synthesize the audio and save to the dynamic temporary file (Removed the kwarg!)
                with wave.open(dynamic_tts_file, "wb") as wav_file:
                    self._piper_voice_cache.synthesize_wav(text, wav_file)
                
                self._play_generated_tts(dynamic_tts_file)
                
                # Fire the visual typing signal EXACTLY when audio starts playing
                if original_text is not None:
                    self.start_typing_signal.emit(original_text)
                    
            except Exception as e:
                logging.error(f"Piper TTS Error: {e}")
                # Fallback: Just print the text normally if generation fails
                if original_text is not None:
                    self.start_typing_signal.emit(original_text)

        # Start the generation in a background thread so the UI doesn't freeze
        threading.Thread(target=run_tts, daemon=True).start()
        
    def _start_typing_effect(self, text: str) -> None:
        """Prepares the buffer and calculates the WPM delay for typing."""
        if self.txt_log.toPlainText():
            self.txt_log.append("")
            
        self.typing_buffer = re.split(r'(\s+)', text)
        self.typing_buffer = [w for w in self.typing_buffer if w]
        
        # Base WPM changed slightly from Edge-TTS to reflect average local TTS pacing
        base_wpm = 160
        multiplier = 1.0 + (self.tts_rate * 0.05)
        if multiplier < 0.1: multiplier = 0.1 
        
        current_wpm = base_wpm * multiplier
        delay_ms = int(60000 / current_wpm)
        
        self.btn_send.setVisible(False)
        self.btn_skip.setVisible(True)
        self.typing_timer.start(delay_ms)
        
    def _type_next_word(self) -> None:
        """Pops the next word from the buffer and inserts it into the text edit inline."""
        if not self.typing_buffer:
            self.typing_timer.stop()
            self._scroll_to_bottom()
            self.btn_skip.setVisible(False)
            self.btn_send.setVisible(True)
            if self._unlock_queued:
                self.set_controls_state(True)
            #else:
                #self.set_controls_state(False)
            return
            
        # Grab the next word token
        word = self.typing_buffer.pop(0)
        
        # Use a cursor to insert inline text without appending new blocks/paragraphs
        cursor = self.txt_log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.txt_log.setTextCursor(cursor)
        self.txt_log.insertPlainText(word)
        
        # If the token was a whitespace/newline, instantly grab and insert the next *actual* word.
        # This guarantees the WPM delay calculates time between actual words, not spaces.
        while self.typing_buffer and self.typing_buffer[0].isspace():
            space = self.typing_buffer.pop(0)
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.txt_log.setTextCursor(cursor)
            self.txt_log.insertPlainText(space)
            
        self._scroll_to_bottom()

    def _flush_typing_buffer(self) -> None:
        """Instantly prints the remainder of the typing buffer if interrupted or stopped."""
        if self.typing_timer.isActive():
            self.typing_timer.stop()
            if self.typing_buffer:
                rest_of_text = "".join(self.typing_buffer)
                cursor = self.txt_log.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self.txt_log.setTextCursor(cursor)
                self.txt_log.insertPlainText(rest_of_text)
                self.typing_buffer.clear()
                self._scroll_to_bottom()

    def _play_generated_tts(self, filepath: str):
        """Loads the generated file into Pygame and plays it on our reserved channel."""
        try:
            if pygame.mixer.get_init():
                channel = pygame.mixer.Channel(1)
                sound = pygame.mixer.Sound(filepath)
                channel.set_volume(self.tts_volume / 100.0)
                channel.play(sound)
        except Exception as e:
            print(f"Audio playback error: {e}")

    def stop_tts(self):
        self._flush_typing_buffer()
        try:
            if pygame.mixer.get_init():
                pygame.mixer.Channel(1).stop()
        except Exception as e:
            logging.error(f"Error stopping TTS: {e}")
            
        self.btn_skip.setVisible(False)
        self.btn_send.setVisible(True)
        
        # Execute queued unlock if AI generation finished while speaking
        if self._unlock_queued:
            self.set_controls_state(True)
        #else:
            #self.set_controls_state(False)

    def play_voice_sample(self) -> None:
        self.stop_tts()
        original_state = self.narrator_enabled
        self.narrator_enabled = True
        # Do not pass a second argument. This suppresses the visual printing for voice samples
        self._generate_and_play_tts("This is a sample of my voice. How do I sound?")
        self.narrator_enabled = original_state
        
    def set_voice_by_name(self, voice_id: str) -> None:
        """
        Updates the selected voice. 
        Note: The actual Piper model is lazily loaded on the next generation request.
        """
        self.tts_voice = voice_id

    def set_music_volume(self, val: int) -> None:
        self.music_volume = val
        self.volume_changed.emit(val / 100.0)

    def set_tts_volume(self, val: int) -> None:
        self.tts_volume = val
        # Dynamically update the Pygame channel volume if it's currently speaking
        try:
            if pygame.mixer.get_init():
                pygame.mixer.Channel(1).set_volume(val / 100.0)
        except: pass

    def set_narrator_enabled(self, enabled: bool) -> None:
        self.narrator_enabled = enabled
        if not enabled:
            self.stop_tts()
    
    def set_tts_rate(self, val: int) -> None:
        self.tts_rate = val

    def _scroll_to_bottom(self) -> None:
        cursor = self.txt_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.txt_log.setTextCursor(cursor)