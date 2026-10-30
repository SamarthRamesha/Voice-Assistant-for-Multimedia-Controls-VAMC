from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import vosk

from vamc.controller import VAMCController
from vamc.feedback import MemoryFeedback
from vamc.media import MockMediaController


SAMPLE_RATE = 16000
BLOCK_SIZE = 800
TARGET_MS = 2000
DEFAULT_TRIALS = 50
CALIBRATION_BLOCKS = 4


def percentile_90(values: list[float]) -> float:
    ordered = sorted(values)
    index = math.ceil(0.90 * len(ordered)) - 1
    return ordered[index]


def capture_command(model, device, timeout):
    recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
    transcript = ""
    started = None

    try:
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            device=device,
            dtype="int16",
            channels=1,
        ) as stream:

            print("Calibrating background noise...")

            noise_levels = []

            for _ in range(CALIBRATION_BLOCKS):
                audio, _ = stream.read(BLOCK_SIZE)
                samples = np.frombuffer(bytes(audio), dtype=np.int16)
                rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                noise_levels.append(rms)

            noise_level = float(np.median(noise_levels))
            threshold = max(600.0, noise_level * 3.5)

            print(f"Background RMS: {noise_level:.1f}")
            print(f"Speech threshold: {threshold:.1f}")
            print("Speak your command now...")

            listen_started = time.perf_counter()

            while time.perf_counter() - listen_started < timeout:
                block_started = time.perf_counter()
                audio, _ = stream.read(BLOCK_SIZE)
                audio_bytes = bytes(audio)

                samples = np.frombuffer(audio_bytes, dtype=np.int16)
                rms = float(
                    np.sqrt(np.mean(samples.astype(np.float64) ** 2))
                )

                if started is None:
                    if rms < threshold:
                        continue

                    started = block_started
                    print("Speech detected. Processing...")

                if recognizer.AcceptWaveform(audio_bytes):
                    result = json.loads(recognizer.Result())
                    transcript = result.get("text", "").strip()

                    if transcript:
                        break

            if started is not None and not transcript:
                result = json.loads(recognizer.FinalResult())
                transcript = result.get("text", "").strip()

    except Exception as exc:
        print(f"Microphone error: {exc}")

    return transcript, started


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="models/vosk-model-small-en-us-0.15",
    )
    parser.add_argument("--device", type=int, default=2)
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--output",
        default="results/nf001_latency.csv",
    )
    args = parser.parse_args()

    model_path = Path(args.model)

    if not model_path.is_dir():
        raise SystemExit(f"Vosk model not found: {model_path}")

    print("Loading Vosk model...")
    model = vosk.Model(str(model_path))

    media = MockMediaController()
    controller = VAMCController(media, MemoryFeedback())

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    results = []

    print("\nVAMC NF-001 latency benchmark")
    print(f"Trials: {args.trials}")
    print(f"Target: {TARGET_MS} ms (P90)")
    print(f"Microphone device: {args.device}")
    print("\nSupported commands:")
    print("volume up, volume down, mute, unmute")
    print("play, pause, next, previous")
    print("\nThe timer starts when speech is detected.")
    print("Press Enter to begin each trial. Ctrl-C to stop.\n")

    try:
        for trial in range(1, args.trials + 1):
            input(f"Trial {trial}/{args.trials} - press Enter to start: ")

            transcript, started = capture_command(
                model,
                args.device,
                args.timeout,
            )

            executed = False
            latency_ms = None

            if transcript:
                executed = controller.handle_text(transcript)

            if started is not None and executed:
                latency_ms = round(
                    (time.perf_counter() - started) * 1000,
                    2,
                )

            results.append({
                "trial": trial,
                "transcript": transcript,
                "speech_detected": started is not None,
                "latency_ms": latency_ms if latency_ms is not None else "",
                "executed": executed,
            })

            print(f"Recognised: {transcript or '[no transcript]'}")
            print(f"Executed: {executed}")

            if latency_ms is not None:
                print(f"Latency: {latency_ms:.2f} ms")
            else:
                print("Latency: N/A (no executed command)")

            print()

    except KeyboardInterrupt:
        print("\nBenchmark interrupted.")

    if not results:
        print("No trials recorded.")
        return

    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "trial",
                "transcript",
                "speech_detected",
                "latency_ms",
                "executed",
            ],
        )
        writer.writeheader()
        writer.writerows(results)

    successful = sum(row["executed"] for row in results)
    failed = len(results) - successful

    valid_latencies = [
        float(row["latency_ms"])
        for row in results
        if row["latency_ms"] != ""
    ]

    p90 = percentile_90(valid_latencies) if valid_latencies else None

    passed = (
        len(results) == args.trials
        and successful >= math.ceil(0.90 * args.trials)
        and p90 is not None
        and p90 <= TARGET_MS
    )

    summary = {
        "requirement": "VAMC-NF-001",
        "test_case": "TC-Perf-01",
        "trials_completed": len(results),
        "successful_commands": successful,
        "failed_commands": failed,
        "latency_samples": len(valid_latencies),
        "p90_latency_ms": p90,
        "mean_latency_ms": (
            round(sum(valid_latencies) / len(valid_latencies), 2)
            if valid_latencies else None
        ),
        "max_latency_ms": max(valid_latencies) if valid_latencies else None,
        "target_latency_ms": TARGET_MS,
        "result": "PASS" if passed else "FAIL",
        "environment": "macOS, MacBook Air microphone, Vosk",
        "media_adapter": "MockMediaController",
        "timing_method": "Speech onset to controller action completion",
    }

    summary_path = output.with_name("nf001_summary.json")
    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("\n========== NF-001 RESULTS ==========")
    print(json.dumps(summary, indent=2))
    print(f"\nCSV: {output}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
