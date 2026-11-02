"""
loop.py
控制信封主循环 —— 把所有部件按"三层认知主干 + 状态层"编排起来。

每轮(turn)流水线:
  ① 物理接收     harness_output (文本)                  (harness_adapter / scenarios)
  ② 派生动作空间  phase ∩ cap ∩ authz (∪ 终止/accept)   (action_space, 纯代码)
  ③ 主观三层      persona LLM -> {perceive,verdict,action,message}  (persona_client)
  ④ resolve      自由产出归类 + 越权投影 + channel 校验  (action_space.resolve)
  ⑤ 状态写回      只吃主观 verdict                        (state.apply_verdict)
  ⑥ 终止判定      Effect.TERMINATE -> 记 end_reason 并 break
  ⑦ 路由          EMIT -> 驱动 harness 出下一轮；终止动作 -> 收场

本轮纯主观(不实现客观真值线):
- harness 只回文本, 无 gold / exit_code; bug 体现在文本里, 由 persona 凭能力识别。
- 状态与体感全程只依赖主观 verdict / trust, 不读任何客观真值。
- 用户自己的读文件/跑命令/看 diff 等核实发生在 AgenticPersonaClient 的私有内层工具循环，
  作为 judge 阶段形成 perceive/verdict 的证据；不是外层 action。
- 感知不在框架侧过滤: harness 文本原样喂入 persona LLM, 由 prompt(G1)+persona 档位约束"只在能力内感知"。
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ahe_beta.usage import set_usage_context

from .action_space import ActionResolutionError, derive_action_space, resolve_action
from .actions import CATALOG, Channel, Effect, Executor, Phase
from .dimensions import Persona
from .feeling import FeelingScore, derive_feeling, experience_feedback, parse_feeling_llm
from .goals import GoalLedger, audit_acceptance_basis, audit_goal_fields
from .persona_client import (
    PersonaClient,
    PersonaProtocolError,
    drain_call_traces,
    drain_protocol_events,
)
from .prompt import (
    WAITING_JUDGMENTS,
    build_issue_turn,
    build_main_act_turn,
    build_main_final_check_turn,
    build_main_intent_turn,
    build_main_judge_turn,
    build_main_reintent_turn,
    build_main_rejudge_turn,
    build_rating_turn,
    build_system,
    build_waiting_act_turn,
    build_waiting_intent_turn,
    build_waiting_judge_turn,
)
from .state import (
    VERDICTS,
    Coef,
    State,
    apply_task_load,
    apply_verdict,
    init_state,
    make_coef,
)


@dataclass
class TurnLog:
    turn: int
    phase: str
    action_space: list
    perceive: str
    verdict: str
    action: str
    message: str
    executor: str
    channel: str
    patience: int
    trust: str
    harness_output: str = ""
    # 与 harness_output 配对：该轮 persona 所看回复的 harness 内层过程流（{kind,text} 序列）。
    # 观测层展开时才用；persona 只感知 harness_output（最终答案），不吃 steps。
    harness_steps: list = field(default_factory=list)
    # 自上次用户决策以来的 harness stdout 可见事件（reply/progress/status/ack/error）；
    # 按观察顺序保留，不做 request/reply 配对推断。
    harness_events: list = field(default_factory=list)
    # 用户 agent 本决策触发的原始 LLM 调用（system/user/raw/steps）；先全量，后续再筛。
    persona_trace: list = field(default_factory=list)
    # Spec-0024/T6：请求–回复配对（观测用；不改 harness 线协议）。
    # utterance_id：本拍外发的用户指令句柄；delivery=open|queued；queued 时 queued_behind=当前 open。
    # answers_*：本拍 harness_output 所应答的那条 utterance（及正文预览）。
    utterance_id: str = ""
    delivery: str = ""
    queued_behind: str = ""
    answers_utterance_id: str = ""
    answers_said: str = ""
    # Explicit user-goal control: compact before/after snapshots plus the model's
    # declared change/effect.  The complete append-only event history lives on
    # SessionResult.goal_ledger.
    goal_before: dict = field(default_factory=dict)
    # Perception-level goal appraisal.  This is deliberately separate from goal_updates:
    # reading a goal's progress guides the next decision but does not mutate the ledger.
    goal_reading: list[dict] = field(default_factory=list)
    # Intent-level binding: which goals this decision is trying to move, and how.
    target_goal_ids: list[str] = field(default_factory=list)
    expected_progress: str = ""
    goal_updates: list[dict] = field(default_factory=list)
    goal_after: dict = field(default_factory=dict)
    goal_effect: dict = field(default_factory=dict)
    # Soft content/integrity audit for goal_reading, targets, expected progress and effect.
    # Warnings are observational and never turn a valid user decision into a protocol error.
    goal_field_audit: dict = field(default_factory=dict)
    # Terminal-only explanation of the persona's acceptance basis.
    acceptance_basis: dict = field(default_factory=dict)


@dataclass
class _UtteranceLedger:
    """局内用户→harness 指令账本：给每条外发编号，reply 挂回它所关闭的 open 指令。

    Spec-0024/T6：persona 仍可能「看见内容才知真相」；落盘/结构综合时间线必须显式配对。
    """

    _seq: int = 0
    open_id: str | None = None
    said: dict[str, str] = field(default_factory=dict)
    pending_answers_id: str | None = None

    def alloc(self, text: str) -> str:
        self._seq += 1
        uid = f"u{self._seq}"
        self.said[uid] = text
        return uid

    def mark_open(self, uid: str) -> None:
        self.open_id = uid

    def clear_open(self) -> None:
        """放弃当前 open（如 give_up），不产生 answers。"""
        self.open_id = None

    def close_open_as_answered(self) -> str | None:
        """当前 open 收到 reply/interrupt 回执：记入 pending，供下一拍 TurnLog 写入 answers。"""
        answered = self.open_id
        self.pending_answers_id = answered
        self.open_id = None
        return answered

    def consume_pending_answers(self) -> tuple[str, str]:
        uid = self.pending_answers_id or ""
        self.pending_answers_id = None
        preview = (self.said.get(uid) or "") if uid else ""
        if len(preview) > 120:
            preview = preview[:120] + "…"
        return uid, preview


@dataclass
class SessionResult:
    persona_id: str
    end_reason: str
    turns: list[TurnLog] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)  # 给开发者的行为反馈信号(纯主观派生)
    issue_artifact: str | None = None
    # 中途 report_issue tool 记下的正文（不终止会话）；收尾与 issue_artifact 一并交 tracker。
    issue_notes: list[str] = field(default_factory=list)
    feeling: FeelingScore | None = None  # 训练信号: persona LLM 会话末自评 (1–4)
    feeling_derived: FeelingScore | None = None  # 独立诊断，不填补自评缺测
    experience: dict = field(default_factory=dict)
    terminal_issue_mode: str | None = None
    # 已收到但尚未进入 TurnLog 的 harness 回复(harness 回复要等下一轮 TurnLog 才随
    # harness_output 落日志, 这里先行暴露给观测层实时展示; 下一条 TurnLog 追加时清空)
    pending_harness_output: str | None = None
    pending_harness_steps: list | None = None  # 与 pending_harness_output 配对的内层过程流
    pending_harness_events: list | None = None  # 与 pending_harness_output 同窗口的 stdout 可见事件
    # 局末不挂某一 Turn 的用户 agent 调用（file_issue 正文 / 体感评分）。
    persona_tail: list = field(default_factory=list)
    # Spec-0048：评估器协议异常与 harness 任务失败分轨；invalid 结果不得计入正常通过率。
    evaluation_status: str = "valid"
    evaluation_error: dict | None = None
    # 轻量协议分轨：保留 evaluation_status 的旧兼容语义，同时让消费者知道是否只是
    # persona 输出契约失败，而不是把它误读成用户 give_up 或客观代码失败。
    interaction_status: str = "completed"
    # Every failed contract attempt is retained separately from persona_tail so an
    # auditor can distinguish malformed output, recovery, and the eventual outcome.
    protocol_events: list[dict] = field(default_factory=list)
    # Explicit goal ledger snapshot and terminal claim.  Objective evaluation remains separate.
    goal_ledger: dict = field(default_factory=dict)
    goal_acceptance: dict | None = None
    # Final non-gating integrity audit; per-turn audits live on TurnLog.
    goal_audit: dict = field(default_factory=dict)
    terminal_audit: dict = field(default_factory=dict)


MAX_TURNS = 24

# 阻塞 send 路径：墙钟超过此值额外耗一点耐心（防无限干等）。心跳路径用 history [+Ns] + 有条件耗心。
_EXTREME_WAIT_SEC = 480.0

# 框架自有的 harness 失败哨兵前缀：route 在 harness.send() 崩溃/超时时回填此串（见下），原样喂给
# 用户 agent 感知。它不再触发任何框架侧动作门控——面对崩溃是否验收/开单/走人，由有判断力的模型自判
# （prompt G6 + 终止时机条主导）；框架只负责把失败如实surfacing，不炸整局、也不替模型下结论。
HARNESS_ERROR_PREFIX = "[harness error] "
_HARNESS_TERMINAL_STATUSES = frozenset({"timed_out", "crashed"})

# 事件等待（用户等待中的主动权）：
#   AwaitEvent = poll 直到 harness reply（唤醒主 loop）或到心跳阈值（一次性等待决策）。
#   心跳是一次性动作（含 keep_waiting）——做完即结束，回到 AwaitEvent；不为「认领上一笔 send」
#   在心跳里继续 poll。
#   persona 侧仍可能「看见 reply 内容才知发生了什么」；观测侧用 _UtteranceLedger 显式配对
#   （Spec-0024/T6：heard.answers → utterance）。
_HEARTBEAT_SEC = 90.0
# 心跳唤醒次数硬上限（兜底防病态：模型一直 keep_waiting 而 harness 永不回）。到顶即强制放弃。
_MAX_HEARTBEATS = 12
# A malformed persona reply is not a user give-up. Allow one warning heartbeat
# to keep listening; repeated failures then stop safely with an auditable status.
_MAX_PROTOCOL_STALL_HEARTBEATS = 2
# 等待菜单：内 = send_message；外 = interrupt（Ctrl+C）+ give_up；keep_waiting = 决定继续等。
WAITING_ACTIONS = ["keep_waiting", "send_message", "interrupt", "give_up"]


def _supports_heartbeat(harness) -> bool:
    """真实子进程句柄：统一写 + poll + 外 interrupt/shutdown；Fake/Scripted 无需心跳。"""
    has_write = hasattr(harness, "write_message") or hasattr(harness, "begin")
    return has_write and all(hasattr(harness, m) for m in ("poll", "interrupt", "shutdown"))


def _harness_terminal_status(harness) -> str:
    """读取 launcher 给出的机器可判终态；绝不从面向人的回复文本猜。"""
    status = str(getattr(harness, "last_request_status", "") or "")
    return status if status in _HARNESS_TERMINAL_STATUSES else ""


def _write_harness_message(harness, message: str) -> None:
    """统一 stdin 写（Spec-0036）：优先 write_message，兼容旧 begin/emit_message 别名。"""
    for name in ("write_message", "begin", "emit_message"):
        fn = getattr(harness, name, None)
        if callable(fn):
            fn(message)
            return
    raise AttributeError("harness has no write_message/begin/emit_message")


def _take_persona_calls(client: PersonaClient, role: str) -> list[dict]:
    """drain client 上刚结束的原始调用，打上 role 标签（供 TurnLog / persona_tail）。"""
    out: list[dict] = []
    for call in drain_call_traces(client):
        tagged = dict(call)
        tagged["role"] = role
        out.append(tagged)
    return out


def _take_protocol_events(client: PersonaClient, result: SessionResult) -> None:
    """Drain protocol evidence into the session; never raise on an audit side channel."""
    for event in drain_protocol_events(client):
        if isinstance(event, dict):
            result.protocol_events.append(dict(event))


_PRIVATE_EVIDENCE_MAX_ITEMS = 8
_PRIVATE_EVIDENCE_MAX_ITEM_CHARS = 650
_PRIVATE_EVIDENCE_MAX_CMD_CHARS = 160


def _phase_stage_label(*, phase: str, role: str) -> str:
    stage = role.rsplit("_", 1)[-1] if "_" in role else role
    if phase == "waiting":
        where = "during_wait"
    elif phase == "opening":
        where = "opening"
    else:
        where = "after_reply"
    return f"{where}/{stage}"


def _one_line(text: object, *, limit: int) -> str:
    out = " ".join(str(text or "").split())
    if len(out) > limit:
        return out[: max(0, limit - 3)] + "..."
    return out


def _tool_action_summary(text: str) -> str:
    raw_full = _one_line(text, limit=4000)
    m = re.match(r"^(\w+)\s+(\{.*\})$", raw_full)
    if not m:
        return _one_line(text, limit=_PRIVATE_EVIDENCE_MAX_CMD_CHARS)
    name, arg_s = m.groups()
    try:
        args = json.loads(arg_s)
    except json.JSONDecodeError:
        return _one_line(text, limit=_PRIVATE_EVIDENCE_MAX_CMD_CHARS)
    if name in {"read_file", "write_file"} and args.get("path"):
        return f"{name} `{_one_line(args['path'], limit=90)}`"
    if name == "run_shell" and args.get("cmd"):
        return f"run_shell `{_one_line(args['cmd'], limit=120)}`"
    if name == "report_issue" and args.get("body"):
        return "report_issue `<body>`"
    return _one_line(text, limit=_PRIVATE_EVIDENCE_MAX_CMD_CHARS)


def _tool_result_summary(text: str) -> str:
    try:
        obj = json.loads(str(text or ""))
    except json.JSONDecodeError:
        return _one_line(text, limit=220)
    bits: list[str] = []
    if "returncode" in obj:
        bits.append(f"returncode={obj.get('returncode')}")
    for key in ("stdout", "stderr", "error", "content"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            bits.append(f"{key}: {_one_line(val, limit=180)}")
            break
    return "; ".join(bits)[:240]


def _record_private_evidence(*, state: State, calls: list[dict], phase: str) -> None:
    """把本轮 private tool-use 压成用户自己的跨轮短记忆。"""
    for call in calls:
        steps = [
            s
            for s in (call.get("steps") or [])
            if isinstance(s, dict) and s.get("kind") in {"tool", "tool_result", "tool_error"}
        ]
        if not steps:
            continue
        tools = [
            _tool_action_summary(str(s.get("text") or "")) for s in steps if s.get("kind") == "tool"
        ]
        results = [
            _tool_result_summary(str(s.get("text") or ""))
            for s in steps
            if s.get("kind") in {"tool_result", "tool_error"}
        ]
        parsed = call.get("parsed") if isinstance(call.get("parsed"), dict) else {}
        perceive = _one_line(parsed.get("perceive", ""), limit=360)
        state.private_evidence_seq += 1
        label = _phase_stage_label(phase=phase, role=str(call.get("role") or "unknown"))
        lines = [f"[E{state.private_evidence_seq} {label}]"]
        if tools:
            lines.append("Private tools: " + "; ".join(tools[:4]) + ".")
        if perceive:
            lines.append("Conclusion: " + perceive)
        elif results:
            lines.append("Observed: " + results[0])
        item = "\n".join(lines)
        if len(item) > _PRIVATE_EVIDENCE_MAX_ITEM_CHARS:
            item = item[: _PRIVATE_EVIDENCE_MAX_ITEM_CHARS - 3] + "..."
        if state.private_evidence is None:
            state.private_evidence = []
        state.private_evidence.append(item)
        if len(state.private_evidence) > _PRIVATE_EVIDENCE_MAX_ITEMS:
            del state.private_evidence[:-_PRIVATE_EVIDENCE_MAX_ITEMS]


def _resolve_gap(ret: dict) -> bool:
    """act 自报 gap；非法缺省 → False。"""
    gap_raw = ret.get("gap")
    return gap_raw is True or (
        isinstance(gap_raw, str) and gap_raw.strip().lower() in ("true", "1", "yes")
    )


def _resolve_waiting(ret: dict) -> tuple[str, str, bool]:
    """把心跳唤醒的自由产出归到 WAITING_ACTIONS + message + gap。

    非法/缺省一律安全落到 keep_waiting（绝不擅自替用户放弃或打断）。
    send_message 缺正文 → 退回 keep_waiting（不 fabricate、不外发空串）。
    gap：由 act 步自报——intent 开放，收敛后若只能兜底、未真正兑现意愿则 True。
    """
    action = str(ret.get("action", "")).strip()
    if action not in WAITING_ACTIONS:
        action = "keep_waiting"
    message = str(ret.get("message", "")).strip()
    if action == "send_message" and not message:
        action = "keep_waiting"
    if action != "send_message":
        message = ""
    return action, message, _resolve_gap(ret)


def _resolve_judgment(ret: dict) -> str:
    """心跳判断轮：归到 WAITING_JUDGMENTS；非法/缺省 → unclear（安全偏向续等侧，由动作轮再决）。"""
    raw = str(ret.get("judgment", "")).strip().lower().replace("-", "_")
    if raw in WAITING_JUDGMENTS:
        return raw
    return "unclear"


def _resolve_intent(ret: dict) -> str:
    """开放意愿：自由文本；空缺省 → keep waiting。可选 intent_detail 并入一句。"""
    raw = str(ret.get("intent", "")).strip()
    detail = str(ret.get("intent_detail", "")).strip()
    if not raw:
        return "keep waiting"
    if detail and detail.lower() not in raw.lower():
        return f"{raw} ({detail})"
    return raw


def _goal_reading(raw: object) -> list[dict]:
    """Keep the model's per-turn goal appraisal as an auditable soft signal.

    Missing or malformed readings are intentionally tolerated.  The goal layer guides
    cognition; it is not a protocol gate that can invalidate a session.
    """
    values = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    return [dict(item) for item in values if isinstance(item, dict)]


def _goal_ids(raw: object) -> list[str]:
    """Normalize soft intent target ids without rejecting unknown future goal ids."""
    values = raw if isinstance(raw, list) else ([raw] if isinstance(raw, str) else [])
    out: list[str] = []
    for item in values:
        value = str(item).strip()
        if value and value not in out:
            out.append(value)
    return out


def _current_goal_text(task: str, goal_ledger: GoalLedger | None) -> str:
    """Use the current B0 wording for cognition; keep the seed task in the ledger audit."""
    if goal_ledger is not None:
        baseline = goal_ledger.goals.get(goal_ledger.baseline_id)
        if baseline is not None and baseline.text.strip():
            return baseline.text.strip()
    return task


def _main_decide(
    *,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    harness_output: str,
    harness_events: list,
    space: list,
    state: State,
    help_text: str,
    appraise_task: bool,
    result: SessionResult,
    phase: str,
    goal_frame: dict | None = None,
    goal_ledger: GoalLedger | None = None,
) -> tuple[dict, list[dict], str, bool]:
    """主 loop 决策：judge → intent → [一次 final-check → rejudge → reintent] → act。

    返回 (act_ret 含 action/message, persona_calls, intent, gap)。
    judge 的 perceive/verdict/task_load 已合并进 act_ret，供后续 apply_verdict / 开局 task_load。
    """
    calls: list[dict] = []
    goal_updates: list = []
    current_goal_frame = goal_frame
    decision_task = _current_goal_text(task, goal_ledger)

    def apply_goal_updates(raw: object) -> None:
        """Apply updates between cognitive stages so this turn sees its own changes."""
        nonlocal current_goal_frame, decision_task
        if goal_ledger is None or raw is None:
            return
        values = goal_ledger.apply_updates(raw, turn=state.turn + 1)
        goal_updates.extend(values)
        current_goal_frame = goal_ledger.prompt_snapshot()
        decision_task = _current_goal_text(task, goal_ledger)

    jret = client.respond(
        system,
        build_main_judge_turn(
            decision_task,
            history,
            harness_output,
            [],  # judge 不看当前动作菜单；只在 act 收敛阶段暴露真实 action_space
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=current_goal_frame,
            appraise_task=appraise_task,
        ),
    )
    new_calls = _take_persona_calls(client, "main_judge")
    calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase=phase)
    perceive = str(jret.get("perceive", ""))
    verdict = str(jret.get("verdict", "unsure"))
    task_load = jret.get("task_load")
    goal_reading = _goal_reading(jret.get("goal_reading"))
    apply_goal_updates(jret.get("goal_update"))
    target_goal_ids: list[str] = []
    expected_progress = ""
    iret = client.respond(
        system,
        build_main_intent_turn(
            decision_task,
            history,
            harness_output,
            [],  # intent 仍是开放意愿，不看当前动作菜单
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=current_goal_frame,
            verdict=verdict,
            perceive=perceive,
            goal_reading=goal_reading,
            final_check_available=phase == Phase.ACTIVE.value,
        ),
    )
    new_calls = _take_persona_calls(client, "main_intent")
    calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase=phase)
    intent = _resolve_intent(iret)
    target_goal_ids = _goal_ids(iret.get("target_goal_ids"))
    expected_progress = str(iret.get("expected_progress") or "").strip()
    apply_goal_updates(iret.get("goal_update"))

    # Spec-0048：仅 ACTIVE 的本决策周期允许一次最终私有核查；无论核查成功、不可用或
    # 协议失败，之后都必须经过无工具 rejudge/reintent，并且不能在同一周期再次回跳。
    if phase == Phase.ACTIVE.value and iret.get("needs_final_check") is True:
        check_goal = str(iret.get("check_goal") or "").strip()
        check_status = "failed"
        check_evidence = "The final check could not be completed. Judge from existing evidence."
        try:
            cret = client.respond(
                system,
                build_main_final_check_turn(
                    decision_task,
                    history,
                    harness_output,
                    state,
                    help_text=help_text,
                    harness_events=harness_events,
                    goal_frame=current_goal_frame,
                    verdict=verdict,
                    perceive=perceive,
                    intent=intent,
                    check_goal=check_goal,
                ),
            )
            new_calls = _take_persona_calls(client, "main_final_check")
            calls.extend(new_calls)
            _record_private_evidence(state=state, calls=new_calls, phase=phase)
            check_status = str(cret.get("check_status") or "failed")
            check_evidence = str(cret.get("perceive") or "").strip() or check_evidence
        except PersonaProtocolError as exc:
            # final-check 本身是可选证据通道：失败时把失败作为证据交给强制复判，不把它
            # 误作 harness 失败，也不允许重新进入工具阶段。
            new_calls = _take_persona_calls(client, "main_final_check")
            calls.extend(new_calls)
            _record_private_evidence(state=state, calls=new_calls, phase=phase)
            check_status = "failed"
            check_evidence = f"Final check unavailable ({exc.code}); use existing evidence."

        rjret = client.respond(
            system,
            build_main_rejudge_turn(
                decision_task,
                history,
                harness_output,
                state,
                help_text=help_text,
                harness_events=harness_events,
                goal_frame=current_goal_frame,
                prior_verdict=verdict,
                prior_perceive=perceive,
                check_status=check_status,
                check_evidence=check_evidence,
            ),
        )
        new_calls = _take_persona_calls(client, "main_rejudge")
        calls.extend(new_calls)
        _record_private_evidence(state=state, calls=new_calls, phase=phase)
        perceive = str(rjret.get("perceive") or "")
        verdict = str(rjret.get("verdict") or "unsure")
        goal_reading = _goal_reading(rjret.get("goal_reading"))
        apply_goal_updates(rjret.get("goal_update"))

        riret = client.respond(
            system,
            build_main_reintent_turn(
                decision_task,
                history,
                harness_output,
                state,
                help_text=help_text,
                harness_events=harness_events,
                goal_frame=current_goal_frame,
                verdict=verdict,
                perceive=perceive,
                goal_reading=goal_reading,
            ),
        )
        new_calls = _take_persona_calls(client, "main_reintent")
        calls.extend(new_calls)
        _record_private_evidence(state=state, calls=new_calls, phase=phase)
        intent = _resolve_intent(riret)
        target_goal_ids = _goal_ids(riret.get("target_goal_ids"))
        expected_progress = str(riret.get("expected_progress") or "").strip()
        apply_goal_updates(riret.get("goal_update"))

    aret = client.respond(
        system,
        build_main_act_turn(
            decision_task,
            history,
            harness_output,
            space,
            state,
            help_text=help_text,
            harness_events=harness_events,
            goal_frame=current_goal_frame,
            verdict=verdict,
            perceive=perceive,
            intent=intent,
            goal_reading=goal_reading,
            target_goal_ids=target_goal_ids,
            expected_progress=expected_progress,
        ),
    )
    new_calls = _take_persona_calls(client, "main_act")
    calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase=phase)
    _drain_issue_notes(client, result)
    _record_act_report(aret, result, history, stage="main_act", turn=state.turn)
    gap = _resolve_gap(aret)
    act_target_ids = _goal_ids(aret.get("target_goal_ids"))
    if act_target_ids:
        target_goal_ids = act_target_ids
    act_expected_progress = str(aret.get("expected_progress") or "").strip()
    if act_expected_progress:
        expected_progress = act_expected_progress
    apply_goal_updates(aret.get("goal_update"))
    goal_effect = aret.get("goal_effect") if isinstance(aret.get("goal_effect"), dict) else {}
    goal_field_audit = (
        audit_goal_fields(
            goal_ledger,
            goal_reading=goal_reading,
            target_goal_ids=target_goal_ids,
            expected_progress=expected_progress,
            goal_effect=goal_effect,
            goal_updates=goal_updates,
        )
        if goal_ledger is not None
        else {}
    )
    merged = {
        "perceive": perceive,
        "verdict": verdict,
        "intent": intent,
        "action": aret.get("action"),
        "message": aret.get("message", ""),
        "gap": gap,
        "goal_reading": goal_reading,
        "target_goal_ids": target_goal_ids,
        "expected_progress": expected_progress,
        "goal_field_audit": goal_field_audit,
    }
    if goal_updates:
        # These are already applied summaries, not raw updates.  Keeping them under a
        # separate key prevents run_session from applying them a second time.
        merged["goal_updates_applied"] = goal_updates
    if "goal_effect" in aret:
        merged["goal_effect"] = aret.get("goal_effect")
    if isinstance(aret.get("acceptance_basis"), dict):
        merged["acceptance_basis"] = dict(aret["acceptance_basis"])
    if task_load is not None:
        merged["task_load"] = task_load
    return merged, calls, intent, gap


def route(action_id: str, message: str, state: State, harness, observable: str) -> str | None:
    """按 executor×channel 分派, 返回下一轮的 harness 文本(无则 None)。"""
    spec = CATALOG[action_id]

    if action_id == "keep_waiting":
        # 主 loop「再等」：poll 等下一条 reply（软唤醒，不绑写旗标；Spec-0036）。
        if not hasattr(harness, "poll"):
            return None
        try:
            kind, val = harness.poll(_HEARTBEAT_SEC)
        except Exception as exc:  # noqa: BLE001
            return f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}"
        if kind == "reply":
            return str(val)
        return None

    if action_id == "interrupt":
        try:
            ctrl_out = harness.interrupt()
        except Exception as exc:  # noqa: BLE001
            return f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}"
        return str(ctrl_out or "[interrupt] no running harness work to stop")

    if spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE:
        if not message.strip():
            # 模型选了要发话的动作却没给出这句话（client 重问后仍空，极少见）：不 fabricate、不外发。
            # 本轮空转（harness 不推进），MAX_TURNS 兜底；绝不把框架编的话发给 harness。
            return None
        try:
            return harness.send(message)  # 发 B 线 -> 驱动 harness 出下一轮文本
        except Exception as exc:  # noqa: BLE001
            # harness 是黑盒：崩溃/超时/协议违例都不该炸掉整局，而应作为可观测的失败信号回给用户 agent
            # （读作 [harness error] → 判 stuck/failed_blame_harness → 掉耐心 → 最终终止并留 issue）。
            return f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}"

    return None  # 终止动作: 不再驱动 harness


def _append_issue_note(result: SessionResult, body: str) -> bool:
    text = body.strip()
    if not text or text in result.issue_notes:
        return False
    result.issue_notes.append(text)
    result.signals.append(f"ISSUE_TOOL: report_issue ({len(result.issue_notes)})")
    return True


def _record_act_report(
    ret: dict, result: SessionResult, history: list[str], *, stage: str, turn: int
) -> None:
    """Spec-0057/T1: reporting is independent of action and persona tool ability.

    The act's raw/parsed trace retains the choice. Malformed optional feedback must
    never retry or replace an otherwise valid main action (including acceptance).
    """
    report = ret.get("report_issue")
    if report is None:
        return
    body = report.get("body") if isinstance(report, dict) else None
    if not isinstance(body, str) or not body.strip():
        result.protocol_events.append(
            {"stage": stage, "turn": turn, "code": "invalid_report_issue", "status": "warning"}
        )
        result.signals.append(f"PERSONA_PROTOCOL_WARNING: stage={stage} code=invalid_report_issue")
        return
    if _append_issue_note(result, body):
        history.append(
            f"[turn {turn}] feedback recorded for tool developers (queued for session close): "
            f"{body.strip()}"
        )


def _drain_issue_notes(client: PersonaClient, result: SessionResult) -> None:
    """把 agentic 中途 report_issue 笔记并入 SessionResult（允许闲置；无则空操作）。"""
    drain = getattr(client, "drain_issue_notes", None)
    if not callable(drain):
        return
    for note in drain():
        text = str(note).strip()
        if not text:
            continue
        _append_issue_note(result, text)


def emit_issue_artifact(persona: Persona, log: list[TurnLog], issue_text: str) -> str:
    """从本局真实(主观)数据派生 issue(不写死场景, 不读客观真值)。

    正文 = issue_text：persona 经专门的 build_issue_turn 以本人口吻写的*自包含* issue(提交给不在场的
    开发团队),不套第三人称标题或模板外壳; 末尾仅附一行斜体的机器自动采集元信息(能力档/纠错风格/复现轮数/
    最近 harness 末行)供开发者分流, 与用户原话明确分隔。issue_text 为空时回落到 file_issue 当轮的 message。
    """
    fails = [t for t in log if t.verdict == "failed_blame_harness"]
    last_out = next((t.harness_output for t in reversed(log) if t.harness_output.strip()), "")
    symptom = last_out.strip().splitlines()[-1][:160] if last_out.strip() else "—"
    body = (
        issue_text.strip() or (log[-1].message.strip() if log else "") or "(filed without detail)"
    )
    meta = (
        f"_auto-collected · {persona.persona_id} · {persona.d1.value}/{persona.d43.value} · "
        f"{len(log)} turns, {len(fails)} blamed the assistant · last reply: {symptom}_"
    )
    return f"{body}\n\n---\n{meta}\n"


def _log_waiting(
    result: SessionResult,
    state: State,
    action: str,
    message: str,
    *,
    judgment: str,
    intent: str,
    perceive: str,
    gap: bool,
    on_progress: Callable[[SessionResult], None] | None,
    persona_trace: list,
    ledger: _UtteranceLedger,
    goal_before: dict | None = None,
    goal_reading: list[dict] | None = None,
    target_goal_ids: list[str] | None = None,
    expected_progress: str = "",
    goal_updates: list[dict] | None = None,
    goal_after: dict | None = None,
    goal_effect: dict | None = None,
    goal_field_audit: dict | None = None,
) -> None:
    """把一次心跳唤醒的等待决策记为 phase='waiting' 的 TurnLog（观测用，不占 harness_output）。

    perceive 形如 [judgment|intent→action] notes；act 自报 gap 时追加 WAIT_GAP 信号。
    send_message 的正文写入 TurnLog.message（内通道）；其余动作为空。
    Spec-0024/T6：send_message 分配 utterance，delivery=queued（排在当前 open 之后）。
    """
    note = perceive.strip()
    head = f"[{judgment}|{intent}→{action}]"
    perceive_logged = f"{head} {note}" if note else head
    # 信道标注：send_message 是内（EMIT）；interrupt/give_up/keep_waiting 是外/本地（SILENT）。
    if action == "send_message":
        executor, channel = Executor.HARNESS.value, Channel.EMIT.value
    else:
        executor, channel = Executor.PERSONA_LOCAL.value, Channel.SILENT.value
    utterance_id = ""
    delivery = ""
    queued_behind = ""
    if action == "send_message" and message.strip():
        utterance_id = ledger.alloc(message)
        delivery = "queued"
        queued_behind = ledger.open_id or ""
    result.turns.append(
        TurnLog(
            turn=state.turn,
            phase="waiting",
            action_space=list(WAITING_ACTIONS),
            perceive=perceive_logged,
            verdict="stuck",
            action=action,
            message=message if action == "send_message" else "",
            executor=executor,
            channel=channel,
            patience=state.patience,
            trust=state.trust.value,
            harness_output="",
            harness_steps=[],
            persona_trace=list(persona_trace),
            utterance_id=utterance_id,
            delivery=delivery,
            queued_behind=queued_behind,
            goal_before=dict(goal_before or {}),
            goal_reading=[dict(item) for item in (goal_reading or [])],
            target_goal_ids=list(target_goal_ids or []),
            expected_progress=expected_progress,
            goal_updates=[dict(item) for item in (goal_updates or [])],
            goal_after=dict(goal_after or {}),
            goal_effect=dict(goal_effect or {}),
            goal_field_audit=dict(goal_field_audit or {}),
        )
    )
    if gap:
        result.signals.append(f"WAIT_GAP: intent={intent} action={action}")
    if on_progress is not None:
        on_progress(result)


class _SessionClock:
    """会话相对时间轴：history 一律 `[+Ns] …`，避免多种增量时间写法混用。

    墙钟与 harness 上报的 waited_sec 取 max，便于单测用 fake poll 的 waited 推进时间轴。
    """

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._logical = 0.0

    def wall(self) -> float:
        return max(0.0, time.monotonic() - self._t0)

    def now(self) -> float:
        self._logical = max(self._logical, self.wall())
        return self._logical

    def observe(self, sec: float) -> float:
        self._logical = max(self._logical, float(sec), self.wall())
        return self._logical

    def stamp(self, history: list[str], body: str) -> None:
        history.append(f"[+{self.now():.0f}s] {body}")


def _note_waiting_memory(
    history: list[str],
    clock: _SessionClock,
    *,
    judgment: str,
    intent: str,
    action: str,
    message: str,
    perceive: str,
    gap: bool,
) -> None:
    """心跳思考+动作写入 history（时间由 clock 统一打 [+Ns] 前缀）。"""
    intent_one = intent.strip().replace("\n", " ")[:120] or "(no intent)"
    note = perceive.strip().replace("\n", " ")[:160]
    gap_bit = " (felt a gap — action did not fully match intent)" if gap else ""
    if action == "send_message":
        msg_one = message.strip().splitlines()[0][:120] if message.strip() else "(empty)"
        act_bit = f"chose send_message: {msg_one}"
    else:
        act_bit = f"chose {action}"
    body = f"waiting: judged {judgment}; wanted {intent_one!r}; {act_bit}{gap_bit}."
    if note:
        body = f"{body} notes: {note}"
    clock.stamp(history, body)


def _finalize_terminal(
    action_id: str,
    *,
    result: SessionResult,
) -> None:
    """Record the chosen terminal action; narrate only after actor output freezing."""
    spec = CATALOG[action_id]
    result.end_reason = spec.end_reason or "terminated"
    result.terminal_issue_mode = {
        "file_issue": "filed",
        "give_up": "left",
        "accept_with_reservations": "accepted",
    }.get(action_id)
    # Spec-0084/T2: narration is deferred until the outer runner has frozen actor outputs.


def _narrate_terminal(*, result, persona, client, system, task, history, state) -> None:
    if result.terminal_issue_mode is not None:
        try:
            issue_resp = client.respond(
                system, build_issue_turn(task, history, state, mode=result.terminal_issue_mode)
            )
        except Exception as exc:  # noqa: BLE001 - preserve actor evidence when review is unavailable
            # Terminal issue narration is non-gating. Preserve the chosen terminal
            # action, but retain a typed warning instead of losing the whole session.
            stage = getattr(exc, "stage", "file_issue")
            code = getattr(exc, "code", type(exc).__name__)
            result.persona_tail.extend(_take_persona_calls(client, stage))
            _take_protocol_events(client, result)
            result.protocol_events.append(
                {
                    "stage": stage,
                    "code": code,
                    "attempts": getattr(exc, "attempts", 1),
                    "status": "warning",
                    "terminal_narration": True,
                }
            )
            result.signals.append(
                f"PERSONA_PROTOCOL_WARNING: stage={stage} code={code} terminal_narration"
            )
            return
        result.persona_tail.extend(_take_persona_calls(client, "file_issue"))
        _take_protocol_events(client, result)
        issue_text = str(issue_resp.get("issue") or "")
        result.issue_artifact = emit_issue_artifact(persona, result.turns, issue_text)


def _activity_from_harness(harness) -> list[dict]:
    """本轮已见活动：优先 last_progress；否则从 last_steps 抽 tool/tool_error（短标题）。"""
    progress = list(getattr(harness, "last_progress", None) or [])
    if progress:
        return progress
    steps = list(getattr(harness, "last_steps", None) or [])
    out: list[dict] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") in ("tool", "tool_error"):
            out.append({"kind": str(step.get("kind")), "text": str(step.get("text") or "")})
    return out


def _heartbeat_once(
    *,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    clock: _SessionClock,
    state: State,
    coef: Coef,
    help_text: str,
    result: SessionResult,
    on_progress: Callable[[SessionResult], None] | None,
    prior_activity: list[dict],
    waited_sec: float,
    progress: list[dict],
    progress_seen: int,
    heartbeats: int,
    ledger: _UtteranceLedger,
    goal_frame: dict | None = None,
    goal_ledger: GoalLedger | None = None,
) -> tuple[str, str, bool, int]:
    """一次性等待决策（timer 触发）。任意动作（含 keep_waiting）做完即结束本次心跳。

    Spec-0023：仅 judge → intent → act（three）。
    返回 (action, message, gap, new_progress_seen)。
    强制 give_up：心跳次数触顶，或 keep_waiting 且无新进度把耐心耗尽。
    """
    new_progress = len(progress) > progress_seen
    goal_before = goal_ledger.snapshot() if goal_ledger is not None else {}
    decision_task = _current_goal_text(task, goal_ledger)
    seen = len(progress)
    ctx = dict(
        task=decision_task,
        history_lines=history,
        state=state,
        help_text=help_text,
        waited_sec=waited_sec,
        progress=progress,
        prior_activity=prior_activity,
        goal_frame=goal_frame,
    )
    jret = client.respond(system, build_waiting_judge_turn(**ctx))
    wait_calls = _take_persona_calls(client, "waiting_judge")
    _record_private_evidence(state=state, calls=wait_calls, phase="waiting")
    judgment = _resolve_judgment(jret)
    perceive = str(jret.get("perceive", ""))
    goal_reading = _goal_reading(jret.get("goal_reading"))
    goal_updates: list[dict] = []
    if goal_ledger is not None and jret.get("goal_update") is not None:
        raw_updates = jret["goal_update"]
        raw_updates = raw_updates if isinstance(raw_updates, list) else [raw_updates]
        goal_updates.extend(goal_ledger.apply_updates(raw_updates, turn=state.turn))
        ctx["goal_frame"] = goal_ledger.prompt_snapshot()
        ctx["task"] = _current_goal_text(task, goal_ledger)
    iret = client.respond(
        system,
        build_waiting_intent_turn(
            **ctx,
            judgment=judgment,
            perceive=perceive,
        ),
    )
    new_calls = _take_persona_calls(client, "waiting_intent")
    wait_calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase="waiting")
    intent = _resolve_intent(iret)
    target_goal_ids = _goal_ids(iret.get("target_goal_ids"))
    expected_progress = str(iret.get("expected_progress") or "").strip()
    if goal_ledger is not None and iret.get("goal_update") is not None:
        raw_updates = iret["goal_update"]
        raw_updates = raw_updates if isinstance(raw_updates, list) else [raw_updates]
        goal_updates.extend(goal_ledger.apply_updates(raw_updates, turn=state.turn))
        ctx["goal_frame"] = goal_ledger.prompt_snapshot()
        ctx["task"] = _current_goal_text(task, goal_ledger)
    aret = client.respond(
        system,
        build_waiting_act_turn(
            **ctx,
            judgment=judgment,
            perceive=perceive,
            intent=intent,
            target_goal_ids=target_goal_ids,
            expected_progress=expected_progress,
        ),
    )
    new_calls = _take_persona_calls(client, "waiting_act")
    wait_calls.extend(new_calls)
    _record_private_evidence(state=state, calls=new_calls, phase="waiting")
    _drain_issue_notes(client, result)
    _record_act_report(aret, result, history, stage="waiting_act", turn=state.turn)
    if goal_ledger is not None and aret.get("goal_update") is not None:
        raw_updates = aret["goal_update"]
        raw_updates = raw_updates if isinstance(raw_updates, list) else [raw_updates]
        goal_updates.extend(goal_ledger.apply_updates(raw_updates, turn=state.turn))
    action, wait_message, gap = _resolve_waiting(aret)
    goal_effect = aret.get("goal_effect") if isinstance(aret.get("goal_effect"), dict) else {}
    goal_field_audit = (
        audit_goal_fields(
            goal_ledger,
            goal_reading=goal_reading,
            target_goal_ids=target_goal_ids,
            expected_progress=expected_progress,
            goal_effect=goal_effect,
            goal_updates=goal_updates,
        )
        if goal_ledger is not None
        else {}
    )
    if heartbeats >= _MAX_HEARTBEATS:
        action = "give_up"
        wait_message = ""
        gap = False
    elif action == "keep_waiting":
        if not new_progress:
            state.patience = max(0, state.patience - coef.patience_decay)
        if state.patience <= 0:
            action = "give_up"
            wait_message = ""
            gap = False
    _log_waiting(
        result,
        state,
        action,
        wait_message,
        judgment=judgment,
        intent=intent,
        perceive=perceive,
        gap=gap,
        on_progress=on_progress,
        persona_trace=wait_calls,
        ledger=ledger,
        goal_before=goal_before,
        goal_reading=goal_reading,
        target_goal_ids=target_goal_ids,
        expected_progress=expected_progress,
        goal_updates=goal_updates,
        goal_after=goal_ledger.snapshot() if goal_ledger is not None else {},
        goal_effect=goal_effect,
        goal_field_audit=goal_field_audit,
    )
    _note_waiting_memory(
        history,
        clock,
        judgment=judgment,
        intent=intent,
        action=action,
        message=wait_message,
        perceive=perceive,
        gap=gap,
    )
    return action, wait_message, gap, seen


def _try_ready_reply(harness) -> str | None:
    """心跳动作执行前：非阻塞看 reply 是否已到（LLM 思考期间可能已进缓冲）。"""
    fn = getattr(harness, "try_reply", None)
    if not callable(fn):
        return None
    return fn()


def _await_harness(
    harness,
    message: str,
    *,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    clock: _SessionClock,
    state: State,
    coef: Coef,
    help_text: str,
    result: SessionResult,
    on_progress: Callable[[SessionResult], None] | None,
    prior_activity: list[dict],
    ledger: _UtteranceLedger,
    open_utterance_id: str,
    goal_frame: dict | None = None,
    goal_ledger: GoalLedger | None = None,
) -> tuple[str, float, str | None, str | None]:
    """写消息后进入 AwaitEvent：reply → 交主 loop；timer → 一次性心跳后回到 AwaitEvent。

    Spec-0024/T6：本轮写对应 open_utterance_id；收到的 reply/interrupt 关闭该 open。
    Spec-0036：写走统一 write_message（兼容 begin/emit 别名）。
    心跳动作（含 keep_waiting / send_message）做完即结束本次心跳，不在心跳内 continue poll。

    返回 (harness_output, elapsed_sec, terminal_action, user_control)：
      - reply：terminal=None，user_control=None（主 loop 下一轮 decide）；
      - interrupt：控制回复入 harness_output，user_control="interrupt"；
      - give_up：harness_output=""，terminal="give_up"；
      - 崩溃：harness_output 为 [harness error] 串。
    """
    t0 = time.monotonic()
    begin_at = clock.now()
    try:
        _write_harness_message(harness, message)
    except Exception as exc:  # noqa: BLE001
        ledger.clear_open()
        return (
            f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}",
            time.monotonic() - t0,
            None,
            None,
        )
    ledger.mark_open(open_utterance_id)
    heartbeats = 0
    progress_seen = 0
    protocol_failures = 0
    while True:
        # —— AwaitEvent ——
        try:
            kind, val = harness.poll(_HEARTBEAT_SEC)
        except Exception as exc:  # noqa: BLE001
            ledger.clear_open()
            return (
                f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}",
                time.monotonic() - t0,
                None,
                None,
            )
        if kind == "reply":
            clock.observe(begin_at + (time.monotonic() - t0))
            ledger.close_open_as_answered()
            return str(val), time.monotonic() - t0, None, None

        # —— HeartbeatOnce（timer）——
        waited = float(val)  # type: ignore[arg-type]
        clock.observe(begin_at + waited)
        heartbeats += 1
        progress = list(getattr(harness, "last_progress", None) or [])
        current_goal_frame = (
            goal_ledger.prompt_snapshot() if goal_ledger is not None else goal_frame
        )
        try:
            action, wait_message, _gap, progress_seen = _heartbeat_once(
                client=client,
                system=system,
                task=task,
                history=history,
                clock=clock,
                state=state,
                coef=coef,
                help_text=help_text,
                result=result,
                on_progress=on_progress,
                prior_activity=prior_activity,
                waited_sec=waited,
                progress=progress,
                progress_seen=progress_seen,
                heartbeats=heartbeats,
                ledger=ledger,
                goal_frame=current_goal_frame,
                goal_ledger=goal_ledger,
            )
            # A successful complete heartbeat clears only the transient warning;
            # protocol evidence remains in result.protocol_events.
            protocol_failures = 0
        except PersonaProtocolError as exc:
            protocol_failures += 1
            result.persona_tail.extend(_take_persona_calls(client, exc.stage))
            _take_protocol_events(client, result)
            result.protocol_events.append(
                {
                    "stage": exc.stage,
                    "code": exc.code,
                    "attempts": exc.attempts,
                    "heartbeat": heartbeats,
                    "status": "warning"
                    if protocol_failures < _MAX_PROTOCOL_STALL_HEARTBEATS
                    else "stalled",
                }
            )
            result.signals.append(
                f"PERSONA_PROTOCOL_WARNING: stage={exc.stage} code={exc.code} "
                f"attempts={exc.attempts} heartbeat={heartbeats}"
            )
            # No fake intent/action, no patience mutation, and no harness write on
            # a malformed decision. Keep polling once so a later harness reply can
            # still be judged. Repeated failure becomes a distinct safe terminal.
            if protocol_failures >= _MAX_PROTOCOL_STALL_HEARTBEATS:
                result.interaction_status = "protocol_stalled"
                result.evaluation_status = "invalid"
                result.evaluation_error = {
                    "kind": "persona_protocol",
                    "stage": exc.stage,
                    "code": exc.code,
                    "attempts": exc.attempts,
                    "heartbeat_failures": protocol_failures,
                }
                # All protocol evidence has already been copied to result. Close
                # the harness only at this terminal boundary; the outer connector
                # also closes idempotently for production sessions.
                try:
                    harness.shutdown()
                except Exception:  # pragma: no cover - cleanup is best effort
                    pass
                return "", time.monotonic() - t0, "protocol_stalled", None
            continue
        # 决策期间 reply 可能已进缓冲：动作执行前先确认；有则作废等待动作，交回主 loop。
        ready = _try_ready_reply(harness)
        if ready is not None:
            clock.stamp(
                history,
                f"waiting decision aborted before acting ({action}): "
                "a harness reply arrived while you were deciding; "
                "you did not carry out that waiting action — "
                "back to the main loop to read the reply.",
            )
            clock.observe(begin_at + (time.monotonic() - t0))
            ledger.close_open_as_answered()
            return ready, time.monotonic() - t0, None, None
        # 任意动作都结束本次心跳；下面只执行 I/O 副作用，然后要么 return 给主环，要么回 AwaitEvent。
        if action == "send_message":
            try:
                _write_harness_message(harness, wait_message)
            except Exception as exc:  # noqa: BLE001
                ledger.clear_open()
                return (
                    f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}",
                    time.monotonic() - t0,
                    None,
                    None,
                )
            continue  # 回 AwaitEvent：下一笔 reply 唤醒主 loop，不再嵌套心跳决策
        if action == "interrupt":
            try:
                ctrl_out = harness.interrupt()
            except Exception as exc:  # noqa: BLE001
                ledger.clear_open()
                return (
                    f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}",
                    time.monotonic() - t0,
                    None,
                    None,
                )
            clock.observe(begin_at + (time.monotonic() - t0))
            ledger.close_open_as_answered()
            if isinstance(ctrl_out, str) and ctrl_out.startswith(HARNESS_ERROR_PREFIX):
                return ctrl_out, time.monotonic() - t0, None, "interrupt"
            return str(ctrl_out or ""), time.monotonic() - t0, None, "interrupt"
        if action == "give_up":
            try:
                harness.shutdown()
            except Exception:  # noqa: BLE001  give_up 是终止意图，关闭失败不应阻塞会话收场
                pass
            ledger.clear_open()
            return "", time.monotonic() - t0, "give_up", None
        # keep_waiting：动作已记录并可能耗心；回 AwaitEvent，等下一笔 reply 或下一跳 timer。
        continue


def run_session(
    persona: Persona,
    client: PersonaClient,
    harness,
    task: str,
    *,
    help_text: str = "",
    on_progress: Callable[[SessionResult], None] | None = None,
    deadline_seconds: float | None = None,
    before_terminal_review: Callable[[], None] | None = None,
    terminal_review: bool = True,
) -> SessionResult:
    # on_progress: 每轮写完 TurnLog 后回调一次进行中的 result(含终止轮)，供观测层(看板)逐轮展示。
    # Spec-0023：主决定与心跳均为 judge → intent → act（three），无 mode 旋钮。
    coef = make_coef(persona)
    state = init_state(persona)
    system = build_system(persona)

    result = SessionResult(persona_id=persona.persona_id, end_reason="max_turns")
    goal_ledger = GoalLedger.from_task(task)
    result.goal_ledger = goal_ledger.snapshot()
    history: list[str] = []
    clock = _SessionClock()
    harness_output = ""
    harness_steps: list = []  # 与 harness_output 配对的内层过程流
    harness_events: list = []  # 上一轮 stdout 可见事件流，供下一次主决策感知
    prior_activity: list[dict] = []  # 上一轮已完成请求的活动条（过程记忆，供对照）
    ledger = _UtteranceLedger()  # Spec-0024/T6：请求–回复配对
    started_at = time.monotonic()

    while state.turn < MAX_TURNS:
        if deadline_seconds is not None and time.monotonic() - started_at >= deadline_seconds:
            result.end_reason = "official_deadline"
            break
        set_usage_context(interaction_id=f"turn-{state.turn}", turn_no=state.turn)
        phase = Phase.OPENING if state.turn == 0 and not history else Phase.ACTIVE
        goal_before = goal_ledger.snapshot()

        # ② 派生动作空间
        space = derive_action_space(phase, persona, state)

        # ③ 同构主决定：judge → intent → act。
        try:
            ret, decide_calls, intent, gap = _main_decide(
                client=client,
                system=system,
                task=task,
                history=history,
                harness_output=harness_output,
                harness_events=harness_events,
                space=space,
                state=state,
                help_text=help_text,
                appraise_task=phase is Phase.OPENING,
                result=result,
                phase=phase.value,
                goal_frame=goal_ledger.prompt_snapshot(),
                goal_ledger=goal_ledger,
            )
        except PersonaProtocolError as exc:
            result.persona_tail.extend(_take_persona_calls(client, exc.stage))
            _take_protocol_events(client, result)
            result.interaction_status = "protocol_unrecoverable"
            result.evaluation_status = "invalid"
            result.evaluation_error = {
                "kind": "persona_protocol",
                "stage": exc.stage,
                "code": exc.code,
                "attempts": exc.attempts,
            }
            result.end_reason = "evaluator_invalid"
            result.goal_ledger = goal_ledger.snapshot()
            result.goal_audit = goal_ledger.audit()
            break
        # _main_decide applies updates between judge/intent/rejudge stages so the current
        # decision sees them.  Do not apply them again here; this is only the turn-log view.
        goal_updates = [dict(item) for item in (ret.get("goal_updates_applied") or [])]
        goal_reading = _goal_reading(ret.get("goal_reading"))
        target_goal_ids = _goal_ids(ret.get("target_goal_ids"))
        expected_progress = str(ret.get("expected_progress") or "").strip()
        goal_effect = ret.get("goal_effect") if isinstance(ret.get("goal_effect"), dict) else {}
        acceptance_basis = (
            dict(ret.get("acceptance_basis") or {})
            if isinstance(ret.get("acceptance_basis"), dict)
            else {}
        )
        goal_field_audit = (
            dict(ret.get("goal_field_audit") or {})
            if isinstance(ret.get("goal_field_audit"), dict)
            else {}
        )
        goal_after = goal_ledger.snapshot()
        result.goal_ledger = goal_after
        result.goal_audit = goal_ledger.audit()
        # 开局：据 persona 主观任务量读数，在耐心基线上叠加一次性小浮动（同一个人接不同任务耐心不同）。
        if phase is Phase.OPENING:
            apply_task_load(state, str(ret.get("task_load", "normal")))

        # ③.5 方案 B：action=='free' 交给模型自评归类到合法 id（替代关键词硬猜）。
        # 仅 client 支持 classify_action 时启用；否则落 resolve 的安全兜底。
        try:
            if ret.get("action") == "free" and hasattr(client, "classify_action"):
                ret = {**ret, "action": client.classify_action(system, ret, space)}
                decide_calls.extend(_take_persona_calls(client, "classify_action"))

            # ④ resolve: 只接收真实合法 action；缺失、越界或信道冲突一律 fail closed。
            action_id, message = resolve_action(ret, space, persona)
        except (PersonaProtocolError, ActionResolutionError) as exc:
            result.persona_tail.extend(decide_calls)
            result.interaction_status = "protocol_unrecoverable"
            if isinstance(exc, PersonaProtocolError):
                result.persona_tail.extend(_take_persona_calls(client, exc.stage))
                _take_protocol_events(client, result)
                detail = {
                    "kind": "persona_protocol",
                    "stage": exc.stage,
                    "code": exc.code,
                    "attempts": exc.attempts,
                }
            else:
                detail = {
                    "kind": "action_resolution",
                    "code": exc.code,
                    "action": exc.action_id,
                }
            result.evaluation_status = "invalid"
            result.evaluation_error = detail
            result.end_reason = "evaluator_invalid"
            result.goal_ledger = goal_ledger.snapshot()
            result.goal_audit = goal_ledger.audit()
            break
        spec = CATALOG[action_id]

        # ⑤ 状态写回 (只吃主观 verdict)
        verdict = ret.get("verdict", "unsure")
        if verdict not in VERDICTS:
            verdict = "unsure"
        apply_verdict(state, verdict, coef)

        note = str(ret.get("perceive", "")).strip()
        head = f"[{verdict}|{intent}→{action_id}]"
        perceive_logged = f"{head} {note}" if note else head

        # Spec-0024/T6：本拍若带着上一笔 reply，挂上 answers；若本拍外发，分配 utterance。
        answers_id, answers_said = ("", "")
        if harness_output.strip():
            answers_id, answers_said = ledger.consume_pending_answers()
        utterance_id = ""
        delivery = ""
        if spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE and message.strip():
            utterance_id = ledger.alloc(message)
            delivery = "open"

        result.pending_harness_output = None  # 该回复即将随本条 TurnLog 落日志, 不再悬挂
        result.pending_harness_steps = None
        result.pending_harness_events = None
        result.turns.append(
            TurnLog(
                turn=state.turn,
                phase=phase.value,
                action_space=space,
                perceive=perceive_logged,
                verdict=verdict,
                action=action_id,
                message=message,
                executor=spec.executor.value,
                channel=spec.channel.value,
                patience=state.patience,
                trust=state.trust.value,
                harness_output=harness_output,
                harness_steps=harness_steps,
                harness_events=list(harness_events or []),
                persona_trace=decide_calls,
                utterance_id=utterance_id,
                delivery=delivery,
                answers_utterance_id=answers_id,
                answers_said=answers_said,
                goal_before=goal_before,
                goal_reading=goal_reading,
                target_goal_ids=target_goal_ids,
                expected_progress=expected_progress,
                goal_updates=goal_updates,
                goal_after=goal_after,
                goal_effect=goal_effect,
                goal_field_audit=goal_field_audit,
                acceptance_basis=acceptance_basis,
            )
        )
        if gap:
            result.signals.append(f"WAIT_GAP: intent={intent} action={action_id}")
        if on_progress is not None:
            on_progress(result)  # 逐轮观测钩子(含终止轮): 喂给看板等观测层, 不影响主循环

        # 记历史(只记 B 线真正发出的话；空 message 不 fabricate、不入史)；统一 [+Ns] 前缀。
        if spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE and message.strip():
            clock.stamp(history, f"you -> harness: {message}")

        # ⑥ 终止判定（三种终止都以本人口吻留一条自包含 issue，见 _finalize_terminal）
        if spec.effect is Effect.TERMINATE:
            # Spec-0056/T4: persist the user's terminal claim without overriding it.
            terminal_audit = goal_ledger.commit_terminal_effect(
                action_id, goal_effect, turn=state.turn
            )
            basis_audit = audit_acceptance_basis(
                action_id,
                acceptance_basis,
                persona_d1=persona.d1.value,
                persona_d3=persona.d3.value if persona.d3 is not None else "",
            )
            terminal_audit["acceptance_basis"] = basis_audit
            if basis_audit.get("status") == "warning":
                terminal_audit["status"] = "warning"
                terminal_audit.setdefault("warnings", []).extend(
                    f"acceptance_basis:{warning}" for warning in basis_audit.get("warnings", [])
                )
            result.terminal_audit = terminal_audit
            result.goal_acceptance = goal_ledger.terminal_check(
                action_id, goal_effect, terminal_audit=terminal_audit
            )
            result.goal_ledger = goal_ledger.snapshot()
            result.goal_audit = goal_ledger.audit()
            result.goal_audit["terminal"] = terminal_audit
            if terminal_audit.get("status") == "warning":
                result.goal_audit["status"] = "warning"
                result.goal_audit.setdefault("warnings", []).extend(
                    terminal_audit.get("warnings", [])
                )
                result.signals.append(
                    "GOAL_TERMINAL_AUDIT_WARNING: " + ",".join(terminal_audit.get("warnings", []))
                )
            if basis_audit.get("alignment") == "weak":
                result.signals.append("PERSONA_ACCEPTANCE_ALIGNMENT: weak")
            # The terminal action is a subjective ledger transaction.  Update the
            # already-persisted terminal turn with the post-commit snapshot so the
            # trace cannot show close while the final goal remains open.
            result.turns[-1].goal_after = goal_ledger.snapshot()
            result.turns[-1].goal_field_audit = {
                **result.turns[-1].goal_field_audit,
                "terminal": terminal_audit,
            }
            if result.goal_acceptance["status"] in {
                "subjective_accept_unverified",
                "reservations_with_unmet_goals",
            }:
                result.signals.append(
                    "GOAL_ACCEPT_UNVERIFIED: "
                    + ",".join(result.goal_acceptance["unresolved_goals"])
                )
            _finalize_terminal(
                action_id,
                result=result,
            )
            break

        # ⑦ 路由。EMIT：真实子进程走 AwaitEvent（reply→主 decide；timer→一次性心跳）；
        # Fake/Scripted 退回阻塞 route。
        _clock_before_route = clock.now()
        _t0 = time.monotonic()
        _emits = spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE
        terminal_from_wait: str | None = None
        user_control: str | None = None
        supervised = _emits and bool(message.strip()) and _supports_heartbeat(harness)
        if supervised:
            nxt, elapsed, terminal_from_wait, user_control = _await_harness(
                harness,
                message,
                client=client,
                system=system,
                task=task,
                history=history,
                clock=clock,
                state=state,
                coef=coef,
                help_text=help_text,
                result=result,
                on_progress=on_progress,
                prior_activity=prior_activity,
                ledger=ledger,
                open_utterance_id=utterance_id,
                goal_frame=goal_ledger.prompt_snapshot(),
                goal_ledger=goal_ledger,
            )
            if terminal_from_wait == "give_up":  # 等待决策放弃：走终止路径并结束
                _finalize_terminal(
                    "give_up",
                    result=result,
                )
                break
            if terminal_from_wait == "protocol_stalled":
                # Protocol degradation is not user give-up and must not fabricate a
                # terminal message or issue. Keep the container/log evidence for the
                # outer session store, then leave the normal metrics as invalid.
                result.end_reason = "protocol_stalled"
                result.interaction_status = "protocol_stalled"
                result.evaluation_status = "invalid"
                break
        else:
            nxt = route(action_id, message, state, harness, harness_output)
            elapsed = time.monotonic() - _t0
            if nxt is not None:
                clock.observe(_clock_before_route + elapsed)
                # 阻塞 route：reply 即关闭本拍刚分配的 open utterance
                if utterance_id:
                    ledger.mark_open(utterance_id)
                    ledger.close_open_as_answered()
            elif action_id == "keep_waiting":
                # 再等无新 reply：仍把等待期吞到的旁路事件交给下一轮感知（避免空转丢 status）。
                drain_only = getattr(harness, "drain_visible_events", None)
                if callable(drain_only):
                    ev_only = list(drain_only())
                    if ev_only:
                        harness_events = ev_only
        if nxt is not None:
            # 时间感知·轻耗心：仅极端超时才自动扣一点耐心。
            # 仅对阻塞 route：AwaitEvent 路径的等待挫败已由 keep_waiting 一次性心跳建模，不双记。
            if not supervised and elapsed >= _EXTREME_WAIT_SEC:
                state.patience = max(0, state.patience - 1)
            harness_output = nxt
            # 与回复配对的内层过程流：send 后 launcher 把它挂在 harness.last_steps（观测旁路）。
            # Fake/Scripted harness 无此属性 → []。route 只在 EMIT 轮真调 send，此处取值即本轮回复的。
            steps = getattr(harness, "last_steps", None)
            harness_steps = list(steps) if isinstance(steps, list) else []
            drain_events = getattr(harness, "drain_visible_events", None)
            if callable(drain_events):
                harness_events = list(drain_events())
            else:
                harness_events = []
            # 活动条写入过程记忆：下次等待时可对照（不宣称「这是哪一轮的活动」归属）。
            prior_activity = _activity_from_harness(harness)
            if prior_activity:
                titles = [
                    str(p.get("text") or "").strip()
                    for p in prior_activity[-8:]
                    if isinstance(p, dict) and str(p.get("text") or "").strip()
                ]
                if titles:
                    clock.stamp(
                        history,
                        "harness activity: " + "; ".join(titles)[:240],
                    )
            # Spec-0024/T6：answers 写在下一拍 TurnLog；history 仍给人读的短预览。
            if user_control:
                clock.stamp(
                    history,
                    "YOU interrupted (Ctrl+C); harness acknowledged: "
                    f"{nxt.splitlines()[0][:80]}...",
                )
            else:
                clock.stamp(history, f"harness -> you: {nxt.splitlines()[0][:80]}...")
            # harness 回复到手即推观测层(不等 persona 下一轮), 否则长任务期间看板对话缺半边
            result.pending_harness_output = nxt
            result.pending_harness_steps = harness_steps
            result.pending_harness_events = list(harness_events or [])
            if on_progress is not None:
                on_progress(result)
            # timeout/crash 是 workspace 已失效的会话终态。回复文本仍作为 pending
            # evidence 保留，但不能再进入下一轮 persona 决策，更不能再向已死容器写消息。
            terminal_status = _harness_terminal_status(harness)
            if terminal_status:
                result.end_reason = f"harness_{terminal_status}"
                result.signals.append(f"HARNESS_TERMINAL: {terminal_status}")
                break
        # 本轮若未产生下一条 harness 输出（例如模型空转），保持上一条可见输出供下一轮继续判断。

    # Spec-0084/T2: main_final_check stayed before accept/continue; terminal review starts only now.
    if before_terminal_review is not None:
        before_terminal_review()
    if terminal_review:
        _narrate_terminal(
            result=result,
            persona=persona,
            client=client,
            system=system,
            task=_current_goal_text(task, goal_ledger),
            history=history,
            state=state,
        )
    # Flush any recovery events from a successful or normally terminated session.
    _take_protocol_events(client, result)
    # 评估器协议失败不是用户体验分，也不是 harness 失败；保留审计哨兵但跳过正常评分。
    result.goal_ledger = goal_ledger.snapshot()
    final_goal_audit = goal_ledger.audit()
    if result.terminal_audit:
        final_goal_audit["terminal"] = result.terminal_audit
        if result.terminal_audit.get("status") == "warning":
            final_goal_audit["status"] = "warning"
            final_goal_audit.setdefault("warnings", []).extend(
                result.terminal_audit.get("warnings", [])
            )
    result.goal_audit = final_goal_audit
    if result.evaluation_status == "invalid":
        err = result.evaluation_error or {}
        reason = f"Evaluator invalid; exclude from harness metrics: {err.get('code', 'unknown')}"
        if result.interaction_status in {"protocol_unrecoverable", "protocol_stalled"}:
            result.signals.append(f"PROTOCOL_UNRECOVERABLE: {err}")
        result.signals.append(f"EVALUATOR_INVALID: {err}")
        result.experience = experience_feedback(None, source="simulated_user", error=reason)
        return result

    # 收尾: 汇总纯主观的行为信号
    _collect_signals(result, persona)

    # 会话末两路并出体感分 (训练信号), 均只吃主观信号, 不读客观真值:
    # ② 框架派生仅作独立诊断，不补测量缺失。
    result.feeling_derived = derive_feeling(result.end_reason, result.turns)
    if not terminal_review:
        result.experience = experience_feedback(None, source="simulated_user", error="Deferred to the uniform post-freeze reviewer")
        return result
    # ① LLM 自评: persona 在角色内给"这次体验"打 1–4 + 理由 (spec-0001/T3 产出方式)
    set_usage_context(interaction_id=None, turn_no=None, operation="rate")
    try:
        rating = client.respond(
            system, build_rating_turn(_current_goal_text(task, goal_ledger), history, state)
        )
        result.persona_tail.extend(_take_persona_calls(client, "rate"))
        _take_protocol_events(client, result)
        result.feeling = parse_feeling_llm(rating)
        result.experience = experience_feedback(rating, source="simulated_user")
    except Exception as exc:  # noqa: BLE001 - a failed reviewer cannot erase the actor's artifacts
        # Rating is non-gating. Retain its failure without inventing a self-rating.
        stage = getattr(exc, "stage", "rate")
        code = getattr(exc, "code", type(exc).__name__)
        result.persona_tail.extend(_take_persona_calls(client, stage))
        _take_protocol_events(client, result)
        result.protocol_events.append(
            {
                "stage": stage,
                "code": code,
                "attempts": getattr(exc, "attempts", 1),
                "status": "warning",
                "non_gating": True,
            }
        )
        result.signals.append(f"PERSONA_PROTOCOL_WARNING: stage={stage} code={code} rating")
        result.experience = experience_feedback(None, source="simulated_user", error=str(exc))
        if isinstance(exc, PersonaProtocolError) and not code.startswith("internal_error:"):
            result.experience["status"] = "invalid"
    return result


def _collect_signals(result: SessionResult, persona: Persona) -> None:
    """行为信号一律从本局主观数据派生(end_reason / verdict / persona), 不读客观真值。"""
    fails = sum(1 for t in result.turns if t.verdict == "failed_blame_harness")
    if persona.d1.value in ("blind", "shallow") and result.end_reason == "abandoned":
        result.signals.append(
            "BEHAVIORAL: low-capability user abandoned without being able to self-fix."
        )
    if result.end_reason == "issue_filed":
        result.signals.append(
            "BEHAVIORAL: user was dissatisfied enough to stop and file a structured issue."
        )
    if fails >= 2:
        result.signals.append(
            f"FRICTION: user blamed the harness on {fails} turns before ending "
            f"({result.end_reason})."
        )
