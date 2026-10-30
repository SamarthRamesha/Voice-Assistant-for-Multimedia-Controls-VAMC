
"""Signed over-the-air updates (SR-004).

An update consists of a package file plus a detached Ed25519 signature.
The device ships with the *public* key only; the private key stays with the
maintainers. An update is installed only if its signature verifies.
"""
from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class UpdateRejected(Exception):
    """Raised when an update is unsigned, tampered with, or signed by an unknown key."""


def generate_keypair() -> tuple[bytes, bytes]:
    """Return ``(private_pem, public_pem)``. Run once by the maintainers."""
    private = Ed25519PrivateKey.generate()

    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return private_pem, public_pem


def sign_package(package: bytes, private_pem: bytes) -> bytes:
    """Maintainer-side: create a detached signature for an update package."""
    key = serialization.load_pem_private_key(
        private_pem,
        password=None,
    )

    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Signing key must be an Ed25519 private key")

    return key.sign(package)


def verify_package(
    package: bytes,
    signature: bytes | None,
    public_pem: bytes,
) -> None:
    """Raise :class:`UpdateRejected` unless ``signature`` is valid for ``package``."""
    if not signature:
        raise UpdateRejected("Update is unsigned")

    try:
        key = serialization.load_pem_public_key(public_pem)
    except ValueError as exc:
        raise UpdateRejected("Trusted public key is invalid") from exc

    if not isinstance(key, Ed25519PublicKey):
        raise UpdateRejected("Trusted public key must be an Ed25519 key")

    try:
        key.verify(signature, package)
    except InvalidSignature as exc:
        raise UpdateRejected(
            "Update signature is invalid (package tampered or wrong key)"
        ) from exc


def _stage_update(
    package_data: bytes,
    package_name: str,
    destination: str | os.PathLike[str],
) -> Path:
    """Stage the exact verified package bytes for installation."""
    target_dir = Path(destination)
    target_dir.mkdir(parents=True, exist_ok=True)

    staged = target_dir / package_name
    staged.write_bytes(package_data)

    return staged


def install_update(
    package_path: str | os.PathLike[str],
    signature_path: str | os.PathLike[str],
    public_key_path: str | os.PathLike[str],
    installer: Callable[[Path], object] | None = None,
    staging_dir: str | os.PathLike[str] = "updates",
) -> Path:
    """Verify an update before staging it or handing it to an installer.

    The package is read once. The exact bytes that pass signature verification
    are written to the staging directory, and the installer receives that
    staged file rather than the original package path.

    By default, a verified package is staged into ``staging_dir``.
    Pass a custom ``installer`` to apply the staged package.
    """
    package = Path(package_path)
    data = package.read_bytes()

    signature_file = Path(signature_path)
    signature = (
        signature_file.read_bytes()
        if signature_file.exists()
        else None
    )

    public_key = Path(public_key_path).read_bytes()

    # Reject unsigned or invalid updates before staging or installation.
    verify_package(data, signature, public_key)

    # Stage the exact bytes that were verified.
    staged = _stage_update(data, package.name, staging_dir)

    if installer is not None:
        return installer(staged)  # type: ignore[return-value]

    return staged
