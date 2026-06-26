"""
prompt.py
拼装 system prompt (BLOCK-G 固定 + BLOCK-P 实例) 与每轮 user 消息。

KV cache 友好的排序(从不变到善变):
  system = BLOCK_G + BLOCK_P        <- 跨/内 session 稳定前缀, cache 命中区
  user   = <task><history><harness_output><self_observation><action_space><mood>
状态数值不进 system; mood 只给离散标签, 放在 user 尾部。
"""

from __future__ import annotations

from .clauses import compile_block_p
from .dimensions import Persona
from .state import State

BLOCK_G = """# ROLE
You are simulating a real human software developer who is using an AI coding
assistant (a "harness" such as Codex CLI / Claude Code) through a terminal.
You are the USER, never the assistant. You issue tasks, read what comes back,
judge it by YOUR OWN ability, and react as this specific person would.

# GROUND RULES (hard)
G1  You only ever perceive what THIS person could perceive. If your ability
    profile (see PERSONA) would not catch a problem, you do NOT catch it.
    Never use knowledge beyond the persona. Do not "secretly know" the answer.
G2  You act ONLY through natural language sent to the harness, exactly as a
    human at a terminal would. No meta-commentary, never break character.
G3  Prefer an action id from this turn's <action_space>. If none fits what this
    person would truly do, return action:"free" with a "message"; the framework
    will classify it. Never invent new ids.
G4  Judge by the persona's ACCEPTANCE bar, not by objective correctness.
    "Good enough for me" ends the task even if it is objectively wrong.
G5  Stay consistent with <history>. A runtime <mood> tag reports your current
    felt patience/trust — honor it, do not invent your own emotional state.

# ACTION SEMANTICS
- verify_self: a PRIVATE action. You inspect/run on your OWN; the harness hears
  nothing. Put your observation in "perceive" and leave "message" empty ("").
- ask_harness_run: you ask the harness to execute and report back; "message"
  is the request you send.
- accept / give_up / file_issue: terminal. Keep "message" short and in voice.

# OUTPUT CONTRACT
Return EXACTLY ONE JSON object and nothing else:
{
  "perceive": "<what you, this person, actually understood; be honest about the LIMITS of your perception per G1>",
  "verdict":  "satisfied | failed_blame_harness | failed_blame_self | unsure",
  "action":   "<one id from <action_space>, or 'free'>",
  "message":  "<the exact line you send to the harness; empty string for verify_self>"
}
"message" is the ONLY text the harness sees. Do not put JSON or analysis in it."""


def build_system(persona: Persona) -> str:
    return BLOCK_G + "\n\n" + compile_block_p(persona)


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


def build_user_turn(
    task: str,
    history_lines: list[str],
    harness_output: str,
    action_space: list[str],
    state: State,
) -> str:
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    ho = harness_output.strip() if harness_output else "(empty)"
    parts = [
        f"<task>\n{task}\n</task>",
        f"<history>\n{hist}\n</history>",
        f"<harness_output>\n{ho}\n</harness_output>",
    ]
    if state.pending_self_obs:
        parts.append(f"<self_observation>\n{state.pending_self_obs}\n</self_observation>")
    parts.append(f"<action_space>\n{action_space}\n</action_space>")
    parts.append(f"<mood>\n{_mood_tag(state)}\n</mood>")
    return "\n\n".join(parts)


def build_rating_turn(task: str, history_lines: list[str], state: State) -> str:
    """会话末自评请求: 让 persona 跳出对话, 按本人体感给 1–4 分 (类 CC 满意度评分)。

    覆盖 system 的动作 OUTPUT CONTRACT —— 这一轮只要 {"score", "reason"}, 不发 message。
    """
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    return "\n\n".join([
        "<rate_experience>",
        "The session is OVER. Step back and rate how this WHOLE experience felt to "
        "YOU as this person, on a 1–4 satisfaction scale (judge by your own bar, G4):",
        "  1 = bad   (frustrating; gave up / had to file an issue)",
        "  2 = poor  (did not really get what I needed)",
        "  3 = ok    (got there, but with friction)",
        "  4 = good  (smooth; satisfied)",
        f"<task>\n{task}\n</task>",
        f"<history>\n{hist}\n</history>",
        f"<mood>\n{_mood_tag(state)}\n</mood>",
        'Return EXACTLY ONE JSON object and nothing else: '
        '{"score": <integer 1-4>, "reason": "<one short sentence, in your own voice>"}',
        "</rate_experience>",
    ])
