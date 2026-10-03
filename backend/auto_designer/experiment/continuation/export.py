"""Spec-0079/T2: export the ledger-selected final Git tree and evidence boundary."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from auto_designer.demand.issue_schema import REPORT, plane
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.materials import sha256_file
from auto_designer.experiment.workload import read_session_plan, read_task_catalog
from auto_designer.loop.recovery import digest_value

EXPORT_PATH = "runtime/continuation-export.json"
HARNESS_PATH = "runtime/continuation-harness.tar.gz"


def _json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def export_git_tree(*, repo: Path, commit: str, destination: Path) -> dict:
    """Read raw blobs, preserving ignored tracked files, modes and clean-filter identity."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ConfigError("Continuation export requires an explicit commit SHA")
    _git(repo, "cat-file", "-e", commit + "^{commit}")
    tree_id = _git(repo, "rev-parse", commit + "^{tree}").decode().strip()
    inventory = {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with (
            temporary.open("wb") as raw,
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
            tarfile.open(fileobj=compressed, mode="w") as archive,
        ):
            for entry in _git(repo, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
                if not entry:
                    continue
                header, raw_name = entry.split(b"\t", 1)
                mode, kind, oid = header.decode().split(" ")
                name = raw_name.decode("utf-8")
                path = Path(name)
                if (
                    mode not in {"100644", "100755"}
                    or kind != "blob"
                    or path.is_absolute()
                    or any(part in {".", "..", ".git"} for part in path.parts)
                    or any(
                        part == ".env" or part.startswith(".env.") and part != ".env.example"
                        for part in path.parts
                    )
                ):
                    raise ConfigError("Unsupported or private file in continuation Git tree")
                data = _git(repo, "cat-file", "blob", oid)
                inventory[name] = {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "blob_oid": oid,
                    "mode": mode,
                    "size_bytes": len(data),
                }
                info = tarfile.TarInfo(name)
                info.mode = 0o755 if mode == "100755" else 0o644
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "commit": commit,
        "tree_id": tree_id,
        "sha256": sha256_file(destination),
        "files": inventory,
    }


def _selected_sessions(
    *, root: Path, sessions_root: Path, manifest: dict, last: dict, round_no: int
) -> list[dict]:
    library = _json(root / manifest["materials"]["persona_library"]["path"])
    cards = {card["id"]: card for card in library}
    stage = last["stages"]["users"]
    plan = last["plan"]
    if stage["status"] != "completed" or len(stage["units"]) != len(plan):
        raise ConfigError("Continuation final users are incomplete")
    by_slot = {}
    for unit in stage["units"].values():
        if unit["status"] != "completed":
            raise ConfigError("Continuation final user unit is incomplete")
        binding = unit["input"]["binding"]
        sid = unit["observed_postconditions"]["session_id"]
        path = sessions_root / f"{sid}.json"
        if not path.is_file() or path.is_symlink():
            raise ConfigError("Continuation final session is missing")
        session = _json(path)
        provenance = session["session_provenance"]
        if (
            session["session_id"] != sid
            or unit["input"]["user_sha"] != last["user_sha"]
            or provenance["run_id"] != manifest["run_id"]
            or provenance["harness_sha"] != last["user_sha"]
            or any(provenance.get(key) != value for key, value in binding.items())
            or binding["round_no"] != round_no
            or binding["slot"] in by_slot
        ):
            raise ConfigError("Continuation final session binding mismatch")
        record = {
            "session_id": sid,
            "path": path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": sha256_file(path),
            "binding": binding,
            "persona_sha256": digest_value(cards[binding["persona_id"]]),
        }
        observation = sessions_root.parent / "observations" / sid
        if (observation / "manifest.json").is_file():
            record["observation_path"] = (
                observation.resolve().relative_to(root.resolve()).as_posix()
            )
        by_slot[binding["slot"]] = record
    result = [by_slot[slot] for slot in range(len(plan))]
    if [record["binding"] for record in result] != plan:
        raise ConfigError("Continuation final users differ from frozen plan")
    return result


def _reports(*, root: Path, sessions: list[dict], forge: dict) -> list[dict]:
    associations: dict[int, list[str]] = {}
    for selected in sessions:
        session = _json(root / selected["path"])
        for ref in session.get("issue_refs", []):
            associations.setdefault(int(ref["number"]), []).append(selected["session_id"])
    reports = []
    by_number = {int(issue["number"]): issue for issue in forge["issues"]}
    for number, sids in sorted(associations.items()):
        issue = by_number.get(number)
        if issue is None:
            raise ConfigError("Continuation session references a missing forge report")
        labels = [label["name"] if isinstance(label, dict) else label for label in issue["labels"]]
        # Proposals/PRs are never imported as fresh report work.
        if plane(labels) != REPORT:
            continue
        report = {
            "number": number,
            "url": issue.get("html_url", issue.get("url", "")),
            "state": issue["state"],
            "title": issue["title"],
            "body": issue.get("body") or "",
            "labels": labels,
            "session_ids": sorted(sids),
        }
        report["sha256"] = digest_value(report)
        reports.append(report)
    return reports


def export_continuation(
    *,
    root: Path,
    harness_repo: Path,
    manifest: dict[str, Any],
    recovery: Any,
    sessions_root: Path,
    forge_path: Path | None = None,
) -> dict:
    """Write readiness or an explicit unavailable receipt; ordinary completion remains valid."""
    destination = root / EXPORT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    identity = {
        key: manifest[key]
        for key in ("experiment_id", "run_id", "config_hash", "controller_sha", "plan_hash")
    }
    document: dict = {"schema_version": 1, "status": "unavailable", "identity": identity}
    try:
        state = recovery.snapshot() if hasattr(recovery, "snapshot") else recovery
        if state["identity"] != identity:
            raise ConfigError("Continuation export recovery identity mismatch")
        count = manifest["config"]["rounds"]["count"]
        if set(state["rounds"]) != {str(n) for n in range(1, count + 1)} or any(
            value["status"] != "completed" for value in state["rounds"].values()
        ):
            raise ConfigError("Continuation export requires all completed rounds")
        last = state["rounds"][str(count)]
        if last["user_sha"] != last["sealed_sha"]:
            raise ConfigError("Continuation final round must be users-only")
        plan = read_session_plan(root, manifest)
        if last["plan"] != plan["rounds"][-1]:
            raise ConfigError("Continuation final ledger differs from the frozen plan")
        sessions = _selected_sessions(
            root=root, sessions_root=sessions_root, manifest=manifest, last=last, round_no=count
        )
        forge_path = forge_path or root / "runtime/gitea-evidence.json"
        # A later collect captures a fresh forge timestamp/status snapshot. Keep
        # the exact completion-boundary snapshot immutable and independently named.
        forge_bytes = forge_path.read_bytes()
        forge = json.loads(forge_bytes)
        frozen_forge = root / "runtime/continuation-forge.json"
        frozen_forge.write_bytes(forge_bytes)
        harness = export_git_tree(
            repo=harness_repo, commit=last["sealed_sha"], destination=root / HARNESS_PATH
        )
        selected_task_ids = {selected["binding"]["task_id"] for selected in sessions}
        material_keys = {"task_catalog", "session_plan", "persona_library", "persona_roster"}
        for task in read_task_catalog(root, manifest)["tasks"]:
            if task["id"] in selected_task_ids:
                material_keys.update(task["materials"].values())
        document.update(
            status="ready",
            boundary={
                "local_round": count,
                "lineage_round": (manifest.get("lineage") or {}).get("base_round", 0) + count,
                "user_sha": last["user_sha"],
                "sealed_sha": last["sealed_sha"],
                "sessions": sessions,
            },
            harness={**harness, "archive": HARNESS_PATH},
            material_keys=sorted(material_keys),
            forge={
                "path": frozen_forge.relative_to(root).as_posix(),
                "sha256": sha256_file(frozen_forge),
            },
            reports=_reports(root=root, sessions=sessions, forge=forge),
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError, ConfigError):
        # Neither credentials nor subprocess output become a public reason.
        document = {
            "schema_version": 1,
            "status": "unavailable",
            "identity": identity,
            "reason": "Final tree or selected evidence could not be verified",
        }
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(destination)
    return document
