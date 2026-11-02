"""Spec-0069/T4: cache a verified build identity, then inspect actual sandbox resources."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ahe_beta.experiment.backends.base import BackendError

BOOTSTRAP_VERSION = "uv-0.11.28-python-3.12.13-claude-2.1.284-v2"
# Spec-0081/T4: public, independently checksummed Docker toolchain for container tasks.
DOCKER_VERSION = "27.5.1"
DOCKER_URL = "https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz"
DOCKER_SHA256 = "4f798b3ee1e0140eab5bf30b0edc4e84f4cdb53255a429dc3bbae9524845d640"


def _container_tasks(run_dir: Path, manifest: dict) -> bool:
    if manifest.get("workload_contract_version") != 1:
        return False
    from ahe_beta.experiment.workload import read_task_catalog

    return any(
        task["package"].get("schema_version") == 3
        for task in read_task_catalog(run_dir, manifest)["tasks"]
    )


def _build_template(Template: Any, *, container_tasks: bool) -> Any:
    template = (
        Template()
        .from_base_image()
        .run_cmd(
            "apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates python3"
            + (" iptables pigz" if container_tasks else "")
            + " && rm -rf /var/lib/apt/lists/*",
            user="root",
        )
    )
    if not container_tasks:
        return template
    return (
        template.run_cmd(
            "curl --fail --location --retry 3 "
            + DOCKER_URL
            + " -o /tmp/docker.tgz && "
            + "echo '"
            + DOCKER_SHA256
            + "  /tmp/docker.tgz' | sha256sum -c - && "
            + "tar -xzf /tmp/docker.tgz -C /usr/local/bin --strip-components=1 && rm /tmp/docker.tgz && "
            + 'test "$(docker --version)" = \'Docker version '
            + DOCKER_VERSION
            + ", build 9f9e405' && "
            + "groupadd -f docker",
            user="root",
        )
        .set_user("root")
        .set_start_cmd(
            "exec dockerd --host=unix:///var/run/docker.sock --group=docker --storage-driver=overlay2",
            "docker info >/dev/null 2>&1",
        )
    )


def resolve_template(
    *, run_dir: Path, manifest: dict[str, Any], credentials: Mapping[str, str]
) -> dict[str, Any]:
    """Template caches contain public resource facts; never API keys.

    A supplied template is also inspected after creation. Its mutable alias is
    recorded as a selection, never represented as a verified build identity.
    """
    from e2b import Template

    settings = manifest["config"]["runtime"]["e2b"]
    api_key = credentials.get("E2B_API_KEY")
    if not api_key:
        raise BackendError("Missing environment variable: E2B_API_KEY")
    if settings.get("template"):
        selected = settings["template"]
        base, separator, requested_tag = selected.partition(":")
        tags = Template.get_tags(base, api_key=api_key)
        tag = next(
            (item for item in tags if item.tag == (requested_tag if separator else "latest")), None
        )
        if tag is None:
            raise BackendError("Selected operator template tag does not exist")
        return {
            "selection": selected,
            "build_id": tag.build_id if tag else None,
            "recipe": "operator-template",
            "expected_cpu": settings["cpu_count"],
            "expected_memory_mb": settings["memory_mb"],
        }
    container_tasks = _container_tasks(run_dir, manifest)
    recipe = {
        "bootstrap": BOOTSTRAP_VERSION,
        "cpu_count": settings["cpu_count"],
        "memory_mb": settings["memory_mb"],
        "base": "e2b-base",
    }
    if container_tasks:
        recipe["docker"] = {"version": DOCKER_VERSION, "url": DOCKER_URL, "sha256": DOCKER_SHA256}
    digest = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    cache = run_dir.parent / ".cache/e2b" / f"{digest}.json"
    if cache.is_file():
        record = json.loads(cache.read_text())
        if record.get("recipe_hash") == digest and Template.exists(
            record["selection"], api_key=api_key
        ):
            tags = Template.get_tags(record["template_id"], api_key=api_key)
            if any(item.build_id == record["build_id"] for item in tags):
                return record
    alias = "ahe-beta-" + digest[:20]
    # Builds are shared immutable runtime inputs. Individual destroy operations
    # intentionally retain them; a failed build never claims a successful cache.
    build = Template.build(
        _build_template(Template, container_tasks=container_tasks),
        name=alias,
        tags=[digest[:20]],
        cpu_count=settings["cpu_count"],
        memory_mb=settings["memory_mb"],
        api_key=api_key,
    )
    record = {
        "selection": build.template_id + ":" + digest[:20],
        "template_id": build.template_id,
        "build_id": build.build_id,
        "alias": build.alias,
        "recipe_hash": digest,
        "recipe": recipe,
        "expected_cpu": settings["cpu_count"],
        "expected_memory_mb": settings["memory_mb"],
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(cache)
    return record


def sandbox_facts(
    info: Any, *, manifest: dict[str, Any], template: dict[str, Any]
) -> dict[str, Any]:
    """CPU/RAM/network are provider observations, not copied from requested JSON."""
    settings = manifest["config"]["runtime"]["e2b"]
    metadata = dict(info.metadata or {})
    if any(metadata.get(key) != str(manifest[key]) for key in ("run_id", "config_hash")):
        raise BackendError("Sandbox ownership metadata does not match the frozen run")
    if info.cpu_count != settings["cpu_count"] or info.memory_mb != settings["memory_mb"]:
        raise BackendError("Actual E2B CPU/memory do not match the frozen resource request")
    if template.get("template_id") and info.template_id != template["template_id"]:
        raise BackendError("Actual E2B template identity differs from the recorded build")
    if info.allow_internet_access is not True:
        raise BackendError("E2B did not confirm required internet access")
    return {
        "sandbox_id": info.sandbox_id,
        "template_id": info.template_id,
        "selected_build_id": template.get("build_id"),
        "cpu_count": info.cpu_count,
        "memory_mb": info.memory_mb,
        "allow_internet_access": info.allow_internet_access,
        "metadata": metadata,
        "started_at": info.started_at.isoformat(),
        "expires_at": info.end_at.isoformat(),
        "state": str(info.state),
    }
