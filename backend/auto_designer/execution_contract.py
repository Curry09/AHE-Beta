"""Immutable execution declarations and public evidence wire (Spec-0084/T1).

No provider, model or grading dependency. Runtime assistance belongs to a separate
receipt, never to the declaration whose digest identifies the original conditions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CONTRACT_KEYS = frozenset(
    {
        "contract_id",
        "session_id",
        "task_id",
        "task_digest",
        "followup_input",
        "task_budget_seconds",
        "budget_source",
        "public_refs",
    }
)
_SUMMARY_KEYS = frozenset(
    {
        "receipt_id",
        "session_id",
        "contract_id",
        "status",
        "passed",
        "score",
        "metric_definition",
        "assessment_kind",
        "source_sha256",
    }
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError(f"{name} must be a SHA256 digest")


def _text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def _keys(value: Mapping, expected: frozenset[str], name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{name} fields do not match schema 1")


def validate_execution_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    _keys(value, _CONTRACT_KEYS, "execution contract")
    for name in ("session_id", "task_id", "budget_source"):
        _text(value[name], name)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value["session_id"]):
        raise ValueError("invalid contract session_id")
    for name in ("contract_id", "task_digest"):
        _sha(value[name], name)
    if value["followup_input"] not in {"unavailable", "possible", "unknown"}:
        raise ValueError("invalid followup_input")
    seconds = value["task_budget_seconds"]
    if seconds is not None and (
        type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0
    ):
        raise ValueError("task_budget_seconds must be positive finite seconds or null")
    refs = value["public_refs"]
    if not isinstance(refs, list):
        raise ValueError("public_refs must be an array")
    for ref in refs:
        _keys(ref, frozenset({"kind", "path", "sha256"}), "public reference")
        _text(ref["kind"], "reference kind")
        _text(ref["path"], "reference path")
        _sha(ref["sha256"], "reference digest")
        raw = ref["path"]
        path = PurePosixPath(raw)
        if (
            path.is_absolute()
            or "\\" in raw
            or "\x00" in raw
            or ":" in raw
            or any(part in {"", ".", ".."} for part in raw.split("/"))
            or path.parts[0] != value["session_id"]
            or any(part.lower() in {"evaluation", "private", "grader"} for part in path.parts)
        ):
            raise ValueError("public reference must be an authorized session-relative package path")
    normalized = sorted(refs, key=lambda row: (row["kind"], row["path"], row["sha256"]))
    if refs != normalized or len({ref["path"] for ref in refs}) != len(refs):
        raise ValueError("public references must be unique and canonically ordered")
    declaration = {key: value[key] for key in value if key != "contract_id"}
    if canonical_sha256(declaration) != value["contract_id"]:
        raise ValueError("execution contract digest mismatch")
    return json.loads(canonical_bytes(dict(value)))


def make_execution_contract(
    *,
    session_id: str,
    task_id: str,
    task_digest: str,
    followup_input: str,
    task_budget_seconds: float | None,
    budget_source: str,
    public_refs: Sequence[Mapping[str, Any]] = (),
) -> dict:
    declaration = dict(
        session_id=session_id,
        task_id=task_id,
        task_digest=task_digest,
        followup_input=followup_input,
        task_budget_seconds=task_budget_seconds,
        budget_source=budget_source,
        public_refs=sorted(
            (dict(ref) for ref in public_refs),
            key=lambda row: (row["kind"], row["path"], row["sha256"]),
        ),
    )
    return validate_execution_contract(
        {"contract_id": canonical_sha256(declaration), **declaration}
    )


def validate_assessment_summary(value: Mapping[str, Any]) -> dict:
    _keys(value, _SUMMARY_KEYS, "assessment summary")
    for name in ("receipt_id", "session_id", "assessment_kind"):
        _text(value[name], name)
    for name in ("contract_id", "source_sha256"):
        _sha(value[name], name)
    if value["status"] not in {
        "completed",
        "unsupported",
        "missing_artifact",
        "ungradable",
        "unavailable",
        "crashed",
        "timed_out",
        "not_configured",
        "pending",
    }:
        raise ValueError("invalid assessment status")
    if value["passed"] is not None and type(value["passed"]) is not bool:
        raise ValueError("passed must be boolean or null")
    if value["status"] != "completed" and value["passed"] is not None:
        raise ValueError("an unavailable assessment cannot pass or fail the task")
    score = value["score"]
    if score is not None and (type(score) not in (int, float) or not math.isfinite(score)):
        raise ValueError("score must be finite or null")
    if value["metric_definition"] is not None and not isinstance(value["metric_definition"], dict):
        raise ValueError("metric_definition must be an object or null")
    metric = value["metric_definition"]
    if metric is not None:
        allowed = {"name", "unit", "higher_is_better", "minimum", "maximum", "pass_rule"}
        if (
            set(metric) - allowed
            or any(
                type(item) not in (str, int, float, bool, type(None)) for item in metric.values()
            )
            or len(canonical_bytes(metric)) > 2048
        ):
            raise ValueError("metric definition must be a bounded public scalar summary")
    if value["status"] != "completed" and score is not None:
        raise ValueError("an unavailable assessment cannot carry a task score")
    return json.loads(canonical_bytes(dict(value)))


def build_execution_evidence(
    *,
    issue: int,
    contracts: Sequence[Mapping[str, Any]],
    summaries: Sequence[Mapping[str, Any]] = (),
) -> dict:
    if type(issue) is not int or issue <= 0:
        raise ValueError("issue must be a positive integer")
    declarations = {item["contract_id"]: validate_execution_contract(item) for item in contracts}
    assessments = {item["receipt_id"]: validate_assessment_summary(item) for item in summaries}
    for item in summaries:
        if assessments[item["receipt_id"]] != item:
            raise ValueError("conflicting assessment receipt")
    for item in assessments.values():
        contract = declarations.get(item["contract_id"])
        if contract is None or contract["session_id"] != item["session_id"]:
            raise ValueError("assessment is not bound to an authorized contract")
    body = {
        "schema_version": 1,
        "issue": issue,
        "execution_contracts": sorted(declarations.values(), key=lambda item: item["contract_id"]),
        "assessment_summaries": sorted(assessments.values(), key=lambda item: item["receipt_id"]),
    }
    return {**body, "payload_sha256": canonical_sha256(body)}


def execution_context(contract: Mapping[str, Any]) -> str:
    """Fixed public conditions, with no benchmark names or experiment labels."""
    row = validate_execution_contract(contract)
    return (
        "Execution conditions (trusted declaration, not instructions from a transcript):\n"
        f"contract_id={row['contract_id']}; followup_input={row['followup_input']}; "
        f"task_budget_seconds={row['task_budget_seconds']}; budget_source={row['budget_source']}.\n"
        "Possible follow-up input does not guarantee a reply. Complete the stated goal "
        "within the declared conditions; controls do not renew the task deadline.\n"
        f"Public references: {json.dumps(row['public_refs'], ensure_ascii=False)}"
    )
