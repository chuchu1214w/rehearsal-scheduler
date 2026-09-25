"""AUTH-01 首次启动向导:数据库为空时创建第一个管理员,创建后入口永久关闭。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select

from ..deps import DB, SettingsDep, create_session, set_session_cookie
from ..models import User
from ..schemas import LoginOut, SetupIn, SetupStatus
from ..security import hash_password
from ..services import serialize_user
from ..utils import utcnow

router = APIRouter(tags=["setup"])


def _user_count(db) -> int:  # noqa: ANN001
    return int(db.scalar(select(func.count(User.id))) or 0)


@router.get("/setup/status", response_model=SetupStatus)
def setup_status(db: DB) -> SetupStatus:
    return SetupStatus(needs_setup=_user_count(db) == 0)


@router.post("/setup", response_model=LoginOut, status_code=201)
def run_setup(body: SetupIn, request: Request, db: DB, settings: SettingsDep, response: Response) -> LoginOut:
    if _user_count(db) > 0:
        raise HTTPException(status_code=404, detail="系统已初始化")
    now = utcnow()
    user = User(username=body.username, password_hash=hash_password(body.password), role="admin", last_login_at=now)
    db.add(user)
    db.flush()
    token = create_session(db, user, settings)
    db.commit()
    set_session_cookie(response, token, settings)
    out = LoginOut(**serialize_user(user).model_dump())
    if request.headers.get("x-client", "").lower() == "native":
        out.token = token
    return out
