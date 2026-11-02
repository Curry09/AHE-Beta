"""Spec-0069/T1: compile operator inputs into a checksummed, credential-free run bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from ahe_beta.experiment.config import (
    ConfigError,
    config_hash,
    load_config_v2,
    load_task_packages,
    local_ci_enabled,
    read_json_document,
)
from ahe_beta.experiment.workload import (
    CONTRACT_VERSION,
    compile_session_plan,
    interaction_plan,
    read_session_plan,
    read_task_catalog,
    task_artifact_declarations,
    task_digest,
    task_material_path,
    validate_artifact_backend,
    validate_task_ids,
)

_SOURCE_ROOTS = (
    ".gitignore",
    "backend/ahe_beta",
    "backend/agent_defs",
    # Include runtime build dependencies explicitly, not historical/dev entrypoints.
    "backend/scripts/prepare_swebench_runtime_tree.py",
    "backend/deploy",
    "backend/harness_template",
    "release",
    "pyproject.toml",
    "uv.lock",
    "LICENSE",
    "README.md",
    "THIRD_PARTY.md",
)
_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".experiments",
    "node_modules",
    "secrets",
}
_EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".pyc"}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_materials(config_path: str | Path) -> dict[str, Any]:
    """Offline validation: no cloud calls, repository cloning, directories, or model requests."""
    config = load_config_v2(config_path)
    if "continuation" in config:
        return _check_parent_materials(config=config)
    tasks = load_task_packages(config)
    validate_task_ids(tasks)
    container_checks = {}
    for task in tasks:
        validate_artifact_backend(task, config["runtime"]["backend"])
        from ahe_beta.experiment.workload import validate_task_execution

        # Spec-0081/T2: container recipes do not invent a source tree or Python setup.
        if task.get("schema_version") == 3:
            from ahe_beta.experiment.task_environments.materials import (
                MaterialError,
            )
            from ahe_beta.experiment.task_environments.materials import (
                check_materials as check_container_materials,
            )

            _require_file(path=Path(task["instruction_file"]))
            if not Path(task["instruction_file"]).read_text(encoding="utf-8").strip():
                raise ConfigError(f"Task {task['id']} instruction must not be empty")
            try:
                container_checks[task["id"]] = check_container_materials(package=task)
            except MaterialError as exc:
                raise ConfigError(f"Task {task['id']}: {exc}") from exc
            validate_task_execution(
                task,
                source_root=None,
                fallback_seconds=config.get("runtime", {})
                .get("harness", {})
                .get("request_budget_seconds"),
            )
            continue

        validate_task_execution(
            task,
            source_root=Path(task["source"]["path"]) if task["source"]["kind"] == "local" else None,
            fallback_seconds=config.get("runtime", {})
            .get("harness", {})
            .get("request_budget_seconds"),
        )
        for path in [task["instruction_file"], *task["setup"].values()]:
            _require_file(path=Path(path))
        if not Path(task["instruction_file"]).read_text(encoding="utf-8").strip():
            raise ConfigError(f"Task {task['id']} instruction must not be empty")
        if task["source"]["kind"] == "local":
            directory = Path(task["source"]["path"])
            if not directory.is_dir():
                raise ConfigError(f"Task {task['id']} source directory missing: {directory}")
            _check_artifact_source_paths(task=task, root=directory)
            _snapshot_files(root=directory, paths=None)
    cards = read_json_document(path=Path(config["workload"]["persona_library"]))
    if not isinstance(cards, list) or not all(isinstance(card, dict) for card in cards):
        raise ConfigError("persona_library must contain a JSON array of persona cards")
    ids = [card.get("id") for card in cards]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ConfigError("persona library IDs must be nonempty and unique")
    by_id = {card["id"]: card for card in cards}
    selected = config["workload"]["persona_ids"]
    for persona_id in selected:
        if persona_id not in by_id:
            raise ConfigError(f"persona library does not contain {persona_id}")
        from ahe_beta.distill.library import validate_card
        from ahe_beta.user.sim.persona_io import card_to_persona

        card = by_id[persona_id]
        if card.get("authenticity") != "authentic":
            raise ConfigError(f"Persona {persona_id} is not admitted as authentic")
        try:
            validate_card(card)
            card_to_persona(card)
        except (ValueError, TypeError, KeyError) as exc:
            raise ConfigError(f"Invalid persona card {persona_id}: {exc}") from exc
    harness = config["harness"]
    if harness["source"] == "archive":
        archive = Path(harness["archive"])
        _require_file(path=archive)
        if sha256_file(archive) != harness["sha256"]:
            raise ConfigError("Harness archive SHA-256 mismatch")
        if local_ci_enabled(config):
            _check_ci_archive(path=archive)
        else:
            _check_archive(path=archive)
    else:
        seed = _controller_root() / "backend/harness_template"
        _require_file(path=seed / "entry.py")
        files = _snapshot_files(root=seed, paths=None)
        if local_ci_enabled(config):
            _check_ci_workflows(
                workflows={
                    name: (seed / name).read_bytes()
                    for name in files
                    if _is_ci_workflow(Path(name))
                }
            )
    report = {
        "ok": True,
        "config": config,
        "config_hash": config_hash(data=config),
        "task_packages": tasks,
        "preview": {"frozen": False},
        "persona_ids": selected,
        "persona_cards": [by_id[value] for value in selected],
        "interaction_plan": interaction_plan(config, tasks),
        "network_required_for_prepare": True,
    }
    if container_checks:
        report["container_materials"] = container_checks
    return report


def prepare_materials(
    config_path: str | Path,
    runs_dir: str | Path,
    secrets_file: str | Path | None = None,
    *,
    grading_plan: Path | None = None,
    grading_worker_public_key: Path | None = None,
) -> dict[str, Any]:
    """Atomically freeze a run. Credentials are referenced, never copied or archived."""
    report = check_materials(config_path)
    config = report["config"]
    from ahe_beta.experiment.assessment_worker import registration

    assessment_registration = registration(
        config=config,
        tasks=report["task_packages"],
        plan_path=grading_plan,
        public_key_path=grading_worker_public_key,
    )
    root = Path(runs_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    final_dir = root / run_id
    stage = Path(tempfile.mkdtemp(prefix=".preparing-", dir=root))
    try:
        if secrets_file is not None:
            secret_path = Path(secrets_file).expanduser().resolve()
            _require_file(path=secret_path)
            if stat.S_IMODE(secret_path.stat().st_mode) & 0o077:
                raise ConfigError("secrets-file permissions must be 0600 (or stricter)")
        else:
            secret_path = None
        for directory in (
            "materials",
            "source",
            "runtime",
            "checkpoints",
            "archive",
        ):
            (stage / directory).mkdir(mode=0o700)
        materials: dict[str, Any] = {}
        controller = _controller_root()
        snapshot = _snapshot_files(root=controller, paths=list(_SOURCE_ROOTS))
        controller_sha = _git_head(root=controller)
        _archive_snapshot(
            root=controller,
            files=snapshot,
            destination=stage / "materials/controller-source.tar.gz",
        )
        _register(
            materials=materials,
            key="controller_source_archive",
            path=stage / "materials/controller-source.tar.gz",
            stage=stage,
        )
        # Spec-0073/T1: every task is fully frozen before finalizing logical bindings.
        inherited = None
        if "continuation" in config:
            inherited = _freeze_parent_materials(stage=stage, config=config, materials=materials)
            tasks = inherited["tasks"]
        else:
            tasks = [
                _freeze_task(
                    stage=stage,
                    task=task,
                    materials=materials,
                    fallback_seconds=config.get("runtime", {})
                    .get("harness", {})
                    .get("request_budget_seconds"),
                )
                for task in report["task_packages"]
            ]
        catalog = {"contract_version": CONTRACT_VERSION, "tasks": tasks}
        catalog_path = stage / "materials/task-catalog.json"
        _write_json(path=catalog_path, value=catalog)
        _register(materials=materials, key="task_catalog", path=catalog_path, stage=stage)
        plan = compile_session_plan(
            config,
            catalog,
            materials["task_catalog"]["sha256"],
            inherited["pairs"] if inherited else None,
        )
        plan_path = stage / "materials/session-plan.json"
        _write_json(path=plan_path, value=plan)
        _register(materials=materials, key="session_plan", path=plan_path, stage=stage)
        harness_path = stage / "materials/harness.tar.gz"
        if inherited:
            shutil.copyfile(stage / inherited["harness_path"], harness_path)
        elif config["harness"]["source"] == "archive":
            shutil.copyfile(config["harness"]["archive"], harness_path)
        else:
            seed = controller / "backend/harness_template"
            _archive_snapshot(
                root=seed, files=_snapshot_files(root=seed, paths=None), destination=harness_path
            )
        _register(materials=materials, key="harness_archive", path=harness_path, stage=stage)
        if local_ci_enabled(config):
            # Validate the actual frozen Harness before any provider/repository fetch.
            _check_ci_archive(path=harness_path)
        cards = report["persona_cards"]
        roster = [
            {
                "id": card["id"],
                "strategy": card["dimensions"]["D3_interaction_style"]["on_offtrack"]["value"],
            }
            for card in cards
        ]
        distribution = dict(Counter(record["strategy"] for record in roster))
        documents = {
            "persona_library": cards,
            "persona_roster": {"personas": roster, "distribution": distribution},
            "config": config,
        }
        for key, document in documents.items():
            target = stage / "materials" / f"{key}.json"
            _write_json(path=target, value=document)
            _register(materials=materials, key=key, path=target, stage=stage)
        source_pins = _source_pins(config=config, controller=controller)
        openagents = source_pins["openagents"]
        oa_source = stage / "source/openagents"
        cache = root / ".cache/openagents" / openagents["revision"]
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            temporary_cache = Path(tempfile.mkdtemp(prefix=".fetch-", dir=cache.parent))
            shutil.rmtree(temporary_cache)
            try:
                _checkout_git(
                    url=openagents["repository"],
                    revision=openagents["revision"],
                    destination=temporary_cache,
                )
                temporary_cache.rename(cache)
            finally:
                if temporary_cache.exists():
                    shutil.rmtree(temporary_cache)
        if _git_head(root=cache) != openagents["revision"] or _git_dirty(root=cache):
            raise ConfigError("Cached OpenAgents source does not match its immutable revision")
        oa_source.mkdir()
        oa_files = _git_source_files(root=cache)
        _copy_snapshot(root=cache, files=oa_files, destination=oa_source)
        _archive_snapshot(
            root=oa_source, files=oa_files, destination=stage / "materials/openagents-source.tar.gz"
        )
        _register(
            materials=materials,
            key="openagents_source_archive",
            path=stage / "materials/openagents-source.tar.gz",
            stage=stage,
        )
        manifest = {
            "schema_version": 2,
            "run_id": run_id,
            "experiment_id": run_id,
            "run_dir": str(final_dir),
            "name": config["name"],
            "config": config,
            "config_hash": report["config_hash"],
            "controller_sha": controller_sha,
            "workload_contract_version": CONTRACT_VERSION,
            "catalog_hash": materials["task_catalog"]["sha256"],
            "plan_hash": materials["session_plan"]["sha256"],
            "created_at": datetime.now(UTC).isoformat(),
            "experiment_state": "PREPARED",
            "resource_state": "ABSENT",
            "collection_state": "NONE",
            "materials": materials,
            "source_pins": source_pins,
            "source_snapshot": {
                "base_commit": controller_sha,
                "dirty": _git_dirty(root=controller),
                "files": snapshot,
                "entrypoint": {
                    "kind": "module",
                    "module": "ahe_beta.experiment.controllers.unified",
                },
            },
            "secrets_file": str(secret_path) if secret_path else None,
        }
        if assessment_registration is not None:
            manifest["assessment_registration"] = assessment_registration
        if inherited:
            manifest["lineage"] = inherited["lineage"]
        _write_json(path=stage / "manifest.json", value=manifest)
        stage.chmod(0o700)
        stage.rename(final_dir)
        return manifest
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_materials(manifest: dict[str, Any]) -> None:
    """Reject missing/replaced frozen inputs before provisioning or resuming."""
    run_dir = Path(manifest["run_dir"]).resolve()
    for key, record in manifest["materials"].items():
        path = run_dir / record["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(run_dir):
            raise ConfigError(f"Unsafe frozen material path: {key}")
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ConfigError(f"Frozen material missing or hash mismatch: {key}")
    if config_hash(data=manifest["config"]) != manifest["config_hash"]:
        raise ConfigError("Frozen configuration hash mismatch")
    if local_ci_enabled(manifest["config"]):
        _check_ci_archive(path=run_dir / manifest["materials"]["harness_archive"]["path"])

    version = manifest.get("workload_contract_version")
    if "workload_contract_version" in manifest:
        if type(version) is not int or version != CONTRACT_VERSION:
            raise ConfigError("Unknown workload_contract_version")
        read_session_plan(run_dir, manifest)
        catalog = read_task_catalog(run_dir, manifest)
        for task in catalog["tasks"]:
            if task["package"].get("schema_version") == 3:
                from ahe_beta.experiment.task_environments.materials import (
                    execution_environment,
                )

                execution_environment(package=task["package"], run_root=run_dir)
                continue
            _verify_task_archive(
                path=task_material_path(run_dir, manifest, task, "source_archive"),
                expected=task["source_snapshot"]["files"],
                task_id=task["id"],
            )


def _verify_task_archive(*, path: Path, expected: dict[str, str], task_id: str) -> None:
    actual = {}
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                relative = Path(member.name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not member.isfile()
                    or member.name in actual
                    or not _safe_path(path=relative)
                ):
                    raise ConfigError(f"Unsafe task source archive member: {task_id}/{member.name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ConfigError(
                        f"Unreadable task source archive member: {task_id}/{member.name}"
                    )
                with stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                actual[member.name] = digest
    except (tarfile.TarError, OSError) as exc:
        raise ConfigError(f"Invalid frozen task source archive: {task_id}") from exc
    if actual != expected:
        raise ConfigError(f"Frozen task source inventory mismatch: {task_id}")


def _freeze_task(
    *,
    stage: Path,
    task: dict[str, Any],
    materials: dict[str, Any],
    fallback_seconds: float | None = None,
) -> dict[str, Any]:
    try:
        return _freeze_task_contents(
            stage=stage, task=task, materials=materials, fallback_seconds=fallback_seconds
        )
    except (ConfigError, OSError) as exc:
        raise ConfigError(f"Task {task['id']} freeze failed: {exc}") from exc


def _freeze_task_contents(
    *,
    stage: Path,
    task: dict[str, Any],
    materials: dict[str, Any],
    fallback_seconds: float | None = None,
) -> dict[str, Any]:
    if task.get("schema_version") == 3:
        return _freeze_container_task(
            stage=stage, task=task, materials=materials, fallback_seconds=fallback_seconds
        )
    task = json.loads(json.dumps(task))
    task_id = task["id"]
    directory = stage / "materials/tasks" / task_id
    directory.mkdir(parents=True)
    source = task["source"]
    source_dir = stage / "source/tasks" / task_id
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    if source["kind"] == "git":
        _checkout_git(url=source["url"], revision=source["revision"], destination=source_dir)
        if _git_head(root=source_dir) != source["revision"]:
            raise ConfigError(f"Task {task_id} fetched revision differs from fixed source")
    else:
        source_dir.mkdir()
        _copy_snapshot(
            root=Path(source["path"]),
            files=_snapshot_files(root=Path(source["path"]), paths=None),
            destination=source_dir,
        )
        source["path"] = str(source_dir.relative_to(stage))
    from ahe_beta.experiment.workload import validate_task_execution

    execution_verification = validate_task_execution(
        task, source_root=source_dir, fallback_seconds=fallback_seconds
    )
    _check_artifact_source_paths(task=task, root=source_dir)
    files = _snapshot_files(root=source_dir, paths=None)
    refs = {}
    hashes = {}
    for name, original, filename in (
        ("instruction", task["instruction_file"], "instruction.md"),
        ("script", task["setup"]["script"], "setup.sh"),
        ("requirements_lock", task["setup"]["requirements_lock"], "requirements.lock"),
    ):
        target = directory / filename
        shutil.copyfile(original, target)
        key = f"task:{task_id}:{name}"
        _register(materials=materials, key=key, path=target, stage=stage)
        refs[name] = key
        hashes[name] = materials[key]["sha256"]
        if name == "instruction":
            task["instruction_file"] = str(target.relative_to(stage))
        else:
            task["setup"][name] = str(target.relative_to(stage))
    archive = directory / "source.tar.gz"
    _archive_snapshot(root=source_dir, files=files, destination=archive)
    refs["source_archive"] = f"task:{task_id}:source_archive"
    _register(materials=materials, key=refs["source_archive"], path=archive, stage=stage)
    package_path = directory / "package.json"
    _write_json(path=package_path, value=task)
    refs["package"] = f"task:{task_id}:package"
    _register(materials=materials, key=refs["package"], path=package_path, stage=stage)
    record = {
        "id": task_id,
        "kind": task["kind"],
        "interaction": task["interaction"],
        "package": task,
        "source_snapshot": {"revision": source.get("revision"), "files": files},
        "content_hashes": hashes,
        "materials": refs,
    }
    if task.get("execution"):
        record["execution_verification"] = execution_verification
    record["digest"] = task_digest(record)
    return record


def _freeze_container_task(
    *, stage: Path, task: dict[str, Any], materials: dict[str, Any], fallback_seconds: float | None
) -> dict[str, Any]:
    """Spec-0081/T2: immutable container inputs retain the shared catalog identity."""
    from ahe_beta.experiment.task_environments.materials import (
        MaterialError,
        freeze_environment,
    )
    from ahe_beta.experiment.workload import validate_task_execution

    directory = stage / "materials/tasks" / task["id"]
    directory.mkdir(parents=True)
    try:
        frozen, files = freeze_environment(
            package=task,
            directory=directory,
            stage=stage,
            cache=stage.parent / ".cache/task-inputs",
        )
    except MaterialError as exc:
        raise ConfigError(str(exc)) from exc
    instruction = directory / "instruction.md"
    shutil.copyfile(task["instruction_file"], instruction)
    frozen["instruction_file"] = instruction.relative_to(stage).as_posix()
    files["instruction"] = instruction
    refs, hashes = {}, {}
    for name, path in files.items():
        key = f"task:{task['id']}:{name}"
        _register(materials=materials, key=key, path=path, stage=stage)
        refs[name], hashes[name] = key, materials[key]["sha256"]
    package_path = directory / "package.json"
    _write_json(path=package_path, value=frozen)
    refs["package"] = f"task:{task['id']}:package"
    _register(materials=materials, key=refs["package"], path=package_path, stage=stage)
    record = {
        "id": task["id"],
        "kind": task["kind"],
        "interaction": task["interaction"],
        "package": frozen,
        "source_snapshot": {"revision": task.get("source", {}).get("revision"), "files": {}},
        "content_hashes": hashes,
        "materials": refs,
    }
    if task.get("execution"):
        record["execution_verification"] = validate_task_execution(
            task, source_root=None, fallback_seconds=fallback_seconds
        )
    record["digest"] = task_digest(record)
    return record


def _check_artifact_source_paths(*, task: dict[str, Any], root: Path) -> None:
    """Reject unsafe existing targets; absent files may be produced by the task later."""
    for declaration in task_artifact_declarations(task):
        if declaration["source"] != "workspace":
            continue
        target = root
        parts = declaration["path"].split("/")
        for index, part in enumerate(parts):
            target = target / part
            if target.is_symlink():
                raise ConfigError(f"Artifact path rejects symbolic links: {declaration['path']}")
            if index < len(parts) - 1 and target.exists() and not target.is_dir():
                raise ConfigError(f"Artifact parent must be a directory: {declaration['path']}")
        if not target.resolve().is_relative_to(root.resolve()):
            raise ConfigError(f"Artifact path escapes task root: {declaration['path']}")
        if target.exists() and not target.is_file():
            raise ConfigError(f"Artifact target must be a regular file: {declaration['path']}")


def _controller_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _require_file(*, path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ConfigError(f"Required regular input file missing or symbolic: {path}")


def _safe_path(*, path: Path) -> bool:
    # Public .env.example templates belong to the source; private env siblings do not.
    return not (
        set(path.parts) & _EXCLUDED_PARTS
        or path.suffix.lower() in (_EXCLUDED_SUFFIXES | {".env"})
        or any(part.startswith(".env") for part in path.parts[:-1])
        or (path.name.startswith(".env") and path.name != ".env.example")
        or path.name in {"credentials.json", "hosts.yml", "settings.local.json"}
    )


def _snapshot_files(*, root: Path, paths: list[str] | None) -> dict[str, str]:
    files = {}
    roots = [root / item for item in paths] if paths is not None else [root]
    for selected in roots:
        if not selected.exists():
            continue
        candidates = [selected] if selected.is_file() else selected.rglob("*")
        for candidate in candidates:
            relative = candidate.relative_to(root)
            if not _safe_path(path=relative):
                continue
            if candidate.is_symlink():
                raise ConfigError(f"Source snapshot rejects symbolic links: {relative}")
            if candidate.is_file():
                files[str(relative)] = sha256_file(candidate)
    if not files:
        raise ConfigError(f"Source snapshot is empty: {root}")
    return dict(sorted(files.items()))


def _copy_snapshot(*, root: Path, files: dict[str, str], destination: Path) -> None:
    for relative, expected in files.items():
        source = root / relative
        if source.is_symlink() or sha256_file(source) != expected:
            raise ConfigError(f"Source changed during freeze: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(source.stat().st_mode & 0o777)


def _archive_snapshot(*, root: Path, files: dict[str, str], destination: Path) -> None:
    with tarfile.open(destination, "w:gz") as archive:
        for relative, expected in files.items():
            source = root / relative
            if source.is_symlink() or sha256_file(source) != expected:
                raise ConfigError(f"Source changed during archive: {relative}")
            archive.add(source, arcname=relative, recursive=False)


def _check_archive(*, path: Path) -> None:
    _validate_harness_archive(path=path, require_ci=False)


def _check_ci_archive(*, path: Path) -> None:
    _validate_harness_archive(path=path, require_ci=True)


def _validate_harness_archive(*, path: Path, require_ci: bool) -> None:
    try:
        with tarfile.open(path, "r:*") as archive:
            names = set()
            ci_names = set()
            workflows = {}
            root_entry = False
            for member in archive.getmembers():
                relative = Path(member.name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not _safe_path(path=relative)
                    or not (member.isfile() or member.isdir())
                ):
                    raise ConfigError(f"Unsafe Harness archive member: {member.name}")
                names.add(member.name.lstrip("./"))
                if require_ci:
                    # Spec-0077/T1: inspect without extraction; reject overwrite ambiguity.
                    normalized = str(relative)
                    if normalized in ci_names:
                        raise ConfigError(f"Duplicate Harness archive member: {member.name}")
                    ci_names.add(normalized)
                    root_entry = root_entry or (normalized == "entry.py" and member.isfile())
                    if member.isfile() and _is_ci_workflow(relative):
                        if member.size > 1024 * 1024:
                            raise ConfigError(f"Harness CI workflow is too large: {member.name}")
                        stream = archive.extractfile(member)
                        if stream is None:
                            raise ConfigError(f"Unreadable Harness CI workflow: {member.name}")
                        with stream:
                            workflows[normalized] = stream.read(1024 * 1024 + 1)
            if not any(name == "entry.py" or name.endswith("/entry.py") for name in names):
                raise ConfigError("Harness archive must contain entry.py")
            if require_ci:
                if not root_entry:
                    raise ConfigError("CI Harness archive requires entry.py at the repository root")
                _check_ci_workflows(workflows=workflows)
    except (tarfile.TarError, OSError) as exc:
        raise ConfigError(f"Invalid Harness archive {path}: {exc}") from exc


def _is_ci_workflow(path: Path) -> bool:
    return path.parent == Path(".gitea/workflows") and path.suffix.lower() in {".yml", ".yaml"}


def _check_ci_workflows(*, workflows: dict[str, bytes]) -> None:
    """Spec-0077/T1: structural precheck only; real execution readiness belongs to T2."""
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    usable = False
    for name, content in workflows.items():
        if len(content) > 1024 * 1024:
            raise ConfigError(f"Harness CI workflow is too large: {name}")
        try:
            # YAML 1.2 keeps the Actions 'on' key a string and rejects duplicate keys.
            document = YAML(typ="safe").load(content.decode("utf-8"))
        except (YAMLError, UnicodeError, ValueError) as exc:
            raise ConfigError(f"Invalid Harness CI workflow: {name}") from exc
        if not isinstance(document, dict):
            raise ConfigError(f"Unsupported Harness CI workflow: {name}")
        trigger = document.get("on")
        if isinstance(trigger, str):
            covers_pr = trigger == "pull_request"
        elif isinstance(trigger, list):
            covers_pr = "pull_request" in trigger and all(
                isinstance(event, str) for event in trigger
            )
        elif isinstance(trigger, dict):
            # Event filters can skip a current PR entirely; do not approve that gate.
            covers_pr = "pull_request" in trigger and trigger["pull_request"] in (None, {})
        else:
            covers_pr = False
        jobs = document.get("jobs")
        if not covers_pr or not isinstance(jobs, dict) or not jobs:
            continue
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if (
                job.get("runs-on") == "ubuntu-latest"
                and job.get("if", True) is True
                and not job.get("strategy")
                and not job.get("continue-on-error")
                and isinstance(steps, list)
                and steps
                and all(_is_ci_step(step) for step in steps)
            ):
                usable = True
    if not usable:
        raise ConfigError(
            "CI Harness requires a usable .gitea/workflows YAML workflow covering "
            "pull_request with an unconditional ubuntu-latest job and executable steps"
        )


def _is_ci_step(step: Any) -> bool:
    if not isinstance(step, dict):
        return False
    commands = [step.get(key) for key in ("run", "uses") if key in step]
    return (
        len(commands) == 1
        and isinstance(commands[0], str)
        and bool(commands[0].strip())
        and step.get("if", True) is True
        and not step.get("continue-on-error")
    )


def _git_head(*, root: Path) -> str:
    return _git(root=root, args=["rev-parse", "HEAD"]).strip()


def _git_dirty(*, root: Path) -> bool:
    return bool(_git(root=root, args=["status", "--porcelain"]).strip())


def _git(*, root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], check=True, text=True, capture_output=True, timeout=120
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Do not echo subprocess argv/errors: remote error messages may contain credentials.
        raise ConfigError(
            "Git operation failed; verify repository permissions (gh auth setup-git for private GitHub repositories), network access, and fixed revision"
        ) from exc


def _checkout_git(*, url: str, revision: str, destination: Path) -> None:
    destination.mkdir()
    _git(root=destination, args=["init", "--quiet"])
    _git(root=destination, args=["fetch", "--quiet", "--depth", "1", url, revision])
    _git(root=destination, args=["checkout", "--quiet", "--detach", "FETCH_HEAD"])
    if _git_head(root=destination) != revision:
        raise ConfigError("Fetched Git source does not match the fixed revision")


def _git_source_files(*, root: Path) -> dict[str, str]:
    files = {}
    for relative in _git(root=root, args=["ls-files", "-z"]).split("\0"):
        if not relative or not _safe_path(path=Path(relative)):
            continue
        path = root / relative
        if path.is_symlink():
            raise ConfigError(f"Git source archive rejects symbolic link: {relative}")
        if path.is_file():
            files[relative] = sha256_file(path)
    return files


def _source_pins(*, config: dict[str, Any], controller: Path) -> dict[str, Any]:
    compatibility = read_json_document(path=controller / "release/compatibility.json")
    reader = compatibility.get("observation_transport", {})
    execution_reader = compatibility.get("execution_evidence", {})
    oa_revision = reader.get("reader_release_commit") or reader.get("reader_candidate_commit")
    if execution_reader:
        oa_revision = execution_reader.get("reader_release_commit") or execution_reader.get(
            "reader_candidate_commit"
        )
    explicit = config.get("source", {})
    locked_nexau = _locked_nexau_source(controller=controller)
    published_nexau = compatibility["nexau"]
    if published_nexau["commit"] != locked_nexau["revision"] or published_nexau[
        "repository"
    ].removesuffix(".git") != locked_nexau["repository"].removesuffix(".git"):
        raise ConfigError("NexAU release compatibility does not match the controller uv.lock pin")
    requested_nexau = explicit.get("nexau", locked_nexau)
    if requested_nexau["revision"] != locked_nexau["revision"] or requested_nexau[
        "repository"
    ].removesuffix(".git") != locked_nexau["repository"].removesuffix(".git"):
        raise ConfigError(
            "NexAU runtime is locked by controller uv.lock; source.nexau must match that repository and revision"
        )
    if "openagents" not in explicit and not oa_revision:
        raise ConfigError(
            "No verified OpenAgents execution-contract reader pin: set source.openagents "
            "to the paired Spec-0093 revision or publish execution_evidence.reader_candidate_commit"
        )
    return {
        "openagents": explicit.get("openagents")
        or {"repository": compatibility["openagents"]["repository"], "revision": oa_revision},
        "nexau": locked_nexau,
        "reader_status": "candidate" if not reader.get("reader_release_commit") else "release",
        "execution_evidence_schema_version": 1,
    }


def _write_dataset(*, task: dict[str, Any], instruction: str, destination: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ConfigError(
            "SWE material generation requires: uv sync --locked --extra experiments"
        ) from exc
    row = {
        "instance_id": task["id"],
        "repo": task["source"]["repo"],
        "base_commit": task["source"]["revision"],
        "problem_statement": instruction,
        "difficulty": task.get("difficulty", "unknown"),
    }
    pq.write_table(pa.Table.from_pylist([row]), destination)


def _register(*, materials: dict[str, Any], key: str, path: Path, stage: Path) -> None:
    materials[key] = {
        "path": str(path.relative_to(stage)),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _write_json(*, path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _locked_nexau_source(*, controller: Path) -> dict[str, str]:
    project = tomllib.loads((controller / "pyproject.toml").read_text())
    lock = tomllib.loads((controller / "uv.lock").read_text())
    dependencies = project["project"]["dependencies"]
    declaration = next((value for value in dependencies if value.startswith("nexau @ git+")), None)
    package = next((value for value in lock["package"] if value["name"] == "nexau"), None)
    if declaration is None or package is None or "git" not in package.get("source", {}):
        raise ConfigError("Controller must lock NexAU as an immutable Git dependency")
    parsed = urlsplit(package["source"]["git"])
    repository = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    revision = parsed.fragment
    declared_url = declaration.removeprefix("nexau @ git+").strip()
    if (
        len(revision) != 40
        or declared_url != f"{repository}@{revision}"
        or parse_qs(parsed.query).get("rev") != [revision]
    ):
        raise ConfigError("NexAU pyproject declaration and uv.lock immutable revision disagree")
    return {"repository": repository, "revision": revision}


# Spec-0079/T4: source validation is shared by offline check and atomic prepare.
def _check_parent_materials(*, config: dict[str, Any]) -> dict[str, Any]:
    from ahe_beta.experiment.continuation.source import load_continuation_source

    source = load_continuation_source(**config["continuation"])
    for task in source.tasks:
        validate_artifact_backend(task["package"], config["runtime"]["backend"])
    if len(source.pairs) != config["rounds"]["sessions_per_round"]:
        raise ConfigError("sessions_per_round must equal the selected parent boundary")
    from ahe_beta.experiment.continuation.forge import pending_report

    if any(pending_report(report) for report in source.reports) and any(
        config["roles"][key] < 1 for key in ("triager", "architect")
    ):
        raise ConfigError("Pending parent reports require at least one triager and architect")
    if local_ci_enabled(config):
        import io

        with tarfile.open(
            fileobj=io.BytesIO(source.read(source.export["harness"]["archive"]))
        ) as bundle:
            workflows = {
                member.name: bundle.extractfile(member).read()
                for member in bundle.getmembers()
                if member.isfile() and _is_ci_workflow(Path(member.name))
            }
        _check_ci_workflows(workflows=workflows)
    pairs = [[pair["persona_id"], pair["task_id"]] for pair in source.pairs]
    return {
        "ok": True,
        "config": config,
        "config_hash": config_hash(data=config),
        "task_packages": source.tasks,
        "persona_cards": source.personas,
        # Spec-0080/T3: freeze each card once while preserving every execution pair.
        "persona_ids": [card["id"] for card in source.personas],
        "interaction_plan": [pairs for _ in range(config["rounds"]["count"])],
        "preview": {"frozen": False},
        "continuation": source.summary(),
        "network_required_for_prepare": True,
    }


def _freeze_parent_materials(
    *, stage: Path, config: dict[str, Any], materials: dict[str, Any]
) -> dict[str, Any]:
    from ahe_beta.experiment.continuation.source import load_continuation_source

    source = load_continuation_source(**config["continuation"])
    parent_root = Path("materials/continuation/parent")
    selected_paths = {
        "manifest.json",
        "collection.json",
        "checkpoints/recovery.json",
        "runtime/continuation-export.json",
        source.export["harness"]["archive"],
        source.export["forge"]["path"],
    }
    selected_paths.update(record["path"] for record in source.export["boundary"]["sessions"])
    for record in source.export["boundary"]["sessions"]:
        observation = record.get("observation_path")
        if observation:
            selected_paths.update(
                path
                for path in source.files
                if path == observation or path.startswith(observation.rstrip("/") + "/")
            )
    for key in source.export["material_keys"]:
        selected_paths.add(source.manifest["materials"][key]["path"])
    for path in sorted(selected_paths):
        target = stage / parent_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read(path))
        _register(materials=materials, key="continuation:" + path, path=target, stage=stage)
    # Tasks keep their exact original records and registry key identities.
    for task in source.tasks:
        for key in task["materials"].values():
            record = source.manifest["materials"][key]
            target = stage / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(record["path"]))
            _register(materials=materials, key=key, path=target, stage=stage)
        if task["package"].get("schema_version") == 3:
            continue
        # Runtime source recipe reads the same frozen archive; restore its logical directory.
        archive_path = stage / materials[task["materials"]["source_archive"]]["path"]
        destination = stage / "source/tasks" / task["id"]
        destination.mkdir(parents=True)
        with tarfile.open(archive_path, "r:gz") as bundle:
            bundle.extractall(destination, filter="data")
    parent = source.manifest
    lineage = {
        "parent_run_id": parent["run_id"],
        "parent_config_hash": parent["config_hash"],
        "parent_controller_sha": parent["controller_sha"],
        "parent_plan_hash": parent["plan_hash"],
        "parent_archive_sha256": source.archive_sha256,
        "base_round": source.export["boundary"]["lineage_round"],
        "parent_user_sha": source.export["boundary"]["user_sha"],
        "parent_tree_id": source.export["harness"]["tree_id"],
        "differences": {
            key: {"parent": parent["config"].get(key), "child": config.get(key)}
            for key in ("models", "runtime", "policies")
            if parent["config"].get(key) != config.get(key)
        },
    }
    inherited = {
        "export": source.export,
        "pairs": source.pairs,
        "lineage": lineage,
        "parent_root": parent_root.as_posix(),
        "source_summary": source.summary(),
    }
    target = stage / "materials/continuation/input.json"
    _write_json(path=target, value=inherited)
    _register(materials=materials, key="continuation_input", path=target, stage=stage)
    return {
        **inherited,
        "tasks": source.tasks,
        "harness_path": (parent_root / source.export["harness"]["archive"]).as_posix(),
    }
