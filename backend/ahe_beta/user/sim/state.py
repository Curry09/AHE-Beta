"""Maintain the cross-turn state used by the three-stage cognitive process.

Spec-0037/T2: initial patience and its decay follow tempo. stuck_extra follows process involvement
(d42), independently of d43. State updates consume only the persona's *subjective verdict*:
emotions respond to what the persona perceives. No objective ground truth enters this layer
(no gold / outcome / GAP).
Persona defines the rate and magnitude of changes; state accumulates those changes.
Waiting patience depends on tempo, independently of the response to quality failures (d43).
"""

from __future__ import annotations

from dataclasses import dataclass

from .dimensions import D1Eval, D42Supervise, Persona, TimeTemperament, TrustStance

# Subjective judgment enum (LLM produces in OUTPUT_CONTRACT)
VERDICTS = {
    "satisfied",
    "failed_blame_harness",
    "failed_blame_self",
    "unsure",
    "stuck",  # Harness failure/idle/repetition/no progress: distinct from 'unsure' pending verification, loses patience when stuck
}


@dataclass
class Coef:
    """State evolution coefficients derived from persona."""

    patience_decay: int = 1
    trust_decay: int = 1
    trust_recover: int = 1
    # stuck extra multiplier: loses patience faster when high process involvement in "seeming stuck/unable to see progress"
    stuck_extra: int = 0


@dataclass
class State:
    turn: int = 0
    patience: int = 4  # Cross-turn patience counter, <=0 unlocks termination
    trust: TrustStance = TrustStance.BALANCED
    # Cross-turn short memory from user's own private tools
    private_evidence: list[str] | None = None
    private_evidence_seq: int = 0
    consec_blame: int = 0  # Count of consecutive harness failures; drives 'diagnostic' escalation (not patience consumption)
    consec_stuck: int = 0  # Count of consecutive stuck; only serves as multiplier for additive patience decay (not termination gate)


# Integer scale of three-tier trust, facilitating increment/decrement then mapping back to enum
_TRUST_SCALE = [TrustStance.SKEPTICAL, TrustStance.BALANCED, TrustStance.BLIND]


def _trust_to_int(t: TrustStance) -> int:
    return _TRUST_SCALE.index(t)


def _int_to_trust(i: int) -> TrustStance:
    i = max(0, min(i, len(_TRUST_SCALE) - 1))
    return _TRUST_SCALE[i]


def make_coef(p: Persona) -> Coef:
    """persona -> state evolution coefficient. Patience decay tracks tempo; trust collapse tracks assessment capability."""
    patience_decay = {
        TimeTemperament.PATIENT: 1,
        TimeTemperament.STEADY: 1,
        TimeTemperament.IMPATIENT: 2,
    }[p.tempo]
    trust_decay = 2 if p.d1 in (D1Eval.COMPETENT, D1Eval.EXPERT) else 1
    # High process involvement: deduct more on subjective stuck (still not tied to specific product keys)
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


# Task volume → initial patience fluctuation: same person on different tasks has different patience. Large/open-ended/ambitious work expects real effort,
# willing to wait longer, go back-and-forth more (higher initial patience); trivial tasks that should be instant have zero tolerance for friction (lower initial patience).
# Range compressed very tight (-1…+2), only micro-fluctuation on baseline, does not override patience tier from tempo personality.
TASK_LOAD_DELTA: dict[str, int] = {
    "quick": -1,  # Trivial/should be instant
    "normal": 0,  # Standard task
    "big": 1,  # Substantial, multi-step
    "epic": 2,  # Large, open-ended, ambitious
}


def apply_task_load(state: State, load: str) -> State:
    """Adjust initial patience slightly using the persona's subjective assessment of task size.

    Apply the adjustment once and clamp to >=1, so it cannot enable termination at session start.
    """
    state.patience = max(1, state.patience + TASK_LOAD_DELTA.get(load, 0))
    return state


def apply_verdict(state: State, verdict: str, coef: Coef) -> State:
    """Each turn: rewrite state using subjective verdict. Objective ground truth never enters this function."""
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
        state.consec_blame += 1  # Consecutive harness failures confirmed → cumulative diagnostics
        state.consec_stuck = 0
    elif verdict == "failed_blame_self":
        state.patience -= coef.patience_decay  # Blaming self also consumes patience
        # But does not undermine trust in harness → t unchanged; self-blame not counted toward 'harness capability gap' diagnostics
        state.consec_blame = 0
        state.consec_stuck = 0
    elif verdict == "unsure":
        state.patience -= 0  # Unresolved/unsure does not consume patience: diligent verification should not be penalized
        # Non-consecutive → diagnostic count resets (strict sense of 'consecutive')
        state.consec_blame = 0
        state.consec_stuck = 0
    elif verdict == "stuck":
        # Harness failure/idle/repetition/no progress: loses patience when stuck, and the longer consecutive, the worse (additive increase, consistent with 'frustration grows with time').
        # All attributed to patience—no separate escalation gate, ultimately still walks patience<=0 unlocking termination (ability independent: any user senses being stuck).
        # Additive increase: first stuck deducts 3+stuck_extra, then +1 for each additional consecutive occurrence.
        state.consec_stuck += 1
        state.patience -= state.consec_stuck + 2 + coef.stuck_extra
        # stuck is not 'confirmed capability gap' blame → diagnostic count resets
        state.consec_blame = 0

    state.trust = _int_to_trust(t)
    return state
