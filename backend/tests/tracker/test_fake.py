"""spec-0001/T5：IssueTracker 协议与 FakeTracker 行为单测。"""

from __future__ import annotations

import pytest

from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.tracker.fake import FakeTracker


def _draft() -> IssueDraft:
    return IssueDraft(title="t", body="b", labels=["bug"])


def test_satisfies_protocol() -> None:
    assert isinstance(FakeTracker(), IssueTracker)


def test_create_issue_monotonic_numbering() -> None:
    t = FakeTracker()
    r1 = t.create_issue(_draft())
    r2 = t.create_issue(_draft())
    assert (r1.number, r2.number) == (1, 2)
    assert r1.state == "open"
    assert r1.url == "fake://issues/1"


def test_add_comment() -> None:
    t = FakeTracker()
    r = t.create_issue(_draft())
    t.add_comment(r.number, "一条评论")
    assert "一条评论" in t.issue(r.number)["comments"]


def test_set_state_round_trip() -> None:
    t = FakeTracker()
    r = t.create_issue(_draft())
    t.set_state(r.number, "closed", "已修复")
    snap = t.issue(r.number)
    assert (snap["state"], snap["reason"]) == ("closed", "已修复")
    t.set_state(r.number, "open", "重新打开")
    assert t.issue(r.number)["state"] == "open"


def test_ensure_labels_idempotent_and_noop() -> None:
    t = FakeTracker()
    t.ensure_labels(["bug", "feature"])
    t.ensure_labels(["bug"])
    assert t.labels() == {"bug", "feature"}
    t.ensure_labels([])  # no-op


def test_missing_number_raises_key_error() -> None:
    t = FakeTracker()
    with pytest.raises(KeyError):
        t.add_comment(999, "x")
    with pytest.raises(KeyError):
        t.set_state(999, "closed", "x")


def test_illegal_state_raises_value_error() -> None:
    t = FakeTracker()
    r = t.create_issue(_draft())
    with pytest.raises(ValueError):
        t.set_state(r.number, "merged", "x")


def test_create_issue_does_not_dedupe() -> None:
    t = FakeTracker()
    d = _draft()
    assert t.create_issue(d).number != t.create_issue(d).number
