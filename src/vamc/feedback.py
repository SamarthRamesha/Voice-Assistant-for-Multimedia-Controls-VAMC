from __future__ import annotations

from enum import Enum
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
