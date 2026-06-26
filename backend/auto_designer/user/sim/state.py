"""
state.py
状态层 —— 跨轮记忆带。三层认知主干每轮读它/写它。

铁律(之前修过的 bug):
  状态更新只吃 *主观 verdict*(persona 感知到的), 绝不吃客观线 outcome.failed。
  情绪只对"自己感知到的事"反应; 客观真值走旁路(终止/评估/GAP), 不回灌状态。
persona 是系数(决定变化速率/力度), state 是被积分的量。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dimensions import D1Eval, D43Correct, Persona, TrustStance

# 主观判断枚举(LLM 在 OUTPUT CONTRACT 里产出)
VERDICTS = {
    "satisfied",
    "failed_blame_harness",
    "failed_blame_self",
    "unsure",
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
    patience: int = 4              # 跨轮耐心计数器, <=0 解锁终止
    trust: TrustStance = TrustStance.BALANCED
    history: list = field(default_factory=list)  # 主观判断记录(perceived), 非客观真值
    pending_self_obs: str | None = None          # verify_self 注入下一轮的私有观察
    last_verdict: str | None = None


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


def apply_verdict(state: State, verdict: str, coef: Coef) -> State:
    """每轮: 用主观 verdict 改写状态。客观线绝不进此函数。"""
    assert verdict in VERDICTS, f"unknown verdict {verdict}"
    state.turn += 1
    t = _trust_to_int(state.trust)

    if verdict == "satisfied":
        t += coef.trust_recover
    elif verdict == "failed_blame_harness":
        state.patience -= coef.patience_decay
        t -= coef.trust_decay
    elif verdict == "failed_blame_self":
        state.patience -= coef.patience_decay   # 怪自己也耗耐心
        # 但不砸对 harness 的信任 -> t 不变
    elif verdict == "unsure":
        state.patience -= 0  # 存疑不耗耐心(可调为轻微损耗)

    state.trust = _int_to_trust(t)
    state.last_verdict = verdict
    return state
