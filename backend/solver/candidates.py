"""排练任务生成与候选枚举(开发文档 §5.2、§5.3)。"""

from __future__ import annotations

from collections.abc import Iterable

from .timegrid import block_allowed, members_available
from .types import Candidate, Problem, Task


def make_tasks(problem: Problem, song_codes: Iterable[str] | None = None) -> list[Task]:
    codes = list(song_codes) if song_codes is not None else [s.code for s in problem.songs]
    tasks: list[Task] = []
    for code in codes:
        song = problem.song(code)
        for i, duration in enumerate(song.durations(problem.config), start=1):
            tasks.append(Task(f"{code}_{i}", code, i, duration))
    return tasks


def build_candidates(
    problem: Problem,
    tasks: Iterable[Task],
    *,
    allow_absent: bool,
) -> dict[str, list[Candidate]]:
    """为每个任务枚举候选 (日期, 开始格, 缺席成员)。

    - 全员到齐的候选总是生成;
    - ``allow_absent=True``(降级层级 ≥ 1)时,额外生成“恰好缺席 1 人”的候选;
    - 有“出勤上限”规则的成员,其缺席候选在任何层级都生成,并标记 ``excused``;
    - 有“允许缺席 N 次”规则的成员,在其不可用的时段也在任何层级生成缺席候选(不标记 excused,
      由 model.py 按 (成员, 曲目) 的次数上限约束)。
    """
    config = problem.config
    rules = problem.rules
    dates = config.formal_dates
    result: dict[str, list[Candidate]] = {}
    for task in tasks:
        song = problem.song(task.song_code)
        members = song.members
        excusable = {m for m in members if rules.attendance_cap(m, song.code) is not None}
        allowed = {m for m in members if rules.absence_allowance(m, song.code) is not None}
        choices: list[Candidate] = []
        for di, d in enumerate(dates):
            for start in range(0, config.slots_per_day - task.duration + 1):
                if not block_allowed(config, rules, d, start, task.duration):
                    continue
                if members_available(problem, members, d, start, task.duration):
                    choices.append(Candidate(di, start, task.duration))
                    # 有出勤上限的成员,即使全员可用也可以选择不出勤
                    for m in excusable:
                        choices.append(Candidate(di, start, task.duration, m, excused=True))
                    continue
                for m in members:
                    if not (allow_absent or m in excusable or m in allowed):
                        continue
                    others = [x for x in members if x != m]
                    if others and members_available(problem, others, d, start, task.duration):
                        choices.append(Candidate(di, start, task.duration, m, excused=m in excusable))
        result[task.task_id] = choices
    return result


def candidate_summary(problem: Problem, tasks: Iterable[Task], candidates: dict[str, list[Candidate]]) -> list[dict]:
    rows = []
    for task in tasks:
        cands = candidates[task.task_id]
        full = [c for c in cands if c.full]
        rows.append(
            {
                "任务": task.task_id,
                "曲目": problem.song(task.song_code).name,
                "时长": task.duration,
                "候选数": len(cands),
                "全员候选": len(full),
                "缺席候选": len(cands) - len(full),
                "覆盖日期数": len({c.date_idx for c in cands}),
            }
        )
    return rows
