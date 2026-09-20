from collections import Counter
from datetime import date

import pytest

from solver.lexicographic import SolveOptions, solve
from solver.types import KIND_EVALUATION, KIND_FORMAL, UNAVAILABLE, FixedSession, LadderLevel, Rules, Song
from tests.conftest import SONGS, START, make_config, make_problem, set_slots


def _formal(result):
    return [s for s in result.sessions if s.kind == KIND_FORMAL]


def test_small_instance_end_to_end(problem):
    messages = []
    result = solve(problem, SolveOptions(progress=messages.append))
    assert result.feasible and result.level_used == 0 and result.exact
    assert result.validation_errors == []
    assert messages  # 进度回调被调用
    counts = Counter(s.song_code for s in _formal(result))
    assert counts == {"s1": 2, "s2": 1, "s3": 2}
    evals = [s for s in result.sessions if s.kind == KIND_EVALUATION]
    assert len(evals) == 1 and evals[0].date == problem.config.eval_date
    assert all(s.date != problem.config.eval_date for s in _formal(result))
    assert [r.key for r in result.stages][:2] == ["feasible", "absent"]
    assert result.objective_values["absent"] == 0


def test_ladder_relaxes_to_allow_one_absence():
    # s2 改为 3h+2h 两场;C 每天只有 2 小时可用:3 小时场在严格层没有候选,
    # 放宽后允许 C 缺席那一场(另一场 2h 全员到齐,满足“每曲至少 1 场全员”)
    songs = (SONGS[0], Song("s2", "第二首", "一般", ("B", "C"), (3, 2)), SONGS[2])
    problem = make_problem(songs=songs)
    for d in problem.config.formal_dates:
        problem.availability.set_row("C", d, [UNAVAILABLE] * 13)
        set_slots(problem.availability, "C", d, [5, 6], 1)
    result = solve(problem)
    assert result.feasible and result.level_used == 1
    assert [a["状态"] for a in result.attempts] == ["无候选", "可行"]
    s2 = sorted((s for s in _formal(result) if s.song_code == "s2"), key=lambda s: -s.duration)
    assert s2[0].duration == 3 and s2[0].absent_members == ("C",)
    assert s2[1].duration == 2 and s2[1].absent_members == ()
    assert result.objective_values["absent"] == 1
    assert result.validation_errors == []


def test_single_session_song_cannot_have_absence(problem):
    # HC-09:每曲至少 1 场全员到齐 —— 只有 1 场的曲目在任何层级都不能缺席
    for d in problem.config.formal_dates:
        problem.availability.set_row("C", d, [UNAVAILABLE] * 13)
        set_slots(problem.availability, "C", d, [5, 6], 1)
    result = solve(problem, SolveOptions(diagnose_on_failure=False))
    assert not result.feasible
    assert [a["状态"] for a in result.attempts] == ["无候选", "INFEASIBLE", "INFEASIBLE"]


def test_ladder_exhausted_returns_diagnosis(problem):
    # B 完全没空:s1 两场、s2 一场都需要缺席 B,超过任何层级的上限(5 场的 25% = 1 场)
    for d in problem.config.formal_dates:
        problem.availability.set_row("B", d, [UNAVAILABLE] * 13)
    result = solve(problem)
    assert not result.feasible and result.level_used is None
    assert result.diagnosis is not None
    assert set(result.diagnosis["无候选任务"]) == {"s1_1", "s1_2", "s2_1"}
    adj = result.diagnosis["最小调整建议"]
    assert adj["可行"] and adj["受影响成员数"] == 1 and adj["调整小时数"] == 7
    assert {c["成员"] for c in adj["调整"]} == {"B"}


def test_fixed_session_is_honored(problem):
    problem.rules = Rules(fixed_sessions=(FixedSession("s1", date(2026, 9, 6), 4, 2),))
    result = solve(problem)
    assert result.feasible and result.validation_errors == []
    assert any(s.song_code == "s1" and s.date == date(2026, 9, 6) and s.start == 4 for s in _formal(result))


def test_fixed_session_impossible_is_reported(problem):
    set_slots(problem.availability, "A", date(2026, 9, 6), [4])
    problem.rules = Rules(fixed_sessions=(FixedSession("s1", date(2026, 9, 6), 4, 2),))
    result = solve(problem, SolveOptions(diagnose_on_failure=False))
    assert not result.feasible
    assert all(a["状态"] == "固定场次不可行" for a in result.attempts)


def test_attendance_cap_creates_excused_absence(problem):
    problem.rules = Rules(member_song_max_attendance={("A", "s1"): 1})
    result = solve(problem)
    assert result.feasible and result.level_used == 0 and result.validation_errors == []
    s1 = [s for s in _formal(result) if s.song_code == "s1"]
    assert sorted(s.absent_members for s in s1) == [(), ("A",)]
    assert result.objective_values["absent"] == 1


def test_blocked_day_and_max_sessions(problem):
    problem.rules = Rules(
        blocked_slots={date(2026, 9, 5): frozenset(range(13))},
        max_sessions_per_date={date(2026, 9, 4): 1},
    )
    result = solve(problem)
    assert result.feasible and result.validation_errors == []
    assert all(s.date != date(2026, 9, 5) for s in _formal(result))
    assert sum(1 for s in _formal(result) if s.date == date(2026, 9, 4)) <= 1


def test_same_song_same_day_allowed_when_disabled():
    cfg = make_config(same_song_different_days=False)
    problem = make_problem(config=cfg)
    # 只开放一天,s1 的两场必须同一天
    for m in problem.members:
        for d in problem.config.formal_dates[1:]:
            problem.availability.set_row(m, d, [UNAVAILABLE] * 13)
    result = solve(problem)
    assert result.feasible and result.validation_errors == []
    assert len({s.date for s in _formal(result)}) == 1
    assert result.objective_values["spacing"] >= 100


def test_custom_objective_order_and_hard_early():
    songs = (Song("h", "难曲", "困难", ("A", "B")), Song("s3", "第三首", "简单", ("C", "D"), (2, 2)))
    problem = make_problem(songs=songs, objectives=("hard_early", "trips"))
    result = solve(problem)
    assert result.feasible
    assert [r.key for r in result.stages] == ["feasible", "hard_early", "trips"]
    hard_days = sorted(problem.config.formal_dates.index(s.date) for s in _formal(result) if s.song_code == "h")
    assert hard_days == [0, 1, 2]  # 尽早且同曲不同天


def test_evaluation_infeasible_but_formal_feasible(problem):
    d = problem.config.eval_date
    for m in problem.members:
        problem.availability.set_row(m, d, [UNAVAILABLE] * 13)
    result = solve(problem)
    assert not result.feasible and result.level_used == 0
    assert _formal(result) and not any(s.kind == KIND_EVALUATION for s in result.sessions)
    assert "评估场" in result.diagnosis and result.diagnosis["评估场"]["可行窗口数"] == 0
    assert any("V-07" in e for e in result.validation_errors)


def test_invalid_problem_raises(problem):
    problem.songs = (Song("bad", "坏", "简单", ("A", "Z")),)
    with pytest.raises(ValueError):
        solve(problem)


def test_overtime_objective_active_when_soft_below_hard():
    cfg = make_config(soft_daily_limit=2, hard_daily_limit=8)
    problem = make_problem(config=cfg, objectives=("overtime",))
    result = solve(problem)
    assert result.feasible
    assert result.stages[-1].key == "overtime" and result.stages[-1].status != "无适用项"


def test_ladder_level_with_zero_cap_is_skipped(problem):
    problem.ladder = (LadderLevel(0), LadderLevel(1, 0.01, 1, 1))
    for d in problem.config.formal_dates:
        problem.availability.set_row("B", d, [UNAVAILABLE] * 13)
    result = solve(problem, SolveOptions(diagnose_on_failure=False))
    assert [a["状态"] for a in result.attempts] == ["无候选", "跳过"]


def test_start_date_boundary():
    cfg = make_config(formal_start_date=START)
    assert cfg.formal_dates[0] == START
