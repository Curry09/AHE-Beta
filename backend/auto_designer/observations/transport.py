"""Spec-0070/T2: freeze transport separately from the historical framework contract."""

import json
import os
import uuid
from pathlib import Path

SCHEMA = "auto-designer-observation-transport-v1"
MAX_TRANSFER = 4_000_000
MAX_EXPANDED = 24_000_000


def make_transport_profile(
    *, repository: str, encoding: str = "gzip", download_policy: str = "same-origin-v1"
) -> dict:
    return validate_transport_profile(
        {
            "schema": SCHEMA,
            "repository": repository,
            "encoding": encoding,
            "download_policy": download_policy,
            "max_transfer_bytes": MAX_TRANSFER,
            "max_expanded_bytes": MAX_EXPANDED,
        }
    )


def validate_transport_profile(profile: dict, *, repository: str | None = None) -> dict:
    keys = {
        "schema",
        "repository",
        "encoding",
        "download_policy",
        "max_transfer_bytes",
        "max_expanded_bytes",
    }
    if (
        not isinstance(profile, dict)
        or set(profile) != keys
        or profile.get("schema") != SCHEMA
        or not isinstance(profile.get("repository"), str)
        or not profile["repository"]
        or profile.get("encoding") not in ("gzip", "zip")
        or profile.get("download_policy") not in ("same-origin-v1", "gitea-com-r2-v1")
        or type(profile.get("max_transfer_bytes")) is not int
        or type(profile.get("max_expanded_bytes")) is not int
        or profile["max_transfer_bytes"] != MAX_TRANSFER
        or profile["max_expanded_bytes"] != MAX_EXPANDED
        or (repository is not None and profile["repository"] != repository)
    ):
        raise ValueError("invalid or mismatched observation transport profile")
    return dict(profile)


def load_transport_profile(root: Path, *, repository: str) -> dict | None:
    root = Path(root)
    path = root / ".transport-profile.json"
    if root.is_symlink() or path.is_symlink() or (root / ".framework-contract.json").is_symlink():
        raise ValueError("observation transport binding must not use symlinks")
    if path.exists():
        return validate_transport_profile(json.loads(path.read_text()), repository=repository)
    contract = root / ".framework-contract.json"
    if contract.exists():
        value = json.loads(contract.read_text())
        if value.get("repository") != repository:
            raise ValueError("historical observation repository mismatch")
        return make_transport_profile(repository=repository)
    return None


def freeze_transport_profile(root: Path, profile: dict) -> dict:
    profile = validate_transport_profile(profile)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    existing = load_transport_profile(root, repository=profile["repository"])
    if existing is not None and existing != profile:
        raise ValueError("frozen observation transport changed; use a new experiment identity")
    path = root / ".transport-profile.json"
    if path.exists():
        return existing
    temporary = root / f".transport-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x") as stream:
            json.dump(profile, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic create, never overwrite another writer's frozen selection.
        try:
            os.link(temporary, path)
        except FileExistsError:
            if load_transport_profile(root, repository=profile["repository"]) != profile:
                raise ValueError("concurrent observation transport selection differs") from None
    finally:
        temporary.unlink(missing_ok=True)
    return profile
