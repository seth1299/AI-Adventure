# qt_ui/story_panel.py
from __future__ import annotations
import re, edge_tts, asyncio, threading, os, tempfile, pygame, uuid, logging, markdown
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

    def append_text(self, markdown_string: str) -> None:
        """
        Converts a Markdown string to HTML and appends it to the log as Rich Text.
        """
        markdown_string = markdown_string.strip()
        if not markdown_string:
            return
            
        # Insert a blank line before every new message block
        if self.txt_log.toMarkdown():
            self.txt_log.append("")
            
        try:
            # Convert the raw markdown string into an HTML formatted string
            rendered_html = markdown.markdown(markdown_string)
            
            # append() natively processes HTML strings and renders them
            self.txt_log.append(rendered_html)
        except Exception as error:
            logging.error(f"Failed to append Markdown/HTML text: {error}")
            # Fallback to plain text if HTML parsing fails
            self.txt_log.append(markdown_string)
            
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

    def get_log_text(self) -> str:
        return self.txt_log.toPlainText()

    def set_log_text(self, text: str) -> None:
        self.txt_log.setPlainText(text or "")
        self._scroll_to_bottom()
        
    def set_controls_state(self, enabled: bool, status_text: str | None = None) -> None:
        """Enable/disable input controls. Optionally updates placeholder text."""
        if enabled:
            self._unlock_queued = True
            return
        self._unlock_queued = False
        self.txt_input.setEnabled(enabled)
        self.btn_send.setEnabled(enabled)

        if enabled:
            self.txt_input.setPlaceholderText("What do you do next?")
            self.txt_input.setFocus()
        else:
            if status_text is not None:
                self.txt_input.setPlaceholderText(status_text)

    def print_text(self, text: str, *, sender: str = "GM") -> None:
        """Prints text to the story window, processing TTS and typing effects if enabled."""
        # Strip trailing/leading whitespace and ignore hardcoded AI spacing
        text = text.strip()
        if not text: 
            return
        
        if self.narrator_enabled and not text.startswith("> "):
            # Strip markdown formatting for the audio so it doesn't narrate "asterisk"
            clean_text = re.sub(r'[*_~`#]', '', text, re.DOTALL)
            
            # Pass BOTH clean_text (for audio) and original text (for UI display)
            self._generate_and_play_tts(clean_text, original_text=text)
        else:
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
        try:
            if pygame.mixer.get_init():
                pygame.mixer.Channel(1).stop()
        except Exception as e:
            logging.error(f"Error stopping TTS: {e}")
        
        # Execute queued unlock if AI generation finished while speaking
        if self._unlock_queued: self.set_controls_state(True)


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