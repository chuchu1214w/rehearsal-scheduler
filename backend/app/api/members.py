"""名册(后台接口,前端没有独立页面)与账号:开通、重置密码、停用。全部仅管理员。"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..deps import DB, AdminUser, SettingsDep, revoke_all_sessions
from ..models import EventMember, Member, User, song_members
from ..notify import on_joined
from ..schemas import (
    AccountCreateIn,
    AccountCredentialsOut,
    AccountOut,
    AccountPatch,
    AccountResetIn,
    MemberIn,
    MemberOut,
    MemberPatch,
)
from ..security import hash_password
from ..services import serialize_account, serialize_member
from ..utils import USERNAME_RE, utcnow

router = APIRouter(tags=["members"])


def get_member(db: Session, member_id: int) -> Member:
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    return member


def check_name_conflicts(db: Session, display_name: str, aliases: list[str], exclude_id: int | None) -> None:
    names = {display_name, *aliases}
    for other in db.scalars(select(Member)).all():
        if other.id == exclude_id:
            continue
        clash = names & {other.display_name, *(other.aliases or [])}
        if clash:
            raise HTTPException(status_code=409, detail=f"名称「{'、'.join(sorted(clash))}」已被成员 {other.display_name} 使用")


def find_member_by_name(db: Session, name: str) -> Member | None:
    for m in db.scalars(select(Member)).all():
        if m.display_name == name or name in (m.aliases or []):
            return m
    return None


# ---------- 名册 ----------
@router.get("/members", response_model=list[MemberOut])
def list_members(db: DB, _admin: AdminUser) -> list[MemberOut]:
    rows = db.scalars(select(Member).order_by(Member.sort_order, Member.id)).all()
    return [serialize_member(m) for m in rows]


@router.post("/members", response_model=MemberOut, status_code=201)
def create_member(body: MemberIn, db: DB, _admin: AdminUser) -> MemberOut:
    aliases = [a for a in body.aliases if a != body.display_name]
    check_name_conflicts(db, body.display_name, aliases, None)
    max_order = db.scalar(select(func.max(Member.sort_order))) or 0
    member = Member(display_name=body.display_name, aliases=aliases, note=body.note, active=body.active, sort_order=max_order + 1)
    db.add(member)
    db.commit()
    return serialize_member(member)


@router.patch("/members/{member_id}", response_model=MemberOut)
def update_member(member_id: int, body: MemberPatch, db: DB, _admin: AdminUser) -> MemberOut:
    member = get_member(db, member_id)
    display_name = body.display_name if body.display_name is not None else member.display_name
    aliases = body.aliases if body.aliases is not None else list(member.aliases or [])
    aliases = [a for a in aliases if a != display_name]
    check_name_conflicts(db, display_name, aliases, member.id)
    member.display_name = display_name
    member.aliases = aliases
    if body.note is not None:
        member.note = body.note
    if body.active is not None:
        member.active = body.active
    if body.sort_order is not None:
        member.sort_order = body.sort_order
    db.commit()
    return serialize_member(member)


@router.delete("/members/{member_id}", status_code=204)
def delete_member(member_id: int, db: DB, _admin: AdminUser) -> None:
    member = get_member(db, member_id)
    if member.user is not None:
        raise HTTPException(status_code=409, detail="该成员已有账号,请改为停用")
    in_events = db.scalar(select(func.count()).select_from(EventMember).where(EventMember.member_id == member.id)) or 0
    in_songs = db.scalar(select(func.count()).select_from(song_members).where(song_members.c.member_id == member.id)) or 0
    if in_events or in_songs:
        raise HTTPException(status_code=409, detail="该成员已参加演出或曲目,请改为停用")
    db.delete(member)
    db.commit()


# ---------- 账号 ----------
def _username_taken(db: Session, username: str, exclude_user_id: int | None = None) -> bool:
    row = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    return row is not None and row.id != exclude_user_id


def suggest_username(db: Session, member: Member) -> str:
    base = (re.sub(r"[^A-Za-z0-9_.\-一-鿿]", "", member.display_name) or f"member{member.id}")[:28]
    candidate = base
    n = 2
    while _username_taken(db, candidate):
        candidate = f"{base}{n}"
        n += 1
    return candidate


def credentials(settings: Settings, member: Member, user: User, password: str) -> AccountCredentialsOut:
    text = f"{settings.public_base_url}\n用户名:{user.username}\n密码:{password}\n登录后请在「账号」页修改密码。"
    return AccountCredentialsOut(
        member_id=member.id, display_name=member.display_name, username=user.username, password=password, copy_text=text
    )


def create_account(db: Session, settings: Settings, member: Member, username: str | None, password: str) -> AccountCredentialsOut:
    if member.user is not None:
        raise HTTPException(status_code=409, detail=f"{member.display_name} 已有账号")
    if not member.active:
        raise HTTPException(status_code=409, detail=f"{member.display_name} 已停用,请先启用")
    if username:
        if not USERNAME_RE.match(username):
            raise HTTPException(status_code=422, detail="用户名只能包含中英文、数字、下划线、点和短横线,长度 2–32")
        if _username_taken(db, username):
            raise HTTPException(status_code=409, detail=f"用户名 {username} 已被使用")
    else:
        username = suggest_username(db, member)
    user = User(
        username=username,
        password_hash=hash_password(password),
        role="member",
        member_id=member.id,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    member.user = user
    return credentials(settings, member, user, password)


@router.post("/members/{member_id}/account", response_model=AccountCredentialsOut, status_code=201)
def open_account(member_id: int, body: AccountCreateIn, db: DB, _admin: AdminUser, settings: SettingsDep) -> AccountCredentialsOut:
    member = get_member(db, member_id)
    out = create_account(db, settings, member, body.username, body.password)
    db.flush()
    for p in db.scalars(select(EventMember).where(EventMember.member_id == member.id)).all():
        on_joined(db, p.event, [p])
    db.commit()
    return out


@router.post("/members/{member_id}/account/reset", response_model=AccountCredentialsOut)
def reset_password(member_id: int, body: AccountResetIn, db: DB, admin: AdminUser, settings: SettingsDep) -> AccountCredentialsOut:
    member = get_member(db, member_id)
    user = member.user
    if user is None:
        raise HTTPException(status_code=404, detail="该成员没有账号")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="请在「账号」页修改自己的密码")
    user.password_hash = hash_password(body.password)
    user.password_changed_at = utcnow()
    user.must_change_password = True
    revoke_all_sessions(db, user)
    db.commit()
    return credentials(settings, member, user, body.password)


@router.patch("/members/{member_id}/account", response_model=AccountOut)
def update_account(member_id: int, body: AccountPatch, db: DB, admin: AdminUser) -> AccountOut:
    member = get_member(db, member_id)
    user = member.user
    if user is None:
        raise HTTPException(status_code=404, detail="该成员没有账号")
    if user.id == admin.id and not body.is_active:
        raise HTTPException(status_code=400, detail="不能停用自己的账号")
    user.is_active = body.is_active
    if not body.is_active:
        revoke_all_sessions(db, user)
    db.commit()
    out = serialize_account(user)
    assert out is not None
    return out
