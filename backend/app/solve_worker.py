"""求解任务执行体:在子进程(或测试时同步)中运行,把进度与结果写回 solve_jobs / schedule_versions。

子进程通过 multiprocessing(spawn)启动,只接收数据库地址与任务 id,自行建立连接。
"""

from __future__ import annotations

import os
import traceback
from dataclasses import asdict, replace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from solver.lexicographic import SolveOptions, solve
from solver.types import Problem, SolveResult
from solver.validator import compute_metrics

from .db import make_engine, make_session_factory
from .models import Event, RehearsalSession, ScheduleVersion, SolveJob
from .operations import _live_report as live_report
from .operations import _readable as readable
from .schedule_edit import copy_locations, copy_locks, locked_fixed_sessions
from .services import event_problem, published_version, ready_song_codes, summarize_diagnosis
from .utils import utcnow

# 锁定场次自身的时间类冲突:窗口 / 禁排、成员没空、成员重叠、单日上限、同曲同天
LOCKED_CHECK_CODES = {"V-01", "V-02", "V-04", "V-05", "V-06"}


def _locked_in(row, codes: set[str]) -> bool:  # noqa: ANN001
    """本次重排要保留的锁定正规场次。"""
    return row.locked and row.kind == "formal" and row.song is not None and row.song.code in codes


def keep_adjusted_durations(problem: Problem, base: ScheduleVersion, rule_fixed: tuple = ()) -> tuple:
    """锁定后重排:锁定的场次原样保留,其余按曲目当前的场次方案重排。

    求解器要求每个固定场次(锁定的场次、「固定场次」要求)都对应方案里一个同样时长的任务。管理员可能手动
    拉长 / 缩短、增删过场次,对不上时只对涉及的曲目调整方案(保持任务顺序):
    1. 锁定场次占用它原来的那一场;时长不同时把那一场改成它的时长(拉长 / 缩短的情况);
    2. 其余(加出来的场次、「固定场次」要求)先找时长相同的剩余任务,再替换时长最接近的;
    3. 方案里没有剩余任务时再加一场(加场后锁定的情况)。
    没有固定场次的曲目完全按当前方案(包括求解后才改的方案)。
    """
    needs: dict[str, list[tuple[int, int | None]]] = {}  # 曲目 → [(时长, 原来第几场)]
    seen: set[tuple] = set()
    for s in base.sessions:
        if s.kind == "formal" and s.locked and s.song is not None:
            needs.setdefault(s.song.code, []).append((s.duration_slots, s.task_no))
            seen.add((s.song.code, s.date, s.start_slot, s.duration_slots))
    for fx in rule_fixed:
        if (fx.song_code, fx.date, fx.start, fx.duration) not in seen:
            needs.setdefault(fx.song_code, []).append((fx.duration, None))
    out = []
    for song in problem.songs:
        want = needs.get(song.code)
        if not want:
            out.append(song)
            continue
        plan = list(song.durations(problem.config))
        slots = list(plan)
        used = [False] * len(slots)
        pending = []
        # 1) 锁定场次先占它原来那一场(时长不同就把那一场改成它的时长:拉长 / 缩短的情况)
        for d, hint in sorted(want, key=lambda w: w[1] is None):
            if hint and 0 < hint <= len(slots) and not used[hint - 1]:
                slots[hint - 1] = d
                used[hint - 1] = True
            else:
                pending.append(d)
        # 2) 其余(加出来的场次、「固定场次」要求):先找时长相同的剩余任务,再替换时长最接近的,都没有就加一场
        for d in pending:
            free = [k for k in range(len(slots)) if not used[k]]
            same = [k for k in free if slots[k] == d]
            if same:
                idx = same[0]
            elif free:
                idx = min(free, key=lambda k: (abs(slots[k] - d), k))
                slots[idx] = d
            else:
                slots.append(d)
                used.append(True)
                continue
            used[idx] = True
        out.append(replace(song, session_plan=tuple(slots)) if slots != plan else song)
    return tuple(out)


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
    if result.feasible or result.partial:
        next_no = (db.scalar(select(func.max(ScheduleVersion.version_no)).where(ScheduleVersion.event_id == event.id)) or 0) + 1
        base_id = (job.options or {}).get("base_version_id")
        base = db.get(ScheduleVersion, base_id) if base_id else None
        version = ScheduleVersion(
            event_id=event.id,
            version_no=next_no,
            source="partial" if not result.feasible else "resolve" if base is not None else "solver",
            parent_version_id=base.id if base is not None else None,
            job_id=job.id,
            status="draft",
            level_used=result.level_used,
            exact_optimum=result.exact and result.feasible,  # 部分排程不算最优解
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
        db.flush()
        db.refresh(version)
        if base is not None:
            copy_locks(base, version)
        source = base or published_version(event)
        if source is not None:
            copy_locations(source, version)  # 时间没变的场次,地点沿用
        job.version_id = version.id
        if not result.feasible:
            # 无解但先排出了能排的场次:任务仍记为无解,草稿供查看与手动补排
            job.status = "infeasible"
            job.diagnosis = {**(result.diagnosis or {}), "部分排程": {"版本号": next_no, "未排": list(result.unscheduled)}}
            missing = f"{'允许缺席时' if result.level_used else ''}还差 {len(result.unscheduled)} 场"
            job.summary = summarize_diagnosis(result.diagnosis) + f";已先把能排的场次存为草稿 v{next_no}({missing})"
        else:
            job.status = "succeeded"
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
            base_id = (job.options or {}).get("base_version_id")
            base = db.get(ScheduleVersion, base_id) if base_id else None
            if base is not None:
                codes_in = {s.code for s in problem.songs}
                # 锁定的场次本身有硬冲突(草稿允许暂存冲突)就无法原样保留:先说清楚是哪几场。
                # 只看「只涉及本次要排的锁定场次」的时间类冲突;场数 / 缺席上限这类与整版场次数有关的,重排后会重新满足
                rows, report = live_report(event, base)
                stuck = [
                    readable(i.message)
                    for i in report.issues
                    if i.message.split(" ", 1)[0] in LOCKED_CHECK_CODES
                    and i.sessions
                    and all(_locked_in(rows[k], codes_in) for k in i.sessions)
                ]
                if stuck:
                    msg = "锁定的场次本身有冲突,重排无法原样保留:" + ";".join(stuck[:3]) + "。请先解锁或调整这些场次。"
                    _mark_failed(db, job_id, msg)
                    return
                fixed_all = locked_fixed_sessions(event, base)
                fixed = tuple(f for f in fixed_all if f.song_code in codes_in)  # 跳过的曲目(未就绪)不参与重排
                problem.songs = keep_adjusted_durations(problem, base, problem.rules.fixed_sessions)
                problem.rules = replace(problem.rules, fixed_sessions=problem.rules.fixed_sessions + fixed)
                skipped_locked = len(fixed_all) - len(fixed)
                extra = f"(另有 {skipped_locked} 场属于本次跳过的曲目)" if skipped_locked else ""
                job.progress = f"保留 {len(fixed)} 场锁定,重排其余{extra}"
                db.commit()
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
