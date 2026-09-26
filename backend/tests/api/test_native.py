"""原生 App 接入:Bearer 令牌会话、CORS、Universal Links 的 AASA、原生推送 token、APNs 发送。"""

import json

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import apns, push
from tests.api.conftest import ADMIN, add_member, make_event, open_account
from tests.api.test_schedule import SHORT


def test_native_login_returns_token_and_bearer_works(app, admin: TestClient):
    plain = TestClient(app)
    r = plain.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200 and r.json().get("token") is None  # 网页客户端不返回令牌
    native = TestClient(app, headers={"X-Client": "native"})
    r = native.post("/api/auth/login", json=ADMIN)
    token = r.json()["token"]
    assert token and len(token) > 20
    # 用 Bearer、不带 Cookie 的客户端
    bearer = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert bearer.get("/api/me").json()["username"] == ADMIN["username"]
    assert TestClient(app, headers={"Authorization": "Bearer nope"}).get("/api/me").status_code == 401
    # 登出后令牌失效
    assert bearer.post("/api/auth/logout").status_code == 204
    assert bearer.get("/api/me").status_code == 401


def test_cors_allows_capacitor_origin_only(app, anon: TestClient):
    r = anon.options(
        "/api/me",
        headers={
            "Origin": "capacitor://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "capacitor://localhost"
    assert r.headers["access-control-allow-credentials"] == "true"
    r = anon.options("/api/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


def test_apple_app_site_association(anon: TestClient):
    r = anon.get("/.well-known/apple-app-site-association")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    d = r.json()["applinks"]["details"][0]
    assert d["appIDs"] == ["TEAM123456.app.test.season"] and d["appID"] == "TEAM123456.app.test.season"
    assert {"/": "/api/*", "exclude": True} in d["components"] and {"/": "/cal/*", "exclude": True} in d["components"]
    assert d["components"][-1] == {"/": "*"} and d["paths"][-1] == "*" and "NOT /cal/*" in d["paths"]


def test_native_token_register_and_fanout(app, admin: TestClient, monkeypatch):
    monkeypatch.setattr(push, "BACKGROUND", False)
    monkeypatch.setattr(push, "APNS", apns.ApnsConfig(key_pem="x", key_id="K", team_id="T", topic="app.test.season"))
    sent: list[tuple[list, dict, str | None]] = []

    def fake(cfg, tokens, payload, collapse=None):
        sent.append((tokens, payload, collapse))
        return apns.DeliveryResult(
            dead=[t for t, _ in tokens if t.endswith("dead")], env={t: "sandbox" for t, _ in tokens if not t.endswith("dead")}
        )

    monkeypatch.setattr(apns, "DELIVER", fake)
    a = add_member(admin, "A")
    ev = make_event(admin, **SHORT, member_ids=[a["id"]], availability_deadline="2026-09-03")
    client_a = open_account(app, admin, a, "aa")
    st = client_a.post("/api/push/native", json={"platform": "ios", "token": "abcdef0123456789"}).json()
    assert st["native"] == 1 and st["native_available"] is True
    assert client_a.post("/api/push/native", json={"platform": "ios", "token": "abcdef0123456789"}).json()["native"] == 1  # 幂等
    client_a.post("/api/push/native", json={"platform": "ios", "token": "0000000000dead"})
    # 同一个人也订阅了 iPhone Safari 的网页推送:装了 App 后不再重复发
    client_a.post("/api/push/subscribe", json={"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "k", "auth": "a"}})
    web_sent: list = []
    monkeypatch.setattr(push, "DELIVER", lambda subs, payload, pem, contact: (web_sent.append(subs), [])[1])
    assert client_a.get("/api/push/status").json()["native"] == 2

    admin.post(f"/api/events/{ev['id']}/remind")
    assert len(sent) == 1 and web_sent == []
    tokens, payload, collapse = sent[0]
    assert {t for t, _ in tokens} == {"abcdef0123456789", "0000000000dead"} and all(env is None for _, env in tokens)
    assert payload["aps"]["alert"]["title"].startswith("请填写空闲时间") and payload["link"] == f"/events/{ev['id']}/availability"
    assert client_a.get("/api/push/status").json()["native"] == 1  # 失效 token 被清理
    # 第二次投递时带上已确认的环境
    admin.post(f"/api/events/{ev['id']}/remind")
    assert sent[-1][0] == [("abcdef0123456789", "sandbox")]
    assert client_a.post("/api/push/native/unregister", json={"token": "abcdef0123456789"}).json()["native"] == 0
    # 未配置 APNs 时不发原生,状态里如实告知
    monkeypatch.setattr(push, "APNS", None)
    assert client_a.post("/api/push/native", json={"platform": "ios", "token": "abcdef0123456789"}).json()["native_available"] is False
    sent.clear()
    admin.post(f"/api/events/{ev['id']}/remind")
    assert sent == []


def _test_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def test_apns_deliver_headers_env_fallback_and_dead_tokens():
    cfg = apns.ApnsConfig(key_pem=_test_key_pem(), key_id="ABC1234567", team_id="TEAM123456", topic="app.test.season")
    seen: list[httpx.Request] = []
    expired_once = {"done": False}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        host, token = request.url.host, request.url.path.rsplit("/", 1)[-1]
        if token == "gone":
            return httpx.Response(410, json={"reason": "Unregistered"})
        if token == "bad":
            return httpx.Response(400, json={"reason": "BadDeviceToken"})
        if token == "sandboxtok" and host == "api.push.apple.com":
            return httpx.Response(400, json={"reason": "BadDeviceToken"})  # 生产环境不认沙箱 token
        if token == "expired" and not expired_once["done"]:
            expired_once["done"] = True
            return httpx.Response(403, json={"reason": "ExpiredProviderToken"})
        if token == "boom":
            return httpx.Response(500, json={"reason": "InternalServerError"})
        return httpx.Response(200)

    payload = apns.apns_payload("标题", "内容", "/schedule", "location:12")
    res = apns._deliver(
        cfg,
        [("tok1", None), ("gone", None), ("bad", None), ("sandboxtok", None), ("expired", "production"), ("boom", None)],
        payload,
        apns.collapse_id("location:12"),
        transport=httpx.MockTransport(handler),
    )
    assert sorted(res.dead) == ["bad", "gone"]  # 两个环境都说 BadDeviceToken 才算失效;500 不删
    assert res.env == {"tok1": "production", "sandboxtok": "sandbox", "expired": "production"}
    req = seen[0]
    assert req.url.host == "api.push.apple.com"
    assert (
        req.headers["apns-topic"] == "app.test.season" and req.headers["apns-push-type"] == "alert" and req.headers["apns-priority"] == "10"
    )
    assert req.headers["apns-collapse-id"] == "location:12" and req.headers["authorization"].startswith("bearer ")
    body = json.loads(req.content)
    assert (
        body["aps"]["alert"] == {"title": "标题", "body": "内容"} and body["link"] == "/schedule" and body["aps"]["thread-id"] == "location"
    )
    # ExpiredProviderToken 后重签并重试成功
    exp = [r for r in seen if r.url.path.endswith("/expired")]
    assert len(exp) == 2
    assert apns.collapse_id("remind:") is None


def test_apns_config_from_settings(tmp_path, settings):
    assert apns.ApnsConfig.from_settings(settings) is None  # 没配密钥
    pem = _test_key_pem()
    f = tmp_path / "k.p8"
    f.write_text(pem)
    s2 = settings.model_copy(update={"apns_key_path": str(f), "apns_key_id": "K1", "apple_team_id": "T1", "ios_bundle_id": "app.x"})
    cfg = apns.ApnsConfig.from_settings(s2)
    assert cfg is not None and cfg.key_pem == pem and cfg.topic == "app.x" and cfg.sandbox is False


def test_session_absolute_lifetime(app, admin: TestClient):
    from datetime import timedelta

    from app.models import AuthSession

    native = TestClient(app, headers={"X-Client": "native"})
    token = native.post("/api/auth/login", json=ADMIN).json()["token"]
    bearer = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert bearer.get("/api/me").status_code == 200
    with app.state.session_factory() as db:
        for s in db.query(AuthSession).all():
            s.created_at = s.created_at - timedelta(days=91)
        db.commit()
    assert bearer.get("/api/me").status_code == 401  # 超过 90 天必须重新登录,即使一直在用
