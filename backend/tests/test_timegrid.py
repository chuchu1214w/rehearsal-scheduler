from datetime import date

import pytest

from solver.timegrid import block_allowed, effective_available, global_allowed
from solver.types import EventConfig, Rules
from tests.conftest import PERF, START, make_config, make_problem, set_slots


def test_window_defaults(config):
    assert config.slots_per_day == 13
    assert config.slot_label(0) == "10:00–11:00"
    assert config.slot_label(12) == "22:00–23:00"
    assert config.range_label(11, 2) == "21:00–23:00"


def test_dates(config):
    assert config.formal_dates == [date(2026, 9, 4 + i) for i in range(5)]
    assert config.eval_date == date(2026, 9, 9)
    assert config.all_dates[-1] == config.eval_date


@pytest.mark.parametrize(
    "overrides",
    [
        {"day_start_hour": 23, "day_end_hour": 10},
        {"soft_daily_limit": 9, "hard_daily_limit": 8},
        {"formal_start_date": PERF},  # 区间为空
        {"eval_durations": (14,)},
        {"difficulty_templates": {"简单": ()}},
    ],
)
def test_config_rejects_invalid(overrides):
    with pytest.raises(ValueError):
        make_config(**overrides)


def test_custom_window():
    cfg = EventConfig(performance_date=PERF, formal_start_date=START, day_start_hour=9, day_end_hour=22)
    assert cfg.slots_per_day == 13
    assert cfg.slot_label(0) == "09:00–10:00"


def test_blocked_slots_close_window(config):
    rules = Rules(blocked_slots={START: frozenset({12})})
    row = global_allowed(config, rules, START)
    assert row[12] == 0 and sum(row) == 12
    assert block_allowed(config, rules, START, 11, 2) is False
    assert block_allowed(config, rules, START, 10, 2) is True
    assert block_allowed(config, Rules(), START, 12, 2) is False  # 超出窗口


def test_effective_available_combines_personal_and_window():
    problem = make_problem(rules=Rules(blocked_slots={START: frozenset({3})}))
    set_slots(problem.availability, "A", START, [4])
    assert effective_available(problem, "A", START, 3) is False  # 窗口关闭
    assert effective_available(problem, "A", START, 4) is False  # 个人不可
    assert effective_available(problem, "A", START, 5) is True
    assert effective_available(problem, "A", START, 13) is False  # 越界
