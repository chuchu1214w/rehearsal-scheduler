"""序列化与业务逻辑:演出进度、成员、曲目、空闲、求解前检查;并把演出转换为求解包的 Problem。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException

from solver.candidates import build_candidates, make_tasks
from solver.evaluation import diagnose_evaluation
from solver.timegrid import weekday_zh
from solver.types import Availability, EventConfig, Problem
from solver.types import Song as SolverSong

from .models import AvailabilityDay, Event, EventMember, Member, RehearsalSession, ScheduleVersion, SolveJob, Song, User
from .rules import to_solver_rules
from .schemas import (
    AccountOut,
    EventMemberOut,
    EventOut,
    EventSettings,
    HeatOut,
    JobOut,
    MemberBrief,
    MemberOut,
    MemberStatOut,
    PrecheckItem,
    PrecheckOut,
    SessionOut,
    SongOut,
    StepOut,
    UserOut,
    VersionDetailOut,
    VersionOut,
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
    latest = event.versions[-1] if event.versions else None
    published = published_version(event)
    last_job = event.jobs[-1] if event.jobs else None

    if last_job is not None and last_job.status in ("queued", "running"):
        solve_summary = "求解中…"
    elif last_job is not None and last_job.status == "infeasible":
        solve_summary = f"上次无解:{last_job.summary}" if last_job.summary else "上次求解无解"
    elif last_job is not None and last_job.status == "failed":
        solve_summary = "上次求解失败,可重试"
    elif latest is not None:
        solve_summary = f"已生成草稿 v{latest.version_no}"
    else:
        solve_summary = "未开始"
    from .schedule_edit import conflict_count  # 局部导入,避免循环引用

    conflicts = conflict_count(event, published)
    if published is not None:
        schedule_summary = (
            f"已发布 v{published.version_no}"
            + (f" · 草稿 v{latest.version_no}" if latest and latest.status == "draft" else "")
            + (f" · {conflicts} 场与最新空闲冲突" if conflicts else "")
        )
    elif latest is not None:
        schedule_summary = f"草稿 v{latest.version_no}(未发布)"
    else:
        schedule_summary = "尚未生成"

    deadline = f",截止 {fmt_md(event.availability_deadline)}" if event.availability_deadline else ""
    defs: list[tuple[bool, str]] = [
        (True, f"{fmt_md(event.formal_start_date)}–{fmt_md(formal_end)} 排练,{fmt_md(eval_date)} 全员评估"),
        (n_members > 0, f"{n_members} 人,已开通账号 {n_accounts} 人" if n_members else "还没有人员"),
        (n_songs > 0, f"{n_songs} 首 · {n_sessions} 场正规排练 + 1 场评估" if n_songs else "还没有曲目"),
        (n_songs > 0, f"{n_rules} 条要求" if n_rules else "没有特殊要求(可跳过)"),
        (n_members > 0 and n_submitted == n_members, f"已提交 {n_submitted} / {n_members}{deadline}"),
        (latest is not None, solve_summary),
        (published is not None, schedule_summary),
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
        "latest_version_no": latest.version_no if latest else None,
        "published_version_no": published.version_no if published else None,
        "latest_job_status": last_job.status if last_job else None,
        "conflict_count": conflicts,
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
def ready_song_codes(event: Event) -> list[str]:
    """参演人员已全部提交空闲的曲目。"""
    submitted = {p.member_id for p in event.participants if p.availability_submitted_at is not None}
    return [s.code for s in event.songs if all(m.id in submitted for m in s.members)]


def event_problem(event: Event, *, include_unsubmitted: bool = False, song_codes: set[str] | None = None) -> Problem:
    """把演出转换为求解包的 Problem。默认只用已提交的空闲,未提交者视为全天不可排;``song_codes`` 可限定只排部分曲目。"""
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
        if song_codes is None or s.code in song_codes
    )
    return Problem(
        config=event_config(event),
        members=names,
        songs=songs,
        availability=avail,
        rules=to_solver_rules(event),
        objectives=tuple(event_settings(event).objectives),
    )


# ---------- 求解任务 / 排练表版本 ----------
def published_version(event: Event) -> ScheduleVersion | None:
    return next((v for v in reversed(event.versions) if v.status == "published"), None)


def summarize_diagnosis(diag: dict | None) -> str:
    """把诊断报告压成一句话(交互设计 A6:「差 3 场:曲目 c、f 排不下,主要卡在 若、思」)。"""
    if not diag:
        return "没有可行方案"
    parts: list[str] = []
    mc = diag.get("最大覆盖") or {}
    gap = int(mc.get("要求场次", 0)) - int(mc.get("最多可排场次", 0))
    songs = [row["曲目"] for row in diag.get("各曲缺口", []) if int(row.get("全局缺口", 0)) > 0]
    ev = diag.get("评估场") or {}
    eval_ok = bool(ev.get("可行", True))
    formal_checked = "最大覆盖" in diag
    if gap > 0:
        parts.append(f"差 {gap} 场" + (f":曲目 {'、'.join(songs)} 排不下" if songs else ""))
    elif diag.get("无候选任务") or songs:
        parts.append("曲目 " + "、".join(songs) + " 排不下" if songs else "有排练没有全员共同时段")
    elif not eval_ok:
        parts.append("正规排练能排下,但评估日没有全员都能到的时段" if formal_checked else "评估日没有全员都能到的时段")
    else:
        parts.append("各曲单独能排,但合在一起有冲突")
    adj = diag.get("最小调整建议") or {}
    if gap > 0 and adj.get("可行"):
        who = sorted({c["成员"] for c in adj.get("调整", [])})
        parts.append(
            f"最少需 {adj.get('受影响成员数', len(who))} 人协调 {adj.get('调整小时数', 0)} 小时" + (f"({'、'.join(who)})" if who else "")
        )
    if not eval_ok and (gap > 0 or songs):
        parts.append("评估日也需协调")
    return ";".join(parts)


def serialize_job(job: SolveJob) -> JobOut:
    elapsed = None
    if job.started_at is not None:
        end = job.finished_at or datetime.utcnow()
        elapsed = round((end - job.started_at).total_seconds(), 1)
    return JobOut(
        id=job.id,
        event_id=job.event_id,
        status=job.status,  # type: ignore[arg-type]
        progress=job.progress or "",
        stage_records=list(job.stage_records or []),
        attempts=list(job.attempts or []),
        ladder_level_used=job.ladder_level_used,
        skipped_songs=list(job.skipped_songs or []),
        diagnosis=job.diagnosis,
        summary=job.summary or "",
        error=job.error,
        version_id=job.version_id,
        only_ready_songs=bool((job.options or {}).get("only_ready_songs")),
        base_version_id=(job.options or {}).get("base_version_id"),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        elapsed_seconds=elapsed,
    )


def serialize_session(event: Event, s: RehearsalSession) -> SessionOut:
    config = event_config(event)
    names = {p.member_id: p.member.display_name for p in event.participants}
    if s.kind == "evaluation":
        members = [MemberBrief(id=p.member_id, display_name=p.member.display_name) for p in sorted_participants(event)]
        song_code, song_name = None, "全员评估"
    else:
        song = s.song
        members = [MemberBrief(id=m.id, display_name=m.display_name) for m in song.members] if song else []
        song_code, song_name = (song.code, song.name) if song else (None, "(曲目已删除)")
    absent_ids = list(s.absent_member_ids or [])
    attendance = None
    if s.attendance:
        attendance = {names.get(int(k), str(k)): config.range_label(int(v[0]), int(v[1]) - int(v[0])) for k, v in s.attendance.items()}
    return SessionOut(
        id=s.id,
        kind=s.kind,  # type: ignore[arg-type]
        song_id=s.song_id,
        song_code=song_code,
        song_name=song_name,
        task_no=s.task_no,
        date=s.date,
        weekday=weekday_zh(s.date),
        start_slot=s.start_slot,
        duration_slots=s.duration_slots,
        time=config.range_label(s.start_slot, s.duration_slots),
        members=members,
        absent=[MemberBrief(id=i, display_name=names.get(i, "?")) for i in absent_ids],
        attendance=attendance,
        locked=s.locked,
    )


def member_stats(event: Event, sessions: list[RehearsalSession]) -> list[MemberStatOut]:
    config = event_config(event)
    stats: dict[int, dict] = {
        p.member_id: {"sessions": 0, "hours": 0, "days": set(), "absent": 0, "eval": None} for p in sorted_participants(event)
    }
    for s in sessions:
        if s.kind == "evaluation":
            for k, v in (s.attendance or {}).items():
                st = stats.get(int(k))
                if st is not None:
                    st["eval"] = config.range_label(int(v[0]), int(v[1]) - int(v[0]))
            continue
        if s.song is None:
            continue
        absent = set(s.absent_member_ids or [])
        for m in s.song.members:
            st = stats.get(m.id)
            if st is None:
                continue
            if m.id in absent:
                st["absent"] += 1
                continue
            st["sessions"] += 1
            st["hours"] += s.duration_slots
            st["days"].add(s.date)
    names = {p.member_id: p.member.display_name for p in event.participants}
    return [
        MemberStatOut(
            member_id=mid,
            display_name=names[mid],
            sessions=st["sessions"],
            hours=st["hours"],
            days=len(st["days"]),
            absent=st["absent"],
            eval_time=st["eval"],
        )
        for mid, st in stats.items()
    ]


def serialize_version(event: Event, v: ScheduleVersion, *, detail: bool = False) -> VersionOut | VersionDetailOut:
    base = dict(
        id=v.id,
        event_id=v.event_id,
        version_no=v.version_no,
        source=v.source,
        parent_version_id=v.parent_version_id,
        status=v.status,
        locked_count=sum(1 for s in v.sessions if s.locked),
        level_used=v.level_used,
        exact_optimum=v.exact_optimum,
        objective_values=dict(v.objective_values or {}),
        validation_errors=list(v.validation_errors or []),
        metrics=dict(v.metrics or {}),
        skipped_songs=list(v.skipped_songs or []),
        session_count=len(v.sessions),
        created_at=v.created_at,
        published_at=v.published_at,
    )
    if not detail:
        return VersionOut(**base)  # type: ignore[arg-type]
    return VersionDetailOut(
        **base,  # type: ignore[arg-type]
        sessions=[serialize_session(event, s) for s in v.sessions],
        member_stats=member_stats(event, list(v.sessions)),
        stage_records=list(v.stage_records or []),
    )


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


# ---------- 规则冲突检查(RULE-06) ----------
def rule_conflict_warning(event: Event) -> str | None:
    """不看个人空闲,只看规则本身是否让某场排练完全没有可排时段(如禁排太多、固定场次落在禁排时段)。"""
    if not event.songs or not event.participants:
        return None
    problem = event_problem(event)
    full = Availability()
    for name in problem.members:
        for d in problem.config.all_dates:
            full.set_row(name, d, [1] * problem.config.slots_per_day)
    problem.availability = full
    errors, _ = problem.validate()
    if errors:
        return ";".join(errors[:3])
    tasks = make_tasks(problem)
    cands = build_candidates(problem, tasks, allow_absent=False)
    dead = [t for t in tasks if not cands[t.task_id]]
    if dead:
        names = "、".join(f"{problem.song(t.song_code).name} 第 {t.task_no} 场({t.duration}h)" for t in dead[:4])
        return f"按现在的要求,{names} 没有任何可排时段(即使所有人都有空)"
    return None
