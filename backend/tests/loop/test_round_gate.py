# Spec-0050/T2：round_gate 终态判定，不打真 Gitea。
"""Hermetic tests for wait_round_delivery."""

from __future__ import annotations

import pytest

from ahe_beta.loop.round_gate import (
    RoundDeliveryBlocked,
    classify_issue,
    inspect_round_delivery,
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


def test_inspect_round_delivery_deduplicates_and_classifies_for_resume() -> None:
    calls: list[int] = []

    def fetch_issue(number: int) -> dict:
        calls.append(number)
        return {
            "state": "closed" if number == 1 else "open",
            "labels": ["ready"] if number != 3 else ["automation-failed"],
        }

    assert inspect_round_delivery(numbers=[1, 1, 2, 3], fetch_issue=fetch_issue) == {
        1: "done",
        2: "inflight",
        3: "blocked",
    }
    assert calls == [1, 2, 3]


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


def test_default_wait_survives_four_hours_and_expires_after_one_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROUND_DELIVERY_TIMEOUT_SEC", raising=False)
    ticks = {"now": 0.0, "reads": 0}
    jumps = iter((14_401.0, 86_399.0, 86_401.0))

    def fetch_issue(number: int) -> dict:
        ticks["reads"] += 1
        return {"state": "open", "labels": ["ready"]}

    with pytest.raises(RoundDeliveryBlocked) as caught:
        wait_round_delivery(
            numbers=[9],
            fetch_issue=fetch_issue,
            poll_sec=1,
            monotonic=lambda: ticks["now"],
            sleep=lambda _seconds: ticks.__setitem__("now", next(jumps)),
        )
    assert caught.value.reason == "timeout"
    assert ticks["reads"] == 4


def test_classify_closed_with_needs_human_is_blocked() -> None:
    assert classify_issue(state="closed", labels=["needs-human"]) == "blocked"
    assert classify_issue(state="closed", labels=["ready"]) == "done"
    assert classify_issue(state="open", labels=["ready"]) == "inflight"


@pytest.mark.parametrize("state", ["open", "closed"])
@pytest.mark.parametrize("label", ["automation-failed", "needs-human"])
@pytest.mark.parametrize("mapping", [True, False])
def test_failure_labels_stop_immediately(state: str, label: str, mapping: bool) -> None:
    """Spec-0062/T1: failure must not wait for timeout, even after issue closure."""
    assert classify_issue(state=state, labels=[label]) == "blocked"
    sleeps: list[float] = []

    def fetch_issue(number: int) -> dict:
        return {"state": state, "labels": [{"name": label}] if mapping else [label]}

    with pytest.raises(RoundDeliveryBlocked) as caught:
        wait_round_delivery(numbers=[8, 8], fetch_issue=fetch_issue, sleep=sleeps.append)
    assert caught.value.numbers == [8]
    assert caught.value.reason == label
    assert sleeps == []


def test_mixed_failure_reasons_are_explicit() -> None:
    """Spec-0062/T1: report all blocked subjects and the labels actually observed."""

    def fetch_issue(number: int) -> dict:
        labels = {1: [], 2: ["needs-human"], 3: ["automation-failed"]}
        return {"state": "closed", "labels": labels[number]}

    with pytest.raises(RoundDeliveryBlocked) as caught:
        wait_round_delivery(numbers=[1, 2, 3], fetch_issue=fetch_issue)
    assert caught.value.numbers == [2, 3]
    assert caught.value.reason == "automation-failed,needs-human"
