"""spec-0006/T1: PersonaLibrary read/write + card schema round-trip + contract constraint validation."""

from __future__ import annotations

import pytest

from ahe_beta.distill.library import (
    D5_AREA_VOCAB,
    PersonaLibrary,
    validate_card,
)


def _card(persona_id: str = "selfreport-example-c") -> dict:
    # card-schema.md card shape: contains source/basis/confidence plus the union of provenance fields.
    return {
        "id": persona_id,
        "authenticity": "authentic",
        "era": {"value": "post_vibe", "basis": "coined 'vibe coding' 2025-02-02"},
        "dimensions": {
            "D1_evaluation_capability": {
                "value": "expert",
                "source": "grounded",
                "basis": "stated+observed",
                "confidence": "high",
            },
            "D2_acceptance_bar": {
                "primary": "ship-fast",
                "flags": [],
                "source": "grounded",
                "basis": "stated",
                "confidence": "high",
            },
            "D3_interaction_style": {
                "delegation": {
                    "value": "vibe-dump",
                    "source": "grounded",
                    "basis": "stated",
                    "confidence": "high",
                },
                "supervision": {
                    "value": "hands-off",
                    "source": "grounded",
                    "basis": "stated",
                    "confidence": "high",
                },
                "on_offtrack": {
                    "value": "retry",
                    "source": "grounded",
                    "basis": "stated",
                    "confidence": "high",
                },
            },
            "D4_trust_model": {
                "value": "over-trust",
                "source": "grounded",
                "basis": "stated",
                "confidence": "high",
            },
            "D5_domain": {
                "area": "ml-ai",
                "depth": "deep",
                "stack": ["python", "pytorch"],
                "weak": ["web-frontend/css"],
                "source": "grounded",
                "basis": "stated",
                "confidence": "medium",
            },
            "D6_autonomy_expectation": {
                "value": "agentic",
                "source": "grounded",
                "basis": "stated",
                "confidence": "medium",
            },
        },
        "provenance": {
            "sources": [{"url": "x.com/karpathy 2025-02-02", "type": "tweet-thread"}],
            "self_report": True,
            "evidence_quotes": [
                {
                    "quote": "I 'Accept All' always, I don't read the diffs anymore.",
                    "source": "x.com/karpathy 2025-02-02",
                },
            ],
        },
        "behavioral_prediction": "Fire-and-forget vibe-dumper who CAN judge but opts out.",
    }


def test_empty_library_loads_empty(tmp_path) -> None:
    lib = PersonaLibrary(tmp_path / "cards.json")
    assert lib.load() == []


def test_add_then_load_and_get(tmp_path) -> None:
    lib = PersonaLibrary(tmp_path / "cards.json")
    card = _card()
    lib.add(card)

    loaded = lib.load()
    assert len(loaded) == 1
    assert loaded[0] == card
    assert lib.get("selfreport-example-c") == card


def test_get_missing_raises_keyerror(tmp_path) -> None:
    lib = PersonaLibrary(tmp_path / "cards.json")
    lib.add(_card("a"))
    with pytest.raises(KeyError):
        lib.get("does-not-exist")


def test_card_roundtrips_and_tolerates_unknown_keys(tmp_path) -> None:
    lib = PersonaLibrary(tmp_path / "cards.json")
    card = _card()
    # Evolution-friendly: unknown keys should be preserved as-is and the read side should not error (forward compatible).
    card["future_field"] = {"note": "schema Added through evolution"}
    lib.add(card)
    assert lib.get(card["id"]) == card  # Field-level equality, including unknown keys


def test_validate_card_rejects_benchmark_field() -> None:
    bad = _card()
    # Field outside the contract (benchmark-derived) → must be rejected
    bad["benchmark_score"] = 0.87
    with pytest.raises(ValueError, match="fields outside the contract"):
        validate_card(bad)


def test_validate_card_rejects_d5_area_out_of_vocab() -> None:
    bad = _card()
    bad["dimensions"]["D5_domain"]["area"] = "quantum-computing"  # Not in the controlled vocabulary
    with pytest.raises(ValueError, match="controlled vocabulary"):
        validate_card(bad)


def test_valid_card_passes_validation() -> None:
    validate_card(_card())  # Passing = no exception raised
    assert _card()["dimensions"]["D5_domain"]["area"] in D5_AREA_VOCAB
