# 创新者侧：Designer 综合全局产结构性提案单测（stub nexau agent + FakeTracker + 临时 SessionStore）。
"""验证 designer 驱动器（Spec-0027/T3：submit-tool 原生结构化路径）：

- agent 经 submit_rfcs 吐 `{"proposals":[...]}`，driver json.loads 取用、落成带 `RFC` 标签的 open issue；
- RFC 按 issue_schema 渲染；缺字段被跳过；空/未调 submit 退化为「本轮无提案」不抛错；
- covers → 被综合的 triaged issue 打 superseded + 挂链；covers 宽进严出；
- backlog（只喂 triaged）+ 体感曲线确实喂进了 agent；
- submit_rfcs.tool.yaml 的 input_schema 与 agent_contract.rfc_input_schema() 同源（drift-guard）。
"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.designer.designer import (
    Designer,
    DesignOutcome,
    _parse_covers,
)
from auto_designer.designer.issue_schema import RFC_LABEL, TRIAGED
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
    """覆盖 _run_agent：不跑真 nexau，回放一段固定的 submit 返回，并记录喂进的信号。

    submit_rfcs 是 stop tool，其 binding 返回 `json.dumps({"proposals":[...]})` 成为 agent.run 的返回；
    故 stub 的 canned 即这串 JSON（与真实路径同形），driver 对其 _proposals_from_submit。
    """

    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_triaged: list = []
        self.seen_trend: list = []
        self.seen_runtime: str = ""

    def _run_agent(self, *, triaged: list, trend: list, runtime: str) -> str:
        self.seen_triaged = triaged
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
    _seed_session(store, score=1, reason="超时两次颗粒无收")  # 体感偏低，构成一条曲线
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
    """把 proposals 打成 submit_rfcs 的返回形状（stop tool binding 的输出）。"""
    return json.dumps({"proposals": proposals}, ensure_ascii=False)


def _rfc_canned(
    covers: object = None, *, title: str = "结构：预算感知", fields: dict | None = None
) -> str:
    item: dict = {"title": title, "fields": fields if fields is not None else _rfc_fields()}
    if covers is not None:
        item["covers"] = covers
    return _submit([item])


def _triaged(tracker: FakeTracker, title: str, kind: str = "bug") -> int:
    return tracker.create_issue(IssueDraft(title=title, body="x", labels=[kind, TRIAGED])).number


def test_submit_rfcs_yaml_matches_contract() -> None:
    """drift-guard：submit_rfcs.tool.yaml 的 input_schema 是 agent_contract.rfc_input_schema() 的
    生成副本，必须与之深度相等（契约单一真源仍是 issue_schema.SCHEMAS）。"""
    import yaml  # noqa: PLC0415  仅本测用

    from auto_designer.designer.agent_contract import rfc_input_schema  # noqa: PLC0415

    yaml_path = (
        Path(__file__).resolve().parents[2]
        / "agent_defs"
        / "designer"
        / "tools"
        / "submit_rfcs.tool.yaml"
    )
    tool_def = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert tool_def["input_schema"] == rfc_input_schema()


def test_rfc_labeled_and_rendered_from_fields(tmp_path) -> None:
    tracker = FakeTracker()
    _triaged(tracker, "超时1")  # 已 triaged backlog（synthesize 的输入）
    designer = _designer(tmp_path, tracker, _rfc_canned())

    outcome = designer.propose_once()

    assert isinstance(outcome, DesignOutcome) and outcome.count == 1
    rfc = tracker.issue(outcome.proposal_numbers[0])
    assert RFC_LABEL in rfc["labels"]  # RFC 标签
    assert "### 问题\n\n大任务撞预算" in rfc["body"]  # 按 RFC schema 渲染
    assert "### 方向\n\n加预算感知" in rfc["body"]
    # 只喂 triaged 工作项（不喂 needs-triage/raw）
    assert [i.title for i in designer.seen_triaged] == ["超时1"]


def test_run_with_timeout_propagates_session_store(tmp_path) -> None:
    """bind_session_store 注入的 store 须能被 worker 线程里的 tool 读到（_run_with_timeout 用
    copy_context 跨线程传 contextvars）。修复前 worker 线程是空 context → get_session_timeline
    报「session store not bound」（线上实测 bug）。"""
    from auto_designer.designer.designer import _run_with_timeout
    from auto_designer.designer.session_timeline import bind_session_store, get_session_timeline
    from auto_designer.user.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    with bind_session_store(store):
        out = _run_with_timeout(lambda: get_session_timeline(session_id="nope"), 10)
    assert out["ok"] is False
    assert "not bound" not in out["error"]  # store 已跨线程绑定上
    assert "not found" in out["error"]  # 到了「查不到该 session」这步 = 绑定成功


def test_rfc_fields_label_whitespace_tolerant(tmp_path) -> None:
    """真实 LLM 可能用无空格「涉及issue」填字段——须能映射到 related，否则 RFC 校验永远失败被静默丢弃
    （线上实测 bug）。schema label 是「涉及 issue」（带空格），归一后应匹配上。"""
    tracker = FakeTracker()
    _triaged(tracker, "超时1")
    fields = {
        "问题": "多轮等待拖沓",
        "根因": "单 agent 长循环",
        "涉及issue": [],  # 无空格 + 空列表（正是线上 designer 的产物）
        "方向": "更早交回中间成果",
        "验收": "等待中能看到进展",
    }
    outcome = _designer(tmp_path, tracker, _rfc_canned(fields=fields)).propose_once()
    assert outcome.count == 1  # 修复前这里是 0（related 映射不上 → 校验失败 → 跳过）
    assert "### 涉及 issue" in tracker.issue(outcome.proposal_numbers[0])["body"]


def test_pm_rfc_without_triaged_or_covers(tmp_path) -> None:
    """synthesize 的 PM 职能：0 条 triaged 时也能凭体感+运行时产结构 RFC（covers 空、不 supersede
    任何票）；这条 RFC 应正常落库、成为 dev 可领项（线上「dev 无可领 RFC」的根因之一）。"""
    tracker = FakeTracker()  # 无 triaged
    fields = {
        "问题": "整轮超时才拿到结果",
        "根因": "长循环 + 超时上限偏大",
        "涉及issue": [],
        "方向": "超时/中断后给可接续状态摘要",
        "验收": "中断后能立即判断已完成/未完成",
    }
    outcome = _designer(tmp_path, tracker, _rfc_canned(fields=fields)).propose_once()
    assert outcome.count == 1
    rfc = tracker.issue(outcome.proposal_numbers[0])
    assert RFC_LABEL in rfc["labels"] and "covers:" not in rfc["body"]


def test_only_triaged_fed_not_needs_triage(tmp_path) -> None:
    """synthesize 的输入只含 triaged；needs-triage / superseded / RFC 自身都排除。"""
    tracker = FakeTracker()
    _triaged(tracker, "已triaged")
    tracker.create_issue(IssueDraft(title="待分诊", body="x", labels=["bug", "needs-triage"]))
    tracker.create_issue(
        IssueDraft(title="被取代", body="x", labels=["bug", TRIAGED, "superseded"])
    )
    tracker.create_issue(IssueDraft(title="旧RFC", body="x", labels=[RFC_LABEL, TRIAGED]))
    designer = _designer(tmp_path, tracker, _submit([]))
    designer.propose_once()
    assert [i.title for i in designer.seen_triaged] == ["已triaged"]


def test_empty_or_invalid_result_yields_no_rfc(tmp_path) -> None:
    """空 proposals / 非 JSON 散文（agent 未调 submit）/ 空串 → 本轮无提案、不抛错、不建任何 RFC。"""
    tracker = FakeTracker()
    _triaged(tracker, "t")
    before = len(tracker.list_open_issues())
    for canned in [_submit([]), "没有值得提的结构性方向。", ""]:
        outcome = _designer(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 0
    assert len(tracker.list_open_issues()) == before  # 未建任何 RFC


def test_rfc_missing_fields_skipped(tmp_path) -> None:
    """RFC 字段没填全 → 跳过（不产半成品）。工具层已锁 fields 键，但 per-kind 必填仍由 driver
    validate 二次把关。"""
    tracker = FakeTracker()
    _triaged(tracker, "t")
    canned = _submit([{"title": "半成品", "fields": {"问题": "只填了这个"}}])
    outcome = _designer(tmp_path, tracker, canned).propose_once()
    assert outcome.count == 0
    assert not any(i.title == "半成品" for i in tracker.list_open_issues())


def test_no_proposals_key_yields_no_rfc(tmp_path) -> None:
    """submit 返回缺 proposals 键 / 非预期形状 → 空列表兜底（不抛错）。"""
    tracker = FakeTracker()
    _triaged(tracker, "t")
    for canned in [json.dumps({}), json.dumps({"proposals": "not-a-list"}), json.dumps([])]:
        outcome = _designer(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 0


def test_multiple_proposals_all_landed(tmp_path) -> None:
    """一次 submit 多条 proposals 全部落库。"""
    tracker = FakeTracker()
    _triaged(tracker, "t")
    items = [
        {"title": "结构A", "fields": _rfc_fields()},
        {"title": "结构B", "fields": _rfc_fields()},
    ]
    outcome = _designer(tmp_path, tracker, _submit(items)).propose_once()
    assert outcome.count == 2
    titles = {tracker.issue(n)["title"] for n in outcome.proposal_numbers}
    assert titles == {"结构A", "结构B"}


def test_double_encoded_submit_tolerated(tmp_path) -> None:
    """兼容 nexau 可能把 stop-tool 返回值再 JSON 编码一层（返回值是「JSON 的 JSON 字符串」）。"""
    tracker = FakeTracker()
    _triaged(tracker, "t")
    once = _rfc_canned()
    twice = json.dumps(once, ensure_ascii=False)  # 再编码一层
    outcome = _designer(tmp_path, tracker, twice).propose_once()
    assert outcome.count == 1


# ---- Spec-0025/T4：covers → 被综合的 triaged issue 打 superseded + 挂链 ----


def test_rfc_covers_marks_triaged_superseded(tmp_path) -> None:
    tracker = FakeTracker()
    t1 = _triaged(tracker, "超时甲")
    t2 = _triaged(tracker, "超时乙")

    outcome = _designer(tmp_path, tracker, _rfc_canned([t1, t2])).propose_once()

    rfc_no = outcome.proposal_numbers[0]
    body = tracker.issue(rfc_no)["body"]
    assert f"covers: #{t1} #{t2}" in body  # 机器可读行
    for n in (t1, t2):
        snap = tracker.issue(n)
        assert "superseded" in snap["labels"]  # 被综合 → superseded（dev 不领）
        assert TRIAGED in snap["labels"]  # 原标签保留
        assert any(f"superseded by #{rfc_no}" in c for c in snap["comments"])
        assert snap["state"] == "open"  # designer 不关它（dev 修 RFC 时连带关，T5）


def test_covers_absent_no_supersede(tmp_path) -> None:
    tracker = FakeTracker()
    t1 = _triaged(tracker, "孤立")
    outcome = _designer(tmp_path, tracker, _rfc_canned(None)).propose_once()
    assert "covers:" not in tracker.issue(outcome.proposal_numbers[0])["body"]
    assert "superseded" not in tracker.issue(t1)["labels"]


def test_covers_skips_non_triaged_numbers(tmp_path) -> None:
    """covers 指向不在 triaged 集合的号（needs-triage/不存在）→ 静默跳过。"""
    tracker = FakeTracker()
    ok = _triaged(tracker, "有效")
    raw = tracker.create_issue(
        IssueDraft(title="raw", body="x", labels=["bug", "needs-triage"])
    ).number
    outcome = _designer(tmp_path, tracker, _rfc_canned([ok, raw, 999])).propose_once()
    body = tracker.issue(outcome.proposal_numbers[0])["body"]
    assert f"covers: #{ok}" in body and f"#{raw}" not in body.split("covers:")[1]
    assert "superseded" not in tracker.issue(raw)["labels"]  # 非 triaged 不被取代


def test_parse_covers_field_shapes() -> None:
    """_parse_covers 的宽进严出：去重、剔 bool/负数/0/字符串（工具层已锁 int，这是额外防线）。"""
    assert _parse_covers([5, 5, 6, True, -1, 0, "8"]) == (5, 6)
    assert _parse_covers("not-a-list") == ()
    assert _parse_covers(None) == ()
