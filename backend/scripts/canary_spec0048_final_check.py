#!/usr/bin/env python3
"""Optional live USER_LLM_* canary for Spec 0048; never prints credentials."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

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
from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
from auto_designer.user.sim.prompt import (
    build_main_act_turn,
    build_main_final_check_turn,
    build_main_reintent_turn,
    build_main_rejudge_turn,
    build_system,
)
from auto_designer.user.sim.state import init_state


def _source_pin() -> str:
    configured = os.getenv("SPEC0048_SOURCE_PIN")
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    persona = finalize_persona(
        Persona(
            persona_id="spec0048-live-canary",
            d1=D1Eval.COMPETENT,
            d2=D2Domain(stack=("python",)),
            d41=D41Grain.HALF_CONTEXT,
            d42=D42Supervise.PHASE_CHECK,
            d43=D43Correct.FEEDBACK,
            d5=D5Autonomy.COLLABORATIVE,
        )
    )
    state = init_state(persona)
    system = build_system(persona)
    task = "Verify a delivered Python value before choosing the next external action."
    output = "I implemented answer.py and the value should be 42."
    api = ApiPersonaClient()
    max_tokens = int(os.getenv("SPEC0048_CANARY_MAX_TOKENS", "2048"))

    def complete(messages: list[dict]) -> str:
        return api.complete(messages, max_tokens=max_tokens)

    with tempfile.TemporaryDirectory(prefix="spec0048-canary-") as workspace:
        Path(workspace, "answer.py").write_text("ANSWER = 42\n", encoding="utf-8")
        client = AgenticPersonaClient(complete, max_inner_steps=8)
        client.bind_session(persona, workspace)
        checked = client.respond(
            system,
            build_main_final_check_turn(
                task,
                [],
                output,
                state,
                verdict="unsure",
                perceive="The delivery claims the requested value exists.",
                intent="Verify answer.py once, then decide.",
                check_goal="Read answer.py and confirm whether ANSWER equals 42.",
            ),
        )
        rejudged = client.respond(
            system,
            build_main_rejudge_turn(
                task,
                [],
                output,
                state,
                prior_verdict="unsure",
                prior_perceive="The delivery claims the requested value exists.",
                check_status=str(checked["check_status"]),
                check_evidence=str(checked["perceive"]),
            ),
        )
        reintent = client.respond(
            system,
            build_main_reintent_turn(
                task,
                [],
                output,
                state,
                verdict=str(rejudged["verdict"]),
                perceive=str(rejudged["perceive"]),
            ),
        )
        acted = client.respond(
            system,
            build_main_act_turn(
                task,
                [],
                output,
                ["accept", "accept_with_reservations", "give_up", "send_message"],
                state,
                verdict=str(rejudged["verdict"]),
                perceive=str(rejudged["perceive"]),
                intent=str(reintent["intent"]),
            ),
        )

    print(
        json.dumps(
            {
                "schema": "spec0048-live-canary/v1",
                "source_pin": _source_pin(),
                "model_pin": api.model,
                "max_tokens_per_call": max_tokens,
                "check_status": checked["check_status"],
                "verdict": rejudged["verdict"],
                "needs_final_check_after_rejudge": reintent["needs_final_check"],
                "action": acted["action"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
