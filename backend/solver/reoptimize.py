"""少改动重排(开发文档 §4.8 EDIT-11):在现有排练表上,只挪动必要的场次来消除冲突。

- 每一场未锁定、可挪动的正规排练是一个任务:时长不变,只换时间。缺席与拖动时的规则一致(EDIT-14):
  放到哪个时段,参演成员里那段时间没空的就缺席(「最多参加 N 场」计划内缺席的保留,未提交空闲的不算);
  留在原位时保持现在记录的缺席。缺席按演出设置允许的规则检查(一场最多缺 1 人、缺席比例、每首至少几场全员到齐等);
- 锁定的场次、满足「固定场次」要求的场次(每条要求留一场)、无法挪动的场次(比单日上限还长、找不到任何可行时段、
  同曲场次比排练日还多时多出来的)原样保留,照样占用成员的时间、计入各项缺席上限(它们自身的冲突留给管理员处理);
  曲目已删除的场次只占当天的场次数;评估场不参与;
- 其余硬约束与校验器一致(时段允许、不重叠、单日上限、同曲不同天、指定日期场次上限);
- 目标依次为:被挪动的场数最少 → 挪动幅度最小(换天比同一天内挪时间代价大)。
- 结果只是“提案”(每场的新时间),由调用方预览、确认后再写入(写入时按新时段重算缺席,与这里一致)。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from ortools.sat.python import cp_model

from .model import Blocker, build_model
from .timegrid import block_allowed
from .types import KIND_FORMAL, Candidate, Problem, Session, Task


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


def _free(problem: Problem, member: str, d: date, start: int, duration: int, submitted: set[str]) -> bool:
    """还没提交空闲的成员不知道有没有空:不当作没空(与拖动时自动记缺席一致)。"""
    return member not in submitted or all(problem.availability.is_available(member, d, h) for h in range(start, start + duration))


def _slots(problem: Problem, s: Session, dates: list[date], submitted: set[str]) -> tuple[list[Candidate], bool]:
    """这一场(时长不变)可以放的时段与缺席:那段时间没空的参演成员缺席,计划内缺席(出勤上限)保留;最多缺 1 人。
    原位保持现在记录的缺席。返回(候选, 原位是否成立)。"""
    config, rules = problem.config, problem.rules
    code = s.song_code or ""
    members = problem.song(code).members
    planned = {m for m in s.absent_members if rules.attendance_cap(m, code) is not None}
    out: list[Candidate] = []
    here_ok = False
    for di, d in enumerate(dates):
        for start in range(0, config.slots_per_day - s.duration + 1):
            if not block_allowed(config, rules, d, start, s.duration):
                continue
            if (d, start) == (s.date, s.start):
                absent = set(s.absent_members)  # 留在原位:缺席照旧
                attending = [m for m in members if m not in absent]
                if len(absent) <= 1 and all(_free(problem, m, d, start, s.duration, submitted) for m in attending):
                    here_ok = True
                else:
                    continue
            else:
                busy = {m for m in members if m not in planned and not _free(problem, m, d, start, s.duration, submitted)}
                absent = planned | busy
                if len(absent) > 1:
                    continue
            who = next(iter(absent), None)
            out.append(Candidate(di, start, s.duration, who, excused=who is not None and rules.attendance_cap(who, code) is not None))
    return out, here_ok


def reoptimize(
    problem: Problem,
    sessions: list[Session],
    *,
    time_limit: float = 10.0,
    workers: int = 2,
    seed: int = 42,
    submitted: set[str] | None = None,
) -> ReoptResult:
    """sessions:当前版本的全部场次(含评估场、锁定场次)。只挪动未锁定、可建模的正规排练。
    submitted:已提交空闲的成员(与写入时自动记缺席一致);不给时按空闲表里有记录的成员。"""
    config = problem.config
    dates = list(config.formal_dates)
    known = {s.code for s in problem.songs}
    submitted = set(problem.availability.members()) if submitted is None else set(submitted)
    blockers: list[Blocker] = []
    stuck_locked: list[Session] = []

    def key(s: Session) -> tuple:
        absent = s.absent_members[0] if len(s.absent_members) == 1 else tuple(s.absent_members) or None
        return (s.song_code, s.date, s.start, s.duration, absent)

    formal_all = [i for i, s in enumerate(sessions) if s.kind == KIND_FORMAL]
    formal = [i for i in formal_all if sessions[i].date in dates]
    # 「固定场次」要求:每条留一场原样不动(已有锁定的就用锁定的),其余同样的场次照常可挪
    pinned: set[int] = set()
    for f in problem.rules.fixed_sessions:
        want = (f.song_code, f.date, f.start, f.duration, f.absent_member)
        match = [i for i in formal if sessions[i].song_code in known and key(sessions[i]) == want]
        match.sort(key=lambda i: not sessions[i].locked)
        if match and not sessions[match[0]].locked:
            pinned.add(match[0])
    movable: list[tuple[int, list[Candidate]]] = []
    for i in formal_all:
        s = sessions[i]
        code = s.song_code or ""
        members = tuple(problem.song(code).members) if code in known else ()
        if s.date not in dates:
            # 不在正规排练日(如演出日期改过):不参与挪动、不占时段,但缺席 / 出勤照常计入各项上限(与校验器一致)
            blockers.append(Blocker(code, members, -1, s.start, s.duration, tuple(s.absent_members)))
            continue
        di = dates.index(s.date)
        if code not in known:
            # 曲目已删除:只占当天的场次数;缺席照常计入缺席场次总数
            blockers.append(Blocker(code, (), di, s.start, s.duration, tuple(s.absent_members)))
            continue
        planned = [m for m in s.absent_members if problem.rules.attendance_cap(m, code) is not None]
        ok = len(planned) <= 1 and s.duration <= config.hard_daily_limit
        slots, here_ok = _slots(problem, s, dates, submitted) if ok else ([], False)
        if s.locked or i in pinned or not slots:
            blockers.append(Blocker(code, members, di, s.start, s.duration, tuple(s.absent_members)))
            if s.locked and not here_ok:
                stuck_locked.append(s)
            continue
        movable.append((i, slots))
    # 同曲不同天:一首曲目可挪的场次比剩下的排练日还多时,逐场原样保留多出来的——
    # 优先留在这首曲目已经占用的日子上的(不再多占一天),否则留最晚的;每留一场,它那天也算占用
    if config.same_song_different_days:
        for code in sorted({sessions[i].song_code or "" for i, _ in movable}):
            mine = [m for m in movable if sessions[m[0]].song_code == code]
            mine.sort(key=lambda m: (sessions[m[0]].date, sessions[m[0]].start))
            taken = {b.date_idx for b in blockers if b.song_code == code and b.date_idx >= 0}
            while mine and len(mine) > len(dates) - len(taken):
                pick = next((m for m in reversed(mine) if dates.index(sessions[m[0]].date) in taken), mine[-1])
                s = sessions[pick[0]]
                mine.remove(pick)
                movable.remove(pick)
                blockers.append(
                    Blocker(code, tuple(problem.song(code).members), dates.index(s.date), s.start, s.duration, tuple(s.absent_members))
                )
                taken.add(dates.index(s.date))
    if not movable:
        return _nothing(problem, stuck_locked, "没有可以挪动的场次")

    # 现有排练表的各项缺席计数(与校验器一样按全部正规场次):已经超出、挪动解决不了的,只要求不更糟
    baseline: dict[tuple, int] = {}

    def bump(k: tuple) -> None:
        baseline[k] = baseline.get(k, 0) + 1

    for s in (sessions[i] for i in formal_all):
        code = s.song_code or ""
        unexcused = [m for m in s.absent_members if not problem.rules.planned_absence(m, code)]
        if unexcused:
            bump(("cap",))
        if code not in known:
            continue
        if unexcused:
            bump(("song", code))
        for m in unexcused:
            bump(("member", code, m))
        for m in s.absent_members:
            bump(("allow", m, code))
        for m in problem.song(code).members:
            if m not in s.absent_members:
                bump(("attend", m, code))

    def here_of(i: int, slots: list[Candidate]) -> int | None:
        s = sessions[i]
        return next((k for k, c in enumerate(slots) if dates[c.date_idx] == s.date and c.start == s.start), None)

    result = _solve(problem, sessions, dates, movable, blockers, baseline, here_of, time_limit, workers, seed)
    if result.status == "infeasible" and result.message.startswith(_NO_WAY):
        # 有的场次怎么挪都不行(如只有让人缺席才放得下,而缺席已到上限):它们原样保留,其余的照样解决
        stuck = [(i, slots) for i, slots in movable if here_of(i, slots) is None]
        if stuck:
            rest = [m for m in movable if m not in stuck]
            kept = [_keep(problem, dates, sessions[i]) for i, _ in stuck]
            if rest:
                retry = _solve(problem, sessions, dates, rest, blockers + kept, baseline, here_of, time_limit, workers, seed)
                if retry.status == "ok":
                    retry.message += f";另有 {len(stuck)} 场怎么挪都解决不了,原样保留"
                    return retry
    if result.status == "unchanged":
        return _nothing(problem, stuck_locked, result.message, optimal=result.optimal)
    return result


_NO_WAY = "只靠挪动未锁定的场次无法消除冲突"


def _keep(problem: Problem, dates: list[date], s: Session) -> Blocker:
    code = s.song_code or ""
    return Blocker(code, tuple(problem.song(code).members), dates.index(s.date), s.start, s.duration, tuple(s.absent_members))


# 新增一位计划外缺席的代价(放在挪动幅度目标里,远大于任何挪动距离):同样挪动场数时优先挪到大家都能来的时段
_NEW_ABSENCE_COST = 1000


def _solve(
    problem: Problem,
    sessions: list[Session],
    dates: list[date],
    movable: list[tuple[int, list[Candidate]]],
    blockers: list[Blocker],
    baseline: dict[tuple, int],
    here_of,  # noqa: ANN001
    time_limit: float,
    workers: int,
    seed: int,
) -> ReoptResult:
    tasks: list[Task] = []
    candidates: dict[str, list[Candidate]] = {}
    task_index: dict[str, int] = {}
    for i, slots in movable:
        s = sessions[i]
        task = Task(f"{s.song_code}#{i}", s.song_code or "", len(tasks) + 1, s.duration)
        tasks.append(task)
        task_index[task.task_id] = i
        candidates[task.task_id] = slots
    # 缺席按演出设置允许的规则(阶梯最宽松的一层)检查,与校验器一致;固定场次要求已作为原样保留的场次处理
    level = problem.ladder[-1]
    p = replace(problem, rules=replace(problem.rules, fixed_sessions=()))
    bundle = build_model(p, tasks, candidates, level, symmetry=False, blockers=tuple(blockers), absence_baseline=baseline)
    model, x = bundle.model, bundle.x
    moved_terms = []
    dist_terms = []
    for t in tasks:
        i = task_index[t.task_id]
        s = sessions[i]
        here = here_of(i, candidates[t.task_id])
        moved_terms.append(1 - x[(t.task_id, here)] if here is not None else 1)
        for k, c in enumerate(candidates[t.task_id]):
            day_gap = abs((dates[c.date_idx] - s.date).days)
            cost = (100 + 10 * day_gap if day_gap else 0) + abs(c.start - s.start)
            if k != here and c.absent_member is not None and not problem.rules.planned_absence(c.absent_member, t.song_code):
                cost += _NEW_ABSENCE_COST
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

    def failed(status: int) -> ReoptResult:
        if status == cp_model.UNKNOWN:
            return ReoptResult("infeasible", "在时间限制内没找到办法(不一定真的无解),可以再试一次或先手动调整几场")
        return ReoptResult("infeasible", _NO_WAY + ";可以解锁部分场次、调整缺席,或用 AI 调度员找其他办法")

    def keep_hints(solver: cp_model.CpSolver) -> None:
        model.clear_hints()
        for t in tasks:
            for k in range(len(candidates[t.task_id])):
                model.add_hint(x[(t.task_id, k)], solver.value(x[(t.task_id, k)]))

    # 第一步:缺席超出上限的量尽量减到最少(拖到有人没空的时段造成的缺席超出,挪开就能解决)
    excess = bundle.objective_terms["absence_excess"]
    optimal = True
    if excess.count:
        model.minimize(excess.expr)
        solver, status = run()
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return failed(status)
        optimal = status == cp_model.OPTIMAL
        model.add(excess.expr <= int(round(solver.objective_value)))
        keep_hints(solver)
    # 第二步:被挪动的场数最少
    model.minimize(moved)
    solver, status = run()
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return failed(status)
    optimal = optimal and status == cp_model.OPTIMAL
    model.add(moved == int(round(solver.objective_value)))
    keep_hints(solver)
    # 第三步:少让人缺席,再让挪动幅度最小
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
        return ReoptResult("unchanged", "现在的排练表已经没有可以靠挪动解决的冲突", optimal=optimal)
    return ReoptResult("ok", f"建议挪动 {len(moves)} 场", moves=moves, optimal=optimal)


def _nothing(problem: Problem, stuck_locked: list[Session], message: str, *, optimal: bool = False) -> ReoptResult:
    """没有可挪的:锁定的场次本身有冲突时说清楚是哪几场。"""
    if stuck_locked:
        names = "、".join(f"{problem.song(s.song_code).name} {s.date.month}/{s.date.day}" for s in stuck_locked[:3])
        return ReoptResult("locked_conflict", f"锁定的 {names} 本身有冲突(有成员没空或落在禁排时段),挪动其他场次解决不了;请先解锁或调整它")
    return ReoptResult("unchanged", message, optimal=optimal)
