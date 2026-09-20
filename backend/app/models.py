"""数据模型(开发文档 §6)。已实现:账号、名册、演出、曲目、特殊要求、空闲填报;求解、排练表在 M3/M4 加入。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .utils import utcnow

# 每次改表结构 +1;启动时与 meta 表比对,不一致就提示删库重建(开发阶段;有真实数据后改用 Alembic)
SCHEMA_VERSION = 4  # 3:新增 solve_jobs / schedule_versions / rehearsal_sessions(可从 2 自动迁移)


class Base(DeclarativeBase):
    pass


class Meta(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(String(64))


song_members = Table(
    "song_members",
    Base.metadata,
    Column("song_id", ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True),
    Column("member_id", ForeignKey("members.id"), primary_key=True),
)


class Member(Base):
    """名册成员;不一定有登录账号。前端没有独立名册页,成员在演出里添加。"""

    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User | None] = relationship(back_populates="member")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))  # admin / member
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)  # 管理员设的初始密码,首次登录提示修改
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    calendar_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)  # 日历订阅令牌(M4)

    member: Mapped[Member | None] = relationship(back_populates="user")
    sessions: Mapped[list[AuthSession]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    """服务端会话:Cookie 里只有随机令牌,数据库只存其哈希。"""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="sessions")


class LoginFailure(Base):
    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(primary_key=True)
    username_lower: Mapped[str] = mapped_column(String(32), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    """一场演出。"""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    performance_date: Mapped[date] = mapped_column(Date)
    formal_start_date: Mapped[date] = mapped_column(Date)
    availability_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)  # 填报截止日;到期只提醒不锁定
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul")
    slot_minutes: Mapped[int] = mapped_column(Integer, default=60)
    day_start_hour: Mapped[int] = mapped_column(Integer, default=10)
    day_end_hour: Mapped[int] = mapped_column(Integer, default=23)
    status: Mapped[str] = mapped_column(String(16), default="preparing")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    participants: Mapped[list[EventMember]] = relationship(back_populates="event", cascade="all, delete-orphan")
    songs: Mapped[list[Song]] = relationship(back_populates="event", cascade="all, delete-orphan", order_by="Song.sort_order")
    rules: Mapped[list[Rule]] = relationship(back_populates="event", cascade="all, delete-orphan", order_by="Rule.sort_order")
    availability: Mapped[list[AvailabilityDay]] = relationship(cascade="all, delete-orphan")
    jobs: Mapped[list[SolveJob]] = relationship(back_populates="event", cascade="all, delete-orphan", order_by="SolveJob.id")
    versions: Mapped[list[ScheduleVersion]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="ScheduleVersion.version_no"
    )


class EventMember(Base):
    __tablename__ = "event_members"

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
    availability_submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    event: Mapped[Event] = relationship(back_populates="participants")
    member: Mapped[Member] = relationship(lazy="joined")


class Song(Base):
    __tablename__ = "songs"
    __table_args__ = (UniqueConstraint("event_id", "code", name="uq_song_event_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    difficulty: Mapped[str] = mapped_column(String(8))
    session_plan: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    event: Mapped[Event] = relationship(back_populates="songs")
    members: Mapped[list[Member]] = relationship(secondary=song_members, order_by="Member.sort_order")


class Rule(Base):
    """特殊排程要求(交互设计 §4④):type + params 存储,人话句子由 services.rules 生成。"""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    event: Mapped[Event] = relationship(back_populates="rules")


class AvailabilityDay(Base):
    """某成员在某演出某天的空闲:slots 为每格一个字符,0 不可排 / 1 可排 / 2 尽量避开。"""

    __tablename__ = "availability_days"

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    slots: Mapped[str] = mapped_column(String(48))
    filled_by: Mapped[str] = mapped_column(String(8), default="member")  # member / admin
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SolveJob(Base):
    """一次求解任务(交互设计 A6):在子进程中运行,进度与结果写回本表。"""

    __tablename__ = "solve_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued / running / succeeded / infeasible / failed / cancelled
    options: Mapped[dict] = mapped_column(JSON, default=dict)  # only_ready_songs 等
    params_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    progress: Mapped[str] = mapped_column(String(200), default="")
    stage_records: Mapped[list] = mapped_column(JSON, default=list)
    attempts: Mapped[list] = mapped_column(JSON, default=list)
    ladder_level_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_songs: Mapped[list] = mapped_column(JSON, default=list)
    diagnosis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str] = mapped_column(String(400), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    event: Mapped[Event] = relationship(back_populates="jobs")


class ScheduleVersion(Base):
    """排练表版本(不可变):求解产出的草稿;M4 增加人工修改、重排、发布。"""

    __tablename__ = "schedule_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="solver")  # solver / manual / resolve / copy
    parent_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft / published / archived
    level_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exact_optimum: Mapped[bool] = mapped_column(Boolean, default=False)
    objective_values: Mapped[dict] = mapped_column(JSON, default=dict)
    stage_records: Mapped[list] = mapped_column(JSON, default=list)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    skipped_songs: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    event: Mapped[Event] = relationship(back_populates="versions")
    sessions: Mapped[list[RehearsalSession]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="(RehearsalSession.date, RehearsalSession.start_slot)"
    )


class RehearsalSession(Base):
    """排练表中的一场:正规排练(有曲目)或全员评估(无曲目)。"""

    __tablename__ = "rehearsal_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("schedule_versions.id", ondelete="CASCADE"))
    song_id: Mapped[int | None] = mapped_column(ForeignKey("songs.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(12))  # formal / evaluation
    task_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date: Mapped[date] = mapped_column(Date)
    start_slot: Mapped[int] = mapped_column(Integer)
    duration_slots: Mapped[int] = mapped_column(Integer)
    absent_member_ids: Mapped[list] = mapped_column(JSON, default=list)
    attendance: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 评估场:member_id -> [start_slot, end_slot]
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    version: Mapped[ScheduleVersion] = relationship(back_populates="sessions")
    song: Mapped[Song | None] = relationship()
