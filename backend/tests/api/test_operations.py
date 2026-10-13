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
    assert body["new_issues"] and who["display_name"] in body["new_issues"][0] and "不可用" in body["new_issues"][0]
    assert [i["session_ids"] for i in v["issues"]] == [[s["id"]]] and not v["issues"][0]["message"].startswith("V-")
    assert v["validation_errors"] and v["can_undo"] is True and v["history"][0]["kind"] == "move"
    # 有冲突不能发布
    r = admin.post(f"/api/schedules/{vid}/publish", json={"expected_revision": 1})
    assert r.status_code == 422 and "冲突" in r.json()["detail"]

    # 撤销 → 回到原位、冲突消失、可以重做;重做 → 冲突回来
    r = admin.post(f"/api/schedules/{vid}/undo", json={"expected_revision": 1}).json()
    back = next(x for x in r["version"]["sessions"] if x["id"] == s["id"])
    assert (back["date"], back["start_slot"]) == (s["date"], s["start_slot"]) and r["version"]["issues"] == []
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
    a, b = _formal(d)[:2]
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
