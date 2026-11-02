"""persona_io.py（spec-0006/T2 + Spec-0037/T4）：把 persona 卡注入控制信封 sim。

card_to_persona 是「采集（行为卡，0006/T1）」与「sim 引擎（dimensions.Persona）」
之间的唯一桥接层：按字段把卡翻成 sim 维度，**卡里 grounded 的验收(D2)/信任(D4) 直接写入 sim 的派生维
d3/trust 并不被 derive_* 改写（覆盖派生）**；时间气质 D7 写入 tempo（缺省 steady）；
卡未 ground 的派生维交 finalize_persona 派生填齐。D6Authz 不进卡库，始终半派生。

为何需要覆盖派生：sim 的 d3/trust 原是「从 D1/D2 派生」，若一律 finalize，会把卡里真实 ground 的
信任/验收改写成合成值——例如 expert×over-trust 的 Karpathy（selfreport 例 C）会被模拟成 skeptical×rigorous
的反面，直接污染训练信号的真实性。卡形状契约见 tools/persona-distill/card-schema.md。

非法/缺失枚举值显式报错（不静默兜底），把采集质量问题暴露在注入边界；唯 D7 缺省兼容旧卡。
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
# 卡枚举 → sim 枚举 映射表（显式，吸收两套受控词表的差异）
# --------------------------------------------------------------------------
_D1: dict[str, D1Eval] = {
    "blind": D1Eval.BLIND,
    "surface": D1Eval.SHALLOW,  # surface ↔ shallow 并轨
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
        raise ValueError(f"卡缺字段：{where}.{key}")
    return container[key]


def _map_enum(table: dict, raw: object, where: str):
    if raw not in table:
        raise ValueError(f"卡 {where} 非法枚举值 {raw!r}；合法取值 {sorted(table)}")
    return table[raw]


def card_to_persona(record: dict) -> Persona:
    """把一条行为卡映射为 sim 的 dimensions.Persona。

    采样维（能力/交互/自主/时间气质）总是从卡直接写入；
    派生维 d3(来自卡 D2)/trust(来自卡 D4) 仅在卡 source=grounded 时直接写入（覆盖派生），
    否则留 None 交 finalize_persona 派生；D6Authz 卡无来源，始终由 finalize 派生。

    D7_time_temperament 缺省时回落 steady（旧卡前向兼容，不当作失败）。
    """
    persona_id = _require(record, "id", "card")
    dims = _require(record, "dimensions", "card")

    # --- 采样维：始终从卡写入 ---
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

    # D7 时间气质：新轴；旧卡缺字段 → steady（兼容，不报错）
    tempo = TimeTemperament.STEADY
    tempo_block = dims.get("D7_time_temperament")
    if isinstance(tempo_block, dict) and "value" in tempo_block:
        tempo = _map_enum(_TEMPO, tempo_block["value"], "D7_time_temperament.value")

    # --- 派生维：仅 grounded 时覆盖写入，否则留 None 交 finalize ---
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
        trust=trust,  # grounded 则透传；None 则 finalize 派生（D6Authz 始终派生）
    )
    return finalize_persona(raw)


def card_to_personas(library: PersonaLibrary) -> list[Persona]:
    """把库内每条卡映射为 sim Persona（等长列表）。"""
    return [card_to_persona(record) for record in library.load()]
