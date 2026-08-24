# Spec-0029/T4：synthesize 生成器单测（stub nexau agent + FakeTracker + 临时 SessionStore）。
"""验证 designer 驱动器：产出落 proposal 平面 + from-synthesize（不可领、不 supersede 任何票）；
covers 只是建议机器行（过滤到 open report/proposal）；输入 = ready + 待准入提案索引 + 体感 + runtime；
缺字段跳过；未调 submit no-op；drift-guard（submit_rfcs yaml == rfc_input_schema）。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.designer import issue_schema as sc
from auto_designer.designer.designer import (
    Designer,
    DesignOutcome,
    _parse_covers,
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
from auto_designer.user.session_store import SessionStore


class _StubDesigner(Designer):
    """覆盖 _run_agent：不跑真 nexau，回放固定 submit 返回，并记录喂进的信号。"""

    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_ready: list = []
        self.seen_proposals: list = []
        self.seen_trend: list = []
        self.seen_runtime: str = ""

    def _run_agent(self, *, ready: list, proposals: list, trend: list, runtime: str) -> str:
        self.seen_ready = ready
        self.seen_proposals = proposals
        self.seen_trend = trend
        self.seen_runtime = runtime
        return self._canned


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _seed_session(store: SessionStore, *, score: int, reason: str = "r") -> None:
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=score, reason=reason),
        )
    )


def _designer(
    tmp_path: Path,
    tracker: FakeTracker,
    canned: str,
    *,
    round_provider=None,
) -> _StubDesigner:
    # A synthesis fixture needs an actual cross-proposal set.
    if '"proposals": []' not in canned and "散文" not in canned and canned:
        while len([i for i in tracker.list_open_issues() if sc.plane(i.labels) in (sc.PROPOSAL, sc.READY)]) < 2:
            _proposal(tracker, "辅助来源")
    store = SessionStore(tmp_path / "sessions")
    _seed_session(store, score=2, reason="等太久")
    _seed_session(store, score=1, reason="超时两次颗粒无收")
    return _StubDesigner(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "agent_def"),
        canned=canned,
        round_provider=round_provider,
    )


def _synthesis_artifact() -> dict:
    return {
        "source_proposals": [1, 2],
        "relationship": "两个提案是同一体验张力的阶段表现",
        "common_tension": "长任务缺少可预期的反馈边界",
        "structural_direction": "统一进展表达和中间交付机制",
        "expected_leverage": "同时降低等待不确定性与失败返工",
        "solution_level": "structural_mechanism",
        "abstraction_rationale": "只描述跨提案共同机制",
    }


def _submit(proposals: list) -> str:
    return json.dumps({"proposals": proposals}, ensure_ascii=False)


def _rfc_canned(
    covers: object = None, *, title: str = "结构：预算感知", fields: dict | None = None
) -> str:
    item: dict = {"title": title, **(fields if fields is not None else _synthesis_artifact())}
    if covers is not None:
        item["covers"] = covers
    return _submit([item])


def _proposal(tracker: FakeTracker, title: str) -> int:
    return tracker.create_issue(
        IssueDraft(title=title, body="x", labels=["bug", sc.PROPOSAL, sc.FROM_TRIAGE])
    ).number


def test_submit_rfcs_yaml_matches_contract() -> None:
    """drift-guard：submit_rfcs.tool.yaml 的 input_schema 与 rfc_input_schema() 深度相等。"""
    import yaml

    from auto_designer.designer.agent_contract import synthesis_input_schema

    yaml_path = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "designer"
        / "tools"
        / "submit_rfcs.tool.yaml"
    )
    tool_def = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert tool_def["input_schema"] == synthesis_input_schema()


def test_structural_proposal_lands_unclaimable(tmp_path) -> None:
    tracker = FakeTracker()
    _proposal(tracker, "超时1")
    designer = _designer(tmp_path, tracker, _rfc_canned())

    outcome = designer.propose_once()

    assert isinstance(outcome, DesignOutcome) and outcome.count == 1
    rfc = tracker.issue(outcome.proposal_numbers[0])
    assert sc.PROPOSAL in rfc["labels"] and sc.FROM_SYNTHESIZE in rfc["labels"]
    assert sc.plane(rfc["labels"]) == sc.PROPOSAL  # 不可领，待 Owner 准入
    assert not sc.is_ready(labels=rfc["labels"], state="open")
    assert "## 结构关系" in rfc["body"]
    assert "## 结构方向" in rfc["body"]


def test_structural_proposal_carries_live_round_label(tmp_path) -> None:
    tracker = FakeTracker()
    outcome = _designer(tmp_path, tracker, _rfc_canned(), round_provider=lambda: 4).propose_once()

    assert "round-4" in tracker.issue(outcome.proposal_numbers[0])["labels"]


def test_structural_proposal_does_not_guess_invalid_round(tmp_path) -> None:
    for value in (None, 0, -1, True):
        tracker = FakeTracker()
        outcome = _designer(
            tmp_path, tracker, _rfc_canned(), round_provider=lambda value=value: value
        ).propose_once()
        labels = tracker.issue(outcome.proposal_numbers[0])["labels"]
        assert not any(label.startswith("round-") for label in labels)


def test_inputs_are_ready_plus_proposal_index(tmp_path) -> None:
    """输入 = ready 工作队列 + 待准入提案索引（report/终态不喂）。"""
    tracker = FakeTracker()
    p = _proposal(tracker, "本轮新升提案")
    r = tracker.create_issue(
        IssueDraft(title="ready 项", body="x", labels=["bug", sc.READY])
    ).number
    tracker.create_issue(IssueDraft(title="raw report", body="x", labels=[sc.REPORT]))
    designer = _designer(tmp_path, tracker, _submit([]))
    designer.propose_once()
    assert [i.number for i in designer.seen_ready] == [r]
    assert [i.number for i in designer.seen_proposals] == [p]
    assert designer.seen_trend and designer.seen_runtime  # 体感+runtime 都喂（delivery 轨）


def test_covers_line_written_but_nothing_superseded(tmp_path) -> None:
    """covers 只是建议机器行：落在 body，**不**打 superseded、不动被覆盖票。"""
    tracker = FakeTracker()
    t1 = _proposal(tracker, "症状1")
    t2 = _proposal(tracker, "症状2")
    outcome = _designer(tmp_path, tracker, _rfc_canned([t1, t2])).propose_once()

    body = tracker.issue(outcome.proposal_numbers[0])["body"]
    assert f"covers: #{t1} #{t2}" in body  # 机器可读行
    for n in (t1, t2):
        snap = tracker.issue(n)
        assert sc.SUPERSEDED not in snap["labels"]  # 不再单方面 supersede
        assert snap["state"] == "open" and sc.plane(snap["labels"]) == sc.PROPOSAL  # 原样


def test_covers_filtered_to_open_report_or_proposal(tmp_path) -> None:
    """covers 指向 ready 项 / 不存在的号 → 静默剔除（合并只对 report/proposal 有意义）。"""
    tracker = FakeTracker()
    ok = _proposal(tracker, "可覆盖提案")
    ready_n = tracker.create_issue(IssueDraft(title="ready", body="x", labels=[sc.READY])).number
    outcome = _designer(tmp_path, tracker, _rfc_canned([ok, ready_n, 999])).propose_once()
    body = tracker.issue(outcome.proposal_numbers[0])["body"]
    assert f"covers: #{ok}" in body
    assert f"#{ready_n}" not in body.split("covers:")[1]


def test_covers_absent_no_line(tmp_path) -> None:
    tracker = FakeTracker()
    _proposal(tracker, "t")
    outcome = _designer(tmp_path, tracker, _rfc_canned(None)).propose_once()
    assert "covers:" not in tracker.issue(outcome.proposal_numbers[0])["body"]


def test_synthesis_renders_explicit_sources(tmp_path) -> None:
    tracker = FakeTracker()
    fields = _synthesis_artifact()
    outcome = _designer(tmp_path, tracker, _rfc_canned(fields=fields)).propose_once()
    assert outcome.count == 1
    assert "## 来源提案" in tracker.issue(outcome.proposal_numbers[0])["body"]


def test_incomplete_fields_skipped(tmp_path) -> None:
    tracker = FakeTracker()
    canned = _submit([{"title": "半成品", "source_proposals": [1]}])
    outcome = _designer(tmp_path, tracker, canned).propose_once()
    assert outcome.count == 0


def test_empty_or_no_submit_yields_no_proposal(tmp_path) -> None:
    tracker = FakeTracker()
    for canned in (_submit([]), "散文没调 submit", ""):
        outcome = _designer(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 0


def test_synthesis_requires_cross_proposal_sources(tmp_path) -> None:
    tracker = FakeTracker()
    outcome = _designer(tmp_path, tracker, _submit([{"title": "单源", **{**_synthesis_artifact(), "source_proposals": [1]}}])).propose_once()
    assert outcome.count == 0


def test_parse_covers_field_shapes() -> None:
    """covers 宽进严出：去重、剔 bool/负数/字符串。"""
    assert _parse_covers([5, 5, 6, True, -1, 0, "8"]) == (5, 6)
    assert _parse_covers("nope") == ()
