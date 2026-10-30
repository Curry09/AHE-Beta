"""内层 prompt 行为框架（可选核实）与 skill 占位（spec-0008/T3）。

纯文本断言、不调 LLM。覆盖：D1 工具清单门控、可选/有成本核实措辞、D3/trust 倾向变化、
skill 占位（senior 才挂、片段为通用方法）、build_inner_system 端到端拼装。
"""

from __future__ import annotations

from auto_designer.user.sim.clauses import clause_capability, clause_verification_policy
from auto_designer.user.sim.dimensions import (
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
from auto_designer.user.sim.prompt import build_inner_system
from auto_designer.user.sim.skills import Skill, select_skills
from auto_designer.user.sim.state import State
from auto_designer.user.sim.tools import tool_stack


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
# 能力清单（CAN，机械门控的如实描述）
# --------------------------------------------------------------------------
def test_capability_clause_varies_by_d1() -> None:
    blind = clause_capability(_persona(D1Eval.BLIND), [])
    assert "NO tools" in blind

    shallow_tools = [t.name for t in tool_stack(_persona(D1Eval.SHALLOW))]
    shallow = clause_capability(_persona(D1Eval.SHALLOW), shallow_tools)
    assert "run_file" not in shallow  # 不臆造
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
# 可选核实 + WILL 倾向（D3 / trust）
# --------------------------------------------------------------------------
def test_verification_is_optional_and_costly() -> None:
    pol = clause_verification_policy(_persona(D1Eval.COMPETENT), TrustStance.BALANCED)
    assert "optional" in pol.lower() and "cost" in pol.lower()
    assert "every turn" in pol.lower()  # 明确「不是每轮都查」


def test_verification_lean_varies() -> None:
    # 严格 D3 或 skeptical -> 倾向核实
    strict = clause_verification_policy(
        _persona(D1Eval.EXPERT, d3=D3Accept.RIGOROUS), TrustStance.SKEPTICAL
    )
    assert "inclined to actually verify" in strict

    # 盲信 / runs 阈值 -> 几乎不查
    lax = clause_verification_policy(_persona(D1Eval.BLIND, d3=D3Accept.RUNS), TrustStance.BLIND)
    assert "almost never" in lax


# --------------------------------------------------------------------------
# skill 占位
# --------------------------------------------------------------------------
def test_select_skills_senior_only_and_generic() -> None:
    assert select_skills(_persona(D1Eval.COMPETENT, depth=D2Depth.PROFICIENT)) == []
    senior = select_skills(_persona(D1Eval.EXPERT, depth=D2Depth.SENIOR))
    assert senior and all(isinstance(s, Skill) for s in senior)
    # 通用方法、不含 bug/benchmark/答案特定词
    blob = " ".join(s.prompt.lower() for s in senior)
    for banned in ("dst", "pytz", "timezone", "answer", "gold", "benchmark"):
        assert banned not in blob


def test_build_inner_system_includes_skills_when_present() -> None:
    p = _persona(D1Eval.EXPERT, depth=D2Depth.SENIOR)
    sys = build_inner_system(p, tool_stack(p), select_skills(p), State())
    assert "# SKILLS" in sys and "reproduce-first" in sys
    assert "# INNER TOOL USE" in sys  # 内层协议段在


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
