"""Canonical normalized proposal projection shared by all downstream roles.

The projection deliberately excludes raw user reports. Historical mixed bodies are
trimmed at the legacy evidence heading; detailed evidence remains available through
session timeline tools and tracker comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from auto_designer.demand.issue_schema import (
    FROM_DIVERGENT,
    FROM_SYNTHESIZE,
    FROM_TRIAGE,
    OPENAGENTS,
    PRIORITIES,
    PROPOSAL,
    READY,
    REPORT,
    parse_covers_line,
    priority_of,
    provenance_of,
    round_of,
)

_LEGACY_EVIDENCE_HEADING = "## 原始用户报告（案例证据，非实现对象）"
_BODY_LIMIT = 3000
_CANONICAL_LABELS = frozenset(
    {REPORT, PROPOSAL, READY, OPENAGENTS, FROM_TRIAGE, FROM_SYNTHESIZE, FROM_DIVERGENT}
    | set(PRIORITIES)
)
_SESSION_REF = re.compile(
    r"^\s*(?:[-*]\s*)?(?:session_id|会话)\s*[:：]\s*([^\n]+)",
    re.MULTILINE | re.IGNORECASE,
)
_SESSION_TAG = re.compile(
    r"\[session=([A-Za-z0-9][A-Za-z0-9_.-]{0,127})\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProposalView:
    number: int
    title: str
    labels: tuple[str, ...]
    priority: str | None
    provenance: str | None
    covers: tuple[int, ...]
    body: str


def normalized_proposal_body(body: str) -> str:
    """Return only the normalized proposal section, including for legacy mixed bodies."""
    return (body or "").split(_LEGACY_EVIDENCE_HEADING, 1)[0].strip()[:_BODY_LIMIT]


def proposal_view(issue) -> ProposalView:
    labels = tuple(
        label
        for label in (str(value) for value in issue.labels)
        if label in _CANONICAL_LABELS or round_of([label]) is not None
    )
    return ProposalView(
        number=int(issue.number),
        title=str(issue.title).strip(),
        labels=labels,
        priority=priority_of(issue.labels),
        provenance=provenance_of(issue.labels),
        covers=tuple(parse_covers_line(issue.body)),
        body=normalized_proposal_body(issue.body),
    )


def format_proposal_view(issue) -> str:
    view = proposal_view(issue)
    metadata = [f"labels={','.join(view.labels) or '-'}"]
    if view.priority:
        metadata.append(f"priority={view.priority}")
    if view.provenance:
        metadata.append(f"provenance={view.provenance}")
    if view.covers:
        metadata.append(f"covers={','.join(f'#{number}' for number in view.covers)}")
    body = view.body or "（无规范化正文）"
    sessions = evidence_session_ids([issue])
    if sessions:
        metadata.append(f"evidence_sessions={','.join(sorted(sessions))}")
    return f"- #{view.number} [{'; '.join(metadata)}] {view.title}\n  {body}"


def format_proposal_list(issues: list) -> str:
    if not issues:
        return "（空）"
    return "\n".join(format_proposal_view(issue) for issue in issues)


def format_proposal_reference(issue) -> str:
    """Compact duplicate-reference projection; deliberately omits proposal body."""
    view = proposal_view(issue)
    metadata = [f"labels={','.join(view.labels) or '-'}"]
    if view.priority:
        metadata.append(f"priority={view.priority}")
    if view.provenance:
        metadata.append(f"provenance={view.provenance}")
    return f"- #{view.number} [{'; '.join(metadata)}] {view.title}"


def format_proposal_reference_list(issues: list) -> str:
    if not issues:
        return "（空）"
    return "\n".join(format_proposal_reference(issue) for issue in issues)


def evidence_session_ids(issues: list) -> set[str]:
    """Extract bounded session handles from normalized proposal evidence.

    This is intentionally lexical rather than semantic: a Synthesizer may inspect
    only evidence a preceding role actually cited.  It never scans the session
    store to discover additional tickets, and malformed/host-path-like values
    are ignored by the conservative token pattern.
    """

    found: set[str] = set()
    for issue in issues:
        # References may follow a long normalized body; never lose the authority
        # chain to the display text budget. Raw legacy reports remain excluded.
        body = str(getattr(issue, "body", "") or "").split(_LEGACY_EVIDENCE_HEADING, 1)[0]
        for match in _SESSION_REF.finditer(body):
            for value in re.split(r"[,，、\s]+", match.group(1)):
                value = value.strip("`\"'[]")
                if (
                    re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
                    and value != "unavailable"
                ):
                    found.add(value)
        found.update(_SESSION_TAG.findall(body))
    return found
