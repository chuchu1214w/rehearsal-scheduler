"""APNs(Apple 推送)直连:HTTP/2 + .p8 令牌认证(JWT ES256),不经 Firebase。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import jwt

PRODUCTION = "https://api.push.apple.com"
SANDBOX = "https://api.sandbox.push.apple.com"


@dataclass
class ApnsConfig:
    key_pem: str
    key_id: str
    team_id: str
    topic: str  # Bundle ID
    sandbox: bool = False

    @classmethod
    def from_settings(cls, settings) -> ApnsConfig | None:  # noqa: ANN001
        pem = settings.apns_key_p8 or (
            Path(settings.apns_key_path).read_text() if settings.apns_key_path and Path(settings.apns_key_path).exists() else ""
        )
        if not (pem and settings.apns_key_id and settings.apple_team_id and settings.ios_bundle_id):
            return None
        return cls(
            key_pem=pem.replace("\\n", "\n"),
            key_id=settings.apns_key_id,
            team_id=settings.apple_team_id,
            topic=settings.ios_bundle_id,
            sandbox=settings.apns_sandbox,
        )


_jwt_cache: dict[str, Any] = {}
_lock = threading.Lock()


def provider_token(cfg: ApnsConfig, now: float | None = None) -> str:
    """Apple 要求令牌 20–60 分钟刷新一次;这里 50 分钟。"""
    now = now or time.time()
    with _lock:
        cached = _jwt_cache.get(cfg.key_id)
        if cached and now - cached["iat"] < 50 * 60:
            return cached["jwt"]
        token = jwt.encode({"iss": cfg.team_id, "iat": int(now)}, cfg.key_pem, algorithm="ES256", headers={"kid": cfg.key_id})
        _jwt_cache[cfg.key_id] = {"jwt": token, "iat": now}
        return token


def apns_payload(title: str, body: str, link: str, tag: str = "") -> dict:
    """Capacitor 的 pushNotificationActionPerformed 事件里 notification.data 就是整个 userInfo,所以 link 放顶层。"""
    payload: dict[str, Any] = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}, "link": link}
    if tag:
        payload["aps"]["thread-id"] = tag.split(":")[0]
    return payload


def _deliver(cfg: ApnsConfig, tokens: list[str], payload: dict, transport: httpx.BaseTransport | None = None) -> list[str]:
    """逐个设备发送;返回已失效(410 Unregistered / 400 BadDeviceToken)的 token。"""
    dead: list[str] = []
    headers = {
        "authorization": f"bearer {provider_token(cfg)}",
        "apns-topic": cfg.topic,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-expiration": str(int(time.time()) + 6 * 3600),
    }
    base = SANDBOX if cfg.sandbox else PRODUCTION
    with httpx.Client(http2=True, base_url=base, timeout=10.0, transport=transport) as client:
        for token in tokens:
            try:
                r = client.post(f"/3/device/{token}", json=payload, headers=headers)
            except httpx.HTTPError:
                continue
            if r.status_code == 410 or (r.status_code == 400 and "BadDeviceToken" in r.text):
                dead.append(token)
    return dead


DELIVER: Callable[[ApnsConfig, list[str], dict], list[str]] = _deliver
