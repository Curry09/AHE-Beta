"""
prompt.py
拼装薄 base system（角色/感知边界 + BLOCK-P）与每轮分阶段 user 消息。

KV cache 友好的排序(从不变到善变):
  system = BASE_USER_SYSTEM + BLOCK_P <- 跨/内 session 稳定前缀, cache 命中区
  user   = <task><history><harness_output><self_observation><mood>
           act 阶段才额外带 <action_space>，避免 judge/intent 先看菜单倒推意图。
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

BASE_USER_SYSTEM = """# ROLE
You are simulating a real human software developer who is using an AI coding
assistant through a terminal. You are the USER, never the assistant. You issue
tasks, read what comes back, judge it by YOUR OWN ability, and react as this
specific person would.

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
# 内层 tool-using system 装配（spec-0008/T3 + spec-0031）
# 内层只拼薄 base + private tool 协议 + 工具清单 + 个性倾向 + skill；阶段输出契约仍来自 user prompt。
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
    """装配内层 system：薄 base + 内层工具协议 + 可选核实框架 + 工具清单 + 个性倾向 + skill。"""
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


# 开局一轮附加：让 persona 自己给这任务估个“分量”，框架据此在耐心基线上叠加一次性小浮动。
# 只在 OPENING 追加（其余轮忽略该字段）——同一个人接不同任务的起始耐心本就不同（见 state.apply_task_load）。
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


def _main_context_parts(
    task: str,
    history_lines: list[str],
    harness_output: str,
    action_space: list[str],
    state: State,
    *,
    help_text: str = "",
    include_action_space: bool,
) -> list[str]:
    """主 decide 共用上下文（不含分步输出契约）。

    <action_space> 只属于 act 收敛阶段；judge / intent 不看当前菜单，避免先按按钮倒推
    判断和意愿。等待时长只靠 <history> 的 [+Ns]。
    """
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    ho = harness_output.strip() if harness_output else "(empty)"
    parts: list[str] = []
    parts.append(f"<task>\n{task}\n</task>")
    if help_text.strip():
        parts.append(f"<harness_help>\n{help_text.strip()}\n</harness_help>")
    parts.append(f"<history>\n{hist}\n</history>")
    parts.append(f"<harness_output>\n{ho}\n</harness_output>")
    if state.pending_self_obs:
        parts.append(f"<self_observation>\n{state.pending_self_obs}\n</self_observation>")
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
    appraise_task: bool = False,
) -> str:
    """主 loop · Judge：只评现状（perceive + verdict）；意愿留给 intent。"""
    parts = ["<main_judge>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            action_space,
            state,
            help_text=help_text,
            include_action_space=False,
        )
    )
    parts.append(
        "# JUDGE — how things stand NOW (not what you will do next)\n"
        "First write what you genuinely perceived in your own words, including the limits "
        "of what you can tell from the visible evidence. Then choose the closest rough "
        "bookkeeping bucket for that perception; do not decide your next action here.\n"
        "Buckets:\n"
        "- satisfied: you personally think this is good enough.\n"
        "- failed_blame_harness: you think the assistant/tool caused the failure.\n"
        "- failed_blame_self: you think your own request, limits, or choices caused the failure.\n"
        "- unsure: you are not convinced yet.\n"
        "- stuck: the tool interaction itself feels blocked or not making usable progress.\n"
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"perceive": "<what you actually understood>", '
        '"verdict": "satisfied | failed_blame_harness | failed_blame_self | unsure | stuck"}'
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
    verdict: str,
    perceive: str = "",
) -> str:
    """主 loop · Intent：开放意愿（可超菜单）。"""
    parts = ["<main_intent>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            action_space,
            state,
            help_text=help_text,
            include_action_space=False,
        )
    )
    parts.append(f"<judgment>\n{verdict}\nyour notes: {perceive.strip() or '(none)'}\n</judgment>")
    parts.append(_intent_options_block())
    parts.append(
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"intent": "<free text: what you WANT next>"}'
    )
    parts.append("</main_intent>")
    return "\n\n".join(parts)


def build_main_act_turn(
    task: str,
    history_lines: list[str],
    harness_output: str,
    action_space: list[str],
    state: State,
    *,
    help_text: str = "",
    verdict: str,
    perceive: str = "",
    intent: str,
) -> str:
    """主 loop · Act：把开放 intent 收敛到 action_space；兑不了就兜底并 gap=true。"""
    parts = ["<main_act>"]
    parts.extend(
        _main_context_parts(
            task,
            history_lines,
            harness_output,
            action_space,
            state,
            help_text=help_text,
            include_action_space=True,
        )
    )
    parts.append(f"<judgment>\n{verdict}\nyour notes: {perceive.strip() or '(none)'}\n</judgment>")
    parts.append(f"<intent>\n{intent.strip() or '(none)'}\n</intent>")
    parts.append(
        "# MENU — only ids in <action_space> exist right now\n"
        "This is the convergence step: map <intent> to the closest id, or use "
        'action:"free" with a message if no id really fits (the framework may classify it).\n'
        "Local action semantics:\n"
        "- verify_self: private; inspect/run on your own if you have tools; the harness hears nothing.\n"
        "- ask_harness_run / request_evidence / give_feedback / refine_request / grant_autorun: "
        "send the exact line in message.\n"
        "- accept / accept_with_reservations / give_up / file_issue: terminal outcomes; keep "
        "message short and in your voice.\n"
        "Before any accept-like terminal outcome, make sure you actually have a basis in "
        "<history>, <harness_output>, or private tool results; do not accept an error, timeout, "
        "empty output, or unverified claim as if it worked.\n"
        "If the chosen id is only a fallback that does NOT really satisfy intent, set gap=true; "
        "otherwise gap=false. Honor <mood>.\n"
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"action": "<id from <action_space>, or free>", '
        '"message": "<exact line to the harness; empty for verify_self>", '
        '"gap": <true if fallback; else false>}'
    )
    parts.append("</main_act>")
    return "\n\n".join(parts)


def _activity_bullets(items: list | None, *, limit: int = 12) -> str:
    """把 progress / 上轮活动收成短标题列表；空则空串。"""
    bullets: list[str] = []
    for item in list(items or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            bullets.append(f"- {text}")
    return "\n".join(bullets)


# 心跳等待：过程判断 → 开放意愿(intent) → 菜单动作(act) 收敛；act 自报 gap 时记 WAIT_GAP。
# judgment 只评「在干什么」；intent 自由文本；菜单四按钮才是能力边界。
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
) -> list[str]:
    """等待轮共用上下文：帮助文本 / 任务 / 历史 / 活动条 / 墙钟 / mood。不含输出契约。"""
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    parts: list[str] = []
    if help_text.strip():
        parts.append(f"<harness_help>\n{help_text.strip()}\n</harness_help>")
    parts.append(f"<task>\n{task}\n</task>")
    parts.append(f"<history>\n{hist}\n</history>")
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
        "The next act step will handle any mapping or gap."
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
) -> str:
    """3 跳模式·第 1 跳：只评过程内容（不对路 / 合预期 / 看不清），不选 intent/动作。"""
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
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"perceive": "<what you notice in the activity vs your task, honestly>", '
        '"judgment": "on_track | off_track | unclear"}'
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
    judgment: str,
    perceive: str = "",
) -> str:
    """3 跳模式·第 2 跳：已有 judgment，只表达真实意愿 intent（开放文本）。"""
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
        )
    )
    parts.append(f"<judgment>\n{judgment}\nyour notes: {perceive.strip() or '(none)'}\n</judgment>")
    parts.append(_intent_options_block())
    parts.append(
        "Return EXACTLY ONE JSON object and nothing else:\n"
        '{"intent": "<free-text wish in your voice — what you want right now>"}'
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
    judgment: str,
    perceive: str = "",
    intent: str,
) -> str:
    """末跳：把开放 intent 收敛到菜单；兑不了就兜底并 gap=true（框架记 WAIT_GAP）。"""
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
        )
    )
    parts.append(f"<judgment>\n{judgment}\nyour notes: {perceive.strip() or '(none)'}\n</judgment>")
    parts.append(f"<intent>\n{intent.strip() or '(none)'}\n</intent>")
    parts.append(
        "# MENU — only these actions exist right now (this is where wishes converge)\n"
        "- keep_waiting: leave it running.\n"
        "- send_message: send another message while it is still running "
        "(inside the harness — ordinary text or slash forms from <harness_help>, "
        "e.g. /btw … /status; whether it handles that message is the harness's job).\n"
        "- interrupt: stop the current run like Ctrl+C (outside the chat).\n"
        "- give_up: abandon and walk away.\n"
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
        '"gap": <true if this is only a fallback that does not satisfy intent; else false>}'
    )
    parts.append("</waiting_act>")
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

    本阶段只要 {"issue"}，不发 message / 不选 action。
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
    # 诉求型开单也合法：若真正困扰你的不是"坏了"而是"这工具缺了你干活需要的东西"，就把这条 issue
    # 写成对你所需的请求（用你自己的话，只能出自你本次会话的真实体验），而不是硬套成 bug。不点名任何
    # 具体功能——要什么由你自己想，绝不照搬这段说明里的措辞。
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


def build_rating_turn(task: str, history_lines: list[str], state: State) -> str:
    """会话末自评请求: 让 persona 跳出对话, 按本人体感给 1–4 分 (类 CC 满意度评分)。

    本阶段只要 {"score", "reason"}，不发 message / 不选 action。
    """
    hist = "\n".join(history_lines) if history_lines else "(empty)"
    return "\n\n".join(
        [
            "<rate_experience>",
            "The session is OVER. Step back and rate how this WHOLE experience felt to "
            "YOU as this person, on a 1–4 satisfaction scale (judge by your own bar):",
            "  1 = bad   (frustrating; gave up / had to file an issue)",
            "  2 = poor  (did not really get what I needed)",
            "  3 = ok    (got there, but with friction)",
            "  4 = good  (smooth; satisfied)",
            "ATTRIBUTION: If you interrupted/stopped the tool yourself, do not phrase the "
            "reason as 'it kept interrupting' — that was you. Rate the underlying progress "
            "(or lack of it), not your own stop button.",
            f"<task>\n{task}\n</task>",
            f"<history>\n{hist}\n</history>",
            f"<mood>\n{_mood_tag(state)}\n</mood>",
            "Return EXACTLY ONE JSON object and nothing else: "
            '{"score": <integer 1-4>, "reason": "<one short sentence, in your own voice>"}',
            "</rate_experience>",
        ]
    )
