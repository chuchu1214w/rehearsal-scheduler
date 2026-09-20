"""测试公共夹具:一个可以随意改空闲数据的小型活动。"""

from __future__ import annotations

from datetime import date

import pytest

from solver.types import AVAILABLE, UNAVAILABLE, Availability, EventConfig, LadderLevel, Problem, Rules, Song

# 正规排练日 09-04 ~ 09-08(5 天),评估日 09-09,演出 09-10
PERF = date(2026, 9, 10)
START = date(2026, 9, 4)
MEMBERS = ("A", "B", "C", "D")
SONGS = (
    Song("s1", "第一首", "简单", ("A", "B"), (2, 2)),
    Song("s2", "第二首", "一般", ("B", "C"), (3,)),
    Song("s3", "第三首", "简单", ("C", "D"), (2, 2)),
)
LADDER = (LadderLevel(0), LadderLevel(1, 0.20, 1, 1), LadderLevel(2, 0.25, 1, 1))


def make_config(**overrides) -> EventConfig:
    kwargs = dict(performance_date=PERF, formal_start_date=START, stage_time_limit=10.0, workers=4)
    kwargs.update(overrides)
    return EventConfig(**kwargs)


def full_availability(config: EventConfig, members=MEMBERS, value: int = AVAILABLE) -> Availability:
    avail = Availability()
    for m in members:
        for d in config.all_dates:
            avail.set_row(m, d, [value] * config.slots_per_day)
    return avail


def make_problem(
    *,
    config: EventConfig | None = None,
    members=MEMBERS,
    songs=SONGS,
    availability: Availability | None = None,
    rules: Rules | None = None,
    ladder=LADDER,
    objectives=None,
) -> Problem:
    config = config or make_config()
    kwargs = dict(
        config=config,
        members=tuple(members),
        songs=tuple(songs),
        availability=availability or full_availability(config, members),
        rules=rules or Rules(),
        ladder=ladder,
    )
    if objectives is not None:
        kwargs["objectives"] = tuple(objectives)
    return Problem(**kwargs)


def set_slots(avail: Availability, member: str, d: date, slots, value: int = UNAVAILABLE) -> None:
    for h in slots:
        avail.grid[member][d][h] = value


@pytest.fixture
def config() -> EventConfig:
    return make_config()


@pytest.fixture
def problem() -> Problem:
    return make_problem()
