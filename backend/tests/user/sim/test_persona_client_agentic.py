"""内层 tool-using agent（AgenticPersonaClient，spec-0008/T4）。

离线覆盖有界 tool-calling 循环：tool_call→observe→最终 contract；blind 退化纯文本；
超步数 / 非法 JSON 兜底；端到端经 run_session + billing-split fixture 不影响外层引擎；
ScriptedPersonaClient 不回归。FakeToolLLM + FakeSandbox 全离线。
"""

from __future__ import annotations

import json

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.dimensions import (
    D1Eval,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.loop import run_session
from auto_designer.user.sim.persona_client import (
    AgenticPersonaClient,
    ScriptedPersonaClient,
)
from auto_designer.user.sim.workspace import materialize


def _persona(d1: D1Eval) -> Persona:
    return finalize_persona(
        Persona(
            persona_id="p",
            d1=d1,
            d2=D2Domain(),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )


class FakeToolLLM:
    """按脚本逐次返回文本；特殊轮（rate/file）自动给合规 JSON；脚本耗尽给默认 accept。"""

    def __init__(self, scripted: list[str] | None = None) -> None:
        self.scripted = list(scripted or [])
        self.calls: list[list[dict]] = []

    def __call__(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        last = messages[-1]["content"]
        if "<rate_experience>" in last:
            return json.dumps({"score": 4, "reason": "ok"})
        if "<file_issue>" in last:
            return json.dumps({"issue": "meh"})
        if self.scripted:
            return self.scripted.pop(0)
        return json.dumps(
            {"perceive": "looks fine", "verdict": "satisfied", "action": "accept", "message": "ok"}
        )


class FakeSandbox:
    def __init__(self, workspace: str | None = None) -> None:
        self.cwd = workspace or "/fake"
        self.runs: list[tuple] = []
        self.cleaned = False

    def run(self, cmd: str, timeout: float = 10.0) -> dict:
        self.runs.append((cmd, timeout))
        return {"ok": True, "stdout": "OK", "stderr": "", "returncode": 0}

    def resolve(self, path: str) -> str:
        return path

    def cleanup(self) -> None:
        self.cleaned = True


# --------------------------------------------------------------------------
# (a) 多步：tool_call -> observe -> 最终 contract
# --------------------------------------------------------------------------
def test_tool_call_then_final_contract() -> None:
    sb = FakeSandbox()
    llm = FakeToolLLM(
        [
            json.dumps({"tool": "run_shell", "args": {"cmd": "python billing/core.py"}}),
            json.dumps(
                {"perceive": "ran it", "verdict": "satisfied", "action": "accept", "message": "ok"}
            ),
        ]
    )
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.COMPETENT), "/ws")

    out = c.respond("SYS", "<task>x</task>")
    assert sb.runs and sb.runs[0][0] == "python billing/core.py"
    assert out["verdict"] == "satisfied" and out["action"] == "accept"
    assert len(llm.calls) == 2 and sb.cleaned


# --------------------------------------------------------------------------
# (b) blind/无工具 -> 纯文本判断，不建 sandbox
# --------------------------------------------------------------------------
def test_blind_degrades_to_text_only() -> None:
    created: list[int] = []
    llm = FakeToolLLM(
        [
            json.dumps(
                {
                    "perceive": "skim",
                    "verdict": "unsure",
                    "action": "give_feedback",
                    "message": "hmm",
                }
            )
        ]
    )

    def factory(workspace=None):
        created.append(1)
        return FakeSandbox(workspace)

    c = AgenticPersonaClient(llm, sandbox_factory=factory)
    c.bind_session(_persona(D1Eval.BLIND), "/ws")

    out = c.respond("SYS", "<task>x</task>")
    assert created == []  # blind 无工具，不进入工具循环
    assert out["action"] == "give_feedback"


# --------------------------------------------------------------------------
# (c) 超 max_inner_steps -> 兜底主观判断
# --------------------------------------------------------------------------
def test_exceed_steps_falls_back() -> None:
    sb = FakeSandbox()
    toolcall = json.dumps({"tool": "run_shell", "args": {"cmd": "echo hi"}})
    llm = FakeToolLLM([toolcall, toolcall, toolcall])  # 恰好用满步数，之后脚本空 -> 默认 accept
    c = AgenticPersonaClient(llm, max_inner_steps=3, sandbox_factory=lambda workspace=None: sb)
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    out = c.respond("SYS", "<task>x</task>")
    assert len(sb.runs) == 3  # 工具调用被步数上限封顶
    assert out["action"] == "accept"  # 兜底返回合法输出


# --------------------------------------------------------------------------
# (d) 非法 JSON -> 安全退化（unsure/free）
# --------------------------------------------------------------------------
def test_invalid_json_degrades_safely() -> None:
    llm = FakeToolLLM(["this is not json at all"])
    c = AgenticPersonaClient(llm, sandbox_factory=lambda workspace=None: FakeSandbox())
    c.bind_session(_persona(D1Eval.EXPERT), "/ws")

    out = c.respond("SYS", "<task>x</task>")
    assert out["action"] == "free" and out["verdict"] == "unsure"


# --------------------------------------------------------------------------
# (e) 端到端：run_session + 真 fixture，外层引擎不受影响
# --------------------------------------------------------------------------
def test_integration_run_session_unaffected() -> None:
    persona = _persona(D1Eval.COMPETENT)
    ws = materialize(WorkspaceSpec(fixture="billing-split"))
    llm = FakeToolLLM()  # 默认每轮给 accept；OPENING 会被投影为 send_task，下一轮 accept 终止
    c = AgenticPersonaClient(llm)  # 真 Sandbox over ws
    c.bind_session(persona, ws)

    res = run_session(persona, c, ScriptedHarness(), "task")
    assert res.turns  # 跑起来了
    assert res.feeling is not None  # 自评产出（外层流程完整）


# --------------------------------------------------------------------------
# (f) ScriptedPersonaClient 不回归
# --------------------------------------------------------------------------
def test_scripted_client_still_works() -> None:
    user = (
        "<harness_output>\n(empty)\n</harness_output>\n\n"
        "<action_space>\n['send_task']\n</action_space>\n\n"
        "<mood>\npatience=full, trust=balanced\n</mood>"
    )
    out = ScriptedPersonaClient().respond("sys", user)
    assert out["action"] == "send_task"
