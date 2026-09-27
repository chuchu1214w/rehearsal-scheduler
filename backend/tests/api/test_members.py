from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import AvailabilityDay
from tests.api.conftest import MEMBER_PW, add_member, make_event


def test_member_crud(admin: TestClient):
    a = add_member(admin, "  衿 ", aliases=["jin", "jin", " 衿 "], note="队长")
    assert a["display_name"] == "衿" and a["aliases"] == ["jin"] and a["account"] is None
    b = add_member(admin, "菁")
    assert [m["display_name"] for m in admin.get("/api/members").json()] == ["衿", "菁"]
    assert a["sort_order"] < b["sort_order"]

    r = admin.patch(f"/api/members/{b['id']}", json={"aliases": ["Jing"], "active": False, "note": "远途"})
    assert r.status_code == 200 and r.json()["aliases"] == ["Jing"] and r.json()["active"] is False

    assert admin.delete(f"/api/members/{b['id']}").status_code == 204
    assert len(admin.get("/api/members").json()) == 1
    assert admin.patch("/api/members/999", json={"note": "x"}).status_code == 404


def test_name_and_alias_conflicts(admin: TestClient):
    add_member(admin, "Ash", aliases=["ash"])
    assert admin.post("/api/members", json={"display_name": "Ash"}).status_code == 409
    assert admin.post("/api/members", json={"display_name": "ash"}).status_code == 409  # 与别名冲突
    other = add_member(admin, "Siri")
    assert admin.patch(f"/api/members/{other['id']}", json={"aliases": ["Ash"]}).status_code == 409
    assert admin.post("/api/members", json={"display_name": "   "}).status_code == 422


def test_cannot_delete_referenced_member(app, admin: TestClient, member):
    _client, m = member
    assert admin.delete(f"/api/members/{m['id']}").status_code == 409  # 有账号
    other = add_member(admin, "小张")
    ev = make_event(admin, member_ids=[other["id"]])
    assert ev["member_count"] == 1
    r = admin.delete(f"/api/members/{other['id']}")
    assert r.status_code == 409 and "演出" in r.json()["detail"]


def test_cannot_open_account_for_inactive_member(admin: TestClient):
    m = add_member(admin, "停用者", active=False)
    assert admin.post(f"/api/members/{m['id']}/account", json={"password": "Member123!"}).status_code == 409


def test_delete_member_after_self_deleted_account_and_removal(admin: TestClient, member):
    """成员填过空闲、自行注销账号、被移出演出后,管理员可以把他从名册删除。"""
    client, m = member
    ev = make_event(admin, member_ids=[m["id"]])
    url = f"/api/events/{ev['id']}/availability/{m['id']}"
    assert client.put(url, json={"days": {"2026-09-04": "1" * 13}, "submit": True}).status_code == 200
    assert client.post("/api/me/delete", json={"password": MEMBER_PW}).status_code == 204
    assert admin.delete(f"/api/members/{m['id']}").status_code == 409  # 仍在演出中
    assert admin.delete(f"/api/events/{ev['id']}/members/{m['id']}").status_code == 204
    assert admin.delete(f"/api/members/{m['id']}").status_code == 204
    assert all(x["id"] != m["id"] for x in admin.get("/api/members").json())


def test_delete_member_with_leftover_availability(app, admin: TestClient):
    """旧版本移出演出时留下的空闲行,不应让删除名册成员报 500。"""
    m = add_member(admin, "旧人")
    ev = make_event(admin)
    with app.state.session_factory() as db:
        db.add(AvailabilityDay(event_id=ev["id"], member_id=m["id"], date=date(2026, 9, 4), slots="1" * 13))
        db.commit()
    assert admin.delete(f"/api/members/{m['id']}").status_code == 204
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AvailabilityDay)) == 0
