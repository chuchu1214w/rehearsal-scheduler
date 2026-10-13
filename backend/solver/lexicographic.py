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
    partial_on_failure: bool = True  # 无解时先排出能排的场次
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


def solve_partial(
    problem: Problem, tasks: list[Task], eval_choice: EvalChoice | None, opts: SolveOptions
) -> tuple[list[Session], list[str], list[StageRecord], bool, int | None]:
    """无解时:在最宽松的层级下尽量多排场次,其余硬约束全部保留。

    返回(场次, 未排任务说明, 阶段记录, 是否严格最优, 使用层级);一场都排不上时场次为空。
    """
    level = problem.ladder[-1]
    candidates = build_candidates(problem, tasks, allow_absent=not level.strict)
    try:
        bundle = build_model(problem, tasks, candidates, level, partial=True)
    except FixedSessionError:
        return [], [], [], False, None
    term = bundle.objective_terms["missing"]
    bundle.model.minimize(term.expr)
    solver = new_solver(problem.config, opts)
    status = solver.solve(bundle.model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], [], [], False, None
    value = int(round(solver.objective_value))
    bundle.model.add(term.expr == value)
    records, exact, last = run_stages(problem, bundle, solver, status, eval_choice, opts)
    records[0] = StageRecord("missing", OBJECTIVE_LABELS["missing"], value // 1000, solver.status_name(status))
    sessions = extract_sessions(problem, bundle, last)
    assert bundle.scheduled is not None
    unscheduled = []
    for t in bundle.tasks:
        if last.value(bundle.scheduled[t.task_id]) == 0:
            song = problem.song(t.song_code)
            unscheduled.append(f"{song.code}({song.name})一场 {t.duration} 小时")
    return sessions, unscheduled, records, exact, level.level


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
        sessions: list[Session] = []
        unscheduled: list[str] = []
        records: list[StageRecord] = []
        exact = False
        level_used = None
        errors_: list[str] = []
        if opts.partial_on_failure:
            _say(opts, "先排出能排的场次")
            sessions, unscheduled, records, exact, level_used = solve_partial(problem, tasks, eval_choice, opts)
            if sessions:
                if eval_choice is not None:
                    sessions.append(eval_choice.to_session(problem))
                report = validate_schedule(problem, sessions, problem.ladder[-1])
                # 场次数不足(V-03)只作提醒;其余硬问题照常保留
                errors_ = list(report.errors)
                warnings.extend(report.warnings)
        return SolveResult(
            feasible=False,
            level_used=level_used,
            exact=exact,
            stages=records,
            sessions=sessions,
            objective_values={r.key: r.value for r in records if r.value is not None},
            attempts=attempts,
            diagnosis=diagnosis,
            warnings=warnings,
            validation_errors=errors_,
            elapsed_seconds=time.perf_counter() - t0,
            partial=bool(sessions),
            unscheduled=unscheduled,
        )

    bundle, last, records, exact = final
    sessions = extract_sessions(problem, bundle, last)
    diagnosis = None
    feasible = True
    if eval_choice is not None:
        sessions.append(eval_choice.to_session(problem))
    else:
        feasible = False
        diagnosis = {"评估场": {**diagnose_evaluation(problem), "可行": False}}

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
