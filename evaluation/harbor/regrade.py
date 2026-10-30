"""Fresh official verification of immutable retained artifacts; no Agent launch."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import traceback
from pathlib import Path

from harbor.environments.factory import EnvironmentFactory
from harbor.models.task.config import VerifierEnvironmentMode
from harbor.models.task.task import Task
from harbor.models.task.verifier_mode import (
    resolve_task_verifier_mode,
    resolve_verifier_environment_definition,
)
from harbor.models.trial.config import AgentConfig, EnvironmentConfig, VerifierConfig
from harbor.models.trial.paths import EnvironmentPaths, TrialPaths
from harbor.trial.artifact_handler import ArtifactHandler
from harbor.trial.network_policy import resolve_trial_network_plan
from harbor.utils.env import resolve_env_vars
from harbor.verifier.factory import VerifierFactory


def artifact_hashes(directory: Path) -> dict:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def _failure_diagnostics(error: Exception, phase: str) -> dict:
    diagnostics = {
        "phase": phase,
        "exception_type": type(error).__name__,
        "exception_message": str(error),
        "exception_traceback": "".join(traceback.format_exception(error)),
    }
    secrets = {
        value
        for name, value in os.environ.items()
        if len(value) > 4
        and any(part in name.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    for secret in sorted(secrets, key=len, reverse=True):
        for field in ("exception_message", "exception_traceback"):
            diagnostics[field] = diagnostics[field].replace(secret, "[redacted]")
    return diagnostics


async def regrade(task_root: Path, original: Path, destination: Path, job: dict) -> dict:
    task = Task(task_root)
    if task.config.steps:
        raise ValueError("Verifier-only recovery currently requires a single-step task")
    if resolve_task_verifier_mode(task.config) is not VerifierEnvironmentMode.SEPARATE:
        raise ValueError("Cannot faithfully regrade a destroyed shared task environment")
    artifacts = original / "artifacts"
    if not artifacts.is_dir():
        raise ValueError("Retained task artifacts are missing")
    before = artifact_hashes(artifacts)
    paths = TrialPaths(destination)
    paths.mkdir()
    definition = resolve_verifier_environment_definition(task.config, task.paths)
    if definition is None:
        raise ValueError("A separate verifier environment definition is required")
    cfg = definition.config
    runtime = EnvironmentConfig.model_validate(job["environment"])
    network = resolve_trial_network_plan(
        task.config,
        AgentConfig.model_validate(job["agents"][0]),
        runtime,
        None,
        verifier_mode=VerifierEnvironmentMode.SEPARATE,
        env_config=cfg,
    )
    env = EnvironmentFactory.create_environment_from_config(
        config=runtime,
        environment_dir=definition.directory,
        environment_name=task.short_name,
        session_id=destination.name + "__verifier__regrade",
        trial_paths=paths,
        task_env_config=cfg,
        network_policy=network.verifier_env_baseline,
        phase_network_policies=[network.verifier_phase],
        mounts=[
            {
                "type": "bind",
                "source": str(paths.verifier_dir.resolve()),
                "target": "/logs/verifier",
            }
        ],
    )
    env.context_id = destination.name
    result = {
        "actor_model_requests": 0,
        "harness_rerun": False,
        "artifact_sha256": before,
        "source_trial": str(original),
        "rewards": None,
    }
    phase = "environment_start"
    try:
        await asyncio.wait_for(env.start(False), timeout=cfg.build_timeout_sec)
        phase = "artifact_upload"
        handler = ArtifactHandler(
            artifacts=task.config.artifacts, logger=logging.getLogger("regrade")
        )
        await handler.upload_artifacts(
            env,
            artifacts_dir=artifacts,
            source_artifacts_dir=EnvironmentPaths.artifacts_dir.as_posix(),
            target_artifacts_dir=EnvironmentPaths.artifacts_dir.as_posix(),
        )
        phase = "verifier_setup"
        verifier = VerifierFactory.create_verifier_from_config(
            VerifierConfig(),
            task=task,
            trial_paths=paths,
            environment=env,
            override_env=resolve_env_vars(job["verifier"]["env"]),
            skip_tests_upload=definition.bundled_tests,
        )
        if network.verifier_phase != network.verifier_env_baseline:
            await env.set_network_policy(network.verifier_phase)
        phase = "verifier_execution"
        with env.with_default_user(task.config.verifier.user):
            verified = await asyncio.wait_for(
                verifier.verify(), timeout=task.config.verifier.timeout_sec
            )
        result["rewards"] = verified.rewards
    except Exception as error:
        result.update(_failure_diagnostics(error, phase))
    finally:
        try:
            await env.stop(True)
        except Exception as error:
            result["cleanup_failure"] = _failure_diagnostics(error, "environment_cleanup")
            raise
        finally:
            result["artifacts_unchanged"] = before == artifact_hashes(artifacts)
            (destination / "regrade.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
