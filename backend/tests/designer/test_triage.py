# Spec-0027/T2：Triager 单测——submit_triage 原生结构化路径 + 四路 disposition 就地落库。
"""stub agent（回放 submit_triage 的回显 JSON `{"dispositions":[...]}`）+ FakeTracker + 临时
SessionStore：验证 driver 把每条已校验 disposition 正确落成标签/评论/关闭，不跑真 nexau。

nexau 在工具调用层已按 input_schema 强校验参数（漂移字段/非法 enum 吐不出 → 重试），故 driver 读到的
永远是契约干净的 dispositions；这里的 canned 数据也都用契约字段（issue/disposition/kind/priority/
fields/of/reason），不再有 issue_number/status/triage_decision/顶层平铺那类漂移（那些在工具层就被拒、
到不了 driver）。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from auto_designer.designer.agent_contract import dispositions_input_schema
from auto_designer.designer.issue_schema import NEEDS_INFO, NEEDS_TRIAGE, REJECTED, TRIAGED
from auto_designer.designer.triage import TriageOutcome, Triager, _confirmed_labels
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


class _StubTriager(Triager):
    """覆盖 _run_agent：不跑真 nexau，回放 submit_triage 的回显 JSON，并记录喂进的待分诊集合。

    dispositions：契约干净的 disposition 列表 → 包成 `{"dispositions": [...]}`（模拟 binding 回显）。
    raw：直接指定 agent.run 的返回文本（测「未调 submit / 非合规 JSON → 本轮 no-op」兜底）。
    """

    def __init__(self, *args, dispositions=None, raw=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._raw = (
            raw
            if raw is not None
            else json.dumps({"dispositions": dispositions or []}, ensure_ascii=False)
        )
        self.seen_pending: list = []

    def _run_agent(self, *, pending: list, triaged: list) -> str:
        self.seen_pending = pending
        return self._raw


def _triager(tmp_path: Path, tracker: FakeTracker, *, dispositions=None, raw=None) -> _StubTriager:
    store = SessionStore(tmp_path / "sessions")
    return _StubTriager(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "agent_def"),
        dispositions=dispositions,
        raw=raw,
    )


def _raw(tracker: FakeTracker, title: str, kind: str = "bug") -> int:
    return tracker.create_issue(
        IssueDraft(title=title, body="x", labels=[kind, NEEDS_TRIAGE, "round-1"])
    ).number


def test_submit_triage_yaml_matches_contract() -> None:
    """drift-guard：submit_triage.tool.yaml 的 input_schema 与 agent_contract 生成的深度相等——
    改字段只改 issue_schema.SCHEMAS 后需重新生成 yaml，否则此测试红（保单一真源）。"""
    yaml_path = (
        Path(__file__).resolve().parents[2]
        / "agent_defs/triage_agent/tools/submit_triage.tool.yaml"
    )
    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert doc["input_schema"] == dispositions_input_schema()


def test_no_pending_is_noop(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="已 triaged", body="x", labels=["bug", TRIAGED]))
    out = _triager(tmp_path, tracker, dispositions=[]).triage_once()
    assert out.handled == 0
    assert _triager(tmp_path, tracker, dispositions=[]).seen_pending == []  # 无 needs-triage → 不跑


def test_no_submit_is_noop(tmp_path) -> None:
    """agent 未调 submit_triage（撞 max_iterations 等）→ agent.run 返回非合规 JSON → 本轮 no-op，
    issue 仍留 needs-triage 待下轮重来（最小兜底，不抛错）。"""
    tracker = FakeTracker()
    n = _raw(tracker, "没提交")
    out = _triager(tmp_path, tracker, raw="抱歉我没能完成分诊。").triage_once()
    assert out.handled == 0
    assert NEEDS_TRIAGE in tracker.issue(n)["labels"]  # 仍待分诊


def test_accept_confirms_labels_and_comments_triage_fields(tmp_path) -> None:
    tracker = FakeTracker()
    n = _raw(tracker, "unidecode 超时", kind="bug")
    dispositions = [
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
    ]
    out = _triager(tmp_path, tracker, dispositions=dispositions).triage_once()

    assert out.accepted == [n]
    snap = tracker.issue(n)
    assert TRIAGED in snap["labels"] and "bug" in snap["labels"]
    assert "P1" in snap["labels"]  # triage 打的优先级
    assert NEEDS_TRIAGE not in snap["labels"]  # 去掉待分诊
    assert "round-1" in snap["labels"]  # 轮号保留
    assert snap["state"] == "open"  # 采纳 → 仍 open 待 dev 领
    assert any("根因区域" in c and "entry.py 无预算感知" in c for c in snap["comments"])


def test_accept_feature_uses_feature_triage_fields(tmp_path) -> None:
    """feature 的 TRIAGE 字段是 边界/交付物/验收（非 bug 的根因区域）——填对即采纳。"""
    tracker = FakeTracker()
    n = _raw(tracker, "希望批量导出", kind="feature")
    dispositions = [
        {
            "issue": n,
            "disposition": "accept",
            "kind": "feature",
            "priority": "P2",
            "fields": {"边界": "只加通用能力", "交付物": "导出接口", "验收": "能批量导出"},
        }
    ]
    out = _triager(tmp_path, tracker, dispositions=dispositions).triage_once()
    assert out.accepted == [n]
    snap = tracker.issue(n)
    assert "feature" in snap["labels"] and "P2" in snap["labels"] and TRIAGED in snap["labels"]
    assert any("交付物" in c and "导出接口" in c for c in snap["comments"])


def test_accept_invalid_priority_not_labeled(tmp_path) -> None:
    """priority 非 P0-P3（driver 二次把关）→ 不打优先级标签，但仍采纳（priority 是判断非硬闸）。"""
    tracker = FakeTracker()
    n = _raw(tracker, "超时")
    dispositions = [
        {
            "issue": n,
            "disposition": "accept",
            "kind": "bug",
            "priority": "紧急",  # driver 侧不认（工具层 enum 也会拒；此处测 driver 兜底）
            "fields": {"根因区域": "a", "边界": "b", "验收": "c"},
        }
    ]
    _triager(tmp_path, tracker, dispositions=dispositions).triage_once()
    labels = tracker.issue(n)["labels"]
    assert TRIAGED in labels and not any(p in labels for p in ("P0", "P1", "P2", "P3"))


def test_accept_missing_triage_fields_downgrades_to_needs_info(tmp_path) -> None:
    """采纳但 TRIAGE 字段没填全 → 降级 needs_info（保证采纳的 issue 定位完整）。"""
    tracker = FakeTracker()
    n = _raw(tracker, "坏了")
    dispositions = [
        {
            "issue": n,
            "disposition": "accept",
            "kind": "bug",
            "fields": {"根因区域": "只填了这个"},
        }
    ]
    out = _triager(tmp_path, tracker, dispositions=dispositions).triage_once()
    assert out.needs_info == [n] and out.accepted == []
    snap = tracker.issue(n)
    assert NEEDS_INFO in snap["labels"] and snap["state"] == "closed"


def test_accept_reclassifies_kind(tmp_path) -> None:
    """暂定 bug，triage 改判 feature → 旧 type 被替换。"""
    tracker = FakeTracker()
    n = _raw(tracker, "希望加个功能", kind="bug")
    dispositions = [
        {
            "issue": n,
            "disposition": "accept",
            "kind": "feature",
            "fields": {"边界": "b", "交付物": "d", "验收": "a"},
        }
    ]
    _triager(tmp_path, tracker, dispositions=dispositions).triage_once()
    labels = tracker.issue(n)["labels"]
    assert "feature" in labels and "bug" not in labels  # 改判、旧 type 去掉


def test_accept_invalid_kind_downgrades_to_needs_info(tmp_path) -> None:
    """kind 不在 USER_KINDS（driver 二次把关）→ 降级 needs_info。"""
    tracker = FakeTracker()
    n = _raw(tracker, "怪东西")
    dispositions = [{"issue": n, "disposition": "accept", "kind": "rfc", "fields": {}}]
    out = _triager(tmp_path, tracker, dispositions=dispositions).triage_once()
    assert out.needs_info == [n] and out.accepted == []


def test_duplicate_closes_and_links(tmp_path) -> None:
    tracker = FakeTracker()
    main = tracker.create_issue(IssueDraft(title="主", body="x", labels=["bug", TRIAGED])).number
    dup = _raw(tracker, "重复的")
    dispositions = [{"issue": dup, "disposition": "duplicate", "of": main}]
    out = _triager(tmp_path, tracker, dispositions=dispositions).triage_once()
    assert out.duplicate == [dup]
    snap = tracker.issue(dup)
    assert snap["state"] == "closed"
    assert NEEDS_TRIAGE not in snap["labels"]  # 重复也是已分诊结局，去 needs-triage
    assert any(f"duplicate of #{main}" in c for c in snap["comments"])


def test_reject_and_needs_info_close_with_reason(tmp_path) -> None:
    tracker = FakeTracker()
    rej = _raw(tracker, "要改 launcher")
    ni = _raw(tracker, "就说坏了")
    dispositions = [
        {"issue": rej, "disposition": "reject", "reason": "属传输层，非 harness 本体"},
        {"issue": ni, "disposition": "needs_info", "reason": "无有效复现"},
    ]
    out = _triager(tmp_path, tracker, dispositions=dispositions).triage_once()

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
    dispositions = [
        {"issue": 999, "disposition": "reject", "reason": "幽灵"},
        {"issue": n, "disposition": "reject", "reason": "真的"},
    ]
    out = _triager(tmp_path, tracker, dispositions=dispositions).triage_once()
    assert out.rejected == [n]  # 只处理了真实待分诊那条


def test_unknown_disposition_left_pending(tmp_path) -> None:
    """未知 disposition（不在四值内）→ 忽略，issue 仍 needs-triage 下轮再来。"""
    tracker = FakeTracker()
    n = _raw(tracker, "含糊结论")
    out = _triager(tmp_path, tracker, dispositions=[{"issue": n, "disposition": "maybe"}]).triage_once()
    assert out.handled == 0
    assert NEEDS_TRIAGE in tracker.issue(n)["labels"]


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
