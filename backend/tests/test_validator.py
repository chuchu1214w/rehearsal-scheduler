import copy
from datetime import date

import pytest

from solver.lexicographic import solve
from solver.types import KIND_EVALUATION, KIND_FORMAL, FixedSession, LadderLevel, Rules, Session
from solver.validator import compute_metrics, validate_schedule
from tests.conftest import make_problem, set_slots


@pytest.fixture(scope="module")
def solved():
    problem = make_problem()
    result = solve(problem)
    assert result.feasible and not result.validation_errors
    return problem, result


def _errors(problem, sessions, level=None, **kw):
    return validate_schedule(problem, sessions, level, **kw).errors


def _formal(sessions):
    return [s for s in sessions if s.kind == KIND_FORMAL]


def test_valid_schedule_passes(solved):
    problem, result = solved
    assert _errors(problem, result.sessions) == []


def test_metrics_match_solver_objectives(solved):
    problem, result = solved
    metrics = compute_metrics(problem, result.sessions)
    for key, value in result.objective_values.items():
        if key in metrics:
            assert metrics[key] == value, key


def test_formal_on_eval_day_rejected(solved):
    problem, result = solved
    sessions = copy.deepcopy(result.sessions)
    _formal(sessions)[0].date = problem.config.eval_date
    assert any("V-07" in e for e in _errors(problem, sessions))


def test_absence_rejected_at_strict_level(solved):
    problem, result = solved
    sessions = copy.deepcopy(result.sessions)
    s = _formal(sessions)[0]
    s.absent_members = (problem.song(s.song_code).members[0],)
    assert any("V-08" in e for e in _errors(problem, sessions))
    # 放宽层级允许 1 场缺席
    assert not any("V-08" in e for e in _errors(problem, sessions, LadderLevel(1, 0.2, 1, 1)))


def test_overlap_and_daily_limit(solved):
    problem, result = solved
    sessions = copy.deepcopy(result.sessions)
    first = [s for s in _formal(sessions) if s.song_code == "s1"]
    first[1].date, first[1].start = first[0].date, first[0].start
    errs = _errors(problem, sessions)
    assert any("V-04" in e for e in errs) and any("V-06" in e for e in errs)


def test_wrong_duration_rejected(solved):
    problem, result = solved
    sessions = copy.deepcopy(result.sessions)
    _formal(sessions)[0].duration = 3
    assert any("V-03" in e for e in _errors(problem, sessions))


def test_unavailable_member_rejected(solved):
    problem, result = solved
    problem = copy.deepcopy(problem)
    s = _formal(result.sessions)[0]
    set_slots(problem.availability, problem.song(s.song_code).members[0], s.date, [s.start])
    assert any("V-02" in e for e in _errors(problem, result.sessions))


def test_evaluation_rules(solved):
    problem, result = solved
    without_eval = [s for s in result.sessions if s.kind != KIND_EVALUATION]
    assert any("恰好 1 场" in e for e in _errors(problem, without_eval))
    sessions = copy.deepcopy(result.sessions)
    ev = next(s for s in sessions if s.kind == KIND_EVALUATION)
    ev.attendance["A"] = (ev.start, ev.start + 1)  # 只到 1 小时
    assert any("V-07" in e and "A" in e for e in _errors(problem, sessions))
    ev.attendance = {m: (ev.start, ev.end) for m in problem.members if m != "D"}
    assert any("缺少成员 D" in e for e in _errors(problem, sessions))


def test_locked_reference(solved):
    problem, result = solved
    ref = copy.deepcopy(result.sessions)
    locked = _formal(ref)[0]
    locked.locked = True
    moved = copy.deepcopy(result.sessions)
    target = next(s for s in moved if s.song_code == locked.song_code and s.start == locked.start and s.date == locked.date)
    target.date = date(2026, 9, 8) if target.date != date(2026, 9, 8) else date(2026, 9, 7)
    assert any("V-10" in e for e in _errors(problem, moved, locked_reference=ref))
    assert not any("V-10" in e for e in _errors(problem, result.sessions, locked_reference=ref))


def test_fixed_session_rule_checked(solved):
    problem, result = solved
    problem = copy.deepcopy(problem)
    problem.rules = Rules(fixed_sessions=(FixedSession("s1", date(2026, 9, 4), 0, 2),))
    has = any(s.song_code == "s1" and s.date == date(2026, 9, 4) and s.start == 0 for s in result.sessions)
    errs = _errors(problem, result.sessions)
    assert has or any("V-09" in e for e in errs)


def test_session_helpers():
    s = Session(KIND_FORMAL, date(2026, 9, 4), 3, 2, "s1")
    assert s.end == 5 and list(s.hours) == [3, 4]
