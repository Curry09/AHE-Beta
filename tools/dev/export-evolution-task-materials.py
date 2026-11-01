#!/usr/bin/env python3
"""Spec-0081/T2: verify and export original task payloads, without running tasks."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from auto_designer.experiment.task_environments.materials import (  # noqa: E402
    MaterialError,
    materialize_input,
    sha256_file,
)


class ExportError(MaterialError):
    """The supplied originals cannot establish a verified task material export."""


def _read_document(*, path: Path) -> tuple[dict, str]:
    if path.is_symlink() or not path.is_file():
        raise ExportError("Input manifest must be a regular, unlinked JSON file")
    data = path.read_bytes()
    try:
        document = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise ExportError("Input manifest is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ExportError("Input manifest must contain a JSON object")
    return document, hashlib.sha256(data).hexdigest()


def _task_rows(*, document: dict) -> list[dict]:
    rows = document.get("tasks")
    if not isinstance(rows, list) or not rows:
        raise ExportError("Input manifest must contain a nonempty tasks array")
    keys = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ExportError("Every task must be a JSON object")
        key = row.get("task_key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", key):
            raise ExportError("Each task needs a safe, explicit task_key")
        if key in keys:
            raise ExportError(f"Duplicate task_key: {key}")
        keys.add(key)
        if not isinstance(row.get("task_id"), str) or not row["task_id"].strip():
            raise ExportError(f"Missing task_id for {key}")
        expected = row.get("agent_payload_sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ExportError(f"Missing original agent_payload_sha256 for {key}")
    return rows


def _image_provenance(*, images: dict, key: str) -> dict | None:
    value = images.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ExportError(f"Invalid image provenance for {key}")
    # Image configs can contain credentials. Keep only the original identifier facts.
    return {name: value[name] for name in ("image", "image_id") if isinstance(value.get(name), str)}


def _export_payload(*, row: dict, payloads: Path, stage: Path, images: dict) -> dict:
    key = row["task_key"]
    source = payloads / (key + ".tar.gz")
    if source.is_symlink() or not source.is_file():
        raise ExportError(
            f"Missing original payload for {key}; solved workspaces are not a substitute"
        )
    destination = stage / "payloads" / source.name
    shutil.copyfile(source, destination)
    destination.chmod(0o600)
    material = {
        "path": str(destination),
        "format": "tar.gz",
        "sha256": row["agent_payload_sha256"],
    }
    with tempfile.TemporaryDirectory(prefix=".inspect-", dir=stage) as temporary:
        inventory_root = Path(temporary)
        files = materialize_input(material=material, destination=inventory_root)
        inventory = {
            name: {
                "sha256": digest,
                "bytes": (inventory_root / name).stat().st_size,
                "mode": (inventory_root / name).stat().st_mode & 0o777,
            }
            for name, digest in sorted(files.items())
        }
    with gzip.open(destination, "rb") as stream:
        uncompressed_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    if sha256_file(destination) != row["agent_payload_sha256"]:
        raise ExportError(f"Exported payload changed for {key}")
    provenance = {
        "original_agent_payload_sha256": row["agent_payload_sha256"],
        "uncompressed_tar_sha256": uncompressed_sha256,
    }
    original_image = _image_provenance(images=images, key=key)
    if original_image is not None:
        provenance["original_image"] = original_image
    return {
        "task_key": key,
        "task_id": row["task_id"],
        "material": {
            **material,
            "path": destination.relative_to(stage).as_posix(),
            "files": files,
        },
        "archive_bytes": destination.stat().st_size,
        "inventory": inventory,
        "provenance": provenance,
    }


def export_materials(
    *, manifest: Path, payloads: Path, output: Path, images: Path | None = None
) -> dict:
    """Export explicitly hashed originals to a new directory, atomically and offline.

    The result verifies byte identity and safe inventory, not task completeness
    or solvability. Intentionally incomplete originals remain unchanged; their
    scenario scope and operator decision belong in the task-library manifest.
    Missing or changed original archives still fail verification. This does not
    select agent-visible paths, construct environments, or publish assets.
    """
    document, manifest_sha256 = _read_document(path=manifest)
    rows = _task_rows(document=document)
    if payloads.is_symlink() or not payloads.is_dir():
        raise ExportError("Payloads must be an existing, unlinked directory of original archives")
    image_map = _read_document(path=images)[0] if images is not None else {}
    target = output.absolute()
    if target.exists() or target.is_symlink():
        raise ExportError("Output must be a new directory; existing exports are never overwritten")
    if target.resolve().is_relative_to(payloads.resolve()):
        raise ExportError("Output cannot be placed inside original payloads")
    if any(parent.is_symlink() for parent in target.parents):
        raise ExportError("Output cannot be placed beneath a linked directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".task-material-export-", dir=target.parent) as temp:
        stage = Path(temp) / "export"
        stage.mkdir(mode=0o700)
        (stage / "payloads").mkdir(mode=0o700)
        exported = [
            _export_payload(row=row, payloads=payloads, stage=stage, images=image_map)
            for row in rows
        ]
        lock = {
            "schema_version": 1,
            "status": "verified_original_payloads",
            "source_manifest_sha256": manifest_sha256,
            "task_count": len(exported),
            "archive_bytes": sum(row["archive_bytes"] for row in exported),
            "tasks": exported,
            "publication": "not_attempted",
            "runtime_recipe": "requires_explicit_environment_and_agent_visible_input_selection",
            "image_provenance": "local_image_ids_are_not_published_registry_digests",
        }
        lock_path = stage / "materials.lock.json"
        lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
        lock_path.chmod(0o600)
        # Reserve the name atomically, so rename cannot replace somebody else's
        # empty output directory after the initial existence check.
        target.mkdir(mode=0o700)
        try:
            stage.rename(target)
        except OSError:
            target.rmdir()
            raise
    return lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--payloads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--images", type=Path, help="Optional original image-reference JSON")
    args = parser.parse_args(argv)
    try:
        result = export_materials(
            manifest=args.manifest, payloads=args.payloads, output=args.output, images=args.images
        )
    except (MaterialError, OSError) as exc:
        print(f"Material export failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "tasks": result["task_count"],
                "archive_bytes": result["archive_bytes"],
                "lock": str(args.output.absolute() / "materials.lock.json"),
                "publication": result["publication"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
