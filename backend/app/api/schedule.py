"""排练表发布(交互设计 A7)与成员端已发布排练表(M3 我的排练表)。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException

from ..deps import DB, AdminUser, CurrentUser
from ..models import ScheduleVersion
from ..notify import on_location_set, on_publish, on_unpublish
from ..schedule_edit import apply_move, diff_versions, ensure_draft, find_session, participants_brief, schedule_conflicts
from ..schemas import ConflictsOut, DiffOut, EditResultOut, LocationIn, LocationOut, LockIn, MoveIn, PublishedScheduleOut, VersionOut
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
def publish_version(version_id: int, db: DB, admin: AdminUser) -> VersionOut:
    version = _get_version(db, version_id, admin)
    if version.validation_errors:
        raise HTTPException(status_code=422, detail="校验未通过的版本不能发布")
    if version.status == "published":
        raise HTTPException(status_code=409, detail="这一版已经是发布状态")
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
    version = _get_version(db, version_id, admin)
    event = version.event
    draft, forked = ensure_draft(db, event, version, admin.id)
    session = find_session(draft, session_id, original=version if forked else None)
    warnings = apply_move(db, event, draft, session, new_date=body.date, new_start=body.start_slot, new_duration=body.duration_slots)
    db.refresh(draft)
    return EditResultOut(version=serialize_version(event, draft, detail=True), warnings=warnings, forked=forked)  # type: ignore[arg-type]


@router.post("/schedules/{version_id}/sessions/{session_id}/lock", response_model=EditResultOut)
def lock_session(version_id: int, session_id: int, body: LockIn, db: DB, admin: AdminUser) -> EditResultOut:
    version = _get_version(db, version_id, admin)
    event = version.event
    draft, forked = ensure_draft(db, event, version, admin.id)
    session = find_session(draft, session_id, original=version if forked else None)
    if session.kind == "evaluation":
        raise HTTPException(status_code=422, detail="全员评估场不需要锁定")
    session.locked = body.locked
    db.commit()
    db.refresh(draft)
    return EditResultOut(version=serialize_version(event, draft, detail=True), warnings=[], forked=forked)  # type: ignore[arg-type]


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
    db.flush()
    notified = on_location_set(db, event, version, session)
    db.commit()
    db.refresh(version)
    return LocationOut(version=serialize_version(event, version, detail=True), notified=notified)  # type: ignore[arg-type]
