"""Web Push(PWA 推送):VAPID 密钥自动生成并存在 meta 表;发送在后台线程进行,失效的订阅自动清理。"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import apns
from .models import Meta, NativePushToken, PushSubscription
from .utils import utcnow

log = logging.getLogger("season.push")

_VAPID_CACHE: dict[str, str] = {}
_LOCK = threading.Lock()
CONTACT = "mailto:season@example.com"  # 由 create_app 按 settings.push_contact 覆盖
APNS: apns.ApnsConfig | None = None  # 由 create_app 按 settings 配置;None = 不发原生推送
BACKGROUND = True  # 测试时设为 False,同步投递


def vapid_keys(db: Session) -> tuple[str, str]:
    """返回 (私钥 PEM, 浏览器用的公钥 base64url)。第一次调用时生成并写入 meta。"""
    if "private" in _VAPID_CACHE:
        return _VAPID_CACHE["private"], _VAPID_CACHE["public"]
    with _LOCK:
        priv = db.scalar(select(Meta).where(Meta.key == "vapid_private_pem"))
        pub = db.scalar(select(Meta).where(Meta.key == "vapid_public_key"))
        if priv is None or pub is None:
            from cryptography.hazmat.primitives import serialization
            from py_vapid import Vapid, b64urlencode

            v = Vapid()
            v.generate_keys()
            pem = v.private_pem().decode() if isinstance(v.private_pem(), bytes) else v.private_pem()
            raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            public = b64urlencode(raw)
            for row in (priv, pub):
                if row is not None:
                    db.delete(row)
            db.add(Meta(key="vapid_private_pem", value=pem))
            db.add(Meta(key="vapid_public_key", value=public))
            db.commit()
            priv_value, pub_value = pem, public
        else:
            priv_value, pub_value = priv.value, pub.value
        _VAPID_CACHE["private"] = priv_value
        _VAPID_CACHE["public"] = pub_value
        return priv_value, pub_value


def reset_cache() -> None:
    _VAPID_CACHE.clear()


# 实际投递函数;测试里替换成桩
def _deliver(subs: list[dict[str, Any]], payload: dict, private_pem: str, contact: str) -> list[str]:
    """逐个订阅发送;返回已失效(404 / 410)的 endpoint 列表。"""
    from pywebpush import WebPushException, webpush

    dead: list[str] = []
    data = json.dumps(payload, ensure_ascii=False)
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=data,
                vapid_private_key=private_pem,
                vapid_claims={"sub": contact},
                ttl=6 * 3600,
            )
        except WebPushException as exc:  # noqa: PERF203
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                dead.append(sub["endpoint"])
        except Exception:  # noqa: BLE001
            continue
    return dead


DELIVER: Callable[[list[dict[str, Any]], dict, str, str], list[str]] = _deliver


def send_to_users(db: Session, user_ids: list[int], payload: dict, contact: str | None = None, *, background: bool | None = None) -> int:
    """给这些用户的所有设备推送 payload(title / body / link / tag):网页推送 + iOS 原生(APNs)。返回设备数。"""
    if not user_ids:
        return 0
    rows = list(db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))).all())
    native_rows = db.scalars(select(NativePushToken).where(NativePushToken.user_id.in_(user_ids))).all() if APNS is not None else []
    ios_tokens = [(r.token, r.env) for r in native_rows if r.platform == "ios"]
    # 装了 App 的人,iPhone 上的 Safari / 主屏幕网页推送就不再发,避免同一台手机弹两次
    has_app = {r.user_id for r in native_rows if r.platform == "ios"}
    rows = [r for r in rows if not (r.user_id in has_app and "web.push.apple.com" in r.endpoint)]
    if not rows and not ios_tokens:
        return 0
    private_pem = vapid_keys(db)[0] if rows else ""
    contact = contact or CONTACT
    background = BACKGROUND if background is None else background
    subs = [{"endpoint": r.endpoint, "p256dh": r.p256dh, "auth": r.auth} for r in rows]
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    cfg = APNS
    tag = payload.get("tag", "")

    def apply(d: Session, dead: list[str], native: apns.DeliveryResult) -> None:
        if dead:
            for r in d.scalars(select(PushSubscription).where(PushSubscription.endpoint.in_(dead))).all():
                d.delete(r)
        touched = set(native.dead) | set(native.env)
        if touched:
            for r in d.scalars(select(NativePushToken).where(NativePushToken.token.in_(touched))).all():
                if r.token in native.dead:
                    d.delete(r)
                elif r.env != native.env[r.token]:
                    r.env = native.env[r.token]

    def run(sync_db: Session | None = None) -> None:
        dead: list[str] = []
        native = apns.DeliveryResult()
        try:
            if subs:
                dead = DELIVER(subs, payload, private_pem, contact)
        except Exception:  # noqa: BLE001
            log.exception("网页推送失败")
        try:
            if cfg is not None and ios_tokens:
                native_payload = apns.apns_payload(payload.get("title", ""), payload.get("body", ""), payload.get("link", ""), tag)
                native = apns.DELIVER(cfg, ios_tokens, native_payload, apns.collapse_id(tag))
        except Exception:  # noqa: BLE001
            log.exception("APNs 推送失败")
        if not (dead or native.dead or native.env):
            return
        if sync_db is not None:  # 同步模式(测试):用请求自己的会话,由请求统一提交,避免 SQLite 写锁冲突
            apply(sync_db, dead, native)
            return
        try:
            with factory() as d:
                apply(d, dead, native)
                d.commit()
        except Exception:  # noqa: BLE001
            log.exception("清理失效推送设备失败")

    if background:
        threading.Thread(target=run, daemon=True).start()
    else:
        run(db)
    return len(subs) + len(ios_tokens)


def upsert_subscription(db: Session, user_id: int, endpoint: str, p256dh: str, auth: str, user_agent: str = "") -> PushSubscription:
    row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if row is None:
        row = PushSubscription(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=user_agent[:200])
        db.add(row)
    else:
        row.user_id = user_id
        row.p256dh = p256dh
        row.auth = auth
        row.user_agent = user_agent[:200]
        row.last_used_at = utcnow()
    db.commit()
    return row


def upsert_native_token(db: Session, user_id: int, platform: str, token: str) -> NativePushToken:
    row = db.scalar(select(NativePushToken).where(NativePushToken.token == token))
    if row is None:
        row = NativePushToken(user_id=user_id, platform=platform, token=token)
        db.add(row)
    else:
        row.user_id = user_id
        row.platform = platform
        row.last_seen_at = utcnow()
    db.commit()
    return row
