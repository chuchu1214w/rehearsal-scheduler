import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import add_member, make_event


@pytest.fixture
def event(admin: TestClient):
    a, b, c = (add_member(admin, n) for n in ("A", "B", "C"))
    ev = make_event(admin)
    admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [a["id"], b["id"]]})
    return ev, a, b, c


def test_song_crud_and_session_plans(admin: TestClient, event):
    ev, a, b, _c = event
    r = admin.post(f"/api/events/{ev['id']}/songs", json={"code": "a", "name": "简单曲", "difficulty": "简单", "member_ids": [a["id"]]})
    assert r.status_code == 201
    s1 = r.json()
    assert s1["durations"] == [2, 2] and s1["session_count"] == 2 and s1["session_plan"] is None
    r = admin.post(
        f"/api/events/{ev['id']}/songs",
        json={"code": "b", "name": "覆盖曲", "difficulty": "一般", "member_ids": [a["id"], b["id"]], "session_plan": [3, 2]},
    )
    s2 = r.json()
    assert s2["durations"] == [3, 2] and s2["session_count"] == 2
    lst = admin.get(f"/api/events/{ev['id']}/songs").json()
    assert lst["total_sessions"] == 4 and lst["warnings"] == []
    assert admin.get(f"/api/events/{ev['id']}").json()["session_count"] == 4

    r = admin.patch(f"/api/songs/{s2['id']}", json={"clear_session_plan": True, "difficulty": "困难"})
    assert r.json()["durations"] == [3, 3, 3]
    r = admin.patch(f"/api/songs/{s1['id']}", json={"session_plan": [2], "name": "改名"})
    assert r.json()["durations"] == [2] and r.json()["name"] == "改名"
    assert admin.delete(f"/api/songs/{s1['id']}").status_code == 204
    assert admin.get(f"/api/events/{ev['id']}/songs").json()["total_sessions"] == 3
    assert admin.delete("/api/songs/999").status_code == 404


def test_template_change_updates_durations(admin: TestClient, event):
    ev, a, _b, _c = event
    s = admin.post(f"/api/events/{ev['id']}/songs", json={"code": "a", "name": "x", "difficulty": "简单", "member_ids": [a["id"]]}).json()
    settings = {**ev["settings"], "difficulty_templates": {**ev["settings"]["difficulty_templates"], "简单": [2, 2, 2]}}
    admin.patch(f"/api/events/{ev['id']}", json={"settings": settings})
    songs = admin.get(f"/api/events/{ev['id']}/songs").json()["songs"]
    assert songs[0]["id"] == s["id"] and songs[0]["durations"] == [2, 2, 2]


def test_song_validation(admin: TestClient, event):
    ev, a, b, c = event
    base = {"name": "x", "difficulty": "简单", "member_ids": [a["id"]]}
    assert admin.post(f"/api/events/{ev['id']}/songs", json={**base, "code": "a"}).status_code == 201
    assert admin.post(f"/api/events/{ev['id']}/songs", json={**base, "code": "A"}).status_code == 409  # 代号不区分大小写
    assert admin.post(f"/api/events/{ev['id']}/songs", json={**base, "code": "b", "member_ids": [c["id"]]}).status_code == 422  # 不在活动中
    assert admin.post(f"/api/events/{ev['id']}/songs", json={**base, "code": "b", "member_ids": []}).status_code == 422
    assert admin.post(f"/api/events/{ev['id']}/songs", json={**base, "code": "b", "difficulty": "超难"}).status_code == 422
    assert admin.post(f"/api/events/{ev['id']}/songs", json={**base, "code": "b", "session_plan": [0]}).status_code == 422
    assert admin.post(f"/api/events/{ev['id']}/songs", json={**base, "code": "b", "member_ids": [a["id"], a["id"]]}).status_code == 422
    assert admin.post("/api/events/999/songs", json={**base, "code": "b"}).status_code == 404
    r = admin.post(f"/api/events/{ev['id']}/songs", json={**base, "code": "b", "member_ids": [a["id"], b["id"]]})
    assert r.status_code == 201
    assert admin.patch(f"/api/songs/{r.json()['id']}", json={"code": "a"}).status_code == 409


def test_identical_member_sets_warn(admin: TestClient, event):
    ev, a, b, _c = event
    for code in ("a", "b"):
        admin.post(
            f"/api/events/{ev['id']}/songs", json={"code": code, "name": code, "difficulty": "简单", "member_ids": [b["id"], a["id"]]}
        )
    lst = admin.get(f"/api/events/{ev['id']}/songs").json()
    assert len(lst["warnings"]) == 1 and "完全相同" in lst["warnings"][0]
