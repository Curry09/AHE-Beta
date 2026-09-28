from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:3000"
API_BASE = BASE + "/api/v1"
USER = "designer"
PASSWORD = "SmokePass-2026!"
REPO = "real-developer-smoke"


def run(argv: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None):
    return subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def model_probe(out: Path) -> None:
    """Probe the exact sandbox-to-WIS path before starting Vigil.

    Keep this deliberately small: it distinguishes an egress/proxy reset from
    a Claude CLI/OpenAgents-specific reset without changing the evaluation
    workflow itself.
    """
    base = os.environ.get("MODEL_BASE_URL", os.environ.get("WIS_BASE_URL", "")).rstrip("/")
    key = os.environ.get("MODEL_API_KEY", os.environ.get("WIS_API_KEY", ""))
    lines = [
        "proxy=" + json.dumps({k: bool(v) for k, v in os.environ.items() if "proxy" in k.lower()}),
        "base=" + base,
    ]
    body = {
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        "max_tokens": 64,
        "stream": True,
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    messages_url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    for label, trust_env in (("proxy", True), ("direct", False)):
        session = requests.Session()
        session.trust_env = trust_env
        try:
            with session.post(
                messages_url, headers=headers, json=body, stream=True, timeout=(15, 90)
            ) as response:
                lines.append(f"{label}_status={response.status_code}")
                lines.append(f"{label}_headers={dict(response.headers)}")
                chunks = []
                for chunk in response.iter_lines(decode_unicode=True):
                    if chunk:
                        chunks.append(chunk[:500])
                    if len(chunks) >= 4:
                        break
                lines.append(f"{label}_chunks={chunks}")
        except Exception as exc:
            lines.append(f"{label}_error={type(exc).__name__}: {exc}")
    (out / "model-probe.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def api(method: str, path: str, **kwargs):
    kwargs.setdefault("auth", (USER, PASSWORD))
    kwargs.setdefault("timeout", 30)
    response = requests.request(method, API_BASE + path, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else {}


def main() -> int:
    out = Path("/tmp/eval-output")
    out.mkdir(parents=True, exist_ok=True)
    model_probe(out)
    gitea = Path("/tmp/gitea")
    gitea.mkdir(parents=True, exist_ok=True)
    gitea_bin = "/tmp/gitea-bin"
    if not Path(gitea_bin).is_file():
        raise RuntimeError("Gitea binary was not installed")
    user_create = run(["useradd", "--system", "--create-home", "--shell", "/bin/sh", "gitea"])
    if (
        user_create.returncode != 0
        and "already exists" not in (user_create.stderr + user_create.stdout).lower()
    ):
        raise RuntimeError(f"cannot create gitea user: {user_create.stderr[-500:]}")
    run(["chown", "-R", "gitea:gitea", str(gitea)])
    gitea_env = {
        **os.environ,
        "GITEA_WORK_DIR": str(gitea),
        "GITEA_CUSTOM": str(gitea / "custom"),
        "GITEA__database__DB_TYPE": "sqlite3",
        "GITEA__server__ROOT_URL": BASE + "/",
        "GITEA__server__HTTP_PORT": "3000",
        "GITEA__security__INSTALL_LOCK": "true",
        "GITEA__service__DISABLE_REGISTRATION": "false",
        "GITEA__service__REQUIRE_SIGNIN_VIEW": "false",
        "GITEA__repository__DISABLED_REPO_UNITS": "",
        "GITEA__repository__DEFAULT_REPO_UNITS": "repo.code,repo.releases,repo.issues,repo.pulls,repo.wiki,repo.projects",
    }
    conf = gitea / "custom" / "conf"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "app.ini").write_text(
        "[database]\n"
        "DB_TYPE = sqlite3\n"
        f"PATH = {gitea / 'data' / 'gitea.db'}\n"
        "[security]\n"
        "INSTALL_LOCK = true\n"
        "SECRET_KEY = daytona-real-developer-smoke\n"
        "INTERNAL_TOKEN = daytona-real-developer-internal\n"
        "[server]\n"
        "DOMAIN = 127.0.0.1\n"
        "HTTP_ADDR = 0.0.0.0\n"
        "HTTP_PORT = 3000\n"
        f"ROOT_URL = {BASE}/\n"
        "[repository]\n"
        "DISABLED_REPO_UNITS =\n"
        "DEFAULT_REPO_UNITS = repo.code,repo.releases,repo.issues,repo.pulls,repo.wiki,repo.projects\n"
        "[service]\n"
        "DISABLE_REGISTRATION = false\n"
        "REQUIRE_SIGNIN_VIEW = false\n",
        encoding="utf-8",
    )
    run(["chown", "-R", "gitea:gitea", str(gitea)])
    gitea_log = (out / "gitea.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        ["runuser", "-u", "gitea", "--", gitea_bin, "web"],
        env=gitea_env,
        stdout=gitea_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        for _ in range(90):
            try:
                if requests.get(BASE + "/api/v1/version", timeout=2).ok:
                    break
            except requests.RequestException:
                time.sleep(1)
        else:
            gitea_log.flush()
            tail = Path("/tmp/eval-output/gitea.log").read_text(encoding="utf-8", errors="replace")[
                -2000:
            ]
            raise RuntimeError(f"Gitea did not become ready; log={tail}")

        create_user = run(
            [
                "runuser",
                "-u",
                "gitea",
                "--",
                gitea_bin,
                "admin",
                "user",
                "create",
                "--username",
                USER,
                "--password",
                PASSWORD,
                "--email",
                "designer@example.invalid",
                "--admin",
                "--must-change-password=false",
            ],
            env=gitea_env,
        )
        if (
            create_user.returncode != 0
            and "already exists" not in (create_user.stderr + create_user.stdout).lower()
        ):
            raise RuntimeError(f"Gitea user create failed: {create_user.stderr[-500:]}")

        token_result = run(
            [
                "runuser",
                "-u",
                "gitea",
                "--",
                gitea_bin,
                "admin",
                "user",
                "generate-access-token",
                "--username",
                USER,
                "--token-name",
                "daytona-real-developer",
                "--scopes",
                "all",
                "--raw",
            ],
            env=gitea_env,
        )
        if token_result.returncode != 0:
            raise RuntimeError(f"Gitea token create failed: {token_result.stderr[-500:]}")
        token = token_result.stdout.strip().splitlines()[-1].strip()
        if not token:
            raise RuntimeError("Gitea token was empty")

        api(
            "POST",
            "/user/repos",
            json={
                "name": REPO,
                "private": True,
                "auto_init": True,
                "default_branch": "main",
                "readme": "Default",
                "has_issues": True,
                "has_projects": True,
                "has_wiki": False,
                "has_pull_requests": True,
            },
        )
        # Gitea 1.22 may apply the repository feature defaults after creation;
        # explicitly PATCH the feature flags and verify the PR surface before
        # handing the repository to Vigil.
        repo_state = api(
            "PATCH",
            f"/repos/{USER}/{REPO}",
            json={
                "has_issues": True,
                "has_projects": True,
                "has_wiki": False,
                "has_pull_requests": True,
            },
        )
        if repo_state.get("has_pull_requests") is not True:
            raise RuntimeError(f"Gitea did not enable pull requests: {repo_state}")
        # Gitea 1.22's API response can report the feature flag while the
        # sqlite repo_unit row is still absent when the instance starts with
        # a minimal config. Ensure the PR unit exists before Vigil probes it.
        db = sqlite3.connect(gitea / "data" / "gitea.db", timeout=30)
        try:
            repo_id = db.execute(
                "SELECT id FROM repository WHERE owner_name = ? AND lower_name = ?",
                (USER, REPO.lower()),
            ).fetchone()
            if not repo_id:
                raise RuntimeError("Gitea repository row was not found")
            existing_unit = db.execute(
                "SELECT 1 FROM repo_unit WHERE repo_id = ? AND type = 3", (repo_id[0],)
            ).fetchone()
            if not existing_unit:
                db.execute(
                    "INSERT INTO repo_unit (repo_id, type, config) VALUES (?, 3, ?)",
                    (
                        repo_id[0],
                        json.dumps(
                            {"allow_merge": True, "allow_rebase": True, "allow_squash": True}
                        ),
                    ),
                )
                db.commit()
        finally:
            db.close()
        # Repository units are cached by the running web process. Restart the
        # local Gitea process once after the direct compatibility insert so the
        # API and Vigil observe the same persisted unit set.
        proc.terminate()
        proc.wait(timeout=20)
        proc = subprocess.Popen(
            ["runuser", "-u", "gitea", "--", gitea_bin, "web"],
            env=gitea_env,
            stdout=gitea_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for _ in range(60):
            try:
                if requests.get(BASE + "/api/v1/version", timeout=2).ok:
                    break
            except requests.RequestException:
                time.sleep(1)
        else:
            raise RuntimeError("Gitea did not become ready after repo-unit restart")
        work = Path("/tmp/developer-repo")
        if work.exists():
            shutil.rmtree(work)
        remote = f"http://{USER}:{PASSWORD}@127.0.0.1:3000/{USER}/{REPO}.git"
        clone = run(["git", "clone", remote, str(work)])
        if clone.returncode != 0:
            raise RuntimeError(f"initial clone failed: {clone.stderr[-500:]}")
        (work / "billing.py").write_text(
            "def total(items):\n    return sum(items)\n", encoding="utf-8"
        )
        (work / "README.md").write_text("# real developer smoke\n", encoding="utf-8")
        (work / ".gitignore").write_text("__pycache__/\n*.py[cod]\n", encoding="utf-8")
        for command in (
            ["git", "config", "user.email", "smoke@example.invalid"],
            ["git", "config", "user.name", "smoke"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "seed"],
        ):
            result = run(command, cwd=str(work))
            if result.returncode != 0:
                raise RuntimeError(f"git setup failed: {result.stderr[-500:]}")
        push = run(["git", "push", "-u", "origin", "main"], cwd=str(work))
        if push.returncode != 0:
            raise RuntimeError(f"initial push failed: {push.stderr[-500:]}")
        # Pull requests are unavailable for an empty repository in Gitea
        # (the route intentionally returns 404). Probe only after the seed
        # commit has been pushed and the repository is non-empty.
        repo_after_push = api("GET", f"/repos/{USER}/{REPO}")
        if repo_after_push.get("empty") is True:
            raise RuntimeError(f"Gitea repository stayed empty after push: {repo_after_push}")
        pulls_probe = requests.get(
            API_BASE + f"/repos/{USER}/{REPO}/pulls", auth=(USER, PASSWORD), timeout=30
        )
        if pulls_probe.status_code != 200:
            raise RuntimeError(
                f"Gitea PR unit probe failed: {pulls_probe.status_code} {pulls_probe.text[:500]}"
            )

        label = api(
            "POST", f"/repos/{USER}/{REPO}/labels", json={"name": "openagents", "color": "1d76db"}
        )
        issue = api(
            "POST",
            f"/repos/{USER}/{REPO}/issues",
            json={
                "title": "Add a safe average helper",
                "body": "Add average(items) to billing.py, handle an empty list explicitly, and add a small test or executable check.",
                "labels": [label["id"]],
            },
        )
        config = work / ".openagents" / "openagents.yml"
        config.parent.mkdir()
        config.write_text(
            "version: 1\n"
            "forge: gitea\n"
            "gitea:\n"
            "  base_url: http://127.0.0.1:3000\n"
            "  owner: designer\n"
            "  repo: real-developer-smoke\n"
            "  token_env: GITEA_TOKEN\n"
            "stages:\n"
            "  triage: skip\n"
            "  rfc: agent\n"
            "  architecture: agent\n"
            "  conflict: agent\n"
            "  ci: skip\n"
            "  e2e: skip\n"
            "  review: agent\n"
            "  merge: agent\n"
            "release: manual\n"
            "defaults:\n"
            "  interval: 1\n"
            "  base: main\n"
            "  labels: [openagents]\n",
            encoding="utf-8",
        )
        # The workflow contract belongs to the seed commit.  Creating it
        # after the seed push leaves an untracked file in the checkout, and
        # Vigil correctly refuses to deliver a branch with a dirty workspace.
        for command in (
            ["git", "add", ".openagents/openagents.yml"],
            ["git", "commit", "-qm", "add OpenAgents workflow config"],
        ):
            result = run(command, cwd=str(work))
            if result.returncode != 0:
                raise RuntimeError(f"workflow config commit failed: {result.stderr[-500:]}")
        push_config = run(["git", "push", "origin", "main"], cwd=str(work))
        if push_config.returncode != 0:
            raise RuntimeError(f"workflow config push failed: {push_config.stderr[-500:]}")
        wis_base = os.environ.get("MODEL_BASE_URL", os.environ["WIS_BASE_URL"]).rstrip("/")
        model_key = os.environ.get("MODEL_API_KEY", os.environ["WIS_API_KEY"])
        claude_env = {
            **os.environ,
            "GITEA_TOKEN": token,
            "GITEA_USER": USER,
            "ANTHROPIC_BASE_URL": wis_base[:-3] if wis_base.endswith("/v1") else wis_base,
            "ANTHROPIC_AUTH_TOKEN": model_key,
            # Use the vendor model spelling understood by Claude Code.  The
            # gateway accepts this identifier on the Anthropic-compatible
            # endpoint; OpenAI-style ``provider/model`` names make Claude's
            # nonessential title request fail before the real turn starts.
            "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            "ANTHROPIC_SMALL_FAST_MODEL": "claude-sonnet-4-5",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-4-5",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-sonnet-4-5",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-sonnet-4-5",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32768",
            "OPENAGENTS_PERMISSION_MODE": "bypassPermissions",
            "OPENAGENTS_CLAUDE_IDLE_TIMEOUT": "180",
            "OPENAGENTS_CLAUDE_MAX_WALL": "900",
            "OPENAGENTS_NO_UPDATE": "1",
            "PATH": "/opt/harness-venv/bin:/opt/claude-bin:" + os.environ.get("PATH", ""),
            "HOME": "/home/worker",
            "USER": "worker",
            "LOGNAME": "worker",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        worker_user = run(["useradd", "--create-home", "--shell", "/bin/bash", "worker"])
        if (
            worker_user.returncode != 0
            and "already exists" not in (worker_user.stderr + worker_user.stdout).lower()
        ):
            raise RuntimeError(f"cannot create worker user: {worker_user.stderr[-500:]}")
        ownership = run(["chown", "-R", "worker:worker", str(work)])
        if ownership.returncode != 0:
            raise RuntimeError(f"cannot prepare worker checkout: {ownership.stderr[-500:]}")
        worker = subprocess.run(
            [
                "runuser",
                "-u",
                "worker",
                "--preserve-environment",
                "--",
                "/opt/harness-venv/bin/openagents",
                "vigil",
                "--once",
                "--parallel",
                "1",
            ],
            cwd=str(work),
            env=claude_env,
            text=True,
            capture_output=True,
            timeout=1200,
        )
        (out / "developer-stdout.log").write_text(worker.stdout, encoding="utf-8")
        (out / "developer-stderr.log").write_text(worker.stderr, encoding="utf-8")
        final_issue = api("GET", f"/repos/{USER}/{REPO}/issues/{issue['number']}")
        issue_labels = [x.get("name") for x in final_issue.get("labels", [])]
        workflow_ok = worker.returncode == 0 and "automation-failed" not in issue_labels
        payload = {
            "worker_exit_code": worker.returncode,
            "workflow_ok": workflow_ok,
            "issue_number": issue["number"],
            "issue_state": final_issue.get("state"),
            "issue_labels": issue_labels,
            "head": run(["git", "rev-parse", "HEAD"], cwd=str(work)).stdout.strip(),
            "status": run(["git", "status", "--short"], cwd=str(work)).stdout,
            "gitea": "local-daytona",
            "owner_mode": "mechanical_review_false_before_worker",
        }
        (out / "real-developer.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 0 if workflow_ok else (worker.returncode or 1)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        gitea_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
