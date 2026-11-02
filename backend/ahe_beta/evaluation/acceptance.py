"""Keep original acceptance distinct from technical evidence (Spec-0083/T1)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .results import EXECUTION_CONTRACTS, GradingResult


def derive_acceptance_assessment(
    *, session: Mapping[str, Any], result: GradingResult | Mapping[str, Any]
) -> str:
    """Assess a completed original interaction; do not mutate Session.accept_validity."""
    outcome = session.get("user_outcome") or session
    trace = session.get("sim_trace") or {}
    direct = outcome.get("interaction_mode") == "direct" or "review_verdict" in outcome
    feedback = session.get("feedback") or {}
    if feedback:
        # Spec-0084/T1: no complaint/bug verdict is not an acceptance judgment.
        accepted = (feedback.get("task_assessment") or {}).get("status") == "fulfilled"
    elif direct:
        accepted = (
            outcome.get("review_verdict") == "accept"
            and outcome.get("review_status") == "completed"
        )
    else:
        accepted = outcome.get("end_reason", trace.get("end_reason")) == "accepted"
    if not accepted:
        return "not_applicable"
    if not feedback and direct:
        return "unverified_accept"
    if (
        session.get("status") in {"crashed", "timed_out", "invalid"}
        or (not feedback and trace.get("evaluation_status", "valid") != "valid")
        or trace.get("interaction_status", "completed") not in {"completed", "protocol_repaired"}
        or (not feedback and outcome.get("evaluation_status", "valid") != "valid")
    ):
        return "unverified_accept"
    if any(
        row.get("status") in {"timed_out", "crashed"}
        for row in session.get("request_outcomes", ())
        if isinstance(row, Mapping)
    ):
        return "false_accept"
    if outcome.get("status", "completed") != "completed":
        return "unverified_accept"
    row = result.to_dict() if isinstance(result, GradingResult) else result
    if row.get("status") != "completed" or row.get("passed") is None:
        return "unverified_accept"
    execution = row.get("execution") or {}
    if (
        execution.get("contract") not in EXECUTION_CONTRACTS
        or execution.get("verified") is not True
        or not isinstance(execution.get("image_digest"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", execution["image_digest"])
    ):
        return "unverified_accept"
    return "valid_accept" if row.get("passed") is True else "false_accept"
