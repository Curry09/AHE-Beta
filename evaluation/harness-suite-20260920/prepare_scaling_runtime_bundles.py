#!/usr/bin/env python3
"""Build the auditable task-material inventory used by E2B scaling runs.

This is intentionally separate from the launch gate.  A runtime bundle is
materialized only from a pinned local source; a missing source is reported and
never replaced by an empty directory or a synthetic placeholder.  The output
is small JSON metadata while the actual archives live under the external
artifact root used by the E2B controller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "evaluation" / "harness-suite-20260920"
ASSIGNMENTS = SUITE / "configs" / "mixed-scaling-20260922.tasks.json"
MEMBERSHIP = SUITE / "configs" / "mixed-scaling-20260922.json"
EXPERIMENT_CONFIGS = ROOT.parent / "auto-designer-experiment-configs"
PUBLIC_SOURCES = EXPERIMENT_CONFIGS / "public-bench-pilot-20260917" / "prepared" / "controller-private" / "task-sources"
HISTORICAL_TASKS = EXPERIMENT_CONFIGS / "harness-mixed16-20260916-strict-goal-r3" / "tasks"
SWE_WORKSPACES = ROOT / "backend" / "data" / "swebench_seed" / "dev-balanced-64" / "workspace"
OUT_ROOT = SUITE / "prepared" / "scaling-e2b-20260922"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    """Hash relative names and bytes, excluding local caches and gold outputs."""
    digest = hashlib.sha256()
    ignored = {".git", ".venv", "__pycache__", ".pytest_cache", "solution", "reference"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix().encode()
        digest.update(len(rel).to_bytes(8, "big"))
        digest.update(rel)
        digest.update(sha256_file(path).encode())
    return digest.hexdigest()


def source_for(row: dict) -> tuple[Path | None, str]:
    benchmark = row["benchmark"]
    task_id = row["task_id"]
    if benchmark == "SWE-bench":
        path = SWE_WORKSPACES / task_id
        return (path if path.is_dir() else None), "swe-prebuilt-workspace"
    if benchmark == "Terminal-Bench":
        path = PUBLIC_SOURCES / "terminal-bench-4.0" / "tasks" / task_id
        return (path if path.is_dir() else None), "terminal-task-source"
    if benchmark == "TUA-Bench":
        path = PUBLIC_SOURCES / "tua-bench" / "tasks" / task_id
        return (path if path.is_dir() else None), "tua-task-source"
    if benchmark == "mechanism":
        path = HISTORICAL_TASKS / task_id
        if path.is_dir():
            return path, "historical-mechanism-task"
        manifest = SUITE / "mechanism-seeds" / "manifest.json"
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        for item in [*manifest_data.get("historical", []), *manifest_data.get("new", [])]:
            if item.get("task_id") == task_id:
                candidate = SUITE / "mechanism-seeds" / str(item["package"])
                return (candidate if candidate.is_dir() else None), "mechanism-seed-package"
        return None, "mechanism-seed-package"
    # NL2Repo and any future family must register a pinned source explicitly.
    return None, f"unregistered-benchmark:{benchmark}"


def rows_for(n: int) -> list[dict]:
    assignments = json.loads(ASSIGNMENTS.read_text(encoding="utf-8"))["tasks"]
    keys = json.loads(MEMBERSHIP.read_text(encoding="utf-8"))["scaling_sets"][f"N{n}"]
    by_key = {item["task_key"]: item for item in assignments}
    rows = []
    for key in keys:
        item = by_key[key]
        source, kind = source_for(item)
        rows.append(
            {
                "task_key": key,
                "task_id": item["task_id"],
                "benchmark": item["benchmark"],
                "interaction": item["interaction"],
                "source_kind": kind,
                "source": str(source) if source else None,
                "source_tree_sha256": tree_digest(source) if source else None,
                "status": "ready" if source else "missing-source",
            }
        )
    return rows


def write_inventory(n: int) -> Path:
    destination = OUT_ROOT / f"n{n}" / "bundle-inventory.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = rows_for(n)
    document = {
        "schema_version": "hse-runtime-bundle-inventory-v1",
        "experiment_id": f"hse-n{n}-e2b-20260922",
        "status": "ready" if all(row["status"] == "ready" for row in rows) else "incomplete",
        "source_policy": "pinned local material only; no empty or synthetic fallback",
        "tasks": rows,
    }
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


def _add_tree(archive: tarfile.TarFile, root: Path, arcroot: str, *, grader: bool) -> None:
    """Add only the side of a task visible to that process."""
    hidden = {".git", ".venv", "__pycache__", ".pytest_cache", "solution", "reference"}
    for path in sorted(root.rglob("*")):
        if any(part in hidden for part in path.parts):
            continue
        rel = path.relative_to(root)
        # Agent must not see benchmark tests; grader must not receive solution
        # material (already excluded above).
        if grader and not (str(rel).startswith("tests/") or rel.name in {"task.toml", "evaluation.json"}):
            continue
        if not grader and (str(rel).startswith("tests/") or rel.name in {"task.toml", "evaluation.json"}):
            continue
        archive.add(path, arcname=f"{arcroot}/{rel.as_posix()}", recursive=False)


def materialize(n: int) -> Path:
    """Create N's payload archives without copying the large SWE repositories."""
    inventory_path = write_inventory(n)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    payload_root = inventory_path.parent / "payloads"
    payload_root.mkdir(parents=True, exist_ok=True)
    for row in inventory["tasks"]:
        source = Path(row["source"]) if row["source"] else None
        if source is None or row["benchmark"] == "SWE-bench":
            continue
        agent_path = payload_root / f"{row['task_key']}.agent.tar.gz"
        grader_path = payload_root / f"{row['task_key']}.grader.tar.gz"
        with tarfile.open(agent_path, "w:gz") as archive:
            _add_tree(archive, source, row["task_key"], grader=False)
        with tarfile.open(grader_path, "w:gz") as archive:
            _add_tree(archive, source, row["task_key"], grader=True)
        row["agent_payload"] = str(agent_path)
        row["agent_payload_sha256"] = sha256_file(agent_path)
        row["grader_payload"] = str(grader_path)
        row["grader_payload_sha256"] = sha256_file(grader_path)
    inventory["status"] = "ready" if all(item["status"] == "ready" for item in inventory["tasks"]) else "incomplete"
    inventory["materialization"] = {
        "payload_root": str(payload_root),
        "policy": "agent and grader payloads are separate; solutions/references are excluded",
    }
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return inventory_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", default="all", choices=["all", "4", "8", "16", "32"])
    parser.add_argument("--materialize", action="store_true", help="also create agent/grader payload archives")
    args = parser.parse_args()
    values = (4, 8, 16, 32) if args.n == "all" else (int(args.n),)
    result = []
    for n in values:
        path = materialize(n) if args.materialize else write_inventory(n)
        document = json.loads(path.read_text(encoding="utf-8"))
        missing = [item["task_key"] for item in document["tasks"] if item["status"] != "ready"]
        result.append({"n": n, "inventory": str(path), "status": document["status"], "missing": missing})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "ready" for item in result) else 2


if __name__ == "__main__":
    raise SystemExit(main())
