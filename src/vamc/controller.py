from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from .commands import CommandIntent, IntentMapper
from .feedback import Feedback, FeedbackState
from .media import MediaController


@dataclass
class VAMCController:
    media: MediaController
    feedback: Feedback
    mapper: IntentMapper = field(default_factory=IntentMapper)
    history: list[dict[str, object]] = field(default_factory=list)

    def handle_text(self, text: str) -> bool:
        started = monotonic()
        self.feedback.state(FeedbackState.PROCESSING)
        command = self.mapper.map(text)
        if command is None:
            self.feedback.state(FeedbackState.ERROR)
            self.feedback.error("Command not recognised")
            return False
        try:
            self._execute(command.intent)
        except Exception as exc:
            self.feedback.state(FeedbackState.ERROR)
            self.feedback.error(f"Command failed: {exc}")
            return False
        elapsed_ms = round((monotonic() - started) * 1000, 2)
        self.history.append({"phrase": command.phrase, "intent": command.intent.value, "latency_ms": elapsed_ms})
        self.feedback.state(FeedbackState.SUCCESS)
        self.feedback.confirm(f"Executed {command.intent.value.replace('_', ' ')}")
        return True

    def _execute(self, intent: CommandIntent) -> None:
        actions = {
            CommandIntent.VOLUME_UP: self.media.volume_up,
            CommandIntent.VOLUME_DOWN: self.media.volume_down,
            CommandIntent.MUTE: self.media.mute,
            CommandIntent.UNMUTE: self.media.unmute,
            CommandIntent.PLAY: self.media.play,
            CommandIntent.PAUSE: self.media.pause,
        }
        actions[intent]()
