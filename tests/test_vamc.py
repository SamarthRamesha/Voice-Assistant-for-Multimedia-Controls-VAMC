import base64
from http.client import HTTPConnection
import json
from threading import Thread

import sys
from types import SimpleNamespace

import pytest

from vamc.commands import CommandIntent, IntentMapper
from vamc.controller import VAMCController
from vamc.dashboard import ConfigStore, serve
from vamc.feedback import FeedbackState, MemoryFeedback, SystemFeedback
from vamc.gestures import CameraGestureRunner, Gesture, GestureClassifier, SwipeDetector
from vamc.media import LinuxMediaController, MockMediaController, WindowsMediaController
from vamc.logs import SystemLog
from vamc.voice import PushToTalk, TextRecognizer, VoiceActivation, VoskRecognizer, WakeWordDetector


def make_controller():
    media = MockMediaController()
    feedback = MemoryFeedback()
    return VAMCController(media, feedback), media, feedback


@pytest.mark.parametrize("text,intent", [
    ("sound on", CommandIntent.UNMUTE),
    ("turn sound on", CommandIntent.UNMUTE),
    ("enable sound", CommandIntent.UNMUTE),
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


def test_system_log_records_commands_and_persists_exports(tmp_path):
    log_path = tmp_path / "system.jsonl"
    system_log = SystemLog(log_path)
    controller = VAMCController(MockMediaController(), MemoryFeedback(), system_log=system_log)
    assert controller.handle_text("play")
    assert not controller.handle_text("not a command")
    assert [entry["status"] for entry in system_log.view()] == ["success", "error"]

    reopened = SystemLog(log_path)
    assert len(reopened.view()) == 2
    json_path = tmp_path / "logs.json"
    csv_path = tmp_path / "logs.csv"
    assert reopened.export(json_path) == 2
    assert reopened.export(csv_path, "csv") == 2
    assert '"source": "voice"' in json_path.read_text()
    assert "timestamp,source,action,status,details" in csv_path.read_text()


def test_system_log_retains_only_last_30_days(tmp_path):
    log_path = tmp_path / "system.jsonl"
    old_entry = {
        "timestamp": "2020-01-01T00:00:00+00:00",
        "source": "voice",
        "action": "old",
        "status": "success",
        "details": "",
    }
    log_path.write_text(json.dumps(old_entry) + "\n")
    log = SystemLog(log_path)
    log.record("voice", "new", "success")
    assert [entry["action"] for entry in log.view()] == ["new"]


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


def test_linux_media_controller_restores_volume_after_unmute(monkeypatch):
    calls = []

    class Result:
        stdout = "Front Left: Playback 35 [35%] [on]\n"

    def fake_run(command, **_kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr("vamc.media.subprocess.run", fake_run)
    media = LinuxMediaController()
    media.mute()
    media.unmute()
    assert calls == [
        ("amixer", "get", "Master"),
        ("amixer", "get", "Master"),
        ("amixer", "set", "Master", "mute"),
        ("amixer", "set", "Master", "unmute"),
        ("amixer", "set", "Master", "35%"),
    ]


def test_linux_media_controller_supports_track_navigation(monkeypatch):
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)

        class Result:
            stdout = ""

        return Result()

    monkeypatch.setattr("vamc.media.subprocess.run", fake_run)
    media = LinuxMediaController()
    media.next()
    media.previous()
    assert calls == [
        ("playerctl", "next"),
        ("playerctl", "previous"),
    ]


def test_windows_media_controller_restores_volume_and_sends_media_keys():
    class Endpoint:
        def __init__(self):
            self.level = 0.35
            self.mute = False

        def GetMasterVolumeLevelScalar(self):
            return self.level

        def SetMasterVolumeLevelScalar(self, value, _context):
            self.level = value

        def GetMute(self):
            return self.mute

        def SetMute(self, value, _context):
            self.mute = bool(value)

    class User32:
        def __init__(self):
            self.events = []

        def keybd_event(self, key, _scan, flags, _extra):
            self.events.append((key, flags))

    endpoint = Endpoint()
    user32 = User32()
    media = WindowsMediaController(endpoint=endpoint, user32=user32)
    media.mute()
    media.unmute()
    media.play()
    media.pause()
    media.next()
    media.previous()
    assert media.volume == 35
    assert not media.muted
    assert user32.events == [
        (0xB3, 0), (0xB3, 0x0002),
        (0xB3, 0), (0xB3, 0x0002),
        (0xB0, 0), (0xB0, 0x0002),
        (0xB1, 0), (0xB1, 0x0002),
    ]


def test_camera_gesture_runner_forwards_rgb_landmarks_and_releases_capture():
    class Capture:
        def __init__(self):
            self.released = False

        def read(self):
            return True, "frame"

        def release(self):
            self.released = True

    class Cv2:
        COLOR_BGR2RGB = "rgb"

        def __init__(self):
            self.converted = []

        def cvtColor(self, frame, code):
            self.converted.append((frame, code))
            return "rgb frame"

    class Landmarker:
        def __init__(self):
            self.images = []

        def detect(self, image):
            self.images.append(image)
            return [(0.2, 0.5)]

    capture = Capture()
    cv2 = Cv2()
    landmarker = Landmarker()
    received = []
    runner = CameraGestureRunner(received.append, landmarker=landmarker, capture=capture, cv2_module=cv2)
    assert runner.run(max_frames=2) == 2
    assert cv2.converted == [("frame", "rgb"), ("frame", "rgb")]
    assert landmarker.images == ["rgb frame", "rgb frame"]
    assert received == [[(0.2, 0.5)], [(0.2, 0.5)]]
    assert capture.released


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


def test_system_feedback_speaks_success_and_updates_indicator(monkeypatch):
    calls = []

    class Indicator:
        def __init__(self):
            self.states = []

        def set_state(self, value):
            self.states.append(value)

    indicator = Indicator()
    monkeypatch.setattr(
        "vamc.feedback.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )
    feedback = SystemFeedback(indicator=indicator)
    feedback.state(FeedbackState.LISTENING)
    feedback.state(FeedbackState.PROCESSING)
    feedback.error("Command failed")
    assert indicator.states == [FeedbackState.LISTENING, FeedbackState.PROCESSING]
    assert calls == [(("espeak", "Command failed"), {"check": True, "capture_output": True})]


def test_config_store_persists_wifi_and_wake_word(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    config = store.load()
    assert config.wake_word == "computer"
    config.wifi_ssid = "test-network"
    config.wifi_password = "secret"
    config.wake_word = "assistant"
    store.save(config)
    assert store.load() == config


def test_dashboard_serves_status_history_and_config(tmp_path):
    controller, media, _ = make_controller()
    controller.handle_text("volume up")
    server = serve(controller, tmp_path / "config.json", port=0, dashboard_token="test-token")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert b"/api/status" in response.read()

        connection.request("GET", "/api/status")
        status = json.loads(connection.getresponse().read())
        assert status["volume"] == media.volume
        assert status["connection_status"] == "connected"
        assert len(status["history"]) == 1
        assert len(status["logs"]) == 1

        connection.request("GET", "/api/config")
        assert connection.getresponse().status == 401

        connection.request("GET", "/api/logs")
        logs = json.loads(connection.getresponse().read())
        assert logs["logs"][0]["action"] == "volume_up"

        connection.request("GET", "/api/logs/export?format=csv")
        export_response = connection.getresponse()
        assert export_response.status == 200
        assert export_response.getheader("Content-Type") == "text/csv"
        assert b"timestamp,source,action,status,details" in export_response.read()

        payload = json.dumps({
            "wifi_ssid": "test-network",
            "wifi_password": "secret",
            "wake_word": "assistant",
        })
        connection.request(
            "POST",
            "/api/config",
            body=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer test-token"},
        )
        assert connection.getresponse().status == 200
        assert ConfigStore(tmp_path / "config.json").load().wake_word == "assistant"

        connection.request("GET", "/api/config", headers={"Authorization": "Bearer test-token"})
        config_response = json.loads(connection.getresponse().read())
        assert config_response == {"wifi_ssid": "test-network", "wake_word": "assistant"}
        assert "secret" not in json.dumps(config_response)
    finally:
        connection.close()
        server.shutdown()
        server.server_close()

def test_vosk_recognizer_uses_optional_grammar(monkeypatch):
    calls = []

    class FakeRecognizer:
        def __init__(self, *args):
            calls.append(args)

        def AcceptWaveform(self, audio):
            return True

        def FinalResult(self):
            return '{"text": "sound on"}'

    fake_vosk = SimpleNamespace(
        Model=lambda path: "fake-model",
        KaldiRecognizer=FakeRecognizer,
    )
    monkeypatch.setitem(sys.modules, "vosk", fake_vosk)

    grammar = ["sound on", "turn sound on", "enable sound"]
    recognizer = VoskRecognizer("fake-model-path", grammar=grammar)

    assert recognizer.transcribe(b"fake audio") == "sound on"
    assert calls[0][0] == "fake-model"
    assert calls[0][1] == 16_000
    assert json.loads(calls[0][2]) == grammar + ["[unk]"]


def test_vosk_recognizer_supports_unrestricted_mode(monkeypatch):
    calls = []

    class FakeRecognizer:
        def __init__(self, *args):
            calls.append(args)

        def AcceptWaveform(self, audio):
            return True

        def FinalResult(self):
            return '{"text": "pause"}'

    fake_vosk = SimpleNamespace(
        Model=lambda path: "fake-model",
        KaldiRecognizer=FakeRecognizer,
    )
    monkeypatch.setitem(sys.modules, "vosk", fake_vosk)

    recognizer = VoskRecognizer("fake-model-path")

    assert recognizer.transcribe(b"fake audio") == "pause"
    assert calls[0] == ("fake-model", 16_000)
