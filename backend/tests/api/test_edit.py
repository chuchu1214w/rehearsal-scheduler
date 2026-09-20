"""M5:手动移动 / 锁定、发布版本复制成草稿、锁定重排、版本差异、与最新空闲的冲突。"""

from fastapi.testclient import TestClient

from tests.api.test_schedule import DAYS, _solved_event


def _detail(admin: TestClient, vid: int) -> dict:
    return admin.get(f"/api/schedules/{vid}").json()


def _free_day(detail: dict) -> str:
    used = {s["date"] for s in detail["sessions"]}
    return next(d for d in DAYS[:-1] if d not in used)


def test_move_in_draft_and_reject_hard_violation(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = next(x for x in d["sessions"] if x["kind"] == "formal")
    target = _free_day(d)
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": target, "start_slot": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["forked"] is False and body["version"]["id"] == vid and body["version"]["source"] == "manual"
    moved = next(x for x in body["version"]["sessions"] if x["id"] == s["id"])
    assert moved["date"] == target and moved["start_slot"] == 2 and moved["time"].startswith("12:00")
    assert isinstance(body["warnings"], list)
    assert body["version"]["validation_errors"] == []

    # 某位参演成员在目标日没空 → 拒绝,并说明原因
    who = s["members"][0]["id"]
    other = next(x for x in DAYS[:-1] if x not in (target, s["date"]) and x not in {y["date"] for y in d["sessions"]})
    admin.put(f"/api/events/{ev['id']}/availability/{who}", json={"days": {other: "0" * 13}, "submit": True})
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": other, "start_slot": 2})
    assert r.status_code == 422 and "不能这样改" in r.json()["detail"]
    # 评估日不能放正规排练;评估场不能手动移
    assert admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": DAYS[-1], "start_slot": 2}).status_code == 422
    ev_s = next(x for x in d["sessions"] if x["kind"] == "evaluation")
    assert admin.post(f"/api/schedules/{vid}/sessions/{ev_s['id']}/move", json={"date": target, "start_slot": 2}).status_code == 422
    # 时长由曲目的排练方案决定(第一首是 2 场 × 2h),改成 3h 会被拒绝
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": target, "start_slot": 2, "duration_slots": 3})
    assert r.status_code == 422, r.text
    print("DURATION-422:", r.json()["detail"])


def test_editing_published_version_forks_a_draft(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 200
    d = _detail(admin, vid)
    s = next(x for x in d["sessions"] if x["kind"] == "formal")
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/lock", json={"locked": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["forked"] is True and body["version"]["id"] != vid and body["version"]["parent_version_id"] == vid
    assert body["version"]["version_no"] == 2 and body["version"]["status"] == "draft" and body["version"]["locked_count"] == 1
    # 原版本原封不动、仍是发布状态
    orig = _detail(admin, vid)
    assert orig["status"] == "published" and all(not x["locked"] for x in orig["sessions"])
    # 再改草稿 → 原地
    draft_id = body["version"]["id"]
    ds = next(x for x in body["version"]["sessions"] if x["locked"])
    r2 = admin.post(f"/api/schedules/{draft_id}/sessions/{ds['id']}/move", json={"date": ds["date"], "start_slot": ds["start_slot"]})
    assert r2.status_code == 422 and "锁定" in r2.json()["detail"]
    assert admin.post(f"/api/schedules/{draft_id}/sessions/{ds['id']}/lock", json={"locked": False}).json()["forked"] is False


def test_lock_and_resolve_keeps_locked_session(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = next(x for x in d["sessions"] if x["kind"] == "formal")
    # 先把它挪到一个明显不优的位置并锁定
    target = _free_day(d)
    moved = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": target, "start_slot": 11}).json()["version"]
    ms = next(x for x in moved["sessions"] if x["id"] == s["id"])
    admin.post(f"/api/schedules/{vid}/sessions/{ms['id']}/lock", json={"locked": True})
    job = admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": vid}).json()
    assert job["status"] == "succeeded", job
    assert job["base_version_id"] == vid
    new = _detail(admin, job["version_id"])
    assert new["source"] == "resolve" and new["parent_version_id"] == vid
    kept = [
        x
        for x in new["sessions"]
        if x["kind"] == "formal" and x["song_code"] == s["song_code"] and x["date"] == target and x["start_slot"] == 11
    ]
    assert len(kept) == 1 and kept[0]["locked"] is True and new["locked_count"] == 1
    assert new["validation_errors"] == []
    # 基准版本不存在 → 404
    assert admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": 999}).status_code == 404


def test_diff_between_versions(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    assert admin.get(f"/api/schedules/{vid}/diff").status_code == 404  # 只有一个版本
    admin.post(f"/api/schedules/{vid}/publish")
    d = _detail(admin, vid)
    s = next(x for x in d["sessions"] if x["kind"] == "formal")
    forked = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": _free_day(d), "start_slot": 3}).json()["version"]
    diff = admin.get(f"/api/schedules/{forked['id']}/diff").json()  # 默认与父版本(v1)比
    assert diff["against_id"] == vid and diff["base_id"] == forked["id"]
    assert [i["change"] for i in diff["items"]] == ["moved"]
    assert diff["items"][0]["before"]["date"] == s["date"] and diff["items"][0]["after"]["start_slot"] == 3
    assert {m["display_name"] for m in diff["affected_members"]} == {m["display_name"] for m in s["members"]}
    assert diff["summary"].startswith("1 场移动")
    assert admin.get(f"/api/schedules/{forked['id']}/diff", params={"against": 999}).status_code == 404
    same = admin.get(f"/api/schedules/{vid}/diff", params={"against": vid}).json()
    assert same["items"] == [] and "完全相同" in same["summary"]


def test_conflicts_after_availability_change(app, admin: TestClient):
    ev, (a, b, c), vid, member_c = _solved_event(app, admin)
    admin.post(f"/api/schedules/{vid}/publish")
    e = admin.get(f"/api/events/{ev['id']}").json()
    assert e["conflict_count"] == 0
    assert admin.get(f"/api/events/{ev['id']}/schedule/conflicts").json()["items"] == []
    # C 把自己参加的那场所在日改成全天没空
    d = _detail(admin, vid)
    s = next(x for x in d["sessions"] if x["kind"] == "formal" and any(m["id"] == c["id"] for m in x["members"]))
    r = member_c.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": {s["date"]: "0" * 13}, "submit": True})
    assert r.status_code == 200
    conflicts = admin.get(f"/api/events/{ev['id']}/schedule/conflicts").json()
    assert conflicts["version_id"] == vid and conflicts["status"] == "published"
    assert [(i["member"]["display_name"], i["session"]["id"]) for i in conflicts["items"]] == [("C", s["id"])]
    assert len(conflicts["items"][0]["hours"]) == s["duration_slots"]
    assert conflicts["members"] == [{"id": c["id"], "display_name": "C"}]
    e = admin.get(f"/api/events/{ev['id']}").json()
    assert e["conflict_count"] == 1 and "1 场与最新空闲冲突" in e["steps"][6]["summary"]
    # 成员看不到冲突接口
    assert member_c.get(f"/api/events/{ev['id']}/schedule/conflicts").status_code == 403
