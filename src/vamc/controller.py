from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from .commands import CommandIntent, IntentMapper
from .feedback import Feedback, FeedbackState
from .gestures import Gesture, GestureClassifier, SwipeDetector
from .logs import SystemLog
from .media import MediaController


@dataclass
class VAMCController:
    media: MediaController
    feedback: Feedback
    mapper: IntentMapper = field(default_factory=IntentMapper)
    history: list[dict[str, object]] = field(default_factory=list)
    gesture_classifier: GestureClassifier = field(default_factory=GestureClassifier)
    swipe_detector: SwipeDetector = field(default_factory=SwipeDetector)
    system_log: SystemLog = field(default_factory=SystemLog)
    _fist_active: bool = field(default=False, init=False)

    def set_listening(self) -> None:
        self.feedback.state(FeedbackState.LISTENING)

    def handle_text(self, text: str) -> bool:
        started = monotonic()
        self.feedback.state(FeedbackState.PROCESSING)
        command = self.mapper.map(text)
        if command is None:
            self.feedback.state(FeedbackState.ERROR)
            self.feedback.error("Command not recognised")
            self.system_log.record("voice", text, "error", "command not recognised")
            return False
        try:
            self._execute(command.intent)
        except Exception as exc:
            self.feedback.state(FeedbackState.ERROR)
            self.feedback.error(f"Command failed: {exc}")
            self.system_log.record("voice", command.intent.value, "error", str(exc))
            return False
        elapsed_ms = round((monotonic() - started) * 1000, 2)
        self.history.append({"phrase": command.phrase, "intent": command.intent.value, "latency_ms": elapsed_ms})
        self.feedback.state(FeedbackState.SUCCESS)
        self.feedback.confirm(f"Executed {command.intent.value.replace('_', ' ')}")
        self.system_log.record("voice", command.intent.value, "success", f"latency_ms={elapsed_ms}")
        return True

    def handle_gesture(self, landmarks: list[object]) -> bool:
        """Apply a fist toggle or a horizontal swipe to the media controller."""
        if not landmarks:
            self.swipe_detector.detect(landmarks)
            self._fist_active = False
            return False
        is_fist = self.gesture_classifier.classify_fist(landmarks)
        if is_fist:
            self.swipe_detector.detect([])
            if self._fist_active:
                return False
            self._fist_active = True
            self.media.pause() if getattr(self.media, "playing", False) else self.media.play()
            self.system_log.record("gesture", "fist", "success", "play_pause_toggle")
            return True
        self._fist_active = False
        gesture = self.swipe_detector.detect(landmarks)
        if gesture == Gesture.SWIPE_RIGHT:
            self.media.volume_up()
            self.system_log.record("gesture", gesture.value, "success", "volume_up")
            return True
        if gesture == Gesture.SWIPE_LEFT:
            self.media.volume_down()
            self.system_log.record("gesture", gesture.value, "success", "volume_down")
            return True
        return False

    def _execute(self, intent: CommandIntent) -> None:
        actions = {
            CommandIntent.VOLUME_UP: self.media.volume_up,
            CommandIntent.VOLUME_DOWN: self.media.volume_down,
            CommandIntent.MUTE: self.media.mute,
            CommandIntent.UNMUTE: self.media.unmute,
            CommandIntent.PLAY: self.media.play,
            CommandIntent.PAUSE: self.media.pause,
            CommandIntent.NEXT: self.media.next,
            CommandIntent.PREVIOUS: self.media.previous,
        }
        actions[intent]()
