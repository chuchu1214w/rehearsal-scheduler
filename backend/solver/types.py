"""求解包的核心数据结构。

约定:
- 时间格 ``h`` 从 0 起,``h = 0`` 对应 ``day_start_hour`` 这一小时;
- 空闲状态:0 不可排 / 1 可排 / 2 尽量避开(可排,但计入软惩罚);
- 日期一律用 ``datetime.date``,时间只在展示时换算。

本模块不依赖 OR-Tools,也不依赖数据库或 Web 框架。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

UNAVAILABLE = 0
AVAILABLE = 1
AVOID = 2

DIFFICULTIES = ("简单", "一般", "困难")
DEFAULT_DIFFICULTY_TEMPLATES: dict[str, tuple[int, ...]] = {
    "困难": (3, 3, 3),
    "一般": (3, 2, 2),
    "简单": (2, 2),
}

# 优化目标注册表(键 → 中文名)。顺序无意义,真正的顺序由 Problem.objectives 决定。
OBJECTIVE_LABELS: dict[str, str] = {
    "absent": "缺席最少",
    "eval_attendance": "评估场迟到早退最少",
    "hard_early": "困难曲目尽早",
    "spacing": "同曲间隔≥1天",
    "focus_days": "指定成员集中排练日",
    "trips": "成员额外往返最少",
    "gaps": "成员长空档最少",
    "overtime": "单日超时最少",
    "soft_avoid": "避开“尽量避开”时段",
}
# 默认顺序(开发文档 A-01 / §5.7)。“困难曲目尽早”默认关闭。
DEFAULT_OBJECTIVES: tuple[str, ...] = (
    "absent",
    "eval_attendance",
    "spacing",
    "focus_days",
    "trips",
    "gaps",
    "overtime",
    "soft_avoid",
)

KIND_FORMAL = "formal"
KIND_EVALUATION = "evaluation"


@dataclass(frozen=True)
class EventConfig:
    """活动级参数(开发文档 §5.1、RULE-01、附录 A)。"""

    performance_date: date
    formal_start_date: date
    day_start_hour: int = 10
    day_end_hour: int = 23
    soft_daily_limit: int = 8
    hard_daily_limit: int = 8
    merge_visit_gap: int = 1
    free_gap: int = 1
    eval_durations: tuple[int, ...] = (3, 2)  # 评估场允许的时长;实际按总到场人时最多选择(见 evaluation.py)
    eval_min_contiguous: int = 2  # 评估场每人至少连续到场小时数(A-16)
    same_song_different_days: bool = True  # HC-08
    difficulty_templates: dict[str, tuple[int, ...]] = field(default_factory=lambda: dict(DEFAULT_DIFFICULTY_TEMPLATES))
    stage_time_limit: float = 90.0
    workers: int = 8
    seed: int = 42

    def __post_init__(self) -> None:
        if not 0 <= self.day_start_hour < self.day_end_hour <= 24:
            raise ValueError("每日排练窗口不合法:需要 0 ≤ 开始小时 < 结束小时 ≤ 24")
        if self.hard_daily_limit < 1:
            raise ValueError("单日硬上限必须 ≥ 1 小时")
        if self.hard_daily_limit < self.soft_daily_limit:
            raise ValueError("单日硬上限不能小于软上限")
        if self.merge_visit_gap < 0 or self.free_gap < 0:
            raise ValueError("往返合并间隔与免罚空档不能为负")
        if self.formal_start_date > self.performance_date - timedelta(days=2):
            raise ValueError("正规排练区间为空:开始日期必须不晚于演出日前两天")
        if not self.eval_durations:
            raise ValueError("评估场至少要有一个可选时长")
        for d in self.eval_durations:
            if not 1 <= d <= self.slots_per_day:
                raise ValueError(f"评估场时长 {d} 超出每日窗口")
        if self.eval_min_contiguous < 1:
            raise ValueError("评估场最少连续到场小时数必须 ≥ 1")
        for name, plan in self.difficulty_templates.items():
            if not plan or any(x < 1 for x in plan):
                raise ValueError(f"难度模板 {name!r} 的场次方案不合法:{plan!r}")
        if self.stage_time_limit <= 0 or self.workers < 1:
            raise ValueError("求解时限必须为正,并行度必须 ≥ 1")

    @property
    def slots_per_day(self) -> int:
        return self.day_end_hour - self.day_start_hour

    @property
    def eval_date(self) -> date:
        return self.performance_date - timedelta(days=1)

    @property
    def formal_dates(self) -> list[date]:
        last = self.performance_date - timedelta(days=2)
        n = (last - self.formal_start_date).days + 1
        return [self.formal_start_date + timedelta(days=i) for i in range(n)]

    @property
    def all_dates(self) -> list[date]:
        return [*self.formal_dates, self.eval_date]

    def slot_time(self, h: int) -> str:
        return f"{(self.day_start_hour + h) % 24:02d}:00"

    def slot_label(self, h: int) -> str:
        return f"{self.slot_time(h)}–{self.slot_time(h + 1)}"

    def range_label(self, start: int, duration: int) -> str:
        return f"{self.slot_time(start)}–{self.slot_time(start + duration)}"


@dataclass(frozen=True)
class Song:
    code: str
    name: str
    difficulty: str
    members: tuple[str, ...]
    session_plan: tuple[int, ...] | None = None  # 曲目级覆盖;None 则用难度模板

    def durations(self, config: EventConfig) -> tuple[int, ...]:
        if self.session_plan:
            return tuple(self.session_plan)
        try:
            return tuple(config.difficulty_templates[self.difficulty])
        except KeyError as exc:
            raise ValueError(f"曲目 {self.code} 的难度 {self.difficulty!r} 没有对应的场次模板") from exc


class Availability:
    """成员 × 日期 → 13 格状态(0/1/2)。缺失的成员或日期一律视为不可排。"""

    def __init__(self, grid: dict[str, dict[date, list[int]]] | None = None) -> None:
        self.grid: dict[str, dict[date, list[int]]] = grid or {}

    def status(self, member: str, d: date, h: int) -> int:
        row = self.grid.get(member, {}).get(d)
        if row is None or not 0 <= h < len(row):
            return UNAVAILABLE
        return row[h]

    def is_available(self, member: str, d: date, h: int) -> bool:
        return self.status(member, d, h) in (AVAILABLE, AVOID)

    def is_avoid(self, member: str, d: date, h: int) -> bool:
        return self.status(member, d, h) == AVOID

    def members(self) -> list[str]:
        return list(self.grid)

    def set_row(self, member: str, d: date, row: list[int]) -> None:
        self.grid.setdefault(member, {})[d] = list(row)

    def copy(self) -> Availability:
        return Availability({m: {d: list(r) for d, r in rows.items()} for m, rows in self.grid.items()})


@dataclass(frozen=True)
class FixedSession:
    """规则模板 ⑤ / HC-14:某曲目必须有一场固定在给定日期与时间。"""

    song_code: str
    date: date
    start: int
    duration: int
    absent_member: str | None = None


@dataclass
class Rules:
    """特例规则(开发文档 RULE-03)。空规则等价于没有特例。"""

    blocked_slots: dict[date, frozenset[int]] = field(default_factory=dict)  # 规则模板 ③:禁排
    max_sessions_per_date: dict[date, int] = field(default_factory=dict)  # 规则模板 ③:限制场次数
    member_song_max_attendance: dict[tuple[str, str], int] = field(default_factory=dict)  # 规则模板 ①
    focus_members: tuple[str, ...] = ()  # 规则模板 ②(目标 focus_days)
    fixed_sessions: tuple[FixedSession, ...] = ()  # 规则模板 ⑤ / 锁定
    # 交互设计 §4④:「成员 X 在曲目 Y 最多可缺席 N 次」——尽量全到,排不开时才缺席;任何层级都允许,计入「缺席最少」
    member_song_max_absent: dict[tuple[str, str], int] = field(default_factory=dict)

    def attendance_cap(self, member: str, song_code: str) -> int | None:
        return self.member_song_max_attendance.get((member, song_code))

    def absence_allowance(self, member: str, song_code: str) -> int | None:
        return self.member_song_max_absent.get((member, song_code))

    def planned_absence(self, member: str | None, song_code: str) -> bool:
        """该成员在该曲目的缺席是否属于“计划内”(出勤上限或允许缺席),因而不受降级阶梯限制。"""
        if member is None:
            return False
        return self.attendance_cap(member, song_code) is not None or self.absence_allowance(member, song_code) is not None


@dataclass(frozen=True)
class LadderLevel:
    """缺席降级阶梯的一层(开发文档 §5.6)。"""

    level: int
    max_absent_ratio: float = 0.0
    per_song_min_full: int | None = None  # None = 全部场次都要全员
    per_member_per_song_max_absent: int = 0

    @property
    def strict(self) -> bool:
        return self.max_absent_ratio <= 0

    def max_absent_sessions(self, n_tasks: int) -> int:
        return max(0, int(n_tasks * self.max_absent_ratio))


DEFAULT_LADDER: tuple[LadderLevel, ...] = (
    LadderLevel(0),
    LadderLevel(1, 0.20, 1, 1),
    LadderLevel(2, 0.25, 1, 1),
)


@dataclass(frozen=True)
class Task:
    task_id: str
    song_code: str
    task_no: int
    duration: int


@dataclass(frozen=True)
class Candidate:
    date_idx: int
    start: int
    duration: int
    absent_member: str | None = None
    excused: bool = False  # 因“出勤上限”规则产生的计划缺席,不计入阶梯与缺席目标

    @property
    def hours(self) -> range:
        return range(self.start, self.start + self.duration)

    @property
    def full(self) -> bool:
        return self.absent_member is None


@dataclass
class Session:
    """排练表中的一场。``kind`` 为 formal(正规)或 evaluation(全员评估)。"""

    kind: str
    date: date
    start: int
    duration: int
    song_code: str | None = None
    task_no: int | None = None
    absent_members: tuple[str, ...] = ()
    # 仅评估场:成员 → (绝对开始格, 绝对结束格),用于记录迟到早退
    attendance: dict[str, tuple[int, int]] | None = None
    locked: bool = False

    @property
    def end(self) -> int:
        return self.start + self.duration

    @property
    def hours(self) -> range:
        return range(self.start, self.end)


@dataclass
class StageRecord:
    key: str
    label: str
    value: int | None
    status: str


@dataclass
class SolveResult:
    feasible: bool
    level_used: int | None
    exact: bool
    stages: list[StageRecord]
    sessions: list[Session]
    objective_values: dict[str, int]
    attempts: list[dict]
    diagnosis: dict | None = None
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class Problem:
    """一次求解所需的全部输入。"""

    config: EventConfig
    members: tuple[str, ...]
    songs: tuple[Song, ...]
    availability: Availability
    rules: Rules = field(default_factory=Rules)
    ladder: tuple[LadderLevel, ...] = DEFAULT_LADDER
    objectives: tuple[str, ...] = DEFAULT_OBJECTIVES

    def song(self, code: str) -> Song:
        for s in self.songs:
            if s.code == code:
                return s
        raise KeyError(f"没有代号为 {code!r} 的曲目")

    def member_index(self, member: str) -> int:
        try:
            return self.members.index(member)
        except ValueError:
            return len(self.members)

    def validate(self) -> tuple[list[str], list[str]]:
        """返回 (错误, 警告)。有错误时不应求解。"""
        errors: list[str] = []
        warnings: list[str] = []
        if not self.members:
            errors.append("成员名单为空")
        if len(set(self.members)) != len(self.members):
            errors.append("成员名单有重复")
        member_set = set(self.members)

        codes = [s.code for s in self.songs]
        if len(set(codes)) != len(codes):
            errors.append("曲目代号有重复")
        if not self.songs:
            errors.append("没有任何曲目")
        seen_member_sets: dict[frozenset[str], str] = {}
        for s in self.songs:
            if not s.members:
                errors.append(f"曲目 {s.code} 没有参演成员")
            unknown = [m for m in s.members if m not in member_set]
            if unknown:
                errors.append(f"曲目 {s.code} 的成员不在名单中:{'、'.join(unknown)}")
            if len(set(s.members)) != len(s.members):
                errors.append(f"曲目 {s.code} 的成员有重复")
            try:
                s.durations(self.config)
            except ValueError as exc:
                errors.append(str(exc))
            key = frozenset(s.members)
            if key in seen_member_sets:
                warnings.append(f"曲目 {s.code} 与 {seen_member_sets[key]} 的成员集合完全相同")
            else:
                seen_member_sets[key] = s.code

        if len(set(self.objectives)) != len(self.objectives):
            errors.append("优化目标列表有重复")
        for key in self.objectives:
            if key not in OBJECTIVE_LABELS:
                errors.append(f"未知的优化目标:{key}")

        if not self.ladder:
            errors.append("降级阶梯为空")
        else:
            if not self.ladder[0].strict:
                errors.append("降级阶梯第一层必须是严格层(缺席比例 0)")
            levels = [lv.level for lv in self.ladder]
            if levels != sorted(levels) or len(set(levels)) != len(levels):
                errors.append("降级阶梯的层级编号必须递增且不重复")

        song_codes = set(codes)
        for (m, code), cap in self.rules.member_song_max_attendance.items():
            if code not in song_codes:
                errors.append(f"出勤上限规则引用了不存在的曲目 {code}")
            elif m not in self.song(code).members:
                errors.append(f"出勤上限规则:成员 {m} 不在曲目 {code} 中")
            if cap < 0:
                errors.append(f"出勤上限规则:{m}/{code} 的上限不能为负")
        for (m, code), n in self.rules.member_song_max_absent.items():
            if code not in song_codes:
                errors.append(f"允许缺席规则引用了不存在的曲目 {code}")
            elif m not in self.song(code).members:
                errors.append(f"允许缺席规则:成员 {m} 不在曲目 {code} 中")
            if n < 1:
                errors.append(f"允许缺席规则:{m}/{code} 的次数必须 ≥ 1")
        for m in self.rules.focus_members:
            if m not in member_set:
                errors.append(f"集中排练日规则引用了不存在的成员 {m}")
        for fx in self.rules.fixed_sessions:
            if fx.song_code not in song_codes:
                errors.append(f"固定场次规则引用了不存在的曲目 {fx.song_code}")
                continue
            if fx.duration not in self.song(fx.song_code).durations(self.config):
                errors.append(f"固定场次规则:曲目 {fx.song_code} 没有 {fx.duration} 小时的场次")
            if fx.date not in self.config.formal_dates:
                errors.append(f"固定场次规则:{fx.date} 不在正规排练区间内")
            if not 0 <= fx.start <= self.config.slots_per_day - fx.duration:
                errors.append(f"固定场次规则:曲目 {fx.song_code} 的开始格 {fx.start} 超出窗口")
        for d in [*self.rules.blocked_slots, *self.rules.max_sessions_per_date]:
            if d not in self.config.all_dates:
                warnings.append(f"日期规则中的 {d} 不在活动日期范围内,已忽略")

        unknown_avail = sorted(set(self.availability.members()) - member_set)
        if unknown_avail:
            warnings.append("空闲数据中有不在名单里的成员:" + "、".join(unknown_avail))
        for m in self.members:
            rows = self.availability.grid.get(m, {})
            missing = [d for d in self.config.all_dates if d not in rows]
            if len(missing) == len(self.config.all_dates):
                warnings.append(f"成员 {m} 没有任何空闲数据,按全部不可排处理")
            elif missing:
                warnings.append(f"成员 {m} 缺少 {len(missing)} 天的空闲数据,这些天按不可排处理")
            for d, row in rows.items():
                if len(row) != self.config.slots_per_day:
                    errors.append(f"成员 {m} 在 {d} 的空闲数据长度为 {len(row)},应为 {self.config.slots_per_day}")
                if any(v not in (UNAVAILABLE, AVAILABLE, AVOID) for v in row):
                    errors.append(f"成员 {m} 在 {d} 的空闲数据含非法值(只能是 0/1/2)")
        return errors, warnings
