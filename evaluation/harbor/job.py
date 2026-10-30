"""One frozen direct Harness request, with task-owned resource and grading rules."""

from __future__ import annotations

from pathlib import Path

from evaluation.benchmarks import get_profile
from evaluation.environments.registry import environment_config

from .contracts import PERSISTENCE_GRACE_SECONDS, resolve_contract


def job_config(manifest: dict, trial: dict, jobs_dir: Path, job_name: str) -> dict:
    case = next(
        c
        for c in manifest["cases"]
        if c["benchmark"] == trial["benchmark"] and c["task_id"] == trial["task_id"]
    )
    harness = next(h for h in manifest["harnesses"] if h["id"] == trial["harness"])
    task_root = Path(case["root"])
    contract = resolve_contract(task_root)
    frozen = manifest["resolved_cases"][f"{case['benchmark']}/{case['task_id']}"]
    if (
        frozen["agent_timeout_seconds"] != contract["agent_timeout_seconds"]
        or frozen["resources"] != contract["resources"]
    ):
        raise ValueError("Task execution contract drifted after planning")
    profile = get_profile(case["benchmark"])
    settings = manifest.get("metadata", {}).get("evaluation_runtime")
    if harness.get("kind") == "native":
        options = settings["actor"]
        simulated = trial.get("interaction") == "simulated_user"
        agent = {
            "import_path": "evaluation.harness.native_sim_agent:"
            + ("SimulatedUserNativeAgent" if simulated else "DirectNativeAgent"),
            "model_name": manifest["harness_model"],
            "override_timeout_sec": contract["agent_timeout_seconds"] + PERSISTENCE_GRACE_SECONDS,
            "override_setup_timeout_sec": 1200,
            "kwargs": {
                "native_kind": harness["agent"],
                "native_version": harness["version"],
                "native_kwargs": {"reasoning_effort": options["reasoning_effort"]},
                "process_runtime": harness["process_runtime"],
                "interaction": manifest["interactions"][0],
                "request_timeout_sec": contract["agent_timeout_seconds"],
                "llm_options": options,
            },
            "env": (
                {
                    "ANTHROPIC_API_KEY": "${CLAUDE_ACTOR_API_KEY}",
                    "ANTHROPIC_BASE_URL": "${CLAUDE_LLM_BASE_URL}",
                }
                if harness["agent"] == "claude-code"
                else {"OPENAI_API_KEY": "${LLM_API_KEY}", "OPENAI_API_BASE": "${LLM_BASE_URL}"}
            ),
        }
    elif harness.get("kind") == "harbor":
        agent = {
            "import_path": "evaluation.harbor.agents:ClaudeCodeAgent",
            "model_name": manifest["harness_model"].removeprefix("anthropic/"),
            "kwargs": {
                "version": harness["version"],
                "process_runtime": harness["process_runtime"],
                **harness["kwargs"],
            },
            "env": {
                "ANTHROPIC_API_KEY": "${LLM_API_KEY}",
                "ANTHROPIC_BASE_URL": "${CLAUDE_LLM_BASE_URL}",
            },
        }
    else:
        agent = frozen_agent(harness, manifest["harness_model"], contract)
        if settings:
            agent["kwargs"]["llm_options"] = settings["actor"]
            agent["kwargs"]["time_adaptation"] = trial.get("time_adaptation", False)
        workdir_override = (
            manifest.get("metadata", {}).get("workdir_by_task", {}).get(case["task_id"])
        )
        if workdir_override:
            agent["kwargs"]["workdir"] = workdir_override
        if trial.get("interaction") == "simulated_user":
            agent["import_path"] = "evaluation.harness.sim_agent:SimulatedUserHarnessAgent"
            agent["kwargs"]["interaction"] = manifest["interactions"][0]
            agent["kwargs"]["time_adaptation"] = trial["time_adaptation"]
    verifier_credentials = {
        "ANTHROPIC_API_KEY": "${JUDGE_ANTHROPIC_API_KEY}",
        "ANTHROPIC_BASE_URL": "${JUDGE_ANTHROPIC_BASE_URL}",
    }
    if (
        case["task_id"].startswith(("algotune-", "gso-"))
        and manifest.get("metadata", {}).get("anti_cheat_review") == "deferred_by_user"
    ):
        verifier_credentials = {"ANTHROPIC_API_KEY": "", "ANTHROPIC_BASE_URL": ""}
    result = {
        "job_name": job_name,
        "jobs_dir": str(jobs_dir),
        "n_attempts": 1,
        "n_concurrent_trials": 1,
        "timeout_multiplier": 1.0,
        "retry": {"max_retries": 0},
        "environment": environment_config(manifest["provider"], case["benchmark"]),
        "agents": [agent],
        "verifier": {
            "disable": False,
            "env": {
                **verifier_credentials,
                **(profile.verifier_env(case["task_id"]) if profile else {}),
            },
        },
        "tasks": [{"path": str(task_root)}],
    }
    if settings:
        result["evaluation_runtime"] = settings
    return result


def frozen_agent(harness: dict, model: str, contract: dict) -> dict:
    budget_key = str(int(contract["agent_timeout_seconds"]))
    materials = (
        harness["timeout_materials"][budget_key]
        if "timeout_materials" in harness
        else {"archive": harness["archive"], "sha256": harness["sha256"]}
    )
    agent_kwargs = {
        "archive": materials["archive"],
        "archive_sha256": materials["sha256"],
        "revision": harness["revision"],
        **harness["runtime"],
        "workdir": "auto",
        "request_timeout_sec": contract["agent_timeout_seconds"],
        "call_timeout_sec": harness.get("internal_call_timeout_sec"),
    }
    return {
        "import_path": "evaluation.harness.agent:FrozenHarnessAgent",
        "model_name": model,
        "kwargs": agent_kwargs,
        "override_timeout_sec": contract["agent_timeout_seconds"] + PERSISTENCE_GRACE_SECONDS,
        "override_setup_timeout_sec": 1200,
        "env": {
            "HARNESS_LLM_API_KEY": "${LLM_API_KEY}",
            "HARNESS_LLM_BASE_URL": "${LLM_BASE_URL}",
        },
    }
