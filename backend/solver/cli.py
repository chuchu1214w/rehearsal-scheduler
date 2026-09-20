"""命令行入口:python -m solver <命令>。

sample   -o 输入.json                 写出附录 A 的示例活动(不含空闲数据)
synth    输入.json -o 输出.json        为输入文件生成合成空闲矩阵(测试/演示用)
solve    输入.json [-o 结果.json]      求解并打印排练表
validate 输入.json 结果.json           用校验器检查一份排练表
diagnose 输入.json [-o 报告.json]      只做无解诊断
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import defaultdict
from importlib import resources
from pathlib import Path

from .diagnosis import diagnose
from .lexicographic import SolveOptions, solve
from .serialization import (
    load_problem,
    load_sessions,
    problem_to_dict,
    result_to_dict,
    save_json,
)
from .synth import synthesize_availability
from .timegrid import weekday_zh
from .types import KIND_EVALUATION, OBJECTIVE_LABELS, Problem, Session, SolveResult
from .validator import validate_schedule


# ---------- 文本表格(中文宽度对齐) ----------
def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def table(rows: list[dict], columns: list[str] | None = None) -> str:
    if not rows:
        return "(空)"
    columns = columns or list(rows[0])
    cells = [[str(r.get(c, "")) for c in columns] for r in rows]
    widths = [max(_width(c), *(_width(row[i]) for row in cells)) for i, c in enumerate(columns)]
    lines = ["  ".join(_pad(c, widths[i]) for i, c in enumerate(columns))]
    lines.append("  ".join("-" * w for w in widths))
    lines.extend("  ".join(_pad(v, widths[i]) for i, v in enumerate(row)) for row in cells)
    return "\n".join(lines)


def session_rows(problem: Problem, sessions: list[Session]) -> list[dict]:
    config = problem.config
    rows = []
    for s in sorted(sessions, key=lambda s: (s.date, s.start)):
        if s.kind == KIND_EVALUATION:
            att = s.attendance or {}
            partial = [f"{m}({config.range_label(a, b - a)})" for m, (a, b) in att.items() if b - a < s.duration]
            rows.append(
                {
                    "日期": s.date.isoformat(),
                    "星期": weekday_zh(s.date),
                    "时间段": config.range_label(s.start, s.duration),
                    "类型": "全员评估",
                    "曲目": "-",
                    "时长": s.duration,
                    "成员": "全员",
                    "备注": "迟到早退:" + "、".join(partial) if partial else "全员全程",
                }
            )
            continue
        song = problem.song(s.song_code)
        rows.append(
            {
                "日期": s.date.isoformat(),
                "星期": weekday_zh(s.date),
                "时间段": config.range_label(s.start, s.duration),
                "类型": "正规",
                "曲目": f"{s.song_code} {song.name}",
                "时长": s.duration,
                "成员": "、".join(m for m in song.members if m not in s.absent_members),
                "备注": ("缺席:" + "、".join(s.absent_members)) if s.absent_members else "",
            }
        )
    return rows


def member_rows(problem: Problem, sessions: list[Session]) -> list[dict]:
    config = problem.config
    per: dict[str, dict] = {m: {"总时长": 0, "场次": 0, "排练天数": set(), "缺席": 0} for m in problem.members}
    busy: dict[tuple[str, object], set[int]] = defaultdict(set)
    for s in sessions:
        if s.kind == KIND_EVALUATION:
            continue
        for m in problem.song(s.song_code).members:
            if m in s.absent_members:
                per[m]["缺席"] += 1
                continue
            per[m]["总时长"] += s.duration
            per[m]["场次"] += 1
            per[m]["排练天数"].add(s.date)
            busy[(m, s.date)].update(s.hours)
    trips: dict[str, int] = defaultdict(int)
    gaps: dict[str, int] = defaultdict(int)
    for (m, _d), hs in busy.items():
        o = sorted(hs)
        for a, b in zip(o, o[1:], strict=False):
            if b - a - 1 > config.merge_visit_gap:
                trips[m] += 1
        gaps[m] += max(0, (o[-1] + 1 - o[0] - len(o)) - config.free_gap)
    return [
        {
            "成员": m,
            "场次": v["场次"],
            "总时长": v["总时长"],
            "排练天数": len(v["排练天数"]),
            "额外往返": trips[m],
            "长空档小时": gaps[m],
            "缺席次数": v["缺席"],
        }
        for m, v in per.items()
    ]


def print_result(problem: Problem, result: SolveResult) -> None:
    for w in result.warnings:
        print("⚠️ ", w)
    print("\n== 降级阶梯尝试 ==")
    print(table(result.attempts))
    if not result.feasible and not result.sessions:
        print("\n❌ 无可行解")
        if result.diagnosis:
            print_diagnosis(result.diagnosis)
        return
    print("\n== 分层求解 ==")
    print(table([{"目标": r.label, "值": "-" if r.value is None else r.value, "状态": r.status} for r in result.stages]))
    print(f"\n采用层级:L{result.level_used}   严格字典序最优:{'是' if result.exact else '否'}   耗时:{result.elapsed_seconds:.1f}s")
    print(f"\n== 排练表(共 {len(result.sessions)} 场)==")
    print(table(session_rows(problem, result.sessions)))
    print("\n== 成员统计 ==")
    print(table(member_rows(problem, result.sessions)))
    if result.validation_errors:
        print(f"\n❌ 校验器发现 {len(result.validation_errors)} 个错误:")
        for e in result.validation_errors:
            print("  ", e)
    else:
        print("\n✅ 校验器:0 错误")
    if not result.feasible:
        print("\n❌ 整体不可行(评估场无法安排),以上为正规排练部分")
        if result.diagnosis:
            print_diagnosis(result.diagnosis)


def print_diagnosis(diag: dict) -> None:
    print("\n== 诊断报告 ==")
    if "无候选任务" in diag:
        zero = diag["无候选任务"]
        print("无候选任务:", "、".join(zero) if zero else "无")
        mc = diag["最大覆盖"]
        print(f"最大覆盖:最多可排 {mc['最多可排场次']} / 要求 {mc['要求场次']} 场({mc['状态']})")
        print("\n各曲缺口:")
        print(table(diag["各曲缺口"]))
        print("\n只差一人的时段(前 15 条):")
        print(table(diag["只差一人的时段"][:15], ["曲目", "日期", "星期", "时间段", "只差成员", "需开放小时数"]))
        adj = diag["最小调整建议"]
        if adj.get("可行"):
            print(f"\n最小调整建议:受影响成员 {adj['受影响成员数']} 人,共开放 {adj['调整小时数']} 小时(严格最优:{adj.get('严格最优')})")
            print(table(adj["调整"]))
        else:
            print(f"\n最小调整建议:不可行({adj.get('状态')})")
    ev = diag.get("评估场")
    if ev:
        print(f"\n评估场({ev['评估日']}):可行窗口 {ev['可行窗口数']} 个,成员 {ev['成员总数']} 人")
        print("每格可到人数:", " ".join(f"{k.split('–')[0]}:{v}" for k, v in ev["每格可到人数"].items()))
        if ev["最接近的窗口"]:
            rows = [
                {
                    **{k: w[k] for k in ("时长", "时间段", "缺少人数", "需开放小时数")},
                    "阻塞成员": "、".join(f"{m}({n}h)" for m, n in w["阻塞成员"].items()),
                }
                for w in ev["最接近的窗口"][:8]
            ]
            print(table(rows))


# ---------- 子命令 ----------
def cmd_sample(args: argparse.Namespace) -> int:
    data = json.loads(resources.files("solver").joinpath("fixtures/sample_event.json").read_text(encoding="utf-8"))
    save_json(args.output, data)
    print(f"已写出示例活动:{args.output}(不含空闲数据,可用 synth 生成)")
    return 0


def cmd_synth(args: argparse.Namespace) -> int:
    problem = load_problem(args.input)
    avail = synthesize_availability(
        problem.config,
        problem.members,
        seed=args.seed,
        density=args.density,
        avoid_rate=args.avoid_rate,
        ensure_eval_window=not args.no_eval_window,
    )
    problem.availability = avail
    save_json(args.output, problem_to_dict(problem))
    print(f"已生成合成空闲数据(seed={args.seed}, density={args.density}):{args.output}")
    return 0


def cmd_solve(args: argparse.Namespace) -> int:
    problem = load_problem(args.input)
    opts = SolveOptions(
        time_limit=args.time_limit,
        workers=args.workers,
        diagnose_on_failure=not args.no_diagnose,
        progress=None if args.quiet else (lambda msg: print("…", msg, flush=True)),
    )
    result = solve(problem, opts)
    print_result(problem, result)
    if args.output:
        save_json(args.output, result_to_dict(problem, result))
        print(f"\n已保存结果:{args.output}")
    return 0 if result.feasible and not result.validation_errors else 1


def cmd_validate(args: argparse.Namespace) -> int:
    problem = load_problem(args.input)
    sessions = load_sessions(args.result)
    level = next((lv for lv in problem.ladder if lv.level == args.level), problem.ladder[0])
    rep = validate_schedule(problem, sessions, level)
    for e in rep.errors:
        print("❌", e)
    for w in rep.warnings:
        print("⚠️ ", w)
    print("指标:", ", ".join(f"{OBJECTIVE_LABELS.get(k, k)}={v}" for k, v in rep.metrics.items()))
    print("✅ 通过" if rep.ok else f"❌ {len(rep.errors)} 个错误")
    return 0 if rep.ok else 1


def cmd_diagnose(args: argparse.Namespace) -> int:
    problem = load_problem(args.input)
    errors, warnings = problem.validate()
    for w in warnings:
        print("⚠️ ", w)
    if errors:
        for e in errors:
            print("❌", e)
        return 2
    diag = diagnose(problem, None, SolveOptions(workers=args.workers))
    print_diagnosis(diag)
    if args.output:
        save_json(args.output, diag)
        print(f"\n已保存诊断报告:{args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m solver", description="舞团排练排程求解器")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sample", help="写出示例活动")
    s.add_argument("-o", "--output", default="sample_event.json")
    s.set_defaults(func=cmd_sample)

    s = sub.add_parser("synth", help="生成合成空闲数据")
    s.add_argument("input")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--density", type=float, default=0.55)
    s.add_argument("--avoid-rate", type=float, default=0.05)
    s.add_argument("--no-eval-window", action="store_true", help="不强制开出评估日全员窗口")
    s.set_defaults(func=cmd_synth)

    s = sub.add_parser("solve", help="求解")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--time-limit", type=float, help="每阶段秒数(默认取活动参数)")
    s.add_argument("--workers", type=int)
    s.add_argument("--no-diagnose", action="store_true")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_solve)

    s = sub.add_parser("validate", help="校验排练表")
    s.add_argument("input")
    s.add_argument("result")
    s.add_argument("--level", type=int, default=0, help="按哪个降级层级校验")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("diagnose", help="无解诊断")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--workers", type=int)
    s.set_defaults(func=cmd_diagnose)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print("❌", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main", "build_parser", "table", "Path"]
