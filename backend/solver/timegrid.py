"""时间网格:每日排练窗口、禁排规则与有效可用度(开发文档 §5.1)。"""

from __future__ import annotations

from datetime import date

from .types import EventConfig, Problem, Rules

WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def weekday_zh(d: date) -> str:
    return WEEKDAY_ZH[d.weekday()]


def global_allowed(config: EventConfig, rules: Rules, d: date) -> list[int]:
    """窗口内每一格是否允许排练(1/0)。窗口本身每天相同,只有禁排规则会关闭某些格。"""
    row = [1] * config.slots_per_day
    for h in rules.blocked_slots.get(d, ()):
        if 0 <= h < config.slots_per_day:
            row[h] = 0
    return row


def block_allowed(config: EventConfig, rules: Rules, d: date, start: int, duration: int) -> bool:
    if start < 0 or start + duration > config.slots_per_day:
        return False
    row = global_allowed(config, rules, d)
    return all(row[h] for h in range(start, start + duration))


def effective_available(problem: Problem, member: str, d: date, h: int) -> bool:
    """有效可用度 = 个人可用 ∧ 窗口允许。"""
    if not 0 <= h < problem.config.slots_per_day:
        return False
    if not global_allowed(problem.config, problem.rules, d)[h]:
        return False
    return problem.availability.is_available(member, d, h)


def members_available(problem: Problem, members, d: date, start: int, duration: int) -> bool:
    if not block_allowed(problem.config, problem.rules, d, start, duration):
        return False
    return all(problem.availability.is_available(m, d, h) for m in members for h in range(start, start + duration))


def unavailable_hours(problem: Problem, member: str, d: date, start: int, duration: int) -> list[int]:
    """成员在该时段内不可用的格(只看个人矩阵,不看窗口)。"""
    return [h for h in range(start, start + duration) if not problem.availability.is_available(member, d, h)]


def avoid_hits(problem: Problem, members, d: date, start: int, duration: int) -> int:
    return sum(1 for m in members for h in range(start, start + duration) if problem.availability.is_avoid(m, d, h))
