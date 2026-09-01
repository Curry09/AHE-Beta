# Spec-0050/T2：round_gate 终态判定，不打真 Gitea。
"""Hermetic tests for wait_round_delivery."""

from __future__ import annotations

import pytest

from auto_designer.loop.round_gate import (
    RoundDeliveryBlocked,
    classify_issue,
    wait_round_delivery,
)


def test_empty_wait_set_does_not_fetch() -> None:
    calls: list[int] = []

    def fetch_issue(number: int) -> dict:
        calls.append(number)
        return {"state": "open", "labels": []}

    wait_round_delivery(numbers=[], fetch_issue=fetch_issue)
    assert calls == []


def test_all_closed_succeeds() -> None:
    def fetch_issue(number: int) -> dict:
        return {"state": "closed", "labels": ["openagents"]}

    wait_round_delivery(numbers=[3, 3, 4], fetch_issue=fetch_issue)


def test_needs_human_raises() -> None:
    def fetch_issue(number: int) -> dict:
        if number == 2:
            return {"state": "open", "labels": [{"name": "needs-human"}]}
        return {"state": "closed", "labels": []}

    with pytest.raises(RoundDeliveryBlocked) as caught:
        wait_round_delivery(numbers=[1, 2], fetch_issue=fetch_issue)
    assert caught.value.numbers == [2]
    assert caught.value.reason == "needs-human"


def test_timeout_raises(*, monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = {"n": 0.0}

    def monotonic() -> float:
        return ticks["n"]

    def sleep(seconds: float) -> None:
        ticks["n"] += float(seconds)

    def fetch_issue(number: int) -> dict:
        return {"state": "open", "labels": ["ready"]}

    with pytest.raises(RoundDeliveryBlocked) as caught:
        wait_round_delivery(
            numbers=[9],
            fetch_issue=fetch_issue,
            timeout_sec=0.05,
            poll_sec=0.02,
            sleep=sleep,
            monotonic=monotonic,
        )
    assert caught.value.reason == "timeout"
    assert caught.value.numbers == [9]


def test_classify_closed_with_needs_human_is_blocked() -> None:
    assert classify_issue(state="closed", labels=["needs-human"]) == "blocked"
    assert classify_issue(state="closed", labels=["ready"]) == "done"
    assert classify_issue(state="open", labels=["ready"]) == "inflight"
