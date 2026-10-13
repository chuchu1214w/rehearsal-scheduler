"""排练表手动修改(开发文档 §4.6):移动 / 交换 / 锁定,冲突标出而不拒绝,撤销 / 重做,修改次数核对。

- 已发布 / 已归档的版本不可变:修改时先复制成新草稿(schedule_edit.ensure_draft)。
- 草稿允许暂存硬冲突(界面标红并说明原因),发布前必须全部解决(api/schedule.publish_version)。
- 每次修改记一条 ScheduleOperation(前后状态),撤销 = 恢复“前”,重做 = 恢复“后”;做了新修改后,已撤销的不能再重做。
- 每次修改 revision +1;请求带上界面看到的 expected_revision,对不上(别的窗口 / 别人改过)返回 409,不会悄悄覆盖。
  修改与发布开始时先用“比较并交换”占住这次修改(claim),同时进行的另一个请求会得到 409,不会互相覆盖或改进已发布的版本。
- 修改记录用场次的固定身份 uid 找场次(数据库 id 在删除后撤销时会变,SQLite 还会复用刚删掉的 id);重建时用回原 uid。
"""

from __future__ import annotations

import re
from datetime import date

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.exc import StaleDataError

from solver.validator import compute_metrics, validate_schedule

from .models import Event, RehearsalSession, ScheduleOperation, ScheduleVersion
from .schedule_edit import _humanize, metric_deltas, to_solver_session, version_level, version_problem
from .schemas import IssueOut, OperationOut, VersionDetailOut
from .services import event_config, serialize_version

HISTORY_LIMIT = 30


STALE = "排练表刚被修改过(可能在别的窗口或别人操作),已为你刷新,请再改一次"


def check_revision(version: ScheduleVersion, expected: int | None) -> None:
    if expected is not None and expected != (version.revision or 0):
        raise HTTPException(status_code=409, detail=STALE)


def claim(db: DbSession, version: ScheduleVersion) -> None:
    """在改动任何场次之前,把修改次数 +1(“比较并交换”):读到之后若别的请求已先改过 / 已发布,这次 409,不改任何东西。"""
    old = version.revision or 0
    try:
        res = db.execute(
            update(ScheduleVersion).where(ScheduleVersion.id == version.id, ScheduleVersion.revision == old).values(revision=old + 1)
        )
    except OperationalError as exc:  # SQLite:读取之后别的请求已写入,本事务无法再写
        db.rollback()
        raise HTTPException(status_code=409, detail=STALE) from exc
    if res.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail=STALE)
    set_committed_value(version, "revision", old + 1)


def _key(s: RehearsalSession) -> dict:
    """场次在版本内的身份:曲目 + 第几场(删除后撤销重建时仍是同一身份;数据库 id 会变)。"""
    return {"kind": s.kind, "song_id": s.song_id, "task_no": s.task_no}


def _state(s: RehearsalSession) -> dict:
    return {"date": s.date.isoformat(), "start_slot": s.start_slot, "duration_slots": s.duration_slots, "locked": s.locked}


def _snapshot(s: RehearsalSession) -> dict:
    """新建 / 删除时保存整场,撤销 / 重做时据此原样重建(包括固定身份 uid)。"""
    return {
        "uid": s.uid,
        **_key(s),
        **_state(s),
        "absent_member_ids": list(s.absent_member_ids or []),
        "attendance": dict(s.attendance) if s.attendance else None,
        "location": s.location or "",
    }


def _restore(s: RehearsalSession, state: dict) -> None:
    s.date = date.fromisoformat(state["date"])
    s.start_slot = int(state["start_slot"])
    s.duration_slots = int(state["duration_slots"])
    s.locked = bool(state["locked"])


def _create(version: ScheduleVersion, snap: dict) -> RehearsalSession:
    row = RehearsalSession(
        song_id=snap["song_id"],
        kind=snap["kind"],
        task_no=snap["task_no"],
        date=date.fromisoformat(snap["date"]),
        start_slot=int(snap["start_slot"]),
        duration_slots=int(snap["duration_slots"]),
        absent_member_ids=list(snap.get("absent_member_ids") or []),
        attendance=snap.get("attendance"),
        locked=bool(snap.get("locked")),
        location=snap.get("location") or "",
    )
    if snap.get("uid"):
        row.uid = snap["uid"]
    version.sessions.append(row)
    return row


def _label(s: RehearsalSession) -> str:
    if s.kind == "evaluation":
        return "全员评估"
    if s.song is None:
        return "?"
    return s.song.code if s.song.name == s.song.code else f"{s.song.code} {s.song.name}"


def _when(event: Event, d: date, start: int, duration: int) -> str:
    return f"{d.month}/{d.day} 周{'一二三四五六日'[d.weekday()]} {event_config(event).range_label(start, duration)}"


def revalidate(event: Event, version: ScheduleVersion) -> list[str]:
    """按当前场次重新校验,写回 validation_errors / metrics;返回错误句子。"""
    problem = version_problem(event, version)
    rows, report = _live_report(event, version)
    version.validation_errors = list(report.errors)
    version.metrics = compute_metrics(problem, [to_solver_session(event, s) for s in rows])
    version.exact_optimum = False
    if version.source == "solver":
        version.source = "manual"
    return list(report.errors)


def _record(db: DbSession, version: ScheduleVersion, kind: str, summary: str, changes: list[dict], actor_id: int | None) -> None:
    """changes: [{key, before, after}];新建时 before 为 None,删除时 after 为 None。
    做了新修改后,已撤销的操作不能再重做,一并删除。"""
    for op in [o for o in version.operations if o.undone]:
        version.operations.remove(op)
    seq = max((o.seq for o in version.operations), default=0) + 1
    version.operations.append(ScheduleOperation(seq=seq, kind=kind, summary=summary[:300], changes=changes, actor_id=actor_id))


def _modified(s: RehearsalSession, before: dict) -> dict:
    return {"uid": s.uid, "key": _key(s), "before": before, "after": _state(s)}


GONE = "这条修改涉及的场次已不存在,无法撤销 / 重做"


def _find(version: ScheduleVersion, change: dict) -> RehearsalSession:
    """按固定身份 uid 找场次;早期记录没有 uid 时按数据库 id,再不行且身份唯一时按曲目 + 编号。"""
    uid = change.get("uid")
    if uid:
        for s in version.sessions:
            if s.uid == uid:
                return s
        raise HTTPException(status_code=409, detail=GONE)
    sid = change.get("session_id")
    for s in version.sessions:
        if sid is not None and s.id == sid:
            return s
    key = change.get("key")
    hits = [s for s in version.sessions if key is not None and _key(s) == key]
    if len(hits) == 1:
        return hits[0]
    raise HTTPException(status_code=409, detail=GONE)


def _flush(db: DbSession) -> None:
    """写入时撞上外键(如曲目刚被删除)→ 409,而不是 500。"""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="涉及的曲目刚被删除,请刷新后再试") from exc
    except StaleDataError as exc:  # 要改的场次刚被别处删除
        db.rollback()
        raise HTTPException(status_code=409, detail=STALE) from exc


def _apply(db: DbSession, event: Event, version: ScheduleVersion, change: dict, to: str) -> dict:
    """把一条变化应用到“前”(撤销)或“后”(重做)的状态:新建 / 删除 / 修改三种情况。

    返回更新后的这条记录:要移除某场时,先把它当前的样子(地点、缺席等,可能在记录之后又改过)存回
    另一侧,之后重做 / 撤销重建时才不会丢掉这些修改。"""
    side = "after" if to == "before" else "before"
    target, other = change[to], change[side]
    if target is None:
        row = _find(version, change)
        change = {**change, "uid": row.uid, side: _snapshot(row)}
        version.sessions.remove(row)
    elif other is None:
        if target.get("song_id") is not None and not any(x.id == target["song_id"] for x in event.songs):
            raise HTTPException(status_code=409, detail="这条修改涉及的曲目已被删除,无法撤销 / 重做")
        if target.get("uid") and any(s.uid == target["uid"] for s in version.sessions):
            raise HTTPException(status_code=409, detail="这一场已经存在,无法重复恢复")
        row = _create(version, target)
        _flush(db)
        change = {**change, "uid": row.uid}
    else:
        _restore(_find(version, change), target)
    return change


def _editable(s: RehearsalSession, action: str = "移动") -> None:
    if s.kind == "evaluation":
        raise HTTPException(status_code=422, detail=f"全员评估场由求解器安排,暂不支持手动{action}")
    if s.locked:
        raise HTTPException(status_code=422, detail=f"这场已锁定,先解锁再{action}")


def _fits(event: Event, d: date, start: int, duration: int) -> None:
    config = event_config(event)
    if duration < 1 or start < 0 or start + duration > config.slots_per_day:
        raise HTTPException(status_code=422, detail="超出每日排练窗口")
    if d not in set(config.formal_dates):
        raise HTTPException(status_code=422, detail="只能移到正规排练日")


def _current_errors(event: Event, version: ScheduleVersion) -> list[str]:
    return list(_live_report(event, version)[1].errors)


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
    claim(db, version)
    before_errors, before_metrics = _current_errors(event, version), dict(version.metrics or {})
    old = (session.date, session.start_slot, session.duration_slots)
    before = _state(session)
    session.date, session.start_slot, session.duration_slots = new_date, new_start, duration
    summary = f"移动 {_label(session)}:{_when(event, *old)} → {_when(event, new_date, new_start, duration)}"
    _record(db, version, "move", summary, [_modified(session, before)], actor_id)
    result = _finish(event, version, before_errors, before_metrics)
    db.commit()
    return result


def resize(
    db: DbSession,
    event: Event,
    version: ScheduleVersion,
    session: RehearsalSession,
    *,
    new_start: int,
    new_duration: int,
    actor_id: int | None,
) -> tuple[list[str], list[str]]:
    """上下拉调整时长(以小时为单位):同一天内改开始时间和 / 或时长。"""
    _editable(session, action="调整时长")
    _fits(event, session.date, new_start, new_duration)
    if (new_start, new_duration) == (session.start_slot, session.duration_slots):
        raise HTTPException(status_code=422, detail="时长没有变化")
    claim(db, version)
    before_errors, before_metrics = _current_errors(event, version), dict(version.metrics or {})
    before = _state(session)
    old_duration = session.duration_slots
    session.start_slot, session.duration_slots = new_start, new_duration
    summary = f"调整 {_label(session)} 时长:{old_duration}h → {new_duration}h({_when(event, session.date, new_start, new_duration)})"
    _record(db, version, "resize", summary, [_modified(session, before)], actor_id)
    result = _finish(event, version, before_errors, before_metrics)
    db.commit()
    return result


def _capped_absent(event: Event, version: ScheduleVersion, song) -> list[int]:  # noqa: ANN001
    """有「某人在这首最多参加 N 场」要求、且已参加满 N 场的成员,在新加的这场记为计划内缺席(与求解器一致)。"""
    caps = {}
    for r in event.rules:
        p = r.params or {}
        if r.enabled and r.type == "member_song_max_attendance" and p.get("song_id") == song.id:
            caps[p.get("member_id")] = int(p.get("n", 0))
    in_song = {m.id for m in song.members}
    in_event = {p.member_id for p in event.participants}
    out = []
    for member_id, cap in caps.items():
        if member_id not in in_song or member_id not in in_event:
            continue  # 规则留下来了,但这人已不在这首 / 这场演出里
        attended = sum(
            1 for s in version.sessions if s.kind == "formal" and s.song_id == song.id and member_id not in (s.absent_member_ids or [])
        )
        if attended >= cap:
            out.append(member_id)
    return out


def add(
    db: DbSession,
    event: Event,
    version: ScheduleVersion,
    *,
    song_id: int,
    new_date: date,
    new_start: int,
    new_duration: int,
    actor_id: int | None,
) -> tuple[RehearsalSession, list[str], list[str]]:
    """新建一场正规排练(像日历里新建事件):场数不必与曲目方案一致,不一致只作提醒。"""
    song = next((x for x in event.songs if x.id == song_id), None)
    if song is None:
        raise HTTPException(status_code=404, detail="曲目不存在")
    if song.code in set(version.skipped_songs or []):
        raise HTTPException(status_code=422, detail=f"这一版没有排曲目 {song.code}(求解时跳过了),不能单独加场")
    _fits(event, new_date, new_start, new_duration)
    claim(db, version)
    before_errors, before_metrics = _current_errors(event, version), dict(version.metrics or {})
    # 固定编号不复用:也避开修改记录里出现过的(删掉的场次撤销时要用回它的编号)
    used = [s.task_no or 0 for s in version.sessions if s.kind == "formal" and s.song_id == song.id]
    for op in version.operations:
        for c in op.changes or []:
            for snap in (c.get("before"), c.get("after"), c.get("key")):
                if isinstance(snap, dict) and snap.get("song_id") == song.id and snap.get("task_no"):
                    used.append(int(snap["task_no"]))
    task_no = max(used, default=0) + 1
    row = RehearsalSession(
        song_id=song.id, kind="formal", task_no=task_no, date=new_date, start_slot=new_start, duration_slots=new_duration
    )
    row.song = song
    row.absent_member_ids, row.attendance, row.locked, row.location = _capped_absent(event, version, song), None, False, ""
    version.sessions.append(row)
    _flush(db)
    summary = f"新建 {song.code}({_when(event, new_date, new_start, new_duration)})"
    _record(db, version, "add", summary, [{"uid": row.uid, "key": _key(row), "before": None, "after": _snapshot(row)}], actor_id)
    new, warnings = _finish(event, version, before_errors, before_metrics)
    db.commit()
    return row, new, warnings


def delete(
    db: DbSession, event: Event, version: ScheduleVersion, session: RehearsalSession, actor_id: int | None
) -> tuple[list[str], list[str]]:
    """删除一场正规排练(可撤销,撤销时原样恢复,包括地点与缺席)。"""
    _editable(session, action="删除")
    claim(db, version)
    before_errors, before_metrics = _current_errors(event, version), dict(version.metrics or {})
    snap = _snapshot(session)
    summary = f"删除 {_label(session)}({_when(event, session.date, session.start_slot, session.duration_slots)})"
    version.sessions.remove(session)
    db.flush()
    _record(
        db,
        version,
        "delete",
        summary,
        [{"uid": snap["uid"], "key": {k: snap[k] for k in ("kind", "song_id", "task_no")}, "before": snap, "after": None}],
        actor_id,
    )
    result = _finish(event, version, before_errors, before_metrics)
    db.commit()
    return result


def swap(
    db: DbSession, event: Event, version: ScheduleVersion, a: RehearsalSession, b: RehearsalSession, actor_id: int | None
) -> tuple[list[str], list[str]]:
    """交换两场的时间(各自保留时长)。"""
    if a.id == b.id:
        raise HTTPException(status_code=422, detail="不能和自己交换")
    if (a.date, a.start_slot) == (b.date, b.start_slot):
        raise HTTPException(status_code=422, detail="两场的时间相同,不需要交换")
    _editable(a)
    _editable(b)
    _fits(event, b.date, b.start_slot, a.duration_slots)
    _fits(event, a.date, a.start_slot, b.duration_slots)
    claim(db, version)
    before_errors, before_metrics = _current_errors(event, version), dict(version.metrics or {})
    ba, bb = _state(a), _state(b)
    where_a = _when(event, a.date, a.start_slot, a.duration_slots)
    where_b = _when(event, b.date, b.start_slot, b.duration_slots)
    (a.date, a.start_slot), (b.date, b.start_slot) = (b.date, b.start_slot), (a.date, a.start_slot)
    summary = f"交换 {_label(a)}(原 {where_a})与 {_label(b)}(原 {where_b})"
    _record(db, version, "swap", summary, [_modified(a, ba), _modified(b, bb)], actor_id)
    result = _finish(event, version, before_errors, before_metrics)
    db.commit()
    return result


def set_lock(db: DbSession, event: Event, version: ScheduleVersion, session: RehearsalSession, locked: bool, actor_id: int | None) -> None:
    if session.kind == "evaluation":
        raise HTTPException(status_code=422, detail="全员评估场不需要锁定")
    if session.locked == locked:
        return
    claim(db, version)
    before = _state(session)
    session.locked = locked
    _record(
        db,
        version,
        "lock",
        f"{'锁定' if locked else '解锁'} {_label(session)}({_when(event, session.date, session.start_slot, session.duration_slots)})",
        [_modified(session, before)],
        actor_id,
    )
    db.commit()


def undo(db: DbSession, event: Event, version: ScheduleVersion) -> str:
    done = [o for o in version.operations if not o.undone]
    if not done:
        raise HTTPException(status_code=409, detail="没有可以撤销的修改")
    op = done[-1]
    claim(db, version)
    op.changes = [_apply(db, event, version, c, "before") for c in reversed(list(op.changes))][::-1]
    _flush(db)  # 重建的场次要先写入,校验时才能读到它的曲目
    op.undone = True
    revalidate(event, version)
    db.commit()
    return op.summary


def redo(db: DbSession, event: Event, version: ScheduleVersion) -> str:
    undone = [o for o in version.operations if o.undone]
    if not undone:
        raise HTTPException(status_code=409, detail="没有可以重做的修改")
    op = undone[0]
    claim(db, version)
    op.changes = [_apply(db, event, version, c, "after") for c in list(op.changes)]
    _flush(db)
    op.undone = False
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


def revalidate_errors(event: Event, version: ScheduleVersion) -> list[str]:
    """按最新空闲与要求重查,把结果写回 validation_errors(不改其他字段);返回错误句子。"""
    _rows, report = _live_report(event, version)
    if list(report.errors) != list(version.validation_errors or []):
        version.validation_errors = list(report.errors)
    return list(report.errors)


def _live_report(event: Event, version: ScheduleVersion):  # noqa: ANN202
    """按最新空闲与要求检查整版。"""
    problem = version_problem(event, version)
    rows = list(version.sessions)
    return rows, validate_schedule(problem, [to_solver_session(event, s) for s in rows], version_level(problem, version))


def live_issues(event: Event, version: ScheduleVersion) -> list[IssueOut]:
    """按最新空闲与要求实时检查,问题对应到具体场次(界面标红)。"""
    rows, report = _live_report(event, version)
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
    rows, report = _live_report(event, version)
    out.issues = [
        IssueOut(
            code=i.message.split(" ", 1)[0] if i.message.startswith("V-") else "",
            message=_readable(i.message),
            session_ids=[rows[k].id for k in i.sessions],
        )
        for i in report.issues
    ]
    out.notices = [_readable(w) for w in report.warnings]
    out.validation_errors = list(report.errors)  # 以实时检查为准(保存的可能是旧规则下的结果)
    out.history = [
        OperationOut(id=o.id, seq=o.seq, kind=o.kind, summary=o.summary, undone=o.undone, created_at=o.created_at)
        for o in reversed(ops[-HISTORY_LIMIT:])
    ]
    out.can_undo = version.status == "draft" and any(not o.undone for o in ops)
    out.can_redo = version.status == "draft" and any(o.undone for o in ops)
    return out


# ---------- 批量修改:AI 修改与少改动重排的方案,一次应用、一次撤销;dry_run 只试算不保存 ----------
OP_KINDS = ("move", "resize", "swap", "add", "delete", "lock")


def _by_uid(version: ScheduleVersion, uid: object) -> RehearsalSession:
    for s in version.sessions:
        if uid and s.uid == uid:
            return s
    raise HTTPException(status_code=422, detail="方案里引用的场次不存在(可能已被修改或删除),请重新生成方案")


def _describe(event: Event, version: ScheduleVersion, op: dict) -> str:
    """给人看的一条修改,按应用这一条之前的状态描述(同一组里前面的修改已经生效)。"""
    kind = op.get("op")
    if kind == "add":
        song = next((x for x in event.songs if x.id == op.get("song_id")), None)
        name = "?" if song is None else song.code if song.name == song.code else f"{song.code} {song.name}"
        d = date.fromisoformat(str(op.get("date")))
        return f"新建 {name}({_when(event, d, int(op['start_slot']), int(op['duration_slots']))})"
    if kind == "swap":
        a, b = _by_uid(version, op.get("a")), _by_uid(version, op.get("b"))
        return (
            f"交换 {_label(a)}({_when(event, a.date, a.start_slot, a.duration_slots)})"
            f"与 {_label(b)}({_when(event, b.date, b.start_slot, b.duration_slots)})"
        )
    s = _by_uid(version, op.get("uid"))
    where = _when(event, s.date, s.start_slot, s.duration_slots)
    if kind == "move":
        d = date.fromisoformat(str(op.get("date")))
        return f"移动 {_label(s)}:{where} → {_when(event, d, int(op['start_slot']), s.duration_slots)}"
    if kind == "resize":
        return f"调整 {_label(s)} 时长:{where} → {_when(event, s.date, int(op['start_slot']), int(op['duration_slots']))}"
    if kind == "delete":
        return f"删除 {_label(s)}({where})"
    return f"{'锁定' if op.get('locked') else '解锁'} {_label(s)}({where})"


def apply_batch(
    db: DbSession,
    event: Event,
    version: ScheduleVersion,
    ops: list[dict],
    *,
    summary: str,
    actor_id: int | None,
    dry_run: bool = False,
) -> dict:
    """把一组修改作为一次修改应用(一条修改记录,一次撤销)。任一条无效则全部不执行(422)。
    dry_run=True 时只试算:在当前事务里应用、检查,然后回滚,数据库不变。
    返回 {new_issues, warnings, issues, notices, lines}。"""
    if not ops:
        raise HTTPException(status_code=422, detail="方案里没有任何修改")
    if len(ops) > 60:
        raise HTTPException(status_code=422, detail="一次最多 60 条修改")
    lines: list[str] = []
    if not dry_run:
        claim(db, version)
    before_errors, before_metrics = _current_errors(event, version), dict(version.metrics or {})
    touched: dict[str, dict] = {}  # uid → 第一次改动前的状态
    created: list[RehearsalSession] = []
    deleted: list[dict] = []

    def touch(s: RehearsalSession) -> None:
        if s.uid not in touched and s not in created:
            touched[s.uid] = _state(s)

    try:
        for op in ops:
            kind = op.get("op")
            if kind not in OP_KINDS:
                raise HTTPException(status_code=422, detail=f"未知的修改类型 {kind}")
            lines.append(_describe(event, version, op))
            if kind == "add":
                song = next((x for x in event.songs if x.id == op.get("song_id")), None)
                if song is None or song.code in set(version.skipped_songs or []):
                    raise HTTPException(status_code=422, detail="新建场次的曲目不存在或这一版没有排它")
                if op.get("song_code") is not None and op["song_code"] != song.code:
                    raise HTTPException(status_code=409, detail="方案里的曲目已经变了(可能被删除或重建),请重新生成方案")
                d = date.fromisoformat(str(op.get("date")))
                start, dur = int(op["start_slot"]), int(op["duration_slots"])
                _fits(event, d, start, dur)
                used = [s.task_no or 0 for s in version.sessions if s.kind == "formal" and s.song_id == song.id]
                used += [int(x.get("task_no") or 0) for x in deleted if x.get("song_id") == song.id]  # 本组里刚删掉的
                for o in version.operations:
                    for c in o.changes or []:
                        for snap in (c.get("before"), c.get("after"), c.get("key")):
                            if isinstance(snap, dict) and snap.get("song_id") == song.id and snap.get("task_no"):
                                used.append(int(snap["task_no"]))
                row = RehearsalSession(
                    song_id=song.id, kind="formal", task_no=max(used, default=0) + 1, date=d, start_slot=start, duration_slots=dur
                )
                row.song = song
                row.absent_member_ids, row.attendance, row.locked, row.location = _capped_absent(event, version, song), None, False, ""
                version.sessions.append(row)
                created.append(row)
                continue
            if kind == "swap":
                a, b = _by_uid(version, op.get("a")), _by_uid(version, op.get("b"))
                if a.id == b.id or (a.date, a.start_slot) == (b.date, b.start_slot):
                    raise HTTPException(status_code=422, detail="交换的两场无效(同一场或时间相同)")
                _editable(a)
                _editable(b)
                _fits(event, b.date, b.start_slot, a.duration_slots)
                _fits(event, a.date, a.start_slot, b.duration_slots)
                touch(a)
                touch(b)
                (a.date, a.start_slot), (b.date, b.start_slot) = (b.date, b.start_slot), (a.date, a.start_slot)
                continue
            s = _by_uid(version, op.get("uid"))
            if kind == "move":
                _editable(s)
                d = date.fromisoformat(str(op.get("date")))
                start = int(op["start_slot"])
                _fits(event, d, start, s.duration_slots)
                touch(s)
                s.date, s.start_slot = d, start
            elif kind == "resize":
                _editable(s, action="调整时长")
                start, dur = int(op["start_slot"]), int(op["duration_slots"])
                _fits(event, s.date, start, dur)
                touch(s)
                s.start_slot, s.duration_slots = start, dur
            elif kind == "lock":
                if s.kind == "evaluation":
                    raise HTTPException(status_code=422, detail="全员评估场不需要锁定")
                touch(s)
                s.locked = bool(op.get("locked"))
            elif kind == "delete":
                _editable(s, action="删除")
                snap = _snapshot(s)
                if s.uid in touched:  # 本批里先改过再删:撤销时恢复到改之前
                    snap.update(touched.pop(s.uid))
                if s in created:
                    created.remove(s)
                else:
                    deleted.append(snap)
                version.sessions.remove(s)
        _flush(db)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"方案格式不对:{exc}") from exc
    except HTTPException:
        db.rollback()
        raise

    changes: list[dict] = []
    for uid, before in touched.items():
        s = next(x for x in version.sessions if x.uid == uid)
        after = _state(s)
        if after != before:
            changes.append({"uid": uid, "key": _key(s), "before": before, "after": after})
    for row in created:
        changes.append({"uid": row.uid, "key": _key(row), "before": None, "after": _snapshot(row)})
    for snap in deleted:
        changes.append({"uid": snap["uid"], "key": {k: snap[k] for k in ("kind", "song_id", "task_no")}, "before": snap, "after": None})

    errors = revalidate(event, version)
    new = list(dict.fromkeys(_readable(e) for e in errors if e not in before_errors))
    warnings = metric_deltas(before_metrics, version.metrics or {})
    rows, report = _live_report(event, version)
    result = {
        "new_issues": new,
        "warnings": warnings,
        "issues": [_readable(i.message) for i in report.issues],
        "notices": [_readable(w) for w in report.warnings],
        "lines": lines,
    }
    if dry_run:
        db.rollback()
        return result
    if not changes:
        db.rollback()
        raise HTTPException(status_code=422, detail="这组修改不会改变任何东西")
    _record(db, version, "batch", summary or f"一次应用 {len(lines)} 条修改", changes, actor_id)
    db.commit()
    return result
