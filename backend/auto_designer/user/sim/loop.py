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
from .persona_client import PersonaClient
from .prompt import (
    build_issue_turn,
    build_rating_turn,
    build_system,
    build_user_turn,
    build_waiting_turn,
)
from .state import VERDICTS, State, apply_task_load, apply_verdict, init_state, make_coef


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


@dataclass
class SessionResult:
    persona_id: str
    end_reason: str
    turns: list[TurnLog] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)  # 给开发者的行为反馈信号(纯主观派生)
    issue_artifact: str | None = None
    feeling: FeelingScore | None = None  # 训练信号: persona LLM 会话末自评 (1–4)
    feeling_derived: FeelingScore | None = None  # 交叉校验/兜底: 框架从主观末态聚合的 1–4
    # 已收到但尚未进入 TurnLog 的 harness 回复(harness 回复要等下一轮 TurnLog 才随
    # harness_output 落日志, 这里先行暴露给观测层实时展示; 下一条 TurnLog 追加时清空)
    pending_harness_output: str | None = None
    pending_harness_steps: list | None = None  # 与 pending_harness_output 配对的内层过程流


MAX_TURNS = 12

# 时间感知（用户视角的墙钟预算，全局固定，可调）：一次 harness 回合等待多久算"难受"。
# EXTREME 之外只把耗时如实 surfacing 给模型自判（见 build_user_turn）；到 EXTREME 才额外给一点
# 自动耗心（干等太久的挫败会累积，防"再好的 persona 也无限干等"）。默认对齐 harness 自身 ~240s 硬超时。
_TURN_WAIT_BUDGET_SEC = 240.0
_EXTREME_WAIT_SEC = 480.0

# 框架自有的 harness 失败哨兵前缀：route 在 harness.send() 崩溃/超时时回填此串（见下），原样喂给
# 用户 agent 感知。它不再触发任何框架侧动作门控——面对崩溃是否验收/开单/走人，由有判断力的模型自判
# （prompt G6 + 终止时机条主导）；框架只负责把失败如实surfacing，不炸整局、也不替模型下结论。
HARNESS_ERROR_PREFIX = "[harness error] "

# 心跳（用户等待中的主动权）：一次 send 阻塞超过该秒数仍无回复，就唤醒用户 agent 做一次"等待决策"
# （继续等 / 动用手册里的控制 / 放弃）。这把"计时"从事后感知升级为等待中途可介入，贴近真实用户。
_HEARTBEAT_SEC = 90.0
# 心跳唤醒次数硬上限（兜底防病态：模型一直"继续等"而 harness 永不回）。到顶即强制放弃；正常情况下
# 会先被 harness 自身单轮上界（~16min → [harness error]）或耐心耗尽终结。
_MAX_HEARTBEATS = 8
# 心跳唤醒时给用户 agent 的等待动作集（框架元行为 + 一个"调用手册所述控制"的通用口）。
WAITING_ACTIONS = ["keep_waiting", "invoke_control", "give_up"]


def _supports_heartbeat(harness) -> bool:
    """真实子进程句柄才有 begin/poll/control（可续等 + 通用控制面）；Fake/Scripted 即时返回、无需心跳。"""
    return all(hasattr(harness, m) for m in ("begin", "poll", "control"))


def _resolve_waiting(ret: dict) -> tuple[str, str]:
    """把心跳唤醒的自由产出归到 {keep_waiting, invoke_control, give_up} 之一 + 控制名（仅 invoke_control）。

    非法/缺省一律安全落到 keep_waiting（绝不擅自替用户放弃或打断）。控制名对框架不透明，原样透传给
    harness.control()——是否为该版 harness 支持的控制，由 harness 自己校验（手册是能力真相源）。"""
    action = str(ret.get("action", "")).strip()
    if action not in WAITING_ACTIONS:
        action = "keep_waiting"
    control = str(ret.get("control", "")).strip()
    if action == "invoke_control" and not control:
        action = "keep_waiting"  # 说要用控制却没点名 → 退回继续等，不瞎猜控制名
    return action, control


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
    control: str,
    ret: dict,
    on_progress: Callable[[SessionResult], None] | None,
) -> None:
    """把一次心跳唤醒的等待决策记为 phase='waiting' 的 TurnLog（观测用，不占 harness_output）。"""
    label = f"{action}:{control}" if action == "invoke_control" and control else action
    result.turns.append(
        TurnLog(
            turn=state.turn,
            phase="waiting",
            action_space=list(WAITING_ACTIONS),
            perceive=str(ret.get("perceive", "")),
            verdict="stuck",
            action=label,
            message="",
            executor=Executor.PERSONA_LOCAL.value,
            channel=Channel.SILENT.value,
            patience=state.patience,
            trust=state.trust.value,
            harness_output="",
            harness_steps=[],
        )
    )
    if on_progress is not None:
        on_progress(result)


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
        issue_text = str(issue_resp.get("issue") or "")
        result.issue_artifact = emit_issue_artifact(persona, result.turns, issue_text)


def _supervise_send(
    harness,
    message: str,
    *,
    client: PersonaClient,
    system: str,
    task: str,
    history: list[str],
    state: State,
    manual: str,
    result: SessionResult,
    on_progress: Callable[[SessionResult], None] | None,
) -> tuple[str, float, str | None]:
    """驱动 harness 出下一轮，但用心跳守望等待：超阈值仍无回复就唤醒用户 agent 决策。

    返回 (harness_output, elapsed_sec, terminal_action)：
      - 正常/打断：harness_output 为回复文本（打断走 harness.control → "[interrupted]…"），terminal=None；
      - 崩溃/超时：harness_output 为 [harness error] 串，terminal=None；
      - 用户在等待中放弃：harness_output=""，terminal="give_up"（由调用方走终止路径）。
    心跳唤醒轮以 phase='waiting' 记入 result.turns（观测用）。"""
    t0 = time.monotonic()
    try:
        harness.begin(message)
    except Exception as exc:  # noqa: BLE001  黑盒起轮失败 → 可观测失败信号
        return f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}", time.monotonic() - t0, None
    heartbeats = 0
    while True:
        try:
            kind, val = harness.poll(_HEARTBEAT_SEC)
        except Exception as exc:  # noqa: BLE001  黑盒崩溃/超时 → 可观测失败信号（不炸整局）
            return f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}", time.monotonic() - t0, None
        if kind == "reply":
            return str(val), time.monotonic() - t0, None
        # kind == "pending"：等待超阈值 → 唤醒用户 agent 做一次等待决策
        waited = float(val)  # type: ignore[arg-type]
        heartbeats += 1
        ret = client.respond(
            system, build_waiting_turn(task, history, state, manual=manual, waited_sec=waited)
        )
        action, control = _resolve_waiting(ret)
        if heartbeats >= _MAX_HEARTBEATS:
            action = "give_up"  # 兜底：唤醒到顶强制收束，防病态无限等
        elif action == "keep_waiting":
            state.patience = max(0, state.patience - 1)  # 干等挫败累积
            if state.patience <= 0:
                action = "give_up"  # 耐心耗尽：这个人不会再等了
        _log_waiting(result, state, action, control, ret, on_progress)
        if action == "invoke_control":
            try:
                reply = harness.control(control)  # control 名对框架不透明，由 harness 校验
            except Exception as exc:  # noqa: BLE001
                reply = f"{HARNESS_ERROR_PREFIX}{type(exc).__name__}: {exc}"
            return reply, time.monotonic() - t0, None
        if action == "give_up":
            return "", time.monotonic() - t0, "give_up"
        # keep_waiting：回到 poll 续等（在途读线程保留，计算不丢）


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
    coef = make_coef(persona)
    state = init_state(persona)
    system = build_system(persona)

    result = SessionResult(persona_id=persona.persona_id, end_reason="max_turns")
    history: list[str] = []
    harness_output = ""
    harness_steps: list = []  # 与 harness_output 配对的内层过程流
    last_wait_sec: float | None = None  # 上一条 harness 回复的墙钟等待耗时（首轮 None）

    while state.turn < MAX_TURNS:
        phase = Phase.OPENING if state.turn == 0 and not history else Phase.ACTIVE

        # ② 派生动作空间
        space = derive_action_space(phase, persona, state)

        # ③ 主观三层 (LLM). harness 文本原样喂入; 能力分叉由 prompt(G1)+persona 档位约束, 不在框架侧过滤。
        # manual：该版本 harness 用户手册（能力预期锚点）；last_wait_sec：上条回复的墙钟等待（时间感知）。
        user = build_user_turn(
            task,
            history,
            harness_output,
            space,
            state,
            manual=manual,
            wait_sec=last_wait_sec,
            appraise_task=phase is Phase.OPENING,  # 开局让 persona 估任务分量，据此调起始耐心
        )
        ret = client.respond(system, user)
        state.pending_self_obs = None  # 用后即焚: self_observation 已被消费

        # 开局：据 persona 主观任务量读数，在耐心基线上叠加一次性小浮动（同一个人接不同任务耐心不同）。
        if phase is Phase.OPENING:
            apply_task_load(state, str(ret.get("task_load", "normal")))

        # ③.5 方案 B：action=='free' 交给模型自评归类到合法 id（替代关键词硬猜）。
        # 仅 client 支持 classify_action 时启用；否则落 resolve 的安全兜底。
        if ret.get("action") == "free" and hasattr(client, "classify_action"):
            ret = {**ret, "action": client.classify_action(system, ret, space)}

        # ④ resolve: 归类 + 投影 + channel 校验
        action_id, message = resolve_action(ret, space, persona)
        spec = CATALOG[action_id]

        # ⑤ 状态写回 (只吃主观 verdict)
        verdict = ret.get("verdict", "unsure")
        if verdict not in VERDICTS:
            verdict = "unsure"
        apply_verdict(state, verdict, coef)

        result.pending_harness_output = None  # 该回复即将随本条 TurnLog 落日志, 不再悬挂
        result.pending_harness_steps = None
        result.turns.append(
            TurnLog(
                turn=state.turn,
                phase=phase.value,
                action_space=space,
                perceive=ret.get("perceive", ""),
                verdict=verdict,
                action=action_id,
                message=message,
                executor=spec.executor.value,
                channel=spec.channel.value,
                patience=state.patience,
                trust=state.trust.value,
                harness_output=harness_output,
                harness_steps=harness_steps,
            )
        )
        if on_progress is not None:
            on_progress(result)  # 逐轮观测钩子(含终止轮): 喂给看板等观测层, 不影响主循环

        # 记历史(只记 B 线真正发出的话；空 message 不 fabricate、不入史)
        if spec.channel is Channel.EMIT and message.strip():
            history.append(f"[turn {state.turn}] you -> harness: {message}")

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

        # ⑦ 路由 -> 下一轮 harness 输入。EMIT 且要驱动 harness 的轮：若后端支持心跳（真实子进程），
        # 用 _supervise_send 守望等待（超阈值唤醒用户 agent 决策：继续等/动用控制/放弃）；否则退回阻塞 route。
        _t0 = time.monotonic()
        _emits = spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE
        terminal_from_wait: str | None = None
        if _emits and message.strip() and _supports_heartbeat(harness):
            nxt, elapsed, terminal_from_wait = _supervise_send(
                harness,
                message,
                client=client,
                system=system,
                task=task,
                history=history,
                state=state,
                manual=manual,
                result=result,
                on_progress=on_progress,
            )
            if terminal_from_wait == "give_up":  # 用户在等待中放弃：走终止路径并结束
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
            last_wait_sec = elapsed  # 供下一轮 persona 感知"这条回复我等了多久、全程零可见性"
            # 时间感知·轻耗心：仅极端超时才自动扣一点耐心（挫败累积），日常耗时只 surfacing 交模型自判。
            if elapsed >= _EXTREME_WAIT_SEC:
                state.patience = max(0, state.patience - 1)
            harness_output = nxt
            # 与回复配对的内层过程流：send 后 launcher 把它挂在 harness.last_steps（观测旁路）。
            # Fake/Scripted harness 无此属性 → []。route 只在 EMIT 轮真调 send，此处取值即本轮回复的。
            steps = getattr(harness, "last_steps", None)
            harness_steps = list(steps) if isinstance(steps, list) else []
            history.append(f"[turn {state.turn}] harness -> you: {nxt.splitlines()[0][:80]}...")
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
