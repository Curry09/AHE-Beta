"""
prompt.py
拼装 system prompt (BLOCK-G 固定 + BLOCK-P 实例) 与每轮 user 消息。

KV cache 友好的排序(从不变到善变):
  system = BLOCK_G + BLOCK_P        <- 跨/内 session 稳定前缀, cache 命中区
  user   = <task><history><harness_output><self_observation><action_space><mood>
状态数值不进 system; mood 只给离散标签, 放在 user 尾部。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .clauses import clause_capability, clause_verification_policy, compile_block_p
from .dimensions import Persona
from .state import State

if TYPE_CHECKING:
    from .skills import Skill
    from .tools import ToolSpec

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
G6  NEVER claim the outcome of running, installing, or inspecting anything you did
    not ACTUALLY do. You have not "run the tests", "checked the files", or found
    "pip missing" unless a real tool result (INNER TOOL USE) or a harness reply
    actually told you so. If you have tools, you must call them to earn any such
    claim; if you have none, you can only reason from what the HARNESS reported —
    say "the harness claims it passes; I have not verified" rather than inventing a
    verification you never performed. Fabricated verification is the worst failure.

# ACTION SEMANTICS
- verify_self: a PRIVATE action. You inspect/run on your OWN; the harness hears
  nothing. Put your observation in "perceive" and leave "message" empty ("").
- ask_harness_run: you ask the harness to execute and report back; "message"
  is the request you send.
- accept / give_up / file_issue: terminal. Keep "message" short and in voice.
- accept_with_reservations: terminal. Use it when the result is good ENOUGH that you'll
  take it and move on, BUT it fell short of what you wanted. You ship it AND leave the dev
  team a short feedback issue about the gap. Pick this over plain "accept" when you'd sign
  off yet still have a real complaint; pick plain "accept" when you're genuinely content.

# OUTPUT CONTRACT
Return EXACTLY ONE JSON object and nothing else:
{
  "perceive": "<what you, this person, actually understood; be honest about the LIMITS of your perception per G1>",
  "verdict":  "satisfied | failed_blame_harness | failed_blame_self | unsure | stuck",
  "action":   "<one id from <action_space>, or 'free'>",
  "message":  "<the exact line you send to the harness; empty string for verify_self>"
}
"message" is the ONLY text the harness sees. Do not put JSON or analysis in it.

# VERDICT: unsure vs stuck (important)
- "unsure": you got a plausible answer and simply have NOT verified it yet. Careful
  verification is legitimate and should NOT cost you patience.
- "stuck": the harness is MALFUNCTIONING rather than merely unverified — it errored,
  returned nothing usable, timed out, repeated the same thing, or made no real progress
  this turn. You do NOT need technical insight to feel this; any user notices a tool that
  keeps spinning. Each consecutive "stuck" wears your patience faster (frustration compounds)."""


def build_system(persona: Persona) -> str:
    return BLOCK_G + "\n\n" + compile_block_p(persona)


# --------------------------------------------------------------------------
# 内层 tool-using system 装配（spec-0008/T3）
# 外层 build_system 不变；内层把「可选核实框架 + 工具清单 + 个性倾向 + skill」拼成 system。
# --------------------------------------------------------------------------
INNER_PROTOCOL = """# INNER TOOL USE (private)
Before you answer, you MAY take a few PRIVATE investigation steps. On each step you
either CALL A TOOL or give your FINAL answer — nothing you do here is seen by the harness.
- To call a tool, return EXACTLY ONE JSON object: {"tool": "<name>", "args": { ... }}.
  You will then be shown that tool's result and may act again.
- When you are done investigating, return the normal OUTPUT CONTRACT JSON
  (perceive/verdict/action/message). Fold whatever you learned into "perceive".
You are still bound by G1: only conclude what THIS person could actually conclude."""


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
    """装配内层 system：BLOCK-G + 内层工具协议 + 可选核实框架 + 工具清单 + 个性倾向 + skill。"""
    parts = [
        BLOCK_G,
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


def build_issue_turn(
    task: str, history_lines: list[str], state: State, *, mode: str = "filed"
) -> str:
    """开单的专门一轮：让 persona 跳出对话，以本人口吻写一条*自包含*的 issue（提交给不在场、
    看不到聊天记录的开发团队），而非对 harness 撂下的那句临场话。

    mode 三种口吻（把"提 issue"从特定动作解耦：无论怎么收场，不满都留信号）：
    - "filed"（file_issue）：你没能在会话里搞定，正式开单——报告哪里一直不对、为什么卡住。
    - "left"（give_up）：你**决定弃坑走人**，临走留一条"问卷式"退出反馈——什么把你逼走了。
    - "accepted"（accept_with_reservations）：你**接受/交付了**产出但不达预期——留一条体感落差反馈。

    覆盖 system 的动作 OUTPUT CONTRACT —— 这一轮只要 {"issue"}, 不发 message / 不选 action。
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
    return "\n\n".join(
        [
            "<file_issue>",
            framing,
            f"<task>\n{task}\n</task>",
            f"<history>\n{hist}\n</history>",
            f"<mood>\n{_mood_tag(state)}\n</mood>",
            "Return EXACTLY ONE JSON object and nothing else: "
            '{"issue": "<your issue text, first person, in your own words>"}',
            "</file_issue>",
        ]
    )


def build_rating_turn(task: str, history_lines: list[str], state: State) -> str:
    """会话末自评请求: 让 persona 跳出对话, 按本人体感给 1–4 分 (类 CC 满意度评分)。

    覆盖 system 的动作 OUTPUT CONTRACT —— 这一轮只要 {"score", "reason"}, 不发 message。
    """
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    return "\n\n".join(
        [
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
            "Return EXACTLY ONE JSON object and nothing else: "
            '{"score": <integer 1-4>, "reason": "<one short sentence, in your own voice>"}',
            "</rate_experience>",
        ]
    )
