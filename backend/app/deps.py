"""依赖注入:数据库会话、当前用户、管理员校验、会话 Cookie。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import AuthSession, User
from .security import new_token, token_hash
from .utils import utcnow

COOKIE_NAME = "rs_session"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


DB = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def optional_user(request: Request, db: DB, settings: SettingsDep) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    now = utcnow()
    if sess is None:
        return None
    if sess.expires_at <= now:
        db.delete(sess)
        db.commit()
        return None
    user = sess.user
    if user is None or not user.is_active:
        return None
    # 滑动续期:每小时最多写一次
    if now - sess.last_seen_at > timedelta(hours=1):
        sess.last_seen_at = now
        sess.expires_at = now + timedelta(days=settings.session_days)
        db.commit()
    request.state.session_id = sess.id
    return user


def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(admin_user)]


def create_session(db: Session, user: User, settings: Settings) -> str:
    token = new_token()
    now = utcnow()
    db.add(
        AuthSession(
            token_hash=token_hash(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=settings.session_days),
            last_seen_at=now,
        )
    )
    return token


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def revoke_all_sessions(db: Session, user: User, keep_session_id: int | None = None) -> None:
    for sess in list(user.sessions):
        if sess.id != keep_session_id:
            db.delete(sess)
