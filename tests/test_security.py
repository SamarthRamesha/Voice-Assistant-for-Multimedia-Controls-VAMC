"""Tests for SR-002 (TLS), SR-003 (encryption at rest), SR-004 (signed OTA), SR-005 (lockout)."""

from http.client import HTTPConnection, HTTPSConnection
import json
import os
import shutil
import ssl
import subprocess
from threading import Thread

import pytest

from vamc.controller import VAMCController
from vamc.dashboard import ConfigStore, DashboardConfig, serve
from vamc.feedback import MemoryFeedback
from vamc.media import MockMediaController
from vamc.ota import (
    UpdateRejected,
    generate_keypair,
    install_update,
    sign_package,
    verify_package,
)
from vamc.security import LoginLimiter, SecretBox, load_or_create_key


def make_controller():
    return VAMCController(MockMediaController(), MemoryFeedback())


def start(server):
    Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop(server):
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------- SR-003 (TC-Sec-03)


def test_sr003_wifi_password_is_not_stored_in_plaintext(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.save(
        DashboardConfig(
            wifi_ssid="home",
            wifi_password="hunter2-wifi",
            wake_word="computer",
        )
    )

    raw = path.read_text()
    assert "hunter2-wifi" not in raw
    assert json.loads(raw)["wifi_password"].startswith("enc:")


def test_sr003_encrypted_password_round_trips(tmp_path):
    path = tmp_path / "config.json"
    ConfigStore(path).save(
        DashboardConfig("home", "hunter2-wifi", "computer")
    )

    assert ConfigStore(path).load().wifi_password == "hunter2-wifi"


def test_sr003_api_key_is_encrypted_and_round_trips(tmp_path):
    path = tmp_path / "config.json"
    api_key = "test-secret-api-key-123"

    config = DashboardConfig(
        wifi_ssid="home",
        wifi_password="hunter2-wifi",
        wake_word="computer",
        api_key=api_key,
    )

    ConfigStore(path).save(config)

    raw = path.read_text()
    stored = json.loads(raw)

    assert api_key not in raw
    assert stored["api_key"].startswith("enc:")

    loaded = ConfigStore(path).load()
    assert loaded.api_key == api_key


def test_sr003_wrong_key_cannot_read_secret(tmp_path):
    path = tmp_path / "config.json"
    ConfigStore(path).save(
        DashboardConfig("home", "hunter2-wifi", "computer")
    )

    other = ConfigStore(
        path,
        SecretBox(load_or_create_key(tmp_path / "other.key")),
    )

    with pytest.raises(RuntimeError):
        other.load()


def test_sr003_legacy_plaintext_config_still_loads(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({
            "wifi_ssid": "s",
            "wifi_password": "old",
            "wake_word": "computer",
        })
    )

    store = ConfigStore(path)
    config = store.load()

    assert config.wifi_password == "old"

    store.save(config)

    saved = json.loads(path.read_text())
    assert "old" not in path.read_text()
    assert saved["wifi_password"].startswith("enc:")


@pytest.mark.skipif(
    os.name == "nt",
    reason="Unix file permission bits are not enforced on Windows",
)
def test_sr003_key_file_is_owner_only(tmp_path):
    key_path = tmp_path / "x.key"
    load_or_create_key(key_path)

    assert key_path.stat().st_mode & 0o077 == 0


# ---------------------------------------------------------------- SR-005 (TC-Sec-05)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_sr005_limiter_blocks_after_five_failures_for_five_minutes():
    clock = FakeClock()
    limiter = LoginLimiter(clock=clock)

    for _ in range(4):
        limiter.record_failure("1.2.3.4")
        assert limiter.retry_after("1.2.3.4") == 0

    limiter.record_failure("1.2.3.4")

    assert limiter.retry_after("1.2.3.4") == pytest.approx(300)

    clock.now += 299
    assert limiter.retry_after("1.2.3.4") > 0

    clock.now += 2
    assert limiter.retry_after("1.2.3.4") == 0


def test_sr005_success_resets_failure_count_and_clients_are_independent():
    limiter = LoginLimiter(clock=FakeClock())

    for _ in range(4):
        limiter.record_failure("a")

    limiter.record_success("a")
    limiter.record_failure("a")

    assert limiter.retry_after("a") == 0

    for _ in range(5):
        limiter.record_failure("b")

    assert limiter.retry_after("b") > 0
    assert limiter.retry_after("a") == 0


def test_sr005_dashboard_blocks_sixth_attempt_even_with_correct_token(tmp_path):
    clock = FakeClock()

    server = start(
        serve(
            make_controller(),
            tmp_path / "c.json",
            port=0,
            dashboard_token="good",
            limiter=LoginLimiter(clock=clock),
        )
    )

    connection = HTTPConnection("127.0.0.1", server.server_port)

    try:
        for _ in range(5):
            connection.request(
                "GET",
                "/api/config",
                headers={"Authorization": "Bearer wrong"},
            )
            response = connection.getresponse()
            response.read()
            assert response.status == 401

        connection.request(
            "GET",
            "/api/config",
            headers={"Authorization": "Bearer good"},
        )
        response = connection.getresponse()
        response.read()

        assert response.status == 429
        assert int(response.getheader("Retry-After")) > 0

        clock.now += 301

        connection.request(
            "GET",
            "/api/config",
            headers={"Authorization": "Bearer good"},
        )
        response = connection.getresponse()
        response.read()

        assert response.status == 200

    finally:
        connection.close()
        stop(server)


# ---------------------------------------------------------------- SR-004 (TC-Sec-04)


@pytest.fixture
def keys():
    return generate_keypair()


def test_sr004_valid_signature_is_accepted(keys):
    private, public = keys
    package = b"vamc-update-v2"

    verify_package(package, sign_package(package, private), public)


def test_sr004_tampered_package_is_rejected(keys):
    private, public = keys
    signature = sign_package(b"vamc-update-v2", private)

    with pytest.raises(UpdateRejected):
        verify_package(b"vamc-update-v2-EVIL", signature, public)


def test_sr004_unsigned_package_is_rejected(keys):
    with pytest.raises(UpdateRejected):
        verify_package(b"vamc-update-v2", None, keys[1])

    with pytest.raises(UpdateRejected):
        verify_package(b"vamc-update-v2", b"", keys[1])


def test_sr004_package_signed_by_unknown_key_is_rejected(keys):
    attacker_private, _ = generate_keypair()
    package = b"vamc-update-v2"

    with pytest.raises(UpdateRejected):
        verify_package(
            package,
            sign_package(package, attacker_private),
            keys[1],
        )


def test_sr004_install_only_runs_after_verification(tmp_path, keys):
    private, public = keys

    (tmp_path / "pub.pem").write_bytes(public)
    package = tmp_path / "update.bin"
    package.write_bytes(b"new-version")

    installed = []

    # An unsigned update must not reach the installer.
    with pytest.raises(UpdateRejected):
        install_update(
            package,
            tmp_path / "update.bin.sig",
            tmp_path / "pub.pem",
            installer=installed.append,
        )

    assert installed == []

    # Sign the package with the trusted private key.
    (tmp_path / "update.bin.sig").write_bytes(
        sign_package(b"new-version", private)
    )

    install_update(
        package,
        tmp_path / "update.bin.sig",
        tmp_path / "pub.pem",
        installer=installed.append,
        staging_dir=tmp_path / "updates",
    )

    # The installer must receive a separate staged copy containing
    # the exact bytes that passed signature verification.
    assert len(installed) == 1
    assert installed[0].read_bytes() == b"new-version"
    assert installed[0] != package

    # A tampered package must be rejected and not reach the installer.
    package.write_bytes(b"new-version-tampered")

    with pytest.raises(UpdateRejected):
        install_update(
            package,
            tmp_path / "update.bin.sig",
            tmp_path / "pub.pem",
            installer=installed.append,
            staging_dir=tmp_path / "updates",
        )

    assert len(installed) == 1


def test_sr004_default_install_stages_verified_package(tmp_path, keys):
    private, public = keys

    (tmp_path / "pub.pem").write_bytes(public)

    package = tmp_path / "update.bin"
    package.write_bytes(b"new-version")

    (tmp_path / "update.bin.sig").write_bytes(
        sign_package(b"new-version", private)
    )

    staged = install_update(
        package,
        tmp_path / "update.bin.sig",
        tmp_path / "pub.pem",
        staging_dir=tmp_path / "updates",
    )

    assert staged.read_bytes() == b"new-version"
    assert staged != package


# ---------------------------------------------------------------- SR-002 (TC-Sec-02)


def test_sr002_non_localhost_requires_tls(tmp_path):
    with pytest.raises(ValueError, match="TLS"):
        serve(
            make_controller(),
            tmp_path / "c.json",
            host="0.0.0.0",
            port=0,
            dashboard_token="t",
        )


def test_sr002_cert_without_key_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        serve(
            make_controller(),
            tmp_path / "c.json",
            port=0,
            dashboard_token="t",
            certfile="x.pem",
        )


@pytest.mark.skipif(
    shutil.which("openssl") is None,
    reason="openssl not installed",
)
def test_sr002_dashboard_serves_https_and_rejects_plain_http(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"

    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-nodes", "-days", "1", "-subj", "/CN=localhost",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
    )

    server = start(
        serve(
            make_controller(),
            tmp_path / "c.json",
            host="0.0.0.0",
            port=0,
            dashboard_token="t",
            certfile=cert,
            keyfile=key,
        )
    )

    try:
        context = ssl.create_default_context(cafile=str(cert))

        secure = HTTPSConnection(
            "localhost",
            server.server_port,
            context=context,
            timeout=5,
        )

        secure.request("GET", "/api/status")
        response = secure.getresponse()

        assert response.status == 200
        assert json.loads(response.read())["connection_status"] == "connected"

        secure.close()

        plain = HTTPConnection(
            "127.0.0.1",
            server.server_port,
            timeout=5,
        )

        with pytest.raises(Exception):
            plain.request("GET", "/api/status")
            plain.getresponse().read()

        plain.close()

    finally:
        stop(server)