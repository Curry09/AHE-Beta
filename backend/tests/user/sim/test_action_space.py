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
from auto_designer.user.sim.state import State, init_state


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


def test_opening_only_send_task() -> None:
    p = _persona()
    assert derive_action_space(Phase.OPENING, p, init_state(p), has_artifact=False) == ["send_task"]


def test_capability_mask_gates_verify_actions() -> None:
    expert = _persona(d1=D1Eval.EXPERT)
    blind = _persona(d1=D1Eval.BLIND)
    se = derive_action_space(Phase.ACTIVE, expert, init_state(expert), has_artifact=False)
    sb = derive_action_space(Phase.ACTIVE, blind, init_state(blind), has_artifact=False)
    assert "verify_self" in se and "request_evidence" in se
    assert "verify_self" not in sb and "request_evidence" not in sb


def test_authz_read_only_removes_run_actions() -> None:
    p = _persona(d1=D1Eval.EXPERT, d5=D5Autonomy.ADVISORY)  # advisory -> READ_ONLY
    space = derive_action_space(Phase.ACTIVE, p, init_state(p), has_artifact=False)
    assert "ask_harness_run" not in space and "grant_autorun" not in space


def test_patience_gate_unlocks_terminal_and_accept() -> None:
    p = _persona(d43=D43Correct.FILE_ISSUE)
    exhausted = State(turn=3, patience=0, trust=p.trust)
    space = derive_action_space(Phase.ACTIVE, p, exhausted, has_artifact=True)
    assert "file_issue" in space  # 耐心耗尽解锁 D4.3 选定的终止动作
    assert "accept" in space  # 有可接受产物 -> accept(与耐心无关)


def test_accept_with_reservations_offered_alongside_accept() -> None:
    # 有可接受产物时，accept 与 accept_with_reservations 一起给出：完成了但不达预期，
    # 模型可选后者「照样交付 + 留一条体感落差 issue」。无产物时都不出现。
    p = _persona()
    with_art = derive_action_space(Phase.ACTIVE, p, init_state(p), has_artifact=True)
    assert "accept" in with_art and "accept_with_reservations" in with_art
    no_art = derive_action_space(Phase.ACTIVE, p, init_state(p), has_artifact=False)
    assert "accept_with_reservations" not in no_art
    # 它是终止动作、end_reason 仍是 accepted（照常交付，不改变交付事实）。
    assert CATALOG["accept_with_reservations"].effect is CATALOG["accept"].effect
    assert CATALOG["accept_with_reservations"].end_reason == "accepted"


def test_resolve_free_falls_back_to_safe_nonterminal() -> None:
    # 方案 B: resolve 不再用关键词猜意图。无模型自评时, free 一律落安全的非终止动作,
    # 即便文本里写着 "accept it" 也绝不擅自终止(避免污染体感/issue 信号)。
    p = _persona()
    space = ["accept", "give_feedback", "refine_request"]
    aid, msg = resolve_action({"action": "free", "message": "looks good, accept it"}, space, p)
    assert aid == "give_feedback" and aid != "accept" and msg.strip()


def test_resolve_projects_illegal_to_same_effect() -> None:
    p = _persona(d1=D1Eval.BLIND)
    # blind 空间没有 verify_self；越权动作按同 effect(VERIFY) 投影到合法集
    space = ["ask_harness_run", "give_feedback", "refine_request"]
    aid, _ = resolve_action({"action": "verify_self", "message": ""}, space, p)
    assert aid in space and CATALOG[aid].effect is CATALOG["verify_self"].effect


def test_resolve_enforces_channel_consistency() -> None:
    p = _persona()
    # SILENT 动作强制清空 message
    space = ["verify_self", "give_feedback"]
    aid, msg = resolve_action({"action": "verify_self", "message": "noisy"}, space, p)
    assert aid == "verify_self" and msg == "" and CATALOG[aid].channel is Channel.SILENT
    # EMIT 但 message 空 -> 兜底填充非空
    aid2, msg2 = resolve_action({"action": "give_feedback", "message": ""}, space, p)
    assert aid2 == "give_feedback" and msg2.strip()


def test_diagnosis_gate_unlocks_terminal_for_capable_without_patience_drain() -> None:
    # 耐心仍充足(>0), 但高能力档连续 2 次坐实 harness 失败 -> 诊断驱动解锁升级。
    p = _persona(d1=D1Eval.EXPERT, d43=D43Correct.FILE_ISSUE)
    diagnosed = State(turn=2, patience=4, trust=p.trust, consec_blame=2)
    space = derive_action_space(Phase.ACTIVE, p, diagnosed, has_artifact=True)
    assert "file_issue" in space


def test_diagnosis_gate_requires_two_consecutive_blames() -> None:
    p = _persona(d1=D1Eval.EXPERT, d43=D43Correct.FILE_ISSUE)
    one = State(turn=1, patience=5, trust=p.trust, consec_blame=1)
    space = derive_action_space(Phase.ACTIVE, p, one, has_artifact=True)
    assert "file_issue" not in space  # 仅 1 次坐实未达阈值, 不解锁


def test_diagnosis_gate_blocked_for_low_capability() -> None:
    # 识别"结构性无能力"本身需要能力: blind/shallow 无诊断快速通道, 仍靠耐心消耗。
    p = _persona(d1=D1Eval.SHALLOW, d43=D43Correct.FILE_ISSUE)
    diagnosed = State(turn=2, patience=4, trust=p.trust, consec_blame=2)
    space = derive_action_space(Phase.ACTIVE, p, diagnosed, has_artifact=True)
    assert "file_issue" not in space


def test_negative_terminal_never_projects_to_accept() -> None:
    # file_issue/give_up 未解锁时, 绝不投影到 accept(语义相反), 降级为继续反馈。
    p = _persona(d43=D43Correct.FILE_ISSUE)
    space = ["accept", "give_feedback", "refine_request"]
    aid, msg = resolve_action({"action": "file_issue", "message": "filing an issue"}, space, p)
    assert aid == "give_feedback" and aid != "accept" and msg.strip()
    aid2, _ = resolve_action({"action": "give_up", "message": "I quit"}, space, p)
    assert aid2 == "give_feedback"
