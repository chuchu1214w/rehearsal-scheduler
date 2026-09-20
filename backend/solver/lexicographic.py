"""字典序分层求解与缺席降级阶梯(开发文档 §5.6、§5.7)。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .candidates import build_candidates, make_tasks
from .diagnosis import diagnose
from .evaluation import EvalChoice, choose_evaluation, diagnose_evaluation
from .model import FixedSessionError, ModelBundle, build_model
from .types import (
    KIND_FORMAL,
    OBJECTIVE_LABELS,
    EventConfig,
    Problem,
    Session,
    SolveResult,
    StageRecord,
    Task,
)
from .validator import validate_schedule

Progress = Callable[[str], None]


@dataclass
class SolveOptions:
    time_limit: float | None = None  # 每阶段秒数;None 用活动参数
    workers: int | None = None
    seed: int | None = None
    diagnose_on_failure: bool = True
    progress: Progress | None = None


def new_solver(config: EventConfig, opts: SolveOptions, time_limit: float | None = None) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit or opts.time_limit or config.stage_time_limit)
    solver.parameters.num_workers = int(opts.workers or config.workers)
    solver.parameters.random_seed = int(config.seed if opts.seed is None else opts.seed)
    solver.parameters.log_search_progress = False
    return solver


def _say(opts: SolveOptions, msg: str) -> None:
    if opts.progress:
        opts.progress(msg)


def _apply_hints(bundle: ModelBundle, solver: cp_model.CpSolver) -> None:
    bundle.model.clear_hints()
    for v in bundle.x.values():
        bundle.model.add_hint(v, solver.value(v))


def run_stages(
    problem: Problem,
    bundle: ModelBundle,
    first_solver: cp_model.CpSolver,
    first_status: int,
    eval_choice: EvalChoice | None,
    opts: SolveOptions,
) -> tuple[list[StageRecord], bool, cp_model.CpSolver]:
    """按 problem.objectives 顺序逐级最小化,每级把最优值固定后再进入下一级。"""
    records = [StageRecord("feasible", "全部排完", 0, first_solver.status_name(first_status))]
    exact = first_status == cp_model.OPTIMAL
    last = first_solver
    for key in problem.objectives:
        label = OBJECTIVE_LABELS[key]
        if key == "eval_attendance":
            if eval_choice is None:
                records.append(StageRecord(key, label, None, "无可行窗口"))
            else:
                records.append(StageRecord(key, label, eval_choice.missing_hours, "枚举最优"))
            continue
        term = bundle.objective_terms.get(key)
        if term is None or term.count == 0:
            records.append(StageRecord(key, label, 0, "无适用项"))
            continue
        _say(opts, f"  优化:{label}")
        _apply_hints(bundle, last)
        bundle.model.minimize(term.expr)
        solver = new_solver(problem.config, opts)
        status = solver.solve(bundle.model)
        name = solver.status_name(status)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            records.append(StageRecord(key, label, None, name))
            exact = False
            break
        value = int(round(solver.objective_value))
        records.append(StageRecord(key, label, value, name))
        exact = exact and status == cp_model.OPTIMAL
        bundle.model.add(term.expr == value)  # 固定本级最优值,保证真正的字典序
        last = solver
    return records, exact, last


def extract_sessions(problem: Problem, bundle: ModelBundle, solver: cp_model.CpSolver) -> list[Session]:
    dates = problem.config.formal_dates
    sessions: list[Session] = []
    for task in bundle.tasks:
        for ci, c in enumerate(bundle.candidates[task.task_id]):
            if solver.value(bundle.x[(task.task_id, ci)]) == 1:
                sessions.append(
                    Session(
                        kind=KIND_FORMAL,
                        date=dates[c.date_idx],
                        start=c.start,
                        duration=c.duration,
                        song_code=task.song_code,
                        task_no=task.task_no,
                        absent_members=(c.absent_member,) if c.absent_member else (),
                    )
                )
                break
    sessions.sort(key=lambda s: (s.date, s.start, s.song_code or ""))
    return sessions


def solve(problem: Problem, opts: SolveOptions | None = None) -> SolveResult:
    opts = opts or SolveOptions()
    t0 = time.perf_counter()
    errors, warnings = problem.validate()
    if errors:
        raise ValueError("输入数据有误:\n" + "\n".join(errors))

    tasks: list[Task] = make_tasks(problem)
    eval_choice = choose_evaluation(problem)
    if eval_choice is None:
        warnings.append("评估日没有满足到场规则的窗口,评估场无法安排")
    attempts: list[dict] = []
    final: tuple[ModelBundle, cp_model.CpSolver, list[StageRecord], bool] | None = None

    for level in problem.ladder:
        tag = f"L{level.level}"
        if not level.strict and level.max_absent_sessions(len(tasks)) == 0:
            attempts.append({"层级": tag, "状态": "跳过", "说明": "缺席场次上限为 0,与严格层等价"})
            continue
        _say(opts, f"层级 {tag}:枚举候选")
        candidates = build_candidates(problem, tasks, allow_absent=not level.strict)
        zero = [t.task_id for t in tasks if not candidates[t.task_id]]
        if zero:
            attempts.append({"层级": tag, "状态": "无候选", "说明": "没有候选时段的任务:" + "、".join(zero)})
            continue
        try:
            bundle = build_model(problem, tasks, candidates, level)
        except FixedSessionError as exc:
            attempts.append({"层级": tag, "状态": "固定场次不可行", "说明": str(exc)})
            continue
        _say(opts, f"层级 {tag}:求可行解")
        solver = new_solver(problem.config, opts)
        status = solver.solve(bundle.model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            attempts.append({"层级": tag, "状态": solver.status_name(status)})
            continue
        attempts.append({"层级": tag, "状态": "可行"})
        records, exact, last = run_stages(problem, bundle, solver, status, eval_choice, opts)
        final = (bundle, last, records, exact)
        break

    if final is None:
        diagnosis = None
        if opts.diagnose_on_failure:
            _say(opts, "无可行解,开始诊断")
            diagnosis = diagnose(problem, tasks, opts)
        return SolveResult(
            feasible=False,
            level_used=None,
            exact=False,
            stages=[],
            sessions=[],
            objective_values={},
            attempts=attempts,
            diagnosis=diagnosis,
            warnings=warnings,
            elapsed_seconds=time.perf_counter() - t0,
        )

    bundle, last, records, exact = final
    sessions = extract_sessions(problem, bundle, last)
    diagnosis = None
    feasible = True
    if eval_choice is not None:
        sessions.append(eval_choice.to_session(problem))
    else:
        feasible = False
        diagnosis = {"评估场": diagnose_evaluation(problem)}

    report = validate_schedule(problem, sessions, bundle.level)
    warnings.extend(report.warnings)
    return SolveResult(
        feasible=feasible,
        level_used=bundle.level.level,
        exact=exact,
        stages=records,
        sessions=sessions,
        objective_values={r.key: r.value for r in records if r.value is not None},
        attempts=attempts,
        diagnosis=diagnosis,
        warnings=warnings,
        validation_errors=report.errors,
        elapsed_seconds=time.perf_counter() - t0,
    )
