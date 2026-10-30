from __future__ import annotations

from enum import Enum
import subprocess
from typing import Protocol


class FeedbackState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


class Feedback(Protocol):
    def state(self, value: FeedbackState) -> None: ...
    def confirm(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...


class MemoryFeedback:
    """Test/local adapter; replace with TTS and GPIO LED adapters on hardware."""

    def __init__(self) -> None:
        self.states: list[FeedbackState] = []
        self.messages: list[tuple[str, str]] = []

    def state(self, value: FeedbackState) -> None:
        self.states.append(value)

    def confirm(self, message: str) -> None:
        self.messages.append(("success", message))

    def error(self, message: str) -> None:
        self.messages.append(("error", message))


class SystemFeedback:
    """Provide audible confirmations and optional indicator output."""

    def __init__(self, speech_command: str = "espeak", indicator: "StatusIndicator | None" = None) -> None:
        self.speech_command = speech_command
        self.indicator = indicator

    def state(self, value: FeedbackState) -> None:
        if self.indicator is not None:
            self.indicator.set_state(value)

    def confirm(self, message: str) -> None:
        self._speak(message)

    def error(self, message: str) -> None:
        self._speak(message)

    def _speak(self, message: str) -> None:
        try:
            subprocess.run((self.speech_command, message), check=True, capture_output=True)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Speech command is unavailable: {self.speech_command}") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Speech command failed with exit code {exc.returncode}") from exc


class StatusIndicator(Protocol):
    def set_state(self, value: FeedbackState) -> None: ...


class GpioStatusIndicator:
    """Map feedback states to Raspberry Pi GPIO LEDs."""

    def __init__(self, pins: dict[FeedbackState, int]) -> None:
        try:
            from gpiozero import LED
        except ImportError as exc:
            raise RuntimeError("Install gpiozero to use the GPIO status indicator") from exc
        self._leds = {state: LED(pin) for state, pin in pins.items()}
        self.current_state: FeedbackState | None = None

    def set_state(self, value: FeedbackState) -> None:
        for led in self._leds.values():
            led.off()
        led = self._leds.get(value)
        if led is not None:
            led.on()
        self.current_state = value
