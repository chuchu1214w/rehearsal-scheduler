"""排练表发布(交互设计 A7)与成员端已发布排练表(M3 我的排练表)。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException

from ..deps import DB, AdminUser, CurrentUser
from ..models import ScheduleVersion
from ..schemas import PublishedScheduleOut, VersionOut
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
    for other in version.event.versions:
        if other.id != version.id and other.status == "published":
            other.status = "archived"
    version.status = "published"
    version.published_at = utcnow()
    db.commit()
    return serialize_version(version.event, version)  # type: ignore[return-value]


@router.post("/schedules/{version_id}/unpublish", response_model=VersionOut)
def unpublish_version(version_id: int, db: DB, admin: AdminUser) -> VersionOut:
    version = _get_version(db, version_id, admin)
    if version.status != "published":
        raise HTTPException(status_code=409, detail="这一版不是发布状态")
    version.status = "draft"
    version.published_at = None
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
