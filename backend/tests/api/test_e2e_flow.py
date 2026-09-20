"""端到端主流程(M6 验收)。

首次设置 → 建演出 → 人员 / 账号 → 曲目 / 要求 → 成员填报 → 求解 → 发布 → 成员查看 / 订阅日历
→ 改空闲 → 锁定重排 → 再发布。
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_full_flow(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'e2e.db'}",
            frontend_dist=None,
            public_base_url="http://test",
            solver_mode="inline",
            solver_workers=4,
            reminders_interval_minutes=0,
        )
    )
    admin = TestClient(app)
    assert admin.get("/api/setup/status").json()["needs_setup"] is True
    assert admin.post("/api/setup", json={"username": "captain", "password": "Passw0rd!"}).status_code == 201

    # 四步向导
    ev = admin.post(
        "/api/events",
        json={
            "name": "端到端演出",
            "performance_date": "2026-09-10",
            "formal_start_date": "2026-09-04",
            "availability_deadline": "2026-09-02",
        },
    ).json()
    members = admin.post(f"/api/events/{ev['id']}/members", json={"names": ["甲", "乙", "丙"]}).json()
    ids = {m["display_name"]: m["member_id"] for m in members}
    s1 = admin.post(
        f"/api/events/{ev['id']}/songs", json={"name": "曲一", "difficulty": "简单", "member_ids": [ids["甲"], ids["乙"]]}
    ).json()
    admin.post(
        f"/api/events/{ev['id']}/songs",
        json={"name": "曲二", "difficulty": "一般", "member_ids": [ids["乙"], ids["丙"]], "session_plan": [3]},
    )
    r = admin.post(
        f"/api/events/{ev['id']}/rules",
        json={"type": "member_song_max_absent", "params": {"member_id": ids["甲"], "song_id": s1["id"], "n": 1}},
    )
    assert r.status_code == 201 and r.json()["warning"] is None
    creds = admin.post(f"/api/events/{ev['id']}/accounts", json={"password": "season2026"}).json()
    assert len(creds) == 3
    e = admin.get(f"/api/events/{ev['id']}").json()
    assert e["current_step"] == 5 and [s["state"] for s in e["steps"]][:4] == ["done"] * 4

    # 成员登录、看到待办通知、填报
    clients = {}
    for c in creds:
        cl = TestClient(app)
        assert cl.post("/api/auth/login", json={"username": c["username"], "password": "season2026"}).status_code == 200
        me = cl.get("/api/me").json()
        assert me["must_change_password"] is True
        assert cl.get("/api/notifications").json()[0]["type"] == "joined"
        clients[c["display_name"]] = cl
    days = {f"2026-09-{x:02d}": "1" * 13 for x in range(4, 10)}
    for name, cl in clients.items():
        r = cl.put(f"/api/events/{ev['id']}/availability/{ids[name]}", json={"days": days, "submit": True})
        assert r.status_code == 200
    assert admin.get("/api/notifications").json()[0]["type"] == "all_submitted"
    assert admin.post(f"/api/events/{ev['id']}/precheck").json()["can_solve"] is True

    # 求解 → 发布 → 成员端可见、日历有事件
    job = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    assert job["status"] == "succeeded"
    assert admin.post(f"/api/schedules/{job['version_id']}/publish").status_code == 200
    pub = clients["丙"].get(f"/api/events/{ev['id']}/schedule/published").json()
    assert pub["version_no"] == 1 and pub["my_member_id"] == ids["丙"]
    cal = clients["丙"].get("/api/me/calendar").json()
    ics = TestClient(app).get(cal["url"].removeprefix("http://test")).text
    assert ics.count("BEGIN:VEVENT") == 2  # 曲二 1 场 + 评估
    assert clients["丙"].get("/api/notifications").json()[0]["type"] == "published"

    # 丙改空闲 → 管理员收到冲突通知 → 锁定其余、重排 → 发布 v2 → 成员收到「较 v1」
    d = admin.get(f"/api/schedules/{job['version_id']}").json()
    s = next(x for x in d["sessions"] if x["kind"] == "formal" and any(m["id"] == ids["丙"] for m in x["members"]))
    clients["丙"].put(f"/api/events/{ev['id']}/availability/{ids['丙']}", json={"days": {s["date"]: "0" * 13}, "submit": True})
    assert admin.get("/api/notifications").json()[0]["type"] == "conflict"
    conflicts = admin.get(f"/api/events/{ev['id']}/schedule/conflicts").json()
    assert len(conflicts["items"]) == 1
    other = next(x for x in d["sessions"] if x["kind"] == "formal" and x["id"] != s["id"])
    forked = admin.post(f"/api/schedules/{job['version_id']}/sessions/{other['id']}/lock", json={"locked": True}).json()
    assert forked["forked"] is True
    job2 = admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": forked["version"]["id"]}).json()
    assert job2["status"] == "succeeded"
    v3 = admin.get(f"/api/schedules/{job2['version_id']}").json()
    assert v3["locked_count"] == 1 and v3["validation_errors"] == []
    assert admin.get(f"/api/events/{ev['id']}/schedule/conflicts", params={"version_id": v3["id"]}).json()["items"] == []
    assert admin.post(f"/api/schedules/{v3['id']}/publish").status_code == 200
    top = clients["丙"].get("/api/notifications").json()[0]
    assert "v3 已发布" in top["title"] and "较 v1" in top["body"]
    e = admin.get(f"/api/events/{ev['id']}").json()
    assert e["published_version_no"] == 3 and e["conflict_count"] == 0 and e["steps"][6]["state"] == "done"
