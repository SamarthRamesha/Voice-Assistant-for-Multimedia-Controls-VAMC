from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any


class SystemLog:
    """Append-only JSON Lines system log with bounded viewing and export."""

    _FIELDS = ("timestamp", "source", "action", "status", "details")

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: list[dict[str, Any]] = self._load()
        self._lock = Lock()

    def _load(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and all(field in entry for field in self._FIELDS):
                entries.append({field: entry[field] for field in self._FIELDS})
        return entries

    def record(
        self,
        source: str,
        action: str,
        status: str,
        details: str = "",
    ) -> dict[str, Any]:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "action": action,
            "status": status,
            "details": details,
        }
        with self._lock:
            self._entries.append(entry)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry) + "\n")
        return entry

    def view(self, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("log limit must be positive")
        with self._lock:
            return [dict(entry) for entry in self._entries[-limit:]]

    def export(self, destination: str | Path, format: str = "json") -> int:
        entries = self.view(limit=max(1, len(self._entries)))
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.render(format, entries), encoding="utf-8")
        return len(entries)

    def render(self, format: str = "json", entries: list[dict[str, Any]] | None = None) -> str:
        entries = self.view(limit=max(1, len(self._entries))) if entries is None else entries
        if format == "json":
            return json.dumps(entries, indent=2) + "\n"
        elif format == "csv":
            import io
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=self._FIELDS)
            writer.writeheader()
            writer.writerows(entries)
            return stream.getvalue()
        else:
            raise ValueError("log export format must be json or csv")

    def __len__(self) -> int:
        return len(self._entries)