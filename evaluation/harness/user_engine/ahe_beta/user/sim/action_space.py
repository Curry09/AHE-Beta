"""
action_space.py
Action space derivation + capability mask + post-hoc validation of free output + routing.

Derivation formula (framework pins only the unique structural boundary; all "judgment" delegated to the model with judgment):
  This round's action space = legal moves set(phase)                           # external dialog actions unified as send_message
                            ∪ (ACTIVE ? {accept, accept_with_reservations, file_issue, give_up})  # four terminal actions fully open, model self-judges

Why terminal actions (including accept) are no longer gated by framework:
  Old design: accept threshold low (any output suffices), file_issue/give_up threshold high (patience exhausted/2 consecutive failures), creating asymmetry that funnels "obvious failures" into accept at the start—only forward exit remains (R4: first turn timed out yet accepted). Root cause: not that the model cannot judge, but that its only retreat is accept. With exits complete, a user with judgment naturally files issues/gives up facing crash/timeout rather than accepting. Thus even "accept requires real output" is removed: whether acceptance is possible (including accepting a crash) is inherently for the model to judge; [harness error] fed as-is for perception, driven by prompt (G6 + ACTION SEMANTICS terminal timing clause + D43_CLAUSE character + <mood> patience). What truly prevents "null acceptance" is the OPENING boundary (no task yet → no accept); once in ACTIVE, at least one harness round can respond. Patience/consec_blame counted as usual, only fed to the prompt/user experience, not locked in action.

Generation discipline:
  LLM prioritizes picking from action space; if no suitable item, return action:"free" + message, framework classifies post-hoc.
  Missing, out-of-bounds, or channel<->message mismatch all raise typed evaluator error; guessing or projection prohibited.
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
    state: State,  # noqa: ARG001  Reserved interface: state no longer locks actions (patience/artifacts are left to model judgment); retain the signature for future use.
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
    """action:'free' but without model self-classification—**safety fallback**.

    No more intent-guessing from keywords—highly unreliable and dangerous: "looks good" could be misread as accept, "report this" as file_issue, directly polluting experience/issue signals (motivation for approach B). True classification by client's LLM self-eval (see classify_action seam before resolve in loop); here only fallback when self-eval absent/fails: always land on safe **non-terminal** action (prefer feedback), never infer accept/file_issue/give_up terminal intent from prose.
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
