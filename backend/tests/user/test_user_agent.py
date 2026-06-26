"""spec-0001/T3：UserAgent 多轮驱动、自判终止、会话末体感/issue 单测。"""

from __future__ import annotations

import pytest

from auto_designer.harness.interface import FakeHarness
from auto_designer.models import Persona, SeedScenario
from auto_designer.user.user_agent import (
    END_SENTINEL,
    UserAgent,
    _parse_feeling,
    _parse_issues,
)


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


class FakeLLM:
    """按 kind 分发的 mock LLM：message 逐条弹出，feeling/issue 各返回固定串。"""

    def __init__(self, messages: list[str], feeling: str, issues: str) -> None:
        self._messages = list(messages)
        self._mi = 0
        self._feeling = feeling
        self._issues = issues

    def __call__(self, *, kind: str, prompt: str) -> str:
        if kind == "message":
            m = self._messages[self._mi]
            self._mi += 1
            return m
        if kind == "feeling":
            return self._feeling
        if kind == "issue":
            return self._issues
        raise ValueError(kind)


def test_self_terminates_at_end_signal() -> None:
    llm = FakeLLM(["m1", "m2", "m3", f"done {END_SENTINEL}"], "3 还行", "[]")
    agent = UserAgent(llm=llm, persona=_persona(), max_turns=10)
    harness = FakeHarness(script=["r1", "r2", "r3"])
    transcript, feeling, drafts = agent.run(SeedScenario(description="x"), harness)
    user_turns = [t for t in transcript.turns if t.role == "user"]
    harness_turns = [t for t in transcript.turns if t.role == "harness"]
    assert len(user_turns) == 3 and len(harness_turns) == 3
    assert harness.sent == ["m1", "m2", "m3"]  # 收发序列与 user 轮一致
    assert [t.content for t in user_turns] == ["m1", "m2", "m3"]
    assert feeling.score == 3
    assert drafts == []


def test_max_turns_cutoff() -> None:
    llm = FakeLLM(["go"] * 5, "2 一般", "[]")  # 永不发结束信号
    agent = UserAgent(llm=llm, persona=_persona(), max_turns=5)
    harness = FakeHarness(callback=lambda m: "ok")
    transcript, _, _ = agent.run(SeedScenario(description="x"), harness)
    assert len([t for t in transcript.turns if t.role == "user"]) == 5


def test_feeling_parsed_with_reason() -> None:
    llm = FakeLLM([f"{END_SENTINEL}"], "4 非常顺手", "[]")
    agent = UserAgent(llm=llm, persona=_persona(), max_turns=3)
    _, feeling, _ = agent.run(SeedScenario(description="x"), FakeHarness())
    assert feeling.score == 4 and feeling.reason == "非常顺手"


def test_issue_stub_zero_and_two() -> None:
    issues = '[{"title": "t1", "body": "b1", "labels": ["bug"]}, {"title": "t2", "body": "b2", "labels": []}]'
    llm = FakeLLM([f"{END_SENTINEL}"], "3 ok", issues)
    agent = UserAgent(llm=llm, persona=_persona(), max_turns=3)
    _, _, drafts = agent.run(SeedScenario(description="x"), FakeHarness())
    assert len(drafts) == 2
    assert drafts[0].title == "t1" and drafts[0].labels == ["bug"]

    llm0 = FakeLLM([f"{END_SENTINEL}"], "3 ok", "[]")
    _, _, drafts0 = UserAgent(llm=llm0, persona=_persona(), max_turns=3).run(
        SeedScenario(description="x"), FakeHarness()
    )
    assert drafts0 == []


def test_parse_issues_strips_code_fence() -> None:
    raw = '```json\n[{"title": "t", "body": "b", "labels": []}]\n```'
    out = _parse_issues(raw)
    assert len(out) == 1 and out[0].title == "t"


def test_parse_issues_with_surrounding_text() -> None:
    raw = '好的，归纳如下：[{"title": "t", "body": "b", "labels": ["bug"]}] 以上。'
    out = _parse_issues(raw)
    assert len(out) == 1 and out[0].labels == ["bug"]


def test_parse_issues_truncated_degrades_to_empty() -> None:
    # 真实崩溃复现：max_tokens 截断导致未闭合字符串，不得炸整轮，降级为 0 条。
    raw = '[{"title": "t", "body": "很长的描述被截断'
    assert _parse_issues(raw) == []


def test_parse_issues_non_list_degrades_to_empty() -> None:
    assert _parse_issues('{"title": "t"}') == []


def test_parse_feeling_tolerates_fence_and_prefix() -> None:
    assert _parse_feeling("```\n3 还行\n```").score == 3
    fs = _parse_feeling("评分 4：非常顺手")
    assert fs.score == 4 and fs.reason == "非常顺手"


def test_on_progress_streams_each_turn() -> None:
    # 流式：每轮回调两次（用户已发→harness 待回复；harness 回复到）。
    snapshots: list[list[tuple[str, str]]] = []

    def on_progress(transcript) -> None:
        snapshots.append([(t.role, t.content) for t in transcript.turns])

    llm = FakeLLM(["问题1", f"done {END_SENTINEL}"], "3 ok", "[]")  # 一轮真对话后结束
    agent = UserAgent(llm=llm, persona=_persona(), max_turns=3, on_progress=on_progress)
    agent.run(SeedScenario(description="x"), FakeHarness(script=["答复1"]))

    # 第一次回调：仅用户已发（末轮为 user → 回复中）；第二次：harness 回复已到。
    assert snapshots[0] == [("user", "问题1")]
    assert snapshots[1] == [("user", "问题1"), ("harness", "答复1")]


def test_no_on_progress_is_optional() -> None:
    llm = FakeLLM([f"hi {END_SENTINEL}"], "3 ok", "[]")
    UserAgent(llm=llm, persona=_persona(), max_turns=3).run(
        SeedScenario(description="x"), FakeHarness()
    )  # 不传 on_progress 不应报错


def test_max_turns_must_be_positive() -> None:
    with pytest.raises(AssertionError):
        UserAgent(llm=FakeLLM([], "3 ok", "[]"), persona=_persona(), max_turns=0)


def test_feeling_out_of_range_fails_at_construction() -> None:
    llm = FakeLLM([f"{END_SENTINEL}"], "5 越界", "[]")
    agent = UserAgent(llm=llm, persona=_persona(), max_turns=3)
    with pytest.raises(AssertionError):
        agent.run(SeedScenario(description="x"), FakeHarness())


def test_send_exception_propagates() -> None:
    def boom(_m: str) -> str:
        raise RuntimeError("harness 崩了")

    llm = FakeLLM(["m1"], "3 ok", "[]")
    agent = UserAgent(llm=llm, persona=_persona(), max_turns=3)
    with pytest.raises(RuntimeError):
        agent.run(SeedScenario(description="x"), FakeHarness(callback=boom))
