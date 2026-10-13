"""第二步:一组修改的试算与一次应用(AI 修改、少改动重排共用)。"""

import json

from fastapi.testclient import TestClient

from tests.api.test_edit import _detail, _free_day
from tests.api.test_schedule import _solved_event


def _formal(d: dict) -> list[dict]:
    return [x for x in d["sessions"] if x["kind"] == "formal"]


def test_preview_does_not_change_anything_and_batch_is_one_undo(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s1, s2 = _formal(d)[:2]
    target = _free_day(d)
    second_song = next(x for x in _formal(d) if x["song_name"] == "第二首")["song_id"]
    ops = [
        {"op": "move", "uid": s1["uid"], "date": target, "start_slot": 0},
        {"op": "lock", "uid": s2["uid"], "locked": True},
        {"op": "add", "song_id": second_song, "date": target, "start_slot": 8, "duration_slots": 2},
    ]
    r = admin.post(f"/api/schedules/{vid}/ops/preview", json={"ops": ops})
    assert r.status_code == 200, r.text
    p = r.json()
    assert len(p["lines"]) == 3 and p["lines"][0].startswith("移动") and p["lines"][2].startswith("新建")
    assert any("多 1 场" in n for n in p["notices"])
    after = _detail(admin, vid)
    assert after["revision"] == 0 and after["history"] == [] and len(after["sessions"]) == len(d["sessions"])

    r = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": ops, "summary": "AI:测试", "expected_revision": 0})
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    assert v["revision"] == 1 and [h["kind"] for h in v["history"]] == ["batch"] and v["history"][0]["summary"] == "AI:测试"
    assert len(v["sessions"]) == len(d["sessions"]) + 1
    moved = next(x for x in v["sessions"] if x["uid"] == s1["uid"])
    assert (moved["date"], moved["start_slot"]) == (target, 0)
    assert next(x for x in v["sessions"] if x["uid"] == s2["uid"])["locked"] is True
    # 一次撤销全部回去
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    assert sorted((x["uid"], x["date"], x["start_slot"], x["locked"]) for x in v["sessions"]) == sorted(
        (x["uid"], x["date"], x["start_slot"], x["locked"]) for x in d["sessions"]
    )
    # 重做 → 全部回来
    v = admin.post(f"/api/schedules/{vid}/redo", json={}).json()["version"]
    assert len(v["sessions"]) == len(d["sessions"]) + 1


def test_batch_is_all_or_nothing(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s1 = _formal(d)[0]
    ev_s = next(x for x in d["sessions"] if x["kind"] == "evaluation")
    ops = [{"op": "move", "uid": s1["uid"], "date": _free_day(d), "start_slot": 0}, {"op": "delete", "uid": ev_s["uid"]}]
    r = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": ops})
    assert r.status_code == 422
    assert _detail(admin, vid)["revision"] == 0
    assert next(x for x in _detail(admin, vid)["sessions"] if x["uid"] == s1["uid"])["date"] == s1["date"]
    # 不存在的场次、未知类型、格式错误 → 422
    for bad in (
        [{"op": "move", "uid": "nope", "date": "2026-09-05", "start_slot": 0}],
        [{"op": "fly", "uid": s1["uid"]}],
        [{"op": "move", "uid": s1["uid"]}],
    ):
        assert admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": bad}).status_code == 422


def test_batch_on_published_forks_and_move_then_delete_undo_restores_original(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 200
    d = _detail(admin, vid)
    s1 = _formal(d)[0]
    ops = [{"op": "move", "uid": s1["uid"], "date": _free_day(d), "start_slot": 1}, {"op": "delete", "uid": s1["uid"]}]
    r = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": ops}).json()
    assert r["forked"] is True and all(x["uid"] != s1["uid"] for x in r["version"]["sessions"])
    draft = r["version"]["id"]
    v = admin.post(f"/api/schedules/{draft}/undo", json={}).json()["version"]
    back = next(x for x in v["sessions"] if x["uid"] == s1["uid"])
    assert (back["date"], back["start_slot"]) == (s1["date"], s1["start_slot"])
    assert _detail(admin, vid)["status"] == "published"


# ---------- 少改动重排 ----------
def test_reoptimize_moves_only_what_is_needed(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    other = next(x for x in _formal(d) if x["uid"] != s["uid"])
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": other["id"], "locked": True})
    # 让 A 在这场所在的那天没空 → 产生冲突
    admin.put(f"/api/events/{ev['id']}/availability/{a['id']}", json={"days": {s["date"]: "0" * 13}, "submit": True})
    before = _detail(admin, vid)
    assert before["issues"]
    r = admin.post(f"/api/schedules/{vid}/reoptimize")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "ok" and p["ops"] and all(o["op"] == "move" for o in p["ops"])
    assert {o["uid"] for o in p["ops"]} == {s["uid"]}  # 只挪有冲突的那一场
    assert p["preview"]["issues"] == []
    # 提案不改数据库
    assert _detail(admin, vid)["revision"] == before["revision"]
    # 应用 → 冲突消失、锁定的那场原地不动、一次撤销
    v = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": p["ops"], "summary": "少改动重排"}).json()["version"]
    assert v["issues"] == [] and v["history"][0]["kind"] == "batch"
    kept = next(x for x in v["sessions"] if x["uid"] == other["uid"])
    assert (kept["date"], kept["start_slot"]) == (other["date"], other["start_slot"])


def test_reoptimize_reports_unchanged_and_locked_conflict(app, admin: TestClient):
    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    r = admin.post(f"/api/schedules/{vid}/reoptimize").json()
    assert r["status"] == "unchanged" and r["ops"] == []
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": s["id"], "locked": True})
    admin.put(f"/api/events/{ev['id']}/availability/{a['id']}", json={"days": {s["date"]: "0" * 13}, "submit": True})
    r = admin.post(f"/api/schedules/{vid}/reoptimize").json()
    assert r["status"] == "locked_conflict" and "锁定" in r["message"]


# ---------- 审查发现的问题(回归) ----------
def test_batch_lines_follow_earlier_ops_and_bad_numbers_are_422(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s1 = next(x for x in _formal(d) if x["song_name"] == "第一首")
    s2 = next(x for x in _formal(d) if x["song_name"] == "第二首")
    target = _free_day(d)
    ops = [{"op": "move", "uid": s1["uid"], "date": target, "start_slot": 4}, {"op": "swap", "a": s1["uid"], "b": s2["uid"]}]
    p = admin.post(f"/api/schedules/{vid}/ops/preview", json={"ops": ops}).json()
    m, dd = target.split("-")[1:]
    assert f"{int(m)}/{int(dd)}" in p["lines"][1] and "14:00" in p["lines"][1]  # 交换按挪过之后的位置描述
    # 超大数字(JSON 里的 1e999 → inf)→ 422,不是 500
    raw = json.dumps({"ops": [{"op": "move", "uid": s1["uid"], "date": target, "start_slot": "INF"}]}).replace('"INF"', "1e999")
    for path in ("ops/preview", "ops/batch"):
        r = admin.post(f"/api/schedules/{vid}/{path}", content=raw, headers={"Content-Type": "application/json"})
        assert r.status_code == 422, r.text


def test_batch_delete_then_add_does_not_reuse_the_number(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    firsts = [x for x in _formal(d) if x["song_name"] == "第一首"]
    last = max(firsts, key=lambda x: x["task_key"])
    ops = [
        {"op": "delete", "uid": last["uid"]},
        {"op": "add", "song_id": last["song_id"], "date": _free_day(d), "start_slot": 0, "duration_slots": 2},
    ]
    v = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": ops}).json()["version"]
    new = next(x for x in v["sessions"] if x["song_id"] == last["song_id"] and x["uid"] not in {f["uid"] for f in firsts})
    assert new["task_key"] > last["task_key"]


def test_stale_proposal_is_rejected_after_the_draft_is_edited_and_published(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s1, s2 = _formal(d)[:2]
    target = _free_day(d)
    ops = [{"op": "move", "uid": s1["uid"], "date": target, "start_slot": 0}]  # 修改次数 0 时生成的方案
    # 之后草稿被改过(锁定 / 解锁,不留下冲突),再发布
    assert admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": s2["id"], "locked": True}).status_code == 200
    assert admin.post(f"/api/schedules/{vid}/ops/lock", json={"session_id": s2["id"], "locked": False}).status_code == 200
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 200
    r = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": ops, "expected_revision": 0})
    assert r.status_code == 409


def test_deleting_a_song_makes_old_proposals_stale(app, admin: TestClient):
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    second = next(x for x in _formal(d) if x["song_name"] == "第二首")
    ops = [
        {
            "op": "add",
            "song_id": second["song_id"],
            "song_code": second["song_code"],
            "date": _free_day(d),
            "start_slot": 0,
            "duration_slots": 3,
        }
    ]
    assert admin.delete(f"/api/songs/{second['song_id']}").status_code == 204
    r = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": ops, "expected_revision": d["revision"]})
    assert r.status_code == 409


def test_reoptimize_is_409_when_the_version_changes_while_solving(app, admin: TestClient, monkeypatch):
    import app.api.schedule as schedule_api

    ev, (a, b, c), vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s = next(x for x in _formal(d) if x["song_name"] == "第一首")
    admin.put(f"/api/events/{ev['id']}/availability/{a['id']}", json={"days": {s["date"]: "0" * 13}, "submit": True})
    real = schedule_api.reoptimize

    def slow(*args, **kwargs):  # 求解期间另一个窗口删掉了这一场
        result = real(*args, **kwargs)
        with admin.app.state.session_factory() as db:
            from app.models import RehearsalSession, ScheduleVersion

            db.delete(db.scalar(__import__("sqlalchemy").select(RehearsalSession).where(RehearsalSession.uid == s["uid"])))
            v = db.get(ScheduleVersion, vid)
            v.revision = (v.revision or 0) + 1
            db.commit()
        return result

    monkeypatch.setattr(schedule_api, "reoptimize", slow)
    r = admin.post(f"/api/schedules/{vid}/reoptimize")
    assert r.status_code == 409, r.text
