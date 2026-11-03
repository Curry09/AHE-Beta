"""spec-0010/T2: card_to_seed field mapping + held-out stripping + envelope shape + injection boundary validation."""

from __future__ import annotations

import json

import pytest

from ahe_beta.distill.seed_adapter import (
    card_to_seed,
    card_to_seeds,
    extract_sidecar,
)
from ahe_beta.distill.seed_library import SeedLibrary

# A resolved, real 40-character commit SHA (counterexample to the placeholder).
_SHA = "0e322af87745eff34caffe4df68456ebc20d9068"


def _git_card(seed_id: str = "seed-requests-6964") -> dict:
    # Field appearance taken from a real harvest example (psf/requests netrc leak fix); repo_at is resolved to a real SHA.
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
            "prompt": "requests.get('http://example.com:@evil.com/') leaks my netrc creds. make it stop.",
            "context": "requests, a ~/.netrc with credentials, a crafted URL",
        },
        "domain": "web-backend",
        "capability_probed": ["correctness-edgecase"],
        "difficulty": "medium",
        "scope": "single-file",
        "autonomy_required": "collaborative",
        "oracle": {
            "tier": "executable-test",
            "spec": "regression test in PR #6962 (FAIL@parent -> PASS@fix)",
            "reference_solution": "PR #6965",
            "confidence": "high",
        },
        "env": {
            "reproducible": "easy",
            "base_image": "python:3.11",
            "repo_at": _SHA,
            "setup": ["pip install -e .", "pip install -r requirements-dev.txt"],
            "test_cmd": "pytest tests/test_utils.py -k netrc",
            "external_deps": "none",
            "budget": {"timeout_s": 300, "mem_gb": 2},
        },
        "pairing_constraints": {"domain": "web-backend", "min_capability": "competent"},
        "gates": {"oracle_gate": "pass", "harbor_repro_gate": "pass"},
        "provenance": {
            "resolution_quote": "uses the hostname attribute from the parsed url",
            "source": "https://github.com/psf/requests/pull/6962",
        },
    }


def _text_card(seed_id: str = "seed-so-4c5d") -> dict:
    # Plain-text scenario: accepted SO answer, no repo (rubric oracle).
    return {
        "id": seed_id,
        "source": {"type": "accepted_so_answer", "repo": "n/a", "not_in_benchmark": True},
        "task": {
            "prompt": "make a popup that warns before leaving the page if my editor has unsaved stuff. react.",
            "context": "react app, a textarea",
        },
        "domain": "web-frontend",
        "capability_probed": ["explanation-teaching"],
        "difficulty": "easy",
        "scope": "single-file",
        "autonomy_required": "advisory",
        "oracle": {
            "tier": "rubric",
            "spec": "must warn on unload + router nav",
            "confidence": "medium",
        },
        "env": {"reproducible": "hard-rubric-only", "external_deps": "none"},
        "gates": {"oracle_gate": "pass", "harbor_repro_gate": "downgraded"},
    }


def test_git_card_maps_to_git_workspace() -> None:
    seed = card_to_seed(_git_card())
    assert seed.description.startswith("requests.get(")
    ws = seed.workspace
    assert ws is not None
    assert ws.kind == "git"
    # owner/repo → https clone URL; repo_at → commit (resolved SHA).
    assert ws.params["repo"] == "https://github.com/psf/requests.git"
    assert ws.params["commit"] == _SHA
    # setup venv prefixing: the first command creates the venv, and pip steps are rewritten to .venv/bin/pip.
    assert ws.setup[0] == "python -m venv .venv"
    assert ws.setup[1] == ".venv/bin/pip install -e ."
    assert ws.setup[2] == ".venv/bin/pip install -r requirements-dev.txt"


def test_heldout_fields_stripped_and_recoverable() -> None:
    card = _git_card()
    seed = card_to_seed(card)

    # Red line: SeedScenario and its to_dict must never contain oracle/test_cmd/gates.
    d = seed.to_dict()
    text = json.dumps(d, ensure_ascii=False)
    for banned in ("oracle", "test_cmd", "gates"):
        assert banned not in d
        assert f'"{banned}"' not in text
    assert "commit" in d["workspace"]["params"]  # But git snapshot metadata is retained

    # Sidecar can retrieve stripped scoring artifacts.
    side = extract_sidecar(card)
    assert side["oracle"]["tier"] == "executable-test"
    assert side["test_cmd"] == "pytest tests/test_utils.py -k netrc"
    assert side["gates"]["oracle_gate"] == "pass"


def test_text_card_maps_to_none_workspace() -> None:
    seed = card_to_seed(_text_card())
    assert seed.workspace is None
    assert seed.description.startswith("make a popup")
    # Plain text to_dict only drops description (preserves existing shape).
    assert seed.to_dict() == {"description": seed.description}


def test_card_to_seeds_envelope_shape_and_no_heldout(tmp_path) -> None:
    lib = SeedLibrary(tmp_path / "seeds.json")
    lib.add(_git_card("seed-a"))
    lib.add(_text_card("seed-b"))

    envelope = card_to_seeds(lib)
    assert envelope["version"] == 1
    assert len(envelope["seeds"]) == 2
    # The entire envelope JSON does not contain three held-out keys.
    text = json.dumps(envelope, ensure_ascii=False)
    for banned in ("oracle", "test_cmd", "gates"):
        assert f'"{banned}"' not in text


def test_raw_card_library_preserves_adapter_boundary(tmp_path) -> None:
    # Archived raw seed libraries still preserve the distill held-out boundary.

    path = tmp_path / "seeds.json"
    lib = SeedLibrary(path)
    lib.add(_git_card("seed-a"))
    lib.add(_text_card("seed-b"))

    seeds = [card_to_seed(record) for record in SeedLibrary(path).load()]
    assert len(seeds) == 2  # Equal-length SeedScenario list
    assert seeds[0].workspace is not None and seeds[0].workspace.kind == "git"
    assert seeds[1].workspace is None
    # Held-out scoring artifacts are stripped at injection boundary: SeedScenario and its to_dict do not contain oracle/test_cmd/gates.
    text = json.dumps([s.to_dict() for s in seeds], ensure_ascii=False)
    for banned in ("oracle", "test_cmd", "gates"):
        assert f'"{banned}"' not in text


def test_missing_repo_at_raises() -> None:
    card = _git_card()
    del card["env"]["repo_at"]
    with pytest.raises(ValueError, match="repo_at"):
        card_to_seed(card)


def test_placeholder_repo_at_raises() -> None:
    card = _git_card()
    card["env"]["repo_at"] = "<parent-commit-of-PR-6965-merge> (resolve at harvest time)"
    with pytest.raises(ValueError, match="unresolved placeholder"):
        card_to_seed(card)


def test_domain_out_of_vocab_raises() -> None:
    card = _git_card()
    card["domain"] = "quantum-computing"
    with pytest.raises(ValueError, match="controlled vocabulary"):
        card_to_seed(card)


def test_missing_prompt_raises() -> None:
    card = _git_card()
    card["task"] = {"context": "no prompt here"}
    with pytest.raises(ValueError, match="task.prompt"):
        card_to_seed(card)
