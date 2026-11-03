"""
dimensions.py
Persona dimension definitions + value enums + derivation functions.

Spec-0037/T2: tempo temporal temperament; process involvement semantics; D6Authz marked as session policy (not persona axis).

Persona source (card-editable) and session derivation hierarchy:
  A Capability Foundation: D1 Assessment Capability, D2 Domain & Depth
  B Acceptance:           D3 Acceptance Threshold            (derivable from D1×D2; overrides when grounded)
  C Interaction Style:    D4_1 Delegation Granularity, D4_2 Process Involvement, D4_3 Quality Failure Strategy, tempo Temporal Temperament
  D Autonomy Expectation: D5 Autonomy Expectation
  E Session Policy:       D6 Authorization Scale            (not persona axis; semi-derived from autonomy + task risk)
  F Trust:                trust                              (derivable from D1×D2; overrides when grounded)

Iron Laws:
- Persona is a static coefficient (frozen at session start), does not change in the loop.
- Quality Failure Strategy ⊥ Temporal Temperament: rigorous but patient, or casual but explodes in two minutes—both real.
- Dimension -> Copy / Configuration is deterministic mapping (see clauses.py), reproducible and code-generable.
- Do not bake current harness UX (interrupt / queued / slash) into dimension enums.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# --------------------------------------------------------------------------
# A. Competence foundation
# --------------------------------------------------------------------------
class D1Eval(StrEnum):
    """D1 Assessment Capability — determines perceptual bandwidth + judgment ceiling. Free sampling."""

    BLIND = "blind"  # Blind trust: hardly any verification
    SHALLOW = "shallow"  # Shallow: read errors, run once, no test writing / no diff review
    COMPETENT = "competent"  # Competent: run tests, read diff, can see through most specious APIs
    # Expert: systematic verification, detect hallucinations / boundary / DST-class bugs
    EXPERT = "expert"


class D2Depth(StrEnum):
    NOVICE = "novice"
    PROFICIENT = "proficient"
    SENIOR = "senior"


@dataclass(frozen=True)
class D2Domain:
    """D2 Domain & Depth. Free sampling. Domains in weak set reduce D1 effective bandwidth by one notch."""

    stack: tuple[str, ...] = ("python",)
    depth: D2Depth = D2Depth.PROFICIENT
    weak: tuple[str, ...] = ()  # e.g. ("timezone", "pytz")


# --------------------------------------------------------------------------
# B. Acceptance (derived)
# --------------------------------------------------------------------------
class D3Accept(StrEnum):
    RUNS = "runs"  # It runs
    FUNCTIONAL = "functional"  # Functional correctness (tested common cases)
    IDIOMATIC = "idiomatic"  # Modern standards
    RIGOROUS = "rigorous"  # Type / boundary rigor


# --------------------------------------------------------------------------
# C. Interaction style (free sampling)
# --------------------------------------------------------------------------
class D41Grain(StrEnum):
    ONE_LINER = "one_liner"  # Just tell me
    HALF_CONTEXT = "half_context"  # Half context
    SPEC_LEVEL = "spec_level"  # Standard-level (includes information supply)


class D42Supervise(StrEnum):
    """Process Involvement (formerly supervision): How much visibility into "what the assistant is doing" is needed.

    Enum strings kept for backward compatibility with legacy tests/card mappings; semantics reflect human process anxiety, not product UI.
    """

    EVERY_STEP = "every_step"  # High involvement: uneasy if process is not visible
    PHASE_CHECK = "phase_check"  # Medium involvement: need confidence at key checkpoints
    FIRE_FORGET = "fire_forget"  # Low involvement: result only


class D43Correct(StrEnum):
    """Strategy after quality failure (answers only "what to do if results are wrong"; does not drive patience for waiting)."""

    FEEDBACK = "feedback"  # Give feedback so it revises
    HANDOVER = "handover"  # Take over and write myself
    RESEND = "resend"  # Re-submit request
    GIVE_UP = "give_up"  # Give up
    FILE_ISSUE = "file_issue"  # Report structured issue


class TimeTemperament(StrEnum):
    """Temporal Temperament: tolerance for waiting and idle time (orthogonal to quality failure strategy)."""

    PATIENT = "patient"
    STEADY = "steady"
    IMPATIENT = "impatient"


# --------------------------------------------------------------------------
# D. Autonomy expectations
# --------------------------------------------------------------------------
class D5Autonomy(StrEnum):
    ADVISORY = "advisory"
    COLLABORATIVE = "collaborative"
    AGENTIC = "agentic"


# --------------------------------------------------------------------------
# E. Session strategy (non-character axis)
# --------------------------------------------------------------------------
class D6Authz(StrEnum):
    """Authorization Scale: session/product policy, semi-derived from autonomy expectation; not in card."""

    READ_ONLY = "read_only"  # Read-only
    WRITE_NO_RUN = "write_no_run"  # Writable, Not Runnable
    FULL_AUTO = "full_auto"  # Fully Automated (Writable and Runnable)


# --------------------------------------------------------------------------
# F. Trust
# --------------------------------------------------------------------------
class TrustStance(StrEnum):
    BLIND = "blind"  # Blind Trust
    BALANCED = "balanced"  # Balanced
    SKEPTICAL = "skeptical"  # Skeptical


# --------------------------------------------------------------------------
# Persona Aggregation
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Persona:
    persona_id: str
    # Free Sampling (Human Axis)
    d1: D1Eval
    d2: D2Domain
    d41: D41Grain
    d42: D42Supervise
    d43: D43Correct
    d5: D5Autonomy
    tempo: TimeTemperament = TimeTemperament.STEADY
    # Derived / Semi-derived: Default None means "not provided, to be filled by finalize_persona".
    # If the caller (e.g., 0006/T2 injection layer) explicitly provides a grounded value, finalize does not overwrite it (fallback-only).
    d3: D3Accept | None = None
    d6: D6Authz | None = None
    trust: TrustStance | None = None


# --------------------------------------------------------------------------
# Derivation Function (Deterministic)
# --------------------------------------------------------------------------
def derive_d3(d1: D1Eval, d2: D2Domain) -> D3Accept:
    """Acceptance Threshold = f(D1, D2). Higher capability + more senior -> stricter threshold."""
    base = {
        D1Eval.BLIND: D3Accept.RUNS,
        D1Eval.SHALLOW: D3Accept.FUNCTIONAL,
        D1Eval.COMPETENT: D3Accept.IDIOMATIC,
        D1Eval.EXPERT: D3Accept.RIGOROUS,
    }[d1]
    # Senior level bumped up one notch, beginner level bumped down one notch (clamped within enum range)
    order = [D3Accept.RUNS, D3Accept.FUNCTIONAL, D3Accept.IDIOMATIC, D3Accept.RIGOROUS]
    idx = order.index(base)
    if d2.depth == D2Depth.SENIOR:
        idx = min(idx + 1, len(order) - 1)
    elif d2.depth == D2Depth.NOVICE:
        idx = max(idx - 1, 0)
    return order[idx]


def derive_trust(d1: D1Eval, d2: D2Domain) -> TrustStance:
    """Trust Initial Value = f(D1, D2). Blind trust in capability -> blind trust; high capability -> balanced skepticism."""
    if d1 == D1Eval.BLIND:
        return TrustStance.BLIND
    if d1 == D1Eval.EXPERT:
        return TrustStance.SKEPTICAL
    return TrustStance.BALANCED


def derive_d6(d5: D5Autonomy, task_risk: str = "low") -> D6Authz:
    """Authorization Scale semi-derived: determined jointly by autonomy expectation + task risk (session policy, not card)."""
    base = {
        D5Autonomy.ADVISORY: D6Authz.READ_ONLY,
        D5Autonomy.COLLABORATIVE: D6Authz.WRITE_NO_RUN,
        D5Autonomy.AGENTIC: D6Authz.FULL_AUTO,
    }[d5]
    # High-risk tasks tightened by one notch
    if task_risk == "high":
        downgrade = {
            D6Authz.FULL_AUTO: D6Authz.WRITE_NO_RUN,
            D6Authz.WRITE_NO_RUN: D6Authz.READ_ONLY,
            D6Authz.READ_ONLY: D6Authz.READ_ONLY,
        }
        base = downgrade[base]
    # collaborative typically allowed to run under low risk (aligned with "verify by running it" habit)
    if d5 == D5Autonomy.COLLABORATIVE and task_risk == "low":
        base = D6Authz.FULL_AUTO
    return base


def finalize_persona(p: Persona, task_risk: str = "low") -> Persona:
    """Fill derived dimensions and return an immutable complete persona.

    Fallback-only: call derive_* only for unfilled (None) derived dimensions; grounded values explicitly
    provided by the caller are preserved unchanged and not overwritten. This allows the 0006/T2 injection
    layer to let grounded acceptance (d3) / trust (trust) in the card override derivation—otherwise
    expert×over-trust (Karpathy) would be simulated as the opposite of skeptical×rigorous.
    """
    return Persona(
        persona_id=p.persona_id,
        d1=p.d1,
        d2=p.d2,
        d41=p.d41,
        d42=p.d42,
        d43=p.d43,
        d5=p.d5,
        tempo=p.tempo,
        d3=p.d3 if p.d3 is not None else derive_d3(p.d1, p.d2),
        d6=p.d6 if p.d6 is not None else derive_d6(p.d5, task_risk),
        trust=p.trust if p.trust is not None else derive_trust(p.d1, p.d2),
    )
