# Spec-0029/T6：Owner 准入单测——机械/评审双模式、四路裁决、covers 默认级联（stub agent）。
"""FakeTracker + 临时 SessionStore：验证唯一准入口的裁决落库——机械段零 LLM 放行、评审段
admit/merge/decline/hold、显式决策 > covers 默认 merge > 默认 hold、review=False 降级。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.designer import issue_schema as sc
from auto_designer.designer.owner import AdmitOutcome, Owner
from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


class _StubOwner(Owner):
    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.agent_calls = 0
        self.seen_review: list = []

    def _run_agent(self, *, proposals: list, ready: list, trend: list) -> str:
        self.agent_calls += 1
        self.seen_review = proposals
        return self._canned


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _owner(tmp_path: Path, tracker: FakeTracker, canned: str, **kw) -> _StubOwner:
    store = SessionStore(tmp_path / "sessions")
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=2, reason="慢"),
        )
    )
    return _StubOwner(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent"), canned=canned, **kw
    )


def _triage_proposal(tracker: FakeTracker, title: str, *, prio: str = "P2") -> int:
    return tracker.create_issue(
        IssueDraft(
            title=title, body="用户报告原文", labels=["bug", sc.PROPOSAL, sc.FROM_TRIAGE, prio]
        )
    ).number


def _synth_proposal(tracker: FakeTracker, title: str, covers: list[int] | None = None) -> int:
    body = "### 问题\n\nx"
    line = sc.format_covers_line(covers or [])
    if line:
        body = f"{body}\n\n{line}"
    return tracker.create_issue(
        IssueDraft(title=title, body=body, labels=[sc.PROPOSAL, sc.FROM_SYNTHESIZE])
    ).number


def _submit(decisions: list) -> str:
    return json.dumps({"decisions": decisions}, ensure_ascii=False)


def test_submit_admission_yaml_matches_contract() -> None:
    """drift-guard：submit_admission.tool.yaml 的 input_schema 与 admission_input_schema() 深度相等。"""
    import yaml

    from auto_designer.designer.agent_contract import admission_input_schema

    p = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "owner"
        / "tools"
        / "submit_admission.tool.yaml"
    )
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["input_schema"] == admission_input_schema()


def test_no_proposals_is_noop(tmp_path: Path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="ready 项", body="x", labels=[sc.READY]))
    o = _owner(tmp_path, tracker, _submit([]))
    out = o.admit_once()
    assert isinstance(out, AdmitOutcome) and out.admitted == []
    assert o.agent_calls == 0


def test_mechanical_admits_clean_triage_singleton_without_llm(tmp_path: Path) -> None:
    tracker = FakeTracker()
    n = _triage_proposal(tracker, "unidecode 安装超时")
    o = _owner(tmp_path, tracker, _submit([]))
    out = o.admit_once()
    assert out.admitted == [n] and out.mechanical == [n]
    assert o.agent_calls == 0  # 全机械 → 零 LLM
    snap = tracker.issue(n)
    assert sc.is_ready(labels=snap["labels"], state=snap["state"])
    assert sc.OPENAGENTS in snap["labels"] and sc.PROPOSAL not in snap["labels"]  # 交接令牌落库
    assert "P2" in snap["labels"]  # 建议优先级沿用为终值


def test_mechanical_conflict_goes_to_review(tmp_path: Path) -> None:
    """标题近似的两条 from-triage 提案 → 冲突嫌疑，进评审段（宁审勿误放）。"""
    tracker = FakeTracker()
    a = _triage_proposal(tracker, "导出按钮点了没反应")
    b = _triage_proposal(tracker, "导出按钮点了没有反应")
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": a, "decision": "admit"}, {"issue": b, "decision": "merge", "into": a}]),
    )
    out = o.admit_once()
    assert o.agent_calls == 1
    assert {i.number for i in o.seen_review} == {a, b}
    assert out.admitted == [a] and out.merged == [b]
    merged = tracker.issue(b)
    assert sc.MERGED in merged["labels"] and merged["state"] == "closed"
    assert any(sc.parse_merged_into(c) == a for c in merged["comments"])  # 反向边


def test_review_admit_with_priority_override(tmp_path: Path) -> None:
    tracker = FakeTracker()
    s = _synth_proposal(tracker, "结构：预算感知")
    o = _owner(tmp_path, tracker, _submit([{"issue": s, "decision": "admit", "priority": "P0"}]))
    out = o.admit_once()
    assert out.admitted == [s]
    labels = tracker.issue(s)["labels"]
    # Spec-0032/T3：admit 打的是交付面交接令牌 openagents（vigil 发现后自己盖 ready），非直接 ready。
    assert sc.OPENAGENTS in labels and sc.READY not in labels and "P0" in labels
    assert sc.plane(labels) == sc.READY  # 读侧仍在 READY 平面（funnel/背压/前端口径不变）


def test_review_decline_and_unlisted_hold(tmp_path: Path) -> None:
    tracker = FakeTracker()
    bad = _synth_proposal(tracker, "过拟合提案")
    quiet = _synth_proposal(tracker, "没被提到的提案")
    o = _owner(
        tmp_path, tracker, _submit([{"issue": bad, "decision": "decline", "reason": "无证据"}])
    )
    out = o.admit_once()
    assert out.declined == [bad] and quiet in out.held
    dead = tracker.issue(bad)
    assert sc.DECLINED in dead["labels"] and dead["state"] == "closed"
    assert sc.PROPOSAL in tracker.issue(quiet)["labels"]  # hold 原样留下轮


def test_covers_default_merge_with_explicit_keep(tmp_path: Path) -> None:
    """裁决优先级：显式决策 > covers 默认 merge。S covers [p1,p2]；p2 显式 admit（急修保留）
    → p1 默认并入 S、p2 独立进 ready。"""
    tracker = FakeTracker()
    p1 = _triage_proposal(tracker, "症状甲：状态丢失")
    p2 = _triage_proposal(tracker, "急修乙：崩溃闪退", prio="P0")
    s = _synth_proposal(tracker, "结构：状态契约重构", covers=[p1, p2])
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": s, "decision": "admit"}, {"issue": p2, "decision": "admit"}]),
    )
    out = o.admit_once()
    assert set(out.admitted) == {s, p2}
    assert out.merged == [p1]  # 默认级联并入 S
    m = tracker.issue(p1)
    assert sc.MERGED in m["labels"] and m["state"] == "closed"
    assert any(sc.parse_merged_into(c) == s for c in m["comments"])
    assert sc.is_ready(labels=tracker.issue(p2)["labels"], state="open")  # 显式保留


def test_covers_untouched_when_structural_held(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p1 = _triage_proposal(tracker, "症状甲：交接断裂")
    s = _synth_proposal(tracker, "结构：交接重构", covers=[p1])
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": s, "decision": "hold"}, {"issue": p1, "decision": "hold"}]),
    )
    out = o.admit_once()
    assert s in out.held and p1 in out.held and out.merged == []
    assert sc.PROPOSAL in tracker.issue(p1)["labels"]  # covers 未触发级联


def test_invalid_merge_target_holds(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p = _synth_proposal(tracker, "并进不存在的票")
    o = _owner(tmp_path, tracker, _submit([{"issue": p, "decision": "merge", "into": 999}]))
    out = o.admit_once()
    assert p in out.held and out.merged == []


def test_review_disabled_mechanical_still_works(tmp_path: Path) -> None:
    """review=False（roster owner=0 降级）：机械段照常放行，评审集合全 hold、零 LLM。"""
    tracker = FakeTracker()
    clean = _triage_proposal(tracker, "干净单条案")
    s = _synth_proposal(tracker, "结构提案")
    o = _owner(tmp_path, tracker, _submit([{"issue": s, "decision": "admit"}]), review=False)
    out = o.admit_once()
    assert out.admitted == [clean] and out.mechanical == [clean]
    assert s in out.held
    assert o.agent_calls == 0


def test_no_submit_holds_review_set(tmp_path: Path) -> None:
    tracker = FakeTracker()
    s = _synth_proposal(tracker, "结构提案")
    o = _owner(tmp_path, tracker, "散文没调 submit")
    out = o.admit_once()
    assert s in out.held and out.admitted == []
