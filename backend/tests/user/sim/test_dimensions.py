"""spec-0005/T1 + Spec-0037/T2: Persona 9-dimensional derivation and copy table lookup (including tempo/process involvement)."""

from __future__ import annotations

import dataclasses

import pytest

from ahe_beta.user.sim.clauses import compile_block_p
from ahe_beta.user.sim.dimensions import (
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
    TimeTemperament,
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
    assert a == b  # Deterministic: same input yields same output
    assert a.d3 is D3Accept.RIGOROUS and a.trust is TrustStance.SKEPTICAL


def test_finalize_is_fallback_only_preserves_grounded() -> None:
    # Caller explicitly provided grounded d3/trust (opposite of derived): finalize must not overwrite.
    raw = Persona(
        persona_id="P-grounded",
        d1=D1Eval.EXPERT,  # derive_trust(EXPERT) = SKEPTICAL
        d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR),  # derive_d3 -> RIGOROUS
        d41=D41Grain.HALF_CONTEXT,
        d42=D42Supervise.PHASE_CHECK,
        d43=D43Correct.FEEDBACK,
        d5=D5Autonomy.COLLABORATIVE,
        d3=D3Accept.RUNS,  # grounded: ship-fast
        trust=TrustStance.BLIND,  # grounded: over-trust
        # d6 left as None → still derived by finalize
    )
    out = finalize_persona(raw)
    assert out.d3 is D3Accept.RUNS  # Not overwritten by derive_d3 into RIGOROUS
    assert out.trust is TrustStance.BLIND  # Not overwritten by derive_trust into SKEPTICAL
    assert out.d6 is not None  # d6 not provided → derivation already filled in
    assert out.d6 is derive_d6(D5Autonomy.COLLABORATIVE, "low")


def test_derive_d3_clamps_within_enum() -> None:
    # senior raises one level; EXPERT already at highest level → clamp does not exceed bounds
    assert derive_d3(D1Eval.EXPERT, D2Domain(depth=D2Depth.SENIOR)) is D3Accept.RIGOROUS
    # novice drops one tier; BLIND is already at minimum -> clamp does not exceed bounds
    assert derive_d3(D1Eval.BLIND, D2Domain(depth=D2Depth.NOVICE)) is D3Accept.RUNS
    # middle tier allows raise/lower visibility
    assert derive_d3(D1Eval.SHALLOW, D2Domain(depth=D2Depth.SENIOR)) is D3Accept.IDIOMATIC
    assert derive_d3(D1Eval.COMPETENT, D2Domain(depth=D2Depth.NOVICE)) is D3Accept.FUNCTIONAL


def test_derive_trust_and_d6() -> None:
    assert derive_trust(D1Eval.BLIND, D2Domain()) is TrustStance.BLIND
    assert derive_trust(D1Eval.EXPERT, D2Domain()) is TrustStance.SKEPTICAL
    assert derive_trust(D1Eval.SHALLOW, D2Domain()) is TrustStance.BALANCED
    # collaborative + low risk permits execution
    assert derive_d6(D5Autonomy.COLLABORATIVE, "low") is D6Authz.FULL_AUTO
    # high risk tightens one tier: collaborative baseline WRITE_NO_RUN tightens to READ_ONLY
    assert derive_d6(D5Autonomy.COLLABORATIVE, "high") is D6Authz.READ_ONLY
    assert derive_d6(D5Autonomy.AGENTIC, "high") is D6Authz.WRITE_NO_RUN
    assert derive_d6(D5Autonomy.ADVISORY, "low") is D6Authz.READ_ONLY


def test_compile_block_p_covers_every_value_no_keyerror() -> None:
    for d1 in D1Eval:
        for d43 in D43Correct:
            for tempo in TimeTemperament:
                p = finalize_persona(
                    Persona(
                        persona_id="P",
                        d1=d1,
                        d2=D2Domain(),
                        d41=D41Grain.ONE_LINER,
                        d42=D42Supervise.FIRE_FORGET,
                        d43=d43,
                        d5=D5Autonomy.COLLABORATIVE,
                        tempo=tempo,
                    )
                )
                block = compile_block_p(p)
                assert "P" in block and "PERSONA" in block
                assert p.d1.value.upper() in block
                assert "Process involvement" in block
                assert "Time temperament" in block
                assert "SESSION POLICY" in block


def test_compile_block_p_process_involvement_not_button_language() -> None:
    p = finalize_persona(
        Persona(
            persona_id="P",
            d1=D1Eval.COMPETENT,
            d2=D2Domain(),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.EVERY_STEP,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=TimeTemperament.IMPATIENT,
        )
    )
    block = compile_block_p(p)
    assert "opaque activity" in block
    assert "short fuse for waiting" in block
    assert "interrupt" not in block.lower()
    assert "queued" not in block.lower()


def test_persona_is_frozen() -> None:
    p = finalize_persona(_raw(D1Eval.SHALLOW, D2Depth.PROFICIENT))
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.persona_id = "mutated"  # type: ignore[misc]
