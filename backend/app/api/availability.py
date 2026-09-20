"""空闲填报(交互设计 M2 / A5):成员填自己的,管理员可代填、看总览。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from ..deps import DB, AdminUser, CurrentUser
from ..models import AvailabilityDay, Event, EventMember, User
from ..schemas import AvailabilityIn, AvailabilityOut, HeatOut
from ..services import availability_index, blank_slots, event_config, heat
from ..utils import utcnow
from .events import load_event

router = APIRouter(tags=["availability"])


def _participant(event: Event, member_id: int) -> EventMember:
    row = next((p for p in event.participants if p.member_id == member_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="该成员不在本演出中")
    return row


def _authorize(event: Event, member_id: int, user: User) -> EventMember:
    if user.role != "admin" and user.member_id != member_id:
        raise HTTPException(status_code=403, detail="只能填写自己的空闲时间")
    return _participant(event, member_id)


def serialize_availability(event: Event, p: EventMember) -> AvailabilityOut:
    config = event_config(event)
    rows = availability_index(event).get(p.member_id, {})
    blank = blank_slots(event)
    days = {d.isoformat(): (rows[d].slots if d in rows else blank) for d in config.all_dates}
    filled_by = None
    if rows:
        filled_by = "admin" if any(r.filled_by == "admin" for r in rows.values()) else "member"
    today = date.today()
    return AvailabilityOut(
        event_id=event.id,
        member_id=p.member_id,
        display_name=p.member.display_name,
        dates=config.all_dates,
        eval_date=config.eval_date,
        slots_per_day=config.slots_per_day,
        day_start_hour=config.day_start_hour,
        days=days,
        filled_days=sum(1 for v in days.values() if set(v) != {"0"}),
        filled_by=filled_by,
        submitted_at=p.availability_submitted_at,
        deadline=event.availability_deadline,
        past_deadline=bool(event.availability_deadline and today > event.availability_deadline),
    )


@router.get("/events/{event_id}/availability/overview", response_model=HeatOut)
def availability_overview(event_id: int, db: DB, admin: AdminUser) -> HeatOut:
    return heat(load_event(db, event_id, admin))


@router.get("/events/{event_id}/availability/{member_id}", response_model=AvailabilityOut)
def get_availability(event_id: int, member_id: int, db: DB, user: CurrentUser) -> AvailabilityOut:
    event = load_event(db, event_id, user)
    return serialize_availability(event, _authorize(event, member_id, user))


def _apply(db: Session, event: Event, p: EventMember, body: AvailabilityIn, user: User) -> None:
    config = event_config(event)
    valid = {d.isoformat(): d for d in config.all_dates}
    filled_by = "admin" if user.role == "admin" and user.member_id != p.member_id else "member"
    index = availability_index(event).get(p.member_id, {})
    for key, value in body.days.items():
        if key not in valid:
            raise HTTPException(status_code=422, detail=f"日期 {key} 不在本演出的排练区间内")
        if len(value) != config.slots_per_day or any(ch not in "012" for ch in value):
            raise HTTPException(status_code=422, detail=f"{key} 的格子数应为 {config.slots_per_day},每格只能是 0 / 1 / 2")
        d = valid[key]
        row = index.get(d)
        if row is None:
            db.add(AvailabilityDay(event_id=event.id, member_id=p.member_id, date=d, slots=value, filled_by=filled_by))
        else:
            row.slots = value
            row.filled_by = filled_by
    if body.submit:
        p.availability_submitted_at = utcnow()


@router.put("/events/{event_id}/availability/{member_id}", response_model=AvailabilityOut)
def put_availability(event_id: int, member_id: int, body: AvailabilityIn, db: DB, user: CurrentUser) -> AvailabilityOut:
    event = load_event(db, event_id, user)
    p = _authorize(event, member_id, user)
    _apply(db, event, p, body, user)
    db.commit()
    db.refresh(event)
    return serialize_availability(event, _participant(event, member_id))


@router.post("/events/{event_id}/availability/{member_id}/submit", response_model=AvailabilityOut)
def submit_availability(event_id: int, member_id: int, db: DB, user: CurrentUser) -> AvailabilityOut:
    event = load_event(db, event_id, user)
    p = _authorize(event, member_id, user)
    p.availability_submitted_at = utcnow()
    db.commit()
    db.refresh(event)
    return serialize_availability(event, _participant(event, member_id))


@router.post("/events/{event_id}/availability/{member_id}/unsubmit", response_model=AvailabilityOut)
def unsubmit_availability(event_id: int, member_id: int, db: DB, user: CurrentUser) -> AvailabilityOut:
    event = load_event(db, event_id, user)
    p = _authorize(event, member_id, user)
    p.availability_submitted_at = None
    db.commit()
    db.refresh(event)
    return serialize_availability(event, _participant(event, member_id))
