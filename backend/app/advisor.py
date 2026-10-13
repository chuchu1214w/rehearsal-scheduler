"""AI 调度员(开发文档 §5.11):无解时让 Claude 读诊断、提出调整、调用求解器验证,循环几轮后给管理员一份可执行的方案。

- 求解器仍负责保证排练表不冲突;Claude 只负责“想办法”:提高允许的缺席、放宽哪条要求、把哪首拆成几场。不会请成员改空闲(成员的空闲时间是给定的)。
- Claude 只在“沙盘”里试算:每次把调整临时套到演出上、转换成求解包后立即回滚,数据库不变。
- 真正修改要求 / 参数,必须由管理员在方案里逐条勾选“允许”后执行(``apply_change``,real=True)。
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from solver.diagnosis import diagnose
from solver.lexicographic import SolveOptions, solve
from solver.types import AVAILABLE as FREE
from solver.types import AVOID, Problem

from .db import make_engine, make_session_factory
from .models import AdvisorRun, Event, Rule
from .rules import RULE_TYPES, sentence, validate_params
from .schemas import EventSettings
from .services import event_config, event_problem, event_settings, ladder_text, song_durations, sorted_participants
from .utils import utcnow

MAX_TURNS = 14  # Claude 最多来回几轮(每轮可试算多次)
EVAL_STAGE_SECONDS = 15.0  # 沙盘试算每阶段的时间上限
FINAL_STAGE_SECONDS = 45.0  # 最终方案复核

KIND_LABELS = {
    "add_rule": "新增要求",
    "edit_rule": "修改要求",
    "disable_rule": "停用要求",
    "setting": "修改排程参数",
    "session_plan": "修改曲目场次方案",
}
SETTING_KEYS = {
    "max_absent_percent": "最多允许缺席的场次比例(%)",
    "absent_per_member_song": "每人每首最多缺席次数",
    "min_full_per_song": "每首至少全员到齐的场次",
    "hard_daily_limit": "单日排练硬上限(小时)",
    "soft_daily_limit": "单日排练软上限(小时)",
    "same_song_different_days": "同一首曲目的几场必须排在不同天",
}


class ChangeError(ValueError):
    pass


# ---------- 调整:沙盘与真实执行共用一套代码 ----------
def _hour(h: int) -> str:
    return f"{h % 24:02d}:00"


def _participant(event: Event, name: str | None):  # noqa: ANN202
    for p in event.participants:
        if name and name in (p.member.display_name, *(p.member.aliases or [])):
            return p
    raise ChangeError(f"找不到成员「{name}」")


def _song(event: Event, code: str | None):  # noqa: ANN202
    for s in event.songs:
        if code and code in (s.code, s.name):
            return s
    raise ChangeError(f"找不到曲目「{code}」")


def _rule(event: Event, rule_id: Any) -> Rule:
    for r in event.rules:
        if r.id == rule_id:
            return r
    raise ChangeError(f"找不到编号为 {rule_id} 的要求")


def _rule_params(event: Event, change: dict, base: dict | None = None) -> dict:
    params = dict(base or {})
    if change.get("member"):
        params["member_id"] = _participant(event, change["member"]).member_id
    if change.get("song"):
        params["song_id"] = _song(event, change["song"]).id
    for key in ("date", "n", "start_hour", "end_hour", "duration"):
        if change.get(key) is not None:
            params[key] = change[key]
    return params


def _validated(event: Event, rule_type: str, params: dict) -> dict:
    try:
        return validate_params(event, rule_type, params)
    except HTTPException as exc:
        raise ChangeError(str(exc.detail)) from exc


def _parse_date(event: Event, value: Any) -> date:
    try:
        d = date.fromisoformat(str(value))
    except ValueError as exc:
        raise ChangeError(f"日期格式不对:{value}(应为 YYYY-MM-DD)") from exc
    config = event_config(event)
    if d not in (*config.formal_dates, config.eval_date):
        raise ChangeError(f"{value} 不在排练日期范围内")
    return d


def describe_change(event: Event, change: dict) -> str:
    """给管理员看的一句话。"""
    kind = change.get("kind")
    try:
        if kind == "add_rule":
            rule = Rule(type=change["rule_type"], params=_rule_params(event, change))
            return "新增:" + sentence(event, rule)
        if kind == "edit_rule":
            r = _rule(event, change["rule_id"])
            new = Rule(type=r.type, params=_rule_params(event, change, r.params))
            return f"把「{sentence(event, r)}」改为「{sentence(event, new)}」"
        if kind == "disable_rule":
            return f"停用:{sentence(event, _rule(event, change['rule_id']))}"
        if kind == "setting":
            label = SETTING_KEYS.get(change.get("key", ""), change.get("key"))
            value = change.get("value")
            old = event_settings(event).model_dump().get(change.get("key", ""))
            if isinstance(value, bool):
                value, old = ("是" if value else "否"), ("是" if old else "否")
            return f"{label}:{old} → {value}"
        if kind == "session_plan":
            plan = " + ".join(f"{h} 小时" for h in change.get("plan") or [])
            return f"曲目 {change['song']} 的场次方案改为 {plan}"
    except (ChangeError, KeyError, TypeError, ValueError):
        pass
    return json.dumps(change, ensure_ascii=False)


def apply_change(db: Session, event: Event, change: dict, *, real: bool) -> None:
    """把一条调整套到 ORM 对象上。沙盘(real=False)由调用方随后回滚;真实执行由调用方提交。"""
    kind = change.get("kind")
    if kind == "add_rule":
        rule_type = change.get("rule_type")
        if rule_type not in RULE_TYPES:
            raise ChangeError(f"未知的要求类型 {rule_type}")
        params = _validated(event, rule_type, _rule_params(event, change))
        event.rules.append(Rule(event_id=event.id, type=rule_type, params=params, enabled=True, sort_order=len(event.rules)))
        return
    if kind == "edit_rule":
        r = _rule(event, change.get("rule_id"))
        r.params = _validated(event, r.type, _rule_params(event, change, r.params))
        r.enabled = True
        return
    if kind == "disable_rule":
        _rule(event, change.get("rule_id")).enabled = False
        return
    if kind == "setting":
        key = change.get("key")
        if key not in SETTING_KEYS:
            raise ChangeError(f"不能修改参数 {key}(可改:{'、'.join(SETTING_KEYS)})")
        data = event_settings(event).model_dump()
        data[key] = change.get("value")
        try:
            event.settings = EventSettings(**data).model_dump()
        except ValidationError as exc:
            msg = ";".join(str(e.get("msg", "")).removeprefix("Value error, ") for e in exc.errors())
            raise ChangeError(f"参数不合法:{msg}") from exc
        return
    if kind == "session_plan":
        song = _song(event, change.get("song"))
        plan = change.get("plan")
        slots = event.day_end_hour - event.day_start_hour
        if not isinstance(plan, list) or not 1 <= len(plan) <= 8 or not all(isinstance(h, int) and 1 <= h <= slots for h in plan):
            raise ChangeError("场次方案应为 1–8 个整数小时数,例如 [2, 2, 1]")
        song.session_plan = list(plan)
        return
    raise ChangeError(f"未知的调整类型 {kind}")


def scenario_problem(db: Session, event_id: int, changes: list[dict]) -> Problem:
    """在沙盘里套用调整并生成求解包;数据库不变。"""
    event = db.get(Event, event_id)
    if event is None:
        raise ChangeError("演出不存在")
    # 先把关系都加载好,套用调整时不再触发查询
    _ = (event.participants, event.songs, event.rules, event.availability)
    for s in event.songs:
        _ = s.members
    try:
        with db.no_autoflush:
            for i, change in enumerate(changes, 1):
                try:
                    apply_change(db, event, change, real=False)
                except ChangeError as exc:
                    raise ChangeError(f"第 {i} 条调整有误:{exc}") from exc
            return event_problem(event)
    finally:
        db.rollback()


# ---------- 给 Claude 看的材料 ----------
def _ranges(hours: list[int]) -> str:
    if not hours:
        return "无"
    out, start, prev = [], hours[0], hours[0]
    for h in hours[1:] + [None]:  # type: ignore[list-item]
        if h is not None and h == prev + 1:
            prev = h
            continue
        out.append(f"{_hour(start)}–{_hour(prev + 1)}")
        if h is not None:
            start = prev = h
    return "、".join(out)


def overview(db: Session, event_id: int) -> dict:
    event = db.get(Event, event_id)
    assert event is not None
    config = event_config(event)
    settings = event_settings(event)
    weekdays = "一二三四五六日"
    members = []
    for p in sorted_participants(event):
        rows = {r.date: r.slots for r in event.availability if r.member_id == p.member_id}
        free = sum(row.count(str(FREE)) for row in rows.values())
        avoid = sum(row.count(str(AVOID)) for row in rows.values())
        members.append(
            {"昵称": p.member.display_name, "已提交空闲": p.availability_submitted_at is not None, "有空小时": free, "尽量避开小时": avoid}
        )
    job = next((j for j in reversed(event.jobs) if j.status in ("infeasible", "succeeded")), None)
    diag = None
    if job is not None and job.diagnosis:
        d = job.diagnosis
        diag = {
            "一句话": job.summary,
            "最大覆盖": d.get("最大覆盖"),
            "各曲缺口": [r for r in d.get("各曲缺口", []) if r.get("全局缺口") or r.get("单曲缺口")],
            "只差一人的时段(前 15 个)": (d.get("只差一人的时段") or [])[:15],
            "最小调整建议": {k: v for k, v in (d.get("最小调整建议") or {}).items() if k != "放宽后示例"},
            "评估场": d.get("评估场"),
            "部分排程": d.get("部分排程"),
        }
    return {
        "演出": event.name,
        "正规排练日期": f"{config.formal_dates[0].isoformat()} 至 {config.formal_dates[-1].isoformat()}(共 {len(config.formal_dates)} 天)",
        "评估日": config.eval_date.isoformat() + "(全员评估,只排评估场)",
        "公演日": event.performance_date.isoformat(),
        "每日排练窗口": f"{_hour(event.day_start_hour)}–{_hour(event.day_end_hour)}",
        "日期星期": {d.isoformat(): "周" + weekdays[d.weekday()] for d in (*config.formal_dates, config.eval_date)},
        "排程参数": {
            "hard_daily_limit": settings.hard_daily_limit,
            "soft_daily_limit": settings.soft_daily_limit,
            "same_song_different_days": settings.same_song_different_days,
            "评估场时长可选": settings.eval_durations,
        },
        "缺席设置": {
            "max_absent_percent": settings.max_absent_percent,
            "absent_per_member_song": settings.absent_per_member_song,
            "min_full_per_song": settings.min_full_per_song,
            "说明": "先试全员到齐;排不下时按阶梯自动允许缺席(每场最多 1 人缺席)。" + ladder_text(settings),
        },
        "曲目": [
            {
                "代号": s.code,
                "名称": s.name,
                "难度": s.difficulty,
                "场次方案(小时)": song_durations(s, settings),
                "是否自定义方案": bool(s.session_plan),
                "参演成员": [m.display_name for m in s.members],
            }
            for s in event.songs
        ],
        "特殊要求": [
            {
                "编号": r.id,
                "内容": sentence(event, r),
                "类型": r.type,
                "硬性": RULE_TYPES.get(r.type, {}).get("hardness") == "hard",
                "启用": r.enabled,
            }
            for r in event.rules
        ],
        "成员": members,
        "上次求解诊断": diag,
    }


def member_availability(db: Session, event_id: int, name: str) -> dict:
    event = db.get(Event, event_id)
    assert event is not None
    p = _participant(event, name)
    config = event_config(event)
    rows = {r.date: r.slots for r in event.availability if r.member_id == p.member_id}
    days = []
    for d in (*config.formal_dates, config.eval_date):
        row = rows.get(d, "")
        free = [event.day_start_hour + i for i, ch in enumerate(row) if ch == str(FREE)]
        avoid = [event.day_start_hour + i for i, ch in enumerate(row) if ch == str(AVOID)]
        days.append({"日期": d.isoformat(), "有空": _ranges(free), "尽量避开": _ranges(avoid)})
    songs = [s.code for s in event.songs if any(m.id == p.member_id for m in s.members)]
    return {"成员": p.member.display_name, "已提交": p.availability_submitted_at is not None, "参演曲目": songs, "每天": days}


def evaluate(problem: Problem, *, stage_seconds: float, workers: int, with_diagnosis: bool = False) -> dict:
    """沙盘试算:只优化“缺席最少”,看能否全部排完、差几场。"""
    errors, _ = problem.validate()
    if errors:
        return {"可以求解": False, "数据问题": errors}
    p = replace(problem, objectives=("absent",))
    r = solve(p, SolveOptions(time_limit=stage_seconds, workers=workers, diagnose_on_failure=False))
    status_text = {"UNKNOWN": "超时未定", "INFEASIBLE": "无解", "无候选": "有场次没有任何全员共同时段"}
    attempts = [f"{a['层级']} {status_text.get(a.get('状态'), a.get('状态'))}" for a in r.attempts]
    out: dict[str, Any] = {"全部排完": r.feasible, "各层级尝试": attempts}
    if r.feasible:
        out["使用层级"] = f"L{r.level_used}"
        out["缺席场次"] = r.objective_values.get("absent", 0)
    elif r.partial:
        out["最多能排"] = f"差 {len(r.unscheduled)} 场"
        out["排不上的场次"] = r.unscheduled
        out["部分排程使用层级"] = f"L{r.level_used}"
    elif r.sessions:
        out["说明"] = "正规排练都能排下,但评估日没有满足到场规则的窗口"
    if any("超时" in a for a in attempts):
        out["注意"] = "有层级在时间限制内没算完(超时未定),不一定真的无解"
    if with_diagnosis and not r.feasible:
        d = diagnose(problem, None, SolveOptions(workers=workers))
        out["诊断"] = {
            "各曲缺口": [x for x in d.get("各曲缺口", []) if x.get("全局缺口") or x.get("单曲缺口")],
            "只差一人的时段(前 15 个)": d.get("只差一人的时段", [])[:15],
            "最小调整建议": d.get("最小调整建议", {}).get("调整"),
            "评估场可行": d.get("评估场", {}).get("可行"),
        }
    return out


def plan_text(plan: list[int]) -> str:
    """[3, 2, 2] → “3 场:3h + 2h + 2h”"""
    return f"{len(plan)} 场:" + " + ".join(f"{h}h" for h in plan) if plan else "不排"


def candidate_plans(plan: list[int]) -> list[list[int]]:
    """一首曲目可以试的场次方案(从改动小到大):最长一场少 1 小时、每场都少 1 小时、少排一场、长场拆成两场。"""
    plan = sorted(plan, reverse=True)
    out: list[list[int]] = []

    def add(p: list[int]) -> None:
        p = sorted((h for h in p if h > 0), reverse=True)
        if p and p != plan and p not in out:
            out.append(p)

    if plan[0] > 1:
        add([plan[0] - 1, *plan[1:]])
    add([max(1, h - 1) for h in plan])
    if len(plan) > 1:
        add(plan[:-1])  # 少排最短的一场
        add(plan[1:])  # 少排最长的一场
    if plan[0] >= 3:
        add([plan[0] - plan[0] // 2, plan[0] // 2, *plan[1:]])  # 最长一场拆成两场
    if len(plan) > 1:
        add([max(1, h - 1) for h in plan[:-1]])  # 少一场且每场少 1 小时
    return out[:6]


def try_session_plans(
    db: Session, event_id: int, song: str, plans: list[list[int]] | None, base_changes: list[dict], *, stage_seconds: float, workers: int
) -> dict:
    """在 base_changes 的基础上,逐个试某首曲目的场次方案,看哪种能让整体有解。"""
    event = db.get(Event, event_id)
    assert event is not None
    s = _song(event, song)
    current = song_durations(s, event_settings(event))
    db.rollback()
    tries = [list(p) for p in plans] if plans else candidate_plans(current)
    rows = []
    for plan in tries[:8]:
        change = {"kind": "session_plan", "song": s.code, "plan": plan, "reason": ""}
        try:
            problem = scenario_problem(db, event_id, [*base_changes, change])
        except ChangeError as exc:
            rows.append({"方案": plan, "说明": plan_text(plan), "结果": f"无效:{exc}"})
            continue
        r = evaluate(problem, stage_seconds=stage_seconds, workers=workers)
        result = "全部排完" if r.get("全部排完") else str(r.get("最多能排") or r.get("说明") or "无解")
        if r.get("全部排完") and r.get("缺席场次"):
            result += f"(缺席 {r['缺席场次']} 场)"
        rows.append({"方案": plan, "说明": plan_text(plan), "结果": result})
    return {"曲目": f"{s.code}({s.name})", "当前方案": plan_text(current), "试算": rows}


# ---------- Claude 的工具与提示 ----------
CHANGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KIND_LABELS), "description": "调整类型"},
        "reason": {"type": "string", "description": "一句话说明为什么这样改(管理员会看到)"},
        "member": {"type": "string", "description": "add_rule / edit_rule 中的成员昵称"},
        "song": {"type": "string", "description": "曲目代号(session_plan;或 add_rule / edit_rule 中的曲目)"},
        "date": {"type": "string", "description": "日期 YYYY-MM-DD"},
        "start_hour": {"type": "integer", "description": "要求中的开始钟点,如 18 表示 18:00"},
        "end_hour": {"type": "integer", "description": "要求中的结束钟点(不含)"},
        "rule_type": {"type": "string", "enum": list(RULE_TYPES), "description": "add_rule 的要求类型"},
        "rule_id": {"type": "integer", "description": "edit_rule / disable_rule 的要求编号"},
        "n": {"type": "integer", "description": "要求里的次数 / 场次数"},
        "duration": {"type": "integer", "description": "fixed_session 的时长(小时)"},
        "key": {"type": "string", "enum": list(SETTING_KEYS), "description": "setting 要改的参数"},
        "value": {"type": ["integer", "boolean"], "description": "setting 的新值"},
        "plan": {"type": "array", "items": {"type": "integer"}, "description": "session_plan 的新场次方案,如 [2, 2, 1]"},
    },
    "required": ["kind", "reason"],
}

TOOLS: list[dict] = [
    {
        "name": "get_overview",
        "description": "读取演出的全部情况:日期、每日窗口、排程参数、曲目(场次方案与参演成员)、特殊要求(含编号)、成员空闲统计、上次求解的诊断。开始时先调用一次。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_member_availability",
        "description": "查看某位成员每天的空闲(有空 / 尽量避开的时段),用于判断卡在谁、哪些曲目适合让谁缺席。空闲是给定的,不能修改。",
        "input_schema": {"type": "object", "properties": {"member": {"type": "string", "description": "成员昵称"}}, "required": ["member"]},
    },
    {
        "name": "evaluate_changes",
        "description": (
            "在沙盘里试算一组调整(不会改数据库):把 changes 全部套用后调用求解器,返回能否全部排完、使用的缺席层级、"
            "或还差哪几场。每次都要传完整的调整列表(不会记住上一次)。with_diagnosis=true 时附带诊断(更慢)。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {"type": "array", "items": CHANGE_SCHEMA},
                "with_diagnosis": {"type": "boolean"},
            },
            "required": ["changes"],
        },
    },
    {
        "name": "try_session_plans",
        "description": (
            "针对一首曲目,一次试算多种场次方案(排几次、每次几小时),看哪种能让整体全部排完。"
            "不传 plans 时自动试:最长一场少 1 小时、每场少 1 小时、少排一场、长场拆两场等。"
            "base_changes 是同时生效的其他调整(例如另一首曲目已选定的新方案),用来组合多首曲目。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "song": {"type": "string", "description": "曲目代号"},
                "plans": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "description": "要试的方案,如 [[2, 2], [3]]",
                },
                "base_changes": {"type": "array", "items": CHANGE_SCHEMA},
            },
            "required": ["song"],
        },
    },
    {
        "name": "submit_proposal",
        "description": "提交最终方案给管理员(只调用一次,之后结束)。方案里的调整会逐条由管理员决定是否允许。",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "给管理员的说明:问题卡在哪、方案怎么解决、代价是什么(3–6 句,中文)"},
                "changes": {"type": "array", "items": CHANGE_SCHEMA},
                "song_plans": {
                    "type": "array",
                    "description": "按曲目的场次建议:哪几首如果改成排几次、每次几小时就能有解(必须是试算验证过的)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "song": {"type": "string", "description": "曲目代号"},
                            "plan": {"type": "array", "items": {"type": "integer"}, "description": "建议的场次方案"},
                            "note": {"type": "string", "description": "效果与代价,如“单独改这首即可全部排完”“需与 b 一起改”"},
                        },
                        "required": ["song", "plan", "note"],
                    },
                },
            },
            "required": ["summary", "changes", "song_plans"],
        },
    },
]

SYSTEM_PROMPT = """你是舞团排练排程系统里的「AI 调度员」。管理员点了求解,结果无解(或只能排出一部分)。你的任务是找出一份管理员能直接执行的调整方案,让排练表能全部排完。

背景:
- 排程由 CP-SAT 求解器完成,它保证排出来的表不冲突。你不直接排表,而是决定“改什么”,再用 evaluate_changes 在沙盘里验证。
- 每首曲目按“场次方案”排若干场;先试全员到齐,排不下时按缺席设置自动允许每场至多 1 人缺席。
- **成员的空闲时间是给定的,不能请成员改空闲或多开放时段。**
- 可用的调整:
  - setting:max_absent_percent(最多允许缺席的场次比例,%,上限 60)、absent_per_member_song(每人每首最多缺几次)、min_full_per_song(每首至少几场全员到齐,可为 0)、hard_daily_limit / soft_daily_limit(单日小时上限)、same_song_different_days(同曲不同天)。
  - add_rule / edit_rule / disable_rule:特殊要求。例如 add_rule 的 member_song_max_absent 允许某人在某首缺席 n 次(只对这一个人、这一首放宽,比整体提高缺席率更精确)。
  - session_plan:把一首曲目的场次拆短或合并。

做法:
1. 先 get_overview,读懂卡在哪里(哪几首排不下、主要卡在谁、只差一人的时段)。
2. **管理员特别想知道:哪几首曲目如果改成排几次、每次几小时,就能有解。** 对每首排不下(有缺口)的曲目都用 try_session_plans 试算,找出能全部排完、且改动最小的场次方案;一首不够时用 base_changes 组合多首。结果填进 submit_proposal 的 song_plans(只写试算验证过的;某首怎么改都不行也要写明)。
3. 再看其他调整(缺席设置、特殊要求)能否用更小的代价解决,用 evaluate_changes 验证。试算之间要真正利用结果,不要重复试一样的东西。
4. 用 submit_proposal 提交:summary 说清两条路(改场次方案 / 其他调整)各自的效果与代价,changes 放你推荐执行的那一套。

衡量代价(从轻到重):
- 允许缺席:优先只对卡住的人和曲目放宽(member_song_max_absent),再考虑整体提高 max_absent_percent;比例够用即可,不要一下提太高。试算结果里的“缺席场次”越少越好。
- 放宽其他特殊要求或排程参数:要说明影响;硬性要求(如场地、固定场次)尽量不动。
- 修改场次方案:会改变排练总时长,谨慎使用,并在 summary 里写明。
- 如果实在无法全部排完,也可以提交“能多排几场”的方案,并在 summary 里说清还差什么。

试算次数有限,通常 4–10 次就应提交。所有给管理员看的文字用简体中文,简洁、具体(写清成员、曲目、数值)。"""


# ---------- 运行 ----------
ClientFactory = Callable[[], Any]
CLIENT_FACTORY: ClientFactory | None = None  # 测试时替换为假客户端


def _client() -> Any:
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY()
    import anthropic

    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or None)


def _create(client: Any, model: str, messages: list) -> Any:
    return client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=messages,
        thinking={"type": "adaptive", "display": "summarized"},
        output_config={"effort": "high"},
        cache_control={"type": "ephemeral"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )


def _proposal_out(
    db: Session, event_id: int, changes: list[dict], summary: str, workers: int, song_plans: list[dict] | None = None
) -> dict:
    event = db.get(Event, event_id)
    assert event is not None
    settings = event_settings(event)
    plans_out = []
    for sp in song_plans or []:
        s = _song(event, sp.get("song"))
        plan = [int(h) for h in sp.get("plan") or []]
        plans_out.append(
            {
                "song": s.code,
                "song_name": s.name,
                "current": plan_text(song_durations(s, settings)),
                "suggested": plan_text(plan),
                "plan": plan,
                "note": str(sp.get("note") or ""),
            }
        )
    items = [
        {**c, "kind_label": KIND_LABELS.get(c.get("kind", ""), c.get("kind")), "description": describe_change(event, c)} for c in changes
    ]
    problem = scenario_problem(db, event_id, changes)
    check = evaluate(problem, stage_seconds=FINAL_STAGE_SECONDS, workers=workers)
    return {"summary": summary, "changes": items, "check": check, "song_plans": plans_out}


def run_advisor(database_url: str, run_id: int, workers: int = 0, model: str = "claude-opus-5-5") -> None:
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    n_workers = workers or min(8, os.cpu_count() or 4)

    def update(**fields: Any) -> bool:
        """写回进度;任务已被取消时返回 False。"""
        with factory() as d:
            run = d.get(AdvisorRun, run_id)
            if run is None or run.status not in ("queued", "running"):
                return False
            for k, v in fields.items():
                setattr(run, k, v)
            d.commit()
            return True

    log: list[dict] = []

    def say(kind: str, text: str) -> bool:
        log.append({"kind": kind, "text": text[:2000], "at": round(time.time() - t0, 1)})
        return update(log=list(log), progress=text[:200])

    t0 = time.time()
    with factory() as db:
        run = db.get(AdvisorRun, run_id)
        if run is None or run.status != "queued":
            return
        event_id = run.event_id
        run.status = "running"
        run.started_at = utcnow()
        db.commit()

    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    try:
        client = _client()
        with factory() as db:
            event = db.get(Event, event_id)
            name = event.name if event else ""
        messages: list = [{"role": "user", "content": f"演出「{name}」现在无解。请找出一份能直接执行的调整方案。"}]
        say("info", "AI 调度员开始分析")
        proposal: dict | None = None
        for turn in range(MAX_TURNS):
            resp = _create(client, model, messages)
            u = getattr(resp, "usage", None)
            for k in usage:
                usage[k] += int(getattr(u, k, 0) or 0)
            if resp.stop_reason == "refusal":
                raise RuntimeError("模型拒绝了这次请求")
            messages.append({"role": "assistant", "content": resp.content})
            for block in resp.content:
                if block.type == "thinking" and getattr(block, "thinking", ""):
                    if not say("think", block.thinking):
                        return
                elif block.type == "text" and block.text.strip():
                    if not say("text", block.text):
                        return
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                if resp.stop_reason == "max_tokens":
                    messages.append({"role": "user", "content": "请继续,并用 submit_proposal 提交方案。"})
                    continue
                messages.append({"role": "user", "content": "请调用 submit_proposal 提交最终方案。"})
                continue
            results = []
            for tu in tool_uses:
                args = tu.input if isinstance(tu.input, dict) else {}
                is_error = False
                try:
                    with factory() as db:
                        if tu.name == "get_overview":
                            say("tool", "读取演出情况与上次诊断")
                            out: Any = overview(db, event_id)
                        elif tu.name == "get_member_availability":
                            say("tool", f"查看 {args.get('member')} 的空闲")
                            out = member_availability(db, event_id, str(args.get("member")))
                        elif tu.name == "evaluate_changes":
                            changes = list(args.get("changes") or [])
                            event = db.get(Event, event_id)
                            desc = ";".join(describe_change(event, c) for c in changes) or "不做调整"
                            if not say("tool", f"试算:{desc}"):
                                return
                            problem = scenario_problem(db, event_id, changes)
                            out = evaluate(
                                problem,
                                stage_seconds=EVAL_STAGE_SECONDS,
                                workers=n_workers,
                                with_diagnosis=bool(args.get("with_diagnosis")),
                            )
                            say("result", "全部排完" if out.get("全部排完") else str(out.get("最多能排") or out.get("说明") or "无解"))
                        elif tu.name == "try_session_plans":
                            if not say("tool", f"试算曲目 {args.get('song')} 的不同场次方案"):
                                return
                            out = try_session_plans(
                                db,
                                event_id,
                                str(args.get("song")),
                                args.get("plans"),
                                list(args.get("base_changes") or []),
                                stage_seconds=EVAL_STAGE_SECONDS,
                                workers=n_workers,
                            )
                            ok = [r["说明"] for r in out["试算"] if str(r["结果"]).startswith("全部排完")]
                            say("result", f"{out['曲目']}:" + (f"{'、'.join(ok)} 可全部排完" if ok else "试过的方案都排不完"))
                        elif tu.name == "submit_proposal":
                            say("tool", "复核最终方案")
                            proposal = _proposal_out(
                                db,
                                event_id,
                                list(args.get("changes") or []),
                                str(args.get("summary") or ""),
                                n_workers,
                                list(args.get("song_plans") or []),
                            )
                            out = {"已提交": True, "复核结果": proposal["check"]}
                        else:
                            out = {"错误": f"未知工具 {tu.name}"}
                            is_error = True
                except ChangeError as exc:
                    out, is_error = {"错误": str(exc)}, True
                    proposal = None if tu.name == "submit_proposal" else proposal
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(out, ensure_ascii=False, default=str),
                        "is_error": is_error,
                    }
                )
            if proposal is not None:
                break
            if turn == MAX_TURNS - 2:
                results.append({"type": "text", "text": "试算次数快用完了,请根据目前的结果立即调用 submit_proposal 提交方案。"})
            messages.append({"role": "user", "content": results})
        if proposal is None:
            raise RuntimeError("AI 调度员在限定轮数内没有给出方案")
        say("done", "方案已生成")
        update(status="done", proposal=proposal, usage=usage, progress="", finished_at=utcnow())
    except Exception as exc:  # noqa: BLE001
        print(traceback.format_exc(), file=sys.stderr, flush=True)  # 完整错误只进服务器日志,页面上只显示一句话
        msg = str(exc).strip().split("\n")[0] or type(exc).__name__
        if "api_key" in msg.lower() or "authentication" in type(exc).__name__.lower():
            msg = "Claude API 密钥无效或未配置"
        update(status="failed", error=msg[:500], usage=usage, progress="", finished_at=utcnow())


def estimate_cost(usage: dict | None) -> float | None:
    """按 Claude Opus 5.5 价格估算花费(美元)。"""
    if not usage:
        return None
    per_m = {"input_tokens": 4.0, "cache_creation_input_tokens": 5.0, "cache_read_input_tokens": 0.2, "output_tokens": 20.0}
    return round(sum(int(usage.get(k, 0) or 0) * v for k, v in per_m.items()) / 1_000_000, 3)


# ---------- 管理员执行 ----------
def apply_selected(db: Session, run: AdvisorRun, indices: list[int]) -> list[int]:
    """执行管理员允许的调整;任何一条失败则全部不执行。返回新执行的序号。"""
    proposal = run.proposal or {}
    changes = proposal.get("changes") or []
    event = db.get(Event, run.event_id)
    assert event is not None
    done = set(run.applied or [])
    todo = [i for i in dict.fromkeys(indices) if 0 <= i < len(changes) and i not in done]
    try:
        for i in todo:
            raw = {k: v for k, v in changes[i].items() if k not in ("kind_label", "description")}
            apply_change(db, event, raw, real=True)
    except ChangeError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"第 {i + 1} 条无法执行:{exc}") from exc
    run.applied = sorted(done | set(todo))
    return todo
