import pytest

from vamc.commands import CommandIntent, IntentMapper
from vamc.controller import VAMCController
from vamc.feedback import FeedbackState, MemoryFeedback
from vamc.gestures import Gesture, GestureClassifier, SwipeDetector
from vamc.media import LinuxMediaController, MockMediaController
from vamc.voice import PushToTalk, TextRecognizer, VoiceActivation, WakeWordDetector


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
    ("next track", CommandIntent.NEXT),
    ("previous track", CommandIntent.PREVIOUS),
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


def test_push_to_talk_activates_without_wake_word():
    button = PushToTalk()
    activation = VoiceActivation(WakeWordDetector("computer"), button)
    button.press()
    assert activation.activated_by_button()
    assert not activation.activated_by_button()


def test_text_recognizer_transcribes_captured_audio():
    assert TextRecognizer().transcribe(b"volume up") == "volume up"


def test_custom_phrase_triggers_mapped_action():
    controller, media, _ = make_controller()
    controller.mapper.register("make it louder", CommandIntent.VOLUME_UP)
    assert controller.handle_text("make it louder")
    assert media.volume == 60


def test_linux_media_controller_uses_safe_commands(monkeypatch):
    calls = []

    class Result:
        stdout = "Front Left: Playback 50 [50%] [on]\n"

    def fake_run(command, **_kwargs):
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


def make_landmarks(tip_y: float) -> list[tuple[float, float]]:
    landmarks = [(0.5, 0.5)] * 21
    for tip, pip in zip((8, 12, 16, 20), (6, 10, 14, 18)):
        landmarks[pip] = (0.5, 0.4)
        landmarks[tip] = (0.5, tip_y)
    return landmarks


def test_fist_classifier_requires_all_four_fingers_folded():
    classifier = GestureClassifier()
    assert classifier.classify_fist(make_landmarks(0.7))
    assert not classifier.classify_fist(make_landmarks(0.3))


def test_swipe_detector_maps_horizontal_motion_to_volume_direction():
    detector = SwipeDetector(threshold=0.1)
    assert detector.detect([(0.2, 0.5)]) is None
    assert detector.detect([(0.4, 0.5)]) == Gesture.SWIPE_RIGHT
    assert detector.detect([(0.2, 0.5)]) == Gesture.SWIPE_LEFT


def test_gestures_control_volume_and_toggle_playback():
    controller, media, _ = make_controller()
    open_hand = make_landmarks(0.3)
    open_hand[0] = (0.2, 0.5)
    fist = make_landmarks(0.7)
    assert not controller.handle_gesture(open_hand)
    assert controller.handle_gesture([(0.2, 0.5)] + open_hand[1:]) is False
    assert controller.handle_gesture([(0.4, 0.5)] + open_hand[1:])
    assert media.volume == 60
    assert controller.handle_gesture(fist)
    assert media.playing
    assert not controller.handle_gesture(fist)
    assert controller.handle_gesture(open_hand) is False
    assert controller.handle_gesture(fist)
    assert not media.playing
