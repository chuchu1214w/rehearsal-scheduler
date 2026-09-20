"""AUTH-06:每个 API 端点都必须在服务端做权限校验。

从 OpenAPI 描述枚举全部端点;凡不在 PUBLIC / MEMBER_OK 名单中的,匿名必须 401、普通成员必须 403。
新增端点若忘了加权限,这个测试会失败。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

PUBLIC = {
    ("get", "/api/setup/status"),
    ("post", "/api/setup"),
    ("post", "/api/auth/login"),
}
MEMBER_OK = {
    ("post", "/api/auth/logout"),
    ("get", "/api/me"),
    ("post", "/api/me/password"),
    ("get", "/api/events"),
    ("get", "/api/events/{event_id}"),
    ("get", "/api/events/{event_id}/members"),
    ("get", "/api/events/{event_id}/songs"),
    ("get", "/api/events/{event_id}/availability/{member_id}"),
    ("put", "/api/events/{event_id}/availability/{member_id}"),
    ("post", "/api/events/{event_id}/availability/{member_id}/submit"),
    ("post", "/api/events/{event_id}/availability/{member_id}/unsubmit"),
    ("get", "/api/events/{event_id}/schedule/published"),
    ("get", "/api/me/calendar"),
    ("post", "/api/me/calendar/rotate"),
}


def _all_endpoints(app) -> list[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return sorted((method, path) for path, ops in paths.items() for method in ops if path.startswith("/api/"))


def _concrete(path: str) -> str:
    return (
        path.replace("{event_id}", "999")
        .replace("{member_id}", "999")
        .replace("{song_id}", "999")
        .replace("{rule_id}", "999")
        .replace("{job_id}", "999")
        .replace("{version_id}", "999")
    )


def test_every_endpoint_is_guarded(app, anon: TestClient, member):
    client, _m = member
    endpoints = _all_endpoints(app)
    assert len(endpoints) >= 35
    for method, path in endpoints:
        key = (method, path)
        body = {} if method in ("post", "put", "patch") else None
        r_anon = anon.request(method.upper(), _concrete(path), json=body)
        if key in PUBLIC:
            assert r_anon.status_code != 401, key
            continue
        assert r_anon.status_code == 401, (key, r_anon.status_code)
        if key == ("post", "/api/auth/logout"):
            continue  # 真正调用会把成员登出,单独在下面测试
        r_member = client.request(method.upper(), _concrete(path), json=body)
        if key in MEMBER_OK:
            assert r_member.status_code != 403, (key, r_member.status_code)
        else:
            assert r_member.status_code == 403, (key, r_member.status_code)


def test_logout_requires_login_and_member_cannot_escalate(anon: TestClient, member):
    client, _m = member
    assert anon.post("/api/auth/logout").status_code == 401
    assert client.get("/api/members").status_code == 403
    assert client.get("/api/rule-types").status_code == 403
    assert (
        client.post("/api/events", json={"name": "x", "performance_date": "2026-09-20", "formal_start_date": "2026-09-01"}).status_code
        == 403
    )
