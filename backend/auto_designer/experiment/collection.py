"""Spec-0069/T5: portable, checksummed evidence collection independent of model keys."""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.materials import sha256_file

_EXCLUDED = {
    "secrets",
    ".git",
    ".venv",
    "__pycache__",
    ".openagents",
    "archive",
    "source",
    "cloud-snapshot",
    "collection-stage",
    ".cache",
}


def export_gitea_snapshot(
    *,
    run_dir: Path,
    resources: Mapping[str, Any],
    credentials: Mapping[str, str],
    terminal: bool = False,
    controller_nonce: str | None = None,
) -> dict[str, Any]:
    """Capture issue/comment/PR facts without a model call or deleting remote data."""
    from urllib.parse import quote

    import requests

    gitea = resources.get("gitea") or {}
    destination = run_dir / "runtime/gitea-evidence.json"
    if not all(gitea.get(field) for field in ("url", "owner", "repo")):
        return {"applicable": False, "complete": True}
    prefix = (
        str(gitea["url"]).rstrip("/")
        + "/api/v1/repos/"
        + quote(str(gitea["owner"]), safe="")
        + "/"
        + quote(str(gitea["repo"]), safe="")
    )
    headers = {"Authorization": "token " + credentials.get("GITEA_TOKEN", "")}

    def get(path: str, params: dict | None = None) -> Any:
        response = requests.get(prefix + path, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            raise ConfigError(f"Gitea evidence export failed (HTTP {response.status_code})")
        return response.json()

    def pages(path: str, **params: Any) -> list:
        values = []
        for page in range(1, 10001):
            batch = get(path, {**params, "page": page, "limit": 50})
            if not isinstance(batch, list):
                raise ConfigError("Gitea evidence endpoint returned an invalid list")
            values.extend(batch)
            if len(batch) < 50:
                return values
        raise ConfigError("Gitea evidence pagination exceeded supported limit")

    try:
        issues = pages("/issues", state="all", type="issues")
        pulls = pages("/pulls", state="all")
        document = {
            "repository": get(""),
            "issues": issues,
            "pulls": pulls,
            "branches": pages("/branches"),
            "comments": {},
            "captured_at": datetime.now(UTC).isoformat(),
            "terminal": terminal,
            "controller_nonce": controller_nonce,
        }
        for item in [*issues, *pulls]:
            index = str(int(item["number"]))
            document["comments"][index] = pages("/issues/" + index + "/comments")
        destination.parent.mkdir(exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(destination)
        return {
            "applicable": True,
            "complete": True,
            "terminal": terminal,
            "sha256": sha256_file(destination),
            "path": str(destination),
        }
    except (requests.RequestException, ConfigError, ValueError, KeyError):
        if destination.is_file():
            previous = json.loads(destination.read_text())
            # local stop captured this after stopping the controller and before
            # stopping Gitea. Active checkpoints alone cannot seal an archive.
            return {
                "applicable": True,
                "complete": bool(previous.get("terminal"))
                and previous.get("controller_nonce") == controller_nonce,
                "terminal": bool(previous.get("terminal"))
                and previous.get("controller_nonce") == controller_nonce,
                "retained": True,
                "path": str(destination),
            }
        return {"applicable": True, "complete": False, "terminal": False}


def _public_file(relative: Path) -> bool:
    if relative.parts[0] == "infrastructure" or relative.as_posix() == "logs/collector.log":
        return False
    if (
        relative.parts[0] == "runtime"
        and len(relative.parts) > 1
        and relative.parts[1] in {"image-build", "vigil-config", "collection.json"}
    ):
        return False
    return not any(part in _EXCLUDED for part in relative.parts) and not any(
        part == ".env"
        or (
            part.startswith(".env.")
            and not (i == len(relative.parts) - 1 and part == ".env.example")
        )
        or part.endswith(".env")
        or part.endswith(".lock")
        and part != "requirements.lock"
        for i, part in enumerate(relative.parts)
    )


def collect_archive(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    snapshot: dict[str, Any],
    credentials: dict[str, str],
) -> dict[str, Any]:
    """COMPLETE describes a quiescent archive, never the experiment outcome.

    Provider observations before/after copying govern consistency. Host materials
    and the original immutable manifest accompany each portable archive.
    """
    source = Path(snapshot["snapshot_dir"]).resolve()
    if not source.is_dir():
        raise ConfigError("Provider did not produce a collection snapshot")
    archive_root = run_dir / "archive"
    archive_root.mkdir(exist_ok=True)
    sensitive = [
        v.encode()
        for k, v in credentials.items()
        if len(v) >= 8 and any(t in k for t in ("KEY", "TOKEN", "PASSWORD"))
    ]
    expected = snapshot.get("files", {})
    consistent = bool(snapshot.get("consistent"))
    with tempfile.TemporaryDirectory(prefix="collection-stage-", dir=run_dir / "runtime") as tmp:
        stage = Path(tmp)
        files: dict[str, str] = {}

        def copy(path: Path, relative: Path) -> None:
            nonlocal consistent
            if path.is_symlink() or not path.is_file():
                return
            before = sha256_file(path)
            dest = stage / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Model trajectories can echo credentials. Never copy them verbatim
            # when an explicitly supplied provider secret appears in their bytes.
            data = path.read_bytes()
            for value in sensitive:
                data = data.replace(value, b"[REDACTED]")
            dest.write_bytes(data)
            after = sha256_file(path)
            if before != after:
                consistent = False
            raw_relative = (
                path.relative_to(source).as_posix() if path.is_relative_to(source) else None
            )
            if raw_relative in expected and expected[raw_relative] != after:
                consistent = False
            files[relative.as_posix()] = hashlib.sha256(data).hexdigest()

        for path in list(source.rglob("*")):
            relative = path.relative_to(source)
            if _public_file(relative) and not path.is_relative_to(stage):
                copy(path, relative)
        copy(run_dir / "manifest.json", Path("manifest.json"))
        for record in manifest["materials"].values():
            relative = Path(record["path"])
            if not relative.is_relative_to("materials"):
                raise ConfigError("Frozen input lies outside materials directory")
            copy(run_dir / relative, relative)
        evidence = run_dir / "runtime/gitea-evidence.json"
        if evidence.is_file() and not evidence.is_relative_to(source):
            copy(evidence, Path("runtime/gitea-evidence.json"))
        if not snapshot.get("gitea_evidence", {}).get("complete", True):
            consistent = False
        state = "COMPLETE" if snapshot.get("terminal") and consistent else "PARTIAL"
        receipt = {
            "run_id": manifest["run_id"],
            "config_hash": manifest["config_hash"],
            "collection_state": state,
            "consistent": consistent,
            "terminal": bool(snapshot.get("terminal")),
            "controller": snapshot.get("controller"),
            "collected_at": datetime.now(UTC).isoformat(),
            "files": files,
        }
        (stage / "collection.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        temporary = archive_root / ".artifacts.tar.gz.tmp"
        with tarfile.open(temporary, "w:gz") as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.add(path, arcname=path.relative_to(stage).as_posix(), recursive=False)
        destination = archive_root / "artifacts.tar.gz"
        temporary.replace(destination)
        receipt["archive"] = str(destination)
        receipt["archive_sha256"] = sha256_file(destination)
        (archive_root / "collection.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf-8"
        )
        shutil.copy2(archive_root / "collection.json", run_dir / "runtime/collection.json")
        return receipt
