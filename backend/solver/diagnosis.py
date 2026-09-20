"""无解诊断(开发文档 §5.8):无候选任务、缺口、只差一人的时段、最小调整建议、评估场诊断。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ortools.sat.python import cp_model

from .candidates import build_candidates, make_tasks
from .evaluation import choose_evaluation, diagnose_evaluation
from .timegrid import block_allowed, unavailable_hours, weekday_zh
from .types import Candidate, Problem, Task

if TYPE_CHECKING:
    from .lexicographic import SolveOptions


def _solver(problem: Problem, opts: SolveOptions | None, time_limit: float) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(time_limit)
    s.parameters.num_workers = int((opts.workers if opts and opts.workers else None) or problem.config.workers)
    s.parameters.random_seed = int(problem.config.seed)
    s.parameters.log_search_progress = False
    return s


def add_partial_hard_constraints(
    model: cp_model.CpModel,
    problem: Problem,
    tasks: Iterable[Task],
    candidates: dict[str, list[Candidate]],
    x: dict[tuple[str, int], cp_model.IntVar],
) -> None:
    """只保留“成员不重叠 + 单日硬上限”,用于诊断模型。"""
    cover: dict[tuple[str, int, int], list[cp_model.IntVar]] = defaultdict(list)
    tasks = list(tasks)
    for task in tasks:
        for ci, c in enumerate(candidates[task.task_id]):
            for m in problem.song(task.song_code).members:
                for h in c.hours:
                    cover[(m, c.date_idx, h)].append(x[(task.task_id, ci)])
    members = {m for t in tasks for m in problem.song(t.song_code).members}
    n_days = len(problem.config.formal_dates)
    for m in members:
        for di in range(n_days):
            hourly = []
            for h in range(problem.config.slots_per_day):
                rel = cover.get((m, di, h), [])
                if rel:
                    model.add(sum(rel) <= 1)
                    hourly.append(sum(rel))
            if hourly:
                model.add(sum(hourly) <= problem.config.hard_daily_limit)


def max_coverage(
    problem: Problem,
    tasks: list[Task],
    candidates: dict[str, list[Candidate]],
    opts: SolveOptions | None = None,
    time_limit: float = 45.0,
) -> tuple[int, dict[str, int], str]:
    """放宽“全部排完”,求最多能排多少场(难度高的优先)。"""
    model = cp_model.CpModel()
    x: dict[tuple[str, int], cp_model.IntVar] = {}
    scheduled: dict[str, cp_model.IntVar] = {}
    for task in tasks:
        vs = []
        for ci, _ in enumerate(candidates[task.task_id]):
            v = model.new_bool_var(f"cov_{task.task_id}_{ci}")
            x[(task.task_id, ci)] = v
            vs.append(v)
        s = model.new_bool_var(f"sched_{task.task_id}")
        scheduled[task.task_id] = s
        if vs:
            model.add(sum(vs) == s)
        else:
            model.add(s == 0)
    add_partial_hard_constraints(model, problem, tasks, candidates, x)
    tie = {"困难": 3, "一般": 2, "简单": 1}
    model.maximize(
        1000 * sum(scheduled.values()) + sum(tie.get(problem.song(t.song_code).difficulty, 1) * scheduled[t.task_id] for t in tasks)
    )
    solver = _solver(problem, opts, time_limit)
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return 0, {}, solver.status_name(status)
    counts: dict[str, int] = defaultdict(int)
    for t in tasks:
        counts[t.song_code] += solver.value(scheduled[t.task_id])
    return sum(counts.values()), dict(counts), solver.status_name(status)


def independent_song_max(problem: Problem, song_code: str, opts: SolveOptions | None = None) -> int:
    tasks = make_tasks(problem, [song_code])
    cands = build_candidates(problem, tasks, allow_absent=False)
    total, _, _ = max_coverage(problem, tasks, cands, opts, time_limit=15.0)
    return total


def missing_sessions(problem: Problem, song_codes: Iterable[str], global_counts: dict[str, int], opts=None) -> list[dict]:
    rows = []
    for code in song_codes:
        song = problem.song(code)
        required = len(song.durations(problem.config))
        alone = independent_song_max(problem, code, opts)
        got = global_counts.get(code, 0)
        rows.append(
            {
                "曲目": code,
                "曲目名": song.name,
                "要求场次": required,
                "单曲最多可排": alone,
                "单曲缺口": max(0, required - alone),
                "全局方案已排": got,
                "全局缺口": max(0, required - got),
            }
        )
    return rows


def near_miss(problem: Problem, song_codes: Iterable[str], limit: int = 250) -> list[dict]:
    """只差一名成员即可成立的全员时段,按需开放小时数升序。"""
    config = problem.config
    rows: list[dict] = []
    for code in song_codes:
        song = problem.song(code)
        for duration in sorted(set(song.durations(config)), reverse=True):
            for d in config.formal_dates:
                for start in range(0, config.slots_per_day - duration + 1):
                    if not block_allowed(config, problem.rules, d, start, duration):
                        continue
                    blockers = {m: unavailable_hours(problem, m, d, start, duration) for m in song.members}
                    blockers = {m: hs for m, hs in blockers.items() if hs}
                    if len(blockers) != 1:
                        continue
                    [(member, hours)] = blockers.items()
                    rows.append(
                        {
                            "曲目": code,
                            "曲目名": song.name,
                            "时长": duration,
                            "日期": d.isoformat(),
                            "星期": weekday_zh(d),
                            "时间段": config.range_label(start, duration),
                            "只差成员": member,
                            "需开放小时数": len(hours),
                            "需开放的格": [config.slot_label(h) for h in hours],
                        }
                    )
    rows.sort(key=lambda r: (r["需开放小时数"], r["日期"], r["曲目"], r["时间段"]))
    return rows[:limit]


def minimum_adjustment(
    problem: Problem,
    tasks: list[Task],
    opts: SolveOptions | None = None,
    time_limit: float = 60.0,
) -> dict:
    """允许把个人矩阵中的 0 格临时视为可用;先最少受影响成员数,再最少调整小时数。"""
    config = problem.config
    dates = config.formal_dates
    # 候选:只看窗口与禁排,不看个人可用度
    candidates: dict[str, list[Candidate]] = {}
    for t in tasks:
        candidates[t.task_id] = [
            Candidate(di, start, t.duration)
            for di, d in enumerate(dates)
            for start in range(0, config.slots_per_day - t.duration + 1)
            if block_allowed(config, problem.rules, d, start, t.duration)
        ]
    if any(not candidates[t.task_id] for t in tasks):
        return {"可行": False, "状态": "每日窗口本身容不下某些任务", "受影响成员数": 0, "调整小时数": 0, "调整": [], "放宽后示例": []}

    model = cp_model.CpModel()
    x: dict[tuple[str, int], cp_model.IntVar] = {}
    change: dict[tuple[str, int, int], cp_model.IntVar] = {}
    for t in tasks:
        vs = []
        members = problem.song(t.song_code).members
        for ci, c in enumerate(candidates[t.task_id]):
            v = model.new_bool_var(f"adj_{t.task_id}_{ci}")
            x[(t.task_id, ci)] = v
            vs.append(v)
            d = dates[c.date_idx]
            for m in members:
                for h in c.hours:
                    if not problem.availability.is_available(m, d, h):
                        key = (m, c.date_idx, h)
                        if key not in change:
                            change[key] = model.new_bool_var(f"open_{m}_{c.date_idx}_{h}")
                        model.add(v <= change[key])
        model.add_exactly_one(vs)
    add_partial_hard_constraints(model, problem, tasks, candidates, x)

    by_member: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    for (m, _di, _h), v in change.items():
        by_member[m].append(v)
    affected: dict[str, cp_model.IntVar] = {}
    for m, vs in by_member.items():
        f = model.new_bool_var(f"affected_{m}")
        model.add_max_equality(f, vs)
        affected[m] = f

    affected_expr = sum(affected.values())
    changed_expr = sum(change.values())
    model.minimize(affected_expr)
    s1 = _solver(problem, opts, time_limit)
    st1 = s1.solve(model)
    if st1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"可行": False, "状态": s1.status_name(st1), "受影响成员数": 0, "调整小时数": 0, "调整": [], "放宽后示例": []}
    best_affected = int(round(s1.objective_value))
    model.add(affected_expr == best_affected)
    model.minimize(changed_expr)
    s2 = _solver(problem, opts, time_limit)
    st2 = s2.solve(model)
    if st2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"可行": False, "状态": s2.status_name(st2), "受影响成员数": 0, "调整小时数": 0, "调整": [], "放宽后示例": []}
    best_changed = int(round(s2.objective_value))

    changes = [
        {"成员": m, "日期": dates[di].isoformat(), "星期": weekday_zh(dates[di]), "需开放的格": config.slot_label(h)}
        for (m, di, h), v in change.items()
        if s2.value(v)
    ]
    changes.sort(key=lambda r: (problem.member_index(r["成员"]), r["日期"], r["需开放的格"]))
    relaxed = []
    for t in tasks:
        for ci, c in enumerate(candidates[t.task_id]):
            if s2.value(x[(t.task_id, ci)]):
                d = dates[c.date_idx]
                relaxed.append(
                    {
                        "任务": t.task_id,
                        "曲目": t.song_code,
                        "日期": d.isoformat(),
                        "星期": weekday_zh(d),
                        "时间段": config.range_label(c.start, c.duration),
                    }
                )
                break
    relaxed.sort(key=lambda r: (r["日期"], r["时间段"], r["曲目"]))
    return {
        "可行": True,
        "状态": s2.status_name(st2),
        "严格最优": st1 == cp_model.OPTIMAL and st2 == cp_model.OPTIMAL,
        "受影响成员数": best_affected,
        "调整小时数": best_changed,
        "调整": changes,
        "放宽后示例": relaxed,
    }


def diagnose(problem: Problem, tasks: list[Task] | None = None, opts: SolveOptions | None = None) -> dict:
    """完整诊断报告(严格口径)。"""
    tasks = tasks if tasks is not None else make_tasks(problem)
    song_codes = sorted({t.song_code for t in tasks}, key=lambda c: [s.code for s in problem.songs].index(c))
    cands = build_candidates(problem, tasks, allow_absent=False)
    zero = [t.task_id for t in tasks if not cands[t.task_id]]
    total, counts, status = max_coverage(problem, tasks, cands, opts)
    report = {
        "无候选任务": zero,
        "最大覆盖": {"状态": status, "最多可排场次": total, "要求场次": len(tasks)},
        "各曲缺口": missing_sessions(problem, song_codes, counts, opts),
        "只差一人的时段": near_miss(problem, song_codes, limit=50),
        "最小调整建议": minimum_adjustment(problem, tasks, opts),
        "评估场": diagnose_evaluation(problem),
    }
    report["评估场"]["可行"] = choose_evaluation(problem) is not None
    return report
