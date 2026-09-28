"""Ingest only authenticated delivery requests, never arbitrary comments or logs."""

from __future__ import annotations

import json
import os
import re

from jsonschema import ValidationError

from auto_designer.observations.gaps import GapService
from auto_designer.observations.grants import authorized_sessions, observation_root

MARKER = "auto-designer:observation-gap-v1"
ROLES = {
    "drafter",
    "spec_writer",
    "architect",
    "developer",
    "implementer",
    "executor",
    "reviewer",
    "acceptance",
}


def ingest_delivery_gaps(*, store, tracker) -> list[dict]:
    """Check issue-scoped automation reports at the next ordinary proposal window."""
    login = getattr(tracker, "authenticated_login", None)
    if login is None:
        return []
    paths = sorted((observation_root(store) / ".grants").glob("*.json"))
    if not paths:
        return []
    actor = os.environ.get("AUTO_DESIGNER_DELIVERY_ACTOR") or login()
    outcomes = []
    for path in paths:
        issue = int(path.stem)
        sessions = authorized_sessions(store=store, issue=issue)
        for comment in tracker.list_comments(number=issue):
            if comment.get("author") != actor:
                continue
            body = comment.get("body", "")
            if len(body) > 64_000 or "<!-- openagents:agent=observation-runner -->" not in body:
                continue
            matches = re.findall(r"<!-- " + re.escape(MARKER) + r" (\{[^\n]+\}) -->", body)
            if len(matches) != 1:
                continue
            try:
                payload = json.loads(matches[0])
                role = payload["role"]
                if payload["issue"] != issue or role not in ROLES:
                    continue
                service = GapService(
                    store=store,
                    tracker=tracker,
                    role=f"delivery-{role}",
                    subject=f"issue-{issue}",
                    sessions=sessions,
                    issues={issue},
                )
                outcomes.append(service.submit(payload["request"]))
            except (ValueError, TypeError, KeyError, ValidationError):
                outcomes.append({"ok": False, "error": "invalid_delivery_gap"})
    return outcomes
