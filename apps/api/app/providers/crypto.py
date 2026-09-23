"""Credential encryption at rest (Fernet, key derived from server secret).

Secrets are encrypted before INSERT and only decrypted inside provider calls.
The API never returns full credentials — only masked previews + status.
"""
from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    secret = get_settings().jwt_secret.encode("utf-8")
    digest = hashlib.sha256(b"seo-provider-vault:" + secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(creds: dict) -> str:
    return _fernet().encrypt(json.dumps(creds).encode("utf-8")).decode("ascii")


def decrypt_credentials(blob: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(blob.encode("ascii")).decode("utf-8"))
    except (InvalidToken, ValueError) as exc:
        raise ValueError("cannot decrypt provider credentials") from exc


def mask_credentials(creds: dict) -> dict:
    """Masked preview safe for API responses (first/last chars only)."""
    out = {}
    for k, v in creds.items():
        s = str(v or "")
        if len(s) <= 4:
            out[k] = "****" if s else ""
        else:
            out[k] = f"{s[:2]}****{s[-2:]}"
    return out
