"""Spec-0081/T3: bind a frozen container recipe to a concrete session attempt."""

from pathlib import Path

from ahe_beta.models import WorkspaceSpec
from ahe_beta.usage import current_usage_context
from ahe_beta.user.sim.seed_source import register


@register("container")
class ContainerSource:
    kind = "container"

    def _validate_collection_binding(self, *, binding: dict, spec: WorkspaceSpec):
        if binding["registry_root"] != spec.params.get("registry_root") or any(
            binding["identity"].get(name) != spec.params.get(name)
            for name in ("run_id", "config_hash", "task_id", "task_digest", "recipe_hash")
        ):
            raise ValueError("Actor collection binding differs from frozen task environment")

    def resume_collection(self, *, binding: dict, expected_provenance: dict, spec: WorkspaceSpec):
        from ahe_beta.experiment.task_environments.docker import resume_collection

        self._validate_collection_binding(binding=binding, spec=spec)
        return resume_collection(binding=binding, expected_provenance=expected_provenance)

    def release_collection(
        self, *, binding: dict, expected_provenance: dict, spec: WorkspaceSpec
    ) -> None:
        from ahe_beta.experiment.task_environments.docker import release_collection

        self._validate_collection_binding(binding=binding, spec=spec)
        release_collection(binding=binding, expected_provenance=expected_provenance)

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None):
        from ahe_beta.experiment.task_environments.contract import (
            container_environment,
            environment_identity,
        )
        from ahe_beta.experiment.task_environments.docker import (
            DockerTaskEnvironmentManager,
            TaskEnvironmentError,
        )

        if dest_root is not None:
            raise ValueError("Container task workspaces are not host directories")
        params = spec.params
        package = {"schema_version": 3, "environment": params["environment"]}
        environment = container_environment(package)
        if environment_identity(package) != params["recipe_hash"]:
            raise TaskEnvironmentError("Prepared task environment recipe changed")
        usage = current_usage_context()
        for name in ("run_id", "task_id", "task_digest"):
            if getattr(usage, name) != params[name]:
                raise TaskEnvironmentError("Container task binding differs from frozen input")
        identity = {
            name: params[name]
            for name in ("run_id", "config_hash", "task_id", "task_digest", "recipe_hash")
        }
        identity.update(
            {name: getattr(usage, name) for name in ("session_id", "attempt", "round_no", "slot")}
        )
        manager = DockerTaskEnvironmentManager(
            environment=environment,
            identity=identity,
            registry_root=Path(params["registry_root"]),
            harness_python=params["harness_python"],
            harness_mounts=params["harness_mounts"],
            expected_git_revision=params.get("expected_git_revision"),
        )
        return manager.open()
