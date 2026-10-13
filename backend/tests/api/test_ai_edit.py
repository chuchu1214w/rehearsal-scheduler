"""第二步:用一句话让 AI 修改排练表。用脚本化的假 Claude 客户端走完“读排练表 → 试算 → 提交方案”,
确认 AI 全程不写数据库,方案经管理员用 /ops/batch 应用后才生效、可整体撤销。"""

import json

from fastapi.testclient import TestClient

from tests.api.test_advisor import _block, _resp, fake  # noqa: F401
from tests.api.test_batch import _formal
from tests.api.test_edit import _detail, _free_day
from tests.api.test_schedule import _solved_event


def _tool_results(call: dict) -> list[dict]:
    """某次请求里最后一条用户消息带回的工具结果(解析成 dict)。"""
    return [json.loads(b["content"]) | {"_error": b["is_error"]} for b in call["messages"][-1]["content"] if b["type"] == "tool_result"]


def test_ai_edit_proposes_without_writing_then_admin_applies(app, admin: TestClient, fake):  # noqa: F811
    ev, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s1 = _formal(d)[0]
    target = _free_day(d)
    move = {"op": "move", "uid": s1["uid"], "date": target, "start_hour": 11}
    client = fake(
        [
            _resp(_block(type="thinking", thinking="先读排练表"), _block(type="tool_use", id="t1", name="get_schedule", input={})),
            _resp(
                _block(type="tool_use", id="t2", name="get_member_availability", input={"member": "A"}),
                _block(type="tool_use", id="t3", name="preview_changes", input={"ops": [move, {"op": "delete", "uid": s1["uid"]}]}),
            ),
            _resp(_block(type="tool_use", id="t4", name="preview_changes", input={"ops": [move]})),
            _resp(_block(type="tool_use", id="t5", name="submit_proposal", input={"summary": "把第一首挪到空的那天", "ops": [move]})),
        ]
    )
    r = admin.post(f"/api/schedules/{vid}/ai-edit", json={"instruction": "把第一首的第一场挪到没排练的那天上午", "consent": True})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "done", run["error"]
    assert run["kind"] == "edit" and run["version_id"] == vid and run["instruction"].startswith("把第一首")
    p = run["proposal"]
    assert p["summary"] == "把第一首挪到空的那天" and p["revision"] == 0 and p["version_id"] == vid
    assert p["ops"] == [{"op": "move", "uid": s1["uid"], "date": target, "start_slot": 1}]  # 11 点 = 第 1 格(10 点开始)
    assert len(p["lines"]) == 1 and p["lines"][0].startswith("移动") and p["new_issues"] == []

    # 第一次请求只有管理员的要求;读到的排练表里有每一场的 uid
    assert "把第一首的第一场" in client.calls[0]["messages"][0]["content"]
    view = _tool_results(client.calls[1])[0]
    assert any(x["uid"] == s1["uid"] for x in view["场次"]) and view["每日排练窗口"] == "10:00–23:00"
    avail, tried = _tool_results(client.calls[2])
    assert not avail["_error"] and not tried["_error"] and len(tried["修改"]) == 2 and "_ops" not in tried

    # AI 只出方案:排练表没变
    after = _detail(admin, vid)
    assert after["revision"] == 0 and after["history"] == [] and after["sessions"] == d["sessions"]
    assert admin.get(f"/api/events/{ev['id']}/ai-edits/latest").json()["id"] == run["id"]
    assert admin.get(f"/api/events/{ev['id']}/advisor/latest").status_code == 404  # 调度员的“最近一次”不含 AI 修改
    assert admin.post(f"/api/advisor-runs/{run['id']}/apply", json={"indices": [0]}).status_code == 422

    # 应用失败(修改次数对不上)不会把方案记成「已应用」
    bad = {"ops": p["ops"], "summary": "AI", "expected_revision": 99, "ai_run_id": run["id"]}
    assert admin.post(f"/api/schedules/{vid}/ops/batch", json=bad).status_code == 409
    assert admin.get(f"/api/advisor-runs/{run['id']}").json()["applied"] == []
    # 管理员应用 → 一条修改记录、可撤销;运行记录记下写入的版本
    body = {"ops": p["ops"], "summary": "AI:" + p["summary"], "expected_revision": p["revision"], "ai_run_id": run["id"]}
    r = admin.post(f"/api/schedules/{vid}/ops/batch", json=body)
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    moved = next(x for x in v["sessions"] if x["uid"] == s1["uid"])
    assert (moved["date"], moved["start_slot"]) == (target, 1) and v["history"][0]["summary"].startswith("AI:")
    assert admin.get(f"/api/advisor-runs/{run['id']}").json()["applied"] == [vid]
    # 同一方案再应用一次:修改次数已变 → 409
    assert admin.post(f"/api/schedules/{vid}/ops/batch", json=body).status_code == 409
    v = admin.post(f"/api/schedules/{vid}/undo", json={}).json()["version"]
    assert next(x for x in v["sessions"] if x["uid"] == s1["uid"])["date"] == s1["date"]


def test_ai_edit_bad_ops_are_reported_back_and_empty_proposal_allowed(app, admin: TestClient, fake):  # noqa: F811
    _, _, vid, _ = _solved_event(app, admin)
    d = _detail(admin, vid)
    s1 = _formal(d)[0]
    ev_s = next(x for x in d["sessions"] if x["kind"] == "evaluation")
    client = fake(
        [
            _resp(
                _block(
                    type="tool_use",
                    id="t1",
                    name="preview_changes",
                    input={"ops": [{"op": "move", "uid": "nope", "date": "2026-09-05", "start_hour": 10}]},
                ),
                _block(
                    type="tool_use",
                    id="t2",
                    name="preview_changes",
                    input={"ops": [{"op": "add", "song": "不存在", "date": "2026-09-05", "start_hour": 10, "hours": 2}]},
                ),
                _block(type="tool_use", id="t3", name="preview_changes", input={"ops": [{"op": "move", "uid": s1["uid"]}]}),
                _block(type="tool_use", id="t4", name="preview_changes", input={"ops": [{"op": "delete", "uid": ev_s["uid"]}]}),
                _block(type="tool_use", id="t5", name="drop_table", input={}),
            ),
            # 提交了无效方案 → 退回错误,方案不成立
            _resp(_block(type="tool_use", id="t6", name="submit_proposal", input={"summary": "x", "ops": [{"op": "fly"}]})),
            # 只说话不调工具 → 被提醒提交
            _resp(_block(type="text", text="我想想"), stop="end_turn"),
            _resp(_block(type="tool_use", id="t7", name="submit_proposal", input={"summary": "评估场不能删,无法照做", "ops": []})),
        ]
    )
    run = admin.post(f"/api/schedules/{vid}/ai-edit", json={"instruction": "删掉评估场", "consent": True}).json()
    assert run["status"] == "done", run["error"]
    assert run["proposal"]["ops"] == [] and run["proposal"]["summary"].startswith("评估场不能删")
    errs = _tool_results(client.calls[1])
    assert all(e["_error"] for e in errs) and len(errs) == 5
    assert "找不到曲目" in errs[1]["错误"] and "缺少或写错了字段" in errs[2]["错误"] and "未知工具" in errs[4]["错误"]
    assert _tool_results(client.calls[2])[0]["_error"]
    assert "submit_proposal" in client.calls[3]["messages"][-1]["content"]
    assert _detail(admin, vid)["sessions"] == d["sessions"]


def test_ai_edit_on_published_version_applies_to_a_new_draft(app, admin: TestClient, fake):  # noqa: F811
    _, _, vid, _ = _solved_event(app, admin)
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 200
    d = _detail(admin, vid)
    s1 = next(x for x in _formal(d) if x["start_slot"] + x["duration_slots"] < 13)  # 往后加长一小时不超出窗口
    op = {"op": "resize", "uid": s1["uid"], "start_hour": 10 + s1["start_slot"], "hours": s1["duration_slots"] + 1}
    fake([_resp(_block(type="tool_use", id="t1", name="submit_proposal", input={"summary": "加长一小时", "ops": [op]}))])
    run = admin.post(f"/api/schedules/{vid}/ai-edit", json={"instruction": "第一首第一场加长一小时", "consent": True}).json()
    assert run["status"] == "done", run["error"]
    p = run["proposal"]
    r = admin.post(f"/api/schedules/{vid}/ops/batch", json={"ops": p["ops"], "summary": "AI", "ai_run_id": run["id"]}).json()
    assert r["forked"] is True
    draft = r["version"]
    assert next(x for x in draft["sessions"] if x["uid"] == s1["uid"])["duration_slots"] == s1["duration_slots"] + 1
    assert _detail(admin, vid)["sessions"] == d["sessions"]  # 已发布的版本不变
    assert admin.get(f"/api/advisor-runs/{run['id']}").json()["applied"] == [draft["id"]]


def test_ai_edit_needs_consent_key_admin_and_no_other_ai_running(app, admin: TestClient, fake):  # noqa: F811
    from app.models import AdvisorRun

    ev, _, vid, member_c = _solved_event(app, admin)
    fake([])
    body = {"instruction": "挪一下", "consent": True}
    assert admin.post(f"/api/schedules/{vid}/ai-edit", json={**body, "consent": False}).status_code == 422
    assert admin.post(f"/api/schedules/{vid}/ai-edit", json={**body, "instruction": "x"}).status_code == 422
    assert admin.post("/api/schedules/99999/ai-edit", json=body).status_code == 404
    assert member_c.post(f"/api/schedules/{vid}/ai-edit", json=body).status_code == 403
    with admin.app.state.session_factory() as db:
        db.add(AdvisorRun(event_id=ev["id"], status="running"))
        db.commit()
    r = admin.post(f"/api/schedules/{vid}/ai-edit", json=body)
    assert r.status_code == 409 and "同一时间只能运行一个" in r.json()["detail"]
    assert admin.post(f"/api/events/{ev['id']}/solve", json={}).status_code == 409


def test_ai_edit_without_api_key_is_unavailable(app, admin: TestClient):
    _, _, vid, _ = _solved_event(app, admin)
    r = admin.post(f"/api/schedules/{vid}/ai-edit", json={"instruction": "挪一下", "consent": True})
    assert r.status_code == 503


def test_ai_proposal_applies_once_and_only_to_its_version(app, admin: TestClient, fake):  # noqa: F811
    _, _, vid, _ = _solved_event(app, admin)
    assert admin.post(f"/api/schedules/{vid}/publish").status_code == 200
    d = _detail(admin, vid)
    s1 = _formal(d)[0]
    op = {"op": "lock", "uid": s1["uid"], "locked": True}
    fake([_resp(_block(type="tool_use", id="t1", name="submit_proposal", input={"summary": "锁定", "ops": [op]}))])
    run = admin.post(f"/api/schedules/{vid}/ai-edit", json={"instruction": "锁定第一场", "consent": True}).json()
    body = {"ops": run["proposal"]["ops"], "summary": "AI", "ai_run_id": run["id"], "expected_revision": run["proposal"]["revision"]}
    first = admin.post(f"/api/schedules/{vid}/ops/batch", json=body)
    assert first.status_code == 200 and first.json()["forked"] is True
    # 另一个窗口再点一次「应用」:不会再复制出一份草稿
    again = admin.post(f"/api/schedules/{vid}/ops/batch", json=body)
    assert again.status_code == 409 and "已经应用过" in again.json()["detail"]
    # 用到别的版本上也不行
    other = first.json()["version"]["id"]
    r = admin.post(f"/api/schedules/{other}/ops/batch", json={**body, "expected_revision": None})
    assert r.status_code == 409


def test_ai_edit_survives_malformed_ops_and_reports_short_errors(app, admin: TestClient, fake):  # noqa: F811
    _, _, vid, _ = _solved_event(app, admin)
    client = fake(
        [
            _resp(_block(type="tool_use", id="t1", name="preview_changes", input={"ops": 42})),
            _resp(_block(type="tool_use", id="t2", name="submit_proposal", input={"summary": "x", "ops": "move everything"})),
        ]
    )
    run = admin.post(f"/api/schedules/{vid}/ai-edit", json={"instruction": "随便改改", "consent": True}).json()
    assert _tool_results(client.calls[1])[0]["_error"] and _tool_results(client.calls[2])[0]["_error"]
    # 脚本用完 → 假客户端抛错;运行记为失败,错误只有一句话(完整错误只进服务器日志)
    assert run["status"] == "failed" and "\n" not in run["error"] and "Traceback" not in run["error"]
