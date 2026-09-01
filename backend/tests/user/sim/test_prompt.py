"""主/等待 three 跳 prompt 契约 + 离线 ScriptedPersonaClient + 容错解析。"""

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
from auto_designer.user.sim.prompt import (
    build_issue_turn,
    build_main_act_turn,
    build_main_final_check_turn,
    build_main_intent_turn,
    build_main_judge_turn,
    build_main_reintent_turn,
    build_main_rejudge_turn,
    build_rating_turn,
    build_system,
    build_waiting_act_turn,
    build_waiting_intent_turn,
    build_waiting_judge_turn,
)
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


GLOBAL_FORBIDDEN_MARKERS = (
    "G3",
    "G7",
    "# ACTION SEMANTICS",
    "# OUTPUT CONTRACT",
    "<action_space>",
    '"action":',
    '"message":',
    "accept / give_up / file_issue",
    "accept_with_reservations: terminal",
    "Terminal TIMING",
    "<file_issue>",
    "<rate_experience>",
    "1–4 satisfaction scale",
    "1-4 satisfaction scale",
)


def test_build_system_prefix_is_stable() -> None:
    p = _persona()
    a, b = build_system(p), build_system(p)
    assert a == b
    assert a.startswith("# ROLE")


def test_build_system_excludes_global_platform_contract() -> None:
    sys = build_system(_persona())
    for marker in GLOBAL_FORBIDDEN_MARKERS:
        assert marker not in sys
    assert "# PERSONA" in sys
    assert "# PERCEPTION BOUNDARY" in sys


def test_main_three_builders_have_sections() -> None:
    p = _persona()
    state = init_state(p)
    hist = ["[+0s] you -> harness: hi"]
    judge = build_main_judge_turn("do X", hist, "some output", ["accept"], state)
    intent = build_main_intent_turn(
        "do X", hist, "some output", ["accept"], state, verdict="unsure", perceive="notes"
    )
    act = build_main_act_turn(
        "do X",
        hist,
        "some output",
        ["accept"],
        state,
        verdict="unsure",
        perceive="notes",
        intent="accept if good",
    )
    for user in (judge, intent, act):
        for tag in ("<task>", "<history>", "<harness_output>", "<mood>"):
            assert tag in user
        assert "<wait_cost>" not in user
    early_forbidden = ("<action_space>", "# MENU", '"action":', '"message":', '"gap":')
    for early in (judge, intent):
        for marker in early_forbidden:
            assert marker not in early
        assert "<file_issue>" not in early and "<rate_experience>" not in early
    assert "<main_judge>" in judge
    assert "<main_intent>" in intent
    assert "raw wish" in intent
    assert "Your wish may go beyond the current tool" in intent
    assert "this step is only about what you want" in intent
    assert "The next act step will handle any mapping or gap" in intent
    assert "Do NOT optimize" not in intent
    assert "what the framework can do" not in intent
    assert "Examples only" not in intent
    assert "if the help text says so" not in intent
    assert "Read <harness_help>" not in intent
    assert "<main_act>" in act and "<action_space>" in act
    assert "# MENU" in act and "<judgment>" in act and "<intent>" in act and '"gap"' in act


def test_main_action_space_only_visible_to_act_turn() -> None:
    p = _persona()
    state = init_state(p)
    sentinel = "__LEAK_SENTINEL_ACTION__"
    hist = ["[+0s] you -> harness: hi"]
    judge = build_main_judge_turn("do X", hist, "some output", [sentinel], state)
    intent = build_main_intent_turn(
        "do X", hist, "some output", [sentinel], state, verdict="unsure", perceive="notes"
    )
    act = build_main_act_turn(
        "do X",
        hist,
        "some output",
        [sentinel],
        state,
        verdict="unsure",
        perceive="notes",
        intent="try the only button",
    )

    assert sentinel not in judge
    assert sentinel not in intent
    assert sentinel in act


def test_main_act_actions_are_mutually_explicit_about_continuation_and_completion() -> None:
    state = init_state(_persona())
    act = build_main_act_turn(
        "implement the requested fix",
        [],
        "I found the bug and can describe a patch.",
        [
            "send_message",
            "keep_waiting",
            "interrupt",
            "accept",
            "accept_with_reservations",
            "give_up",
            "file_issue",
        ],
        state,
        verdict="satisfied",
        perceive="the diagnosis looks right but no patch exists",
        intent="decide whether the task is actually done",
    )

    assert "- send_message: CONTINUE the session" in act
    assert "- keep_waiting: CONTINUE the session" in act
    assert "- interrupt: CONTINUE the session" in act
    assert "- accept: END the session immediately" in act
    assert "outcome of the original <task>" in act
    assert "not merely the latest reply, plan, diagnosis, or partial subtask" in act
    assert "No required deliverable remains for you to supply" in act
    assert "- accept_with_reservations: END the session immediately" in act
    assert "Use the same completion bar as accept" in act
    assert "if necessary work is missing, do not accept" in act
    assert "- give_up: END the session immediately" in act
    assert "taking over the remaining work yourself" in act
    assert "It does not require blaming the harness" in act
    assert "- file_issue: END the session immediately" in act
    assert "there is no later return in this same session" in act


def test_satisfied_judgment_is_not_a_terminal_completion_decision() -> None:
    judge = build_main_judge_turn(
        "implement the requested fix",
        [],
        "I found the bug.",
        ["accept", "send_message"],
        init_state(_persona()),
    )

    assert "satisfied: the current observation looks good enough to you" in judge
    assert "does NOT mean the original task is complete" in judge
    assert "if required work still remains" in judge


def test_handover_persona_does_not_count_self_completion_as_assistant_delivery() -> None:
    system = build_system(_persona(d43=D43Correct.HANDOVER))

    assert "stop relying on the assistant" in system
    assert "take over the remaining work yourself" in system
    assert "your own takeover is not a successful assistant delivery" in system


def test_final_check_rejudge_reintent_contracts_are_one_way() -> None:
    state = init_state(_persona())
    check = build_main_final_check_turn(
        "do X",
        [],
        "done",
        state,
        verdict="unsure",
        perceive="plausible",
        intent="verify once",
        check_goal="inspect the changed API",
    )
    rejudge = build_main_rejudge_turn(
        "do X",
        [],
        "done",
        state,
        prior_verdict="unsure",
        prior_perceive="plausible",
        check_status="completed",
        check_evidence="tests pass",
    )
    reintent = build_main_reintent_turn(
        "do X", [], "done", state, verdict="satisfied", perceive="tests pass"
    )

    assert "<main_final_check>" in check and "inspect the changed API" in check
    assert '"check_status"' in check and "Do not edit" in check
    assert "<main_rejudge>" in rejudge and "tests pass" in rejudge
    assert "cannot use another private tool" in rejudge
    assert "<main_reintent>" in reintent
    assert '"needs_final_check": false' in reintent
    assert "already been used" in reintent
    assert "<action_space>" not in check + rejudge + reintent


def test_main_judge_injects_help_text() -> None:
    p = _persona()
    state = init_state(p)
    user = build_main_judge_turn(
        "do X",
        [],
        "out",
        ["accept"],
        state,
        help_text="# Help\nno live progress; no /btw.",
    )
    assert "<harness_help>" in user and "no live progress" in user


def test_main_judge_omits_help_text_when_absent() -> None:
    p = _persona()
    user = build_main_judge_turn("do X", [], "out", ["accept"], init_state(p))
    assert "<harness_help>" not in user


def test_private_evidence_is_threaded_into_main_and_waiting_prompts() -> None:
    p = _persona()
    state = init_state(p)
    state.private_evidence = [
        "[E1 after_reply/judge]\n"
        "Private tools: read_file `xarray/core/dataarray.py`.\n"
        "Conclusion: DataArray.integrate now accepts coord."
    ]
    main = build_main_judge_turn("do X", [], "out", ["accept"], state)
    waiting = build_waiting_judge_turn("do X", [], state, waited_sec=90.0)
    for user in (main, waiting):
        assert "<private_evidence>" in user
        assert "[E1 after_reply/judge]" in user
        assert "DataArray.integrate now accepts coord" in user


def test_waiting_three_builders_tags() -> None:
    state = init_state(_persona())
    judge = build_waiting_judge_turn("t", [], state, waited_sec=90.0)
    intent = build_waiting_intent_turn(
        "t", [], state, waited_sec=90.0, judgment="on_track", perceive="ok"
    )
    act = build_waiting_act_turn(
        "t",
        [],
        state,
        waited_sec=90.0,
        judgment="on_track",
        perceive="ok",
        intent="keep waiting",
    )
    assert "<waiting_judge>" in judge
    assert "<waiting_intent>" in intent
    assert "<waiting_act>" in act and "gap" in act
    assert "<wait_cost>" not in judge + intent + act
    for early in (judge, intent):
        assert "<action_space>" not in early
        assert "# MENU" not in early
        assert "keep_waiting | send_message | interrupt | give_up" not in early
    assert "raw wish" in intent
    assert "Your wish may go beyond the current tool" in intent
    assert "this step is only about what you want" in intent
    assert "The next act step will handle any mapping or gap" in intent
    assert "Do NOT optimize" not in intent
    assert "what the framework can do" not in intent
    assert "Examples only" not in intent
    assert "if the help text says so" not in intent
    assert "Read <harness_help>" not in intent
    assert "# MENU" in act
    assert "/status" not in act and "/btw" not in act
    assert "not listed in <harness_help> is just raw text" in act
    assert "report_issue" in act
    for action in ("keep_waiting", "send_message", "interrupt", "give_up"):
        assert action in act
    assert "- interrupt: CONTINUE the session" in act
    assert "- give_up: END the session immediately" in act
    assert "even if you continue the real-world task yourself" in act


def test_issue_and_rating_contracts_are_stage_local() -> None:
    state = init_state(_persona())
    issue = build_issue_turn("do X", ["[+0s] history"], state)
    rating = build_rating_turn("do X", ["[+0s] history"], state)

    assert "<file_issue>" in issue and '"issue"' in issue
    assert "<rate_experience>" not in issue
    assert "1-4" not in issue and "1–4" not in issue
    assert "# MENU" not in issue and "<action_space>" not in issue

    assert "<rate_experience>" in rating and '"score"' in rating and '"reason"' in rating
    assert "1-4" in rating or "1–4" in rating
    assert "<file_issue>" not in rating
    assert "# MENU" not in rating and "<action_space>" not in rating


def test_build_rating_turn_contract() -> None:
    out = build_rating_turn("do X", [], init_state(_persona()))
    assert "1-4" in out or "1–4" in out
    assert '"score"' in out and '"reason"' in out


def test_scripted_client_opening_sends_task() -> None:
    p = _persona()
    state = init_state(p)
    ret = ScriptedPersonaClient().respond(
        build_system(p),
        build_main_act_turn(
            "t",
            [],
            "",
            ["send_message"],
            state,
            verdict="unsure",
            intent="start",
        ),
    )
    assert ret["action"] == "send_message"


def test_scripted_client_rate_experience_returns_score() -> None:
    p = _persona()
    user = build_rating_turn("t", [], init_state(p))
    ret = ScriptedPersonaClient().respond(build_system(p), user)
    assert 1 <= int(ret["score"]) <= 4 and "reason" in ret


def test_scripted_client_exhausted_files_issue() -> None:
    p = _persona(d43=D43Correct.FILE_ISSUE)
    exhausted = State(turn=5, patience=0, trust=p.trust)
    user = build_main_act_turn(
        "t",
        ["prev"],
        "Works now.",
        ["accept", "file_issue"],
        exhausted,
        verdict="failed_blame_harness",
        intent="file an issue",
    )
    ret = ScriptedPersonaClient().respond(build_system(p), user)
    assert ret["action"] == "file_issue"


def test_scripted_client_capability_fork() -> None:
    state_full = init_state(_persona())
    ho = "$ ran it: 2024-07-01 09:00:00+08:00 (no error)\nWorks now."
    space = ["accept", "send_message", "send_message"]

    def _act(d1: D1Eval) -> dict:
        return ScriptedPersonaClient().respond(
            build_system(_persona(d1=d1)),
            build_main_act_turn(
                "t",
                ["p"],
                ho,
                space,
                state_full,
                verdict="unsure",
                intent="decide next",
            ),
        )

    assert _act(D1Eval.EXPERT)["action"] != "accept"  # 专家不轻易接受
    assert _act(D1Eval.SHALLOW)["action"] == "accept"  # 浅层能跑即接受


def test_parse_json_tolerant() -> None:
    assert _parse_json('```json\n{"action": "accept", "message": "ok"}\n```')["action"] == "accept"
    assert _parse_json('noise {"action": "give_up"} trailing')["action"] == "give_up"
    # 完全无法解析 -> 返回安全 dict, 不抛
    safe = _parse_json("not json at all")
    assert safe["action"] == "free"
