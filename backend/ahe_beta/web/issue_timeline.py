"""Spec-0039/T2: Collapse Gitea label timeline into replayable issue state and integrity anomalies.

This module has no network or storage access: current state is projected only from current issue labels; timeline only explains history and provides last-known state, never back-fills current ground truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ahe_beta.demand.issue_schema import (
    DECLINED,
    FROM_ARCHITECT,
    FROM_DIVERGENT,
    FROM_TRIAGE,
    GATE_DROPPED,
    MERGED,
    NEEDS_INFO,
    OPENAGENTS,
    PRIORITIES,
    PROPOSAL,
    READY,
    REJECTED,
    REPORT,
    SUPERSEDED,
    plane,
    priority_of,
    provenance_of,
    round_of,
)

_PROVENANCE = (FROM_TRIAGE, FROM_ARCHITECT, FROM_DIVERGENT)
_TERMINALS = (MERGED, DECLINED, REJECTED, NEEDS_INFO, GATE_DROPPED, SUPERSEDED)
_NEEDS_HUMAN = "needs-human"


def unavailable_timeline(*, reason: str = "tracker does not expose timeline") -> dict[str, Any]:
    """Stable degradation shape for detail API."""
    return {
        "available": False,
        "reason": reason,
        "complete": False,
        "events": [],
        "transitions": [],
        "current": None,
        "historical": None,
        "last_known": {},
        "anomalies": [],
    }


def build_issue_timeline(*, issue: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay label events in server order to generate migration batches, current/historical state, and deterministic anomalies."""
    current_labels = frozenset(str(label) for label in issue.get("labels") or [])
    label_events = [
        event
        for event in events
        if event.get("type") == "label"
        and event.get("label")
        and event.get("operation") in {"add", "remove"}
    ]
    complete = _history_starts_at_creation(issue=issue, label_events=label_events)
    batches = _batch_events(events=events)
    labels: frozenset[str] = frozenset()
    transitions: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    last_known: dict[str, Any] = {
        "plane": None,
        "provenance": None,
        "priority": None,
        "round": None,
    }

    for index, batch in enumerate(batches):
        before = _state(labels=labels)
        added = frozenset(event["label"] for event in batch if event["operation"] == "add")
        removed = frozenset(event["label"] for event in batch if event["operation"] == "remove")
        labels = (labels - removed) | added
        after = _state(labels=labels)
        transition_id = f"transition-{index + 1}"
        transition_anomalies = _transition_anomalies(
            before=before,
            after=after,
            added=added,
            transition_id=transition_id,
        )
        anomalies.extend(transition_anomalies)
        for key in last_known:
            if after[key] is not None:
                last_known[key] = after[key]
        transitions.append(
            {
                "id": transition_id,
                "created_at": batch[0].get("created_at") or "",
                "actor": batch[0].get("actor") or "",
                "title": _transition_title(
                    added=added, removed=removed, anomalies=transition_anomalies
                ),
                "added": sorted(added),
                "removed": sorted(removed),
                "before": before,
                "after": after,
                "anomaly_ids": [item["id"] for item in transition_anomalies],
            }
        )

    historical = _state(labels=labels)
    current = _state(labels=current_labels)
    if not complete:
        anomalies.append(
            _anomaly(
                code="incomplete-history",
                message="The timeline does not cover the initial labels at issue creation; historical replay is less reliable.",
            )
        )
    if labels != current_labels:
        anomalies.append(
            _anomaly(
                code="timeline-current-drift",
                message="The final replayed labels differ from current Gitea labels; issue details remain authoritative for the current state.",
            )
        )

    return {
        "available": True,
        "reason": None,
        "complete": complete,
        "events": events,
        "transitions": transitions,
        "current": current,
        "historical": historical,
        "last_known": last_known,
        "anomalies": anomalies,
    }


def _batch_events(*, events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Only collapse consecutive, simultaneous, same-actor label events; other types naturally break batches."""
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    key: tuple[str, str] | None = None
    for event in events:
        known_label = (
            event.get("type") == "label"
            and event.get("label")
            and event.get("operation") in {"add", "remove"}
        )
        event_key = (str(event.get("created_at") or ""), str(event.get("actor") or ""))
        if not known_label:
            if current:
                batches.append(current)
                current = []
            key = None
            continue
        if current and event_key != key:
            batches.append(current)
            current = []
        current.append(event)
        key = event_key
    if current:
        batches.append(current)
    return batches


def _state(*, labels: frozenset[str]) -> dict[str, Any]:
    plane_values = []
    if REPORT in labels:
        plane_values.append(REPORT)
    if PROPOSAL in labels:
        plane_values.append(PROPOSAL)
    if READY in labels or OPENAGENTS in labels:
        plane_values.append(READY)
    provenance_values = [value for value in _PROVENANCE if value in labels]
    priority_values = [value for value in PRIORITIES if value in labels]
    round_labels = sorted(label for label in labels if _is_round_label(label))
    conflicts: list[str] = []
    if len(set(plane_values)) > 1:
        conflicts.append("plane")
    if len(provenance_values) > 1:
        conflicts.append("provenance")
    if len(priority_values) > 1:
        conflicts.append("priority")
    if len(round_labels) > 1:
        conflicts.append("round")
    terminal = next((value for value in _TERMINALS if value in labels), None)
    label_list = sorted(labels)
    return {
        "labels": label_list,
        "plane": plane(label_list),
        "provenance": provenance_of(label_list),
        "priority": priority_of(label_list),
        "round": round_of(label_list),
        "handoff": OPENAGENTS in labels and READY not in labels,
        "delivery_active": READY in labels,
        "blocked": _NEEDS_HUMAN in labels,
        "terminal": terminal,
        "conflicts": conflicts,
    }


def _transition_anomalies(
    *, before: dict[str, Any], after: dict[str, Any], added: frozenset[str], transition_id: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    lost: list[str] = []
    if before["plane"] is not None and after["plane"] is None and after["terminal"] is None:
        lost.append("plane")
        out.append(
            _anomaly(
                code="plane-drop-without-terminal",
                message="The open workflow lost its valid plane without a terminal label in the same batch.",
                transition_id=transition_id,
                dimensions=["plane"],
            )
        )
    for dimension, code in (
        ("provenance", "provenance-lost"),
        ("round", "round-lost"),
        ("priority", "priority-lost"),
    ):
        if dimension == "priority" and not (
            before["plane"] == READY or before["handoff"] or before["delivery_active"]
        ):
            continue
        if before[dimension] is not None and after[dimension] is None and after["terminal"] is None:
            lost.append(dimension)
            out.append(
                _anomaly(
                    code=code,
                    message=f"The existing {dimension} label was removed without a replacement.",
                    transition_id=transition_id,
                    dimensions=[dimension],
                )
            )
    if _NEEDS_HUMAN in added and lost:
        out.append(
            _anomaly(
                code="blocking-destroyed-metadata",
                message="The batch that added needs-human also cleared workflow metadata.",
                transition_id=transition_id,
                dimensions=sorted(set(lost)),
                severity="critical",
            )
        )
    if after["conflicts"]:
        out.append(
            _anomaly(
                code="exclusive-dimension-conflict",
                message="The same state contains multiple mutually exclusive dimension labels.",
                transition_id=transition_id,
                dimensions=after["conflicts"],
            )
        )
    return out


def _anomaly(
    *,
    code: str,
    message: str,
    transition_id: str | None = None,
    dimensions: list[str] | None = None,
    severity: str = "warning",
) -> dict[str, Any]:
    suffix = transition_id or "timeline"
    return {
        "id": f"{code}:{suffix}",
        "code": code,
        "severity": severity,
        "message": message,
        "transition_id": transition_id,
        "dimensions": dimensions or [],
    }


def _transition_title(
    *, added: frozenset[str], removed: frozenset[str], anomalies: list[dict[str, Any]]
) -> str:
    if anomalies:
        return "Label integrity anomaly"
    if _NEEDS_HUMAN in added:
        return "Delivery blocked"
    if any(label in added for label in _TERMINALS):
        return "Entered terminal state"
    if PROPOSAL in added:
        return "Proposal created"
    if READY in added:
        return "Entered Ready"
    if OPENAGENTS in added or PROPOSAL in removed:
        return "Owner admission / delivery handoff"
    return "Labels updated"


def _history_starts_at_creation(
    *, issue: dict[str, Any], label_events: list[dict[str, Any]]
) -> bool:
    if not label_events or not issue.get("created_at"):
        return False
    created = _parse_time(str(issue["created_at"]))
    first = _parse_time(str(label_events[0].get("created_at") or ""))
    return created is not None and first is not None and first <= created + timedelta(seconds=1)


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_round_label(label: str) -> bool:
    head, separator, tail = label.partition("-")
    return head == "round" and separator == "-" and tail.isdigit() and int(tail) > 0
