"""spec-0001/T6：本地 SessionStore 落盘与索引单测。"""

from __future__ import annotations

import pytest

from auto_designer.models import (
    FeelingScore,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
    Transcript,
    Turn,
)
from auto_designer.user.session_store import SessionStore


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


def test_resave_overwrites_full_index_duplicates(tmp_path) -> None:
    store = SessionStore(tmp_path)
    s = _session()
    store.save(s)
    store.save(s)
    # 全量被覆盖（仍单文件），索引不去重 → 两条
    assert len(store.index()) == 2


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
