#!/usr/bin/env python3
"""Start an isolated OpenAgents validation container with the repository's env parser."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run as run_mod  # noqa: E402


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--gateway-env", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--parallel", type=int, default=1)
    return parser.parse_args()


def gateway_environment(path: Path, model: str) -> dict[str, str]:
    """Translate the shared WIS file into Claude Code's Anthropic-compatible contract."""
    values = run_mod._load_env(path)
    missing = [key for key in ("wis_base_url", "wis_api_key") if not values.get(key)]
    if missing:
        raise SystemExit(f"gateway env missing required fields: {', '.join(missing)}")
    parsed = urlsplit(values["wis_base_url"].rstrip("/"))
    # WIS stores a conventional API base ending in /v1. Anthropic clients append
    # /v1/messages themselves, so their base is the prefix immediately before /v1.
    path_without_version = parsed.path[:-3] if parsed.path.endswith("/v1") else parsed.path
    anthropic_base_url = urlunsplit(parsed._replace(path=path_without_version))
    return {
        "ANTHROPIC_BASE_URL": anthropic_base_url,
        "ANTHROPIC_AUTH_TOKEN": values["wis_api_key"],
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

    gitea = run_mod._load_env(ROOT / "deploy" / "gitea" / ".env")
    gateway = gateway_environment(args.gateway_env, args.model)
    runtime_env = {
        **os.environ,
        **gateway,
        "GITEA_TOKEN": gitea["TOKEN"],
        "VIGIL_REPO_URL": run_mod._gitea_remote_url({**gitea, "REPO": args.repo}).replace(
            "localhost:3000", "gitea:3000"
        ),
        "VIGIL_PARALLEL": str(args.parallel),
    }
    entrypoint = (ROOT / "deploy" / "vigil" / "entrypoint.sh").resolve()
    proxy = "http://egress-proxy:3128"
    passthrough = [
        "GITEA_TOKEN",
        "VIGIL_REPO_URL",
        "VIGIL_PARALLEL",
        *gateway,
    ]
    command = [
        "docker", "run", "-d", "--name", args.container,
        "--network", "auto-designer-vigil-net",
        "-v", f"{config}:/config:ro",
        "-v", f"{entrypoint}:/entrypoint.sh:ro",
    ]
    for key in passthrough:
        command += ["-e", key]
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        command += ["-e", f"{key}={proxy}"]
    command += [
        "-e", "NO_PROXY=gitea,localhost,127.0.0.1",
        "-e", "no_proxy=gitea,localhost,127.0.0.1",
        "-e", "OPENAGENTS_PERMISSION_MODE=bypassPermissions",
        "auto-designer-vigil:latest", "bash", "/entrypoint.sh",
    ]
    subprocess.run(command, env=runtime_env, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
