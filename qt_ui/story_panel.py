# qt_ui/story_panel.py
from __future__ import annotations
import re, edge_tts, asyncio, threading, os, tempfile, pygame, uuid, logging, markdown
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QTextCursor, QTextBlockFormat, QTextCharFormat
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
    text_ready_signal = Signal(str)
    
    AVAILABLE_VOICES = {
        "Aria (Female, US)": "en-US-AriaNeural",
        "Guy (Male, US)": "en-US-GuyNeural",
        "Jenny (Female, US)": "en-US-JennyNeural",
        "Christopher (Male, US)": "en-US-ChristopherNeural",
        "Sonia (Female, UK)": "en-GB-SoniaNeural",
        "Ryan (Male, UK)": "en-GB-RyanNeural",
        "Natasha (Female, AU)": "en-AU-NatashaNeural",
        "William (Male, AU)": "en-AU-WilliamNeural"
    }
    # Menu signals removed as MainWindow handles them via its MenuBar natively

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._status_cache = {
            "turn": "1",
            "location": "Unknown",
            "day": "Day 1",
            "time": "Morning",
            "weather": "Sunny",     
            "temperature": "76",   
            "dynamic_stats": []
        }
        
        self.narrator_enabled = False
        self.music_volume = 100
        self.tts_volume = 100
        self.tts_rate = 0
        self.tts_voice = "en-US-AriaNeural"
        self.temp_dir = tempfile.gettempdir()
        self._unlock_queued = False
        self.text_ready_signal.connect(self.append_text)
        
        self._tts_check_timer = QTimer(self)
        self._tts_check_timer.setInterval(250) # Poll every 250ms
        self._tts_check_timer.timeout.connect(self._check_tts_finished)
        self._tts_check_timer.start()

        self.header_layout = QHBoxLayout() # <--- Changed to Horizontal Layout
        self.header_layout.setSpacing(20)

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
        
        # Stats Container (Right side)
        self.stats_layout = QVBoxLayout()
        self.stats_layout.setSpacing(2)
        # Adding stretch=1 pushes the status text to the left and gives the bars room to breathe
        self.header_layout.addLayout(self.stats_layout, stretch=1)

        root.addLayout(self.header_layout)

        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

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

        self.btn_send = QPushButton("Send")
        self.btn_send.setFixedWidth(100)
        self.btn_send.clicked.connect(self._emit_send)
        input_row.addWidget(self.btn_send)

        root.addLayout(input_row)

        # Initial UI render
        self._update_status_ui()
        
    def _emit_volume(self, val: int) -> None:
        # Pygame uses 0.0 to 1.0 for volume, so we divide the 0-100 slider value by 100
        self.volume_changed.emit(val / 100.0)
        
    def _check_tts_finished(self) -> None:
        """
        Periodically checks if the TTS audio has finished playing.
        If the audio is done and an unlock is queued, it releases the UI.
        """
        if self._unlock_queued:
            try:
                # If Pygame is initialized and Channel 1 is no longer playing audio...
                if pygame.mixer.get_init() and not pygame.mixer.Channel(1).get_busy():
                    self._unlock_queued = False
                    self.set_controls_state(True, force_unlock=True)
            except Exception as e:
                logging.error(f"Error checking TTS channel status: {e}")
                # Failsafe: Unlock the UI anyway so the player isn't soft-locked
                self._unlock_queued = False
                self.set_controls_state(True, force_unlock=True)

    def append_text(self, markdown_string: str) -> None:
        """
        Converts a Markdown string to HTML and appends it to the log as Rich Text.
        Safely resets block formatting to prevent lists from bleeding into the next message.
        """
        markdown_string = markdown_string.strip()
        if not markdown_string:
            return
            
        try:
            # Convert the raw markdown string into an HTML formatted string
            rendered_html = markdown.markdown(markdown_string)
            
            cursor = self.txt_log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)

            # --- MODIFIED: If the text log isn't empty, insert a clean block break to escape any active lists ---
            if not self.txt_log.document().isEmpty():
                cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
                # Add a visual spacer between turns
                cursor.insertHtml("<br>")
                
            # Insert the generated HTML natively via the cursor
            cursor.insertHtml(rendered_html)
            self.txt_log.setTextCursor(cursor)
            
        except Exception as error:
            logging.error(f"Failed to append Markdown/HTML text: {error}")
            # Fallback to plain text if HTML parsing fails
            self.txt_log.append(markdown_string)
            
        self._scroll_to_bottom()

    def set_status(self, *, turn=None, location=None, day=None, time=None, weather=None, temperature=None, dynamic_stats=None):
        if turn is not None: self._status_cache["turn"] = str(turn)
        if location is not None: self._status_cache["location"] = str(location)
        if day is not None: self._status_cache["day"] = str(day)
        if time is not None: self._status_cache["time"] = str(time)
        if weather is not None: self._status_cache["weather"] = str(weather)
        if temperature is not None: self._status_cache["temperature"] = str(temperature)
        if dynamic_stats is not None: self._status_cache["dynamic_stats"] = dynamic_stats 
        
        self._update_status_ui()

    def _update_status_ui(self) -> None:
        """Rebuilds the status text and dynamically creates progress bars for stats."""
        s = self._status_cache
        
        base_str = (
            f"Turn: {s['turn']} \n"
            f"Location: {s['location']} \n"
            f"Date: {s['day']} \n"
            f"Time: {s['time']} \n"
            f"Weather: {s['weather']} ({s['temperature']}°F)"
        )
        self.lbl_base_status.setText(base_str)
        self.lbl_base_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        # 1. Clear out the old progress bars from the layout so they don't stack infinitely
        while self.stats_layout.count():
            child = self.stats_layout.takeAt(0)
            widget_to_delete = child.widget() # type: ignore
            if widget_to_delete is not None:
                widget_to_delete.deleteLater()
                
        # 2. Iterate through the tracked stats and generate a bar for each
        stats = s.get("dynamic_stats", [])
        for stat in stats:
            if not stat.get("enabled", True):
                continue
                
            # Create a horizontal row for the Label + Bar
            stat_row_layout = QHBoxLayout()
            stat_row_layout.setContentsMargins(0, 0, 0, 0)
            
            # Stat Name Label
            name_label = QLabel(f"{stat.get('name', 'Stat')}:")
            name_label.setFixedWidth(80) # Lock the width so the progress bars perfectly align
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            
            # The actual Progress Bar
            progress_bar = QProgressBar()
            progress_bar.setMinimum(int(stat.get("min", 0)))
            progress_bar.setMaximum(int(stat.get("max", 100)))
            progress_bar.setValue(int(stat.get("value", 0)))
            progress_bar.setTextVisible(True)
            progress_bar.setFormat("%v / %m") # Displays as "Current / Max" (e.g., 50 / 100)
            
            # Apply some clean styling to make it look RPG-like
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #555;
                    border-radius: 3px;
                    text-align: center;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #4CAF50;
                }
            """)
            
            stat_row_layout.addWidget(name_label)
            stat_row_layout.addWidget(progress_bar)
            
            # Wrap the layout in a QWidget so it can be easily targeted and deleted in the next refresh
            stat_wrapper = QWidget()
            stat_wrapper.setLayout(stat_row_layout)
            self.stats_layout.addWidget(stat_wrapper)

    def get_log_text(self) -> str:
        return self.txt_log.toPlainText()

    def set_log_text(self, text: str) -> None:
        self.txt_log.setPlainText(text or "")
        self._scroll_to_bottom()
        
    def set_controls_state(self, is_enabled: bool, status_text: str | None = None, force_unlock: bool = False) -> None:
        """
        Enables or disables the player's text input controls.
        
        If the TTS narrator is currently speaking, enabling the controls is queued 
        until the audio finishes playing (unless force_unlock is True).
        """
        # 1. Queue the unlock if we are trying to enable, but the TTS is currently speaking
        if is_enabled and not force_unlock:
            try:
                # Check if the pygame mixer is initialized and the TTS channel (1) is busy playing audio
                if pygame.mixer.get_init() and pygame.mixer.Channel(1).get_busy():
                    self._unlock_queued = True
                    return
            except Exception as error:
                logging.error(f"Error checking TTS channel status: {error}")

        # 2. Proceed with actually locking/unlocking the UI elements
        self._unlock_queued = False
        self.txt_input.setEnabled(is_enabled)
        self.btn_send.setEnabled(is_enabled)

        if is_enabled:
            self.txt_input.setPlaceholderText("What do you do next?")
            self.txt_input.setFocus()
        else:
            if status_text is not None:
                self.txt_input.setPlaceholderText(status_text)
                
    def _apply_phonetic_fixes(self, text: str) -> str:
        """
        Applies Regex-based phonetic replacements to fix common TTS mispronunciations.
        By matching phrases rather than single words, we can deduce the context of heteronyms
        (e.g., 'tear into' vs 'shed a tear').
        """
        # Dictionary mapping regex patterns to phonetic spellings.
        # The \b ensures we only match whole words, not partial matches.
        replacements = {
            r"\btear into\b": "tare into",
            r"\btear off\b": "tare off",
            r"\btears off\b": "tares off",
            r"\btearing\b": "tare-ing",  # Watch out: this will catch crying tearing too!
            r"\bbow and arrow\b": "boe and arrow",
            r"\btake a bow\b": "take a bough",
            r"\bwind blows\b": "winned blows",
            r"\bwind up\b": "wined up",
            r"\blead pipe\b": "led pipe",
            r"\blead the way\b": "leed the way"
        }
        
        fixed_text = text
        try:
            for pattern, replacement in replacements.items():
                # re.IGNORECASE ensures "Tear into" and "tear into" are both caught
                fixed_text = re.sub(pattern, replacement, fixed_text, flags=re.IGNORECASE)
        except Exception as e:
            logging.error(f"Error applying phonetic fixes to TTS: {e}")
            
        return fixed_text

    def print_text(self, text: str, *, sender: str = "GM") -> None:
        """Prints text to the story window, processing TTS and typing effects if enabled."""
        # Strip trailing/leading whitespace and ignore hardcoded AI spacing
        text = text.strip()
        if not text: 
            return
        
        if self.narrator_enabled and not text.startswith("> "):
            # Strip out the entire <pre>...</pre> HTML blocks ---
            # ASCII grids sound terrible when read aloud by TTS. This regex completely removes 
            # the HTML block and its contents from the audio queue so the TTS skips over it.
            clean_text = re.sub(r'<pre.*?>.*?</pre>', '', text, flags=re.DOTALL)
            # Strip markdown formatting for the audio so it doesn't narrate "asterisk"
            clean_text = re.sub(r'[*_~`#]', '', clean_text, re.DOTALL)
            
            # Prevent Edge-TTS from stuttering/pausing on dashes ---
            # We replace double hyphens with a comma for a natural breath, 
            # and strip out any extra hyphens that might confuse the engine.
            clean_text = clean_text.replace('--', ', ').replace('-', ' ')
            
            # Prevent TTS stuttering on hard line breaks ---
            # Replace all newline characters with a space so the engine 
            # treats it as one continuous flowing sentence, ignoring text wrapping.
            clean_text = clean_text.replace('\n', ' ').replace('\r', '')
            
            # Apply our contextual phonetic dictionary ---
            clean_text = self._apply_phonetic_fixes(clean_text)
            
            # Pass BOTH clean_text (for audio) and original text (for UI display)
            self._generate_and_play_tts(clean_text, original_text=text)
        else:
            if text.startswith("> "):
                text = "\\" + text
                
            self.append_text("\n" + text)

    def _emit_send(self) -> None:
        text = (self.txt_input.text() or "").strip()
        if not text:
            return
        if self.narrator_enabled:
            self.stop_tts()
        self.txt_input.clear()
        self.send_requested.emit(text)
        
    def _generate_and_play_tts(self, text: str, original_text: str | None = None) -> None:
        """Generates the audio file asynchronously so the UI doesn't freeze."""
        def run_async():
            # Convert UI slider (-10 to 10) to Edge-TTS percentage format (-50% to +50%)
            unique_filename = f"ai_adventure_tts_{uuid.uuid4().hex}.mp3"
            dynamic_tts_file = os.path.join(self.temp_dir, unique_filename)
            rate_str = f"{self.tts_rate * 5}%"
            if self.tts_rate >= 0: 
                rate_str = f"+{rate_str}"
                
            try:
                communicate = edge_tts.Communicate(text, self.tts_voice, rate=rate_str)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # Save to the unique file instead of the static one
                loop.run_until_complete(communicate.save(dynamic_tts_file))
                loop.close()
                
                self._play_generated_tts(dynamic_tts_file)
                
                if original_text is not None:
                    self.text_ready_signal.emit(original_text)
                
            except Exception as e:
                print(f"Edge-TTS Error: {e}")
                if original_text is not None:
                    self.text_ready_signal.emit(original_text)

        # Start the generator in a background thread
        threading.Thread(target=run_async, daemon=True).start()

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
        """
        Stops the TTS audio playback and executes any queued UI unlocks.
        """
        try:
            if pygame.mixer.get_init():
                pygame.mixer.Channel(1).stop()
        except Exception as error:
            logging.error(f"Error stopping TTS playback: {error}")
        
        # If the text box was waiting for the narrator to finish before unlocking, do it now.
        # We pass force_unlock=True to bypass the mixer check, since we just stopped it.
        if self._unlock_queued: 
            self.set_controls_state(True, force_unlock=True)


    def play_voice_sample(self) -> None:
        self.stop_tts()
        original_state = self.narrator_enabled
        self.narrator_enabled = True
        # Do not pass a second argument. This suppresses the visual printing for voice samples
        self._generate_and_play_tts("This is a sample of my voice. How do I sound?")
        self.narrator_enabled = original_state
        
    def set_voice_by_name(self, voice_id: str) -> None:
        # We now store the edge-tts string (e.g. "en-US-AriaNeural") directly
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