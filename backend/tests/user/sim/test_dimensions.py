"""spec-0005/T1：Persona 9 维派生与文案查表。"""

from __future__ import annotations

import dataclasses

import pytest

from auto_designer.user.sim.clauses import compile_block_p
from auto_designer.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D3Accept,
    D5Autonomy,
    D6Authz,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    TrustStance,
    derive_d3,
    derive_d6,
    derive_trust,
    finalize_persona,
)


def _raw(d1: D1Eval, depth: D2Depth, d5: D5Autonomy = D5Autonomy.COLLABORATIVE) -> Persona:
    return Persona(
        persona_id="P-X",
        d1=d1,
        d2=D2Domain(stack=("python",), depth=depth),
        d41=D41Grain.HALF_CONTEXT,
        d42=D42Supervise.PHASE_CHECK,
        d43=D43Correct.FEEDBACK,
        d5=d5,
    )


def test_finalize_is_complete_and_reproducible() -> None:
    raw = _raw(D1Eval.EXPERT, D2Depth.SENIOR)
    a = finalize_persona(raw)
    b = finalize_persona(raw)
    assert a == b  # 确定性: 同输入同输出
    assert a.d3 is D3Accept.RIGOROUS and a.trust is TrustStance.SKEPTICAL


def test_finalize_is_fallback_only_preserves_grounded() -> None:
    # 调用方显式给了 grounded 的 d3/trust（与 derive 出来的相反）：finalize 不得改写。
    raw = Persona(
        persona_id="P-grounded",
        d1=D1Eval.EXPERT,                  # derive_trust(EXPERT) = SKEPTICAL
        d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR),  # derive_d3 -> RIGOROUS
        d41=D41Grain.HALF_CONTEXT,
        d42=D42Supervise.PHASE_CHECK,
        d43=D43Correct.FEEDBACK,
        d5=D5Autonomy.COLLABORATIVE,
        d3=D3Accept.RUNS,                  # grounded: ship-fast
        trust=TrustStance.BLIND,           # grounded: over-trust
        # d6 留 None -> 仍由 finalize 派生
    )
    out = finalize_persona(raw)
    assert out.d3 is D3Accept.RUNS         # 未被 derive_d3 改写成 RIGOROUS
    assert out.trust is TrustStance.BLIND  # 未被 derive_trust 改写成 SKEPTICAL
    assert out.d6 is not None              # d6 未提供 -> 已派生填齐
    assert out.d6 is derive_d6(D5Autonomy.COLLABORATIVE, "low")


def test_derive_d3_clamps_within_enum() -> None:
    # senior 抬一档；EXPERT 已在最高档 -> clamp 不越界
    assert derive_d3(D1Eval.EXPERT, D2Domain(depth=D2Depth.SENIOR)) is D3Accept.RIGOROUS
    # novice 降一档；BLIND 已在最低档 -> clamp 不越界
    assert derive_d3(D1Eval.BLIND, D2Domain(depth=D2Depth.NOVICE)) is D3Accept.RUNS
    # 中间档可见抬/降
    assert derive_d3(D1Eval.SHALLOW, D2Domain(depth=D2Depth.SENIOR)) is D3Accept.IDIOMATIC
    assert derive_d3(D1Eval.COMPETENT, D2Domain(depth=D2Depth.NOVICE)) is D3Accept.FUNCTIONAL


def test_derive_trust_and_d6() -> None:
    assert derive_trust(D1Eval.BLIND, D2Domain()) is TrustStance.BLIND
    assert derive_trust(D1Eval.EXPERT, D2Domain()) is TrustStance.SKEPTICAL
    assert derive_trust(D1Eval.SHALLOW, D2Domain()) is TrustStance.BALANCED
    # collaborative + 低风险 放开可跑
    assert derive_d6(D5Autonomy.COLLABORATIVE, "low") is D6Authz.FULL_AUTO
    # 高风险收紧一档: collaborative 基线 WRITE_NO_RUN 收紧到 READ_ONLY
    assert derive_d6(D5Autonomy.COLLABORATIVE, "high") is D6Authz.READ_ONLY
    assert derive_d6(D5Autonomy.AGENTIC, "high") is D6Authz.WRITE_NO_RUN
    assert derive_d6(D5Autonomy.ADVISORY, "low") is D6Authz.READ_ONLY


def test_compile_block_p_covers_every_value_no_keyerror() -> None:
    for d1 in D1Eval:
        for d43 in D43Correct:
            p = finalize_persona(
                Persona(
                    persona_id="P",
                    d1=d1,
                    d2=D2Domain(),
                    d41=D41Grain.ONE_LINER,
                    d42=D42Supervise.FIRE_FORGET,
                    d43=d43,
                    d5=D5Autonomy.COLLABORATIVE,
                )
            )
            block = compile_block_p(p)
            assert "P" in block and "PERSONA" in block
            assert p.d1.value.upper() in block


def test_persona_is_frozen() -> None:
    p = finalize_persona(_raw(D1Eval.SHALLOW, D2Depth.PROFICIENT))
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.persona_id = "mutated"  # type: ignore[misc]
