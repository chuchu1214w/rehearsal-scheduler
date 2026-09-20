from fastapi.testclient import TestClient

from tests.api.conftest import EVENT_BODY, MEMBER_PW, add_member, add_song, make_event, open_account


def test_create_event_derives_dates_and_steps(admin: TestClient):
    ev = make_event(admin)
    assert ev["formal_end_date"] == "2026-09-18" and ev["eval_date"] == "2026-09-19"
    assert ev["formal_day_count"] == 15 and ev["slots_per_day"] == 13
    assert ev["availability_deadline"] == "2026-09-10"  # 默认演出前 10 天
    assert ev["settings"]["difficulty_templates"]["困难"] == [3, 3, 3]
    assert ev["status"] == "preparing" and ev["member_count"] == 0 and ev["session_count"] == 0
    assert ev["current_step"] == 2
    assert [s["state"] for s in ev["steps"]] == ["done", "current", "todo", "todo", "todo", "todo", "todo"]
    assert "9/4–9/18 排练" in ev["steps"][0]["summary"]


def test_create_event_validation(admin: TestClient):
    assert admin.post("/api/events", json={**EVENT_BODY, "formal_start_date": "2026-09-19"}).status_code == 422
    assert admin.post("/api/events", json={**EVENT_BODY, "timezone": "Mars/Olympus"}).status_code == 422
    assert admin.post("/api/events", json={**EVENT_BODY, "day_start_hour": 12, "day_end_hour": 11}).status_code == 422
    assert admin.post("/api/events", json={**EVENT_BODY, "settings": {"soft_daily_limit": 9, "hard_daily_limit": 8}}).status_code == 422
    assert admin.post("/api/events", json={**EVENT_BODY, "settings": {"difficulty_templates": {"简单": [2]}}}).status_code == 422
    assert admin.post("/api/events", json={**EVENT_BODY, "settings": {"eval_durations": [14]}}).status_code == 422
    assert admin.post("/api/events", json={**EVENT_BODY, "member_ids": [999]}).status_code == 422


def test_patch_and_delete_event(admin: TestClient):
    ev = make_event(admin)
    r = admin.patch(
        f"/api/events/{ev['id']}", json={"name": "改名", "status": "collecting", "day_end_hour": 22, "availability_deadline": "2026-09-01"}
    )
    assert r.status_code == 200 and r.json()["name"] == "改名" and r.json()["slots_per_day"] == 12
    assert r.json()["availability_deadline"] == "2026-09-01"
    assert admin.patch(f"/api/events/{ev['id']}", json={"clear_availability_deadline": True}).json()["availability_deadline"] is None
    assert admin.patch(f"/api/events/{ev['id']}", json={"performance_date": "2026-09-05"}).status_code == 422
    new_settings = {**ev["settings"], "soft_daily_limit": 6}
    assert admin.patch(f"/api/events/{ev['id']}", json={"settings": new_settings}).json()["settings"]["soft_daily_limit"] == 6
    assert admin.delete(f"/api/events/{ev['id']}").status_code == 204
    assert admin.get(f"/api/events/{ev['id']}").status_code == 404


def test_member_visibility(app, admin: TestClient, member):
    client, m = member
    ev1 = make_event(admin, name="我参加的", member_ids=[m["id"]])
    ev2 = make_event(admin, name="我没参加的")
    assert [e["name"] for e in client.get("/api/events").json()] == ["我参加的"]
    assert client.get(f"/api/events/{ev1['id']}").status_code == 200
    assert client.get(f"/api/events/{ev2['id']}").status_code == 403
    assert client.get(f"/api/events/{ev2['id']}/members").status_code == 403
    assert client.get(f"/api/events/{ev2['id']}/songs").status_code == 403
    row = client.get(f"/api/events/{ev1['id']}/members").json()[0]
    assert row["display_name"] == "小明" and row["account"]["username"] == "xiaoming"


def test_add_members_by_name_and_remove(admin: TestClient):
    existing = add_member(admin, "衿", aliases=["jin"])
    ev = make_event(admin)
    r = admin.post(f"/api/events/{ev['id']}/members", json={"names": ["jin", " 菁 ", "若", "菁"]})
    assert r.status_code == 201
    names = [x["display_name"] for x in r.json()]
    assert names == ["衿", "菁", "若"]  # 别名匹配到已有成员,其余自动创建,去重
    assert r.json()[0]["member_id"] == existing["id"]
    assert len(admin.get("/api/members").json()) == 3
    assert admin.get(f"/api/events/{ev['id']}").json()["current_step"] == 3

    ids = {x["display_name"]: x["member_id"] for x in r.json()}
    add_song(admin, ev["id"], "歌", [ids["衿"]])
    assert admin.delete(f"/api/events/{ev['id']}/members/{ids['衿']}").status_code == 409
    assert admin.delete(f"/api/events/{ev['id']}/members/{ids['若']}").status_code == 204
    assert admin.delete(f"/api/events/{ev['id']}/members/{ids['若']}").status_code == 404
    assert [x["display_name"] for x in admin.get(f"/api/events/{ev['id']}/members").json()] == ["衿", "菁"]


def test_set_event_members(admin: TestClient):
    a, b = add_member(admin, "A"), add_member(admin, "B")
    ev = make_event(admin)
    r = admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [b["id"], a["id"], a["id"]]})
    assert [x["display_name"] for x in r.json()] == ["A", "B"]
    assert admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [999]}).status_code == 422
    add_song(admin, ev["id"], "歌", [a["id"]])
    r = admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [b["id"]]})
    assert r.status_code == 409 and "A(a)" in r.json()["detail"]
    r = admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [a["id"]]})
    assert [x["display_name"] for x in r.json()] == ["A"]
    assert admin.get(f"/api/events/{ev['id']}").json()["member_count"] == 1


def test_batch_open_accounts(app, admin: TestClient):
    a, b, c = add_member(admin, "衿"), add_member(admin, "菁"), add_member(admin, "停用", active=False)
    ev = make_event(admin, member_ids=[a["id"], b["id"], c["id"]])
    open_account(app, admin, a, "jin")
    r = admin.post(f"/api/events/{ev['id']}/accounts", json={"password": MEMBER_PW})
    assert r.status_code == 201
    assert [x["display_name"] for x in r.json()] == ["菁"]  # 已开通与停用的跳过
    assert r.json()[0]["username"] == "菁" and r.json()[0]["password"] == MEMBER_PW
    assert admin.get(f"/api/events/{ev['id']}").json()["account_count"] == 2
    assert TestClient(app).post("/api/auth/login", json={"username": "菁", "password": MEMBER_PW}).status_code == 200
    assert admin.post(f"/api/events/{ev['id']}/accounts", json={"password": MEMBER_PW}).json() == []


def test_clone_event(app, admin: TestClient):
    a, b = add_member(admin, "A"), add_member(admin, "B")
    ev = make_event(admin, member_ids=[a["id"], b["id"]])
    add_song(admin, ev["id"], "歌", [a["id"], b["id"]], "一般", session_plan=[3, 2])
    r = admin.post(
        f"/api/events/{ev['id']}/clone", json={"name": "冬季路演", "performance_date": "2026-12-20", "formal_start_date": "2026-12-01"}
    )
    assert r.status_code == 201
    clone = r.json()
    assert clone["member_count"] == 2 and clone["song_count"] == 1 and clone["session_count"] == 2
    assert clone["availability_deadline"] == "2026-12-10"
    songs = admin.get(f"/api/events/{clone['id']}/songs").json()["songs"]
    assert songs[0]["session_plan"] == [3, 2] and [m["display_name"] for m in songs[0]["members"]] == ["A", "B"]
    admin.delete(f"/api/events/{ev['id']}")
    assert admin.get(f"/api/events/{clone['id']}").status_code == 200
    c = open_account(app, admin, add_member(admin, "C"), "cc")
    assert c.get("/api/events").json() == []


def test_precheck(app, admin: TestClient):
    a, b = add_member(admin, "A"), add_member(admin, "B")
    ev = make_event(admin, member_ids=[a["id"], b["id"]])
    r = admin.post(f"/api/events/{ev['id']}/precheck")
    assert r.status_code == 200 and r.json()["can_solve"] is False
    assert any(i["key"] == "songs" and i["level"] == "error" for i in r.json()["items"])

    add_song(admin, ev["id"], "歌", [a["id"], b["id"]])
    r = admin.post(f"/api/events/{ev['id']}/precheck").json()
    assert r["can_solve"] is True
    keys = {i["key"]: i for i in r["items"]}
    assert keys["submitted"]["ok"] is False and "2 位成员" in keys["submitted"]["label"]
    assert keys["evaluation"]["ok"] is False and keys["candidates"]["ok"] is False

    # 两人都填满并提交 → 全部通过
    full = {d: "1" * 13 for d in [f"2026-09-{x:02d}" for x in range(4, 20)]}
    for m in (a, b):
        assert admin.put(f"/api/events/{ev['id']}/availability/{m['id']}", json={"days": full, "submit": True}).status_code == 200
    r = admin.post(f"/api/events/{ev['id']}/precheck").json()
    assert r["warnings"] == 0 and all(i["ok"] for i in r["items"])
    ev2 = admin.get(f"/api/events/{ev['id']}").json()
    assert ev2["submitted_count"] == 2 and ev2["current_step"] == 6
    assert [s["state"] for s in ev2["steps"]] == ["done"] * 5 + ["current", "todo"]
