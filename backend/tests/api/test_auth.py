from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Invite
from app.utils import utcnow
from tests.api.conftest import ADMIN, MEMBER_PW, add_member, invite_and_accept


def test_setup_once(anon: TestClient):
    assert anon.get("/api/setup/status").json() == {"needs_setup": True}
    assert anon.get("/api/me").status_code == 401
    r = anon.post("/api/setup", json=ADMIN)
    assert r.status_code == 201 and r.json()["role"] == "admin"
    assert anon.get("/api/me").json()["username"] == "captain"
    assert anon.get("/api/setup/status").json() == {"needs_setup": False}
    assert TestClient(anon.app).post("/api/setup", json={"username": "x2", "password": "Passw0rd!"}).status_code == 404


def test_setup_validates_username_and_password(anon: TestClient):
    assert anon.post("/api/setup", json={"username": "a b", "password": "Passw0rd!"}).status_code == 422
    assert anon.post("/api/setup", json={"username": "ok_name", "password": "short"}).status_code == 422


def test_login_logout_and_rate_limit(app, admin: TestClient):
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": "captain", "password": "wrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "CAPTAIN", "password": ADMIN["password"]}).status_code == 200
    assert c.get("/api/me").status_code == 200
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/me").status_code == 401

    for _ in range(5):
        c.post("/api/auth/login", json={"username": "captain", "password": "wrong"})
    r = c.post("/api/auth/login", json={"username": "captain", "password": ADMIN["password"]})
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert anon_can_login_other_user(app)


def anon_can_login_other_user(app) -> bool:
    # 限流按用户名计,不影响其他账号
    return TestClient(app).post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401


def test_change_password_revokes_other_sessions(app, admin: TestClient):
    other = TestClient(app)
    assert other.post("/api/auth/login", json=ADMIN).status_code == 200
    assert admin.post("/api/me/password", json={"old_password": "nope", "new_password": "NewPassw0rd!"}).status_code == 400
    assert admin.post("/api/me/password", json={"old_password": ADMIN["password"], "new_password": "NewPassw0rd!"}).status_code == 204
    assert admin.get("/api/me").status_code == 200  # 当前会话保留
    assert other.get("/api/me").status_code == 401  # 其他会话失效
    assert TestClient(app).post("/api/auth/login", json={"username": "captain", "password": "NewPassw0rd!"}).status_code == 200


def test_invite_flow(app, admin: TestClient):
    m = add_member(admin, "小红")
    inv = admin.post(f"/api/members/{m['id']}/invite").json()
    assert inv["url"] == f"http://test/invite/{inv['token']}"
    anon = TestClient(app)
    assert anon.get(f"/api/invites/{inv['token']}").json()["member_name"] == "小红"
    assert anon.get("/api/invites/not-a-token").status_code == 404
    assert anon.post(f"/api/invites/{inv['token']}/accept", json={"username": "captain", "password": MEMBER_PW}).status_code == 409
    r = anon.post(f"/api/invites/{inv['token']}/accept", json={"username": "xiaohong", "password": MEMBER_PW})
    assert r.status_code == 201
    assert r.json()["role"] == "member" and r.json()["member_id"] == m["id"] and r.json()["member_name"] == "小红"
    assert anon.get("/api/me").status_code == 200
    # 一次性
    assert TestClient(app).get(f"/api/invites/{inv['token']}").status_code == 410
    # 已有账号的成员不能再邀请
    assert admin.post(f"/api/members/{m['id']}/invite").status_code == 409
    account = admin.get("/api/members").json()[0]["account"]
    assert account["username"] == "xiaohong" and account["is_active"]


def test_expired_invite(app, admin: TestClient):
    m = add_member(admin, "小刚")
    token = admin.post(f"/api/members/{m['id']}/invite").json()["token"]
    with app.state.session_factory() as db:
        inv = db.scalar(select(Invite))
        inv.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    r = TestClient(app).get(f"/api/invites/{token}")
    assert r.status_code == 410 and "过期" in r.json()["detail"]
    # 重新生成后旧链接作废、新链接可用
    new_token = admin.post(f"/api/members/{m['id']}/invite").json()["token"]
    assert TestClient(app).get(f"/api/invites/{token}").status_code == 404
    assert TestClient(app).get(f"/api/invites/{new_token}").status_code == 200


def test_reset_password_and_deactivate(app, admin: TestClient):
    m = add_member(admin, "小丽")
    client = invite_and_accept(app, admin, m, "xiaoli")
    r = admin.post(f"/api/members/{m['id']}/reset-password")
    assert r.status_code == 200 and len(r.json()["temp_password"]) >= 10
    assert client.get("/api/me").status_code == 401  # 旧会话失效
    login = TestClient(app).post("/api/auth/login", json={"username": "xiaoli", "password": r.json()["temp_password"]})
    assert login.status_code == 200

    fresh = TestClient(app)
    fresh.post("/api/auth/login", json={"username": "xiaoli", "password": r.json()["temp_password"]})
    assert admin.patch(f"/api/members/{m['id']}/account", json={"is_active": False}).json()["is_active"] is False
    assert fresh.get("/api/me").status_code == 401  # 停用后立即失效
    again = TestClient(app).post("/api/auth/login", json={"username": "xiaoli", "password": r.json()["temp_password"]})
    assert again.status_code == 403
    assert admin.patch(f"/api/members/{m['id']}/account", json={"is_active": True}).status_code == 200
    assert TestClient(app).post("/api/auth/login", json={"username": "xiaoli", "password": r.json()["temp_password"]}).status_code == 200


def test_member_without_account_cannot_reset(admin: TestClient):
    m = add_member(admin, "无账号")
    assert admin.post(f"/api/members/{m['id']}/reset-password").status_code == 404
    assert admin.patch(f"/api/members/{m['id']}/account", json={"is_active": False}).status_code == 404
