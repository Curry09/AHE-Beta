"""FakeTracker (spec-0001/T5): in-memory implementation of IssueTracker for unit tests and end-to-end runs without Gitea.

Issue IDs increment monotonically starting from 1 (per-instance counter, aligned with auto-increment within a Gitea instance); semantics align with Gitea but without network or persistence.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ahe_beta.models import ISSUE_STATES, IssueDraft, IssueRef, OpenIssue
from ahe_beta.tracker.base import (
    IdempotencyConflictError,
    issue_payload_digest,
    operation_marker,
    operation_marker_digest,
)

# Placeholder prefix for FakeTracker URL synthesis.
_URL_PREFIX = "fake://issues/"


class FakeTracker:
    """In-memory implementation of IssueTracker."""

    def __init__(self) -> None:
        self._counter = 0
        self._issues: dict[int, dict[str, Any]] = {}
        self._labels: set[str] = set()

    def ensure_labels(self, names: list[str]) -> None:
        self._labels.update(names)  # Idempotent: set deduplication; empty list is a no-op

    def create_issue(self, draft: IssueDraft) -> IssueRef:
        self._counter += 1
        number = self._counter
        self._issues[number] = {
            "title": draft.title,
            "body": draft.body,
            "labels": list(draft.labels),
            "state": "open",
            "reason": "",
            "comments": [],
        }
        return IssueRef(number=number, url=f"{_URL_PREFIX}{number}", state="open")

    def create_issue_once(self, draft: IssueDraft, *, operation_key: str) -> IssueRef:
        """Spec-0064/T1: reconcile an earlier successful create before retrying."""
        payload_digest = issue_payload_digest(draft)
        for number, issue in self._issues.items():
            existing = operation_marker_digest(text=issue["body"], operation_key=operation_key)
            if existing is None:
                continue
            if existing != payload_digest:
                raise IdempotencyConflictError(
                    f"operation key already created issue #{number} with another payload"
                )
            return IssueRef(number=number, url=f"{_URL_PREFIX}{number}", state=issue["state"])
        marker = operation_marker(operation_key=operation_key, payload_digest=payload_digest)
        body = f"{draft.body.rstrip()}\n\n{marker}" if draft.body else marker
        return self.create_issue(
            IssueDraft(title=draft.title, body=body, labels=list(draft.labels))
        )

    def list_open_issues(self) -> list[OpenIssue]:
        return [
            OpenIssue(
                number=n,
                title=i["title"],
                body=i["body"],
                labels=list(i["labels"]),
                state=i["state"],
            )
            for n, i in sorted(self._issues.items())
            if i["state"] == "open"
        ]

    def add_comment(self, number: int, body: str) -> None:
        self._require(number)["comments"].append(body)

    def add_comment_once(self, number: int, body: str, *, operation_key: str) -> None:
        """Spec-0064/T1: reconcile an earlier successful comment before retrying."""
        issue = self._require(number)
        payload_digest = hashlib.sha256(body.encode()).hexdigest()
        for comment in issue["comments"]:
            existing = operation_marker_digest(text=comment, operation_key=operation_key)
            if existing is None:
                continue
            if existing != payload_digest:
                raise IdempotencyConflictError(
                    f"operation key already added another comment to issue #{number}"
                )
            return
        marker = operation_marker(operation_key=operation_key, payload_digest=payload_digest)
        self.add_comment(number, f"{body.rstrip()}\n\n{marker}" if body else marker)

    def list_comments(self, *, number: int) -> list[dict[str, Any]]:
        """Observation read path (Spec-0020/T2, shape aligned with GiteaTracker.list_comments): [{author, body, created_at}].

        Not part of the IssueTracker protocol; used by dev side via getattr probe (data source for retry escalation/sink determination).
        """
        return [
            {"author": "", "body": c, "created_at": ""} for c in self._require(number)["comments"]
        ]

    def set_state(self, number: int, state: str, reason: str) -> None:
        if state not in ISSUE_STATES:
            raise ValueError(f"Invalid state: {state!r} (must be one of {ISSUE_STATES})")
        issue = self._require(number)
        issue["state"] = state
        issue["reason"] = reason

    def set_labels(self, number: int, labels: list[str]) -> None:
        """Spec-0025/T3a: bulk replace labels (replacement semantics); also ensure presence in the label set (aligned with Gitea)."""
        issue = self._require(number)
        self._labels.update(labels)
        issue["labels"] = list(labels)

    def update_issue(self, number: int, *, title: str, body: str, labels: list[str]) -> None:
        issue = self._require(number)
        self._labels.update(labels)
        issue.update(title=title, body=body, labels=list(labels))

    def transition_issue(self, number: int, *, state: str, labels: list[str]) -> None:
        if state not in ISSUE_STATES:
            raise ValueError(f"Invalid state: {state!r} (must be one of {ISSUE_STATES})")
        issue = self._require(number)
        self._labels.update(labels)
        issue.update(state=state, labels=list(labels))

    def issue(self, number: int) -> dict[str, Any]:
        """Read-only: return a snapshot copy of this issue for unit test assertions on comment/state changes."""
        snapshot = self._require(number)
        return {
            **snapshot,
            "labels": list(snapshot["labels"]),
            "comments": list(snapshot["comments"]),
        }

    def get_issue(self, *, number: int) -> dict[str, Any]:
        return self.issue(number)

    def labels(self) -> set[str]:
        """Read-only: copy of the current label set."""
        return set(self._labels)

    def find_observation_gap(self, *, marker: str) -> int | None:
        return next((n for n, issue in self._issues.items() if marker in issue["body"]), None)

    def _require(self, number: int) -> dict[str, Any]:
        if number not in self._issues:
            raise KeyError(f"Issue does not exist: #{number}")
        return self._issues[number]
