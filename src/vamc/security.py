"""Security helpers for the VAMC dashboard.

SR-003  SecretBox      - encrypts secrets (Wi-Fi password, API keys) at rest.
SR-005  LoginLimiter   - locks out a client after repeated failed logins.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import Lock
from time import monotonic

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTED_PREFIX = "enc:"


# --------------------------------------------------------------------------
# SR-003: encryption at rest
# --------------------------------------------------------------------------
def load_or_create_key(path: str | os.PathLike[str]) -> bytes:
    """Return the encryption key stored at ``path``, creating it if needed.

    The key file is created readable only by the owner (mode 0600). Keep it
    out of version control (see .gitignore).
    """
    key_path = Path(path)
    if key_path.exists():
        return key_path.read_bytes().strip()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(key)
    return key


class SecretBox:
    """Encrypts and decrypts short secret strings with Fernet (AES-128-CBC + HMAC)."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        token = self._fernet.encrypt(plaintext.encode()).decode()
        return ENCRYPTED_PREFIX + token

    def decrypt(self, stored: str) -> str:
        if not stored:
            return ""
        if not stored.startswith(ENCRYPTED_PREFIX):
            # Legacy plaintext value from an older config file; it is
            # re-saved in encrypted form the next time the config is saved.
            return stored
        try:
            return self._fernet.decrypt(stored[len(ENCRYPTED_PREFIX):].encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Unable to decrypt stored secret: wrong key or corrupted data") from exc


# --------------------------------------------------------------------------
# SR-005: login lockout
# --------------------------------------------------------------------------
@dataclass
class LoginLimiter:
    """Blocks a client for ``lockout_seconds`` after ``max_failures`` consecutive failures."""

    max_failures: int = 5
    lockout_seconds: float = 300.0
    clock: Callable[[], float] = monotonic
    _failures: dict[str, int] = field(default_factory=dict, init=False)
    _locked_until: dict[str, float] = field(default_factory=dict, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def retry_after(self, client: str) -> float:
        """Seconds the client must still wait; 0 if it may try to log in."""
        with self._lock:
            until = self._locked_until.get(client)
            if until is None:
                return 0.0
            remaining = until - self.clock()
            if remaining > 0:
                return remaining
            # Lockout has expired: start again with a clean slate.
            del self._locked_until[client]
            self._failures.pop(client, None)
            return 0.0

    def record_failure(self, client: str) -> None:
        with self._lock:
            count = self._failures.get(client, 0) + 1
            self._failures[client] = count
            if count >= self.max_failures:
                self._locked_until[client] = self.clock() + self.lockout_seconds

    def record_success(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)
            self._locked_until.pop(client, None)
