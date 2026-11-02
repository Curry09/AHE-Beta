"""spec-0001/T6：本地 SessionStore 落盘与索引单测。"""

from __future__ import annotations

import pytest

from ahe_beta.models import (
    FeelingScore,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
    SimTrace,
    Transcript,
    Turn,
)
from ahe_beta.user.session_store import SessionConflictError, SessionStore


def _session(n_issues: int = 1) -> Session:
    return Session(
        persona=Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s"),
        scenario=SeedScenario(description="x"),
        transcript=Transcript(turns=[Turn("user", "a"), Turn("harness", "b")]),
        feeling=FeelingScore(score=3, reason="还行"),
        issue_refs=[
            IssueRef(number=i + 1, url=f"fake://issues/{i + 1}", state="open")
            for i in range(n_issues)
        ],
    )


def test_save_writes_full_and_index(tmp_path) -> None:
    store = SessionStore(tmp_path)
    s = _session(n_issues=2)
    store.save(s)
    assert (tmp_path / f"{s.session_id}.json").exists()
    entries = store.index()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["session_id"] == s.session_id
    assert entry["score"] == 3
    assert entry["n_issues"] == 2
    assert entry["created_at"] == s.created_at.isoformat()


def test_index_keeps_subjective_and_objective_acceptance_separate(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = _session()
    session.user_outcome = {"end_reason": "accepted"}
    session.accept_validity = "false_accept"
    session.objective_evaluation = {"status": "completed", "fresh": True, "passed": False}
    store.save(session)

    row = store.index()[0]
    assert row["user_outcome"] == "accepted"
    assert row["accept_validity"] == "false_accept"
    assert row["objective_passed"] is False


def test_save_auto_creates_root(tmp_path) -> None:
    store = SessionStore(tmp_path / "nested" / "sessions")
    s = _session()
    store.save(s)  # 不存在的 root 应自动创建
    assert store.load(s.session_id) == s


def test_load_round_trip(tmp_path) -> None:
    store = SessionStore(tmp_path)
    s = _session()
    store.save(s)
    assert store.load(s.session_id) == s


def test_index_empty_when_no_file(tmp_path) -> None:
    assert SessionStore(tmp_path).index() == []


def test_invalid_evaluator_session_is_persisted_but_excluded_from_default_index(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = _session()
    session.sim_trace = SimTrace(
        persona_id="P",
        end_reason="evaluator_invalid",
        evaluation_status="invalid",
        evaluation_error={"stage": "main_act", "code": "missing_action"},
    )
    store.save(session)

    assert store.load(session.session_id).sim_trace.evaluation_status == "invalid"
    assert store.index() == []
    assert store.index(include_invalid=True)[0]["evaluation_status"] == "invalid"


def test_multiple_saves_append_index(tmp_path) -> None:
    store = SessionStore(tmp_path)
    store.save(_session())
    store.save(_session())
    assert len(store.index()) == 2


def test_n_issues_zero(tmp_path) -> None:
    store = SessionStore(tmp_path)
    s = _session(n_issues=0)
    store.save(s)
    assert store.index()[0]["n_issues"] == 0


def test_load_missing_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        SessionStore(tmp_path).load("nope")


def test_resave_same_content_is_idempotent_index_upsert(tmp_path) -> None:
    store = SessionStore(tmp_path)
    s = _session()
    store.save(s)
    store.save(s)
    assert len(store.index()) == 1


def test_stable_session_id_rejects_different_content(tmp_path) -> None:
    store = SessionStore(tmp_path)
    first = _session()
    store.save(first)
    changed = _session(n_issues=0)
    changed.session_id = first.session_id
    with pytest.raises(SessionConflictError, match="different content"):
        store.save(changed)
    assert store.load(first.session_id) == first


def test_legacy_second_save_may_only_attach_issue_handoff(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = _session(n_issues=0)
    store.save(session)
    session.issue_refs = [IssueRef(number=7, url="fake://issues/7", state="open")]
    session.user_feedback_envelope = {"level": "L1", "source_issue_ids": [7]}

    store.save(session)

    assert store.load(session.session_id).issue_refs[0].number == 7
    assert store.index()[0]["issue_numbers"] == [7]


def test_reconcile_repairs_missing_or_duplicate_index_without_rewriting_session(tmp_path) -> None:
    import json

    store = SessionStore(tmp_path)
    session = _session()
    store.save(session)
    full = tmp_path / f"{session.session_id}.json"
    original = full.read_bytes()
    row = store.index()[0]
    (tmp_path / "index.json").write_text(json.dumps([row, row]), encoding="utf-8")
    assert store.reconcile(session.session_id) == session
    assert store.index() == [row]
    assert full.read_bytes() == original


def test_reconcile_missing_session_returns_none_and_ids_are_path_safe(tmp_path) -> None:
    store = SessionStore(tmp_path)
    assert store.reconcile("missing") is None
    with pytest.raises(ValueError, match="invalid session id"):
        store.load("../escape")


def test_find_session_by_issue_recovers_from_empty_index(tmp_path) -> None:
    store = SessionStore(tmp_path)
    session = _session()
    store.save(session)
    (tmp_path / "index.json").write_text("[]\n", encoding="utf-8")

    assert store.find_session_id_by_issue(1) == session.session_id
    assert store.index(include_invalid=True)[0]["issue_numbers"] == [1]


def test_rebuild_index_recovers_all_authoritative_session_files(tmp_path) -> None:
    store = SessionStore(tmp_path)
    first = _session()
    second = _session()
    second.session_id = "second-session"
    store.save(first)
    store.save(second)
    (tmp_path / "index.json").write_text("[]\n", encoding="utf-8")

    rows = store.rebuild_index()
    assert {row["session_id"] for row in rows} == {first.session_id, second.session_id}
    assert len(store.index(include_invalid=True)) == 2


def test_concurrent_saves_lose_no_index_entries(tmp_path) -> None:
    """Spec-0017/T1 竞态回归：并发 save N 局后 index 恰好 N 条、全量文件 N 个。

    加锁前 index.json 是无锁读-改-写，并发追加会基于同一旧快照互相覆盖（丢条目）。
    用屏障让所有线程同时冲 save，最大化竞态窗口。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    store = SessionStore(tmp_path)
    n = 16
    sessions = [_session() for _ in range(n)]
    barrier = threading.Barrier(n)

    def save_one(s):
        barrier.wait()  # 齐射，逼出读-改-写交错
        store.save(s)

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(save_one, sessions))

    entries = store.index()
    assert len(entries) == n  # 丢条目即回归
    assert {e["session_id"] for e in entries} == {s.session_id for s in sessions}
    full_files = {p.name for p in tmp_path.glob("*.json")} - {"index.json"}
    assert len(full_files) == n  # 全量文件一个不少，逐个可读回
    for s in sessions:
        assert store.load(s.session_id) == s
