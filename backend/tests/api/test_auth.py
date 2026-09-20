from fastapi.testclient import TestClient

from tests.api.conftest import ADMIN, MEMBER_PW, add_member, open_account


def test_setup_once(anon: TestClient):
    assert anon.get("/api/setup/status").json() == {"needs_setup": True}
    assert anon.get("/api/me").status_code == 401
    r = anon.post("/api/setup", json=ADMIN)
    assert r.status_code == 201 and r.json()["role"] == "admin" and r.json()["must_change_password"] is False
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
    # 限流按用户名计,不影响其他账号
    assert TestClient(app).post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401


def test_change_password_revokes_other_sessions(app, admin: TestClient):
    other = TestClient(app)
    assert other.post("/api/auth/login", json=ADMIN).status_code == 200
    assert admin.post("/api/me/password", json={"old_password": "nope", "new_password": "NewPassw0rd!"}).status_code == 400
    assert admin.post("/api/me/password", json={"old_password": ADMIN["password"], "new_password": "NewPassw0rd!"}).status_code == 204
    assert admin.get("/api/me").status_code == 200  # 当前会话保留
    assert other.get("/api/me").status_code == 401  # 其他会话失效
    assert TestClient(app).post("/api/auth/login", json={"username": "captain", "password": "NewPassw0rd!"}).status_code == 200


def test_open_account_flow(app, admin: TestClient):
    m = add_member(admin, "小红")
    r = admin.post(f"/api/members/{m['id']}/account", json={"password": MEMBER_PW})
    assert r.status_code == 201
    cred = r.json()
    assert cred["username"] == "小红" and cred["password"] == MEMBER_PW
    assert "http://test" in cred["copy_text"] and "小红" in cred["copy_text"]
    # 再开一次 → 409
    assert admin.post(f"/api/members/{m['id']}/account", json={"password": MEMBER_PW}).status_code == 409
    # 成员登录,首次登录需要改密码
    c = TestClient(app)
    login = c.post("/api/auth/login", json={"username": "小红", "password": MEMBER_PW})
    assert login.status_code == 200 and login.json()["must_change_password"] is True
    assert login.json()["role"] == "member" and login.json()["member_id"] == m["id"] and login.json()["member_name"] == "小红"
    assert c.post("/api/me/password", json={"old_password": MEMBER_PW, "new_password": "MyOwnPass1"}).status_code == 204
    assert c.get("/api/me").json()["must_change_password"] is False
    account = admin.get("/api/members").json()[0]["account"]
    assert account["username"] == "小红" and account["is_active"] and account["must_change_password"] is False


def test_open_account_username_rules(app, admin: TestClient):
    a = add_member(admin, "Ash")
    b = add_member(admin, "ash2")
    assert admin.post(f"/api/members/{a['id']}/account", json={"username": "captain", "password": MEMBER_PW}).status_code == 409
    assert admin.post(f"/api/members/{a['id']}/account", json={"username": "bad name", "password": MEMBER_PW}).status_code == 422
    assert admin.post(f"/api/members/{a['id']}/account", json={"username": "ash_official", "password": MEMBER_PW}).status_code == 201
    # 昵称与已有用户名冲突时自动加序号
    add_member(admin, "captain2")
    c = add_member(admin, "Captain")
    r = admin.post(f"/api/members/{c['id']}/account", json={"password": MEMBER_PW})
    assert r.status_code == 201 and r.json()["username"].lower() != "captain"
    assert admin.post(f"/api/members/{b['id']}/account", json={"password": "short"}).status_code == 422


def test_reset_password_and_deactivate(app, admin: TestClient):
    m = add_member(admin, "小丽")
    client = open_account(app, admin, m, "xiaoli")
    r = admin.post(f"/api/members/{m['id']}/account/reset", json={"password": "ResetPass1"})
    assert r.status_code == 200 and r.json()["password"] == "ResetPass1"
    assert client.get("/api/me").status_code == 401  # 旧会话失效
    login = TestClient(app).post("/api/auth/login", json={"username": "xiaoli", "password": "ResetPass1"})
    assert login.status_code == 200 and login.json()["must_change_password"] is True

    fresh = TestClient(app)
    fresh.post("/api/auth/login", json={"username": "xiaoli", "password": "ResetPass1"})
    assert admin.patch(f"/api/members/{m['id']}/account", json={"is_active": False}).json()["is_active"] is False
    assert fresh.get("/api/me").status_code == 401  # 停用后立即失效
    assert TestClient(app).post("/api/auth/login", json={"username": "xiaoli", "password": "ResetPass1"}).status_code == 403
    assert admin.patch(f"/api/members/{m['id']}/account", json={"is_active": True}).status_code == 200
    assert TestClient(app).post("/api/auth/login", json={"username": "xiaoli", "password": "ResetPass1"}).status_code == 200


def test_member_without_account_cannot_reset(admin: TestClient):
    m = add_member(admin, "无账号")
    assert admin.post(f"/api/members/{m['id']}/account/reset", json={"password": "ResetPass1"}).status_code == 404
    assert admin.patch(f"/api/members/{m['id']}/account", json={"is_active": False}).status_code == 404
