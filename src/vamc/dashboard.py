from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import secrets
import ssl
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import parse_qs, urlparse

from .controller import VAMCController
from .security import LoginLimiter, SecretBox, load_or_create_key


@dataclass
class DashboardConfig:
    wifi_ssid: str = ""
    wifi_password: str = ""
    wake_word: str = "computer"
    api_key: str = ""


class ConfigStore:
    """Persists dashboard settings. Secrets are encrypted at rest (SR-003)."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        secret_box: SecretBox | None = None,
    ) -> None:
        self.path = Path(path)
        if secret_box is None:
            key_path = self.path.with_name(self.path.name + ".key")
            secret_box = SecretBox(load_or_create_key(key_path))
        self._box = secret_box

    def load(self) -> DashboardConfig:
        if not self.path.exists():
            return DashboardConfig()

        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Unable to read dashboard configuration: {self.path}"
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError("Dashboard configuration must be a JSON object")

        return DashboardConfig(
            wifi_ssid=str(data.get("wifi_ssid", "")),
            wifi_password=self._box.decrypt(
                str(data.get("wifi_password", ""))
            ),
            wake_word=str(data.get("wake_word", "computer")),
            api_key=self._box.decrypt(str(data.get("api_key", ""))),
        )

    def save(self, config: DashboardConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            "w",
            dir=self.path.parent,
            delete=False,
        ) as temporary:
            stored = asdict(config)
            stored["wifi_password"] = self._box.encrypt(
                config.wifi_password
            )
            stored["api_key"] = self._box.encrypt(config.api_key)

            json.dump(stored, temporary, indent=2)
            temporary.write("\n")
            temporary_path = temporary.name

        os.replace(temporary_path, self.path)


def _dashboard_html() -> bytes:
    return b"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>VAMC dashboard</title><style>
:root{font:16px system-ui,sans-serif;color:#17212b;background:#eef2f5}body{margin:0}
main{max-width:1100px;margin:auto;padding:clamp(16px,4vw,40px)}header{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
h1{margin:0;font-size:clamp(1.5rem,4vw,2.4rem)}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:24px 0}.card{background:white;border:1px solid #d5dde5;border-radius:8px;padding:18px;min-width:0}.value{font-size:1.6rem;font-weight:700;overflow-wrap:anywhere}
section{background:white;border:1px solid #d5dde5;border-radius:8px;padding:18px;margin-top:16px;overflow:auto}table{width:100%;border-collapse:collapse;min-width:560px}th,td{text-align:left;padding:10px;border-bottom:1px solid #e5e9ed}th{font-size:.8rem;text-transform:uppercase;color:#5a6875}a{color:#075985}
@media(max-width:640px){.grid{grid-template-columns:1fr 1fr}.grid .card:last-child{grid-column:1/-1}section{padding:12px}table{min-width:0}thead{display:none}tr{display:block;padding:10px 0}td{display:block;border:0;padding:3px 0}td:before{content:attr(data-label);font-weight:700;margin-right:8px;color:#5a6875}}
</style></head><body><main><header><h1>VAMC dashboard</h1><span id="updated">Loading...</span></header>
<div class="grid"><div class="card"><div>Volume</div><div class="value" id="volume">-</div></div><div class="card"><div>Muted</div><div class="value" id="muted">-</div></div><div class="card"><div>Connection</div><div class="value" id="connection">-</div></div></div>
<section><h2>System logs</h2><p><a href="/api/logs/export?format=json">Export JSON</a> &middot; <a href="/api/logs/export?format=csv">Export CSV</a></p><table><thead><tr><th>Time</th><th>Source</th><th>Action</th><th>Status</th><th>Details</th></tr></thead><tbody id="logs"></tbody></table></section>
</main><script>
async function refresh(){const data=await (await fetch('/api/status')).json();document.getElementById('volume').textContent=data.volume+'%';document.getElementById('muted').textContent=data.muted?'Yes':'No';document.getElementById('connection').textContent=data.connection_status;document.getElementById('updated').textContent='Updated '+new Date().toLocaleTimeString();document.getElementById('logs').innerHTML=data.logs.map(log=>'<tr><td data-label="Time">'+log.timestamp+'</td><td data-label="Source">'+log.source+'</td><td data-label="Action">'+log.action+'</td><td data-label="Status">'+log.status+'</td><td data-label="Details">'+log.details+'</td></tr>').join('')}
refresh();setInterval(refresh,1000);
</script></body></html>"""


def make_handler(
    controller: VAMCController,
    store: ConfigStore,
    dashboard_token: str,
    limiter: LoginLimiter | None = None,
) -> type[BaseHTTPRequestHandler]:
    limiter = limiter or LoginLimiter()

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

        def _authenticated(self) -> bool:
            client = self.client_address[0]
            wait = limiter.retry_after(client)

            if wait > 0:
                # SR-005: locked out, even a correct token is refused until it expires.
                body = json.dumps({
                    "error": "Too many failed attempts; try again later"
                }).encode()

                self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", str(int(wait) + 1))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return False

            expected = f"Bearer {dashboard_token}"

            if secrets.compare_digest(
                self.headers.get("Authorization", ""),
                expected,
            ):
                limiter.record_success(client)
                return True

            limiter.record_failure(client)
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "Bearer token required"},
            )
            return False

        def do_GET(self) -> None:
            if self.path == "/":
                body = _dashboard_html()
                self.send_response(HTTPStatus.OK)
                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8",
                )
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
                    "logs": controller.system_log.view(10),
                })
                return

            if self.path == "/api/logs":
                self._json(
                    HTTPStatus.OK,
                    {"logs": controller.system_log.view(100)},
                )
                return

            parsed = urlparse(self.path)

            if parsed.path == "/api/logs/export":
                format = parse_qs(parsed.query).get(
                    "format",
                    ["json"],
                )[0]

                try:
                    body = controller.system_log.render(format).encode()
                except ValueError as exc:
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": str(exc)},
                    )
                    return

                content_type = (
                    "text/csv"
                    if format == "csv"
                    else "application/json"
                )

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=vamc-logs.{format}",
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/api/config":
                if not self._authenticated():
                    return

                config = store.load()
                self._json(HTTPStatus.OK, {
                    "wifi_ssid": config.wifi_ssid,
                    "wake_word": config.wake_word,
                })
                return

            self._json(
                HTTPStatus.NOT_FOUND,
                {"error": "Not found"},
            )

        def do_POST(self) -> None:
            if self.path != "/api/config":
                self._json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "Not found"},
                )
                return

            if not self._authenticated():
                return

            try:
                payload = self._read_json()
                config = store.load()

                # Preserve the existing API key unless a new one is provided.
                updated = DashboardConfig(
                    wifi_ssid=str(
                        payload.get("wifi_ssid", config.wifi_ssid)
                    ),
                    wifi_password=str(
                        payload.get("wifi_password", config.wifi_password)
                    ),
                    wake_word=str(
                        payload.get("wake_word", config.wake_word)
                    ).strip(),
                    api_key=str(
                        payload.get("api_key", config.api_key)
                    ),
                )

                if not updated.wake_word:
                    raise ValueError("wake_word must not be empty")

                store.save(updated)

            except (ValueError, RuntimeError) as exc:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": str(exc)},
                )
                return

            self._json(HTTPStatus.OK, {"saved": True})

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


def serve(
    controller: VAMCController,
    config_path: str | os.PathLike[str],
    host: str = "127.0.0.1",
    port: int = 8080,
    dashboard_token: str | None = None,
    certfile: str | os.PathLike[str] | None = None,
    keyfile: str | os.PathLike[str] | None = None,
    limiter: LoginLimiter | None = None,
) -> ThreadingHTTPServer:
    store = ConfigStore(config_path)
    store.load()

    token = dashboard_token or os.environ.get("VAMC_DASHBOARD_TOKEN")

    if not token:
        raise ValueError(
            "dashboard_token or VAMC_DASHBOARD_TOKEN is required"
        )

    if bool(certfile) != bool(keyfile):
        raise ValueError("TLS needs both a certificate and a private key")

    if not certfile and not _is_loopback(host):
        # SR-002: never expose the dashboard over the network without TLS.
        raise ValueError(
            "TLS certificate and key are required when binding beyond localhost"
        )

    server = ThreadingHTTPServer(
        (host, port),
        make_handler(controller, store, token, limiter),
    )

    if certfile:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            certfile=certfile,
            keyfile=keyfile,
        )
        server.socket = context.wrap_socket(
            server.socket,
            server_side=True,
        )

    return server