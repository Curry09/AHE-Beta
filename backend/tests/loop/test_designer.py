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


def _designer(tmp_path: Path, tracker: FakeTracker, canned: str) -> _StubDesigner:
    store = SessionStore(tmp_path / "sessions")
    _seed_session(store, score=2, reason="等太久")
    _seed_session(store, score=1, reason="超时两次颗粒无收")
    return _StubDesigner(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "agent_def"),
        canned=canned,
    )


def _rfc_fields() -> dict:
    return {
        "问题": "大任务撞预算",
        "根因": "无增量交付",
        "涉及 issue": "#多条",
        "方向": "加预算感知",
        "验收": "预算内给交付",
    }


def _submit(proposals: list) -> str:
    return json.dumps({"proposals": proposals}, ensure_ascii=False)


def _rfc_canned(
    covers: object = None, *, title: str = "结构：预算感知", fields: dict | None = None
) -> str:
    item: dict = {"title": title, "fields": fields if fields is not None else _rfc_fields()}
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

    from auto_designer.designer.agent_contract import rfc_input_schema

    yaml_path = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "designer"
        / "tools"
        / "submit_rfcs.tool.yaml"
    )
    tool_def = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert tool_def["input_schema"] == rfc_input_schema()


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
    assert "### 问题\n\n大任务撞预算" in rfc["body"]  # 按 RFC schema 渲染
    assert "### 方向\n\n加预算感知" in rfc["body"]


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


def test_rfc_fields_label_whitespace_tolerant(tmp_path) -> None:
    """LLM 用无空格「涉及issue」填字段——归一后应映射到 related，不被静默丢弃。"""
    tracker = FakeTracker()
    fields = {
        "问题": "多轮等待拖沓",
        "根因": "单 agent 长循环",
        "涉及issue": "session=x",  # 无空格
        "方向": "更早交回中间成果",
        "验收": "等待中能看到进展",
    }
    outcome = _designer(tmp_path, tracker, _rfc_canned(fields=fields)).propose_once()
    assert outcome.count == 1
    assert "### 涉及 issue" in tracker.issue(outcome.proposal_numbers[0])["body"]


def test_incomplete_fields_skipped(tmp_path) -> None:
    tracker = FakeTracker()
    canned = _submit([{"title": "半成品", "fields": {"问题": "只填了这个"}}])
    outcome = _designer(tmp_path, tracker, canned).propose_once()
    assert outcome.count == 0


def test_empty_or_no_submit_yields_no_proposal(tmp_path) -> None:
    tracker = FakeTracker()
    for canned in (_submit([]), "散文没调 submit", ""):
        outcome = _designer(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 0


def test_pm_proposal_without_covers(tmp_path) -> None:
    """0 条既有票时也能凭体感+runtime 产结构提案（covers 空）。"""
    tracker = FakeTracker()
    outcome = _designer(tmp_path, tracker, _rfc_canned()).propose_once()
    assert outcome.count == 1


def test_parse_covers_field_shapes() -> None:
    """covers 宽进严出：去重、剔 bool/负数/字符串。"""
    assert _parse_covers([5, 5, 6, True, -1, 0, "8"]) == (5, 6)
    assert _parse_covers("nope") == ()
