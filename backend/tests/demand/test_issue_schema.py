# Spec-0025/T1 + Spec-0027/T1: platform-level issue schema unit tests — converged to canonical fields (USER-section template removed).
"""Tests issue_schema: each kind declares only canonical artifact fields (the scoping fields filled in by the triage/RFC agent);
validate rejects unknown kinds / missing required fields / empty values; render has a stable layout with placeholders for missing fields; the section parameter is backward compatible."""

from __future__ import annotations

import pytest

from ahe_beta.demand import issue_schema as sc


def test_bug_fields_are_normalized_only() -> None:
    keys = {f.key for f in sc.fields_of(kind="bug")}
    # only scoping/acceptance remain, no USER reproduction template
    assert keys == {"root_cause", "boundary", "acceptance"}
    # the original USER section has been removed
    assert "repro" not in keys and "expected" not in keys


def test_feature_fields_are_normalized_only() -> None:
    keys = {f.key for f in sc.fields_of(kind="feature")}
    assert keys == {"boundary", "deliverable", "acceptance"}
    assert "background" not in keys and "scenario" not in keys


def test_rfc_is_independent_kind() -> None:
    keys = {f.key for f in sc.fields_of(kind="rfc")}
    assert keys == {"problem", "root_cause", "related", "direction", "acceptance"}
    assert "rfc" in sc.kinds() and "rfc" not in sc.USER_KINDS  # RFCs are not filed by users


def test_validate_unknown_kind() -> None:
    errs = sc.validate(kind="nonsense", fields={})
    assert errs and "Unknown" in errs[0]


def test_validate_missing_required() -> None:
    errs = sc.validate(
        kind="bug", fields={"root_cause": "entry.py No budget awareness"}
    )  # missing boundary/acceptance
    joined = " ".join(errs)
    assert "boundary" in joined and "acceptance" in joined


def test_validate_empty_string_is_missing() -> None:
    errs = sc.validate(kind="bug", fields={"root_cause": "   ", "boundary": "b", "acceptance": "c"})
    assert any("root_cause" in e for e in errs)  # blank is treated as missing


def test_validate_optional_not_required() -> None:
    # chore's boundary is optional → passes with only acceptance filled in
    assert sc.validate(kind="chore", fields={"acceptance": "Run through successfully"}) == []
    # document has only acceptance and it is optional → passes even when empty
    assert sc.validate(kind="document", fields={}) == []


@pytest.mark.parametrize("fields", [None, [], "not an object", 7, True])
def test_validate_rejects_non_object_fields(fields) -> None:
    assert sc.validate(kind="document", fields=fields)


@pytest.mark.parametrize("key", ["Root cause area", "Root cause", "unexpected"])
def test_validate_rejects_unknown_keys_even_with_complete_required_fields(key) -> None:
    fields = {"root_cause": "cause", "boundary": "scope", "acceptance": "result", key: "extra"}
    assert sc.validate(kind="bug", fields=fields)


@pytest.mark.parametrize("value", [None, 0, False, [], {}])
def test_validate_rejects_non_string_optional_values(value) -> None:
    assert sc.validate(kind="document", fields={"acceptance": value})


def test_validate_preserves_unicode_content_with_english_keys() -> None:
    fields = {
        "root_cause": "Losing characters in Unicode responses 🌍",
        "boundary": "Only modify general harness behavior",
        "acceptance": "Verify café and emoji 🌍 remain intact",
    }
    assert sc.validate(kind="bug", fields=fields) == []
    body = sc.render(kind="bug", fields=fields)
    assert all(value in body for value in fields.values())


def test_validate_section_param_back_compat() -> None:
    # section degenerates to a single value: all fields belong to TRIAGE; the USER section has no fields to look up → always passes.
    fields = {"root_cause": "a", "boundary": "b", "acceptance": "c"}
    assert sc.validate(kind="bug", fields=fields, section=sc.TRIAGE) == []
    assert sc.validate(kind="bug", fields={}, section=sc.USER) == []  # no USER fields


def test_render_layout_stable() -> None:
    body = sc.render(
        kind="bug",
        fields={
            "root_cause": "entry.py No budget awareness",
            "boundary": "Only modify harness The body",
            "acceptance": "Deliver within budget for this type of task",
        },
    )
    assert "### Root cause\n\nentry.py No budget awareness" in body
    assert body.index("### Root cause") < body.index("### Boundary")  # declaration order is stable


def test_render_missing_field_placeholder() -> None:
    full = sc.render(kind="bug", fields={"root_cause": "a"})
    assert "### Acceptance criteria\n\n_(to be filled)_" in full  # placeholder for missing fields


@pytest.mark.parametrize(
    ("kind", "headings"),
    [
        ("feature", ["Boundary", "Deliverable", "Acceptance criteria"]),
        ("rfc", ["Problem", "Root cause", "Related issues", "Direction", "Acceptance criteria"]),
    ],
)
def test_render_uses_english_display_headings_for_machine_fields(kind, headings) -> None:
    fields = {field.key: f"Content for {field.key}" for field in sc.fields_of(kind=kind)}
    body = sc.render(kind=kind, fields=fields)
    assert [line for line in body.splitlines() if line.startswith("### ")] == [
        f"### {heading}" for heading in headings
    ]
    assert all(value in body for value in fields.values())


def test_render_unknown_kind_raises() -> None:
    try:
        sc.render(kind="nope", fields={})
        raise AssertionError("Should throw ValueError")
    except ValueError:
        pass


def test_divergent_and_gate_dropped_status_and_backlog() -> None:
    # Spec-0027/T1: candidates cannot be claimed; discarded is a terminal state; after promote they can enter the backlog.
    assert sc.triage_status([sc.DIVERGENT, "round-1"]) == sc.DIVERGENT
    assert sc.triage_status([sc.GATE_DROPPED, sc.DIVERGENT]) == sc.GATE_DROPPED
    assert not sc.is_backlog_by_labels([sc.DIVERGENT, "feature"])
    assert not sc.is_backlog_by_labels([sc.GATE_DROPPED])
    assert sc.is_backlog_by_labels([sc.TRIAGED, "feature"])  # after promote


# ---- Spec-0029/T1: three-plane projection + is_ready whitelist + covers/merged-into machine lines ----


def test_plane_new_labels() -> None:
    assert sc.plane([sc.REPORT, "bug", "round-1"]) == sc.REPORT
    assert sc.plane([sc.PROPOSAL, sc.FROM_TRIAGE, "bug", "P1"]) == sc.PROPOSAL
    assert sc.plane([sc.READY, "feature", "P0"]) == sc.READY
    assert sc.plane(["bug"]) is None  # no plane labels
    assert sc.plane([]) is None


def test_plane_openagents_handoff_is_ready() -> None:
    # Spec-0032/T3: openagents (the Owner admission handoff token) belongs to the same READY plane as ready;
    # after vigil stamps ready, both labels coexisting is still READY (idempotent).
    assert sc.plane([sc.OPENAGENTS, "bug", "P1"]) == sc.READY
    assert sc.plane([sc.OPENAGENTS, sc.READY, "bug"]) == sc.READY
    assert sc.is_ready(labels=[sc.OPENAGENTS], state="open")
    assert not sc.is_ready(labels=[sc.OPENAGENTS], state="closed")
    # same order as ready: the new plane label takes precedence over the terminal-state determination (the write side would remove the plane label when closing; this only locks in consistent precedence)
    assert sc.plane([sc.OPENAGENTS, sc.MERGED]) == sc.READY


def test_plane_terminal_labels_are_no_plane() -> None:
    # new terminal state + old terminal state: neither is in any plane
    for t in (sc.DECLINED, sc.MERGED, sc.REJECTED, sc.NEEDS_INFO, sc.GATE_DROPPED, sc.SUPERSEDED):
        assert sc.plane([t, "bug"]) is None
    # the old triaged+superseded combination is a terminal state (aligned with the old \"most decisive wins\" rule)
    assert sc.plane([sc.TRIAGED, sc.SUPERSEDED]) is None


def test_plane_old_label_mapping() -> None:
    # read-side mapping for old data: needs-triage→report, triaged|RFC→ready, divergent→proposal
    assert sc.plane([sc.NEEDS_TRIAGE, "bug"]) == sc.REPORT
    assert sc.plane([sc.TRIAGED, "bug", "P1"]) == sc.READY
    assert sc.plane([sc.RFC_LABEL]) == sc.READY
    assert sc.plane([sc.DIVERGENT, "feature"]) == sc.PROPOSAL


def test_is_ready_whitelist() -> None:
    assert sc.is_ready(labels=[sc.READY, "bug"], state="open")
    # closed items cannot be claimed
    assert not sc.is_ready(labels=[sc.READY, "bug"], state="closed")
    assert not sc.is_ready(labels=[sc.PROPOSAL, "bug"], state="open")  # proposals cannot be claimed
    assert not sc.is_ready(labels=[sc.REPORT], state="open")
    # old data is claimable after mapping
    assert sc.is_ready(labels=[sc.TRIAGED, "bug"], state="open")
    # fail-closed: unknown/newly added workflow labels are not claimable by default
    assert not sc.is_ready(labels=["some-future-label"], state="open")


def test_covers_line_roundtrip() -> None:
    line = sc.format_covers_line([12, 15])
    assert line == "covers: #12 #15"
    assert sc.parse_covers_line(f"Body text\n\n{line}\n") == [12, 15]
    assert sc.parse_covers_line("No machine generated lines") == []
    assert sc.format_covers_line([]) == ""  # empty list writes no line
    # with multiple entries, take the last one
    assert sc.parse_covers_line("covers: #1\nMiddle\ncovers: #2 #3") == [2, 3]


def test_merged_into_roundtrip() -> None:
    line = sc.format_merged_into(7)
    assert line == "merged-into: #7"
    assert sc.parse_merged_into(f"gate Decide to merge\n{line}") == 7
    assert sc.parse_merged_into("None") is None


def test_provenance_of() -> None:
    assert sc.provenance_of([sc.PROPOSAL, sc.FROM_TRIAGE]) == sc.FROM_TRIAGE
    assert sc.provenance_of([sc.PROPOSAL, sc.FROM_ARCHITECT]) == sc.FROM_ARCHITECT
    assert sc.provenance_of([sc.PROPOSAL, sc.FROM_DIVERGENT]) == sc.FROM_DIVERGENT
    assert sc.provenance_of(["bug"]) is None
