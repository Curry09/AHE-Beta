"""Freeze and validate standard Harbor task packages, independently of their source."""

import hashlib
import json
from pathlib import Path

from evaluation.benchmarks import get_profile
from evaluation.config import PlanError

from .contracts import resolve_contract


def local_task_digest(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"Task package directory is missing: {root}")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Task packages must not contain symbolic links")
        if path.is_file():
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def verify_case(case: dict) -> None:
    profile = get_profile(case["benchmark"])
    if profile:
        profile.verify_case(case)
    elif local_task_digest(Path(case["root"])) != case["digest"]:
        raise ValueError("Frozen local Harbor task package changed")


def resolve_case(case: dict) -> dict:
    from harbor.models.task.task import Task

    root = Path(case["root"])
    if not (root / "task.toml").is_file():
        raise PlanError("Task materials missing; run python -m evaluation prepare first")
    verify_case(case)
    task = Task(root)
    if task.config.steps:
        raise PlanError("This adapter requires a single-step task")
    return resolve_contract(root)
