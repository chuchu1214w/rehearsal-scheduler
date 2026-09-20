"""AUTH-02 登录 / 登出 / 当前用户;AUTH-05 修改密码。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, func, select

from ..deps import (
    DB,
    CurrentUser,
    SettingsDep,
    clear_session_cookie,
    create_session,
    revoke_all_sessions,
    set_session_cookie,
)
from ..models import AuthSession, LoginFailure, User
from ..schemas import LoginIn, PasswordChangeIn, UserOut
from ..security import hash_password, token_hash, verify_password
from ..services import serialize_user
from ..utils import utcnow

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=UserOut)
def login(body: LoginIn, db: DB, settings: SettingsDep, response: Response) -> UserOut:
    username_lower = body.username.strip().lower()
    now = utcnow()
    cutoff = now - timedelta(minutes=settings.login_window_minutes)
    db.execute(delete(LoginFailure).where(LoginFailure.at < cutoff))
    failures = db.scalar(
        select(func.count(LoginFailure.id)).where(LoginFailure.username_lower == username_lower, LoginFailure.at >= cutoff)
    )
    if failures and failures >= settings.login_max_failures:
        db.commit()
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多,请 {settings.login_window_minutes} 分钟后再试",
            headers={"Retry-After": str(settings.login_window_minutes * 60)},
        )
    user = db.scalar(select(User).where(func.lower(User.username) == username_lower))
    if user is None or not verify_password(user.password_hash, body.password):
        db.add(LoginFailure(username_lower=username_lower, at=now))
        db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用,请联系管理员")
    db.execute(delete(LoginFailure).where(LoginFailure.username_lower == username_lower))
    user.last_login_at = now
    token = create_session(db, user, settings)
    db.commit()
    set_session_cookie(response, token, settings)
    return serialize_user(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: DB, response: Response, _user: CurrentUser) -> Response:
    token = request.cookies.get("rs_session")
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        db.commit()
    clear_session_cookie(response)
    return Response(status_code=204, headers=response.headers)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return serialize_user(user)


@router.post("/me/password", status_code=204)
def change_password(body: PasswordChangeIn, request: Request, db: DB, user: CurrentUser) -> Response:
    if not verify_password(user.password_hash, body.old_password):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    # 其他设备的会话全部失效,当前会话保留
    revoke_all_sessions(db, user, keep_session_id=getattr(request.state, "session_id", None))
    db.commit()
    return Response(status_code=204)
