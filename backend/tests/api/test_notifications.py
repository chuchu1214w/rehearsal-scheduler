"""M6:站内通知、一键催办、定时提醒、规则冲突检查、优化目标顺序。"""

from datetime import date

from fastapi.testclient import TestClient

from tests.api.conftest import add_member, add_song, make_event, open_account
from tests.api.test_schedule import DAYS, FULL, SHORT


def _titles(client: TestClient) -> list[str]:
    return [n["title"] for n in client.get("/api/notifications").json()]


def test_joined_publish_and_conflict_notifications(app, admin: TestClient):
    a, b = add_member(admin, "A"), add_member(admin, "B")
    ev = make_event(admin, **SHORT, member_ids=[a["id"], b["id"]], availability_deadline="2026-09-03")
    add_song(admin, ev["id"], "第一首", [a["id"], b["id"]], "简单")
    # 开通账号 → 「你被加入演出」
    client_a = open_account(app, admin, a, "aa")
    client_b = open_account(app, admin, b, "bb")
    assert client_a.get("/api/notifications/unread-count").json() == {"count": 1}
    assert _titles(client_a) == [f"你被加入演出「{ev['name']}」"]
    n = client_a.get("/api/notifications").json()[0]
    assert n["link"] == f"/events/{ev['id']}/availability" and "9/3" in n["body"] and n["read_at"] is None

    # 成员提交空闲;最后一人提交 → 管理员收到「全员已提交」
    client_a.put(f"/api/events/{ev['id']}/availability/{a['id']}", json={"days": FULL, "submit": True})
    assert "全员已提交空闲" not in "".join(_titles(admin))
    client_b.put(f"/api/events/{ev['id']}/availability/{b['id']}", json={"days": FULL, "submit": True})
    assert any(t.startswith("全员已提交空闲") for t in _titles(admin))

    # 求解 + 发布 → 成员收到「已发布」
    job = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    assert admin.post(f"/api/schedules/{job['version_id']}/publish").status_code == 200
    latest = client_a.get("/api/notifications").json()[0]
    assert latest["type"] == "published" and "v1 已发布" in latest["title"] and "你有 2 场排练" in latest["body"]
    assert latest["link"] == f"/schedule?event={ev['id']}"
    assert client_a.get("/api/notifications/unread-count").json()["count"] == 2

    # 成员改空闲导致冲突 → 管理员收到「修改了空闲」
    d = admin.get(f"/api/schedules/{job['version_id']}").json()
    s = next(x for x in d["sessions"] if x["kind"] == "formal")
    client_a.put(f"/api/events/{ev['id']}/availability/{a['id']}", json={"days": {s["date"]: "0" * 13}, "submit": True})
    top = admin.get("/api/notifications").json()[0]
    assert (
        top["type"] == "conflict" and top["title"].startswith("A 修改了空闲,1 场受影响") and top["link"] == f"/events/{ev['id']}/schedule"
    )

    # 标记已读:先只读一条,再全部
    ids = [n["id"] for n in client_a.get("/api/notifications").json()]
    assert client_a.post("/api/notifications/read", json={"ids": [ids[0]]}).json()["count"] == 1
    assert client_a.post("/api/notifications/read", json={}).json()["count"] == 0
    assert all(n["read_at"] for n in client_a.get("/api/notifications").json())
    # 别人的通知看不到
    assert all(n["type"] != "conflict" for n in client_b.get("/api/notifications").json())

    # 再发布一版(不同内容)→ 「较 v1:你的 N 场有变动」
    admin.post(f"/api/schedules/{job['version_id']}/sessions/{s['id']}/lock", json={"locked": True})  # 复制成草稿 v2
    v2 = admin.get(f"/api/events/{ev['id']}/schedules").json()[0]
    assert admin.post(f"/api/schedules/{v2['id']}/publish").status_code == 200
    latest = client_a.get("/api/notifications").json()[0]
    assert "v2 已发布" in latest["title"] and "较 v1" in latest["body"]
    # 撤回 → 通知
    admin.post(f"/api/schedules/{v2['id']}/unpublish")
    assert client_a.get("/api/notifications").json()[0]["type"] == "unpublished"


def test_remind_endpoint(app, admin: TestClient):
    a, b, c = add_member(admin, "A"), add_member(admin, "B"), add_member(admin, "C")
    ev = make_event(admin, **SHORT, member_ids=[a["id"], b["id"], c["id"]], availability_deadline="2026-09-03")
    client_a = open_account(app, admin, a, "aa")
    client_b = open_account(app, admin, b, "bb")
    client_b.put(f"/api/events/{ev['id']}/availability/{b['id']}", json={"days": FULL, "submit": True})
    r = admin.post(f"/api/events/{ev['id']}/remind")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["notified"] == ["A"] and body["without_account"] == ["C"] and "C" in body["copy_text"] and "9/3" in body["copy_text"]
    assert _titles(client_a)[0].startswith("请填写空闲时间")
    assert all(n["type"] != "remind" for n in client_b.get("/api/notifications").json())
    assert client_a.post(f"/api/events/{ev['id']}/remind").status_code == 403


def test_due_reminders_are_idempotent(app, admin: TestClient):
    from app.notify import run_due_reminders

    a, b = add_member(admin, "A"), add_member(admin, "B")
    ev = make_event(admin, **SHORT, member_ids=[a["id"], b["id"]], availability_deadline="2026-09-03")
    add_song(admin, ev["id"], "第一首", [a["id"], b["id"]], "简单")
    client_a = open_account(app, admin, a, "aa")
    client_b = open_account(app, admin, b, "bb")
    client_b.put(f"/api/events/{ev['id']}/availability/{b['id']}", json={"days": FULL, "submit": True})

    with app.state.session_factory() as db:
        assert run_due_reminders(db, today=date(2026, 9, 1)) == 0  # 截止还有 2 天:不提醒
        assert run_due_reminders(db, today=date(2026, 9, 2)) == 1  # 明天截止:A 一条
        assert run_due_reminders(db, today=date(2026, 9, 2)) == 0  # 重复运行不重复发
        assert run_due_reminders(db, today=date(2026, 9, 4)) == 2  # 已过截止:A 一条 + 管理员一条
    titles = _titles(client_a)
    assert titles[0].startswith("填报已过截止日") and titles[1].startswith("明天就是填报截止日")
    assert any(t.startswith("填报已过截止日,还有 1 人未提交") for t in _titles(admin))
    assert all(n["type"] != "deadline" for n in client_b.get("/api/notifications").json())

    # 发布后:排练前一天给每人发明天的日程
    client_a.put(f"/api/events/{ev['id']}/availability/{a['id']}", json={"days": FULL, "submit": True})
    job = admin.post(f"/api/events/{ev['id']}/solve", json={}).json()
    admin.post(f"/api/schedules/{job['version_id']}/publish")
    d = admin.get(f"/api/schedules/{job['version_id']}").json()
    first = min(s["date"] for s in d["sessions"])
    day_before = date.fromisoformat(first).replace(day=date.fromisoformat(first).day - 1)
    with app.state.session_factory() as db:
        n = run_due_reminders(db, today=day_before)
        assert n >= 1
        assert run_due_reminders(db, today=day_before) == 0
    top = client_a.get("/api/notifications").json()[0]
    assert top["type"] == "tomorrow" and "明天有" in top["title"] and top["link"].startswith(f"/schedule/day/{first}")
    # 管理员手动触发接口
    assert admin.post("/api/admin/run-reminders").status_code == 200


def test_rule_conflict_warning_and_objectives(admin: TestClient):
    a, b = add_member(admin, "A"), add_member(admin, "B")
    ev = make_event(admin, **SHORT, member_ids=[a["id"], b["id"]])
    add_song(admin, ev["id"], "第一首", [a["id"], b["id"]], "简单")
    # 把全部正规排练日禁排 → 新规则返回冲突提示
    for d in DAYS[:-2]:
        r = admin.post(f"/api/events/{ev['id']}/rules", json={"type": "blocked_day", "params": {"date": d}})
        assert r.status_code == 201, r.text
        assert r.json()["warning"] is None
    r = admin.post(f"/api/events/{ev['id']}/rules", json={"type": "blocked_day", "params": {"date": DAYS[-2]}})
    assert r.status_code == 201 and r.json()["warning"] and "没有任何可排时段" in r.json()["warning"]
    # 停用最后一条 → 警告消失
    assert admin.patch(f"/api/rules/{r.json()['id']}", json={"enabled": False}).json()["warning"] is None

    # 优化目标顺序可配置
    objs = admin.get("/api/objectives").json()
    assert {o["key"] for o in objs} >= {"absent", "trips", "hard_early"} and next(o for o in objs if o["key"] == "hard_early")[
        "default_on"
    ] is False
    e = admin.get(f"/api/events/{ev['id']}").json()
    assert e["settings"]["objectives"][0] == "absent"
    new_order = ["trips", "absent", "eval_attendance"]
    r = admin.patch(f"/api/events/{ev['id']}", json={"settings": {**e["settings"], "objectives": new_order}})
    assert r.status_code == 200 and r.json()["settings"]["objectives"] == new_order
    assert (
        admin.patch(f"/api/events/{ev['id']}", json={"settings": {**e["settings"], "objectives": ["absent", "absent"]}}).status_code == 422
    )
    assert admin.patch(f"/api/events/{ev['id']}", json={"settings": {**e["settings"], "objectives": ["nope"]}}).status_code == 422
