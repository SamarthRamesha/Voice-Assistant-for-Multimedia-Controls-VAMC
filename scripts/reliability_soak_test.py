
#!/usr/bin/env python3
"""Monitor an application during a continuous-operation soak test."""

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(
        description="VAMC continuous-operation reliability monitor"
    )
    parser.add_argument("--duration-hours", type=float, default=8)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--output-dir", default="results/nf003")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]

    if not command:
        parser.error("Provide the application command after --")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    events_file = output_dir / "events.csv"
    stdout_file = output_dir / "application.log"
    report_file = output_dir / "reliability_report.json"

    start_time = time.monotonic()
    start_timestamp = timestamp()
    target_seconds = args.duration_hours * 3600
    incidents = []
    samples = 0
    exit_code = None

    print(f"Starting reliability monitor: {start_timestamp}")
    print(f"Target duration: {args.duration_hours} hours")
    print(f"Command: {' '.join(command)}")

    with open(stdout_file, "w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

        with open(events_file, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([
                "timestamp",
                "elapsed_seconds",
                "process_id",
                "process_status",
            ])

            try:
                while time.monotonic() - start_time < target_seconds:
                    elapsed = time.monotonic() - start_time
                    exit_code = process.poll()
                    samples += 1

                    status = "RUNNING" if exit_code is None else "EXITED"

                    writer.writerow([
                        timestamp(),
                        round(elapsed, 2),
                        process.pid,
                        status,
                    ])
                    csv_file.flush()

                    if exit_code is not None:
                        incidents.append({
                            "time": timestamp(),
                            "type": "PROCESS_EXIT",
                            "exit_code": exit_code,
                            "elapsed_seconds": round(elapsed, 2),
                        })
                        print(f"Application exited unexpectedly: {exit_code}")
                        break

                    time.sleep(min(args.interval, max(
                        0, target_seconds - elapsed
                    )))

            except KeyboardInterrupt:
                incidents.append({
                    "time": timestamp(),
                    "type": "MONITOR_INTERRUPTED",
                    "description": "Soak test stopped manually",
                })
                print("\nSoak test interrupted.")

            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    elapsed = time.monotonic() - start_time
    completed = (
        elapsed >= target_seconds
        and exit_code is None
        and not incidents
    )

    report = {
        "test_case": "TC-Rel-01",
        "requirement": "VAMC-NF-003",
        "start_time": start_timestamp,
        "end_time": timestamp(),
        "target_hours": args.duration_hours,
        "actual_hours": round(elapsed / 3600, 4),
        "samples_recorded": samples,
        "command": command,
        "process_exit_code": exit_code,
        "incidents": incidents,
        "result": "PASS" if completed else "FAIL",
        "note": (
            "Monitor completed without detecting process exit."
            if completed else
            "Target duration was not completed cleanly."
        ),
    }

    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nReliability report:")
    print(json.dumps(report, indent=2))
    print(f"\nReport saved to: {report_file}")

    return 0 if completed else 1


if __name__ == "__main__":
    sys.exit(main())

