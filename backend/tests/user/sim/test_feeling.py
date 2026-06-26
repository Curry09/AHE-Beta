"""spec-0005/T4：体感评分两路并出 + held-out（不读客观真值）。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from auto_designer.user.sim.feeling import FeelingScore, derive_feeling, parse_feeling_llm


@dataclass
class _Turn:
    """derive_feeling 只 duck-type 读 verdict / trust 两个主观字段。"""

    verdict: str
    trust: str = "balanced"


def test_feelingscore_roundtrip_and_bounds() -> None:
    fs = FeelingScore(score=3, reason="ok")
    assert FeelingScore.from_dict(fs.to_dict()) == fs
    for bad in (0, 5):
        with pytest.raises(AssertionError):
            FeelingScore(score=bad, reason="x")


def test_parse_feeling_llm() -> None:
    assert parse_feeling_llm({"score": 4, "reason": "smooth"}) == FeelingScore(4, "smooth")
    assert parse_feeling_llm({"reason": "no score"}) is None       # 缺 score
    assert parse_feeling_llm({"score": "abc"}) is None             # 非整数
    assert parse_feeling_llm({"score": 5}) is None                 # 越界
    assert parse_feeling_llm({"score": 2}).reason == ""            # reason 缺省空串


def test_derive_feeling_mapping() -> None:
    assert derive_feeling("accepted", [_Turn("satisfied")]).score == 4
    # accepted 但多次怪 harness -> 降为有摩擦的接受(3)
    assert derive_feeling("accepted", [_Turn("failed_blame_harness")] * 2).score == 3
    # accepted 但末态信任 skeptical -> 3
    assert derive_feeling("accepted", [_Turn("satisfied", "skeptical")]).score == 3
    assert derive_feeling("max_turns", [_Turn("unsure")]).score == 2
    assert derive_feeling("issue_filed", [_Turn("failed_blame_harness")]).score == 2
    assert derive_feeling("abandoned", [_Turn("failed_blame_harness")]).score == 1
    assert derive_feeling("terminated", []).score == 2  # 未知 end_reason 落 2


def test_derive_feeling_is_held_out() -> None:
    # 仅含主观字段的 turns 即可派生；不依赖任何 gold/objective 字段
    turns = [_Turn("satisfied"), _Turn("unsure")]
    fs = derive_feeling("accepted", turns)
    assert 1 <= fs.score <= 4
