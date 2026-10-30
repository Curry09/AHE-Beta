"""Task-owned execution budgets, resources and runtime provenance."""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from importlib.metadata import version
from pathlib import Path

from evaluation import __version__

PERSISTENCE_GRACE_SECONDS = 600


def resolve_contract(root: Path) -> dict:
    task = tomllib.loads((root / "task.toml").read_text())
    agent = task.get("agent", {})
    environment = task.get("environment", {})
    verifier = task.get("verifier", {})
    agent_budget = agent.get("timeout_sec", 1800)
    for value in (
        agent_budget,
        environment.get("build_timeout_sec", 600),
        verifier.get("timeout_sec", 600),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("Task budgets must be finite positive numbers")
    mode = verifier.get("environment_mode") or (
        "separate" if "environment" in verifier else "shared"
    )
    verification_environment = verifier.get("environment", environment)
    return {
        "agent_timeout_seconds": agent_budget,
        "outer_agent_timeout_seconds": agent_budget + PERSISTENCE_GRACE_SECONDS,
        "agent_timeout_source": "official_task_metadata"
        if "timeout_sec" in agent
        else "fallback_no_official_timeout",
        "environment_build_timeout_seconds": environment.get("build_timeout_sec", 600),
        "verifier_timeout_seconds": verifier.get("timeout_sec", 600),
        "persistence_grace_seconds": PERSISTENCE_GRACE_SECONDS,
        "clock": "agent_execution_wall",
        "grader_isolation": mode,
        "resources": {"agent": environment, "verifier": verification_environment},
        "artifacts": task.get("artifacts", []),
        "task_toml_sha256": hashlib.sha256((root / "task.toml").read_bytes()).hexdigest(),
    }


def runtime_source_files() -> dict:
    package = Path(__file__).resolve().parent.parent
    candidates = list(package.glob("*.py"))
    candidates.extend(package.glob("*.json"))
    for name in ("harbor", "harness", "environments", "benchmarks"):
        candidates.extend((package / name).rglob("*.py"))
        candidates.extend((package / name).rglob("*.json"))
    return {
        str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(candidates)
        if "__pycache__" not in p.parts
    }


def runtime_identity() -> dict:
    import harbor

    root = Path(harbor.__file__).resolve().parent
    integration = runtime_source_files()
    core = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in (
            "trial/trial.py",
            "models/task/config.py",
            "trial/artifact_handler.py",
            "verifier/verifier.py",
        )
    }
    return {
        "harbor_version": version("harbor"),
        "integration_version": __version__,
        "integration_files": integration,
        "harbor_core_files": core,
        "digest": hashlib.sha256(
            json.dumps([integration, core], sort_keys=True).encode()
        ).hexdigest(),
    }
