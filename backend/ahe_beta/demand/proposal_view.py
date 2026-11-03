"""Canonical normalized proposal projection shared by all downstream roles.

The projection deliberately excludes raw user reports. Mixed bodies are trimmed
at the raw report heading; detailed evidence remains available through
session timeline tools and tracker comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ahe_beta.demand.evidence_contract import execution_for_sessions, format_execution_facts
from ahe_beta.demand.issue_schema import (
    FROM_ARCHITECT,
    FROM_DIVERGENT,
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
from ahe_beta.observations.grants import authorized_sessions

_RAW_REPORT_HEADING = "## Original user report (case evidence, not an implementation target)"
_BODY_LIMIT = 3000
_CANONICAL_LABELS = frozenset(
    {REPORT, PROPOSAL, READY, OPENAGENTS, FROM_TRIAGE, FROM_ARCHITECT, FROM_DIVERGENT}
    | set(PRIORITIES)
)
_SESSION_REF = re.compile(
    r"^\s*(?:[-*]\s*)?session_id\s*:\s*([^\n]+)",
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
    execution_contracts: tuple[dict, ...] = ()
    assessment_summaries: tuple[dict, ...] = ()
    unavailable_sources: tuple[dict, ...] = ()


def normalized_proposal_body(body: str) -> str:
    """Return only the normalized proposal section, excluding appended raw reports."""
    return _without_raw_report(body or "").strip()[:_BODY_LIMIT]


def _without_raw_report(body: str) -> str:
    return body.split(_RAW_REPORT_HEADING, 1)[0]


def proposal_view(issue, *, store=None) -> ProposalView:
    labels = tuple(
        label
        for label in (str(value) for value in issue.labels)
        if label in _CANONICAL_LABELS or round_of([label]) is not None
    )
    execution = (
        execution_for_sessions(
            store=store, session_ids=authorized_sessions(store=store, issue=int(issue.number))
        )
        if store is not None
        else {}
    )
    return ProposalView(
        execution_contracts=tuple(execution.get("execution_contracts") or []),
        assessment_summaries=tuple(execution.get("assessment_summaries") or []),
        unavailable_sources=tuple(execution.get("unavailable_sources") or []),
        number=int(issue.number),
        title=str(issue.title).strip(),
        labels=labels,
        priority=priority_of(issue.labels),
        provenance=provenance_of(issue.labels),
        covers=tuple(parse_covers_line(issue.body)),
        body=normalized_proposal_body(issue.body),
    )


def format_proposal_view(issue, *, store=None) -> str:
    view = proposal_view(issue, store=store)
    metadata = [f"labels={','.join(view.labels) or '-'}"]
    if view.priority:
        metadata.append(f"priority={view.priority}")
    if view.provenance:
        metadata.append(f"provenance={view.provenance}")
    if view.covers:
        metadata.append(f"covers={','.join(f'#{number}' for number in view.covers)}")
    body = view.body or "(No normalized body)"
    sessions = evidence_session_ids([issue])
    if sessions:
        metadata.append(f"evidence_sessions={','.join(sorted(sessions))}")
    execution = format_execution_facts(
        {
            "execution_contracts": list(view.execution_contracts),
            "assessment_summaries": list(view.assessment_summaries),
            "unavailable_sources": list(view.unavailable_sources),
        }
    )
    return f"- #{view.number} [{'; '.join(metadata)}] {view.title}\n  {body}" + (
        f"\n  Trusted execution conditions (independent of body truncation): {execution}"
        if execution
        else ""
    )


def format_proposal_list(issues: list, *, store=None) -> str:
    if not issues:
        return "(empty)"
    return "\n".join(format_proposal_view(issue, store=store) for issue in issues)


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
        return "(empty)"
    return "\n".join(format_proposal_reference(issue) for issue in issues)


def evidence_session_ids(issues: list) -> set[str]:
    """Extract bounded session handles from normalized proposal evidence.

    This is intentionally lexical rather than semantic: an Architect may inspect
    only evidence a preceding role actually cited.  It never scans the session
    store to discover additional tickets, and malformed/host-path-like values
    are ignored by the conservative token pattern.
    """

    found: set[str] = set()
    for issue in issues:
        # References may follow a long normalized body; never lose the authority
        # chain to the display text budget. Raw legacy reports remain excluded.
        body = _without_raw_report(str(getattr(issue, "body", "") or ""))
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
