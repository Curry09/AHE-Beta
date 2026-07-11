"""spec-0005/T3：提示装配 + 离线 ScriptedPersonaClient + 容错解析。"""

from __future__ import annotations

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
from auto_designer.user.sim.persona_client import ScriptedPersonaClient, _parse_json
from auto_designer.user.sim.prompt import build_rating_turn, build_system, build_user_turn
from auto_designer.user.sim.state import State, init_state


def _persona(d1: D1Eval = D1Eval.EXPERT, d43: D43Correct = D43Correct.FILE_ISSUE) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P",
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.EVERY_STEP,
            d43=d43,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


def test_build_system_prefix_is_stable() -> None:
    p = _persona()
    a, b = build_system(p), build_system(p)
    assert a == b
    assert a.startswith("# ROLE")


def test_build_user_turn_has_sections() -> None:
    p = _persona()
    state = init_state(p)
    state.pending_self_obs = "I ran it; no error."
    user = build_user_turn("do X", ["[t0] you -> harness: hi"], "some output", ["accept"], state)
    for tag in (
        "<task>",
        "<history>",
        "<harness_output>",
        "<action_space>",
        "<mood>",
        "<self_observation>",
    ):
        assert tag in user


def test_build_user_turn_injects_manual_and_wait_cost() -> None:
    p = _persona()
    state = init_state(p)
    user = build_user_turn(
        "do X",
        [],
        "out",
        ["accept"],
        state,
        manual="# Manual\nno live progress; no /btw.",
        wait_sec=372.0,
    )
    assert "<harness_manual>" in user and "no live progress" in user
    assert "<wait_cost>" in user and "372s" in user


def test_build_user_turn_omits_manual_and_wait_when_absent() -> None:
    p = _persona()
    user = build_user_turn("do X", [], "out", ["accept"], init_state(p))  # 默认无手册/无耗时
    assert "<harness_manual>" not in user
    assert "<wait_cost>" not in user


def test_build_rating_turn_contract() -> None:
    out = build_rating_turn("do X", [], init_state(_persona()))
    assert "1-4" in out or "1–4" in out
    assert '"score"' in out and '"reason"' in out


def test_scripted_client_opening_sends_task() -> None:
    p = _persona()
    ret = ScriptedPersonaClient().respond(
        build_system(p), build_user_turn("t", [], "", ["send_task"], init_state(p))
    )
    assert ret["action"] == "send_task"


def test_scripted_client_rate_experience_returns_score() -> None:
    p = _persona()
    user = build_rating_turn("t", [], init_state(p))
    ret = ScriptedPersonaClient().respond(build_system(p), user)
    assert 1 <= int(ret["score"]) <= 4 and "reason" in ret


def test_scripted_client_exhausted_files_issue() -> None:
    p = _persona(d43=D43Correct.FILE_ISSUE)
    exhausted = State(turn=5, patience=0, trust=p.trust)
    user = build_user_turn("t", ["prev"], "Works now.", ["accept", "file_issue"], exhausted)
    ret = ScriptedPersonaClient().respond(build_system(p), user)
    assert ret["action"] == "file_issue"


def test_scripted_client_capability_fork() -> None:
    state_full = init_state(_persona())
    ho = "$ ran it: 2024-07-01 09:00:00+08:00 (no error)\nWorks now."
    space = ["accept", "request_evidence", "give_feedback"]
    expert = ScriptedPersonaClient().respond(
        build_system(_persona(d1=D1Eval.EXPERT)), build_user_turn("t", ["p"], ho, space, state_full)
    )
    shallow = ScriptedPersonaClient().respond(
        build_system(_persona(d1=D1Eval.SHALLOW)),
        build_user_turn("t", ["p"], ho, space, state_full),
    )
    assert expert["action"] != "accept"  # 专家不轻易接受
    assert shallow["action"] == "accept"  # 浅层能跑即接受


def test_parse_json_tolerant() -> None:
    assert _parse_json('```json\n{"action": "accept", "message": "ok"}\n```')["action"] == "accept"
    assert _parse_json('noise {"action": "give_up"} trailing')["action"] == "give_up"
    # 完全无法解析 -> 返回安全 dict, 不抛
    safe = _parse_json("not json at all")
    assert safe["action"] == "free"
