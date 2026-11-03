"""spec-0005/T2: Action space derivation + free output classification / privilege projection / channel validation."""

from __future__ import annotations

import pytest

from ahe_beta.user.sim.action_space import (
    ActionResolutionError,
    derive_action_space,
    resolve_action,
)
from ahe_beta.user.sim.actions import CATALOG, MessagePolicy, Phase
from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from ahe_beta.user.sim.state import init_state


def _persona(
    d1: D1Eval = D1Eval.EXPERT,
    d5: D5Autonomy = D5Autonomy.COLLABORATIVE,
    d43: D43Correct = D43Correct.FILE_ISSUE,
) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P",
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.EVERY_STEP,
            d43=d43,
            d5=d5,
        )
    )


def test_opening_only_send_message() -> None:
    p = _persona()
    assert derive_action_space(Phase.OPENING, p, init_state(p)) == ["send_message"]


def test_active_external_actions_are_unified_across_capability_and_authz() -> None:
    expert = _persona(d1=D1Eval.EXPERT)
    blind_read_only = _persona(d1=D1Eval.BLIND, d5=D5Autonomy.ADVISORY)
    se = derive_action_space(Phase.ACTIVE, expert, init_state(expert))
    sb = derive_action_space(Phase.ACTIVE, blind_read_only, init_state(blind_read_only))
    assert {"interrupt", "keep_waiting", "send_message"} <= set(se)
    assert {"interrupt", "keep_waiting", "send_message"} <= set(sb)
    for legacy in (
        "verify_self",
        "request_evidence",
        "ask_harness_run",
        "grant_autorun",
        "give_feedback",
        "refine_request",
    ):
        assert legacy not in se
        assert legacy not in sb


def test_active_offers_all_four_terminals_without_framework_gate() -> None:
    # loosen: After entering ACTIVE, all four termination actions (accept/accept_with_reservations/file_issue/give_up) are fully unlocked.
    # Not gated by patience/diagnostics/artifacts — acceptance and exit timing are determined by the model according to persona character + <mood>. Same applies even when patience is exhausted.
    p = _persona(d43=D43Correct.FILE_ISSUE)
    fresh = derive_action_space(Phase.ACTIVE, p, init_state(p))
    assert {"accept", "accept_with_reservations", "file_issue", "give_up"} <= set(fresh)
    # Unlocked for all personas (whether to open a issue or exit is governed by D43_CLAUSE in the prompt; the framework does not make the choice).
    p2 = _persona(d43=D43Correct.GIVE_UP)
    fresh2 = derive_action_space(Phase.ACTIVE, p2, init_state(p2))
    assert {"accept", "accept_with_reservations", "file_issue", "give_up"} <= set(fresh2)
    # accept_with_reservations and accept are both TERMINATE with end_reason=accepted (delivery proceeds as normal, leaving a gap in user experience).
    assert CATALOG["accept_with_reservations"].effect is CATALOG["accept"].effect
    assert CATALOG["accept_with_reservations"].end_reason == "accepted"


def test_resolve_free_falls_back_to_safe_nonterminal() -> None:
    # Option B: resolve no longer guesses intent from keywords. Without model self-evaluation, free always falls back to the safe non-termination action.
    # Even if the text says "accept it", never arbitrarily terminate (to avoid polluting user experience/issue signals).
    p = _persona()
    space = ["accept", "send_message"]
    aid, msg = resolve_action({"action": "free", "message": "looks good, accept it"}, space, p)
    assert aid == "send_message" and aid != "accept" and msg.strip()


def test_resolve_rejects_legacy_external_actions() -> None:
    p = _persona(d1=D1Eval.BLIND)
    space = ["send_message", "accept"]
    for legacy in ("verify_self", "ask_harness_run", "request_evidence", "give_feedback"):
        with pytest.raises(ActionResolutionError, match="action_not_in_space"):
            resolve_action({"action": legacy, "message": "show me evidence"}, space, p)


def test_resolve_enforces_channel_consistency() -> None:
    p = _persona()
    # EMIT with empty message: the client contract must fail if retry has not fixed the issue; cannot spin idle or fabricate.
    space = ["send_message"]
    with pytest.raises(ActionResolutionError, match="channel_mismatch"):
        resolve_action({"action": "send_message", "message": ""}, space, p)


def test_accept_without_terminal_message_is_valid_and_not_emitted() -> None:
    p = _persona()
    aid, msg = resolve_action({"action": "accept"}, ["accept", "send_message"], p)
    assert aid == "accept" and msg == ""
    assert CATALOG["accept"].message_policy is MessagePolicy.OPTIONAL
    assert CATALOG["send_message"].message_policy is MessagePolicy.REQUIRED


def test_terminal_message_policy_is_action_specific() -> None:
    assert CATALOG["give_up"].message_policy is MessagePolicy.OPTIONAL
    assert CATALOG["accept_with_reservations"].message_policy is MessagePolicy.REQUIRED
    assert CATALOG["file_issue"].message_policy is MessagePolicy.REQUIRED


def test_opening_is_the_only_structural_gate_against_accepting_nothing() -> None:
    # The only structural boundary preventing "acceptance void" is OPENING (no message sent yet → only send_message allowed, no termination actions).
    # Once ACTIVE, there is at least one harness round to respond; acceptance is left to the model.
    p = _persona()
    opening = derive_action_space(Phase.OPENING, p, init_state(p))
    assert opening == ["send_message"]
    active = derive_action_space(Phase.ACTIVE, p, init_state(p))
    assert "accept" in active and "file_issue" in active
    assert "keep_waiting" in active and "interrupt" in active


def test_negative_terminal_outside_space_is_rejected() -> None:
    # When file_issue/give_up are not available in the current state, do not guess substitute actions or project onto accept.
    p = _persona(d43=D43Correct.FILE_ISSUE)
    space = ["accept", "send_message"]
    for action in ("file_issue", "give_up"):
        with pytest.raises(ActionResolutionError, match="action_not_in_space"):
            resolve_action({"action": action, "message": "stop"}, space, p)


def test_missing_action_is_rejected_even_when_accept_is_first() -> None:
    p = _persona()
    invalid_objects = [
        {"message": "looks fine"},
        {"tool": "run_shell", "args": {"cmd": "git diff"}},
        {"ok": True, "stdout": "tests pass", "returncode": 0},
    ]
    for space in (["accept", "send_message"], ["send_message", "accept"]):
        for ret in invalid_objects:
            with pytest.raises(ActionResolutionError, match="missing_action"):
                resolve_action(ret, space, p)


def test_silent_action_with_message_is_rejected() -> None:
    p = _persona()
    with pytest.raises(ActionResolutionError, match="channel_mismatch"):
        resolve_action({"action": "keep_waiting", "message": "keep going"}, ["keep_waiting"], p)
