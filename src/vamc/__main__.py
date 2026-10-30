import argparse
import json
import platform
from threading import Thread

from .controller import VAMCController
from .dashboard import serve
from .feedback import FeedbackState, GpioStatusIndicator, MemoryFeedback, SystemFeedback
from .gestures import CameraGestureRunner
from .logs import SystemLog
from .media import LinuxMediaController, MockMediaController, WindowsMediaController


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the VAMC command loop")
    parser.add_argument("--real", action="store_true", help="use the native media adapter")
    parser.add_argument("--gestures", action="store_true", help="control media with the camera")
    parser.add_argument("--camera", type=int, default=0, help="camera index for gesture mode")
    parser.add_argument("--feedback", action="store_true", help="enable audible system feedback")
    parser.add_argument("--led-listening-pin", type=int, help="GPIO pin for listening state")
    parser.add_argument("--led-processing-pin", type=int, help="GPIO pin for processing state")
    parser.add_argument("--led-error-pin", type=int, help="GPIO pin for error state")
    parser.add_argument("--dashboard", action="store_true", help="serve the local status dashboard")
    parser.add_argument("--config", default="config.json", help="dashboard configuration path")
    parser.add_argument("--port", type=int, default=8080, help="dashboard port")
    parser.add_argument("--dashboard-token", help="Bearer token for dashboard configuration access")
    parser.add_argument("--log-file", default="vamc.log.jsonl", help="JSON Lines system log path")
    parser.add_argument("--view-logs", action="store_true", help="view recent system logs and exit")
    parser.add_argument("--export-logs", metavar="PATH", help="export system logs to JSON or CSV")
    parser.add_argument("--export-format", choices=("json", "csv"), default="json")
    args = parser.parse_args()

    log = SystemLog(args.log_file)
    if args.view_logs:
        print(json.dumps(log.view(), indent=2))
        return
    if args.export_logs:
        print(f"Exported {log.export(args.export_logs, args.export_format)} log entries")
        return

    if args.real:
        if platform.system() == "Windows":
            media = WindowsMediaController()
        elif platform.system() == "Linux":
            media = LinuxMediaController()
        else:
            parser.error("--real is supported on Windows and Linux")
        indicator = None
        led_pins = {
            state: pin for state, pin in (
                (FeedbackState.LISTENING, args.led_listening_pin),
                (FeedbackState.PROCESSING, args.led_processing_pin),
                (FeedbackState.ERROR, args.led_error_pin),
            ) if pin is not None
        }
        if led_pins:
            indicator = GpioStatusIndicator({
                state: pin for state, pin in led_pins.items()
            })
        feedback = SystemFeedback(indicator=indicator) if args.feedback else MemoryFeedback()
    else:
        media = MockMediaController()
        feedback = SystemFeedback() if args.feedback else MemoryFeedback()
    controller = VAMCController(media, feedback, system_log=log)
    dashboard = None
    if args.dashboard:
        dashboard = serve(controller, args.config, port=args.port, dashboard_token=args.dashboard_token)
        Thread(target=dashboard.serve_forever, daemon=True).start()
        print(f"VAMC dashboard running at http://127.0.0.1:{args.port}")
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
        if dashboard is not None:
            dashboard.shutdown()


if __name__ == "__main__":
    main()
