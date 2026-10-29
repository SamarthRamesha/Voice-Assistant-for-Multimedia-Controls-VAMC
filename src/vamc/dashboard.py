from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .controller import VAMCController


@dataclass
class DashboardConfig:
    wifi_ssid: str = ""
    wifi_password: str = ""
    wake_word: str = "computer"


class ConfigStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def load(self) -> DashboardConfig:
        if not self.path.exists():
            return DashboardConfig()
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Unable to read dashboard configuration: {self.path}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Dashboard configuration must be a JSON object")
        return DashboardConfig(
            wifi_ssid=str(data.get("wifi_ssid", "")),
            wifi_password=str(data.get("wifi_password", "")),
            wake_word=str(data.get("wake_word", "computer")),
        )

    def save(self, config: DashboardConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", dir=self.path.parent, delete=False) as temporary:
            json.dump(asdict(config), temporary, indent=2)
            temporary.write("\n")
            temporary_path = temporary.name
        os.replace(temporary_path, self.path)


def _dashboard_html() -> bytes:
    return b"""<!doctype html>
<html><head><meta charset="utf-8"><title>VAMC status</title></head>
<body><h1>VAMC status</h1><pre id="status">Loading...</pre>
<script>
async function refresh() {
  const response = await fetch('/api/status');
  document.getElementById('status').textContent =
    JSON.stringify(await response.json(), null, 2);
}
refresh();
setInterval(refresh, 1000);
</script></body></html>"""


def make_handler(controller: VAMCController, store: ConfigStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: HTTPStatus, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError("Request body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
            return payload

        def do_GET(self) -> None:
            if self.path == "/":
                body = _dashboard_html()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/api/status":
                media = controller.media
                self._json(HTTPStatus.OK, {
                    "volume": media.volume,
                    "muted": media.muted,
                    "connection_status": "connected",
                    "history": controller.history[-10:],
                })
                return
            if self.path == "/api/config":
                config = store.load()
                self._json(HTTPStatus.OK, {
                    "wifi_ssid": config.wifi_ssid,
                    "wake_word": config.wake_word,
                })
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self) -> None:
            if self.path != "/api/config":
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            try:
                payload = self._read_json()
                config = store.load()
                updated = DashboardConfig(
                    wifi_ssid=str(payload.get("wifi_ssid", config.wifi_ssid)),
                    wifi_password=str(payload.get("wifi_password", config.wifi_password)),
                    wake_word=str(payload.get("wake_word", config.wake_word)).strip(),
                )
                if not updated.wake_word:
                    raise ValueError("wake_word must not be empty")
                store.save(updated)
            except (ValueError, RuntimeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json(HTTPStatus.OK, {"saved": True})

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def serve(
    controller: VAMCController,
    config_path: str | os.PathLike[str],
    host: str = "127.0.0.1",
    port: int = 8080,
) -> ThreadingHTTPServer:
    store = ConfigStore(config_path)
    store.load()
    return ThreadingHTTPServer((host, port), make_handler(controller, store))
