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

from auto_designer.experiment.config import (
    ConfigError,
    config_hash,
    load_config_v2,
    load_task_package,
    read_json_document,
)

_SOURCE_ROOTS = (
    ".gitignore",
    "backend/auto_designer",
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


def _interaction_plan(*, config: dict[str, Any], task_id: str) -> list[list[list[str]]]:
    """Validate every round before freezing, or generate the default rotating plan."""
    workload = config["workload"]
    personas = workload["persona_ids"]
    rounds = config["rounds"]["count"]
    plan = workload.get("interaction_plan")
    if plan is None:
        return [[[personas[index % len(personas)], task_id]] for index in range(rounds)]
    if not isinstance(plan, list) or len(plan) != rounds:
        raise ConfigError(f"workload.interaction_plan must contain {rounds} rounds")
    for round_no, picks in enumerate(plan, start=1):
        label = f"workload.interaction_plan round {round_no}"
        if not isinstance(picks, list) or not picks:
            raise ConfigError(f"{label} must contain sessions")
        seen_personas: set[str] = set()
        seen_tasks: set[str] = set()
        for pair in picks:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(value, str) for value in pair)
            ):
                raise ConfigError(f"{label} must contain [persona_id, task_id] pairs")
            persona, task = pair
            if persona not in personas:
                raise ConfigError(f"{label} references unselected persona {persona}")
            if task != task_id:
                raise ConfigError(f"{label} references unknown task {task}")
            if persona in seen_personas or task in seen_tasks:
                raise ConfigError(f"{label} contains duplicate persona or task")
            seen_personas.add(persona)
            seen_tasks.add(task)
        if len(picks) != config["rounds"]["sessions_per_round"]:
            raise ConfigError(f"{label} does not match rounds.sessions_per_round")
    return plan


def check_materials(config_path: str | Path) -> dict[str, Any]:
    """Offline validation: no cloud calls, repository cloning, directories, or model requests."""
    config = load_config_v2(config_path)
    task = load_task_package(config["workload"]["task_package"])
    if task["kind"] != config["workload"]["kind"]:
        raise ConfigError("task package kind differs from workload.kind")
    # The current public task package contains one task. SWE's frozen plan requires unique
    # instances in a round: refuse broader-looking configuration until a task-pool schema exists.
    if config["rounds"]["sessions_per_round"] != 1:
        raise ConfigError(
            "task-package-v1 supports sessions_per_round=1; multi-task pools are not yet supported"
        )
    for path in [task["instruction_file"], *task["setup"].values()]:
        _require_file(path=Path(path))
    if not Path(task["instruction_file"]).read_text(encoding="utf-8").strip():
        raise ConfigError("Task instruction must not be empty")
    if task["source"]["kind"] == "local":
        directory = Path(task["source"]["path"])
        if not directory.is_dir():
            raise ConfigError(f"Task source directory missing: {directory}")
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
        from auto_designer.distill.library import validate_card
        from auto_designer.user.sim.persona_io import card_to_persona

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
        _check_archive(path=archive)
    else:
        seed = _controller_root() / "backend/harness_template"
        _require_file(path=seed / "entry.py")
        _snapshot_files(root=seed, paths=None)
    return {
        "ok": True,
        "config": config,
        "config_hash": config_hash(data=config),
        "task_package": task,
        "persona_ids": selected,
        "persona_cards": [by_id[value] for value in selected],
        "interaction_plan": _interaction_plan(config=config, task_id=task["id"]),
        "network_required_for_prepare": True,
    }


def prepare_materials(
    config_path: str | Path, runs_dir: str | Path, secrets_file: str | Path | None = None
) -> dict[str, Any]:
    """Atomically freeze a run. Credentials are referenced, never copied or archived."""
    report = check_materials(config_path)
    config = report["config"]
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
        task = json.loads(json.dumps(report["task_package"]))
        task_source = task["source"]
        source_directory = stage / "source/task"
        if task_source["kind"] == "git":
            _checkout_git(
                url=task_source["url"],
                revision=task_source["revision"],
                destination=source_directory,
            )
        else:
            source_directory.mkdir()
            _copy_snapshot(
                root=Path(task_source["path"]),
                files=_snapshot_files(root=Path(task_source["path"]), paths=None),
                destination=source_directory,
            )
        source_files = _snapshot_files(root=source_directory, paths=None)
        _archive_snapshot(
            root=source_directory,
            files=source_files,
            destination=stage / "materials/task-source.tar.gz",
        )
        _register(
            materials=materials,
            key="task_source_archive",
            path=stage / "materials/task-source.tar.gz",
            stage=stage,
        )
        for field, key in (("instruction_file", "task_instruction"),):
            target = stage / "materials/instruction.md"
            shutil.copyfile(task[field], target)
            task[field] = str(target.relative_to(stage))
            _register(materials=materials, key=key, path=target, stage=stage)
        for field in ("script", "requirements_lock"):
            target = (
                stage / "materials" / ("setup.sh" if field == "script" else "requirements.lock")
            )
            shutil.copyfile(task["setup"][field], target)
            task["setup"][field] = str(target.relative_to(stage))
            _register(materials=materials, key=field, path=target, stage=stage)
        if task_source["kind"] == "local":
            task_source["path"] = "source/task"
        harness_path = stage / "materials/harness.tar.gz"
        if config["harness"]["source"] == "archive":
            shutil.copyfile(config["harness"]["archive"], harness_path)
        else:
            seed = controller / "backend/harness_template"
            _archive_snapshot(
                root=seed, files=_snapshot_files(root=seed, paths=None), destination=harness_path
            )
        _register(materials=materials, key="harness_archive", path=harness_path, stage=stage)
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
            "pool": {"instances": [{"instance_id": task["id"]}]},
            "interaction_plan": report["interaction_plan"],
            "task_package": task,
            "config": config,
        }
        for key, document in documents.items():
            target = stage / "materials" / f"{key}.json"
            _write_json(path=target, value=document)
            _register(materials=materials, key=key, path=target, stage=stage)
        if task["kind"] == "swebench":
            _write_dataset(
                task=task,
                instruction=(stage / task["instruction_file"]).read_text(),
                destination=stage / "materials/instances.parquet",
            )
            _register(
                materials=materials,
                key="dataset",
                path=stage / "materials/instances.parquet",
                stage=stage,
            )
        else:
            # Existing ordinary seed cards retain provenance. Runtime's context maps the
            # frozen source snapshot into a prebuilt workspace; it must not re-clone HEAD.
            seed_card = {
                "id": task["id"],
                "task": {"prompt": (stage / task["instruction_file"]).read_text()},
                "source": {"not_in_benchmark": True},
                "env": {"snapshot": "source/task", "setup_script": task["setup"]["script"]},
            }
            _write_json(path=stage / "materials/seeds.json", value=[seed_card])
            _register(
                materials=materials, key="seeds", path=stage / "materials/seeds.json", stage=stage
            )
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
            "plan_hash": materials["interaction_plan"]["sha256"],
            "task_package": task,
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
                    "module": "auto_designer.experiment.controllers."
                    + ("swebench" if task["kind"] == "swebench" else "ordinary"),
                },
            },
            "task_source_snapshot": {
                "revision": task_source.get("revision"),
                "files": source_files,
            },
            "secrets_file": str(secret_path) if secret_path else None,
        }
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
    try:
        with tarfile.open(path, "r:*") as archive:
            names = set()
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
            if not any(name == "entry.py" or name.endswith("/entry.py") for name in names):
                raise ConfigError("Harness archive must contain entry.py")
    except (tarfile.TarError, OSError) as exc:
        raise ConfigError(f"Invalid Harness archive {path}: {exc}") from exc


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
    oa_revision = reader.get("reader_release_commit") or reader.get("reader_candidate_commit")
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
            "No verified OpenAgents reader pin: set source.openagents revision or publish reader_candidate_commit"
        )
    return {
        "openagents": explicit.get("openagents")
        or {"repository": compatibility["openagents"]["repository"], "revision": oa_revision},
        "nexau": locked_nexau,
        "reader_status": "candidate" if not reader.get("reader_release_commit") else "release",
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
