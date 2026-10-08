#!/usr/bin/env python3
"""Start an isolated OpenAgents Docker validation with explicit run/provider settings."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from tools.dev import add_inputs, read_secrets, run_inputs

ROOT = Path(__file__).resolve().parents[3] / "backend"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--container", required=True, help="New, isolated container name")
    parser.add_argument("--model", help="Override the run's delivery model")
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--network", help="Docker network override; defaults to selected run")
    parser.add_argument("--image", help="OpenAgents image override; defaults to selected run")
    parser.add_argument("--internal-url", help="Container-accessible Gitea URL override")
    add_inputs(parser, run=True)
    return parser.parse_args()


def gateway_environment(
    path: Path | None, model: str, *, settings: dict | None = None
) -> dict[str, str]:
    """Use standard Anthropic variables or the run's explicit delivery key mapping."""
    values = {**os.environ, **read_secrets(path)}
    explicit_mapping = settings is not None
    settings = settings or {}
    base_name = settings.get("base_url_env", "ANTHROPIC_BASE_URL")
    key_name = settings.get("api_key_env", "ANTHROPIC_API_KEY")
    base = values.get(base_name)
    token = values.get(key_name)
    if not explicit_mapping:
        token = token or values.get("ANTHROPIC_AUTH_TOKEN")
    if not base or not token:
        raise SystemExit(f"Missing delivery credentials: {base_name} / {key_name}")
    auth_name = (
        "ANTHROPIC_API_KEY"
        if key_name == "ANTHROPIC_API_KEY" and values.get(key_name)
        else "ANTHROPIC_AUTH_TOKEN"
    )
    return {
        "ANTHROPIC_BASE_URL": base,
        auth_name: token,
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_SMALL_FAST_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1",
    }


def main() -> int:
    args = _args()
    config = args.config_dir.resolve()
    if not (config / "openagents.yml").is_file():
        raise SystemExit(f"missing validation config: {config / 'openagents.yml'}")
    if args.parallel < 1:
        raise SystemExit("parallel must be >= 1")
    manifest, resources, gitea = run_inputs(args.run_dir, args.secrets_file)
    vigil = resources.get("vigil", {})
    network = args.network or vigil.get("network")
    image = args.image or vigil.get("image")
    if not network or not image:
        raise SystemExit("Provide --network and --image when absent from the selected run")
    # Do not reuse or overwrite the controller's own delivery container.
    if args.container == vigil.get("container"):
        raise SystemExit("Validation container must differ from the run's delivery container")
    settings = manifest["config"]["models"]["delivery"]
    model = args.model or settings["model"]
    credential_path = args.secrets_file
    private = args.run_dir / "secrets/provider.env"
    if credential_path is None and private.is_file():
        credential_path = private
    gateway = gateway_environment(credential_path, model, settings=settings)
    internal = args.internal_url or resources["gitea"].get("internal_url") or gitea["GITEA_URL"]
    runtime_env = {
        **os.environ,
        **gateway,
        "GITEA_TOKEN": gitea["TOKEN"],
        "VIGIL_REPO_URL": f"{internal.rstrip('/')}/{gitea['OWNER']}/{args.repo}.git",
        "VIGIL_PARALLEL": str(args.parallel),
    }
    # Pass only the selected authentication header, even if host settings contain both.
    for auth in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if auth not in gateway:
            runtime_env.pop(auth, None)
    entrypoint = (ROOT / "deploy/vigil/entrypoint.sh").resolve()
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        args.container,
        "--network",
        network,
        "-v",
        f"{config}:/config:ro",
        "-v",
        f"{entrypoint}:/entrypoint.sh:ro",
    ]
    for key in ("GITEA_TOKEN", "VIGIL_REPO_URL", "VIGIL_PARALLEL", *gateway):
        command += ["-e", key]
    command += [
        "-e",
        "OPENAGENTS_PERMISSION_MODE=bypassPermissions",
        image,
        "bash",
        "/entrypoint.sh",
    ]
    subprocess.run(command, env=runtime_env, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
