"""spec-0006/T2：card_to_persona 注入 sim —— grounded 覆盖派生（含 Karpathy 例 C）。"""

from __future__ import annotations

import copy

import pytest

from auto_designer.distill.library import PersonaLibrary
from auto_designer.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D3Accept,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    TrustStance,
    derive_d3,
    derive_trust,
)
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.loop import SessionResult, run_session
from auto_designer.user.sim.persona_client import ScriptedPersonaClient
from auto_designer.user.sim.persona_io import card_to_persona, card_to_personas

TASK = "Add to_user_tz(dt, tz_name); handle DST."


def _karpathy_card() -> dict:
    """selfreport 例 C：expert × over-trust × ship-fast，全 grounded。"""
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
        },
    }


def test_grounded_override_karpathy_not_simulated_as_opposite() -> None:
    p = card_to_persona(_karpathy_card())
    # D1=expert：若一律 finalize，d3 会 derive 成 RIGOROUS、trust 会 derive 成 SKEPTICAL。
    assert derive_d3(D1Eval.EXPERT, p.d2) is D3Accept.RIGOROUS  # 反面基准
    assert derive_trust(D1Eval.EXPERT, p.d2) is TrustStance.SKEPTICAL
    # 实际：grounded 的卡 D2=ship-fast / D4=over-trust 覆盖派生。
    assert p.d3 is D3Accept.RUNS  # 未被改写成 RIGOROUS
    assert p.trust is TrustStance.BLIND  # over-trust ↔ blind，未被改写成 SKEPTICAL
    assert p.d1 is D1Eval.EXPERT
    assert p.d6 is not None  # D6Authz 卡无来源 → 仍由 finalize 派生填齐


def test_sampled_axes_mapped_and_surface_aliases_shallow() -> None:
    card = _karpathy_card()
    card["dimensions"]["D1_evaluation_capability"]["value"] = "surface"
    p = card_to_persona(card)
    assert p.d1 is D1Eval.SHALLOW  # surface ↔ shallow 并轨
    assert p.d2.depth is D2Depth.SENIOR  # deep → senior
    assert p.d41 is D41Grain.ONE_LINER  # vibe-dump
    assert p.d42 is D42Supervise.FIRE_FORGET  # hands-off
    assert p.d43 is D43Correct.RESEND  # retry
    assert p.d5 is D5Autonomy.AGENTIC  # agentic


def test_ungrounded_derived_axes_fall_back_to_finalize() -> None:
    card = _karpathy_card()
    card["dimensions"]["D1_evaluation_capability"]["value"] = "competent"
    card["dimensions"]["D5_domain"]["depth"] = "working"
    # 验收/信任都标 injected → 不覆盖，交 finalize 派生。
    card["dimensions"]["D2_acceptance_bar"]["source"] = "injected"
    card["dimensions"]["D4_trust_model"]["source"] = "injected"
    a = card_to_persona(card)
    b = card_to_persona(card)
    assert a == b  # 可复现
    assert a.d3 is derive_d3(D1Eval.COMPETENT, a.d2)
    assert a.trust is derive_trust(D1Eval.COMPETENT, a.d2)


def test_illegal_enum_raises() -> None:
    card = _karpathy_card()
    card["dimensions"]["D1_evaluation_capability"]["value"] = "wizard"
    with pytest.raises(ValueError, match="非法枚举值"):
        card_to_persona(card)


def test_missing_field_raises() -> None:
    card = _karpathy_card()
    del card["dimensions"]["D4_trust_model"]
    with pytest.raises(ValueError, match="缺字段"):
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
