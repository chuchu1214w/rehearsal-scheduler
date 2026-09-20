"""应用工厂。uvicorn 入口见 app/asgi.py。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .api import ROUTERS
from .config import Settings
from .db import SchemaOutdated, init_db, make_engine, make_session_factory
from .models import SolveJob
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
        version="0.2.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    _fail_stale_jobs(app.state.session_factory)
    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    _mount_frontend(app, settings.frontend_dist)
    return app


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
