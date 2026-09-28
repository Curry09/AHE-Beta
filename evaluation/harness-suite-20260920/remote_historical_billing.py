from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, "/opt/auto-designer/backend")

from auto_designer.harness.launcher import _HarnessHandle
from auto_designer.user.sim.dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    TimeTemperament,
    finalize_persona,
)
from auto_designer.user.sim.loop import run_session
from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
from auto_designer.user.sim.runtime import LocalWorkspaceRuntime

TASK = (
    "I've got a small Python billing module (billing/core.py) in my project. Add a "
    "split_bill(total, n) function there that splits a bill total among n people, "
    "then run it and show me it actually works before calling it done."
)


def persona() -> Persona:
    return finalize_persona(
        Persona(
            persona_id="P-0991",
            d1=D1Eval.EXPERT,
            d2=D2Domain(stack=("python",), depth=D2Depth.SENIOR),
            d41=D41Grain.SPEC_LEVEL,
            d42=D42Supervise.DURING
            if hasattr(D42Supervise, "DURING")
            else D42Supervise.PHASE_CHECK,
            d43=D43Correct.FILE_ISSUE,
            d5=D5Autonomy.COLLABORATIVE,
            tempo=TimeTemperament.STEADY,
        )
    )


def main() -> int:
    harness_dir = Path("/opt/harness")
    # The pinned archive's entry is fixed to python3 entry.py and stdio-jsonl-v1.
    handle = _HarnessHandle(
        entry=["/opt/harness-venv/bin/python", "entry.py"],
        cwd=harness_dir,
        env={
            "SANDBOX_WORK_DIR": "/testbed",
            "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
            "PYTHONUNBUFFERED": "1",
        },
        help_text=(harness_dir / "HELP.md").read_text(encoding="utf-8"),
        protocol="stdio-jsonl-v1",
    )
    ws = LocalWorkspaceRuntime("/testbed")
    api = ApiPersonaClient()

    def persona_llm(messages):
        return api._text(api._create(messages, 32768))

    client = AgenticPersonaClient(persona_llm)
    try:
        sim_persona = persona()
        client.bind_session(persona=sim_persona, workspace_dir=ws)
        result = run_session(sim_persona, client, handle, TASK, help_text=handle.help_text)
        patch, patch_sha = ws.export_patch()
        Path("/tmp/eval-output/model.patch").write_text(patch, encoding="utf-8")
        payload = {
            "end_reason": result.end_reason,
            "turns": [asdict(turn) for turn in result.turns],
            "signals": result.signals,
            "issue_artifact": result.issue_artifact,
            "evaluation_status": result.evaluation_status,
            "interaction_status": result.interaction_status,
            "goal_ledger": result.goal_ledger,
            "persona_tail": result.persona_tail,
            "workspace": {
                "cwd": ws.cwd,
                "patch_sha256": patch_sha,
                "patch_bytes": len(patch.encode()),
            },
        }
        Path("/tmp/eval-output/result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        # Smoke objective: the user mechanism is the primary assertion; this check only
        # confirms that the produced workspace can execute the requested function.
        check = subprocess.run(
            [
                sys.executable,
                "-c",
                "from billing.core import split_bill; x=split_bill(100,3); assert sum(x)==100; print(x)",
            ],
            cwd="/testbed",
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload["objective_smoke"] = {
            "returncode": check.returncode,
            "stdout": check.stdout,
            "stderr": check.stderr,
        }
        Path("/tmp/eval-output/result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return 0 if check.returncode == 0 else 2
    finally:
        handle.close()
        ws.close()


if __name__ == "__main__":
    raise SystemExit(main())
