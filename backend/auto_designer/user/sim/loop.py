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
  ⑦ 路由          EMIT -> 驱动 harness 出下一轮; verify_self -> 注入私有自观察

本轮纯主观(不实现客观真值线):
- harness 只回文本, 无 gold / exit_code; bug 体现在文本里, 由 persona 凭能力识别。
- 状态与体感全程只依赖主观 verdict / trust, 不读任何客观真值。
- verify_self: 框架把最近一次 harness 文本原样注入 self_observation(不过滤/不伪造); 能力分叉由 prompt(G1) 承载。
- 感知不在框架侧过滤: harness 文本原样喂入 persona LLM, 由 prompt(G1)+persona 档位约束"只在能力内感知"。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .action_space import derive_action_space, resolve_action
from .actions import CATALOG, Channel, Effect, Executor, Phase
from .dimensions import Persona
from .feeling import FeelingScore, derive_feeling, parse_feeling_llm
from .persona_client import PersonaClient, drain_call_traces
from .prompt import (
    WAITING_JUDGMENTS,
    build_issue_turn,
    build_main_act_turn,
    build_main_intent_turn,
    build_main_judge_turn,
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


@dataclass
class _UtteranceLedger:
    """局内用户→harness 指令账本：给每条外发编号，reply 挂回它所关闭的 open 指令。

    Spec-0024/T6：persona 仍可能「看见内容才知真相」；落盘/设计师时间线必须显式配对。
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
    feeling_derived: FeelingScore | None = None  # 交叉校验/兜底: 框架从主观末态聚合的 1–4
    # 已收到但尚未进入 TurnLog 的 harness 回复(harness 回复要等下一轮 TurnLog 才随
    # harness_output 落日志, 这里先行暴露给观测层实时展示; 下一条 TurnLog 追加时清空)
    pending_harness_output: str | None = None
    pending_harness_steps: list | None = None  # 与 pending_harness_output 配对的内层过程流
    # 局末不挂某一 Turn 的用户 agent 调用（file_issue 正文 / 体感评分）。
    persona_tail: list = field(default_factory=list)


MAX_TURNS = 12

# 阻塞 send 路径：墙钟超过此值额外耗一点耐心（防无限干等）。心跳路径用 history [+Ns] + 有条件耗心。
_EXTREME_WAIT_SEC = 480.0

# 框架自有的 harness 失败哨兵前缀：route 在 harness.send() 崩溃/超时时回填此串（见下），原样喂给
# 用户 agent 感知。它不再触发任何框架侧动作门控——面对崩溃是否验收/开单/走人，由有判断力的模型自判
# （prompt G6 + 终止时机条主导）；框架只负责把失败如实surfacing，不炸整局、也不替模型下结论。
HARNESS_ERROR_PREFIX = "[harness error] "

# 事件等待（用户等待中的主动权）：
#   AwaitEvent = poll 直到 harness reply（唤醒主 loop）或到心跳阈值（一次性等待决策）。
#   心跳是一次性动作（含 keep_waiting）——做完即结束，回到 AwaitEvent；不为「认领上一笔 send」
#   在心跳里继续 poll。
#   persona 侧仍可能「看见 reply 内容才知发生了什么」；观测侧用 _UtteranceLedger 显式配对
#   （Spec-0024/T6：heard.answers → utterance）。
_HEARTBEAT_SEC = 90.0
# 心跳唤醒次数硬上限（兜底防病态：模型一直 keep_waiting 而 harness 永不回）。到顶即强制放弃。
_MAX_HEARTBEATS = 8
# 等待菜单：内 = send_message；外 = interrupt（Ctrl+C）+ give_up；keep_waiting = 决定继续等。
WAITING_ACTIONS = ["keep_waiting", "send_message", "interrupt", "give_up"]


def _supports_heartbeat(harness) -> bool:
    """真实子进程句柄：begin/poll + 内 emit_message + 外 control(interrupt)；Fake/Scripted 无需心跳。"""
    return all(hasattr(harness, m) for m in ("begin", "poll", "control", "emit_message"))


def _take_persona_calls(client: PersonaClient, role: str) -> list[dict]:
    """drain client 上刚结束的原始调用，打上 role 标签（供 TurnLog / persona_tail）。"""
    out: list[dict] = []
    for call in drain_call_traces(client):
        tagged = dict(call)
        tagged["role"] = role
        out.append(tagged)
    return out


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


def _main_decide(
    *,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    harness_output: str,
    space: list,
    state: State,
    manual: str,
    appraise_task: bool,
    result: SessionResult,
) -> tuple[dict, list[dict], str, bool]:
    """主 loop 同构决策：judge → intent → act（Spec-0023：仅 three）。

    返回 (act_ret 含 action/message, persona_calls, intent, gap)。
    judge 的 perceive/verdict/task_load 已合并进 act_ret，供后续 apply_verdict / 开局 task_load。
    """
    calls: list[dict] = []
    jret = client.respond(
        system,
        build_main_judge_turn(
            task,
            history,
            harness_output,
            space,
            state,
            manual=manual,
            appraise_task=appraise_task,
        ),
    )
    calls.extend(_take_persona_calls(client, "main_judge"))
    perceive = str(jret.get("perceive", ""))
    verdict = str(jret.get("verdict", "unsure"))
    task_load = jret.get("task_load")
    iret = client.respond(
        system,
        build_main_intent_turn(
            task,
            history,
            harness_output,
            space,
            state,
            manual=manual,
            verdict=verdict,
            perceive=perceive,
        ),
    )
    calls.extend(_take_persona_calls(client, "main_intent"))
    intent = _resolve_intent(iret)

    aret = client.respond(
        system,
        build_main_act_turn(
            task,
            history,
            harness_output,
            space,
            state,
            manual=manual,
            verdict=verdict,
            perceive=perceive,
            intent=intent,
        ),
    )
    calls.extend(_take_persona_calls(client, "main_act"))
    _drain_issue_notes(client, result)
    gap = _resolve_gap(aret)
    merged = {
        "perceive": perceive,
        "verdict": verdict,
        "intent": intent,
        "action": aret.get("action"),
        "message": aret.get("message", ""),
        "gap": gap,
    }
    if task_load is not None:
        merged["task_load"] = task_load
    return merged, calls, intent, gap


def route(action_id: str, message: str, state: State, harness, observable: str) -> str | None:
    """按 executor×channel 分派, 返回下一轮的 harness 文本(无则 None)。"""
    spec = CATALOG[action_id]

    if spec.executor is Executor.FRAMEWORK:  # verify_self: 注入原始观察(不过滤/不伪造)
        state.pending_self_obs = observable or ""
        return None

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


def _drain_issue_notes(client: PersonaClient, result: SessionResult) -> None:
    """把 agentic 中途 report_issue 笔记并入 SessionResult（允许闲置；无则空操作）。"""
    drain = getattr(client, "drain_issue_notes", None)
    if not callable(drain):
        return
    for note in drain():
        text = str(note).strip()
        if not text:
            continue
        result.issue_notes.append(text)
        result.signals.append(f"ISSUE_TOOL: report_issue ({len(result.issue_notes)})")


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
    persona: Persona,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    state: State,
) -> None:
    """终止收尾：记 end_reason；对 file_issue/give_up/accept_with_reservations 以本人口吻并出一条 issue。"""
    spec = CATALOG[action_id]
    result.end_reason = spec.end_reason or "terminated"
    issue_mode = {
        "file_issue": "filed",
        "give_up": "left",
        "accept_with_reservations": "accepted",
    }.get(action_id)
    if issue_mode is not None:
        issue_resp = client.respond(system, build_issue_turn(task, history, state, mode=issue_mode))
        result.persona_tail.extend(_take_persona_calls(client, "file_issue"))
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
    manual: str,
    result: SessionResult,
    on_progress: Callable[[SessionResult], None] | None,
    prior_activity: list[dict],
    waited_sec: float,
    progress: list[dict],
    progress_seen: int,
    heartbeats: int,
    ledger: _UtteranceLedger,
) -> tuple[str, str, bool, int]:
    """一次性等待决策（timer 触发）。任意动作（含 keep_waiting）做完即结束本次心跳。

    Spec-0023：仅 judge → intent → act（three）。
    返回 (action, message, gap, new_progress_seen)。
    强制 give_up：心跳次数触顶，或 keep_waiting 且无新进度把耐心耗尽。
    """
    new_progress = len(progress) > progress_seen
    seen = len(progress)
    ctx = dict(
        task=task,
        history_lines=history,
        state=state,
        manual=manual,
        waited_sec=waited_sec,
        progress=progress,
        prior_activity=prior_activity,
    )
    jret = client.respond(system, build_waiting_judge_turn(**ctx))
    wait_calls = _take_persona_calls(client, "waiting_judge")
    judgment = _resolve_judgment(jret)
    perceive = str(jret.get("perceive", ""))
    iret = client.respond(
        system,
        build_waiting_intent_turn(
            **ctx,
            judgment=judgment,
            perceive=perceive,
        ),
    )
    wait_calls.extend(_take_persona_calls(client, "waiting_intent"))
    intent = _resolve_intent(iret)
    aret = client.respond(
        system,
        build_waiting_act_turn(
            **ctx,
            judgment=judgment,
            perceive=perceive,
            intent=intent,
        ),
    )
    wait_calls.extend(_take_persona_calls(client, "waiting_act"))
    _drain_issue_notes(client, result)
    action, wait_message, gap = _resolve_waiting(aret)
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
    manual: str,
    result: SessionResult,
    on_progress: Callable[[SessionResult], None] | None,
    prior_activity: list[dict],
    ledger: _UtteranceLedger,
    open_utterance_id: str,
) -> tuple[str, float, str | None, str | None]:
    """begin 后进入 AwaitEvent：reply → 交主 loop；timer → 一次性心跳后回到 AwaitEvent。

    Spec-0024/T6：本轮 begin 对应 open_utterance_id；收到的 reply/interrupt 关闭该 open。
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
        harness.begin(message)
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
        action, wait_message, _gap, progress_seen = _heartbeat_once(
            client=client,
            system=system,
            task=task,
            history=history,
            clock=clock,
            state=state,
            coef=coef,
            manual=manual,
            result=result,
            on_progress=on_progress,
            prior_activity=prior_activity,
            waited_sec=waited,
            progress=progress,
            progress_seen=progress_seen,
            heartbeats=heartbeats,
            ledger=ledger,
        )
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
                harness.emit_message(wait_message)
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
                ctrl_out = harness.control("interrupt")
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
            return str(ctrl_out), time.monotonic() - t0, None, "interrupt"
        if action == "give_up":
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
    manual: str = "",
    on_progress: Callable[[SessionResult], None] | None = None,
) -> SessionResult:
    # on_progress: 每轮写完 TurnLog 后回调一次进行中的 result(含终止轮)，供观测层(看板)逐轮展示。
    # Spec-0023：主决定与心跳均为 judge → intent → act（three），无 mode 旋钮。
    coef = make_coef(persona)
    state = init_state(persona)
    system = build_system(persona)

    result = SessionResult(persona_id=persona.persona_id, end_reason="max_turns")
    history: list[str] = []
    clock = _SessionClock()
    harness_output = ""
    harness_steps: list = []  # 与 harness_output 配对的内层过程流
    prior_activity: list[dict] = []  # 上一轮已完成请求的活动条（过程记忆，供对照）
    ledger = _UtteranceLedger()  # Spec-0024/T6：请求–回复配对

    while state.turn < MAX_TURNS:
        phase = Phase.OPENING if state.turn == 0 and not history else Phase.ACTIVE

        # ② 派生动作空间
        space = derive_action_space(phase, persona, state)

        # ③ 同构主决定：judge → intent → act。
        ret, decide_calls, intent, gap = _main_decide(
            client=client,
            system=system,
            task=task,
            history=history,
            harness_output=harness_output,
            space=space,
            state=state,
            manual=manual,
            appraise_task=phase is Phase.OPENING,
            result=result,
        )
        state.pending_self_obs = None  # 用后即焚: self_observation 已被消费

        # 开局：据 persona 主观任务量读数，在耐心基线上叠加一次性小浮动（同一个人接不同任务耐心不同）。
        if phase is Phase.OPENING:
            apply_task_load(state, str(ret.get("task_load", "normal")))

        # ③.5 方案 B：action=='free' 交给模型自评归类到合法 id（替代关键词硬猜）。
        # 仅 client 支持 classify_action 时启用；否则落 resolve 的安全兜底。
        if ret.get("action") == "free" and hasattr(client, "classify_action"):
            ret = {**ret, "action": client.classify_action(system, ret, space)}
            decide_calls.extend(_take_persona_calls(client, "classify_action"))

        # ④ resolve: 归类 + 投影 + channel 校验
        action_id, message = resolve_action(ret, space, persona)
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
        if spec.channel is Channel.EMIT and message.strip():
            utterance_id = ledger.alloc(message)
            delivery = "open"

        result.pending_harness_output = None  # 该回复即将随本条 TurnLog 落日志, 不再悬挂
        result.pending_harness_steps = None
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
                persona_trace=decide_calls,
                utterance_id=utterance_id,
                delivery=delivery,
                answers_utterance_id=answers_id,
                answers_said=answers_said,
            )
        )
        if gap:
            result.signals.append(f"WAIT_GAP: intent={intent} action={action_id}")
        if on_progress is not None:
            on_progress(result)  # 逐轮观测钩子(含终止轮): 喂给看板等观测层, 不影响主循环

        # 记历史(只记 B 线真正发出的话；空 message 不 fabricate、不入史)；统一 [+Ns] 前缀。
        if spec.channel is Channel.EMIT and message.strip():
            clock.stamp(history, f"you -> harness: {message}")

        # ⑥ 终止判定（三种终止都以本人口吻留一条自包含 issue，见 _finalize_terminal）
        if spec.effect is Effect.TERMINATE:
            _finalize_terminal(
                action_id,
                result=result,
                persona=persona,
                client=client,
                system=system,
                task=task,
                history=history,
                state=state,
            )
            break

        # ⑦ 路由。EMIT：真实子进程走 AwaitEvent（reply→主 decide；timer→一次性心跳）；
        # Fake/Scripted 退回阻塞 route。
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
                manual=manual,
                result=result,
                on_progress=on_progress,
                prior_activity=prior_activity,
                ledger=ledger,
                open_utterance_id=utterance_id,
            )
            if terminal_from_wait == "give_up":  # 等待决策放弃：走终止路径并结束
                _finalize_terminal(
                    "give_up",
                    result=result,
                    persona=persona,
                    client=client,
                    system=system,
                    task=task,
                    history=history,
                    state=state,
                )
                break
        else:
            nxt = route(action_id, message, state, harness, harness_output)
            elapsed = time.monotonic() - _t0
            if nxt is not None:
                clock.observe(clock.now() + elapsed)
                # 阻塞 route：reply 即关闭本拍刚分配的 open utterance
                if utterance_id:
                    ledger.mark_open(utterance_id)
                    ledger.close_open_as_answered()
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
            if on_progress is not None:
                on_progress(result)
        # verify_self: harness_output 不变, 但 self_obs 已注入下一轮

    # 收尾: 汇总纯主观的行为信号
    _collect_signals(result, persona)

    # 会话末两路并出体感分 (训练信号), 均只吃主观信号, 不读客观真值:
    # ② 框架派生: 从 end_reason / verdict / trust 确定性聚合, 可复现, 也作兜底
    result.feeling_derived = derive_feeling(result.end_reason, result.turns)
    # ① LLM 自评: persona 在角色内给"这次体验"打 1–4 + 理由 (spec-0001/T3 产出方式)
    rating = client.respond(system, build_rating_turn(task, history, state))
    result.persona_tail.extend(_take_persona_calls(client, "rate"))
    result.feeling = parse_feeling_llm(rating) or result.feeling_derived
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
