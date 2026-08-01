"""spec-0005/T2：动作空间派生 + 自由产出归类/越权投影/channel 校验。"""

from __future__ import annotations

from auto_designer.user.sim.action_space import derive_action_space, resolve_action
from auto_designer.user.sim.actions import CATALOG, Channel, Phase
from auto_designer.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from auto_designer.user.sim.state import init_state


def _persona(
    d1: D1Eval = D1Eval.EXPERT,
    d5: D5Autonomy = D5Autonomy.COLLABORATIVE,
    d43: D43Correct = D43Correct.FILE_ISSUE,
) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P",
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.EVERY_STEP,
            d43=d43,
            d5=d5,
        )
    )


def test_opening_only_send_message() -> None:
    p = _persona()
    assert derive_action_space(Phase.OPENING, p, init_state(p)) == ["send_message"]


def test_active_external_actions_are_unified_across_capability_and_authz() -> None:
    expert = _persona(d1=D1Eval.EXPERT)
    blind_read_only = _persona(d1=D1Eval.BLIND, d5=D5Autonomy.ADVISORY)
    se = derive_action_space(Phase.ACTIVE, expert, init_state(expert))
    sb = derive_action_space(Phase.ACTIVE, blind_read_only, init_state(blind_read_only))
    assert {"interrupt", "keep_waiting", "send_message"} <= set(se)
    assert {"interrupt", "keep_waiting", "send_message"} <= set(sb)
    for legacy in (
        "verify_self",
        "request_evidence",
        "ask_harness_run",
        "grant_autorun",
        "give_feedback",
        "refine_request",
    ):
        assert legacy not in se
        assert legacy not in sb


def test_active_offers_all_four_terminals_without_framework_gate() -> None:
    # loosen：进 ACTIVE 后四个终止动作(accept/accept_with_reservations/file_issue/give_up)全放开，
    # 不被耐心/诊断/产物门控——验收与否、何时退，均由模型按 persona 性格 + <mood> 自判。耐心满也一样。
    p = _persona(d43=D43Correct.FILE_ISSUE)
    fresh = derive_action_space(Phase.ACTIVE, p, init_state(p))
    assert {"accept", "accept_with_reservations", "file_issue", "give_up"} <= set(fresh)
    # 对所有 persona 都放开（该开单/该走人由 prompt 里的 D43_CLAUSE 主导，框架不替选）。
    p2 = _persona(d43=D43Correct.GIVE_UP)
    fresh2 = derive_action_space(Phase.ACTIVE, p2, init_state(p2))
    assert {"accept", "accept_with_reservations", "file_issue", "give_up"} <= set(fresh2)
    # accept_with_reservations 与 accept 同为 TERMINATE、end_reason=accepted（照常交付，留体感落差）。
    assert CATALOG["accept_with_reservations"].effect is CATALOG["accept"].effect
    assert CATALOG["accept_with_reservations"].end_reason == "accepted"


def test_resolve_free_falls_back_to_safe_nonterminal() -> None:
    # 方案 B: resolve 不再用关键词猜意图。无模型自评时, free 一律落安全的非终止动作,
    # 即便文本里写着 "accept it" 也绝不擅自终止(避免污染体感/issue 信号)。
    p = _persona()
    space = ["accept", "send_message"]
    aid, msg = resolve_action({"action": "free", "message": "looks good, accept it"}, space, p)
    assert aid == "send_message" and aid != "accept" and msg.strip()


def test_resolve_projects_legacy_external_actions_to_send_message() -> None:
    p = _persona(d1=D1Eval.BLIND)
    space = ["send_message", "accept"]
    for legacy in ("verify_self", "ask_harness_run", "request_evidence", "give_feedback"):
        aid, _ = resolve_action({"action": legacy, "message": "show me evidence"}, space, p)
        assert aid == "send_message"


def test_resolve_enforces_channel_consistency() -> None:
    p = _persona()
    # EMIT 但 message 空 -> 框架不再 fabricate 罐头，保持空（补齐由 client 侧重问模型完成）。
    space = ["send_message"]
    aid, msg = resolve_action({"action": "send_message", "message": ""}, space, p)
    assert aid == "send_message" and msg == "" and CATALOG[aid].channel is Channel.EMIT


def test_opening_is_the_only_structural_gate_against_accepting_nothing() -> None:
    # 唯一防"验收虚无"的结构边界是 OPENING（还没发消息→只能 send_message，无任何终止动作）。
    # 进了 ACTIVE 就至少有一条 harness 回合可反应，验收与否交给模型。
    p = _persona()
    opening = derive_action_space(Phase.OPENING, p, init_state(p))
    assert opening == ["send_message"]
    active = derive_action_space(Phase.ACTIVE, p, init_state(p))
    assert "accept" in active and "file_issue" in active
    assert "keep_waiting" in active and "interrupt" in active


def test_negative_terminal_never_projects_to_accept() -> None:
    # file_issue/give_up 未解锁时, 绝不投影到 accept(语义相反), 降级为继续对 harness 发消息。
    p = _persona(d43=D43Correct.FILE_ISSUE)
    space = ["accept", "send_message"]
    aid, msg = resolve_action({"action": "file_issue", "message": "filing an issue"}, space, p)
    assert aid == "send_message" and aid != "accept" and msg.strip()
    aid2, _ = resolve_action({"action": "give_up", "message": "I quit"}, space, p)
    assert aid2 == "send_message"
