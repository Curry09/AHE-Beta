from auto_designer.user.sim.goals import GoalLedger, GoalStatus, audit_goal_fields


def test_goal_updates_are_append_only_and_relax_requires_reason() -> None:
    ledger = GoalLedger.from_task("implement the feature")
    added = ledger.apply_updates(
        {
            "op": "add",
            "goal_id": "G1",
            "text": "show the changed file",
            "goal_kind": "request",
        },
        turn=1,
    )
    assert added == [{"op": "add", "goal_id": "G1"}]
    assert ledger.goals["G1"].status == GoalStatus.OPEN.value
    assert ledger.apply_updates(
        {"op": "relax", "goal_id": "G1", "done_if": "a summary is enough"}, turn=2
    ) == []
    assert ledger.goals["G1"].status == GoalStatus.OPEN.value
    assert ledger.apply_updates(
        {
            "op": "relax",
            "goal_id": "G1",
            "done_if": "a summary is enough",
            "reason": "I only need the high-level shape now",
        },
        turn=3,
    ) == [{"op": "relax", "goal_id": "G1", "reason": "I only need the high-level shape now"}]
    assert len(ledger.events) == 3  # initialize + add + relax


def test_baseline_can_be_revised_without_losing_origin() -> None:
    ledger = GoalLedger.from_task("make the command work")
    applied = ledger.apply_updates(
        {
            "op": "revise",
            "goal_id": "B0",
            "text": "make the command work for empty input and report errors clearly",
            "reason": "the first request was too broad after seeing the current behavior",
        },
        turn=1,
    )
    assert applied and applied[0]["op"] == "revise"
    assert ledger.goals["B0"].text.endswith("report errors clearly")
    assert ledger.goals["B0"].initial_text == "make the command work"
    revision = next(event for event in ledger.events if event.op == "revise")
    assert revision.before["text"] == "make the command work"
    assert revision.after["text"].endswith("report errors clearly")
    assert ledger.audit()["status"] == "ok"
    assert ledger.prompt_snapshot()["baseline_revision_count"] == 1


def test_goal_field_audit_warns_but_does_not_gate_unknown_annotations() -> None:
    ledger = GoalLedger.from_task("make the command work")
    audit = audit_goal_fields(
        ledger,
        goal_reading=[{"goal_id": "G99", "progress": "wat", "why": "?"}],
        target_goal_ids=["G99"],
        expected_progress="more evidence",
        goal_effect={"kind": "strange", "goal_ids": ["G99"]},
        goal_updates=[{"op": "revise", "goal_id": "B0"}],
    )
    assert audit["status"] == "warning"
    assert "target_unknown_goal:G99" in audit["warnings"]
    assert "goal_update_missing_reason:revise" in audit["warnings"]


def test_terminal_accept_reports_unresolved_goals_without_overriding_action() -> None:
    ledger = GoalLedger.from_task("implement the feature")
    result = ledger.terminal_check(
        "accept",
        {"kind": "close", "goal_ids": ["B0"], "evidence_refs": []},
    )
    assert result["status"] == "subjective_accept_unverified"
    assert result["unresolved_goals"] == ["B0"]
    assert result["effect"]["kind"] == "close"


def test_terminal_accept_is_normal_after_explicit_goal_completion() -> None:
    ledger = GoalLedger.from_task("implement the feature")
    ledger.apply_updates(
        {
            "op": "status",
            "goal_id": "B0",
            "status": "met",
            "evidence_refs": ["harness-reply-3"],
        },
        turn=3,
    )
    result = ledger.terminal_check("accept")
    assert result == {"status": "accepted", "unresolved_goals": []}
