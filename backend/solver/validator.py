"""校验器(开发文档 §5.9):独立于求解器的纯函数,用于求解后自检、手动微调实时校验、发布前门禁。

返回的 ``metrics`` 与模型各目标项的定义一致,便于显示“软目标变化量”。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .evaluation import attendance_options
from .timegrid import block_allowed, unavailable_hours
from .types import KIND_EVALUATION, KIND_FORMAL, LadderLevel, Problem, Session


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _label(problem: Problem, s: Session) -> str:
    who = problem.song(s.song_code).name if s.song_code else "全员评估"
    return f"{who} {s.date} {problem.config.range_label(s.start, s.duration)}"


def validate_schedule(
    problem: Problem,
    sessions: list[Session],
    level: LadderLevel | None = None,
    locked_reference: list[Session] | None = None,
) -> ValidationReport:
    config, rules = problem.config, problem.rules
    level = level or problem.ladder[0]
    rep = ValidationReport()
    err = rep.errors.append
    formal_dates = set(config.formal_dates)
    formal = [s for s in sessions if s.kind == KIND_FORMAL]
    evals = [s for s in sessions if s.kind == KIND_EVALUATION]

    for s in sessions:
        if s.kind not in (KIND_FORMAL, KIND_EVALUATION):
            err(f"未知的场次类型 {s.kind!r}")
            continue
        if s.duration < 1 or s.start < 0 or s.start + s.duration > config.slots_per_day:
            err(f"V-01 {_label(problem, s)} 超出每日窗口")
            continue
        # V-01 窗口与禁排
        if not block_allowed(config, rules, s.date, s.start, s.duration):
            err(f"V-01 {_label(problem, s)} 落在禁排时段")

    # ---- 正规排练 ----
    by_song: dict[str, list[Session]] = defaultdict(list)
    for s in formal:
        if s.song_code is None:
            err(f"V-03 正规排练缺少曲目:{s.date} {config.range_label(s.start, s.duration)}")
            continue
        try:
            song = problem.song(s.song_code)
        except KeyError:
            err(f"V-03 未知曲目 {s.song_code}")
            continue
        by_song[s.song_code].append(s)
        if s.date not in formal_dates:
            if s.date == config.eval_date:
                err(f"V-07 {_label(problem, s)} 排在了公演前一天(只允许全员评估)")
            else:
                err(f"V-01 {_label(problem, s)} 不在正规排练区间内")
        if len(s.absent_members) > 1:
            err(f"V-08 {_label(problem, s)} 缺席人数超过 1")
        for m in s.absent_members:
            if m not in song.members:
                err(f"V-02 {_label(problem, s)} 的缺席成员 {m} 不在该曲目中")
        # V-02 到场成员可用
        for m in song.members:
            if m in s.absent_members:
                continue
            missing = unavailable_hours(problem, m, s.date, s.start, s.duration)
            if missing:
                err(f"V-02 {_label(problem, s)} 成员 {m} 在 {'、'.join(config.slot_label(h) for h in missing)} 不可用")

    # V-03 场次数与时长
    for song in problem.songs:
        expected = sorted(song.durations(config), reverse=True)
        actual = sorted((s.duration for s in by_song.get(song.code, [])), reverse=True)
        if actual != expected:
            err(f"V-03 曲目 {song.code}({song.name}) 场次时长 {actual} 与方案 {expected} 不符")

    # V-04 成员不重叠(含缺席成员,保守);V-05 单日硬上限
    per_member_day: dict[tuple[str, date], list[Session]] = defaultdict(list)
    for s in formal:
        if s.song_code is None:
            continue
        for m in problem.song(s.song_code).members:
            per_member_day[(m, s.date)].append(s)
    for (m, d), ss in per_member_day.items():
        ss = sorted(ss, key=lambda s: s.start)
        for a, b in zip(ss, ss[1:], strict=False):
            if b.start < a.end:
                err(f"V-04 成员 {m} 在 {d} 有重叠:{_label(problem, a)} 与 {_label(problem, b)}")
        hours = sum(s.duration for s in ss)
        if hours > config.hard_daily_limit:
            err(f"V-05 成员 {m} 在 {d} 排练 {hours} 小时,超过硬上限 {config.hard_daily_limit}")

    # V-06 同曲不同天
    if config.same_song_different_days:
        for code, ss in by_song.items():
            days = [s.date for s in ss]
            if len(set(days)) != len(days):
                err(f"V-06 曲目 {code} 有两场排在同一天")

    # V-07 评估场
    if len(evals) != 1:
        err(f"V-07 全员评估场应恰好 1 场,实际 {len(evals)} 场")
    for e in evals:
        if e.date != config.eval_date:
            err(f"V-07 评估场日期 {e.date} 不是公演前一天 {config.eval_date}")
        if e.duration not in config.eval_durations:
            err(f"V-07 评估场时长 {e.duration} 不在允许范围 {list(config.eval_durations)}")
        att = e.attendance or {}
        min_len = min(config.eval_min_contiguous, e.duration)
        allowed = {(e.start + a, e.start + b) for a, b in attendance_options(e.duration, config.eval_min_contiguous)}
        for m in problem.members:
            if m not in att:
                err(f"V-07 评估场缺少成员 {m} 的到场记录")
                continue
            a, b = att[m]
            if (a, b) not in allowed:
                err(f"V-07 评估场成员 {m} 的到场区间 {config.range_label(a, b - a)} 不符合规则(须连续 ≥ {min_len} 小时且在场内)")
                continue
            missing = unavailable_hours(problem, m, e.date, a, b - a)
            if missing:
                err(f"V-02 评估场成员 {m} 在 {'、'.join(config.slot_label(h) for h in missing)} 不可用")

    # V-08 降级层级
    unexcused: list[Session] = []
    for s in formal:
        for m in s.absent_members:
            if not rules.planned_absence(m, s.song_code or ""):
                unexcused.append(s)
    if level.strict:
        for s in unexcused:
            err(f"V-08 严格层不允许缺席:{_label(problem, s)} 缺席 {'、'.join(s.absent_members)}")
    else:
        n_tasks = sum(len(song.durations(config)) for song in problem.songs)
        cap = level.max_absent_sessions(n_tasks)
        if len(unexcused) > cap:
            err(f"V-08 缺席场次 {len(unexcused)} 超过层级上限 {cap}")
        for song in problem.songs:
            ss = by_song.get(song.code, [])
            n = len(song.durations(config))
            min_full = n if level.per_song_min_full is None else min(level.per_song_min_full, n)
            song_unexcused = [s for s in ss if s in unexcused]
            if len(song_unexcused) > n - min_full:
                err(f"V-08 曲目 {song.code} 全员到齐场次不足 {min_full}")
            per_member: dict[str, int] = defaultdict(int)
            for s in song_unexcused:
                for m in s.absent_members:
                    per_member[m] += 1
            for m, cnt in per_member.items():
                if cnt > level.per_member_per_song_max_absent:
                    err(f"V-08 成员 {m} 在曲目 {song.code} 缺席 {cnt} 次,超过 {level.per_member_per_song_max_absent}")

    # V-09 自定义硬规则
    for (m, code), cap in rules.member_song_max_attendance.items():
        attended = sum(1 for s in by_song.get(code, []) if m not in s.absent_members)
        if attended > cap:
            err(f"V-09 成员 {m} 在曲目 {code} 出勤 {attended} 场,超过上限 {cap}")
    for (m, code), allowance in rules.member_song_max_absent.items():
        absent_n = sum(1 for s in by_song.get(code, []) if m in s.absent_members)
        if absent_n > allowance:
            err(f"V-09 成员 {m} 在曲目 {code} 缺席 {absent_n} 次,超过允许的 {allowance} 次")
    for d, limit in rules.max_sessions_per_date.items():
        n = sum(1 for s in formal if s.date == d)
        if n > limit:
            err(f"V-09 {d} 安排了 {n} 场,超过上限 {limit}")
    for fx in rules.fixed_sessions:
        hit = any(
            s.song_code == fx.song_code
            and s.date == fx.date
            and s.start == fx.start
            and s.duration == fx.duration
            and (tuple(s.absent_members) == ((fx.absent_member,) if fx.absent_member else ()))
            for s in formal
        )
        if not hit:
            err(f"V-09 固定场次 {fx.song_code} {fx.date} {config.range_label(fx.start, fx.duration)} 未出现在排练表中")

    # V-10 锁定场次
    for ref in locked_reference or []:
        if not ref.locked:
            continue
        hit = any(
            s.kind == ref.kind
            and s.song_code == ref.song_code
            and s.date == ref.date
            and s.start == ref.start
            and s.duration == ref.duration
            for s in sessions
        )
        if not hit:
            err(f"V-10 锁定场次 {_label(problem, ref)} 被改动")

    rep.metrics = compute_metrics(problem, sessions)
    return rep


def compute_metrics(problem: Problem, sessions: list[Session]) -> dict[str, int]:
    """与 model.py 各目标项定义一致的指标。"""
    config, rules = problem.config, problem.rules
    dates = config.formal_dates
    date_idx = {d: i for i, d in enumerate(dates)}
    formal = [s for s in sessions if s.kind == KIND_FORMAL and s.song_code]
    evals = [s for s in sessions if s.kind == KIND_EVALUATION]

    absent = sum(1 for s in formal if s.absent_members)
    eval_missing = 0
    for e in evals:
        for a, b in (e.attendance or {}).values():
            eval_missing += e.duration - (b - a)

    # 占用:成员 × 日 → 忙碌格集合(含缺席成员,与模型一致)
    busy: dict[tuple[str, date], set[int]] = defaultdict(set)
    for s in formal:
        for m in problem.song(s.song_code).members:
            busy[(m, s.date)].update(s.hours)
    trips = gaps = overtime = 0
    focus_days = 0
    for (m, d), hs in busy.items():
        if not hs:
            continue
        ordered = sorted(hs)
        visits = 1
        for a, b in zip(ordered, ordered[1:], strict=False):
            if b - a - 1 > config.merge_visit_gap:
                visits += 1
        trips += visits - 1
        gap = (ordered[-1] + 1) - ordered[0] - len(ordered)
        gaps += max(0, gap - config.free_gap)
        overtime += max(0, len(ordered) - config.soft_daily_limit)
        if m in rules.focus_members and d in date_idx:
            focus_days += 1

    spacing = 0
    hard_early = 0
    by_song: dict[str, list[Session]] = defaultdict(list)
    for s in formal:
        by_song[s.song_code].append(s)
    for code, ss in by_song.items():
        idx = [date_idx.get(s.date, 0) for s in ss]
        for i in range(len(idx)):
            for j in range(i + 1, len(idx)):
                diff = abs(idx[i] - idx[j])
                spacing += max(0, 2 - diff) + (100 if diff == 0 and not config.same_song_different_days else 0)
        if problem.song(code).difficulty == "困难" and idx:
            hard_early += 100 * max(idx) + sum(idx)

    soft_avoid = 0
    for s in formal:
        for m in problem.song(s.song_code).members:
            if m in s.absent_members:
                continue
            soft_avoid += sum(1 for h in s.hours if problem.availability.is_avoid(m, s.date, h))

    return {
        "absent": absent,
        "eval_attendance": eval_missing,
        "hard_early": hard_early,
        "spacing": spacing,
        "focus_days": focus_days,
        "trips": trips,
        "gaps": gaps,
        "overtime": overtime,
        "soft_avoid": soft_avoid,
    }
