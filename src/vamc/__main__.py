import argparse

from .controller import VAMCController
from .feedback import MemoryFeedback
from .media import LinuxMediaController, MockMediaController


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the VAMC command loop")
    parser.add_argument("--real", action="store_true", help="use the Linux media adapter")
    args = parser.parse_args()

    if args.real:
        media = LinuxMediaController()
        feedback = MemoryFeedback()
    else:
        media = MockMediaController()
        feedback = MemoryFeedback()
    controller = VAMCController(media, feedback)
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
