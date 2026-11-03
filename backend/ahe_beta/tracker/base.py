"""IssueTracker protocol (spec-0001/T5): abstraction for issue submission destinations, decoupling user side from specific backend.

Use FakeTracker for testing (fake.py in same directory); inject GiteaTracker (spec-0002) at runtime. Both are equivalent for run_session.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Protocol, runtime_checkable

from ahe_beta.models import IssueDraft, IssueRef, OpenIssue

_OPERATION_MARKER_RE = re.compile(r"<!-- ahe-beta-operation:([0-9a-f]{32}):([0-9a-f]{64}) -->")


class IdempotencyConflictError(RuntimeError):
    """A stable operation key already exists with a different payload."""


def operation_marker(*, operation_key: str, payload_digest: str) -> str:
    """Return a hidden marker without exposing the original operation key."""
    key_digest = hashlib.sha256(operation_key.encode()).hexdigest()[:32]
    return f"<!-- ahe-beta-operation:{key_digest}:{payload_digest} -->"


def operation_marker_digest(*, text: str, operation_key: str) -> str | None:
    """Return the payload digest recorded for an operation, when present."""
    key_digest = hashlib.sha256(operation_key.encode()).hexdigest()[:32]
    return next(
        (
            payload_digest
            for marker_key, payload_digest in _OPERATION_MARKER_RE.findall(text)
            if marker_key == key_digest
        ),
        None,
    )


def issue_payload_digest(draft: IssueDraft) -> str:
    """Return the digest used to detect operation-key payload conflicts."""
    body = json.dumps(draft.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


@runtime_checkable
class IssueTracker(Protocol):
    """Issue backend contract (structured subtyping). number is issued monotonically by backend, semantics align with Gitea."""

    def ensure_labels(self, names: list[str]) -> None:
        """Ensure all given labels exist. Idempotent; empty list is a no-op."""
        ...

    def create_issue(self, draft: IssueDraft) -> IssueRef:
        """Create issue from draft, return receipt IssueRef with assigned number (initial state="open"). No deduplication."""
        ...

    def create_issue_once(self, draft: IssueDraft, *, operation_key: str) -> IssueRef:
        """Create once by stable operation key; reconcile an existing matching issue."""
        ...

    def list_open_issues(self) -> list[OpenIssue]:
        """Read path: list currently open issues (for developer side to claim per spec-0003/T3). Empty list if none."""
        ...

    def get_issue(self, *, number: int) -> dict[str, Any]:
        """Read current title, body, state and label names, including closed issues."""
        ...

    def add_comment(self, number: int, body: str) -> None:
        """Append a comment to the specified issue. Raises KeyError if number does not exist."""
        ...

    def add_comment_once(self, number: int, body: str, *, operation_key: str) -> None:
        """Append a comment once by stable operation key."""
        ...

    def set_state(self, number: int, state: str, reason: str) -> None:
        """Change state. state ∈ {open, closed}; raises ValueError if invalid; raises KeyError if number does not exist."""
        ...

    def set_labels(self, number: int, labels: list[str]) -> None:
        """Wholesale replace labels on an issue to labels (Spec-0025/T3a: triage removes needs-triage and adds triaged).

        Replacement semantics (not incremental)—caller computes the target label set. Unknown labels are ensured first.
        Raises KeyError if number does not exist.
        """
        ...

    def update_issue(self, number: int, *, title: str, body: str, labels: list[str]) -> None:
        """Replace title, body, and labels with retryable semantics; backend implementations must roll back on failure."""
        ...

    def transition_issue(self, number: int, *, state: str, labels: list[str]) -> None:
        """Replace state and labels with retryable semantics; backend implementations must roll back on failure."""
        ...
