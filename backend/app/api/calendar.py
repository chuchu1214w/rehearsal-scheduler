"""日历订阅(CAL-01~03):每个账号一个私密令牌,`/cal/{token}.ics` 输出已发布排练表;成员只含自己的场次。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from ..deps import DB, CurrentUser, SettingsDep
from ..models import Event, RehearsalSession, User
from ..schemas import CalendarOut
from ..services import published_version

router = APIRouter(tags=["calendar"])  # 挂在 /api 下
public_router = APIRouter(tags=["calendar"])  # 不带 /api 前缀,凭令牌访问


def _ensure_token(db, user: User) -> str:  # noqa: ANN001
    if not user.calendar_token:
        user.calendar_token = secrets.token_urlsafe(24)
        db.commit()
    return user.calendar_token


def _calendar_out(token: str, base_url: str) -> CalendarOut:
    url = f"{base_url}/cal/{token}.ics"
    return CalendarOut(url=url, webcal_url="webcal://" + url.split("://", 1)[1])


@router.get("/me/calendar", response_model=CalendarOut)
def my_calendar(db: DB, user: CurrentUser, settings: SettingsDep) -> CalendarOut:
    return _calendar_out(_ensure_token(db, user), settings.public_base_url)


@router.post("/me/calendar/rotate", response_model=CalendarOut)
def rotate_calendar(db: DB, user: CurrentUser, settings: SettingsDep) -> CalendarOut:
    user.calendar_token = secrets.token_urlsafe(24)
    db.commit()
    return _calendar_out(user.calendar_token, settings.public_base_url)


# ---------- ICS ----------
def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", r"\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545:每行不超过 75 字节,续行以空格开头(空格也计入 75 字节);按字符切,不会切开多字节字符。"""
    out: list[str] = []
    cur, cur_len, limit = "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if cur_len + n > limit:
            out.append(cur)
            cur, cur_len, limit = ch, n, 74
        else:
            cur += ch
            cur_len += n
    out.append(cur)
    return "\r\n ".join(out)


def _utc(d: datetime) -> str:
    return d.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")


def _session_events(event: Event, sessions: list[RehearsalSession], member_id: int | None) -> list[list[str]]:
    tz = ZoneInfo(event.timezone or "Asia/Seoul")
    names = {p.member_id: p.member.display_name for p in event.participants}
    out: list[list[str]] = []
    for s in sessions:
        start_slot, duration = s.start_slot, s.duration_slots
        if s.kind == "evaluation":
            if member_id is not None and s.attendance and str(member_id) in s.attendance:
                a, b = s.attendance[str(member_id)]
                start_slot, duration = int(a), int(b) - int(a)
            summary = f"全员评估 · {event.name}"
            people = "、".join(names[p.member_id] for p in sorted(event.participants, key=lambda p: (p.member.sort_order, p.member_id)))
        else:
            if s.song is None:
                continue
            if member_id is not None and (member_id not in {m.id for m in s.song.members} or member_id in (s.absent_member_ids or [])):
                continue
            summary = f"排练 {s.song.code} · {s.song.name}"
            absent = set(s.absent_member_ids or [])
            people = "、".join(m.display_name + ("(缺席)" if m.id in absent else "") for m in s.song.members)
        start = datetime.combine(s.date, datetime.min.time(), tzinfo=tz) + timedelta(hours=event.day_start_hour + start_slot)
        end = start + timedelta(hours=duration)
        out.append(
            [
                "BEGIN:VEVENT",
                f"UID:rs-{event.id}-{s.id}@season",
                f"DTSTAMP:{_utc(datetime.now(tz))}",
                f"DTSTART:{_utc(start)}",
                f"DTEND:{_utc(end)}",
                f"SUMMARY:{_esc(summary)}",
                f"DESCRIPTION:{_esc('人员:' + people)}",
                "BEGIN:VALARM",
                "TRIGGER:-PT60M",
                "ACTION:DISPLAY",
                "DESCRIPTION:排练提醒",
                "END:VALARM",
                "END:VEVENT",
            ]
        )
    return out


def build_ics(events: list[Event], member_id: int | None, calendar_name: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Season//Rehearsal Scheduler//ZH",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(calendar_name)}",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for event in events:
        version = published_version(event)
        if version is None:
            continue
        for block in _session_events(event, list(version.sessions), member_id):
            lines.extend(block)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


@public_router.get("/cal/{token}.ics", include_in_schema=False)
def ics_feed(token: str, db: DB) -> Response:
    user = db.scalar(select(User).where(User.calendar_token == token, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(status_code=404, detail="订阅链接无效")
    events = list(db.scalars(select(Event).order_by(Event.performance_date)).all())
    if user.role != "admin":
        events = [e for e in events if any(p.member_id == user.member_id for p in e.participants)]
        name = f"Season 排练 · {user.member.display_name if user.member else user.username}"
    else:
        name = "Season 排练(全部)"
    body = build_ics(events, None if user.role == "admin" else user.member_id, name)
    return Response(
        content=body, media_type="text/calendar; charset=utf-8", headers={"Content-Disposition": 'inline; filename="season.ics"'}
    )
