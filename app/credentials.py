"""Saved Google sign-in (Gmail + password) per profile, kept in the macOS Keychain
(or, on Windows/Linux, the OS credential store via `keyring`).

Nothing is written to the project folder: each profile is one generic-password item
(service SERVICE, account = profile name) whose secret is {"email", "password", "totp"} as
JSON. "totp" is the optional Google Authenticator setup key, used to answer 2-Step
Verification without a phone.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import struct
import subprocess
import sys
import time

SERVICE = "gemini_video_tool"

_has_cache: dict[str, bool] = {}  # the UI polls has() every few seconds


def _security(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["security", *args], capture_output=True, text=True)


def normalize_totp(key: str) -> str:
    """Authenticator setup key as Google shows it ("abcd efgh ...") -> base32, validated."""
    key = key.replace(" ", "").upper()
    base64.b32decode(key + "=" * (-len(key) % 8))  # raises binascii.Error if invalid
    return key


def totp_code(key: str, at: float | None = None) -> str:
    """Current 6-digit RFC 6238 code (SHA-1, 30 s), as Google Authenticator shows it."""
    raw = base64.b32decode(key + "=" * (-len(key) % 8))
    counter = int((time.time() if at is None else at) // 30)
    digest = hmac.new(raw, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _store_secret(name: str, secret: str) -> None:
    if sys.platform != "darwin":
        import keyring
        keyring.set_password(SERVICE, name, secret)
        return
    # -U updates the item if it already exists.
    r = _security("add-generic-password", "-U", "-s", SERVICE, "-a", name, "-w", secret)
    if r.returncode != 0:
        raise RuntimeError(f"could not save to Keychain: {r.stderr.strip()}")


def _load_secret(name: str) -> str | None:
    if sys.platform != "darwin":
        import keyring
        return keyring.get_password(SERVICE, name)
    r = _security("find-generic-password", "-s", SERVICE, "-a", name, "-w")
    return r.stdout.strip() if r.returncode == 0 else None


def _delete_secret(name: str) -> bool:
    if sys.platform != "darwin":
        import keyring
        from keyring.errors import PasswordDeleteError
        try:
            keyring.delete_password(SERVICE, name)
            return True
        except PasswordDeleteError:
            return False
    return _security("delete-generic-password", "-s", SERVICE, "-a", name).returncode == 0


def save(name: str, email: str, password: str, totp: str | None = None) -> None:
    _store_secret(name, json.dumps({"email": email, "password": password, "totp": totp or None}))
    _has_cache[name] = True


def get(name: str) -> dict | None:
    """{"email", "password"} for the profile, or None if nothing is saved."""
    raw = _load_secret(name)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if data.get("email") and data.get("password") else None


def has(name: str) -> bool:
    if name not in _has_cache:
        _has_cache[name] = _load_secret(name) is not None
    return _has_cache[name]


def delete(name: str) -> bool:
    _has_cache[name] = False
    return _delete_secret(name)
