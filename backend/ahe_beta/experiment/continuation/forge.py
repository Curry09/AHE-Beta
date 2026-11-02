"""Spec-0079/T2: project only selected pending reports into the child's fresh forge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ahe_beta.demand.issue_schema import REPORT, plane
from ahe_beta.experiment.config import ConfigError
from ahe_beta.loop.recovery import digest_value, operation_key
from ahe_beta.models import IssueDraft, IssueRef
from ahe_beta.tracker.base import issue_payload_digest, operation_marker


def source_report_key(
    *, export: dict, repository: dict, number: int, parent_archive_sha256: str | None
) -> str:
    """Namespace a historical number by the frozen direct-parent identity and repository."""
    return digest_value(
        {
            "parent": export["identity"],
            "parent_archive_sha256": parent_archive_sha256,
            "repository": repository,
            "number": number,
        }
    )


def pending_report(report: dict) -> bool:
    labels = set(report["labels"])
    return (
        report["state"] == "open"
        and plane(report["labels"]) == REPORT
        and not labels.intersection(
            {
                "declined",
                "merged",
                "rejected",
                "needs-info",
                "gate-dropped",
                "superseded",
                "delivered",
                "owner-rejected",
                "openagents/ready",
            }
        )
    )


def _verify_remote_report(*, tracker: Any, draft: IssueDraft, mapped: dict, operation: str) -> None:
    observed = tracker.get_issue(number=mapped["current_number"])
    if ("number" in observed and observed["number"] != mapped["current_number"]) or (
        observed.get("url") and observed["url"] != mapped["current_url"]
    ):
        raise ConfigError("Continuation projected report remote identity changed")
    marker = operation_marker(operation_key=operation, payload_digest=issue_payload_digest(draft))
    expected_body = f"{draft.body.rstrip()}\n\n{marker}" if draft.body else marker
    if observed.get("title") == draft.title and observed.get("body") == expected_body:
        return
    audit = (
        "## 原始用户报告（案例证据，非实现对象）\n\n"
        f"**原始标题：** {draft.title}\n\n{expected_body}"
    )
    if not any(
        comment.get("body", "").startswith(audit)
        for comment in tracker.list_comments(number=mapped["current_number"])
    ):
        raise ConfigError("Continuation projected report payload changed remotely")


def verify_report_projection(
    *,
    tracker: Any,
    parent_root: Path,
    export: dict,
    projection: dict,
    child_identity: dict,
    child_seed: str,
    parent_archive_sha256: str | None = None,
) -> None:
    """Read-only reconciliation after feedback import; never create or rewrite a receipt."""
    identity = {
        "child": child_identity,
        "parent": export["identity"],
        "parent_archive_sha256": parent_archive_sha256,
        "child_seed": child_seed,
    }
    if (
        projection.get("schema_version") != 1
        or projection.get("identity") != identity
        or projection.get("complete") is not True
        or projection.get("source_digest") != digest_value(export["reports"])
        or projection.get("map_hash") != digest_value(projection.get("issue_map"))
    ):
        raise ConfigError("Continuation report projection receipt changed")
    repository = json.loads((parent_root / export["forge"]["path"]).read_text())["repository"]
    expected_keys = set()
    used_numbers = set()
    for report in export["reports"]:
        if not pending_report(report):
            continue
        source_key = source_report_key(
            export=export,
            repository=repository,
            number=report["number"],
            parent_archive_sha256=parent_archive_sha256,
        )
        expected_keys.add(source_key)
        mapped = projection["issue_map"].get(source_key)
        if not isinstance(mapped, dict):
            raise ConfigError("Continuation source report has no current mapping")
        operation = operation_key(
            "continuation-bootstrap", child_identity, source_key, report["sha256"]
        )
        expected = {
            "source_number": report["number"],
            "source_url": report["url"],
            "source_sha256": report["sha256"],
            "projected_sha256": digest_value({k: v for k, v in report.items() if k != "sha256"}),
            "source_labels": list(report["labels"]),
            "source_repository": repository,
            "session_ids": list(report["session_ids"]),
            "operation_key": operation,
        }
        if (
            type(mapped.get("current_number")) is not int
            or mapped["current_number"] <= 0
            or mapped["current_number"] in used_numbers
            or any(mapped.get(key) != value for key, value in expected.items())
        ):
            raise ConfigError("Continuation projected report mapping changed")
        used_numbers.add(mapped["current_number"])
        draft = IssueDraft(
            title=report["title"], body=report["body"], labels=["report", "needs-triage"]
        )
        _verify_remote_report(tracker=tracker, draft=draft, mapped=mapped, operation=operation)
    if expected_keys != set(projection["issue_map"]):
        raise ConfigError("Continuation projection contains an unexpected source report")


def project_reports(
    *,
    tracker: Any,
    parent_root: Path,
    export: dict,
    child_identity: dict,
    child_seed: str,
    receipt_path: Path,
    parent_archive_sha256: str | None = None,
) -> dict:
    """Reconcile remote markers before atomically publishing the actual issue map."""
    forge = json.loads((parent_root / export["forge"]["path"]).read_text())
    repository = forge["repository"]
    collection = parent_root / "collection.json"
    projections = (
        json.loads(collection.read_text()).get("public_projections", {})
        if collection.is_file()
        else {}
    )
    identity = {
        "child": child_identity,
        "parent": export["identity"],
        "parent_archive_sha256": parent_archive_sha256,
        "child_seed": child_seed,
    }
    receipt = {"schema_version": 1, "identity": identity, "issue_map": {}}
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("identity") != identity:
            raise ConfigError("Continuation report projection identity changed")
    for report in export["reports"]:
        if not pending_report(report):
            continue
        source_key = source_report_key(
            export=export,
            repository=repository,
            number=report["number"],
            parent_archive_sha256=parent_archive_sha256,
        )
        source = {key: value for key, value in report.items() if key != "sha256"}
        projected_digest = digest_value(source)
        if projected_digest != report["sha256"] and (
            projections.get("runtime/continuation-export.json", {}).get("reason")
            != "credential_redaction"
        ):
            raise ConfigError("Continuation source report digest changed")
        # Source-round labels and execution authority never become child authority.
        draft = IssueDraft(
            title=report["title"],
            body=report["body"],
            labels=["report", "needs-triage"],
        )
        key = operation_key("continuation-bootstrap", child_identity, source_key, report["sha256"])
        previous = receipt["issue_map"].get(source_key)
        # Triage deliberately replaces an accepted report's body with a proposal.
        # Its original operation marker then lives in the audit comment. Never
        # create another report merely because that deliberate migration happened.
        ref = (
            IssueRef(previous["current_number"], previous["current_url"], "open")
            if previous is not None
            else tracker.create_issue_once(draft, operation_key=key)
        )
        mapped = {
            "source_number": report["number"],
            "source_url": report["url"],
            "source_sha256": report["sha256"],
            "projected_sha256": projected_digest,
            "source_labels": list(report["labels"]),
            "source_repository": repository,
            "session_ids": list(report["session_ids"]),
            "current_number": ref.number,
            "current_url": ref.url,
            "operation_key": key,
        }
        if previous is not None and previous != mapped:
            raise ConfigError("Continuation projected report mapping changed")
        _verify_remote_report(tracker=tracker, draft=draft, mapped=mapped, operation=key)
        receipt["issue_map"][source_key] = mapped
        _write_receipt(receipt_path, receipt)
    receipt["source_digest"] = digest_value(export["reports"])
    receipt["map_hash"] = digest_value(receipt["issue_map"])
    receipt["complete"] = True
    _write_receipt(receipt_path, receipt)
    return receipt


def _write_receipt(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
