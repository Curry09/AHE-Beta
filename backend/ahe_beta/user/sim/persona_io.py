"""persona_io.py (spec-0006/T2 + Spec-0037/T4): inject persona card into control envelope sim.

card_to_persona is the sole bridge between "collection (behavior card, 0006/T1)" and "sim engine (dimensions.Persona)": map card fields to sim dimensions per field; **grounded acceptance (D2)/trust (D4) in the card directly write to sim's derived dimensions d3/trust and are not rewritten by derive_*   (override derivation)**; time temperament D7 writes to tempo (default steady); ungrounded derived dimensions leave as None for finalize_persona to derive and fill. D6Authz not in card store, always semi-derived.

Why override derivation is needed: sim's d3/trust originally "derived from D1/D2"; if always finalize, rewrites genuinely grounded card trust/acceptance into synthetic values—e.g., expert×over-trust Karpathy (selfreport example C) would be simulated as skeptical×rigorous opposite, directly polluting authenticity of training signal. Card shape contract see tools/persona-distill/card-schema.md.

Illegal/missing enum values raise explicit error (no silent fallback), exposing collection quality issues at injection boundary; only D7 defaults compatibly for old cards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D3Accept,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    TimeTemperament,
    TrustStance,
    finalize_persona,
)

if TYPE_CHECKING:
    from ahe_beta.distill.library import PersonaLibrary

# --------------------------------------------------------------------------
# Card enum → sim enum mapping table (explicit, absorbs differences between two controlled vocabularies)
# --------------------------------------------------------------------------
_D1: dict[str, D1Eval] = {
    "blind": D1Eval.BLIND,
    "surface": D1Eval.SHALLOW,  # surface ↔ shallow merged
    "competent": D1Eval.COMPETENT,
    "expert": D1Eval.EXPERT,
}
_DEPTH: dict[str, D2Depth] = {
    "shallow": D2Depth.NOVICE,
    "working": D2Depth.PROFICIENT,
    "deep": D2Depth.SENIOR,
}
_ACCEPT: dict[str, D3Accept] = {
    "ship-fast": D3Accept.RUNS,
    "functional": D3Accept.FUNCTIONAL,
    "modern-correct": D3Accept.IDIOMATIC,
    "type-safety-purist": D3Accept.RIGOROUS,
}
_DELEGATION: dict[str, D41Grain] = {
    "vibe-dump": D41Grain.ONE_LINER,
    "loose": D41Grain.HALF_CONTEXT,
    "spec-driven": D41Grain.SPEC_LEVEL,
}
_SUPERVISION: dict[str, D42Supervise] = {
    "hands-off": D42Supervise.FIRE_FORGET,
    "reviews": D42Supervise.PHASE_CHECK,
    "micromanage": D42Supervise.EVERY_STEP,
}
_ON_OFFTRACK: dict[str, D43Correct] = {
    "abandon": D43Correct.GIVE_UP,
    "retry": D43Correct.RESEND,
    "correct": D43Correct.FEEDBACK,
    "fix-self": D43Correct.HANDOVER,
    "file-issue": D43Correct.FILE_ISSUE,
}
_TRUST: dict[str, TrustStance] = {
    "over-trust": TrustStance.BLIND,  # over-trust ↔ blind
    "balanced": TrustStance.BALANCED,
    "skeptical": TrustStance.SKEPTICAL,
}
_AUTONOMY: dict[str, D5Autonomy] = {
    "advisory": D5Autonomy.ADVISORY,
    "collaborative": D5Autonomy.COLLABORATIVE,
    "agentic": D5Autonomy.AGENTIC,
}
_TEMPO: dict[str, TimeTemperament] = {
    "patient": TimeTemperament.PATIENT,
    "steady": TimeTemperament.STEADY,
    "impatient": TimeTemperament.IMPATIENT,
}


def _require(container: dict, key: str, where: str) -> object:
    if not isinstance(container, dict) or key not in container:
        raise ValueError(f"Missing card field: {where}.{key}")
    return container[key]


def _map_enum(table: dict, raw: object, where: str):
    if raw not in table:
        raise ValueError(
            f"Invalid enum value in card {where}: {raw!r}; allowed values: {sorted(table)}"
        )
    return table[raw]


def card_to_persona(record: dict) -> Persona:
    """Map one behavior card to sim's dimensions.Persona.

    Sampling dimensions (capability/interaction/autonomy/time temperament) always written directly from card;
    derived dimensions d3(from card D2)/trust(from card D4) written directly only when card source=grounded (override derivation),
    otherwise left None for finalize_persona to derive; D6Authz cards have no source, always derived by finalize.

    D7_time_temperament defaults to steady when absent (old card forward compatibility, not treated as failure).
    """
    persona_id = _require(record, "id", "card")
    dims = _require(record, "dimensions", "card")

    # --- Sampling dimension: always written from card ---
    d1_block = _require(dims, "D1_evaluation_capability", "dimensions")
    d1 = _map_enum(_D1, _require(d1_block, "value", "D1"), "D1.value")

    d5dom = _require(dims, "D5_domain", "dimensions")
    depth = _map_enum(_DEPTH, _require(d5dom, "depth", "D5_domain"), "D5_domain.depth")
    stack = tuple(d5dom.get("stack", ()))
    weak = tuple(d5dom.get("weak", ()))
    d2 = D2Domain(stack=stack or ("python",), depth=depth, weak=weak)

    d3int = _require(dims, "D3_interaction_style", "dimensions")
    deleg = _require(d3int, "delegation", "D3_interaction_style")
    superv = _require(d3int, "supervision", "D3_interaction_style")
    offtrack = _require(d3int, "on_offtrack", "D3_interaction_style")
    d41 = _map_enum(_DELEGATION, _require(deleg, "value", "D3.delegation"), "D3.delegation.value")
    d42 = _map_enum(
        _SUPERVISION, _require(superv, "value", "D3.supervision"), "D3.supervision.value"
    )
    d43 = _map_enum(
        _ON_OFFTRACK, _require(offtrack, "value", "D3.on_offtrack"), "D3.on_offtrack.value"
    )

    d6auto = _require(dims, "D6_autonomy_expectation", "dimensions")
    d5 = _map_enum(_AUTONOMY, _require(d6auto, "value", "D6_autonomy_expectation"), "D6.value")

    # D7 time temperament: new axis; old card missing field → steady (compatible, no error)
    tempo = TimeTemperament.STEADY
    tempo_block = dims.get("D7_time_temperament")
    if isinstance(tempo_block, dict) and "value" in tempo_block:
        tempo = _map_enum(_TEMPO, tempo_block["value"], "D7_time_temperament.value")

    # --- Derived dimension: overwritten only when grounded, otherwise left None for finalize ---
    d2bar = _require(dims, "D2_acceptance_bar", "dimensions")
    d3: D3Accept | None = None
    if _require(d2bar, "source", "D2_acceptance_bar") == "grounded":
        d3 = _map_enum(_ACCEPT, _require(d2bar, "primary", "D2_acceptance_bar"), "D2.primary")

    d4block = _require(dims, "D4_trust_model", "dimensions")
    trust: TrustStance | None = None
    if _require(d4block, "source", "D4_trust_model") == "grounded":
        trust = _map_enum(_TRUST, _require(d4block, "value", "D4_trust_model"), "D4.value")

    raw = Persona(
        persona_id=str(persona_id),
        d1=d1,
        d2=d2,
        d41=d41,
        d42=d42,
        d43=d43,
        d5=d5,
        tempo=tempo,
        d3=d3,
        trust=trust,  # Grounded then pass through; None then finalize derives (D6Authz always derived)
    )
    return finalize_persona(raw)


def card_to_personas(library: PersonaLibrary) -> list[Persona]:
    """Map each card in store to sim Persona (equal-length list)."""
    return [card_to_persona(record) for record in library.load()]
