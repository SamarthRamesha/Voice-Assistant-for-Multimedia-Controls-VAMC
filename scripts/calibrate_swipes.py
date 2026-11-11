import time
import cv2
from vamc.gestures import MediaPipeHandLandmarker

CAMERA_INDEX = 0
DURATION = 2.5

camera = cv2.VideoCapture(CAMERA_INDEX)
if not camera.isOpened():
    raise RuntimeError("Could not open webcam")

landmarker = MediaPipeHandLandmarker(
    model_path="models/hand_landmarker.task"
)

def record_swipe(label):
    input(f"\nGet ready. Press ENTER, then swipe {label.upper()}...")
    values = []
    start = time.monotonic()

    while time.monotonic() - start < DURATION:
        success, frame = camera.read()
        if not success:
            continue

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        hands = landmarker.detect(rgb)

        if hands:
            values.append(float(hands[0].x))

    if len(values) < 5:
        print("Not enough hand tracking data. Try again.")
        return

    print(f"\n{label.upper()} SWIPE")
    print(f"Samples: {len(values)}")
    print(f"Start X: {values[0]:.4f}")
    print(f"End X:   {values[-1]:.4f}")
    print(f"Delta X: {values[-1] - values[0]:+.4f}")
    print(f"Minimum: {min(values):.4f}")
    print(f"Maximum: {max(values):.4f}")

try:
    print("VAMC SWIPE CALIBRATION")
    print("Keep your hand visible and move it horizontally.")
    record_swipe("left")
    record_swipe("right")
    record_swipe("left")
    record_swipe("right")
finally:
    camera.release()
    landmarker._landmarker.close()
    print("\nCalibration finished.")
