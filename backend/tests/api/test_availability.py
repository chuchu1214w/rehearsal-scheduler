from fastapi.testclient import TestClient

from tests.api.conftest import add_member, make_event, open_account

DAYS = [f"2026-09-{x:02d}" for x in range(4, 20)]  # 15 个正规排练日 + 评估日 9/19


def test_member_fills_own_availability(app, admin: TestClient):
    a, b = add_member(admin, "衿"), add_member(admin, "菁")
    ev = make_event(admin, member_ids=[a["id"], b["id"]])
    client = open_account(app, admin, a, "jin")
    url = f"/api/events/{ev['id']}/availability/{a['id']}"

    r = client.get(url)
    assert r.status_code == 200
    body = r.json()
    assert body["dates"] == DAYS and body["eval_date"] == "2026-09-19" and body["slots_per_day"] == 13
    assert set(body["days"].values()) == {"0" * 13} and body["filled_days"] == 0 and body["submitted_at"] is None
    assert body["deadline"] == "2026-09-10" and body["past_deadline"] is True  # 今天(2026-09-21)已过截止

    r = client.put(url, json={"days": {"2026-09-04": "0000011112000", "2026-09-19": "0000000011100"}})
    assert r.status_code == 200 and r.json()["filled_days"] == 2 and r.json()["filled_by"] == "member"
    assert r.json()["days"]["2026-09-04"] == "0000011112000"
    # 校验
    assert client.put(url, json={"days": {"2026-09-03": "0" * 13}}).status_code == 422  # 不在区间
    assert client.put(url, json={"days": {"2026-09-04": "0" * 12}}).status_code == 422  # 长度
    assert client.put(url, json={"days": {"2026-09-04": "3" * 13}}).status_code == 422  # 非法值
    # 提交
    r = client.post(f"{url}/submit")
    assert r.status_code == 200 and r.json()["submitted_at"] is not None
    members = admin.get(f"/api/events/{ev['id']}/members").json()
    me = next(x for x in members if x["member_id"] == a["id"])
    assert me["availability_submitted_at"] is not None and me["availability_filled_days"] == 2
    assert admin.get(f"/api/events/{ev['id']}").json()["submitted_count"] == 1
    assert client.post(f"{url}/unsubmit").json()["submitted_at"] is None
    # 一次保存并提交
    r = client.put(url, json={"days": {"2026-09-05": "1" * 13}, "submit": True})
    assert r.json()["submitted_at"] is not None and r.json()["filled_days"] == 3


def test_member_cannot_touch_others(app, admin: TestClient):
    a, b = add_member(admin, "衿"), add_member(admin, "菁")
    ev = make_event(admin, member_ids=[a["id"], b["id"]])
    client = open_account(app, admin, a, "jin")
    other = f"/api/events/{ev['id']}/availability/{b['id']}"
    assert client.get(other).status_code == 403
    assert client.put(other, json={"days": {}}).status_code == 403
    assert client.post(f"{other}/submit").status_code == 403
    assert client.get(f"/api/events/{ev['id']}/availability/overview").status_code == 403
    # 不在演出中的成员
    c = add_member(admin, "路人")
    assert admin.get(f"/api/events/{ev['id']}/availability/{c['id']}").status_code == 404


def test_admin_proxy_fill_and_overview(app, admin: TestClient):
    a, b = add_member(admin, "衿"), add_member(admin, "菁")
    ev = make_event(admin, member_ids=[a["id"], b["id"]])
    url_a = f"/api/events/{ev['id']}/availability/{a['id']}"
    r = admin.put(url_a, json={"days": {"2026-09-04": "1" * 13}, "submit": True})
    assert r.json()["filled_by"] == "admin"
    admin.put(f"/api/events/{ev['id']}/availability/{b['id']}", json={"days": {"2026-09-04": "0000011110000"}, "submit": True})

    heat = admin.get(f"/api/events/{ev['id']}/availability/overview").json()
    assert heat["member_count"] == 2 and heat["submitted_count"] == 2
    assert heat["heat"]["2026-09-04"] == [1, 1, 1, 1, 1, 2, 2, 2, 2, 1, 1, 1, 1]
    assert heat["heat"]["2026-09-05"] == [0] * 13
    members = admin.get(f"/api/events/{ev['id']}/members").json()
    assert next(x for x in members if x["member_id"] == a["id"])["availability_filled_by"] == "admin"
