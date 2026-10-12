"""AI 调度员(开发文档 §5.11):无解时让 Claude 想办法、给出方案;管理员逐条允许后执行。仅管理员。"""

from __future__ import annotations

import multiprocessing
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import advisor
from ..deps import DB, AdminUser, SettingsDep
from ..models import AdvisorRun
from ..schemas import AdvisorApplyIn, AdvisorRunOut
from ..utils import utcnow
from .events import load_event

router = APIRouter(tags=["advisor"])

RUNNING: dict[int, Any] = {}


def serialize_run(run: AdvisorRun) -> AdvisorRunOut:
    elapsed = None
    if run.started_at is not None:
        end = run.finished_at or datetime.utcnow()
        elapsed = round((end - run.started_at).total_seconds(), 1)
    return AdvisorRunOut(
        id=run.id,
        event_id=run.event_id,
        status=run.status,  # type: ignore[arg-type]
        progress=run.progress or "",
        log=list(run.log or []),
        proposal=run.proposal,
        applied=list(run.applied or []),
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
        elapsed_seconds=elapsed,
        cost_usd=advisor.estimate_cost(run.usage),
    )


def _refresh(db: Session, run: AdvisorRun) -> AdvisorRun:
    proc = RUNNING.get(run.id)
    if run.status in ("queued", "running") and proc is not None and not proc.is_alive():
        db.refresh(run)
        if run.status in ("queued", "running"):
            run.status = "failed"
            run.error = "AI 调度员进程意外退出"
            run.finished_at = utcnow()
            db.commit()
        RUNNING.pop(run.id, None)
    return run


def _get_run(db: Session, run_id: int, admin) -> AdvisorRun:  # noqa: ANN001
    run = db.get(AdvisorRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="AI 调度记录不存在")
    load_event(db, run.event_id, admin)
    return _refresh(db, run)


@router.post("/events/{event_id}/advisor", response_model=AdvisorRunOut, status_code=202)
def start_advisor(event_id: int, db: DB, admin: AdminUser, settings: SettingsDep) -> AdvisorRunOut:
    event = load_event(db, event_id, admin)
    if not settings.anthropic_api_key and advisor.CLIENT_FACTORY is None:
        raise HTTPException(status_code=503, detail="AI 调度员还没开通:服务器需要配置 Claude API 密钥(ANTHROPIC_API_KEY)")
    if not event.participants or not event.songs:
        raise HTTPException(status_code=422, detail="先添加人员和曲目")
    active = db.scalar(select(AdvisorRun).where(AdvisorRun.event_id == event.id, AdvisorRun.status.in_(["queued", "running"])))
    if active is not None and _refresh(db, active).status in ("queued", "running"):
        raise HTTPException(status_code=409, detail="AI 调度员正在工作")
    run = AdvisorRun(event_id=event.id, created_by=admin.id)
    db.add(run)
    db.commit()
    args = (settings.database_url, run.id, settings.solver_workers, settings.advisor_model)
    if settings.solver_mode == "inline":
        advisor.run_advisor(*args)
        db.refresh(run)
    else:
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=advisor.run_advisor, args=args, daemon=True)
        proc.start()
        RUNNING[run.id] = proc
    return serialize_run(run)


@router.get("/events/{event_id}/advisor/latest", response_model=AdvisorRunOut)
def latest_advisor(event_id: int, db: DB, admin: AdminUser) -> AdvisorRunOut:
    event = load_event(db, event_id, admin)
    run = db.scalar(select(AdvisorRun).where(AdvisorRun.event_id == event.id).order_by(AdvisorRun.id.desc()))
    if run is None:
        raise HTTPException(status_code=404, detail="还没有用过 AI 调度员")
    return serialize_run(_refresh(db, run))


@router.get("/advisor-runs/{run_id}", response_model=AdvisorRunOut)
def get_advisor(run_id: int, db: DB, admin: AdminUser) -> AdvisorRunOut:
    return serialize_run(_get_run(db, run_id, admin))


@router.post("/advisor-runs/{run_id}/cancel", response_model=AdvisorRunOut)
def cancel_advisor(run_id: int, db: DB, admin: AdminUser) -> AdvisorRunOut:
    run = _get_run(db, run_id, admin)
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail="已经结束,无法取消")
    proc = RUNNING.pop(run.id, None)
    if proc is not None and proc.is_alive():
        proc.terminate()
    run.status = "cancelled"
    run.progress = ""
    run.finished_at = utcnow()
    db.commit()
    return serialize_run(run)


def _done_run(db: Session, run_id: int, admin) -> AdvisorRun:  # noqa: ANN001
    run = _get_run(db, run_id, admin)
    if run.status != "done" or not run.proposal:
        raise HTTPException(status_code=409, detail="还没有可执行的方案")
    return run


@router.post("/advisor-runs/{run_id}/apply", response_model=AdvisorRunOut)
def apply_advisor(run_id: int, body: AdvisorApplyIn, db: DB, admin: AdminUser) -> AdvisorRunOut:
    """管理员允许后执行所选调整(修改要求 / 参数 / 场次方案)。"""
    run = _done_run(db, run_id, admin)
    advisor.apply_selected(db, run, body.indices)
    db.commit()
    return serialize_run(run)
