"""Derive legal actions, apply capability masks, validate free-form output, and route actions.

The framework enforces structural boundaries; the model makes subjective judgments:
  Current action space = legal actions(phase)  # external conversation uses send_message
                       ∪ (ACTIVE ? {accept, accept_with_reservations, file_issue, give_up})

All four terminal actions are available in ACTIVE. Previously, accept required only an output,
while file_issue/give_up required exhausted patience or two confirmed consecutive failures.
This asymmetry forced even obvious failures into accept (R4 accepted a timeout on the first turn).
Providing all exits lets the model choose acceptance, an issue report, or departure after a crash
or timeout. Even the requirement that accept have a real artifact is therefore left to the model.
The [harness error] text is passed through unchanged. The prompt determines the response through
G6, the ACTION SEMANTICS termination-timing clause, D43_CLAUSE personality, and <mood> patience.

OPENING prevents acceptance before any task is sent. ACTIVE means at least one harness turn is
available to react to, including an error. Patience/consec_blame are still calculated, but inform
the prompt and user experience assessment rather than restricting actions.

The LLM should choose from the action space. If none fits, it may return action:"free" + message
for classification afterward. Missing or unauthorized actions and channel<->message mismatches
raise typed evaluator errors; the framework must not guess or project them onto a legal action.
"""

from __future__ import annotations

from .actions import CATALOG, Effect, Phase, assert_channel
from .dimensions import Persona
from .state import State

# --------------------------------------------------------------------------
# set of legal states
# --------------------------------------------------------------------------
LEGAL_BY_PHASE: dict[Phase, set[str]] = {
    Phase.OPENING: {"send_message"},
    Phase.ACTIVE: {"interrupt", "keep_waiting", "send_message"},
}


class ActionResolutionError(ValueError):
    """Spec-0048/T4: action missing, out-of-bounds, or channel mismatch; guessing final state prohibited."""

    def __init__(self, code: str, action_id: str = "") -> None:
        self.code = code
        self.action_id = action_id
        super().__init__(f"invalid action ({code}): {action_id!r}")


# --------------------------------------------------------------------------
# derived
# --------------------------------------------------------------------------
def derive_action_space(
    phase: Phase,
    persona: Persona,
    state: State,  # noqa: ARG001  interface reserved: state no longer locks actions (patience/artifacts left to model judgment), signature retained for future use
) -> list[str]:
    space = set(LEGAL_BY_PHASE[phase])

    if phase == Phase.ACTIVE:
        # entered ACTIVE (= message sent, at least one harness round, even if [harness error]), four terminating actions
        # Fully open; let the model self-judge by persona character (D43_CLAUSE) + <mood>: accept / accept with reservations / give up / file issue.
        # Framework does not judge "whether acceptance is possible"—including harness crash/timeout: feed errors as-is for the model to perceive; users with judgment will decide.
        # Crashes naturally lead to filing issues/giving up rather than acceptance (R4's false acceptance was merely a funnel artifact from "only accept as one exit", now remedied).
        space.update({"accept", "accept_with_reservations", "file_issue", "give_up"})

    return sorted(space)


# --------------------------------------------------------------------------
# Free-form output classification (escape hatch)
# --------------------------------------------------------------------------
def classify_free_action(message: str, space: list[str], persona: Persona) -> str:
    """Safely handle action:'free' when model self-classification is unavailable.

    Keyword-based intent guessing is unsafe: "looks good" might be mistaken for accept, or "report this"
    for file_issue, corrupting user experience and issue signals (the motivation for approach B).
    The client's LLM performs the real self-classification through classify_action before resolve in
    loop. If that classification is missing or fails, choose a safe **non-terminal** action, preferring
    feedback. Never infer accept/file_issue/give_up or other terminal intent from prose.
    """
    if "send_message" in space and message.strip():
        return "send_message"
    non_terminal = [a for a in space if CATALOG[a].effect is not Effect.TERMINATE]
    if message.strip() and non_terminal:
        return sorted(non_terminal)[0]
    raise ActionResolutionError("unclassifiable_free", "free")


def project_to_legal(action_id: str, space: list[str]) -> str:
    """Confirm only legal actions; order, effect, or history id must not bear fallback semantics."""
    if action_id in space:
        return action_id
    code = "missing_action" if not action_id else "action_not_in_space"
    raise ActionResolutionError(code, action_id)


# --------------------------------------------------------------------------
# resolve: generate result -> legal, consistent action
# --------------------------------------------------------------------------
def resolve_action(ret: dict, space: list[str], persona: Persona) -> tuple[str, str]:
    """
    ret: dict returned by LLM, containing action / message.
    Return (action_id, message): action within space; message always from model verbatim, framework never authors.

    Whether message is required depends on the action's own message_policy. No fabrication, clearing, or projection here;
    optional terminal notes for accept/give_up do not create harness requests.
    """
    action_id = ret.get("action", "")
    message = ret.get("message", "") or ""

    if action_id == "free":
        action_id = classify_free_action(message, space, persona)
    action_id = project_to_legal(str(action_id).strip(), space)

    try:
        assert_channel(action_id, message)
    except ValueError as exc:
        raise ActionResolutionError("channel_mismatch", action_id) from exc
    return action_id, message.strip()
