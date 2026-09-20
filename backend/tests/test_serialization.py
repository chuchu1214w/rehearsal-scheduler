import json
from datetime import date

from solver.lexicographic import solve
from solver.serialization import problem_from_dict, problem_to_dict, result_to_dict, session_from_dict, session_to_dict
from solver.types import FixedSession, Rules
from tests.conftest import set_slots


def test_problem_round_trip(problem):
    problem.rules = Rules(
        blocked_slots={date(2026, 9, 5): frozenset({1, 2})},
        max_sessions_per_date={date(2026, 9, 4): 1},
        member_song_max_attendance={("A", "s1"): 1},
        focus_members=("B",),
        fixed_sessions=(FixedSession("s3", date(2026, 9, 6), 3, 2),),
    )
    set_slots(problem.availability, "A", date(2026, 9, 4), [0, 1])
    set_slots(problem.availability, "A", date(2026, 9, 4), [2], 2)
    data = problem_to_dict(problem)
    text = json.dumps(data, ensure_ascii=False)  # 必须可序列化
    back = problem_from_dict(json.loads(text))
    assert back.config == problem.config
    assert back.members == problem.members and back.songs == problem.songs
    assert back.availability.grid == problem.availability.grid
    assert back.rules == problem.rules
    assert back.ladder == problem.ladder and back.objectives == problem.objectives
    assert data["availability"]["A"]["2026-09-04"].startswith("0021")


def test_availability_accepts_list_rows(problem):
    data = problem_to_dict(problem)
    data["availability"]["A"]["2026-09-04"] = [1] * 13
    assert problem_from_dict(data).availability.grid["A"][date(2026, 9, 4)] == [1] * 13


def test_blocked_all_keyword(problem):
    data = problem_to_dict(problem)
    data["rules"]["blocked_slots"] = {"2026-09-05": "all"}
    back = problem_from_dict(data)
    assert set(range(13)) <= back.rules.blocked_slots[date(2026, 9, 5)]


def test_result_and_sessions_round_trip(problem):
    result = solve(problem)
    payload = result_to_dict(problem, result)
    json.dumps(payload, ensure_ascii=False)
    for s in result.sessions:
        assert session_from_dict(session_to_dict(problem, s)) == s
    assert payload["sessions"][-1]["song_name"] in {"全员评估", "第一首", "第二首", "第三首"}
