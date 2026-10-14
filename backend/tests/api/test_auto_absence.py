"""拖动 / 调整后自动显示谁会缺席:参演成员在新时段没空就记为缺席(撤销一起恢复),按演出设置的缺席规则检查。"""

from fastapi.testclient import TestClient

from tests.api.test_edit import _detail, _free_day
from tests.api.test_schedule import _solved_event


def _formal(d: dict) -> list[dict]:
    return [x for x in d["sessions"] if x["kind"] == "formal"]


def _allow_absence(admin: TestClient, ev: dict, percent: int = 50) -> None:
    settings = admin.get(f"/api/events/{ev['id']}").json()["settings"]
    assert admin.patch(f"/api/events/{ev['id']}", json={"settings": {**settings, "max_absent_percent": percent}}).status_code == 200


def _busy(admin: TestClient, ev: dict, member: dict, day: str) -> None:
    admin.put(f"/api/events/{ev['id']}/availability/{member['id']}", json={"days": {day: "0" * 13}, "submit": True})


def _session(v: dict, uid: str) -> dict:
    return next(x for x in v["sessions"] if x["uid"] == uid)


def test_moving_marks_unavailable_members_absent_and_back_again(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev)  # 3 场里允许 1 场有人缺席
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")  # A、B
    target = _free_day(d)
    _busy(admin, ev, a, target)
    r = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 0})
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    moved = _session(v, s["uid"])
    assert [m["id"] for m in moved["absent"]] == [a["id"]]
    assert r.json()["new_issues"] == [] and v["issues"] == []  # 在演出设置允许的范围内,不算冲突
    assert "缺 A" in v["history"][0]["summary"]
    # 拖回 A 有空的时段 → A 又能来了
    v = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": s["date"], "start_slot": s["start_slot"]}).json()[
        "version"
    ]
    assert _session(v, s["uid"])["absent"] == []
    # 撤销 → 回到挪过去的状态,A 缺席也一起恢复;再撤销 → 原样
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    assert [m["id"] for m in _session(v, s["uid"])["absent"]] == [a["id"]]
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    assert _session(v, s["uid"])["absent"] == [] and _session(v, s["uid"])["date"] == s["date"]


def test_two_people_away_is_still_a_conflict_and_resize_recomputes(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    target = _free_day(d)
    _busy(admin, ev, a, target)
    _busy(admin, ev, b, target)
    r = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 0}).json()
    assert sorted(m["id"] for m in _session(r["version"], s["uid"])["absent"]) == sorted([a["id"], b["id"]])
    assert any("每场最多缺 1 人" in x for x in r["new_issues"])
    # 只有下午 B 没空:把一场从上午拉长到下午 → B 记为缺席
    s2 = next(x for x in _formal(d) if x["song_name"] == "第一首" and x["uid"] != s["uid"])
    day2 = s2["date"]
    admin.put(f"/api/events/{ev['id']}/availability/{b['id']}", json={"days": {day2: "1" * 6 + "0" * 7}, "submit": True})
    admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s2["id"], "date": day2, "start_slot": 0})
    v = admin.post(f"/api/schedules/{vid}/ops/resize", json={"session_id": s2["id"], "start_slot": 0, "duration_slots": 8}).json()[
        "version"
    ]
    assert [m["id"] for m in _session(v, s2["uid"])["absent"]] == [b["id"]]


def test_unsubmitted_members_are_not_marked_absent_and_planned_absence_is_kept(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")  # B、C
    # C 有「第二首最多参加 0 场」的要求 → 新建的第二首场次里 C 是计划内缺席;挪到 C 有空的时段也保留
    r = admin.post(
        f"/api/events/{ev['id']}/rules",
        json={"type": "member_song_max_attendance", "params": {"member_id": c["id"], "song_id": second["song_id"], "n": 0}},
    )
    assert r.status_code in (200, 201), r.text
    add = admin.post(
        f"/api/schedules/{vid}/ops/add", json={"song_id": second["song_id"], "date": _free_day(d), "start_slot": 0, "duration_slots": 2}
    ).json()
    new = next(x for x in add["version"]["sessions"] if x["uid"] not in {y["uid"] for y in d["sessions"]})
    assert [m["id"] for m in new["absent"]] == [c["id"]]
    v = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": new["id"], "date": new["date"], "start_slot": 3}).json()["version"]
    assert [m["id"] for m in _session(v, new["uid"])["absent"]] == [c["id"]]
    # B 还没提交空闲(撤回提交):不知道有没有空,不记缺席
    with admin.app.state.session_factory() as db:
        from app.models import EventMember

        row = db.query(EventMember).filter_by(event_id=ev["id"], member_id=b["id"]).one()
        row.availability_submitted_at = None
        db.commit()
    v = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": new["id"], "date": new["date"], "start_slot": 5}).json()["version"]
    assert [m["id"] for m in _session(v, new["uid"])["absent"]] == [c["id"]]


def test_batch_moves_from_ai_or_reoptimize_also_recompute_absence(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    target = _free_day(d)
    _busy(admin, ev, a, target)
    p = admin.post(f"/api/schedules/{vid}/ops/preview", json={"ops": [{"op": "move", "uid": s["uid"], "date": target, "start_slot": 0}]})
    assert p.status_code == 200 and p.json()["issues"] == []
    v = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": [{"op": "move", "uid": s["uid"], "date": target, "start_slot": 0}]})
    assert [m["id"] for m in _session(v.json()["version"], s["uid"])["absent"]] == [a["id"]]
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    assert _session(v, s["uid"])["absent"] == []


# ---------- 审查发现的问题(回归) ----------
def test_reoptimize_can_fix_an_absence_created_by_dragging(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)  # 默认设置:3 场里一场也不能缺
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    target = _free_day(d)
    _busy(admin, ev, a, target)
    v = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 0}).json()["version"]
    assert v["issues"] and [m["id"] for m in _session(v, s["uid"])["absent"]] == [a["id"]]
    assert v["level_used"] and v["level_used"] > 0  # 有计划外缺席,不再是「全员到齐」那一层
    p = admin.post(f"/api/schedules/{vid}/reoptimize").json()
    assert p["status"] == "ok" and [o["uid"] for o in p["ops"]] == [s["uid"]], p
    assert p["preview"]["issues"] == []
    v = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": p["ops"], "expected_revision": p["revision"]}).json()["version"]
    assert v["issues"] == [] and _session(v, s["uid"])["absent"] == [] and v["level_used"] == 0


def test_two_absent_counts_as_one_session_and_reoptimize_moves_it(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    target = _free_day(d)
    _busy(admin, ev, a, target)
    _busy(admin, ev, b, target)
    v = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 0}).json()["version"]
    msgs = [i["message"] for i in v["issues"]]
    assert any("每场最多缺 1 人" in m for m in msgs) and not any("共 2 场" in m for m in msgs)  # 缺 2 人的一场只算一场
    p = admin.post(f"/api/schedules/{vid}/reoptimize").json()
    assert p["status"] == "ok" and p["preview"]["issues"] == []


def test_legacy_move_accepts_moving_an_auto_absent_session_to_a_free_slot(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    target = _free_day(d)
    _busy(admin, ev, a, target)
    admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 0})
    # 旧版 App:移回大家都有空的原位 → 允许,缺席清掉
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": s["date"], "start_slot": s["start_slot"]})
    assert r.status_code == 200, r.text
    assert _session(r.json()["version"], s["uid"])["absent"] == []
    # 旧版 App:移到 A 没空的时段 → 仍然拒绝(旧规则)
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": target, "start_slot": 0})
    assert r.status_code == 422


def test_locked_session_with_two_absent_fails_resolve_clearly(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    target = _free_day(d)
    _busy(admin, ev, a, target)
    _busy(admin, ev, b, target)
    admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 0})
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": s["id"], "locked": True})
    job = admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": vid}).json()
    assert job["status"] == "failed" and "锁定的场次本身有冲突" in job["error"] and "一场最多缺 1 人" in job["error"], job


def test_preview_lines_say_who_will_be_absent(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    target = _free_day(d)
    _busy(admin, ev, a, target)
    p = admin.post(f"/api/schedules/{vid}/ops/preview", json={"ops": [{"op": "move", "uid": s["uid"], "date": target, "start_slot": 0}]})
    assert p.status_code == 200 and "缺 A" in p.json()["lines"][0]


def test_locked_absence_over_settings_fails_resolve_clearly(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev, 60)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")  # 第二首只有 1 场:要全员到齐
    target = _free_day(d)
    _busy(admin, ev, c, target)
    admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": second["id"], "date": target, "start_slot": 0})
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": second["id"], "locked": True})
    job = admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": vid}).json()
    assert job["status"] == "failed" and "锁定的场次本身有冲突" in job["error"] and "全员到齐" in job["error"], job


def test_legacy_move_that_reduces_absence_count_is_accepted(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    _allow_absence(admin, ev)  # 3 场里最多 1 场有人缺席
    d = _detail(admin, vid)
    firsts = [x for x in _formal(d) if x["song_name"] == "第一首"]
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")
    used = {x["date"] for x in d["sessions"]}
    free = [day for day in ("2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08") if day not in used]
    # 网页上拖出 2 场缺席(超过上限 1)
    _busy(admin, ev, a, free[0])
    _busy(admin, ev, c, free[1])
    admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": firsts[0]["id"], "date": free[0], "start_slot": 0})
    admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": second["id"], "date": free[1], "start_slot": 0})
    assert any("超过演出设置允许" in i["message"] for i in _detail(admin, vid)["issues"])
    # 旧版 App 把其中一场移回大家都有空的原位:缺席变少,应当允许
    r = admin.post(
        f"/api/schedules/{vid}/sessions/{firsts[0]['id']}/move", json={"date": firsts[0]["date"], "start_slot": firsts[0]["start_slot"]}
    )
    assert r.status_code == 200, r.text
