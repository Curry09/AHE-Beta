# Spec-0029/T6：Owner 准入单测——全量模型评审、四路裁决、covers 默认级联（stub agent）。
"""FakeTracker + 临时 SessionStore：验证唯一准入口的裁决落库——所有来源统一评审、
admit/merge/decline/hold、显式决策 > covers 默认 merge > 默认 hold、review=False 全 hold。"""

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
    for decision in decisions:
        decision.setdefault("value_assessment", "价值明确")
        decision.setdefault("evidence_assessment", "证据充分")
        decision.setdefault("scope_assessment", "范围内聚")
        decision.setdefault("overlap_assessment", "已检查重叠")
        decision.setdefault("delivery_risk", "风险可控")
        decision.setdefault("product_boundary", "in_scope")
        decision.setdefault("abstraction_quality", "appropriate")
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


def test_owner_agent_exposes_only_admission_tool() -> None:
    """Owner evaluates supplied artifacts and cannot reopen source/session investigation."""
    import yaml

    path = Path(__file__).resolve().parents[2] / "agent_defs" / "owner" / "agent.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [tool["name"] for tool in config["tools"]] == ["submit_admission"]


def test_no_proposals_is_noop(tmp_path: Path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="ready 项", body="x", labels=[sc.READY]))
    o = _owner(tmp_path, tracker, _submit([]))
    out = o.admit_once()
    assert isinstance(out, AdmitOutcome) and out.admitted == []
    assert o.agent_calls == 0


def test_clean_triage_singleton_requires_explicit_model_admission(tmp_path: Path) -> None:
    tracker = FakeTracker()
    n = _triage_proposal(tracker, "unidecode 安装超时")
    o = _owner(tmp_path, tracker, _submit([{"issue": n, "decision": "admit"}]))
    out = o.admit_once()
    assert out.admitted == [n] and out.mechanical == []
    assert o.agent_calls == 1
    assert [i.number for i in o.seen_review] == [n]
    snap = tracker.issue(n)
    assert sc.is_ready(labels=snap["labels"], state=snap["state"])
    assert sc.OPENAGENTS in snap["labels"] and sc.PROPOSAL not in snap["labels"]  # 交接令牌落库
    assert "P2" in snap["labels"]  # 建议优先级沿用为终值
    assert snap["comments"]
    assert all("<!-- openagents:agent=auto-designer -->" in body for body in snap["comments"])


def test_all_triage_proposals_go_to_one_batch_review(tmp_path: Path) -> None:
    """无论标题是否近似，from-triage 都必须进入同一次全局评审。"""
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


def test_merge_target_cannot_be_held_or_declined_proposal(tmp_path: Path) -> None:
    tracker = FakeTracker()
    source = _synth_proposal(tracker, "待合并")
    held = _synth_proposal(tracker, "暂缓目标")
    declined = _synth_proposal(tracker, "拒绝目标")
    o = _owner(
        tmp_path,
        tracker,
        _submit(
            [
                {"issue": source, "decision": "merge", "into": held},
                {"issue": held, "decision": "hold"},
                {"issue": declined, "decision": "decline", "reason": "无价值"},
            ]
        ),
    )
    out = o.admit_once()
    assert source in out.held and source in out.invalid
    assert sc.PROPOSAL in tracker.issue(source)["labels"]


def test_owner_core_write_failure_is_reported(tmp_path: Path) -> None:
    class BrokenTransitionTracker(FakeTracker):
        def transition_issue(self, number: int, *, state: str, labels: list[str]) -> None:
            raise RuntimeError("transition failed")

    tracker = BrokenTransitionTracker()
    p = _synth_proposal(tracker, "拒绝时写入失败")
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": p, "decision": "decline", "reason": "无价值"}]),
    )
    out = o.admit_once()
    assert p in out.failed and p in out.held
    assert sc.PROPOSAL in tracker.issue(p)["labels"]


def test_review_disabled_holds_every_proposal(tmp_path: Path) -> None:
    """review=False（roster owner=0）：不存在机械旁路，全部 hold、零 LLM。"""
    tracker = FakeTracker()
    clean = _triage_proposal(tracker, "干净单条案")
    s = _synth_proposal(tracker, "结构提案")
    o = _owner(tmp_path, tracker, _submit([{"issue": s, "decision": "admit"}]), review=False)
    out = o.admit_once()
    assert out.admitted == [] and out.mechanical == []
    assert set(out.held) == {clean, s}
    assert o.agent_calls == 0


def test_review_prompt_keeps_owner_lightweight(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p = _triage_proposal(tracker, "某具体任务中的失败")
    o = _owner(tmp_path, tracker, _submit([]))
    issue = tracker.list_open_issues()[0]
    msg = o._review_message(proposals=[issue], ready=[], trend=[])
    assert "投资与组合治理" in msg
    assert "重叠" in msg
    assert "不重新执行 Triage" in msg
    assert "必须使用仓库工具核验" not in msg
    assert f"#{p}" in msg


def test_owner_receives_normalized_body_for_every_proposal_source(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p = tracker.create_issue(
        IssueDraft(
            title="精确指令下探索范围失控",
            body=(
                "## Triage 规范化提案（实施对象：harness）\n\n"
                "### 根因区域\n\nagents/main.md 在精确指令下仍无界探索\n\n"
                "### 边界\n\n只改通用 harness 行为"
            ),
            labels=["bug", sc.PROPOSAL, sc.FROM_TRIAGE, "P2"],
        )
    ).number
    issue = tracker.list_open_issues()[0]
    rendered = Owner._format_index([issue])
    assert "agents/main.md 在精确指令下仍无界探索" in rendered
    assert "只改通用 harness 行为" in rendered
    assert f"#{p}" in rendered


def test_no_submit_holds_review_set(tmp_path: Path) -> None:
    tracker = FakeTracker()
    s = _synth_proposal(tracker, "结构提案")
    o = _owner(tmp_path, tracker, "散文没调 submit")
    out = o.admit_once()
    assert s in out.held and out.admitted == []
