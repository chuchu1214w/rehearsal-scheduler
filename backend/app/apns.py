"""APNs(Apple 推送)直连:HTTP/2 + .p8 令牌认证(JWT ES256),不经 Firebase。

环境:TestFlight / App Store 包拿到的是生产环境 token,Xcode 直装的 Debug 包拿到的是沙箱 token。
每个 token 记住自己的环境(native_push_tokens.env);未知时先试默认环境,收到 BadDeviceToken 再试另一个。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jwt

log = logging.getLogger("season.apns")

PRODUCTION = "https://api.push.apple.com"
SANDBOX = "https://api.sandbox.push.apple.com"
HOSTS = {"production": PRODUCTION, "sandbox": SANDBOX}


@dataclass
class ApnsConfig:
    key_pem: str
    key_id: str
    team_id: str
    topic: str  # Bundle ID
    sandbox: bool = False  # 未知环境的 token 先试哪个

    @property
    def default_env(self) -> str:
        return "sandbox" if self.sandbox else "production"

    @classmethod
    def from_settings(cls, settings) -> ApnsConfig | None:  # noqa: ANN001
        pem = settings.apns_key_p8 or (
            Path(settings.apns_key_path).read_text() if settings.apns_key_path and Path(settings.apns_key_path).exists() else ""
        )
        if not (pem and settings.apns_key_id and settings.apple_team_id and settings.ios_bundle_id):
            return None
        cfg = cls(
            key_pem=pem.replace("\\n", "\n"),
            key_id=settings.apns_key_id,
            team_id=settings.apple_team_id,
            topic=settings.ios_bundle_id,
            sandbox=settings.apns_sandbox,
        )
        try:
            provider_token(cfg)  # 启动时就校验密钥,配错立即在日志里看到
        except Exception:  # noqa: BLE001
            log.exception("APNs 密钥无效(APNS_KEY_P8 / APNS_KEY_ID),原生推送已停用")
            return None
        return cfg


@dataclass
class DeliveryResult:
    dead: list[str] = field(default_factory=list)  # 已失效,应删除
    env: dict[str, str] = field(default_factory=dict)  # 投递成功的 token → 实际环境


_jwt_cache: dict[str, Any] = {}
_lock = threading.Lock()


def provider_token(cfg: ApnsConfig, now: float | None = None, *, refresh: bool = False) -> str:
    """Apple 要求令牌 20–60 分钟刷新一次;这里 50 分钟。refresh=True 时强制重签(收到 ExpiredProviderToken 后)。"""
    now = now or time.time()
    with _lock:
        cached = _jwt_cache.get(cfg.key_id)
        if cached and not refresh and now - cached["iat"] < 50 * 60:
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


def collapse_id(tag: str) -> str | None:
    """同一件事(如同一场的地点更新)的多次推送在通知中心里替换而不是堆叠;APNs 限 64 字节。"""
    if not tag or tag.endswith(":"):
        return None
    return tag.encode("utf-8")[:64].decode("utf-8", "ignore")


def _reason(r: httpx.Response) -> str:
    try:
        return str(r.json().get("reason", ""))
    except ValueError:
        return ""


def _deliver(
    cfg: ApnsConfig,
    tokens: list[tuple[str, str | None]],
    payload: dict,
    collapse: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> DeliveryResult:
    """逐个设备发送。tokens 为 (token, 已知环境或 None)。"""
    result = DeliveryResult()
    clients: dict[str, httpx.Client] = {}

    def client(env: str) -> httpx.Client:
        if env not in clients:
            clients[env] = httpx.Client(http2=True, base_url=HOSTS[env], timeout=10.0, transport=transport)
        return clients[env]

    def headers(refresh: bool = False) -> dict[str, str]:
        h = {
            "authorization": f"bearer {provider_token(cfg, refresh=refresh)}",
            "apns-topic": cfg.topic,
            "apns-push-type": "alert",
            "apns-priority": "10",
            "apns-expiration": str(int(time.time()) + 6 * 3600),
        }
        if collapse:
            h["apns-collapse-id"] = collapse
        return h

    def post(env: str, token: str) -> httpx.Response | None:
        try:
            r = client(env).post(f"/3/device/{token}", json=payload, headers=headers())
            if r.status_code == 403 and _reason(r) in ("ExpiredProviderToken", "InvalidProviderToken"):
                r = client(env).post(f"/3/device/{token}", json=payload, headers=headers(refresh=True))
            return r
        except httpx.HTTPError as exc:
            log.warning("APNs 请求失败(%s):%s", env, exc)
            return None

    try:
        for token, known in tokens:
            envs = [known] if known in HOSTS else [cfg.default_env, "sandbox" if cfg.default_env == "production" else "production"]
            outcome = "dead"
            for env in envs:
                r = post(env, token)
                if r is None:
                    outcome = "error"
                    break
                if r.status_code == 200:
                    result.env[token] = env
                    outcome = "ok"
                    break
                reason = _reason(r)
                if r.status_code == 410:
                    break  # Unregistered:App 已删除或关闭了通知
                if r.status_code == 400 and reason in ("BadDeviceToken", "DeviceTokenNotForTopic"):
                    continue  # 可能是另一个环境的 token
                log.error("APNs 返回 %s %s(环境 %s,topic %s)", r.status_code, reason or r.text[:200], env, cfg.topic)
                outcome = "error"
                break
            if outcome == "dead":
                result.dead.append(token)
    finally:
        for c in clients.values():
            c.close()
    return result


DELIVER: Callable[..., DeliveryResult] = _deliver
