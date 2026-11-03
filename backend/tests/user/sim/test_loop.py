"""spec-0005/T5: conversation main loop engine (purely subjective, two user experience paths, capability branching)."""

from __future__ import annotations

from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    TimeTemperament,
    finalize_persona,
)
from ahe_beta.user.sim.feeling import FeelingScore
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.loop import (
    MAX_TURNS,
    SessionResult,
    _record_private_evidence,
    route,
    run_session,
)
from ahe_beta.user.sim.persona_client import PersonaProtocolError, ScriptedPersonaClient
from ahe_beta.user.sim.state import State, init_state


def _persona(
    d1: D1Eval,
    d43: D43Correct,
    pid: str = "P",
    *,
    tempo: TimeTemperament = TimeTemperament.STEADY,
) -> Persona:
    return finalize_persona(
        Persona(
            persona_id=pid,
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=d43,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=tempo,
        )
    )


TASK = "Add to_user_tz(dt, tz_name); handle DST. We use Asia/Shanghai and America/New_York."


class _StubClient:
    """Controlled client: execute actions script-wise per round; judge/intent do not consume actions during isomorphic triple hops."""

    def __init__(self, actions: list[str], verdict: str = "unsure", rating: dict | None = None):
        self._actions = actions
        self._i = 0
        self._verdict = verdict
        self._rating = rating if rating is not None else {"score": 3, "reason": "ok"}

    def respond(self, system: str, user: str) -> dict:
        if "<rate_experience>" in user:
            return self._rating
        if "<file_issue>" in user:
            return {"issue": "stub issue"}
        if "<main_judge>" in user or "<main_judge_intent>" in user:
            out: dict = {
                "perceive": "",
                "verdict": self._verdict,
                "intent": "do the scripted next step",
            }
            if "SIZE UP THIS TASK" in user or "task_load" in user.lower():
                out["task_load"] = "normal"
            return out
        if "<main_intent>" in user:
            return {
                "intent": "do the scripted next step",
                "needs_final_check": False,
                "check_goal": "",
            }
        if "<main_act>" in user or "<main_decide>" in user:
            a = self._actions[self._i] if self._i < len(self._actions) else self._actions[-1]
            self._i += 1
            return {
                "perceive": "",
                "verdict": self._verdict,
                "intent": "do the scripted next step",
                "action": a,
                "message": "x",
                "gap": False,
            }
        # Compatible with legacy single-shot decide / other prompts
        a = self._actions[self._i] if self._i < len(self._actions) else self._actions[-1]
        self._i += 1
        return {"perceive": "", "verdict": self._verdict, "action": a, "message": "x"}


class _RecordingClient(_StubClient):
    """Record user prompt received each round, used to assert content fed to LLM (perceive whether unchanged)."""

    def __init__(self, actions: list[str], verdict: str = "unsure") -> None:
        super().__init__(actions, verdict=verdict)
        self.seen: list[str] = []

    def respond(self, system: str, user: str) -> dict:
        if "<rate_experience>" not in user:
            self.seen.append(user)
        return super().respond(system, user)


class _ClassifyingClient(_RecordingClient):
    """When act returns free, simulate post-processing categorization of same persona; record allowed ids visible only here."""

    def __init__(self, actions: list[str], verdict: str = "unsure") -> None:
        super().__init__(actions, verdict=verdict)
        self.classifications: list[tuple[dict, list[str]]] = []

    def classify_action(self, system: str, ret: dict, space: list[str]) -> str:  # noqa: ARG002
        self.classifications.append((dict(ret), list(space)))
        return space[0] if space else "free"


class _FinalCheckClient(_RecordingClient):
    def __init__(self, outcome: dict | Exception) -> None:
        super().__init__(["send_message", "accept"], verdict="satisfied")
        self._intent_calls = 0
        self._outcome = outcome

    def respond(self, system: str, user: str) -> dict:
        if "<main_intent>" in user:
            self.seen.append(user)
            self._intent_calls += 1
            if self._intent_calls == 2:
                return {
                    "intent": "verify the changed file once before accepting",
                    "needs_final_check": True,
                    "check_goal": "confirm the requested implementation is present",
                }
            return {"intent": "start", "needs_final_check": False, "check_goal": ""}
        if "<main_final_check>" in user:
            self.seen.append(user)
            if isinstance(self._outcome, Exception):
                raise self._outcome
            return self._outcome
        if "<main_rejudge>" in user:
            self.seen.append(user)
            return {"perceive": "the available evidence is sufficient", "verdict": "satisfied"}
        if "<main_reintent>" in user:
            self.seen.append(user)
            return {"intent": "accept now", "needs_final_check": False, "check_goal": ""}
        return super().respond(system, user)


def test_harness_text_fed_raw_without_perception_filter() -> None:
    # Low-capability tier (prototype uses perceive_filter to erase source lines); after filter removal, source should be fed to LLM unchanged.
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _RecordingClient(["send_message", "send_message", "accept"], verdict="unsure")
    run_session(p, client, ScriptedHarness(), TASK)
    after_harness = next(u for u in client.seen if "pytz.localize_safe(dt, tz)" in u)
    # No-filter placeholder string
    assert "you don't read the diff line by line" not in after_harness


def test_main_decide_is_judge_intent_act_isomorphic() -> None:
    """Main loop defaults to three: judge → intent → act; perceive carries [verdict|intent→action]."""
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _RecordingClient(["send_message", "accept"], verdict="satisfied")
    res = run_session(p, client, ScriptedHarness(), TASK)
    tags = []
    for u in client.seen:
        if "<main_judge>" in u:
            tags.append("judge")
        elif "<main_intent>" in u:
            tags.append("intent")
        elif "<main_act>" in u:
            tags.append("act")
    # At least two main decision rounds × three hops
    assert tags.count("judge") >= 2
    assert tags.count("intent") >= 2
    assert tags.count("act") >= 2
    judge_prompts = [u for u in client.seen if "<main_judge>" in u]
    intent_prompts = [u for u in client.seen if "<main_intent>" in u]
    act_prompts = [u for u in client.seen if "<main_act>" in u]
    assert all("<action_space>" not in u for u in judge_prompts)
    assert all("<action_space>" not in u for u in intent_prompts)
    assert all("<action_space>" in u for u in act_prompts)
    active = [t for t in res.turns if t.phase in ("opening", "active")]
    assert any("|" in t.perceive and "→" in t.perceive for t in active)


def test_goal_layer_guides_same_turn_intent_without_becoming_a_gate() -> None:
    class _GoalLayerClient(_StubClient):
        def __init__(self) -> None:
            super().__init__(["send_message", "accept"], verdict="unsure")
            self.goal_added = False
            self.seen: list[str] = []

        def respond(self, system: str, user: str) -> dict:  # noqa: ARG002
            self.seen.append(user)
            if "<main_judge>" in user:
                out = {"perceive": "only a diagnosis is visible", "verdict": "unsure"}
                if not self.goal_added:
                    self.goal_added = True
                    out["goal_update"] = [
                        {
                            "op": "add",
                            "goal_id": "G1",
                            "text": "show the actual implementation and regression test",
                            "goal_kind": "request",
                        }
                    ]
                out["goal_reading"] = [
                    {"goal_id": "B0", "progress": "blocked", "why": "diagnosis only"}
                ]
                return out
            if "<main_intent>" in user:
                # The judge update must already be visible in the same turn.
                assert '"goal_id": "G1"' in user
                return {
                    "intent": "ask for the implementation and regression test",
                    "needs_final_check": False,
                    "check_goal": "",
                    "target_goal_ids": ["G1"],
                    "expected_progress": "receive the changed file and test result",
                }
            if "<main_act>" in user:
                assert '"target_goal_ids": ["G1"]' in user
                action = "send_message" if self._i == 0 else "accept"
                self._i += 1
                return {
                    "action": action,
                    "message": "please implement it" if action == "send_message" else "",
                    "goal_effect": {
                        "kind": "advance" if action == "send_message" else "close",
                        "goal_ids": ["G1"],
                    },
                }
            return super().respond(system, user)

    client = _GoalLayerClient()
    res = run_session(
        _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK), client, ScriptedHarness(), TASK
    )

    assert res.turns[0].goal_reading == [
        {"goal_id": "B0", "progress": "blocked", "why": "diagnosis only"}
    ]
    assert res.turns[0].target_goal_ids == ["G1"]
    assert any(goal["goal_id"] == "G1" for goal in res.turns[0].goal_after["goals"])
    # The ledger reports the unresolved claim, but the user's accept action is not rejected.
    assert res.end_reason == "accepted"
    assert res.goal_acceptance["status"] == "subjective_accept_unverified"
    g1 = next(goal for goal in res.goal_ledger["goals"] if goal["goal_id"] == "G1")
    assert g1["status"] == "met"
    assert res.terminal_audit["committed_goal_ids"] == ["G1"]


def test_baseline_revision_is_visible_to_same_turn_act_and_persisted() -> None:
    class _BaselineRevisionClient(_StubClient):
        def __init__(self) -> None:
            super().__init__(["accept"], verdict="satisfied")

        def respond(self, system: str, user: str) -> dict:  # noqa: ARG002
            if "<main_judge>" in user:
                return {
                    "perceive": "the request needs a narrower, concrete scope",
                    "verdict": "unsure",
                    "goal_reading": [
                        {"goal_id": "B0", "progress": "unclear", "why": "scope is too broad"}
                    ],
                    "goal_update": [
                        {
                            "op": "revise",
                            "goal_id": "B0",
                            "text": "implement the smallest working change and show its test",
                            "reason": "narrowed scope after inspecting the starting request",
                        }
                    ],
                }
            if "<main_intent>" in user:
                assert "implement the smallest working change" in user
                return {
                    "intent": "accept the narrowed outcome",
                    "needs_final_check": False,
                    "check_goal": "",
                    "target_goal_ids": ["B0"],
                    "expected_progress": "the narrowed change and its test are shown",
                }
            if "<main_act>" in user:
                action = "send_message" if self._i == 0 else "accept"
                self._i += 1
                return {
                    "action": action,
                    "message": "narrow the request" if action == "send_message" else "",
                    "target_goal_ids": ["B0"],
                    "goal_effect": {
                        "kind": "advance" if action == "send_message" else "close",
                        "goal_ids": ["B0"],
                    },
                }
            return super().respond(system, user)

    res = run_session(
        _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK),
        _BaselineRevisionClient(),
        ScriptedHarness(),
        TASK,
    )
    baseline = next(goal for goal in res.goal_ledger["goals"] if goal["goal_id"] == "B0")
    assert baseline["text"].startswith("implement the smallest working change")
    assert baseline["initial_text"] == TASK
    revision = next(event for event in res.goal_ledger["events"] if event["op"] == "revise")
    assert revision["before"]["version"] == 1
    assert revision["after"]["version"] == 2
    assert res.turns[0].goal_field_audit["status"] == "ok"


def test_accept_without_message_finishes_without_fake_harness_utterance() -> None:
    class _NoTerminalMessageClient(_StubClient):
        def respond(self, system: str, user: str) -> dict:
            out = super().respond(system, user)
            if "<main_act>" in user and out.get("action") == "accept":
                out.pop("message", None)
                out.pop("gap", None)
            return out

    res = run_session(
        _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK),
        _NoTerminalMessageClient(["send_message", "accept"], verdict="satisfied"),
        ScriptedHarness(),
        TASK,
    )
    assert res.end_reason == "accepted"
    assert res.interaction_status == "completed"
    terminal = res.turns[-1]
    assert terminal.action == "accept"
    assert terminal.message == ""
    assert terminal.utterance_id == ""


def test_active_final_check_converges_through_rejudge_and_reintent() -> None:
    """After one final check, can only rejudge → reintent → act; cannot backtrack to investigate again."""
    client = _FinalCheckClient(
        {"perceive": "the implementation is present", "check_status": "completed"}
    )
    res = run_session(_persona(D1Eval.EXPERT, D43Correct.FEEDBACK), client, ScriptedHarness(), TASK)

    assert res.end_reason == "accepted"
    tags = [
        tag
        for user in client.seen
        for tag in ("main_final_check", "main_rejudge", "main_reintent", "main_act")
        if f"<{tag}>" in user
    ]
    assert tags[-4:] == ["main_final_check", "main_rejudge", "main_reintent", "main_act"]
    assert tags.count("main_final_check") == 1


def test_failed_or_exhausted_final_check_still_forces_rejudge() -> None:
    outcomes: list[dict | Exception] = [
        {"perceive": "the command failed", "check_status": "failed"},
        {"perceive": "no private tools", "check_status": "unavailable"},
        PersonaProtocolError("main_final_check", "tool_budget_exhausted", attempts=4),
    ]
    for outcome in outcomes:
        client = _FinalCheckClient(outcome)
        res = run_session(
            _persona(D1Eval.EXPERT, D43Correct.FEEDBACK), client, ScriptedHarness(), TASK
        )
        assert res.end_reason == "accepted"
        tags = "\n".join(client.seen)
        assert tags.count("<main_final_check>") == 1
        assert "<main_rejudge>" in tags and "<main_reintent>" in tags


def test_protocol_failure_is_evaluator_invalid_not_accept() -> None:
    class _BrokenActClient(_StubClient):
        def respond(self, system: str, user: str) -> dict:
            if "<main_act>" in user:
                raise PersonaProtocolError("main_act", "tool_not_allowed_in_stage", attempts=2)
            return super().respond(system, user)

    res = run_session(
        _persona(D1Eval.EXPERT, D43Correct.FEEDBACK),
        _BrokenActClient(["accept"], verdict="satisfied"),
        ScriptedHarness(),
        TASK,
    )
    assert res.end_reason == "evaluator_invalid"
    assert res.evaluation_status == "invalid"
    assert res.evaluation_error == {
        "kind": "persona_protocol",
        "stage": "main_act",
        "code": "tool_not_allowed_in_stage",
        "attempts": 2,
    }
    assert not res.turns
    assert res.feeling is None
    assert res.experience["status"] == "unavailable"
    assert "exclude from harness metrics" in res.experience["reason"]


def test_free_action_classification_still_converges_after_open_intent() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _ClassifyingClient(["free", "accept"], verdict="satisfied")
    res = run_session(p, client, ScriptedHarness(), TASK)

    assert res.end_reason == "accepted"
    assert client.classifications
    assert client.classifications[0][0]["action"] == "free"
    assert "send_message" in client.classifications[0][1]
    judge_prompts = [u for u in client.seen if "<main_judge>" in u]
    intent_prompts = [u for u in client.seen if "<main_intent>" in u]
    assert all("<action_space>" not in u for u in judge_prompts)
    assert all("<action_space>" not in u for u in intent_prompts)


def test_main_action_space_has_no_private_verify_action() -> None:
    p = _persona(D1Eval.EXPERT, D43Correct.FEEDBACK)
    client = _RecordingClient(["send_message", "accept"], verdict="unsure")
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert all("verify_self" not in t.action_space for t in res.turns)
    assert all("<self_observation>" not in u for u in client.seen)


def test_private_tool_steps_become_bounded_evidence_memory() -> None:
    state = State()
    calls = [
        {
            "role": "main_judge",
            "parsed": {
                "perceive": "I inspected the diff and saw DataArray.integrate now accepts coord."
            },
            "steps": [
                {"kind": "tool", "text": '{"ignored": "bad prefix"}'},
                {
                    "kind": "tool",
                    "text": 'read_file {"path": "xarray/core/dataarray.py"}',
                },
                {
                    "kind": "tool_result",
                    "text": '{"ok": true, "content": "very long file body"}',
                },
            ],
        }
    ]
    _record_private_evidence(state=state, calls=calls, phase="active")
    assert state.private_evidence is not None
    assert len(state.private_evidence) == 1
    evidence = state.private_evidence[0]
    assert evidence.startswith("[E1 after_reply/judge]")
    assert "read_file `xarray/core/dataarray.py`" in evidence
    assert "DataArray.integrate now accepts coord" in evidence


def test_runs_one_session_returns_result() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    res = run_session(p, ScriptedPersonaClient(), ScriptedHarness(), TASK)
    assert isinstance(res, SessionResult)
    assert res.persona_id == "P"
    assert res.turns and res.turns[0].action == "send_message"


def test_self_terminates_at_chosen_turn() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _StubClient(["send_message", "accept"], verdict="satisfied")
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.end_reason == "accepted"
    assert len(res.turns) == 2


def test_on_progress_pushes_pending_harness_reply_immediately() -> None:
    """Harness reply in hand pushes to observation layer: after send returns, before persona's next-round response, trigger on_progress once more and suspend snapshot this reply; when next TurnLog lands in logs, suspend clears (reply already carried with logs)."""
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _StubClient(["send_message", "accept"], verdict="satisfied")
    snaps: list[tuple[int, str | None]] = []
    run_session(
        p,
        client,
        ScriptedHarness(),
        TASK,
        on_progress=lambda res: snaps.append((len(res.turns), res.pending_harness_output)),
    )
    # turn1 lands in logs (no suspend) → harness reply in hand (suspend push) → turn2 lands in logs (suspend cleared)
    assert snaps[0] == (1, None)
    assert snaps[1][0] == 1 and snaps[1][1]
    assert snaps[2] == (2, None)


def test_help_text_is_threaded_into_persona_prompt() -> None:
    # Help text pierces through run_session(help_text=) to each round's persona-visible user turn (capability expectation anchor).
    p = _persona(D1Eval.EXPERT, D43Correct.FEEDBACK)
    client = _RecordingClient(["send_message", "accept"], verdict="satisfied")
    run_session(p, client, ScriptedHarness(), TASK, help_text="# Help\nno live progress; no /btw.")
    assert client.seen and all("<harness_help>" in u for u in client.seen)
    assert any("no live progress" in u for u in client.seen)


class _AppraisingClient(_RecordingClient):
    """Return a task_load reading at session start; remaining rounds normal. Used to verify starting patience floats with task volume."""

    def __init__(self, actions: list[str], task_load: str) -> None:
        super().__init__(actions, verdict="unsure")
        self._task_load = task_load

    def respond(self, system: str, user: str) -> dict:
        ret = super().respond(system, user)
        if "SIZE UP THIS TASK" in user:  # Task volume assessment instruction only at session start
            ret = {**ret, "task_load": self._task_load}
        return ret


def test_opening_appraisal_floats_starting_patience() -> None:
    # STEADY baseline 5; session start reports epic(+2) → starting patience 7, falls in first TurnLog.
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _AppraisingClient(["send_message", "send_message"], task_load="epic")
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.turns[0].patience == 7  # 5 + epic(+2), unsure does not adjust patience further
    # Assessment instruction appears only at session start; subsequent rounds no longer need task_load field
    assert "SIZE UP THIS TASK" in client.seen[0]
    assert all("SIZE UP THIS TASK" not in u for u in client.seen[1:])


def test_opening_appraisal_quick_lowers_patience() -> None:
    # IMPATIENT baseline 3; session start reports quick(-1) → starting patience 2 (unrelated to d43).
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK, tempo=TimeTemperament.IMPATIENT)
    client = _AppraisingClient(["send_message", "send_message"], task_load="quick")
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.turns[0].patience == 2  # 3 + quick(-1)


def test_max_turns_cutoff() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _StubClient(["send_message", "send_message"], verdict="unsure")  # Never terminate
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.end_reason == "max_turns"
    assert len(res.turns) == MAX_TURNS


def test_missing_self_rating_does_not_fall_back_to_derived() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _StubClient(["send_message", "accept"], verdict="satisfied", rating={"oops": 1})
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.feeling is None and isinstance(res.feeling_derived, FeelingScore)
    assert res.experience["status"] == "missing"


def test_pure_subjective_turnlog_has_no_objective_fields() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    res = run_session(p, ScriptedPersonaClient(), ScriptedHarness(), TASK)
    t = res.turns[0]
    for attr in ("objective_failed", "control_fatal", "gap"):
        assert not hasattr(t, attr)


def test_capability_fork() -> None:
    shallow = run_session(
        _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK, "P-shallow"),
        ScriptedPersonaClient(),
        ScriptedHarness(),
        TASK,
    )
    expert = run_session(
        _persona(D1Eval.EXPERT, D43Correct.FILE_ISSUE, "P-expert"),
        ScriptedPersonaClient(),
        ScriptedHarness(),
        TASK,
    )
    # Low capability acceptance upon completion (high user experience)
    assert shallow.end_reason == "accepted"
    assert shallow.feeling.score >= 3
    # High capability drive evidence to exhaustion → file_issue (low user experience)
    assert expert.end_reason == "issue_filed"
    assert expert.feeling.score <= 2
    assert expert.issue_artifact is not None


def test_give_up_also_leaves_exit_issue() -> None:
    # Leave=abandon the pit yet still file a questionnaire-style issue "why you drove me away": decouple "file issue" from specific actions,
    # otherwise FEEDBACK/GIVE_UP type frustrated exits leave backlog with no signal. end_reason remains abandoned.
    p = _persona(D1Eval.EXPERT, D43Correct.GIVE_UP)
    # EXPERT: Consecutive harness failures (2×) trigger diagnostic gate; give_up unlocks; exit on round 3.
    client = _StubClient(
        ["send_message", "send_message", "give_up"], verdict="failed_blame_harness"
    )
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.end_reason == "abandoned"  # Mechanism unchanged: still give_up
    assert res.issue_artifact is not None  # But additionally leave an exit issue


class _RaisingHarness:
    """Crash on first message: send throws exception, simulating harness timeout/crash (route wraps as [harness error] sentinel)."""

    def send(self, message: str) -> str:  # noqa: ARG002
        raise TimeoutError("agent.run timeout >240s")


def test_route_keep_waiting_polls_followup_when_not_awaiting() -> None:
    """Main loop keep_waiting: after reply, should still fetch subsequent output via poll (Spec-0036)."""

    class _FollowupHarness:
        in_flight = False

        def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
            return ("reply", "second-queued")

    p = _persona(D1Eval.EXPERT, D43Correct.GIVE_UP)
    state = init_state(p)
    got = route("keep_waiting", "", state, _FollowupHarness(), "first")
    assert got == "second-queued"


def test_route_keep_waiting_idle_returns_none() -> None:
    class _IdleHarness:
        in_flight = False

        def poll(self, timeout: float) -> tuple[str, object]:  # noqa: ARG002
            return ("pending", timeout)

    p = _persona(D1Eval.EXPERT, D43Correct.GIVE_UP)
    state = init_state(p)
    assert route("keep_waiting", "", state, _IdleHarness(), "first") is None


def test_harness_error_surfaced_and_negative_exit_available_immediately() -> None:
    # After unlock: framework no longer blocks accept; instead feeds [harness error] as-is to persona, enabling negative exits (give_up/
    # file_issue) from the start—discerning users facing a crash naturally exit/file an issue rather than accept (R4 funnel now complete).
    # Here persona sees crash on first round and give_ups: session ends abandoned with an exit issue, never forced to accept.
    p = _persona(D1Eval.EXPERT, D43Correct.GIVE_UP)
    client = _StubClient(["send_message", "give_up"], verdict="stuck")
    res = run_session(p, client, _RaisingHarness(), TASK)
    assert res.end_reason == "abandoned"  # Exit, not false acceptance
    assert res.issue_artifact is not None  # Leave an exit issue: "why was I forced out"
    assert any("[harness error]" in t.harness_output for t in res.turns if t.harness_output)


def test_issue_artifact_is_user_voice_with_metadata_footer() -> None:
    expert = run_session(
        _persona(D1Eval.EXPERT, D43Correct.FILE_ISSUE, "P-expert"),
        ScriptedPersonaClient(),
        ScriptedHarness(),
        TASK,
    )
    art = expert.issue_artifact
    assert art is not None
    # No longer wrap in third-person template shell
    assert "### What the user reported" not in art
    assert "Issue filed by simulated user" not in art
    # Body first = persona file_issue first-person original text (non-empty) for this round, separated from machine footnote by ---
    body, sep, footer = art.partition("\n---\n")
    assert sep  # Has separator line
    assert body.strip()  # User original text non-empty
    # Footnote is machine-collected metadata (including capability tier/correction style) for developer triage
    assert "auto-collected" in footer
    assert "expert/file_issue" in footer
