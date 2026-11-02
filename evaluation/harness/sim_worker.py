# ruff: noqa: E402
"""Isolated host-side adapter for the existing persona state machine.

Only public task text, final replies and the candidate's public diff cross IPC.
No verifier results, hidden tests, old runs, or Harness internals enter it.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "user_engine"))

from ahe_beta.usage import bind_usage_context
from ahe_beta.user.sim import loop as sim_loop
from ahe_beta.user.sim.dimensions import (
    D1Eval,
    D2Domain,
    D3Accept,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from ahe_beta.user.sim.loop import run_session

_original_space = sim_loop.derive_action_space


def _reply_only_space(*args, **kwargs):
    return [a for a in _original_space(*args, **kwargs) if a not in {"interrupt", "keep_waiting"}]


from ahe_beta.user.sim import persona_client as _persona_module
from ahe_beta.user.sim.persona_client import ApiPersonaClient

_persona_module.PERSONA_MAX_OUTPUT_TOKENS = int(
    os.environ.get("USER_LLM_MAX_OUTPUT_TOKENS", "65536")
)


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


class IPCClient:
    last_request_status = ""
    last_steps = []

    def send(self, text):
        emit({"type": "request", "text": text})
        reply = json.loads(sys.stdin.readline())
        self.last_request_status = (
            "timeout" if reply.get("timed_out") else "crashed" if reply.get("failed") else ""
        )
        return reply["text"]


class ExactOpeningClient(ApiPersonaClient):
    """Keep the benchmark's first request identical across treatments."""

    def __init__(self, task):
        super().__init__(model=os.environ["USER_LLM_MODEL"], temperature=0.8)
        self.task = task
        self.opening = True

    def respond(self, system, user):
        result = super().respond(system, user)
        if self.opening and "<main_act>" in user:
            # Preserve judge/intent/goal transactions; pin only the spoken initial request.
            result = {**result, "action": "send_message", "message": self.task}
            self.opening = False
            emit({"type": "opening_pinned", "message": self.task})
        return result


def main():
    sim_loop.derive_action_space = _reply_only_space
    if __package__:
        from .fulltrace import install
    else:
        from fulltrace import install
    install("simulated_user", os.environ["FULL_TRACE_DIR"])
    config = json.loads(sys.stdin.readline())
    task = config["task"]
    persona = finalize_persona(
        Persona(
            persona_id="python-competent-feedback-v1",
            d1=D1Eval.COMPETENT,
            d2=D2Domain(),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
            d3=D3Accept.FUNCTIONAL,
        )
    )

    def freeze():
        emit({"type": "freeze"})
        json.loads(sys.stdin.readline())

    emit({"type": "persona", "persona": asdict(persona)})
    with bind_usage_context(
        role="user", persona_id=persona.persona_id, interaction_mode="simulated_user"
    ):
        result = run_session(
            persona,
            ExactOpeningClient(task),
            IPCClient(),
            task,
            help_text=(
                "The first request must reproduce the public task exactly. Keep the original task and scope fixed. "
                "You receive completed assistant replies and a read-only public git diff. "
                "You cannot execute commands or independently verify claimed test results. "
                "Do not invent observations, hidden tests, or new requirements. "
                "You may provide feedback, ask questions, accept, or give up only after a completed reply. "
                "A shared wall-clock deadline includes your deliberation and all assistant turns."
            ),
            on_progress=lambda result: emit({"type": "progress", "result": asdict(result)}),
            deadline_seconds=config["remaining_seconds"],
            before_terminal_review=freeze,
            terminal_review=False,
        )
    emit({"type": "result", "result": asdict(result)})


if __name__ == "__main__":
    main()
