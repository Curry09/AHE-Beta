"""Verified Git subtree identities for the first official tasks (Spec-0083/T4)."""

from __future__ import annotations

import hashlib
import io
import tarfile
import tomllib
from pathlib import PurePosixPath
from typing import Any

from ..contracts import GradingRequest, InputValidationError
from .container import archive_files, require_material

# Git object identities are taken from the actual pinned official revisions,
# not from operator-written labels in a plan. Extra files inside tests/environment
# change these identities and cannot masquerade as the official verifier.
PROFILES = {
    "production-planning": {
        "adapter": "terminal-bench",
        "revision": "452bf305c6daa62fc59061d22133a7cbc7c1572e",
        "task_blob": "d169ceec79b4ad575a02c23dd3ac501f2e152d1e",
        "tests_tree": "b09b81a2f7153c23f5fe619e3d4237ba024529ee",
        "environment_tree": "e89beb1f89937a78280233128e722dda63e26cd5",
    },
    "kv-live-surgery": {
        "adapter": "terminal-bench",
        "revision": "452bf305c6daa62fc59061d22133a7cbc7c1572e",
        "task_blob": "29997bfe66e1f209f7e2e979dfe49caa39a7dd65",
        "tests_tree": "36f85bc2edd9a849a415a0cc59e6e168029f4188",
        "environment_tree": "c09eef07444629c0dcff01cd82800553894369fe",
    },
    "010-pivot-product-revenue": {
        "adapter": "tua-bench",
        "revision": "3497fd320abcafaf4797424192c891a593fd7964",
        "task_blob": "b67f95537242f7d95a1b7a869da8c2797d3c98bf",
        "tests_tree": "242d3ed4f03368af48b663e4027b763bee031f53",
        "environment_tree": "bd670db32cbaef2331aef17208d833e27405644f",
    },
}


def git_object(kind: str, data: bytes) -> bytes:
    return hashlib.sha1(f"{kind} {len(data)}\0".encode() + data).digest()


def git_tree(files: dict[str, bytes], modes: dict[str, int], prefix: str = "") -> bytes:
    children: dict[str, bool] = {}
    for path in files:
        if not path.startswith(prefix):
            continue
        relative = path[len(prefix) :]
        name, _, remainder = relative.partition("/")
        children[name] = bool(remainder)
    result = b""
    # Git sorts directories as if their name ended in '/'.
    for name in sorted(children, key=lambda name: name + ("/" if children[name] else "")):
        path = prefix + name
        if children[name]:
            mode, digest = "40000", git_tree(files, modes, path + "/")
        else:
            mode = "100755" if modes.get(path, 0) & 0o111 else "100644"
            digest = git_object("blob", files[path])
        result += mode.encode() + b" " + name.encode() + b"\0" + digest
    return git_object("tree", result)


def validate_task_bundle(
    request: GradingRequest,
) -> tuple[dict[str, bytes], dict[str, int], dict[str, Any]]:
    data = require_material(request, "task_bundle")
    files = archive_files(data)
    modes: dict[str, int] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive:
            if member.isfile():
                modes[str(PurePosixPath(member.name))] = member.mode
    task = request.source.get("instance_id") or request.source.get("task_id") or request.instance_id
    if not task:
        task = request.task_id
    profile = PROFILES.get(str(task))
    if not profile or profile["adapter"] != request.adapter:
        raise InputValidationError(
            f"official task profile not supported: {task}", status="unsupported"
        )
    if (
        request.source.get("revision") != profile["revision"]
        or request.config.get("revision") != profile["revision"]
    ):
        raise InputValidationError(
            "task source and grading revision must match the fixed official profile"
        )
    if (
        "task.toml" not in files
        or git_object("blob", files["task.toml"]).hex() != profile["task_blob"]
    ):
        raise InputValidationError("task.toml does not match the pinned official source")
    for directory in ("tests", "environment"):
        if git_tree(files, modes, directory + "/").hex() != profile[directory + "_tree"]:
            raise InputValidationError(
                f"{directory} tree does not match the pinned official source"
            )
    metadata = tomllib.loads(files["task.toml"].decode())
    return files, modes, metadata
