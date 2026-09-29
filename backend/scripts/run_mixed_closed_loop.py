#!/usr/bin/env python3
"""Mixed-task adapter for the existing durable closed-loop orchestrator.

The orchestration, triage, synthesizer, delivery, recovery, and checkpoint
semantics remain in ``run_swebench_closed_loop``.  This adapter only replaces
the SWE-specific task loader/session planner with a frozen mixed-task manifest;
the session runner dispatches ``simulated_user`` and ``direct`` explicitly.
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_swebench_closed_loop as base  # noqa: E402

MANIFEST = Path(os.environ.get("MIXED_TASK_MANIFEST", "")).expanduser().resolve()
if not MANIFEST.is_file():
    raise SystemExit(f"MIXED_TASK_MANIFEST missing: {MANIFEST}")

document = json.loads(MANIFEST.read_text(encoding="utf-8"))
TASKS = list(document.get("tasks") or [])
if not TASKS or len({str(item.get("task_id")) for item in TASKS}) != len(TASKS):
    raise SystemExit("mixed task manifest must contain unique non-empty task_id values")
BY_ID = {str(item["task_id"]): item for item in TASKS}
TASK_IDS = list(BY_ID)
SIM_PERSONAS = [str(item["persona_id"]) for item in TASKS if item.get("persona_id")]
if not SIM_PERSONAS:
    raise SystemExit("mixed task manifest must contain at least one simulated-user persona")
DIRECT_PERSONA = SIM_PERSONAS[0]


def _load_instances() -> dict[str, dict]:
    return {
        task_id: {
            "instance_id": task_id,
            "repo": str(item.get("benchmark") or "mixed"),
            "problem_statement": str(item["description"]),
            "difficulty": str(item.get("benchmark") or "mixed"),
        }
        for task_id, item in BY_ID.items()
    }


def _to_scenario(meta: dict):
    from auto_designer.models import SeedScenario, WorkspaceSpec

    item = BY_ID[str(meta["instance_id"])]
    return SeedScenario(
        description=str(item["description"]),
        workspace=WorkspaceSpec(
            kind="prebuilt",
            params={
                "source": str(item["workspace"]),
                "instance_id": str(item["task_id"]),
                "task_id": str(item["task_id"]),
                "task_key": str(item["task_key"]),
                "benchmark": str(item["benchmark"]),
                "interaction": str(item["interaction"]),
            },
            setup=list(item.get("workspace_setup") or []),
        ),
    )


def _session_picks(rng: random.Random, *, round_index: int) -> list[tuple[str, str]]:
    # Task membership and task/persona assignment are frozen.  Round order is
    # deterministic but may rotate, preserving the existing per-round fan-out.
    offset = round_index % len(TASK_IDS)
    ordered = TASK_IDS[offset:] + TASK_IDS[:offset]
    return [
        (str(BY_ID[task_id].get("persona_id") or DIRECT_PERSONA), task_id) for task_id in ordered
    ]


base._load_instances = _load_instances
base._to_scenario = _to_scenario
base._session_picks = _session_picks
base.INSTANCE_IDS = TASK_IDS
base.FROZEN_INTERACTION_PLAN = None
base.SESSIONS_PER_ROUND = len(TASK_IDS)
os.environ["MIXED_TASK_MANIFEST"] = str(MANIFEST)
os.environ["N_USERS"] = str(len(TASK_IDS))


if __name__ == "__main__":
    raise SystemExit(base.main())
