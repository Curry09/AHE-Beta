"""Harbor adapter for one historical simulated-user trial.

The adapter keeps the benchmark interaction loop inside the Harbor task.  It is
intentionally separate from the single-turn ``HarnessV0Agent`` smoke adapter:
the paper condition needs the existing persona/heartbeat protocol, not Harbor's
generic simulated-user bridge.
"""

from __future__ import annotations

import os
from pathlib import Path

from harbor.agents.base import AgentContext, BaseAgent
from harbor.environments.base import BaseEnvironment


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARCHIVE = ROOT / ".artifacts" / "harness-v0-cade14d.tar.gz"
BACKEND_ROOT = ROOT / "backend" / "auto_designer"
EVAL_HARNESS_ROOT = ROOT / "evaluation" / "harness_bench" / "harness"
DRIVER = ROOT / "evaluation" / "harness_bench" / "harbor_historical_user_driver.py"
PERSONA_LIBRARY = ROOT / "backend" / "persona_library.json"
PYTHON312_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/20260814/"
    "cpython-3.12.14%2B20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
)
PYTHON312_SHA256 = "5acfa3e9ba26b51ae161c83aff278da915b590d22373a424b2ba55b8afe91fcc"


class HarborHistoricalUserAgent(BaseAgent):
    """Run exactly one historical persona loop inside the Harbor sandbox."""

    @staticmethod
    def name() -> str:
        return "harness-v0-historical-user"

    def version(self) -> str:
        return "baseline-v0-cade14d-historical-user"

    @classmethod
    def preflight(cls, kwargs=None, env=None) -> None:
        archive = Path((env or os.environ).get("HSE_HARNESS_ARCHIVE", str(DEFAULT_ARCHIVE)))
        for path in (archive, DRIVER, PERSONA_LIBRARY):
            if not path.is_file():
                raise FileNotFoundError(f"missing historical-user input: {path}")

    def _value(self, name: str, default: str = "") -> str:
        # Harbor serializes some ``--agent-env`` values as references such as
        # ``${HARNESS_LLM_API_KEY}``. Resolve those references on the
        # controller before injecting the environment into the sandbox; the
        # literal placeholder would make OpenRouter reject the request with a
        # missing-authentication-header 401.
        value = str(self.extra_env.get(name) or "")
        if value.startswith("${") and value.endswith("}"):
            value = os.environ.get(value[2:-1], "")
        if not value:
            value = os.environ.get(name, "")
        return value or default

    def _outer_timeout(self) -> tuple[int, int]:
        official = int(self._value("HSE_OFFICIAL_AGENT_TIMEOUT_SECONDS", "1800"))
        configured = int(
            self._value("HSE_OUTER_AGENT_TIMEOUT_SECONDS", str(official + 600))
        )
        expected = official + 600
        if configured != expected:
            raise ValueError(
                "HSE_OUTER_AGENT_TIMEOUT_SECONDS must equal "
                f"HSE_OFFICIAL_AGENT_TIMEOUT_SECONDS + 600 ({expected})"
            )
        return official, configured

    async def setup(self, environment: BaseEnvironment) -> None:
        archive = Path(self._value("HSE_HARNESS_ARCHIVE", str(DEFAULT_ARCHIVE)))
        await environment.exec(
            "mkdir -p /opt/hse-round/harness /opt/hse-round/backend /opt/hse-round/eval /logs/agent /eval-out",
            timeout_sec=30,
            user="root",
        )
        await environment.upload_file(archive, "/opt/hse-round/harness.tar.gz")
        await environment.upload_file(DRIVER, "/opt/hse-round/driver.py")
        await environment.upload_file(PERSONA_LIBRARY, "/opt/hse-round/persona_library.json")
        # Upload source trees individually so the task remains self-contained and
        # does not need package-index access during a trial.
        await environment.upload_dir(BACKEND_ROOT, "/opt/hse-round/backend/auto_designer")
        await environment.upload_dir(EVAL_HARNESS_ROOT, "/opt/hse-round/eval/harness")
        result = await environment.exec(
            "curl -fL --retry 3 "
            f"'{PYTHON312_URL}' -o /tmp/python312.tar.gz && "
            f"echo '{PYTHON312_SHA256}  /tmp/python312.tar.gz' | sha256sum -c - && "
            "tar -xzf /tmp/python312.tar.gz -C /opt && "
            "/opt/python/bin/python3 -m venv /opt/hse-venv && "
            "/opt/hse-venv/bin/pip install --no-cache-dir "
            "'ag-ui-protocol==0.1.22' 'nexau==0.4.1' && "
            "rm -f /tmp/python312.tar.gz && "
            "tar -xzf /opt/hse-round/harness.tar.gz -C /opt/hse-round/harness && "
            "test -f /opt/hse-round/harness/entry.py && "
            "test -f /opt/hse-round/backend/auto_designer/user/sim/loop.py",
            timeout_sec=900,
            user="root",
        )
        if result.return_code != 0:
            raise RuntimeError(result.stderr or result.stdout or "historical-user setup failed")

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        import base64

        official_timeout, outer_timeout = self._outer_timeout()

        encoded = base64.b64encode(instruction.encode("utf-8")).decode("ascii")
        await environment.exec(
            f"printf '%s' '{encoded}' | base64 -d > /opt/hse-round/instruction.md",
            timeout_sec=30,
            user="root",
        )
        env = {
            "HSE_PYTHON": self._value("HSE_PYTHON", "/opt/hse-venv/bin/python"),
            "USER_LLM_MODEL": self._value("USER_LLM_MODEL", "glm-5.3-flash"),
            "USER_LLM_BASE_URL": self._value("USER_LLM_BASE_URL"),
            "USER_LLM_API_KEY": self._value("USER_LLM_API_KEY"),
            "HARNESS_LLM_MODEL": self._value("HARNESS_LLM_MODEL", "glm-5.3-flash"),
            "HARNESS_LLM_BASE_URL": self._value("HARNESS_LLM_BASE_URL"),
            "HARNESS_LLM_API_KEY": self._value("HARNESS_LLM_API_KEY"),
            "HSE_PERSONA_ID": self._value("HSE_PERSONA_ID", "sr-01-willison"),
            "HSE_TASK_INSTANCE": self._value(
                "HSE_TASK_INSTANCE", "pvlib__pvlib-python-1478"
            ),
            "HSE_OFFICIAL_AGENT_TIMEOUT_SECONDS": str(official_timeout),
            "HSE_OUTER_AGENT_TIMEOUT_SECONDS": str(outer_timeout),
            "PYTHONUNBUFFERED": "1",
        }
        result = await environment.exec(
            f"{env['HSE_PYTHON']} -u /opt/hse-round/driver.py",
            cwd="/opt/hse-round",
            env=env,
            timeout_sec=outer_timeout,
            user="root",
        )
        context.metadata = {
            "adapter": "harbor-historical-user",
            "harness_revision": "baseline-v0-cade14d",
            "model": env["HARNESS_LLM_MODEL"],
            "user_model": env["USER_LLM_MODEL"],
            "return_code": result.return_code,
        }
        if result.return_code != 0:
            diagnostics = await environment.exec(
                "for f in /logs/agent/harness-stderr.log /eval-out/session.json /eval-out/driver.log; do "
                "echo ===$f===; test -f $f && tail -120 $f || true; done",
                timeout_sec=30,
                user="root",
            )
            raise RuntimeError(result.stderr or result.stdout or diagnostics.stdout or "historical-user failed")
