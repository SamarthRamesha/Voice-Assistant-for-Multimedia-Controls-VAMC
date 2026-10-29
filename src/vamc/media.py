from __future__ import annotations

from dataclasses import dataclass, field
import re
import subprocess
from typing import Protocol


class MediaController(Protocol):
    volume: int
    muted: bool

    def volume_up(self) -> None: ...
    def volume_down(self) -> None: ...
    def mute(self) -> None: ...
    def unmute(self) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def next(self) -> None: ...
    def previous(self) -> None: ...


@dataclass
class MockMediaController:
    volume: int = 50
    step: int = 10
    muted: bool = False
    playing: bool = False
    _previous_volume: int = field(default=50, init=False)

    def __post_init__(self) -> None:
        self.volume = self._clamp(self.volume)
        self.step = self._clamp(self.step)
        self._previous_volume = self.volume

    def volume_up(self) -> None:
        self.volume = self._clamp(self.volume + self.step)

    def volume_down(self) -> None:
        self.volume = self._clamp(self.volume - self.step)

    def mute(self) -> None:
        if not self.muted:
            self._previous_volume = self.volume
        self.muted = True
        self.volume = 0

    def unmute(self) -> None:
        if self.muted:
            self.volume = self._previous_volume
            self.muted = False

    def play(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def next(self) -> None:
        self.playing = True

    def previous(self) -> None:
        self.playing = True

    @staticmethod
    def _clamp(value: int) -> int:
        return max(0, min(100, value))


class LinuxMediaController:
    """Controls Linux audio with amixer and playback with playerctl."""

    def __init__(self, mixer: str = "Master", step: int = 10) -> None:
        self.mixer = mixer
        self.step = max(0, min(100, step))
        self._previous_volume = 0

    @property
    def volume(self) -> int:
        result = self._run("amixer", "get", self.mixer)
        matches = re.findall(r"\[(\d+)%\]", result.stdout)
        if not matches:
            raise RuntimeError("amixer did not return a readable volume")
        return int(matches[-1])

    @volume.setter
    def volume(self, value: int) -> None:
        value = max(0, min(100, value))
        self._run("amixer", "set", self.mixer, f"{value}%")

    @property
    def muted(self) -> bool:
        result = self._run("amixer", "get", self.mixer)
        states = re.findall(r"\[(on|off)\]", result.stdout)
        return bool(states) and states[-1] == "off"

    def volume_up(self) -> None:
        self.volume = self.volume + self.step

    def volume_down(self) -> None:
        self.volume = self.volume - self.step

    def mute(self) -> None:
        if not self.muted:
            self._previous_volume = self.volume
        self._run("amixer", "set", self.mixer, "mute")

    def unmute(self) -> None:
        self._run("amixer", "set", self.mixer, "unmute")
        if self._previous_volume:
            self.volume = self._previous_volume

    def play(self) -> None:
        self._run("playerctl", "play")

    def pause(self) -> None:
        self._run("playerctl", "pause")

    def next(self) -> None:
        self._run("playerctl", "next")

    def previous(self) -> None:
        self._run("playerctl", "previous")

    @staticmethod
    def _run(*command: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Required Linux command is unavailable: {command[0]}") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or "command failed"
            raise RuntimeError(f"{' '.join(command)}: {detail}") from exc
