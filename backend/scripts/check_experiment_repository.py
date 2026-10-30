#!/usr/bin/env python3
"""Spec-0071/T6: offline checks for public experiments and repository boundaries."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from auto_designer.experiment.batch_config import load_batch_config  # noqa: E402
from auto_designer.experiment.config import ConfigError  # noqa: E402
from auto_designer.experiment.materials import check_materials  # noqa: E402

PUBLIC_COMMANDS = {
    "check",
    "prepare",
    "run",
    "status",
    "logs",
    "stop",
    "resume",
    "collect",
    "destroy",
    "dashboard",  # Spec-0072/T5: the same entry binds a selected run for observation.
    "batch",  # Spec-0074/T3: lists reuse the maintained single-run entry.
    "grade",  # Spec-0075/T3: independent grading consumes collected run artifacts.
    "assessment-worker",  # Spec-0084/T5: trusted external per-round grading.
    "task",  # Spec-0076/T2: input conversion produces existing task packages.
}
BATCH_COMMANDS = {"check", "prepare", "run", "status", "stop", "resume", "collect"}
TASK_COMMANDS = {"import-seeds", "from-text"}
RETIRED_PATHS = (
    "run.sh",
    "backend/run.py",
    "backend/auto_designer/experiment/controllers/ordinary.py",
    "backend/auto_designer/experiment/controllers/swebench.py",
    "backend/scripts/run_auditable_experiment.py",
    "backend/scripts/run_mixed_closed_loop.py",
    "backend/scripts/run_swebench_closed_loop.py",
    "examples/models.env.example",
    "backend/.env.example",
    "evaluation/public-bench-pilot",
    "evaluation/harness-suite-20260920",
)


def inventory_errors(root: Path) -> list[str]:
    path = root / "research/inventory.json"
    try:
        inventory = json.loads(path.read_text())
        rows = inventory["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return ["Missing or malformed research/inventory.json"]
    errors: list[str] = []
    seen: set[str] = set()
    for row in rows:
        original = row.get("original_path", "")
        if not original or original in seen:
            errors.append(f"Duplicate or missing inventory original path: {original}")
        seen.add(original)
        if (
            not row.get("reason")
            or not row.get("source_commit")
            or len(row.get("source_sha256", "")) != 64
        ):
            errors.append(f"Incomplete provenance: {original}")
        kind = row.get("disposition")
        destination = row.get("destination")
        if kind not in {"maintained", "moved", "archived", "removed"}:
            errors.append(f"Unknown disposition: {original}")
        if kind == "removed":
            if (root / original).exists():
                errors.append(f"Removed file is present: {original}")
            continue
        if not isinstance(destination, str):
            errors.append(f"Missing inventory destination: {original}")
            continue
        target = root / destination
        if (
            Path(destination).is_absolute()
            or ".." in Path(destination).parts
            or not target.resolve().is_relative_to(root.resolve())
            or not target.is_file()
        ):
            errors.append(f"Missing or unsafe destination: {destination}")
            continue
        if (
            kind == "archived"
            and hashlib.sha256(target.read_bytes()).hexdigest() != row["source_sha256"]
        ):
            errors.append(f"Frozen archive content changed: {destination}")
        if kind in {"archived", "moved"} and destination != original and (root / original).exists():
            errors.append(f"Obsolete duplicate remains: {original}")
    # Every archived file must have provenance; README is newly authored explanation.
    for file in (root / "research/archives").rglob("*"):
        if (
            file.is_file()
            and file != root / "research/archives/README.md"
            and file.suffix not in {".pyc"}
        ):
            relative = file.relative_to(root).as_posix()
            if not any(row.get("destination") == relative for row in rows):
                errors.append(f"Archive missing provenance: {relative}")
    return errors


def maintained_import_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for prefix in ["backend/auto_designer", "backend/scripts", "tools/dev", "evaluation"]:
        for path in (root / prefix).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text()
            try:
                tree = ast.parse(text)
            except SyntaxError:
                errors.append(f"Invalid Python: {path.relative_to(root)}")
                continue
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [x.name for x in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                    if node.module == "auto_designer.experiment.controllers":
                        modules.extend(f"{node.module}.{name.name}" for name in node.names)
                for module in modules:
                    if (
                        module == "run"
                        or module == "run_swebench_closed_loop"
                        or module == "run_auditable_experiment"
                        or module
                        in {
                            "auto_designer.experiment.controllers.ordinary",
                            "auto_designer.experiment.controllers.swebench",
                        }
                        or module.startswith("research.")
                    ):
                        errors.append(
                            f"Retired/archived production import: {path.relative_to(root)}:{node.lineno}: {module}"
                        )
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "run"
                ):
                    errors.append(f"Retired dynamic import: {path.relative_to(root)}:{node.lineno}")
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and any(
                        node.value.startswith(prefix) and len(node.value) > len(prefix)
                        for prefix in ("/Users/bytedance/", "/root/src/", "/home/wydlinux/")
                    )
                ):
                    errors.append(f"Personal source path: {path.relative_to(root)}:{node.lineno}")
    return errors


def check_repository(root: Path) -> dict:
    errors = inventory_errors(root)
    for relative in RETIRED_PATHS:
        if (root / relative).exists():
            errors.append(f"Retired public path remains: {relative}")
    examples = sorted((root / "examples/experiments").glob("*.json"))
    if not examples:
        errors.append("No public experiment definitions")
    for path in examples:
        try:
            check_materials(path)
        except (ConfigError, OSError, ValueError) as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
    batches = sorted((root / "examples/batches").glob("*.json"))
    if not batches:
        errors.append("No public batch definitions")
    for path in batches:
        try:
            load_batch_config(path)
        except (ConfigError, OSError, ValueError) as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
    errors.extend(maintained_import_errors(root))
    from auto_designer.experiment.cli import build_parser
    from auto_designer.experiment.materials import _SOURCE_ROOTS

    parser = build_parser()
    command_actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    commands = set(command_actions[0].choices)
    if commands != PUBLIC_COMMANDS:
        errors.append(f"Unexpected public commands: {sorted(commands)}")
    batch_parser = command_actions[0].choices.get("batch")
    batch_actions = (
        [a for a in batch_parser._actions if isinstance(a, argparse._SubParsersAction)]
        if batch_parser
        else []
    )
    if not batch_actions or set(batch_actions[0].choices) != BATCH_COMMANDS:
        errors.append("Unexpected public batch commands")
    task_parser = command_actions[0].choices.get("task")
    task_actions = (
        [a for a in task_parser._actions if isinstance(a, argparse._SubParsersAction)]
        if task_parser
        else []
    )
    if not task_actions or set(task_actions[0].choices) != TASK_COMMANDS:
        errors.append("Unexpected public task commands")
    if any(
        p.startswith(("examples", "research", "tools/dev")) or p == "backend/scripts"
        for p in _SOURCE_ROOTS
    ):
        errors.append("Controller snapshot includes development/history/example roots")
    for relative in _SOURCE_ROOTS:
        if not (root / relative).exists():
            errors.append(f"Frozen source dependency missing: {relative}")
    return {
        "ok": not errors,
        "examples": [p.relative_to(root).as_posix() for p in examples],
        "batches": [p.relative_to(root).as_posix() for p in batches],
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = check_repository(args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
