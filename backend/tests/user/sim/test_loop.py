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


class _RecordingClient(_StubClient):
    """记录每轮收到的 user 提示, 用于断言喂给 LLM 的内容(感知是否原样)。"""

    def __init__(self, actions: list[str], verdict: str = "unsure") -> None:
        super().__init__(actions, verdict=verdict)
        self.seen: list[str] = []

    def respond(self, system: str, user: str) -> dict:
        if "<rate_experience>" not in user:
            self.seen.append(user)
        return super().respond(system, user)


def test_harness_text_fed_raw_without_perception_filter() -> None:
    # 低能力档(原型会用 perceive_filter 抹掉源码行)；删除过滤后, 源码应原样喂入 LLM。
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _RecordingClient(["send_task", "give_feedback", "accept"], verdict="unsure")
    run_session(p, client, ScriptedHarness(), TASK)
    after_harness = client.seen[1]  # turn1: 已看到 harness 首轮(含缩进源码)
    assert "pytz.localize_safe(dt, tz)" in after_harness  # 源码原样可见
    assert "you don't read the diff line by line" not in after_harness  # 无过滤占位串


def test_verify_self_injects_raw_observation() -> None:
    # verify_self 注入「原始」最近 harness 文本, 不再按子串伪造「崩了/没报错」。
    p = _persona(D1Eval.EXPERT, D43Correct.FEEDBACK)
    client = _RecordingClient(["send_task", "verify_self", "accept"], verdict="unsure")
    run_session(p, client, ScriptedHarness(), TASK)
    after_verify = client.seen[2]  # turn2: verify_self 注入的私有观察已进 user
    assert "<self_observation>" in after_verify
    assert "pytz.localize_safe(dt, tz)" in after_verify  # 原始观察(含代码)
    assert "I ran it once" not in after_verify  # 无伪造串


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


def test_on_progress_pushes_pending_harness_reply_immediately() -> None:
    """harness 回复到手即推观测层：send 返回后、persona 下一轮响应前，多触发一次
    on_progress 且快照悬挂该回复；下一条 TurnLog 落日志时悬挂清空（回复已随日志携带）。"""
    p = _persona(D1Eval.SHALLOW, D43Correct.FEEDBACK)
    client = _StubClient(["send_task", "accept"], verdict="satisfied")
    snaps: list[tuple[int, str | None]] = []
    run_session(
        p,
        client,
        ScriptedHarness(),
        TASK,
        on_progress=lambda res: snaps.append((len(res.turns), res.pending_harness_output)),
    )
    # turn1 落日志(无悬挂) → harness 回复到手(悬挂推送) → turn2 落日志(悬挂已清)
    assert snaps[0] == (1, None)
    assert snaps[1][0] == 1 and snaps[1][1]
    assert snaps[2] == (2, None)


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
        ScriptedPersonaClient(),
        ScriptedHarness(),
        TASK,
    )
    expert = run_session(
        _persona(D1Eval.EXPERT, D43Correct.FILE_ISSUE, "P-expert"),
        ScriptedPersonaClient(),
        ScriptedHarness(),
        TASK,
    )
    assert shallow.end_reason == "accepted"  # 低能力跑通即接受(高体感)
    assert shallow.feeling.score >= 3
    assert expert.end_reason == "issue_filed"  # 高能力逼证据至耗尽 -> file_issue(低体感)
    assert expert.feeling.score <= 2
    assert expert.issue_artifact is not None


def test_give_up_also_leaves_exit_issue() -> None:
    # 走人=弃坑也留一条"为什么把我逼走"的问卷式 issue：把"提 issue"从特定动作解耦,
    # 否则 FEEDBACK/GIVE_UP 型气跑后 backlog 收不到任何信号。end_reason 仍是 abandoned。
    p = _persona(D1Eval.EXPERT, D43Correct.GIVE_UP)
    # EXPERT 连坐实 harness 失败 2 次触发诊断门, give_up 解锁; 第 3 轮走人。
    client = _StubClient(["send_task", "give_feedback", "give_up"], verdict="failed_blame_harness")
    res = run_session(p, client, ScriptedHarness(), TASK)
    assert res.end_reason == "abandoned"  # 机制不变: 仍是放弃
    assert res.issue_artifact is not None  # 但额外留下退出 issue


def test_issue_artifact_is_user_voice_with_metadata_footer() -> None:
    expert = run_session(
        _persona(D1Eval.EXPERT, D43Correct.FILE_ISSUE, "P-expert"),
        ScriptedPersonaClient(),
        ScriptedHarness(),
        TASK,
    )
    art = expert.issue_artifact
    assert art is not None
    # 不再套第三人称模板外壳
    assert "### What the user reported" not in art
    assert "Issue filed by simulated user" not in art
    # 正文在前 = persona file_issue 当轮第一人称原话(非空)，与机器脚注用 --- 分隔
    body, sep, footer = art.partition("\n---\n")
    assert sep  # 有分隔线
    assert body.strip()  # 用户原话非空
    # 脚注是机器自动采集的元信息(含能力档/纠错风格)，供开发者分流
    assert "auto-collected" in footer
    assert "expert/file_issue" in footer
