
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

import numpy as np


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
    """On-device ASR adapter; optionally supports command-constrained grammar."""

    def __init__(
        self,
        model_path: str,
        sample_rate: int = 16_000,
        grammar: list[str] | None = None,
    ) -> None:
        try:
            import vosk
        except ImportError as exc:
            raise RuntimeError(
                "Install vosk to use on-device speech recognition"
            ) from exc

        self._vosk = vosk
        self._model = vosk.Model(model_path)
        self._sample_rate = sample_rate
        self._grammar = grammar

    def transcribe(self, audio: bytes) -> str:
        if self._grammar:
            grammar_json = json.dumps(self._grammar + ["[unk]"])
            recognizer = self._vosk.KaldiRecognizer(
                self._model,
                self._sample_rate,
                grammar_json,
            )
        else:
            recognizer = self._vosk.KaldiRecognizer(
                self._model,
                self._sample_rate,
            )

        recognizer.AcceptWaveform(audio)

        result = json.loads(recognizer.FinalResult())
        text = result.get("text")

        if not isinstance(text, str) or not text:
            raise ValueError("No speech could be recognised")

        return text


class MicrophoneRecorder:
    """Capture one speech command from the default microphone."""

    def __init__(
        self,
        sample_rate: int = 16_000,
        silence_duration: float = 1.2,
        max_duration: float = 6.0,
        threshold: float = 0.015,
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_duration = silence_duration
        self.max_duration = max_duration
        self.threshold = threshold

    def record(self) -> bytes:
        # Import only when microphone recording is actually requested.
        import sounddevice as sd

        print("Listening... speak your command.")

        block_duration = 0.1
        block_size = int(self.sample_rate * block_duration)
        silence_blocks_required = int(
            self.silence_duration / block_duration
        )
        max_blocks = int(self.max_duration / block_duration)

        audio_blocks = []
        speech_started = False
        silence_blocks = 0

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=block_size,
        ) as stream:
            for _ in range(max_blocks):
                audio, overflowed = stream.read(block_size)

                if overflowed:
                    print("Warning: microphone input overflowed.")

                audio = audio.reshape(-1)
                volume = np.sqrt(
                    np.mean(audio.astype(np.float32) ** 2)
                )
                audio_blocks.append(audio.copy())

                if volume >= self.threshold * 32768:
                    speech_started = True
                    silence_blocks = 0
                elif speech_started:
                    silence_blocks += 1

                if (
                    speech_started
                    and silence_blocks >= silence_blocks_required
                ):
                    break

        if not speech_started:
            raise ValueError("No speech detected. Please try again.")

        samples = np.concatenate(audio_blocks)
        return samples.astype(np.int16).tobytes()


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
            raise RuntimeError(
                "Install gpiozero to use the GPIO button adapter"
            ) from exc

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
