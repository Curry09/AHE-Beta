"""Explicit inputs shared by maintenance tools; never discover host secrets."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path


def add_inputs(parser: argparse.ArgumentParser, *, run: bool = False) -> None:
    parser.add_argument(
        "--secrets-file",
        type=Path,
        help="Explicit credential file; otherwise use injected environment",
    )
    if run:
        parser.add_argument(
            "--run-dir",
            type=Path,
            required=True,
            help="Prepared v2 run containing manifest.json and resources.json",
        )


def read_secrets(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    from dotenv import dotenv_values

    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"Credential file must be a regular file: {path}")
    return {
        key: str(value)
        for key, value in dotenv_values(path, interpolate=False).items()
        if value is not None
    }


def load_secrets(path: Path | None) -> None:
    os.environ.update(read_secrets(path))


def role_environment(*roles: str, model: str | None = None) -> None:
    """Require each requested role; optionally use an explicitly supplied common profile."""
    selected_run = bool(os.environ.get("AHE_BETA_DEV_RUN_PROFILE"))
    for role in roles:
        for suffix in ("MODEL", "BASE_URL", "API_KEY"):
            key = f"{role}_LLM_{suffix}"
            value = model if suffix == "MODEL" and model else os.environ.get(key)
            if not value and not selected_run:
                value = os.environ.get(f"LLM_{suffix}")
            if not value:
                raise SystemExit(f"Missing {key}; set injected environment or --secrets-file")
            os.environ[key] = value


def run_inputs(
    run_dir: Path, secrets_file: Path | None = None
) -> tuple[dict, dict, dict[str, str]]:
    """Resolve provider and model settings only within the explicitly selected run."""
    root = run_dir.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2:
        raise SystemExit("Maintenance tools require a prepared schema_version=2 run")
    resources = json.loads((root / "resources.json").read_text(encoding="utf-8"))
    values = dict(os.environ)
    private = root / "secrets/provider.env"
    if private.is_file():
        values.update(read_secrets(private))
    values.update(read_secrets(secrets_file))
    model_settings = manifest.get("config", {}).get("models", {})
    os.environ["AHE_BETA_DEV_RUN_PROFILE"] = str(root)
    for role in ("user", "harness", "demand"):
        model = model_settings.get(role) or {}
        for suffix, value in (
            ("MODEL", model.get("model")),
            ("BASE_URL", values.get(model.get("base_url_env", ""))),
            ("API_KEY", values.get(model.get("api_key_env", ""))),
        ):
            key = f"{role.upper()}_LLM_{suffix}"
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    gitea = resources.get("gitea", {})
    provider = {
        "GITEA_URL": gitea.get("url", ""),
        "OWNER": gitea.get("owner", ""),
        "REPO": gitea.get("repo", ""),
        "TOKEN": values.get("GITEA_TOKEN", ""),
    }
    if any(not value for value in provider.values()):
        raise SystemExit(
            "Selected run has incomplete Gitea address/identity/token; supply --secrets-file if needed"
        )
    return manifest, resources, provider


@contextmanager
def harness_environment():
    """Expose plain LLM keys only while spawning a Harness child."""
    role_environment("HARNESS")
    keys = {
        f"LLM_{suffix}": os.environ[f"HARNESS_LLM_{suffix}"]
        for suffix in ("MODEL", "BASE_URL", "API_KEY")
    }
    before = {key: os.environ.get(key) for key in keys}
    os.environ.update(keys)
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
