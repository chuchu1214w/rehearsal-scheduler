"""AI 调度员:用脚本化的假 Claude 客户端走完“读情况 → 沙盘试算 → 提交方案 → 管理员允许执行 → 重新求解”。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import advisor
from tests.api.test_solve import FULL, NONE, _setup


def _block(**kw):
    return SimpleNamespace(**kw)


def _resp(*blocks, stop="tool_use"):
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop, usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0)
    )


class FakeClient:
    """按顺序返回预设回复,并记下每次收到的消息。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # 消息列表会继续增长,存快照
        if not self.script:
            raise AssertionError(str(kwargs["messages"][-1]))
        return self.script.pop(0)


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(script):
        holder["client"] = FakeClient(script)
        monkeypatch.setattr(advisor, "CLIENT_FACTORY", lambda: holder["client"])
        return holder["client"]

    yield install
    monkeypatch.setattr(advisor, "CLIENT_FACTORY", None)


def test_advisor_raises_absence_and_admin_applies(admin: TestClient, fake):
    ev, (a, b, c), (s1, s2) = _setup(admin, availability={})
    # C 只有评估日有空:第二首(B、C,只有 1 场)只能让 C 缺席,但默认设置不允许(每首至少 1 场全员、3 场的 25% 不到 1 场)
    c_days = {**NONE, "2026-09-09": "1" * 13}
    for m, days in ((a, FULL), (b, FULL), (c, c_days)):
        admin.put(f"/api/events/{ev['id']}/availability/{m['id']}", json={"days": days, "submit": True})
    assert admin.post(f"/api/events/{ev['id']}/solve", json={}).json()["status"] == "infeasible"

    changes = [
        {"kind": "setting", "key": "max_absent_percent", "value": 40, "reason": "允许约 1 场有人缺席"},
        {"kind": "setting", "key": "min_full_per_song", "value": 0, "reason": "第二首只有 1 场,C 排练期间都没空"},
    ]
    client = fake(
        [
            _resp(_block(type="thinking", thinking="先看情况"), _block(type="tool_use", id="t1", name="get_overview", input={})),
            _resp(
                _block(type="tool_use", id="t2", name="get_member_availability", input={"member": "C"}),
                _block(type="tool_use", id="t3", name="evaluate_changes", input={"changes": changes}),
            ),
            _resp(_block(type="tool_use", id="t4", name="submit_proposal", input={"summary": "让 C 缺席第二首", "changes": changes})),
        ]
    )
    r = admin.post(f"/api/events/{ev['id']}/advisor", json={"consent": True})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "done", run["error"]
    assert run["cost_usd"] is not None and any(x["kind"] == "think" for x in run["log"])

    # 工具结果回传给了 Claude:概况里有诊断与缺席设置,沙盘试算成功
    overview = client.calls[1]["messages"][-1]["content"][0]["content"]
    assert "上次求解诊断" in overview and "第二首" in overview and "max_absent_percent" in overview
    trial = client.calls[2]["messages"][-1]["content"][1]["content"]
    assert '"全部排完": true' in trial and '"缺席场次": 1' in trial
    # 提示词明确不能请成员改空闲,工具里也没有这个选项
    assert "不能请成员改空闲" in client.calls[0]["system"]
    assert "open_slots" not in str(client.calls[0]["tools"])

    p = run["proposal"]
    assert p["summary"] == "让 C 缺席第二首" and p["check"]["全部排完"] is True
    assert p["changes"][0]["description"] == "最多允许缺席的场次比例(%):25 → 40"
    # 沙盘没有改数据库
    assert admin.get(f"/api/events/{ev['id']}").json()["settings"]["max_absent_percent"] == 25
    assert admin.get(f"/api/events/{ev['id']}/advisor/latest").json()["id"] == run["id"]

    # 管理员允许后执行 → 设置已改,重新求解可行,C 缺席第二首
    r = admin.post(f"/api/advisor-runs/{run['id']}/apply", json={"indices": [0, 1]})
    assert r.status_code == 200 and r.json()["applied"] == [0, 1]
    settings = admin.get(f"/api/events/{ev['id']}").json()["settings"]
    assert settings["max_absent_percent"] == 40 and settings["min_full_per_song"] == 0
    job = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    assert job["status"] == "succeeded"
    detail = admin.get(f"/api/schedules/{job['version_id']}").json()
    assert [[m["display_name"] for m in x["absent"]] for x in detail["sessions"] if x["song_code"] == s2["code"]] == [["C"]]


def test_advisor_rule_change_and_bad_change_is_reported(admin: TestClient, fake):
    ev, (a, b, c), (s1, s2) = _setup(admin)
    rule = admin.post(f"/api/events/{ev['id']}/rules", json={"type": "blocked_day", "params": {"date": "2026-09-05"}}).json()
    bad = {"kind": "disable_rule", "rule_id": 99999, "reason": "x"}
    good = {"kind": "disable_rule", "rule_id": rule["id"], "reason": "9/5 场地其实可用"}
    setting = {"kind": "setting", "key": "hard_daily_limit", "value": 10, "reason": "允许单日多排一点"}
    client = fake(
        [
            _resp(_block(type="tool_use", id="t1", name="evaluate_changes", input={"changes": [bad]})),
            _resp(
                _block(type="text", text="换一个"),
                _block(type="tool_use", id="t2", name="submit_proposal", input={"summary": "s", "changes": [good, setting]}),
            ),
        ]
    )
    run = admin.post(f"/api/events/{ev['id']}/advisor", json={"consent": True}).json()
    assert run["status"] == "done", run["error"]
    err = client.calls[1]["messages"][-1]["content"][0]
    assert err["is_error"] and "找不到编号为 99999 的要求" in err["content"]
    assert run["proposal"]["changes"][0]["description"] == "停用:9/5 整天不排练"

    assert admin.post(f"/api/advisor-runs/{run['id']}/apply", json={"indices": [1]}).json()["applied"] == [1]
    assert admin.get(f"/api/events/{ev['id']}").json()["settings"]["hard_daily_limit"] == 10
    rules = admin.get(f"/api/events/{ev['id']}/rules").json()
    assert next(r for r in rules if r["id"] == rule["id"])["enabled"] is True  # 未勾选的不执行


def test_advisor_needs_api_key(admin: TestClient):
    ev, *_ = _setup(admin)
    r = admin.post(f"/api/events/{ev['id']}/advisor", json={"consent": True})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_event_ladder_follows_settings():
    from app.schemas import EventSettings
    from app.services import event_ladder
    from solver.types import DEFAULT_LADDER, LadderLevel

    assert event_ladder(EventSettings()) == DEFAULT_LADDER  # 默认设置与原来的阶梯一致
    assert event_ladder(EventSettings(max_absent_percent=0)) == (LadderLevel(0),)
    assert event_ladder(EventSettings(max_absent_percent=40, min_full_per_song=0, absent_per_member_song=2)) == (
        LadderLevel(0),
        LadderLevel(1, 0.20, 1, 1),
        LadderLevel(2, 0.40, 0, 2),
    )
    assert event_ladder(EventSettings(max_absent_percent=10)) == (LadderLevel(0), LadderLevel(1, 0.10, 1, 1))


def test_candidate_plans():
    assert advisor.candidate_plans([3]) == [[2], [2, 1]]
    assert advisor.candidate_plans([3, 2, 2]) == [[2, 2, 2], [2, 1, 1], [3, 2], [2, 2], [2, 2, 2, 1], [2, 1]]


def test_advisor_suggests_song_session_plans(admin: TestClient, fake):
    ev, (a, b, c), (s1, s2) = _setup(admin, availability={})
    # C 每个排练日只有 10:00–12:00 有空:第二首要 1 场 3 小时,排不下;改成 2 小时就行
    c_days = {d: "11" + "0" * 11 for d in FULL} | {"2026-09-09": "1" * 13}
    for m, days in ((a, FULL), (b, FULL), (c, c_days)):
        admin.put(f"/api/events/{ev['id']}/availability/{m['id']}", json={"days": days, "submit": True})
    assert admin.post(f"/api/events/{ev['id']}/solve", json={}).json()["status"] == "infeasible"

    plan_change = {"kind": "session_plan", "song": s2["code"], "plan": [2], "reason": "C 每天只有 2 小时"}
    client = fake(
        [
            _resp(_block(type="tool_use", id="t1", name="try_session_plans", input={"song": s2["code"]})),
            _resp(
                _block(
                    type="tool_use",
                    id="t2",
                    name="submit_proposal",
                    input={
                        "summary": "第二首改成 1 场 2 小时即可",
                        "changes": [plan_change],
                        "song_plans": [{"song": s2["code"], "plan": [2], "note": "单独改这首即可全部排完"}],
                    },
                )
            ),
        ]
    )
    run = admin.post(f"/api/events/{ev['id']}/advisor", json={"consent": True}).json()
    assert run["status"] == "done", run["error"]
    tried = client.calls[1]["messages"][-1]["content"][0]["content"]
    assert '"当前方案": "1 场:3h"' in tried and '"说明": "1 场:2h", "结果": "全部排完"' in tried
    assert any(x["kind"] == "result" and "1 场:2h、2 场:2h + 1h 可全部排完" in x["text"] for x in run["log"]), run["log"]

    p = run["proposal"]
    assert p["check"]["全部排完"] is True
    assert p["song_plans"] == [
        {
            "song": s2["code"],
            "song_name": "第二首",
            "current": "1 场:3h",
            "suggested": "1 场:2h",
            "plan": [2],
            "note": "单独改这首即可全部排完",
        }
    ]
    assert p["changes"][0]["description"] == f"曲目 {s2['code']} 的场次方案改为 2 小时"


def test_advisor_and_solve_do_not_run_together(admin: TestClient, fake):
    from app.models import AdvisorRun

    ev, *_ = _setup(admin)
    fake([])
    # 模拟一个正在运行的 AI 调度员(服务器内存小,两者不同时跑)→ 不能求解,也不能再开一个
    with admin.app.state.session_factory() as db:
        db.add(AdvisorRun(event_id=ev["id"], status="running"))
        db.commit()
    r = admin.post(f"/api/events/{ev['id']}/solve", json={})
    assert r.status_code == 409 and "AI 调度员正在工作" in r.json()["detail"]
    r = admin.post(f"/api/events/{ev['id']}/advisor", json={"consent": True})
    assert r.status_code == 409


def test_advisor_requires_consent(admin: TestClient, fake):
    ev, *_ = _setup(admin)
    fake([])
    r = admin.post(f"/api/events/{ev['id']}/advisor", json={})
    assert r.status_code == 422 and "Anthropic" in r.json()["detail"]
