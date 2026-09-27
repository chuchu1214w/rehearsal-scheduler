"""成员自助注销账号(App Store 审核 5.1.1(v))。"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import AuthSession, Member, NativePushToken, Notification, User
from tests.api.conftest import ADMIN, MEMBER_PW


def test_member_deletes_own_account(app, admin: TestClient, member):
    client, m = member
    assert client.post("/api/me/delete", json={"password": "wrong"}).status_code == 400
    with app.state.session_factory() as db:
        uid = db.scalar(select(User.id).where(User.username == "xiaoming"))
        db.add(NativePushToken(user_id=uid, platform="ios", token="t" * 64))
        db.commit()

    assert client.post("/api/me/delete", json={"password": MEMBER_PW}).status_code == 204
    assert client.get("/api/me").status_code == 401
    assert TestClient(app).post("/api/auth/login", json={"username": "xiaoming", "password": MEMBER_PW}).status_code == 401

    with app.state.session_factory() as db:
        assert db.scalar(select(User).where(User.id == uid)) is None
        for model in (AuthSession, Notification, NativePushToken):
            assert db.scalar(select(func.count()).select_from(model).where(model.user_id == uid)) == 0
        assert db.get(Member, m["id"]) is not None  # 名册保留,管理员可重新开通

    assert any(n["title"] == "小明 注销了 App 账号" for n in admin.get("/api/notifications").json())
    assert admin.post(f"/api/members/{m['id']}/account", json={"password": MEMBER_PW}).status_code == 201


def test_admin_cannot_self_delete(admin: TestClient):
    assert admin.post("/api/me/delete", json={"password": ADMIN["password"]}).status_code == 400
    assert admin.get("/api/me").status_code == 200


def test_privacy_and_support_pages(anon: TestClient):
    for path in ("/privacy", "/support"):
        r = anon.get(path)
        assert r.status_code == 200 and "{{" not in r.text and "联系你所在舞团的管理员" in r.text
