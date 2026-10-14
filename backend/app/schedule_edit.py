"""排练表调整(M5):手动移动 / 锁定、版本差异、与最新空闲的冲突。

版本规则:草稿可原地修改;已发布 / 已归档的版本不可变,修改时先复制成新的草稿(parent_version_id 指向原版本)。
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from solver.types import FixedSession, Problem, Session
from solver.validator import compute_metrics, validate_schedule

from .models import Event, RehearsalSession, ScheduleVersion
from .schemas import ConflictOut, DiffItemOut, DiffOut, MemberBrief
from .services import availability_index, event_config, event_problem, serialize_session, sorted_participants

METRIC_LABELS = {
    "absent": "计划外缺席",
    "eval_attendance": "评估场迟到早退",
    "spacing": "同曲间隔不足",
    "focus_days": "集中排练日",
    "trips": "成员额外往返",
    "gaps": "成员长空档",
    "overtime": "单日超时",
    "soft_avoid": "落在「尽量避开」时段",
}


# ---------- 转换 ----------
def member_names(event: Event) -> dict[int, str]:
    return {p.member_id: p.member.display_name for p in event.participants}


def to_solver_session(event: Event, s: RehearsalSession) -> Session:
    names = member_names(event)
    return Session(
        kind=s.kind,
        date=s.date,
        start=s.start_slot,
        duration=s.duration_slots,
        song_code=s.song.code if s.song else None,
        task_no=s.task_no,
        absent_members=tuple(names[i] for i in (s.absent_member_ids or []) if i in names),
        attendance={names[int(k)]: (int(v[0]), int(v[1])) for k, v in (s.attendance or {}).items() if int(k) in names} or None,
        locked=s.locked,
    )


def version_problem(event: Event, version: ScheduleVersion) -> Problem:
    skipped = set(version.skipped_songs or [])
    codes = {s.code for s in event.songs if s.code not in skipped}
    return event_problem(event, song_codes=codes)


def version_level(problem: Problem, version: ScheduleVersion):  # noqa: ANN201
    if version.level_used is not None and 0 <= version.level_used < len(problem.ladder):
        return problem.ladder[version.level_used]
    return problem.ladder[0]


# ---------- 草稿 ----------
def next_version_no(db: DbSession, event: Event) -> int:
    return (db.scalar(select(func.max(ScheduleVersion.version_no)).where(ScheduleVersion.event_id == event.id)) or 0) + 1


def fork_as_draft(db: DbSession, event: Event, base: ScheduleVersion, actor_id: int | None, source: str = "manual") -> ScheduleVersion:
    """把一个版本复制成新的草稿(场次连同锁定状态一起复制)。"""
    version = ScheduleVersion(
        event_id=event.id,
        version_no=next_version_no(db, event),
        source=source,
        parent_version_id=base.id,
        job_id=None,
        status="draft",
        level_used=base.level_used,
        exact_optimum=False,
        objective_values=dict(base.objective_values or {}),
        stage_records=[],
        validation_errors=list(base.validation_errors or []),
        metrics=dict(base.metrics or {}),
        skipped_songs=list(base.skipped_songs or []),
        created_by=actor_id,
    )
    db.add(version)
    db.flush()
    for s in base.sessions:
        db.add(
            RehearsalSession(
                version_id=version.id,
                song_id=s.song_id,
                kind=s.kind,
                task_no=s.task_no,
                date=s.date,
                start_slot=s.start_slot,
                duration_slots=s.duration_slots,
                absent_member_ids=list(s.absent_member_ids or []),
                attendance=dict(s.attendance) if s.attendance else None,
                locked=s.locked,
                location=s.location or "",
                uid=s.uid,
            )
        )
    db.flush()
    db.refresh(version)
    return version


def ensure_draft(db: DbSession, event: Event, version: ScheduleVersion, actor_id: int | None) -> tuple[ScheduleVersion, bool]:
    """草稿直接返回;发布 / 归档的版本先复制成草稿。返回 (草稿, 是否新建)。"""
    if version.status == "draft":
        return version, False
    return fork_as_draft(db, event, version, actor_id), True


def find_session(version: ScheduleVersion, session_id: int, *, original: ScheduleVersion | None = None) -> RehearsalSession:
    """在(可能是复制出来的)草稿里找到对应场次:复制后 id 变了,用固定身份 uid 对应。"""
    for s in version.sessions:
        if s.id == session_id:
            return s
    if original is not None:
        src = next((s for s in original.sessions if s.id == session_id), None)
        if src is not None:
            for s in version.sessions:
                if src.uid and s.uid == src.uid:
                    return s
            for s in version.sessions:
                if not src.uid and (s.kind, s.song_id, s.task_no) == (src.kind, src.song_id, src.task_no):
                    return s
    raise HTTPException(status_code=404, detail="场次不存在")


# ---------- 校验与指标 ----------
def refresh_version_quality(event: Event, version: ScheduleVersion) -> None:
    problem = version_problem(event, version)
    sessions = [to_solver_session(event, s) for s in version.sessions]
    report = validate_schedule(problem, sessions, version_level(problem, version))
    version.validation_errors = list(report.errors)
    version.metrics = compute_metrics(problem, sessions)
    version.exact_optimum = False


def metric_deltas(before: dict[str, int], after: dict[str, int]) -> list[str]:
    out: list[str] = []
    for key, label in METRIC_LABELS.items():
        a, b = int(before.get(key, 0)), int(after.get(key, 0))
        if a != b:
            out.append(f"{label} {b - a:+d}")
    return out


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUM = re.compile(r"\d+")


def _worse(error: str, before: list[str]) -> bool:
    """这次移动后的错误是否「新引入」:完全相同的不算;缺席计数类句子(不带日期,如「缺席场次 3 超过层级上限 1」)
    只在数字变大时才算——把一场移回大家都有空的时段、缺席变少时不能被拒。"""
    if error in before:
        return False
    if _DATE.search(error):
        return True
    shape = _NUM.sub("#", error)
    counts = [[int(n) for n in _NUM.findall(b)] for b in before if _NUM.sub("#", b) == shape]
    mine = [int(n) for n in _NUM.findall(error)]
    return not any(mine <= c for c in counts)


def check_move_strict(
    event: Event, version: ScheduleVersion, session: RehearsalSession, *, new_date: date, new_start: int, new_duration: int | None
) -> None:
    """旧接口(iOS App 1.0 使用)的规则:这次移动若新引入硬冲突则 422 拒绝。只检查,不修改。"""
    if session.locked:
        raise HTTPException(status_code=422, detail="这场已锁定,先解锁再移动")
    if session.kind == "evaluation":
        raise HTTPException(status_code=422, detail="全员评估场由求解器安排,暂不支持手动移动")
    if new_duration is not None and new_duration != session.duration_slots:
        # 时长不再是硬规则(网页版可上下拉调整),但旧接口保持原来的行为
        raise HTTPException(status_code=422, detail="不能这样改:时长由曲目的排练方案决定,请在网页版调整时长")
    problem = version_problem(event, version)
    config = event_config(event)
    duration = new_duration or session.duration_slots
    if duration < 1 or new_start < 0 or new_start + duration > config.slots_per_day:
        raise HTTPException(status_code=422, detail="超出每日排练窗口")
    if new_date not in set(config.formal_dates):
        raise HTTPException(status_code=422, detail="只能移到正规排练日")
    # 与网页版的实时检查一致:缺席按演出设置允许的规则;移过去后只保留计划内缺席(出勤上限),
    # 其余参演成员都要有空——这样仍是「新引入冲突就拒绝」,而移到大家都有空的时段时,原来记下的缺席会清掉、不会被误拒
    level = problem.ladder[-1]
    before_sessions = [to_solver_session(event, s) for s in version.sessions]
    before = validate_schedule(problem, before_sessions, level)
    code = session.song.code if session.song else ""
    after_sessions = [
        replace(
            x,
            date=new_date,
            start=new_start,
            duration=duration,
            absent_members=tuple(m for m in x.absent_members if problem.rules.attendance_cap(m, code) is not None),
        )
        if s.id == session.id
        else x
        for s, x in zip(version.sessions, before_sessions, strict=True)
    ]
    after = validate_schedule(problem, after_sessions, level)
    new_errors = [e for e in after.errors if _worse(e, before.errors)]
    if new_errors:
        # 校验器的句子以「曲目名 日期 时段」开头;这些错误都是这场引起的,去掉重复的前缀更好读
        label = f"{session.song.name if session.song else ''} {new_date} {config.range_label(new_start, duration)} "
        msgs = dict.fromkeys(_humanize(e).replace(label, "") for e in new_errors)
        raise HTTPException(status_code=422, detail="不能这样改:" + ";".join(list(msgs)[:3]))


def _humanize(error: str) -> str:
    """把校验器的 V-xx 编号去掉,句子本身已是中文。"""
    parts = error.split(" ", 1)
    return parts[1] if len(parts) == 2 and parts[0].startswith("V-") else error


# ---------- 锁定重排 ----------
def locked_fixed_sessions(event: Event, version: ScheduleVersion) -> tuple[FixedSession, ...]:
    names = member_names(event)
    out: list[FixedSession] = []
    for s in version.sessions:
        if not s.locked or s.kind != "formal" or s.song is None:
            continue
        absent = [names[i] for i in (s.absent_member_ids or []) if i in names]
        out.append(FixedSession(s.song.code, s.date, s.start_slot, s.duration_slots, absent[0] if absent else None))
    return tuple(out)


def copy_locations(source: ScheduleVersion, target: ScheduleVersion) -> int:
    """把 source 里已填的排练地点带到 target 中时间、曲目都相同的场次上。返回带过去的数量。"""
    where = {(s.kind, s.song_id, s.date, s.start_slot, s.duration_slots): s.location for s in source.sessions if s.location}
    n = 0
    for s in target.sessions:
        loc = where.get((s.kind, s.song_id, s.date, s.start_slot, s.duration_slots))
        if loc and not s.location:
            s.location = loc
            n += 1
    return n


def copy_locks(base: ScheduleVersion, target: ScheduleVersion) -> None:
    """重排后,把基准版本里锁定的场次在新版本中标回锁定。"""
    keys = {(s.song_id, s.date, s.start_slot, s.duration_slots) for s in base.sessions if s.locked and s.kind == "formal"}
    for s in target.sessions:
        if s.kind == "formal" and (s.song_id, s.date, s.start_slot, s.duration_slots) in keys:
            s.locked = True


# ---------- 差异 ----------
def _key(s: RehearsalSession) -> tuple:
    return ("eval",) if s.kind == "evaluation" else ("formal", s.song_id, s.task_no)


def diff_versions(event: Event, base: ScheduleVersion, against: ScheduleVersion) -> DiffOut:
    """against(旧)→ base(新)的变化。"""
    old = {_key(s): s for s in against.sessions}
    new = {_key(s): s for s in base.sessions}
    items: list[DiffItemOut] = []
    affected: set[int] = set()
    for key, s in new.items():
        o = old.get(key)
        if o is None:
            items.append(DiffItemOut(change="added", kind=s.kind, before=None, after=serialize_session(event, s)))
            affected.update(_people(s))
        elif (o.date, o.start_slot, o.duration_slots) != (s.date, s.start_slot, s.duration_slots):
            items.append(DiffItemOut(change="moved", kind=s.kind, before=serialize_session(event, o), after=serialize_session(event, s)))
            affected.update(_people(s) | _people(o))
        elif (set(o.absent_member_ids or []) != set(s.absent_member_ids or [])) or (o.attendance or {}) != (s.attendance or {}):
            items.append(DiffItemOut(change="changed", kind=s.kind, before=serialize_session(event, o), after=serialize_session(event, s)))
            affected.update(set(o.absent_member_ids or []) ^ set(s.absent_member_ids or []))
            affected.update(
                int(k)
                for k in {**(o.attendance or {}), **(s.attendance or {})}
                if (o.attendance or {}).get(k) != (s.attendance or {}).get(k)
            )
    for key, o in old.items():
        if key not in new:
            items.append(DiffItemOut(change="removed", kind=o.kind, before=serialize_session(event, o), after=None))
            affected.update(_people(o))
    order = {"moved": 0, "changed": 1, "added": 2, "removed": 3}
    items.sort(key=lambda i: (order[i.change], (i.after or i.before).date, (i.after or i.before).start_slot))  # type: ignore[union-attr]
    names = member_names(event)
    parts = [
        f"{n} 场{label}"
        for label, n in (
            ("移动", sum(i.change == "moved" for i in items)),
            ("变更", sum(i.change == "changed" for i in items)),
            ("新增", sum(i.change == "added" for i in items)),
            ("删除", sum(i.change == "removed" for i in items)),
        )
        if n
    ]
    return DiffOut(
        base_id=base.id,
        base_no=base.version_no,
        against_id=against.id,
        against_no=against.version_no,
        items=items,
        affected_members=[MemberBrief(id=i, display_name=names[i]) for i in sorted(affected, key=lambda i: names.get(i, "")) if i in names],
        summary=("、".join(parts) + f",影响 {len(affected)} 人") if parts else "两个版本完全相同",
    )


def _people(s: RehearsalSession) -> set[int]:
    if s.kind == "evaluation":
        return set(int(k) for k in (s.attendance or {}))
    return {m.id for m in s.song.members} if s.song else set()


# ---------- 与最新空闲的冲突 ----------
def availability_hits(event: Event, version: ScheduleVersion) -> list[tuple[RehearsalSession, int, list[int]]]:
    """排练表里成员没空的场次:(场次, 成员 id, 没空的格)。未提交空闲的成员不算。"""
    avail = availability_index(event)
    submitted = {p.member_id for p in event.participants if p.availability_submitted_at is not None}
    names = member_names(event)
    out: list[tuple[RehearsalSession, int, list[int]]] = []
    for s in version.sessions:
        if s.kind == "evaluation":
            expected = {int(k): (int(v[0]), int(v[1])) for k, v in (s.attendance or {}).items()}
        else:
            if s.song is None:
                continue
            absent = set(s.absent_member_ids or [])
            expected = {m.id: (s.start_slot, s.start_slot + s.duration_slots) for m in s.song.members if m.id not in absent}
        for mid, (a, b) in expected.items():
            if mid not in submitted or mid not in names:
                continue
            row = avail.get(mid, {}).get(s.date)
            slots = row.slots if row is not None else ""
            bad = [h for h in range(a, b) if h >= len(slots) or slots[h] == "0"]
            if bad:
                out.append((s, mid, bad))
    return out


def hit_key(s: RehearsalSession, member_id: int) -> str:
    return f"{s.uid}:{member_id}"


def accepted_hits(event: Event, version: ScheduleVersion) -> dict[str, list[int]]:
    """带冲突发布时,把当时「成员没空」的冲突逐条记下(场次固定身份:成员 → 没空的格),之后不再当作新冲突。"""
    return {hit_key(s, mid): bad for s, mid, bad in availability_hits(event, version)}


def schedule_conflicts(event: Event, version: ScheduleVersion, *, include_accepted: bool = False) -> list[ConflictOut]:
    """发布后有人改了空闲:列出排练表里成员已不再有空的场次。未提交空闲的成员不算。
    带冲突发布的版本,发布时管理员已确认的(同一场、同一人、没空的格没有变多)不算。"""
    config = event_config(event)
    names = member_names(event)
    accepted = {} if include_accepted else dict((version.forced_publish or {}).get("accepted") or {})
    out: list[ConflictOut] = []
    for s, mid, bad in availability_hits(event, version):
        if set(bad) <= set(accepted.get(hit_key(s, mid), [])):
            continue
        out.append(
            ConflictOut(
                session=serialize_session(event, s),
                member=MemberBrief(id=mid, display_name=names[mid]),
                hours=[config.slot_label(h) for h in bad],
            )
        )
    return out


def conflict_count(event: Event, version: ScheduleVersion | None) -> int:
    return len(schedule_conflicts(event, version)) if version is not None else 0


def participants_brief(event: Event) -> list[MemberBrief]:
    return [MemberBrief(id=p.member_id, display_name=p.member.display_name) for p in sorted_participants(event)]
