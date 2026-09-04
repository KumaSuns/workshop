from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from app.paths import DATA_DIR

_AUTH_PATH = DATA_DIR / "auth.json"
PASSWORD = "9090"


def load_or_create_password() -> str:
    save_password(PASSWORD)
    return PASSWORD


def save_password(password: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_hex(16)
    digest = _digest(password, salt)
    _AUTH_PATH.write_text(
        json.dumps(
            {"password": password, "salt": salt, "hash": digest},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def password_ok(password: str) -> bool:
    if not _AUTH_PATH.exists():
        return False
    payload = json.loads(_AUTH_PATH.read_text(encoding="utf-8"))
    salt = str(payload.get("salt") or "")
    stored = str(payload.get("hash") or "")
    if not salt or not stored:
        return hmac.compare_digest(str(payload.get("password") or ""), password)
    return hmac.compare_digest(stored, _digest(password, salt))


def _digest(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def new_session() -> str:
    return secrets.token_urlsafe(32)
