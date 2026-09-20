"""演出:列表 / 新建(可带人员)/ 设置 / 复制;参与人员;批量开通账号;求解前检查。成员只能读取自己参加的演出。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import DB, AdminUser, CurrentUser, SettingsDep
from ..models import Event, EventMember, Member, Song, User
from ..schemas import (
    AccountCredentialsOut,
    BatchAccountsIn,
    EventCloneIn,
    EventIn,
    EventMemberOut,
    EventMembersAddIn,
    EventMembersIn,
    EventOut,
    EventPatch,
    PrecheckOut,
)
from ..services import (
    default_deadline,
    event_settings,
    precheck,
    serialize_event,
    serialize_event_members,
    validate_event,
)
from .members import check_name_conflicts, create_account, find_member_by_name

router = APIRouter(tags=["events"])


def load_event(db: Session, event_id: int, user: User) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="演出不存在")
    if user.role != "admin":
        if user.member_id is None or not any(p.member_id == user.member_id for p in event.participants):
            raise HTTPException(status_code=403, detail="你不是该演出的参与人员")
    return event


def _resolve_member_ids(db: Session, member_ids: list[int]) -> dict[int, Member]:
    wanted = list(dict.fromkeys(member_ids))
    found = {m.id: m for m in db.scalars(select(Member).where(Member.id.in_(wanted))).all()} if wanted else {}
    missing = [i for i in wanted if i not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"成员不存在:{missing}")
    return found


@router.get("/events", response_model=list[EventOut])
def list_events(db: DB, user: CurrentUser) -> list[EventOut]:
    stmt = select(Event).order_by(Event.performance_date.desc(), Event.id.desc())
    if user.role != "admin":
        if user.member_id is None:
            return []
        stmt = stmt.join(EventMember, EventMember.event_id == Event.id).where(EventMember.member_id == user.member_id)
    return [serialize_event(e) for e in db.scalars(stmt).all()]


@router.post("/events", response_model=EventOut, status_code=201)
def create_event(body: EventIn, db: DB, admin: AdminUser) -> EventOut:
    validate_event(
        performance_date=body.performance_date,
        formal_start_date=body.formal_start_date,
        day_start_hour=body.day_start_hour,
        day_end_hour=body.day_end_hour,
        settings=body.settings,
    )
    members = _resolve_member_ids(db, body.member_ids)
    event = Event(
        name=body.name,
        performance_date=body.performance_date,
        formal_start_date=body.formal_start_date,
        availability_deadline=body.availability_deadline or default_deadline(body.performance_date),
        timezone=body.timezone,
        slot_minutes=body.slot_minutes,
        day_start_hour=body.day_start_hour,
        day_end_hour=body.day_end_hour,
        settings=body.settings.model_dump(),
        created_by=admin.id,
    )
    db.add(event)
    db.flush()
    for mid in members:
        db.add(EventMember(event_id=event.id, member_id=mid))
    db.commit()
    db.refresh(event)
    return serialize_event(event)


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: int, db: DB, user: CurrentUser) -> EventOut:
    return serialize_event(load_event(db, event_id, user))


@router.patch("/events/{event_id}", response_model=EventOut)
def update_event(event_id: int, body: EventPatch, db: DB, admin: AdminUser) -> EventOut:
    event = load_event(db, event_id, admin)
    settings = body.settings if body.settings is not None else event_settings(event)
    performance_date = body.performance_date or event.performance_date
    formal_start_date = body.formal_start_date or event.formal_start_date
    day_start = body.day_start_hour if body.day_start_hour is not None else event.day_start_hour
    day_end = body.day_end_hour if body.day_end_hour is not None else event.day_end_hour
    validate_event(
        performance_date=performance_date,
        formal_start_date=formal_start_date,
        day_start_hour=day_start,
        day_end_hour=day_end,
        settings=settings,
    )
    if body.name is not None:
        event.name = body.name
    event.performance_date = performance_date
    event.formal_start_date = formal_start_date
    if body.clear_availability_deadline:
        event.availability_deadline = None
    elif body.availability_deadline is not None:
        event.availability_deadline = body.availability_deadline
    if body.timezone is not None:
        event.timezone = body.timezone
    event.day_start_hour = day_start
    event.day_end_hour = day_end
    if body.status is not None:
        event.status = body.status
    if body.settings is not None:
        event.settings = body.settings.model_dump()
    db.commit()
    return serialize_event(event)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: DB, admin: AdminUser) -> None:
    event = load_event(db, event_id, admin)
    db.delete(event)
    db.commit()


@router.post("/events/{event_id}/clone", response_model=EventOut, status_code=201)
def clone_event(event_id: int, body: EventCloneIn, db: DB, admin: AdminUser) -> EventOut:
    """复制人员、曲目、规则,日期重新设置;不带空闲数据与排练表。"""
    source = load_event(db, event_id, admin)
    settings = event_settings(source)
    validate_event(
        performance_date=body.performance_date,
        formal_start_date=body.formal_start_date,
        day_start_hour=source.day_start_hour,
        day_end_hour=source.day_end_hour,
        settings=settings,
    )
    event = Event(
        name=body.name,
        performance_date=body.performance_date,
        formal_start_date=body.formal_start_date,
        availability_deadline=default_deadline(body.performance_date),
        timezone=source.timezone,
        slot_minutes=source.slot_minutes,
        day_start_hour=source.day_start_hour,
        day_end_hour=source.day_end_hour,
        settings=settings.model_dump(),
        created_by=admin.id,
    )
    db.add(event)
    db.flush()
    for p in source.participants:
        db.add(EventMember(event_id=event.id, member_id=p.member_id))
    for s in source.songs:
        song = Song(
            event_id=event.id,
            code=s.code,
            name=s.name,
            difficulty=s.difficulty,
            session_plan=list(s.session_plan) if s.session_plan else None,
            sort_order=s.sort_order,
        )
        song.members = list(s.members)
        db.add(song)
    db.commit()
    db.refresh(event)
    return serialize_event(event)


# ---------- 参与人员 ----------
@router.get("/events/{event_id}/members", response_model=list[EventMemberOut])
def list_event_members(event_id: int, db: DB, user: CurrentUser) -> list[EventMemberOut]:
    return serialize_event_members(load_event(db, event_id, user))


def _blocking_songs(event: Event, removed: set[int]) -> list[str]:
    return [f"{m.display_name}({s.code})" for s in event.songs for m in s.members if m.id in removed]


@router.put("/events/{event_id}/members", response_model=list[EventMemberOut])
def set_event_members(event_id: int, body: EventMembersIn, db: DB, admin: AdminUser) -> list[EventMemberOut]:
    event = load_event(db, event_id, admin)
    found = _resolve_member_ids(db, body.member_ids)
    current = {p.member_id: p for p in event.participants}
    removed = {mid for mid in current if mid not in found}
    blocking = _blocking_songs(event, removed)
    if blocking:
        raise HTTPException(status_code=409, detail="以下人员仍在曲目中,请先从曲目移除:" + "、".join(blocking))
    for mid in removed:
        db.delete(current[mid])
    for mid in found:
        if mid not in current:
            db.add(EventMember(event_id=event.id, member_id=mid))
    db.commit()
    db.refresh(event)
    return serialize_event_members(event)


@router.post("/events/{event_id}/members", response_model=list[EventMemberOut], status_code=201)
def add_event_members(event_id: int, body: EventMembersAddIn, db: DB, admin: AdminUser) -> list[EventMemberOut]:
    """按昵称添加:名册里已有同名(或别名)的直接关联,没有的自动创建。"""
    event = load_event(db, event_id, admin)
    current = {p.member_id for p in event.participants}
    max_order = db.scalar(select(func.max(Member.sort_order))) or 0
    for name in body.names:
        member = find_member_by_name(db, name)
        if member is None:
            check_name_conflicts(db, name, [], None)
            max_order += 1
            member = Member(display_name=name, aliases=[], sort_order=max_order)
            db.add(member)
            db.flush()
        if member.id not in current:
            db.add(EventMember(event_id=event.id, member_id=member.id))
            current.add(member.id)
    db.commit()
    db.refresh(event)
    return serialize_event_members(event)


@router.delete("/events/{event_id}/members/{member_id}", status_code=204)
def remove_event_member(event_id: int, member_id: int, db: DB, admin: AdminUser) -> None:
    event = load_event(db, event_id, admin)
    row = next((p for p in event.participants if p.member_id == member_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="该成员不在本演出中")
    blocking = _blocking_songs(event, {member_id})
    if blocking:
        raise HTTPException(status_code=409, detail="该成员仍在曲目中,请先从曲目移除:" + "、".join(blocking))
    db.delete(row)
    db.commit()


@router.post("/events/{event_id}/accounts", response_model=list[AccountCredentialsOut], status_code=201)
def open_accounts(event_id: int, body: BatchAccountsIn, db: DB, _admin: AdminUser, settings: SettingsDep) -> list[AccountCredentialsOut]:
    """为本演出所有未开通账号的人员一次开通,统一初始密码。"""
    event = load_event(db, event_id, _admin)
    out: list[AccountCredentialsOut] = []
    for p in sorted(event.participants, key=lambda p: (p.member.sort_order, p.member.id)):
        if p.member.user is None and p.member.active:
            out.append(create_account(db, settings, p.member, None, body.password))
    db.commit()
    return out


@router.post("/events/{event_id}/precheck", response_model=PrecheckOut)
def run_precheck(event_id: int, db: DB, admin: AdminUser) -> PrecheckOut:
    return precheck(load_event(db, event_id, admin))
