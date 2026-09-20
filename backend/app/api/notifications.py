"""站内通知(NOTIF-01)、一键催办(AVAIL-06)、定时提醒手动触发、优化目标列表(RULE-04)。"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from solver.types import DEFAULT_OBJECTIVES, OBJECTIVE_LABELS

from ..deps import DB, AdminUser, CurrentUser, SettingsDep
from ..models import Notification
from ..notify import remind_unsubmitted, run_due_reminders
from ..schemas import NotificationOut, ObjectiveOut, ReadIn, RemindOut, UnreadCountOut
from ..services import fmt_md
from ..utils import utcnow
from .events import load_event

router = APIRouter(tags=["notifications"])


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, type=n.type, title=n.title, body=n.body, link=n.link, event_id=n.event_id, created_at=n.created_at, read_at=n.read_at
    )


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(db: DB, user: CurrentUser, limit: int = 50) -> list[NotificationOut]:
    rows = db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(min(limit, 200))
    ).all()
    return [_out(n) for n in rows]


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
def unread_count(db: DB, user: CurrentUser) -> UnreadCountOut:
    n = db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    return UnreadCountOut(count=int(n))


@router.post("/notifications/read", response_model=UnreadCountOut)
def mark_read(body: ReadIn, db: DB, user: CurrentUser) -> UnreadCountOut:
    q = select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if body.ids:
        q = q.where(Notification.id.in_(body.ids))
    now = utcnow()
    rows = db.scalars(q).all()
    for n in rows:
        n.read_at = now
    db.commit()
    return unread_count(db, user)


@router.post("/events/{event_id}/remind", response_model=RemindOut)
def remind(event_id: int, db: DB, admin: AdminUser) -> RemindOut:
    event = load_event(db, event_id, admin)
    notified, without = remind_unsubmitted(db, event)
    db.commit()
    names = "、".join(without or notified)
    deadline = f" {fmt_md(event.availability_deadline)} 前" if event.availability_deadline else "尽快"
    copy_text = f"{names}:请在{deadline}登录 Season 填写空闲时间,谢谢!" if names else ""
    return RemindOut(notified=notified, without_account=without, copy_text=copy_text)


@router.post("/admin/run-reminders", response_model=UnreadCountOut)
def run_reminders_now(db: DB, _admin: AdminUser, settings: SettingsDep) -> UnreadCountOut:
    return UnreadCountOut(count=run_due_reminders(db, tz=settings.app_timezone))


@router.get("/objectives", response_model=list[ObjectiveOut])
def list_objectives(_admin: AdminUser) -> list[ObjectiveOut]:
    return [ObjectiveOut(key=k, label=v, default_on=k in DEFAULT_OBJECTIVES) for k, v in OBJECTIVE_LABELS.items()]
