"""应用工厂。uvicorn 入口见 app/asgi.py。"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from . import push
from .api import PUBLIC_ROUTERS, ROUTERS
from .apns import ApnsConfig
from .backup import backup_sqlite
from .config import Settings
from .db import SchemaOutdated, init_db, make_engine, make_session_factory
from .models import SCHEMA_VERSION, SolveJob
from .utils import utcnow


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    try:
        init_db(engine)
    except SchemaOutdated as exc:
        raise SystemExit(f"\n❌ {exc}\n") from exc

    app = FastAPI(
        title="舞团排练排程系统",
        version="0.3.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    push.CONTACT = settings.push_contact
    push.APNS = ApnsConfig.from_settings(settings)
    # 原生 App 的 WebView 源是 capacitor://localhost,跨域调用 API 需要显式白名单(带凭据时不能用 *)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Client"],
    )
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    _fail_stale_jobs(app.state.session_factory)

    @app.get("/api/health", tags=["health"])
    def _health() -> dict:
        return {"ok": True, "version": app.version, "schema_version": SCHEMA_VERSION}

    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    for router in PUBLIC_ROUTERS:
        app.include_router(router)
    _mount_frontend(app, settings.frontend_dist)
    return app


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """后台任务:定时提醒(NOTIF-02,每 N 分钟)与每日自动备份(§10.4)。"""
    settings: Settings = app.state.settings
    tasks = []
    if settings.reminders_interval_minutes > 0:
        tasks.append(asyncio.create_task(_reminder_loop(app, settings.reminders_interval_minutes)))
    if settings.backup_keep_days > 0:
        tasks.append(asyncio.create_task(_backup_loop(settings)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def _backup_loop(settings: Settings) -> None:
    """每天自动备份一次 SQLite:启动 1 分钟后做第一次,之后每 24 小时。"""
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(backup_sqlite, settings.database_url, settings.backup_keep_days)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(24 * 3600)


async def _reminder_loop(app: FastAPI, minutes: int) -> None:
    from .notify import run_due_reminders

    while True:
        try:
            with app.state.session_factory() as db:
                await asyncio.to_thread(run_due_reminders, db, None, app.state.settings.app_timezone)
        except Exception:  # noqa: BLE001
            pass  # 提醒失败不影响服务;下一轮再试
        await asyncio.sleep(minutes * 60)


def _fail_stale_jobs(session_factory) -> None:  # noqa: ANN001
    """服务重启后,上次未完成的求解任务不可能再有结果,标记为失败。"""
    with session_factory() as db:
        stale = db.scalars(select(SolveJob).where(SolveJob.status.in_(["queued", "running"]))).all()
        for job in stale:
            job.status = "failed"
            job.error = "服务重启,任务中断;请重新求解"
            job.progress = ""
            job.finished_at = utcnow()
        if stale:
            db.commit()


def _mount_frontend(app: FastAPI, dist: Path | None) -> None:
    index = dist / "index.html" if dist else None
    if index is None or not index.exists():

        @app.get("/", include_in_schema=False)
        def _no_frontend() -> JSONResponse:
            return JSONResponse(
                {"detail": "前端尚未构建:请运行 scripts/start.sh,或在 frontend 目录执行 npm install && npm run build"},
                status_code=503,
            )

        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def _spa(path: str):  # noqa: ANN202
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return HTMLResponse(index.read_text(encoding="utf-8"))
