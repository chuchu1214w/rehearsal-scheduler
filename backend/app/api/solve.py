"""排程求解(交互设计 A6)与排练表版本读取(A7 的数据部分)。仅管理员。"""

from __future__ import annotations

import multiprocessing
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import DB, AdminUser, SettingsDep
from ..models import ScheduleVersion, SolveJob
from ..schemas import JobOut, SolveIn, VersionDetailOut, VersionOut
from ..services import serialize_job, serialize_version
from ..solve_worker import run_job
from ..utils import utcnow
from .events import load_event

router = APIRouter(tags=["solve"])

# 正在运行的子进程(单实例部署;服务重启后由 main.py 把残留任务标记为失败)
RUNNING: dict[int, Any] = {}


def _active_job(db: Session, event_id: int) -> SolveJob | None:
    return db.scalar(
        select(SolveJob).where(SolveJob.event_id == event_id, SolveJob.status.in_(["queued", "running"])).order_by(SolveJob.id.desc())
    )


def _refresh_liveness(db: Session, job: SolveJob) -> SolveJob:
    """子进程意外退出时,把任务标记为失败。"""
    proc = RUNNING.get(job.id)
    if job.status in ("queued", "running") and proc is not None and not proc.is_alive():
        db.refresh(job)
        if job.status in ("queued", "running"):
            job.status = "failed"
            job.error = "求解进程意外退出"
            job.finished_at = utcnow()
            db.commit()
        RUNNING.pop(job.id, None)
    return job


@router.post("/events/{event_id}/solve", response_model=JobOut, status_code=202)
def start_solve(event_id: int, body: SolveIn, db: DB, admin: AdminUser, settings: SettingsDep) -> JobOut:
    event = load_event(db, event_id, admin)
    active = _active_job(db, event.id)
    if active is not None:
        _refresh_liveness(db, active)
        if active.status in ("queued", "running"):
            raise HTTPException(status_code=409, detail="已有求解任务在进行中")
    if not event.participants or not event.songs:
        raise HTTPException(status_code=422, detail="先添加人员和曲目,再开始求解")
    job = SolveJob(
        event_id=event.id,
        options={"only_ready_songs": body.only_ready_songs},
        params_snapshot={"settings": event.settings, "day_start_hour": event.day_start_hour, "day_end_hour": event.day_end_hour},
        created_by=admin.id,
    )
    db.add(job)
    db.commit()
    if settings.solver_mode == "inline":
        run_job(settings.database_url, job.id, settings.solver_workers)
        db.refresh(job)
    else:
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=run_job, args=(settings.database_url, job.id, settings.solver_workers), daemon=True)
        proc.start()
        RUNNING[job.id] = proc
    return serialize_job(job)


@router.get("/events/{event_id}/solve-jobs/latest", response_model=JobOut)
def latest_job(event_id: int, db: DB, admin: AdminUser) -> JobOut:
    event = load_event(db, event_id, admin)
    job = db.scalar(select(SolveJob).where(SolveJob.event_id == event.id).order_by(SolveJob.id.desc()))
    if job is None:
        raise HTTPException(status_code=404, detail="还没有求解过")
    return serialize_job(_refresh_liveness(db, job))


def _get_job(db: Session, job_id: int, admin) -> SolveJob:  # noqa: ANN001
    job = db.get(SolveJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="求解任务不存在")
    load_event(db, job.event_id, admin)
    return job


@router.get("/solve-jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: DB, admin: AdminUser) -> JobOut:
    return serialize_job(_refresh_liveness(db, _get_job(db, job_id, admin)))


@router.post("/solve-jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, db: DB, admin: AdminUser) -> JobOut:
    job = _get_job(db, job_id, admin)
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail="任务已结束,无法取消")
    proc = RUNNING.pop(job.id, None)
    if proc is not None and proc.is_alive():
        proc.terminate()
    job.status = "cancelled"
    job.progress = ""
    job.finished_at = utcnow()
    db.commit()
    return serialize_job(job)


@router.get("/events/{event_id}/schedules", response_model=list[VersionOut])
def list_versions(event_id: int, db: DB, admin: AdminUser) -> list[VersionOut]:
    event = load_event(db, event_id, admin)
    return [serialize_version(event, v) for v in reversed(event.versions)]  # type: ignore[misc]


@router.get("/schedules/{version_id}", response_model=VersionDetailOut)
def get_version(version_id: int, db: DB, admin: AdminUser) -> VersionDetailOut:
    version = db.get(ScheduleVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="排练表版本不存在")
    event = load_event(db, version.event_id, admin)
    return serialize_version(event, version, detail=True)  # type: ignore[return-value]
