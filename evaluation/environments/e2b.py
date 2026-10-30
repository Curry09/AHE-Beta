"""Native E2B templates keyed by the task image and each role's resources."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import shlex
from pathlib import Path

from e2b import AsyncSandbox, AsyncTemplate
from e2b.api import encode_path_param, handle_api_exception
from e2b.api.client.api.templates import get_templates_aliases_alias
from e2b.api.client_async import get_api_client
from e2b.connection_config import ConnectionConfig
from e2b.exceptions import FileNotFoundException, TemplateException
from e2b.template.types import BuildInfo, TemplateBuildStatus
from harbor.environments.e2b import E2BEnvironment
from harbor.models.task.config import NetworkMode
from platformdirs import user_cache_path
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import TaskEnvironmentMixin


class HarnessE2BEnvironment(TaskEnvironmentMixin, E2BEnvironment):
    def __init__(self, *args, sandbox_timeout_sec=21600, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = self.task_env_config
        if not cfg.docker_image or "@sha256:" not in cfg.docker_image:
            raise ValueError("E2B evaluation requires a digest-pinned task image")
        identity = json.dumps(
            [
                "task-resources-v2",
                self.environment_id,
                cfg.docker_image,
                self._effective_cpus,
                self._effective_memory_mb,
            ]
        )
        self._template_name = "ad-harbor-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        self._sandbox_timeout_sec = sandbox_timeout_sec
        self._force_template_rebuild = False

    def child_kwargs(self):
        return {"sandbox_timeout_sec": self._sandbox_timeout_sec}

    async def start(self, force_build):
        self._force_template_rebuild = force_build
        try:
            await super().start(force_build)
        finally:
            self._force_template_rebuild = False

    async def _does_template_exist(self):
        # Alias lookup alone also succeeds for a failed build. Check the exact
        # default tag used by sandbox creation, not the template's newest build.
        client = get_api_client(ConnectionConfig(request_timeout=30))
        try:
            response = await get_templates_aliases_alias.asyncio_detailed(
                alias=encode_path_param(self._template_name), client=client
            )
        finally:
            await client.get_async_httpx_client().aclose()
        if response.status_code == 404:
            return False
        if response.status_code >= 300:
            raise handle_api_exception(response, TemplateException)
        template_id = response.parsed.template_id
        tags = await AsyncTemplate.get_tags(self._template_name, request_timeout=30)
        tag = next((tag for tag in tags if tag.tag == "default"), None)
        if tag is None:
            raise TemplateException(f"Cached E2B template {self._template_name} has no default tag")
        build = BuildInfo(
            template_id=template_id,
            build_id=tag.build_id,
            name=self._template_name,
            alias=self._template_name,
            tags=["default"],
        )
        while True:
            status = await AsyncTemplate.get_build_status(build, request_timeout=30)
            if status.status == TemplateBuildStatus.READY:
                return True
            if status.status not in {TemplateBuildStatus.BUILDING, TemplateBuildStatus.WAITING}:
                reason = status.reason.message if status.reason else "No provider reason"
                raise TemplateException(
                    f"Cached E2B template {self._template_name} default build {build.build_id} "
                    f"is {status.status.value}: {reason}"
                )
            # Harbor's environment build deadline bounds this wait. Do not
            # create another build or sandbox while the selected build runs.
            await asyncio.sleep(2)

    def _validate_definition(self):
        compose = self.environment_dir / "docker-compose.yaml"
        if compose.exists():
            if self.support is None:
                raise ValueError(
                    "This E2B environment cannot execute a generic Compose task; use a supported task source or local"
                )
            self.support.validate_compose()
            return
        super()._validate_definition()

    async def _create_template(self):
        directory = user_cache_path("auto-designer-evaluation") / "template-locks"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (self._template_name + ".lock")).open("w") as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(1)
            if self._force_template_rebuild or not await self._does_template_exist():
                await super()._create_template()

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=10), reraise=True)
    async def _create_sandbox(self):
        # Harbor fixes the lifetime at 24h. Keep our configurable lifetime while
        # preserving its startup environment, networking and retry behavior.
        self._sandbox = await AsyncSandbox.create(
            template=self._template_name,
            metadata={
                "application": "auto-designer-evaluation",
                "environment_name": self.environment_name,
                "session_id": self.session_id,
            },
            envs=self._startup_env(),
            timeout=self._sandbox_timeout_sec,
            allow_internet_access=self.network_policy.network_mode is not NetworkMode.NO_NETWORK,
            network=self._sandbox_create_network_options(),
        )

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=10), reraise=True)
    async def upload_file(self, source_path, target_path):
        if self._sandbox is None:
            raise RuntimeError("Sandbox not found. Please start the environment first.")
        # Model artifacts can exceed 100 MiB. Stream the existing file instead
        # of buffering it, and give the SDK an explicit transfer deadline.
        # Each idempotent retry reopens the file at byte zero. Agent budgets
        # are unaffected; this is artifact delivery to the fresh verifier.
        source = await asyncio.to_thread(Path(source_path).open, "rb")
        try:
            await self._sandbox.files.write(target_path, source, request_timeout=600)
        finally:
            await asyncio.to_thread(source.close)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def download_file(self, source_path, target_path):
        """Stream immutable artifacts with an explicit transport bound and hash.

        This runs after the actor has frozen. It changes artifact delivery only;
        neither the solver wall clock nor the official verifier is extended.
        """
        if self._sandbox is None:
            raise RuntimeError("Sandbox not found")
        target = Path(target_path)
        temporary = target.with_name(target.name + ".transfer-part")
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        if not hasattr(self, "_unfinished_artifact_downloads"):
            self._unfinished_artifact_downloads = set()
        self._unfinished_artifact_downloads.add(str(source_path))
        check = await self._sandbox.commands.run(
            "if test -f "
            + shlex.quote(str(source_path))
            + "; then sha256sum -- "
            + shlex.quote(str(source_path))
            + "; fi",
            user="root",
            timeout=120,
        )
        if check.exit_code != 0 or not check.stdout.strip():
            # The normal collector recognizes truly absent task outputs.
            try:
                return await super().download_file(source_path, target_path)
            except FileNotFoundException:
                self._unfinished_artifact_downloads.discard(str(source_path))
                raise
        expected = check.stdout.split()[0]
        if len(expected) != 64:
            raise RuntimeError("Missing artifact checksum")
        checksum = hashlib.sha256()
        try:
            async with asyncio.timeout(900):
                async with await self._sandbox.files.read(
                    source_path, format="stream", request_timeout=600
                ) as stream:
                    with temporary.open("wb") as output:
                        async for chunk in stream:
                            output.write(chunk)
                            checksum.update(chunk)
            if checksum.hexdigest() != expected:
                raise RuntimeError("Downloaded artifact SHA256 mismatch")
            temporary.replace(target)
            self._unfinished_artifact_downloads.discard(str(source_path))
            directory = self.trial_paths.trial_dir / "infrastructure"
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "artifact-downloads.jsonl").open("a") as log:
                log.write(
                    json.dumps(
                        {
                            "source": str(source_path),
                            "target": str(target),
                            "bytes": (await asyncio.to_thread(target.stat)).st_size,
                            "sha256": expected,
                            "verified": True,
                            "stream": True,
                            "request_timeout_seconds": 600,
                        }
                    )
                    + "\n"
                )
        finally:
            temporary.unlink(missing_ok=True)

    async def stop(self, delete):
        if getattr(self, "_unfinished_artifact_downloads", set()) and self._sandbox is not None:
            # Preserve a frozen submission for one bounded hour if collection
            # still fails. A later recovery can copy it without resampling.
            await self._sandbox.set_timeout(3600)
            directory = self.trial_paths.trial_dir / "infrastructure"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "artifact-retention.json").write_text(
                json.dumps(
                    {
                        "sandbox_id": self._sandbox.sandbox_id,
                        "ttl_seconds": 3600,
                        "reason": "Artifact transfer incomplete; actor already frozen",
                        "paths": sorted(self._unfinished_artifact_downloads),
                        "solver_restart_authorized_by_this_receipt": False,
                    }
                )
                + "\n"
            )
            return
        await super().stop(delete)

    async def record_allocation(self, directory):
        probe = await self.exec("nproc && head -1 /proc/meminfo", user="root", timeout_sec=30)
        lines = (probe.stdout or "").splitlines()
        if probe.return_code or len(lines) < 2:
            raise RuntimeError("E2B allocation preflight failed")
        cpus = int(lines[0])
        memory_kib = int(lines[1].split()[1])
        info = await self._sandbox.get_info()
        requested_cpus, requested_memory = self._effective_cpus, self._effective_memory_mb
        if requested_cpus is not None and (
            info.cpu_count != requested_cpus or cpus != requested_cpus
        ):
            raise RuntimeError("E2B CPU allocation differs from task declaration")
        if requested_memory is not None and info.memory_mb != requested_memory:
            raise RuntimeError("E2B memory allocation differs from task declaration")
        if not 0.85 * info.memory_mb * 1024 <= memory_kib <= info.memory_mb * 1024:
            raise RuntimeError("E2B guest memory disagrees with allocated memory")
        record = {
            "provider": "e2b",
            "sandbox_id": self._sandbox.sandbox_id,
            "image": self.task_env_config.docker_image,
            "template": self._template_name,
            "declared_cpus": self.task_env_config.cpus,
            "declared_memory_mb": self.task_env_config.memory_mb,
            "declared_storage_mb": self.task_env_config.storage_mb,
            "allocated_cpus": info.cpu_count,
            "allocated_memory_mb": info.memory_mb,
            "observed_cpus": cpus,
            "guest_memory_kib": memory_kib,
            "storage_limit_enforced": False,
            "role": self.role or ("verifier" if self._verifier_environment else "agent"),
        }
        (directory / f"{self.session_id}.json").write_text(json.dumps(record, indent=2) + "\n")
