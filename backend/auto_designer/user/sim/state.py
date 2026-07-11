"""
state.py
状态层 —— 跨轮记忆带。三层认知主干每轮读它/写它。

铁律:
  状态更新只吃 *主观 verdict*(persona 感知到的)。情绪只对"自己感知到的事"反应。
  本轮纯主观: 不存在任何客观真值入口(无 gold / outcome / GAP)。
persona 是系数(决定变化速率/力度), state 是被积分的量。
"""

from __future__ import annotations

from dataclasses import dataclass

from .dimensions import D1Eval, D43Correct, Persona, TrustStance

# 主观判断枚举(LLM 在 OUTPUT CONTRACT 里产出)
VERDICTS = {
    "satisfied",
    "failed_blame_harness",
    "failed_blame_self",
    "unsure",
    "stuck",  # harness 故障/空转/复读/无进展：区别于"存疑待核实"的 unsure，受挫掉耐心
}


@dataclass
class Coef:
    """persona 派生的状态演化系数。"""

    patience_decay: int = 1
    trust_decay: int = 1
    trust_recover: int = 1


@dataclass
class State:
    turn: int = 0
    patience: int = 4  # 跨轮耐心计数器, <=0 解锁终止
    trust: TrustStance = TrustStance.BALANCED
    pending_self_obs: str | None = None  # verify_self 注入下一轮的私有观察
    consec_blame: int = 0  # 连续判定 harness 失败的次数; 驱动"诊断式"升级(非耐心消耗)
    consec_stuck: int = 0  # 连续 stuck 次数; 仅作耐心加性递增衰减的倍率(非终止门)


# 信任三档的整型刻度, 便于增减后再映射回枚举
_TRUST_SCALE = [TrustStance.SKEPTICAL, TrustStance.BALANCED, TrustStance.BLIND]


def _trust_to_int(t: TrustStance) -> int:
    return _TRUST_SCALE.index(t)


def _int_to_trust(i: int) -> TrustStance:
    i = max(0, min(i, len(_TRUST_SCALE) - 1))
    return _TRUST_SCALE[i]


def make_coef(p: Persona) -> Coef:
    """persona -> 状态演化系数。"""
    # 急躁/低容错倾向 -> 耐心掉得快
    patience_decay = 2 if p.d43 in (D43Correct.GIVE_UP, D43Correct.RESEND) else 1
    # 越懂行, 看穿错误后信任崩得越快(反直觉但真实)
    trust_decay = 2 if p.d1 in (D1Eval.COMPETENT, D1Eval.EXPERT) else 1
    trust_recover = 1
    return Coef(patience_decay, trust_decay, trust_recover)


def init_state(p: Persona) -> State:
    patience_base = {  # D4.3 给耐心基线
        D43Correct.GIVE_UP: 3,
        D43Correct.RESEND: 4,
        D43Correct.FEEDBACK: 5,
        D43Correct.HANDOVER: 6,
        D43Correct.FILE_ISSUE: 6,
    }.get(p.d43, 4)
    return State(turn=0, patience=patience_base, trust=p.trust)


# 任务量 -> 起始耐心浮动：同一个人接不同任务，耐心不一样。大/开放式/有野心的活儿预期要真功夫，
# 愿意多等、多来回（起始耐心更高）；该秒回的小任务则对任何摩擦零容忍（起始耐心更低）。
# 范围压得很小（-1…+2），只做基线上的微浮动，不盖过 D4.3 性格给的耐心档位。
TASK_LOAD_DELTA: dict[str, int] = {
    "quick": -1,  # 琐碎/理应秒回
    "normal": 0,  # 常规任务
    "big": 1,  # 有分量、多步
    "epic": 2,  # 大、开放式、有野心
}


def apply_task_load(state: State, load: str) -> State:
    """开局据 persona 对任务量的主观读数，在耐心基线上叠加一次性小浮动（钳到 >=1，别一开局就可终止）。"""
    state.patience = max(1, state.patience + TASK_LOAD_DELTA.get(load, 0))
    return state


def apply_verdict(state: State, verdict: str, coef: Coef) -> State:
    """每轮: 用主观 verdict 改写状态。客观线绝不进此函数。"""
    assert verdict in VERDICTS, f"unknown verdict {verdict}"
    state.turn += 1
    t = _trust_to_int(state.trust)

    if verdict == "satisfied":
        t += coef.trust_recover
        state.consec_blame = 0
        state.consec_stuck = 0
    elif verdict == "failed_blame_harness":
        state.patience -= coef.patience_decay
        t -= coef.trust_decay
        state.consec_blame += 1  # 连续坐实 harness 失败 -> 累计诊断
        state.consec_stuck = 0
    elif verdict == "failed_blame_self":
        state.patience -= coef.patience_decay  # 怪自己也耗耐心
        # 但不砸对 harness 的信任 -> t 不变; 怪自己不计入"harness 能力缺口"诊断
        state.consec_blame = 0
        state.consec_stuck = 0
    elif verdict == "unsure":
        state.patience -= 0  # 存疑不耗耐心：尽职核查不该被罚
        state.consec_blame = 0  # 非连续 -> 诊断计数清零("连续"严格语义)
        state.consec_stuck = 0
    elif verdict == "stuck":
        # harness 故障/空转/复读/无进展：受挫掉耐心，且连续越久掉得越狠(加性递增，符合"越拖越火")。
        # 全归于耐心——不另开升级门，最终仍走 patience<=0 解锁终止(能力无关：任何用户都察觉得到卡住)。
        # 加性递增：首次 stuck 扣 3，之后每多连一次 +1（3→4→5→6…）。
        state.consec_stuck += 1
        state.patience -= state.consec_stuck + 2
        state.consec_blame = 0  # stuck 非"坐实能力缺口"式的 blame -> 诊断计数清零

    state.trust = _int_to_trust(t)
    return state
