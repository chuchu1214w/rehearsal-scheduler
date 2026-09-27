"""为 App Store 审核准备演示账号:只调用 HTTP API,不碰舞团真实的演出和成员。

用法(管理员在自己电脑上运行):
    .venv/bin/python scripts/make_review_demo.py [--base https://timetomeet.fly.dev]
会提示输入管理员用户名和密码(只用于本次登录,不保存、不打印),然后:
  - 建立(或复用)演出「审核演示 · 冬季公演」:正规排练从今天开始,约 4–5 周后演出;
  - 名册里加入 5 位虚构成员(「演示·」前缀)和「审核员」,全部只参加这场演出;
  - 3 首曲目,管理员代填并提交全员空闲(工作日晚上 + 周末);
  - 求解并发布排练表(数据没变、已有发布版本时不重复求解);
  - 为审核员开通账号(已有则重置密码),再以审核员身份改一次密码,免去首次登录强制改密。
最后只打印审核账号的用户名、密码和一行摘要。可以重复运行(审核前再跑一次会把日期顺延到今天起)。
测试用:环境变量 SEASON_ADMIN_USER / SEASON_ADMIN_PASSWORD 可代替交互输入。
"""

from __future__ import annotations

import argparse
import getpass
import os
import random
import secrets
import sys
import time
from datetime import date, timedelta

import httpx

EVENT_NAME = "审核演示 · 冬季公演"
DEMO_NOTE = "App Store 审核演示数据,以后提交新版本审核还要用,请保留"
REVIEWER = "审核员"
LEAD_DAYS = 33  # 演出日 = 今天 + 33 天:正规排练 32 天,至少含 4 个周六
MIN_LEFT_DAYS = 26  # 复用已有演出时,离演出不足这么多天就整体顺延到今天起
STAGE_TIME_LIMIT = 30.0  # 每个求解阶段的时限(秒),演示数据很小,足够
SOLVE_TIMEOUT = 20 * 60
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"

# 每人每周固定的空闲:星期几(0 = 周一)-> (开始小时, 结束小时)。
# 只有周六下午全员都在,所以全员曲的 4 场会分到 4 个不同的周六,审核期间总有接下来的排练。
WEEKLY: dict[str, dict[int, tuple[int, int]]] = {
    "演示·小林": {1: (19, 22), 3: (19, 22), 5: (12, 20), 6: (14, 18)},
    "演示·阿澄": {0: (18, 22), 3: (18, 22), 5: (13, 19)},
    "演示·Mina": {2: (19, 23), 3: (19, 23), 5: (13, 21), 6: (13, 17)},
    "演示·七七": {1: (19, 22), 4: (19, 22), 5: (13, 19), 6: (15, 19)},
    "演示·周周": {1: (19, 22), 3: (19, 22), 5: (14, 20), 6: (14, 18)},
    REVIEWER: {0: (19, 22), 3: (19, 22), 5: (13, 19), 6: (14, 18)},
}
SONGS: list[tuple[str, str, list[str], list[int] | None]] = [
    ("冬日序曲", "简单", list(WEEKLY), [2, 2, 2, 2]),
    ("初雪", "一般", ["演示·小林", "演示·阿澄", "演示·Mina", REVIEWER], None),
    ("北极星", "困难", ["演示·七七", "演示·周周", "演示·小林"], None),
]
JOB_STATUS = {"infeasible": "无可行方案", "failed": "求解失败", "cancelled": "已取消"}


class DemoError(Exception):
    pass


def _detail(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail")
    except ValueError:
        return r.text[:200] or r.reason_phrase
    if isinstance(detail, list):  # 422 参数校验
        return ";".join(str(x.get("msg", x)) for x in detail)
    return str(detail)


def request(c: httpx.Client, method: str, path: str, what: str, **kw) -> httpx.Response:  # noqa: ANN003
    try:
        return c.request(method, path, **kw)
    except httpx.HTTPError as exc:
        raise DemoError(f"{what}失败:连不上服务器 {c.base_url}({exc})") from exc


def call(c: httpx.Client, method: str, path: str, what: str, **kw):  # noqa: ANN003, ANN201
    r = request(c, method, path, what, **kw)
    if r.status_code >= 400:
        raise DemoError(f"{what}失败(HTTP {r.status_code}):{_detail(r)}")
    return r.json() if r.content else None


def new_password() -> str:
    while True:
        s = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(16))
        if any(ch.islower() for ch in s) and any(ch.isupper() for ch in s) and any(ch.isdigit() for ch in s):
            return "-".join(s[i : i + 4] for i in range(0, 16, 4))


def login(base: str, username: str, password: str, what: str) -> tuple[httpx.Client, dict]:
    c = httpx.Client(base_url=base, timeout=60, headers={"X-Client": "native"})
    try:
        me = call(c, "POST", "/api/auth/login", what, json={"username": username, "password": password})
    except DemoError:
        c.close()
        raise
    c.cookies.clear()  # 只用 Bearer 令牌
    c.headers["Authorization"] = f"Bearer {me['token']}"
    return c, me


def logout(c: httpx.Client) -> None:
    try:
        c.post("/api/auth/logout")
    except httpx.HTTPError:
        pass
    c.close()


# ---------- 空闲 ----------
def day_slots(name: str, d: date, eval_date: date, start_hour: int, slots: int) -> str:
    """按每周固定空闲合成一天的格子;同一人同一天每次结果相同,重复运行不会改动数据。"""
    row = ["0"] * slots

    def mark(a: int, b: int, ch: str = "1") -> None:
        for hour in range(a, b):
            if 0 <= hour - start_hour < slots:
                row[hour - start_hour] = ch

    if d == eval_date:  # 评估日全员 14:00–21:00 有空
        mark(14, 21)
        return "".join(row)
    rng = random.Random(f"{name}|{d.isoformat()}")
    wd = d.weekday()
    span = WEEKLY[name].get(wd)
    if wd == 5 and span:  # 周六核心时段不动,只随机加宽
        a, b = span
        extra = rng.choice((0, 0, 1))
        mark(a - rng.choice((0, 0, 1)), b + extra)
        if extra and rng.random() < 0.5:
            mark(b, b + 1, "2")
    elif span and rng.random() > 0.15:  # 偶尔有事来不了
        mark(*span)
        if rng.random() < 0.2:
            mark(span[1] - 1, span[1], "2")
    if wd < 5 and rng.random() < 0.15:  # 偶尔下午没课
        mark(14, 17, "1" if rng.random() < 0.6 else "2")
    return "".join(row)


# ---------- 各步骤 ----------
def ensure_event(c: httpx.Client, today: date) -> tuple[dict, bool]:
    perf = today + timedelta(days=LEAD_DAYS)
    window = {
        "performance_date": perf.isoformat(),
        "formal_start_date": today.isoformat(),
        "availability_deadline": (perf - timedelta(days=10)).isoformat(),
    }
    same = [e for e in call(c, "GET", "/api/events", "读取演出列表") if e["name"] == EVENT_NAME]
    if len(same) > 1:
        raise DemoError(f"有 {len(same)} 场同名演出「{EVENT_NAME}」,请先在网页上删掉多余的再运行")
    if not same:
        body = {"name": EVENT_NAME, **window, "settings": {"stage_time_limit": STAGE_TIME_LIMIT}}
        return call(c, "POST", "/api/events", "新建演示演出", json=body), True
    ev = same[0]
    left = (date.fromisoformat(ev["performance_date"]) - today).days
    if left >= MIN_LEFT_DAYS and date.fromisoformat(ev["formal_start_date"]) <= today + timedelta(days=3) and ev["status"] != "closed":
        return ev, False
    if ev["status"] == "closed":
        window["status"] = "preparing"
    return call(c, "PATCH", f"/api/events/{ev['id']}", "顺延演示演出日期", json=window), True


def ensure_members(c: httpx.Client) -> dict[str, int]:
    roster = call(c, "GET", "/api/members", "读取名册")
    ids: dict[str, int] = {}
    for name in WEEKLY:
        hit = next((m for m in roster if m["display_name"] == name), None)
        if hit is None:
            owner = next((m for m in roster if name in (m["aliases"] or [])), None)
            if owner is not None:
                raise DemoError(f"「{name}」已是成员 {owner['display_name']} 的别名,请先在名册里改掉再运行")
            hit = call(c, "POST", "/api/members", f"添加成员 {name}", json={"display_name": name, "note": DEMO_NOTE})
        elif not hit["active"]:
            hit = call(c, "PATCH", f"/api/members/{hit['id']}", f"启用成员 {name}", json={"active": True})
        ids[name] = hit["id"]
    return ids


def ensure_participants(c: httpx.Client, eid: int, ids: dict[str, int]) -> bool:
    rows = call(c, "GET", f"/api/events/{eid}/members", "读取演出人员")
    demo = set(ids.values())
    others = [r["display_name"] for r in rows if r["member_id"] not in demo]
    if others:
        raise DemoError(f"演示演出里有非演示成员:{'、'.join(others)}。请先在网页上把他们移出,免得审核员看到真实姓名")
    current = {r["member_id"] for r in rows}
    if demo <= current:
        return False
    call(c, "PUT", f"/api/events/{eid}/members", "添加演出人员", json={"member_ids": sorted(current | demo)})
    return True


def guard_reviewer(c: httpx.Client, eid: int, rid: int) -> None:
    """审核员只能参加演示演出,否则登录后会看到真实演出。"""
    for e in call(c, "GET", "/api/events", "读取演出列表"):
        if e["id"] == eid:
            continue
        rows = call(c, "GET", f"/api/events/{e['id']}/members", f"读取演出「{e['name']}」的人员")
        if any(r["member_id"] == rid for r in rows):
            raise DemoError(f"成员「{REVIEWER}」还参加了演出「{e['name']}」,审核员会看到真实数据。请先把他移出那场演出再运行")


def ensure_songs(c: httpx.Client, eid: int, ids: dict[str, int]) -> bool:
    existing = {s["name"]: s for s in call(c, "GET", f"/api/events/{eid}/songs", "读取曲目")["songs"]}
    changed = False
    for name, difficulty, members, plan in SONGS:
        want = [ids[m] for m in members]
        s = existing.get(name)
        if s is None:
            body = {"name": name, "difficulty": difficulty, "member_ids": want, "session_plan": plan}
            call(c, "POST", f"/api/events/{eid}/songs", f"添加曲目 {name}", json=body)
            changed = True
        elif sorted(m["id"] for m in s["members"]) != sorted(want) or s["difficulty"] != difficulty or s["session_plan"] != plan:
            body = {"difficulty": difficulty, "member_ids": want, **({"session_plan": plan} if plan else {"clear_session_plan": True})}
            call(c, "PATCH", f"/api/songs/{s['id']}", f"更新曲目 {name}", json=body)
            changed = True
    return changed


def fill_availability(c: httpx.Client, ev: dict, ids: dict[str, int]) -> bool:
    eid = ev["id"]
    eval_date = date.fromisoformat(ev["eval_date"])
    start = date.fromisoformat(ev["formal_start_date"])
    dates = [start + timedelta(days=i) for i in range(ev["formal_day_count"])] + [eval_date]
    changed = False
    for name, mid in ids.items():
        want = {d.isoformat(): day_slots(name, d, eval_date, ev["day_start_hour"], ev["slots_per_day"]) for d in dates}
        cur = call(c, "GET", f"/api/events/{eid}/availability/{mid}", f"读取 {name} 的空闲")
        if cur["submitted_at"] and all(cur["days"].get(k) == v for k, v in want.items()):
            continue
        call(c, "PUT", f"/api/events/{eid}/availability/{mid}", f"代填 {name} 的空闲", json={"days": want, "submit": True})
        changed = True
    return changed


def wait_job(c: httpx.Client, job_id: int) -> dict:
    deadline = time.monotonic() + SOLVE_TIMEOUT
    while True:
        job = call(c, "GET", f"/api/solve-jobs/{job_id}", "查询求解进度")
        if job["status"] not in ("queued", "running"):
            return job
        if time.monotonic() > deadline:
            raise DemoError(f"求解超过 {SOLVE_TIMEOUT // 60} 分钟仍未结束(任务 #{job_id}),可稍后在网页「排程」页查看,或重新运行本脚本")
        time.sleep(2)


def solve(c: httpx.Client, eid: int) -> dict:
    r = request(c, "POST", f"/api/events/{eid}/solve", "开始求解", json={})
    if r.status_code == 409:  # 上次运行留下的任务还在跑:等它结束,再按当前数据重排
        wait_job(c, call(c, "GET", f"/api/events/{eid}/solve-jobs/latest", "读取求解任务")["id"])
        r = request(c, "POST", f"/api/events/{eid}/solve", "开始求解", json={})
    if r.status_code >= 400:
        raise DemoError(f"开始求解失败(HTTP {r.status_code}):{_detail(r)}")
    job = wait_job(c, r.json()["id"])
    if job["status"] != "succeeded" or not job["version_id"]:
        reason = job["summary"] or job["error"] or job["progress"] or "没有给出原因"
        raise DemoError(f"没有可发布的排练表({JOB_STATUS.get(job['status'], job['status'])}):{reason}")
    version = call(c, "GET", f"/api/schedules/{job['version_id']}", "读取新排练表")
    if version["validation_errors"]:
        raise DemoError("新排练表校验未通过,不能发布:" + ";".join(version["validation_errors"][:3]))
    return version


def set_locations(c: httpx.Client, version: dict) -> None:
    """发布前在草稿上填地点:草稿改地点不会给成员发通知。"""
    for s in version["sessions"]:
        if s["location"]:
            continue
        if s["kind"] == "evaluation":
            loc = "小剧场"
        else:
            loc = "学生活动中心 排练室 A" if date.fromisoformat(s["date"]).weekday() >= 5 else "体育馆 2 楼舞蹈室"
        call(c, "POST", f"/api/schedules/{version['id']}/sessions/{s['id']}/location", "填写排练地点", json={"location": loc})


def ensure_account(c: httpx.Client, rid: int, username: str) -> tuple[str, str]:
    """返回 (用户名, 临时密码):没有账号就开通(含自助注销过的),有就重置密码。"""
    member = next((m for m in call(c, "GET", "/api/members", "读取名册") if m["id"] == rid), None)
    if member is None:
        raise DemoError(f"名册里找不到「{REVIEWER}」")
    password = new_password()
    account = member["account"]
    if account is None:
        r = request(c, "POST", f"/api/members/{rid}/account", "开通审核账号", json={"username": username, "password": password})
        if r.status_code == 409 and username in _detail(r):
            raise DemoError(f"开通审核账号失败:用户名 {username} 已被别的账号占用,请加 --username 换一个")
        if r.status_code >= 400:
            raise DemoError(f"开通审核账号失败(HTTP {r.status_code}):{_detail(r)}")
        return r.json()["username"], password
    if not account["is_active"]:
        call(c, "PATCH", f"/api/members/{rid}/account", "启用审核账号", json={"is_active": True})
    out = call(c, "POST", f"/api/members/{rid}/account/reset", "重置审核账号密码", json={"password": password})
    return out["username"], password


def finish_reviewer(base: str, username: str, temp: str, today: date) -> tuple[str, dict, int, int]:
    """以审核员身份登录、改密码(清掉首次改密要求),并确认只看得到演示演出。"""
    rc, _ = login(base, username, temp, "审核账号登录")
    try:
        final = new_password()
        call(rc, "POST", "/api/me/password", "修改审核账号密码", json={"old_password": temp, "new_password": final})
        me = call(rc, "GET", "/api/me", "读取审核账号")
        if me["must_change_password"]:
            raise DemoError("审核账号改密后仍要求首次改密,请检查服务器版本")
        events = call(rc, "GET", "/api/events", "以审核员身份读取演出")
        names = [e["name"] for e in events]
        if names != [EVENT_NAME]:
            raise DemoError(f"审核员能看到的演出不只演示演出:{'、'.join(names) or '(没有)'}。请检查后重新运行")
        pub = call(rc, "GET", f"/api/events/{events[0]['id']}/schedule/published", "以审核员身份读取排练表")
    finally:
        logout(rc)
    mine = [s for s in pub["sessions"] if any(m["id"] == me["member_id"] for m in s["members"])]
    upcoming = [s for s in mine if date.fromisoformat(s["date"]) >= today]
    return final, pub, len(mine), len(upcoming)


def md(value: str) -> str:
    d = date.fromisoformat(value)
    return f"{d.month}/{d.day}"


def run(base: str, admin_user: str, admin_password: str, username: str) -> tuple[str, str, str]:
    today = date.today()
    admin, me = login(base, admin_user, admin_password, "管理员登录")
    try:
        if me["role"] != "admin":
            raise DemoError(f"{me['username']} 不是管理员账号")
        ev, changed = ensure_event(admin, today)
        eid = ev["id"]
        ids = ensure_members(admin)
        changed |= ensure_participants(admin, eid, ids)
        guard_reviewer(admin, eid, ids[REVIEWER])
        changed |= ensure_songs(admin, eid, ids)
        changed |= fill_availability(admin, call(admin, "GET", f"/api/events/{eid}", "读取演出"), ids)
        ev = call(admin, "GET", f"/api/events/{eid}", "读取演出")
        published_now = changed or ev["published_version_no"] is None or ev["conflict_count"] > 0
        if published_now:
            version = solve(admin, eid)
            set_locations(admin, version)
            call(admin, "POST", f"/api/schedules/{version['id']}/publish", "发布排练表")
        reviewer_name, temp = ensure_account(admin, ids[REVIEWER], username)
    finally:
        logout(admin)
    final, pub, n_mine, n_upcoming = finish_reviewer(base, reviewer_name, temp, today)
    how = "本次新发布" if published_now else "数据未变,沿用已发布版本"
    summary = (
        f"演出「{EVENT_NAME}」(#{eid}):{len(ids)} 人、{len(SONGS)} 首曲目,排练 {md(pub['formal_start_date'])}–{md(pub['formal_end_date'])},"
        f"演出 {md(pub['performance_date'])};排练表 v{pub['version_no']} 已发布({how}),共 {pub['session_count']} 场,"
        f"审核员参加 {n_mine} 场、今天起还有 {n_upcoming} 场。"
    )
    return reviewer_name, final, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="为 App Store 审核准备演示演出和审核账号(可重复运行)")
    parser.add_argument("--base", default="https://timetomeet.fly.dev", help="服务器地址")
    parser.add_argument("--username", default="appreview", help="首次开通审核账号时用的用户名")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    try:
        admin_user = os.environ.get("SEASON_ADMIN_USER") or input(f"管理员用户名({base}):").strip()
        admin_password = os.environ.get("SEASON_ADMIN_PASSWORD") or getpass.getpass("管理员密码:")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消", file=sys.stderr)
        return 1
    if not admin_user or not admin_password:
        print("错误:管理员用户名和密码都不能为空", file=sys.stderr)
        return 1
    try:
        username, password, summary = run(base, admin_user, admin_password, args.username)
    except DemoError as exc:
        print(f"错误:{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断;可以直接重新运行", file=sys.stderr)
        return 1
    print(f"审核账号用户名:{username}")
    print(f"审核账号密码:{password}")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
