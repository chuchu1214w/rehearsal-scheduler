"""全员评估场(开发文档 HC-06、A-16、OB-02b、§5.8 评估场诊断)。

评估场固定在公演前一天,与正规排练互不影响(那天没有正规排练),
因此可以独立于 CP-SAT 模型,用穷举精确求解。
"""

from __future__ import annotations

from dataclasses import dataclass

from .timegrid import block_allowed, global_allowed, unavailable_hours
from .types import KIND_EVALUATION, Problem, Session


@dataclass(frozen=True)
class EvalChoice:
    start: int
    duration: int
    attendance: dict[str, tuple[int, int]]  # 成员 → (绝对开始格, 绝对结束格)
    missing_hours: int  # Σ(时长 − 实际到场小时)
    avoid_hits: int

    def to_session(self, problem: Problem) -> Session:
        return Session(
            kind=KIND_EVALUATION,
            date=problem.config.eval_date,
            start=self.start,
            duration=self.duration,
            attendance=dict(self.attendance),
        )


def attendance_options(duration: int, min_contiguous: int) -> list[tuple[int, int]]:
    """到场区间(相对格)的候选,按“全程优先、区间越长越好、越早越好”排序。

    3 小时、最少连续 2 小时时返回 [(0,3), (0,2), (1,3)];2 小时时只返回 [(0,2)]。
    """
    options: list[tuple[int, int]] = []
    for length in range(duration, min(min_contiguous, duration) - 1, -1):
        for s in range(0, duration - length + 1):
            options.append((s, s + length))
    return options


def member_attendance(problem: Problem, member: str, start: int, duration: int) -> tuple[int, int] | None:
    """返回该成员能做到的最佳到场区间(绝对格);做不到则返回 None。"""
    d = problem.config.eval_date
    for rel_s, rel_e in attendance_options(duration, problem.config.eval_min_contiguous):
        abs_s, abs_e = start + rel_s, start + rel_e
        if not unavailable_hours(problem, member, d, abs_s, abs_e - abs_s):
            return abs_s, abs_e
    return None


def enumerate_choices(problem: Problem, duration: int) -> list[EvalChoice]:
    config = problem.config
    d = config.eval_date
    choices: list[EvalChoice] = []
    for start in range(0, config.slots_per_day - duration + 1):
        if not block_allowed(config, problem.rules, d, start, duration):
            continue
        attendance: dict[str, tuple[int, int]] = {}
        missing = 0
        avoid = 0
        ok = True
        for m in problem.members:
            interval = member_attendance(problem, m, start, duration)
            if interval is None:
                ok = False
                break
            attendance[m] = interval
            missing += duration - (interval[1] - interval[0])
            avoid += sum(1 for h in range(*interval) if problem.availability.is_avoid(m, d, h))
        if ok:
            choices.append(EvalChoice(start, duration, attendance, missing, avoid))
    return choices


def choose_evaluation(problem: Problem) -> EvalChoice | None:
    """在所有允许时长中选**总到场人时最多**的窗口;人时相同时取迟到早退最少、软偏好命中最少、最早者。

    这样 3 小时场只有在至少一人能全程时才胜过 2 小时全员场,
    避免选出“所有人都迟到 1 小时”的假 3 小时场。
    """
    n = len(problem.members)
    choices = [c for duration in problem.config.eval_durations for c in enumerate_choices(problem, duration)]
    if not choices:
        return None
    return min(choices, key=lambda c: (-(n * c.duration - c.missing_hours), c.missing_hours, c.avoid_hits, c.start))


def diagnose_evaluation(problem: Problem, limit: int = 10) -> dict:
    """评估日诊断:每格可到人数,以及“只差 k 人”的窗口与最少调整。"""
    config = problem.config
    d = config.eval_date
    allowed = global_allowed(config, problem.rules, d)
    per_slot = [
        sum(1 for m in problem.members if allowed[h] and problem.availability.is_available(m, d, h)) for h in range(config.slots_per_day)
    ]
    windows: list[dict] = []
    for duration in config.eval_durations:
        for start in range(0, config.slots_per_day - duration + 1):
            if not block_allowed(config, problem.rules, d, start, duration):
                continue
            blockers: dict[str, int] = {}
            for m in problem.members:
                if member_attendance(problem, m, start, duration) is not None:
                    continue
                # 让这名成员达标所需开放的最少小时数:在各到场区间选项中取最小
                need = min(
                    len(unavailable_hours(problem, m, d, start + s, e - s))
                    for s, e in attendance_options(duration, config.eval_min_contiguous)
                )
                blockers[m] = need
            windows.append(
                {
                    "时长": duration,
                    "时间段": config.range_label(start, duration),
                    "开始格": start,
                    "缺少人数": len(blockers),
                    "需开放小时数": sum(blockers.values()),
                    "阻塞成员": dict(sorted(blockers.items(), key=lambda kv: problem.member_index(kv[0]))),
                }
            )
    windows.sort(key=lambda w: (w["缺少人数"], w["需开放小时数"], -w["时长"], w["开始格"]))
    return {
        "评估日": d.isoformat(),
        "每格可到人数": {config.slot_label(h): n for h, n in enumerate(per_slot)},
        "成员总数": len(problem.members),
        "可行窗口数": sum(1 for w in windows if w["缺少人数"] == 0),
        "最接近的窗口": windows[:limit],
    }
