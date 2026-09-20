"""序列化与业务校验;把数据库对象转换为响应模型,并复用求解包的参数校验。"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException

from solver.types import EventConfig

from .models import Event, Member, Song, User
from .schemas import (
    AccountOut,
    EventMemberOut,
    EventOut,
    EventSettings,
    MemberBrief,
    MemberOut,
    SongOut,
    UserOut,
)


def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        member_id=user.member_id,
        member_name=user.member.display_name if user.member else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def serialize_account(user: User | None) -> AccountOut | None:
    if user is None:
        return None
    return AccountOut(user_id=user.id, username=user.username, is_active=user.is_active, last_login_at=user.last_login_at)


def serialize_member(member: Member) -> MemberOut:
    return MemberOut(
        id=member.id,
        display_name=member.display_name,
        aliases=list(member.aliases or []),
        note=member.note or "",
        active=member.active,
        sort_order=member.sort_order,
        account=serialize_account(member.user),
    )


def event_settings(event: Event) -> EventSettings:
    return EventSettings(**(event.settings or {}))


def build_config(
    *,
    performance_date: date,
    formal_start_date: date,
    day_start_hour: int,
    day_end_hour: int,
    settings: EventSettings,
) -> EventConfig:
    """构造求解包的 EventConfig;其 __post_init__ 会做日期与参数的一致性校验。"""
    return EventConfig(
        performance_date=performance_date,
        formal_start_date=formal_start_date,
        day_start_hour=day_start_hour,
        day_end_hour=day_end_hour,
        soft_daily_limit=settings.soft_daily_limit,
        hard_daily_limit=settings.hard_daily_limit,
        merge_visit_gap=settings.merge_visit_gap,
        free_gap=settings.free_gap,
        eval_durations=tuple(settings.eval_durations),
        eval_min_contiguous=settings.eval_min_contiguous,
        same_song_different_days=settings.same_song_different_days,
        difficulty_templates={k: tuple(v) for k, v in settings.difficulty_templates.items()},
        stage_time_limit=settings.stage_time_limit,
    )


def validate_event(
    *, performance_date: date, formal_start_date: date, day_start_hour: int, day_end_hour: int, settings: EventSettings
) -> EventConfig:
    try:
        return build_config(
            performance_date=performance_date,
            formal_start_date=formal_start_date,
            day_start_hour=day_start_hour,
            day_end_hour=day_end_hour,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def event_config(event: Event) -> EventConfig:
    return build_config(
        performance_date=event.performance_date,
        formal_start_date=event.formal_start_date,
        day_start_hour=event.day_start_hour,
        day_end_hour=event.day_end_hour,
        settings=event_settings(event),
    )


def song_durations(song: Song, settings: EventSettings) -> list[int]:
    if song.session_plan:
        return list(song.session_plan)
    return list(settings.difficulty_templates.get(song.difficulty, []))


def serialize_song(song: Song, settings: EventSettings) -> SongOut:
    durations = song_durations(song, settings)
    return SongOut(
        id=song.id,
        event_id=song.event_id,
        code=song.code,
        name=song.name,
        difficulty=song.difficulty,  # type: ignore[arg-type]
        members=[MemberBrief(id=m.id, display_name=m.display_name) for m in song.members],
        session_plan=list(song.session_plan) if song.session_plan else None,
        durations=durations,
        session_count=len(durations),
        sort_order=song.sort_order,
    )


def song_warnings(event: Event) -> list[str]:
    """SONG-03:成员集合完全相同的曲目给出警告(不阻止)。"""
    seen: dict[frozenset[int], Song] = {}
    warnings: list[str] = []
    for song in event.songs:
        key = frozenset(m.id for m in song.members)
        if key in seen:
            warnings.append(f"曲目 {song.code}({song.name})与 {seen[key].code}({seen[key].name})的参演成员完全相同")
        else:
            seen[key] = song
    return warnings


def serialize_event(event: Event) -> EventOut:
    settings = event_settings(event)
    formal_end = event.performance_date - timedelta(days=2)
    return EventOut(
        id=event.id,
        name=event.name,
        performance_date=event.performance_date,
        formal_start_date=event.formal_start_date,
        formal_end_date=formal_end,
        eval_date=event.performance_date - timedelta(days=1),
        formal_day_count=max(0, (formal_end - event.formal_start_date).days + 1),
        timezone=event.timezone,
        slot_minutes=event.slot_minutes,
        day_start_hour=event.day_start_hour,
        day_end_hour=event.day_end_hour,
        slots_per_day=event.day_end_hour - event.day_start_hour,
        status=event.status,  # type: ignore[arg-type]
        settings=settings,
        member_count=len(event.participants),
        song_count=len(event.songs),
        session_count=sum(len(song_durations(s, settings)) for s in event.songs),
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def serialize_event_members(event: Event) -> list[EventMemberOut]:
    rows = sorted(event.participants, key=lambda p: (p.member.sort_order, p.member.id))
    return [
        EventMemberOut(
            member_id=p.member_id,
            display_name=p.member.display_name,
            active=p.member.active,
            availability_submitted_at=p.availability_submitted_at,
        )
        for p in rows
    ]


def next_song_code(event: Event) -> str:
    used = {s.code.lower() for s in event.songs}
    for i in range(26):
        code = chr(ord("a") + i)
        if code not in used:
            return code
    n = 1
    while f"s{n}" in used:
        n += 1
    return f"s{n}"
