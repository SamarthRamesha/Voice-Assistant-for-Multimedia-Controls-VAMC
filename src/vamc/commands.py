from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class CommandIntent(str, Enum):
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    UNMUTE = "unmute"
    PLAY = "play"
    PAUSE = "pause"
    NEXT = "next"
    PREVIOUS = "previous"


@dataclass(frozen=True)
class Command:
    intent: CommandIntent
    phrase: str


class IntentMapper:
    """Maps speech to an allow-listed intent; it never executes speech directly."""

    _defaults = {
        CommandIntent.VOLUME_UP: ("volume up", "increase volume", "turn it up"),
        CommandIntent.VOLUME_DOWN: ("volume down", "decrease volume", "turn it down"),
        CommandIntent.MUTE: ("mute", "silence"),
        CommandIntent.UNMUTE: ("unmute", "sound on", "turn sound on", "enable sound"),
        CommandIntent.PLAY: ("play", "resume"),
        CommandIntent.PAUSE: ("pause", "stop playback"),
        CommandIntent.NEXT: ("next", "next track"),
        CommandIntent.PREVIOUS: ("previous", "previous track"),
    }

    def __init__(self, custom_phrases: dict[str, CommandIntent] | None = None) -> None:
        self._phrases: dict[str, CommandIntent] = {
            self._normalise(phrase): intent
            for intent, phrases in self._defaults.items()
            for phrase in phrases
        }
        self._custom_phrases: set[str] = set()
        for phrase, intent in (custom_phrases or {}).items():
            self.register(phrase, intent)

    def register(self, phrase: str, intent: CommandIntent) -> None:
        phrase = self._normalise(phrase)
        if not phrase:
            raise ValueError("A custom phrase must not be empty")
        if phrase not in self._phrases and len(self._custom_phrases) >= 10:
            raise ValueError("At most 10 custom phrases may be registered")
        self._phrases[phrase] = intent
        if phrase not in self._defaults_for_phrase():
            self._custom_phrases.add(phrase)

    def map(self, text: str) -> Command | None:
        phrase = self._normalise(text)
        intent = self._phrases.get(phrase)
        return Command(intent, phrase) if intent else None

    @staticmethod
    def _normalise(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    def _defaults_for_phrase(self) -> set[str]:
        return {self._normalise(phrase) for phrases in self._defaults.values() for phrase in phrases}
