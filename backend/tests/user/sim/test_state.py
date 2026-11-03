"""spec-0005/T2 + Spec-0037/T2: patience/trust state machine only consumes subjective verdict; patience is orthogonal to tempo and d43."""

from __future__ import annotations

import pytest

from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    TimeTemperament,
    TrustStance,
    finalize_persona,
)
from ahe_beta.user.sim.state import (
    TASK_LOAD_DELTA,
    apply_task_load,
    apply_verdict,
    init_state,
    make_coef,
)


def _persona(
    *,
    d1: D1Eval = D1Eval.SHALLOW,
    d43: D43Correct = D43Correct.FEEDBACK,
    tempo: TimeTemperament = TimeTemperament.STEADY,
    d42: D42Supervise = D42Supervise.PHASE_CHECK,
) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P",
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=d42,
            d43=d43,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=tempo,
        )
    )


def test_init_state_patience_base_by_tempo_not_d43() -> None:
    # Same failure strategy, different temporal characteristic → different patience
    assert init_state(_persona(tempo=TimeTemperament.IMPATIENT)).patience == 3
    assert init_state(_persona(tempo=TimeTemperament.STEADY)).patience == 5
    assert init_state(_persona(tempo=TimeTemperament.PATIENT)).patience == 7
    # Orthogonal: give_up no longer depresses patience baseline
    assert init_state(_persona(d43=D43Correct.GIVE_UP, tempo=TimeTemperament.PATIENT)).patience == 7
    assert (
        init_state(_persona(d43=D43Correct.FILE_ISSUE, tempo=TimeTemperament.IMPATIENT)).patience
        == 3
    )


def test_apply_task_load_floats_around_base() -> None:
    p = _persona(tempo=TimeTemperament.STEADY)  # Baseline 5
    assert apply_task_load(init_state(p), "normal").patience == 5
    assert apply_task_load(init_state(p), "quick").patience == 4
    assert apply_task_load(init_state(p), "big").patience == 6
    assert apply_task_load(init_state(p), "epic").patience == 7
    assert TASK_LOAD_DELTA["epic"] == 2


def test_apply_task_load_unknown_is_noop_and_floor() -> None:
    p = _persona(tempo=TimeTemperament.IMPATIENT)  # Baseline 3
    assert apply_task_load(init_state(p), "wat").patience == 3
    s = init_state(p)
    s.patience = 1
    assert apply_task_load(s, "quick").patience == 1


def test_make_coef_reflects_tempo_and_eval() -> None:
    assert make_coef(_persona(tempo=TimeTemperament.IMPATIENT)).patience_decay == 2
    assert make_coef(_persona(tempo=TimeTemperament.STEADY)).patience_decay == 1
    # d43 no longer drives decay
    assert make_coef(_persona(d43=D43Correct.GIVE_UP)).patience_decay == 1
    assert make_coef(_persona(d1=D1Eval.EXPERT)).trust_decay == 2
    assert make_coef(_persona(d1=D1Eval.SHALLOW)).trust_decay == 1
    assert make_coef(_persona(d42=D42Supervise.EVERY_STEP)).stuck_extra == 1
    assert make_coef(_persona(d42=D42Supervise.FIRE_FORGET)).stuck_extra == 0


def test_apply_verdict_transitions() -> None:
    p = _persona()  # SHALLOW + STEADY -> trust BALANCED, patience 5, decays = 1
    coef = make_coef(p)

    s = init_state(p)
    apply_verdict(s, "satisfied", coef)
    assert s.turn == 1 and s.trust is TrustStance.BLIND

    s = init_state(p)
    apply_verdict(s, "failed_blame_harness", coef)
    assert s.patience == 4 and s.trust is TrustStance.SKEPTICAL

    s = init_state(p)
    apply_verdict(s, "failed_blame_self", coef)
    assert s.patience == 4 and s.trust is TrustStance.BALANCED

    s = init_state(p)
    apply_verdict(s, "unsure", coef)
    assert s.patience == 5 and s.trust is TrustStance.BALANCED

    s = init_state(p)
    apply_verdict(s, "stuck", coef)
    assert s.patience == 2 and s.trust is TrustStance.BALANCED


def test_apply_verdict_stuck_escalates_additively() -> None:
    p = _persona()
    coef = make_coef(p)

    s = init_state(p)
    apply_verdict(s, "stuck", coef)  # -(1+2)=3 -> 2
    assert s.patience == 2 and s.consec_stuck == 1
    apply_verdict(s, "stuck", coef)  # -(2+2)=4 -> -2
    assert s.patience == -2 and s.consec_stuck == 2
    apply_verdict(s, "stuck", coef)
    assert s.patience == -7 and s.consec_stuck == 3


def test_high_involvement_adds_stuck_extra() -> None:
    p = _persona(d42=D42Supervise.EVERY_STEP)
    coef = make_coef(p)
    s = init_state(p)
    apply_verdict(s, "stuck", coef)  # -(1+2+1)=4 -> 1
    assert s.patience == 1


def test_stuck_streak_resets_on_non_stuck() -> None:
    p = _persona()
    coef = make_coef(p)
    s = init_state(p)

    apply_verdict(s, "stuck", coef)
    apply_verdict(s, "satisfied", coef)
    assert s.consec_stuck == 0
    apply_verdict(s, "stuck", coef)
    assert s.patience == -1 and s.consec_stuck == 1


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
    assert s.consec_blame == 2

    apply_verdict(s, "unsure", coef)
    assert s.consec_blame == 0

    apply_verdict(s, "failed_blame_harness", coef)
    apply_verdict(s, "failed_blame_self", coef)
    assert s.consec_blame == 0

    apply_verdict(s, "failed_blame_harness", coef)
    apply_verdict(s, "satisfied", coef)
    assert s.consec_blame == 0
