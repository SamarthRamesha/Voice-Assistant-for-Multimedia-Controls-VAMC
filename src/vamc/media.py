from __future__ import annotations

from dataclasses import dataclass, field
import re
import subprocess
from typing import Protocol
import json

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
        self._previous_volume: int | None = None

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

    @property
    def playing(self) -> bool:
        result = self._run("playerctl", "status")
        return result.stdout.strip().lower() == "playing"

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
        if self._previous_volume is not None:
            self.volume = self._previous_volume
            self._previous_volume = None

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


class WindowsMediaController:
    """Controls Windows audio through pycaw and playback through media keys."""

    _MEDIA_KEYS = {"play": 0xB3, "next": 0xB0, "previous": 0xB1}
    _KEYEVENTF_KEYUP = 0x0002

    def __init__(self, step: int = 10, endpoint=None, user32=None) -> None:
        self.step = max(0, min(100, step))
        self._previous_volume: int | None = None
        self._endpoint = endpoint or self._load_endpoint()
        if user32 is None:
            try:
                import ctypes
                user32 = ctypes.windll.user32
            except (AttributeError, ImportError) as exc:
                raise RuntimeError("Windows media controls require Windows") from exc
        self._user32 = user32

    @staticmethod
    def _load_endpoint():
        try:
            from pycaw.pycaw import AudioUtilities
            return AudioUtilities.GetSpeakers().EndpointVolume
        except ImportError as exc:
            raise RuntimeError("Install pycaw to use Windows media controls") from exc

    @property
    def volume(self) -> int:
        return round(self._endpoint.GetMasterVolumeLevelScalar() * 100)

    @volume.setter
    def volume(self, value: int) -> None:
        value = max(0, min(100, value))
        self._endpoint.SetMasterVolumeLevelScalar(value / 100, None)

    @property
    def muted(self) -> bool:
        return bool(self._endpoint.GetMute())

    def volume_up(self) -> None:
        self.volume = self.volume + self.step

    def volume_down(self) -> None:
        self.volume = self.volume - self.step

    def mute(self) -> None:
        if not self.muted:
            self._previous_volume = self.volume
        self._endpoint.SetMute(1, None)

    def unmute(self) -> None:
        self._endpoint.SetMute(0, None)
        if self._previous_volume is not None:
            self.volume = self._previous_volume
            self._previous_volume = None

    def play(self) -> None:
        self._media_key("play")

    def pause(self) -> None:
        self._media_key("play")

    def next(self) -> None:
        self._media_key("next")

    def previous(self) -> None:
        self._media_key("previous")

    def _media_key(self, name: str) -> None:
        key = self._MEDIA_KEYS[name]
        self._user32.keybd_event(key, 0, 0, 0)
        self._user32.keybd_event(key, 0, self._KEYEVENTF_KEYUP, 0)


class MacOSMediaController:
    """Controls system audio and whichever app owns the macOS media session."""

    def __init__(self, step: int = 10) -> None:
        self.step = max(0, min(100, step))
        self._previous_volume: int | None = None

    @staticmethod
    def _run(*command: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Required macOS command is unavailable: {command[0]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"macOS media command timed out: {' '.join(command)}"
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or "command failed"
            raise RuntimeError(
                f"{' '.join(command)}: {detail}"
            ) from exc

    @property
    def volume(self) -> int:
        result = self._run(
            "osascript",
            "-e",
            "get volume settings",
        )

        match = re.search(r"output volume:\s*(\d+)", result.stdout)
        if not match:
            raise RuntimeError(
                f"Could not read macOS output volume: {result.stdout.strip()}"
            )

        return int(match.group(1))

    @volume.setter
    def volume(self, value: int) -> None:
        value = max(0, min(100, value))
        self._run(
            "osascript",
            "-e",
            f"set volume output volume {value}",
        )

    @property
    def muted(self) -> bool:
        result = self._run(
            "osascript",
            "-e",
            "get volume settings",
        )

        match = re.search(r"output muted:\s*(true|false)", result.stdout, re.I)
        if not match:
            raise RuntimeError(
                f"Could not read macOS mute state: {result.stdout.strip()}"
            )

        return match.group(1).lower() == "true"

    @property
    def playing(self) -> bool:
        result = self._run("media-control", "get", "--no-artwork")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "media-control returned invalid JSON"
            ) from exc

        # The current media-control output may expose state at the root
        # or inside a payload, depending on the command/output version.
        state = data.get("payload", data)

        if "isPlaying" in state:
            return bool(state["isPlaying"])

        if "playing" in state:
            return bool(state["playing"])

        if "playbackRate" in state:
            return float(state["playbackRate"]) > 0

        raise RuntimeError(
            "Could not determine playback state from media-control output"
        )

    def volume_up(self) -> None:
        self.volume = self.volume + self.step

    def volume_down(self) -> None:
        self.volume = self.volume - self.step

    def mute(self) -> None:
        if not self.muted:
            self._previous_volume = self.volume

        self._run(
            "osascript",
            "-e",
            "set volume output muted true",
        )

    def unmute(self) -> None:
        self._run(
            "osascript",
            "-e",
            "set volume output muted false",
        )

        if self._previous_volume is not None:
            self.volume = self._previous_volume
            self._previous_volume = None

    def play(self) -> None:
        self._run("media-control", "play")

    def pause(self) -> None:
        self._run("media-control", "pause")

    def next(self) -> None:
        self._run("media-control", "next-track")

    def previous(self) -> None:
        self._run("media-control", "previous-track")

