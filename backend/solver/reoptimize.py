"""少改动重排(开发文档 §4.8 EDIT-11):在现有排练表上,只挪动必要的场次来消除冲突。

- 每一场未锁定、可挪动的正规排练是一个任务:时长、谁缺席保持不变,只换时间;
- 锁定的场次、满足「固定场次」要求的场次(每条要求留一场)、无法挪动的场次(缺席超过 1 人、比单日上限还长、
  找不到任何可行时段、同曲场次比排练日还多时多出来的)原样保留,照样占用成员的时间(它们自身的冲突留给管理员处理);
  曲目已删除的场次只占当天的场次数;评估场不参与;
- 硬约束与校验器一致(时段允许、到场成员有空、不重叠、单日上限、同曲不同天、指定日期场次上限);
  只与缺席有关的规则与挪动无关,不参与;
- 目标依次为:被挪动的场数最少 → 挪动幅度最小(换天比同一天内挪时间代价大)。
- 结果只是“提案”(每场的新时间),由调用方预览、确认后再写入。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from ortools.sat.python import cp_model

from .model import Blocker, build_model
from .timegrid import block_allowed, members_available
from .types import KIND_FORMAL, Candidate, LadderLevel, Problem, Session, Task

# 缺席安排保持原样(不在这里改谁缺席),因此不需要缺席阶梯的限制
_ANY_ABSENCE = LadderLevel(99, 1.0, 0, 99)


@dataclass
class Move:
    index: int  # 在输入 sessions 里的下标
    date: date
    start: int


@dataclass
class ReoptResult:
    status: str  # ok / unchanged / infeasible / locked_conflict / error
    message: str
    moves: list[Move] = field(default_factory=list)
    optimal: bool = False


def _slots(problem: Problem, s: Session, dates: list[date]) -> list[Candidate]:
    """这一场(谁缺席不变、时长不变)可以放的全部时段:时段允许,到场的成员都有空。"""
    config = problem.config
    song = problem.song(s.song_code)
    absent = s.absent_members[0] if s.absent_members else None
    attending = [m for m in song.members if m != absent]
    out = []
    for di, d in enumerate(dates):
        for start in range(0, config.slots_per_day - s.duration + 1):
            if block_allowed(config, problem.rules, d, start, s.duration) and members_available(problem, attending, d, start, s.duration):
                out.append(Candidate(di, start, s.duration, absent))
    return out


def reoptimize(problem: Problem, sessions: list[Session], *, time_limit: float = 10.0, workers: int = 2, seed: int = 42) -> ReoptResult:
    """sessions:当前版本的全部场次(含评估场、锁定场次)。只挪动未锁定、可建模的正规排练。"""
    config = problem.config
    dates = list(config.formal_dates)
    known = {s.code for s in problem.songs}
    task_index: dict[str, int] = {}
    tasks: list[Task] = []
    candidates: dict[str, list[Candidate]] = {}
    blockers: list[Blocker] = []
    stuck_locked: list[Session] = []

    def key(s: Session) -> tuple:
        absent = s.absent_members[0] if len(s.absent_members) == 1 else tuple(s.absent_members) or None
        return (s.song_code, s.date, s.start, s.duration, absent)

    formal = [i for i, s in enumerate(sessions) if s.kind == KIND_FORMAL and s.date in dates]
    # 「固定场次」要求:每条留一场原样不动(已有锁定的就用锁定的),其余同样的场次照常可挪
    pinned: set[int] = set()
    for f in problem.rules.fixed_sessions:
        want = (f.song_code, f.date, f.start, f.duration, f.absent_member)
        match = [i for i in formal if sessions[i].song_code in known and key(sessions[i]) == want]
        match.sort(key=lambda i: not sessions[i].locked)
        if match and not sessions[match[0]].locked:
            pinned.add(match[0])
    movable: list[tuple[int, list[Candidate]]] = []
    for i in formal:
        s = sessions[i]
        di = dates.index(s.date)
        if s.song_code not in known:
            blockers.append(Blocker(s.song_code or "", (), di, s.start, s.duration))  # 曲目已删除:只占当天的场次数
            continue
        members = tuple(problem.song(s.song_code).members)
        ok = len(s.absent_members) <= 1 and s.duration <= config.hard_daily_limit
        slots = _slots(problem, s, dates) if ok else []
        if s.locked or i in pinned or not slots:
            blockers.append(Blocker(s.song_code, members, di, s.start, s.duration))
            if s.locked and not any(dates[c.date_idx] == s.date and c.start == s.start for c in slots):
                stuck_locked.append(s)
            continue
        movable.append((i, slots))
    # 同曲不同天:一首曲目可挪的场次比剩下的排练日还多时,逐场原样保留多出来的——
    # 优先留在这首曲目已经占用的日子上的(不再多占一天),否则留最晚的;每留一场,它那天也算占用
    if config.same_song_different_days:
        for code in sorted({sessions[i].song_code for i, _ in movable}):
            mine = [m for m in movable if sessions[m[0]].song_code == code]
            mine.sort(key=lambda m: (sessions[m[0]].date, sessions[m[0]].start))
            taken = {b.date_idx for b in blockers if b.song_code == code}
            while mine and len(mine) > len(dates) - len(taken):
                pick = next((m for m in reversed(mine) if dates.index(sessions[m[0]].date) in taken), mine[-1])
                s = sessions[pick[0]]
                mine.remove(pick)
                movable.remove(pick)
                blockers.append(Blocker(code, tuple(problem.song(code).members), dates.index(s.date), s.start, s.duration))
                taken.add(dates.index(s.date))
    for i, slots in movable:
        s = sessions[i]
        task = Task(f"{s.song_code}#{i}", s.song_code, len(tasks) + 1, s.duration)
        tasks.append(task)
        task_index[task.task_id] = i
        candidates[task.task_id] = slots
    if not tasks:
        return _nothing(problem, stuck_locked, "没有可以挪动的场次")

    # 场次方案只用于建任务;这里任务直接对应现有场次,固定场次要求已经作为原样保留的场次处理
    p = replace(problem, rules=replace(problem.rules, fixed_sessions=()), ladder=(LadderLevel(0), _ANY_ABSENCE))
    bundle = build_model(p, tasks, candidates, _ANY_ABSENCE, symmetry=False, blockers=tuple(blockers), frozen_absence=True)
    model, x = bundle.model, bundle.x
    moved_terms = []
    dist_terms = []
    for t in tasks:
        s = sessions[task_index[t.task_id]]
        here = next((k for k, c in enumerate(candidates[t.task_id]) if dates[c.date_idx] == s.date and c.start == s.start), None)
        moved_terms.append(1 - x[(t.task_id, here)] if here is not None else 1)
        for k, c in enumerate(candidates[t.task_id]):
            day_gap = abs((dates[c.date_idx] - s.date).days)
            cost = (100 + 10 * day_gap if day_gap else 0) + abs(c.start - s.start)
            if cost:
                dist_terms.append(cost * x[(t.task_id, k)])
            if k == here:
                model.add_hint(x[(t.task_id, k)], 1)
    moved = sum(moved_terms)
    dist = sum(dist_terms)

    def run() -> tuple[cp_model.CpSolver, int]:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit)
        solver.parameters.num_workers = int(workers)
        solver.parameters.random_seed = int(seed)
        return solver, solver.solve(model)

    model.minimize(moved)
    solver, status = run()
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.UNKNOWN:
            return ReoptResult("infeasible", "在时间限制内没找到办法(不一定真的无解),可以再试一次或先手动调整几场")
        return ReoptResult("infeasible", "只靠挪动未锁定的场次无法消除冲突;可以解锁部分场次、调整缺席,或用 AI 调度员找其他办法")
    optimal = status == cp_model.OPTIMAL
    best = int(round(solver.objective_value))
    model.add(moved == best)
    model.clear_hints()
    for t in tasks:
        for k in range(len(candidates[t.task_id])):
            model.add_hint(x[(t.task_id, k)], solver.value(x[(t.task_id, k)]))
    model.minimize(dist)
    solver2, status2 = run()
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solver, optimal = solver2, optimal and status2 == cp_model.OPTIMAL
    moves = []
    for t in tasks:
        i = task_index[t.task_id]
        for k, c in enumerate(candidates[t.task_id]):
            if solver.value(x[(t.task_id, k)]):
                d = dates[c.date_idx]
                if (d, c.start) != (sessions[i].date, sessions[i].start):
                    moves.append(Move(i, d, c.start))
                break
    if not moves:
        return _nothing(problem, stuck_locked, "现在的排练表已经没有可以靠挪动解决的冲突", optimal=optimal)
    return ReoptResult("ok", f"建议挪动 {len(moves)} 场", moves=moves, optimal=optimal)


def _nothing(problem: Problem, stuck_locked: list[Session], message: str, *, optimal: bool = False) -> ReoptResult:
    """没有可挪的:锁定的场次本身有冲突时说清楚是哪几场。"""
    if stuck_locked:
        names = "、".join(f"{problem.song(s.song_code).name} {s.date.month}/{s.date.day}" for s in stuck_locked[:3])
        return ReoptResult("locked_conflict", f"锁定的 {names} 本身有冲突(有成员没空或落在禁排时段),挪动其他场次解决不了;请先解锁或调整它")
    return ReoptResult("unchanged", message, optimal=optimal)
