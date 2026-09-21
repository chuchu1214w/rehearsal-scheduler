"""排练地点:任何版本原地填写;已发布版本通知该场成员;显示在详情与日历;复制 / 重排时沿用。"""

from fastapi.testclient import TestClient

from tests.api.conftest import open_account
from tests.api.test_schedule import _solved_event


def test_location_notifies_session_members_when_published(app, admin: TestClient):
    ev, (a, b, c), vid, client_c = _solved_event(app, admin)
    client_a = open_account(app, admin, a, "aa")
    d = admin.get(f"/api/schedules/{vid}").json()
    s = next(x for x in d["sessions"] if x["kind"] == "formal" and {m["display_name"] for m in x["members"]} == {"A", "B"})
    # 草稿:能存,但不通知,也不产生新版本
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/location", json={"location": " 三楼排练厅 "})
    assert r.status_code == 200, r.text
    assert r.json()["notified"] == 0 and r.json()["version"]["id"] == vid
    assert next(x for x in r.json()["version"]["sessions"] if x["id"] == s["id"])["location"] == "三楼排练厅"
    assert len(admin.get(f"/api/events/{ev['id']}/schedules").json()) == 1
    assert all(n["type"] != "location" for n in client_a.get("/api/notifications").json())

    # 发布后再改地点 → 只通知这场的 A(B 没账号)、C 不在这场
    admin.post(f"/api/schedules/{vid}/publish")
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/location", json={"location": "B1 舞蹈室"})
    assert r.json()["notified"] == 1
    top = client_a.get("/api/notifications").json()[0]
    assert top["type"] == "location" and top["title"] == "排练地点:B1 舞蹈室" and top["link"].startswith(f"/schedule/day/{s['date']}")
    assert all(n["type"] != "location" for n in client_c.get("/api/notifications").json())
    # 同一地点重复保存不重复通知;版本仍是发布状态
    assert admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/location", json={"location": "B1 舞蹈室"}).json()["notified"] == 0
    assert admin.get(f"/api/schedules/{vid}").json()["status"] == "published"

    # 成员端详情与日历里都有地点
    pub = client_a.get(f"/api/events/{ev['id']}/schedule/published").json()
    assert next(x for x in pub["sessions"] if x["id"] == s["id"])["location"] == "B1 舞蹈室"
    cal = client_a.get("/api/me/calendar").json()
    ics = TestClient(app).get(cal["url"].removeprefix("http://test")).text
    assert "LOCATION:B1 舞蹈室" in ics

    # 评估场也能填地点并通知全员(A、C 有账号)
    ev_s = next(x for x in d["sessions"] if x["kind"] == "evaluation")
    assert admin.post(f"/api/schedules/{vid}/sessions/{ev_s['id']}/location", json={"location": "大剧场"}).json()["notified"] == 2

    # 复制成草稿(锁定)时地点跟着走;锁定后重排时时间不变的场次沿用地点
    forked = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/lock", json={"locked": True}).json()["version"]
    assert next(x for x in forked["sessions"] if x["song_code"] == s["song_code"] and x["date"] == s["date"])["location"] == "B1 舞蹈室"
    job = admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": forked["id"]}).json()
    assert job["status"] == "succeeded"
    new = admin.get(f"/api/schedules/{job['version_id']}").json()
    kept = next(x for x in new["sessions"] if x["locked"])
    assert kept["location"] == "B1 舞蹈室"
    # 清空地点
    assert (
        next(
            x
            for x in admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/location", json={"location": ""}).json()["version"]["sessions"]
            if x["id"] == s["id"]
        )["location"]
        == ""
    )
