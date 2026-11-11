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
    """Detect deliberate horizontal swipes using a rolling position window."""

    threshold: float = 0.16
    cooldown_seconds: float = 0.65
    window_size: int = 8

    _positions: list[float] = None
    _last_trigger: float = 0.0

    def __post_init__(self) -> None:
        from dataclasses import field
        self._positions = []

    def detect(self, landmarks: Sequence[Any]) -> Gesture | None:
        from time import monotonic

        if not landmarks:
            self._positions.clear()
            return None

        current_x = _coordinates(landmarks[0])[0]
        self._positions.append(current_x)

        if len(self._positions) > self.window_size:
            self._positions.pop(0)

        if len(self._positions) < self.window_size:
            return None

        now = monotonic()
        if now - self._last_trigger < self.cooldown_seconds:
            return None

        delta = self._positions[-1] - self._positions[0]

        if abs(delta) < self.threshold:
            return None

        self._last_trigger = now
        self._positions.clear()

        return (
            Gesture.SWIPE_RIGHT
            if delta > 0
            else Gesture.SWIPE_LEFT
        )

class MediaPipeHandLandmarker:
    """MediaPipe Tasks adapter returning the first detected hand's landmarks."""

    def __init__(
        self,
        max_num_hands: int = 1,
        model_path: str = "models/hand_landmarker.task",
    ) -> None:
        try:
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
        except ImportError as exc:
            raise RuntimeError(
                "Install a compatible mediapipe package to use hand detection"
            ) from exc

        from pathlib import Path

        model_file = Path(model_path)
        if not model_file.is_file():
            raise FileNotFoundError(
                f"Hand landmarker model not found: {model_file}"
            )

        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(
                model_asset_path=str(model_file.resolve())
            ),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=max_num_hands,
        )

        self._mp = mp
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    def detect(self, image: Any) -> list[Any]:
        mp_image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=image,
        )
        result = self._landmarker.detect(mp_image)

        if not result.hand_landmarks:
            return []

        return list(result.hand_landmarks[0])

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
