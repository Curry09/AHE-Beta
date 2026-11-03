"""Spec-0043: task-independent cognitive contracts for demand-side roles.

Only mechanically provable boundaries live here.  We deliberately do not scan
prose for banned words: vocabulary is not a reliable proxy for role quality.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractViolation:
    code: str
    detail: str


def validate_triage(item: dict, *, report_number: int) -> list[ContractViolation]:
    if item.get("issue") != report_number:
        return [ContractViolation("foreign-source", "disposition is not for the isolated report")]
    if item.get("disposition") == "accept" and not isinstance(item.get("artifact"), dict):
        return [
            ContractViolation("missing-artifact", "accepted report needs factual triage artifact")
        ]
    if (
        item.get("disposition") == "accept"
        and item.get("artifact", {}).get("implementation_target") != "harness"
    ):
        return [
            ContractViolation(
                "out-of-product-scope", "accepted proposal must target harness behaviour"
            )
        ]
    return []


def validate_pm(item: dict, *, known_sessions: set[str]) -> list[ContractViolation]:
    if item.get("solution_level") != "product_capability":
        return [
            ContractViolation(
                "wrong-abstraction", "PM output must stay at product capability level"
            )
        ]
    evidence = item.get("evidence_sessions")
    if not isinstance(evidence, list) or not evidence:
        return [ContractViolation("missing-evidence", "product insight needs session evidence")]
    if any(not isinstance(session_id, str) or not session_id for session_id in evidence):
        return [ContractViolation("invalid-evidence", "session evidence must use non-empty ids")]
    foreign = [sid for sid in evidence if sid not in known_sessions]
    if foreign:
        return [ContractViolation("foreign-source", f"unknown sessions: {foreign}")]
    return []


def validate_synthesis(item: dict, *, visible_proposals: set[int]) -> list[ContractViolation]:
    if item.get("solution_level") != "structural_mechanism":
        return [
            ContractViolation(
                "wrong-abstraction", "synthesis must stay at structural mechanism level"
            )
        ]
    sources = item.get("source_proposals")
    if not isinstance(sources, list) or len(sources) < 2:
        return [ContractViolation("not-cross-proposal", "synthesis needs at least two proposals")]
    if any(not isinstance(number, int) or isinstance(number, bool) for number in sources):
        return [
            ContractViolation("invalid-source", "proposal sources must use integer issue numbers")
        ]
    if len(set(sources)) < 2:
        return [ContractViolation("not-cross-proposal", "synthesis needs at least two proposals")]
    foreign = [number for number in sources if number not in visible_proposals]
    if foreign:
        return [ContractViolation("foreign-source", f"unknown proposals: {foreign}")]
    return []


def validate_owner(item: dict, *, review_batch: set[int]) -> list[ContractViolation]:
    if item.get("issue") not in review_batch:
        return [ContractViolation("decision-out-of-batch", "decision is outside review batch")]
    if item.get("decision") == "merge" and not isinstance(item.get("into"), int):
        return [ContractViolation("missing-merge-target", "merge requires an integer target")]
    if item.get("decision") == "hold" and not str(item.get("reason", "")).strip():
        return [ContractViolation("missing-hold-gap", "hold must name the missing handoff input")]
    return []


def render_pm_artifact(item: dict) -> str:
    behaviors = "\n".join(f"- {x}" for x in item["observed_behaviors"])
    sessions = ", ".join(item["evidence_sessions"])
    related = ", ".join(f"#{x}" for x in item.get("related_proposals", [])) or "(none)"
    return (
        f"## User goal\n\n{item['user_goal']}\n\n"
        f"## Observed behaviors\n\n{behaviors}\n\n"
        f"## Experience tension\n\n{item['experience_tension']}\n\n"
        f"## Product opportunity\n\n{item['product_opportunity']}\n\n"
        f"## Desired outcome\n\n{item['desired_outcome']}\n\n"
        f"## Evidence\n\nsession_id: {sessions}\n\nRelated proposals: {related}"
    )


def render_synthesis_artifact(item: dict) -> str:
    sources = ", ".join(f"#{x}" for x in item["source_proposals"])
    return (
        f"## Source proposals\n\n{sources}\n\n"
        f"## Structural relationship\n\n{item['relationship']}\n\n"
        f"## Common tension\n\n{item['common_tension']}\n\n"
        f"## Structural direction\n\n{item['structural_direction']}\n\n"
        f"## Expected leverage\n\n{item['expected_leverage']}"
    )
