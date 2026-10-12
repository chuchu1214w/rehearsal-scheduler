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


def _open_c(day):
    return {"kind": "open_slots", "member": "C", "date": day, "start_hour": 10, "end_hour": 23, "reason": "C 全程没空"}


def test_advisor_proposes_and_admin_applies(admin: TestClient, fake):
    ev, (a, b, c), (s1, s2) = _setup(admin, availability={})
    for m, days in ((a, FULL), (b, FULL), (c, NONE)):
        admin.put(f"/api/events/{ev['id']}/availability/{m['id']}", json={"days": days, "submit": True})
    assert admin.post(f"/api/events/{ev['id']}/solve", json={}).json()["status"] == "infeasible"

    changes = [_open_c("2026-09-05"), _open_c("2026-09-09")]
    client = fake(
        [
            _resp(_block(type="thinking", thinking="先看情况"), _block(type="tool_use", id="t1", name="get_overview", input={})),
            _resp(
                _block(type="tool_use", id="t2", name="get_member_availability", input={"member": "C"}),
                _block(type="tool_use", id="t3", name="evaluate_changes", input={"changes": changes}),
            ),
            _resp(_block(type="tool_use", id="t4", name="submit_proposal", input={"summary": "请 C 开放两天", "changes": changes})),
        ]
    )
    r = admin.post(f"/api/events/{ev['id']}/advisor")
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "done", run["error"]
    assert run["cost_usd"] is not None and any(x["kind"] == "think" for x in run["log"])

    # 工具结果回传给了 Claude:概况里有诊断,沙盘试算成功
    overview = client.calls[1]["messages"][-1]["content"][0]["content"]
    assert "上次求解诊断" in overview and "第二首" in overview
    trial = client.calls[2]["messages"][-1]["content"][1]["content"]
    assert '"全部排完": true' in trial

    p = run["proposal"]
    assert p["summary"] == "请 C 开放两天" and p["check"]["全部排完"] is True
    assert p["changes"][0]["description"].startswith("请 C 把 9/5 10:00–23:00")
    # 沙盘没有改数据库
    assert admin.get(f"/api/events/{ev['id']}/availability/{c['id']}").json()["days"]["2026-09-05"] == "0" * 13

    assert admin.get(f"/api/events/{ev['id']}/advisor/latest").json()["id"] == run["id"]
    # C 没有账号:通知会被跳过
    assert admin.post(f"/api/advisor-runs/{run['id']}/ask-members", json={"indices": [0, 1]}).json() == {"sent": [], "skipped": ["C"]}

    # 管理员允许后执行 → 空闲被代填,重新求解可行
    r = admin.post(f"/api/advisor-runs/{run['id']}/apply", json={"indices": [0, 1]})
    assert r.status_code == 200 and r.json()["applied"] == [0, 1]
    got = admin.get(f"/api/events/{ev['id']}/availability/{c['id']}").json()
    assert got["days"]["2026-09-05"] == "1" * 13 and got["filled_by"] == "admin"
    assert admin.post(f"/api/events/{ev['id']}/solve", json={}).json()["status"] == "succeeded"


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
    run = admin.post(f"/api/events/{ev['id']}/advisor").json()
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
    r = admin.post(f"/api/events/{ev['id']}/advisor")
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
