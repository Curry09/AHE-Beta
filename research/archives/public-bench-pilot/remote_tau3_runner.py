#!/usr/bin/env python3
"""Remote-only runner for one pinned tau3 text task.

This file is uploaded to Daytona.  It intentionally has no local-workspace paths:
the official benchmark, user simulator, harness runtime, and grader all execute in
the sandbox, while only the resulting artifacts are downloaded by the controller.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import traceback
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="airline")
    parser.add_argument("--task-id", default="7")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--output-dir", default="/tmp/eval-output")
    args = parser.parse_args()

    from adapters.harness_v0.tau3 import HarnessV0TauAgent
    from tau2.evaluator import evaluator_nl_assertions
    from tau2.evaluator.evaluator import EvaluationType
    from tau2.orchestrator.orchestrator import Orchestrator
    from tau2.runner import build_environment, build_user, get_tasks, run_simulation

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    model = os.environ["AGENT_LLM"]
    user_model = os.environ.get("USER_SIMULATOR_LLM", model)
    nl_judge_model = os.environ.get("NL_JUDGE_LLM", "openrouter/openai/gpt-4.1")
    # The pinned benchmark hard-codes an OpenAI model. Route the same judge
    # family through the configured OpenRouter credential in sandbox runs.
    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS = nl_judge_model
    tasks = get_tasks(args.domain, task_ids=[args.task_id])
    if len(tasks) != 1:
        raise RuntimeError(f"expected one {args.domain}/{args.task_id} task, got {len(tasks)}")
    task = tasks[0]
    environment = build_environment(args.domain)
    agent = HarnessV0TauAgent(
        tools=environment.get_tools(),
        domain_policy=environment.get_policy(),
        llm=model,
        harness_archive="/opt/pilot/harness-v0.tar.gz",
        harness_python="/opt/harness-venv/bin/python",
        trial_timeout_sec=args.timeout,
    )
    user = build_user("user_simulator", environment, task, llm=user_model)
    orchestrator = Orchestrator(
        domain=args.domain,
        agent=agent,
        user=user,
        environment=environment,
        task=task,
        max_steps=args.max_steps,
        max_errors=5,
        seed=args.seed,
    )
    manifest = {
        "benchmark": "tau3-bench Core/Text",
        "source_commit": "fc0055dc4e0a316c3f83133267fbd6faaa770992",
        "domain": args.domain,
        "task_id": args.task_id,
        "seed": args.seed,
        "max_steps": args.max_steps,
        "agent_timeout_seconds": args.timeout,
        "agent_timeout_source": "fallback_no_official_timeout",
        "agent": os.environ.get("HARNESS_AGENT_LABEL", "harness-v0-cade14d"),
        "model": model,
        "user_simulator_model": user_model,
        "nl_judge_model": nl_judge_model,
        "execution_location": "daytona",
        "user_simulator_location": "daytona",
        "started_at": datetime.now(UTC).isoformat(),
    }

    def preserve_adapter_artifacts() -> None:
        state = agent._active_state
        if state is None:
            return
        workspace = Path(state.workspace_temp.name)
        for source_name in ("harness-transcript.jsonl", "harness-stderr.log"):
            source = workspace / source_name
            if source.is_file():
                shutil.copy2(source, output / source_name)
        (output / "adapter-turns.json").write_text(
            json.dumps(state.transcript, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    try:
        result = run_simulation(orchestrator, evaluation_type=EvaluationType.ALL)
        preserve_adapter_artifacts()
        (output / "simulation.json").write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest.update(
            {
                "preflight_completed": True,
                "adapter_protocol_passed": True,
                "task_reward": result.reward_info.reward,
                "message_count": len(result.messages),
                "task_resolved": result.reward_info.reward == 1,
            }
        )
        return 0
    except Exception as exc:
        preserve_adapter_artifacts()
        manifest.update(
            {
                "preflight_completed": False,
                "adapter_protocol_passed": False,
                "task_resolved": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
        return 1
    finally:
        agent.stop()
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(main())
