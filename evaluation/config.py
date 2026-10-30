"""Task-owned Harbor plan: immutable materials, platform selection, no global image."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .benchmarks import resolve_dataset


class PlanError(ValueError):
    """The requested experiment cannot be made comparable or auditable."""


class InteractionMode(StrEnum):
    DIRECT = "direct"
    SIMULATED = "simulated_user"


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PlanError(f"{field_name} must be a mapping")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{field_name} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlanError(f"{field_name} must be a positive integer")
    return value


@dataclass(frozen=True)
class CaseRef:
    benchmark: str
    task_id: str
    revision: str
    digest: str
    root: str | None = None

    @classmethod
    def from_mapping(cls, value: object, index: int) -> CaseRef:
        item = _mapping(value, f"cases[{index}]")
        return cls(
            benchmark=_text(item.get("benchmark"), f"cases[{index}].benchmark"),
            task_id=_text(item.get("task_id"), f"cases[{index}].task_id"),
            revision=_text(item.get("revision"), f"cases[{index}].revision"),
            digest=_text(item.get("digest"), f"cases[{index}].digest"),
            root=str(item["root"]) if item.get("root") else None,
        )


@dataclass(frozen=True)
class InteractionSpec:
    mode: InteractionMode = InteractionMode.DIRECT
    policy: str = "direct"
    user_model: str | None = None
    persona: str | None = None

    @classmethod
    def from_mapping(cls, value: object, index: int) -> InteractionSpec:
        item = _mapping(value, f"interactions[{index}]")
        if item.get("mode") == "simulated_user":
            if set(item) - {"mode", "policy", "user_model", "persona"}:
                raise PlanError("Unsupported simulated user option")
            if item.get("policy") != "reply_then_followup_v1":
                raise PlanError("Unsupported simulated user policy")
            if item.get("persona") != "python-competent-feedback-v1":
                raise PlanError("Unsupported simulator persona")
            return cls(
                InteractionMode.SIMULATED,
                item["policy"],
                _text(item.get("user_model"), "interaction.user_model"),
                item["persona"],
            )
        if item.get("mode") != "direct":
            raise PlanError("Harbor evaluation supports direct interaction only")
        if set(item) - {"mode", "policy"}:
            raise PlanError(
                "direct interaction accepts only mode and policy; user simulation is retired"
            )
        if item.get("policy", "direct") != "direct":
            raise PlanError("direct interaction policy must be direct")
        return cls()


@dataclass(frozen=True)
class MeasurementSpec:
    repetitions: int = 1
    scheduling_seed: int = 17

    @classmethod
    def from_mapping(cls, value: object) -> MeasurementSpec:
        item = _mapping(value, "measurement")
        seed = item.get("scheduling_seed", 17)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise PlanError("measurement.scheduling_seed must be an integer")
        return cls(
            repetitions=_positive_int(item.get("repetitions", 1), "measurement.repetitions"),
            scheduling_seed=seed,
        )


@dataclass(frozen=True)
class FrozenHarnessSpec:
    id: str
    archive: str
    sha256: str
    revision: str
    runtime: Mapping[str, str]
    adapter: str = "stdio-jsonl-v1"
    internal_call_timeout_sec: int | None = None


@dataclass(frozen=True)
class HarborAgentSpec:
    id: str
    agent: str
    version: str
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    kind: str = "harbor"


@dataclass(frozen=True)
class HarborProviderSpec:
    type: str
    concurrency: int = 1
    ephemeral: bool = True
    import_path: str | None = None
    kwargs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarborEvaluationPlan:
    schema_version: int
    suite: str
    cases: tuple[CaseRef, ...]
    harnesses: tuple[FrozenHarnessSpec | HarborAgentSpec, ...]
    harness_model: str
    interactions: tuple[InteractionSpec, ...]
    provider: HarborProviderSpec
    measurement: MeasurementSpec
    dataset: Mapping[str, Any]
    fallback_agent_timeout_seconds: int = 1800
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping, source: Path) -> HarborEvaluationPlan:
        data = _mapping(data, "plan")
        if data.get("schema_version") != 2:
            raise PlanError("Only schema_version 2 Harbor plans are supported; schema 1 is retired")
        if "budgets" in data:
            raise PlanError("Budgets belong to task.toml; plan-level budgets are retired")

        def path(value, label):
            raw = Path(_text(value, label)).expanduser()
            return str((source.parent / raw).resolve() if not raw.is_absolute() else raw.resolve())

        dataset = _mapping(data.get("dataset", {}), "dataset")
        if dataset:
            if data.get("cases"):
                raise PlanError("Choose dataset or explicit cases, not both")
            dataset, cases = resolve_dataset(dataset, source)
        else:
            raw_cases = data.get("cases")
            if not isinstance(raw_cases, list) or not raw_cases:
                raise PlanError("A Harbor plan requires dataset or explicit cases")
            cases = tuple(
                CaseRef.from_mapping({**item, "root": path(item.get("root"), "case.root")}, i)
                for i, value in enumerate(raw_cases)
                for item in [_mapping(value, "case")]
            )
            if any(c.benchmark != "Harbor" for c in cases):
                raise PlanError("Explicit schema-2 cases must use benchmark: Harbor")
        raw_harnesses = data.get("harnesses")
        if not isinstance(raw_harnesses, list) or not raw_harnesses:
            raise PlanError("harnesses must be a non-empty list")
        harnesses = []
        for raw in raw_harnesses:
            item = dict(_mapping(raw, "harness"))
            kind = item.get("kind", "frozen")
            if kind == "harbor":
                if set(item) - {"id", "kind", "agent", "version", "kwargs"}:
                    raise PlanError(
                        "Native Harbor agents accept id, kind, agent, version and kwargs"
                    )
                agent = _text(item.get("agent"), "harness.agent")
                if agent != "claude-code":
                    raise PlanError("The native agent entry currently supports claude-code")
                version = _text(item.get("version"), "harness.version")
                if version in {"latest", "stable"}:
                    raise PlanError("Native agent version must be pinned")
                options = dict(_mapping(item.get("kwargs", {}), "harness.kwargs"))
                if set(options) - {"reasoning_effort", "max_thinking_tokens", "disable_web_search"}:
                    raise PlanError("Unsupported native Claude Code option")
                harnesses.append(
                    HarborAgentSpec(_text(item.get("id"), "harness.id"), agent, version, options)
                )
                continue
            if kind != "frozen":
                raise PlanError("harness.kind must be frozen or harbor")
            if "materials" in item:
                descriptor = Path(path(item["materials"], "harness.materials"))
                material = json.loads(descriptor.read_text())
                # Descriptor paths are relative to the descriptor, not plan cwd.
                for key in ("archive",):
                    if not Path(material[key]).is_absolute():
                        material[key] = str((descriptor.parent / material[key]).resolve())
                runtime = dict(material["runtime"])
                for key in ("runtime_wheel", "runtime_lock", "python_archive"):
                    if not Path(runtime[key]).is_absolute():
                        runtime[key] = str((descriptor.parent / runtime[key]).resolve())
                material["runtime"] = runtime
                item = {**material, **item}
            runtime = dict(_mapping(item.get("runtime"), "harness.runtime"))
            for key in ("runtime_wheel", "runtime_lock", "python_archive"):
                runtime[key] = path(runtime.get(key), "runtime." + key)
            for key in ("runtime_sha256", "runtime_lock_sha256", "python_sha256"):
                runtime[key] = _text(runtime.get(key), "runtime." + key)
            timeout = item.get("internal_call_timeout_sec")
            if timeout is not None:
                timeout = _positive_int(timeout, "harness.internal_call_timeout_sec")
            harnesses.append(
                FrozenHarnessSpec(
                    id=_text(item.get("id"), "harness.id"),
                    archive=path(item.get("archive"), "harness.archive"),
                    sha256=_text(item.get("sha256"), "harness.sha256"),
                    revision=_text(item.get("revision"), "harness.revision"),
                    runtime=runtime,
                    internal_call_timeout_sec=timeout,
                )
            )
        provider = _mapping(data.get("provider"), "provider")
        if any(
            k in provider
            for k in ("image", "image_digest", "cpu", "cpus", "memory_mb", "storage_mb")
        ):
            raise PlanError("Harbor task resources and images belong to task.toml, not provider")
        provider_type = _text(provider.get("type"), "provider.type")
        import_path = provider.get("import_path")
        if provider_type not in {"local", "daytona", "e2b"} and not import_path:
            raise PlanError("Unknown platform requires an explicit environment import_path")
        if provider.get("ephemeral", True) is not True:
            raise PlanError("Evaluation requires ephemeral task environments")
        kwargs = _mapping(provider.get("kwargs", {}), "provider.kwargs")
        forbidden = {
            "override_cpus",
            "override_memory_mb",
            "override_storage_mb",
            "override_gpus",
            "network_policy",
            "task_env_config",
            "extra_docker_compose",
            "benchmark",
        }
        if forbidden.intersection(kwargs):
            raise PlanError("Provider kwargs cannot override the task contract")
        if not import_path:
            supported = {"sandbox_timeout_sec"} if provider_type == "e2b" else set()
            if set(kwargs) - supported:
                raise PlanError("Unsupported built-in provider kwargs")
        interaction_values = data.get("interactions", [{"mode": "direct"}])
        if not isinstance(interaction_values, list):
            raise PlanError("interactions must be a list")
        interactions = tuple(
            InteractionSpec.from_mapping(v, i) for i, v in enumerate(interaction_values)
        )
        if not interactions:
            raise PlanError("The built-in Harbor executor currently supports direct interaction")
        if any(i.mode is InteractionMode.SIMULATED for i in interactions):
            if provider_type != "e2b" or any(isinstance(h, HarborAgentSpec) for h in harnesses):
                raise PlanError(
                    "The simulated-user pilot requires E2B and frozen Harness materials"
                )
        plan = cls(
            schema_version=2,
            suite=_text(data.get("suite"), "suite"),
            cases=cases,
            harnesses=tuple(harnesses),
            harness_model=_text(
                _mapping(data.get("models"), "models").get("harness"), "models.harness"
            ),
            interactions=interactions,
            provider=HarborProviderSpec(
                provider_type,
                _positive_int(provider.get("concurrency", 1), "provider.concurrency"),
                import_path=import_path,
                kwargs=_mapping(provider.get("kwargs", {}), "provider.kwargs"),
            ),
            measurement=MeasurementSpec.from_mapping(data.get("measurement", {"repetitions": 1})),
            dataset=dataset,
            metadata=_mapping(data.get("metadata", {}), "metadata"),
        )
        if len({h.id for h in plan.harnesses}) != len(plan.harnesses):
            raise PlanError("harness ids must be unique")
        if len({(c.benchmark, c.task_id) for c in plan.cases}) != len(plan.cases):
            raise PlanError("benchmark/task_id pairs must be unique")
        if len(plan.interactions) != 1:
            raise PlanError("Declare exactly one interaction")
        return plan

    def validate_local_artifacts(self) -> None:
        from evaluation.harness.materials import sha256

        for harness in self.harnesses:
            if isinstance(harness, HarborAgentSpec):
                from harbor.agents.installed.claude_code import ClaudeCodeOptions

                ClaudeCodeOptions.model_validate(harness.kwargs)
                continue
            for key, digest_key in (
                ("runtime_wheel", "runtime_sha256"),
                ("runtime_lock", "runtime_lock_sha256"),
                ("python_archive", "python_sha256"),
            ):
                material = Path(harness.runtime[key])
                if not material.is_file():
                    raise PlanError(f"Missing runtime material: {material}")
                if sha256(material) != harness.runtime[digest_key]:
                    raise PlanError(f"Runtime material checksum mismatch: {material}")
            if not Path(harness.archive).is_file():
                raise PlanError(f"Missing Harness archive: {harness.archive}")
            if sha256(Path(harness.archive)) != harness.sha256:
                raise PlanError(f"Harness checksum mismatch: {harness.id}")


def load_plan(path: str | Path) -> HarborEvaluationPlan:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise PlanError(f"plan does not exist: {source}")
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
    else:
        from ruamel.yaml import YAML

        payload = YAML(typ="safe").load(source.read_text(encoding="utf-8"))
    return HarborEvaluationPlan.from_mapping(payload, source)
