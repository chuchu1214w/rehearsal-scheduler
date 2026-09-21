"""站内通知(NOTIF-01)与定时提醒(NOTIF-02)。

通知只写数据库,不发邮件 / 推送;前端每分钟拉一次未读数。提醒类通知带 dedupe_key,重复运行不会重复发。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Event, EventMember, Notification, ScheduleVersion, User
from .schedule_edit import diff_versions, schedule_conflicts
from .services import fmt_md, published_version, sorted_participants


# ---------- 基础 ----------
def notify(
    db: Session,
    user_ids: list[int],
    *,
    type: str,  # noqa: A002
    title: str,
    body: str = "",
    link: str = "",
    event_id: int | None = None,
    dedupe_key: str | None = None,
) -> int:
    """给一组用户各发一条通知;dedupe_key 已存在的用户跳过。返回实际发出的条数。"""
    sent = 0
    for uid in dict.fromkeys(user_ids):
        if dedupe_key and db.scalar(select(Notification.id).where(Notification.user_id == uid, Notification.dedupe_key == dedupe_key)):
            continue
        db.add(
            Notification(
                user_id=uid, type=type, title=title[:200], body=body[:1000], link=link[:200], event_id=event_id, dedupe_key=dedupe_key
            )
        )
        sent += 1
    return sent


def admin_ids(db: Session) -> list[int]:
    return list(db.scalars(select(User.id).where(User.role == "admin", User.is_active.is_(True))).all())


def member_user_id(p: EventMember) -> int | None:
    u = p.member.user
    return u.id if u is not None and u.is_active else None


def participants_with_accounts(event: Event) -> list[tuple[EventMember, int]]:
    out = []
    for p in sorted_participants(event):
        uid = member_user_id(p)
        if uid is not None:
            out.append((p, uid))
    return out


# ---------- 事件触发 ----------
def on_publish(db: Session, event: Event, version: ScheduleVersion, previous: ScheduleVersion | None) -> int:
    """发布:通知每位有账号的成员;若之前发布过,附上「你的 N 场有变动」。"""
    diff = diff_versions(event, version, previous) if previous is not None else None
    sent = 0
    for p, uid in participants_with_accounts(event):
        mine = [
            s
            for s in version.sessions
            if s.kind == "formal"
            and s.song is not None
            and any(m.id == p.member_id for m in s.song.members)
            and p.member_id not in (s.absent_member_ids or [])
        ]
        body = f"你有 {len(mine)} 场排练 + 1 场全员评估。"
        if diff is not None:
            changes = [i for i in diff.items if _touches(i, p.member_id)]
            body += (
                f"较 v{previous.version_no}:你的 {len(changes)} 场有变动。" if changes else f"较 v{previous.version_no} 你的场次没有变化。"
            )
        sent += notify(
            db,
            [uid],
            type="published",
            title=f"排练表 v{version.version_no} 已发布 · {event.name}",
            body=body,
            link=f"/schedule?event={event.id}",
            event_id=event.id,
        )
    return sent


def _touches(item, member_id: int) -> bool:  # noqa: ANN001
    for s in (item.before, item.after):
        if s is None:
            continue
        if s.kind == "evaluation":
            return True
        if any(m.id == member_id for m in s.members):
            return True
    return False


def on_unpublish(db: Session, event: Event, version: ScheduleVersion) -> int:
    ids = [uid for _, uid in participants_with_accounts(event)]
    return notify(
        db,
        ids,
        type="unpublished",
        title=f"排练表 v{version.version_no} 已撤回 · {event.name}",
        body="管理员撤回了这一版,新的排练表发布后会再通知你。",
        link=f"/schedule?event={event.id}",
        event_id=event.id,
    )


def on_availability_submitted(db: Session, event: Event, p: EventMember, actor: User) -> int:
    """成员(本人)提交或重新提交空闲后:排练表已发布且受影响 → 通知管理员;全员提交完成 → 通知管理员。"""
    if actor.role == "admin":
        return 0
    sent = 0
    name = p.member.display_name
    published = published_version(event)
    if published is not None:
        hits = [c for c in schedule_conflicts(event, published) if c.member.id == p.member_id]
        if hits:
            detail = ";".join(f"{fmt_md(c.session.date)} {c.session.time} {c.session.song_code or '评估'}" for c in hits[:4])
            sent += notify(
                db,
                admin_ids(db),
                type="conflict",
                title=f"{name} 修改了空闲,{len(hits)} 场受影响 · {event.name}",
                body=detail,
                link=f"/events/{event.id}/schedule",
                event_id=event.id,
            )
    participants = list(event.participants)
    if participants and all(x.availability_submitted_at is not None for x in participants):
        sent += notify(
            db,
            admin_ids(db),
            type="all_submitted",
            title=f"全员已提交空闲 · {event.name}",
            body=f"{len(participants)} 人已全部提交,可以排程了。",
            link=f"/events/{event.id}/solve",
            event_id=event.id,
            dedupe_key=f"all-submitted:{event.id}:{'-'.join(str(x.member_id) for x in sorted(participants, key=lambda x: x.member_id))}",
        )
    return sent


def on_joined(db: Session, event: Event, members: list[EventMember]) -> int:
    """被加入演出 / 刚开通账号:提醒填空闲。"""
    sent = 0
    for p in members:
        uid = member_user_id(p)
        if uid is None or p.availability_submitted_at is not None:
            continue
        deadline = f",请在 {fmt_md(event.availability_deadline)} 前填写空闲时间" if event.availability_deadline else ",请填写空闲时间"
        sent += notify(
            db,
            [uid],
            type="joined",
            title=f"你被加入演出「{event.name}」",
            body=f"演出 {fmt_md(event.performance_date)}{deadline}。",
            link=f"/events/{event.id}/availability",
            event_id=event.id,
            dedupe_key=f"joined:{event.id}:{p.member_id}",
        )
    return sent


def on_location_set(db: Session, event: Event, version: ScheduleVersion, session) -> int:  # noqa: ANN001
    """已发布版本的某场填了地点:通知这场的到场成员。同一场同一地点只通知一次。"""
    if version.status != "published" or not session.location:
        return 0
    if session.kind == "evaluation":
        ids = {int(k) for k in (session.attendance or {})}
        what = "全员评估"
    else:
        if session.song is None:
            return 0
        absent = set(session.absent_member_ids or [])
        ids = {m.id for m in session.song.members if m.id not in absent}
        what = f"{session.song.code} {session.song.name}"
    users = [uid for p, uid in participants_with_accounts(event) if p.member_id in ids]
    start_h = event.day_start_hour + session.start_slot
    when = f"{fmt_md(session.date)} {start_h:02d}:00–{start_h + session.duration_slots:02d}:00"
    return notify(
        db,
        users,
        type="location",
        title=f"排练地点:{session.location}",
        body=f"{when} {what} · {event.name}",
        link=f"/schedule/day/{session.date.isoformat()}?event={event.id}",
        event_id=event.id,
        dedupe_key=f"location:{session.id}:{session.location}",
    )


def remind_unsubmitted(db: Session, event: Event) -> tuple[list[str], list[str]]:
    """一键催办(AVAIL-06):给未提交且有账号的成员发通知。返回 (已通知, 没有账号)。"""
    notified: list[str] = []
    without: list[str] = []
    for p in sorted_participants(event):
        if p.availability_submitted_at is not None:
            continue
        uid = member_user_id(p)
        if uid is None:
            without.append(p.member.display_name)
            continue
        deadline = f"截止 {fmt_md(event.availability_deadline)}," if event.availability_deadline else ""
        notify(
            db,
            [uid],
            type="remind",
            title=f"请填写空闲时间 · {event.name}",
            body=f"{deadline}管理员在等你的空闲时间,大约 2 分钟就能填完。",
            link=f"/events/{event.id}/availability",
            event_id=event.id,
        )
        notified.append(p.member.display_name)
    return notified, without


# ---------- 定时提醒 ----------
def run_due_reminders(db: Session, today: date | None = None, tz: str = "Asia/Seoul") -> int:
    """每次运行都可重复调用:填报截止前一天 / 当天 / 已过;排练前一天晚上给每人发明天的日程。"""
    today = today or datetime.now(ZoneInfo(tz)).date()
    sent = 0
    for event in db.scalars(select(Event)).all():
        if event.performance_date < today:
            continue
        sent += _deadline_reminders(db, event, today)
        sent += _day_before_reminders(db, event, today)
    db.commit()
    return sent


def _deadline_reminders(db: Session, event: Event, today: date) -> int:
    dl = event.availability_deadline
    if dl is None:
        return 0
    days_left = (dl - today).days
    if days_left > 1:
        return 0
    stage = "tomorrow" if days_left == 1 else "today" if days_left == 0 else "overdue"
    title = {"tomorrow": "明天就是填报截止日", "today": "今天是填报截止日", "overdue": "填报已过截止日"}[stage] + f" · {event.name}"
    sent = 0
    pending = [p for p in sorted_participants(event) if p.availability_submitted_at is None]
    for p in pending:
        uid = member_user_id(p)
        if uid is None:
            continue
        sent += notify(
            db,
            [uid],
            type="deadline",
            title=title,
            body=f"截止 {fmt_md(dl)};仍可填写,但请尽快,管理员在等你。",
            link=f"/events/{event.id}/availability",
            event_id=event.id,
            dedupe_key=f"deadline:{event.id}:{p.member_id}:{stage}",
        )
    if stage == "overdue" and pending:
        names = "、".join(p.member.display_name for p in pending)
        sent += notify(
            db,
            admin_ids(db),
            type="deadline",
            title=f"填报已过截止日,还有 {len(pending)} 人未提交 · {event.name}",
            body=names,
            link=f"/events/{event.id}/progress",
            event_id=event.id,
            dedupe_key=f"deadline-admin:{event.id}",
        )
    return sent


def _day_before_reminders(db: Session, event: Event, today: date) -> int:
    version = published_version(event)
    if version is None:
        return 0
    tomorrow = today + timedelta(days=1)
    sessions = [s for s in version.sessions if s.date == tomorrow]
    if not sessions:
        return 0
    sent = 0
    for p, uid in participants_with_accounts(event):
        lines: list[str] = []
        for s in sessions:
            if s.kind == "evaluation":
                att = (s.attendance or {}).get(str(p.member_id))
                if att is not None:
                    lines.append(f"{event.day_start_hour + int(att[0]):02d}:00–{event.day_start_hour + int(att[1]):02d}:00 全员评估")
                continue
            if s.song is None or not any(m.id == p.member_id for m in s.song.members) or p.member_id in (s.absent_member_ids or []):
                continue
            start_h = event.day_start_hour + s.start_slot
            lines.append(f"{start_h:02d}:00–{start_h + s.duration_slots:02d}:00 {s.song.code} {s.song.name}")
        if not lines:
            continue
        sent += notify(
            db,
            [uid],
            type="tomorrow",
            title=f"明天有 {len(lines)} 场排练 · {fmt_md(tomorrow)}",
            body=";".join(lines),
            link=f"/schedule/day/{tomorrow.isoformat()}?event={event.id}",
            event_id=event.id,
            dedupe_key=f"tomorrow:{event.id}:{p.member_id}:{tomorrow.isoformat()}",
        )
    return sent
