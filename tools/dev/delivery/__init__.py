"""Explicit Git transport for maintenance tools; credentials stay out of argv."""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit


def require_execution_config(checkout: Path) -> None:
    """Keep the trusted requirement when preparing a new delivery validation."""
    import yaml

    path = checkout / ".openagents/openagents.yml"
    document = yaml.safe_load(path.read_text()) if path.exists() else {"version": 1}
    if not isinstance(document, dict):
        raise SystemExit("OpenAgents validation configuration must be an object")
    document["execution_evidence"] = {"required": True}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False))


def git_remote_url(gitea: dict[str, str], repo: str) -> str:
    base = gitea["GITEA_URL"].rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username is not None:
        raise SystemExit("Gitea base must be an HTTP(S) URL without embedded credentials")
    return f"{base}/{quote(gitea['OWNER'], safe='')}/{quote(repo, safe='')}.git"


def git_environment(gitea: dict[str, str]) -> dict[str, str]:
    # URL-scoped Basic authentication works for both localhost and Gitea.com Git.
    base = gitea["GITEA_URL"].rstrip("/")
    git_remote_url(gitea, gitea.get("REPO", "validation"))
    auth = base64.b64encode(f"{gitea['OWNER']}:{gitea['TOKEN']}".encode()).decode()
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    }
    env.update(
        GIT_CONFIG_COUNT="2",
        GIT_CONFIG_KEY_0="credential.helper",
        GIT_CONFIG_VALUE_0="",
        GIT_CONFIG_KEY_1=f"http.{base}/.extraHeader",
        GIT_CONFIG_VALUE_1=f"Authorization: Basic {auth}",
        GIT_TERMINAL_PROMPT="0",
        GIT_ASKPASS="",
        SSH_ASKPASS="",
    )
    return env


def run_git(
    command: list[str], *, gitea: dict[str, str], cwd: Path | None = None, text: bool = False
):
    """Capture Git diagnostics and never expose raw failure output or exception argv."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=git_environment(gitea),
            capture_output=True,
            text=text,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        raise SystemExit("Git transport failed; sensitive diagnostics withheld") from None
    if result.returncode:
        raise SystemExit(
            f"Git command failed (exit {result.returncode}); sensitive diagnostics withheld"
        )
    return result
