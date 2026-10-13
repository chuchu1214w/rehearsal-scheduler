"""排练表发布(交互设计 A7)与成员端已发布排练表(M3 我的排练表)。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm.exc import StaleDataError

from .. import operations as ops
from ..deps import DB, AdminUser, CurrentUser
from ..models import ScheduleVersion
from ..notify import on_location_set, on_publish, on_unpublish
from ..schedule_edit import (
    check_move_strict,
    diff_versions,
    ensure_draft,
    find_session,
    fork_as_draft,
    participants_brief,
    schedule_conflicts,
)
from ..schemas import (
    ConflictsOut,
    DiffOut,
    EditResultOut,
    LocationIn,
    LocationOut,
    LockIn,
    MoveIn,
    OpAddIn,
    OpDeleteIn,
    OpLockIn,
    OpMoveIn,
    OpResizeIn,
    OpSwapIn,
    PublishedScheduleOut,
    RevisionIn,
    VersionOut,
)
from ..services import published_version, serialize_version
from ..utils import utcnow
from .events import load_event

router = APIRouter(tags=["schedule"])


def _get_version(db, version_id: int, admin) -> ScheduleVersion:  # noqa: ANN001
    version = db.get(ScheduleVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="排练表版本不存在")
    load_event(db, version.event_id, admin)
    return version


@router.post("/schedules/{version_id}/publish", response_model=VersionOut)
def publish_version(version_id: int, db: DB, admin: AdminUser, body: RevisionIn | None = None) -> VersionOut:
    version = _get_version(db, version_id, admin)
    ops.check_revision(version, body.expected_revision if body else None)
    # 发布门槛:按最新空闲与要求重新检查(保存的结果可能过时,如旧规则下的「场数不符」),有任何硬冲突都不能发布
    if version.status != "published" and ops.revalidate_errors(version.event, version):
        db.commit()
        raise HTTPException(status_code=422, detail="还有冲突没有解决,不能发布")
    if version.status == "published":
        raise HTTPException(status_code=409, detail="这一版已经是发布状态")
    ops.claim(db, version)  # 与同时进行的修改互斥:读到之后若有人改过,这次发布 409
    previous = None
    for other in version.event.versions:
        if other.id != version.id and other.status == "published":
            other.status = "archived"
            previous = other
    version.status = "published"
    version.published_at = utcnow()
    on_publish(db, version.event, version, previous)
    db.commit()
    return serialize_version(version.event, version)  # type: ignore[return-value]


@router.post("/schedules/{version_id}/unpublish", response_model=VersionOut)
def unpublish_version(version_id: int, db: DB, admin: AdminUser) -> VersionOut:
    version = _get_version(db, version_id, admin)
    if version.status != "published":
        raise HTTPException(status_code=409, detail="这一版不是发布状态")
    version.status = "draft"
    version.published_at = None
    on_unpublish(db, version.event, version)
    db.commit()
    return serialize_version(version.event, version)  # type: ignore[return-value]


@router.get("/events/{event_id}/schedule/published", response_model=PublishedScheduleOut)
def get_published(event_id: int, db: DB, user: CurrentUser) -> PublishedScheduleOut:
    event = load_event(db, event_id, user)
    version = published_version(event)
    if version is None:
        raise HTTPException(status_code=404, detail="排练表尚未发布")
    detail = serialize_version(event, version, detail=True)
    return PublishedScheduleOut(
        **detail.model_dump(),
        event_name=event.name,
        performance_date=event.performance_date,
        formal_start_date=event.formal_start_date,
        formal_end_date=event.performance_date - timedelta(days=2),
        eval_date=event.performance_date - timedelta(days=1),
        day_start_hour=event.day_start_hour,
        day_end_hour=event.day_end_hour,
        my_member_id=user.member_id if user.role != "admin" else None,
    )


# ---------- 调整(M5) ----------
@router.post("/schedules/{version_id}/sessions/{session_id}/move", response_model=EditResultOut)
def move_session(version_id: int, session_id: int, body: MoveIn, db: DB, admin: AdminUser) -> EditResultOut:
    """旧接口(iOS App 1.0):新引入硬冲突时拒绝。新界面用 /ops/move(冲突标出不拒绝)。"""
    version = _get_version(db, version_id, admin)
    event = version.event
    draft, forked = ensure_draft(db, event, version, admin.id)
    session = find_session(draft, session_id, original=version if forked else None)
    try:
        check_move_strict(event, draft, session, new_date=body.date, new_start=body.start_slot, new_duration=body.duration_slots)
    except HTTPException:
        db.rollback()  # 不留下刚复制出来的草稿
        raise
    _new, warnings = ops.move(
        db, event, draft, session, new_date=body.date, new_start=body.start_slot, new_duration=body.duration_slots, actor_id=admin.id
    )
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(event, draft), warnings=warnings, forked=forked)


@router.post("/schedules/{version_id}/sessions/{session_id}/lock", response_model=EditResultOut)
def lock_session(version_id: int, session_id: int, body: LockIn, db: DB, admin: AdminUser) -> EditResultOut:
    version = _get_version(db, version_id, admin)
    event = version.event
    draft, forked = ensure_draft(db, event, version, admin.id)
    session = find_session(draft, session_id, original=version if forked else None)
    ops.set_lock(db, event, draft, session, body.locked, admin.id)
    db.commit()
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(event, draft), warnings=[], forked=forked)


# ---------- 新界面:冲突标出不拒绝、交换、撤销 / 重做、恢复历史版本 ----------
def _editable_draft(db, version_id: int, expected: int | None, admin):  # noqa: ANN001, ANN202
    """返回(演出, 草稿, 是否新复制)。已发布 / 已归档的版本先复制成草稿;草稿要核对修改次数。"""
    version = _get_version(db, version_id, admin)
    if version.status == "draft":
        ops.check_revision(version, expected)
    draft, forked = ensure_draft(db, version.event, version, admin.id)
    return version, draft, forked


@router.post("/schedules/{version_id}/ops/move", response_model=EditResultOut)
def op_move(version_id: int, body: OpMoveIn, db: DB, admin: AdminUser) -> EditResultOut:
    version, draft, forked = _editable_draft(db, version_id, body.expected_revision, admin)
    session = find_session(draft, body.session_id, original=version if forked else None)
    new, warnings = ops.move(
        db,
        version.event,
        draft,
        session,
        new_date=body.date,
        new_start=body.start_slot,
        new_duration=body.duration_slots,
        actor_id=admin.id,
    )
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(version.event, draft), warnings=warnings, forked=forked, new_issues=new)


@router.post("/schedules/{version_id}/ops/resize", response_model=EditResultOut)
def op_resize(version_id: int, body: OpResizeIn, db: DB, admin: AdminUser) -> EditResultOut:
    version, draft, forked = _editable_draft(db, version_id, body.expected_revision, admin)
    session = find_session(draft, body.session_id, original=version if forked else None)
    new, warnings = ops.resize(
        db, version.event, draft, session, new_start=body.start_slot, new_duration=body.duration_slots, actor_id=admin.id
    )
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(version.event, draft), warnings=warnings, forked=forked, new_issues=new)


@router.post("/schedules/{version_id}/ops/add", response_model=EditResultOut)
def op_add(version_id: int, body: OpAddIn, db: DB, admin: AdminUser) -> EditResultOut:
    version, draft, forked = _editable_draft(db, version_id, body.expected_revision, admin)
    _row, new, warnings = ops.add(
        db,
        version.event,
        draft,
        song_id=body.song_id,
        new_date=body.date,
        new_start=body.start_slot,
        new_duration=body.duration_slots,
        actor_id=admin.id,
    )
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(version.event, draft), warnings=warnings, forked=forked, new_issues=new)


@router.post("/schedules/{version_id}/ops/delete", response_model=EditResultOut)
def op_delete(version_id: int, body: OpDeleteIn, db: DB, admin: AdminUser) -> EditResultOut:
    version, draft, forked = _editable_draft(db, version_id, body.expected_revision, admin)
    session = find_session(draft, body.session_id, original=version if forked else None)
    new, warnings = ops.delete(db, version.event, draft, session, admin.id)
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(version.event, draft), warnings=warnings, forked=forked, new_issues=new)


@router.post("/schedules/{version_id}/ops/swap", response_model=EditResultOut)
def op_swap(version_id: int, body: OpSwapIn, db: DB, admin: AdminUser) -> EditResultOut:
    version, draft, forked = _editable_draft(db, version_id, body.expected_revision, admin)
    original = version if forked else None
    a, b = find_session(draft, body.a, original=original), find_session(draft, body.b, original=original)
    new, warnings = ops.swap(db, version.event, draft, a, b, admin.id)
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(version.event, draft), warnings=warnings, forked=forked, new_issues=new)


@router.post("/schedules/{version_id}/ops/lock", response_model=EditResultOut)
def op_lock(version_id: int, body: OpLockIn, db: DB, admin: AdminUser) -> EditResultOut:
    version, draft, forked = _editable_draft(db, version_id, body.expected_revision, admin)
    session = find_session(draft, body.session_id, original=version if forked else None)
    ops.set_lock(db, version.event, draft, session, body.locked, admin.id)
    db.commit()
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(version.event, draft), warnings=[], forked=forked)


def _draft_only(db, version_id: int, expected: int | None, admin) -> ScheduleVersion:  # noqa: ANN001
    version = _get_version(db, version_id, admin)
    if version.status != "draft":
        raise HTTPException(status_code=409, detail="只有草稿可以撤销 / 重做")
    ops.check_revision(version, expected)
    return version


@router.post("/schedules/{version_id}/undo", response_model=EditResultOut)
def undo(version_id: int, body: RevisionIn, db: DB, admin: AdminUser) -> EditResultOut:
    version = _draft_only(db, version_id, body.expected_revision, admin)
    summary = ops.undo(db, version.event, version)
    db.refresh(version)
    return EditResultOut(version=ops.admin_detail(version.event, version), warnings=[f"已撤销:{summary}"], forked=False)


@router.post("/schedules/{version_id}/redo", response_model=EditResultOut)
def redo(version_id: int, body: RevisionIn, db: DB, admin: AdminUser) -> EditResultOut:
    version = _draft_only(db, version_id, body.expected_revision, admin)
    summary = ops.redo(db, version.event, version)
    db.refresh(version)
    return EditResultOut(version=ops.admin_detail(version.event, version), warnings=[f"已重做:{summary}"], forked=False)


@router.post("/schedules/{version_id}/fork", response_model=EditResultOut, status_code=201)
def fork(version_id: int, db: DB, admin: AdminUser) -> EditResultOut:
    """以任意版本(含历史版本)为底稿复制一个新草稿,原版本不变。"""
    version = _get_version(db, version_id, admin)
    draft = fork_as_draft(db, version.event, version, admin.id, source="copy")
    ops.revalidate(version.event, draft)
    draft.source = "copy"
    db.commit()
    db.refresh(draft)
    return EditResultOut(version=ops.admin_detail(version.event, draft), warnings=[], forked=True)


@router.get("/schedules/{version_id}/diff", response_model=DiffOut)
def version_diff(version_id: int, db: DB, admin: AdminUser, against: int | None = None) -> DiffOut:
    version = _get_version(db, version_id, admin)
    event = version.event
    other: ScheduleVersion | None
    if against is not None:
        other = db.get(ScheduleVersion, against)
        if other is None or other.event_id != event.id:
            raise HTTPException(status_code=404, detail="对比的版本不存在")
    else:
        other = db.get(ScheduleVersion, version.parent_version_id) if version.parent_version_id else None
        if other is None:
            other = next((v for v in event.versions if v.status == "published" and v.id != version.id), None)
        if other is None:
            other = next((v for v in reversed(event.versions) if v.version_no < version.version_no), None)
    if other is None:
        raise HTTPException(status_code=404, detail="没有可对比的版本")
    return diff_versions(event, version, other)


@router.get("/events/{event_id}/schedule/conflicts", response_model=ConflictsOut)
def schedule_conflict_list(event_id: int, db: DB, admin: AdminUser, version_id: int | None = None) -> ConflictsOut:
    event = load_event(db, event_id, admin)
    version: ScheduleVersion | None
    if version_id is not None:
        version = db.get(ScheduleVersion, version_id)
        if version is None or version.event_id != event.id:
            raise HTTPException(status_code=404, detail="排练表版本不存在")
    else:
        version = published_version(event) or (event.versions[-1] if event.versions else None)
    if version is None:
        raise HTTPException(status_code=404, detail="还没有排练表")
    items = schedule_conflicts(event, version)
    ids = {c.member.id for c in items}
    return ConflictsOut(
        version_id=version.id,
        version_no=version.version_no,
        status=version.status,
        items=items,
        members=[m for m in participants_brief(event) if m.id in ids],
    )


@router.post("/schedules/{version_id}/sessions/{session_id}/location", response_model=LocationOut)
def set_location(version_id: int, session_id: int, body: LocationIn, db: DB, admin: AdminUser) -> LocationOut:
    """填写 / 修改排练地点:地点是附加信息,任何版本都原地改、不产生新版本;已发布版本会通知这场的成员。"""
    version = _get_version(db, version_id, admin)
    event = version.event
    session = find_session(version, session_id)
    session.location = body.location.strip()
    try:
        db.flush()
    except StaleDataError as exc:  # 这场刚被删除(另一个窗口)
        db.rollback()
        raise HTTPException(status_code=409, detail="这一场刚被修改或删除,请刷新后再试") from exc
    notified = on_location_set(db, event, version, session)
    db.commit()
    db.refresh(version)
    return LocationOut(version=ops.admin_detail(event, version), notified=notified)
