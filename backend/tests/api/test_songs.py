import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import add_member, add_song, make_event


@pytest.fixture
def event(admin: TestClient):
    a, b, c = (add_member(admin, n) for n in ("A", "B", "C"))
    ev = make_event(admin, member_ids=[a["id"], b["id"]])
    return ev, a, b, c


def test_song_crud_and_session_plans(admin: TestClient, event):
    ev, a, b, _c = event
    s1 = add_song(admin, ev["id"], "简单曲", [a["id"]])
    assert s1["code"] == "a" and s1["durations"] == [2, 2] and s1["session_count"] == 2 and s1["session_plan"] is None
    s2 = add_song(admin, ev["id"], "覆盖曲", [a["id"], b["id"]], "一般", session_plan=[3, 2])
    assert s2["code"] == "b" and s2["durations"] == [3, 2]
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
    # 删除 a 后,新曲目重新拿到代号 a
    assert add_song(admin, ev["id"], "新曲", [a["id"]])["code"] == "a"


def test_template_change_updates_durations(admin: TestClient, event):
    ev, a, _b, _c = event
    s = add_song(admin, ev["id"], "x", [a["id"]])
    settings = {**ev["settings"], "difficulty_templates": {**ev["settings"]["difficulty_templates"], "简单": [2, 2, 2]}}
    admin.patch(f"/api/events/{ev['id']}", json={"settings": settings})
    songs = admin.get(f"/api/events/{ev['id']}/songs").json()["songs"]
    assert songs[0]["id"] == s["id"] and songs[0]["durations"] == [2, 2, 2]


def test_song_validation(admin: TestClient, event):
    ev, a, b, c = event
    base = {"name": "x", "difficulty": "简单", "member_ids": [a["id"]]}
    url = f"/api/events/{ev['id']}/songs"
    assert admin.post(url, json={**base, "code": "a"}).status_code == 201
    assert admin.post(url, json={**base, "code": "A"}).status_code == 409  # 代号不区分大小写
    assert admin.post(url, json={**base, "member_ids": [c["id"]]}).status_code == 422  # 不在演出中
    assert admin.post(url, json={**base, "member_ids": []}).status_code == 422
    assert admin.post(url, json={**base, "difficulty": "超难"}).status_code == 422
    assert admin.post(url, json={**base, "session_plan": [0]}).status_code == 422
    assert admin.post(url, json={**base, "member_ids": [a["id"], a["id"]]}).status_code == 422
    assert admin.post("/api/events/999/songs", json=base).status_code == 404
    r = admin.post(url, json={**base, "member_ids": [a["id"], b["id"]]})
    assert r.status_code == 201 and r.json()["code"] == "b"
    assert admin.patch(f"/api/songs/{r.json()['id']}", json={"code": "a"}).status_code == 409


def test_identical_member_sets_warn(admin: TestClient, event):
    ev, a, b, _c = event
    for name in ("x", "y"):
        add_song(admin, ev["id"], name, [b["id"], a["id"]])
    lst = admin.get(f"/api/events/{ev['id']}/songs").json()
    assert len(lst["warnings"]) == 1 and "完全相同" in lst["warnings"][0]
