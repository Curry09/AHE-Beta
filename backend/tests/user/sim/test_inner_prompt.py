"""Inner layer prompt behavior framework (optional verification) and skill placeholder (spec-0008/T3).

Plain text assertions, no LLM call. Coverage: D1 tool list gating, optional/costly verification wording, D3/trust inclination changes, skill placeholder (senior only, fragments as generic methods), build_inner_system end-to-end assembly.
"""

from __future__ import annotations

from ahe_beta.user.sim.clauses import clause_capability, clause_verification_policy
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
    TrustStance,
    finalize_persona,
)
from ahe_beta.user.sim.prompt import build_inner_system
from ahe_beta.user.sim.skills import Skill, select_skills
from ahe_beta.user.sim.state import State
from ahe_beta.user.sim.tools import tool_stack


def _persona(d1: D1Eval, depth: D2Depth = D2Depth.PROFICIENT, d3=None) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="p",
            d1=d1,
            d2=D2Domain(depth=depth),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
            d3=d3,
        )
    )


# --------------------------------------------------------------------------
# Capability list (CAN, mechanical gating truthful description)
# --------------------------------------------------------------------------
def test_capability_clause_varies_by_d1() -> None:
    blind = clause_capability(_persona(D1Eval.BLIND), [])
    assert "NO tools" in blind

    shallow_tools = [t.name for t in tool_stack(_persona(D1Eval.SHALLOW))]
    shallow = clause_capability(_persona(D1Eval.SHALLOW), shallow_tools)
    assert "run_file" not in shallow  # Do not fabricate
    assert "do not author your own test suites" in shallow

    expert_tools = [t.name for t in tool_stack(_persona(D1Eval.EXPERT))]
    expert = clause_capability(_persona(D1Eval.EXPERT), expert_tools)
    assert "write your own test scripts or code changes" in expert
    assert "your own contributions" in expert


def test_inner_system_renders_tools_by_d1() -> None:
    state = State()
    blind = build_inner_system(
        _persona(D1Eval.BLIND), tool_stack(_persona(D1Eval.BLIND)), [], state
    )
    assert "no tools" in blind.lower()

    expert_p = _persona(D1Eval.EXPERT)
    expert = build_inner_system(expert_p, tool_stack(expert_p), [], state)
    assert "write_file(" in expert and "run_shell(" in expert


# --------------------------------------------------------------------------
# Optional verification + WILL inclination (D3 / trust)
# --------------------------------------------------------------------------
def test_verification_is_optional_and_costly() -> None:
    pol = clause_verification_policy(_persona(D1Eval.COMPETENT), TrustStance.BALANCED)
    assert "optional" in pol.lower() and "cost" in pol.lower()
    assert "every turn" in pol.lower()  # Clarify "not every round checks"


def test_verification_lean_varies() -> None:
    # Strict D3 or skeptical → tend to verify
    strict = clause_verification_policy(
        _persona(D1Eval.EXPERT, d3=D3Accept.RIGOROUS), TrustStance.SKEPTICAL
    )
    assert "inclined to actually verify" in strict

    # Blind trust / runs threshold → rarely checks
    lax = clause_verification_policy(_persona(D1Eval.BLIND, d3=D3Accept.RUNS), TrustStance.BLIND)
    assert "almost never" in lax


# --------------------------------------------------------------------------
# skill placeholder
# --------------------------------------------------------------------------
def test_select_skills_senior_only_and_generic() -> None:
    assert select_skills(_persona(D1Eval.COMPETENT, depth=D2Depth.PROFICIENT)) == []
    senior = select_skills(_persona(D1Eval.EXPERT, depth=D2Depth.SENIOR))
    assert senior and all(isinstance(s, Skill) for s in senior)
    # Generic methods, no bug/benchmark/answer-specific keywords
    blob = " ".join(s.prompt.lower() for s in senior)
    for banned in ("dst", "pytz", "timezone", "answer", "gold", "benchmark"):
        assert banned not in blob


def test_build_inner_system_includes_skills_when_present() -> None:
    p = _persona(D1Eval.EXPERT, depth=D2Depth.SENIOR)
    sys = build_inner_system(p, tool_stack(p), select_skills(p), State())
    assert "# SKILLS" in sys and "reproduce-first" in sys
    assert "# INNER TOOL USE" in sys  # Inner protocol section at


def test_build_inner_system_excludes_global_action_contract() -> None:
    p = _persona(D1Eval.EXPERT, depth=D2Depth.SENIOR)
    sys = build_inner_system(p, tool_stack(p), select_skills(p), State())
    for marker in (
        "G3",
        "G7",
        "# ACTION SEMANTICS",
        "# OUTPUT CONTRACT",
        "<action_space>",
        "accept / give_up / file_issue",
        "accept_with_reservations: terminal",
        "Terminal TIMING",
        "<file_issue>",
        "<rate_experience>",
        "1–4 satisfaction scale",
        "1-4 satisfaction scale",
    ):
        assert marker not in sys
    assert "# INNER TOOL USE" in sys
    assert "# TOOLS" in sys
    assert "# PERSONA" in sys
