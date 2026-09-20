"""Harbor agent adapter for the frozen harness-v0 archive.

This adapter deliberately keeps Harbor as the outer lifecycle runner while
starting the existing stdio harness inside the task environment. It is used
for integration smoke tests and the formal harness-v0 benchmark path; it does
not substitute Harbor's generic Claude Code installer.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from harbor.agents.base import AgentContext, BaseAgent
from harbor.environments.base import BaseEnvironment


ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = ROOT / "evaluation/public-bench-pilot/adapters/harness_v0"
DRIVER = Path(__file__).with_name("harbor_v0_driver.py")
HARNESS_ARCHIVE = Path(
    "/root/src/auto-designer-experiment-artifacts/harness-v0-cade14d.tar.gz"
)
NEXAU_WHEEL = Path("/tmp/nexau-wheel/nexau-0.4.1-py3-none-any.whl")


class HarnessV0Agent(BaseAgent):
    """Run the frozen harness-v0 through Harbor's agent interface."""

    @staticmethod
    def name() -> str:
        return "harness-v0"

    def version(self) -> str:
        return "baseline-v0-cade14d"

    @classmethod
    def preflight(cls, kwargs=None, env=None) -> None:
        if not HARNESS_ARCHIVE.is_file():
            raise FileNotFoundError(f"missing frozen harness archive: {HARNESS_ARCHIVE}")
        if not NEXAU_WHEEL.is_file():
            raise FileNotFoundError(f"missing pinned NexAU wheel: {NEXAU_WHEEL}")

    async def setup(self, environment: BaseEnvironment) -> None:
        await environment.exec(
            "mkdir -p /opt/hse-v0/harness /logs/agent",
            timeout_sec=30,
            user="root",
        )
        await environment.upload_file(HARNESS_ARCHIVE, "/tmp/harness-v0.tar.gz")
        await environment.upload_file(NEXAU_WHEEL, "/tmp/nexau-0.4.1-py3-none-any.whl")
        await environment.upload_file(
            ADAPTER_ROOT / "stdio.py", "/opt/hse-v0/stdio.py"
        )
        await environment.upload_file(
            DRIVER, "/opt/hse-v0/driver.py"
        )
        result = await environment.exec(
            "chmod 0644 /tmp/harness-v0.tar.gz "
            "/tmp/nexau-0.4.1-py3-none-any.whl "
            "/opt/hse-v0/stdio.py /opt/hse-v0/driver.py && "
            "tar -xzf /tmp/harness-v0.tar.gz -C /opt/hse-v0/harness && "
            "chmod -R a+rX /opt/hse-v0 && "
            "test -f /opt/hse-v0/harness/entry.py && "
            "if ! python3 -c 'import nexau, ag_ui_protocol' >/dev/null 2>&1; then "
            "python3 -m pip install --no-cache-dir "
            "'ag-ui-protocol==0.1.22' '/tmp/nexau-0.4.1-py3-none-any.whl'; "
            "fi",
            timeout_sec=900,
            user="root",
        )
        if result.return_code != 0:
            raise RuntimeError(result.stderr or result.stdout or "harness unpack failed")

    def _env_value(self, *names: str) -> str | None:
        for source in (self.extra_env, os.environ):
            for name in names:
                value = source.get(name)
                if value:
                    return value
        return None

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        model = self.model_name or self._env_value("HARNESS_LLM_MODEL", "LLM_MODEL")
        base_url = self._env_value("HARNESS_LLM_BASE_URL", "LLM_BASE_URL")
        api_key = self._env_value("HARNESS_LLM_API_KEY", "LLM_API_KEY")
        if not model or not base_url or not api_key:
            raise RuntimeError(
                "harness-v0 requires model, HARNESS_LLM_BASE_URL, and "
                "HARNESS_LLM_API_KEY"
            )
        encoded = base64.b64encode(instruction.encode("utf-8")).decode("ascii")
        write_instruction = (
            f"printf '%s' '{encoded}' | base64 -d > /tmp/hse-v0-instruction.md"
        )
        result = await environment.exec(write_instruction, timeout_sec=30)
        if result.return_code != 0:
            raise RuntimeError(result.stderr or result.stdout or "instruction upload failed")
        env = {
            "LLM_MODEL": model,
            "LLM_BASE_URL": base_url,
            "LLM_API_KEY": api_key,
            "SANDBOX_WORK_DIR": "/app",
            "HARNESS_STDIO_PROTOCOL": "stdio-jsonl-v1",
            "PYTHONUNBUFFERED": "1",
            "HARNESS_PYTHON": "python3",
        }
        result = await environment.exec(
            "python3 -u /opt/hse-v0/driver.py",
            cwd="/opt/hse-v0",
            env=env,
            timeout_sec=1800,
        )
        context.metadata = {
            "adapter": "harbor-harness-v0",
            "harness_revision": "sha256:dd7cdd91a4dc170af3662cdca28d2ed9fbd0dd2676e57ce9a4041146a488e011",
            "model": model,
            "base_url": base_url,
            "return_code": result.return_code,
        }
        if result.return_code != 0:
            diagnostics = await environment.exec(
                "for f in /logs/agent/harness-stderr.log /logs/agent/harness-transcript.jsonl; do "
                "echo ===$f===; test -f $f && tail -80 $f || true; done",
                timeout_sec=30,
            )
            raise RuntimeError(
                result.stderr
                or result.stdout
                or diagnostics.stdout
                or "harness-v0 failed"
            )
