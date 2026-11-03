# Spec-0027/T1: unit tests for the agent_contract contract generator — generates the submit
# tool's input_schema (triage dispositions / RFC proposals).
"""Validate the generated input_schema: correct structure, enums locked down, fields keys sourced from the same origin as SCHEMAS, extra fields rejected."""

from __future__ import annotations

from dataclasses import replace

import jsonschema
import pytest

from ahe_beta.demand import agent_contract as ac
from ahe_beta.demand import issue_schema as sc


@pytest.mark.parametrize("count", [0, 2])
def test_dispositions_schema_rejects_non_single_decisions(count) -> None:
    decision = {
        "issue": 1,
        "disposition": "needs_info",
        "artifact": {
            "reported_problem": "unclear",
            "user_impact": "unknown",
            "scope_boundary": "harness",
            "evidence": [],
            "uncertainties": ["missing evidence"],
            "implementation_target": "uncertain",
        },
    }
    schema = ac.dispositions_input_schema()
    jsonschema.validate({"dispositions": [decision]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"dispositions": [decision] * count}, schema)


def test_dispositions_schema_shape_and_enums() -> None:
    schema = ac.dispositions_input_schema()
    assert schema["required"] == ["dispositions"]
    assert schema["additionalProperties"] is False
    item = schema["properties"]["dispositions"]["items"]
    props = item["properties"]
    # Three disposition values (Spec-0029: duplicate retired, cross-proposal absorption assigned to the Architect), kind∈USER_KINDS, priority∈P0-P3
    assert props["disposition"]["enum"] == ["accept", "reject", "needs_info"]
    assert props["kind"]["enum"] == list(sc.USER_KINDS)
    assert props["priority"]["enum"] == list(sc.PRIORITIES)
    # Only contract fields allowed at the top level — no issue_number/status/flat scattered fields
    assert item["additionalProperties"] is False
    assert set(props) == {
        "issue",
        "disposition",
        "kind",
        "priority",
        "proposal_title",
        "fields",
        "reason",
        "artifact",
    }
    assert item["required"] == ["issue", "disposition", "artifact"]


def test_dispositions_fields_keys_are_union_from_schemas() -> None:
    """Legal keys of fields = the union of machine field keys across all user kinds (same source as SCHEMAS)."""
    schema = ac.dispositions_input_schema()
    field_keys = set(
        schema["properties"]["dispositions"]["items"]["properties"]["fields"]["properties"]
    )
    expected: set[str] = set()
    for k in sc.USER_KINDS:
        expected |= {f.key for f in sc.fields_of(kind=k)}
    assert field_keys == expected
    assert (
        "root_cause" in field_keys and "deliverable" in field_keys
    )  # Triage fields of bug/feature
    # fields must not contain extra keys
    assert (
        schema["properties"]["dispositions"]["items"]["properties"]["fields"][
            "additionalProperties"
        ]
        is False
    )


def test_rfc_schema_shape_and_fields() -> None:
    schema = ac.rfc_input_schema()
    assert schema["required"] == ["proposals"]
    item = schema["properties"]["proposals"]["items"]
    assert item["required"] == ["title", "fields"]
    assert item["additionalProperties"] is False
    field_keys = set(item["properties"]["fields"]["properties"])
    assert field_keys == {f.key for f in sc.fields_of(kind="rfc")}
    assert item["properties"]["covers"]["items"]["type"] == "integer"


def test_single_source_new_field_flows_through(monkeypatch) -> None:
    """Adding a machine field updates both generated triage contracts without a label alias."""
    monkeypatch.setitem(
        sc.SCHEMAS,
        "bug",
        (*sc.SCHEMAS["bug"], sc.Field("evidence_summary", "Evidence caption", sc.TRIAGE, False)),
    )
    disp_field_keys = set(
        ac.dispositions_input_schema()["properties"]["dispositions"]["items"]["properties"][
            "fields"
        ]["properties"]
    )
    for f in sc.fields_of(kind="bug"):
        assert f.key in disp_field_keys
    assert "evidence_summary" in disp_field_keys
    assert "Evidence caption" not in disp_field_keys
    legacy_keys = sc.output_contract_schema()["properties"]["dispositions"]["items"]["properties"][
        "fields"
    ]["properties"]
    assert "evidence_summary" in legacy_keys and "Evidence caption" not in legacy_keys


@pytest.mark.parametrize(
    ("factory", "collection", "fields"),
    [
        (
            ac.dispositions_input_schema,
            "dispositions",
            {
                "root_cause": "Cause 🌍",
                "boundary": "General capabilities",
                "acceptance": "Verifiable",
            },
        ),
        (
            sc.output_contract_schema,
            "dispositions",
            {
                "root_cause": "Cause 🌍",
                "boundary": "General capabilities",
                "acceptance": "Verifiable",
            },
        ),
        (
            ac.rfc_input_schema,
            "proposals",
            {
                "problem": "Problem 🌍",
                "root_cause": "Cause",
                "related": "#1 #2",
                "direction": "General mechanism",
                "acceptance": "Verifiable",
            },
        ),
    ],
)
def test_generated_field_contract_accepts_machine_keys_and_unicode(factory, collection, fields):
    schema = factory()["properties"][collection]["items"]["properties"]["fields"]
    jsonschema.validate(fields, schema)


@pytest.mark.parametrize(
    ("factory", "collection"),
    [
        (ac.dispositions_input_schema, "dispositions"),
        (sc.output_contract_schema, "dispositions"),
        (ac.rfc_input_schema, "proposals"),
    ],
)
@pytest.mark.parametrize(
    "label",
    [
        "Root cause area",
        "Root cause summary",
        "Acceptance",
        "Root cause",
        "Acceptance criteria",
    ],
)
def test_generated_field_contract_rejects_display_label_keys(factory, collection, label):
    schema = factory()["properties"][collection]["items"]["properties"]["fields"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({label: "content"}, schema)


def test_display_labels_can_change_without_changing_wire_keys(monkeypatch) -> None:
    for kind, fields in sc.SCHEMAS.items():
        monkeypatch.setitem(
            sc.SCHEMAS,
            kind,
            tuple(replace(field, label=f"Caption {kind} {i}") for i, field in enumerate(fields)),
        )

    expected_triage_keys = {
        field.key for kind in sc.USER_KINDS for field in sc.fields_of(kind=kind)
    }
    for factory in (ac.dispositions_input_schema, sc.output_contract_schema):
        schema = factory()["properties"]["dispositions"]["items"]["properties"]["fields"]
        assert set(schema["properties"]) == expected_triage_keys
        jsonschema.validate({"root_cause": "Cause: café 🌍"}, schema)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"Caption bug 0": "Cause: café 🌍"}, schema)

    rfc_schema = ac.rfc_input_schema()["properties"]["proposals"]["items"]["properties"]["fields"]
    assert set(rfc_schema["properties"]) == {field.key for field in sc.fields_of(kind="rfc")}
    jsonschema.validate({"problem": "Problem: naïve parsing 🌍"}, rfc_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"Caption rfc 0": "Problem: naïve parsing 🌍"}, rfc_schema)

    values = {
        "root_cause": "Cause",
        "boundary": "Boundary content",
        "acceptance": "Acceptance content",
    }
    assert sc.validate(kind="bug", fields=values) == []
    rendered = sc.render(kind="bug", fields=values)
    assert "### Caption bug 0\n\nCause" in rendered
    assert "### Caption bug 1\n\nBoundary content" in rendered
    assert "### Caption bug 2\n\nAcceptance content" in rendered
