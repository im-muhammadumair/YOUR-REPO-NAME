"""Reversible encryption for account passwords at rest.

Passwords are never stored as plaintext in the database. Instead each password
is encrypted with a symmetric key (Fernet) before it is written, so a leaked
database yields only ciphertext. The key is a stable secret loaded from the
``CREDENTIALS_KEY`` environment variable or from a key file created once under
the backend folder (``.credentials.key``).

Because admins are allowed to view the credentials they manage, the ciphertext
is *reversible*: the admin account endpoints decrypt before returning a
password, and login decrypts the stored value before comparing it.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

from config import BASE_DIR, CREDENTIALS_KEY

PREFIX = "fcd1$"


def _load_key() -> bytes:
    """Return the Fernet key used to encrypt stored credentials.

    Reads ``CREDENTIALS_KEY`` from the environment first; otherwise loads (or
    creates) a key file under the backend folder so restarts keep working. A
    random per-process key would make every stored password unreadable on the
    next start.
    """
    env_value = (CREDENTIALS_KEY or "").strip()
    if env_value:
        return env_value.encode()

    key_path = BASE_DIR / ".credentials.key"
    if key_path.exists():
        return key_path.read_bytes().strip()

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


_internal_key = None


def _cipher():
    global _internal_key
    if _internal_key is None:
        _internal_key = Fernet(_load_key())
    return _internal_key


def is_encrypted(value) -> bool:
    """Return True when ``value`` is a stored credential ciphertext."""
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt_password(plaintext: str | None) -> str:
    """Encrypt a plaintext password for storage.

    Passing already-encrypted text returns it unchanged, so the resolver and
    sync helpers can run repeatedly without double-encrypting.
    """
    if plaintext is None:
        return ""
    if is_encrypted(plaintext):
        return plaintext
    token = _cipher().encrypt((plaintext or "").encode("utf-8"))
    return f"{PREFIX}{token.decode('ascii')}"


def decrypt_password(token: str | None):
    """Return the plaintext behind a stored credential, or None on failure.

    Non-encrypted values are returned as-is for compatibility with any legacy
    plaintext that is still present before migration.
    """
    if token is None:
        return None
    if not is_encrypted(token):
        return token
    try:
        return _cipher().decrypt(token[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None