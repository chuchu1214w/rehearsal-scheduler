from solver.candidates import build_candidates, candidate_summary, make_tasks
from solver.types import Rules, Song
from tests.conftest import START, make_config, make_problem, set_slots


def test_make_tasks_uses_override_then_template():
    problem = make_problem(songs=(Song("x", "x", "困难", ("A", "B")), Song("y", "y", "一般", ("C", "D"), (3, 2))))
    tasks = make_tasks(problem)
    assert [(t.task_id, t.duration) for t in tasks] == [("x_1", 3), ("x_2", 3), ("x_3", 3), ("y_1", 3), ("y_2", 2)]


def test_full_availability_counts(problem):
    tasks = make_tasks(problem)
    cands = build_candidates(problem, tasks, allow_absent=False)
    assert len(cands["s1_1"]) == 5 * (13 - 2 + 1)
    assert len(cands["s2_1"]) == 5 * (13 - 3 + 1)
    assert all(c.full for cs in cands.values() for c in cs)
    # 全员都可用时不会产生缺席候选
    assert build_candidates(problem, tasks, allow_absent=True) == cands


def test_absent_candidates_only_when_allowed(problem):
    set_slots(problem.availability, "A", START, [0])
    tasks = make_tasks(problem)
    strict = build_candidates(problem, tasks, allow_absent=False)["s1_1"]
    assert len(strict) == 5 * 12 - 1
    relaxed = build_candidates(problem, tasks, allow_absent=True)["s1_1"]
    absent = [c for c in relaxed if not c.full]
    assert [(c.date_idx, c.start, c.absent_member, c.excused) for c in absent] == [(0, 0, "A", False)]


def test_excused_candidates_generated_at_strict_level(problem):
    problem.rules = Rules(member_song_max_attendance={("A", "s1"): 1})
    set_slots(problem.availability, "A", START, [0])
    tasks = make_tasks(problem)
    cands = build_candidates(problem, tasks, allow_absent=False)["s1_1"]
    excused = [c for c in cands if c.excused]
    assert all(c.absent_member == "A" for c in excused)
    # 每个全员候选配一个计划缺席候选,再加 A 不可用那一格的缺席候选
    assert len(excused) == 5 * 12
    assert sum(1 for c in cands if c.full) == 5 * 12 - 1


def test_candidates_respect_window_and_blocks():
    cfg = make_config()
    problem = make_problem(config=cfg, rules=Rules(blocked_slots={START: frozenset(range(13))}))
    tasks = make_tasks(problem)
    cands = build_candidates(problem, tasks, allow_absent=False)
    assert all(c.date_idx != 0 for c in cands["s1_1"])
    assert all(c.start + c.duration <= cfg.slots_per_day for cs in cands.values() for c in cs)


def test_summary_rows(problem):
    tasks = make_tasks(problem)
    rows = candidate_summary(problem, tasks, build_candidates(problem, tasks, allow_absent=False))
    assert rows[0]["任务"] == "s1_1" and rows[0]["覆盖日期数"] == 5
