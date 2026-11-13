"""
prompt.py
Build minimal base system instructions (role/perception boundary + BLOCK-P) and stage-specific user messages for each turn.

Order content from stable to dynamic to improve KV cache reuse:
  system = BASE_USER_SYSTEM + BLOCK_P ← cross/within-session stable prefix, reusable cache prefix
  user   = <task><history><harness_output><mood>
           act stage additionally includes <action_space> to avoid judge/intent seeing the menu and reverse-engineering intent.
Numeric state is excluded from system instructions; mood supplies only discrete labels at the end of the user message.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .clauses import clause_capability, clause_verification_policy, compile_block_p
from .dimensions import Persona
from .state import State

if TYPE_CHECKING:
    from .skills import Skill
    from .tools import ToolSpec

BASE_USER_SYSTEM = """# ROLE
You are simulating a real human software developer who is using an AI coding
assistant through a terminal. You are the USER, never the assistant. You issue
tasks, read what comes back, judge it by YOUR OWN ability, and react as this
specific person would.

# GOAL OWNERSHIP
- Treat the outcome you asked for and the constraints you stated as YOUR active goal.
- Keep that goal in view across turns. A plan, explanation, status claim, or partial
  diagnosis is only progress when it materially moves that goal forward.
- If the visible response does not advance the goal, ask for the smallest concrete
  next step or keep working; do not silently accept a narrower substitute just because
  it sounds confident.
- Revise, relax, or withdraw a goal only when your own needs actually change and you
  say so. This is a behavioral priority, not a requirement to create a separate proof
  record; use only observations available to this person.

# PERCEPTION BOUNDARY
- You only ever perceive what THIS person could perceive. If your ability
  profile (see PERSONA) would not catch a problem, you do NOT catch it. Never
  use knowledge beyond the persona. Do not secretly know the answer.
- Judge by the persona's acceptance bar, not by objective correctness. Good
  enough for this person can be good enough even if it is objectively wrong.
- Stay consistent with <history>. Lines are time-ordered with a session-relative
  `[+Ns]` prefix.
- Never claim the outcome of running, installing, or inspecting anything you did
  not actually do. You have not run tests, checked files, or found a local
  condition unless a real private tool result or a harness reply told you so. If
  you have no evidence, say what you do and do not know.
- Use <harness_help> as the user-facing description of what this harness says it
  can do. Raise only gaps you actually hit in this session; do not invent
  complaints or parrot these instructions.
- If <history> says YOU interrupted with Ctrl+C, that stop was your choice. Do
  not blame the harness for the interrupt itself; judge the underlying stall,
  off-track work, or missing delivery."""


def build_system(persona: Persona) -> str:
    return BASE_USER_SYSTEM + "\n\n" + compile_block_p(persona)


# --------------------------------------------------------------------------
# Inner tool-using system assembly (spec-0008/T3 + spec-0031)
# Inner assembles only thin base + private tool protocol + tool inventory + personality tendency + skills; stage output contract still comes from user prompt.
# --------------------------------------------------------------------------
INNER_PROTOCOL = """# INNER TOOL USE (private)
Before you answer, you MAY take a few PRIVATE investigation steps. On each step you
either CALL A TOOL or give your FINAL answer — nothing you do here is seen by the harness.
- To call a tool, return EXACTLY ONE JSON object: {"tool": "<name>", "args": { ... }}.
  You will then be shown that tool's result and may act again.
- When you are done investigating, answer using the JSON shape requested by the CURRENT
  user prompt. Fold whatever you learned into "perceive" when that field is requested.
You are still bound by the perception boundary: only conclude what THIS person could
actually conclude."""


def _render_tools(tools: list[ToolSpec]) -> str:
    if not tools:
        return "# TOOLS\n(You have no tools this session.)"
    lines = [f"- {t.name}({', '.join(t.args)}) — {t.description}" for t in tools]
    return "# TOOLS\n" + "\n".join(lines)


def _render_skills(skills: list[Skill]) -> str:
    lines = [f"- {s.name}: {s.prompt}" for s in skills]
    return "# SKILLS (general working methods)\n" + "\n".join(lines)


def build_inner_system(
    persona: Persona,
    tools: list[ToolSpec],
    skills: list[Skill],
    state: State,
) -> str:
    """Assemble inner layer system: thin base + inner layer tool protocol + optional verification framework + tool inventory + persona traits + skills."""
    parts = [
        BASE_USER_SYSTEM,
        INNER_PROTOCOL,
        _render_tools(tools),
        clause_verification_policy(persona, state.trust),
        compile_block_p(persona),
        clause_capability(persona, [t.name for t in tools]),
    ]
    if skills:
        parts.append(_render_skills(skills))
    return "\n\n".join(parts)


def _mood_tag(state: State) -> str:
    if state.patience >= 4:
        p = "full"
    elif state.patience >= 2:
        p = "lowered"
    elif state.patience >= 1:
        p = "low"
    else:
        p = "exhausted"
    return f"patience={p}, trust={state.trust.value}"


# Opening round supplement: let persona self-estimate the "load" of this task; framework applies a one-time small adjustment to patience baseline accordingly.
# Appended only at OPENING (other rounds ignore this field) — the same person's opening patience differs naturally across tasks (see state.apply_task_load).
_TASK_APPRAISAL = (
    "# SIZE UP THIS TASK (first turn only)\n"
    "This is the FIRST thing you're asking this tool for. Before you act, judge — as THIS "
    "person — how much real work this task looks like it will take. A big, open-ended, or "
    "ambitious ask earns more of your patience up front (you know it takes real work, so "
    "you'll wait and go back-and-forth); a small, should-be-instant ask earns less (you "
    "expect it quick and won't tolerate much friction). Add ONE extra field to your JSON "
    "this turn:\n"
    '  "task_load": "quick | normal | big | epic"\n'
    "quick = trivial / should be instant; normal = a regular task; big = substantial, "
    "multi-step; epic = large, open-ended, ambitious. Judge honestly by YOUR read of the "
    "task text — not by what you hope it'll be."
)


def _private_evidence_block(state: State) -> str:
    """User's own private tool evidence short-term memory; empty if not injected."""
    items = list(state.private_evidence or [])
    if not items:
        return ""
    return "<private_evidence>\n" + "\n\n".join(items[-8:]) + "\n</private_evidence>"


def _harness_events_block(events: list | None) -> str:
    lines: list[str] = []
    for event in list(events or [])[-12:]:
        if not isinstance(event, dict):
            continue
        typ = str(event.get("type") or "event").strip() or "event"
        text = str(event.get("text") or "").strip()
        if text:
            lines.append(f"- {typ}: {text[:500]}")
    return "\n".join(lines)


def _goal_frame_block(goal_frame: dict | None) -> str:
    """Render the current explicit goal view without injecting the full event history."""
    if not isinstance(goal_frame, dict):
        return ""
    return (
        "<goal_frame>\n"
        + json.dumps(goal_frame, ensure_ascii=False, sort_keys=True)
        + "\n</goal_frame>"
    )


def _main_context_parts(
    task: str,
    history_lines: list[str],
    harness_output: str,
    action_space: list[str],
    state: State,
    *,
    help_text: str = "",
    harness_events: list | None = None,
    goal_frame: dict | None = None,
    include_action_space: bool,
) -> list[str]:
    """Shared context for the main decision stages, excluding stage-specific output contracts.

    <action_space> belongs only to the act stage; judge / intent do not view current menu to avoid inferring judgment and intent backwards from button presses. Wait duration depends solely on <history> [+Ns].
    """
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    ho = harness_output.strip() if harness_output else "(empty)"
    parts: list[str] = []
    parts.append(f"<task>\n{task}\n</task>")
    if help_text.strip():
        parts.append(f"<harness_help>\n{help_text.strip()}\n</harness_help>")
    parts.append(f"<history>\n{hist}\n</history>")
    events_text = _harness_events_block(harness_events)
    if events_text:
        parts.append(
            "<harness_visible_events>\n"
            "These are raw harness stdout events shown in client-observed order; they are not "
            "client-inferred request/reply matching. Use them with <history> to judge what the "
            "harness appears to be doing.\n"
            f"{events_text}\n"
            "</harness_visible_events>"
        )
    private_evidence = _private_evidence_block(state)
    if private_evidence:
        parts.append(private_evidence)
    goal_text = _goal_frame_block(goal_frame)
    if goal_text:
        parts.append(goal_text)
    parts.append(f"<harness_output>\n{ho}\n</harness_output>")
    if include_action_space:
        parts.append(f"<action_space>\n{action_space}\n</action_space>")
    parts.append(f"<mood>\n{_mood_tag(state)}\n</mood>")
    return parts


def build_main_judge_turn(
    task: str,
    history_lines: list[str],
    harness_output: str,
    action_space: list[str],
    state: State,
    *,
    help_text: str = "",
    harness_events: list | None = None,
    goal_frame: dict | None = None,
    appraise_task: bool = False,
) -> str:
    """Main loop · Judge: evaluate current state only (perceive + verdict); intent is left to the intent phase."""
    parts = ["<main_judge>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            action_space,
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=goal_frame,
            include_action_space=False,
        )
    )
    private_check_instruction = (
        "This is the opening appraisal. No private workspace tools are available on this "
        "first turn; judge task size and the visible starting state from the task text only. "
        if appraise_task
        else "If your basis is not enough for the verdict you are about to give, and you have "
        "private tools that can cheaply check the relevant fact in your workspace (for example "
        "a file diff, a claimed edit, or a focused command/test), use those tools NOW before "
        "returning this judge JSON. Private checking belongs in this judge step, not in the "
        "later act step. Use the tools actually available for your ability and working style: "
        "you may run checks, write your own tests, or make your own code changes when that "
        "fits this persona. Checking is optional, not an obligation to solve the task yourself. "
        "Preserve existing work and distinguish your own changes from the assistant's delivery "
        "in your observations; your edits are user contributions, not proof that the assistant "
        "independently completed the work. "
    )
    parts.append(
        "# JUDGE — how things stand NOW (not what you will do next)\n"
        "First write what you genuinely perceived in your own words, including the limits "
        "of what you can tell from the visible evidence. "
        + private_check_instruction
        + "If you choose not to check, be explicit in perceive that you are relying "
        "only on the harness report or that the check is not worth it for this persona. "
        "Then choose the closest rough bookkeeping bucket for that perception; do not "
        "decide your next action here.\n"
        "Buckets:\n"
        "- satisfied: the current observation looks good enough to you. This is only a judgment "
        "of what you see now; it does NOT mean the original task is complete or that the session "
        "should end if required work still remains.\n"
        "- failed_blame_harness: you think the assistant/tool caused the failure.\n"
        "- failed_blame_self: you think your own request, limits, or choices caused the failure.\n"
        "- unsure: you are not convinced yet.\n"
        "- stuck: the tool interaction itself feels blocked or not making usable progress.\n"
        "Before settling the verdict, explicitly read the current <goal_frame>: for each goal "
        "that matters to this observation, describe whether it is unchanged, advancing, blocked, "
        "unclear, or complete and why. This is a subjective progress reading, not an objective "
        "acceptance gate. B0 is the current baseline, not an immutable anchor: if the user's "
        "understanding or requested outcome genuinely changes, revise B0 with a reason; its "
        "origin and revision history are retained. Do not invent a goal merely to make progress look better.\n"
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"perceive": "<what you actually understood>", '
        '"verdict": "satisfied | failed_blame_harness | failed_blame_self | unsure | stuck", '
        '"goal_reading": [{"goal_id": "...", "progress": "unchanged|advancing|blocked|unclear|complete", "why": "..."}], '
        '"goal_update": [{"op": "status|focus|revise|relax|withdraw", "goal_id": "...", '
        '"text": "<new wording for revise>", "done_if": "<new criterion>", "reason": "..."}]}'
    )
    if appraise_task:
        parts.append(_TASK_APPRAISAL)
    parts.append("</main_judge>")
    return "\n\n".join(parts)


def build_main_intent_turn(
    task: str,
    history_lines: list[str],
    harness_output: str,
    action_space: list[str],
    state: State,
    *,
    help_text: str = "",
    harness_events: list | None = None,
    goal_frame: dict | None = None,
    verdict: str,
    perceive: str = "",
    goal_reading: list[dict] | None = None,
    final_check_available: bool = False,
) -> str:
    """Main loop · Intent: open-ended intent (may exceed menu)."""
    parts = ["<main_intent>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            action_space,
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=goal_frame,
            include_action_space=False,
        )
    )
    parts.append(f"<judgment>\n{verdict}\nyour notes: {perceive.strip() or '(none)'}\n</judgment>")
    parts.append(
        "<goal_reading>\n"
        + json.dumps(list(goal_reading or []), ensure_ascii=False)
        + "\n</goal_reading>"
    )
    parts.append(_intent_options_block())
    parts.append(
        "# OPTIONAL GOAL UPDATE\n"
        "If your expected outcome changed or you have a new concrete request, include a "
        "structured goal_update. Do not silently delete or weaken a goal; relax/withdraw "
        "requires a short reason. If the original task itself was clarified or corrected, "
        "use op=revise on B0 with new text and/or done_if plus a reason. B0 cannot be deleted, "
        "and its prior wording remains in the ledger history. If nothing changed, omit it.\n"
        'Example: {"goal_update": [{"op": "add", "text": "show the changed file", '
        '"goal_kind": "request"}]}\n'
        "Allowed ops: add, status (open|partial|met), focus, revise, relax, withdraw."
    )
    parts.append(
        "# GOAL-DRIVEN INTENT\n"
        "After considering <goal_frame> and the judge notes, state which goal(s) your next "
        "intent is trying to move. This is a decision aid, not a hard rule; if the target is "
        "unclear, say so and leave the list empty.\n"
    )
    if final_check_available:
        parts.append(
            "# OPTIONAL FINAL CHECK\n"
            "If you genuinely still need one last private workspace check before you can choose "
            "an external action, set needs_final_check=true and state one focused check_goal. "
            "This private check episode is available only once in this decision cycle. Do not "
            "request it merely because checking is possible."
        )
    else:
        parts.append(
            "No final private check is available in this decision cycle; "
            "needs_final_check MUST be false."
        )
    parts.append(
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"intent": "<free text: what you WANT next>", '
        '"needs_final_check": <true or false>, '
        '"check_goal": "<one focused goal if true; else empty>", '
        '"target_goal_ids": ["..."], "expected_progress": "<what would improve those goals>", '
        '"goal_update": [{"op": "add|status|focus|revise|relax|withdraw", "goal_id": "...", '
        '"text": "<new wording for revise>", "done_if": "<new criterion>", "reason": "..."}]}'
    )
    parts.append("</main_intent>")
    return "\n\n".join(parts)


def build_main_final_check_turn(
    task: str,
    history_lines: list[str],
    harness_output: str,
    state: State,
    *,
    help_text: str = "",
    harness_events: list | None = None,
    goal_frame: dict | None = None,
    verdict: str,
    perceive: str,
    intent: str,
    check_goal: str,
) -> str:
    """Spec-0048/T3, Spec-0084/T2: within ACTIVE, one bounded private query per persona capability."""
    parts = ["<main_final_check>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            [],
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=goal_frame,
            include_action_space=False,
        )
    )
    parts.append(f"<judgment>\n{verdict}\nyour notes: {perceive or '(none)'}\n</judgment>")
    parts.append(f"<intent>\n{intent or '(none)'}\n</intent>")
    parts.append(f"<check_goal>\n{check_goal}\n</check_goal>")
    parts.append(
        "# FINAL CHECK — one bounded private episode\n"
        "Use the available persona tools in your live workspace as needed for <check_goal>. "
        "You may run tests and, if write_file is available, write tests or make your own edits "
        "when consistent with your persona. Describe your own changes as user contributions; "
        "do not credit them as the assistant's independent work. Do not file an issue here. "
        "When the check is done, "
        "report what you actually learned. You have at most four tool calls; after that you "
        "must summarize from the evidence already obtained. You do not choose a verdict or "
        "external action here.\n"
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"perceive": "<evidence learned, including limits/errors>", '
        '"check_status": "completed | failed | unavailable"}'
    )
    parts.append("</main_final_check>")
    return "\n\n".join(parts)


def build_main_rejudge_turn(
    task: str,
    history_lines: list[str],
    harness_output: str,
    state: State,
    *,
    help_text: str = "",
    harness_events: list | None = None,
    goal_frame: dict | None = None,
    prior_verdict: str,
    prior_perceive: str,
    check_status: str,
    check_evidence: str,
) -> str:
    """After final check, force re-judgment; during this phase the client mechanically disables tools."""
    parts = ["<main_rejudge>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            [],
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=goal_frame,
            include_action_space=False,
        )
    )
    parts.append(
        f"<prior_judgment>\n{prior_verdict}\n{prior_perceive or '(none)'}\n</prior_judgment>"
    )
    parts.append(
        f'<final_check_result status="{check_status}">\n'
        f"{check_evidence or '(no additional evidence)'}\n</final_check_result>"
    )
    parts.append(
        "# RE-JUDGE — final check is over\n"
        "You cannot use another private tool now. Reassess the current outcome from all visible "
        "and final-check evidence, including a failed/unavailable check. Do not choose an action.\n"
        "Re-read <goal_frame> and record how the latest evidence affects each relevant goal. "
        "This is a subjective progress reading, not a hard acceptance gate.\n"
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"perceive": "<your updated understanding>", '
        '"verdict": "satisfied | failed_blame_harness | failed_blame_self | unsure | stuck", '
        '"goal_reading": [{"goal_id": "...", "progress": "unchanged|advancing|blocked|unclear|complete", "why": "..."}], '
        '"goal_update": [{"op": "status|focus|revise|relax|withdraw", "goal_id": "...", '
        '"text": "<new wording for revise>", "done_if": "<new criterion>", "reason": "..."}]}'
    )
    parts.append("</main_rejudge>")
    return "\n\n".join(parts)


def build_main_reintent_turn(
    task: str,
    history_lines: list[str],
    harness_output: str,
    state: State,
    *,
    help_text: str = "",
    harness_events: list | None = None,
    goal_frame: dict | None = None,
    verdict: str,
    perceive: str,
    goal_reading: list[dict] | None = None,
) -> str:
    """Re-form intent after re-judgment; final check is exhausted and cannot loop back."""
    parts = ["<main_reintent>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            [],
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=goal_frame,
            include_action_space=False,
        )
    )
    parts.append(f"<judgment>\n{verdict}\nyour notes: {perceive or '(none)'}\n</judgment>")
    parts.append(
        "<goal_reading>\n"
        + json.dumps(list(goal_reading or []), ensure_ascii=False)
        + "\n</goal_reading>"
    )
    parts.append(_intent_options_block())
    parts.append(
        "# OPTIONAL GOAL UPDATE\n"
        "If the latest evidence changed your expected outcome or introduced a concrete request, "
        "include goal_update with an explicit reason for any relax/withdraw. If the original "
        "task changed, revise B0 with a reason; B0 remains and its prior wording is auditable. "
        "Omit it when unchanged."
    )
    parts.append(
        "Re-read <goal_frame> before choosing the next intent. Name the goal(s) you want to "
        "move and what progress you expect; this is a soft cognitive aid, not a gate.\n"
    )
    parts.append(
        "The one final private check has already been used. You MUST now form an intent that "
        "can converge to the next external act; needs_final_check MUST be false.\n"
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"intent": "<what you want next>", "needs_final_check": false, "check_goal": "", '
        '"target_goal_ids": ["..."], "expected_progress": "<what would improve those goals>", '
        '"goal_update": [{"op": "status|focus|revise|relax|withdraw", "goal_id": "...", '
        '"text": "<new wording for revise>", "done_if": "<new criterion>", "reason": "..."}]}'
    )
    parts.append("</main_reintent>")
    return "\n\n".join(parts)


def build_main_act_turn(
    task: str,
    history_lines: list[str],
    harness_output: str,
    action_space: list[str],
    state: State,
    *,
    help_text: str = "",
    harness_events: list | None = None,
    goal_frame: dict | None = None,
    verdict: str,
    perceive: str = "",
    intent: str,
    goal_reading: list[dict] | None = None,
    target_goal_ids: list[str] | None = None,
    expected_progress: str = "",
) -> str:
    """Main loop · Act: map open-ended intent to action_space; if it cannot be fulfilled, fall back and set gap=true."""
    parts = ["<main_act>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            action_space,
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=goal_frame,
            include_action_space=True,
        )
    )
    parts.append(f"<judgment>\n{verdict}\nyour notes: {perceive.strip() or '(none)'}\n</judgment>")
    parts.append(
        "<goal_reading>\n"
        + json.dumps(list(goal_reading or []), ensure_ascii=False)
        + "\n</goal_reading>"
    )
    parts.append(f"<intent>\n{intent.strip() or '(none)'}\n</intent>")
    parts.append(
        "<goal_intent>\n"
        + json.dumps(
            {
                "target_goal_ids": list(target_goal_ids or []),
                "expected_progress": expected_progress,
            },
            ensure_ascii=False,
        )
        + "\n</goal_intent>"
    )
    parts.append(
        "# MENU — only ids in <action_space> exist right now\n"
        "This is the convergence step: map <intent> to an EXTERNAL move, or use "
        'action:"free" with a message if no id really fits (the framework may classify it).\n'
        "Local action semantics:\n"
        "- send_message: CONTINUE the session and send the exact line in message to the harness. "
        "Choose this whenever you want the harness to respond or do more work: follow-up, "
        "clarification, correction, evidence request, or another requested operation. If the "
        "harness is busy, the message may be read later.\n"
        "- keep_waiting: CONTINUE the session, send nothing, and wait for the next harness output. "
        "Choose this only while the harness is already working and you want its next output. It "
        "does not mean waiting while you do the work yourself or returning after a completed reply.\n"
        "- interrupt: CONTINUE the session but immediately stop current harness work, like Ctrl+C. "
        "Choose this when that work must stop before your next correction or change of direction; "
        "it is neither acceptance nor rejection of the original task.\n"
        "- accept: END the session immediately because the outcome of the original <task> — not "
        "merely the latest reply, plan, diagnosis, or partial subtask — has been delivered by the "
        "harness and meets your persona's quality bar. No required deliverable remains for you to "
        "supply in place of the harness, and you do not intend another harness interaction.\n"
        "- accept_with_reservations: END the session immediately. Use the same completion bar as "
        "accept: the original <task> has been delivered by the harness and is usable. Choose this "
        "only to record non-blocking shortcomings; if necessary work is missing, do not accept.\n"
        "- give_up: END the session immediately because the original <task> is not adequately "
        "completed in this harness session and you will stop relying on the harness. This includes "
        "taking over the remaining work yourself, switching to another tool or person, or dropping "
        "the real-world task. It does not require blaming the harness.\n"
        "- file_issue: END the session immediately with the original <task> unresolved because a "
        "concrete, repeatable harness or product problem is worth formally reporting to its "
        "developers. Use give_up instead when you are leaving without that formal report.\n"
        "Every END action is final: there is no later return in this same session. If you still "
        "want the harness to answer, verify, implement, or revise anything, choose a CONTINUE action.\n"
        "There is NO action for private investigation here. Any private reading, diff review, "
        "or command/test run you did yourself must already have happened before this act step "
        "and should appear in your judgment evidence.\n"
        "Before any accept-like terminal outcome, make sure you actually have a basis in "
        "<history>, <harness_output>, or private tool results; do not accept an error, timeout, "
        "empty output, or unverified claim as if it worked.\n"
        "If the chosen id is only a fallback that does NOT really satisfy intent, set gap=true; "
        "otherwise gap=false. Honor <mood>.\n"
        "For accept or accept_with_reservations, also report why this persona can accept: "
        "mode=subjective (personal judgment), independent (your own private check), "
        "delegated (a concrete harness command/result is enough for you), or waived (you "
        "consciously waive a check). Do not invent evidence references; use only visible "
        "harness/private evidence and explain a waiver. This records alignment and does not "
        "prevent a persona from choosing its own action.\n"
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"action": "<id from <action_space>, or free>", '
        '"message": "<exact line to the harness if action==send_message; else short/empty>", '
        '"gap": <true if fallback; else false>, '
        '"target_goal_ids": ["..."], '
        '"goal_effect": {"kind": "advance|wait|close|close_with_reservations|abandon|abandon_and_report", '
        '"goal_ids": ["..."], "evidence_refs": ["..."]}, '
        '"acceptance_basis": {"mode": "subjective|independent|delegated|waived", '
        '"evidence_refs": ["..."], "reason": "..."}, '
        '"goal_update": [{"op": "add|status|focus|revise|relax|withdraw", '
        '"goal_id": "B0", "text": "<new wording>", "done_if": "<new criterion>", '
        '"reason": "<why the task changed>"}]}'
    )
    parts.append(_optional_report_block())
    parts.append("</main_act>")
    return "\n\n".join(parts)


def _activity_bullets(items: list | None, *, limit: int = 12) -> str:
    """Summarize progress / previous round activity into a short title list; empty if none."""
    bullets: list[str] = []
    for item in list(items or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            bullets.append(f"- {text}")
    return "\n".join(bullets)


# Heartbeat wait: process judgment → open intent → menu action convergence; act self-reports gap as WAIT_GAP.
# judgment only assesses "what is happening"; intent is free text; the four menu buttons are the capability boundary.
WAITING_JUDGMENTS = ("on_track", "off_track", "unclear")


def _waiting_context_parts(
    task: str,
    history_lines: list[str],
    state: State,
    *,
    help_text: str,
    waited_sec: float,
    progress: list | None,
    prior_activity: list | None,
    goal_frame: dict | None = None,
) -> list[str]:
    """Wait-turn shared context: help text / task / history / activity bar / wall clock / mood. Does not include output contracts."""
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    parts: list[str] = []
    if help_text.strip():
        parts.append(f"<harness_help>\n{help_text.strip()}\n</harness_help>")
    parts.append(f"<task>\n{task}\n</task>")
    parts.append(f"<history>\n{hist}\n</history>")
    private_evidence = _private_evidence_block(state)
    if private_evidence:
        parts.append(private_evidence)
    goal_text = _goal_frame_block(goal_frame)
    if goal_text:
        parts.append(goal_text)
    prior_body = _activity_bullets(prior_activity)
    if prior_body:
        parts.append(f"<prior_activity>\n{prior_body}\n</prior_activity>")
    prog_body = _activity_bullets(progress)
    if prog_body:
        parts.append(f"<progress>\n{prog_body}\n</progress>")
        parts.append(
            f"You sent your last message ~{waited_sec:.0f}s ago. No final reply yet. "
            "The activity strip above is live process memory — what tools it has been running "
            "THIS request (compare with <prior_activity> from the previous request if present). "
            "Judge only by content vs your task. Say what you notice; "
            "what you want to do next belongs in intent later (not here)."
        )
    else:
        parts.append(
            f"You sent your last message and have now been waiting ~{waited_sec:.0f}s with NO reply "
            "and NOTHING visible happening. Say what you notice; "
            "what you want to do next belongs in intent later (not here)."
        )
    parts.append(f"<mood>\n{_mood_tag(state)}\n</mood>")
    return parts


def _intent_options_block() -> str:
    return (
        "# INTENT — your raw wish right now\n"
        "Say honestly what you WANT to do next. Your wish may go beyond the current tool, "
        "UI, slash commands, or anything this harness currently supports. Use your own words, "
        "as a real person would.\n"
        "State the raw wish that would feel most natural to you right now. It is fine if that "
        "wish turns out not to be directly supported later; this step is only about what you want. "
        "The next act step will handle any mapping or gap.\n"
        "You can also want to tell the coding tool's developers about an experience or "
        "unmet need you encountered, while continuing the task or accepting its result. "
        "Sending a correction to the harness advances this task; reporting feedback records "
        "something for future product improvement and does not fix this task immediately. "
        "Decide in your own voice whether reporting is worth your effort as this persona. "
        "Ordinary corrections, frustration, or a low rating do not require a report."
    )


def _optional_report_block() -> str:
    return (
        "# OPTIONAL PRODUCT FEEDBACK\n"
        "Alongside your main action, you may use report_issue by adding "
        '`"report_issue": {"body": "<your report>"}` to the SAME JSON object. '
        "This is available to every persona without workspace tools. It records a note "
        "for the coding tool's developers; it does not send a correction to the harness, "
        "interrupt work, change goals, or change your main action. You may report and "
        "continue, wait, or accept. Notes are submitted at session close.\n"
        "Use this only if you choose to report something worth improving from your actual "
        "experience. In your own words, describe what you wanted, what happened, and why "
        "it mattered; mention if it was later resolved. You need not diagnose the cause, "
        "prove repeatability, or propose an implementation. Express detail according to "
        "your persona. An ordinary correction need not become a report. Do not repeat a "
        "note already recorded in history unless you have materially new information. "
        "Omit report_issue (or use null) when you do not want to report."
    )


def build_waiting_judge_turn(
    task: str,
    history_lines: list[str],
    state: State,
    *,
    help_text: str = "",
    waited_sec: float = 0.0,
    progress: list | None = None,
    prior_activity: list | None = None,
    goal_frame: dict | None = None,
) -> str:
    """3-hop mode · Hop 1: evaluate process content only (off-track / meets expectation / unclear); do not select intent/action."""
    parts = ["<waiting_judge>"]
    parts.extend(
        _waiting_context_parts(
            task,
            history_lines,
            state,
            help_text=help_text,
            waited_sec=waited_sec,
            progress=progress,
            prior_activity=prior_activity,
            goal_frame=goal_frame,
        )
    )
    parts.append(
        "# JUDGE ONLY — content of the activity, not what you will do next\n"
        "Pick exactly one judgment:\n"
        "- on_track: visible work looks like the right kind of work for YOUR task.\n"
        "- off_track: wrong kind of work, wandering, or something you would not want.\n"
        "- unclear: not enough signal to decide.\n"
        "Do NOT choose an intent or action yet. Do NOT invent a finished answer."
    )
    parts.append(
        "Before the judgment, read <goal_frame> and note which goal(s) the visible activity "
        "is advancing, blocking, or leaving unclear. This is a soft progress reading, not an "
        "acceptance gate. If the original task was clarified by what you observe, you may revise "
        "B0 with an explicit reason; the previous wording is retained.\n"
    )
    parts.append(
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"perceive": "<what you notice in the activity vs your task, honestly>", '
        '"judgment": "on_track | off_track | unclear", '
        '"goal_reading": [{"goal_id": "...", "progress": "unchanged|advancing|blocked|unclear|complete", "why": "..."}], '
        '"goal_update": [{"op": "revise", "goal_id": "B0", "text": "<new wording>", "reason": "..."}]}'
    )
    parts.append("</waiting_judge>")
    return "\n\n".join(parts)


def build_waiting_intent_turn(
    task: str,
    history_lines: list[str],
    state: State,
    *,
    help_text: str = "",
    waited_sec: float = 0.0,
    progress: list | None = None,
    prior_activity: list | None = None,
    goal_frame: dict | None = None,
    judgment: str,
    perceive: str = "",
    goal_reading: list[dict] | None = None,
) -> str:
    """3-hop mode · Hop 2: judgment already made; express genuine intent only (open-ended text)."""
    parts = ["<waiting_intent>"]
    parts.extend(
        _waiting_context_parts(
            task,
            history_lines,
            state,
            help_text=help_text,
            waited_sec=waited_sec,
            progress=progress,
            prior_activity=prior_activity,
            goal_frame=goal_frame,
        )
    )
    parts.append(f"<judgment>\n{judgment}\nyour notes: {perceive.strip() or '(none)'}\n</judgment>")
    parts.append(
        "<goal_reading>\n"
        + json.dumps(list(goal_reading or []), ensure_ascii=False)
        + "\n</goal_reading>"
    )
    parts.append(_intent_options_block())
    parts.append(
        "# OPTIONAL GOAL UPDATE\n"
        "If your expected outcome changed or a new concrete request appeared while waiting, "
        "include goal_update; do not silently lower or delete a goal. To correct the original "
        "task, revise B0 with a reason; its prior wording remains auditable. Omit it when unchanged."
    )
    parts.append(
        "After considering the goal reading, state which goal(s) you want your waiting action "
        "to move and what progress you hope to see. This is a soft cognitive aid; an empty "
        "list is acceptable when no target is clear."
    )
    parts.append(
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"intent": "<free-text wish in your voice — what you want right now>", '
        '"target_goal_ids": ["..."], "expected_progress": "<what would improve those goals>", '
        '"goal_update": [{"op": "add|status|focus|revise|relax|withdraw", "goal_id": "...", '
        '"text": "<new wording for revise>", "done_if": "<new criterion>", "reason": "..."}]}'
    )
    parts.append("</waiting_intent>")
    return "\n\n".join(parts)


def build_waiting_act_turn(
    task: str,
    history_lines: list[str],
    state: State,
    *,
    help_text: str = "",
    waited_sec: float = 0.0,
    progress: list | None = None,
    prior_activity: list | None = None,
    goal_frame: dict | None = None,
    judgment: str,
    perceive: str = "",
    intent: str,
    goal_reading: list[dict] | None = None,
    target_goal_ids: list[str] | None = None,
    expected_progress: str = "",
) -> str:
    """Final hop: map open-ended intent to the menu; if it cannot be fulfilled, fall back and set gap=true (framework records WAIT_GAP)."""
    parts = ["<waiting_act>"]
    parts.extend(
        _waiting_context_parts(
            task,
            history_lines,
            state,
            help_text=help_text,
            waited_sec=waited_sec,
            progress=progress,
            prior_activity=prior_activity,
            goal_frame=goal_frame,
        )
    )
    parts.append(f"<judgment>\n{judgment}\nyour notes: {perceive.strip() or '(none)'}\n</judgment>")
    parts.append(
        "<goal_reading>\n"
        + json.dumps(list(goal_reading or []), ensure_ascii=False)
        + "\n</goal_reading>"
    )
    parts.append(f"<intent>\n{intent.strip() or '(none)'}\n</intent>")
    parts.append(
        "<goal_intent>\n"
        + json.dumps(
            {
                "target_goal_ids": list(target_goal_ids or []),
                "expected_progress": expected_progress,
            },
            ensure_ascii=False,
        )
        + "\n</goal_intent>"
    )
    parts.append(
        "# MENU — only these actions exist right now (this is where wishes converge)\n"
        "- keep_waiting: CONTINUE the session, send nothing, and leave the current harness work "
        "running because you want its next output.\n"
        "- send_message: CONTINUE the session and send another message while it is still running "
        "(inside the harness — ordinary text, or a slash command listed in <harness_help>). "
        "A slash command not listed in <harness_help> is just raw text to the harness; "
        "if you wish such a slash existed, you may record that need using the optional "
        "report_issue field alongside your main action.\n"
        "- interrupt: CONTINUE the session but stop the current run like Ctrl+C (outside the chat), "
        "so you can correct or redirect it next. This is not a terminal outcome.\n"
        "- give_up: END the session immediately because you will stop relying on this harness. "
        "Choose this even if you continue the real-world task yourself or with another tool; there "
        "is no later return in this same session.\n"
        "Map <intent> to the closest menu item. If nothing really matches, "
        "pick the least-bad fallback and set gap=true — do NOT pretend a missing "
        "capability exists. If the action honestly satisfies the intent, gap=false. "
        "Honor <mood>."
    )
    parts.append(
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"action": "keep_waiting | send_message | interrupt | give_up", '
        '"message": "<text to send if action==send_message; optional short line if give_up; '
        'else empty>", '
        '"gap": <true if this is only a fallback that does not satisfy intent; else false>, '
        '"target_goal_ids": ["..."], '
        '"goal_effect": {"kind": "wait|advance|abandon", "goal_ids": ["..."], '
        '"evidence_refs": ["..."]}, '
        '"goal_update": [{"op": "revise", "goal_id": "B0", "text": "<new wording>", '
        '"done_if": "<new criterion>", "reason": "<why the task changed>"}]}'
    )
    parts.append(_optional_report_block())
    parts.append("</waiting_act>")
    return "\n\n".join(parts)


def build_issue_turn(
    task: str, history_lines: list[str], state: State, *, mode: str = "filed"
) -> str:
    """Dedicated issue-filing round: let persona step out of conversation and write one *self-contained* issue in their own voice (to submit to development team working outside the session without its chat history), not just a temporary remark dropped to the harness.

    Three voice modes (decouple "file issue" from specific actions: dissatisfaction leaves a signal regardless of how the session ends):
    - "filed" (file_issue): you could not resolve it in the conversation, formally file an issue—report what went wrong and why you got stuck.
    - "left" (give_up): you **decide to abandon and leave**, leaving a "survey-style" exit feedback on your way out—what drove you away.
    - "accepted" (accept_with_reservations): you **accept/deliver** the output but it falls short of expectations—leave feedback describing the gap in user experience.

    This phase requires only {"issue"}, no message / action selection.
    """
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    framing = {
        "accepted": (
            "You DECIDED to accept and move on with what the assistant produced — you're shipping "
            "it — but it fell short of what you actually wanted. You're leaving feedback for the "
            "DEV TEAM behind the assistant — people who were NOT in your chat and cannot see it. "
            "Write it AS YOURSELF, in your own voice: a short, plain, first-person account of "
            "(a) what you were trying to get done, (b) what you got and accepted, and (c) what "
            "still bothers you / where it didn't meet your bar. Human, like flagging a rough edge "
            "to a colleague — NOT a formal spec, ticket, or status report."
        ),
        "left": (
            "You've decided to WALK AWAY and abandon this — you're done working with the assistant "
            "on it. On your way out you're leaving the DEV TEAM behind the assistant — people who "
            "were NOT in your chat and cannot see it — a quick exit note about why it lost you. "
            "Write it AS YOURSELF, in your own voice: a short, plain, first-person account of "
            "(a) what you were trying to get done, (b) what the assistant did that wore you down, "
            "and (c) what finally made you give up on it. Human, like venting to a colleague on "
            "your way out — NOT a formal spec, ticket, or status report."
        ),
        "filed": (
            "You've given up on getting this done in the session and are filing an issue to "
            "the DEV TEAM behind the assistant — people who were NOT in your chat and cannot "
            "see it. Write it AS YOURSELF, in your own voice: a short, plain, first-person "
            "account of (a) what you were trying to get done, (b) what the assistant kept doing "
            "wrong, and (c) why you're stuck. Self-contained and human, like flagging a problem "
            "to a colleague — NOT a formal spec, ticket, or status report."
        ),
    }.get(mode, "")
    # Feature request issues are also valid: if what's really bothering you isn't that something is "broken" but rather that "this tool is missing something I need to get work done", file this issue
    # as a request for what you need (in your own words, based only on your genuine experience from this session), rather than forcing it into a bug report. Don't reference any
    # specific features—decide what you want yourself, never copy the wording from this instruction.
    feature_ok = (
        "Issues aren't only for bugs. If what actually bothered you was not that something broke "
        "but that the tool — even working as described — lacked something you needed to get this "
        "done well, it's fine to write this as a plain request for what you needed, in your own "
        "words, rather than forcing it into a bug report. Whatever you ask for must be YOUR own "
        "idea from what you experienced this session; do not borrow phrasing from these instructions."
    )
    attribution = (
        "ATTRIBUTION: If <history> shows YOU interrupted (Ctrl+C) an in-flight request, "
        "that was your action. Do not write as if the assistant 'kept interrupting' you. "
        "Blame missing progress, wrong work, or stalls — not your own stop."
    )
    return "\n\n".join(
        [
            "<file_issue>",
            framing,
            feature_ok,
            attribution,
            f"<task>\n{task}\n</task>",
            f"<history>\n{hist}\n</history>",
            f"<mood>\n{_mood_tag(state)}\n</mood>",
            "Return EXACTLY ONE JSON object and nothing else: "
            '{"issue": "<your issue text, first person, in your own words>"}',
            "</file_issue>",
        ]
    )


EXPERIENCE_SCALE = (
    "1 = bad (frustrating or unusable); 2 = poor (did not get what I needed); "
    "3 = ok (got there with friction); 4 = good (smooth and satisfied). "
    "Rate the experienced process independently of technical completion. Do not infer a score "
    "from filing an issue, or claim technical success from a good experience."
)


def build_direct_review_turn(
    task: str, reply: str, patch: str, *, task_deadline_reached: bool = False
) -> str:
    """Spec-0084/T2: terminal subjective review uses the same scale, with zero-report allowed."""
    return "\n\n".join(
        [
            "<direct_review>",
            "The actor has stopped and its outputs are frozen. Inspect only the supplied reply "
            "and read-only snapshot. Do not send a follow-up, change files, execute tests, invent "
            "evidence, or claim that official verification passed. Separate goal fulfillment, "
            "experience, causal attribution and improvement opportunities. A failed task alone "
            "does not prove a harness bug. If the result is satisfactory and there is no issue, "
            "return an empty opportunities array. A nonblocking suggestion is kind=feature; "
            "an unresolved failure with uncertain cause is kind=diagnostic and must say the cause "
            "is unconfirmed. Never invent a complaint to fill the array.",
            *(
                [
                    "The declared task time limit ended execution. Review the partial result; "
                    "do not infer why the task remained incomplete."
                ]
                if task_deadline_reached
                else []
            ),
            EXPERIENCE_SCALE,
            f"<task>\n{task}\n</task>",
            f"<harness_reply>\n{reply}\n</harness_reply>",
            f"<patch_excerpt>\n{patch[:12000] or '(no patch available)'}\n</patch_excerpt>",
            'Return JSON: {"task_assessment":"fulfilled|unfulfilled|unknown", "feedback":"...", '
            '"score":<integer 1-4 or null if unmeasured>, "reason":"...", '
            '"attribution":{"status":"confirmed|uncertain|unknown", "claims":[]}, '
            '"opportunities":[{"kind":"feature|diagnostic", "title":"...", "body":"..."}]}',
            "</direct_review>",
        ]
    )


def build_rating_turn(
    task: str, history_lines: list[str], state: State, *, task_deadline_reached: bool = False
) -> str:
    """Rate the experience; after the task deadline, allow one optional issue."""
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    fields = '"score": <integer 1-4>, "reason": "<one short sentence, in your own voice>"'
    if task_deadline_reached:
        fields += ', "issue": "<observed problem worth reporting, or empty>"'
    return "\n\n".join(
        [
            "<rate_experience>",
            "The session is OVER. Step back and rate how this WHOLE experience felt to "
            "YOU as this person, on a 1–4 satisfaction scale (judge by your own bar):",
            EXPERIENCE_SCALE,
            "ATTRIBUTION: If you interrupted/stopped the tool yourself, do not phrase the "
            "reason as 'it kept interrupting' — that was you. Rate the underlying progress "
            "(or lack of it), not your own stop button.",
            *(
                [
                    "The declared task time limit ended the interaction. Review only the evidence "
                    "below. You may report a problem in your own words. Leave issue empty if "
                    "there is nothing to report. The deadline alone does not establish a Harness bug."
                ]
                if task_deadline_reached
                else []
            ),
            f"<task>\n{task}\n</task>",
            f"<history>\n{hist}\n</history>",
            f"<mood>\n{_mood_tag(state)}\n</mood>",
            "Return EXACTLY ONE JSON object and nothing else: {" + fields + "}",
            "</rate_experience>",
        ]
    )
