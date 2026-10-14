"""CP-SAT 模型:硬约束与各优化目标项(开发文档 §5.4、§5.5、§5.7)。

只负责“建模”,不负责求解顺序;字典序求解见 ``lexicographic.py``。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

from ortools.sat.python import cp_model

from .types import Candidate, LadderLevel, Problem, Task


class NoCandidatesError(ValueError):
    def __init__(self, task_ids: list[str]) -> None:
        super().__init__("以下任务没有任何候选时段:" + "、".join(task_ids))
        self.task_ids = task_ids


class FixedSessionError(ValueError):
    pass


@dataclass(frozen=True)
class Blocker:
    """不参与求解、原样保留的场次(少改动重排里锁定的、无法挪动的场次):照样占用成员的时间,
    计入单日上限、指定日期场次上限与同曲不同天。members 为空时只占「这一天的场次数」(如曲目已删除的场次)。"""

    song_code: str
    members: tuple[str, ...]
    date_idx: int
    start: int
    duration: int
    absent: tuple[str, ...] = ()  # 这场里缺席的成员(计入各项缺席上限)


@dataclass
class ObjectiveTerm:
    expr: object  # LinearExpr 或 int
    count: int  # 适用项数量;0 表示该目标在本模型中无意义


@dataclass
class ModelBundle:
    model: cp_model.CpModel
    tasks: list[Task]
    candidates: dict[str, list[Candidate]]
    x: dict[tuple[str, int], cp_model.IntVar]
    day_vars: dict[str, cp_model.IntVar]
    busy: dict[tuple[str, int, int], cp_model.IntVar]
    objective_terms: dict[str, ObjectiveTerm]
    level: LadderLevel
    scheduled: dict[str, cp_model.IntVar] | None = None  # 仅“部分排程”模型:任务是否排上


def build_model(
    problem: Problem,
    tasks: list[Task],
    candidates: dict[str, list[Candidate]],
    level: LadderLevel,
    partial: bool = False,
    *,
    symmetry: bool = True,
    blockers: tuple[Blocker, ...] = (),
    frozen_absence: bool = False,
    absence_baseline: dict[tuple, int] | None = None,
) -> ModelBundle:
    """partial=True 时放宽 HC-01 为“至多一个候选”,其余硬约束不变,并增加目标项 missing(未排场次)。

    用于无解时先排出能排的场次(开发文档 §5.8)。

    少改动重排(开发文档 §4.8 EDIT-11)用到的选项:
    - symmetry=False:任务对应具体的现有场次(各自的锁定、缺席、身份),不能互换,不加同曲同时长的顺序约束;
    - blockers:原样保留的场次(见 Blocker);它们之间已有的冲突不在这里解决(不让模型因此无解);
    - frozen_absence=True:每场谁缺席保持不变,只与缺席有关的约束(阶梯、出勤上限、允许缺席次数)与挪动无关,不加。
    - absence_baseline:现在整版的各项缺席计数;已经超出上限的不要求修好(挪动解决不了),只要求不更糟。
      键:("cap",) 有人缺席的场次数、("song", 曲目) 该曲目有人缺席的场次数、("member", 曲目, 成员)、
      ("allow", 成员, 曲目) 该成员在该曲目的缺席次数(含计划内)、("attend", 成员, 曲目) 出勤次数。
    """
    base = absence_baseline or {}
    excess_terms: list = []  # 少改动重排:各项缺席超出上限的量(先尽量减到最少)

    def capped(expr, value: int, key: tuple, kept: int, name: str) -> None:  # noqa: ANN001
        """expr(要排的任务) + kept(原样保留的) ≤ value。给了 absence_baseline 时:现在已超出的不要求修好、只要求不更糟,
        超出量另计为目标项 absence_excess(调用方先把它降到最少)。"""
        model.add(expr <= max(max(value, base.get(key, value)) - kept, 0))
        if absence_baseline is not None:
            ex = model.new_int_var(0, len(tasks) + len(blockers) + 1, f"excess_{name}")
            model.add(ex >= expr + kept - value)
            excess_terms.append(ex)

    config, rules = problem.config, problem.rules
    dates = config.formal_dates
    n_days = len(dates)
    slots = config.slots_per_day

    zero = [t.task_id for t in tasks if not candidates[t.task_id]]
    if zero and not partial:
        raise NoCandidatesError(zero)

    model = cp_model.CpModel()
    x: dict[tuple[str, int], cp_model.IntVar] = {}
    day_vars: dict[str, cp_model.IntVar] = {}
    start_abs: dict[str, cp_model.IntVar] = {}
    scheduled: dict[str, cp_model.IntVar] = {}

    # HC-01:每个任务恰好一个候选(部分排程时至多一个);派生日期与绝对开始格
    for task in tasks:
        cands = candidates[task.task_id]
        vars_for_task = []
        for ci, _ in enumerate(cands):
            v = model.new_bool_var(f"x_{task.task_id}_{ci}")
            x[(task.task_id, ci)] = v
            vars_for_task.append(v)
        day = model.new_int_var(0, n_days - 1, f"day_{task.task_id}")
        sa = model.new_int_var(0, n_days * slots - 1, f"start_{task.task_id}")
        day_expr = sum(c.date_idx * x[(task.task_id, ci)] for ci, c in enumerate(cands))
        sa_expr = sum((c.date_idx * slots + c.start) * x[(task.task_id, ci)] for ci, c in enumerate(cands))
        if partial:
            on = model.new_bool_var(f"sched_{task.task_id}")
            model.add(sum(vars_for_task) == on)
            # 未排上的任务日期 / 开始格不受约束,不影响其他约束
            model.add(day == day_expr).only_enforce_if(on)
            model.add(sa == sa_expr).only_enforce_if(on)
            scheduled[task.task_id] = on
        else:
            model.add_exactly_one(vars_for_task)
            model.add(day == day_expr)
            model.add(sa == sa_expr)
        day_vars[task.task_id] = day
        start_abs[task.task_id] = sa

    # 对称性破除:同曲同时长的任务按编号顺序开始,不改变可行解集合
    groups: dict[tuple[str, int], list[Task]] = defaultdict(list)
    for task in tasks:
        groups[(task.song_code, task.duration)].append(task)
    for group in groups.values() if symmetry else ():
        group = sorted(group, key=lambda t: t.task_no)
        for left, right in zip(group, group[1:], strict=False):
            if partial:
                # 同组任务可互换:编号小的先排上,两者都排上时按开始先后
                model.add(scheduled[left.task_id] >= scheduled[right.task_id])
                model.add(start_abs[left.task_id] < start_abs[right.task_id]).only_enforce_if(scheduled[right.task_id])
            else:
                model.add(start_abs[left.task_id] < start_abs[right.task_id])

    # 覆盖表:成员 × 日 × 格 → 会占用该格的候选变量。缺席成员仍按占用处理(保守)。
    cover: dict[tuple[str, int, int], list[cp_model.IntVar]] = defaultdict(list)
    for task in tasks:
        members = problem.song(task.song_code).members
        for ci, c in enumerate(candidates[task.task_id]):
            v = x[(task.task_id, ci)]
            for m in members:
                for h in c.hours:
                    cover[(m, c.date_idx, h)].append(v)

    # 原样保留的场次:成员 × 日 × 格 是否已被占用;成员 × 日 的小时数(按场次时长累加,与校验器 V-05 一致)
    fixed_cover: set[tuple[str, int, int]] = set()
    fixed_hours: dict[tuple[str, int], int] = defaultdict(int)
    for b in blockers:
        for m in b.members:
            fixed_hours[(m, b.date_idx)] += b.duration
            for h in range(b.start, b.start + b.duration):
                fixed_cover.add((m, b.date_idx, h))

    active_members = sorted({m for t in tasks for m in problem.song(t.song_code).members}, key=problem.member_index)
    busy: dict[tuple[str, int, int], cp_model.IntVar] = {}
    day_active: dict[tuple[str, int], cp_model.IntVar] = {}
    trip_terms: list = []
    gap_terms: list = []
    overtime_terms: list = []
    use_overtime = config.soft_daily_limit < config.hard_daily_limit

    for member in active_members:
        for di in range(n_days):
            ys: list[cp_model.IntVar] = []
            for h in range(slots):
                y = model.new_bool_var(f"busy_{member}_{di}_{h}")
                relevant = cover.get((member, di, h), [])
                fixed = 1 if (member, di, h) in fixed_cover else 0
                if relevant:
                    model.add(sum(relevant) + fixed <= 1)  # HC-04:同一成员同一格至多一场
                    model.add(y == sum(relevant) + fixed)
                else:
                    model.add(y == fixed)
                busy[(member, di, h)] = y
                ys.append(y)

            daily = model.new_int_var(0, slots, f"hours_{member}_{di}")
            model.add(daily == sum(ys))
            # HC-07,与校验器 V-05 一样按场次时长累加:原样保留的场次按时长计(它们之间可能互相重叠,
            # 占用的格数会少于时长),其余是要排的任务的小时数;原样保留的已超过上限时不因此无解,只是不能再加
            fh = fixed_hours.get((member, di), 0)
            fixed_slots = sum(1 for h in range(slots) if (member, di, h) in fixed_cover)
            model.add(daily - fixed_slots <= max(config.hard_daily_limit - fh, 0))
            active = model.new_bool_var(f"active_{member}_{di}")
            model.add_max_equality(active, ys)
            day_active[(member, di)] = active

            # OB-06 往返:若当前格忙、且前 merge_visit_gap+1 格都不忙,则是一次新到场
            lookback = config.merge_visit_gap + 1
            visit_starts: list[cp_model.IntVar] = []
            for h, y in enumerate(ys):
                sv = model.new_bool_var(f"visit_{member}_{di}_{h}")
                previous = ys[max(0, h - lookback) : h]
                model.add(sv <= y)
                if not previous:
                    model.add(sv == y)
                else:
                    for p in previous:
                        model.add(sv <= 1 - p)
                    model.add(sv >= y - sum(previous))
                visit_starts.append(sv)
            extra = model.new_int_var(0, slots, f"extratrips_{member}_{di}")
            model.add(extra == sum(visit_starts) - active)
            trip_terms.append(extra)

            # OB-07 空档 = 最晚结束 − 最早开始 − 实际小时
            first_c: list[cp_model.IntVar] = []
            last_c: list[cp_model.IntVar] = []
            for h, y in enumerate(ys):
                ft = model.new_int_var(0, slots, f"first_{member}_{di}_{h}")
                model.add(ft == h).only_enforce_if(y)
                model.add(ft == slots).only_enforce_if(y.negated())
                first_c.append(ft)
                lt = model.new_int_var(0, slots, f"last_{member}_{di}_{h}")
                model.add(lt == h + 1).only_enforce_if(y)
                model.add(lt == 0).only_enforce_if(y.negated())
                last_c.append(lt)
            first = model.new_int_var(0, slots, f"firststart_{member}_{di}")
            last = model.new_int_var(0, slots, f"lastend_{member}_{di}")
            model.add_min_equality(first, first_c)
            model.add_max_equality(last, last_c)
            gap = model.new_int_var(0, slots, f"gap_{member}_{di}")
            model.add(gap == last - first - daily).only_enforce_if(active)
            model.add(gap == 0).only_enforce_if(active.negated())
            excess = model.new_int_var(0, slots, f"excessgap_{member}_{di}")
            model.add_max_equality(excess, [gap - config.free_gap, 0])
            gap_terms.append(excess)

            # OB-08 超时(软上限 = 硬上限时恒为 0,不建项)
            if use_overtime:
                ot = model.new_int_var(0, slots, f"overtime_{member}_{di}")
                model.add_max_equality(ot, [daily - config.soft_daily_limit, 0])
                overtime_terms.append(ot)

    tasks_by_song: dict[str, list[Task]] = defaultdict(list)
    for t in tasks:
        tasks_by_song[t.song_code].append(t)

    # HC-08 同曲不同天(可关闭);OB-04 间隔不足量
    spacing_terms: list = []
    for song_tasks in tasks_by_song.values():
        for i in range(len(song_tasks)):
            for j in range(i + 1, len(song_tasks)):
                left, right = song_tasks[i], song_tasks[j]
                raw = model.new_int_var(-(n_days - 1), n_days - 1, f"rawdiff_{left.task_id}_{right.task_id}")
                model.add(raw == day_vars[left.task_id] - day_vars[right.task_id])
                diff = model.new_int_var(0, max(n_days - 1, 0), f"diff_{left.task_id}_{right.task_id}")
                model.add_abs_equality(diff, raw)
                shortfall = model.new_int_var(0, 2, f"shortfall_{left.task_id}_{right.task_id}")
                model.add_max_equality(shortfall, [2 - diff, 0])
                if config.same_song_different_days:
                    if partial:
                        both = model.new_bool_var(f"both_{left.task_id}_{right.task_id}")
                        model.add_multiplication_equality(both, [scheduled[left.task_id], scheduled[right.task_id]])
                        model.add(diff >= 1).only_enforce_if(both)
                    else:
                        model.add(diff >= 1)
                    spacing_terms.append(shortfall)
                else:
                    same_day = model.new_bool_var(f"sameday_{left.task_id}_{right.task_id}")
                    model.add(diff == 0).only_enforce_if(same_day)
                    model.add(diff >= 1).only_enforce_if(same_day.negated())
                    spacing_terms.append(100 * same_day + shortfall)
    if config.same_song_different_days:
        for b in blockers:
            for t in tasks_by_song.get(b.song_code, []):
                if partial:
                    model.add(day_vars[t.task_id] != b.date_idx).only_enforce_if(scheduled[t.task_id])
                else:
                    model.add(day_vars[t.task_id] != b.date_idx)

    # 缺席:计划内缺席(出勤上限 excused、允许缺席 allowed)不计入阶梯限制,但计入 OB-02,使成员尽量多出勤
    absent_all: list[cp_model.IntVar] = []
    absent_unexcused: list[cp_model.IntVar] = []
    for t in tasks:
        for ci, c in enumerate(candidates[t.task_id]):
            if c.absent_member is not None:
                absent_all.append(x[(t.task_id, ci)])
                if not rules.planned_absence(c.absent_member, t.song_code):
                    absent_unexcused.append(x[(t.task_id, ci)])

    # 原样保留的场次(少改动重排)里已有的缺席也计入各项上限:场次总数、每首场次数按整版算(与校验器一致)
    def kept_unexcused(code: str | None = None, member: str | None = None) -> int:
        return sum(
            1
            for b in blockers
            if (code is None or b.song_code == code)
            and any((member is None or m == member) and not rules.planned_absence(m, b.song_code) for m in b.absent)
        )

    if absent_unexcused and not frozen_absence:
        # HC-11 缺席场次总数上限;部分排程时按实际排上的场次计(与校验器一致)
        if partial:
            frac = Fraction(level.max_absent_ratio).limit_denominator(10_000)
            model.add(frac.denominator * sum(absent_unexcused) <= frac.numerator * sum(scheduled.values()))
        else:
            capped(sum(absent_unexcused), level.max_absent_sessions(len(tasks) + len(blockers)), ("cap",), kept_unexcused(), "cap")
        for code, song_tasks in tasks_by_song.items():
            n = len(song_tasks) + sum(1 for b in blockers if b.song_code == code)
            min_full = n if level.per_song_min_full is None else min(level.per_song_min_full, n)
            song_unexcused = [
                x[(t.task_id, ci)]
                for t in song_tasks
                for ci, c in enumerate(candidates[t.task_id])
                if c.absent_member is not None and not rules.planned_absence(c.absent_member, code)
            ]
            if song_unexcused and partial:
                # HC-09(部分排程):排上的 S 场里至少 min(要求, S) 场全员到齐
                placed = sum(scheduled[t.task_id] for t in song_tasks)
                if level.per_song_min_full is None:
                    model.add(sum(song_unexcused) == 0)
                else:
                    need = model.new_int_var(0, n, f"minfull_{code}")
                    model.add_min_equality(need, [level.per_song_min_full, placed])
                    model.add(sum(song_unexcused) <= placed - need)
            elif song_unexcused:
                capped(sum(song_unexcused), n - min_full, ("song", code), kept_unexcused(code), f"song_{code}")  # HC-09
            for m in problem.song(code).members:
                member_unexcused = [
                    x[(t.task_id, ci)]
                    for t in song_tasks
                    for ci, c in enumerate(candidates[t.task_id])
                    if c.absent_member == m and not rules.planned_absence(m, code)
                ]
                if member_unexcused:
                    capped(  # HC-10
                        sum(member_unexcused),
                        level.per_member_per_song_max_absent,
                        ("member", code, m),
                        kept_unexcused(code, m),
                        f"m_{code}_{m}",
                    )

    # HC-13 规则「允许缺席 N 次」:该成员在该曲目的缺席场次 ≤ N
    for (m, code), n in rules.member_song_max_absent.items() if not frozen_absence else ():
        absent_vars = [
            x[(t.task_id, ci)] for t in tasks_by_song.get(code, []) for ci, c in enumerate(candidates[t.task_id]) if c.absent_member == m
        ]
        if absent_vars:
            kept = sum(1 for b in blockers if b.song_code == code and m in b.absent)
            capped(sum(absent_vars), n, ("allow", m, code), kept, f"allow_{m}_{code}")

    # HC-13 规则模板 ①:成员–曲目出勤上限
    for (m, code), cap in rules.member_song_max_attendance.items() if not frozen_absence else ():
        attended = [
            x[(t.task_id, ci)] for t in tasks_by_song.get(code, []) for ci, c in enumerate(candidates[t.task_id]) if c.absent_member != m
        ]
        if attended:
            kept = sum(1 for b in blockers if b.song_code == code and m in b.members and m not in b.absent)
            capped(sum(attended), cap, ("attend", m, code), kept, f"attend_{m}_{code}")

    # HC-13 规则模板 ③:指定日期最多场次
    for d, limit in rules.max_sessions_per_date.items():
        if d not in dates:
            continue
        di = dates.index(d)
        on_day = [x[(t.task_id, ci)] for t in tasks for ci, c in enumerate(candidates[t.task_id]) if c.date_idx == di]
        if on_day:
            model.add(sum(on_day) <= max(limit - sum(1 for b in blockers if b.date_idx == di), 0))

    # HC-13 规则模板 ⑤ / HC-14:固定场次
    for fx in rules.fixed_sessions:
        di = dates.index(fx.date)
        matching = [
            x[(t.task_id, ci)]
            for t in tasks_by_song.get(fx.song_code, [])
            if t.duration == fx.duration
            for ci, c in enumerate(candidates[t.task_id])
            if c.date_idx == di and c.start == fx.start and c.absent_member == fx.absent_member
        ]
        if not matching:
            raise FixedSessionError(f"固定场次 {fx.song_code} {fx.date} {config.range_label(fx.start, fx.duration)} 没有对应的可行候选")
        model.add(sum(matching) == 1)

    # OB-05 指定成员集中排练日
    focus_terms = [day_active[(m, di)] for m in rules.focus_members if m in active_members for di in range(n_days)]

    # OB-03 困难曲目尽早(默认关闭,仅当出现在目标列表时才有意义)
    hard_terms: list = []
    for code, song_tasks in tasks_by_song.items():
        if problem.song(code).difficulty != "困难":
            continue
        song_days = [day_vars[t.task_id] for t in song_tasks]
        completion = model.new_int_var(0, n_days - 1, f"complete_{code}")
        model.add_max_equality(completion, song_days)
        hard_terms.append(100 * completion + sum(song_days))

    # OB-09 软偏好:到场成员在候选时段内命中“尽量避开”的小时数
    soft_terms: list = []
    for t in tasks:
        members = problem.song(t.song_code).members
        for ci, c in enumerate(candidates[t.task_id]):
            d = dates[c.date_idx]
            attending = [m for m in members if m != c.absent_member]
            penalty = sum(1 for m in attending for h in c.hours if problem.availability.is_avoid(m, d, h))
            if penalty:
                soft_terms.append(penalty * x[(t.task_id, ci)])

    # 部分排程:未排场次(困难曲目优先排上,作为同数量时的次序)
    missing_terms: list = []
    if partial:
        weight = {"困难": 3, "一般": 2, "简单": 1}
        for t in tasks:
            missing_terms.append((1000 + weight.get(problem.song(t.song_code).difficulty, 1)) * (1 - scheduled[t.task_id]))

    objective_terms = {
        "missing": ObjectiveTerm(sum(missing_terms), len(missing_terms)),
        "absent": ObjectiveTerm(sum(absent_all), len(absent_all)),
        "hard_early": ObjectiveTerm(sum(hard_terms), len(hard_terms)),
        "spacing": ObjectiveTerm(sum(spacing_terms), len(spacing_terms)),
        "focus_days": ObjectiveTerm(sum(focus_terms), len(focus_terms)),
        "trips": ObjectiveTerm(sum(trip_terms), len(trip_terms)),
        "gaps": ObjectiveTerm(sum(gap_terms), len(gap_terms)),
        "overtime": ObjectiveTerm(sum(overtime_terms), len(overtime_terms)),
        "soft_avoid": ObjectiveTerm(sum(soft_terms), len(soft_terms)),
        "absence_excess": ObjectiveTerm(sum(excess_terms), len(excess_terms)),
    }
    return ModelBundle(model, list(tasks), candidates, x, day_vars, busy, objective_terms, level, scheduled if partial else None)
