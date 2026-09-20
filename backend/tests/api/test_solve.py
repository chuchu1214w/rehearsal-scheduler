"""M3:一键求解、无解诊断、排练表版本。测试用 solver_mode=inline 同步执行。"""

from fastapi.testclient import TestClient

from tests.api.conftest import add_member, add_song, make_event

# 短一点的演出:9/4 开始、9/10 演出 → 正规排练 9/4–9/8(5 天),评估日 9/9
SHORT = {"performance_date": "2026-09-10", "formal_start_date": "2026-09-04"}
DAYS = [f"2026-09-{x:02d}" for x in range(4, 10)]
FULL = {d: "1" * 13 for d in DAYS}
NONE = {d: "0" * 13 for d in DAYS}


def _setup(admin: TestClient, *, availability=None):
    a, b, c = (add_member(admin, n) for n in ("A", "B", "C"))
    ev = make_event(admin, **SHORT, member_ids=[a["id"], b["id"], c["id"]])
    s1 = add_song(admin, ev["id"], "第一首", [a["id"], b["id"]], "简单")  # 2 场 × 2h
    s2 = add_song(admin, ev["id"], "第二首", [b["id"], c["id"]], "一般", session_plan=[3])
    if availability is None:
        availability = {a["id"]: FULL, b["id"]: FULL, c["id"]: FULL}
    for mid, days in availability.items():
        assert admin.put(f"/api/events/{ev['id']}/availability/{mid}", json={"days": days, "submit": True}).status_code == 200
    return ev, (a, b, c), (s1, s2)


def test_solve_success_creates_draft_version(admin: TestClient):
    ev, (a, b, c), (s1, s2) = _setup(admin)
    r = admin.post(f"/api/events/{ev['id']}/solve", json={})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "succeeded" and job["version_id"] is not None and job["ladder_level_used"] == 0
    assert job["summary"].startswith("已生成草稿 v1") and job["elapsed_seconds"] is not None
    assert [s["key"] for s in job["stage_records"]][:2] == ["feasible", "absent"]

    assert admin.get(f"/api/solve-jobs/{job['id']}").json()["status"] == "succeeded"
    assert admin.get(f"/api/events/{ev['id']}/solve-jobs/latest").json()["id"] == job["id"]
    assert admin.post(f"/api/solve-jobs/{job['id']}/cancel").status_code == 409

    versions = admin.get(f"/api/events/{ev['id']}/schedules").json()
    assert len(versions) == 1 and versions[0]["version_no"] == 1 and versions[0]["status"] == "draft"
    assert versions[0]["session_count"] == 4  # 2 + 1 正规 + 1 评估
    detail = admin.get(f"/api/schedules/{versions[0]['id']}").json()
    kinds = [s["kind"] for s in detail["sessions"]]
    assert kinds.count("formal") == 3 and kinds.count("evaluation") == 1
    ev_session = next(s for s in detail["sessions"] if s["kind"] == "evaluation")
    assert ev_session["date"] == "2026-09-09" and ev_session["song_name"] == "全员评估"
    assert set(ev_session["attendance"]) == {"A", "B", "C"}
    formal = [s for s in detail["sessions"] if s["kind"] == "formal"]
    assert all(s["date"] <= "2026-09-08" for s in formal)
    assert {s["song_code"] for s in formal} == {s1["code"], s2["code"]}
    assert all(s["absent"] == [] for s in formal)
    stats = {m["display_name"]: m for m in detail["member_stats"]}
    assert stats["A"]["sessions"] == 2 and stats["A"]["hours"] == 4 and stats["B"]["sessions"] == 3 and stats["B"]["hours"] == 7
    assert stats["C"]["eval_time"] is not None
    assert detail["validation_errors"] == [] and detail["exact_optimum"] is True

    e = admin.get(f"/api/events/{ev['id']}").json()
    assert e["latest_version_no"] == 1 and e["published_version_no"] is None and e["latest_job_status"] == "succeeded"
    assert [s["state"] for s in e["steps"]] == ["done"] * 6 + ["current"]
    assert "草稿 v1" in e["steps"][5]["summary"] and "草稿 v1" in e["steps"][6]["summary"]

    # 再求解一次 → v2
    r2 = admin.post(f"/api/events/{ev['id']}/solve", json={})
    assert r2.json()["summary"].startswith("已生成草稿 v2")
    assert [v["version_no"] for v in admin.get(f"/api/events/{ev['id']}/schedules").json()] == [2, 1]


def test_solve_infeasible_gives_diagnosis(admin: TestClient):
    # C 全程没空:第二首(B、C)排不下
    ev, (a, b, c), _ = _setup(admin, availability={})
    for m, days in ((a, FULL), (b, FULL), (c, NONE)):
        admin.put(f"/api/events/{ev['id']}/availability/{m['id']}", json={"days": days, "submit": True})
    r = admin.post(f"/api/events/{ev['id']}/solve", json={})
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "infeasible" and job["version_id"] is None
    assert job["diagnosis"] is not None
    assert job["summary"].startswith("差 1 场") and "b" in job["summary"]
    assert job["diagnosis"]["最小调整建议"]["可行"] and {c_["成员"] for c_ in job["diagnosis"]["最小调整建议"]["调整"]} == {"C"}
    assert job["diagnosis"]["评估场"]["可行"] is False
    assert admin.get(f"/api/events/{ev['id']}/schedules").json() == []
    e = admin.get(f"/api/events/{ev['id']}").json()
    assert e["latest_job_status"] == "infeasible" and "上次无解" in e["steps"][5]["summary"]


def test_only_ready_songs_skips_unsubmitted(admin: TestClient):
    # C 未提交 → 第二首不就绪;只排就绪曲目时跳过它
    ev, (a, b, c), (s1, s2) = _setup(admin, availability={})
    for m in (a, b):
        admin.put(f"/api/events/{ev['id']}/availability/{m['id']}", json={"days": FULL, "submit": True})
    r = admin.post(f"/api/events/{ev['id']}/solve", json={"only_ready_songs": True})
    assert r.status_code == 202
    job = r.json()
    # C 未提交视为全天没空,评估场也排不了 → 仍无解,但跳过的曲目已记录
    assert job["skipped_songs"] == [s2["code"]] and job["only_ready_songs"] is True
    assert job["status"] == "infeasible" and job["diagnosis"]["评估场"]["可行"] is False

    # C 也提交后,只排就绪曲目 = 全部曲目
    admin.put(f"/api/events/{ev['id']}/availability/{c['id']}", json={"days": FULL, "submit": True})
    job2 = admin.post(f"/api/events/{ev['id']}/solve", json={"only_ready_songs": True}).json()
    assert job2["status"] == "succeeded" and job2["skipped_songs"] == []
    detail = admin.get(f"/api/schedules/{job2['version_id']}").json()
    assert {s["song_code"] for s in detail["sessions"] if s["kind"] == "formal"} == {s1["code"], s2["code"]}


def test_solve_requires_data(admin: TestClient):
    ev = make_event(admin, **SHORT)
    assert admin.post(f"/api/events/{ev['id']}/solve", json={}).status_code == 422
    assert admin.get(f"/api/events/{ev['id']}/solve-jobs/latest").status_code == 404
    assert admin.get("/api/solve-jobs/999").status_code == 404
    assert admin.get("/api/schedules/999").status_code == 404
