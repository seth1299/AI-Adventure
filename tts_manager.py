# tts_manager.py
from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, ClassVar


@dataclass(frozen=True)
class TTSRequest:
    """
    Represents a single text-to-speech request.

    Args:
        text: Text to synthesize.
        voice: Engine-specific voice identifier.
        speed: Speech speed multiplier. 1.0 is normal speed.
        language: Engine-specific language code.
    """

    text: str
    voice: str
    speed: float = 1.0
    language: str = "en-us"


class TTSEngine(ABC):
    """Abstract base class for TTS engines."""

    DEFAULT_VOICE: ClassVar[str] = ""

    def get_available_voices(self) -> dict[str, str]:
        """
        Returns display-name-to-engine-voice mappings.

        Returns:
            Dictionary where keys are UI labels and values are engine voice IDs.
        """

        return {}

    def get_default_voice(self) -> str:
        """
        Returns the engine's default voice identifier.

        Returns:
            Default voice ID.
        """

        return self.DEFAULT_VOICE

    @abstractmethod
    def synthesize_to_file(self, request: TTSRequest) -> Path:
        ...


class KokoroOnnxTTSEngine(TTSEngine):
    """Local Kokoro-ONNX TTS engine."""

    DEFAULT_VOICE: Final[str] = "af_sarah"
    
    AVAILABLE_VOICES: ClassVar[dict[str, str]] = {
        "Heart (Female, US)": "af_heart",
        "Alloy (Female, US)": "af_alloy",
        "Aoede (Female, US)": "af_aoede",
        "Bella (Female, US)": "af_bella",
        "Jessica (Female, US)": "af_jessica",
        "Kore (Female, US)": "af_kore",
        "Nicole (Female, US)": "af_nicole",
        "Nova (Female, US)": "af_nova",
        "River (Female, US)": "af_river",
        "Sarah (Female, US)": "af_sarah",
        "Sky (Female, US)": "af_sky",
        "Adam (Male, US)": "am_adam",
        "Echo (Male, US)": "am_echo",
        "Eric (Male, US)": "am_eric",
        "Fenrir (Male, US)": "am_fenrir",
        "Liam (Male, US)": "am_liam",
        "Michael (Male, US)": "am_michael",
        "Onyx (Male, US)": "am_onyx",
        "Puck (Male, US)": "am_puck",
        "Santa (Male, US)": "am_santa",
        "Alice (Female, UK)": "bf_alice",
        "Emma (Female, UK)": "bf_emma",
        "Isabella (Female, UK)": "bf_isabella",
        "Lily (Female, UK)": "bf_lily",
        "Daniel (Male, UK)": "bm_daniel",
        "Fable (Male, UK)": "bm_fable",
        "George (Male, UK)": "bm_george",
        "Lewis (Male, UK)": "bm_lewis",
    }

    LANGUAGE_BY_VOICE_PREFIX: ClassVar[dict[str, str]] = {
        "a": "en-us",
        "b": "en-gb",
        "e": "es",
        "f": "fr-fr",
        "h": "hi",
        "i": "it",
        "p": "pt-br",
        "z": "zh",
    }

    def get_available_voices(self) -> dict[str, str]:
        """
        Returns Kokoro voice choices for the Audio Settings dialog.

        Returns:
            Display-name-to-voice-ID mapping.
        """

        return dict(self.AVAILABLE_VOICES)

    def _resolve_voice_id(self, voice_id: str | None) -> str:
        """
        Resolves a possibly blank voice ID to a safe Kokoro voice.

        Args:
            voice_id: Requested Kokoro voice ID.

        Returns:
            Kokoro voice ID.
        """

        clean_voice = str(voice_id or "").strip()
        return clean_voice or self.DEFAULT_VOICE

    def _resolve_language_for_voice(self, voice_id: str, requested_language: str | None) -> str:
        """
        Resolves Kokoro language code from the voice prefix.

        Args:
            voice_id: Kokoro voice ID, such as af_sarah or bf_emma.
            requested_language: Caller-provided fallback language.

        Returns:
            Kokoro ONNX language code.
        """

        clean_voice = str(voice_id or "").strip().lower()
        voice_prefix = clean_voice[:1]
        return self.LANGUAGE_BY_VOICE_PREFIX.get(
            voice_prefix,
            str(requested_language or "en-us").strip() or "en-us",
        )

    def __init__(
        self,
        model_path: str | Path,
        voices_path: str | Path,
        output_directory: str | Path | None = None,
    ) -> None:
        """
        Initializes the Kokoro model once so each narration request can reuse it.

        Args:
            model_path: Path to kokoro-v1.0.onnx.
            voices_path: Path to voices-v1.0.bin.
            output_directory: Directory where generated WAV files should be written.
        """

        from kokoro_onnx import Kokoro

        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self.output_directory = Path(output_directory or tempfile.gettempdir())
        self.output_directory.mkdir(parents=True, exist_ok=True)

        if not self.model_path.exists():
            raise FileNotFoundError(f"Kokoro model file not found: {self.model_path}")

        if not self.voices_path.exists():
            raise FileNotFoundError(f"Kokoro voices file not found: {self.voices_path}")

        self._kokoro = Kokoro(str(self.model_path), str(self.voices_path))
        logging.info("Kokoro-ONNX TTS initialized.")

    def synthesize_to_file(self, request: TTSRequest) -> Path:
        """
        Synthesizes text into a WAV file.

        Args:
            request: TTS request data.

        Returns:
            Path to the generated WAV file.
        """

        import soundfile as sf

        clean_text = str(request.text or "").strip()
        if not clean_text:
            logging.warning("KokoroOnnxTTSEngine received empty text.")
            raise ValueError("Cannot synthesize empty text.")

        output_path = self.output_directory / f"ai_adventure_tts_{uuid.uuid4().hex}.wav"

        try:
            voice_id = self._resolve_voice_id(request.voice)
            language_code = self._resolve_language_for_voice(voice_id, request.language)

            samples, sample_rate = self._kokoro.create(
                clean_text,
                voice=voice_id,
                speed=max(0.25, min(2.0, float(request.speed))),
                lang=language_code,
            )

            sf.write(str(output_path), samples, sample_rate)
            return output_path

        except Exception as error:
            logging.exception("Kokoro-ONNX synthesis failed: %s", error)
            raise


class EdgeTTSEngine(TTSEngine):
    """Optional cloud fallback for the old Edge TTS behavior."""

    DEFAULT_VOICE: Final[str] = "en-US-AriaNeural"
    
    AVAILABLE_VOICES: ClassVar[dict[str, str]] = {
        "Aria (Female, US)": "en-US-AriaNeural",
        "Jenny (Female, US)": "en-US-JennyNeural",
        "Guy (Male, US)": "en-US-GuyNeural",
        "Ryan (Male, UK)": "en-GB-RyanNeural",
        "Sonia (Female, UK)": "en-GB-SoniaNeural",
    }

    KOKORO_VOICE_PREFIXES: ClassVar[tuple[str, ...]] = (
        "af_",
        "am_",
        "bf_",
        "bm_",
    )

    def get_available_voices(self) -> dict[str, str]:
        """
        Returns Edge TTS voice choices for the Audio Settings dialog.

        Returns:
            Display-name-to-voice-ID mapping.
        """

        return dict(self.AVAILABLE_VOICES)

    def _resolve_voice_id(self, voice_id: str | None) -> str:
        """
        Prevents Kokoro voice IDs from being passed into Edge TTS.

        Args:
            voice_id: Requested voice ID.

        Returns:
            Valid Edge TTS voice ID.
        """

        clean_voice = str(voice_id or "").strip()

        if not clean_voice:
            return self.DEFAULT_VOICE

        if clean_voice.startswith(self.KOKORO_VOICE_PREFIXES):
            logging.warning(
                "Edge TTS received Kokoro voice ID %r. Using Edge default %r instead.",
                clean_voice,
                self.DEFAULT_VOICE,
            )
            return self.DEFAULT_VOICE

        return clean_voice

    def __init__(self, output_directory: str | Path | None = None) -> None:
        """
        Initializes the Edge TTS fallback engine.

        Args:
            output_directory: Directory where generated MP3 files should be written.
        """

        self.output_directory = Path(output_directory or tempfile.gettempdir())
        self.output_directory.mkdir(parents=True, exist_ok=True)

    def synthesize_to_file(self, request: TTSRequest) -> Path:
        """
        Synthesizes text into an MP3 file using Edge TTS.

        Args:
            request: TTS request data.

        Returns:
            Path to the generated MP3 file.
        """

        import edge_tts

        clean_text = str(request.text or "").strip()
        if not clean_text:
            logging.warning("EdgeTTSEngine received empty text.")
            raise ValueError("Cannot synthesize empty text.")

        output_path = self.output_directory / f"ai_adventure_tts_{uuid.uuid4().hex}.mp3"
        edge_rate = self._speed_to_edge_rate(request.speed)

        try:
            communicate = edge_tts.Communicate(
                clean_text,
                self._resolve_voice_id(request.voice),
                rate=edge_rate,
            )

            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(communicate.save(str(output_path)))
            finally:
                loop.close()

            return output_path

        except Exception as error:
            logging.exception("Edge TTS synthesis failed: %s", error)
            raise

    def _speed_to_edge_rate(self, speed: float) -> str:
        """
        Converts a generic speed multiplier into Edge TTS rate syntax.

        Args:
            speed: Speech speed multiplier.

        Returns:
            Edge rate string, such as '+10%' or '-10%'.
        """

        try:
            normalized_speed = max(0.25, min(2.0, float(speed)))
        except (TypeError, ValueError):
            logging.exception("Invalid TTS speed value: %r", speed)
            normalized_speed = 1.0

        percent_delta = int((normalized_speed - 1.0) * 100)
        return f"{percent_delta:+d}%"


class TTSManager:
    """Facade for whichever TTS engine the application is currently using."""

    def __init__(self, engine: TTSEngine | None, disabled_reason: str = "") -> None:
        """
        Initializes the manager.

        Args:
            engine: Active TTS engine. If None, synthesis is disabled.
        """

        self.engine = engine
        self.disabled_reason = disabled_reason.strip()

    def synthesize_to_file(self, request: TTSRequest) -> Path | None:
        """
        Synthesizes speech using the active engine.

        Args:
            request: TTS request data.

        Returns:
            Path to audio file, or None if no engine is available.
        """

        if self.engine is None:
            if self.disabled_reason:
                logging.warning(
                    "TTS requested, but no TTS engine is configured. Reason: %s",
                    self.disabled_reason,
                )
            else:
                logging.warning("TTS requested, but no TTS engine is configured.")
            return None

        try:
            return self.engine.synthesize_to_file(request)
        except Exception as error:
            logging.exception("TTSManager synthesis failed: %s", error)
            return None
        
    def get_available_voices(self) -> dict[str, str]:
        """
        Returns voices supported by the active engine.

        Returns:
            Display-name-to-voice-ID mapping.
        """

        if self.engine is None:
            return {}

        return self.engine.get_available_voices()

    def get_default_voice(self) -> str:
        """
        Returns the active engine's default voice.

        Returns:
            Voice ID, or an empty string if TTS is disabled.
        """

        if self.engine is None:
            return ""

        return self.engine.get_default_voice()
        
class TTSSettingsProtocol(Protocol):
    """Settings attributes required by the TTS manager."""

    tts_engine: str


class TTSConfigurationProtocol(Protocol):
    """Configuration attributes required by the TTS manager."""

    settings: TTSSettingsProtocol
    kokoro_model_path: Path
    kokoro_voices_path: Path
        
def create_tts_manager(configuration: TTSConfigurationProtocol) -> TTSManager:
    """
    Creates the configured TTS manager.

    Args:
        configuration: Application Configuration instance.

    Returns:
        Configured TTSManager.
    """

    engine_name = str(configuration.settings.tts_engine or "kokoro_onnx").strip().lower()

    if engine_name == "kokoro_onnx":
        try:
            logging.info("Initializing Kokoro-ONNX TTS.")
            logging.info("Kokoro model path: %s", configuration.kokoro_model_path)
            logging.info("Kokoro voices path: %s", configuration.kokoro_voices_path)

            return TTSManager(
                KokoroOnnxTTSEngine(
                    model_path=configuration.kokoro_model_path,
                    voices_path=configuration.kokoro_voices_path,
                )
            )

        except Exception as error:
            disabled_reason = (
                "Failed to initialize Kokoro-ONNX TTS. "
                f"This can be caused by missing model files, missing voices files, "
                f"or missing PyInstaller package data for kokoro_onnx/phonemizer dependencies. "
                f"Model path: {configuration.kokoro_model_path}. Voices path: {configuration.kokoro_voices_path}. Error: {error}"
            )

            logging.exception(disabled_reason)
            return TTSManager(None, disabled_reason)

    if engine_name == "edge_tts":
        try:
            return TTSManager(EdgeTTSEngine())
        except Exception as error:
            return TTSManager(None, f"Failed to initialize Edge TTS: {error}")

    if engine_name in {"none", "disabled", "off"}:
        return TTSManager(None, f"TTS engine was explicitly disabled with value: {engine_name}")

    return TTSManager(None, f"Unknown TTS engine setting: {engine_name}")