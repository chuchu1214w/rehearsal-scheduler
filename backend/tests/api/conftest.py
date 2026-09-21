"""API 测试夹具:每个测试一个临时 SQLite;admin / member 各自独立的 Cookie。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ADMIN = {"username": "captain", "password": "Passw0rd!"}
MEMBER_PW = "Member123!"
EVENT_BODY = {"name": "秋季路演", "performance_date": "2026-09-20", "formal_start_date": "2026-09-04"}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        frontend_dist=None,
        public_base_url="http://test",
        solver_mode="inline",
        solver_workers=4,
        reminders_interval_minutes=0,
        backup_keep_days=0,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def anon(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def admin(app) -> TestClient:
    client = TestClient(app)
    r = client.post("/api/setup", json=ADMIN)
    assert r.status_code == 201, r.text
    return client


def add_member(admin: TestClient, name: str, **extra) -> dict:
    r = admin.post("/api/members", json={"display_name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def open_account(app, admin: TestClient, member: dict, username: str | None = None, password: str = MEMBER_PW) -> TestClient:
    """管理员开通账号,并返回以该成员身份登录的客户端。"""
    r = admin.post(f"/api/members/{member['id']}/account", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": r.json()["username"], "password": password})
    assert login.status_code == 200, login.text
    return client


def make_event(admin: TestClient, **overrides) -> dict:
    r = admin.post("/api/events", json={**EVENT_BODY, **overrides})
    assert r.status_code == 201, r.text
    return r.json()


def add_song(admin: TestClient, event_id: int, name: str, member_ids: list[int], difficulty: str = "简单", **extra) -> dict:
    r = admin.post(f"/api/events/{event_id}/songs", json={"name": name, "difficulty": difficulty, "member_ids": member_ids, **extra})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def member(app, admin) -> tuple[TestClient, dict]:
    m = add_member(admin, "小明", aliases=["ming"])
    return open_account(app, admin, m, "xiaoming"), m
