"""Pinned official task selection and verified, reusable download cache."""

from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PIN = json.loads(Path(__file__).with_name("release.json").read_text())


def task_files(name: str) -> dict[str, str]:
    if name not in PIN["tasks"]:
        raise ValueError(f"Task is outside the supported pinned selection: {name}")
    prefix = f"tasks/{name}/"
    return {p.removeprefix(prefix): h for p, h in PIN["files"].items() if p.startswith(prefix)}


def task_digest(name: str) -> str:
    return hashlib.sha256(json.dumps(task_files(name), sort_keys=True).encode()).hexdigest()


def verify_task(root: Path, name: str, revision: str, digest: str) -> None:
    if revision != PIN["revision"] or digest != task_digest(name):
        raise ValueError("Task identity does not match the pinned release")
    expected = task_files(name)
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    if actual != set(expected):
        raise ValueError(f"Task file inventory differs from pinned release: {name}")
    for relative, sha in expected.items():
        path = root / relative
        if path.is_symlink():
            raise ValueError("Pinned task files must not be symbolic links")
        data = path.read_bytes()
        observed = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if observed != sha:
            raise ValueError(f"Pinned task file changed: {name}/{relative}")


def prepare_tasks(cache: Path, names: list[str]) -> None:
    expected = {f"tasks/{n}/{p}": h for n in names for p, h in task_files(n).items()}
    if all((cache / p).is_file() for p in expected):
        for name in names:
            verify_task(cache / "tasks" / name, name, PIN["revision"], task_digest(name))
        return
    cache.mkdir(parents=True, exist_ok=True)
    url = f"https://api.github.com/repos/harbor-framework/harbor-index/tarball/{PIN['revision']}"
    with tempfile.TemporaryDirectory(prefix="harbor-index-") as temp:
        archive_path = Path(temp) / "release.tar.gz"
        with urllib.request.urlopen(url, timeout=120) as response, archive_path.open("wb") as out:
            while chunk := response.read(1024**2):
                out.write(chunk)
        seen = set()
        with tarfile.open(archive_path) as archive:
            for member in archive:
                name = "/".join(Path(member.name).parts[1:])
                if name not in expected:
                    continue
                if name in seen or not member.isfile():
                    raise ValueError("Invalid pinned task archive member")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Missing task member data")
                data = stream.read()
                sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                if sha != expected[name]:
                    raise ValueError(f"Downloaded task checksum mismatch: {name}")
                target = cache / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(member.mode & 0o777)
                seen.add(name)
        if seen != set(expected):
            raise ValueError("Incomplete pinned task download")
    for name in names:
        verify_task(cache / "tasks" / name, name, PIN["revision"], task_digest(name))


def resolve_dataset(dataset, source):
    from platformdirs import user_cache_path

    from evaluation.config import CaseRef, PlanError, _text

    revision = _text(dataset.get("revision"), "dataset.revision")
    if (
        revision != PIN["revision"]
        or dataset.get("repository", PIN["repository"]) != PIN["repository"]
    ):
        raise PlanError("This plan requires the supported pinned Harbor Index release")
    names = dataset.get("task_names", PIN["tasks"])
    if (
        not isinstance(names, list)
        or not names
        or any(not isinstance(n, str) for n in names)
        or len(set(names)) != len(names)
        or any(n not in PIN["tasks"] for n in names)
    ):
        raise PlanError("dataset.task_names must be a unique supported task selection")
    if "cache_dir" in dataset:
        cache = Path(_text(dataset["cache_dir"], "dataset.cache_dir")).expanduser()
        cache = (source.parent / cache).resolve()
    else:
        cache = user_cache_path("auto-designer-evaluation") / revision
    cases = tuple(
        CaseRef("Harbor Index", n, revision, task_digest(n), str(cache / "tasks" / n))
        for n in names
    )
    return {
        "source": "harbor_index",
        "repository": PIN["repository"],
        "revision": revision,
        "cache_dir": str(cache),
        "task_names": names,
    }, cases


def verify_case(case):
    verify_task(Path(case["root"]), case["task_id"], case["revision"], case["digest"])
