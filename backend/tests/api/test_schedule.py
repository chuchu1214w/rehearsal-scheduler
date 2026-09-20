"""M4:发布 / 撤回、成员端已发布排练表、日历订阅。"""

from fastapi.testclient import TestClient

from tests.api.conftest import add_member, add_song, make_event, open_account

SHORT = {"performance_date": "2026-09-10", "formal_start_date": "2026-09-04"}
DAYS = [f"2026-09-{x:02d}" for x in range(4, 10)]
FULL = {d: "1" * 13 for d in DAYS}


def _solved_event(app, admin: TestClient):
    a, b, c = (add_member(admin, n) for n in ("A", "B", "C"))
    ev = make_event(admin, **SHORT, member_ids=[a["id"], b["id"], c["id"]])
    add_song(admin, ev["id"], "第一首", [a["id"], b["id"]], "简单")
    add_song(admin, ev["id"], "第二首", [b["id"], c["id"]], "一般", session_plan=[3])
    for m in (a, b, c):
        admin.put(f"/api/events/{ev['id']}/availability/{m['id']}", json={"days": FULL, "submit": True})
    job = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    assert job["status"] == "succeeded"
    client_c = open_account(app, admin, c, "cc")
    return ev, (a, b, c), job["version_id"], client_c


def test_publish_and_member_view(app, admin: TestClient):
    ev, (a, b, c), vid, member_c = _solved_event(app, admin)
    # 未发布:成员看不到
    assert member_c.get(f"/api/events/{ev['id']}/schedule/published").status_code == 404
    assert admin.get(f"/api/events/{ev['id']}").json()["steps"][6]["state"] == "current"

    r = admin.post(f"/api/schedules/{vid}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published" and r.json()["published_at"] is not None
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 409
    e = admin.get(f"/api/events/{ev['id']}").json()
    assert e["published_version_no"] == 1 and e["steps"][6]["state"] == "done" and "已发布 v1" in e["steps"][6]["summary"]

    pub = member_c.get(f"/api/events/{ev['id']}/schedule/published").json()
    assert pub["version_no"] == 1 and pub["my_member_id"] == c["id"] and pub["event_name"] == ev["name"]
    assert pub["eval_date"] == "2026-09-09" and pub["formal_end_date"] == "2026-09-08" and pub["day_start_hour"] == 10
    assert len(pub["sessions"]) == 4
    admin_view = admin.get(f"/api/events/{ev['id']}/schedule/published").json()
    assert admin_view["my_member_id"] is None

    # 再求解一版并发布 → 旧版归档
    job2 = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    assert admin.post(f"/api/schedules/{job2['version_id']}/publish").status_code == 200
    statuses = {v["version_no"]: v["status"] for v in admin.get(f"/api/events/{ev['id']}/schedules").json()}
    assert statuses == {1: "archived", 2: "published"}
    assert member_c.get(f"/api/events/{ev['id']}/schedule/published").json()["version_no"] == 2

    # 撤回发布
    assert admin.post(f"/api/schedules/{job2['version_id']}/unpublish").json()["status"] == "draft"
    assert member_c.get(f"/api/events/{ev['id']}/schedule/published").status_code == 404
    assert admin.post(f"/api/schedules/{job2['version_id']}/unpublish").status_code == 409


def test_publish_requires_clean_validation(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    # 直接把校验错误写进版本,模拟校验未通过
    from app.models import ScheduleVersion

    with app.state.session_factory() as db:
        v = db.get(ScheduleVersion, vid)
        v.validation_errors = ["V-01 某场成员不可用"]
        db.commit()
    r = admin.post(f"/api/schedules/{vid}/publish")
    assert r.status_code == 422


def test_calendar_feed(app, admin: TestClient, anon: TestClient):
    ev, (a, b, c), vid, member_c = _solved_event(app, admin)
    cal = member_c.get("/api/me/calendar").json()
    assert cal["url"].startswith("http://test/cal/") and cal["url"].endswith(".ics") and cal["webcal_url"].startswith("webcal://test/cal/")
    assert member_c.get("/api/me/calendar").json() == cal  # 令牌稳定
    path = cal["url"].removeprefix("http://test")

    # 未发布:空日历
    r = anon.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar") and "BEGIN:VEVENT" not in r.text

    admin.post(f"/api/schedules/{vid}/publish")
    text = anon.get(path).text
    # C 只参加第二首(1 场)+ 评估 → 2 个事件;第一首(A、B)不在 C 的日历里
    assert text.count("BEGIN:VEVENT") == 2 and "第二首" in text and "第一首" not in text and "全员评估" in text
    assert "DTSTART:" in text and "TRIGGER:-PT60M" in text
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))

    # 管理员的日历包含全部 4 场
    admin_cal = admin.get("/api/me/calendar").json()
    assert anon.get(admin_cal["url"].removeprefix("http://test")).text.count("BEGIN:VEVENT") == 4

    # 轮换令牌后旧链接失效
    new = member_c.post("/api/me/calendar/rotate").json()
    assert new["url"] != cal["url"]
    assert anon.get(path).status_code == 404
    assert anon.get(new["url"].removeprefix("http://test")).status_code == 200
    assert anon.get("/cal/nope.ics").status_code == 404


def test_ics_folding_keeps_multibyte_chars_intact():
    from app.api.calendar import _fold

    line = "DESCRIPTION:人员:" + "、".join(f"成员{i}" for i in range(40))
    folded = _fold(line)
    parts = folded.split("\r\n")
    assert len(parts) > 3
    assert all(len(p.encode("utf-8")) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert folded.replace("\r\n ", "") == line
