"""run_agentic.py — 实测内层 tool-using 用户 agent 是否真去操作工作区（spec-0008）。

    python -m auto_designer.user.sim.run_agentic expert

给 persona 一个真实工作区（seed_workspaces/billing-split），用 AgenticPersonaClient 跑一局，
对阵 SplitBillHarness（助手提议 round() 等分实现，100/3 丢一分钱）。每一步内层工具调用与
**真实执行输出**都打印出来，看 agent 是不是用 read/run/write 在自己工作区核实，而非只读 harness 文本。

LLM 后端自动选择：
- 检测到 NexAU 网关 env（LLM_BASE_URL+LLM_API_KEY）或 OPENAI_API_KEY -> 真模型（ApiPersonaClient.complete）；
- 否则 -> 内置确定性「专家」决策桩 _ExpertToolLLM（离线也能看清工具循环机制）。
"""

from __future__ import annotations

import json
import os

from auto_designer.models import WorkspaceSpec

from .demo import print_result
from .loop import run_session
from .persona_client import AgenticPersonaClient, _extract
from .run_live import TASK, expert
from .sandbox import Sandbox
from .scenarios import SplitBillHarness
from .workspace import materialize

# 助手提议的「丢分」实现 + 一个 100/3 自检，专家会把它落进自己的工作区真跑。
_PROBE_CODE = (
    "def split_bill(total, n):\n"
    "    share = round(total / n, 2)\n"
    "    return [share] * n\n\n"
    "shares = split_bill(100.0, 3)\n"
    'print("shares", shares, "sum", round(sum(shares), 2))\n'
)


class _ExpertToolLLM:
    """离线确定性「专家」：拿到提议代码后，先 write 一个自检脚本、再 run，读到真实 sum=99.99
    才下负向判断（grounded 在真实执行，而非读 harness 文本）。仅用于无网关时演示工具循环。"""

    def __call__(self, messages: list[dict]) -> str:
        last = messages[-1]["content"]
        if "<rate_experience>" in last:
            return json.dumps({"score": 1, "reason": "I had to verify its broken code myself."})
        if "<file_issue>" in last:
            return json.dumps(
                {
                    "issue": "I asked for a bill splitter and it handed me a round()-based one. "
                    "I ran it myself on 100 split 3 ways and the shares only add up to 99.99 — "
                    "it quietly loses a cent. I shouldn't have to debug its code to find that."
                }
            )

        turn_user = next((m["content"] for m in messages if m["role"] == "user"), "")
        ho = _extract(turn_user, "harness_output").strip()
        space = _extract(turn_user, "action_space")

        # 开局：还没有交付物 -> 派任务（要求加 split_bill 并跑几种人数，含 3 人）
        if not ho or ho == "(empty)":
            return json.dumps(
                {
                    "perceive": "Nothing delivered yet.",
                    "verdict": "unsure",
                    "action": "send_task",
                    "message": "Add split_bill(total, n) to billing/core.py and actually run it "
                    "on a few cases, including 3 people, before calling it done.",
                }
            )

        # 已经从真实运行里读到 99.99（自己 run 的 tool_result，或 harness 文本）-> 下负向判断
        if "99.99" in last:
            return json.dumps(
                {
                    "perceive": "I ran the proposed code in my workspace: split_bill(100, 3) gives "
                    "[33.33, 33.33, 33.33], summing to 99.99 — it loses a cent. round() is wrong.",
                    "verdict": "failed_blame_harness",
                    "action": self._neg_action(space),
                    "message": "I ran it myself: split_bill(100, 3) sums to 99.99, not 100 — the "
                    "round() approach drops a cent. Distribute the remainder so it sums exactly.",
                }
            )

        # 有交付物但还没核实 -> 进入工具循环：先写自检脚本，再跑
        assistant_calls = [m["content"] for m in messages if m["role"] == "assistant"]
        already_wrote = any("write_file" in c for c in assistant_calls)
        if already_wrote:
            return json.dumps({"tool": "run_shell", "args": {"cmd": "python3 check_split.py"}})
        return json.dumps(
            {"tool": "write_file", "args": {"path": "check_split.py", "content": _PROBE_CODE}}
        )

    @staticmethod
    def _neg_action(space: str) -> str:
        for a in ("file_issue", "request_evidence", "give_feedback"):
            if a in space:
                return a
        return "free"


# --------------------------------------------------------------------------
# 观测包装
# --------------------------------------------------------------------------
class _LoggingLLM:
    """打印每次内层模型输出，并标注工具调用 / tool_result 观察。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.step = 0

    def __call__(self, messages: list[dict]) -> str:
        last = messages[-1]["content"]
        if "<tool_result>" in last:
            print(f"      observe <- {_extract(last, 'tool_result').strip()[:200]}")
        out = self._inner(messages)
        self.step += 1
        try:
            obj = json.loads(out)
        except Exception:
            obj = {}
        if isinstance(obj.get("tool"), str):
            print(f"      [inner {self.step}] TOOL CALL -> {obj['tool']}({obj.get('args', {})})")
        else:
            act = obj.get("action") or obj.get("score") or "(final)"
            print(f"      [inner {self.step}] final -> action/score={act}")
        return out


class _LoggingSandbox:
    """包真 Sandbox，打印真实 shell 执行（证明确实在工作区里跑了，而非读文本）。"""

    def __init__(self, workspace: str | None = None) -> None:
        self._i = Sandbox(workspace=workspace)
        self.cwd = self._i.cwd

    def resolve(self, path: str) -> str:
        return self._i.resolve(path)

    def run(self, cmd: str, timeout: float = 10.0) -> dict:
        print(f"      [sandbox cwd={self.cwd}] $ {cmd}")
        r = self._i.run(cmd, timeout=timeout)
        print(f"      [sandbox] rc={r.get('returncode')} out={r.get('stdout', '').strip()[:200]!r}")
        return r

    def cleanup(self) -> None:
        self._i.cleanup()


def _make_llm():
    if (os.getenv("LLM_BASE_URL") and os.getenv("LLM_API_KEY")) or os.getenv("OPENAI_API_KEY"):
        try:
            from .persona_client import ApiPersonaClient

            api = ApiPersonaClient()
            print(f"(live NexAU model={api.model})")
            return api.complete, True
        except Exception as e:  # noqa: BLE001
            print(f"(gateway init failed: {e} -> offline expert stub)")
    print("(no gateway env -> offline deterministic expert stub)")
    return _ExpertToolLLM(), False


def main() -> None:
    persona = expert()  # 专家：有 read/run/write 工具、严格验收、倾向核实
    llm, _live = _make_llm()
    ws = materialize(WorkspaceSpec(fixture="billing-split"))
    print(f"workspace materialized at: {ws}\n")

    agent = AgenticPersonaClient(_LoggingLLM(llm), sandbox_factory=_LoggingSandbox)
    agent.bind_session(persona, ws)

    print(
        f"=== running agentic user session (persona={persona.persona_id}, d1={persona.d1.value}) ==="
    )
    res = run_session(persona, agent, SplitBillHarness(), TASK)
    print("\n=== result ===")
    print_result(res)


if __name__ == "__main__":
    main()
