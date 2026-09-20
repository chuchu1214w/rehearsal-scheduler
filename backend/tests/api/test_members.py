from fastapi.testclient import TestClient

from tests.api.conftest import add_member, make_event


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
    ev = make_event(admin)
    admin.put(f"/api/events/{ev['id']}/members", json={"member_ids": [other["id"]]})
    r = admin.delete(f"/api/members/{other['id']}")
    assert r.status_code == 409 and "活动" in r.json()["detail"]


def test_cannot_invite_inactive_member(admin: TestClient):
    m = add_member(admin, "停用者", active=False)
    assert admin.post(f"/api/members/{m['id']}/invite").status_code == 409
