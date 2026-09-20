"""AUTH-03 邀请链接(公开端点):查看邀请信息、接受邀请并创建账号。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select

from ..deps import DB, SettingsDep, create_session, set_session_cookie
from ..models import Invite, User
from ..schemas import InviteAcceptIn, InviteInfo, UserOut
from ..security import hash_password, token_hash
from ..services import serialize_user
from ..utils import utcnow

router = APIRouter(tags=["invites"])


def _load_invite(db, token: str) -> Invite:  # noqa: ANN001
    invite = db.scalar(select(Invite).where(Invite.token_hash == token_hash(token)))
    if invite is None:
        raise HTTPException(status_code=404, detail="邀请链接不存在")
    if invite.used_at is not None:
        raise HTTPException(status_code=410, detail="邀请链接已使用")
    if invite.expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="邀请链接已过期,请联系管理员重新生成")
    if invite.member.user is not None:
        raise HTTPException(status_code=410, detail="该成员已有账号")
    if not invite.member.active:
        raise HTTPException(status_code=410, detail="该成员已停用")
    return invite


@router.get("/invites/{token}", response_model=InviteInfo)
def invite_info(token: str, db: DB) -> InviteInfo:
    invite = _load_invite(db, token)
    return InviteInfo(member_name=invite.member.display_name, expires_at=invite.expires_at)


@router.post("/invites/{token}/accept", response_model=UserOut, status_code=201)
def accept_invite(token: str, body: InviteAcceptIn, db: DB, settings: SettingsDep, response: Response) -> UserOut:
    invite = _load_invite(db, token)
    exists = db.scalar(select(User).where(func.lower(User.username) == body.username.lower()))
    if exists is not None:
        raise HTTPException(status_code=409, detail="用户名已被使用")
    now = utcnow()
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role="member",
        member_id=invite.member_id,
        last_login_at=now,
    )
    db.add(user)
    db.flush()
    invite.used_at = now
    session_token = create_session(db, user, settings)
    db.commit()
    db.refresh(user)
    set_session_cookie(response, session_token, settings)
    return serialize_user(user)
