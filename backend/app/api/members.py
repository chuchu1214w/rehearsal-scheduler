"""ROS-01 名册;AUTH-03 邀请链接;AUTH-04 重置密码 / 停用账号。全部仅管理员。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, func, select

from ..deps import DB, AdminUser, SettingsDep, revoke_all_sessions
from ..models import EventMember, Invite, Member, song_members
from ..schemas import AccountOut, AccountPatch, InviteOut, MemberIn, MemberOut, MemberPatch, TempPasswordOut
from ..security import hash_password, new_token, token_hash
from ..services import serialize_account, serialize_member
from ..utils import temp_password, utcnow

router = APIRouter(tags=["members"])


def _get_member(db, member_id: int) -> Member:  # noqa: ANN001
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    return member


def _check_name_conflicts(db, display_name: str, aliases: list[str], exclude_id: int | None) -> None:  # noqa: ANN001
    names = {display_name, *aliases}
    for other in db.scalars(select(Member)).all():
        if other.id == exclude_id:
            continue
        other_names = {other.display_name, *(other.aliases or [])}
        clash = names & other_names
        if clash:
            raise HTTPException(status_code=409, detail=f"名称「{'、'.join(sorted(clash))}」已被成员 {other.display_name} 使用")


@router.get("/members", response_model=list[MemberOut])
def list_members(db: DB, _admin: AdminUser) -> list[MemberOut]:
    rows = db.scalars(select(Member).order_by(Member.sort_order, Member.id)).all()
    return [serialize_member(m) for m in rows]


@router.post("/members", response_model=MemberOut, status_code=201)
def create_member(body: MemberIn, db: DB, _admin: AdminUser) -> MemberOut:
    aliases = [a for a in body.aliases if a != body.display_name]
    _check_name_conflicts(db, body.display_name, aliases, None)
    max_order = db.scalar(select(func.max(Member.sort_order))) or 0
    member = Member(display_name=body.display_name, aliases=aliases, note=body.note, active=body.active, sort_order=max_order + 1)
    db.add(member)
    db.commit()
    return serialize_member(member)


@router.patch("/members/{member_id}", response_model=MemberOut)
def update_member(member_id: int, body: MemberPatch, db: DB, _admin: AdminUser) -> MemberOut:
    member = _get_member(db, member_id)
    display_name = body.display_name if body.display_name is not None else member.display_name
    aliases = body.aliases if body.aliases is not None else list(member.aliases or [])
    aliases = [a for a in aliases if a != display_name]
    _check_name_conflicts(db, display_name, aliases, member.id)
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
    member = _get_member(db, member_id)
    if member.user is not None:
        raise HTTPException(status_code=409, detail="该成员已有账号,请改为停用")
    in_events = db.scalar(select(func.count()).select_from(EventMember).where(EventMember.member_id == member.id)) or 0
    in_songs = db.scalar(select(func.count()).select_from(song_members).where(song_members.c.member_id == member.id)) or 0
    if in_events or in_songs:
        raise HTTPException(status_code=409, detail="该成员已参加活动或曲目,请改为停用")
    db.execute(delete(Invite).where(Invite.member_id == member.id))
    db.delete(member)
    db.commit()


@router.post("/members/{member_id}/invite", response_model=InviteOut, status_code=201)
def create_invite(member_id: int, db: DB, admin: AdminUser, settings: SettingsDep) -> InviteOut:
    member = _get_member(db, member_id)
    if member.user is not None:
        raise HTTPException(status_code=409, detail="该成员已有账号")
    if not member.active:
        raise HTTPException(status_code=409, detail="该成员已停用,请先启用")
    # 旧的未使用邀请作废
    db.execute(delete(Invite).where(Invite.member_id == member.id, Invite.used_at.is_(None)))
    token = new_token()
    now = utcnow()
    expires = now + timedelta(days=settings.invite_days)
    db.add(Invite(token_hash=token_hash(token), member_id=member.id, created_by=admin.id, created_at=now, expires_at=expires))
    db.commit()
    return InviteOut(token=token, url=f"{settings.public_base_url}/invite/{token}", expires_at=expires)


@router.post("/members/{member_id}/reset-password", response_model=TempPasswordOut)
def reset_password(member_id: int, db: DB, _admin: AdminUser) -> TempPasswordOut:
    member = _get_member(db, member_id)
    user = member.user
    if user is None:
        raise HTTPException(status_code=404, detail="该成员没有账号")
    password = temp_password()
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    revoke_all_sessions(db, user)
    db.commit()
    return TempPasswordOut(username=user.username, temp_password=password)


@router.patch("/members/{member_id}/account", response_model=AccountOut)
def update_account(member_id: int, body: AccountPatch, db: DB, admin: AdminUser) -> AccountOut:
    member = _get_member(db, member_id)
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
