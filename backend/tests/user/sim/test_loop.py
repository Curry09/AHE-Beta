"""spec-0005/T5：会话主循环引擎（纯主观、两路体感、能力分叉）。"""

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
from auto_designer.user.sim.feeling import FeelingScore
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.loop import MAX_TURNS, SessionResult, run_session
from auto_designer.user.sim.persona_client import ScriptedPersonaClient


def _persona(d1: D1Eval, d43: D43Correct, pid: str = "P") -> Persona:
    return finalize_persona(
        Persona(
            persona_id=pid,
            d1=d1,
            d2=D2Domain(stack=("python",), depth=D2Depth.PROFICIENT),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=d43,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


TASK = "Add to_user_tz(dt, tz_name); handle DST. We use Asia/Shanghai and America/New_York."


class _StubClient:
    """受控 client：按脚本逐轮出动作；<rate_experience> 返回固定 rating。"""

    def __init__(self, actions: list[str], verdict: str = "unsure", rating: dict | None = None):
        self._actions = actions
        self._i = 0
        self._verdict = verdict
        self._rating = rating if rating is not None else {"score": 3, "reason": "ok"}

    def respond(self, system: str, user: str) -> dict:
        if "<rate_experience>" in user:
            return self._rating
        a = self._actions[self._i] if self._i < len(self._actions) else self._actions[-1]
        self._i += 1
        return {"perceive": "", "verdict": self._verdict, "action": a, "message": "x"}


def test_runs_one_session_returns_result() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    res = run_session(p, ScriptedPersonaClient(), ScriptedHarness(), TASK)
    assert isinstance(res, SessionResult)
    assert res.persona_id == "P"
    assert res.turns and res.turns[0].action == "send_task"


def test_self_terminates_at_chosen_turn() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _StubClient(["send_task", "accept"], verdict="satisfied")
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.end_reason == "accepted"
    assert len(res.turns) == 2


def test_max_turns_cutoff() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _StubClient(["send_task", "give_feedback"], verdict="unsure")  # 永不终止
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.end_reason == "max_turns"
    assert len(res.turns) == MAX_TURNS


def test_two_track_feeling_falls_back_to_derived() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _StubClient(["send_task", "accept"], verdict="satisfied", rating={"oops": 1})
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert isinstance(res.feeling, FeelingScore) and isinstance(res.feeling_derived, FeelingScore)
    assert res.feeling == res.feeling_derived  # LLM 解析失败 -> 回落派生分


def test_pure_subjective_turnlog_has_no_objective_fields() -> None:
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    res = run_session(p, ScriptedPersonaClient(), ScriptedHarness(), TASK)
    t = res.turns[0]
    for attr in ("objective_failed", "control_fatal", "gap"):
        assert not hasattr(t, attr)


def test_capability_fork() -> None:
    shallow = run_session(
        _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK, "P-shallow"),
        ScriptedPersonaClient(), ScriptedHarness(), TASK,
    )
    expert = run_session(
        _persona(D1Eval.EXPERT, D43Correct.FILE_ISSUE, "P-expert"),
        ScriptedPersonaClient(), ScriptedHarness(), TASK,
    )
    assert shallow.end_reason == "accepted"      # 低能力跑通即接受(高体感)
    assert shallow.feeling.score >= 3
    assert expert.end_reason == "issue_filed"     # 高能力逼证据至耗尽 -> file_issue(低体感)
    assert expert.feeling.score <= 2
    assert expert.issue_artifact is not None
