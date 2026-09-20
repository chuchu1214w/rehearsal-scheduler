"""序列化与业务逻辑:演出进度、成员、曲目、空闲、求解前检查;并把演出转换为求解包的 Problem。"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException

from solver.candidates import build_candidates, make_tasks
from solver.evaluation import diagnose_evaluation
from solver.types import Availability, EventConfig, Problem
from solver.types import Song as SolverSong

from .models import AvailabilityDay, Event, EventMember, Member, Song, User
from .rules import to_solver_rules
from .schemas import (
    AccountOut,
    EventMemberOut,
    EventOut,
    EventSettings,
    HeatOut,
    MemberBrief,
    MemberOut,
    PrecheckItem,
    PrecheckOut,
    SongOut,
    StepOut,
    UserOut,
)

STEPS = [
    ("info", "演出信息"),
    ("members", "人员"),
    ("songs", "曲目"),
    ("rules", "特殊要求"),
    ("availability", "填报"),
    ("solve", "排程"),
    ("schedule", "排练表"),
]


def fmt_md(d: date) -> str:
    return f"{d.month}/{d.day}"


# ---------- 账号 / 成员 ----------
def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        member_id=user.member_id,
        member_name=user.member.display_name if user.member else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def serialize_account(user: User | None) -> AccountOut | None:
    if user is None:
        return None
    return AccountOut(
        user_id=user.id,
        username=user.username,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
    )


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


# ---------- 演出参数 ----------
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


def default_deadline(performance_date: date) -> date:
    return performance_date - timedelta(days=10)


# ---------- 曲目 ----------
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
            warnings.append(f"曲目 {song.code}({song.name})与 {seen[key].code}({seen[key].name})的参演人员完全相同")
        else:
            seen[key] = song
    return warnings


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


# ---------- 空闲 ----------
def blank_slots(event: Event) -> str:
    return "0" * (event.day_end_hour - event.day_start_hour)


def availability_index(event: Event) -> dict[int, dict[date, AvailabilityDay]]:
    out: dict[int, dict[date, AvailabilityDay]] = {}
    for row in event.availability:
        out.setdefault(row.member_id, {})[row.date] = row
    return out


def sorted_participants(event: Event) -> list[EventMember]:
    return sorted(event.participants, key=lambda p: (p.member.sort_order, p.member.id))


# ---------- 进度 ----------
def event_steps(event: Event) -> tuple[int, list[StepOut], dict[str, int]]:
    settings = event_settings(event)
    participants = sorted_participants(event)
    n_members = len(participants)
    n_accounts = sum(1 for p in participants if p.member.user is not None)
    n_submitted = sum(1 for p in participants if p.availability_submitted_at is not None)
    n_songs = len(event.songs)
    n_sessions = sum(len(song_durations(s, settings)) for s in event.songs)
    n_rules = sum(1 for r in event.rules if r.enabled)
    formal_end = event.performance_date - timedelta(days=2)
    eval_date = event.performance_date - timedelta(days=1)

    deadline = f",截止 {fmt_md(event.availability_deadline)}" if event.availability_deadline else ""
    defs: list[tuple[bool, str]] = [
        (True, f"{fmt_md(event.formal_start_date)}–{fmt_md(formal_end)} 排练,{fmt_md(eval_date)} 全员评估"),
        (n_members > 0, f"{n_members} 人,已开通账号 {n_accounts} 人" if n_members else "还没有人员"),
        (n_songs > 0, f"{n_songs} 首 · {n_sessions} 场正规排练 + 1 场评估" if n_songs else "还没有曲目"),
        (n_songs > 0, f"{n_rules} 条要求" if n_rules else "没有特殊要求(可跳过)"),
        (n_members > 0 and n_submitted == n_members, f"已提交 {n_submitted} / {n_members}{deadline}"),
        (False, "未开始"),
        (False, "尚未生成"),
    ]
    steps: list[StepOut] = []
    current = 0
    for i, ((key, label), (done, summary)) in enumerate(zip(STEPS, defs, strict=True), start=1):
        if done and current == 0:
            state = "done"
        elif current == 0:
            state = "current"
            current = i
        else:
            state = "todo"
        steps.append(StepOut(no=i, key=key, label=label, state=state, summary=summary))  # type: ignore[arg-type]
    if current == 0:
        current = len(STEPS)
    counts = {
        "member_count": n_members,
        "account_count": n_accounts,
        "submitted_count": n_submitted,
        "song_count": n_songs,
        "session_count": n_sessions,
        "rule_count": n_rules,
    }
    return current, steps, counts


def serialize_event(event: Event) -> EventOut:
    settings = event_settings(event)
    formal_end = event.performance_date - timedelta(days=2)
    current, steps, counts = event_steps(event)
    return EventOut(
        id=event.id,
        name=event.name,
        performance_date=event.performance_date,
        formal_start_date=event.formal_start_date,
        formal_end_date=formal_end,
        eval_date=event.performance_date - timedelta(days=1),
        formal_day_count=max(0, (formal_end - event.formal_start_date).days + 1),
        availability_deadline=event.availability_deadline,
        days_until_performance=(event.performance_date - date.today()).days,
        timezone=event.timezone,
        slot_minutes=event.slot_minutes,
        day_start_hour=event.day_start_hour,
        day_end_hour=event.day_end_hour,
        slots_per_day=event.day_end_hour - event.day_start_hour,
        status=event.status,  # type: ignore[arg-type]
        settings=settings,
        current_step=current,
        steps=steps,
        created_at=event.created_at,
        updated_at=event.updated_at,
        **counts,
    )


def serialize_event_members(event: Event) -> list[EventMemberOut]:
    avail = availability_index(event)
    out: list[EventMemberOut] = []
    for p in sorted_participants(event):
        rows = avail.get(p.member_id, {})
        filled_by = None
        if rows:
            filled_by = "admin" if any(r.filled_by == "admin" for r in rows.values()) else "member"
        out.append(
            EventMemberOut(
                member_id=p.member_id,
                display_name=p.member.display_name,
                active=p.member.active,
                note=p.member.note or "",
                account=serialize_account(p.member.user),
                availability_submitted_at=p.availability_submitted_at,
                availability_filled_days=sum(1 for r in rows.values() if set(r.slots) != {"0"}),
                availability_filled_by=filled_by,
            )
        )
    return out


# ---------- 求解包桥接 ----------
def event_problem(event: Event, *, include_unsubmitted: bool = False) -> Problem:
    """把演出转换为求解包的 Problem。默认只用已提交的空闲,未提交者视为全天不可排。"""
    participants = sorted_participants(event)
    names = tuple(p.member.display_name for p in participants)
    avail = Availability()
    index = availability_index(event)
    for p in participants:
        if not include_unsubmitted and p.availability_submitted_at is None:
            continue
        for d, row in index.get(p.member_id, {}).items():
            avail.set_row(p.member.display_name, d, [int(ch) for ch in row.slots])
    songs = tuple(
        SolverSong(
            code=s.code,
            name=s.name,
            difficulty=s.difficulty,
            members=tuple(m.display_name for m in s.members),
            session_plan=tuple(s.session_plan) if s.session_plan else None,
        )
        for s in event.songs
    )
    return Problem(config=event_config(event), members=names, songs=songs, availability=avail, rules=to_solver_rules(event))


def heat(event: Event) -> HeatOut:
    config = event_config(event)
    participants = sorted_participants(event)
    submitted = [p for p in participants if p.availability_submitted_at is not None]
    index = availability_index(event)
    out: dict[str, list[int]] = {}
    for d in config.all_dates:
        counts = [0] * config.slots_per_day
        for p in submitted:
            row = index.get(p.member_id, {}).get(d)
            if row is None:
                continue
            for h, ch in enumerate(row.slots[: config.slots_per_day]):
                if ch in ("1", "2"):
                    counts[h] += 1
        out[d.isoformat()] = counts
    return HeatOut(
        dates=config.all_dates,
        slots_per_day=config.slots_per_day,
        day_start_hour=config.day_start_hour,
        member_count=len(participants),
        submitted_count=len(submitted),
        heat=out,
    )


def precheck(event: Event) -> PrecheckOut:
    """求解前检查(交互设计 A6):有 ✘ 仍可求解,但会提示。"""
    items: list[PrecheckItem] = []
    participants = sorted_participants(event)
    n_members = len(participants)
    missing = [p.member.display_name for p in participants if p.availability_submitted_at is None]
    settings = event_settings(event)
    n_sessions = sum(len(song_durations(s, settings)) for s in event.songs)
    n_rules = sum(1 for r in event.rules if r.enabled)

    def add(key: str, ok: bool, label: str, detail: str = "", level: str | None = None) -> None:
        items.append(PrecheckItem(key=key, ok=ok, level=level or ("ok" if ok else "warn"), label=label, detail=detail))  # type: ignore[arg-type]

    if n_members == 0:
        add("members", False, "还没有参与人员", level="error")
    if not event.songs:
        add("songs", False, "还没有曲目", level="error")
    else:
        add("songs", True, "每首曲目都有参演人员")
        add("plans", True, f"曲目排练次数与时长已设置({n_sessions} 场)")
    add("rules", True, f"{n_rules} 条特殊要求已启用" if n_rules else "没有特殊要求")
    if missing:
        add("submitted", False, f"{len(missing)} 位成员尚未提交空闲时间", "、".join(missing))
    elif n_members:
        add("submitted", True, "全员已提交空闲时间")

    if n_members and event.songs:
        problem = event_problem(event)
        errors, _ = problem.validate()
        if errors:
            add("problem", False, "数据有误", ";".join(errors), level="error")
        else:
            diag = diagnose_evaluation(problem, limit=1)
            if diag["可行窗口数"] > 0:
                add("evaluation", True, "评估日有全员共同空闲")
            else:
                best = diag["最接近的窗口"][0] if diag["最接近的窗口"] else None
                who = "、".join(best["阻塞成员"]) if best else ""
                short = f"差 {best['缺少人数']} 人" if best else "没有可用窗口"
                hint = "(未提交的成员按没空计算)" if missing else ""
                add("evaluation", False, f"评估日共同空闲不足:{short}{hint}", who)
            tasks = make_tasks(problem)
            cands = build_candidates(problem, tasks, allow_absent=False)
            zero = [t for t in tasks if not cands[t.task_id]]
            if zero:
                by_song: dict[str, int] = {}
                for t in zero:
                    by_song[t.song_code] = by_song.get(t.song_code, 0) + 1
                detail = "、".join(f"{code} 缺 {n} 场" for code, n in by_song.items())
                add("candidates", False, f"{len(zero)} 场排练没有任何全员共同时段", detail)
            else:
                add("candidates", True, "每场排练都有全员共同时段")

    errors = [i for i in items if i.level == "error"]
    warnings = [i for i in items if i.level == "warn"]
    return PrecheckOut(items=items, can_solve=not errors, warnings=len(warnings))
