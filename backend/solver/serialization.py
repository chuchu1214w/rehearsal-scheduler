"""JSON 输入 / 输出格式。

输入文件结构(全部键名见 README):
{
  "event": {...活动参数...},
  "members": ["衿", ...],
  "songs": [{"code": "a", "name": "...", "difficulty": "简单", "members": [...], "session_plan": [2]}],
  "availability": {"衿": {"2026-09-04": "1111000000000", ...}},
  "rules": {...},
  "ladder": [...],
  "objectives": [...]
}
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .timegrid import weekday_zh
from .types import (
    DEFAULT_LADDER,
    DEFAULT_OBJECTIVES,
    Availability,
    EventConfig,
    FixedSession,
    LadderLevel,
    Problem,
    Rules,
    Session,
    SolveResult,
    Song,
)


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def _row(value: str | list[int], slots: int) -> list[int]:
    if isinstance(value, str):
        return [int(ch) for ch in value.strip()]
    return [int(v) for v in value]


def config_from_dict(data: dict) -> EventConfig:
    kwargs: dict = {
        "performance_date": parse_date(data["performance_date"]),
        "formal_start_date": parse_date(data["formal_start_date"]),
    }
    for key in (
        "day_start_hour",
        "day_end_hour",
        "soft_daily_limit",
        "hard_daily_limit",
        "merge_visit_gap",
        "free_gap",
        "eval_min_contiguous",
        "same_song_different_days",
        "stage_time_limit",
        "workers",
        "seed",
    ):
        if key in data:
            kwargs[key] = data[key]
    if "eval_durations" in data:
        kwargs["eval_durations"] = tuple(int(x) for x in data["eval_durations"])
    if "difficulty_templates" in data:
        kwargs["difficulty_templates"] = {k: tuple(int(x) for x in v) for k, v in data["difficulty_templates"].items()}
    return EventConfig(**kwargs)


def config_to_dict(config: EventConfig) -> dict:
    return {
        "performance_date": config.performance_date.isoformat(),
        "formal_start_date": config.formal_start_date.isoformat(),
        "day_start_hour": config.day_start_hour,
        "day_end_hour": config.day_end_hour,
        "soft_daily_limit": config.soft_daily_limit,
        "hard_daily_limit": config.hard_daily_limit,
        "merge_visit_gap": config.merge_visit_gap,
        "free_gap": config.free_gap,
        "eval_durations": list(config.eval_durations),
        "eval_min_contiguous": config.eval_min_contiguous,
        "same_song_different_days": config.same_song_different_days,
        "difficulty_templates": {k: list(v) for k, v in config.difficulty_templates.items()},
        "stage_time_limit": config.stage_time_limit,
        "workers": config.workers,
        "seed": config.seed,
    }


def rules_from_dict(data: dict | None) -> Rules:
    data = data or {}
    blocked: dict[date, frozenset[int]] = {}
    for k, v in (data.get("blocked_slots") or {}).items():
        d = parse_date(k)
        blocked[d] = frozenset(range(0, 24)) if v == "all" else frozenset(int(h) for h in v)
    max_per_date = {parse_date(k): int(v) for k, v in (data.get("max_sessions_per_date") or {}).items()}
    caps = {(r["member"], r["song"]): int(r["max"]) for r in data.get("member_song_max_attendance") or []}
    allow = {(r["member"], r["song"]): int(r["max"]) for r in data.get("member_song_max_absent") or []}
    fixed = tuple(
        FixedSession(r["song"], parse_date(r["date"]), int(r["start"]), int(r["duration"]), r.get("absent_member"))
        for r in data.get("fixed_sessions") or []
    )
    return Rules(
        blocked_slots=blocked,
        max_sessions_per_date=max_per_date,
        member_song_max_attendance=caps,
        member_song_max_absent=allow,
        focus_members=tuple(data.get("focus_members") or ()),
        fixed_sessions=fixed,
    )


def rules_to_dict(rules: Rules) -> dict:
    return {
        "blocked_slots": {d.isoformat(): sorted(hs) for d, hs in rules.blocked_slots.items()},
        "max_sessions_per_date": {d.isoformat(): n for d, n in rules.max_sessions_per_date.items()},
        "member_song_max_attendance": [{"member": m, "song": s, "max": cap} for (m, s), cap in rules.member_song_max_attendance.items()],
        "member_song_max_absent": [{"member": m, "song": s, "max": n} for (m, s), n in rules.member_song_max_absent.items()],
        "focus_members": list(rules.focus_members),
        "fixed_sessions": [
            {
                "song": fx.song_code,
                "date": fx.date.isoformat(),
                "start": fx.start,
                "duration": fx.duration,
                "absent_member": fx.absent_member,
            }
            for fx in rules.fixed_sessions
        ],
    }


def ladder_from_list(items: list[dict] | None) -> tuple[LadderLevel, ...]:
    if not items:
        return DEFAULT_LADDER
    return tuple(
        LadderLevel(
            level=int(it.get("level", i)),
            max_absent_ratio=float(it.get("max_absent_ratio", 0.0)),
            per_song_min_full=it.get("per_song_min_full"),
            per_member_per_song_max_absent=int(it.get("per_member_per_song_max_absent", 0)),
        )
        for i, it in enumerate(items)
    )


def ladder_to_list(ladder: tuple[LadderLevel, ...]) -> list[dict]:
    return [
        {
            "level": lv.level,
            "max_absent_ratio": lv.max_absent_ratio,
            "per_song_min_full": lv.per_song_min_full,
            "per_member_per_song_max_absent": lv.per_member_per_song_max_absent,
        }
        for lv in ladder
    ]


def problem_from_dict(data: dict) -> Problem:
    config = config_from_dict(data["event"])
    members = tuple(str(m) for m in data["members"])
    songs = tuple(
        Song(
            code=str(s["code"]),
            name=str(s.get("name", s["code"])),
            difficulty=str(s.get("difficulty", "简单")),
            members=tuple(str(m) for m in s["members"]),
            session_plan=tuple(int(x) for x in s["session_plan"]) if s.get("session_plan") else None,
        )
        for s in data["songs"]
    )
    avail = Availability()
    for m, rows in (data.get("availability") or {}).items():
        for k, v in rows.items():
            avail.set_row(str(m), parse_date(k), _row(v, config.slots_per_day))
    return Problem(
        config=config,
        members=members,
        songs=songs,
        availability=avail,
        rules=rules_from_dict(data.get("rules")),
        ladder=ladder_from_list(data.get("ladder")),
        objectives=tuple(data.get("objectives") or DEFAULT_OBJECTIVES),
    )


def problem_to_dict(problem: Problem) -> dict:
    return {
        "event": config_to_dict(problem.config),
        "members": list(problem.members),
        "songs": [
            {
                "code": s.code,
                "name": s.name,
                "difficulty": s.difficulty,
                "members": list(s.members),
                "session_plan": list(s.session_plan) if s.session_plan else None,
            }
            for s in problem.songs
        ],
        "availability": {
            m: {d.isoformat(): "".join(str(v) for v in row) for d, row in sorted(rows.items())}
            for m, rows in problem.availability.grid.items()
        },
        "rules": rules_to_dict(problem.rules),
        "ladder": ladder_to_list(problem.ladder),
        "objectives": list(problem.objectives),
    }


def load_problem(path: str | Path) -> Problem:
    return problem_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save_json(path: str | Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def session_to_dict(problem: Problem, s: Session) -> dict:
    config = problem.config
    song = problem.song(s.song_code) if s.song_code else None
    return {
        "kind": s.kind,
        "date": s.date.isoformat(),
        "weekday": weekday_zh(s.date),
        "start": s.start,
        "duration": s.duration,
        "time": config.range_label(s.start, s.duration),
        "song": s.song_code,
        "song_name": song.name if song else "全员评估",
        "task_no": s.task_no,
        "members": list(song.members) if song else list(problem.members),
        "absent": list(s.absent_members),
        "attendance": ({m: [a, b] for m, (a, b) in s.attendance.items()} if s.attendance else None),
        "locked": s.locked,
    }


def session_from_dict(row: dict) -> Session:
    att = row.get("attendance")
    return Session(
        kind=row["kind"],
        date=parse_date(row["date"]),
        start=int(row["start"]),
        duration=int(row["duration"]),
        song_code=row.get("song"),
        task_no=row.get("task_no"),
        absent_members=tuple(row.get("absent") or ()),
        attendance={m: (int(a), int(b)) for m, (a, b) in att.items()} if att else None,
        locked=bool(row.get("locked", False)),
    )


def result_to_dict(problem: Problem, result: SolveResult) -> dict:
    return {
        "feasible": result.feasible,
        "level_used": result.level_used,
        "exact_optimum": result.exact,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
        "stages": [{"key": r.key, "label": r.label, "value": r.value, "status": r.status} for r in result.stages],
        "objective_values": result.objective_values,
        "attempts": result.attempts,
        "sessions": [session_to_dict(problem, s) for s in result.sessions],
        "warnings": result.warnings,
        "validation_errors": result.validation_errors,
        "diagnosis": result.diagnosis,
    }


def load_sessions(path: str | Path) -> list[Session]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data["sessions"] if isinstance(data, dict) else data
    return [session_from_dict(r) for r in rows]
