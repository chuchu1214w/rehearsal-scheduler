"""排练表手动修改(开发文档 §4.6):移动 / 交换 / 锁定,冲突标出而不拒绝,撤销 / 重做,修改次数核对。

- 已发布 / 已归档的版本不可变:修改时先复制成新草稿(schedule_edit.ensure_draft)。
- 草稿允许暂存硬冲突(界面标红并说明原因),发布前必须全部解决(api/schedule.publish_version)。
- 每次修改记一条 ScheduleOperation(前后状态),撤销 = 恢复“前”,重做 = 恢复“后”;做了新修改后,已撤销的不能再重做。
- 每次修改 revision +1;请求带上界面看到的 expected_revision,对不上(别的窗口 / 别人改过)返回 409,不会悄悄覆盖。
"""

from __future__ import annotations

import re
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session as DbSession

from solver.validator import compute_metrics, validate_schedule

from .models import Event, RehearsalSession, ScheduleOperation, ScheduleVersion
from .schedule_edit import _humanize, metric_deltas, to_solver_session, version_level, version_problem
from .schemas import IssueOut, OperationOut, VersionDetailOut
from .services import event_config, serialize_version

HISTORY_LIMIT = 30


def check_revision(version: ScheduleVersion, expected: int | None) -> None:
    if expected is not None and expected != (version.revision or 0):
        raise HTTPException(status_code=409, detail="排练表刚被修改过(可能在别的窗口或别人操作),已为你刷新,请再改一次")


def _state(s: RehearsalSession) -> dict:
    return {"date": s.date.isoformat(), "start_slot": s.start_slot, "duration_slots": s.duration_slots, "locked": s.locked}


def _restore(s: RehearsalSession, state: dict) -> None:
    s.date = date.fromisoformat(state["date"])
    s.start_slot = int(state["start_slot"])
    s.duration_slots = int(state["duration_slots"])
    s.locked = bool(state["locked"])


def _label(s: RehearsalSession) -> str:
    if s.kind == "evaluation":
        return "全员评估"
    return s.song.code if s.song else "?"


def _when(event: Event, d: date, start: int, duration: int) -> str:
    return f"{d.month}/{d.day} {event_config(event).range_label(start, duration)}"


def revalidate(event: Event, version: ScheduleVersion) -> list[str]:
    """按当前场次重新校验,写回 validation_errors / metrics;返回错误句子。"""
    problem = version_problem(event, version)
    sessions = [to_solver_session(event, s) for s in version.sessions]
    report = validate_schedule(problem, sessions, version_level(problem, version))
    version.validation_errors = list(report.errors)
    version.metrics = compute_metrics(problem, sessions)
    version.exact_optimum = False
    if version.source == "solver":
        version.source = "manual"
    return list(report.errors)


def _record(
    db: DbSession, version: ScheduleVersion, kind: str, summary: str, touched: list[tuple[RehearsalSession, dict]], actor_id: int | None
) -> None:
    """touched: (场次, 修改前状态)。做了新修改后,已撤销的操作不能再重做,一并删除。"""
    for op in [o for o in version.operations if o.undone]:
        version.operations.remove(op)
    seq = max((o.seq for o in version.operations), default=0) + 1
    changes = [{"session_id": s.id, "before": before, "after": _state(s)} for s, before in touched]
    version.operations.append(ScheduleOperation(seq=seq, kind=kind, summary=summary[:300], changes=changes, actor_id=actor_id))
    version.revision = (version.revision or 0) + 1


def _session(version: ScheduleVersion, session_id: int) -> RehearsalSession:
    for s in version.sessions:
        if s.id == session_id:
            return s
    raise HTTPException(status_code=404, detail="场次不存在")


def _editable(s: RehearsalSession) -> None:
    if s.kind == "evaluation":
        raise HTTPException(status_code=422, detail="全员评估场由求解器安排,暂不支持手动移动")
    if s.locked:
        raise HTTPException(status_code=422, detail="这场已锁定,先解锁再移动")


def _fits(event: Event, d: date, start: int, duration: int) -> None:
    config = event_config(event)
    if duration < 1 or start < 0 or start + duration > config.slots_per_day:
        raise HTTPException(status_code=422, detail="超出每日排练窗口")
    if d not in set(config.formal_dates):
        raise HTTPException(status_code=422, detail="只能移到正规排练日")


def _current_errors(event: Event, version: ScheduleVersion) -> list[str]:
    problem = version_problem(event, version)
    return validate_schedule(problem, [to_solver_session(event, s) for s in version.sessions], version_level(problem, version)).errors


def _finish(event: Event, version: ScheduleVersion, before_errors: list[str], before_metrics: dict) -> tuple[list[str], list[str]]:
    """重新校验;返回(这次新引入的冲突,软目标变化说明)。"""
    errors = revalidate(event, version)
    new = [_readable(e) for e in errors if e not in before_errors]
    return list(dict.fromkeys(new)), metric_deltas(before_metrics, version.metrics or {})


def move(
    db: DbSession,
    event: Event,
    version: ScheduleVersion,
    session: RehearsalSession,
    *,
    new_date: date,
    new_start: int,
    new_duration: int | None,
    actor_id: int | None,
) -> tuple[list[str], list[str]]:
    _editable(session)
    duration = new_duration or session.duration_slots
    _fits(event, new_date, new_start, duration)
    before_errors, before_metrics = _current_errors(event, version), dict(version.metrics or {})
    old = (session.date, session.start_slot, session.duration_slots)
    before = _state(session)
    session.date, session.start_slot, session.duration_slots = new_date, new_start, duration
    summary = f"移动 {_label(session)}:{_when(event, *old)} → {_when(event, new_date, new_start, duration)}"
    _record(db, version, "move", summary, [(session, before)], actor_id)
    result = _finish(event, version, before_errors, before_metrics)
    db.commit()
    return result


def swap(
    db: DbSession, event: Event, version: ScheduleVersion, a: RehearsalSession, b: RehearsalSession, actor_id: int | None
) -> tuple[list[str], list[str]]:
    """交换两场的时间(各自保留时长)。"""
    if a.id == b.id:
        raise HTTPException(status_code=422, detail="不能和自己交换")
    _editable(a)
    _editable(b)
    _fits(event, b.date, b.start_slot, a.duration_slots)
    _fits(event, a.date, a.start_slot, b.duration_slots)
    before_errors, before_metrics = _current_errors(event, version), dict(version.metrics or {})
    ba, bb = _state(a), _state(b)
    where_a = _when(event, a.date, a.start_slot, a.duration_slots)
    where_b = _when(event, b.date, b.start_slot, b.duration_slots)
    (a.date, a.start_slot), (b.date, b.start_slot) = (b.date, b.start_slot), (a.date, a.start_slot)
    summary = f"交换 {_label(a)}(原 {where_a})与 {_label(b)}(原 {where_b})"
    _record(db, version, "swap", summary, [(a, ba), (b, bb)], actor_id)
    result = _finish(event, version, before_errors, before_metrics)
    db.commit()
    return result


def set_lock(db: DbSession, event: Event, version: ScheduleVersion, session: RehearsalSession, locked: bool, actor_id: int | None) -> None:
    if session.kind == "evaluation":
        raise HTTPException(status_code=422, detail="全员评估场不需要锁定")
    if session.locked == locked:
        return
    before = _state(session)
    session.locked = locked
    _record(
        db,
        version,
        "lock",
        f"{'锁定' if locked else '解锁'} {_label(session)}({_when(event, session.date, session.start_slot, session.duration_slots)})",
        [(session, before)],
        actor_id,
    )
    db.commit()


def undo(db: DbSession, event: Event, version: ScheduleVersion) -> str:
    done = [o for o in version.operations if not o.undone]
    if not done:
        raise HTTPException(status_code=409, detail="没有可以撤销的修改")
    op = done[-1]
    for c in op.changes:
        _restore(_session(version, c["session_id"]), c["before"])
    op.undone = True
    version.revision = (version.revision or 0) + 1
    revalidate(event, version)
    db.commit()
    return op.summary


def redo(db: DbSession, event: Event, version: ScheduleVersion) -> str:
    undone = [o for o in version.operations if o.undone]
    if not undone:
        raise HTTPException(status_code=409, detail="没有可以重做的修改")
    op = undone[0]
    for c in op.changes:
        _restore(_session(version, c["session_id"]), c["after"])
    op.undone = False
    version.revision = (version.revision or 0) + 1
    revalidate(event, version)
    db.commit()
    return op.summary


_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_WEEK = "一二三四五六日"


def _readable(message: str) -> str:
    """校验句子去掉编号,日期写成「10/5 周一」。"""

    def fmt(m: re.Match[str]) -> str:
        d = date(int(m[1]), int(m[2]), int(m[3]))
        return f"{d.month}/{d.day} 周{_WEEK[d.weekday()]}"

    return _ISO.sub(fmt, _humanize(message))


def live_issues(event: Event, version: ScheduleVersion) -> list[IssueOut]:
    """按最新空闲与要求实时检查,问题对应到具体场次(界面标红)。"""
    problem = version_problem(event, version)
    rows = list(version.sessions)
    report = validate_schedule(problem, [to_solver_session(event, s) for s in rows], version_level(problem, version))
    return [
        IssueOut(
            code=i.message.split(" ", 1)[0] if i.message.startswith("V-") else "",
            message=_readable(i.message),
            session_ids=[rows[k].id for k in i.sessions],
        )
        for i in report.issues
    ]


def admin_detail(event: Event, version: ScheduleVersion) -> VersionDetailOut:
    """管理员看到的版本详情:另附冲突、修改历史与能否撤销 / 重做。"""
    out = serialize_version(event, version, detail=True)
    assert isinstance(out, VersionDetailOut)
    ops = list(version.operations)
    out.issues = live_issues(event, version)
    out.history = [
        OperationOut(id=o.id, seq=o.seq, kind=o.kind, summary=o.summary, undone=o.undone, created_at=o.created_at)
        for o in reversed(ops[-HISTORY_LIMIT:])
    ]
    out.can_undo = version.status == "draft" and any(not o.undone for o in ops)
    out.can_redo = version.status == "draft" and any(o.undone for o in ops)
    return out
