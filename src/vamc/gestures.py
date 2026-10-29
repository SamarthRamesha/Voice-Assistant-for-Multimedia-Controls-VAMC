from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol, Sequence


class Gesture(str, Enum):
    FIST = "fist"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"


def _coordinates(landmark: Any) -> tuple[float, float]:
    if hasattr(landmark, "x") and hasattr(landmark, "y"):
        return float(landmark.x), float(landmark.y)
    return float(landmark[0]), float(landmark[1])


class GestureClassifier:
    """Classifies normalized MediaPipe hand landmarks without importing MediaPipe."""

    _FINGER_TIPS = (8, 12, 16, 20)
    _FINGER_PIPS = (6, 10, 14, 18)

    def classify_fist(self, landmarks: Sequence[Any]) -> bool:
        if len(landmarks) < 21:
            raise ValueError("a hand must contain at least 21 landmarks")
        return all(
            _coordinates(landmarks[tip])[1] > _coordinates(landmarks[pip])[1]
            for tip, pip in zip(self._FINGER_TIPS, self._FINGER_PIPS)
        )


@dataclass
class SwipeDetector:
    """Detects horizontal movement between successive wrist landmarks."""

    threshold: float = 0.18
    _previous_x: float | None = None

    def detect(self, landmarks: Sequence[Any]) -> Gesture | None:
        if not landmarks:
            self._previous_x = None
            return None
        current_x = _coordinates(landmarks[0])[0]
        if self._previous_x is None:
            self._previous_x = current_x
            return None
        delta = current_x - self._previous_x
        self._previous_x = current_x
        if abs(delta) < self.threshold:
            return None
        return Gesture.SWIPE_RIGHT if delta > 0 else Gesture.SWIPE_LEFT


class MediaPipeHandLandmarker:
    """Optional MediaPipe adapter that returns the first detected hand's landmarks."""

    def __init__(self, max_num_hands: int = 1) -> None:
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError("Install mediapipe to use hand landmark detection") from exc
        self._hands = mp.solutions.hands.Hands(max_num_hands=max_num_hands)

    def detect(self, image: Any) -> list[Any]:
        result = self._hands.process(image)
        if not result.multi_hand_landmarks:
            return []
        return list(result.multi_hand_landmarks[0].landmark)


class FrameCapture(Protocol):
    def read(self) -> tuple[bool, Any]: ...
    def release(self) -> None: ...


class CameraGestureRunner:
    """Reads camera frames and forwards detected hand landmarks to a handler."""

    def __init__(
        self,
        on_landmarks: Callable[[list[Any]], bool],
        camera_index: int = 0,
        landmarker: MediaPipeHandLandmarker | None = None,
        capture: FrameCapture | None = None,
        cv2_module: Any | None = None,
    ) -> None:
        try:
            cv2 = cv2_module or __import__("cv2")
        except ImportError as exc:
            raise RuntimeError("Install opencv-python to use camera gesture controls") from exc
        self._cv2 = cv2
        self._capture = capture or cv2.VideoCapture(camera_index)
        self._landmarker = landmarker or MediaPipeHandLandmarker()
        self._on_landmarks = on_landmarks

    def run(self, max_frames: int | None = None) -> int:
        processed = 0
        try:
            while max_frames is None or processed < max_frames:
                success, frame = self._capture.read()
                if not success:
                    break
                rgb_frame = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
                self._on_landmarks(self._landmarker.detect(rgb_frame))
                processed += 1
        finally:
            self._capture.release()
        return processed