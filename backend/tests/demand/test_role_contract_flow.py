"""Spec-0042: cross-role contract checks for the active demand-side flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ahe_beta.demand import issue_schema as sc
from ahe_beta.demand.architect import Architect
from ahe_beta.demand.divergent import Divergent
from ahe_beta.demand.owner import Owner
from ahe_beta.demand.proposal_view import format_proposal_list
from ahe_beta.demand.role_contract import (
    validate_owner,
    validate_pm,
    validate_synthesis,
    validate_triage,
)
from ahe_beta.demand.triage import Triager
from ahe_beta.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.user.session_store import SessionStore


class _Triage(Triager):
    def __init__(self, *args, result: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._result = result

    def _run_agent(self, *, pending: list) -> str:
        return self._result


class _Owner(Owner):
    def __init__(self, *args, result: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._result = result
        self.review_context = ""

    def _run_agent(self, *, proposals: list, ready: list, trend: list) -> str:
        self.review_context = self._review_message(proposals=proposals, ready=ready, trend=trend)
        return self._result


class _Divergent(Divergent):
    def __init__(self, *args, result: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._result = result
        self.reference_numbers: list[int] = []

    def _run_agent(self, *, trend: list, reference: list) -> str:
        self.reference_numbers = [issue.number for issue in reference]
        return self._result


class _Architect(Architect):
    def __init__(self, *args, result: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._result = result
        self.proposal_numbers: list[int] = []

    def _run_agent(self, *, ready: list, proposals: list, trend: list, runtime: str) -> str:
        self.proposal_numbers = [issue.number for issue in proposals]
        return self._result


def _rfc_fields(*, direction: str) -> dict[str, str]:
    return {
        "问题": "跨场景能力边界不稳定",
        "根因": "运行时约束缺少统一表达",
        "涉及 issue": "规范化提案集合",
        "方向": direction,
        "验收": "相同约束在不同场景保持一致",
    }


def _seed_session(store: SessionStore) -> str:
    store.save(
        Session(
            persona=Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s"),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=2, reason="等待中缺少确定感"),
        )
    )
    return str(store.index()[0]["session_id"])


def _owner_decision(issue: int, decision: str) -> dict:
    row = {
        "issue": issue,
        "decision": decision,
        "handoff_summary": "交接原始目标",
        "preserved_capabilities": ["原始能力"],
        "acceptance_groups": ["独立验收"],
    }
    if decision == "hold":
        row["reason"] = "缺少可观察验收接口"
    return row


def test_role_contract_violations_are_structural_not_vocabulary_based() -> None:
    assert validate_triage({"issue": 8}, report_number=7)[0].code == "foreign-source"
    assert (
        validate_pm(
            {"evidence_sessions": [], "solution_level": "product_capability"}, known_sessions={"s1"}
        )[0].code
        == "missing-evidence"
    )
    assert (
        validate_synthesis(
            {"source_proposals": [1], "solution_level": "structural_mechanism"},
            visible_proposals={1, 2},
        )[0].code
        == "not-cross-proposal"
    )
    assert validate_owner({"issue": 9}, review_batch={1, 2})[0].code == "decision-out-of-batch"
    # No prose keyword or workflow-term blacklist: valid source binding is sufficient here.
    assert (
        validate_pm(
            {
                "evidence_sessions": ["s1"],
                "product_opportunity": "任意措辞",
                "solution_level": "product_capability",
            },
            known_sessions={"s1"},
        )
        == []
    )
    assert (
        validate_triage(
            {
                "issue": 1,
                "disposition": "accept",
                "artifact": {"implementation_target": "outside_harness"},
            },
            report_number=1,
        )[0].code
        == "out-of-product-scope"
    )
    assert (
        validate_owner({"issue": 1, "decision": "hold"}, review_batch={1})[0].code
        == "missing-hold-gap"
    )


def test_report_is_normalized_once_and_raw_case_stays_out_of_downstream_context(
    tmp_path: Path,
) -> None:
    tracker = FakeTracker()
    raw_title = "RAW_CASE_TITLE_SENTINEL"
    raw_body = "RAW_CASE_BODY_SENTINEL"
    number = tracker.create_issue(
        IssueDraft(title=raw_title, body=raw_body, labels=["bug", sc.REPORT])
    ).number
    store = SessionStore(tmp_path / "sessions")
    triage_result = json.dumps(
        {
            "dispositions": [
                {
                    "issue": number,
                    "disposition": "accept",
                    "kind": "bug",
                    "priority": "P1",
                    "proposal_title": "执行约束未被稳定传递到验证阶段",
                    "fields": {
                        "根因区域": "执行与验证之间的约束传递",
                        "边界": "仅调整跨任务成立的 harness 行为",
                        "验收": "约束在执行和验证输出中保持一致",
                    },
                    "artifact": {
                        "reported_problem": "执行约束丢失",
                        "user_impact": "结果不稳定",
                        "scope_boundary": "harness 跨阶段行为",
                        "evidence": ["report"],
                        "uncertainties": [],
                        "implementation_target": "harness",
                    },
                }
            ]
        },
        ensure_ascii=False,
    )
    triager = _Triage(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "triage-agent"),
        result=triage_result,
    )

    outcome = triager.triage_once()
    assert outcome.accepted == [number]
    issue = tracker.list_open_issues()[0]
    downstream = format_proposal_list([issue])
    assert raw_title not in downstream
    assert raw_body not in downstream
    assert "执行约束未被稳定传递到验证阶段" in downstream
    assert any(raw_title in comment for comment in tracker.issue(number)["comments"])

    owner = _Owner(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "owner-agent"),
        result=json.dumps({"decisions": [{**_owner_decision(number, "admit"), "priority": "P1"}]}),
    )
    admitted = owner.admit_once()
    assert admitted.admitted == [number]
    assert raw_title not in owner.review_context
    assert raw_body not in owner.review_context
    admitted_issue = tracker.issue(number)
    assert sc.is_ready(labels=admitted_issue["labels"], state=admitted_issue["state"])


def test_exact_proposal_set_flows_through_divergent_architect_and_owner(
    tmp_path: Path,
) -> None:
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    session_id = _seed_session(store)
    report = tracker.create_issue(
        IssueDraft(title="RAW_TITLE_SENTINEL", body="RAW_BODY_SENTINEL", labels=[sc.REPORT])
    ).number
    triager = _Triage(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "triage"),
        result=json.dumps(
            {
                "dispositions": [
                    {
                        "issue": report,
                        "disposition": "accept",
                        "kind": "bug",
                        "priority": "P1",
                        "proposal_title": "执行约束缺少统一传递边界",
                        "fields": {
                            "根因区域": "执行约束传递",
                            "边界": "跨任务运行时行为",
                            "验收": "约束在阶段之间保持一致",
                        },
                        "artifact": {
                            "reported_problem": "约束传递失败",
                            "user_impact": "交付不稳定",
                            "scope_boundary": "harness 行为",
                            "evidence": ["report"],
                            "uncertainties": [],
                            "implementation_target": "harness",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    assert triager.triage_once().accepted == [report]

    divergent = _Divergent(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "divergent"),
        result=json.dumps(
            {
                "proposals": [
                    {
                        "title": "约束反馈能力",
                        "user_goal": "掌握任务进展",
                        "observed_behaviors": ["等待后追问"],
                        "experience_tension": "进展不可见",
                        "product_opportunity": "连续反馈",
                        "desired_outcome": "无需追问",
                        "evidence_sessions": [session_id],
                        "related_proposals": [report],
                        "solution_level": "product_capability",
                        "abstraction_rationale": "用户能力层",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    divergent_number = divergent.propose_once().proposal_numbers[0]
    assert divergent.reference_numbers == [report]

    second_report = tracker.create_issue(
        IssueDraft(
            title="验证阶段再次丢失约束",
            body="session_id: " + session_id,
            labels=[sc.PROPOSAL, sc.FROM_TRIAGE],
        )
    ).number
    expected_for_architect = {report, second_report}
    architect = _Architect(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "architect"),
        result=json.dumps(
            {
                "proposals": [
                    {
                        "title": "统一约束生命周期",
                        "source_proposals": sorted(expected_for_architect),
                        "relationship": "互补",
                        "common_tension": "反馈边界不一致",
                        "structural_direction": "统一约束表达与反馈边界",
                        "expected_leverage": "覆盖多个体验问题",
                        "solution_level": "structural_mechanism",
                        "abstraction_rationale": "跨提案机制层",
                        "covers": sorted({*expected_for_architect, divergent_number}),
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    synthesis_outcome = architect.propose_once()
    architect_number = synthesis_outcome.proposal_numbers[0]
    assert set(architect.proposal_numbers) == expected_for_architect
    assert synthesis_outcome.merged_numbers == sorted({report, second_report})
    assert all(tracker.issue(number)["state"] == "closed" for number in (report, second_report))
    assert tracker.issue(divergent_number)["state"] == "open"
    assert sc.PROPOSAL in tracker.issue(divergent_number)["labels"]
    assert sc.parse_covers_line(tracker.issue(architect_number)["body"]) == [report, second_report]

    # PM independent route survives even an explicit Architect attempt to cover it.
    expected_for_owner = {architect_number, divergent_number}
    owner = _Owner(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "owner"),
        result=json.dumps(
            {
                "decisions": [
                    _owner_decision(number, "hold") for number in sorted(expected_for_owner)
                ]
            }
        ),
    )
    outcome = owner.admit_once()
    assert set(outcome.held) == expected_for_owner
    assert set(owner.review_context.split())  # context was actually assembled
    assert "RAW_TITLE_SENTINEL" not in owner.review_context
    assert "RAW_BODY_SENTINEL" not in owner.review_context


@pytest.mark.parametrize(
    "labels", [[sc.FROM_DIVERGENT], [sc.DIVERGENT], [sc.FROM_DIVERGENT, sc.FROM_TRIAGE]]
)
def test_pm_is_not_visible_and_cannot_be_cited(tmp_path, labels):
    tracker = FakeTracker()
    a = tracker.create_issue(IssueDraft("delivery", "fact", [sc.PROPOSAL, sc.FROM_TRIAGE])).number
    b = tracker.create_issue(IssueDraft("product", "user outcome", [sc.PROPOSAL, *labels])).number
    artifact = {
        "title": "should not rewrite PM",
        "source_proposals": [a, b],
        "relationship": "related",
        "common_tension": "waiting",
        "structural_direction": "shared mechanism",
        "expected_leverage": "control",
        "solution_level": "structural_mechanism",
        "abstraction_rationale": "shared",
        "covers": [a, b],
    }
    architect = _Architect(
        tracker,
        SessionStore(tmp_path / "sessions"),
        str(tmp_path),
        str(tmp_path),
        result=json.dumps({"proposals": [artifact]}),
    )
    outcome = architect.propose_once()
    assert outcome.proposal_numbers == outcome.merged_numbers == []
    assert architect.proposal_numbers == [a]
    assert outcome.rejected_proposals[0]["reasons"] == ["foreign-source"]
    assert {i.number for i in tracker.list_open_issues()} == {a, b}


@pytest.mark.parametrize("labels", [[sc.FROM_DIVERGENT], [sc.DIVERGENT]])
def test_pm_only_synthesis_is_rejected_but_owner_receives_products(tmp_path, labels):
    tracker = FakeTracker()
    nums = [
        tracker.create_issue(IssueDraft(title, "outcome", [sc.PROPOSAL, *labels])).number
        for title in ("control", "visibility")
    ]
    artifact = {
        "title": "unnecessary architecture",
        "source_proposals": nums,
        "relationship": "related",
        "common_tension": "waiting",
        "structural_direction": "stages",
        "expected_leverage": "control",
        "solution_level": "structural_mechanism",
        "abstraction_rationale": "shared",
        "covers": nums,
    }
    store = SessionStore(tmp_path / "sessions")
    out = _Architect(
        tracker, store, str(tmp_path), str(tmp_path), result=json.dumps({"proposals": [artifact]})
    ).propose_once()
    assert not out.proposal_numbers and out.rejected_proposals
    admitted = Owner(tracker, store, str(tmp_path), str(tmp_path), review=False).admit_once()
    assert set(admitted.admitted) == set(nums)
