"""设计师 get_session_timeline：使用事件投影（去仿真外壳，保留珍贵上帝视角标注）。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.designer.session_timeline import (
    bind_session_store,
    format_session_timeline,
    get_harness_beat,
    get_harness_step,
    get_session_timeline,
)
from auto_designer.models import (
    FeelingScore,
    IssueRef,
    Persona,
    PersonaCallTrace,
    SeedScenario,
    Session,
    SimTrace,
    SimTurn,
    Transcript,
)
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.goals import GoalLedger, audit_goal_fields


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _session_rich(*, issue_n: int | None = 7) -> Session:
    turns = [
        SimTurn(
            turn=1,
            phase="opening",
            action_space=["send_message"],
            perceive="Nothing yet; starting the DST task.",
            verdict="unsure",
            action="send_message",
            message="please fix DST",
            executor="harness",
            channel="emit",
            patience=5,
            trust="skeptical",
            harness_output="",
            utterance_id="u1",
            delivery="open",
            persona_trace=[
                PersonaCallTrace(
                    role="main_act",
                    system="MUST NOT LEAK SYSTEM",
                    user="MUST NOT LEAK USER",
                    raw="{}",
                    parsed={"action": "send_message", "message": "please fix DST"},
                )
            ],
        ),
        SimTurn(
            turn=2,
            phase="waiting",
            action_space=["keep_waiting", "send_message", "interrupt", "give_up"],
            perceive=(
                "[on_track|I want a status peek→keep_waiting] Still grepping; I'd peek "
                "the terminal myself if I could."
            ),
            verdict="stuck",
            action="keep_waiting",
            message="",
            executor="persona_local",
            channel="silent",
            patience=3,
            trust="skeptical",
            harness_output="",
            harness_steps=[
                {"kind": "tool", "text": "run_shell: rg cssPlugin"},
                {"kind": "tool_result", "text": "huge stdout " * 50},
            ],
            persona_trace=[
                PersonaCallTrace(
                    role="waiting_judge",
                    system="NO",
                    user="NO",
                    raw="{}",
                    parsed={
                        "perceive": "still grepping",
                        "judgment": "on_track",
                    },
                ),
                PersonaCallTrace(
                    role="waiting_intent",
                    system="NO",
                    user="NO",
                    raw="{}",
                    parsed={
                        "intent": "I want a status peek / open another terminal myself",
                    },
                ),
                PersonaCallTrace(
                    role="waiting_act",
                    system="NO",
                    user="NO",
                    raw="{}",
                    parsed={"action": "keep_waiting", "message": "", "gap": True},
                    steps=[{"kind": "assistant", "text": "SHOULD NOT LEAK RAW STEP"}],
                ),
            ],
        ),
        SimTurn(
            turn=2,
            phase="waiting",
            action_space=["keep_waiting", "send_message", "interrupt", "give_up"],
            perceive="[unclear|stop full suite→send_message] Don't run all tests.",
            verdict="stuck",
            action="send_message",
            message="stop, don't run the full suite",
            executor="harness",
            channel="emit",
            patience=3,
            trust="skeptical",
            harness_output="",
            utterance_id="u2",
            delivery="queued",
            queued_behind="u1",
            persona_trace=[],
        ),
        SimTurn(
            turn=3,
            phase="active",
            action_space=["accept", "give_up", "send_message"],
            perceive="Looks done; I checked it privately.",
            verdict="satisfied",
            action="accept",
            message="Looks good.",
            executor="persona_local",
            channel="emit",
            patience=2,
            trust="skeptical",
            harness_output="Fixed in core.py and tests passed.",
            answers_utterance_id="u1",
            answers_said="please fix DST",
            persona_trace=[
                PersonaCallTrace(
                    role="main_judge",
                    system="NO",
                    user="NO",
                    raw="{}",
                    parsed={
                        "perceive": "I ran pytest privately; it passed",
                        "verdict": "satisfied",
                    },
                    steps=[
                        {
                            "kind": "tool",
                            "text": 'run_shell {"cmd": "pytest -q"}',
                        },
                        {"kind": "tool_result", "text": "1 passed"},
                    ],
                )
            ],
        ),
        SimTurn(
            turn=4,
            phase="active",
            action_space=["send_message", "give_up"],
            perceive="It burned the budget again.",
            verdict="stuck",
            action="send_message",
            message="Please continue from the diff.",
            executor="harness",
            channel="emit",
            patience=1,
            trust="skeptical",
            harness_output="\n\n[Error: Maximum iteration limit reached.]",
            harness_steps=[
                {"kind": "tool", "text": "run_shell: ls"},
                {"kind": "tool_result", "text": "a.py\nb.py\n" + ("x" * 400)},
                {"kind": "tool", "text": "run_shell: pytest -q"},
                {"kind": "tool_result", "text": "still running forever " * 40},
            ],
            utterance_id="u3",
            delivery="open",
            persona_trace=[
                PersonaCallTrace(
                    role="main_act",
                    system="NO",
                    user="NO",
                    raw="{}",
                    parsed={
                        "action": "send_message",
                        "message": "Please continue from the diff.",
                    },
                )
            ],
        ),
    ]
    refs = [IssueRef(number=issue_n, url=f"fake://{issue_n}", state="open")] if issue_n else []
    return Session(
        persona=_persona(),
        scenario=SeedScenario(description="Fix DST"),
        transcript=Transcript(turns=[]),
        feeling=FeelingScore(score=1, reason="waited too long then crash"),
        issue_refs=refs,
        sim_trace=SimTrace(
            persona_id="SR-005",
            end_reason="issue_filed",
            turns=turns,
            signals=["WAIT_GAP: intent=peek action=keep_waiting"],
            persona_tail=[
                PersonaCallTrace(
                    role="file_issue",
                    system="NO",
                    user="NO",
                    raw="{}",
                    parsed={"issue": "I waited forever then it crashed"},
                ),
                PersonaCallTrace(
                    role="rate",
                    system="NO",
                    user="NO",
                    raw="{}",
                    parsed={"score": 1, "reason": "waited too long then crash"},
                ),
            ],
        ),
    )


def test_projection_keeps_precious_godview_drops_sim_machinery(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sess = _session_rich()
    store.save(sess)
    data = json.loads(format_session_timeline(store.load(sess.session_id)))
    blob = json.dumps(data)

    assert "MUST NOT LEAK" not in blob
    assert "SHOULD NOT LEAK" not in blob
    assert "SR-005" not in blob
    assert "fake://" not in blob
    assert "waiting_judge" not in blob
    assert "action_space" not in blob or "capability_gap" in blob
    assert "patience" not in blob
    assert data["issues"][0]["number"] == 7
    assert "url" not in data["issues"][0]

    events = data["timeline"]["events"]
    wait = next(e for e in events if e.get("when") == "during_wait")
    assert wait["wanted"].startswith("I want a status peek")
    assert wait["did"] == "keep_waiting"
    assert wait["process_read"] == "on_track"
    assert wait["thought"].startswith("Still grepping")
    assert "[on_track|" not in wait["thought"]
    assert wait["saw_activity"] and "rg cssPlugin" in wait["saw_activity"][0]
    assert "huge stdout" not in blob
    # gap：不对齐才带 available
    assert wait["capability_gap"]["available"] == [
        "keep_waiting",
        "send_message",
        "interrupt",
        "give_up",
    ]

    # Spec-0024/T6：插话 queued 在 open 之后；随后 heard 仍 answers 指向 begin 那条
    opening = next(
        e for e in events if e.get("did") == "send_message" and e.get("utterance") == "u1"
    )
    assert opening["delivery"] == "open"
    queued = next(
        e for e in events if e.get("did") == "send_message" and e.get("utterance") == "u2"
    )
    assert queued["delivery"] == "queued" and queued["queued_behind"] == "u1"

    accepted = next(e for e in events if e.get("did") == "accept")
    assert accepted["private_check"]
    assert any("pytest" in c["detail"] for c in accepted["private_check"])
    assert accepted["answers"] == "u1"
    assert accepted["answers_said"] == "please fix DST"
    assert accepted["answers"] != queued["utterance"]

    assert any(e.get("did") == "file_issue" for e in events)
    assert any(e.get("did") == "rate_experience" for e in events)


def test_tool_by_issue_and_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sess = _session_rich(issue_n=42)
    store.save(sess)
    with bind_session_store(store):
        by_issue = get_session_timeline(issue_number=42)
        by_sid = get_session_timeline(session_id=sess.session_id)
    assert by_issue["ok"] and by_sid["ok"]
    payload = json.loads(by_issue["timeline"])
    assert payload["timeline"]["events"][0]["did"] == "send_message"
    with bind_session_store(store):
        assert get_session_timeline(issue_number=999)["ok"] is False


def test_harness_beat_drilldown_clips_and_classifies(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sess = _session_rich(issue_n=9)
    store.save(sess)
    with bind_session_store(store):
        miss = get_harness_beat(turn=99, session_id=sess.session_id)
        assert miss["ok"] is False
        by_issue = get_harness_beat(turn=4, issue_number=9)
    assert by_issue["ok"] is True
    assert by_issue["stop_kind"] == "max_iterations"
    assert "Maximum iteration" in by_issue["heard"]
    assert by_issue["user_did"] == "send_message"
    assert by_issue["n_steps_raw"] == 4
    assert by_issue["n_steps_returned"] == 4
    # tool_result 截断，不全量 stdout
    blob = json.dumps(by_issue)
    assert "xxxx" not in blob or by_issue["steps"][1].get("truncated") is True
    assert any(s.get("truncated") for s in by_issue["steps"] if s["kind"] == "tool_result")
    assert "MUST NOT LEAK" not in blob


def test_harness_beat_prefers_turn_with_harness_activity(tmp_path: Path) -> None:
    """同 turn 号：优先返回带 harness_steps/output 的拍。"""
    store = SessionStore(tmp_path)
    sess = _session_rich()
    store.save(sess)
    with bind_session_store(store):
        beat = get_harness_beat(turn=2, session_id=sess.session_id)
    assert beat["ok"]
    assert beat["n_steps_raw"] >= 2
    assert any("rg cssPlugin" in s["text"] for s in beat["steps"])
    results = [s for s in beat["steps"] if s["kind"] == "tool_result"]
    assert results and results[0].get("truncated") is True
    assert len(results[0]["text"]) <= 281
    assert "MUST NOT LEAK" not in json.dumps(beat)


def test_timeline_and_drilldown_include_goal_revision_and_field_audit(tmp_path: Path) -> None:
    ledger = GoalLedger.from_task("make the command work")
    ledger.apply_updates(
        {
            "op": "revise",
            "goal_id": "B0",
            "text": "make the command work for empty input",
            "reason": "the observed failure narrowed the original request",
        },
        turn=1,
    )
    field_audit = audit_goal_fields(
        ledger,
        goal_reading=[{"goal_id": "B0", "progress": "advancing", "why": "focused fix"}],
        target_goal_ids=["B0"],
        expected_progress="empty input is handled",
        goal_effect={"kind": "advance", "goal_ids": ["B0"]},
    )
    sess = _session_rich(issue_n=13)
    sess.sim_trace.goal_ledger = ledger.snapshot()
    sess.sim_trace.goal_audit = ledger.audit()
    sess.sim_trace.turns[4].goal_before = GoalLedger.from_task("make the command work").snapshot()
    sess.sim_trace.turns[4].goal_reading = [
        {"goal_id": "B0", "progress": "advancing", "why": "focused fix"}
    ]
    sess.sim_trace.turns[4].target_goal_ids = ["B0"]
    sess.sim_trace.turns[4].expected_progress = "empty input is handled"
    sess.sim_trace.turns[4].goal_after = ledger.snapshot()
    sess.sim_trace.turns[4].goal_effect = {"kind": "advance", "goal_ids": ["B0"]}
    sess.sim_trace.turns[4].goal_field_audit = field_audit
    store = SessionStore(tmp_path)
    store.save(sess)
    payload = json.loads(format_session_timeline(store.load(sess.session_id)))
    timeline = payload["timeline"]
    assert timeline["goal_ledger"]["baseline_revision_count"] == 1
    revision = next(e for e in timeline["goal_ledger"]["events"] if e["op"] == "revise")
    assert revision["before"]["text"] == "make the command work"
    assert revision["after"]["text"].endswith("empty input")
    turn4 = next(event for event in timeline["events"] if event.get("t") == 4)
    assert turn4["goal"]["targets"] == ["B0"]
    assert turn4["goal"]["field_audit"]["status"] == "ok"
    with bind_session_store(store):
        beat = get_harness_beat(turn=4, session_id=sess.session_id)
        step = get_harness_step(turn=4, step_i=0, session_id=sess.session_id)
    assert beat["goal"]["targets"] == ["B0"]
    assert step["goal"]["after"]["goals"][0]["text"].endswith("empty input")


def test_harness_step_expands_clipped_body(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sess = _session_rich(issue_n=11)
    store.save(sess)
    with bind_session_store(store):
        beat = get_harness_beat(turn=4, issue_number=11)
        step = get_harness_step(turn=4, step_i=1, issue_number=11)
        miss = get_harness_step(turn=4, step_i=99, session_id=sess.session_id)
    assert beat["ok"] and any(s.get("truncated") for s in beat["steps"])
    assert step["ok"]
    assert step["kind"] == "tool_result"
    assert step["n_chars_raw"] > 280
    assert "xxxx" in step["text"] or "a.py" in step["text"]
    assert miss["ok"] is False
