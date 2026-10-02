"""Spec-0072/T4: read-only dashboard bound to a prepared run, without provider discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI

from auto_designer.experiment.config import ConfigError, validate_schema
from auto_designer.experiment.manifest import recovery_identity
from auto_designer.experiment.materials import sha256_file, verify_materials
from auto_designer.experiment.runtime import credentials_v2, load_run_v2
from auto_designer.tracker.gitea import GiteaTracker
from auto_designer.usage import UsageStore
from auto_designer.user.session_store import SessionStore
from auto_designer.web.api import create_app


def _contained(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ConfigError("Dashboard artifact path escapes the selected run")
    if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
        raise ConfigError("Dashboard artifact paths must not contain symbolic links")
    return path


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ConfigError("Dashboard metadata is unreadable") from exc
    if not isinstance(value, dict):
        raise ConfigError("Dashboard metadata must be an object")
    return value


def _snapshot(run_dir: Path) -> tuple[Path, dict]:
    receipt = _read(_contained(run_dir, "runtime/e2b-collection.json"))
    snapshot = _contained(run_dir, "runtime/cloud-snapshot")
    if not receipt or not snapshot.is_dir():
        raise ConfigError(
            "E2B dashboard requires local artifacts; run experiment collect RUN_ID first"
        )
    location = receipt.get("snapshot_dir")
    if not isinstance(location, str) or Path(location).resolve() != snapshot.resolve():
        raise ConfigError("E2B dashboard snapshot does not belong to this run")
    inventory = receipt.get("files")
    if not isinstance(inventory, dict):
        raise ConfigError("E2B dashboard snapshot has no verified file inventory; collect again")
    for relative, digest in inventory.items():
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ConfigError("Invalid E2B dashboard snapshot inventory")
        path = _contained(snapshot, relative)
        if not path.is_file() or sha256_file(path) != digest:
            raise ConfigError("E2B dashboard snapshot checksum changed; collect again")
    for path in snapshot.rglob("*"):
        # Historical sessions aliases are deliberately unused; the fixed run slice is authoritative.
        if (
            path.is_file()
            and not path.is_symlink()
            and path.relative_to(snapshot).as_posix() not in inventory
        ):
            raise ConfigError("E2B dashboard snapshot contains unverified files; collect again")
    return snapshot, receipt


def _snapshot_generation(run_dir: Path) -> tuple[tuple[int, int, int], str]:
    snapshot = _contained(run_dir, "runtime/cloud-snapshot")
    stat = snapshot.stat()
    receipt = _read(_contained(run_dir, "runtime/e2b-collection.json"))
    return (stat.st_dev, stat.st_ino, stat.st_ctime_ns), json.dumps(receipt, sort_keys=True)


def _snapshot_guard(run_dir: Path):
    """Validate each new collection once; refuse directory/receipt publication races."""
    generation = _snapshot_generation(run_dir)
    _path, receipt = _snapshot(run_dir)
    if _snapshot_generation(run_dir) != generation:
        raise ConfigError("E2B snapshot changed during dashboard validation; retry after collect")

    def guard():
        nonlocal generation, receipt
        before = _snapshot_generation(run_dir)
        if before != generation:
            # collect publishes the directory before its receipt. Even if the bytes are
            # identical, wait for the matching receipt rather than reuse its old time.
            if before[0] != generation[0] and before[1] == generation[1]:
                raise ConfigError("E2B snapshot collection is still publishing")
            _path, candidate = _snapshot(run_dir)
            if _snapshot_generation(run_dir) != before:
                raise ConfigError("E2B snapshot changed during dashboard refresh")
            generation, receipt = before, candidate
        return {
            "collected_at": receipt.get("collected_at"),
            "consistent": receipt.get("consistent"),
            "terminal": receipt.get("terminal"),
        }, generation

    return guard


def dashboard_app(
    *, run_id: str, root: Path | None = None, secrets_file: Path | None = None
) -> FastAPI:
    """Validate local identities and bind observations; never provision or call a model."""
    run_dir, manifest = load_run_v2(run_id=run_id, root=root)
    recovery_identity(manifest)
    validate_schema(document=manifest["config"], schema_name="experiment-v2.json")
    verify_materials(manifest)
    backend = manifest["config"]["runtime"]["backend"]
    receipt = {}
    observations = run_dir
    if backend == "e2b":
        observations, receipt = _snapshot(run_dir)
    observation_guard = _snapshot_guard(run_dir) if backend == "e2b" else None
    data = _contained(observations, "data")
    role_runs = _contained(data, f"role_runs/{run_id}")
    sessions = _contained(role_runs, "sessions")
    usage = _contained(role_runs, "usage.jsonl")
    _contained(data, "live")
    # Validate existing read inputs, including individual session files, before serving them.
    for area in (sessions, data / "live"):
        if area.is_dir():
            for path in area.rglob("*"):
                _contained(observations, path.relative_to(observations).as_posix())
    resources = _read(_contained(run_dir, "resources.json"))
    gitea = resources.get("gitea") or {}
    tracker = None
    repo_url = None
    if all(gitea.get(key) for key in ("url", "owner", "repo")):
        url = str(gitea["url"])
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigError("Dashboard requires a credential-free Gitea URL")
        repo_url = (
            url.rstrip("/")
            + "/"
            + quote(str(gitea["owner"]), safe="")
            + "/"
            + quote(str(gitea["repo"]), safe="")
        )
        credentials = credentials_v2(manifest=manifest, run_dir=run_dir, secrets_file=secrets_file)
        if credentials.get("GITEA_TOKEN"):
            tracker = GiteaTracker(
                base_url=url,
                owner=str(gitea["owner"]),
                repo=str(gitea["repo"]),
                token=credentials["GITEA_TOKEN"],
            )
    roles = manifest["config"]["roles"]
    return create_app(
        store=SessionStore(sessions),
        tracker=tracker,
        repo_url=repo_url,
        board_url=f"{repo_url}/issues" if repo_url else None,
        usage_store=UsageStore(usage),
        data_dir=data,
        roster={
            "user": manifest["config"]["rounds"]["sessions_per_round"],
            **{name: roles[name] for name in ("triager", "synthesizer", "divergent", "developer")},
            "owner": int(roles["owner_mode"] != "mechanical"),
        },
        runmeta={
            "run_id": run_id,
            "backend": backend,
            "source": "local-live" if backend == "local" else "collected-snapshot",
            "collected_at": receipt.get("collected_at"),
            "consistent": receipt.get("consistent") if receipt else None,
            "terminal": receipt.get("terminal") if receipt else None,
            "gitea_credentials_available": tracker is not None,
        },
        observation_guard=observation_guard,
    )


def serve_dashboard(
    *,
    run_id: str,
    root: Path | None = None,
    secrets_file: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    if not 1 <= port <= 65535:
        raise ConfigError("Dashboard --port must be between 1 and 65535")
    import uvicorn

    app = dashboard_app(run_id=run_id, root=root, secrets_file=secrets_file)
    metadata = app.state.runmeta
    detail = (
        f"collected snapshot from {metadata['collected_at']}; cloud activity is not live"
        if metadata["backend"] == "e2b"
        else "local live artifacts"
    )
    print(f"[dashboard] run {run_id} · {detail}", file=sys.stderr, flush=True)
    uvicorn.run(app, host=host, port=port)
