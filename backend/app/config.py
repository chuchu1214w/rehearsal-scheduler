"""运行配置(开发文档 §10.3)。全部有默认值,本机运行不需要任何环境变量。"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]  # 仓库根目录


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    database_url: str = f"sqlite:///{ROOT / 'data' / 'app.db'}"
    app_timezone: str = "Asia/Seoul"
    public_base_url: str = "http://localhost:8000"  # 生成邀请链接、日历订阅链接时使用
    cookie_secure: bool = False  # 上线启用 HTTPS 后设为 true
    session_days: int = 14
    invite_days: int = 7
    login_max_failures: int = 5
    login_window_minutes: int = 15
    frontend_dist: Path | None = ROOT / "frontend" / "dist"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        kwargs: dict = {}
        if v := env.get("DATABASE_URL"):
            kwargs["database_url"] = v
        if v := env.get("APP_TIMEZONE"):
            kwargs["app_timezone"] = v
        if v := env.get("PUBLIC_BASE_URL"):
            kwargs["public_base_url"] = v.rstrip("/")
        if "COOKIE_SECURE" in env:
            kwargs["cookie_secure"] = _bool(env.get("COOKIE_SECURE"), False)
        if v := env.get("SESSION_DAYS"):
            kwargs["session_days"] = int(v)
        if v := env.get("INVITE_DAYS"):
            kwargs["invite_days"] = int(v)
        if v := env.get("FRONTEND_DIST"):
            kwargs["frontend_dist"] = Path(v)
        return cls(**kwargs)
