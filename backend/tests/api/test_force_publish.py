"""有冲突的排练表:默认不能发布;管理员看过全部冲突并确认后,可以带着冲突发布(记下当时的冲突、说明、操作人)。"""

from fastapi.testclient import TestClient

from tests.api.test_edit import _detail
from tests.api.test_schedule import _solved_event


def _make_conflict(admin: TestClient, ev: dict, member: dict, day: str) -> None:
    admin.put(f"/api/events/{ev['id']}/availability/{member['id']}", json={"days": {day: "0" * 13}, "submit": True})


def test_force_publish_needs_confirmation_of_every_current_issue(app, admin: TestClient):
    ev, (a, b, c), vid, member_c = _solved_event(app, admin)
    d = _detail(admin, vid)
    first = next(x for x in d["sessions"] if x["kind"] == "formal" and x["song_name"] == "第一首")
    _make_conflict(admin, ev, a, first["date"])
    d = _detail(admin, vid)
    issues = [i["message"] for i in d["issues"]]
    assert issues

    # 不确认:照旧不能发布(旧客户端不带参数也一样)
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 422
    assert admin.post(f"/api/schedules/{vid}/publish", json={"expected_revision": d["revision"]}).status_code == 422
    # 确认了但没列出全部冲突 → 409,要重新确认
    r = admin.post(f"/api/schedules/{vid}/publish", json={"force": True, "acknowledged_issues": issues[:-1]})
    assert r.status_code == 409

    # 确认之后、发布之前又冒出新冲突(另一位成员改了空闲)→ 409
    second = next(x for x in d["sessions"] if x["kind"] == "formal" and x["song_name"] == "第二首")
    _make_conflict(admin, ev, c, second["date"])
    r = admin.post(f"/api/schedules/{vid}/publish", json={"force": True, "acknowledged_issues": issues, "expected_revision": d["revision"]})
    assert r.status_code == 409 and "重新确认" in r.json()["detail"]

    # 看过全部冲突再确认 → 发布成功,记下冲突、说明、操作人
    d = _detail(admin, vid)
    now = [i["message"] for i in d["issues"]]
    body = {"force": True, "acknowledged_issues": now, "note": "A 那天会晚到,已当面确认", "expected_revision": d["revision"]}
    r = admin.post(f"/api/schedules/{vid}/publish", json=body)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["status"] == "published"
    fp = v["forced_publish"]
    assert fp["issues"] == now and fp["note"] == "A 那天会晚到,已当面确认" and fp["by_name"] and fp["at"]
    assert _detail(admin, vid)["forced_publish"]["issues"] == now

    # 成员看得到排练表,但看不到冲突说明(里面有其他人的空闲情况)
    pub = member_c.get(f"/api/events/{ev['id']}/schedule/published").json()
    assert pub["version_no"] == v["version_no"] and pub["forced_publish"] is None and pub["validation_errors"] == []
    assert admin.get(f"/api/events/{ev['id']}/schedule/published").json()["forced_publish"]["issues"] == now

    # 撤回发布 → 记录清掉;没有冲突时即使带 force 也是正常发布
    assert admin.post(f"/api/schedules/{vid}/unpublish").json()["forced_publish"] is None


def test_force_flag_without_conflicts_is_a_normal_publish(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    r = admin.post(f"/api/schedules/{vid}/publish", json={"force": True, "acknowledged_issues": []})
    assert r.status_code == 200 and r.json()["forced_publish"] is None


def test_force_publish_still_checks_revision_and_archives_previous(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 200
    fork = admin.post(f"/api/schedules/{vid}/fork").json()["version"]
    first = next(x for x in fork["sessions"] if x["kind"] == "formal")
    _make_conflict(admin, ev, a, first["date"])
    d = _detail(admin, fork["id"])
    issues = [i["message"] for i in d["issues"]]
    body = {"force": True, "acknowledged_issues": issues, "expected_revision": d["revision"] + 5}
    assert admin.post(f"/api/schedules/{fork['id']}/publish", json=body).status_code == 409  # 修改次数对不上
    r = admin.post(f"/api/schedules/{fork['id']}/publish", json={**body, "expected_revision": d["revision"]})
    assert r.status_code == 200, r.text
    assert _detail(admin, vid)["status"] == "archived"  # 之前发布的那版照常归档


def _conflict_notes(admin: TestClient) -> list[dict]:
    return [n for n in admin.get("/api/notifications").json() if n["type"] == "conflict"]


def test_accepted_conflicts_are_not_reported_again_and_old_clients_see_no_errors(app, admin: TestClient):
    ev, (a, b, c), vid, member_c = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in d["sessions"] if x["kind"] == "formal" and x["song_name"] == "第二首")
    # C 本人把第二首那天改成没空(还没发布,不提醒),管理员确认后带冲突发布
    member_c.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": {second["date"]: "0" * 13}, "submit": True})
    d = _detail(admin, vid)
    issues = [i["message"] for i in d["issues"]]
    assert issues
    r = admin.post(f"/api/schedules/{vid}/publish", json={"force": True, "acknowledged_issues": issues + issues})  # 重复的也接受
    assert r.status_code == 200, r.text
    assert r.json()["forced_publish"]["accepted"]
    # 旧版 App 按 validation_errors 显示「校验未通过,不能发布」:带冲突发布的版本不再返回这些
    listed = next(v for v in admin.get(f"/api/events/{ev['id']}/schedules").json() if v["id"] == vid)
    assert listed["validation_errors"] == []
    # 已确认的冲突:工作台不再算作「与最新空闲冲突」,冲突列表里也没有
    assert admin.get(f"/api/events/{ev['id']}").json()["conflict_count"] == 0
    assert admin.get(f"/api/events/{ev['id']}/schedule/conflicts").json()["items"] == []

    # C 改了别的日子再提交:不提醒已确认过的冲突
    other = next(day for day in ("2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08") if day != second["date"])
    member_c.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": {other: "1" * 13}, "submit": True})
    assert _conflict_notes(admin) == []

    # C 在另一场(评估场)也没空了:这是新冲突,照常提醒(只提这一场,不提已确认的)
    member_c.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": {"2026-09-09": "0" * 13}, "submit": True})
    notes = _conflict_notes(admin)
    assert len(notes) == 1 and "C 修改了空闲,1 场受影响" in notes[0]["title"] and "评估" in notes[0]["body"]
    assert admin.get(f"/api/events/{ev['id']}").json()["conflict_count"] == 1
    # 先恢复,再「存草稿 → 提交」制造同样的冲突:照常提醒(不能因为草稿已写入就漏掉)
    member_c.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": {"2026-09-09": "1" * 13}, "submit": True})
    before = len(_conflict_notes(admin))
    member_c.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": {"2026-09-09": "0" * 13}, "submit": False})
    member_c.post(f"/api/events/{ev['id']}/availability/{c['id']}/submit")
    assert len(_conflict_notes(admin)) == before + 1

    # 之后有新版本正常发布、这一版归档:旧版 App 又能看到它的校验错误(不会以为可以直接再发布)
    listed = next(v for v in admin.get(f"/api/events/{ev['id']}/schedules").json() if v["id"] == vid)
    assert listed["status"] == "published" and listed["validation_errors"] == []


def test_archived_forced_version_reports_its_errors_again(app, admin: TestClient):
    ev, (a, b, c), vid, member_c = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in d["sessions"] if x["kind"] == "formal" and x["song_name"] == "第二首")
    member_c.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": {second["date"]: "0" * 13}, "submit": True})
    issues = [i["message"] for i in _detail(admin, vid)["issues"]]
    assert admin.post(f"/api/schedules/{vid}/publish", json={"force": True, "acknowledged_issues": issues}).status_code == 200
    # 另一版正常发布 → 这一版归档;旧版 App 据 validation_errors 判断能否直接发布,要看到错误
    job = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    assert job["status"] == "succeeded", job
    assert admin.post(f"/api/schedules/{job['version_id']}/publish").status_code == 200
    listed = next(v for v in admin.get(f"/api/events/{ev['id']}/schedules").json() if v["id"] == vid)
    assert listed["status"] == "archived" and listed["validation_errors"]
