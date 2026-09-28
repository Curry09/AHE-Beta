"""Delivery Router 单测：无损交接、精确去重、Designer covers 不由 Owner 重复处理、遗漏项 fail-open。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_designer.designer import issue_schema as sc
from auto_designer.designer.owner import AdmitOutcome, Owner
from auto_designer.loop.recovery import (
    RecoveryConflictError,
    RecoveryIdentity,
    RecoveryStore,
    operation_key,
)
from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import bind_usage_context
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
        decision.setdefault("handoff_summary", "交给 OpenAgents 规划")
        decision.setdefault("preserved_capabilities", ["保留原始能力"])
        decision.setdefault("acceptance_groups", ["独立验收原始目标"])
    return json.dumps({"decisions": decisions}, ensure_ascii=False)


def _owner_recovery(
    tmp_path: Path, *, designer_proposals: list[int] | None = None
) -> RecoveryStore:
    store = RecoveryStore.initialize(
        root=tmp_path / "recovery",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )
    store.freeze_round(round_no=1, user_sha="user", plan=[])
    for stage in ("divergent", "designer"):
        key = operation_key(stage, "complete")
        store.begin_unit(
            round_no=1,
            stage=stage,
            key=key,
            input_value={},
            expected_postconditions={"completed": True},
        )
        store.complete_unit(
            round_no=1,
            stage=stage,
            key=key,
            observed_postconditions={
                "completed": True,
                **({"proposal_numbers": designer_proposals} if stage == "designer" else {}),
            },
        )
        store.complete_stage(round_no=1, stage=stage)
    return store


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
    assert [tool["name"] for tool in config["tools"]] == [
        "submit_observation_gap",
        "submit_admission",
    ]
    assert config["stop_tools"] == ["submit_admission"]


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


def test_similar_but_nonidentical_proposals_are_preserved(tmp_path: Path) -> None:
    """相似标题不构成精确重复，错误 merge 会被 driver 恢复为独立 handoff。"""
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
    assert out.admitted == [a, b] and out.merged == []
    assert b in out.invalid
    assert sc.is_ready(labels=tracker.issue(b)["labels"], state="open")


def test_exact_duplicate_can_merge(tmp_path: Path) -> None:
    tracker = FakeTracker()
    a = _triage_proposal(tracker, "完全相同")
    b = _triage_proposal(tracker, "完全相同")
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": a, "decision": "admit"}, {"issue": b, "decision": "merge", "into": a}]),
    )
    out = o.admit_once()
    assert out.admitted == [a] and out.merged == [b]
    assert sc.MERGED in tracker.issue(b)["labels"]


@pytest.mark.parametrize("bad_overlap", [None, "invalid", [999], [True]])
def test_cross_route_overlap_preserves_independent_handoffs(tmp_path, bad_overlap):
    tracker = FakeTracker()
    pm = tracker.create_issue(
        IssueDraft("用户能随时纠偏", "product outcome", [sc.PROPOSAL, sc.FROM_DIVERGENT])
    ).number
    synth = _synth_proposal(tracker, "控制生命周期")
    rows = [
        {
            "issue": pm,
            "decision": "admit",
            "delivery_overlaps": [synth],
            "handoff_summary": "共享控制实现，但 PM 独立验收用户可及时纠偏",
        },
        {"issue": synth, "decision": "admit", "delivery_overlaps": bad_overlap},
    ]
    owner = _owner(tmp_path, tracker, _submit(rows))
    out = owner.admit_once()
    assert set(out.admitted) == {pm, synth}
    assert not out.merged and not out.failed
    assert synth in out.invalid
    assert any(f"交付重叠（关联，不合并）：#{synth}" in c for c in tracker.issue(pm)["comments"])
    assert "product outcome" == tracker.issue(pm)["body"]


def test_overlap_can_reference_ready_but_not_self_or_report(tmp_path):
    tracker = FakeTracker()
    pm = _triage_proposal(tracker, "new")
    ready = tracker.create_issue(IssueDraft("existing", "x", [sc.READY])).number
    report = tracker.create_issue(IssueDraft("raw", "x", [sc.REPORT])).number
    owner = _owner(
        tmp_path,
        tracker,
        _submit(
            [
                {"issue": pm, "decision": "admit", "delivery_overlaps": [pm, ready, report]},
            ]
        ),
    )
    out = owner.admit_once()
    assert out.admitted == [pm] and pm in out.invalid
    comments = tracker.issue(pm)["comments"]
    assert any(f"交付重叠（关联，不合并）：#{ready}" in c for c in comments)
    assert all(f"#{report}" not in c for c in comments)


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


def test_explicit_incomplete_hold_and_unlisted_default_handoff(tmp_path: Path) -> None:
    tracker = FakeTracker()
    bad = _synth_proposal(tracker, "过拟合提案")
    quiet = _synth_proposal(tracker, "没被提到的提案")
    o = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": bad, "decision": "hold", "reason": "缺少可观察验收结果"}]),
    )
    out = o.admit_once()
    assert out.held == [bad] and quiet in out.admitted
    assert sc.PROPOSAL in tracker.issue(bad)["labels"]
    assert sc.is_ready(labels=tracker.issue(quiet)["labels"], state="open")


def test_invalid_explicit_decision_is_held_not_default_admitted(tmp_path: Path) -> None:
    tracker = FakeTracker()
    proposal = _synth_proposal(tracker, "缺少 hold 理由")
    o = _owner(tmp_path, tracker, _submit([{"issue": proposal, "decision": "hold"}]))

    out = o.admit_once()

    assert out.held == [proposal]
    assert proposal in out.invalid
    assert sc.PROPOSAL in tracker.issue(proposal)["labels"]


def test_owner_does_not_process_designer_covers(tmp_path: Path) -> None:
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
    assert set(out.admitted) == {p1, p2, s}
    assert out.merged == []  # Designer 已在创建阶段处理 covers；Owner 不重复处理
    assert all(sc.is_ready(labels=tracker.issue(n)["labels"], state="open") for n in (p1, p2, s))


def test_covers_untouched_when_structural_held(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p1 = _triage_proposal(tracker, "症状甲：交接断裂")
    s = _synth_proposal(tracker, "结构：交接重构", covers=[p1])
    o = _owner(
        tmp_path,
        tracker,
        _submit(
            [
                {"issue": s, "decision": "hold", "reason": "缺少验收接口"},
                {"issue": p1, "decision": "hold", "reason": "缺少复现步骤"},
            ]
        ),
    )
    out = o.admit_once()
    assert s in out.held and p1 in out.held and out.merged == []
    assert sc.PROPOSAL in tracker.issue(p1)["labels"]  # Owner 不消费 covers


def test_invalid_merge_target_is_preserved_as_handoff(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p = _synth_proposal(tracker, "并进不存在的票")
    o = _owner(tmp_path, tracker, _submit([{"issue": p, "decision": "merge", "into": 999}]))
    out = o.admit_once()
    assert p in out.admitted and p in out.invalid and out.merged == []


def test_merge_target_cannot_be_held_proposal(tmp_path: Path) -> None:
    tracker = FakeTracker()
    source = _synth_proposal(tracker, "待合并")
    held = _synth_proposal(tracker, "暂缓目标")
    o = _owner(
        tmp_path,
        tracker,
        _submit(
            [
                {"issue": source, "decision": "merge", "into": held},
                {"issue": held, "decision": "hold", "reason": "缺少验收接口"},
            ]
        ),
    )
    out = o.admit_once()
    assert source in out.admitted and source in out.invalid
    assert held in out.held
    assert sc.is_ready(labels=tracker.issue(source)["labels"], state="open")


def test_owner_core_write_failure_is_reported(tmp_path: Path) -> None:
    class BrokenSetLabelsTracker(FakeTracker):
        def set_labels(self, number: int, labels: list[str]) -> None:
            raise RuntimeError("set labels failed")

    tracker = BrokenSetLabelsTracker()
    p = _synth_proposal(tracker, "交接时写入失败")
    o = _owner(tmp_path, tracker, _submit([]))
    out = o.admit_once()
    assert p in out.failed and p in out.held
    assert sc.PROPOSAL in tracker.issue(p)["labels"]


def test_review_disabled_mechanically_handoffs_every_proposal(tmp_path: Path) -> None:
    """review=False（roster owner=0）：纯机制交接，全部 admit、零 LLM。"""
    tracker = FakeTracker()
    clean = _triage_proposal(tracker, "干净单条案")
    s = _synth_proposal(tracker, "结构提案")
    o = _owner(tmp_path, tracker, _submit([{"issue": s, "decision": "admit"}]), review=False)
    out = o.admit_once()
    assert set(out.admitted) == {clean, s} and out.mechanical == []
    assert out.held == []
    assert o.agent_calls == 0


def test_recovery_owner_only_admits_pm_and_designer_processed_proposals(tmp_path: Path) -> None:
    tracker = FakeTracker()

    def create(title: str, labels: list[str]) -> int:
        return tracker.create_issue(IssueDraft(title=title, body="summary", labels=labels)).number

    pm = create("PM", [sc.PROPOSAL, sc.FROM_DIVERGENT])
    synthesized = create("Designer", [sc.PROPOSAL, sc.FROM_SYNTHESIZE])
    triage = create("retained triage", [sc.PROPOSAL, sc.FROM_TRIAGE, "round-1"])
    gap = create("retained gap", [sc.PROPOSAL, sc.OBSERVATION_GAP])
    merged = create("merged source", [sc.PROPOSAL, sc.FROM_TRIAGE, "round-1"])
    late_gap = create("late gap", [sc.PROPOSAL, sc.OBSERVATION_GAP])
    stray = create("unseen triage", [sc.PROPOSAL, sc.FROM_TRIAGE, "round-1"])
    recovery = RecoveryStore.initialize(
        root=tmp_path / "recovery",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )
    recovery.freeze_round(round_no=1, user_sha="user", plan=[])
    pm_key = operation_key("pm", "output")
    recovery.begin_unit(round_no=1, stage="divergent", key=pm_key, input_value={})
    recovery.complete_unit(
        round_no=1,
        stage="divergent",
        key=pm_key,
        observed_postconditions={"proposal_numbers": [pm]},
    )
    recovery.complete_stage(round_no=1, stage="divergent")
    designer_key = operation_key("designer", "grouping")
    seen = [i.to_dict() for i in tracker.list_open_issues() if i.number in {triage, gap, merged}]
    recovery.begin_unit(
        round_no=1, stage="designer", key=designer_key, input_value={"issues": seen}
    )
    recovery.complete_unit(round_no=1, stage="designer", key=designer_key)
    worker_key = operation_key("designer", "batch")
    recovery.begin_unit(round_no=1, stage="designer", key=worker_key, input_value={})
    recovery.complete_unit(
        round_no=1,
        stage="designer",
        key=worker_key,
        observed_postconditions={"merged_numbers": [merged], "proposal_numbers": [synthesized]},
    )
    recovery.complete_stage(round_no=1, stage="designer")

    owner = _owner(tmp_path, tracker, _submit([]), review=False, recovery=recovery)
    with bind_usage_context(round_no=1, operation="owner-stage"):
        outcome = owner.admit_once()
    assert set(outcome.admitted) == {pm, synthesized, triage, gap}
    assert owner.agent_calls == 0
    for number in (merged, late_gap, stray):
        assert sc.PROPOSAL in tracker.issue(number)["labels"]


def test_review_prompt_is_handoff_only(tmp_path: Path) -> None:
    tracker = FakeTracker()
    p = _triage_proposal(tracker, "某具体任务中的失败")
    o = _owner(tmp_path, tracker, _submit([]))
    issue = tracker.list_open_issues()[0]
    msg = o._review_message(proposals=[issue], ready=[], trend=[])
    assert "Delivery Router" in msg
    assert "无损打包交接" in msg
    assert "不审核上游方案" in msg
    assert "Designer 已在结构提案创建阶段处理 `covers` 来源" in msg
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


def test_no_submit_defaults_to_direct_handoff(tmp_path: Path) -> None:
    tracker = FakeTracker()
    s = _synth_proposal(tracker, "结构提案")
    o = _owner(tmp_path, tracker, "散文没调 submit")
    out = o.admit_once()
    assert s in out.admitted and out.held == []


def test_recovery_replays_owner_decisions_after_partial_admission(tmp_path: Path) -> None:
    class CrashAfterLabelsTracker(FakeTracker):
        crashed = False

        def set_labels(self, number: int, labels: list[str]) -> None:
            super().set_labels(number, labels)
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("injected after admission labels")

    tracker = CrashAfterLabelsTracker()
    proposal = _synth_proposal(tracker, "resume owner")
    owner = _owner(
        tmp_path,
        tracker,
        _submit([{"issue": proposal, "decision": "admit"}]),
        recovery=_owner_recovery(tmp_path, designer_proposals=[proposal]),
    )
    with bind_usage_context(round_no=1, operation="owner-stage"):
        with pytest.raises(RecoveryConflictError, match="remain incomplete"):
            owner.admit_once()
    with bind_usage_context(round_no=1, operation="owner-stage"):
        outcome = owner.admit_once()
    assert outcome.admitted == [proposal]
    assert owner.agent_calls == 1
    assert len(tracker.issue(proposal)["comments"]) == 2
