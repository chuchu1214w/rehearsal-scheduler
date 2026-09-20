import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import add_member, add_song, make_event


@pytest.fixture
def event(admin: TestClient):
    a, b = add_member(admin, "菁"), add_member(admin, "若")
    ev = make_event(admin, member_ids=[a["id"], b["id"]])
    song = add_song(admin, ev["id"], "aespa-lemonadeB", [a["id"], b["id"]])
    return ev, a, b, song


def test_rule_types_listed(admin: TestClient):
    types = admin.get("/api/rule-types").json()
    assert {t["type"] for t in types} >= {"member_song_max_absent", "blocked_day", "fixed_session"}
    absent = next(t for t in types if t["type"] == "member_song_max_absent")
    assert absent["hardness"] == "soft" and "{member}" in absent["template"]


def test_rule_sentences_and_crud(admin: TestClient, event):
    ev, a, b, song = event
    url = f"/api/events/{ev['id']}/rules"
    r = admin.post(url, json={"type": "member_song_max_absent", "params": {"member_id": a["id"], "song_id": song["id"], "n": 1}})
    assert r.status_code == 201
    assert r.json()["sentence"] == "菁 在 a·aespa-lemonadeB 最多可缺席 1 次" and r.json()["hardness"] == "soft"
    r2 = admin.post(url, json={"type": "blocked_day", "params": {"date": "2026-09-10"}})
    assert r2.json()["sentence"] == "9/10 整天不排练" and r2.json()["hardness"] == "hard"
    r3 = admin.post(url, json={"type": "blocked_slots", "params": {"date": "2026-09-11", "start_hour": 18, "end_hour": 21}})
    assert r3.json()["sentence"] == "9/11 的 18:00–21:00 不排练"
    r4 = admin.post(
        url, json={"type": "fixed_session", "params": {"song_id": song["id"], "date": "2026-09-12", "start_hour": 19, "duration": 2}}
    )
    assert r4.json()["sentence"] == "a·aespa-lemonadeB 有一场固定在 9/12 19:00–21:00"
    r5 = admin.post(url, json={"type": "focus_member", "params": {"member_id": b["id"]}})
    assert r5.json()["sentence"] == "尽量把 若 的排练集中在少数几天"
    r6 = admin.post(url, json={"type": "max_sessions_per_date", "params": {"date": "2026-09-13", "n": 2}})
    assert r6.json()["sentence"] == "9/13 最多排 2 场"

    assert len(admin.get(url).json()) == 6
    assert admin.get(f"/api/events/{ev['id']}").json()["rule_count"] == 6
    p = admin.patch(f"/api/rules/{r.json()['id']}", json={"enabled": False})
    assert p.status_code == 200 and p.json()["enabled"] is False
    assert admin.get(f"/api/events/{ev['id']}").json()["rule_count"] == 5
    p = admin.patch(f"/api/rules/{r.json()['id']}", json={"params": {"member_id": a["id"], "song_id": song["id"], "n": 2}})
    assert "2 次" in p.json()["sentence"]
    assert admin.delete(f"/api/rules/{r.json()['id']}").status_code == 204
    assert admin.delete(f"/api/rules/{r.json()['id']}").status_code == 404


def test_rule_validation(admin: TestClient, event):
    ev, a, b, song = event
    url = f"/api/events/{ev['id']}/rules"
    outsider = add_member(admin, "路人")
    bad = [
        {"type": "member_song_max_absent", "params": {"member_id": outsider["id"], "song_id": song["id"], "n": 1}},  # 不是参与人员
        {"type": "member_song_max_absent", "params": {"member_id": a["id"], "song_id": 999, "n": 1}},
        {"type": "member_song_max_absent", "params": {"member_id": a["id"], "song_id": song["id"], "n": 0}},  # 至少 1 次
        {"type": "blocked_day", "params": {"date": "2026-09-19"}},  # 评估日不在正规区间
        {"type": "blocked_day", "params": {"date": "not-a-date"}},
        {"type": "blocked_slots", "params": {"date": "2026-09-11", "start_hour": 22, "end_hour": 22}},
        {"type": "fixed_session", "params": {"song_id": song["id"], "date": "2026-09-12", "start_hour": 22, "duration": 3}},  # 超出窗口
        {"type": "unknown", "params": {}},
    ]
    for body in bad:
        assert admin.post(url, json=body).status_code == 422, body
    # 成员不在该曲目
    other = add_song(admin, ev["id"], "solo", [a["id"]])
    r = admin.post(url, json={"type": "member_song_max_absent", "params": {"member_id": b["id"], "song_id": other["id"], "n": 1}})
    assert r.status_code == 422 and "参演" in r.json()["detail"]


def test_rules_feed_solver_problem(admin: TestClient, event):
    from app.models import Event
    from app.services import event_problem

    ev, a, b, song = event
    url = f"/api/events/{ev['id']}/rules"
    admin.post(url, json={"type": "member_song_max_absent", "params": {"member_id": a["id"], "song_id": song["id"], "n": 1}})
    admin.post(url, json={"type": "blocked_slots", "params": {"date": "2026-09-11", "start_hour": 18, "end_hour": 21}})
    admin.post(
        url, json={"type": "fixed_session", "params": {"song_id": song["id"], "date": "2026-09-12", "start_hour": 19, "duration": 2}}
    )
    with admin.app.state.session_factory() as db:
        problem = event_problem(db.get(Event, ev["id"]))
    assert problem.rules.member_song_max_absent == {("菁", "a"): 1}
    assert problem.rules.blocked_slots[__import__("datetime").date(2026, 9, 11)] == frozenset({8, 9, 10})  # 18–21 点 → 格 8–10
    fx = problem.rules.fixed_sessions[0]
    assert (fx.song_code, fx.start, fx.duration) == ("a", 9, 2)
    assert problem.validate()[0] == []
