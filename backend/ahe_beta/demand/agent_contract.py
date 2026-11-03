# Spec-0027/T1: canonical source generator for agent structured output contracts.
"""Generate each producer's submit tool input_schema from issue_schema.SCHEMAS—contract and schema share one source,
change fields only in SCHEMAS.

nexau validates tool parameters at the tool call layer using jsonschema (archs/tool/tool.py: `jsonschema.validate(params,
input_schema)`, violations raise ToolValidationError→agent retries). Attach these schemas to the submit tool's
input_schema so the agent "output-equals-compliant"—no need for post-hoc second-pass LLM reordering or bracket-scanning parsing.

- `dispositions_input_schema()`: input schema for triage's submit_triage tool (dispositions array).
- `rfc_input_schema()`: input schema for architect's submit_rfcs tool (proposals array).

Both pull fields keys and optional kind/priority enums entirely from issue_schema; do not duplicate them here."""

from __future__ import annotations

from ahe_beta.demand.issue_schema import PRIORITIES, USER_KINDS, fields_of


def _fields_object_schema(keys: list[str]) -> dict:
    """Use canonical machine keys and string values, independent of display labels."""
    return {
        "type": "object",
        "properties": {key: {"type": "string"} for key in keys},
        "additionalProperties": False,
    }


def _triage_field_keys() -> list[str]:
    """Collect canonical keys across user kinds in declaration order, without duplicates."""
    keys: list[str] = []
    for kind in USER_KINDS:
        for f in fields_of(kind=kind):
            if f.key not in keys:
                keys.append(f.key)
    return keys


def dispositions_input_schema() -> dict:
    """Input schema for triage submit_triage tool.

    Each disposition: `issue`(int) + `disposition`(ternary enum, Spec-0029: duplicate retired, cross-proposal absorption to Architect)
    required; accept additionally requires `kind`(∈USER_KINDS), `priority`(∈P0-P3 recommended values), task-agnostic
    `proposal_title`, `fields`(keys ∈ normalized field union);
    reject/needs_info require `reason`. additionalProperties=false prevents self-invented fields like issue_number/status/flattened root_cause;
    enum blocks illegal priorities like "high". The tool exposes the union of canonical user-kind keys;
    the driver separately checks allowed fields and required values for the selected kind.
    """
    item = {
        "type": "object",
        "properties": {
            "issue": {"type": "integer"},
            "disposition": {
                "type": "string",
                "enum": ["accept", "reject", "needs_info"],
            },
            "kind": {"type": "string", "enum": list(USER_KINDS)},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "proposal_title": {"type": "string"},
            "fields": _fields_object_schema(_triage_field_keys()),
            "reason": {"type": "string"},
            "artifact": {
                "type": "object",
                "properties": {
                    "reported_problem": {"type": "string"},
                    "user_impact": {"type": "string"},
                    "scope_boundary": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "uncertainties": {"type": "array", "items": {"type": "string"}},
                    "implementation_target": {
                        "type": "string",
                        "enum": ["harness", "outside_harness", "uncertain"],
                    },
                },
                "required": [
                    "reported_problem",
                    "user_impact",
                    "scope_boundary",
                    "evidence",
                    "uncertainties",
                    "implementation_target",
                ],
                "additionalProperties": False,
            },
        },
        "required": ["issue", "disposition", "artifact"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "dispositions": {"type": "array", "minItems": 1, "maxItems": 1, "items": item}
        },
        "required": ["dispositions"],
        "additionalProperties": False,
    }


def rfc_input_schema() -> dict:
    """Input schema for architect submit_rfcs tool.

    Each proposal: `title`(str) + `fields`(RFC fields: problem/root cause/involved issues/direction/acceptance) required, optional
    `covers`(int array, identifies the open issues this structural proposal absorbs and closes). fields keys drawn from
    issue_schema's rfc declaration.
    """
    rfc_keys = [f.key for f in fields_of(kind="rfc")]
    item = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "fields": _fields_object_schema(rfc_keys),
            "covers": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["title", "fields"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"proposals": {"type": "array", "items": item}},
        "required": ["proposals"],
        "additionalProperties": False,
    }


def pm_input_schema() -> dict:
    """Product PM: infer product meaning/opportunity from user behaviour."""
    item = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "user_goal": {"type": "string"},
            "observed_behaviors": {"type": "array", "items": {"type": "string"}},
            "experience_tension": {"type": "string"},
            "product_opportunity": {"type": "string"},
            "desired_outcome": {"type": "string"},
            "evidence_sessions": {"type": "array", "items": {"type": "string"}},
            "related_proposals": {"type": "array", "items": {"type": "integer"}},
            "solution_level": {
                "type": "string",
                "enum": ["product_capability", "implementation_design"],
            },
            "abstraction_rationale": {"type": "string"},
        },
        "required": [
            "title",
            "user_goal",
            "observed_behaviors",
            "experience_tension",
            "product_opportunity",
            "desired_outcome",
            "evidence_sessions",
            "solution_level",
            "abstraction_rationale",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"proposals": {"type": "array", "items": item}},
        "required": ["proposals"],
        "additionalProperties": False,
    }


def synthesis_input_schema() -> dict:
    """Architect: explain relationships and common mechanisms across proposals."""
    item = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "source_proposals": {"type": "array", "items": {"type": "integer"}},
            "relationship": {"type": "string"},
            "common_tension": {"type": "string"},
            "structural_direction": {"type": "string"},
            "expected_leverage": {"type": "string"},
            "covers": {"type": "array", "items": {"type": "integer"}},
            "solution_level": {
                "type": "string",
                "enum": ["structural_mechanism", "implementation_design"],
            },
            "abstraction_rationale": {"type": "string"},
        },
        "required": [
            "title",
            "source_proposals",
            "relationship",
            "common_tension",
            "structural_direction",
            "expected_leverage",
            "solution_level",
            "abstraction_rationale",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"proposals": {"type": "array", "items": item}},
        "required": ["proposals"],
        "additionalProperties": False,
    }


def admission_input_schema() -> dict:
    """Owner handoff tool contract: package handoff only, do not review product design or implementation choices."""
    item = {
        "type": "object",
        "properties": {
            "issue": {"type": "integer"},
            "decision": {"type": "string", "enum": ["admit", "merge", "hold"]},
            "into": {"type": "integer"},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "reason": {"type": "string"},
            "handoff_summary": {"type": "string"},
            "preserved_capabilities": {"type": "array", "items": {"type": "string"}},
            "acceptance_groups": {"type": "array", "items": {"type": "string"}},
            "delivery_overlaps": {
                "type": "array",
                "items": {"type": "integer"},
                "uniqueItems": True,
            },
        },
        "required": [
            "issue",
            "decision",
            "handoff_summary",
            "preserved_capabilities",
            "acceptance_groups",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"decisions": {"type": "array", "items": item}},
        "required": ["decisions"],
        "additionalProperties": False,
    }
