from fastapi.testclient import TestClient

from tests.api.conftest import EVENT_BODY, add_member, invite_and_accept, make_event


def test_create_event_derives_dates(admin: TestClient):
    ev = make_event(admin)
    assert ev["formal_end_date"] == "2026-09-18" and ev["eval_date"] == "2026-09-19"
    assert ev["formal_day_count"] == 15 and ev["slots_per_day"] == 13
    assert ev["settings"]["difficulty_templates"]["困难"] == [3, 3, 3]
    assert ev["status"] == "preparing" and ev["member_count"] == 0 and ev["session_count"] == 0


def test_create_event_validation(admin: TestClient):
    assert admin.post("/api/events", json={**EVENT_BODY, "formal_start_date": "2026-09-19"}).status_code == 422
    assert admin.post("/api/events", json={**EVENT_BODY, "timezone": "Mars/Olympus"}).status_code == 422
    assert admin.post("/api/events", json={**EVENT_BODY, "day_start_hour": 12, "day_end_hour": 11}).status_code == 422
    bad = {**EVENT_BODY, "settings": {"soft_daily_limit": 9, "hard_daily_limit": 8}}
    assert admin.post("/api/events", json=bad).status_code == 422
    bad = {**EVENT_BODY, "settings": {"difficulty_templates": {"简单": [2]}}}
    assert admin.post("/api/events", json=bad).status_code == 422
    bad = {**EVENT_BODY, "settings": {"eval_durations": [14]}}
    assert admin.post("/api/events", json=bad).status_code == 422


def test_patch_and_delete_event(admin: TestClient):
    ev = make_event(admin)
    r = admin.patch(f"/api/events/{ev['id']}", json={"name": "改名", "status": "collecting", "day_end_hour": 22})
    assert r.status_code == 200 and r.json()["name"] == "改名" and r.json()["slots_per_day"] == 12
    assert admin.patch(f"/api/events/{ev['id']}", json={"performance_date": "2026-09-05"}).status_code == 422
    new_settings = {**ev["settings"], "soft_daily_limit": 6}
    assert admin.patch(f"/api/events/{ev['id']}", json={"settings": new_settings}).json()["settings"]["soft_daily_limit"] == 6
    assert admin.delete(f"/api/events/{ev['id']}").status_code == 204
    assert admin.get(f"/api/events/{ev['id']}").status_code == 404


def test_member_visibility(app, admin: TestClient, member):
    client, m = member
    ev1 = make_event(admin, name="我参加的")
    ev2 = make_event(admin, name="我没参加的")
    admin.put(f"/api/events/{ev1['id']}/members", json={"member_ids": [m["id"]]})
    assert [e["name"] for e in client.get("/api/events").json()] == ["我参加的"]
    assert client.get(f"/api/events/{ev1['id']}").status_code == 200
    assert client.get(f"/api/events/{ev2['id']}").status_code == 403
    assert client.get(f"/api/events/{ev2['id']}/members").status_code == 403
    assert client.get(f"/api/events/{ev2['id']}/songs").status_code == 403
    assert client.get(f"/api/events/{ev1['id']}/members").json()[0]["display_name"] == "小明"


def test_set_event_members(admin: TestClient):
    a, b = add_member(admin, "A"), add_member(admin, "B")
    ev = make_event(admin)
    r = admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [b["id"], a["id"], a["id"]]})
    assert [x["display_name"] for x in r.json()] == ["A", "B"]
    assert admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [999]}).status_code == 422
    admin.post(f"/api/events/{ev['id']}/songs", json={"code": "a", "name": "歌", "difficulty": "简单", "member_ids": [a["id"]]})
    r = admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [b["id"]]})
    assert r.status_code == 409 and "A(a)" in r.json()["detail"]
    r = admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [a["id"]]})
    assert [x["display_name"] for x in r.json()] == ["A"]
    assert admin.get(f"/api/events/{ev['id']}").json()["member_count"] == 1


def test_clone_event(app, admin: TestClient):
    a, b = add_member(admin, "A"), add_member(admin, "B")
    ev = make_event(admin)
    admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [a["id"], b["id"]]})
    admin.post(
        f"/api/events/{ev['id']}/songs",
        json={"code": "a", "name": "歌", "difficulty": "一般", "member_ids": [a["id"], b["id"]], "session_plan": [3, 2]},
    )
    r = admin.post(
        f"/api/events/{ev['id']}/clone",
        json={"name": "冬季路演", "performance_date": "2026-12-20", "formal_start_date": "2026-12-01"},
    )
    assert r.status_code == 201
    clone = r.json()
    assert clone["member_count"] == 2 and clone["song_count"] == 1 and clone["session_count"] == 2
    songs = admin.get(f"/api/events/{clone['id']}/songs").json()["songs"]
    assert songs[0]["session_plan"] == [3, 2] and [m["display_name"] for m in songs[0]["members"]] == ["A", "B"]
    # 克隆是独立副本
    admin.delete(f"/api/events/{ev['id']}")
    assert admin.get(f"/api/events/{clone['id']}").status_code == 200
    # 新成员账号看不到未参加的克隆
    c = invite_and_accept(app, admin, add_member(admin, "C"), "cc")
    assert c.get("/api/events").json() == []
