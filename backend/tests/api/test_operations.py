"""第一步:手动修改排练表——冲突标出不拒绝、交换、撤销 / 重做、修改次数核对、恢复历史版本、发布门槛。"""

from fastapi.testclient import TestClient

from tests.api.test_edit import _detail, _free_day
from tests.api.test_schedule import _solved_event


def _formal(d: dict) -> list[dict]:
    return [x for x in d["sessions"] if x["kind"] == "formal"]


def test_move_with_conflict_is_kept_marked_and_blocks_publish(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    assert d["revision"] == 0 and d["issues"] == [] and d["can_undo"] is False
    s = _formal(d)[0]
    # 让一位参演成员在某天没空,再把这场拖过去:草稿保留修改,冲突标出(不拒绝)
    who = s["members"][0]
    target = _free_day(d)
    admin.put(f"/api/events/{ev['id']}/availability/{who['id']}", json={"days": {target: "0" * 13}, "submit": True})
    r = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 2, "expected_revision": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    v = body["version"]
    moved = next(x for x in v["sessions"] if x["id"] == s["id"])
    assert moved["date"] == target and v["revision"] == 1
    # 拖过去后没空的人自动记为缺席;这个小例子只有 3 场,按默认设置(25%)一场也不能缺 → 仍算冲突
    assert [m["id"] for m in moved["absent"]] == [who["id"]]
    assert body["new_issues"] and "缺席" in body["new_issues"][0] and "演出设置" in body["new_issues"][0]
    assert [i["session_ids"] for i in v["issues"]] == [[s["id"]]] and not v["issues"][0]["message"].startswith("V-")
    assert v["validation_errors"] and v["can_undo"] is True and v["history"][0]["kind"] == "move"
    # 有冲突不能发布
    r = admin.post(f"/api/schedules/{vid}/publish", json={"expected_revision": 1})
    assert r.status_code == 422 and "冲突" in r.json()["detail"]

    # 撤销 → 回到原位、冲突消失、可以重做;重做 → 冲突回来
    r = admin.post(f"/api/schedules/{vid}/undo", json={"expected_revision": 1}).json()
    back = next(x for x in r["version"]["sessions"] if x["id"] == s["id"])
    assert (back["date"], back["start_slot"]) == (s["date"], s["start_slot"]) and r["version"]["issues"] == []
    assert back["absent"] == s["absent"]  # 缺席也一起恢复
    assert r["version"]["can_undo"] is False and r["version"]["can_redo"] is True and r["warnings"][0].startswith("已撤销")
    r = admin.post(f"/api/schedules/{vid}/redo", json={"expected_revision": 2}).json()
    assert r["version"]["issues"] and r["version"]["revision"] == 3
    # 再撤销 → 可发布
    admin.post(f"/api/schedules/{vid}/undo", json={})
    assert admin.post(f"/api/schedules/{vid}/publish", json={"expected_revision": 4}).status_code == 200


def test_stale_revision_is_rejected(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = _formal(d)[0]
    target = _free_day(d)
    assert (
        admin.post(
            f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 1, "expected_revision": 0}
        ).status_code
        == 200
    )
    # 另一个窗口还拿着修改前的版本号 → 409,不会覆盖
    r = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 5, "expected_revision": 0})
    assert r.status_code == 409 and "刚被修改过" in r.json()["detail"]
    assert next(x for x in _detail(admin, vid)["sessions"] if x["id"] == s["id"])["start_slot"] == 1
    assert admin.post(f"/api/schedules/{vid}/publish", json={"expected_revision": 0}).status_code == 409


def test_swap_two_sessions_and_new_edit_clears_redo(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    fs = _formal(d)
    # 挑两场换过去都不超出每日窗口的(求解结果可能因多线程略有不同)
    a, b = next(
        (x, y)
        for x in fs
        for y in fs
        if x["id"] != y["id"] and x["start_slot"] + y["duration_slots"] <= 13 and y["start_slot"] + x["duration_slots"] <= 13
    )
    r = admin.post(f"/api/schedules/{vid}/ops/swap", json={"a": a["id"], "b": b["id"]})
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    na, nb = (next(x for x in v["sessions"] if x["id"] == i) for i in (a["id"], b["id"]))
    assert (na["date"], na["start_slot"]) == (b["date"], b["start_slot"]) and (nb["date"], nb["start_slot"]) == (a["date"], a["start_slot"])
    assert na["duration_slots"] == a["duration_slots"] and v["history"][0]["kind"] == "swap" and "交换" in v["history"][0]["summary"]
    # 撤销一次交换 → 两场都回原位
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    assert {(x["id"], x["date"], x["start_slot"]) for x in v["sessions"] if x["id"] in (a["id"], b["id"])} == {
        (a["id"], a["date"], a["start_slot"]),
        (b["id"], b["date"], b["start_slot"]),
    }
    # 撤销后做了新修改 → 不能再重做
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": a["id"], "locked": True})
    v = _detail(admin, vid)
    assert v["can_redo"] is False and [h["kind"] for h in v["history"]] == ["lock"]
    # 锁定的场次不能交换 / 移动;评估场不能交换;不能和自己交换
    assert admin.post(f"/api/schedules/{vid}/ops/swap", json={"a": a["id"], "b": b["id"]}).status_code == 422
    ev_s = next(x for x in d["sessions"] if x["kind"] == "evaluation")
    assert admin.post(f"/api/schedules/{vid}/ops/swap", json={"a": b["id"], "b": ev_s["id"]}).status_code == 422
    assert admin.post(f"/api/schedules/{vid}/ops/swap", json={"a": b["id"], "b": b["id"]}).status_code == 422


def test_editing_published_forks_and_restore_history(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 200
    d = _detail(admin, vid)
    s = _formal(d)[0]
    target = _free_day(d)
    # 改已发布版 → 复制成草稿再改;原版不动;已发布版不能撤销
    r = admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": s["id"], "date": target, "start_slot": 3}).json()
    assert r["forked"] is True and r["version"]["status"] == "draft" and r["version"]["parent_version_id"] == vid
    draft = r["version"]
    assert (
        _detail(admin, vid)["status"] == "published"
        and next(x for x in _detail(admin, vid)["sessions"] if x["id"] == s["id"])["date"] == s["date"]
    )
    assert admin.post(f"/api/schedules/{vid}/undo", json={}).status_code == 409
    assert draft["can_undo"] is True
    # 从历史版本(已发布的 v1)恢复一个新草稿:内容与 v1 相同,原版本仍不变
    r = admin.post(f"/api/schedules/{vid}/fork")
    assert r.status_code == 201
    restored = r.json()["version"]
    assert restored["status"] == "draft" and restored["source"] == "copy" and restored["parent_version_id"] == vid
    assert sorted((x["date"], x["start_slot"]) for x in restored["sessions"]) == sorted((x["date"], x["start_slot"]) for x in d["sessions"])
    assert restored["history"] == [] and restored["revision"] == 0


def test_old_move_endpoint_still_rejects_conflicts(app, admin: TestClient):
    """iOS App 1.0 用的旧接口保持原样:新引入冲突时拒绝,且不留下复制出来的草稿。"""
    ev, _, vid, _ = _solved_event(app, admin)
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 200
    d = _detail(admin, vid)
    s = _formal(d)[0]
    target = _free_day(d)
    admin.put(f"/api/events/{ev['id']}/availability/{s['members'][0]['id']}", json={"days": {target: "0" * 13}, "submit": True})
    before = len(admin.get(f"/api/events/{ev['id']}/schedules").json())
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/move", json={"date": target, "start_slot": 2})
    assert r.status_code == 422 and "不能这样改" in r.json()["detail"]
    assert len(admin.get(f"/api/events/{ev['id']}/schedules").json()) == before


# ---------- 像日历一样:上下拉调整时长、新建、删除 ----------
def _song_id(admin: TestClient, ev: dict, name: str) -> int:
    return next(s["id"] for s in admin.get(f"/api/events/{ev['id']}/songs").json()["songs"] if s["name"] == name)


def test_resize_by_hour_is_saved_noted_and_undoable(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")  # 方案 2 场 × 2h
    end = s["start_slot"] + s["duration_slots"]
    start = s["start_slot"] - 1 if s["start_slot"] > 0 else s["start_slot"]
    # 向上拉 1 小时(或在最早时段时向下拉):时长 2h → 3h,保存;与方案不同只作提醒,不挡发布
    new_dur = end - start if start != s["start_slot"] else s["duration_slots"] + 1
    r = admin.post(
        f"/api/schedules/{vid}/ops/resize",
        json={"session_id": s["id"], "start_slot": start, "duration_slots": new_dur, "expected_revision": 0},
    )
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    got = next(x for x in v["sessions"] if x["id"] == s["id"])
    assert (got["start_slot"], got["duration_slots"]) == (start, 3)
    assert v["history"][0]["kind"] == "resize" and "2h → 3h" in v["history"][0]["summary"]
    assert any("时长不同" in n for n in v["notices"]) and not any("第一首" in i["message"] and "方案" in i["message"] for i in v["issues"])
    # 撤销 → 回到 2h
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    got = next(x for x in v["sessions"] if x["id"] == s["id"])
    assert (got["start_slot"], got["duration_slots"]) == (s["start_slot"], 2) and v["notices"] == []
    # 时长至少 1 小时、不能超出每日窗口;没变化时拒绝
    bad = [(s["start_slot"], 0), (s["start_slot"], 99), (s["start_slot"], s["duration_slots"])]
    for st, du in bad:
        assert (
            admin.post(f"/api/schedules/{vid}/ops/resize", json={"session_id": s["id"], "start_slot": st, "duration_slots": du}).status_code
            == 422
        )


def test_add_and_delete_sessions_like_a_calendar(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    target = _free_day(d)
    song_id = _song_id(admin, ev, "第二首")  # 方案 1 场 × 3h
    # 新建一场 → 第二首变成 2 场:提醒「多 1 场」,不挡发布
    r = admin.post(f"/api/schedules/{vid}/ops/add", json={"song_id": song_id, "date": target, "start_slot": 0, "duration_slots": 2})
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    added = next(x for x in v["sessions"] if x["date"] == target and x["song_name"] == "第二首")
    assert added["task_key"] == 2 and added["duration_slots"] == 2 and v["history"][0]["kind"] == "add"
    # 给人看的「第几场」按日期排序,与固定编号无关
    assert sorted(x["task_no"] for x in v["sessions"] if x["song_name"] == "第二首") == [1, 2]
    assert any("多 1 场" in n for n in v["notices"]) and v["issues"] == []

    # 删除原来那场(先给它填地点、锁定再解锁,看撤销能否原样恢复)
    orig = next(x for x in _formal(d) if x["song_name"] == "第二首")
    admin.post(f"/api/schedules/{vid}/sessions/{orig['id']}/location", json={"location": "三楼排练厅"})
    r = admin.post(f"/api/schedules/{vid}/ops/delete", json={"session_id": orig["id"]})
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    assert all(x["id"] != orig["id"] for x in v["sessions"]) and v["history"][0]["kind"] == "delete"
    # 撤销删除 → 原样恢复(时间、地点、第几场);再撤销新建 → 回到求解结果
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    back = next(x for x in v["sessions"] if x["song_name"] == "第二首" and x["task_key"] == orig["task_key"])
    assert (back["date"], back["start_slot"], back["duration_slots"], back["location"]) == (
        orig["date"],
        orig["start_slot"],
        orig["duration_slots"],
        "三楼排练厅",
    )
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    assert len(_formal(v)) == len(_formal(d)) and v["notices"] == []
    # 重做两次 → 新建的那场回来、原来那场又被删
    admin.post(f"/api/schedules/{vid}/redo", json={})
    v = admin.post(f"/api/schedules/{vid}/redo", json={}).json()["version"]
    secs = [x for x in _formal(v) if x["song_name"] == "第二首"]
    assert [(x["date"], x["task_key"], x["task_no"]) for x in secs] == [(target, 2, 1)]
    # 第二首现在只剩新建的那场:可以发布(场数不同只是提醒)
    assert admin.post(f"/api/schedules/{vid}/publish", json={}).status_code == 200


def test_cannot_delete_locked_or_evaluation_and_old_endpoint_keeps_duration(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = _formal(d)[0]
    ev_s = next(x for x in d["sessions"] if x["kind"] == "evaluation")
    assert admin.post(f"/api/schedules/{vid}/ops/delete", json={"session_id": ev_s["id"]}).status_code == 422
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": s["id"], "locked": True})
    r = admin.post(f"/api/schedules/{vid}/ops/delete", json={"session_id": s["id"]})
    assert r.status_code == 422 and "解锁" in r.json()["detail"]
    # 旧接口(iOS App 1.0)仍不能改时长
    other = _formal(d)[1]
    r = admin.post(
        f"/api/schedules/{vid}/sessions/{other['id']}/move",
        json={"date": other["date"], "start_slot": other["start_slot"], "duration_slots": other["duration_slots"] + 1},
    )
    assert r.status_code == 422 and "时长" in r.json()["detail"]


def test_resolve_keeps_manually_resized_locked_session(app, admin: TestClient):
    """拉长后锁定,再「锁定后重排」:新方案沿用改过的时长,锁定那场原样保留。"""
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    start = s["start_slot"] if s["start_slot"] + 3 <= 13 else s["start_slot"] - 1  # 往窗口内的方向拉长
    r = admin.post(f"/api/schedules/{vid}/ops/resize", json={"session_id": s["id"], "start_slot": start, "duration_slots": 3})
    assert r.status_code == 200, r.text
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": s["id"], "locked": True})
    job = admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": vid}).json()
    assert job["status"] == "succeeded", job
    new = _detail(admin, job["version_id"])
    kept = [x for x in _formal(new) if x["song_name"] == "第一首" and x["locked"]]
    assert [(x["date"], x["start_slot"], x["duration_slots"]) for x in kept] == [(s["date"], start, 3)]


# ---------- 审查发现的问题(回归测试) ----------
def _resolve(admin: TestClient, ev: dict, base_id: int) -> dict:
    return admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": base_id}).json()


def test_resolve_after_adding_and_locking_more_sessions_than_planned(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")  # 方案 1 场 × 3h
    v = admin.post(
        f"/api/schedules/{vid}/ops/add", json={"song_id": second["song_id"], "date": _free_day(d), "start_slot": 0, "duration_slots": 3}
    ).json()["version"]
    for x in _formal(v):
        if x["song_name"] == "第二首":
            admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": x["id"], "locked": True})
    job = _resolve(admin, ev, vid)
    assert job["status"] == "succeeded", job
    new = _detail(admin, job["version_id"])
    assert sorted((x["date"], x["start_slot"]) for x in _formal(new) if x["song_name"] == "第二首") == sorted(
        (x["date"], x["start_slot"]) for x in _formal(v) if x["song_name"] == "第二首"
    )


def test_resolve_after_resize_lock_and_delete(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    a1, a2 = [x for x in _formal(d) if x["song_name"] == "第一首"]  # 方案 2 场 × 2h
    a1_start = a1["start_slot"] if a1["start_slot"] + 3 <= 13 else a1["start_slot"] - 1
    assert (
        admin.post(
            f"/api/schedules/{vid}/ops/resize", json={"session_id": a1["id"], "start_slot": a1_start, "duration_slots": 3}
        ).status_code
        == 200
    )
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": a1["id"], "locked": True})
    admin.post(f"/api/schedules/{vid}/ops/delete", json={"session_id": a2["id"]})
    job = _resolve(admin, ev, vid)
    assert job["status"] == "succeeded", job
    firsts = [x for x in _formal(_detail(admin, job["version_id"])) if x["song_name"] == "第一首"]
    # 锁定的 3h 原样保留;方案里的另一场(2h)按方案重新排上
    assert sorted(x["duration_slots"] for x in firsts) == [2, 3] and any(x["locked"] and x["start_slot"] == a1_start for x in firsts)


def test_resolve_uses_plan_changed_after_solving_for_unlocked_songs(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")
    first = next(x for x in _formal(d) if x["song_name"] == "第一首")
    assert admin.patch(f"/api/songs/{second['song_id']}", json={"session_plan": [2]}).status_code == 200
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": first["id"], "locked": True})
    job = _resolve(admin, ev, vid)
    assert job["status"] == "succeeded", job
    assert [x["duration_slots"] for x in _formal(_detail(admin, job["version_id"])) if x["song_name"] == "第二首"] == [2]


def test_undo_redo_keeps_edits_made_after_the_add(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")
    v = admin.post(
        f"/api/schedules/{vid}/ops/add", json={"song_id": second["song_id"], "date": _free_day(d), "start_slot": 0, "duration_slots": 2}
    ).json()["version"]
    added = next(x for x in _formal(v) if x["task_key"] == 2 and x["song_name"] == "第二首")
    admin.post(f"/api/schedules/{vid}/sessions/{added['id']}/location", json={"location": "三楼排练厅"})
    admin.post(f"/api/schedules/{vid}/undo", json={})
    v = admin.post(f"/api/schedules/{vid}/redo", json={}).json()["version"]
    back = next(x for x in _formal(v) if x["task_key"] == 2 and x["song_name"] == "第二首")
    assert back["location"] == "三楼排练厅"


def test_deleting_a_song_clears_history_instead_of_breaking_undo(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")
    admin.post(f"/api/schedules/{vid}/ops/delete", json={"session_id": second["id"]})
    assert admin.delete(f"/api/songs/{second['song_id']}").status_code == 204
    v = _detail(admin, vid)
    assert v["history"] == [] and v["can_undo"] is False
    assert admin.post(f"/api/schedules/{vid}/undo", json={}).status_code == 409


def test_concurrent_edit_with_same_revision_is_rejected(app, admin: TestClient):
    from fastapi import HTTPException

    from app import operations
    from app.models import ScheduleVersion

    _, _, vid, _ = _solved_event(app, admin)
    with app.state.session_factory() as db1, app.state.session_factory() as db2:
        v1 = db1.get(ScheduleVersion, vid)
        assert v1.revision == 0
        v2 = db2.get(ScheduleVersion, vid)
        operations.claim(db2, v2)  # 另一个请求先改了
        db2.commit()
        try:
            operations.claim(db1, v1)
            raise AssertionError("应当 409")
        except HTTPException as exc:
            assert exc.status_code == 409
    assert _detail(admin, vid)["revision"] == 1


def test_added_session_respects_attendance_cap_rule(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")  # 成员 B、C
    r = admin.post(
        f"/api/events/{ev['id']}/rules",
        json={"type": "member_song_max_attendance", "params": {"member_id": c["id"], "song_id": second["song_id"], "n": 1}},
    )
    assert r.status_code in (200, 201), r.text
    v = admin.post(
        f"/api/schedules/{vid}/ops/add", json={"song_id": second["song_id"], "date": _free_day(d), "start_slot": 0, "duration_slots": 3}
    ).json()["version"]
    added = next(x for x in _formal(v) if x["song_name"] == "第二首" and x["task_key"] == 2)
    assert [m["id"] for m in added["absent"]] == [c["id"]]
    assert not any("出勤" in i["message"] for i in v["issues"])


def test_legacy_operation_records_are_upgraded(app, admin: TestClient):
    from sqlalchemy import text

    from app.db import _migrate_11_to_12

    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = _formal(d)[0]
    engine = app.state.engine
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO schedule_operations (version_id, seq, kind, summary, changes, undone, created_at) "
                "VALUES (:v, 1, 'move', 'x', :c, 0, '2026-10-13 00:00:00')"
            ),
            {"v": vid, "c": f'[{{"session_id": {s["id"]}, "before": {{}}, "after": {{}}}}]'},
        )
    _migrate_11_to_12(engine)
    with engine.begin() as conn:
        raw = conn.execute(text("SELECT changes FROM schedule_operations WHERE version_id = :v"), {"v": vid}).scalar_one()
    assert '"key"' in raw and f'"task_no": {s["task_key"]}' in raw


# ---------- 第二轮复查发现的问题(回归测试) ----------
def test_resolve_keeps_fixed_session_rule_duration(app, admin: TestClient):
    """曲目有「固定场次」要求时,加场并锁定后重排:要求需要的时长不能被换掉。"""
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")  # 方案 [3]
    r = admin.post(
        f"/api/events/{ev['id']}/rules",
        json={
            "type": "fixed_session",
            "params": {"song_id": second["song_id"], "date": second["date"], "start_hour": 10 + second["start_slot"], "duration": 3},
        },
    )
    assert r.status_code in (200, 201), r.text
    v = admin.post(
        f"/api/schedules/{vid}/ops/add", json={"song_id": second["song_id"], "date": _free_day(d), "start_slot": 0, "duration_slots": 1}
    ).json()["version"]
    added = next(x for x in _formal(v) if x["song_name"] == "第二首" and x["duration_slots"] == 1)
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": added["id"], "locked": True})
    job = _resolve(admin, ev, vid)
    assert job["status"] == "succeeded", job
    secs = [x for x in _formal(_detail(admin, job["version_id"])) if x["song_name"] == "第二首"]
    assert sorted(x["duration_slots"] for x in secs) == [1, 3]


def test_resolve_replaces_the_resized_task_not_another(app, admin: TestClient):
    """[3, 2, 2] 把 3h 拉成 4h 并锁定:其余两场仍是 2h,不会把一场 2h 变成 3h。"""
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")
    admin.patch(f"/api/songs/{second['song_id']}", json={"session_plan": [3, 2, 2]})
    job = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    assert job["status"] == "succeeded", job
    vid2 = job["version_id"]
    three = next(x for x in _formal(_detail(admin, vid2)) if x["song_name"] == "第二首" and x["duration_slots"] == 3)
    start = three["start_slot"] if three["start_slot"] + 4 <= 13 else three["start_slot"] - 1
    assert (
        admin.post(
            f"/api/schedules/{vid2}/ops/resize", json={"session_id": three["id"], "start_slot": start, "duration_slots": 4}
        ).status_code
        == 200
    )
    admin.post(f"/api/schedules/{vid2}/ops/lock", json={"session_id": three["id"], "locked": True})
    job = _resolve(admin, ev, vid2)
    assert job["status"] == "succeeded", job
    secs = [x for x in _formal(_detail(admin, job["version_id"])) if x["song_name"] == "第二首"]
    assert sorted(x["duration_slots"] for x in secs) == [2, 2, 4]


def test_resolve_explains_locked_session_conflict(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": s["id"], "locked": True})
    admin.put(f"/api/events/{ev['id']}/availability/{a['id']}", json={"days": {s["date"]: "0" * 13}, "submit": True})
    job = _resolve(admin, ev, vid)
    assert job["status"] == "failed" and "锁定的场次本身有冲突" in job["error"] and "A" in job["error"]


def test_publish_and_edit_cannot_interleave(app, admin: TestClient):
    """发布占用修改次数:读到发布前状态的修改会 409,不会改进已发布的版本。"""
    from fastapi import HTTPException

    from app import operations
    from app.models import ScheduleVersion

    _, _, vid, _ = _solved_event(app, admin)
    with app.state.session_factory() as db_edit:
        stale = db_edit.get(ScheduleVersion, vid)  # 修改请求读到草稿
        assert admin.post(f"/api/schedules/{vid}/publish", json={}).status_code == 200  # 发布先完成
        try:
            operations.claim(db_edit, stale)
            raise AssertionError("应当 409")
        except HTTPException as exc:
            assert exc.status_code == 409
    v = _detail(admin, vid)
    assert v["status"] == "published" and v["history"] == []


def test_location_response_keeps_conflicts(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = _formal(d)[0]
    admin.put(f"/api/events/{ev['id']}/availability/{s['members'][0]['id']}", json={"days": {s["date"]: "0" * 13}, "submit": True})
    r = admin.post(f"/api/schedules/{vid}/sessions/{s['id']}/location", json={"location": "三楼"}).json()
    assert r["version"]["issues"] and r["version"]["validation_errors"]


def test_orphan_sessions_undo_targets_the_right_one(app, admin: TestClient):
    """曲目被删后,剩下的场次身份可能重复:撤销仍要改回被操作的那一场。"""
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    a1 = next(x for x in _formal(d) if x["song_name"] == "第一首" and x["task_key"] == 1)
    b1 = next(x for x in _formal(d) if x["song_name"] == "第二首")
    admin.delete(f"/api/songs/{a1['song_id']}")
    admin.delete(f"/api/songs/{b1['song_id']}")
    target = _free_day(d)
    assert admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": b1["id"], "date": target, "start_slot": 8}).status_code == 200
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    got = {x["id"]: (x["date"], x["start_slot"]) for x in v["sessions"]}
    assert got[b1["id"]] == (b1["date"], b1["start_slot"]) and got[a1["id"]] == (a1["date"], a1["start_slot"])


def test_added_session_never_reuses_a_deleted_number(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    a2 = next(x for x in _formal(d) if x["song_name"] == "第一首" and x["task_key"] == 2)
    admin.post(f"/api/schedules/{vid}/ops/delete", json={"session_id": a2["id"]})
    v = admin.post(
        f"/api/schedules/{vid}/ops/add", json={"song_id": a2["song_id"], "date": _free_day(d), "start_slot": 0, "duration_slots": 2}
    ).json()["version"]
    assert sorted(x["task_key"] for x in _formal(v) if x["song_name"] == "第一首") == [1, 3]
    # 撤销新建、撤销删除 → 原来的第 2 场回来
    admin.post(f"/api/schedules/{vid}/undo", json={})
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    assert sorted(x["task_key"] for x in _formal(v) if x["song_name"] == "第一首") == [1, 2]


# ---------- 最后一轮复查(回归测试) ----------
def test_undo_survives_sqlite_id_reuse(app, admin: TestClient):
    """新建 X、新建 Y、删 X、删 Y,再连撤 4 次:SQLite 会复用刚删掉的 id,撤销仍要恢复正确的场次。"""
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    song = next(x for x in _formal(d) if x["song_name"] == "第二首")["song_id"]
    days = [x for x in ("2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08")]
    ids = []
    for day in days[:2]:
        v = admin.post(f"/api/schedules/{vid}/ops/add", json={"song_id": song, "date": day, "start_slot": 0, "duration_slots": 1}).json()[
            "version"
        ]
        ids.append(next(x["id"] for x in _formal(v) if x["date"] == day and x["start_slot"] == 0 and x["duration_slots"] == 1))
    for sid in ids:
        assert admin.post(f"/api/schedules/{vid}/ops/delete", json={"session_id": sid}).status_code == 200
    for _ in range(4):
        r = admin.post(f"/api/schedules/{vid}/undo", json={})
        assert r.status_code == 200, r.text
    v = r.json()["version"]
    assert sorted((x["date"], x["start_slot"], x["duration_slots"]) for x in _formal(v)) == sorted(
        (x["date"], x["start_slot"], x["duration_slots"]) for x in _formal(d)
    )


def test_resolve_precheck_ignores_count_based_issues_and_skipped_songs(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")
    # 锁定第二首,然后让 C 退回未提交 → 「只排已就绪」会跳过第二首,它的锁定场次不参与、也不报冲突
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": second["id"], "locked": True})
    admin.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": {second["date"]: "0" * 13}, "submit": True})
    admin.post(f"/api/events/{ev['id']}/availability/{c['id']}/unsubmit")
    job = admin.post(f"/api/events/{ev['id']}/solve", json={"base_version_id": vid, "only_ready_songs": True}).json()
    assert job["status"] != "failed" or "锁定的场次本身有冲突" not in (job.get("error") or ""), job


def test_resolve_keeps_resize_to_a_duration_already_in_plan(app, admin: TestClient):
    """方案 [3, 2]:把 2h 那场拉成 3h 并锁定,重排后应为 3h + 3h(不能被悄悄改回)。"""
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")
    admin.patch(f"/api/songs/{second['song_id']}", json={"session_plan": [3, 2]})
    job = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    assert job["status"] == "succeeded", job
    vid2 = job["version_id"]
    two = next(x for x in _formal(_detail(admin, vid2)) if x["song_name"] == "第二首" and x["duration_slots"] == 2)
    start = two["start_slot"] if two["start_slot"] + 3 <= 13 else two["start_slot"] - 1
    assert (
        admin.post(
            f"/api/schedules/{vid2}/ops/resize", json={"session_id": two["id"], "start_slot": start, "duration_slots": 3}
        ).status_code
        == 200
    )
    admin.post(f"/api/schedules/{vid2}/ops/lock", json={"session_id": two["id"], "locked": True})
    job = _resolve(admin, ev, vid2)
    assert job["status"] == "succeeded", job
    assert sorted(x["duration_slots"] for x in _formal(_detail(admin, job["version_id"])) if x["song_name"] == "第二首") == [3, 3]


def test_swap_of_identical_slots_is_rejected(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    a = _formal(d)[0]
    second = next(x for x in _formal(d) if x["id"] != a["id"])
    # 让第二场与第一场同一时间(会冲突,但草稿允许),再交换 → 无意义,拒绝
    admin.post(f"/api/schedules/{vid}/ops/move", json={"session_id": second["id"], "date": a["date"], "start_slot": a["start_slot"]})
    r = admin.post(f"/api/schedules/{vid}/ops/swap", json={"a": a["id"], "b": second["id"]})
    assert r.status_code == 422 and "相同" in r.json()["detail"]
