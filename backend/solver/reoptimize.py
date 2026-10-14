"""少改动重排(开发文档 §4.8 EDIT-11):在现有排练表上,只挪动必要的场次来消除冲突。

专用的 CP-SAT 模型(不用求解排程的 build_model),约束与校验器逐条对应:
- 每一场未锁定的正规排练可以挪到别的时段(时长不变),也可以留在原位。挪过去时,参演成员里那段时间没空的缺席
  (「最多参加 N 场」计划内缺席保留,未提交空闲的不算,与写入时自动记缺席一致,EDIT-14),最多缺 1 人;
- 留在原位有两种:原样没问题(照常检查),或「原样保留」——它本身的冲突先不管(怎么挪都解决不了时),
  但别的场次不能挪进来和它冲突;
- 锁定的、满足「固定场次」要求的(每条要求留一场)场次不动,照样占用成员的时间;曲目已删除的场次只占当天的场次数;
  不在排练日内的场次只计入各项计数;评估场不参与;
- 硬约束:成员不重叠、单日小时上限、同曲不同天、指定日期场次上限、缺席规则(演出设置允许的那层:缺席场次比例、
  每首至少几场全员到齐、每人每首最多缺几次;「最多参加 / 允许缺席」要求);时段允许与到场成员有空由候选保证。
  现有排练表已经超出、挪动解决不了的,只要求不更糟;
- 目标依次为:「原样保留」(仍有冲突)的场次最少 → 超出上限的量最少 → 挪动的场数最少 →
  少让人新缺席、挪动幅度最小(换天比同一天内挪时间代价大)。
- 结果只是“提案”(每场的新时间),由调用方预览、确认后再写入(写入时按新时段重算缺席,与这里一致)。
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from ortools.sat.python import cp_model

from .timegrid import block_allowed
from .types import KIND_FORMAL, Problem, Session


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


@dataclass
class _Option:
    """一场排练的一种放法:日期下标、开始格、缺席成员。"""

    day: int
    start: int
    absent: tuple[str, ...]


# 新增一位计划外缺席的代价(放在挪动幅度目标里,远大于任何挪动距离):同样挪动场数时优先挪到大家都能来的时段
_NEW_ABSENCE_COST = 1000


def reoptimize(
    problem: Problem,
    sessions: list[Session],
    *,
    time_limit: float = 10.0,
    workers: int = 2,
    seed: int = 42,
    submitted: set[str] | None = None,
) -> ReoptResult:
    """sessions:当前版本的全部场次(含评估场、锁定场次)。
    submitted:已提交空闲的成员(与写入时自动记缺席一致);不给时按空闲表里有记录的成员。"""
    config, rules = problem.config, problem.rules
    dates = list(config.formal_dates)
    day_of = {d: i for i, d in enumerate(dates)}
    known = {s.code for s in problem.songs}
    submitted = set(problem.availability.members()) if submitted is None else set(submitted)
    level = problem.ladder[-1]  # 演出设置允许的缺席规则,与校验器一致

    def members_of(code: str | None) -> tuple[str, ...]:
        return tuple(problem.song(code).members) if code in known else ()

    def free(m: str, d: date, start: int, duration: int) -> bool:
        return m not in submitted or all(problem.availability.is_available(m, d, h) for h in range(start, start + duration))

    def unplanned(m: str, code: str) -> bool:
        return not rules.planned_absence(m, code)

    formal = [i for i, s in enumerate(sessions) if s.kind == KIND_FORMAL]

    # 「固定场次」要求:每条留一场原样不动(已有锁定的就用锁定的)
    pinned: set[int] = set()
    for f in rules.fixed_sessions:
        want_absent = (f.absent_member,) if f.absent_member else ()
        match = [
            i
            for i in formal
            if (sessions[i].song_code, sessions[i].date, sessions[i].start, sessions[i].duration)
            == (f.song_code, f.date, f.start, f.duration)
            and tuple(sessions[i].absent_members) == want_absent
        ]
        match.sort(key=lambda i: not sessions[i].locked)
        if match and not sessions[match[0]].locked:
            pinned.add(match[0])

    # 要排的场次(可挪 / 留原位)与不动的场次
    tasks: list[int] = []
    fixed: list[int] = []
    for i in formal:
        s = sessions[i]
        if s.song_code in known and not s.locked and i not in pinned:
            tasks.append(i)  # 不在排练日内的也算(只能挪回来或原样保留)
        else:
            fixed.append(i)
    stuck_locked = [sessions[i] for i in fixed if sessions[i].locked and not _valid_here(problem, sessions[i], free)]
    if not tasks:
        return _nothing(problem, stuck_locked, "没有可以挪动的场次")

    # 每场的放法:挪过去时按「谁没空谁缺席」;原位(本身成立时)保持现在的缺席
    options: dict[int, list[_Option]] = {}
    here_opt: dict[int, int | None] = {}
    for i in tasks:
        s = sessions[i]
        code = s.song_code or ""
        planned = tuple(m for m in s.absent_members if rules.attendance_cap(m, code) is not None)
        opts: list[_Option] = []
        here = None
        if _valid_here(problem, s, free):
            here = 0
            opts.append(_Option(day_of[s.date], s.start, tuple(s.absent_members)))
        if len(planned) <= 1:
            for di, d in enumerate(dates):
                for start in range(0, config.slots_per_day - s.duration + 1):
                    if (d, start) == (s.date, s.start) or not block_allowed(config, rules, d, start, s.duration):
                        continue
                    busy = {m for m in members_of(code) if m not in planned and not free(m, d, start, s.duration)}
                    absent = tuple(sorted(set(planned) | busy))
                    # 演出设置不允许缺席时,挪过去不能产生计划外缺席(否则只是把冲突换成「不允许缺席」)
                    if len(absent) <= 1 and not (level.strict and any(unplanned(m, code) for m in absent)):
                        opts.append(_Option(di, start, absent))
        options[i] = opts
        here_opt[i] = here

    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    keep: dict[int, cp_model.IntVar] = {}  # 原样保留(它本身的冲突先不管)
    for i in tasks:
        for k in range(len(options[i])):
            x[(i, k)] = model.new_bool_var(f"x_{i}_{k}")
        keep[i] = model.new_bool_var(f"keep_{i}")
        model.add_exactly_one([*(x[(i, k)] for k in range(len(options[i]))), keep[i]])

    def x_terms(i: int) -> list[tuple[cp_model.IntVar, _Option]]:
        return [(x[(i, k)], o) for k, o in enumerate(options[i])]

    # ---- 成员不重叠(与校验器一样,缺席成员也算占用)----
    cover: dict[tuple[str, int, int], list] = defaultdict(list)  # 放上去(含原位没问题)的
    keep_cover: dict[tuple[str, int, int], list] = defaultdict(list)  # 原样保留的
    fixed_cover: set[tuple[str, int, int]] = set()
    for i in tasks:
        s = sessions[i]
        ms = members_of(s.song_code)
        for v, o in x_terms(i):
            for m in ms:
                for h in range(o.start, o.start + s.duration):
                    cover[(m, o.day, h)].append(v)
        if s.date in day_of:
            for m in ms:
                for h in range(s.start, s.end):
                    keep_cover[(m, day_of[s.date], h)].append(keep[i])
    for i in fixed:
        s = sessions[i]
        if s.date in day_of:
            for m in members_of(s.song_code):
                for h in range(s.start, s.end):
                    fixed_cover.add((m, day_of[s.date], h))
    for cell, vs in cover.items():
        model.add(sum(vs) <= (0 if cell in fixed_cover else 1))
        for kv in keep_cover.get(cell, []):
            model.add(sum(vs) + kv <= 1)

    excess: list = []  # 超出上限的量(先尽量减到最少)

    def capped(expr, const: int, limit: int, current: int, name: str) -> None:  # noqa: ANN001
        """expr(要排的场次)+ const(不动的场次)≤ limit;现在已超出的只要求不更糟,超出量另计。"""
        model.add(expr + const <= max(limit, current))
        ex = model.new_int_var(0, 100_000, f"excess_{name}")
        model.add(ex >= expr + const - limit)
        excess.append(ex)

    def on_day(i: int, di: int) -> bool:
        return sessions[i].date == dates[di]

    # ---- 单日小时上限(按场次时长累加,与校验器一致);已超出的一天只要求不更糟 ----
    hard = config.hard_daily_limit
    for m in sorted({m for i in formal for m in members_of(sessions[i].song_code)}):
        mine = [i for i in tasks if m in members_of(sessions[i].song_code)]
        overlong = max((sessions[i].duration for i in mine if sessions[i].duration > hard), default=0)  # 本身就超长的场次
        for di in range(len(dates)):
            placed = [sessions[i].duration * v for i in mine for v, o in x_terms(i) if o.day == di]
            if not placed:
                continue
            fixed_h = sum(sessions[i].duration for i in fixed if on_day(i, di) and m in members_of(sessions[i].song_code))
            kept_h = sum(sessions[i].duration * keep[i] for i in mine if on_day(i, di))
            now_h = sum(sessions[i].duration for i in formal if on_day(i, di) and m in members_of(sessions[i].song_code))
            capped(sum(placed) + kept_h, fixed_h, hard, max(now_h, overlong), f"hours_{m}_{di}")

    # ---- 同曲不同天;已在同一天的只要求不更糟 ----
    if config.same_song_different_days:
        for code in sorted(known):
            mine = [i for i in tasks if sessions[i].song_code == code]
            for di in range(len(dates)):
                placed = [v for i in mine for v, o in x_terms(i) if o.day == di]
                if not placed:
                    continue
                kept = [keep[i] for i in mine if on_day(i, di)]
                const = sum(1 for i in fixed if sessions[i].song_code == code and on_day(i, di))
                now = sum(1 for i in formal if sessions[i].song_code == code and on_day(i, di))
                capped(sum(placed) + sum(kept), const, 1, now, f"day_{code}_{di}")

    # ---- 「固定场次」要求还没满足的:尽量挪一场过去补上(计入超出量)----
    for f in rules.fixed_sessions:
        if f.date not in day_of or f.song_code not in known:
            continue
        want = (f.absent_member,) if f.absent_member else ()
        if any(
            (sessions[i].song_code, sessions[i].date, sessions[i].start, sessions[i].duration) == (f.song_code, f.date, f.start, f.duration)
            and tuple(sessions[i].absent_members) == want
            for i in fixed
        ):
            continue
        match = [
            v
            for i in tasks
            if sessions[i].song_code == f.song_code and sessions[i].duration == f.duration
            for v, o in x_terms(i)
            if o.day == day_of[f.date] and o.start == f.start and o.absent == want
        ]
        if match:
            ex = model.new_int_var(0, 1, f"fixedrule_{len(excess)}")
            model.add(ex >= 1 - sum(match))
            excess.append(ex)

    # ---- 指定日期最多场次 ----
    for d, limit in rules.max_sessions_per_date.items():
        if d not in day_of:
            continue
        di = day_of[d]
        placed = [v for i in tasks for v, o in x_terms(i) if o.day == di]
        kept = [keep[i] for i in tasks if sessions[i].date == d]
        const = sum(1 for i in fixed if sessions[i].date == d)
        capped(sum(placed) + sum(kept), const, limit, sum(1 for i in formal if sessions[i].date == d), f"date_{di}")

    # ---- 缺席规则(按全部正规场次计,与校验器一致)----
    def count(pred) -> tuple:  # noqa: ANN001
        """要排的场次里满足 pred(缺席成员, 曲目) 的放法之和、不动的场次里满足的个数、现在的个数。"""
        terms = []
        for i in tasks:
            code = sessions[i].song_code or ""
            terms += [v for v, o in x_terms(i) if pred(o.absent, code)]
            if pred(tuple(sessions[i].absent_members), code):
                terms.append(keep[i])
        const = sum(1 for i in fixed if pred(tuple(sessions[i].absent_members), sessions[i].song_code or ""))
        now = sum(1 for i in formal if pred(tuple(sessions[i].absent_members), sessions[i].song_code or ""))
        return sum(terms), const, now

    e, c, now = count(lambda ab, cd: any(unplanned(m, cd) for m in ab))
    capped(e, c, level.max_absent_sessions(len(formal)), now, "cap")
    for code in sorted(known):
        n = sum(1 for i in formal if sessions[i].song_code == code)
        if not n:
            continue
        min_full = n if level.per_song_min_full is None else min(level.per_song_min_full, n)
        e, c, now = count(lambda ab, cd, code=code: cd == code and any(unplanned(m, cd) for m in ab))
        capped(e, c, n - min_full, now, f"song_{code}")
        for m in members_of(code):
            e, c, now = count(lambda ab, cd, code=code, m=m: cd == code and m in ab and unplanned(m, cd))
            capped(e, c, level.per_member_per_song_max_absent, now, f"member_{code}_{m}")
    for (m, code), n in rules.member_song_max_absent.items():
        e, c, now = count(lambda ab, cd, code=code, m=m: cd == code and m in ab)
        capped(e, c, n, now, f"allow_{m}_{code}")
    for (m, code), cap in rules.member_song_max_attendance.items():
        e, c, now = count(lambda ab, cd, code=code, m=m: cd == code and m not in ab)
        capped(e, c, cap, now, f"attend_{m}_{code}")

    # ---- 目标 ----
    kept_sum = sum(keep.values())
    moved_sum = sum(x[(i, k)] for i in tasks for k in range(len(options[i])) if k != here_opt[i])
    dist_terms = []
    for i in tasks:
        s = sessions[i]
        code = s.song_code or ""
        for k, o in enumerate(options[i]):
            if k == here_opt[i]:
                continue
            day_gap = abs((dates[o.day] - s.date).days)
            cost = (100 + 10 * day_gap if day_gap else 0) + abs(o.start - s.start)
            if any(unplanned(m, code) for m in o.absent):
                cost += _NEW_ABSENCE_COST
            dist_terms.append(cost * x[(i, k)])
        # 起始提示:原位没问题就留原位,否则原样保留(总是可行)
        model.add_hint(x[(i, here_opt[i])] if here_opt[i] is not None else keep[i], 1)

    optimal = True
    solver: cp_model.CpSolver | None = None
    deadline = time.monotonic() + float(time_limit)  # 四步共用一个时间上限,按比例分给每一步(保证「挪动最少」一定会跑到)
    for objective, share in ((kept_sum, 0.35), (sum(excess), 0.2), (moved_sum, 0.3), (sum(dist_terms), 1.0)):
        left_time = deadline - time.monotonic()
        if solver is not None and left_time < 0.3:
            optimal = False  # 时间用完:用已有的结果
            break
        model.minimize(objective)
        attempt = cp_model.CpSolver()
        attempt.parameters.max_time_in_seconds = max(min(left_time, share * float(time_limit)), 0.5)
        attempt.parameters.num_workers = int(workers)
        attempt.parameters.random_seed = int(seed)
        status = attempt.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if solver is None:  # 全部原样保留总是可行;第一步就没结果只可能是时间不够
                return ReoptResult("infeasible", "在时间限制内没找到办法,可以再试一次或先手动调整几场")
            optimal = False
            break
        solver = attempt
        optimal = optimal and status == cp_model.OPTIMAL
        model.add(objective <= int(round(solver.objective_value)))
        model.clear_hints()
        for v in [*x.values(), *keep.values()]:
            model.add_hint(v, solver.value(v))

    assert solver is not None
    moves = [
        Move(i, dates[o.day], o.start) for i in tasks for k, o in enumerate(options[i]) if k != here_opt[i] and solver.value(x[(i, k)])
    ]
    left = sum(1 for i in tasks if solver.value(keep[i]))
    if not moves:
        if left:
            msg = f"有 {left} 场的冲突靠挪动解决不了;可以解锁部分场次、调整缺席,或用 AI 调度员找其他办法"
            return _nothing(problem, stuck_locked, msg, optimal=optimal, status="infeasible")
        return _nothing(problem, stuck_locked, "现在的排练表已经没有可以靠挪动解决的冲突", optimal=optimal)
    msg = f"建议挪动 {len(moves)} 场" + (f";另有 {left} 场怎么挪都解决不了,原样保留" if left else "")
    return ReoptResult("ok", msg, moves=moves, optimal=optimal)


def _valid_here(problem: Problem, s: Session, free) -> bool:  # noqa: ANN001
    """这一场留在原位、按现在的缺席,本身成立吗:正规排练日、时段允许、最多缺 1 人、到场成员都有空。"""
    config = problem.config
    code = s.song_code or ""
    if code not in {x.code for x in problem.songs} or s.date not in config.formal_dates:
        return False
    if len(s.absent_members) > 1:  # 比单日上限还长不算:那是它自己的时长问题,挪到哪都一样(单日上限另有容忍)
        return False
    if not block_allowed(config, problem.rules, s.date, s.start, s.duration):
        return False
    return all(free(m, s.date, s.start, s.duration) for m in problem.song(code).members if m not in s.absent_members)


def _nothing(
    problem: Problem, stuck_locked: list[Session], message: str, *, optimal: bool = False, status: str = "unchanged"
) -> ReoptResult:
    """没有可挪的:锁定的场次本身有冲突时说清楚是哪几场。"""
    if stuck_locked:
        names = "、".join(f"{problem.song(s.song_code).name} {s.date.month}/{s.date.day}" for s in stuck_locked[:3] if s.song_code)
        return ReoptResult("locked_conflict", f"锁定的 {names} 本身有冲突(有成员没空或落在禁排时段),挪动其他场次解决不了;请先解锁或调整它")
    return ReoptResult(status, message, optimal=optimal)
