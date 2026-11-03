"""spec-0005/T4: subjective feeling scores output both paths + held-out (does not read objective ground truth)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ahe_beta.user.sim.feeling import FeelingScore, derive_feeling, parse_feeling_llm


@dataclass
class _Turn:
    """derive_feeling duck-types only verdict / trust two subjective fields."""

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
    assert parse_feeling_llm({"reason": "no score"}) is None  # missing score
    assert parse_feeling_llm({"score": "abc"}) is None  # non-integer
    assert parse_feeling_llm({"score": 5}) is None  # out of bounds
    assert parse_feeling_llm({"score": 2}).reason == ""  # reason defaults to empty string
    for value in (True, False, "2", 2.9, 2.0, None):
        assert parse_feeling_llm({"score": value}) is None


def test_derive_feeling_mapping() -> None:
    assert derive_feeling("accepted", [_Turn("satisfied")]).score == 4
    # accepted but harness misbehaves multiple times -> downgrade to friction-laden acceptance (3)
    assert derive_feeling("accepted", [_Turn("failed_blame_harness")] * 2).score == 3
    # accepted but final trust state skeptical -> 3
    assert derive_feeling("accepted", [_Turn("satisfied", "skeptical")]).score == 3
    assert derive_feeling("max_turns", [_Turn("unsure")]).score == 2
    assert derive_feeling("issue_filed", [_Turn("failed_blame_harness")]).score == 2
    assert derive_feeling("abandoned", [_Turn("failed_blame_harness")]).score == 1
    assert derive_feeling("terminated", []).score == 2  # unknown end_reason falls to 2


def test_derive_feeling_is_held_out() -> None:
    # turns containing only subjective fields can be derived; do not depend on any gold/objective fields
    turns = [_Turn("satisfied"), _Turn("unsure")]
    fs = derive_feeling("accepted", turns)
    assert 1 <= fs.score <= 4
