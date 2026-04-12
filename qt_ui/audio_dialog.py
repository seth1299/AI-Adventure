from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, 
                               QSlider, QCheckBox, QLabel, QComboBox, 
                               QPushButton, QDialogButtonBox)
from PySide6.QtCore import Qt

class AudioSettingsDialog(QDialog):
    def __init__(self, parent, story_panel):
        super().__init__(parent)
        self.setWindowTitle("Audio Settings")
        self.setMinimumWidth(350)
        self.story_panel = story_panel

        # Cache original settings in case the user hits "Cancel"
        self.orig_music_vol = story_panel.music_volume
        self.orig_tts_vol = story_panel.tts_volume
        self.orig_tts_rate = story_panel.tts_rate
        self.orig_narrator_enabled = story_panel.narrator_enabled
        self.orig_voice = story_panel.tts.voice().name() if story_panel.tts.voice() else ""

        layout = QVBoxLayout(self)

        # --- 1. Music Section ---
        music_group = QGroupBox("🎵 Music")
        music_layout = QVBoxLayout()
        
        music_row = QHBoxLayout()
        self.lbl_music_val = QLabel(f"{self.orig_music_vol}%")
        self.lbl_music_val.setFixedWidth(35)
        
        self.slider_music = QSlider(Qt.Orientation.Horizontal)
        self.slider_music.setRange(0, 100)
        self.slider_music.setValue(self.orig_music_vol)
        self.slider_music.valueChanged.connect(self._on_music_slider)
        
        music_row.addWidget(QLabel("Volume:"))
        music_row.addWidget(self.slider_music)
        music_row.addWidget(self.lbl_music_val)
        music_layout.addLayout(music_row)
        music_group.setLayout(music_layout)
        layout.addWidget(music_group)

        # --- 2. Narrator Section ---
        self.narrator_group = QGroupBox("🗣️ Narrator")
        narrator_layout = QVBoxLayout()

        self.chk_enable = QCheckBox("Enable Narrator")
        self.chk_enable.setChecked(self.orig_narrator_enabled)
        self.chk_enable.toggled.connect(self._toggle_narrator_ui)
        narrator_layout.addWidget(self.chk_enable)

        tts_row = QHBoxLayout()
        self.lbl_tts_val = QLabel(f"{self.orig_tts_vol}%")
        self.lbl_tts_val.setFixedWidth(35)
        
        self.slider_tts = QSlider(Qt.Orientation.Horizontal)
        self.slider_tts.setRange(0, 100)
        self.slider_tts.setValue(self.orig_tts_vol)
        self.slider_tts.valueChanged.connect(self._on_tts_slider)
        
        self.lbl_tts_label = QLabel("Volume:")
        tts_row.addWidget(self.lbl_tts_label)
        tts_row.addWidget(self.slider_tts)
        tts_row.addWidget(self.lbl_tts_val)
        narrator_layout.addLayout(tts_row)
        speed_row = QHBoxLayout()
        
        init_speed_str = "Normal" if self.orig_tts_rate == 0 else f"{'+' if self.orig_tts_rate > 0 else ''}{self.orig_tts_rate}"
        self.lbl_tts_speed_val = QLabel(init_speed_str)
        self.lbl_tts_speed_val.setFixedWidth(45)
        
        self.slider_tts_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_tts_speed.setRange(-10, 10)
        self.slider_tts_speed.setValue(self.orig_tts_rate)
        self.slider_tts_speed.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_tts_speed.setTickInterval(5)
        self.slider_tts_speed.valueChanged.connect(self._on_tts_speed_slider)
        
        self.lbl_tts_speed_label = QLabel("Speed:")
        speed_row.addWidget(self.lbl_tts_speed_label)
        speed_row.addWidget(self.slider_tts_speed)
        speed_row.addWidget(self.lbl_tts_speed_val)
        narrator_layout.addLayout(speed_row)

        voice_row = QHBoxLayout()
        self.combo_voices = QComboBox()
        available_voices = self.story_panel.get_available_voices()
        for voice in available_voices:
            self.combo_voices.addItem(voice.name(), voice.name())
            if voice.name() == self.orig_voice:
                self.combo_voices.setCurrentText(voice.name())
                
        self.lbl_voice_label = QLabel("Voice:")
        voice_row.addWidget(self.lbl_voice_label)
        voice_row.addWidget(self.combo_voices, stretch=1)
        narrator_layout.addLayout(voice_row)

        self.btn_test = QPushButton("Play Voice Sample")
        self.btn_test.clicked.connect(self._play_sample)
        narrator_layout.addWidget(self.btn_test)

        self.narrator_group.setLayout(narrator_layout)
        layout.addWidget(self.narrator_group)

        # --- 3. Buttons ---
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Initialize grey-out state based on checkbox
        self._toggle_narrator_ui(self.orig_narrator_enabled)

    def _on_music_slider(self, val):
        self.lbl_music_val.setText(f"{val}%")
        self.story_panel.set_music_volume(val) # Live preview!

    def _on_tts_slider(self, val):
        self.lbl_tts_val.setText(f"{val}%")
        self.story_panel.set_tts_volume(val) # Live preview!

    def _toggle_narrator_ui(self, checked):
        # Greys out all sub-options if disabled
        self.lbl_tts_label.setEnabled(checked)
        self.slider_tts.setEnabled(checked)
        self.lbl_tts_speed_label.setEnabled(checked)
        self.slider_tts_speed.setEnabled(checked)
        self.lbl_tts_speed_val.setEnabled(checked)
        self.lbl_tts_val.setEnabled(checked)
        self.lbl_voice_label.setEnabled(checked)
        self.combo_voices.setEnabled(checked)
        self.btn_test.setEnabled(checked)

    def _play_sample(self):
        # Temporarily lock the voice in and test it
        voice_name = self.combo_voices.currentText()
        self.story_panel.set_voice_by_name(voice_name)
        
        orig = self.story_panel.narrator_enabled
        self.story_panel.narrator_enabled = True
        self.story_panel.play_voice_sample()
        self.story_panel.narrator_enabled = orig

    def reject(self):
        # Revert live-previews if Cancel is clicked
        self.story_panel.set_music_volume(self.orig_music_vol)
        self.story_panel.set_tts_volume(self.orig_tts_vol)
        self.story_panel.set_voice_by_name(self.orig_voice)
        self.story_panel.set_tts_rate(self.orig_tts_rate) 
        super().reject()

    def accept(self):
        # Finalize
        self.story_panel.set_narrator_enabled(self.chk_enable.isChecked())
        self.story_panel.set_voice_by_name(self.combo_voices.currentText())
        super().accept()
        
    def _on_tts_speed_slider(self, val):
        if val == 0: display_str = "Normal"
        elif val > 0: display_str = f"+{val}"
        else: display_str = f"{val}"
        
        self.lbl_tts_speed_val.setText(display_str)
        self.story_panel.set_tts_rate(val) # Live preview!