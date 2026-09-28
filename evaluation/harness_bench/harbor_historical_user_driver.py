"""Run one O03 historical user session inside a Harbor task container."""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/hse-round")
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

from harness.adapters import FROZEN_V0  # noqa: E402
from harness.session import HarnessSession  # noqa: E402

from auto_designer.user.sim.loop import run_session  # noqa: E402
from auto_designer.user.sim.persona_client import (  # noqa: E402
    AgenticPersonaClient,
    ApiPersonaClient,
)
from auto_designer.user.sim.persona_io import card_to_persona  # noqa: E402
from auto_designer.user.sim.runtime import LocalWorkspaceRuntime  # noqa: E402


class SessionBridge:
    """Expose the backend HarnessInterface surface over the eval JSONL session."""

    def __init__(self, session: HarnessSession) -> None:
        self._session = session
        self.help_text = (
            (ROOT / "harness" / "HELP.md").read_text(encoding="utf-8")
            if (ROOT / "harness" / "HELP.md").is_file()
            else ""
        )

    @property
    def last_progress(self):
        return self._session.last_progress

    def write_message(self, text: str) -> None:
        self._session.write_message(text)

    def poll(self, timeout: float):
        kind, value = self._session.poll(timeout)
        return kind, value.text if kind == "reply" else value

    def try_reply(self):
        value = self._session.try_reply()
        return value.text if value is not None else None

    def interrupt(self):
        value = self._session.interrupt()
        return value.text if value is not None else None

    def shutdown(self):
        self._session.shutdown()


def _jsonable(value):
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value") and isinstance(value.value, (str, int, float, bool)):
        return value.value
    return value


def main() -> int:
    # Public SWE-bench Daytona images expose the checked-out task at /testbed.
    # Keep HSE_REPO_ROOT overridable for the historical local image, but do not
    # require the private nested /workspace/<instance>/repo layout remotely.
    repo = Path(os.environ.get("HSE_REPO_ROOT", "/testbed"))
    if not repo.is_dir():
        raise SystemExit(f"task repository missing: {repo}")
    instruction = (ROOT / "instruction.md").read_text(encoding="utf-8")
    cards = json.loads((ROOT / "persona_library.json").read_text(encoding="utf-8"))
    card = next(item for item in cards if item["id"] == os.environ["HSE_PERSONA_ID"])
    sim_persona = card_to_persona(card)
    work = LocalWorkspaceRuntime(str(repo))
    harness_dir = ROOT / "harness"
    transcript = Path("/logs/agent/harness-transcript.jsonl")
    stderr = Path("/logs/agent/harness-stderr.log")
    obs = Path("/logs/agent/observations")
    obs.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "HARNESS_LLM_MODEL": os.environ["HARNESS_LLM_MODEL"],
        "HARNESS_LLM_BASE_URL": os.environ["HARNESS_LLM_BASE_URL"],
        "HARNESS_LLM_API_KEY": os.environ["HARNESS_LLM_API_KEY"],
        "LLM_MODEL": os.environ["HARNESS_LLM_MODEL"],
        "LLM_BASE_URL": os.environ["HARNESS_LLM_BASE_URL"],
        "LLM_API_KEY": os.environ["HARNESS_LLM_API_KEY"],
        "SANDBOX_WORK_DIR": str(repo),
        "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
        "HARNESS_OBSERVATION_DIR": str(obs),
        "PYTHONUNBUFFERED": "1",
        # Runtime tasks have no package-network dependency.  The frozen task
        # image preinstalls pytest; make any harness-side pip probe fail fast
        # offline instead of hanging on restricted Harbor egress.
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    python_bin = os.environ.get("HSE_PYTHON", "python3")
    session = HarnessSession(
        [python_bin, "-u", str(harness_dir / "entry.py")],
        cwd=harness_dir,
        env=env,
        adapter=FROZEN_V0,
        transcript_path=transcript,
        stderr_path=stderr,
    )
    try:
        api = ApiPersonaClient(model=os.environ["USER_LLM_MODEL"])
        client = AgenticPersonaClient(api.complete)
        client.bind_session(sim_persona, work)
        result = run_session(
            sim_persona,
            client,
            SessionBridge(session),
            instruction,
            deadline_seconds=float(os.environ["HSE_OFFICIAL_AGENT_TIMEOUT_SECONDS"]),
        )
        payload = _jsonable(result)
        payload["task_instance"] = os.environ["HSE_TASK_INSTANCE"]
        payload["persona_id"] = os.environ["HSE_PERSONA_ID"]
        payload["harness_model"] = os.environ["HARNESS_LLM_MODEL"]
        payload["user_model"] = os.environ["USER_LLM_MODEL"]
        payload["workspace"] = {
            "kind": "harbor-task",
            "cwd": str(repo),
            "git_diff_stat": work.run("git diff --stat", timeout=30),
        }
        Path("/eval-out/session.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        patch, digest = work.export_patch()
        Path("/eval-out/model.patch").write_text(patch, encoding="utf-8")
        Path("/eval-out/patch.sha256").write_text(digest + "\n", encoding="utf-8")
        return 0
    finally:
        session.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
