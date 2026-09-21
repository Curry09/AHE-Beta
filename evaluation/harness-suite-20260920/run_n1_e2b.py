#!/usr/bin/env python3
"""Launch or resume the frozen N=1 E2B evolution experiment.

The controller is deliberately small and auditable:
- fresh creates exactly one E2B sandbox and one private Gitea repository;
- resume reconnects to the recorded sandbox and repository, never creates a replacement;
- --dry-run validates and prints the redacted plan without contacting E2B, Gitea, or a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "evaluation" / "harness-suite-20260920"
DEFAULT_CONFIG = SUITE / "configs" / "n1-e2b-20260922.json"
ARTIFACTS = ROOT.parent / "auto-designer-experiment-artifacts"
HARNESS_ARCHIVE = ARTIFACTS / "harness-v0-cade14d.tar.gz"
CLAUDE = Path("/root/.local/share/claude/versions/2.1.261")
OPENAGENTS = ROOT.parent / "OpenAgents"
TASK_ID = "pvlib__pvlib-python-1478"
TASK_COMMIT = "3f397ed44075b01f4ba535750356859195a51b2d"
TASK_REPO = "pvlib/pvlib-python"
PERSONA = "sr-15-swyx"


class LaunchError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaunchError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchError(f"expected JSON object: {path}")
    return value


def read_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def config_hash(path: Path) -> str:
    return sha256(path)


def git_sha() -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def load_plan(path: Path) -> dict:
    plan = read_json(path)
    task = plan.get("task") or {}
    if (
        task.get("task_key") != "O03"
        or task.get("task_id") != TASK_ID
        or task.get("revision") != TASK_COMMIT
        or task.get("persona_id") != PERSONA
    ):
        raise LaunchError("N=1 config drift: expected frozen O03 task/revision/persona")
    if plan.get("rounds", {}).get("count") != 5:
        raise LaunchError("N=1 config must contain exactly five rounds")
    archive = Path(plan["harness"]["archive"]).expanduser()
    if not archive.is_file() or sha256(archive) != plan["harness"]["sha256"]:
        raise LaunchError(f"frozen harness archive missing or hash mismatch: {archive}")
    return plan


def credentials(gitea_file: Path | None) -> dict[str, str]:
    env = {}
    for secret_path in (ROOT / ".e2b", ROOT.parent / ".e2b"):
        env.update(read_kv(secret_path))
    for secret_path in (ROOT / ".boyue", ROOT.parent / ".boyue"):
        env.update(read_kv(secret_path))
    if gitea_file is not None:
        env.update(read_kv(gitea_file))
    env.update({key: value for key, value in os.environ.items() if value})
    e2b_key = env.get("E2B_API_KEY") or env.get("API_KEY") or env.get("API_KET")
    boyue_key = env.get("BOYUE_API_KEY") or env.get("api-key") or env.get("BOYUE_KEY")
    gitea_url = env.get("GITEA_URL", "http://38.47.121.235:3000").rstrip("/")
    gitea_user = env.get("GITEA_USER") or env.get("OWNER") or "hseadmin"
    gitea_token = env.get("GITEA_TOKEN") or env.get("TOKEN") or env.get("GITEA_PASSWORD")
    missing = [
        name
        for name, value in (
            ("E2B_API_KEY", e2b_key),
            ("BOYUE_API_KEY", boyue_key),
            ("GITEA_USER", gitea_user),
            ("GITEA_TOKEN", gitea_token),
        )
        if not value
    ]
    if missing:
        raise LaunchError("missing secret(s): " + ", ".join(missing))
    if urlparse(gitea_url).scheme == "http" and os.environ.get("ALLOW_INSECURE_GITEA") != "1":
        raise LaunchError(
            "Gitea is currently HTTP; use HTTPS for a formal run or explicitly set "
            "ALLOW_INSECURE_GITEA=1 for the VPS smoke deployment"
        )
    return {
        "E2B_API_KEY": str(e2b_key),
        "BOYUE_API_KEY": str(boyue_key),
        "GITEA_URL": gitea_url,
        "GITEA_USER": str(gitea_user),
        "GITEA_TOKEN": str(gitea_token),
        "BOYUE_OPENAI": "https://api.boyuerichdata.opensphereai.com/v1",
        "BOYUE_ANTHROPIC": "https://api.boyuerichdata.opensphereai.com",
    }


def request_gitea(method: str, url: str, token: str, **kwargs) -> requests.Response:
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"token {token}"
    headers.setdefault("Accept", "application/json")
    return requests.request(method, url, headers=headers, timeout=30, **kwargs)


def ensure_repo(creds: dict[str, str], name: str, resume: bool) -> None:
    api = creds["GITEA_URL"] + "/api/v1"
    if resume:
        response = request_gitea(
            "GET", f"{api}/repos/{quote(creds['GITEA_USER'])}/{quote(name)}", creds["GITEA_TOKEN"]
        )
        if response.status_code != 200:
            raise LaunchError(f"resume repository is unavailable: HTTP {response.status_code}")
        return
    response = request_gitea(
        "POST",
        f"{api}/user/repos",
        creds["GITEA_TOKEN"],
        json={"name": name, "private": True, "auto_init": False},
    )
    if response.status_code != 201:
        raise LaunchError(
            f"cannot create Gitea repository: HTTP {response.status_code} {response.text[:300]}"
        )


def archive_sources(destination: Path) -> None:
    roots = [
        ROOT / "backend" / "auto_designer",
        ROOT / "backend" / "agent_defs",
        ROOT / "backend" / "harness_template",
        ROOT / "backend" / "run.py",
        ROOT / "backend" / "scripts" / "run_swebench_closed_loop.py",
        ROOT / "backend" / "persona_library.json",
        ROOT / "pyproject.toml",
    ]
    with tarfile.open(destination, "w:gz") as archive:
        for source in roots:
            if not source.exists():
                raise LaunchError(f"source missing: {source}")
            arcname = str(source.relative_to(ROOT))
            archive.add(
                source,
                arcname=arcname,
                filter=lambda info: (
                    None
                    if any(
                        part in {".git", "__pycache__", ".pytest_cache", ".openagents"}
                        for part in Path(info.name).parts
                    )
                    else info
                ),
            )


def instance_metadata(instruction: str) -> dict:
    return {
        "instance_id": TASK_ID,
        "repo": TASK_REPO,
        "base_commit": TASK_COMMIT,
        "problem_statement": instruction,
        "difficulty": "frozen-pilot",
    }


def remote_files(
    plan: dict, creds: dict[str, str], run_id: str, repo_name: str, metadata: dict
) -> dict[str, str]:
    task_file = (SUITE / "harbor-ordinary-o03" / "instruction.md").read_text(encoding="utf-8")
    backend_env = "\n".join(
        [
            "USER_LLM_MODEL=glm-5.3-flash",
            f"USER_LLM_BASE_URL={creds['BOYUE_OPENAI']}",
            f"USER_LLM_API_KEY={creds['BOYUE_API_KEY']}",
            "HARNESS_LLM_MODEL=glm-5.3-flash",
            f"HARNESS_LLM_BASE_URL={creds['BOYUE_OPENAI']}",
            f"HARNESS_LLM_API_KEY={creds['BOYUE_API_KEY']}",
            "DESIGNER_LLM_MODEL=glm-5.3",
            f"DESIGNER_LLM_BASE_URL={creds['BOYUE_OPENAI']}",
            f"DESIGNER_LLM_API_KEY={creds['BOYUE_API_KEY']}",
            "DEVELOPER_LLM_MODEL=glm-5.3",
            f"DEVELOPER_LLM_BASE_URL={creds['BOYUE_OPENAI']}",
            f"DEVELOPER_LLM_API_KEY={creds['BOYUE_API_KEY']}",
            "ANTHROPIC_MODEL=glm-5.3",
            "ANTHROPIC_SMALL_FAST_MODEL=glm-5.3",
            f"ANTHROPIC_BASE_URL={creds['BOYUE_ANTHROPIC']}",
            f"ANTHROPIC_AUTH_TOKEN={creds['BOYUE_API_KEY']}",
            "PYTHONUNBUFFERED=1",
            "",
        ]
    )
    gitea_env = "\n".join(
        [
            f"GITEA_URL={creds['GITEA_URL']}",
            f"OWNER={creds['GITEA_USER']}",
            f"REPO={repo_name}",
            f"TOKEN={creds['GITEA_TOKEN']}",
            "",
        ]
    )
    plan_json = json.dumps(
        [[PERSONA, TASK_ID] for _ in range(int(plan["rounds"]["count"]))],
        ensure_ascii=False,
    )
    return {
        "/opt/hse-round/backend/.env": backend_env,
        "/opt/hse-round/backend/deploy/gitea/.env": gitea_env,
        "/opt/hse-round/instruction.md": task_file,
        "/opt/hse-round/instance.json": json.dumps(metadata, ensure_ascii=False) + "\n",
        "/opt/hse-round/instance-pool.json": json.dumps(
            {"instances": [{"instance_id": TASK_ID}]}, ensure_ascii=False
        )
        + "\n",
        "/opt/hse-round/interaction-plan.json": plan_json + "\n",
        "/opt/hse-round/run.sh": """#!/usr/bin/env bash
set -u
mkdir -p /opt/hse-run
set +e
PYTHONPATH=/opt/hse-round/backend /opt/hse-venv/bin/python -u /opt/hse-round/backend/scripts/run_swebench_closed_loop.py
code=$?
printf '%s\\n' "$code" > /opt/hse-run/exit_code
exit "$code"
""",
    }


def shell_setup() -> str:
    return r"""set -eux
mkdir -p /opt/hse-round/backend/deploy/gitea /opt/hse-run /opt/hse-run/recovery /opt/claude-bin
tar -xzf /tmp/hse-code.tar.gz -C /opt/hse-round
install -m 0644 /tmp/hse-harness.tar.gz /opt/hse-round/harness-v0-cade14d.tar.gz
tar -xzf /tmp/hse-openagents.tar.gz -C /opt/hse-round
install -m 0755 /tmp/claude-bin /usr/local/bin/claude
python3 -m venv /opt/hse-venv
/opt/hse-venv/bin/pip install --no-cache-dir requests ruamel.yaml jsonschema fastapi uvicorn pyarrow
/opt/hse-venv/bin/pip install --no-cache-dir ag-ui-protocol==0.1.22 nexau==0.4.1
/opt/hse-venv/bin/pip install --no-cache-dir -e /opt/hse-round/OpenAgents
mkdir -p /opt/hse-run/workspace/pvlib__pvlib-python-1478
git clone --quiet https://github.com/pvlib/pvlib-python.git /opt/hse-run/workspace/pvlib__pvlib-python-1478/repo
git -C /opt/hse-run/workspace/pvlib__pvlib-python-1478/repo checkout --quiet 3f397ed44075b01f4ba535750356859195a51b2d
ln -s /opt/hse-venv /opt/hse-run/workspace/pvlib__pvlib-python-1478/repo/.venv
/opt/hse-venv/bin/pip install --no-cache-dir -e /opt/hse-run/workspace/pvlib__pvlib-python-1478/repo
python3 - <<'PY'
import json, pyarrow as pa, pyarrow.parquet as pq
from pathlib import Path
item=json.loads(Path('/opt/hse-round/instance.json').read_text())
pq.write_table(pa.Table.from_pylist([item]), '/opt/hse-run/instances.parquet')
PY
chmod +x /opt/hse-round/run.sh
test -f /opt/hse-round/harness/entry.py
test -f /opt/hse-round/backend/scripts/run_swebench_closed_loop.py
test -x /usr/local/bin/claude
"""


def identity(plan_path: Path, run_id: str) -> dict[str, str]:
    plan_hash = sha256(SUITE / "configs" / "mixed-scaling-20260922.tasks.json")
    return {
        "experiment_id": "hse-n1-e2b-20260922",
        "run_id": run_id,
        "config_hash": config_hash(plan_path),
        "controller_sha": git_sha(),
        "plan_hash": plan_hash,
        "recovery_root": "/opt/hse-run/recovery",
    }


def write_state(run_dir: Path, state: dict) -> None:
    state["updated_at"] = now()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def redacted(plan: dict, state: dict | None = None) -> dict:
    result = {
        "experiment_id": plan["experiment_id"],
        "status": plan["status"],
        "task": plan["task"],
        "rounds": plan["rounds"],
        "harness": {k: v for k, v in plan["harness"].items() if k != "archive"},
        "roles": plan["roles"],
        "roster": plan["roster"],
        "execution": plan["execution"],
        "interaction_contract": plan["interaction_contract"],
        "resume_contract": plan["resume_contract"],
        "secrets": "loaded at runtime; never printed",
    }
    if state:
        result["state"] = {k: v for k, v in state.items() if k not in {"token"}}
    return result


def start_remote(sandbox, plan: dict, identity_data: dict[str, str], resume: bool) -> object:
    envs = {
        **identity_data,
        "AUTO_DESIGNER_RUN_MODE": "resume" if resume else "fresh",
        "AUTO_DESIGNER_GITEA_ENV_FILE": "/opt/hse-round/backend/deploy/gitea/.env",
        "AUTO_DESIGNER_HARNESS_ARCHIVE": "/opt/hse-round/harness-v0-cade14d.tar.gz",
        "SWEBENCH_PARQUET": "/opt/hse-run/instances.parquet",
        "SWEBENCH_SEED_ROOT": "/opt/hse-run",
        "SWEBENCH_INSTANCE_FILE": "/opt/hse-round/instance-pool.json",
        "SWEBENCH_INSTANCE": TASK_ID,
        "PERSONA_ROSTER": "/opt/hse-round/persona-roster.json",
        "SWEBENCH_INTERACTION_PLAN": "/opt/hse-round/interaction-plan.json",
        "TOTAL_ROUNDS": "5",
        "SESSIONS_PER_ROUND": "1",
        "MAX_PARALLEL_USERS": "1",
        "N_USERS": "1",
        "N_TRIAGERS": "1",
        "N_DESIGNERS": "1",
        "N_DIVERGENTS": "0",
        "N_OWNERS": "0",
        "N_DEVELOPERS": "1",
        "HSE_OFFICIAL_AGENT_TIMEOUT_SECONDS": "1800",
        "HSE_OUTER_AGENT_TIMEOUT_SECONDS": "2400",
        "VIGIL_MODE": "subprocess",
        "AUTO_DESIGNER_OBJECTIVE_EVALUATION": "0",
        "OPENAGENTS_PERMISSION_MODE": "bypassPermissions",
        "PYTHONUNBUFFERED": "1",
    }
    # The closed-loop script accepts the same command for fresh and resume;
    # AUTO_DESIGNER_RUN_MODE is the only lifecycle switch.
    return sandbox.commands.run(
        "bash /opt/hse-round/run.sh",
        envs=envs,
        background=True,
        timeout=120,
    )


def create_sandbox(
    plan: dict, creds: dict[str, str], run_id: str, repo_name: str, identity_data: dict[str, str]
):
    from e2b import Sandbox

    metadata = instance_metadata(
        (SUITE / "harbor-ordinary-o03" / "instruction.md").read_text(encoding="utf-8")
    )
    temp = Path(tempfile.mkdtemp(prefix="hse-n1-"))
    code_tar = temp / "hse-code.tar.gz"
    oa_tar = temp / "hse-openagents.tar.gz"
    archive_sources(code_tar)
    with tarfile.open(oa_tar, "w:gz") as archive:
        archive.add(
            OPENAGENTS,
            arcname="OpenAgents",
            filter=lambda info: (
                None
                if any(part in {".git", "__pycache__"} for part in Path(info.name).parts)
                else info
            ),
        )
    sandbox = None
    try:
        sandbox = Sandbox.create(
            template="base",
            timeout=int(plan["execution"]["sandbox_timeout_seconds"]),
            allow_internet_access=True,
            metadata={"experiment_id": plan["experiment_id"], "run_id": run_id, "task": TASK_ID},
            api_key=creds["E2B_API_KEY"],
        )
        bootstrap = sandbox.commands.run(
            "mkdir -p /opt/hse-round/backend/deploy/gitea /opt/hse-run", user="root", timeout=30
        )
        if bootstrap.exit_code != 0:
            raise LaunchError(f"E2B bootstrap failed: {bootstrap.stderr or bootstrap.stdout}")

        def upload(local: Path, remote: str) -> None:
            with local.open("rb") as stream:
                sandbox.files.write(remote, stream, request_timeout=1800, use_octet_stream=True)

        upload(code_tar, "/tmp/hse-code.tar.gz")
        upload(oa_tar, "/tmp/hse-openagents.tar.gz")
        upload(HARNESS_ARCHIVE, "/tmp/hse-harness.tar.gz")
        upload(CLAUDE, "/tmp/claude-bin")
        for path, text in remote_files(plan, creds, run_id, repo_name, metadata).items():
            sandbox.files.write(path, text)
        sandbox.files.write(
            "/opt/hse-round/persona-roster.json",
            json.dumps({"personas": [{"id": PERSONA}]}, ensure_ascii=False) + "\n",
        )
        setup = sandbox.commands.run(shell_setup(), timeout=1800, user="root")
        if setup.exit_code != 0:
            raise LaunchError(f"E2B setup failed: {setup.stderr or setup.stdout}")
        return sandbox
    except Exception:
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                pass
        raise


def fresh(args, plan: dict, creds: dict[str, str]) -> int:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    run_dir = SUITE / "runs" / f"e2b-n1-20260922-{run_id}"
    repo_name = f"hse-n1-20260922-{run_id}"
    if run_dir.exists():
        raise LaunchError(f"run directory already exists: {run_dir}")
    ensure_repo(creds, repo_name, False)
    ident = identity(args.config, run_id)
    sandbox = create_sandbox(plan, creds, run_id, repo_name, ident)
    command = start_remote(sandbox, plan, ident, False)
    state = {
        "run_id": run_id,
        "sandbox_id": sandbox.sandbox_id,
        "gitea_url": creds["GITEA_URL"],
        "gitea_repository": f"{creds['GITEA_USER']}/{repo_name}",
        "gitea_repo_name": repo_name,
        "task_id": TASK_ID,
        "harness_id": plan["harness"]["id"],
        "identity": ident,
        "command_id": getattr(command, "cmd_id", None),
        "started_at": now(),
    }
    write_state(run_dir, state)
    print(f"STARTED run_id={run_id}")
    print(f"E2B_SANDBOX_ID={sandbox.sandbox_id}")
    print(f"STATE={run_dir / 'state.json'}")
    print("RESUME=bash evaluation/harness-suite-20260920/resume_n1_e2b.sh " + run_id)
    return 0


def resume(args, plan: dict, creds: dict[str, str]) -> int:
    if not args.run_id:
        raise LaunchError("--resume requires --run-id")
    run_dir = SUITE / "runs" / f"e2b-n1-20260922-{args.run_id}"
    state_path = run_dir / "state.json"
    state = read_json(state_path)
    if state.get("run_id") != args.run_id:
        raise LaunchError("run id does not match state")
    ident = state.get("identity") or {}
    if ident.get("config_hash") != config_hash(args.config):
        raise LaunchError("config hash changed; refusing resume")
    expected_plan = sha256(SUITE / "configs" / "mixed-scaling-20260922.tasks.json")
    if ident.get("plan_hash") != expected_plan or ident.get("controller_sha") != git_sha():
        raise LaunchError("controller or task-plan revision changed; refusing resume")
    repo_name = str(state.get("gitea_repo_name") or "")
    if not repo_name:
        raise LaunchError("state is missing the frozen Gitea repository name")
    ensure_repo(creds, repo_name, True)
    from e2b import Sandbox

    sandbox = Sandbox.connect(
        state["sandbox_id"], api_key=creds["E2B_API_KEY"], timeout=86400, on_resume="restore"
    )
    exit_probe = sandbox.commands.run(
        "test -f /opt/hse-run/exit_code && cat /opt/hse-run/exit_code || true", timeout=30
    )
    if exit_probe.stdout.strip():
        print(f"ALREADY_FINISHED exit_code={exit_probe.stdout.strip()} run_id={args.run_id}")
        return int(exit_probe.stdout.strip())
    command = start_remote(sandbox, plan, ident, True)
    state["resume_command_id"] = getattr(command, "cmd_id", None)
    state["resumed_at"] = now()
    write_state(run_dir, state)
    print(f"RESUMED run_id={args.run_id} sandbox={state['sandbox_id']}")
    print(f"STATE={state_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--gitea-env", type=Path, help="ignored env file with GITEA_URL/GITEA_USER/GITEA_TOKEN"
    )
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.config = args.config.expanduser().resolve()
    try:
        plan = load_plan(args.config)
        if args.dry_run:
            print(json.dumps(redacted(plan), ensure_ascii=False, indent=2))
            return 0
        creds = credentials(args.gitea_env.expanduser().resolve() if args.gitea_env else None)
        return resume(args, plan, creds) if args.resume else fresh(args, plan, creds)
    except LaunchError as exc:
        print(f"LAUNCH_ERROR: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
