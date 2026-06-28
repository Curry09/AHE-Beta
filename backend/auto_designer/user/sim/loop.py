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
- verify_self: 框架按能力掩码过滤"可观察到的东西"(最近一次 harness 文本)后注入 self_observation。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .action_space import cap_mask, derive_action_space, resolve_action
from .actions import CATALOG, Channel, Effect, Executor, Phase
from .dimensions import Persona
from .feeling import FeelingScore, derive_feeling, parse_feeling_llm
from .persona_client import PersonaClient
from .prompt import build_rating_turn, build_system, build_user_turn
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
    feeling: FeelingScore | None = None          # 训练信号: persona LLM 会话末自评 (1–4)
    feeling_derived: FeelingScore | None = None  # 交叉校验/兜底: 框架从主观末态聚合的 1–4


MAX_TURNS = 12


def _filter_self_obs(observable: str, mask: dict) -> str:
    """verify_self 时, 按能力掩码把"可观察到的最近 harness 文本"降级成 persona 私有观察。
    SHALLOW 只看到'跑通/报错', 看不到它没构造的边界。"""
    if "Traceback" in observable or "Error" in observable:
        return "I ran it once and it crashed with an error."
    if not mask.get("run_tests"):
        return "I ran it once on a normal input; no error, output looked fine."
    return observable  # 高能力者(能跑测试)看到更完整的回显


def perceive_filter(harness_output: str, mask: dict) -> str:
    """感知侧能力掩码: 能力掩码不止 gate 动作, 也 gate *感知输入*。

    不会 review_diff 的用户(blind/shallow)在 <harness_output> 里看不到源码逐行 ——
    只看到 prose 声明 / 运行回显 / 报错(他们真能感知的东西)。能 review_diff 者原样看。
    动机: 防强模型把喂进来的代码 *心算* 出来从而越过低能力档(违反 G1)。
    """
    if not harness_output or mask.get("review_diff"):
        return harness_output
    out: list[str] = []
    in_code = False
    for line in harness_output.splitlines():
        s = line.strip()
        indented = line[:4] == "    "
        looks_src = (
            indented and any(k in s for k in ("def ", "return ", "import ", "lambda ", "class "))
        ) or (
            indented and "=" in s and "->" not in s
            and not s.startswith("$") and "sum" not in s.lower()
        )
        if looks_src:
            if not in_code:
                out.append("    [the assistant changed the code — you don't read the diff line by line]")
                in_code = True
            continue
        in_code = False
        out.append(line)
    return "\n".join(out)


def route(action_id: str, message: str, state: State, harness, mask: dict,
          observable: str) -> str | None:
    """按 executor×channel 分派, 返回下一轮的 harness 文本(无则 None)。"""
    spec = CATALOG[action_id]

    if spec.executor is Executor.FRAMEWORK:        # verify_self: 框架代跑, 按能力掩码注入私有观察
        state.pending_self_obs = _filter_self_obs(observable or "ran, no error", mask)
        return None

    if spec.channel is Channel.EMIT and spec.effect is not Effect.TERMINATE:
        return harness.send(message)               # 发 B 线 -> 驱动 harness 出下一轮文本

    return None  # 终止动作: 不再驱动 harness


def emit_issue_artifact(persona: Persona, log: list[TurnLog]) -> str:
    """从本局真实(主观)数据派生 issue(不写死场景, 不读客观真值)。"""
    fails = [t for t in log if t.verdict == "failed_blame_harness"]
    last_out = next((t.harness_output for t in reversed(log) if t.harness_output.strip()), "")
    if last_out.strip():
        symptom = last_out.strip().splitlines()[-1][:160]
    else:
        symptom = "the delivered result did not meet the user's bar"
    return (
        f"## Issue filed by simulated user {persona.persona_id}\n"
        f"**Repro turns:** {len(log)} (failed_blame_harness: {len(fails)})\n"
        f"**Symptom (last harness output):** {symptom}\n"
        f"**User capability:** {persona.d1.value}; correction style: {persona.d43.value}.\n"
    )


def run_session(persona: Persona, client: PersonaClient, harness, task: str) -> SessionResult:
    coef = make_coef(persona)
    state = init_state(persona)
    mask = cap_mask(persona)
    system = build_system(persona)

    result = SessionResult(persona_id=persona.persona_id, end_reason="max_turns")
    history: list[str] = []
    harness_output = ""
    has_artifact = False

    while state.turn < MAX_TURNS:
        phase = Phase.OPENING if state.turn == 0 and not history else Phase.ACTIVE

        # ② 派生动作空间
        space = derive_action_space(phase, persona, state, has_artifact)

        # ③ 主观三层 (LLM). harness 输出先过感知侧能力掩码再喂 persona。
        shown_output = perceive_filter(harness_output, mask)
        user = build_user_turn(task, history, shown_output, space, state)
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

        result.turns.append(TurnLog(
            turn=state.turn, phase=phase.value, action_space=space,
            perceive=ret.get("perceive", ""), verdict=verdict,
            action=action_id, message=message,
            executor=spec.executor.value, channel=spec.channel.value,
            patience=state.patience, trust=state.trust.value,
            harness_output=harness_output,
        ))

        # 记历史(只记 B 线可见内容)
        if spec.channel is Channel.EMIT:
            history.append(f"[turn {state.turn}] you -> harness: {message}")

        # ⑥ 终止判定
        if spec.effect is Effect.TERMINATE:
            result.end_reason = spec.end_reason or "terminated"
            if action_id == "file_issue":
                result.issue_artifact = emit_issue_artifact(persona, result.turns)
            break

        # ⑦ 路由 -> 下一轮 harness 输入
        nxt = route(action_id, message, state, harness, mask, harness_output)
        if nxt is not None:
            harness_output = nxt
            history.append(f"[turn {state.turn}] harness -> you: {nxt.splitlines()[0][:80]}...")
            has_artifact = True   # harness 给出了可评判的产物
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
