#!/usr/bin/env python3
"""Build the thin, controller-private 19-task public benchmark pilot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import tomllib

import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
SELECTION = HERE / "selection.json"
DEFAULT_ARCHIVES = {
    "tua": Path("/tmp/tua-bench-3497fd32.tar.gz"),
    "tau3": Path("/tmp/tau3-bench-fc0055dc.tar.gz"),
}
DEFAULT_TERMINAL_TASKS = Path("/tmp/harbor-registry-preflight")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = item.relative_to(path).as_posix().encode()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def benchmark(selection: dict, name: str) -> dict:
    return next(item for item in selection["benchmarks"] if item["name"] == name)


def archive_root(archive: tarfile.TarFile) -> str:
    roots = {
        PurePosixPath(member.name).parts[0]
        for member in archive.getmembers()
        if PurePosixPath(member.name).parts
    }
    if len(roots) != 1:
        raise RuntimeError(f"archive has unexpected roots: {sorted(roots)}")
    return roots.pop()


def read_archive_text(archive: tarfile.TarFile, name: str) -> str:
    stream = archive.extractfile(name)
    if stream is None:
        raise FileNotFoundError(name)
    return stream.read().decode("utf-8")


def extract_selected_tasks(
    archive_path: Path,
    task_ids: list[str],
    destination: Path,
) -> tuple[str, dict[str, dict]]:
    metadata: dict[str, dict] = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        root = archive_root(archive)
        members = archive.getmembers()
        names = {member.name for member in members}
        for task_id in task_ids:
            prefix = f"{root}/tasks/{task_id}/"
            selected = [member for member in members if member.name.startswith(prefix)]
            if not selected:
                raise RuntimeError(f"task {task_id!r} is missing from {archive_path}")
            for member in selected:
                relative = PurePosixPath(member.name).relative_to(root)
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise RuntimeError(f"unsupported archive entry: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(f"could not read {member.name}")
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)

            task_toml_name = f"{prefix}task.toml"
            instruction_name = f"{prefix}instruction.md"
            if task_toml_name not in names or instruction_name not in names:
                raise RuntimeError(f"task {task_id!r} lacks task.toml or instruction.md")
            metadata[task_id] = {
                "task_config": tomllib.loads(read_archive_text(archive, task_toml_name)),
                "instruction": read_archive_text(archive, instruction_name),
            }
    return root, metadata


def copy_registry_tasks(
    source_root: Path,
    task_ids: list[str],
    destination: Path,
) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    for task_id in task_ids:
        source = source_root / task_id
        if not source.is_dir():
            raise RuntimeError(f"registry task is missing: {source}")
        for required in ("task.toml", "instruction.md", "environment", "tests"):
            if not (source / required).exists():
                raise RuntimeError(f"registry task {task_id!r} lacks {required}")
        target = destination / "tasks" / task_id
        shutil.copytree(source, target)
        metadata[task_id] = {
            "task_config": tomllib.loads((source / "task.toml").read_text()),
            "instruction": (source / "instruction.md").read_text(encoding="utf-8"),
        }
    return metadata


def load_tau_tasks(archive_path: Path, wanted: list[tuple[str, str]]) -> list[dict]:
    by_domain: dict[str, set[str]] = {}
    for domain, task_id in wanted:
        by_domain.setdefault(domain, set()).add(str(task_id))

    found: list[dict] = []
    with tarfile.open(archive_path, "r:gz") as archive:
        root = archive_root(archive)
        for domain, ids in by_domain.items():
            name = f"{root}/data/tau2/domains/{domain}/tasks.json"
            tasks = json.loads(read_archive_text(archive, name))
            indexed = {str(task["id"]): task for task in tasks}
            missing = ids - indexed.keys()
            if missing:
                raise RuntimeError(f"tau3 {domain} missing task ids: {sorted(missing)}")
            for task_id in ids:
                found.append({"domain": domain, "task": indexed[task_id]})
    order = {(domain, task_id): i for i, (domain, task_id) in enumerate(wanted)}
    found.sort(key=lambda item: order[(item["domain"], str(item["task"]["id"]))])
    return found


def build(args: argparse.Namespace) -> Path:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    counts = {entry["name"]: len(entry["tasks"]) for entry in selection["benchmarks"]}
    expected_counts = {
        "SWE-bench Verified": 6,
        "Terminal-Bench 4.0": 5,
        "TUA-Bench": 4,
        "tau3-bench Core/Text": 4,
    }
    if counts != expected_counts or sum(counts.values()) != selection["total_tasks"]:
        raise RuntimeError(f"selection counts differ from contract: {counts}")

    archive_paths = {
        "tua": args.tua_archive,
        "tau3": args.tau3_archive,
    }
    for name, path in archive_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"{name} archive not found: {path}")
    if not args.terminal_tasks.is_dir():
        raise FileNotFoundError(
            f"materialized Terminal-Bench task directory not found: {args.terminal_tasks}"
        )

    terminal = benchmark(selection, "Terminal-Bench 4.0")
    tua = benchmark(selection, "TUA-Bench")
    tau3 = benchmark(selection, "tau3-bench Core/Text")
    expected_archive_hashes = {
        "tua": tua["version"]["source_archive_sha256"],
        "tau3": tau3["version"]["source_archive_sha256"],
    }
    archive_info = {}
    for name, path in archive_paths.items():
        actual = sha256_file(path)
        if actual != expected_archive_hashes[name]:
            raise RuntimeError(
                f"{name} archive checksum mismatch: expected "
                f"{expected_archive_hashes[name]}, got {actual}"
            )
        archive_info[name] = {"sha256": actual, "bytes": path.stat().st_size}

    if sha256_file(args.swe_parquet) != benchmark(selection, "SWE-bench Verified")["version"][
        "local_parquet_sha256"
    ]:
        raise RuntimeError("local SWE-bench Verified parquet checksum mismatch")

    output = args.output
    if output.exists():
        raise FileExistsError(f"refusing to replace existing prepared set: {output}")
    staging = Path(tempfile.mkdtemp(prefix=".prepared-", dir=HERE))
    try:
        controller = staging / "controller-private"
        agent_inputs = staging / "agent-inputs"

        swe = benchmark(selection, "SWE-bench Verified")
        wanted_swe = [task["id"] for task in swe["tasks"]]
        rows = pq.read_table(args.swe_parquet).to_pylist()
        indexed = {row["instance_id"]: row for row in rows}
        missing = set(wanted_swe) - indexed.keys()
        if missing:
            raise RuntimeError(f"SWE-bench parquet missing: {sorted(missing)}")
        selected_swe = [indexed[task_id] for task_id in wanted_swe]
        write_jsonl(controller / "swe-bench-verified-full.jsonl", selected_swe)
        write_jsonl(
            agent_inputs / "swe-bench-verified.jsonl",
            [
                {
                    "benchmark": "SWE-bench Verified",
                    "task_id": row["instance_id"],
                    "repo": row["repo"],
                    "base_commit": row["base_commit"],
                    "problem_statement": row["problem_statement"],
                    "difficulty": row["difficulty"],
                }
                for row in selected_swe
            ],
        )

        terminal_ids = [task["id"] for task in terminal["tasks"]]
        terminal_meta = copy_registry_tasks(
            args.terminal_tasks,
            terminal_ids,
            controller / "task-sources/terminal-bench-4.0",
        )
        write_jsonl(
            agent_inputs / "terminal-bench-4.0.jsonl",
            [
                {
                    "benchmark": "Terminal-Bench 4.0",
                    "task_id": task_id,
                    "hub_digest": next(
                        task["hub_digest"] for task in terminal["tasks"]
                        if task["id"] == task_id
                    ),
                    "instruction": terminal_meta[task_id]["instruction"],
                }
                for task_id in terminal_ids
            ],
        )

        tua_ids = [task["id"] for task in tua["tasks"]]
        tua_root, tua_meta = extract_selected_tasks(
            archive_paths["tua"],
            tua_ids,
            controller / "task-sources/tua-bench",
        )
        write_jsonl(
            agent_inputs / "tua-bench.jsonl",
            [
                {
                    "benchmark": "TUA-Bench",
                    "task_id": task_id,
                    "instruction": tua_meta[task_id]["instruction"],
                }
                for task_id in tua_ids
            ],
        )

        wanted_tau = [(task["domain"], str(task["id"])) for task in tau3["tasks"]]
        selected_tau = load_tau_tasks(archive_paths["tau3"], wanted_tau)
        write_jsonl(controller / "tau3-selected-tasks.jsonl", selected_tau)
        write_jsonl(
            agent_inputs / "tau3-routing.jsonl",
            [
                {
                    "benchmark": "tau3-bench Core/Text",
                    "domain": item["domain"],
                    "task_id": str(item["task"]["id"]),
                    "delivery": "user-simulator",
                    **(
                        {"retrieval": "bm25"}
                        if item["domain"] == "banking_knowledge" else {}
                    ),
                }
                for item in selected_tau
            ],
        )

        write_json(
            staging / "source-lock.json",
            {
                "schema_version": 1,
                "selection": "../selection.json",
                "sources": {
                    "terminal_bench": {
                        **terminal["version"],
                        "task_digests": {
                            task["id"]: task["hub_digest"] for task in terminal["tasks"]
                        },
                        "materialized_from": "Harbor Hub task downloads by digest",
                        "materialized_tree_sha256": {
                            task_id: sha256_tree(args.terminal_tasks / task_id)
                            for task_id in terminal_ids
                        },
                    },
                    "tua_bench": {**tua["version"], **archive_info["tua"]},
                    "tau3_bench": {**tau3["version"], **archive_info["tau3"]},
                    "swe_bench_verified": {
                        **swe["version"],
                        "parquet": str(args.swe_parquet),
                        "bytes": args.swe_parquet.stat().st_size,
                    },
                },
            },
        )
        write_json(
            staging / "prepared-manifest.json",
            {
                "schema_version": 1,
                "prepared_at": datetime.now(timezone.utc).isoformat(),
                "total_tasks": 19,
                "counts": counts,
                "source_archive_roots": {
                    "terminal_bench": "Harbor Hub packages pinned by task digest",
                    "tua_bench": tua_root,
                },
                "data_boundary": {
                    "agent_inputs": "Only task instructions/routing; no gold patches, solutions, tests, or evaluation criteria.",
                    "controller_private": "Contains graders, solutions, full SWE rows, and tau evaluation criteria; never mount into the agent sandbox.",
                },
            },
        )

        run_matrix: list[dict] = []
        for index, task in enumerate(swe["tasks"], 1):
            run_matrix.append(
                {
                    "case_id": f"swe-{index:02d}",
                    "benchmark": "SWE-bench Verified",
                    "task_id": task["id"],
                    "agent_input": "agent-inputs/swe-bench-verified.jsonl",
                    "sandbox": {"cpu": 2, "memory_gb": 8, "disk_gb": 10},
                    "timeout_minutes": 45,
                    "user_mode": "external-strict-followup-v1",
                    "grader_isolation": "fresh-sandbox",
                    "smoke_runs": 1,
                    "measurement_runs": 3,
                }
            )
        for index, task in enumerate(terminal["tasks"], 1):
            run_matrix.append(
                {
                    "case_id": f"terminal-{index:02d}",
                    "benchmark": "Terminal-Bench 4.0",
                    "task_id": task["id"],
                    "agent_input": "agent-inputs/terminal-bench-4.0.jsonl",
                    "sandbox": {
                        "cpu": 4 if task["recommended_memory_gb"] >= 8 else 2,
                        "memory_gb": task["recommended_memory_gb"],
                        "disk_gb": 30,
                    },
                    "timeout_minutes": 120,
                    "user_mode": "external-strict-followup-v1",
                    "grader_isolation": "harbor-managed",
                    "smoke_runs": 1,
                    "measurement_runs": 3,
                }
            )
        for index, task in enumerate(tua["tasks"], 1):
            run_matrix.append(
                {
                    "case_id": f"tua-{index:02d}",
                    "benchmark": "TUA-Bench",
                    "task_id": task["id"],
                    "agent_input": "agent-inputs/tua-bench.jsonl",
                    "sandbox": {
                        "cpu": task["cpu"],
                        "memory_gb": task["memory_gb"],
                        "disk_gb": task["storage_gb"],
                    },
                    "timeout_minutes": 90,
                    "user_mode": "external-strict-followup-v1",
                    "grader_isolation": "harbor-managed",
                    "smoke_runs": 1,
                    "measurement_runs": 3,
                }
            )
        for index, task in enumerate(tau3["tasks"], 1):
            run_matrix.append(
                {
                    "case_id": f"tau3-{index:02d}",
                    "benchmark": "tau3-bench Core/Text",
                    "domain": task["domain"],
                    "task_id": str(task["id"]),
                    "agent_input": "agent-inputs/tau3-routing.jsonl",
                    "sandbox": {"cpu": 2, "memory_gb": 4, "disk_gb": 10},
                    "timeout_minutes": 30,
                    "max_turns": 40,
                    "user_mode": "native-tau3-simulator",
                    "user_seeds": [17, 29, 43, 71],
                    "grader_isolation": "fresh-task-state",
                    "smoke_runs": 1,
                    "measurement_runs": 4,
                }
            )
        write_jsonl(staging / "run-matrix.jsonl", run_matrix)

        checksum_lines = []
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            relative = path.relative_to(staging)
            checksum_lines.append(f"{sha256_file(path)}  {relative.as_posix()}\n")
        (staging / "checksums.sha256").write_text("".join(checksum_lines), encoding="utf-8")
        staging.rename(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--swe-parquet",
        type=Path,
        default=Path(os.environ.get("SWE_BENCH_PARQUET", "test.parquet")),
    )
    parser.add_argument("--terminal-tasks", type=Path, default=DEFAULT_TERMINAL_TASKS)
    parser.add_argument("--tua-archive", type=Path, default=DEFAULT_ARCHIVES["tua"])
    parser.add_argument("--tau3-archive", type=Path, default=DEFAULT_ARCHIVES["tau3"])
    parser.add_argument("--output", type=Path, default=HERE / "prepared")
    return parser.parse_args()


if __name__ == "__main__":
    built = build(parse_args())
    print(f"prepared_evalset={built}")
