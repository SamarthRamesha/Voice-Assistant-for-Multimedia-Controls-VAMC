from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol


class SpeechRecognizer(Protocol):
    def transcribe(self, audio: bytes) -> str: ...


class WakeWordDetector:
    def __init__(self, wake_word: str = "computer") -> None:
        if not wake_word.strip():
            raise ValueError("wake word must not be empty")
        self.wake_word = wake_word.strip().lower()

    def detected(self, text: str) -> bool:
        return self.wake_word in text.lower().split()


class TextRecognizer:
    """Deterministic adapter used by tests and development without a microphone."""

    def transcribe(self, audio: bytes) -> str:
        return audio.decode("utf-8").strip()


class VoskRecognizer:
    """On-device ASR adapter; requires a downloaded Vosk model directory."""

    def __init__(self, model_path: str, sample_rate: int = 16_000) -> None:
        try:
            import vosk
        except ImportError as exc:
            raise RuntimeError("Install vosk to use on-device speech recognition") from exc
        self._vosk = vosk
        self._model = vosk.Model(model_path)
        self._sample_rate = sample_rate

    def transcribe(self, audio: bytes) -> str:
        recognizer = self._vosk.KaldiRecognizer(self._model, self._sample_rate)
        if not recognizer.AcceptWaveform(audio):
            raise ValueError("ASR did not produce a final result")
        result = json.loads(recognizer.Result())
        text = result.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("ASR returned no transcript")
        return text


@dataclass
class PushToTalk:
    """Activation boundary shared by GPIO and mock button implementations."""

    pressed: bool = False

    def press(self) -> None:
        self.pressed = True

    def consume(self) -> bool:
        was_pressed = self.pressed
        self.pressed = False
        return was_pressed


class GpioPushToTalk:
    """Raspberry Pi GPIO adapter using gpiozero's Button."""

    def __init__(self, pin: int, on_press) -> None:
        try:
            from gpiozero import Button
        except ImportError as exc:
            raise RuntimeError("Install gpiozero to use the GPIO button adapter") from exc
        self._button = Button(pin)
        self._button.when_pressed = on_press


@dataclass
class VoiceActivation:
    wake_word: WakeWordDetector
    push_to_talk: PushToTalk

    def activated_by_text(self, text: str) -> bool:
        return self.wake_word.detected(text)

    def activated_by_button(self) -> bool:
        return self.push_to_talk.consume()
