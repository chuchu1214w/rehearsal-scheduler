from solver.candidates import build_candidates, make_tasks
from solver.diagnosis import diagnose, max_coverage, minimum_adjustment, near_miss
from solver.types import UNAVAILABLE
from tests.conftest import START, set_slots


def test_near_miss_lists_single_blocker(problem):
    set_slots(problem.availability, "A", START, [0])
    rows = near_miss(problem, ["s1"])
    hit = [r for r in rows if r["日期"] == START.isoformat() and r["时间段"] == "10:00–12:00"]
    assert hit and hit[0]["只差成员"] == "A" and hit[0]["需开放小时数"] == 1


def test_max_coverage_counts_schedulable_tasks(problem):
    for d in problem.config.formal_dates:
        problem.availability.set_row("B", d, [UNAVAILABLE] * 13)
    tasks = make_tasks(problem)
    cands = build_candidates(problem, tasks, allow_absent=False)
    total, counts, status = max_coverage(problem, tasks, cands)
    assert total == 2 and counts == {"s1": 0, "s2": 0, "s3": 2}


def test_minimum_adjustment_prefers_fewer_members(problem):
    # A 与 B 各缺一格,只需一人调整即可让 s1 排上;但 s2 也需要 B,最优是只动 B
    for d in problem.config.formal_dates:
        problem.availability.set_row("B", d, [UNAVAILABLE] * 13)
    adj = minimum_adjustment(problem, make_tasks(problem))
    assert adj["可行"] and adj["受影响成员数"] == 1 and adj["调整小时数"] == 7
    assert len(adj["放宽后示例"]) == 5


def test_full_report_shape(problem):
    for d in problem.config.all_dates:  # 含评估日
        problem.availability.set_row("B", d, [UNAVAILABLE] * 13)
    report = diagnose(problem)
    assert set(report) >= {"无候选任务", "最大覆盖", "各曲缺口", "只差一人的时段", "最小调整建议", "评估场"}
    gaps = {r["曲目"]: r for r in report["各曲缺口"]}
    assert gaps["s1"]["单曲缺口"] == 2 and gaps["s3"]["单曲缺口"] == 0
    assert report["评估场"]["可行"] is False  # B 在评估日也没空
