"""Spec-0061: scoped maintainer diagnostic gaps with a durable outbox.

User-facing feedback requirements use ordinary product proposals. This service
validates request structure and authority; role contracts define diagnostic intent.
"""

from __future__ import annotations

import contextvars
import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

from ahe_beta.demand.issue_schema import round_label
from ahe_beta.invocation import _redact
from ahe_beta.models import IssueDraft
from ahe_beta.observations.grants import authorized_sessions, grant, is_pm_source
from ahe_beta.usage import current_usage_context

_CURRENT: contextvars.ContextVar = contextvars.ContextVar("observation_gap_service", default=None)
FIELDS = ("question", "checked", "unknowns", "impact", "desired_capability", "verification")
FIELD_DESCRIPTIONS = {
    "question": "The concrete diagnostic question a maintainer needs to answer about execution or a change.",
    "checked": "Authorized versioned records and reading guidance already checked, with their limits.",
    "unknowns": "Facts or causes the maintainer still cannot distinguish; do not invent a root cause.",
    "impact": "Which maintenance, design, or verification decision is blocked or weakened by missing evidence.",
    "desired_capability": "The ability to reconstruct or distinguish execution from evidence, not a user-facing status feature.",
    "verification": "A scenario proving the diagnostic question is answerable; user-visible progress alone is insufficient.",
}


def gap_schema() -> dict:
    properties = {
        key: {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "description": FIELD_DESCRIPTIONS[key],
        }
        for key in FIELDS
    }
    properties.update(
        {
            "request_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "scope": {"type": "string", "enum": ["harness", "framework"]},
            "session_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
            "related_issues": {"type": "array", "items": {"type": "integer"}, "maxItems": 16},
        }
    )
    return {
        "type": "object",
        "properties": properties,
        "required": [*FIELDS, "request_id", "scope", "session_ids", "related_issues"],
        "additionalProperties": False,
    }


class GapService:
    def __init__(
        self, *, store, tracker, role: str, subject: str, sessions: set[str], issues: set[int]
    ) -> None:
        self.store, self.tracker, self.role = store, tracker, role
        self.subject, self.sessions, self.issues = subject, sessions, issues
        self.root = store.root.parent / "observation-gaps"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.active = True

    def submit(self, request: dict) -> dict:
        import jsonschema

        if not self.active:
            return {"ok": False, "error": "invocation_closed"}
        jsonschema.validate(request, gap_schema())
        if (
            not set(request["session_ids"]) <= self.sessions
            or not set(request["related_issues"]) <= self.issues
        ):
            return {"ok": False, "error": "outside_evidence_scope"}
        identity = f"{self.role}:{self.subject}:{request['request_id']}"
        key = hashlib.sha256(identity.encode()).hexdigest()
        path = self.root / f"{key}.json"
        clean = json.loads(_redact(text=json.dumps(request, ensure_ascii=False)) or "null")
        if not isinstance(clean, dict):
            return {"ok": False, "error": "redaction_failed"}
        with (self.root / f"{key}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                row = json.loads(path.read_text())
                if row["request"] != clean:
                    return {"ok": False, "error": "request_id_conflict"}
            else:
                row = {"key": key, "request": clean, "role": self.role, "state": "pending"}
                self._save(path, row)
            if clean["scope"] == "framework":
                row["state"] = "infrastructure_diagnostic"
                self._save(path, row)
                return {
                    "ok": True,
                    "status": row["state"],
                    "request_id": key,
                    "note": "Framework is fixed during this experiment; no evolution proposal created.",
                }
            return self._flush(path, row)

    def _save(self, path: Path, row: dict) -> None:
        temp = path.with_suffix(".tmp")
        with temp.open("w") as stream:
            json.dump(row, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)

    def _flush(self, path: Path, row: dict) -> dict:
        try:
            marker = f"observation-gap-id: {row['key']}"
            found = row.get("issue")
            if found is None:
                found = self.tracker.find_observation_gap(marker=marker)
            request = row["request"]
            pm_origin = row["role"] in {"pm", "divergent", "divergent_pm"} or any(
                is_pm_source(store=self.store, issue=n) for n in request["related_issues"]
            )
            if found is None:
                if not self.active:
                    return {"ok": False, "status": "pending", "error": "invocation_closed"}
                body = "\n\n".join(f"## {key}\n\n{request[key]}" for key in FIELDS)
                body += "\n\n" + "\n".join(f"session_id: {sid}" for sid in request["session_ids"])
                body += "\n\nrelated issues: " + ", ".join(
                    f"#{n}" for n in request["related_issues"]
                )
                body += f"\n\nsource-role: {row['role']}\n{marker}"
                labels = ["proposal", "observation-gap"]
                round_no = current_usage_context().round_no
                if type(round_no) is int and round_no > 0:
                    labels.append(round_label(round_no))
                if pm_origin:
                    labels.append("from-divergent")
                found = self.tracker.create_issue(
                    IssueDraft(
                        title="诊断观测补强：" + request["question"][:120],
                        body=body,
                        labels=labels,
                    )
                ).number
            row.update(issue=found, state="pending")
            # Persist the remote identity before subsequent steps, so retries do not create a new ticket.
            self._save(path, row)
            sessions = set(request["session_ids"])
            if row["role"] == "owner":
                # Forward original evidence authority, without giving Owner any raw read tool.
                sessions |= set().union(
                    *(
                        authorized_sessions(store=self.store, issue=n)
                        for n in request["related_issues"]
                    )
                )
            grant(store=self.store, issue=found, sessions=sessions, pm_origin=pm_origin)
            row["state"] = "submitted"
            self._save(path, row)
            return {"ok": True, "status": "submitted", "issue": found}
        except Exception as exc:  # Durable pending is not a successful submission.
            row["error"] = type(exc).__name__
            self._save(path, row)
            return {
                "ok": False,
                "status": "pending",
                "request_id": row["key"],
                "error": row["error"],
            }

    def retry_pending(self) -> None:
        attempted = 0
        for path in sorted(self.root.glob("*.json")):
            with path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    row = json.loads(path.read_text())
                except (OSError, ValueError):
                    continue
                if row.get("state") == "pending":
                    self._flush(path, row)
                    attempted += 1
                    if attempted >= 10:
                        break


@contextmanager
def bind_gaps(service):
    token = _CURRENT.set(service)
    try:
        if service is not None:
            service.retry_pending()
        yield
    finally:
        if service is not None:
            service.active = False
        _CURRENT.reset(token)


def submit_observation_gap(**request) -> dict:
    service = _CURRENT.get()
    if service is None:
        return {"ok": False, "error": "no_authorized_invocation"}
    # NexAU may inject execution objects; only declared request fields are data.
    return service.submit(
        {key: request[key] for key in gap_schema()["properties"] if key in request}
    )
