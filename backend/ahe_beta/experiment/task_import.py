"""Spec-0076/T1: offline conversion into the existing ordinary task package contract."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ahe_beta.distill.seed_library import validate_card
from ahe_beta.experiment.config import ConfigError, load_task_package
from ahe_beta.experiment.workload import validate_task_ids

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[a-f0-9]{40}$")
_INTERACTIONS = {"simulated_user", "direct"}
_SCRATCH = (
    "# Initial task workspace\n\n"
    "This scratch directory is the initial source for a task to be implemented.\n"
    "The task instruction is supplied separately.\n"
)


def import_seed_tasks(
    *,
    library: Path,
    output: Path,
    seed_ids: list[str] | None = None,
    interaction: str = "simulated_user",
) -> dict:
    """Convert selected raw cards in library order, without executing their recipes."""
    raw = _read_input(path=library)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ConfigError("Seed library must contain UTF-8 JSON") from exc
    records = document.get("seeds") if isinstance(document, dict) else document
    if not isinstance(records, list) or not records:
        raise ConfigError("Seed library must contain a nonempty card array or seeds array")
    if not all(isinstance(record, dict) for record in records):
        raise ConfigError("Seed library cards must be objects")
    validate_task_ids(records)
    if seed_ids is not None:
        if not isinstance(seed_ids, list) or not all(isinstance(v, str) for v in seed_ids):
            raise ConfigError("Selected seed IDs must be a list of strings")
        validate_task_ids([{"id": value} for value in seed_ids])
        missing = set(seed_ids) - {record["id"] for record in records}
        if missing:
            raise ConfigError(f"Seed library does not contain requested IDs: {sorted(missing)}")
        selected = set(seed_ids)
        records = [record for record in records if record["id"] in selected]
    tasks = [_seed_task(record=record) for record in records]
    return _publish(
        tasks=tasks,
        output=output,
        interaction=interaction,
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def import_text_task(
    *,
    instruction: Path,
    task_id: str,
    output: Path,
    not_in_benchmark: bool,
    interaction: str = "simulated_user",
) -> dict:
    """Copy an explicitly declared ordinary instruction into a scratch task package."""
    if not_in_benchmark is not True:
        raise ConfigError("Text import requires an explicit not_in_benchmark=true declaration")
    validate_task_ids([{"id": task_id}])
    raw = _read_input(path=instruction)
    _instruction_bytes(value=raw)
    return _publish(
        tasks=[{"id": task_id, "instruction": raw, "source": None, "setup": []}],
        output=output,
        interaction=interaction,
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _read_input(*, path: Path) -> bytes:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ConfigError("Import input must be an existing regular file, not a symbolic link")
    return path.read_bytes()


def _instruction_bytes(*, value: bytes) -> None:
    try:
        text = value.decode("utf-8")
    except UnicodeError as exc:
        raise ConfigError("Task instruction must be valid UTF-8") from exc
    if not text.strip():
        raise ConfigError("Task instruction must not be empty")


def _seed_task(*, record: dict) -> dict:
    if "reject_reason" in record or "action" in record:
        raise ConfigError(f"Rejected seed card cannot be imported: {record['id']}")
    source = record.get("source")
    if not isinstance(source, dict) or source.get("not_in_benchmark") is not True:
        raise ConfigError(f"Seed {record['id']} must declare source.not_in_benchmark=true")
    task = record.get("task")
    if not isinstance(task, dict) or not isinstance(task.get("prompt"), str):
        raise ConfigError(f"Seed {record['id']} must contain a string task.prompt")
    # The old validation gate is partial; reject wrong types before its set operations.
    domain = record.get("domain")
    capabilities = record.get("capability_probed")
    if domain is not None and not isinstance(domain, str):
        raise ConfigError(f"Seed {record['id']} domain must be a string")
    if capabilities is not None and (
        not isinstance(capabilities, list)
        or not all(isinstance(value, str) for value in capabilities)
    ):
        raise ConfigError(f"Seed {record['id']} capability_probed must be a string array")
    try:
        validate_card(record)
    except ValueError as exc:
        # Do not expose raw card fields or hidden evaluation material in error receipts.
        raise ConfigError(f"Seed {record['id']} violates the seed card field contract") from exc
    try:
        instruction = task["prompt"].encode("utf-8")
    except UnicodeError as exc:
        raise ConfigError(f"Seed {record['id']} prompt must be valid UTF-8") from exc
    _instruction_bytes(value=instruction)
    env = record.get("env", {})
    if not isinstance(env, dict):
        raise ConfigError(f"Seed {record['id']} env must be an object")
    setup = env.get("setup", [])
    if not isinstance(setup, list) or not all(
        isinstance(command, str) and command.strip() and "\x00" not in command for command in setup
    ):
        raise ConfigError(f"Seed {record['id']} env.setup must be an array of shell commands")
    repo = source.get("repo")
    if repo is not None and not isinstance(repo, str):
        raise ConfigError(f"Seed {record['id']} source.repo must be a string")
    git_source = None
    if repo and repo != "n/a":
        git_source = _git_source(repo=repo, revision=env.get("repo_at"))
    result = {
        "id": record["id"],
        "instruction": instruction,
        "source": git_source,
        "setup": setup,
    }
    if "difficulty" in record:
        if not isinstance(record["difficulty"], str) or not record["difficulty"]:
            raise ConfigError(f"Seed {record['id']} difficulty must be a nonempty string")
        result["difficulty"] = record["difficulty"]
    return result


def _git_source(*, repo: str, revision: Any) -> dict:
    if not isinstance(revision, str) or not _SHA.fullmatch(revision):
        raise ConfigError("Git seed env.repo_at must be a fixed 40-character lowercase SHA")
    if "://" in repo:
        try:
            url = urlsplit(repo)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or any(character.isspace() or ord(character) < 32 for character in repo)
            ):
                raise ValueError
        except ValueError as exc:
            raise ConfigError("Git seed repository must be credential-free HTTPS") from exc
        identifier = url.path.removeprefix("/").removesuffix(".git")
        clone_url = repo
    else:
        identifier = repo
        clone_url = f"https://github.com/{repo}.git"
    if not _REPO.fullmatch(identifier) or any(
        part in {".", ".."} for part in identifier.split("/")
    ):
        raise ConfigError("Git seed repository must identify owner/repo")
    return {"kind": "git", "url": clone_url, "revision": revision, "repo": identifier}


def _setup_script(*, commands: list[str]) -> str:
    # Each bash -c receives the original string as one argument, including embedded newlines.
    # All nonempty legacy setup gets pip inside the venv; dependencies remain unpinned.
    seed = " --seed" if commands else ""
    lines = [
        "#!/usr/bin/env bash",
        "# Spec-0076/T1: setup executes only in the existing isolated task runtime.",
        "set -e",
        ': "${TASK_ROOT:?task repository is required}"',
        ': "${TASK_PYTHON:?managed Python is required}"',
        ': "${VIRTUAL_ENV:?task virtual environment is required}"',
        ': "${UV_BIN:?pinned uv executable is required}"',
        'cd "$TASK_ROOT"',
        f'"$UV_BIN" venv --allow-existing{seed} --python "$TASK_PYTHON" "$VIRTUAL_ENV"',
        'export PATH="$VIRTUAL_ENV/bin:$PATH"',
    ]
    lines.extend("bash -e -c " + shlex.quote(command) for command in commands)
    return "\n".join(lines) + "\n"


def _write_package(*, directory: Path, task: dict, interaction: str) -> None:
    directory.mkdir()
    (directory / "instruction.md").write_bytes(task["instruction"])
    (directory / "setup.sh").write_text(_setup_script(commands=task["setup"]), encoding="utf-8")
    lock = (
        "# Legacy env.setup is preserved; its dependencies were NOT automatically locked.\n"
        if task["setup"]
        else "# No external dependencies are declared by this imported task.\n"
    )
    (directory / "requirements.lock").write_text(lock, encoding="utf-8")
    source = task["source"]
    if source is None:
        (directory / "source").mkdir()
        (directory / "source/README.md").write_text(_SCRATCH, encoding="utf-8")
        source = {"kind": "local", "path": "source"}
    package = {
        "schema_version": 1,
        "kind": "ordinary",
        "id": task["id"],
        "instruction_file": "instruction.md",
        "source": source,
        "setup": {"script": "setup.sh", "requirements_lock": "requirements.lock"},
        "not_in_benchmark": True,
        "interaction": interaction,
    }
    if "difficulty" in task:
        package["difficulty"] = task["difficulty"]
    (directory / "task.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    load_task_package(directory / "task.json")


def _publish(*, tasks: list[dict], output: Path, interaction: str, source_sha256: str) -> dict:
    if not isinstance(interaction, str) or interaction not in _INTERACTIONS:
        raise ConfigError("Task interaction must be simulated_user or direct")
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ConfigError("Task import output must not already exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".task-import-", dir=output.parent))
    owned_output = False
    try:
        packages = stage / "tasks"
        packages.mkdir()
        for task in tasks:
            _write_package(directory=packages / task["id"], task=task, interaction=interaction)
        index = {
            "schema_version": 1,
            "source_sha256": source_sha256,
            "task_packages": [f"tasks/{task['id']}/task.json" for task in tasks],
            "tasks": [
                {
                    "id": task["id"],
                    "source_kind": "git" if task["source"] is not None else "local",
                    "task_package": f"tasks/{task['id']}/task.json",
                }
                for task in tasks
            ],
        }
        (stage / "tasks.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # mkdir is exclusive, including when another importer publishes after the precheck.
        output.mkdir()
        owned_output = True
        shutil.move(str(packages), str(output / "tasks"))
        shutil.move(str(stage / "tasks.json"), str(output / "tasks.json"))
    except BaseException:
        if owned_output:
            shutil.rmtree(output)
        raise
    finally:
        shutil.rmtree(stage)
    return {
        "ok": True,
        "output_dir": str(output),
        "task_packages": [str(output / "tasks" / task["id"] / "task.json") for task in tasks],
        "index_file": str(output / "tasks.json"),
        "source_sha256": source_sha256,
    }
