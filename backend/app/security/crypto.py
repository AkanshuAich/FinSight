"""Keyed tokenisation and the PII vault.

tok = HMAC-SHA256(key, normalised value). Deterministic, so transfer matching, dedup and idempotent IDs
work on tokens, but not reversible by brute force the way a plain hash of an account number would be.
Clear values live only in security.pii_vault, encrypted with Fernet (AES-128-CBC + HMAC).
Dev keys are generated into data/dev_keys.json; production would load them from a KMS.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import unicodedata
from datetime import datetime
from functools import lru_cache

from cryptography.fernet import Fernet

from ..config import KEYS_PATH


@lru_cache(maxsize=1)
def _keys() -> dict:
    env_h, env_f = os.environ.get("FINSIGHT_HMAC_KEY"), os.environ.get("FINSIGHT_FERNET_KEY")
    if env_h and env_f:
        return {"hmac": env_h, "fernet": env_f}
    if KEYS_PATH.exists():
        return json.loads(KEYS_PATH.read_text())
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    keys = {"hmac": base64.urlsafe_b64encode(os.urandom(32)).decode(), "fernet": Fernet.generate_key().decode()}
    KEYS_PATH.write_text(json.dumps(keys))
    return keys


def _fernet() -> Fernet:
    return Fernet(_keys()["fernet"].encode())


def normalise(value: str) -> str:
    """Case- and punctuation-insensitive form for matching identifiers and names in ANY script.
    Keeps letters, combining marks (Indic vowel signs) and digits; an ASCII-only filter would erase
    Devanagari, Gujarati and Tamil text and make different values share one token."""
    s = unicodedata.normalize("NFC", str(value)).upper()
    return "".join(ch for ch in s if unicodedata.category(ch)[0] in "LMN" or ch in "@.")


def token(value: str, kind: str = "v") -> str:
    # narrations ("d") are hashed exactly: two different narrations must never share a token
    basis = unicodedata.normalize("NFC", str(value)) if kind == "d" else normalise(value)
    digest = hmac.new(_keys()["hmac"].encode(), f"{kind}:{basis}".encode(), hashlib.sha256).hexdigest()
    return f"{kind}_{digest[:24]}"


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(blob: bytes) -> bytes:
    return _fernet().decrypt(bytes(blob))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix: str, *parts) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()[:20]}"


def vault_put(con, value: str, kind: str) -> str:
    """Store a clear value encrypted; returns its token. Idempotent on the token."""
    tok = token(value, kind) if kind != "desc" else stable_id("desc", token(value, "d"))
    con.execute("INSERT OR IGNORE INTO security.pii_vault VALUES (?, ?, ?, ?)",
                [tok, kind, encrypt(value.encode()), datetime.utcnow()])
    return tok


def vault_get(con, tok: str) -> str | None:
    row = con.execute("SELECT value_enc FROM security.pii_vault WHERE token = ?", [tok]).fetchone()
    return decrypt(row[0]).decode() if row else None
