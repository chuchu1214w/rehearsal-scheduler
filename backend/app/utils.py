from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-一-鿿]{1,32}$")
TEMP_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def utcnow() -> datetime:
    """数据库统一存 UTC 的 naive datetime(SQLite 不保存时区)。"""
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def temp_password(length: int = 10) -> str:
    return "".join(secrets.choice(TEMP_PASSWORD_ALPHABET) for _ in range(length))


def normalize_name(value: str) -> str:
    return " ".join(value.split())
