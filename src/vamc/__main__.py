
import argparse
import json
import platform
from threading import Thread

from .controller import VAMCController
from .dashboard import serve
from .feedback import (
    FeedbackState,
    GpioStatusIndicator,
    MemoryFeedback,
    SystemFeedback,
)
from .gestures import CameraGestureRunner
from .logs import SystemLog
from .media import LinuxMediaController, MockMediaController, WindowsMediaController
from .voice import MicrophoneRecorder, VoskRecognizer

from vamc.voice import (
    PushToTalk,
    TextRecognizer,
    VoiceActivation,
    VoskRecognizer,
    WakeWordDetector,
)

COMMAND_GRAMMAR = [
    "volume up",
    "increase volume",
    "volume down",
    "decrease volume",
    "mute",
    "sound on",
    "turn sound on",
    "enable sound",
    "play",
    "resume",
    "pause",
    "stop",
    "next",
    "skip",
    "previous",
    "go back",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the VAMC command loop")
    parser.add_argument("--real", action="store_true", help="use the native media adapter")
    parser.add_argument("--gestures", action="store_true", help="control media with the camera")
    parser.add_argument("--voice", action="store_true", help="control media using microphone input")
    parser.add_argument("--model", default="models/vosk-model-small-en-us-0.15", help="Vosk model directory")
    parser.add_argument("--camera", type=int, default=0, help="camera index for gesture mode")
    parser.add_argument("--feedback", action="store_true", help="enable audible system feedback")
    parser.add_argument("--led-listening-pin", type=int, help="GPIO pin for listening state")
    parser.add_argument("--led-processing-pin", type=int, help="GPIO pin for processing state")
    parser.add_argument("--led-error-pin", type=int, help="GPIO pin for error state")
    parser.add_argument("--dashboard", action="store_true", help="serve the local status dashboard")
    parser.add_argument("--config", default="config.json", help="dashboard configuration path")
    parser.add_argument("--port", type=int, default=8080, help="dashboard port")
    parser.add_argument("--host", default="127.0.0.1", help="dashboard bind address (non-localhost requires TLS)")
    parser.add_argument("--tls-cert", help="TLS certificate (PEM) for the dashboard")
    parser.add_argument("--tls-key", help="TLS private key (PEM) for the dashboard")
    parser.add_argument("--install-update", metavar="PACKAGE", help="verify and stage a signed update package, then exit")
    parser.add_argument("--update-signature", help="detached signature file (default: PACKAGE.sig)")
    parser.add_argument("--update-public-key", default="update_public_key.pem", help="trusted public key (PEM)")
    parser.add_argument("--dashboard-token", help="Bearer token for dashboard configuration access")
    parser.add_argument("--log-file", default="vamc.log.jsonl", help="JSON Lines system log path")
    parser.add_argument("--view-logs", action="store_true", help="view recent system logs and exit")
    parser.add_argument("--export-logs", metavar="PATH", help="export system logs to JSON or CSV")
    parser.add_argument("--export-format", choices=("json", "csv"), default="json")
    args = parser.parse_args()

    if args.voice and args.gestures:
        parser.error("--voice and --gestures cannot be used together")

    log = SystemLog(args.log_file)
    if args.view_logs:
        print(json.dumps(log.view(), indent=2))
        return
    if args.export_logs:
        print(f"Exported {log.export(args.export_logs, args.export_format)} log entries")
        return

    if args.install_update:
        from .ota import UpdateRejected, install_update
        try:
            staged = install_update(
                args.install_update,
                args.update_signature or args.install_update + ".sig",
                args.update_public_key,
            )
        except UpdateRejected as exc:
            log.record("ota", "install_update", "rejected", str(exc))
            parser.exit(1, f"Update rejected: {exc}\n")
        log.record("ota", "install_update", "success", str(staged))
        print(f"Update verified and staged at {staged}")
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
            state: pin
            for state, pin in (
                (FeedbackState.LISTENING, args.led_listening_pin),
                (FeedbackState.PROCESSING, args.led_processing_pin),
                (FeedbackState.ERROR, args.led_error_pin),
            )
            if pin is not None
        }
        if led_pins:
            indicator = GpioStatusIndicator(led_pins)

        feedback = (
            SystemFeedback(indicator=indicator)
            if args.feedback
            else MemoryFeedback()
        )
    else:
        media = MockMediaController()
        feedback = SystemFeedback() if args.feedback else MemoryFeedback()
    controller = VAMCController(media, feedback, system_log=log)
    dashboard = None
    if args.dashboard:
        try:
            dashboard = serve(
                controller,
                args.config,
                host=args.host,
                port=args.port,
                dashboard_token=args.dashboard_token,
                certfile=args.tls_cert,
                keyfile=args.tls_key,
            )
        except ValueError as exc:
            parser.error(str(exc))
        Thread(target=dashboard.serve_forever, daemon=True).start()
        scheme = "https" if args.tls_cert else "http"
        print(f"VAMC dashboard running at {scheme}://{args.host}:{args.port}")

    try:
        if args.gestures:
            print("VAMC gesture mode active. Press Ctrl-C to exit.")
            CameraGestureRunner(
                controller.handle_gesture,
                camera_index=args.camera,
            ).run()
            return

        if args.voice:
            print("VAMC voice mode active.")
            print("Press Enter, speak one command, then wait for the result.")
            print("Press Ctrl-C to exit.")

            recognizer = VoskRecognizer(
                args.model,
                sample_rate=16_000,
                grammar=COMMAND_GRAMMAR,
            )
            recorder = MicrophoneRecorder(sample_rate=16_000)

            while True:
                input("\nPress Enter to speak...")
                controller.set_listening()

                try:
                    audio = recorder.record()
                    transcript = recognizer.transcribe(audio)
                    print(f"Recognised: {transcript}")
                    controller.handle_text(transcript)
                    print(
                        f"volume={media.volume}% "
                        f"muted={media.muted} "
                        f"playing={media.playing}"
                    )
                except (ValueError, RuntimeError) as exc:
                    print(f"Voice input error: {exc}")
                    feedback.state(FeedbackState.ERROR)
                    feedback.error(str(exc))

            return

        print("VAMC ready. Type a command (Ctrl-D to exit).")
        while True:
            text = input("> ")
            controller.handle_text(text)
            print(
                f"volume={media.volume}% "
                f"muted={media.muted} "
                f"playing={media.playing}"
            )

    except (EOFError, KeyboardInterrupt):
        print("\nVAMC shutting down.")
    finally:
        if dashboard is not None:
            dashboard.shutdown()


if __name__ == "__main__":
    main()

