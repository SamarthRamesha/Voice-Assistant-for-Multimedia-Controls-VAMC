import argparse
import platform

from .controller import VAMCController
from .feedback import MemoryFeedback
from .gestures import CameraGestureRunner
from .media import LinuxMediaController, MockMediaController, WindowsMediaController


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the VAMC command loop")
    parser.add_argument("--real", action="store_true", help="use the native media adapter")
    parser.add_argument("--gestures", action="store_true", help="control media with the camera")
    parser.add_argument("--camera", type=int, default=0, help="camera index for gesture mode")
    args = parser.parse_args()

    if args.real:
        if platform.system() == "Windows":
            media = WindowsMediaController()
        elif platform.system() == "Linux":
            media = LinuxMediaController()
        else:
            parser.error("--real is supported on Windows and Linux")
        feedback = MemoryFeedback()
    else:
        media = MockMediaController()
        feedback = MemoryFeedback()
    controller = VAMCController(media, feedback)
    if args.gestures:
        print("VAMC gesture mode active. Press Ctrl-C to exit.")
        CameraGestureRunner(controller.handle_gesture, camera_index=args.camera).run()
        return
    print("VAMC ready. Type a command (Ctrl-D to exit).")
    try:
        while True:
            text = input("> ")
            controller.handle_text(text)
            print(f"volume={media.volume}% muted={media.muted} playing={media.playing}")
    except EOFError:
        return


if __name__ == "__main__":
    main()
