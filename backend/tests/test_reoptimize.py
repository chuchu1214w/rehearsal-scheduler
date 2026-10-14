"""少改动重排(开发文档 §4.8 EDIT-11):只挪必要的场次,锁定 / 无法挪动的原样保留,结果不引入新冲突。"""

from dataclasses import replace
from datetime import date

from solver.reoptimize import reoptimize
from solver.types import KIND_FORMAL, Availability, EventConfig, FixedSession, Problem, Rules, Session, Song
from solver.validator import validate_schedule

CFG = EventConfig(performance_date=date(2026, 9, 12), formal_start_date=date(2026, 9, 4))
ALL = list(range(CFG.slots_per_day))
D4, D5, D6, D7, D8 = (date(2026, 9, d) for d in (4, 5, 6, 7, 8))


def _problem(free: dict, rules: Rules | None = None, songs: tuple | None = None, cfg: EventConfig = CFG) -> Problem:
    """free:成员 → (日期 → 有空的格);没写的日期全天有空。"""
    songs = songs or (Song("s1", "第一首", "一般", ("A", "B"), (2, 2)), Song("s2", "第二首", "简单", ("B", "C"), (2,)))
    members = tuple(sorted({m for s in songs for m in s.members}))
    av = Availability()
    for m in members:
        for d in cfg.all_dates:
            hours = free.get(m, {}).get(d, ALL)
            av.set_row(m, d, [1 if h in hours else 0 for h in range(cfg.slots_per_day)])
    return Problem(cfg, members, songs, av, rules or Rules())


def _moved(problem: Problem, s: Session, d: date, start: int) -> Session:
    """与写入时一致:挪过去后,参演成员里那段时间没空的缺席,计划内缺席(出勤上限)保留。"""
    code = s.song_code or ""
    planned = {m for m in s.absent_members if problem.rules.attendance_cap(m, code) is not None}
    busy = {
        m
        for m in problem.song(code).members
        if m not in planned and not all(problem.availability.is_available(m, d, h) for h in range(start, start + s.duration))
    }
    return replace(s, date=d, start=start, absent_members=tuple(sorted(planned | busy)))


def _apply(problem: Problem, sessions: list[Session], result) -> list[str]:
    """应用提案;返回应用后新出现的错误(评估场不在这些例子里,忽略 V-07)。"""
    level = problem.ladder[-1]  # 与线上一致:按演出设置允许的缺席规则检查
    before = set(validate_schedule(problem, sessions, level).errors)
    after = [replace(s) for s in sessions]
    for m in result.moves:
        after[m.index] = _moved(problem, after[m.index], m.date, m.start)
    return [e for e in validate_schedule(problem, after, level).errors if e not in before and not e.startswith("V-07")]


def _errors(problem: Problem, sessions: list[Session], result) -> list[str]:
    after = [replace(s) for s in sessions]
    for m in result.moves:
        after[m.index] = _moved(problem, after[m.index], m.date, m.start)
    return [e for e in validate_schedule(problem, after, problem.ladder[-1]).errors if not e.startswith("V-07")]


def test_moves_one_session_past_a_same_length_sibling_locked_or_not():
    # A 在 9/4、9/5 没空:9/4 那场只能挪到 9/6 那场(同曲同时长)之后;只挪这一场
    p = _problem({"A": {D4: [], D5: []}})
    for locked in (True, False):
        ss = [
            Session(KIND_FORMAL, D4, 0, 2, "s1", 1),
            Session(KIND_FORMAL, D6, 0, 2, "s1", 2, locked=locked),
            Session(KIND_FORMAL, D8, 6, 2, "s2", 1),
        ]
        r = reoptimize(p, ss, time_limit=5)
        assert r.status == "ok" and [m.index for m in r.moves] == [0], (locked, r)
        assert _errors(p, ss, r) == []


def test_absence_is_kept_but_slot_need_not_be_one_where_the_absentee_is_busy():
    # 第一首这场 A 缺席(当初 A 没空),现在 A 有空了:它仍是合法的(谁缺席不变),只需挪一场消除与第二首的重叠;
    # 锁定时它原样保留(不是「锁定场次本身有冲突」),挪第二首
    p = _problem({}, Rules(member_song_max_absent={("A", "s1"): 1}))
    ss = [
        Session(KIND_FORMAL, D4, 0, 2, "s1", 1, absent_members=("A",)),
        Session(KIND_FORMAL, D6, 0, 2, "s1", 2),
        Session(KIND_FORMAL, D4, 0, 2, "s2", 1),  # B 重叠
    ]
    for locked in (False, True):
        ss[0] = replace(ss[0], locked=locked)
        r = reoptimize(p, ss, time_limit=5)
        assert r.status == "ok" and len(r.moves) == 1 and (not locked or r.moves[0].index == 2), (locked, r)
        assert _errors(p, ss, r) == []


def test_unmovable_sessions_still_block_their_members_time():
    # 第二首那场缺席 2 人且锁定(原样保留):照样占用 B 的时间、计入缺席上限;第一首不能挪到和它重叠的时段
    p = _problem({"A": {D4: [0, 1], D6: [0, 1], D5: [], D7: [], D8: []}})
    ss = [
        Session(KIND_FORMAL, D6, 0, 2, "s1", 1),
        Session(KIND_FORMAL, D8, 0, 2, "s1", 2),  # A 在 9/8 没空 → 要挪,只剩 9/4 0–2 点(被下面那场占着 B)
        Session(KIND_FORMAL, D5, 0, 2, "s2", 1),
        Session(KIND_FORMAL, D4, 0, 2, "s2", 2, absent_members=("B", "C"), locked=True),
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert _apply(p, ss, r) == []
    assert all(m.index != 3 for m in r.moves)


def test_fixed_rule_outside_formal_dates_and_absence_rule_violations_do_not_block():
    # 「固定场次」要求已不在排练日期内、出勤上限已被违反:都与挪动无关,照样给出消除重叠的提案
    rules = Rules(
        member_song_max_attendance={("A", "s1"): 1},
        fixed_sessions=(FixedSession("s1", date(2026, 9, 1), 0, 2, None),),
    )
    p = _problem({}, rules)
    ss = [
        Session(KIND_FORMAL, D4, 0, 2, "s1", 1),
        Session(KIND_FORMAL, D6, 0, 2, "s1", 2),
        Session(KIND_FORMAL, D4, 0, 2, "s2", 1),  # B 重叠
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert r.status == "ok" and len(r.moves) == 1
    assert not [e for e in _errors(p, ss, r) if e.startswith(("V-04", "V-02", "V-06"))]


def test_session_matching_a_fixed_rule_stays_put():
    rules = Rules(fixed_sessions=(FixedSession("s1", D4, 0, 2, None),))
    p = _problem({}, rules)
    ss = [
        Session(KIND_FORMAL, D4, 0, 2, "s1", 1),
        Session(KIND_FORMAL, D6, 0, 2, "s1", 2),
        Session(KIND_FORMAL, D4, 1, 2, "s2", 1),  # B 重叠:只能挪第二首
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert r.status == "ok" and [m.index for m in r.moves] == [2]


# ---------- 第二轮复查发现的问题(回归) ----------
def test_daily_limit_counts_overlapping_kept_sessions_by_duration():
    # B 在 9/4 已有两场锁定且互相重叠(按时长共 8 小时 = 上限):第三首不能再挪到 9/4
    songs = (
        Song("s1", "一", "一般", ("A", "B"), (4,)),
        Song("s2", "二", "一般", ("B", "C"), (4,)),
        Song("s3", "三", "一般", ("B", "D"), (4,)),
    )
    p = _problem({"B": {d: [] for d in (D5, D6, D7, D8)}}, songs=songs)
    ss = [
        Session(KIND_FORMAL, D4, 0, 4, "s1", 1, locked=True),
        Session(KIND_FORMAL, D4, 0, 4, "s2", 1, locked=True),
        Session(KIND_FORMAL, D5, 0, 4, "s3", 1),
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert _apply(p, ss, r) == [], r


def test_sessions_of_deleted_songs_still_count_toward_the_date_limit():
    p = _problem({"A": {D5: [], D7: [], D8: []}}, Rules(max_sessions_per_date={D4: 1}))
    ss = [
        Session(KIND_FORMAL, D6, 0, 2, "s1", 1),
        Session(KIND_FORMAL, D8, 0, 2, "s1", 2),  # A 在 9/8 没空,能去的只有 9/4,但 9/4 已有一场(曲目已删除)
        Session(KIND_FORMAL, D4, 6, 2, None, 1),
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert _apply(p, ss, r) == [], r


def test_a_session_longer_than_the_daily_limit_does_not_block_other_fixes():
    cfg = EventConfig(performance_date=date(2026, 9, 12), formal_start_date=D4, soft_daily_limit=5, hard_daily_limit=5)
    songs = (Song("s1", "一", "一般", ("A",), (6,)), Song("s2", "二", "一般", ("B", "C"), (2,)), Song("s3", "三", "一般", ("C", "D"), (2,)))
    p = _problem({}, songs=songs, cfg=cfg)
    ss = [
        Session(KIND_FORMAL, D4, 0, 6, "s1", 1),  # 被拉长到 6 小时,超过单日上限
        Session(KIND_FORMAL, D5, 0, 2, "s2", 1),
        Session(KIND_FORMAL, D5, 1, 2, "s3", 1),  # C 重叠
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert r.status == "ok" and len(r.moves) == 1 and r.moves[0].index != 0, r
    assert not [e for e in _errors(p, ss, r) if e.startswith("V-04")]


def test_a_fixed_rule_keeps_only_one_of_two_identical_sessions():
    p = _problem({}, Rules(fixed_sessions=(FixedSession("s1", D4, 0, 2, None),)))
    ss = [Session(KIND_FORMAL, D4, 0, 2, "s1", 1), Session(KIND_FORMAL, D4, 0, 2, "s1", 2), Session(KIND_FORMAL, D7, 0, 2, "s2", 1)]
    r = reoptimize(p, ss, time_limit=5)
    assert r.status == "ok" and len(r.moves) == 1
    assert not [e for e in _errors(p, ss, r) if e.startswith(("V-04", "V-06"))]


def test_a_song_with_more_sessions_than_days_does_not_block_other_fixes():
    # 3 个排练日,第一首有 4 场(必有两场同一天,解决不了);另外第二首与第三首在 9/6 让 C 重叠,挪一场就好
    cfg = EventConfig(performance_date=date(2026, 9, 8), formal_start_date=D4)
    songs = (
        Song("s1", "一", "一般", ("A",), (1, 1, 1, 1)),
        Song("s2", "二", "一般", ("B", "C"), (2,)),
        Song("s3", "三", "一般", ("C", "D"), (2,)),
    )
    p = _problem({}, songs=songs, cfg=cfg)
    ss = [
        Session(KIND_FORMAL, D4, 0, 1, "s1", 1),
        Session(KIND_FORMAL, D5, 0, 1, "s1", 2),
        Session(KIND_FORMAL, D6, 0, 1, "s1", 3),
        Session(KIND_FORMAL, D6, 5, 1, "s1", 4),
        Session(KIND_FORMAL, D6, 2, 2, "s2", 1),
        Session(KIND_FORMAL, D6, 3, 2, "s3", 1),
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert r.status == "ok" and len(r.moves) == 1, r
    assert _apply(p, ss, r) == []
    assert not [e for e in _errors(p, ss, r) if e.startswith("V-04")]


# ---------- 拖动后自动记缺席之后的复查(回归) ----------
def test_one_unfixable_session_does_not_block_other_fixes():
    # C 哪天都没空:第二首两场都只能让 C 缺席,而每首至少 1 场全员到齐 → 第二首#1 怎么挪都不行(原样保留);
    # 第一首#1 与它让 B 重叠,挪开一场就好
    p = _problem({"C": {d: [] for d in CFG.all_dates}})
    p = replace(p, songs=(p.songs[0], replace(p.songs[1], session_plan=(2, 2))))
    ss = [
        Session(KIND_FORMAL, D4, 0, 2, "s2", 1),
        Session(KIND_FORMAL, D6, 0, 2, "s2", 2, absent_members=("C",)),
        Session(KIND_FORMAL, D4, 1, 2, "s1", 1),
        Session(KIND_FORMAL, D5, 0, 2, "s1", 2),
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert r.status == "ok" and 2 in [m.index for m in r.moves], r
    assert not [e for e in _errors(p, ss, r) if e.startswith("V-04")]
    assert _apply(p, ss, r) == []


def test_absences_of_deleted_song_sessions_count_toward_the_cap():
    # 默认 25%:4 场里最多 1 场有人缺席,已删除曲目的那场已经占了这 1 场 → 第一首不能靠让 A 缺席来解决
    p = _problem({"A": {d: [] for d in CFG.all_dates if d != D6}})
    ss = [
        Session(KIND_FORMAL, D4, 0, 2, "s1", 1),  # A 没空
        Session(KIND_FORMAL, D6, 0, 2, "s1", 2),
        Session(KIND_FORMAL, D7, 4, 2, "s2", 1),
        Session(KIND_FORMAL, D5, 0, 2, None, 1, absent_members=("C",)),
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert _apply(p, ss, r) == [], r


def test_prefers_a_slot_where_everyone_can_come():
    # 允许缺席时,同样挪 1 场,宁可换到大家都有空的日子,也不在同一天挪一小时让人缺席
    from solver.types import LadderLevel

    p = _problem({"A": {D5: []}})
    p = replace(p, ladder=(LadderLevel(0), LadderLevel(1, 0.5, 1, 1)))
    ss = [
        Session(KIND_FORMAL, D5, 0, 2, "s1", 1),  # A 这天没空
        Session(KIND_FORMAL, D7, 0, 2, "s1", 2),
        Session(KIND_FORMAL, D8, 4, 2, "s2", 1),
    ]
    r = reoptimize(p, ss, time_limit=5)
    assert r.status == "ok" and len(r.moves) == 1 and r.moves[0].date != D5, r
