"""Spec-0069/T4: cache a verified build identity, then inspect actual sandbox resources."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from auto_designer.experiment.backends.base import BackendError

BOOTSTRAP_VERSION = "uv-0.11.28-python-3.12.13-claude-2.1.284-v2"


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
    recipe = {
        "bootstrap": BOOTSTRAP_VERSION,
        "cpu_count": settings["cpu_count"],
        "memory_mb": settings["memory_mb"],
        "base": "e2b-base",
    }
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
    alias = "auto-designer-" + digest[:20]
    # Builds are shared immutable runtime inputs. Individual destroy operations
    # intentionally retain them; a failed build never claims a successful cache.
    build = Template.build(
        Template()
        .from_base_image()
        .run_cmd(
            "apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates python3 && rm -rf /var/lib/apt/lists/*",
            user="root",
        ),
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
