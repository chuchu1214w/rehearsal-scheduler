"""请求 / 响应模型(Pydantic v2)。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from .utils import USERNAME_RE, normalize_name

Difficulty = Literal["简单", "一般", "困难"]
DIFFICULTIES: tuple[Difficulty, ...] = ("简单", "一般", "困难")
EventStatus = Literal["preparing", "collecting", "scheduling", "published", "closed"]
Password = Annotated[str, Field(min_length=8, max_length=128)]


def _check_username(value: str) -> str:
    value = value.strip()
    if not USERNAME_RE.match(value):
        raise ValueError("用户名只能包含中英文、数字、下划线、点和短横线,长度 1–32")
    return value


def _check_plan(plan: list[int], what: str) -> list[int]:
    if not plan:
        raise ValueError(f"{what}至少要有一场")
    if any(not isinstance(x, int) or x < 1 or x > 12 for x in plan):
        raise ValueError(f"{what}每场时长必须是 1–12 的整数")
    return list(plan)


# ---------- 账号 ----------
class SetupStatus(BaseModel):
    needs_setup: bool


class SetupIn(BaseModel):
    username: str
    password: Password

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return _check_username(v)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: Password


class UserOut(BaseModel):
    id: int
    username: str
    role: Literal["admin", "member"]
    is_active: bool
    must_change_password: bool
    member_id: int | None
    member_name: str | None
    created_at: datetime
    last_login_at: datetime | None


class AccountOut(BaseModel):
    user_id: int
    username: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None


class AccountCreateIn(BaseModel):
    """管理员为成员开通账号:用户名默认昵称,初始密码由管理员输入。"""

    username: str | None = None
    password: Password

    @field_validator("username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        return None if v is None or not v.strip() else _check_username(v)


class AccountCredentialsOut(BaseModel):
    """开通 / 重置后返回一次,供管理员复制发给成员。"""

    member_id: int
    display_name: str
    username: str
    password: str
    copy_text: str


class BatchAccountsIn(BaseModel):
    password: Password


class AccountResetIn(BaseModel):
    password: Password


class AccountPatch(BaseModel):
    is_active: bool


# ---------- 名册 ----------
class MemberIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)
    aliases: list[str] = []
    note: str = Field(default="", max_length=500)
    active: bool = True

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = normalize_name(v)
        if not v:
            raise ValueError("昵称不能为空")
        return v

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for a in v:
            a = normalize_name(a)
            if a and a not in out:
                out.append(a)
        return out


class MemberPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    aliases: list[str] | None = None
    note: str | None = Field(default=None, max_length=500)
    active: bool | None = None
    sort_order: int | None = None

    _name = field_validator("display_name")(lambda cls, v: normalize_name(v) if v is not None else v)  # noqa: E731
    _aliases = field_validator("aliases")(MemberIn._aliases.__func__)  # type: ignore[attr-defined]


class MemberOut(BaseModel):
    id: int
    display_name: str
    aliases: list[str]
    note: str
    active: bool
    sort_order: int
    account: AccountOut | None


class MemberBrief(BaseModel):
    id: int
    display_name: str


# ---------- 演出 ----------
class EventSettings(BaseModel):
    soft_daily_limit: int = Field(default=8, ge=1, le=24)
    hard_daily_limit: int = Field(default=8, ge=1, le=24)
    merge_visit_gap: int = Field(default=1, ge=0, le=12)
    free_gap: int = Field(default=1, ge=0, le=12)
    eval_durations: list[int] = [3, 2]
    eval_min_contiguous: int = Field(default=2, ge=1, le=12)
    same_song_different_days: bool = True
    difficulty_templates: dict[str, list[int]] = {"困难": [3, 3, 3], "一般": [3, 2, 2], "简单": [2, 2]}
    stage_time_limit: float = Field(default=90.0, ge=5, le=600)

    @field_validator("eval_durations")
    @classmethod
    def _eval(cls, v: list[int]) -> list[int]:
        v = _check_plan(v, "评估场时长")
        if len(set(v)) != len(v):
            raise ValueError("评估场时长不能重复")
        return v

    @field_validator("difficulty_templates")
    @classmethod
    def _templates(cls, v: dict[str, list[int]]) -> dict[str, list[int]]:
        missing = [d for d in DIFFICULTIES if d not in v]
        if missing:
            raise ValueError("难度模板缺少:" + "、".join(missing))
        extra = [k for k in v if k not in DIFFICULTIES]
        if extra:
            raise ValueError("未知的难度:" + "、".join(extra))
        return {k: _check_plan(v[k], f"难度「{k}」的场次方案") for k in DIFFICULTIES}

    @model_validator(mode="after")
    def _limits(self) -> EventSettings:
        if self.hard_daily_limit < self.soft_daily_limit:
            raise ValueError("单日硬上限不能小于软上限")
        return self


class EventBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    performance_date: date
    formal_start_date: date
    availability_deadline: date | None = None  # 缺省时取演出前 10 天
    timezone: str = "Asia/Seoul"
    slot_minutes: Literal[60] = 60
    day_start_hour: int = Field(default=10, ge=0, le=23)
    day_end_hour: int = Field(default=23, ge=1, le=24)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = normalize_name(v)
        if not v:
            raise ValueError("演出名称不能为空")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"无法识别的时区:{v}") from exc
        return v


class EventIn(EventBase):
    settings: EventSettings = EventSettings()
    member_ids: list[int] = []  # 新建时可直接带入人员(向导「带入上次演出的人员」)


class EventPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    performance_date: date | None = None
    formal_start_date: date | None = None
    availability_deadline: date | None = None
    clear_availability_deadline: bool = False
    timezone: str | None = None
    day_start_hour: int | None = Field(default=None, ge=0, le=23)
    day_end_hour: int | None = Field(default=None, ge=1, le=24)
    status: EventStatus | None = None
    settings: EventSettings | None = None

    _tz = field_validator("timezone")(lambda cls, v: EventBase._tz.__func__(cls, v) if v is not None else v)  # type: ignore[attr-defined]


class EventCloneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    performance_date: date
    formal_start_date: date


StepState = Literal["done", "current", "todo"]


class StepOut(BaseModel):
    no: int
    key: str
    label: str
    state: StepState
    summary: str


class EventOut(BaseModel):
    id: int
    name: str
    performance_date: date
    formal_start_date: date
    formal_end_date: date
    eval_date: date
    formal_day_count: int
    availability_deadline: date | None
    days_until_performance: int
    timezone: str
    slot_minutes: int
    day_start_hour: int
    day_end_hour: int
    slots_per_day: int
    status: EventStatus
    settings: EventSettings
    member_count: int
    account_count: int
    submitted_count: int
    song_count: int
    session_count: int
    rule_count: int
    current_step: int
    steps: list[StepOut]
    created_at: datetime
    updated_at: datetime


class EventMemberOut(BaseModel):
    member_id: int
    display_name: str
    active: bool
    note: str
    account: AccountOut | None
    availability_submitted_at: datetime | None
    availability_filled_days: int
    availability_filled_by: str | None


class EventMembersIn(BaseModel):
    member_ids: list[int]


class EventMembersAddIn(BaseModel):
    """按昵称添加人员:已在名册的直接关联,不在的自动创建。"""

    names: list[str] = Field(min_length=1)

    @field_validator("names")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for n in v:
            n = normalize_name(n)
            if n and n not in out:
                out.append(n)
        if not out:
            raise ValueError("请输入至少一个昵称")
        return out


# ---------- 曲目 ----------
class SongIn(BaseModel):
    code: str | None = Field(default=None, max_length=16)  # 缺省自动 a、b、c…
    name: str = Field(min_length=1, max_length=120)
    difficulty: Difficulty
    member_ids: list[int] = Field(min_length=1)
    session_plan: list[int] | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        v = normalize_name(v or "")
        return v or None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = normalize_name(v)
        if not v:
            raise ValueError("曲目名称不能为空")
        return v

    @field_validator("session_plan")
    @classmethod
    def _plan(cls, v: list[int] | None) -> list[int] | None:
        return None if v is None else _check_plan(v, "场次方案")

    @field_validator("member_ids")
    @classmethod
    def _members(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("参演成员有重复")
        return v


class SongPatch(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=16)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    difficulty: Difficulty | None = None
    member_ids: list[int] | None = Field(default=None, min_length=1)
    session_plan: list[int] | None = None
    clear_session_plan: bool = False  # True 表示改回难度模板
    sort_order: int | None = None

    _strip = field_validator("code", "name")(lambda cls, v: normalize_name(v) if v is not None else v)  # noqa: E731
    _plan = field_validator("session_plan")(SongIn._plan.__func__)  # type: ignore[attr-defined]
    _members = field_validator("member_ids")(lambda cls, v: SongIn._members.__func__(cls, v) if v is not None else v)  # type: ignore[attr-defined]


class SongOut(BaseModel):
    id: int
    event_id: int
    code: str
    name: str
    difficulty: Difficulty
    members: list[MemberBrief]
    session_plan: list[int] | None
    durations: list[int]
    session_count: int
    sort_order: int


class SongListOut(BaseModel):
    songs: list[SongOut]
    warnings: list[str]
    total_sessions: int


# ---------- 特殊排程要求 ----------
RuleType = Literal[
    "member_song_max_absent",
    "member_song_max_attendance",
    "blocked_day",
    "blocked_slots",
    "max_sessions_per_date",
    "fixed_session",
    "focus_member",
]


class RuleIn(BaseModel):
    type: RuleType
    params: dict = {}
    enabled: bool = True


class RulePatch(BaseModel):
    params: dict | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class RuleOut(BaseModel):
    id: int
    event_id: int
    type: RuleType
    params: dict
    hardness: Literal["hard", "soft"]
    enabled: bool
    sentence: str
    sort_order: int


class RuleTypeOut(BaseModel):
    type: RuleType
    hardness: Literal["hard", "soft"]
    template: str  # 带 {member} {song} {date} 等占位的填空句
    fields: list[str]
    description: str


# ---------- 空闲填报 ----------
class AvailabilityOut(BaseModel):
    event_id: int
    member_id: int
    display_name: str
    dates: list[date]
    eval_date: date
    slots_per_day: int
    day_start_hour: int
    days: dict[str, str]  # "YYYY-MM-DD" -> "0110…"(缺省全部 0)
    filled_days: int
    filled_by: str | None
    submitted_at: datetime | None
    deadline: date | None
    past_deadline: bool


class AvailabilityIn(BaseModel):
    days: dict[str, str]
    submit: bool = False


class HeatOut(BaseModel):
    dates: list[date]
    slots_per_day: int
    day_start_hour: int
    member_count: int
    submitted_count: int
    heat: dict[str, list[int]]  # 日期 -> 每格可排人数(只统计已提交的成员)


class PrecheckItem(BaseModel):
    key: str
    ok: bool
    level: Literal["ok", "warn", "error"]
    label: str
    detail: str = ""


class PrecheckOut(BaseModel):
    items: list[PrecheckItem]
    can_solve: bool
    warnings: int
