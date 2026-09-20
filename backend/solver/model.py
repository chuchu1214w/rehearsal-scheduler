"""CP-SAT 模型:硬约束与各优化目标项(开发文档 §5.4、§5.5、§5.7)。

只负责“建模”,不负责求解顺序;字典序求解见 ``lexicographic.py``。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .types import Candidate, LadderLevel, Problem, Task


class NoCandidatesError(ValueError):
    def __init__(self, task_ids: list[str]) -> None:
        super().__init__("以下任务没有任何候选时段:" + "、".join(task_ids))
        self.task_ids = task_ids


class FixedSessionError(ValueError):
    pass


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


def build_model(
    problem: Problem,
    tasks: list[Task],
    candidates: dict[str, list[Candidate]],
    level: LadderLevel,
) -> ModelBundle:
    config, rules = problem.config, problem.rules
    dates = config.formal_dates
    n_days = len(dates)
    slots = config.slots_per_day

    zero = [t.task_id for t in tasks if not candidates[t.task_id]]
    if zero:
        raise NoCandidatesError(zero)

    model = cp_model.CpModel()
    x: dict[tuple[str, int], cp_model.IntVar] = {}
    day_vars: dict[str, cp_model.IntVar] = {}
    start_abs: dict[str, cp_model.IntVar] = {}

    # HC-01:每个任务恰好一个候选;派生日期与绝对开始格
    for task in tasks:
        cands = candidates[task.task_id]
        vars_for_task = []
        for ci, _ in enumerate(cands):
            v = model.new_bool_var(f"x_{task.task_id}_{ci}")
            x[(task.task_id, ci)] = v
            vars_for_task.append(v)
        model.add_exactly_one(vars_for_task)
        day = model.new_int_var(0, n_days - 1, f"day_{task.task_id}")
        model.add(day == sum(c.date_idx * x[(task.task_id, ci)] for ci, c in enumerate(cands)))
        sa = model.new_int_var(0, n_days * slots - 1, f"start_{task.task_id}")
        model.add(sa == sum((c.date_idx * slots + c.start) * x[(task.task_id, ci)] for ci, c in enumerate(cands)))
        day_vars[task.task_id] = day
        start_abs[task.task_id] = sa

    # 对称性破除:同曲同时长的任务按编号顺序开始,不改变可行解集合
    groups: dict[tuple[str, int], list[Task]] = defaultdict(list)
    for task in tasks:
        groups[(task.song_code, task.duration)].append(task)
    for group in groups.values():
        group = sorted(group, key=lambda t: t.task_no)
        for left, right in zip(group, group[1:], strict=False):
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
                if relevant:
                    model.add(sum(relevant) <= 1)  # HC-04:同一成员同一格至多一场
                    model.add(y == sum(relevant))
                else:
                    model.add(y == 0)
                busy[(member, di, h)] = y
                ys.append(y)

            daily = model.new_int_var(0, slots, f"hours_{member}_{di}")
            model.add(daily == sum(ys))
            model.add(daily <= config.hard_daily_limit)  # HC-07
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
                    model.add(diff >= 1)
                    spacing_terms.append(shortfall)
                else:
                    same_day = model.new_bool_var(f"sameday_{left.task_id}_{right.task_id}")
                    model.add(diff == 0).only_enforce_if(same_day)
                    model.add(diff >= 1).only_enforce_if(same_day.negated())
                    spacing_terms.append(100 * same_day + shortfall)

    # 缺席:计划缺席(excused)不计入阶梯限制,但计入 OB-02,使成员在上限内尽量多出勤
    absent_all: list[cp_model.IntVar] = []
    absent_unexcused: list[cp_model.IntVar] = []
    for t in tasks:
        for ci, c in enumerate(candidates[t.task_id]):
            if c.absent_member is not None:
                absent_all.append(x[(t.task_id, ci)])
                if not c.excused:
                    absent_unexcused.append(x[(t.task_id, ci)])

    if absent_unexcused:
        # HC-11 缺席场次总数上限
        model.add(sum(absent_unexcused) <= level.max_absent_sessions(len(tasks)))
        for code, song_tasks in tasks_by_song.items():
            n = len(song_tasks)
            min_full = n if level.per_song_min_full is None else min(level.per_song_min_full, n)
            song_unexcused = [
                x[(t.task_id, ci)]
                for t in song_tasks
                for ci, c in enumerate(candidates[t.task_id])
                if c.absent_member is not None and not c.excused
            ]
            if song_unexcused:
                model.add(sum(song_unexcused) <= n - min_full)  # HC-09
            for m in problem.song(code).members:
                member_unexcused = [
                    x[(t.task_id, ci)]
                    for t in song_tasks
                    for ci, c in enumerate(candidates[t.task_id])
                    if c.absent_member == m and not c.excused
                ]
                if member_unexcused:
                    model.add(sum(member_unexcused) <= level.per_member_per_song_max_absent)  # HC-10

    # HC-13 规则模板 ①:成员–曲目出勤上限
    for (m, code), cap in rules.member_song_max_attendance.items():
        attended = [
            x[(t.task_id, ci)] for t in tasks_by_song.get(code, []) for ci, c in enumerate(candidates[t.task_id]) if c.absent_member != m
        ]
        if attended:
            model.add(sum(attended) <= cap)

    # HC-13 规则模板 ③:指定日期最多场次
    for d, limit in rules.max_sessions_per_date.items():
        if d not in dates:
            continue
        di = dates.index(d)
        on_day = [x[(t.task_id, ci)] for t in tasks for ci, c in enumerate(candidates[t.task_id]) if c.date_idx == di]
        if on_day:
            model.add(sum(on_day) <= limit)

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

    objective_terms = {
        "absent": ObjectiveTerm(sum(absent_all), len(absent_all)),
        "hard_early": ObjectiveTerm(sum(hard_terms), len(hard_terms)),
        "spacing": ObjectiveTerm(sum(spacing_terms), len(spacing_terms)),
        "focus_days": ObjectiveTerm(sum(focus_terms), len(focus_terms)),
        "trips": ObjectiveTerm(sum(trip_terms), len(trip_terms)),
        "gaps": ObjectiveTerm(sum(gap_terms), len(gap_terms)),
        "overtime": ObjectiveTerm(sum(overtime_terms), len(overtime_terms)),
        "soft_avoid": ObjectiveTerm(sum(soft_terms), len(soft_terms)),
    }
    return ModelBundle(model, list(tasks), candidates, x, day_vars, busy, objective_terms, level)
