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

from collections.abc import Callable
from dataclasses import dataclass, field

from .action_space import derive_action_space, resolve_action
from .actions import CATALOG, Channel, Effect, Executor, Phase
from .dimensions import Persona
from .feeling import FeelingScore, derive_feeling, parse_feeling_llm
from .persona_client import PersonaClient
from .prompt import build_issue_turn, build_rating_turn, build_system, build_user_turn
from .state import VERDICTS, State, apply_verdict, init_state, make_coef


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


MAX_TURNS = 12


def route(action_id: str, message: str, state: State, harness, observable: str) -> str | None:
    """按 executor×channel 分派, 返回下一轮的 harness 文本(无则 None)。"""
    spec = CATALOG[action_id]

    if spec.executor is Executor.FRAMEWORK:  # verify_self: 注入原始观察(不过滤/不伪造)
        state.pending_self_obs = observable or ""
        return None

    if spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE:
        return harness.send(message)  # 发 B 线 -> 驱动 harness 出下一轮文本

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


def run_session(
    persona: Persona,
    client: PersonaClient,
    harness,
    task: str,
    on_progress: Callable[[SessionResult], None] | None = None,
) -> SessionResult:
    # on_progress: 每轮写完 TurnLog 后回调一次进行中的 result(含终止轮)，供观测层(看板)逐轮展示。
    coef = make_coef(persona)
    state = init_state(persona)
    system = build_system(persona)

    result = SessionResult(persona_id=persona.persona_id, end_reason="max_turns")
    history: list[str] = []
    harness_output = ""
    has_artifact = False

    while state.turn < MAX_TURNS:
        phase = Phase.OPENING if state.turn == 0 and not history else Phase.ACTIVE

        # ② 派生动作空间
        space = derive_action_space(phase, persona, state, has_artifact)

        # ③ 主观三层 (LLM). harness 文本原样喂入; 能力分叉由 prompt(G1)+persona 档位约束, 不在框架侧过滤。
        user = build_user_turn(task, history, harness_output, space, state)
        ret = client.respond(system, user)
        state.pending_self_obs = None  # 用后即焚: self_observation 已被消费

        # ④ resolve: 归类 + 投影 + channel 校验
        action_id, message = resolve_action(ret, space, persona)
        spec = CATALOG[action_id]

        # ⑤ 状态写回 (只吃主观 verdict)
        verdict = ret.get("verdict", "unsure")
        if verdict not in VERDICTS:
            verdict = "unsure"
        apply_verdict(state, verdict, coef)

        result.pending_harness_output = None  # 该回复即将随本条 TurnLog 落日志, 不再悬挂
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
            )
        )
        if on_progress is not None:
            on_progress(result)  # 逐轮观测钩子(含终止轮): 喂给看板等观测层, 不影响主循环

        # 记历史(只记 B 线可见内容)
        if spec.channel is Channel.EMIT:
            history.append(f"[turn {state.turn}] you -> harness: {message}")

        # ⑥ 终止判定
        if spec.effect is Effect.TERMINATE:
            result.end_reason = spec.end_reason or "terminated"
            if action_id == "file_issue":
                # 专门一轮：让 persona 跳出对话、以本人口吻写自包含 issue（≠ 撂给 harness 的临场 message）
                issue_resp = client.respond(system, build_issue_turn(task, history, state))
                issue_text = str(issue_resp.get("issue") or "")
                result.issue_artifact = emit_issue_artifact(persona, result.turns, issue_text)
            break

        # ⑦ 路由 -> 下一轮 harness 输入
        nxt = route(action_id, message, state, harness, harness_output)
        if nxt is not None:
            harness_output = nxt
            history.append(f"[turn {state.turn}] harness -> you: {nxt.splitlines()[0][:80]}...")
            has_artifact = True  # harness 给出了可评判的产物
            # harness 回复到手即推观测层(不等 persona 下一轮), 否则长任务期间看板对话缺半边
            result.pending_harness_output = nxt
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
