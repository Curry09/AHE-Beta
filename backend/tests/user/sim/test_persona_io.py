"""spec-0006/T2 + Spec-0037/T4: card_to_persona injects sim —— grounded overrides derivation; D7→tempo."""

from __future__ import annotations

import copy

import pytest

from ahe_beta.distill.library import PersonaLibrary
from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D3Accept,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    TimeTemperament,
    TrustStance,
    derive_d3,
    derive_trust,
)
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.loop import SessionResult, run_session
from ahe_beta.user.sim.persona_client import ScriptedPersonaClient
from ahe_beta.user.sim.persona_io import card_to_persona, card_to_personas

TASK = "Add to_user_tz(dt, tz_name); handle DST."


def _karpathy_card() -> dict:
    """selfreport example C: expert × over-trust × ship-fast, fully grounded."""
    return {
        "id": "selfreport-example-c",
        "authenticity": "authentic",
        "dimensions": {
            "D1_evaluation_capability": {
                "value": "expert",
                "source": "grounded",
                "confidence": "high",
            },
            "D2_acceptance_bar": {
                "primary": "ship-fast",
                "flags": [],
                "source": "grounded",
                "confidence": "high",
            },
            "D3_interaction_style": {
                "delegation": {"value": "vibe-dump", "source": "grounded"},
                "supervision": {"value": "hands-off", "source": "grounded"},
                "on_offtrack": {"value": "retry", "source": "grounded"},
            },
            "D4_trust_model": {"value": "over-trust", "source": "grounded", "confidence": "high"},
            "D5_domain": {
                "area": "ml-ai",
                "depth": "deep",
                "stack": ["python", "pytorch"],
                "weak": [],
                "source": "grounded",
            },
            "D6_autonomy_expectation": {
                "value": "agentic",
                "source": "grounded",
                "confidence": "medium",
            },
            "D7_time_temperament": {
                "value": "patient",
                "source": "grounded",
                "confidence": "medium",
            },
        },
    }


def test_grounded_override_karpathy_not_simulated_as_opposite() -> None:
    p = card_to_persona(_karpathy_card())
    # D1=expert: if finalize always applied, d3 would derive to RIGOROUS and trust would derive to SKEPTICAL.
    assert derive_d3(D1Eval.EXPERT, p.d2) is D3Accept.RIGOROUS  # Counter-baseline
    assert derive_trust(D1Eval.EXPERT, p.d2) is TrustStance.SKEPTICAL
    # Actual: grounded cards D2=ship-fast / D4=over-trust override derivation.
    assert p.d3 is D3Accept.RUNS  # Not rewritten to RIGOROUS
    assert p.trust is TrustStance.BLIND  # over-trust ↔ blind, not rewritten to SKEPTICAL
    assert p.d1 is D1Eval.EXPERT
    assert p.d6 is not None  # D6Authz card has no source → still filled by finalize derivation


def test_sampled_axes_mapped_and_surface_aliases_shallow() -> None:
    card = _karpathy_card()
    card["dimensions"]["D1_evaluation_capability"]["value"] = "surface"
    p = card_to_persona(card)
    assert p.d1 is D1Eval.SHALLOW  # surface ↔ shallow merged
    assert p.d2.depth is D2Depth.SENIOR  # deep → senior
    assert p.d41 is D41Grain.ONE_LINER  # vibe-dump
    assert p.d42 is D42Supervise.FIRE_FORGET  # hands-off
    assert p.d43 is D43Correct.RESEND  # retry
    assert p.d5 is D5Autonomy.AGENTIC  # agentic
    assert p.tempo is TimeTemperament.PATIENT


def test_missing_tempo_defaults_to_steady() -> None:
    card = _karpathy_card()
    del card["dimensions"]["D7_time_temperament"]
    p = card_to_persona(card)
    assert p.tempo is TimeTemperament.STEADY


def test_ungrounded_derived_axes_fall_back_to_finalize() -> None:
    card = _karpathy_card()
    card["dimensions"]["D1_evaluation_capability"]["value"] = "competent"
    card["dimensions"]["D5_domain"]["depth"] = "working"
    # Both acceptance and trust marked injected → does not override, left to finalize derivation.
    card["dimensions"]["D2_acceptance_bar"]["source"] = "injected"
    card["dimensions"]["D4_trust_model"]["source"] = "injected"
    a = card_to_persona(card)
    b = card_to_persona(card)
    assert a == b  # Reproducible
    assert a.d3 is derive_d3(D1Eval.COMPETENT, a.d2)
    assert a.trust is derive_trust(D1Eval.COMPETENT, a.d2)


def test_illegal_enum_raises() -> None:
    card = _karpathy_card()
    card["dimensions"]["D1_evaluation_capability"]["value"] = "wizard"
    with pytest.raises(ValueError, match="Invalid enum value"):
        card_to_persona(card)


def test_illegal_tempo_raises() -> None:
    """Spec-0037/T4: illegal D7 error (only falls back to steady if fields missing)."""
    card = _karpathy_card()
    card["dimensions"]["D7_time_temperament"]["value"] = "zen"
    with pytest.raises(ValueError, match="D7_time_temperament"):
        card_to_persona(card)


def test_missing_field_raises() -> None:
    card = _karpathy_card()
    del card["dimensions"]["D4_trust_model"]
    with pytest.raises(ValueError, match="Missing card field"):
        card_to_persona(card)


def test_injected_card_runs_one_session_end_to_end() -> None:
    p = card_to_persona(_karpathy_card())
    res = run_session(p, ScriptedPersonaClient(), ScriptedHarness(), TASK)
    assert isinstance(res, SessionResult)
    assert res.persona_id == "selfreport-example-c"


def test_card_to_personas_batch(tmp_path) -> None:
    lib = PersonaLibrary(tmp_path / "cards.json")
    c1 = _karpathy_card()
    c2 = copy.deepcopy(_karpathy_card())
    c2["id"] = "selfreport-example-a"
    c2["dimensions"]["D4_trust_model"]["value"] = "skeptical"
    lib.add(c1)
    lib.add(c2)
    personas = card_to_personas(lib)
    assert len(personas) == 2
    assert personas[0].trust is TrustStance.BLIND  # over-trust
    assert personas[1].trust is TrustStance.SKEPTICAL  # skeptical
