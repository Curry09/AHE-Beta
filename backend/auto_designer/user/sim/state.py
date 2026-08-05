"""
state.py
状态层 —— 跨轮记忆带。三层认知主干每轮读它/写它。

Spec-0037/T2: 耐心初值与衰减跟 tempo；stuck_extra 跟过程卷入（d42）；与 d43 正交。

铁律:
  状态更新只吃 *主观 verdict*(persona 感知到的)。情绪只对"自己感知到的事"反应。
  本轮纯主观: 不存在任何客观真值入口(无 gold / outcome / GAP)。
persona 是系数(决定变化速率/力度), state 是被积分的量。

耐心由时间气质（tempo）驱动，不再由质量失败策略（d43）驱动——二者正交。
"""

from __future__ import annotations

from dataclasses import dataclass

from .dimensions import D1Eval, D42Supervise, Persona, TimeTemperament, TrustStance

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
    # stuck 额外倍率：高过程卷入在「像卡住/看不懂进展」时掉耐心更快
    stuck_extra: int = 0


@dataclass
class State:
    turn: int = 0
    patience: int = 4  # 跨轮耐心计数器, <=0 解锁终止
    trust: TrustStance = TrustStance.BALANCED
    private_evidence: list[str] | None = None  # 用户自己用 private tools 查到的跨轮短记忆
    private_evidence_seq: int = 0
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
    """persona -> 状态演化系数。耐心衰减跟 tempo；信任崩塌跟评估能力。"""
    patience_decay = {
        TimeTemperament.PATIENT: 1,
        TimeTemperament.STEADY: 1,
        TimeTemperament.IMPATIENT: 2,
    }[p.tempo]
    trust_decay = 2 if p.d1 in (D1Eval.COMPETENT, D1Eval.EXPERT) else 1
    # 高过程卷入：主观 stuck 时多扣一点（仍不绑定具体产品键）
    stuck_extra = 1 if p.d42 is D42Supervise.EVERY_STEP else 0
    return Coef(
        patience_decay=patience_decay,
        trust_decay=trust_decay,
        trust_recover=1,
        stuck_extra=stuck_extra,
    )


def init_state(p: Persona) -> State:
    patience_base = {
        TimeTemperament.IMPATIENT: 3,
        TimeTemperament.STEADY: 5,
        TimeTemperament.PATIENT: 7,
    }[p.tempo]
    return State(turn=0, patience=patience_base, trust=p.trust)


# 任务量 -> 起始耐心浮动：同一个人接不同任务，耐心不一样。大/开放式/有野心的活儿预期要真功夫，
# 愿意多等、多来回（起始耐心更高）；该秒回的小任务则对任何摩擦零容忍（起始耐心更低）。
# 范围压得很小（-1…+2），只做基线上的微浮动，不盖过 tempo 性格给的耐心档位。
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
        # 加性递增：首次 stuck 扣 3+stuck_extra，之后每多连一次 +1。
        state.consec_stuck += 1
        state.patience -= state.consec_stuck + 2 + coef.stuck_extra
        state.consec_blame = 0  # stuck 非"坐实能力缺口"式的 blame -> 诊断计数清零

    state.trust = _int_to_trust(t)
    return state
