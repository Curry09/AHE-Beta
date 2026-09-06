"""Spec-0056/T3: persist terminal evidence without promoting subjective claims."""

import json

from auto_designer.designer.evidence_contract import _goal_acceptance
from auto_designer.designer.session_timeline import _project_sim_trace
from auto_designer.models import SimTrace, SimTurn


def test_terminal_fields_roundtrip_and_legacy_defaults() -> None:
    basis = {"mode": "delegated", "evidence_refs": ["turn-2"], "reason": "visible check"}
    audit = {"status": "ok", "action": "accept", "acceptance_basis": basis}
    turn = SimTurn.from_dict(
        {"turn": 3, "phase": "active", "action": "accept", "acceptance_basis": basis}
    )
    trace = SimTrace(persona_id="p", end_reason="accepted", turns=[turn], terminal_audit=audit)
    restored = SimTrace.from_dict(json.loads(json.dumps(trace.to_dict())))
    assert restored.terminal_audit == audit
    assert restored.turns[0].acceptance_basis == basis
    projected = _project_sim_trace(restored)
    assert projected["terminal_audit"] == audit
    assert projected["events"][0]["goal"]["acceptance_basis"] == basis
    legacy = SimTrace.from_dict(
        {"persona_id": "p", "end_reason": "accepted", "turns": [{"turn": 1, "phase": "active"}]}
    )
    assert legacy.terminal_audit == {}
    assert legacy.turns[0].acceptance_basis == {}


def test_l1_acceptance_basis_is_bounded_and_redacted_without_mutating_trace() -> None:
    basis = {
        "mode": "delegated",
        "alignment": "aligned",
        "reason": "/root/src/private/report.txt " + "evidence " * 400,
        "evidence_refs": ["/mnt/c/Users/private/check.txt"] * 40,
        "warnings": ["warning " * 80] * 40,
        "raw_output": "RAW_OUTPUT_SHOULD_STAY_PRIVATE",
    }
    trace = SimTrace(
        persona_id="p",
        end_reason="accepted",
        goal_acceptance={"status": "accepted", "terminal_audit": {"acceptance_basis": basis}},
    )
    snapshot = json.dumps(trace.to_dict())
    view = _goal_acceptance(trace, session_id="session-1")
    actual = view["terminal_audit"]["acceptance_basis"]
    assert actual["alignment"] == "aligned"
    assert len(actual["reason"]) <= 300
    assert len(actual["evidence_refs"]) == len(actual["warnings"]) == 24
    assert all(len(w) <= 100 for w in actual["warnings"])
    assert "raw_output" not in actual
    assert "/root/src/" not in json.dumps(view)
    assert "/mnt/c/" not in json.dumps(view)
    assert "objective_passed" not in view
    assert json.dumps(trace.to_dict()) == snapshot
