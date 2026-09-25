"""PWA 推送:公钥、订阅 / 退订、通知时投递、失效订阅清理。投递函数用桩替换。"""

import pytest
from fastapi.testclient import TestClient

from app import push
from tests.api.conftest import add_member, make_event, open_account
from tests.api.test_schedule import SHORT

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BPk", "auth": "a1"}}


@pytest.fixture(autouse=True)
def _sync_push(monkeypatch):
    push.reset_cache()
    monkeypatch.setattr(push, "BACKGROUND", False)
    yield
    push.reset_cache()


def test_public_key_and_subscribe(app, admin: TestClient):
    k1 = admin.get("/api/push/public-key").json()["public_key"]
    assert len(k1) > 60 and "=" not in k1 and "+" not in k1
    assert admin.get("/api/push/public-key").json()["public_key"] == k1  # 稳定
    assert admin.get("/api/push/status").json()["devices"] == 0
    assert admin.post("/api/push/subscribe", json=SUB).json()["devices"] == 1
    assert admin.post("/api/push/subscribe", json=SUB).json()["devices"] == 1  # 同一设备重复订阅不翻倍
    assert admin.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]}).json()["devices"] == 0


def test_notification_triggers_push_and_dead_endpoint_cleanup(app, admin: TestClient, monkeypatch):
    calls: list[tuple[list, dict]] = []

    def fake_deliver(subs, payload, private_pem, contact):
        calls.append((subs, payload))
        assert private_pem.startswith("-----BEGIN") and contact.startswith("mailto:")
        return [s["endpoint"] for s in subs if s["endpoint"].endswith("/dead")]

    monkeypatch.setattr(push, "DELIVER", fake_deliver)
    a = add_member(admin, "A")
    ev = make_event(admin, **SHORT, member_ids=[a["id"]], availability_deadline="2026-09-03")
    client_a = open_account(app, admin, a, "aa")
    client_a.post("/api/push/subscribe", json=SUB)
    client_a.post("/api/push/subscribe", json={"endpoint": "https://push.example/dead", "keys": {"p256dh": "x", "auth": "y"}})
    assert client_a.get("/api/push/status").json()["devices"] == 2

    r = admin.post(f"/api/events/{ev['id']}/remind")
    assert r.status_code == 200 and r.json()["notified"] == ["A"]
    assert len(calls) == 1
    subs, payload = calls[0]
    assert {s["endpoint"] for s in subs} == {SUB["endpoint"], "https://push.example/dead"}
    assert payload["title"].startswith("请填写空闲时间") and payload["link"] == f"/events/{ev['id']}/availability"
    # 失效的订阅被清理
    assert client_a.get("/api/push/status").json()["devices"] == 1
    # 没有订阅的用户不会触发投递
    calls.clear()
    admin.post(f"/api/events/{ev['id']}/remind")
    assert len(calls) == 1  # A 还有 1 台设备
