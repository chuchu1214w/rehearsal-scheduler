"""随机小实例:求解器输出必须被校验器接受,指标必须与目标值一致;无解时诊断必须给出报告。"""

import random
from datetime import date

import pytest

from solver.lexicographic import SolveOptions, solve
from solver.synth import synthesize_availability
from solver.types import DEFAULT_LADDER, EventConfig, Problem, Rules, Song
from solver.validator import compute_metrics, validate_schedule


def random_problem(seed: int) -> Problem:
    rng = random.Random(seed)
    members = tuple("ABCDEF"[: rng.randint(4, 6)])
    config = EventConfig(
        performance_date=date(2026, 9, 10),
        formal_start_date=date(2026, 9, 10 - rng.randint(3, 5)),
        stage_time_limit=5.0,
        workers=4,
    )
    songs = []
    for i in range(rng.randint(2, 4)):
        size = rng.randint(2, min(3, len(members)))
        plan = rng.choice([(2,), (2, 2), (3,), (3, 2)])
        songs.append(Song(f"s{i}", f"歌{i}", "简单", tuple(rng.sample(members, size)), plan))
    availability = synthesize_availability(config, members, seed=seed, density=rng.uniform(0.5, 0.9))
    rules = Rules(focus_members=(members[0],)) if rng.random() < 0.5 else Rules()
    return Problem(config, members, tuple(songs), availability, rules, DEFAULT_LADDER)


@pytest.mark.parametrize("seed", range(12))
def test_random_instance_consistency(seed):
    problem = random_problem(seed)
    result = solve(problem, SolveOptions(diagnose_on_failure=True))
    if result.feasible:
        report = validate_schedule(problem, result.sessions, next(lv for lv in problem.ladder if lv.level == result.level_used))
        assert report.errors == []
        metrics = compute_metrics(problem, result.sessions)
        for key, value in result.objective_values.items():
            if key in metrics:
                assert metrics[key] == value, (seed, key)
    else:
        assert result.diagnosis is not None
        assert "最小调整建议" in result.diagnosis or "评估场" in result.diagnosis
