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
    DESIGN_LABEL,
    Designer,
    DesignOutcome,
    _unwrap_result,
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
    """覆盖 _run_agent：不跑真 nexau，回放一段固定 result，并记录喂进的信号。"""

    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.seen_backlog: list = []
        self.seen_trend: list = []
        self.seen_runtime: str = ""

    def _run_agent(self, *, backlog: list, trend: list, runtime: str) -> str:
        self.seen_backlog = backlog
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


def test_proposals_become_design_labeled_issues(tmp_path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="慢", body="ORM 慢", labels=["bug"]))  # 已有 backlog
    canned = (
        "分析后给出提案：\n```json\n"
        '[{"title": "统一错误处理契约", "body": "多条 issue 指向缺乏统一兜底", "labels": ["design"]},'
        '{"title": "澄清前置追问策略", "body": "体感偏低源于不追问", "labels": []}]\n'
        "```\n以上。"
    )
    designer = _designer(tmp_path, tracker, canned)

    outcome = designer.propose_once()

    assert isinstance(outcome, DesignOutcome)
    assert outcome.count == 2
    # 两条提案都落成 open issue，且都带 design 标签（第二条原本没 labels 也被补上）。
    opened = {i.number: i for i in tracker.list_open_issues()}
    for number in outcome.proposal_numbers:
        assert DESIGN_LABEL in opened[number].labels
    titles = {i.title for i in opened.values()}
    assert {"统一错误处理契约", "澄清前置追问策略"} <= titles
    # backlog + 体感曲线确实喂进了 agent（曲线现在带上体感 reason 那句「为什么」）。
    assert [i.title for i in designer.seen_backlog] == ["慢"]
    assert [s for _, s, _, _ in designer.seen_trend] == [2, 1]
    assert [reason for _, _, reason, _ in designer.seen_trend] == ["等太久", "超时两次颗粒无收"]
    assert all(sid for _, _, _, sid in designer.seen_trend)  # 带 session_id 供 timeline tool
    # 运行时聚合也注入了（空 transcript 会话 → 0 harness 轮，但仍有窗口说明）。
    assert "局会话" in designer.seen_runtime or "暂无会话数据" in designer.seen_runtime


def test_empty_or_invalid_result_yields_no_proposals(tmp_path) -> None:
    tracker = FakeTracker()
    for canned in ["[]", "没有值得提的结构性方向。", ""]:
        outcome = _designer(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 0
    assert tracker.list_open_issues() == []  # 全程未建任何 issue


# ---- Spec-0020/T1：covers 覆盖关系——提案字段 → body 机器行 + 被覆盖 bug 挂链 ----


def _covers_canned(covers: object) -> str:
    return json.dumps(
        [{"title": "整合根因", "body": "多 bug 同根因", "labels": [], "covers": covers}],
        ensure_ascii=False,
    )


def test_covers_written_to_body_and_linked_on_bugs(tmp_path) -> None:
    tracker = FakeTracker()
    b1 = tracker.create_issue(IssueDraft(title="bug甲", body="x", labels=["bug"])).number
    b2 = tracker.create_issue(IssueDraft(title="bug乙", body="y", labels=["bug"])).number

    outcome = _designer(tmp_path, tracker, _covers_canned([b1, b2])).propose_once()

    assert outcome.count == 1
    design_no = outcome.proposal_numbers[0]
    body = tracker.issue(design_no)["body"]
    assert f"covers: #{b1} #{b2}" in body  # 机器可读行（单一真源）
    for n in (b1, b2):
        assert f"covered-by: #{design_no}" in tracker.issue(n)["comments"]  # 挂链
        assert tracker.issue(n)["state"] == "open"  # designer 无关票权：bug 仍 open


def test_covers_absent_or_invalid_behaves_like_today(tmp_path) -> None:
    """covers 缺省/空/整体非法时：body 无 covers 行、无任何 comment——与今天行为一致。"""
    for covers in (None, [], "not-a-list", [0, -3, True, "7"]):
        tracker = FakeTracker()
        bug = tracker.create_issue(IssueDraft(title="bug", body="x", labels=["bug"])).number
        canned = (
            _covers_canned(covers)
            if covers is not None
            else json.dumps([{"title": "无覆盖", "body": "b", "labels": []}], ensure_ascii=False)
        )
        outcome = _designer(tmp_path, tracker, canned).propose_once()
        assert outcome.count == 1
        assert "covers:" not in tracker.issue(outcome.proposal_numbers[0])["body"]
        assert tracker.issue(bug)["comments"] == []


def test_covers_skips_closed_missing_and_design_numbers(tmp_path) -> None:
    """covers 指向已 closed / 不存在 / design 票的号：静默跳过，只留合法 bug 号。"""
    tracker = FakeTracker()
    closed = tracker.create_issue(IssueDraft(title="已关", body="x", labels=["bug"])).number
    tracker.set_state(closed, "closed", "done")
    other_design = tracker.create_issue(
        IssueDraft(title="设计", body="d", labels=["design"])
    ).number
    ok = tracker.create_issue(IssueDraft(title="有效bug", body="y", labels=["bug"])).number

    covers = [closed, other_design, ok, 999]
    outcome = _designer(tmp_path, tracker, _covers_canned(covers)).propose_once()

    design_no = outcome.proposal_numbers[0]
    body = tracker.issue(design_no)["body"]
    assert f"covers: #{ok}" in body and f"#{closed}" not in body.split("covers:")[1]
    assert tracker.issue(other_design)["comments"] == []  # design 票不被互指
    assert f"covered-by: #{design_no}" in tracker.issue(ok)["comments"]


def test_parse_covers_field_shapes() -> None:
    """_parse_proposals 对 covers 的宽进严出：去重、剔 bool/负数/字符串。"""
    text = json.dumps(
        [{"title": "t", "body": "b", "covers": [5, 5, 6, True, -1, 0, "8"]}],
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
    return [p.draft.title for p in Designer._parse_proposals(_unwrap_result(text))]


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
