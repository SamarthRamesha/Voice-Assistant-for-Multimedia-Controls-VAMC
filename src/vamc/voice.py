from __future__ import annotations

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
