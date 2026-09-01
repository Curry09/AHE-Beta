#!/usr/bin/env python3
"""Incrementally prepare cached SWE-bench workspaces for a manifest.

The builder reuses the existing GitSource repository/commit cache, writes each
instance to a deterministic directory, and records resumable per-instance
state.  Source preparation and dependency installation are separate stages so
operators can validate storage/network behavior before creating large venvs.

Examples (from the repository root)::

    PYTHONPATH=backend .venv/bin/python backend/scripts/build_swebench_seed_workspaces.py \
      --validate-only

    PYTHONPATH=backend .venv/bin/python backend/scripts/build_swebench_seed_workspaces.py \
      --instance psf__requests-6028 --instance mwaskom__seaborn-3187 --source-only

    PYTHONPATH=backend .venv/bin/python backend/scripts/build_swebench_seed_workspaces.py \
      --instance psf__requests-6028 --with-deps
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.seed_source import provision

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = BACKEND / "swebench_pools" / "medium_hard_16.json"
DEFAULT_OUTPUT = BACKEND / "data" / "swebench_seed" / "medium-hard-16"
STATE_NAME = "build-state.json"
DEPS_MARKER = ".seed-deps-v6"
LEGACY_COMPAT_MARKER = ".seed-legacy-compat-v1"
LEGACY_COMPAT_SOURCE = Path(__file__).with_name("swebench_seed_sitecustomize.py")
LEGACY_COMPAT_REPOS = {"psf/requests", "sympy/sympy"}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    configured_parquet = os.environ.get("SWEBENCH_PARQUET", "").strip()
    parser.add_argument(
        "--parquet",
        type=Path,
        default=Path(configured_parquet) if configured_parquet else None,
        help="SWE-bench Verified parquet path (or set SWEBENCH_PARQUET).",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--instance", action="append", default=[])
    parser.add_argument("--validate-only", action="store_true")
    stages = parser.add_mutually_exclusive_group()
    stages.add_argument("--source-only", action="store_true")
    stages.add_argument("--with-deps", action="store_true")
    parser.add_argument(
        "--setup-timeout",
        type=float,
        default=1800.0,
        help="Timeout in seconds for each dependency setup command.",
    )
    args = parser.parse_args()
    if args.parquet is None:
        parser.error("--parquet or SWEBENCH_PARQUET is required")
    return args


def _load_pool(manifest_path: Path, parquet_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    requested = list(manifest.get("instances") or [])
    if not requested:
        raise SystemExit(f"manifest has no instances: {manifest_path}")
    ids = [str(item.get("instance_id", "")) for item in requested]
    if any(not iid for iid in ids) or len(ids) != len(set(ids)):
        raise SystemExit("manifest instance_id values must be non-empty and unique")
    table = pq.read_table(
        parquet_path,
        columns=["instance_id", "repo", "base_commit", "problem_statement", "difficulty"],
    )
    rows = table.to_pylist()
    by_id = {str(row["instance_id"]): row for row in rows}
    missing = [iid for iid in ids if iid not in by_id]
    if missing:
        raise SystemExit(f"parquet is missing manifest instances: {missing}")
    enriched: list[dict[str, Any]] = []
    for item in requested:
        actual = by_id[str(item["instance_id"])]
        if item.get("difficulty") != actual["difficulty"]:
            raise SystemExit(
                f"difficulty mismatch for {item['instance_id']}: "
                f"manifest={item.get('difficulty')!r}, parquet={actual['difficulty']!r}"
            )
        enriched.append({**actual, **item})
    return manifest, enriched


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"instances": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _tree_size(path: Path) -> int:
    proc = subprocess.run(
        ["du", "-sb", str(path)], capture_output=True, text=True, check=True
    )
    return int(proc.stdout.split()[0])


def _setup_interpreter(row: dict[str, Any]) -> tuple[str, tuple[int, int]]:
    requested = str(row.get("setup_python") or "").strip()
    if not requested and row["repo"] == "scikit-learn/scikit-learn":
        requested = "python3.10"
    if requested == "python3.10":
        return "python3.10", (3, 10)
    if requested in {"", "current"}:
        return shlex.quote(sys.executable), (sys.version_info.major, sys.version_info.minor)
    raise ValueError(f"unsupported setup_python: {requested!r}")


def _setup_commands(row: dict[str, Any]) -> list[str]:
    interpreter, _expected = _setup_interpreter(row)
    commands = [
        f"{interpreter} -m venv .venv",
        # setuptools 81 removed pkg_resources, which several historical Verified
        # snapshots still import at runtime (xarray-3993 is one example).
        ".venv/bin/python -m pip install -U pip 'setuptools<81' wheel",
    ]
    # Historical scientific snapshots often declare only lower bounds and are
    # incompatible with NumPy 2 / Pandas 3.  Python 3.12 still has wheels for
    # NumPy 1.26 and Pandas 2, so cap only the breaking major versions.
    repo = str(row["repo"])
    if repo in {
        "astropy/astropy",
        "matplotlib/matplotlib",
        "mwaskom/seaborn",
        "pydata/xarray",
        "scikit-learn/scikit-learn",
    }:
        commands.append(".venv/bin/python -m pip install 'numpy>=1.26,<2'")
    if repo in {"mwaskom/seaborn", "pydata/xarray", "scikit-learn/scikit-learn"}:
        commands.append(".venv/bin/python -m pip install 'pandas<3'")
    if repo == "astropy/astropy":
        # These snapshots import setuptools.dep_util during their extension
        # discovery.  PEP 517 isolation would ignore our pin and install a
        # modern setuptools where that module no longer exists.
        commands.append(
            ".venv/bin/python -m pip install 'setuptools<70' setuptools_scm "
            "'cython<3' extension-helpers"
        )
        commands.append(".venv/bin/python -m pip install --no-build-isolation -e .")
    elif repo == "scikit-learn/scikit-learn":
        # This pre-PEP-660 backend cannot do editable installs with modern pip.
        # Python 3.10 + the period build toolchain preserves setup.py develop.
        commands.append(
            ".venv/bin/python -m pip install 'pip<25' 'setuptools<60' 'cython<3' scipy"
        )
        commands.append(".venv/bin/python -m pip install --no-build-isolation -e .")
    else:
        commands.append(".venv/bin/python -m pip install -e .")
    return commands


def _run_setup(repo_dir: Path, row: dict[str, Any], *, timeout: float) -> None:
    venv_python = repo_dir / ".venv" / "bin" / "python"
    _interpreter, expected = _setup_interpreter(row)
    if venv_python.is_file():
        proc = subprocess.run(
            [str(venv_python), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or proc.stdout.strip() != f"{expected[0]}.{expected[1]}":
            stale = repo_dir / f".venv.stale-{int(time.time())}"
            (repo_dir / ".venv").replace(stale)
    for cmd in _setup_commands(row):
        proc = subprocess.run(
            cmd,
            cwd=repo_dir,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "")[-5000:]
            raise RuntimeError(f"setup failed rc={proc.returncode}: {cmd}\n{stderr}")
    if row["repo"] in LEGACY_COMPAT_REPOS:
        site_packages = list((repo_dir / ".venv" / "lib").glob("python*/site-packages"))
        if len(site_packages) != 1:
            raise RuntimeError(f"cannot locate unique venv site-packages: {site_packages}")
        shutil.copyfile(LEGACY_COMPAT_SOURCE, site_packages[0] / "sitecustomize.py")
        (repo_dir / LEGACY_COMPAT_MARKER).write_text(
            "v1: collections aliases; inspect.getargspec\n", encoding="utf-8"
        )
    (repo_dir / DEPS_MARKER).write_text(
        "v6: setuptools<81; scientific=numpy<2,pandas<3; astropy=setuptools<70,no-isolation; "
        "scikit-learn=python3.10,pip<25,setuptools<60,no-isolation\n",
        encoding="utf-8",
    )


def _deps_cached(repo_dir: Path, row: dict[str, Any]) -> bool:
    if not (repo_dir / DEPS_MARKER).is_file():
        return False
    venv_python = repo_dir / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        return False
    _interpreter, expected = _setup_interpreter(row)
    proc = subprocess.run(
        [
            str(venv_python),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or proc.stdout.strip() != f"{expected[0]}.{expected[1]}":
        return False
    return row["repo"] not in LEGACY_COMPAT_REPOS or (
        repo_dir / LEGACY_COMPAT_MARKER
    ).is_file()


def _prepare_source(row: dict[str, Any], instance_root: Path) -> Path:
    repo_dir = instance_root / "repo"
    if repo_dir.is_dir() and (repo_dir / ".git").is_dir():
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True
        ).stdout.strip()
        if head == str(row["base_commit"]):
            return repo_dir
        stale = instance_root.with_name(instance_root.name + f".stale-{int(time.time())}")
        instance_root.replace(stale)
    instance_root.mkdir(parents=True, exist_ok=True)
    spec = WorkspaceSpec(
        kind="git",
        params={
            "repo": f"https://github.com/{row['repo']}.git",
            "commit": str(row["base_commit"]),
        },
    )
    provisioned = Path(provision(spec, dest_root=str(instance_root)))
    if provisioned != repo_dir:
        raise RuntimeError(f"unexpected provision path: {provisioned} != {repo_dir}")
    return repo_dir


def main() -> int:
    args = _args()
    manifest, rows = _load_pool(args.manifest.resolve(), args.parquet.resolve())
    selected = set(args.instance)
    known = {str(row["instance_id"]) for row in rows}
    unknown = sorted(selected - known)
    if unknown:
        raise SystemExit(f"--instance is not in manifest: {unknown}")
    if selected:
        rows = [row for row in rows if row["instance_id"] in selected]

    counts = Counter(str(row["difficulty"]) for row in rows)
    repos = {str(row["repo"]) for row in rows}
    print(
        f"validated pool={manifest.get('name')} instances={len(rows)} "
        f"repos={len(repos)} difficulty={dict(counts)}"
    )
    if args.validate_only:
        return 0

    output = args.output.resolve()
    state_path = output / STATE_NAME
    state = _read_state(state_path)
    state.update(
        {
            "pool": manifest.get("name"),
            "manifest": str(args.manifest.resolve()),
            "parquet": str(args.parquet.resolve()),
            "updated_at": datetime.now().astimezone().isoformat(),
        }
    )
    instance_states = state.setdefault("instances", {})
    want_deps = args.with_deps and not args.source_only

    failures = 0
    for index, row in enumerate(rows, start=1):
        iid = str(row["instance_id"])
        instance_root = output / "workspace" / iid
        current = instance_states.setdefault(iid, {})
        started = time.monotonic()
        print(f"[{index}/{len(rows)}] {iid}: source", flush=True)
        try:
            repo_dir = _prepare_source(row, instance_root)
            current.update(
                {
                    "repo": row["repo"],
                    "base_commit": row["base_commit"],
                    "difficulty": row["difficulty"],
                    "theme": row.get("theme"),
                    "source_path": str(repo_dir.resolve()),
                    "source": "ok",
                    "error": None,
                }
            )
            if want_deps:
                if _deps_cached(repo_dir, row):
                    print(f"[{index}/{len(rows)}] {iid}: deps cached", flush=True)
                else:
                    print(f"[{index}/{len(rows)}] {iid}: deps", flush=True)
                    _run_setup(repo_dir, row, timeout=args.setup_timeout)
                current["deps"] = "ok"
            else:
                current.setdefault("deps", "pending")
            current["bytes"] = _tree_size(instance_root)
            current["seconds"] = round(time.monotonic() - started, 3)
            print(
                f"[{index}/{len(rows)}] {iid}: ok "
                f"{current['bytes'] / 1024 / 1024:.1f} MiB in {current['seconds']}s",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - one bad task must not abort the pool
            failures += 1
            current.update(
                {
                    "source": current.get("source", "failed"),
                    "deps": "failed" if want_deps else current.get("deps", "pending"),
                    "error": f"{type(exc).__name__}: {exc}",
                    "seconds": round(time.monotonic() - started, 3),
                }
            )
            print(f"[{index}/{len(rows)}] {iid}: FAILED: {current['error']}", flush=True)
        finally:
            state["updated_at"] = datetime.now().astimezone().isoformat()
            _write_state(state_path, state)

    total_bytes = sum(int(item.get("bytes", 0)) for item in instance_states.values())
    print(
        f"done failures={failures} recorded={len(instance_states)} "
        f"workspace_size={total_bytes / 1024 / 1024 / 1024:.2f} GiB "
        f"state={state_path}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
