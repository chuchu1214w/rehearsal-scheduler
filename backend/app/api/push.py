"""PWA 推送订阅:公钥、订阅、退订。任何登录用户都可以为自己的设备订阅。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from .. import push as push_module
from ..deps import DB, CurrentUser
from ..models import NativePushToken, PushSubscription
from ..push import upsert_native_token, upsert_subscription, vapid_keys
from ..schemas import NativeTokenIn, NativeTokenOut, PushPublicKeyOut, PushStatusOut, PushSubscribeIn, PushUnsubscribeIn

router = APIRouter(tags=["push"])


@router.get("/push/public-key", response_model=PushPublicKeyOut)
def public_key(db: DB, _user: CurrentUser) -> PushPublicKeyOut:
    _, public = vapid_keys(db)
    return PushPublicKeyOut(public_key=public)


@router.post("/push/subscribe", response_model=PushStatusOut)
def subscribe(body: PushSubscribeIn, request: Request, db: DB, user: CurrentUser) -> PushStatusOut:
    upsert_subscription(db, user.id, body.endpoint, body.keys.p256dh, body.keys.auth, request.headers.get("user-agent", ""))
    return status(db, user)


@router.post("/push/unsubscribe", response_model=PushStatusOut)
def unsubscribe(body: PushUnsubscribeIn, db: DB, user: CurrentUser) -> PushStatusOut:
    row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id))
    if row is not None:
        db.delete(row)
        db.commit()
    return status(db, user)


@router.get("/push/status", response_model=PushStatusOut)
def status(db: DB, user: CurrentUser) -> PushStatusOut:
    n = len(db.scalars(select(PushSubscription.id).where(PushSubscription.user_id == user.id)).all())
    m = len(db.scalars(select(NativePushToken.id).where(NativePushToken.user_id == user.id)).all())
    return PushStatusOut(devices=n, native=m, native_available=push_module.APNS is not None)


@router.post("/push/native", response_model=PushStatusOut)
def register_native(body: NativeTokenIn, db: DB, user: CurrentUser) -> PushStatusOut:
    upsert_native_token(db, user.id, body.platform, body.token)
    return status(db, user)


@router.post("/push/native/unregister", response_model=PushStatusOut)
def unregister_native(body: NativeTokenOut, db: DB, user: CurrentUser) -> PushStatusOut:
    row = db.scalar(select(NativePushToken).where(NativePushToken.token == body.token, NativePushToken.user_id == user.id))
    if row is not None:
        db.delete(row)
        db.commit()
    return status(db, user)
