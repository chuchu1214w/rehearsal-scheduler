"""附录 A 示例活动 + 合成空闲数据的端到端回归。"""

import json
from collections import Counter
from importlib import resources

import pytest

from solver.lexicographic import SolveOptions, solve
from solver.serialization import problem_from_dict
from solver.synth import synthesize_availability
from solver.types import KIND_EVALUATION, KIND_FORMAL
from solver.validator import compute_metrics, validate_schedule


@pytest.fixture(scope="module")
def sample_problem():
    data = json.loads(resources.files("solver").joinpath("fixtures/sample_event.json").read_text(encoding="utf-8"))
    problem = problem_from_dict(data)
    problem.availability = synthesize_availability(problem.config, problem.members, seed=42, density=0.7)
    return problem


def test_sample_solves_strictly(sample_problem):
    result = solve(sample_problem, SolveOptions(time_limit=30))
    assert result.feasible and result.level_used == 0 and result.exact
    assert result.validation_errors == []
    formal = [s for s in result.sessions if s.kind == KIND_FORMAL]
    assert len(formal) == 25 and sum(1 for s in result.sessions if s.kind == KIND_EVALUATION) == 1
    counts = Counter(s.song_code for s in formal)
    assert counts["a"] == 1 and counts["j"] == 3 and counts["c"] == 2
    # 菁在 e 只出勤 1 场(出勤上限规则)
    e_sessions = [s for s in formal if s.song_code == "e"]
    assert sum(1 for s in e_sessions if "菁" not in s.absent_members) == 1
    assert validate_schedule(sample_problem, result.sessions, sample_problem.ladder[0]).ok
    metrics = compute_metrics(sample_problem, result.sessions)
    for key, value in result.objective_values.items():
        if key in metrics:
            assert metrics[key] == value, key


def test_sample_infeasible_path_gives_diagnosis(sample_problem):
    problem = sample_problem
    sparse = synthesize_availability(problem.config, problem.members, seed=42, density=0.55)
    problem = type(problem)(
        config=problem.config,
        members=problem.members,
        songs=problem.songs,
        availability=sparse,
        rules=problem.rules,
        ladder=problem.ladder,
        objectives=problem.objectives,
    )
    result = solve(problem, SolveOptions(time_limit=20))
    assert not result.feasible and result.diagnosis is not None
    assert result.diagnosis["最大覆盖"]["最多可排场次"] < 25
    assert result.diagnosis["最小调整建议"]["可行"]
