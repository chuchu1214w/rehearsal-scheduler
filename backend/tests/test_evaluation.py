from solver.evaluation import attendance_options, choose_evaluation, diagnose_evaluation, member_attendance
from solver.types import UNAVAILABLE
from tests.conftest import set_slots


def test_attendance_options():
    assert attendance_options(3, 2) == [(0, 3), (0, 2), (1, 3)]
    assert attendance_options(2, 2) == [(0, 2)]
    assert attendance_options(3, 3) == [(0, 3)]


def test_prefers_full_attendance_and_three_hours(problem):
    choice = choose_evaluation(problem)
    assert choice is not None
    assert choice.duration == 3 and choice.missing_hours == 0 and choice.start == 0
    assert all(b - a == 3 for a, b in choice.attendance.values())


def test_late_arrival_counts_as_missing_hour(problem):
    eval_date = problem.config.eval_date
    assert member_attendance(problem, "A", 0, 3) == (0, 3)
    set_slots(problem.availability, "A", eval_date, [0])
    assert member_attendance(problem, "A", 0, 3) == (1, 3)  # 迟到 1 小时
    # 但整体会选一个大家都能全程的开始时间
    choice = choose_evaluation(problem)
    assert choice.missing_hours == 0 and choice.start >= 1


def test_three_hours_with_late_beats_two_hours_full(problem):
    d = problem.config.eval_date
    for m in problem.members:
        problem.availability.set_row(m, d, [UNAVAILABLE] * 13)
        set_slots(problem.availability, m, d, [5, 6, 7], 1)
    set_slots(problem.availability, "A", d, [7])  # A 只能到 5、6 两格
    choice = choose_evaluation(problem)
    assert choice.duration == 3 and choice.start == 5
    assert choice.attendance["A"] == (5, 7) and choice.missing_hours == 1


def test_falls_back_to_two_hours(problem):
    d = problem.config.eval_date
    for m in problem.members:
        problem.availability.set_row(m, d, [UNAVAILABLE] * 13)
        set_slots(problem.availability, m, d, [5, 6], 1)
    choice = choose_evaluation(problem)
    assert choice.duration == 2 and choice.start == 5 and choice.missing_hours == 0


def test_infeasible_when_member_cannot_stay_two_hours(problem):
    d = problem.config.eval_date
    for m in problem.members:
        problem.availability.set_row(m, d, [UNAVAILABLE] * 13)
        set_slots(problem.availability, m, d, [5, 6, 7], 1)
    set_slots(problem.availability, "A", d, [5, 7])  # A 只剩 6
    assert choose_evaluation(problem) is None
    diag = diagnose_evaluation(problem)
    assert diag["可行窗口数"] == 0
    best = diag["最接近的窗口"][0]
    assert best["缺少人数"] == 1 and best["阻塞成员"] == {"A": 1}
