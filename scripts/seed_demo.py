"""通过 API 往一个**空数据库**填入演示数据(附录 A 的人员与曲目 + 合成空闲)。

用法:先启动服务(默认 http://localhost:8000),再运行
    python scripts/seed_demo.py [--base http://localhost:8000]
会创建管理员 demo / demo12345、一场演出、14 名人员(已开通账号,密码 season2026)、12 首曲目、
3 条特殊要求,并为其中 11 人填好合成的空闲时间(3 人留空,便于演示「催办」)。数据库非空时拒绝执行。
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta

import httpx

MEMBERS = ["衿", "菁", "幸", "思", "Ash", "嘎", "Siri", "Mo", "林", "郑", "若", "颜", "娄", "诗"]
SONGS = [
    ("恋爱的条件", "简单", ["衿", "菁", "嘎", "幸"], [2]),
    ("Kiss of life-sweat", "一般", ["Ash", "幸", "嘎", "菁"], None),
    ("KATSEYE-ANIMAL", "一般", ["Siri", "Mo", "幸", "思", "林"], [3, 2]),
    ("aespa-lemonadeA", "简单", ["郑", "嘎", "幸", "Ash"], None),
    ("aespa-lemonadeB", "简单", ["菁", "Mo", "Siri", "若"], None),
    ("thatsnono", "简单", ["Siri", "娄", "诗", "若", "思"], None),
    ("rescene-pretty girl", "简单", ["郑", "衿", "若"], None),
    ("少时-说出愿望吧", "简单", ["衿", "郑", "菁", "Mo", "若", "林"], None),
    ("itzy-kill shot", "简单", ["娄", "衿", "思", "若"], None),
    ("BTS-ineedu", "困难", ["思", "林", "菁", "Ash", "颜"], None),
    ("blackpink-玩火", "简单", ["菁", "Siri", "若", "嘎"], None),
    ("aespa-kissntell", "一般", ["郑", "Siri", "若", "诗"], [3, 2]),
]
UNFILLED = {"颜", "娄", "诗"}


def synth_days(rng: random.Random, dates: list[date], slots: int, eval_date: date) -> dict[str, str]:
    days: dict[str, str] = {}
    for d in dates:
        weekend = d.weekday() >= 5
        row = []
        prev = "0"
        for h in range(slots):
            hour = 10 + h
            p = 0.75 if weekend else (0.7 if hour >= 18 else 0.3)
            state = ("1" if rng.random() < p else "0") if rng.random() > 0.75 or prev is None else prev
            if state == "1" and rng.random() < 0.06:
                state = "2"
            prev = state
            row.append(state)
        if d == eval_date:
            for h in range(4, 9):  # 评估日 14:00–19:00 大家尽量有空
                row[h] = "1"
        days[d.isoformat()] = "".join(row)
    return days


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--username", default="demo")
    parser.add_argument("--password", default="demo12345")
    parser.add_argument("--member-password", default="season2026")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    with httpx.Client(base_url=args.base, timeout=60) as c:
        if not c.get("/api/setup/status").json()["needs_setup"]:
            print("数据库已初始化,不重复填充。", file=sys.stderr)
            return 1
        c.post("/api/setup", json={"username": args.username, "password": args.password}).raise_for_status()
        r = c.post("/api/events", json={"name": "2026 秋季路演", "performance_date": "2026-09-20", "formal_start_date": "2026-09-04"})
        r.raise_for_status()
        ev = r.json()
        eid = ev["id"]
        rows = c.post(f"/api/events/{eid}/members", json={"names": MEMBERS}).json()
        ids = {row["display_name"]: row["member_id"] for row in rows}
        c.post(f"/api/events/{eid}/accounts", json={"password": args.member_password}).raise_for_status()
        song_ids: dict[str, int] = {}
        for name, difficulty, members, plan in SONGS:
            r = c.post(f"/api/events/{eid}/songs", json={"name": name, "difficulty": difficulty, "member_ids": [ids[m] for m in members], "session_plan": plan})
            r.raise_for_status()
            song_ids[name] = r.json()["id"]
        rules = [
            {"type": "member_song_max_absent", "params": {"member_id": ids["菁"], "song_id": song_ids["aespa-lemonadeB"], "n": 1}},
            {"type": "blocked_day", "params": {"date": "2026-09-10"}},
            {"type": "focus_member", "params": {"member_id": ids["若"]}},
        ]
        for body in rules:
            c.post(f"/api/events/{eid}/rules", json=body).raise_for_status()
        eval_date = date.fromisoformat(ev["eval_date"])
        dates = [date.fromisoformat(ev["formal_start_date"]) + timedelta(days=i) for i in range(ev["formal_day_count"])] + [eval_date]
        for name, mid in ids.items():
            if name in UNFILLED:
                continue
            days = synth_days(rng, dates, ev["slots_per_day"], eval_date)
            c.put(f"/api/events/{eid}/availability/{mid}", json={"days": days, "submit": True}).raise_for_status()
        ev = c.get(f"/api/events/{eid}").json()
        print(
            f"✅ 已填充:管理员 {args.username} / {args.password};成员账号 = 昵称 / {args.member_password};"
            f"演出「{ev['name']}」{ev['member_count']} 人、{ev['song_count']} 首、{ev['session_count']} 场、"
            f"{ev['rule_count']} 条要求,已提交空闲 {ev['submitted_count']} 人,当前第 {ev['current_step']} 步"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
