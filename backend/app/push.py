"""Web Push(PWA 推送):VAPID 密钥自动生成并存在 meta 表;发送在后台线程进行,失效的订阅自动清理。"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import Meta, PushSubscription
from .utils import utcnow

_VAPID_CACHE: dict[str, str] = {}
_LOCK = threading.Lock()
CONTACT = "mailto:season@example.com"  # 由 create_app 按 settings.push_contact 覆盖
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
    """给这些用户的所有订阅推送 payload(title / body / link / tag)。返回订阅数。"""
    if not user_ids:
        return 0
    rows = db.scalars(select(PushSubscription).where(PushSubscription.user_id.in_(user_ids))).all()
    if not rows:
        return 0
    private_pem, _ = vapid_keys(db)
    contact = contact or CONTACT
    background = BACKGROUND if background is None else background
    subs = [{"endpoint": r.endpoint, "p256dh": r.p256dh, "auth": r.auth} for r in rows]
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    def run() -> None:
        dead = DELIVER(subs, payload, private_pem, contact)
        if dead:
            with factory() as d:
                for r in d.scalars(select(PushSubscription).where(PushSubscription.endpoint.in_(dead))).all():
                    d.delete(r)
                d.commit()

    if background:
        threading.Thread(target=run, daemon=True).start()
    else:
        run()
    return len(subs)


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
