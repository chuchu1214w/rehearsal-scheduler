"""求解任务执行体:在子进程(或测试时同步)中运行,把进度与结果写回 solve_jobs / schedule_versions。

子进程通过 multiprocessing(spawn)启动,只接收数据库地址与任务 id,自行建立连接。
"""

from __future__ import annotations

import os
import traceback
from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from solver.lexicographic import SolveOptions, solve
from solver.types import Problem, SolveResult
from solver.validator import compute_metrics

from .db import make_engine, make_session_factory
from .models import Event, RehearsalSession, ScheduleVersion, SolveJob
from .services import event_problem, ready_song_codes, summarize_diagnosis
from .utils import utcnow


def _mark_failed(db: Session, job_id: int, message: str) -> None:
    job = db.get(SolveJob, job_id)
    if job is None:
        return
    job.status = "failed"
    job.error = message[-2000:]
    job.progress = ""
    job.finished_at = utcnow()
    db.commit()


def store_result(db: Session, job: SolveJob, problem: Problem, result: SolveResult) -> None:
    event: Event = job.event
    job.stage_records = [asdict(r) for r in result.stages]
    job.attempts = list(result.attempts)
    job.ladder_level_used = result.level_used
    job.finished_at = utcnow()
    job.progress = ""
    if result.feasible:
        next_no = (db.scalar(select(func.max(ScheduleVersion.version_no)).where(ScheduleVersion.event_id == event.id)) or 0) + 1
        version = ScheduleVersion(
            event_id=event.id,
            version_no=next_no,
            source="solver",
            job_id=job.id,
            status="draft",
            level_used=result.level_used,
            exact_optimum=result.exact,
            objective_values=dict(result.objective_values),
            stage_records=job.stage_records,
            validation_errors=list(result.validation_errors),
            metrics=compute_metrics(problem, result.sessions),
            skipped_songs=list(job.skipped_songs or []),
            created_by=job.created_by,
        )
        db.add(version)
        db.flush()
        name_to_id = {p.member.display_name: p.member_id for p in event.participants}
        code_to_song = {s.code: s for s in event.songs}
        for s in result.sessions:
            song = code_to_song.get(s.song_code) if s.song_code else None
            db.add(
                RehearsalSession(
                    version_id=version.id,
                    song_id=song.id if song else None,
                    kind=s.kind,
                    task_no=s.task_no,
                    date=s.date,
                    start_slot=s.start,
                    duration_slots=s.duration,
                    absent_member_ids=[name_to_id[m] for m in s.absent_members if m in name_to_id],
                    attendance={str(name_to_id[m]): [a, b] for m, (a, b) in (s.attendance or {}).items() if m in name_to_id} or None,
                )
            )
        job.status = "succeeded"
        job.version_id = version.id
        level = f"层级 L{result.level_used}" if result.level_used is not None else ""
        job.summary = f"已生成草稿 v{next_no}({'严格最优' if result.exact else '非严格最优'}{'、' + level if level else ''})"
    else:
        job.status = "infeasible"
        job.diagnosis = result.diagnosis
        job.summary = summarize_diagnosis(result.diagnosis)
    db.commit()


def run_job(database_url: str, job_id: int, workers: int = 0) -> None:
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)

    with session_factory() as db:
        job = db.get(SolveJob, job_id)
        if job is None or job.status not in ("queued", "running"):
            return
        job.status = "running"
        job.started_at = utcnow()
        job.progress = "准备曲目与候选时段"
        db.commit()
        try:
            event = job.event
            only_ready = bool((job.options or {}).get("only_ready_songs"))
            codes = set(ready_song_codes(event)) if only_ready else None
            job.skipped_songs = [s.code for s in event.songs if codes is not None and s.code not in codes]
            db.commit()
            problem = event_problem(event, song_codes=codes)
            errors, _warnings = problem.validate()
            if errors:
                _mark_failed(db, job_id, "数据有误:" + ";".join(errors))
                return
            if not problem.songs:
                _mark_failed(db, job_id, "没有可排的曲目(所有曲目都有人员尚未提交空闲)")
                return
        except Exception:  # noqa: BLE001
            _mark_failed(db, job_id, traceback.format_exc())
            return

    def progress(message: str) -> None:
        with session_factory() as d:
            j = d.get(SolveJob, job_id)
            if j is not None and j.status == "running":
                j.progress = message
                d.commit()

    try:
        n_workers = workers or min(8, os.cpu_count() or 4)
        result = solve(problem, SolveOptions(progress=progress, workers=n_workers, time_limit=problem.config.stage_time_limit))
    except Exception:  # noqa: BLE001
        with session_factory() as db:
            _mark_failed(db, job_id, traceback.format_exc())
        return

    with session_factory() as db:
        job = db.get(SolveJob, job_id)
        if job is None or job.status != "running":
            return  # 已被取消
        try:
            store_result(db, job, problem, result)
        except Exception:  # noqa: BLE001
            db.rollback()
            _mark_failed(db, job_id, traceback.format_exc())
