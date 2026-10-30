"""Explicit integration points for the pinned Index task set."""

import shlex
from pathlib import Path

from .grading import grade_issues as grade_issues
from .source import PIN, prepare_tasks
from .source import resolve_dataset as resolve_dataset
from .source import verify_case as verify_case


def prepare_dataset(dataset):
    prepare_tasks(Path(dataset["cache_dir"]), dataset["task_names"])


def verifier_env(task_id):
    env = dict(PIN["judge"])
    if task_id == "usaco-assign-cows-to-barns":
        env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    return env


class EnvironmentSupport:
    def __init__(self, environment):
        self.environment = environment
        self.are = None
        self.affinity_path = None
        self.mcp_client_path = None

    def validate_compose(self):
        import yaml

        env = self.environment
        services = yaml.safe_load((env.environment_dir / "docker-compose.yaml").read_text())[
            "services"
        ]
        if not env.environment_name.startswith("gaia2-") or set(services) != {
            "main",
            "are-sidecar",
        }:
            raise ValueError(
                "This task source supports only the pinned GAIA2 main + ARE topology on E2B"
            )

    async def start(self, directory):
        env = self.environment
        if env._verifier_environment and env.environment_name.startswith("gso-"):
            from .support.gso_affinity import configure

            self.affinity_path = await configure(env, directory)
        if (
            not env._verifier_environment
            and (Path(env.environment_dir) / "docker-compose.yaml").exists()
        ):
            from .support.are_sidecar import AreSidecar

            self.are = AreSidecar(env)
            await self.are.start()

    @property
    def mcp_ready(self):
        return self.are is not None

    @property
    def mcp_transport(self):
        return "official ARE via shell CLI"

    async def prepare_mcp(self, workdir):
        if not self.mcp_ready or not Path(workdir).is_absolute():
            raise ValueError("Public MCP client requires a ready transport and absolute workspace")
        directory = Path(workdir) / ".harbor-mcp"
        result = await self.environment.exec(
            "mkdir -p " + shlex.quote(str(directory)), user="root", timeout_sec=30
        )
        if result.return_code:
            raise RuntimeError("Cannot publish the public MCP client in the task workspace")
        await self.environment.upload_file(
            Path(__file__).parent / "support/mcp_timeouts.py",
            str(directory / "mcp_timeouts.py"),
        )
        path = str(directory / "client.py")
        await self.environment.upload_file(
            Path(__file__).parent / "support/mcp_shell_client.py", path
        )
        self.mcp_client_path = path

    def mcp_instructions(self):
        if self.mcp_client_path is None:
            raise RuntimeError("Public MCP client has not been published in the task workspace")
        command = shlex.join(["python3", self.mcp_client_path])
        return (
            "\n\nThe public MCP client is available inside your workspace at "
            + self.mcp_client_path
            + ". Use the shell tool to run `"
            + command
            + " list` for public tool schemas, then `"
            + command
            + ' TOOL_NAME \'{"argument":"value"}\'`. '
            "These commands call the official ARE MCP tools; they return the tool "
            "response and notifications. Begin with AgentUserInterface__get_last_message_from_user."
        )

    async def native_mcp_servers(self, servers):
        if self.environment.capabilities.docker_compose:
            return servers
        from harbor.models.task.config import MCPServerConfig

        if {server.name for server in servers} != {"are"} or not self.mcp_ready:
            raise ValueError("Native MCP transport requires the official ARE server")
        await self.environment.upload_file(
            Path(__file__).parent / "support/mcp_stdio_client.py",
            "/opt/harbor-mcp/stdio.py",
        )
        return [
            MCPServerConfig(
                name="are",
                transport="stdio",
                command="python3",
                args=["/opt/harbor-mcp/stdio.py"],
            )
        ]

    def command_env(self, supplied):
        if self.affinity_path:
            return {**(supplied or {}), "PATH": self.affinity_path}
        return supplied

    def command(self, command):
        if not self.environment._verifier_environment:
            return command
        name = self.environment.environment_name
        if name.startswith("swtbenchverified-") and "/tests/test.sh" in command:
            # E2B's outer login shell activates testbed, while the official
            # verifier image installs its top-level parser in conda base.
            # Child test scripts still activate their own testbed environment.
            return (
                'env PATH=/opt/miniconda3/bin:"$PATH" /bin/bash --noprofile --norc -c '
                + shlex.quote(command)
            )
        if name.startswith("gso-"):
            # Keep task imports out of the independent scoring interpreter.
            # The image owns the anti-hack SDK in /opt/gso-venv; test.sh uses
            # python3 for that judge, so select the existing verifier runtime.
            # eval.sh still explicitly activates each benchmark's own venv.
            runtime = ' PATH=/opt/gso-venv/bin:"$PATH"' if "/tests/test.sh" in command else ""
            return (
                "env -u PYTHONPATH -u PYTHONHOME"
                + runtime
                + " /bin/bash --noprofile --norc -c "
                + shlex.quote(command)
            )
        return command

    async def collect(self):
        if self.are:
            await self.are.collect()

    async def stop(self):
        if self.are:
            try:
                await self.are.stop()
            finally:
                self.are = None
