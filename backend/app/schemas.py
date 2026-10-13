"""请求 / 响应模型(Pydantic v2)。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from solver.types import DEFAULT_OBJECTIVES, OBJECTIVE_LABELS

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


class AccountDeleteIn(BaseModel):
    password: str


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
    # 缺席阶梯(开发文档 §5.6):排不下时最多允许多少比例的场次有 1 人缺席
    max_absent_percent: int = Field(default=25, ge=0, le=60)
    absent_per_member_song: int = Field(default=1, ge=1, le=5)  # 每人每首最多缺席几次
    min_full_per_song: int = Field(default=1, ge=0, le=5)  # 每首至少几场全员到齐
    difficulty_templates: dict[str, list[int]] = {"困难": [3, 3, 3], "一般": [3, 2, 2], "简单": [2, 2]}
    stage_time_limit: float = Field(default=90.0, ge=5, le=600)
    objectives: list[str] = list(DEFAULT_OBJECTIVES)  # 优化目标顺序(RULE-04),可去掉不要的项

    @field_validator("objectives")
    @classmethod
    def _objectives(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("优化目标不能重复")
        for key in v:
            if key not in OBJECTIVE_LABELS or key == "missing":
                raise ValueError(f"未知的优化目标 {key}")
        return v

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
    latest_version_no: int | None
    published_version_no: int | None
    latest_job_status: str | None
    conflict_count: int  # 已发布版本中与最新空闲冲突的场次数
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
    warning: str | None = None  # 新建 / 修改时的规则冲突检查结果(RULE-06)


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
    # 热力图点格子看“谁有空”、按曲目算共同空闲用(仅管理员):成员昵称 -> 日期 -> 每格状态 0/1/2
    availability: dict[str, dict[str, str]] = {}
    songs: list[dict] = []  # [{code, name, members: [昵称], durations: [小时]}]


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


# ---------- 求解 / 排练表 ----------
JobStatus = Literal["queued", "running", "succeeded", "infeasible", "failed", "cancelled"]


class SolveIn(BaseModel):
    only_ready_songs: bool = False  # 只排参演人员已全部提交空闲的曲目
    base_version_id: int | None = None  # 锁定后重排:保留该版本中锁定的场次


class JobOut(BaseModel):
    id: int
    event_id: int
    status: JobStatus
    progress: str
    stage_records: list[dict]
    attempts: list[dict]
    ladder_level_used: int | None
    skipped_songs: list[str]
    diagnosis: dict | None
    summary: str
    error: str | None
    version_id: int | None
    only_ready_songs: bool
    base_version_id: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    elapsed_seconds: float | None


class SessionOut(BaseModel):
    id: int
    kind: Literal["formal", "evaluation"]
    song_id: int | None
    song_code: str | None
    song_name: str
    task_no: int | None  # 给人看的「第几场」:同一首按日期排序后的序号(增删场次后仍连续)
    task_key: int | None = None  # 场次在版本内的固定编号(撤销 / 复制草稿时用来对应同一场)
    uid: str | None = None  # 场次的固定身份(复制成草稿后不变;一组修改里用它指明场次)
    date: date
    weekday: str
    start_slot: int
    duration_slots: int
    time: str
    members: list[MemberBrief]
    absent: list[MemberBrief]
    attendance: dict[str, str] | None  # 评估场:成员名 -> "14:00–17:00"
    locked: bool
    location: str = ""


class MemberStatOut(BaseModel):
    member_id: int
    display_name: str
    sessions: int
    hours: int
    days: int
    absent: int
    eval_time: str | None


class VersionOut(BaseModel):
    id: int
    event_id: int
    version_no: int
    source: str
    parent_version_id: int | None
    status: Literal["draft", "published", "archived"]
    locked_count: int
    level_used: int | None
    exact_optimum: bool
    objective_values: dict
    validation_errors: list[str]
    metrics: dict
    skipped_songs: list[str]
    session_count: int
    created_at: datetime
    published_at: datetime | None
    revision: int = 0


class IssueOut(BaseModel):
    """一条硬约束问题(冲突):message 是给人看的句子,session_ids 是涉及的场次(界面标红)。"""

    code: str
    message: str
    session_ids: list[int]


class OperationOut(BaseModel):
    id: int
    seq: int
    kind: str
    summary: str
    undone: bool
    created_at: datetime


class VersionDetailOut(VersionOut):
    sessions: list[SessionOut]
    member_stats: list[MemberStatOut]
    stage_records: list[dict]
    # 以下仅管理员接口填写
    issues: list[IssueOut] = []
    notices: list[str] = []  # 不影响发布的提醒,如某首曲目手动调整过时长
    history: list[OperationOut] = []
    can_undo: bool = False
    can_redo: bool = False


# ---------- 发布 / 日历订阅(M4) ----------
class PublishedScheduleOut(VersionDetailOut):
    event_name: str
    performance_date: date
    formal_start_date: date
    formal_end_date: date
    eval_date: date
    day_start_hour: int
    day_end_hour: int
    my_member_id: int | None


class CalendarOut(BaseModel):
    url: str
    webcal_url: str


# ---------- 排练表调整(M5) ----------
class MoveIn(BaseModel):
    date: date
    start_slot: int
    duration_slots: int | None = None


class LockIn(BaseModel):
    locked: bool


class EditResultOut(BaseModel):
    version: VersionDetailOut
    warnings: list[str]  # 软目标变化,如「成员额外往返 +1」
    forked: bool  # 原版本不是草稿,已复制成新草稿
    new_issues: list[str] = []  # 这次修改新引入的冲突(草稿允许暂存,发布前必须解决)


class RevisionIn(BaseModel):
    expected_revision: int | None = None  # 提交修改时界面看到的版本号;对不上说明期间被改过


class OpMoveIn(RevisionIn):
    session_id: int
    date: date
    start_slot: int
    duration_slots: int | None = None


class OpResizeIn(RevisionIn):
    """上下拉调整时长:同一天内的新开始格与新时长(都以小时为单位)。"""

    session_id: int
    start_slot: int
    duration_slots: int


class OpAddIn(RevisionIn):
    """新建一场正规排练。"""

    song_id: int
    date: date
    start_slot: int
    duration_slots: int


class OpDeleteIn(RevisionIn):
    session_id: int


class OpBatchIn(RevisionIn):
    """一组修改(AI 修改 / 少改动重排的方案):每条 {op: move|resize|swap|add|delete|lock, ...},场次用固定身份 uid 指明。"""

    ops: list[dict] = Field(min_length=1, max_length=60)
    summary: str = Field(default="", max_length=200)
    ai_run_id: int | None = None  # 来自「AI 修改」的方案:应用后在那条运行记录上记下写入的版本


class BatchPreviewOut(BaseModel):
    lines: list[str]  # 每条修改的说明
    new_issues: list[str]  # 这组修改新引入的冲突
    issues: list[str]  # 应用后仍有的全部冲突
    notices: list[str]  # 不影响发布的提醒
    warnings: list[str]  # 软目标变化


class ReoptOut(BaseModel):
    """少改动重排的提案:只挪动必要的场次;确认后用 /ops/batch 应用。"""

    status: Literal["ok", "unchanged", "infeasible", "locked_conflict", "error"]
    message: str
    ops: list[dict]
    preview: BatchPreviewOut | None = None
    optimal: bool = False
    revision: int = 0  # 算提案时这一版的修改次数;应用时作为 expected_revision


class OpSwapIn(RevisionIn):
    a: int
    b: int


class OpLockIn(RevisionIn):
    session_id: int
    locked: bool


class DiffItemOut(BaseModel):
    change: Literal["added", "removed", "moved", "changed"]
    kind: Literal["formal", "evaluation"]
    before: SessionOut | None
    after: SessionOut | None


class DiffOut(BaseModel):
    base_id: int
    base_no: int
    against_id: int
    against_no: int
    items: list[DiffItemOut]
    affected_members: list[MemberBrief]
    summary: str


class ConflictOut(BaseModel):
    session: SessionOut
    member: MemberBrief
    hours: list[str]


class ConflictsOut(BaseModel):
    version_id: int
    version_no: int
    status: str
    items: list[ConflictOut]
    members: list[MemberBrief]


# ---------- 通知(M6) ----------
class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: str
    link: str
    event_id: int | None
    created_at: datetime
    read_at: datetime | None


class UnreadCountOut(BaseModel):
    count: int


class ReadIn(BaseModel):
    ids: list[int] = []  # 空 = 全部


class RemindOut(BaseModel):
    notified: list[str]
    without_account: list[str]
    copy_text: str


class ObjectiveOut(BaseModel):
    key: str
    label: str
    default_on: bool


# ---------- 排练地点 ----------
class LocationIn(BaseModel):
    location: str = Field(default="", max_length=200)


class LocationOut(BaseModel):
    version: VersionDetailOut
    notified: int  # 已通知的成员数(仅已发布版本会通知)


# ---------- PWA 推送 ----------
class PushKeys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(max_length=600)
    keys: PushKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=600)


class PushPublicKeyOut(BaseModel):
    public_key: str


class PushStatusOut(BaseModel):
    devices: int  # 网页推送订阅数
    native: int = 0  # 原生 App 设备数
    native_available: bool = False  # 服务器是否配置了 APNs;False 时 App 里开了推送也收不到


# ---------- 原生 App(Capacitor) ----------
class LoginOut(UserOut):
    token: str | None = None  # 仅请求头 X-Client: native 时返回


class NativeTokenIn(BaseModel):
    platform: Literal["ios", "android"]
    token: str = Field(min_length=8, max_length=400)


class NativeTokenOut(BaseModel):
    token: str = Field(min_length=8, max_length=400)


# ---------- AI 调度员 ----------
class AdvisorRunOut(BaseModel):
    id: int
    event_id: int
    kind: str = "advisor"  # advisor = 无解时的 AI 调度员;edit = 用一句话修改排练表
    version_id: int | None = None
    instruction: str = ""
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    progress: str
    log: list[dict]
    proposal: dict | None
    applied: list[int]  # 调度员:已执行的调整序号;AI 修改:方案写入的版本 id
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    elapsed_seconds: float | None
    cost_usd: float | None


class AdvisorStartIn(BaseModel):
    consent: bool = False  # 管理员已确认:排程数据(含成员昵称与空闲)会发送给 Anthropic


class AiEditIn(BaseModel):
    instruction: str = Field(min_length=2, max_length=500)
    consent: bool = False  # 管理员已确认:排练表数据(含成员昵称与空闲)会发送给 Anthropic


class AdvisorApplyIn(BaseModel):
    indices: list[int] = Field(min_length=1, max_length=100)
