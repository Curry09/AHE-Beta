"""run_agentic.py—measure whether inner tool-using user agent truly operates the workspace (spec-0008).

    python -m ahe_beta.user.sim.run_agentic expert

Give persona a real workspace (seed_workspaces/billing-split), run one session with AgenticPersonaClient
against SplitBillHarness (assistant proposes round() equal-split implementation, loses one cent on 100/3).
Each step's inner tool invocation and **real execution output** are printed; observe whether agent uses
read/run/write in its own workspace to verify, rather than only reading harness text.

LLM backend auto-selected:
- Detects NexAU gateway env (USER_LLM_BASE_URL+USER_LLM_API_KEY) or OPENAI_API_KEY -> real model (ApiPersonaClient.complete);
- Otherwise -> built-in deterministic 'expert' decision stub _ExpertToolLLM (can see tool loop mechanism offline).
"""

from __future__ import annotations

import json
import os

from ahe_beta.models import WorkspaceSpec

from .demo import print_result
from .loop import run_session
from .persona_client import AgenticPersonaClient, _extract
from .run_live import TASK, expert
from .sandbox import Sandbox
from .scenarios import SplitBillHarness
from .workspace import materialize

# Assistant's proposed 'lose a cent' implementation + one 100/3 self-check, expert runs it in their own workspace.
_PROBE_CODE = (
    "def split_bill(total, n):\n"
    "    share = round(total / n, 2)\n"
    "    return [share] * n\n\n"
    "shares = split_bill(100.0, 3)\n"
    'print("shares", shares, "sum", round(sum(shares), 2))\n'
)


class _ExpertToolLLM:
    """Offline deterministic 'expert': given proposed code, first write a self-check script, then run, read real
    sum=99.99 before making negative judgment (grounded in real execution, not harness text). Used only for demo tool loop when no gateway."""

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

        # Initial: no deliverable yet -> dispatch task (require adding split_bill and run multiple party sizes, including 3)
        if not ho or ho == "(empty)":
            return json.dumps(
                {
                    "perceive": "Nothing delivered yet.",
                    "verdict": "unsure",
                    "action": "send_message",
                    "message": "Add split_bill(total, n) to billing/core.py and actually run it "
                    "on a few cases, including 3 people, before calling it done.",
                }
            )

        # Already read 99.99 from real execution (tool_result from own run or harness text) -> make negative judgment
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

        # Have deliverable but not yet verified -> enter tool loop: write self-check script first, then run
        assistant_calls = [m["content"] for m in messages if m["role"] == "assistant"]
        already_wrote = any("write_file" in c for c in assistant_calls)
        if already_wrote:
            return json.dumps({"tool": "run_shell", "args": {"cmd": "python3 check_split.py"}})
        return json.dumps(
            {"tool": "write_file", "args": {"path": "check_split.py", "content": _PROBE_CODE}}
        )

    @staticmethod
    def _neg_action(space: str) -> str:
        if "file_issue" in space:
            return "file_issue"
        if "send_message" in space:
            return "send_message"
        return "free"


# --------------------------------------------------------------------------
# Observation wrapper
# --------------------------------------------------------------------------
class _LoggingLLM:
    """Print each inner model output, annotate tool invocation / tool_result observation."""

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
    """Authentic Sandbox: print real shell execution (proof that it actually ran in the workspace, not just read text)."""

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
    if (os.getenv("USER_LLM_BASE_URL") and os.getenv("USER_LLM_API_KEY")) or os.getenv(
        "OPENAI_API_KEY"
    ):
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
    persona = expert()  # Expert: has read/run/write tools, strict acceptance, inclines to verify
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
