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
    return Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", frontend_dist=None, public_base_url="http://test")


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


def invite_and_accept(app, admin: TestClient, member: dict, username: str, password: str = MEMBER_PW) -> TestClient:
    inv = admin.post(f"/api/members/{member['id']}/invite")
    assert inv.status_code == 201, inv.text
    client = TestClient(app)
    r = client.post(f"/api/invites/{inv.json()['token']}/accept", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    return client


def make_event(admin: TestClient, **overrides) -> dict:
    r = admin.post("/api/events", json={**EVENT_BODY, **overrides})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def member(app, admin) -> tuple[TestClient, dict]:
    m = add_member(admin, "小明", aliases=["ming"])
    return invite_and_accept(app, admin, m, "xiaoming"), m
