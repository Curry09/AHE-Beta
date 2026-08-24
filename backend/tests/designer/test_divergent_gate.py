# Spec-0029/T5：divergent = discovery 轨生成器单测（stub agent，不跑真 LLM）。
"""验证 divergent：吃会话证据（体感索引）+ 勿重复参照（紧凑索引），产 proposal+from-divergent
（不可领）；每轮硬顶 3 条；字段不全跳过；drift-guard（submit_divergent yaml == rfc_input_schema）。
旧 gate 三路测试已随 gate_once 退役删除——准入裁决测试见 test_owner.py（Spec-0029/T6）。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.designer import issue_schema as sc
from auto_designer.designer.divergent import Divergent, DivergentOutcome
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


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _seed_session(store: SessionStore, *, score: int = 3) -> None:
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=score, reason="timeout then ask status"),
        )
    )


def _pm_artifact() -> dict:
    return {
        "user_goal": "持续掌握长任务进展",
        "observed_behaviors": ["超时后反复追问状态"],
        "experience_tension": "系统在工作但用户无法判断是否仍值得等待",
        "product_opportunity": "提供连续、可理解的进展反馈",
        "desired_outcome": "用户无需用追问恢复确定感",
        "evidence_sessions": ["SESSION_ID"],
        "solution_level": "product_capability",
        "abstraction_rationale": "只描述用户可感知能力与结果",
    }


def _submit(proposals: list) -> str:
    return json.dumps({"proposals": proposals}, ensure_ascii=False)


class _StubDivergent(Divergent):
    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_trend: list = []
        self.seen_reference: list = []

    def _run_agent(self, *, trend: list, reference: list) -> str:
        self.seen_trend = trend
        self.seen_reference = reference
        return self._canned


def _divergent(tmp_path: Path, tracker: FakeTracker, canned: str, **kw) -> _StubDivergent:
    store = SessionStore(tmp_path / "sessions")
    _seed_session(store)
    canned = canned.replace("SESSION_ID", str(store.index()[0]["session_id"]))
    return _StubDivergent(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent"), canned=canned, **kw
    )


def test_submit_divergent_yaml_matches_contract() -> None:
    """drift-guard：submit_divergent.tool.yaml 的 input_schema = rfc_input_schema()（同 RFC shape）。"""
    import yaml

    from auto_designer.designer.agent_contract import pm_input_schema

    p = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "divergent_pm"
        / "tools"
        / "submit_divergent.tool.yaml"
    )
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["input_schema"] == pm_input_schema()


def test_divergent_creates_unclaimable_proposal(tmp_path: Path) -> None:
    tracker = FakeTracker()
    canned = _submit([{"title": "状态交接产品化", **_pm_artifact()}])
    d = _divergent(tmp_path, tracker, canned, round_provider=lambda: 2)
    out = d.propose_once()
    assert isinstance(out, DivergentOutcome) and out.count == 1
    issues = tracker.list_open_issues()
    assert len(issues) == 1
    labels = issues[0].labels
    assert sc.PROPOSAL in labels and sc.FROM_DIVERGENT in labels
    assert "round-2" in labels
    assert sc.plane(labels) == sc.PROPOSAL
    assert not sc.is_ready(labels=labels, state="open")  # 不可领，待 Owner 准入


def test_divergent_inputs_are_session_first(tmp_path: Path) -> None:
    """输入 = 体感索引 + 勿重复参照（open 提案/ready），不吃 triaged backlog/runtime_agg。"""
    tracker = FakeTracker()
    ref1 = tracker.create_issue(
        IssueDraft(title="已有提案", body="x", labels=[sc.PROPOSAL, sc.FROM_TRIAGE])
    ).number
    ref2 = tracker.create_issue(IssueDraft(title="ready 项", body="x", labels=[sc.READY])).number
    tracker.create_issue(IssueDraft(title="raw report", body="x", labels=[sc.REPORT]))  # 不作参照
    d = _divergent(tmp_path, tracker, _submit([]))
    d.propose_once()
    assert len(d.seen_trend) == 1  # 体感索引喂进
    assert {i.number for i in d.seen_reference} == {ref1, ref2}  # 参照只含提案/ready


def test_divergent_dedupe_reference_is_compact() -> None:
    tracker = FakeTracker()
    tracker.create_issue(
        IssueDraft(
            title="精确指令下探索范围失控",
            body="### 根因区域\n\nagents/main.md 未约束精确任务的探索范围",
            labels=[sc.PROPOSAL, sc.FROM_TRIAGE],
        )
    )
    rendered = Divergent._format_issues(tracker.list_open_issues())
    assert "精确指令下探索范围失控" in rendered
    assert "agents/main.md 未约束精确任务的探索范围" not in rendered


def test_divergent_caps_at_three(tmp_path: Path) -> None:
    tracker = FakeTracker()
    many = [{"title": f"候选{i}", **_pm_artifact()} for i in range(5)]
    out = _divergent(tmp_path, tracker, _submit(many)).propose_once()
    assert out.count == 3  # 每轮硬顶


def test_divergent_incomplete_fields_skipped(tmp_path: Path) -> None:
    tracker = FakeTracker()
    out = _divergent(
        tmp_path, tracker, _submit([{"title": "半成品", "user_goal": "只填了这个"}])
    ).propose_once()
    assert out.count == 0
    assert tracker.list_open_issues() == []


def test_divergent_no_submit_is_noop(tmp_path: Path) -> None:
    tracker = FakeTracker()
    out = _divergent(tmp_path, tracker, "散文，没调 submit").propose_once()
    assert out.count == 0
