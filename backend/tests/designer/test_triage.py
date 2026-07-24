# Spec-0025/T3：Triager 单测——四路 disposition（accept/duplicate/reject/needs_info）就地落库。
"""stub agent（回放固定 disposition JSON）+ FakeTracker + 临时 SessionStore：验证 driver 把
每条 disposition 正确落成标签/评论/关闭，不跑真 nexau。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.designer.issue_schema import NEEDS_INFO, NEEDS_TRIAGE, REJECTED, TRIAGED
from auto_designer.designer.triage import (
    TriageOutcome,
    Triager,
    _confirmed_labels,
    _parse_dispositions,
)
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


class _StubTriager(Triager):
    """覆盖 _run_agent：不跑真 nexau，回放固定 disposition JSON，并记录喂进的待分诊集合。"""

    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_pending: list = []

    def _run_agent(self, *, pending: list, triaged: list) -> str:
        self.seen_pending = pending
        return self._canned


def _triager(tmp_path: Path, tracker: FakeTracker, canned: str) -> _StubTriager:
    store = SessionStore(tmp_path / "sessions")
    return _StubTriager(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent_def"), canned=canned
    )


def _raw(tracker: FakeTracker, title: str, kind: str = "bug") -> int:
    return tracker.create_issue(
        IssueDraft(title=title, body="x", labels=[kind, NEEDS_TRIAGE, "round-1"])
    ).number


def test_no_pending_is_noop(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="已 triaged", body="x", labels=["bug", TRIAGED]))
    out = _triager(tmp_path, tracker, "[]").triage_once()
    assert out.handled == 0
    assert _triager(tmp_path, tracker, "[]").seen_pending == []  # 无 needs-triage → 不跑


def test_accept_confirms_labels_and_comments_triage_fields(tmp_path) -> None:
    tracker = FakeTracker()
    n = _raw(tracker, "unidecode 超时", kind="bug")
    canned = json.dumps(
        [
            {
                "issue": n,
                "disposition": "accept",
                "kind": "bug",
                "priority": "P1",
                "fields": {
                    "根因区域": "entry.py 无预算感知",
                    "边界": "只改通用能力",
                    "验收": "同类任务预算内给交付",
                },
            }
        ],
        ensure_ascii=False,
    )
    out = _triager(tmp_path, tracker, canned).triage_once()

    assert out.accepted == [n]
    snap = tracker.issue(n)
    assert TRIAGED in snap["labels"] and "bug" in snap["labels"]
    assert "P1" in snap["labels"]  # triage 打的优先级
    assert NEEDS_TRIAGE not in snap["labels"]  # 去掉待分诊
    assert "round-1" in snap["labels"]  # 轮号保留
    assert snap["state"] == "open"  # 采纳 → 仍 open 待 dev 领
    assert any("根因区域" in c and "entry.py 无预算感知" in c for c in snap["comments"])


def test_variant_schema_issue_number_and_flat_fields_processed(tmp_path) -> None:
    """线上实测：agent 不照契约、自创 issue_number/status + 字段平铺顶层。driver 应容错归一：
    issue_number→issue、status=confirmed_bug→accept、平铺的根因区域/边界/验收→fields，仍能采纳。"""
    tracker = FakeTracker()
    n = _raw(tracker, "从零构建包超时", kind="bug")
    canned = json.dumps(
        [
            {
                "issue_number": n,  # 非 issue
                "kind": "bug",
                "status": "confirmed_bug",  # 非 disposition
                "duplicate_of": None,
                "needs_info": False,
                "reject": False,
                "priority": "P1",
                # 字段平铺在顶层（非 fields）
                "根因区域": "entry.py 无预算感知，大任务一轮做不完",
                "边界": "只改 harness 通用能力",
                "验收": "同类任务预算内给交付或明确进度",
            }
        ],
        ensure_ascii=False,
    )
    out = _triager(tmp_path, tracker, canned).triage_once()
    assert out.accepted == [n]  # 修复前是 0（int(None) 直接 skip）
    snap = tracker.issue(n)
    assert TRIAGED in snap["labels"] and "P1" in snap["labels"] and NEEDS_TRIAGE not in snap["labels"]


def test_variant_schema_reject_and_duplicate_flags(tmp_path) -> None:
    """容错推断 disposition：reject=true→reject、duplicate_of 非空→duplicate（of 取 duplicate_of）。"""
    tracker = FakeTracker()
    main = tracker.create_issue(
        IssueDraft(title="主", body="x", labels=["bug", TRIAGED])
    ).number
    dup = _raw(tracker, "重复的")
    bad = _raw(tracker, "超范围的")
    canned = json.dumps(
        [
            {"issue_number": dup, "duplicate_of": main, "note": "同根因"},
            {"issue_number": bad, "reject": True, "reason": "要改的是 launcher（编排层）"},
        ],
        ensure_ascii=False,
    )
    out = _triager(tmp_path, tracker, canned).triage_once()
    assert out.duplicate == [dup] and out.rejected == [bad]
    assert tracker.issue(dup)["state"] == "closed"
    assert tracker.issue(bad)["state"] == "closed"


def test_accept_feature_uses_feature_triage_fields(tmp_path) -> None:
    """feature 的 TRIAGE 字段是 边界/交付物/验收（非 bug 的根因区域）——填对即采纳。"""
    tracker = FakeTracker()
    n = _raw(tracker, "希望批量导出", kind="feature")
    canned = json.dumps(
        [
            {
                "issue": n,
                "disposition": "accept",
                "kind": "feature",
                "priority": "P2",
                "fields": {"边界": "只加通用能力", "交付物": "导出接口", "验收": "能批量导出"},
            }
        ],
        ensure_ascii=False,
    )
    out = _triager(tmp_path, tracker, canned).triage_once()
    assert out.accepted == [n]
    snap = tracker.issue(n)
    assert "feature" in snap["labels"] and "P2" in snap["labels"] and TRIAGED in snap["labels"]
    assert any("交付物" in c and "导出接口" in c for c in snap["comments"])


def test_accept_invalid_priority_not_labeled(tmp_path) -> None:
    """priority 非法（不在 P0-P3）→ 不打优先级标签，但仍采纳（priority 是判断非硬闸）。"""
    tracker = FakeTracker()
    n = _raw(tracker, "超时")
    canned = json.dumps(
        [
            {
                "issue": n,
                "disposition": "accept",
                "kind": "bug",
                "priority": "紧急",  # 非法
                "fields": {"根因区域": "a", "边界": "b", "验收": "c"},
            }
        ],
        ensure_ascii=False,
    )
    _triager(tmp_path, tracker, canned).triage_once()
    labels = tracker.issue(n)["labels"]
    assert TRIAGED in labels and not any(p in labels for p in ("P0", "P1", "P2", "P3"))


def test_accept_missing_triage_fields_downgrades_to_needs_info(tmp_path) -> None:
    """采纳但 TRIAGE 字段没填全 → 降级 needs_info（保证采纳的 issue 定位完整）。"""
    tracker = FakeTracker()
    n = _raw(tracker, "坏了")
    canned = json.dumps(
        [
            {
                "issue": n,
                "disposition": "accept",
                "kind": "bug",
                "fields": {"根因区域": "只填了这个"},
            }
        ],
        ensure_ascii=False,
    )
    out = _triager(tmp_path, tracker, canned).triage_once()
    assert out.needs_info == [n] and out.accepted == []
    snap = tracker.issue(n)
    assert NEEDS_INFO in snap["labels"] and snap["state"] == "closed"


def test_accept_reclassifies_kind(tmp_path) -> None:
    """暂定 bug，triage 改判 feature → 旧 type 被替换。"""
    tracker = FakeTracker()
    n = _raw(tracker, "希望加个功能", kind="bug")
    canned = json.dumps(
        [
            {
                "issue": n,
                "disposition": "accept",
                "kind": "feature",
                "fields": {"边界": "b", "交付物": "d", "验收": "a"},
            }
        ],
        ensure_ascii=False,
    )
    _triager(tmp_path, tracker, canned).triage_once()
    labels = tracker.issue(n)["labels"]
    assert "feature" in labels and "bug" not in labels  # 改判、旧 type 去掉


def test_duplicate_closes_and_links(tmp_path) -> None:
    tracker = FakeTracker()
    main = tracker.create_issue(IssueDraft(title="主", body="x", labels=["bug", TRIAGED])).number
    dup = _raw(tracker, "重复的")
    canned = json.dumps(
        [{"issue": dup, "disposition": "duplicate", "of": main, "note": "同根因"}],
        ensure_ascii=False,
    )
    out = _triager(tmp_path, tracker, canned).triage_once()
    assert out.duplicate == [dup]
    snap = tracker.issue(dup)
    assert snap["state"] == "closed"
    assert any(f"duplicate of #{main}" in c for c in snap["comments"])


def test_reject_and_needs_info_close_with_reason(tmp_path) -> None:
    tracker = FakeTracker()
    rej = _raw(tracker, "要改 launcher")
    ni = _raw(tracker, "就说坏了")
    canned = json.dumps(
        [
            {"issue": rej, "disposition": "reject", "reason": "属传输层，非 harness 本体"},
            {"issue": ni, "disposition": "needs_info", "reason": "无有效复现"},
        ],
        ensure_ascii=False,
    )
    out = _triager(tmp_path, tracker, canned).triage_once()

    assert out.rejected == [rej] and out.needs_info == [ni]
    rsnap = tracker.issue(rej)
    assert REJECTED in rsnap["labels"] and rsnap["state"] == "closed"
    assert any("传输层" in c for c in rsnap["comments"])
    nsnap = tracker.issue(ni)
    assert NEEDS_INFO in nsnap["labels"] and nsnap["state"] == "closed"


def test_disposition_for_unknown_issue_skipped(tmp_path) -> None:
    """disposition 指向不在本轮待分诊集合的号 → 跳过，不越界改动。"""
    tracker = FakeTracker()
    n = _raw(tracker, "真的待分诊")
    canned = json.dumps(
        [
            {"issue": 999, "disposition": "reject", "reason": "幽灵"},
            {"issue": n, "disposition": "reject", "reason": "真的"},
        ],
        ensure_ascii=False,
    )
    out = _triager(tmp_path, tracker, canned).triage_once()
    assert out.rejected == [n]  # 只处理了真实待分诊那条


def test_parse_dispositions_tolerates_prose_and_bad() -> None:
    assert _parse_dispositions("") == []
    assert _parse_dispositions("没有 JSON 的散文") == []
    text = '想了想：\n[{"issue": 1, "disposition": "reject", "reason": "x"}]\n以上。'
    assert _parse_dispositions(text) == [{"issue": 1, "disposition": "reject", "reason": "x"}]


def test_confirmed_labels_drops_old_type_and_workflow() -> None:
    got = _confirmed_labels(["bug", "needs-triage", "round-2", "custom"], "feature")
    assert set(got) == {
        "feature",
        "triaged",
        "round-2",
        "custom",
    }  # 去 bug/needs-triage，留 round/custom


def test_outcome_dataclass_shape() -> None:
    o = TriageOutcome(accepted=[1], rejected=[2])
    assert o.handled == 2
