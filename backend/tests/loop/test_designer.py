# 创新者侧：Designer 综合全局产结构性提案单测（stub nexau agent + FakeTracker + 临时 SessionStore）。
"""验证 designer 驱动器：

- agent 产出的 JSON 提案被落成带 `design` 标签的 open issue（供开发者领取）；
- 提案 result 含代码块/前后散文时仍能鲁棒解析；空/非法 result 退化为「本轮无提案」不抛错；
- backlog + 体感曲线确实喂进了 agent 的任务消息。
"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.designer.designer import (
    Designer,
    DesignOutcome,
    _unwrap_result,
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
    """覆盖 _run_agent：不跑真 nexau，回放一段固定 result，并记录喂进的信号（Spec-0025/T4：triaged）。"""

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
    return {"问题": "大任务撞预算", "根因": "无增量交付", "涉及 issue": "#多条", "方向": "加预算感知", "验收": "预算内给交付"}


def _rfc_canned(covers: object = None, *, title: str = "结构：预算感知", fields: dict | None = None) -> str:
    item: dict = {"title": title, "fields": fields if fields is not None else _rfc_fields()}
    if covers is not None:
        item["covers"] = covers
    return json.dumps([item], ensure_ascii=False)


def _triaged(tracker: FakeTracker, title: str, kind: str = "bug") -> int:
    return tracker.create_issue(IssueDraft(title=title, body="x", labels=[kind, TRIAGED])).number


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


def test_only_triaged_fed_not_needs_triage(tmp_path) -> None:
    """synthesize 的输入只含 triaged；needs-triage / superseded / RFC 自身都排除。"""
    tracker = FakeTracker()
    _triaged(tracker, "已triaged")
    tracker.create_issue(IssueDraft(title="待分诊", body="x", labels=["bug", "needs-triage"]))
    tracker.create_issue(IssueDraft(title="被取代", body="x", labels=["bug", TRIAGED, "superseded"]))
    tracker.create_issue(IssueDraft(title="旧RFC", body="x", labels=[RFC_LABEL, TRIAGED]))
    designer = _designer(tmp_path, tracker, "[]")
    designer.propose_once()
    assert [i.title for i in designer.seen_triaged] == ["已triaged"]


def test_empty_or_invalid_result_yields_no_rfc(tmp_path) -> None:
    tracker = FakeTracker()
    _triaged(tracker, "t")
    before = len(tracker.list_open_issues())
    for canned in ["[]", "没有值得提的结构性方向。", ""]:
        outcome = _designer(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 0
    assert len(tracker.list_open_issues()) == before  # 未建任何 RFC


def test_rfc_missing_fields_skipped(tmp_path) -> None:
    """RFC 字段没填全 → 跳过（不产半成品）。"""
    tracker = FakeTracker()
    _triaged(tracker, "t")
    canned = json.dumps([{"title": "半成品", "fields": {"问题": "只填了这个"}}], ensure_ascii=False)
    outcome = _designer(tmp_path, tracker, canned).propose_once()
    assert outcome.count == 0
    assert not any(i.title == "半成品" for i in tracker.list_open_issues())


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
    raw = tracker.create_issue(IssueDraft(title="raw", body="x", labels=["bug", "needs-triage"])).number
    outcome = _designer(tmp_path, tracker, _rfc_canned([ok, raw, 999])).propose_once()
    body = tracker.issue(outcome.proposal_numbers[0])["body"]
    assert f"covers: #{ok}" in body and f"#{raw}" not in body.split("covers:")[1]
    assert "superseded" not in tracker.issue(raw)["labels"]  # 非 triaged 不被取代


def test_parse_covers_field_shapes() -> None:
    """_parse_proposals 对 covers 的宽进严出：去重、剔 bool/负数/字符串。"""
    text = json.dumps(
        [{"title": "t", "fields": {}, "covers": [5, 5, 6, True, -1, 0, "8"]}],
        ensure_ascii=False,
    )
    (prop,) = Designer._parse_proposals(text)
    assert prop.covers == (5, 6)


# ---- Spec-0018/T1：拆 complete_task 信封（提案被静默丢弃的回归） ----

# 真实回归夹具：一次长跑里被静默丢弃的那条 designer 返回原文（逐字照抄，未做任何整形）。
# 注意它是**双重编码**的——整段是一个 JSON 字符串，里面才是 complete_task 信封：
# 只 json.loads 一次只得到 str（而非 dict），这正是「看似修好、实则没修」的陷阱所在。
_REAL_ENVELOPE = (
    r'"{\"success\": true, \"message\": \"Result submitted and task completed.\", '
    r"\"status\": \"TASK_COMPLETED\", \"task_completed\": true, \"output\": {\"result\": "
    r"\"[\\n  {\\n    \\\"title\\\": \\\"长编码任务的完成性预算与未完成交付\\\",\\n    "
    r"\\\"body\\\": \\\"#19 与体感曲线中“首次超时但最终通过”的那次共同指向同一根因：当任务超过"
    r"单轮稳定完成预算时，用户拿到的是中断/等待后的低信任状态，而不是可审查、可验证、可继续推进的"
    r"产物。\\\",\\n    \\\"labels\\\": [\\n      \\\"structural\\\",\\n      "
    r'\\\"reliability\\\"\\n    ]\\n  }\\n]\"}}"'
)


def _envelope(result: object) -> str:
    """nexau complete_task 信封；实测还会被再 JSON 编码一层，故双重 dumps。"""
    inner = {
        "success": True,
        "message": "Result submitted and task completed.",
        "status": "TASK_COMPLETED",
        "task_completed": True,
        "output": {"result": result},
    }
    return json.dumps(json.dumps(inner, ensure_ascii=False), ensure_ascii=False)


def _titles(text: str) -> list[str]:
    return [p.title for p in Designer._parse_proposals(_unwrap_result(text))]


def test_unwrap_envelope_with_result_as_json_string() -> None:
    """信封里 result 是「JSON 数组的字符串」（agent 听话用 complete_task 交付的标准形状）。"""
    drafts = json.dumps([{"title": "预算拖垮可用交付", "body": "b", "labels": ["design"]}])
    assert _titles(_envelope(drafts)) == ["预算拖垮可用交付"]


def test_unwrap_envelope_with_result_as_array_body() -> None:
    """信封里 result 直接是数组本体（而非其字符串形式）——两种都要接。"""
    assert _titles(_envelope([{"title": "等待不可见", "body": "b"}])) == ["等待不可见"]


def test_unwrap_envelope_with_empty_result_yields_no_proposals() -> None:
    """宁缺毋滥：信封里 result 为空数组 → 0 条提案，而非报错。"""
    assert _titles(_envelope("[]")) == []


def test_bare_array_path_unchanged() -> None:
    """裸 JSON 数组（agent 不调 complete_task 时的形状）行为一字不变。"""
    bare = json.dumps([{"title": "裸数组", "body": "b"}], ensure_ascii=False)
    assert _titles(bare) == ["裸数组"]


def test_fenced_and_prose_paths_unchanged() -> None:
    """```json 围栏 + 前后散文两条既有路径行为不变。"""
    fenced = '想了想：\n```json\n[{"title": "围栏", "body": "b"}]\n```\n以上。'
    assert _titles(fenced) == ["围栏"]


def test_malformed_envelope_falls_back_to_raw_text() -> None:
    """畸形 / 非信封 JSON → 回落原文、不抛错（退回今天的行为，而非炸）。"""
    assert _unwrap_result('{"success": true}') == '{"success": true}'  # dict 但无 output.result
    assert _unwrap_result("就是一段散文，没有 JSON") == "就是一段散文，没有 JSON"
    assert _unwrap_result(None) == "None"  # 非 str 兜底


def test_real_long_run_envelope_regression() -> None:
    """回归：长跑里被静默丢弃的那条真实返回原文——修前解析出 0 条，修后必须解析出提案。"""
    assert Designer._parse_proposals(_REAL_ENVELOPE) == []  # 修前的行为：提案被信封吞掉
    titles = _titles(_REAL_ENVELOPE)  # 修后：提案回来了
    assert titles and "长编码任务的完成性预算与未完成交付" in titles[0]
