"""特殊排程要求:类型定义、参数校验、人话句子、转换为求解包的 Rules。"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException

from solver.types import FixedSession, Rules

from .models import Event, Member, Rule, Song
from .schemas import RuleOut, RuleTypeOut

RULE_TYPES: dict[str, dict] = {
    "member_song_max_absent": {
        "hardness": "soft",
        "template": "{member} 在 {song} 最多可缺席 {n} 次",
        "fields": ["member_id", "song_id", "n"],
        "description": "尽量让 TA 全到,排不开时才让 TA 缺席,最多 N 次",
    },
    "member_song_max_attendance": {
        "hardness": "hard",
        "template": "{member} 在 {song} 最多参加 {n} 场",
        "fields": ["member_id", "song_id", "n"],
        "description": "TA 本来就只打算来 N 场",
    },
    "blocked_day": {
        "hardness": "hard",
        "template": "{date} 整天不排练",
        "fields": ["date"],
        "description": "场地没空、集体活动等",
    },
    "blocked_slots": {
        "hardness": "hard",
        "template": "{date} 的 {start}–{end} 不排练",
        "fields": ["date", "start_hour", "end_hour"],
        "description": "某天的某个时段不排",
    },
    "max_sessions_per_date": {
        "hardness": "hard",
        "template": "{date} 最多排 {n} 场",
        "fields": ["date", "n"],
        "description": "控制某天的强度",
    },
    "fixed_session": {
        "hardness": "hard",
        "template": "{song} 有一场固定在 {date} {start}–{end}",
        "fields": ["song_id", "date", "start_hour", "duration"],
        "description": "已经和场地 / 老师约好的场次",
    },
    "focus_member": {
        "hardness": "soft",
        "template": "尽量把 {member} 的排练集中在少数几天",
        "fields": ["member_id"],
        "description": "住得远的成员少跑几趟",
    },
}


def rule_types() -> list[RuleTypeOut]:
    return [RuleTypeOut(type=k, **v) for k, v in RULE_TYPES.items()]  # type: ignore[arg-type]


def _fmt_date(d: date) -> str:
    return f"{d.month}/{d.day}"


def _hour(h: int) -> str:
    return f"{h % 24:02d}:00"


def _int(params: dict, key: str, lo: int, hi: int, what: str) -> int:
    try:
        v = int(params[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"缺少或无法识别的参数:{what}") from exc
    if not lo <= v <= hi:
        raise HTTPException(status_code=422, detail=f"{what}必须在 {lo}–{hi} 之间")
    return v


def _date(params: dict, key: str, event: Event, *, formal_only: bool = True) -> date:
    try:
        d = date.fromisoformat(str(params[key]))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="缺少或无法识别的日期") from exc
    last = event.performance_date - timedelta(days=2 if formal_only else 1)
    if not event.formal_start_date <= d <= last:
        raise HTTPException(status_code=422, detail=f"日期 {d} 不在排练区间 {event.formal_start_date} ~ {last} 内")
    return d


def _member(params: dict, event: Event) -> Member:
    try:
        mid = int(params["member_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="缺少成员") from exc
    for p in event.participants:
        if p.member_id == mid:
            return p.member
    raise HTTPException(status_code=422, detail="该成员不是本演出的参与人员")


def _song(params: dict, event: Event) -> Song:
    try:
        sid = int(params["song_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="缺少曲目") from exc
    for s in event.songs:
        if s.id == sid:
            return s
    raise HTTPException(status_code=422, detail="曲目不属于本演出")


def validate_params(event: Event, rule_type: str, params: dict) -> dict:
    """校验并规范化参数(返回可存储的 dict)。"""
    if rule_type not in RULE_TYPES:
        raise HTTPException(status_code=422, detail=f"未知的要求类型 {rule_type}")
    slots = event.day_end_hour - event.day_start_hour
    if rule_type in ("member_song_max_absent", "member_song_max_attendance"):
        m, s = _member(params, event), _song(params, event)
        if m not in s.members:
            raise HTTPException(status_code=422, detail=f"{m.display_name} 不是曲目「{s.name}」的参演人员")
        n = _int(params, "n", 1 if rule_type == "member_song_max_absent" else 0, 20, "次数")
        return {"member_id": m.id, "song_id": s.id, "n": n}
    if rule_type == "blocked_day":
        return {"date": _date(params, "date", event).isoformat()}
    if rule_type == "blocked_slots":
        d = _date(params, "date", event)
        start = _int(params, "start_hour", event.day_start_hour, event.day_end_hour - 1, "开始时间")
        end = _int(params, "end_hour", start + 1, event.day_end_hour, "结束时间")
        return {"date": d.isoformat(), "start_hour": start, "end_hour": end}
    if rule_type == "max_sessions_per_date":
        return {"date": _date(params, "date", event).isoformat(), "n": _int(params, "n", 0, 20, "场次数")}
    if rule_type == "fixed_session":
        s = _song(params, event)
        d = _date(params, "date", event)
        duration = _int(params, "duration", 1, slots, "时长")
        start = _int(params, "start_hour", event.day_start_hour, event.day_end_hour - duration, "开始时间")
        return {"song_id": s.id, "date": d.isoformat(), "start_hour": start, "duration": duration}
    if rule_type == "focus_member":
        return {"member_id": _member(params, event).id}
    raise HTTPException(status_code=422, detail=f"未知的要求类型 {rule_type}")


def sentence(event: Event, rule: Rule) -> str:
    p = rule.params or {}
    members = {pt.member_id: pt.member.display_name for pt in event.participants}
    songs = {s.id: f"{s.code}·{s.name}" for s in event.songs}
    t = RULE_TYPES.get(rule.type, {}).get("template", rule.type)
    try:
        return t.format(
            member=members.get(p.get("member_id"), "?"),
            song=songs.get(p.get("song_id"), "?"),
            n=p.get("n", "?"),
            date=_fmt_date(date.fromisoformat(p["date"])) if p.get("date") else "?",
            start=_hour(int(p["start_hour"])) if "start_hour" in p else "?",
            end=(
                _hour(int(p["end_hour"]))
                if "end_hour" in p
                else _hour(int(p["start_hour"]) + int(p.get("duration", 0)))
                if "start_hour" in p
                else "?"
            ),
        )
    except (KeyError, ValueError, TypeError):
        return t


def serialize_rule(event: Event, rule: Rule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        event_id=rule.event_id,
        type=rule.type,  # type: ignore[arg-type]
        params=dict(rule.params or {}),
        hardness=RULE_TYPES.get(rule.type, {}).get("hardness", "hard"),
        enabled=rule.enabled,
        sentence=sentence(event, rule),
        sort_order=rule.sort_order,
    )


def to_solver_rules(event: Event) -> Rules:
    """把启用的要求转换为求解包的 Rules(成员用昵称、曲目用代号)。"""
    members = {pt.member_id: pt.member.display_name for pt in event.participants}
    songs = {s.id: s.code for s in event.songs}
    slots = event.day_end_hour - event.day_start_hour
    blocked: dict[date, set[int]] = {}
    max_per_date: dict[date, int] = {}
    caps: dict[tuple[str, str], int] = {}
    allow: dict[tuple[str, str], int] = {}
    focus: list[str] = []
    fixed: list[FixedSession] = []
    for r in event.rules:
        if not r.enabled:
            continue
        p = r.params or {}
        try:
            if r.type == "member_song_max_absent":
                allow[(members[p["member_id"]], songs[p["song_id"]])] = int(p["n"])
            elif r.type == "member_song_max_attendance":
                caps[(members[p["member_id"]], songs[p["song_id"]])] = int(p["n"])
            elif r.type == "blocked_day":
                blocked.setdefault(date.fromisoformat(p["date"]), set()).update(range(slots))
            elif r.type == "blocked_slots":
                d = date.fromisoformat(p["date"])
                hs = range(int(p["start_hour"]) - event.day_start_hour, int(p["end_hour"]) - event.day_start_hour)
                blocked.setdefault(d, set()).update(hs)
            elif r.type == "max_sessions_per_date":
                max_per_date[date.fromisoformat(p["date"])] = int(p["n"])
            elif r.type == "fixed_session":
                fixed.append(
                    FixedSession(
                        songs[p["song_id"]],
                        date.fromisoformat(p["date"]),
                        int(p["start_hour"]) - event.day_start_hour,
                        int(p["duration"]),
                    )
                )
            elif r.type == "focus_member":
                focus.append(members[p["member_id"]])
        except KeyError:
            continue  # 引用的成员 / 曲目已被移除,忽略该条
    return Rules(
        blocked_slots={d: frozenset(hs) for d, hs in blocked.items()},
        max_sessions_per_date=max_per_date,
        member_song_max_attendance=caps,
        focus_members=tuple(focus),
        fixed_sessions=tuple(fixed),
        member_song_max_absent=allow,
    )
