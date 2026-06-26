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
    assert "accept" in space      # 有可接受产物 -> accept(与耐心无关)


def test_resolve_free_is_classified_into_space() -> None:
    p = _persona()
    space = ["accept", "give_feedback", "refine_request"]
    aid, msg = resolve_action({"action": "free", "message": "looks good, accept it"}, space, p)
    assert aid == "accept" and msg


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
