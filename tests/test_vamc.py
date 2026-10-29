import pytest

from vamc.commands import CommandIntent, IntentMapper
from vamc.controller import VAMCController
from vamc.feedback import FeedbackState, MemoryFeedback
from vamc.media import LinuxMediaController, MockMediaController
from vamc.voice import WakeWordDetector


def make_controller():
    media = MockMediaController()
    feedback = MemoryFeedback()
    return VAMCController(media, feedback), media, feedback


@pytest.mark.parametrize("text,intent", [
    ("volume up", CommandIntent.VOLUME_UP),
    ("volume down", CommandIntent.VOLUME_DOWN),
    ("mute", CommandIntent.MUTE),
    ("unmute", CommandIntent.UNMUTE),
    ("play", CommandIntent.PLAY),
    ("pause", CommandIntent.PAUSE),
])
def test_supported_intents(text, intent):
    assert IntentMapper().map(text).intent == intent


def test_volume_boundaries_and_mute_restore():
    controller, media, _ = make_controller()
    media.volume = 95
    controller.handle_text("volume up")
    assert media.volume == 100
    controller.handle_text("mute")
    assert media.volume == 0 and media.muted
    controller.handle_text("unmute")
    assert media.volume == 100 and not media.muted
    controller.handle_text("volume down")
    assert media.volume == 90


def test_play_pause_and_feedback():
    controller, media, feedback = make_controller()
    assert controller.handle_text("play")
    assert media.playing
    assert controller.handle_text("pause")
    assert not media.playing
    assert FeedbackState.SUCCESS in feedback.states


def test_unknown_command_is_rejected():
    controller, media, feedback = make_controller()
    assert not controller.handle_text("delete all files")
    assert media.playing is False
    assert feedback.messages[-1][0] == "error"


def test_custom_phrase_limit():
    mapper = IntentMapper()
    for index in range(10):
        mapper.register(f"custom {index}", CommandIntent.PLAY)
    with pytest.raises(ValueError):
        mapper.register("custom 11", CommandIntent.PLAY)


def test_wake_word():
    detector = WakeWordDetector("computer")
    assert detector.detected("Computer volume up")
    assert not detector.detected("compute volume up")


def test_linux_media_controller_uses_safe_commands(monkeypatch):
    calls = []

    class Result:
        stdout = "Front Left: Playback 50 [50%] [on]\n"

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr("vamc.media.subprocess.run", fake_run)
    media = LinuxMediaController()
    media.volume_up()
    media.mute()
    media.play()
    assert calls == [
        ("amixer", "get", "Master"),
        ("amixer", "set", "Master", "60%"),
        ("amixer", "get", "Master"),
        ("amixer", "get", "Master"),
        ("amixer", "set", "Master", "mute"),
        ("playerctl", "play"),
    ]
