#!/usr/bin/env python3
"""One-command controller for a pinned, isolated, auditable evolution run.

The controller deliberately keeps model credentials out of config/manifest.  It consumes the
named 0600 profile, provisions only this experiment's Gitea and egress proxy, bootstraps a private
repository, writes a private ExperimentContext, and launches the existing closed-loop runner with
the frozen persona/task plan.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
SOURCE_ROOT = REPOSITORY.parent
sys.path.insert(0, str(BACKEND))

from auto_designer.experiment import runtime  # noqa: E402
from auto_designer.experiment.config import (  # noqa: E402
    ConfigError,
    ExperimentConfig,
    config_hash,
    experiment_paths,
    experiments_root,
)
from auto_designer.experiment.infrastructure import (  # noqa: E402
    compose_argv,
    render_stack,
)
from auto_designer.experiment.manifest import (  # noqa: E402
    append_journal,
    last_state,
    read_manifest,
    recovery_identity,
)
from auto_designer.loop.recovery import RecoveryError, RecoveryIdentity, RecoveryStore  # noqa: E402

_REQUIRED_ROSTER = {"user", "triager", "synthesizer", "divergent", "owner", "developer"}
_PROFILE_KEYS = {
    "USER_LLM_BASE_URL",
    "USER_LLM_API_KEY",
    "DEMAND_LLM_BASE_URL",
    "DEMAND_LLM_API_KEY",
    "HARNESS_LLM_BASE_URL",
    "HARNESS_LLM_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
}


class AuditLaunchError(RuntimeError):
    """Reject drift, unsafe resume, missing credentials, or failed infrastructure."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditLaunchError(f"JSON 不可读：{path}: {exc}") from exc


def _atomic_private_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AuditLaunchError(
            f"命令失败 ({result.returncode})：{' '.join(command[:5])}: "
            f"{result.stderr.strip()[:400]}"
        )
    return result


@dataclass(frozen=True)
class FrozenExperiment:
    config_path: Path
    config: ExperimentConfig
    root: Path
    paths: dict[str, Path]
    raw: dict[str, Any]

    @property
    def experiment_id(self) -> str:
        return self.config.experiment_id

    @property
    def execution(self) -> dict[str, Any]:
        return dict(self.raw["execution"])

    @property
    def roster(self) -> dict[str, int]:
        return {key: int(value) for key, value in self.raw["roster"].items()}

    @property
    def model_profile_path(self) -> Path:
        profile = str(self.config.models.get("profile") or "")
        return self.root.parent / ".profiles" / f"{profile}.env"

    @classmethod
    def load(cls, *, config_path: Path, root: Path) -> FrozenExperiment:
        config_path = config_path.expanduser().resolve()
        config = runtime.load_config(path=config_path)
        paths = experiment_paths(experiment_id=config.experiment_id, root=root)
        frozen = cls(
            config_path=config_path,
            config=config,
            root=paths["root"],
            paths=paths,
            raw=config.raw,
        )
        frozen.validate_contract()
        return frozen

    def _pinned_file(self, node: dict[str, Any], *, label: str) -> Path:
        path = Path(str(node.get("path") or "")).expanduser().resolve()
        expected = str(node.get("sha256") or "")
        if not path.is_file():
            raise AuditLaunchError(f"{label} 不存在：{path}")
        actual = _sha256(path)
        if actual != expected:
            raise AuditLaunchError(f"{label} SHA 漂移：expected={expected} actual={actual}")
        return path

    def validate_contract(self) -> None:
        if self.config.mode not in {"full-evolution", "user-only"}:
            raise AuditLaunchError("审计闭环只接受 mode=full-evolution 或 user-only")
        execution = self.raw.get("execution")
        if not isinstance(execution, dict) or execution.get("runner") != "swebench-closed-loop":
            raise AuditLaunchError("execution.runner 必须为 swebench-closed-loop")
        if type(execution.get("synthesizer_grouping", False)) is not bool:
            raise AuditLaunchError("execution.synthesizer_grouping 必须为 boolean")
        rounds = int(execution.get("total_rounds") or 0)
        if self.config.mode == "full-evolution":
            if rounds < 2 or not execution.get("final_round_users_only"):
                raise AuditLaunchError("完整闭环要求至少两轮且末轮 users-only")
            if not execution.get("wait_for_delivery_between_rounds"):
                raise AuditLaunchError("闭环必须等待本轮交付封口后再切轮")
        elif rounds != 1 or not execution.get("final_round_users_only"):
            raise AuditLaunchError("user-only canary 必须恰好一轮且为 users-only")

        roster = self.raw.get("roster")
        if not isinstance(roster, dict) or set(roster) != _REQUIRED_ROSTER:
            raise AuditLaunchError(f"roster 必须且只能包含 {sorted(_REQUIRED_ROSTER)}")
        normalized = self.roster
        if any(value < 0 for value in normalized.values()):
            raise AuditLaunchError("roster 计数不得为负")
        if self.config.mode == "full-evolution" and normalized["owner"] != 1:
            raise AuditLaunchError("full-evolution 的 owner 必须为 1")
        if self.config.mode == "user-only" and any(
            normalized[role] != 0
            for role in ("triager", "synthesizer", "divergent", "owner", "developer")
        ):
            raise AuditLaunchError("user-only canary 除 user 外的 roster 必须全为 0")
        capacity = self.config.capacity
        if int(capacity.get("user_parallel") or 0) != normalized["user"]:
            raise AuditLaunchError("capacity.user_parallel 必须等于 roster.user")
        if int(capacity.get("delivery_parallel") or 0) != normalized["developer"]:
            raise AuditLaunchError("capacity.delivery_parallel 必须等于 roster.developer")

        source = self.raw.get("source") or {}
        harness = self._pinned_file(dict(source.get("harness") or {}), label="Harness archive")
        if not harness.name.endswith(".tar.gz"):
            raise AuditLaunchError("Harness archive 必须为 .tar.gz")
        personas = self.raw.get("personas") or {}
        library_path = self._pinned_file(
            dict(personas.get("library") or {}), label="persona library"
        )
        roster_path = self._pinned_file(dict(personas.get("roster") or {}), label="persona roster")
        workload = self.raw.get("workload") or {}
        dataset_path = self._pinned_file(
            dict(workload.get("dataset") or {}), label="SWE-bench dataset"
        )
        if dataset_path.suffix != ".parquet":
            raise AuditLaunchError("SWE-bench dataset 必须为 parquet")
        pool_path = self._pinned_file(dict(workload.get("pool") or {}), label="SWE-bench pool")
        plan_path = self._pinned_file(dict(execution.get("plan") or {}), label="interaction plan")
        self._validate_plan(
            library_path=library_path,
            roster_path=roster_path,
            pool_path=pool_path,
            plan_path=plan_path,
            rounds=rounds,
        )

        for role in ("user", "harness", "triage", "synthesizer", "divergent", "owner", "delivery"):
            if not str(self.config.models.get(role) or ""):
                raise AuditLaunchError(f"models.{role} 缺失")
        for role in ("gitea", "runner", "egress", "vigil", "seed"):
            reference = str(self.config.images.get(role) or "")
            if not reference or ":latest" in reference or not reference.rsplit("sha256:", 1)[-1]:
                raise AuditLaunchError(f"images.{role} 必须为不可变引用")

    def _validate_plan(
        self,
        *,
        library_path: Path,
        roster_path: Path,
        pool_path: Path,
        plan_path: Path,
        rounds: int,
    ) -> None:
        library = _load_json(library_path)
        persona_doc = _load_json(roster_path)
        pool = _load_json(pool_path)
        plan = _load_json(plan_path)
        if not isinstance(library, list) or not isinstance(persona_doc, dict):
            raise AuditLaunchError("persona library/roster 结构非法")
        cards = {str(item["id"]): item for item in library}
        records = persona_doc.get("personas") or []
        persona_ids = [str(item["id"]) for item in records]
        strategies = {str(item["id"]): str(item["strategy"]) for item in records}
        if len(persona_ids) != self.roster["user"] or len(set(persona_ids)) != len(persona_ids):
            raise AuditLaunchError("persona roster 数量必须等于 roster.user 且 ID 唯一")
        for persona_id, strategy in strategies.items():
            try:
                actual = cards[persona_id]["dimensions"]["D3_interaction_style"]["on_offtrack"][
                    "value"
                ]
            except (KeyError, TypeError) as exc:
                raise AuditLaunchError(f"persona 卡缺策略：{persona_id}") from exc
            if actual != strategy:
                raise AuditLaunchError(f"persona 策略漂移：{persona_id}: {strategy} != {actual}")
        pool_ids = {str(item["instance_id"]) for item in pool.get("instances") or []}
        if not isinstance(plan, list) or len(plan) != rounds:
            raise AuditLaunchError(f"interaction plan 必须恰好 {rounds} 轮")
        expected_distribution = {
            str(key): int(value) for key, value in (persona_doc.get("distribution") or {}).items()
        }
        for index, round_plan in enumerate(plan, start=1):
            if not isinstance(round_plan, list) or len(round_plan) != self.roster["user"]:
                raise AuditLaunchError(f"第 {index} 轮必须恰好 {self.roster['user']} 个 session")
            round_personas = [str(pair[0]) for pair in round_plan]
            round_instances = [str(pair[1]) for pair in round_plan]
            if set(round_personas) != set(persona_ids):
                raise AuditLaunchError(f"第 {index} 轮 persona 集与 roster 不一致")
            if (
                len(set(round_instances)) != len(round_instances)
                or not set(round_instances) <= pool_ids
            ):
                raise AuditLaunchError(f"第 {index} 轮 instance 非唯一或越出题池")
            observed = {key: 0 for key in expected_distribution}
            for persona_id in round_personas:
                observed[strategies[persona_id]] = observed.get(strategies[persona_id], 0) + 1
            if observed != expected_distribution:
                raise AuditLaunchError(
                    f"第 {index} 轮 persona 配比漂移：{observed} != {expected_distribution}"
                )


def _load_profile(path: Path) -> dict[str, str]:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise AuditLaunchError(f"模型 profile 不存在：{path}") from exc
    if mode & 0o077:
        raise AuditLaunchError(f"模型 profile 必须为 0600：{path}")
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip() or "\x00" in value:
            raise AuditLaunchError(f"模型 profile 第 {line_number} 行非法")
        values[key.strip()] = value.strip().strip('"')
    missing = sorted(key for key in _PROFILE_KEYS if not values.get(key))
    if missing:
        raise AuditLaunchError(f"模型 profile 缺字段：{', '.join(missing)}")
    return values


def _verify_git_pins(spec: FrozenExperiment) -> dict[str, str]:
    repositories = {
        "auto-designer": (REPOSITORY, str(spec.raw["source"]["auto_designer_sha"])),
        "openagents": (SOURCE_ROOT / "OpenAgents", str(spec.raw["source"]["openagents_sha"])),
        "nexau": (SOURCE_ROOT / "NexAU", str(spec.raw["source"]["nexau_sha"])),
    }
    resolved: dict[str, str] = {}
    for name, (repository, revision) in repositories.items():
        result = _run(["git", "-C", str(repository), "rev-parse", f"{revision}^{{commit}}"])
        resolved[name] = result.stdout.strip()
    controller_head = _run(["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"]).stdout.strip()
    if controller_head != resolved["auto-designer"]:
        raise AuditLaunchError(
            "controller HEAD 与 source.auto_designer_sha 不一致："
            f"head={controller_head} pin={resolved['auto-designer']}"
        )
    return resolved


def _verify_images(spec: FrozenExperiment) -> None:
    for role, reference in spec.config.images.items():
        inspected = _run(["docker", "image", "inspect", str(reference)])
        if role == "seed":
            info = json.loads(inspected.stdout)[0]
            labels = (info.get("Config") or {}).get("Labels") or {}
            if labels.get("org.auto-designer.seed-runtime") != "1":
                raise AuditLaunchError(
                    "images.seed 不是 runnable v1；禁止使用 storage-only seed 启动实验"
                )


def _verify_official_evaluator() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import swebench; print(swebench.__version__)"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AuditLaunchError(
            "缺官方 SWE-bench evaluator；请安装项目 evaluation extra，"
            "客观验收不可退化为 persona 自测"
        )


def _probe_endpoint(*, profile: dict[str, str], model: str) -> None:
    openai_url = profile["USER_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    response = requests.post(
        openai_url,
        headers={
            "Authorization": f"Bearer {profile['USER_LLM_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "OK"}]},
        timeout=60,
        proxies={"http": None, "https": None},
    )
    if response.status_code != 200 or not response.json().get("choices"):
        raise AuditLaunchError(f"OpenAI endpoint 探测失败：HTTP {response.status_code}")
    anthropic_url = profile["ANTHROPIC_BASE_URL"].rstrip("/") + "/v1/messages"
    response = requests.post(
        anthropic_url,
        headers={
            "Authorization": f"Bearer {profile['ANTHROPIC_AUTH_TOKEN']}",
            "x-api-key": profile["ANTHROPIC_AUTH_TOKEN"],
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "OK"}]},
        timeout=60,
        proxies={"http": None, "https": None},
    )
    if response.status_code != 200 or not response.json().get("content"):
        raise AuditLaunchError(f"Anthropic endpoint 探测失败：HTTP {response.status_code}")


def _compose(
    spec: FrozenExperiment, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    manifest = read_manifest(path=spec.paths["manifest"])
    command = compose_argv(
        dest=spec.paths["infrastructure"],
        project=str(manifest["compose_project"]),
        extra=list(arguments),
    )
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise AuditLaunchError(f"Docker Compose 失败：{result.stderr.strip()[:500]}")
    return result


def _ensure_created(spec: FrozenExperiment, *, resume: bool = False) -> None:
    if not spec.root.exists():
        if resume:
            raise AuditLaunchError(f"resume 实验不存在：{spec.root}")
        runtime.create(config_path=spec.config_path, root=spec.root.parent)
        return
    manifest = read_manifest(path=spec.paths["manifest"])
    expected = config_hash(data=spec.raw)
    if manifest.get("config_hash") != expected:
        raise AuditLaunchError("已有 experiment_id 的 manifest 与当前配置不一致")


def _validate_recovery_identity(spec: FrozenExperiment, *, resume: bool) -> dict[str, str]:
    manifest = read_manifest(path=spec.paths["manifest"])
    identity = recovery_identity(manifest)
    expected = {
        "experiment_id": spec.experiment_id,
        "config_hash": config_hash(data=spec.raw),
        "controller_sha": str(spec.raw["source"]["auto_designer_sha"]),
        "plan_hash": str(spec.raw["execution"]["plan"]["sha256"]),
    }
    drift = {
        key: (expected[key], identity[key]) for key in expected if expected[key] != identity[key]
    }
    if drift:
        raise AuditLaunchError(f"manifest 恢复身份漂移：{drift}")
    recovery_path = spec.paths["checkpoints"] / "recovery.json"
    if resume:
        try:
            RecoveryStore.open(
                root=spec.paths["checkpoints"], identity=RecoveryIdentity(**identity)
            )
        except RecoveryError as exc:
            raise AuditLaunchError(f"recovery state 不可续跑：{exc}") from exc
    elif recovery_path.exists():
        raise AuditLaunchError("fresh 发现已有 recovery state；请使用 --resume")
    return identity


def _provision_base(spec: FrozenExperiment) -> None:
    manifest = read_manifest(path=spec.paths["manifest"])
    render_stack(
        dest=spec.paths["infrastructure"],
        experiment_id=spec.experiment_id,
        manifest_sha=str(manifest["config_hash"]),
        vigil_image=str(spec.config.images["vigil"]),
        images=spec.config.images,
    )
    _compose(spec, "up", "-d", "gitea", "egress-proxy")
    state = last_state(path=spec.paths["journal"])
    if state == "CREATED":
        append_journal(
            path=spec.paths["journal"],
            action="provision-base",
            from_state=state,
            to_state="PROVISIONED",
            resources={"compose_project": manifest["compose_project"]},
        )


def _gitea_base_url(spec: FrozenExperiment) -> str:
    result = _compose(spec, "port", "gitea", "3000")
    address = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    _host, separator, port = address.rpartition(":")
    if not separator or not port.isdigit():
        raise AuditLaunchError(f"无法解析 Gitea 动态端口：{address!r}")
    return f"http://127.0.0.1:{port}"


def _bootstrap_gitea(spec: FrozenExperiment) -> dict[str, str]:
    credentials_path = spec.paths["secrets"] / "gitea.json"
    demand_env_path = spec.paths["secrets"] / "demand-gitea.env"
    if credentials_path.is_file() and demand_env_path.is_file():
        values = _load_json(credentials_path)
        if isinstance(values, dict):
            return {str(key): str(value) for key, value in values.items()}
        raise AuditLaunchError("已有 Gitea credentials 结构非法")

    base_url = _gitea_base_url(spec)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base_url}/api/v1/version", timeout=2)
        except requests.RequestException:
            response = None
        if response is not None and response.status_code == 200:
            break
        time.sleep(0.5)
    else:
        raise AuditLaunchError(f"Gitea readiness 超时：{base_url}")

    owner = "designer"
    repository = "harness"
    password = secrets.token_urlsafe(32)
    created = _compose(
        spec,
        "exec",
        "-T",
        "--user",
        "git",
        "gitea",
        "gitea",
        "admin",
        "user",
        "create",
        "--admin",
        "--username",
        owner,
        "--password",
        password,
        "--email",
        f"{owner}@{spec.experiment_id}.invalid",
        "--must-change-password=false",
        check=False,
    )
    if created.returncode != 0 and "already exists" not in created.stderr.lower():
        raise AuditLaunchError(f"创建 Gitea 用户失败：{created.stderr.strip()[:300]}")
    token_result = _compose(
        spec,
        "exec",
        "-T",
        "--user",
        "git",
        "gitea",
        "gitea",
        "admin",
        "user",
        "generate-access-token",
        "--username",
        owner,
        "--token-name",
        f"experiment-{spec.experiment_id}",
        "--scopes",
        "write:user,write:issue,write:repository",
        "--raw",
    )
    token = token_result.stdout.strip()
    response = requests.post(
        f"{base_url}/api/v1/user/repos",
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
        json={"name": repository, "private": True, "auto_init": False},
        timeout=15,
    )
    if response.status_code not in {201, 409}:
        raise AuditLaunchError(f"创建 Gitea 仓失败：HTTP {response.status_code}")
    credentials = {
        "base_url": base_url,
        "owner": owner,
        "repository": repository,
        "token": token,
    }
    _atomic_private_write(
        credentials_path, json.dumps(credentials, ensure_ascii=False, indent=2) + "\n"
    )
    _atomic_private_write(
        demand_env_path,
        f"GITEA_URL={base_url}\nOWNER={owner}\nREPO={repository}\nTOKEN={token}\n",
    )
    append_journal(
        path=spec.paths["journal"],
        action="bootstrap-gitea",
        from_state=last_state(path=spec.paths["journal"]),
        to_state="READY",
        resources={"gitea_url": base_url, "repository": f"{owner}/{repository}"},
    )
    return credentials


def _write_context(spec: FrozenExperiment, *, credentials: dict[str, str]) -> Path:
    manifest = read_manifest(path=spec.paths["manifest"])
    project = str(manifest["compose_project"])
    context = runtime.ExperimentContext(
        experiment_id=spec.experiment_id,
        data_root=spec.paths["data"],
        harness_repo=spec.paths["data"] / "harness_sandbox" / "harness_repo",
        harness_runs_root=spec.paths["data"] / "harness_runs",
        sessions_root=spec.paths["sessions"],
        vigil_config_root=spec.paths["runtime"] / "vigil-config",
        vigil_container=f"{project}-vigil",
        vigil_network=f"{project}_vigil_net",
        compose_project=project,
        gitea_host=credentials["base_url"],
        gitea_internal="http://gitea:3000",
        model_profile=str(spec.config.models["profile"]),
        telemetry_root=spec.paths["telemetry"],
        mode=spec.config.mode,
        manifest_sha=str(manifest["config_hash"]),
    )
    path = spec.paths["runtime"] / "context.json"
    _atomic_private_write(path, json.dumps(context.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return path


def _execution_environment(
    spec: FrozenExperiment,
    *,
    profile: dict[str, str],
    context_path: Path,
    identity: dict[str, str],
    run_mode: str = "fresh",
) -> dict[str, str]:
    roster = spec.roster
    models = spec.config.models
    source = spec.raw["source"]
    personas = spec.raw["personas"]
    workload = spec.raw["workload"]
    execution = spec.raw["execution"]
    environment = os.environ.copy()
    environment.update(profile)
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join([str(BACKEND), str(SOURCE_ROOT / "NexAU")]),
            "EXPERIMENTS_ROOT": str(spec.root.parent),
            "AUTO_DESIGNER_EXPERIMENT_ID": spec.experiment_id,
            "AUTO_DESIGNER_EXPERIMENT_CONTEXT": str(context_path),
            "AUTO_DESIGNER_GITEA_ENV_FILE": str(spec.paths["secrets"] / "demand-gitea.env"),
            "AUTO_DESIGNER_HARNESS_ARCHIVE": str(source["harness"]["path"]),
            "AUTO_DESIGNER_VIGIL_IMAGE": str(spec.config.images["vigil"]),
            "AUTO_DESIGNER_RUN_ID": identity["run_id"],
            "AUTO_DESIGNER_RUN_MODE": run_mode,
            "AUTO_DESIGNER_RECOVERY_ROOT": str(spec.paths["checkpoints"]),
            "AUTO_DESIGNER_CONFIG_HASH": identity["config_hash"],
            "AUTO_DESIGNER_CONTROLLER_SHA": identity["controller_sha"],
            "AUTO_DESIGNER_PLAN_HASH": identity["plan_hash"],
            "PERSONA_LIBRARY": str(personas["library"]["path"]),
            "PERSONA_ROSTER": str(personas["roster"]["path"]),
            "SWEBENCH_INSTANCE_FILE": str(workload["pool"]["path"]),
            "SWEBENCH_PARQUET": str(workload["dataset"]["path"]),
            "SWEBENCH_EVAL_RESULTS_ROOT": str(spec.paths["archive"] / "objective-evaluation"),
            "AUTO_DESIGNER_OBJECTIVE_EVALUATION": "1"
            if execution.get("objective_evaluation", True)
            else "0",
            "SWEBENCH_INTERACTION_PLAN": str(execution["plan"]["path"]),
            "SWEBENCH_SEED_IMAGE": str(spec.config.images["seed"]),
            "TOTAL_ROUNDS": str(execution["total_rounds"]),
            "N_USERS": str(roster["user"]),
            "N_TRIAGERS": str(roster["triager"]),
            "N_SYNTHESIZERS": str(roster["synthesizer"]),
            "SYNTHESIZER_GROUPING": "1" if execution.get("synthesizer_grouping", False) else "0",
            "N_DIVERGENTS": str(roster["divergent"]),
            "N_OWNERS": str(roster["owner"]),
            "N_DEVELOPERS": str(roster["developer"]),
            "MAX_PARALLEL_USERS": str(spec.config.capacity["user_parallel"]),
            "USER_LLM_MODEL": str(models["user"]),
            "HARNESS_LLM_MODEL": str(models["harness"]),
            "DEMAND_LLM_MODEL": str(models["synthesizer"]),
            "ANTHROPIC_MODEL": str(models["delivery"]),
            "ANTHROPIC_SMALL_FAST_MODEL": str(models["delivery"]),
            "CLAUDE_CODE_SUBAGENT_MODEL": str(models["delivery"]),
            "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": str(models["delivery"]),
            "ANTHROPIC_DEFAULT_SONNET_MODEL": str(models["delivery"]),
            "ANTHROPIC_DEFAULT_OPUS_MODEL": str(models["delivery"]),
            "ROLE_RUNS_TRANSCRIPT": "1"
            if spec.raw.get("audit", {}).get("role_runs_transcript")
            else "0",
            "VIGIL_MODE": "container",
            "VIGIL_GITEA_INTERNAL_URL": "http://gitea:3000",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    return environment


def _snapshot_gitea(spec: FrozenExperiment, credentials: dict[str, str]) -> None:
    base = credentials["base_url"]
    owner = credentials["owner"]
    repository = credentials["repository"]
    headers = {"Authorization": f"token {credentials['token']}"}
    evidence: dict[str, Any] = {"captured_at": _now(), "repository": f"{owner}/{repository}"}
    for name, endpoint in {
        "issues": f"/api/v1/repos/{owner}/{repository}/issues?state=all&limit=100",
        "pulls": f"/api/v1/repos/{owner}/{repository}/pulls?state=all&limit=100",
        "commits": f"/api/v1/repos/{owner}/{repository}/commits?limit=100",
    }.items():
        response = requests.get(base + endpoint, headers=headers, timeout=30)
        evidence[name] = (
            response.json()
            if response.status_code == 200
            else {"http_status": response.status_code}
        )
    path = spec.paths["telemetry"] / "gitea-snapshot.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _archive_harness(spec: FrozenExperiment) -> None:
    repo = spec.paths["data"] / "harness_sandbox" / "harness_repo"
    if not repo.joinpath(".git").exists():
        return
    _run(["git", "-C", str(repo), "fetch", "origin", "main"])
    destination = spec.paths["archive"] / "harness.bundle"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "-C", str(repo), "bundle", "create", str(destination), "--all"])


def _redacted_plan(spec: FrozenExperiment, *, source_pins: dict[str, str]) -> dict[str, Any]:
    status = subprocess.run(
        [
            "git",
            "-C",
            str(REPOSITORY),
            "status",
            "--porcelain",
            "--",
            "backend",
            "pyproject.toml",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    return {
        "experiment_id": spec.experiment_id,
        "root": str(spec.root),
        "mode": spec.config.mode,
        "rounds": int(spec.execution["total_rounds"]),
        "roster": spec.roster,
        "persona_distribution": spec.raw["personas"]["distribution"],
        "models": spec.config.models,
        "capacity": spec.config.capacity,
        "images": spec.config.images,
        "source_pins": source_pins,
        "controller_worktree_dirty": status,
        "secrets_excluded": True,
    }


def check(spec: FrozenExperiment, *, probe: bool) -> dict[str, Any]:
    source_pins = _verify_git_pins(spec)
    _verify_images(spec)
    if spec.execution.get("objective_evaluation", True):
        _verify_official_evaluator()
    profile = _load_profile(spec.model_profile_path)
    if probe:
        _probe_endpoint(profile=profile, model=str(spec.config.models["user"]))
    return _redacted_plan(spec, source_pins=source_pins)


def run_experiment(
    spec: FrozenExperiment,
    *,
    probe: bool,
    allow_dirty_controller: bool = False,
    resume: bool = False,
) -> int:
    plan = check(spec, probe=probe)
    print(json.dumps({"preflight": plan}, ensure_ascii=False, indent=2), flush=True)
    dirty = plan["controller_worktree_dirty"]
    if dirty and not allow_dirty_controller:
        raise AuditLaunchError(
            "controller worktree 非干净状态，正式实验拒绝启动；"
            "先提交并更新 source.auto_designer_sha，开发联调才可显式使用 "
            "--allow-dirty-controller"
        )
    _ensure_created(spec, resume=resume)
    identity = _validate_recovery_identity(spec, resume=resume)
    lock_path = spec.paths["runtime"] / "controller.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AuditLaunchError("已有 controller 正在运行该实验") from exc
        state = last_state(path=spec.paths["journal"])
        allowed = (
            {"FAILED", "STOPPED", "PROVISIONED", "READY"}
            if resume
            else {
                "CREATED",
                "PROVISIONED",
                "READY",
            }
        )
        if state not in allowed:
            action = "resume" if resume else "fresh"
            raise AuditLaunchError(f"实验当前状态 {state}，拒绝 {action}")
        if resume:
            ledger = RecoveryStore.open(
                root=spec.paths["checkpoints"], identity=RecoveryIdentity(**identity)
            )
            append_journal(
                path=spec.paths["journal"],
                action="reconcile-recovery",
                from_state=state,
                to_state=state,
                resources={
                    "run_id": identity["run_id"],
                    "recovery_revision": ledger.revision,
                    "round": ledger.snapshot().get("round", 0),
                },
            )
        _provision_base(spec)
        credentials = _bootstrap_gitea(spec)
        context_path = _write_context(spec, credentials=credentials)
        profile = _load_profile(spec.model_profile_path)
        environment = _execution_environment(
            spec,
            profile=profile,
            context_path=context_path,
            run_mode="resume" if resume else "fresh",
            identity=identity,
        )
        log_path = spec.paths["logs"] / "closed-loop.log"
        pid_path = spec.paths["runtime"] / "demand.pid"
        command = [sys.executable, str(BACKEND / "scripts" / "run_swebench_closed_loop.py")]
        append_journal(
            path=spec.paths["journal"],
            action="resume-closed-loop" if resume else "launch-closed-loop",
            from_state=last_state(path=spec.paths["journal"]),
            to_state="RUNNING",
            resources={
                "log": str(log_path),
                "runner": "swebench-closed-loop",
                "run_id": identity["run_id"],
            },
        )
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                command,
                cwd=REPOSITORY,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
        print(f"experiment={spec.experiment_id} pid={process.pid} log={log_path}", flush=True)
        returncode = process.wait()
        pid_path.unlink(missing_ok=True)
        try:
            _snapshot_gitea(spec, credentials)
            _archive_harness(spec)
        except Exception as exc:  # noqa: BLE001 - preserve primary process outcome
            (spec.paths["logs"] / "evidence-warning.log").write_text(
                f"{_now()} {type(exc).__name__}: {exc}\n", encoding="utf-8"
            )
        if returncode != 0:
            append_journal(
                path=spec.paths["journal"],
                action="closed-loop-failed",
                from_state="RUNNING",
                to_state="FAILED",
                resources={"returncode": returncode, "log": str(log_path)},
            )
            raise AuditLaunchError(f"闭环退出 {returncode}；现场已保留：{spec.root}")
        append_journal(
            path=spec.paths["journal"],
            action="closed-loop-completed",
            from_state="RUNNING",
            to_state="COMPLETED",
            resources={"returncode": 0, "log": str(log_path)},
        )
        _compose(spec, "stop")
        append_journal(
            path=spec.paths["journal"],
            action="stop-after-completion",
            from_state="COMPLETED",
            to_state="STOPPED",
            resources={"kept": True},
        )
        archive = runtime.archive(experiment_id=spec.experiment_id, root=spec.root.parent)
        print(f"completed experiment={spec.experiment_id} archive={archive}", flush=True)
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="配置驱动的可审计闭环实验启动器")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--check", action="store_true", help="只做静态/环境预检，不创建实验或启动容器"
    )
    parser.add_argument("--no-probe", action="store_true", help="预检时不调用模型 endpoint")
    parser.add_argument("--resume", action="store_true", help="复用冻结身份并从 recovery 状态续跑")
    parser.add_argument(
        "--allow-dirty-controller",
        action="store_true",
        help="仅开发联调：允许未提交 controller 代码，正式实验禁止使用",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = experiments_root()
    try:
        spec = FrozenExperiment.load(config_path=args.config, root=root)
        if args.check:
            print(json.dumps(check(spec, probe=not args.no_probe), ensure_ascii=False, indent=2))
            return 0
        return run_experiment(
            spec,
            probe=not args.no_probe,
            allow_dirty_controller=args.allow_dirty_controller,
            resume=args.resume,
        )
    except (AuditLaunchError, ConfigError) as exc:
        print(f"[auditable-experiment] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
