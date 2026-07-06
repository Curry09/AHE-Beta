"""spec-0005/T2：patience/trust 状态机仅吃主观 verdict。"""

from __future__ import annotations

import pytest

from auto_designer.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    TrustStance,
    finalize_persona,
)
from auto_designer.user.sim.state import apply_verdict, init_state, make_coef


def _persona(d1: D1Eval = D1Eval.SHALLOW, d43: D43Correct = D43Correct.FEEDBACK) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P",
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=d43,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


def test_init_state_patience_base_by_d43() -> None:
    assert init_state(_persona(d43=D43Correct.GIVE_UP)).patience == 3
    assert init_state(_persona(d43=D43Correct.FEEDBACK)).patience == 5
    assert init_state(_persona(d43=D43Correct.FILE_ISSUE)).patience == 6


def test_make_coef_reflects_persona() -> None:
    assert make_coef(_persona(d43=D43Correct.GIVE_UP)).patience_decay == 2
    assert make_coef(_persona(d1=D1Eval.EXPERT)).trust_decay == 2
    assert make_coef(_persona(d1=D1Eval.SHALLOW)).trust_decay == 1


def test_apply_verdict_transitions() -> None:
    p = _persona()  # SHALLOW + FEEDBACK -> trust BALANCED, decays = 1
    coef = make_coef(p)

    s = init_state(p)
    apply_verdict(s, "satisfied", coef)
    assert s.turn == 1 and s.trust is TrustStance.BLIND  # 满意 -> 信任上升

    s = init_state(p)
    apply_verdict(s, "failed_blame_harness", coef)
    assert s.patience == 4 and s.trust is TrustStance.SKEPTICAL  # 怪 harness -> 耐心↓信任↓

    s = init_state(p)
    apply_verdict(s, "failed_blame_self", coef)
    assert s.patience == 4 and s.trust is TrustStance.BALANCED  # 怪自己 -> 耐心↓但信任不变

    s = init_state(p)
    apply_verdict(s, "unsure", coef)
    assert s.patience == 5 and s.trust is TrustStance.BALANCED  # 存疑 -> 不耗耐心

    s = init_state(p)
    apply_verdict(s, "stuck", coef)
    # 卡住 -> 耐心↓(首次=一次普通失败代价), 信任不动(纯归耐心)
    assert s.patience == 4 and s.trust is TrustStance.BALANCED


def test_apply_verdict_stuck_escalates_additively() -> None:
    p = _persona()  # FEEDBACK -> patience 基线 5, patience_decay = 1
    coef = make_coef(p)

    s = init_state(p)
    apply_verdict(s, "stuck", coef)  # 第1次: -(1+0) -> 4
    assert s.patience == 4 and s.consec_stuck == 1
    apply_verdict(s, "stuck", coef)  # 第2次: -(1+1) -> 2
    assert s.patience == 2 and s.consec_stuck == 2
    apply_verdict(s, "stuck", coef)  # 第3次: -(1+2) -> -1 (解锁终止)
    assert s.patience == -1 and s.consec_stuck == 3


def test_stuck_streak_resets_on_non_stuck() -> None:
    p = _persona()
    coef = make_coef(p)
    s = init_state(p)

    apply_verdict(s, "stuck", coef)  # 5 -> 4, consec_stuck=1
    apply_verdict(s, "satisfied", coef)  # 非 stuck -> 递增清零
    assert s.consec_stuck == 0
    apply_verdict(s, "stuck", coef)  # 重新从首次起: -(1+0) -> 3
    assert s.patience == 3 and s.consec_stuck == 1


def test_apply_verdict_rejects_unknown() -> None:
    p = _persona()
    with pytest.raises(AssertionError):
        apply_verdict(init_state(p), "objectively_failed", make_coef(p))


def test_consec_blame_counts_only_consecutive_harness_failures() -> None:
    p = _persona()
    coef = make_coef(p)
    s = init_state(p)

    apply_verdict(s, "failed_blame_harness", coef)
    apply_verdict(s, "failed_blame_harness", coef)
    assert s.consec_blame == 2  # 连续坐实 harness 失败 -> 累计

    apply_verdict(s, "unsure", coef)  # 非连续 -> 清零("连续"严格语义)
    assert s.consec_blame == 0

    apply_verdict(s, "failed_blame_harness", coef)
    apply_verdict(s, "failed_blame_self", coef)  # 怪自己不算 harness 能力缺口 -> 清零
    assert s.consec_blame == 0

    apply_verdict(s, "failed_blame_harness", coef)
    apply_verdict(s, "satisfied", coef)  # 满意 -> 清零
    assert s.consec_blame == 0
