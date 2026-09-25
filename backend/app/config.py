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
    solver_mode: str = "subprocess"  # subprocess:独立子进程(生产);inline:同步执行(测试)
    solver_workers: int = 0
    reminders_interval_minutes: int = 30  # 定时提醒检查间隔;0 = 关闭(测试用)
    backup_keep_days: int = 14  # 每日自动备份保留天数;0 = 不自动备份
    push_contact: str = "mailto:season@example.com"  # Web Push 的 VAPID 联系方式(推送服务出问题时联系用)
    # 原生 App(Capacitor)相关
    cors_origins: list[str] = [
        "capacitor://localhost",
        "https://localhost",
        "http://localhost",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    apple_team_id: str = ""  # Apple Developer Team ID(Universal Links 的 AASA 需要)
    ios_bundle_id: str = ""  # 如 app.timetomeet.season
    apns_key_p8: str = ""  # APNs Auth Key 的 PEM 内容(优先)
    apns_key_path: str = ""  # 或 .p8 文件路径(本机调试用)
    apns_key_id: str = ""
    apns_sandbox: bool = False  # Xcode 直装的 Debug 包走沙箱;TestFlight / App Store 走生产  # 0 = min(8, CPU 核数)

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
        if v := env.get("SOLVER_MODE"):
            kwargs["solver_mode"] = v
        if v := env.get("SOLVER_WORKERS"):
            kwargs["solver_workers"] = int(v)
        if v := env.get("REMINDERS_INTERVAL_MINUTES"):
            kwargs["reminders_interval_minutes"] = int(v)
        if v := env.get("BACKUP_KEEP_DAYS"):
            kwargs["backup_keep_days"] = int(v)
        if v := env.get("PUSH_CONTACT"):
            kwargs["push_contact"] = v
        if v := env.get("CORS_ORIGINS"):
            kwargs["cors_origins"] = [x.strip() for x in v.split(",") if x.strip()]
        for key, name in (
            ("apple_team_id", "APPLE_TEAM_ID"),
            ("ios_bundle_id", "IOS_BUNDLE_ID"),
            ("apns_key_p8", "APNS_KEY_P8"),
            ("apns_key_path", "APNS_KEY_PATH"),
            ("apns_key_id", "APNS_KEY_ID"),
        ):
            if v := env.get(name):
                kwargs[key] = v
        if "APNS_SANDBOX" in env:
            kwargs["apns_sandbox"] = _bool(env.get("APNS_SANDBOX"), False)
        return cls(**kwargs)
