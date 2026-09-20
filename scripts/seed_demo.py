"""通过 API 往一个**空数据库**填入演示数据(附录 A 的名册与曲目)。

用法:先启动服务(默认 http://localhost:8000),再运行
    python scripts/seed_demo.py [--base http://localhost:8000]
会创建管理员 demo / demo12345、14 名成员、1 个活动和 12 首曲目。数据库非空时会拒绝执行。
"""

from __future__ import annotations

import argparse
import sys

import httpx

MEMBERS = ["衿", "菁", "幸", "思", "Ash", "嘎", "Siri", "Mo", "林", "郑", "若", "颜", "娄", "诗"]
SONGS = [
    ("a", "恋爱的条件", "简单", ["衿", "菁", "嘎", "幸"], [2]),
    ("b", "Kiss of life-sweat", "一般", ["Ash", "幸", "嘎", "菁"], None),
    ("c", "KATSEYE-ANIMAL", "一般", ["Siri", "Mo", "幸", "思", "林"], [3, 2]),
    ("d", "aespa-lemonadeA", "简单", ["郑", "嘎", "幸", "Ash"], None),
    ("e", "aespa-lemonadeB", "简单", ["菁", "Mo", "Siri", "若"], None),
    ("f", "thatsnono", "简单", ["Siri", "娄", "诗", "若", "思"], None),
    ("g", "rescene-pretty girl", "简单", ["郑", "衿", "若"], None),
    ("h", "少时-说出愿望吧", "简单", ["衿", "郑", "菁", "Mo", "若", "林"], None),
    ("i", "itzy-kill shot", "简单", ["娄", "衿", "思", "若"], None),
    ("j", "BTS-ineedu", "困难", ["思", "林", "菁", "Ash", "颜"], None),
    ("k", "blackpink-玩火", "简单", ["菁", "Siri", "若", "嘎"], None),
    ("l", "aespa-kissntell", "一般", ["郑", "Siri", "若", "诗"], [3, 2]),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--username", default="demo")
    parser.add_argument("--password", default="demo12345")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base, timeout=30) as c:
        if not c.get("/api/setup/status").json()["needs_setup"]:
            print("数据库已初始化,不重复填充。", file=sys.stderr)
            return 1
        c.post("/api/setup", json={"username": args.username, "password": args.password}).raise_for_status()
        ids: dict[str, int] = {}
        for name in MEMBERS:
            r = c.post("/api/members", json={"display_name": name, "aliases": [name.lower()] if name.isascii() else []})
            r.raise_for_status()
            ids[name] = r.json()["id"]
        r = c.post("/api/events", json={"name": "2026 秋季路演", "performance_date": "2026-09-20", "formal_start_date": "2026-09-04"})
        r.raise_for_status()
        event_id = r.json()["id"]
        c.put(f"/api/events/{event_id}/members", json={"member_ids": list(ids.values())}).raise_for_status()
        for code, name, difficulty, members, plan in SONGS:
            body = {"code": code, "name": name, "difficulty": difficulty, "member_ids": [ids[m] for m in members], "session_plan": plan}
            c.post(f"/api/events/{event_id}/songs", json=body).raise_for_status()
        ev = c.get(f"/api/events/{event_id}").json()
        print(f"✅ 已填充:管理员 {args.username} / {args.password},活动「{ev['name']}」{ev['member_count']} 人 {ev['song_count']} 首 {ev['session_count']} 场")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
