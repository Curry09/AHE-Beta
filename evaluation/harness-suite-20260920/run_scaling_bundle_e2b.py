#!/usr/bin/env python3
"""Concrete executor for one frozen mixed-scaling E2B runtime.

The outer launcher owns policy and gates. This module owns the E2B upload,
Gitea repository, remote run and resume lifecycle. Missing prompts/payloads
fail closed; no synthetic task text is allowed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "evaluation" / "harness-suite-20260920"
CONFIG = SUITE / "configs" / "scaling-e2b-20260922.json"
MIXED = SUITE / "configs" / "mixed-scaling-20260922.json"
ASSIGNMENTS = SUITE / "configs" / "mixed-scaling-20260922.tasks.json"
ARTIFACTS = ROOT.parent / "auto-designer-experiment-artifacts"
HARNESS_ARCHIVE = ARTIFACTS / "harness-v0-cade14d.tar.gz"
CLAUDE = Path("/root/.local/share/claude/versions/2.1.261")
OPENAGENTS = ROOT.parent / "OpenAgents"
NEXAU = ROOT.parent / "NexAU"


class LaunchError(RuntimeError):
    pass


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaunchError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LaunchError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def kv_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip("\"'")
    return result


def credentials(gitea_env: Path | None, source_sandbox_id: str | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (ROOT / ".e2b", ROOT.parent / ".e2b", ROOT / ".boyue", ROOT.parent / ".boyue"):
        values.update(kv_file(path))
    values.update(kv_file(gitea_env))
    values.update({key: value for key, value in os.environ.items() if value})
    if source_sandbox_id:
        from e2b import Sandbox

        e2b_key = values.get("E2B_API_KEY") or values.get("API_KEY") or values.get("API_KET")
        if not e2b_key:
            raise LaunchError("cannot relay N1 Gitea credentials without E2B_API_KEY")
        source = Sandbox.connect(source_sandbox_id, api_key=e2b_key)
        result = source.commands.run(
            "cat /opt/hse-round/backend/deploy/gitea/.env", user="root", timeout=30
        )
        if result.exit_code != 0:
            raise LaunchError("N1 source sandbox Gitea credentials are unavailable")
        for line in (result.stdout or "").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key == "GITEA_URL" and value:
                values["GITEA_URL"] = value
            elif key == "OWNER" and value:
                values["GITEA_USER"] = value
            elif key == "TOKEN" and value:
                values["GITEA_TOKEN"] = value
    result = {
        "E2B_API_KEY": values.get("E2B_API_KEY") or values.get("API_KEY") or values.get("API_KET"),
        "BOYUE_API_KEY": values.get("BOYUE_API_KEY") or values.get("BOYUE_KEY") or values.get("api-key"),
        "GITEA_URL": (values.get("GITEA_URL") or "http://38.47.121.235:3000").rstrip("/"),
        "GITEA_USER": values.get("GITEA_USER") or values.get("OWNER") or "hseadmin",
        "GITEA_TOKEN": values.get("GITEA_TOKEN") or values.get("TOKEN") or values.get("GITEA_PASSWORD"),
    }
    missing = [key for key in ("E2B_API_KEY", "BOYUE_API_KEY", "GITEA_TOKEN") if not result[key]]
    if missing:
        raise LaunchError("missing secret(s): " + ", ".join(missing))
    if result["GITEA_URL"].startswith("http://") and os.environ.get("ALLOW_INSECURE_GITEA") != "1":
        raise LaunchError("Gitea is HTTP; set ALLOW_INSECURE_GITEA=1 explicitly for the VPS smoke run")
    result.update(BOYUE_OPENAI="https://api.boyuerichdata.opensphereai.com/v1", BOYUE_ANTHROPIC="https://api.boyuerichdata.opensphereai.com")
    return {key: str(value) for key, value in result.items()}


def gitea(method: str, url: str, token: str, **kwargs):
    import requests
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = f"token {token}"
    headers.setdefault("Accept", "application/json")
    return requests.request(method, url, headers=headers, timeout=30, **kwargs)


def ensure_repo(creds: dict[str, str], name: str, resume: bool) -> None:
    api = creds["GITEA_URL"] + "/api/v1"
    if resume:
        response = gitea("GET", f"{api}/repos/{creds['GITEA_USER']}/{name}", creds["GITEA_TOKEN"])
        if response.status_code != 200:
            raise LaunchError(f"resume repository unavailable: HTTP {response.status_code}")
        return
    response = gitea("POST", f"{api}/user/repos", creds["GITEA_TOKEN"], json={"name": name, "private": True, "auto_init": False})
    if response.status_code != 201:
        raise LaunchError(f"cannot create Gitea repository: HTTP {response.status_code} {response.text[:300]}")


def task_rows(n: int) -> list[dict]:
    assignments = {str(row["task_key"]): row for row in read_json(ASSIGNMENTS)["tasks"]}
    membership = read_json(MIXED)["scaling_sets"][f"N{n}"]
    root = SUITE / "prepared" / "scaling-e2b-20260922" / f"n{n}"
    # N=1 was an earlier smoke run and its standalone receipt was never
    # materialized.  O03 is frozen identically in the launchable N=4 bundle;
    # reuse that verified payload rather than silently inventing a new one.
    if n == 1 and not root.is_dir():
        root = SUITE / "prepared" / "scaling-e2b-20260922" / "n4"
    inventory, receipt = read_json(root / "bundle-inventory.json"), read_json(root / "receipt.json")
    if receipt.get("status") != "ready" or not receipt.get("launchable"):
        raise LaunchError(f"N{n} receipt is not launchable: {receipt.get('status')!r}")
    if inventory.get("status") != "ready":
        raise LaunchError(f"N{n} bundle inventory is not ready")
    found = {str(row["task_key"]): row for row in inventory.get("tasks", [])}
    receipt_payloads = {str(row.get("task_key")): row for row in receipt.get("payloads", [])}
    rows: list[dict] = []
    for key in membership:
        receipt_row = receipt_payloads.get(key)
        if receipt_row is None:
            raise LaunchError(f"N{n}/{key} missing from runtime receipt payload list")
        row = {**assignments[key], **found.get(key, {}), **receipt_row}
        for field in ("agent_payload", "grader_payload", "agent_payload_sha256", "grader_payload_sha256"):
            if not row.get(field):
                raise LaunchError(f"N{n}/{key} missing frozen {field}")
        for kind in ("agent", "grader"):
            path = Path(row[f"{kind}_payload"])
            if not path.is_file() or sha256(path) != row[f"{kind}_payload_sha256"]:
                raise LaunchError(f"N{n}/{key} {kind} payload missing or hash mismatch")
        for kind in ("agent", "grader"):
            digest_key = f"{kind}_payload_sha256"
            if receipt_row.get(digest_key) != row.get(digest_key):
                raise LaunchError(f"N{n}/{key} {kind} payload differs from runtime receipt")
        rows.append(row)
    return rows


def prompt_for(row: dict) -> str:
    if row["benchmark"] == "mechanism":
        for item in read_json(SUITE / "task-manifest.json").get("mechanism_tasks", []):
            if item.get("task_id") == row["task_id"]:
                opening = str(item.get("opening_message") or "").strip()
                if opening:
                    expected = str(row.get("prompt_sha256") or "").strip()
                    if expected and hashlib.sha256(opening.encode("utf-8")).hexdigest() != expected:
                        raise LaunchError(f"{row['task_key']}/{row['task_id']} mechanism prompt hash mismatch")
                    return opening
        raise LaunchError(f"{row['task_key']}/{row['task_id']} has no frozen mechanism prompt")
    # SWE task prompts are frozen outside the agent-visible payload.  Resolve
    # and verify the pinned source before putting the text into the remote
    # manifest; never synthesize a prompt from the task id.
    prompt_source = str(row.get("prompt_source") or "").strip()
    if prompt_source:
        path = Path(prompt_source)
        if not path.is_file():
            raise LaunchError(f"{row['task_key']}/{row['task_id']} frozen prompt is missing: {path}")
        expected = str(row.get("prompt_sha256") or "").strip()
        if expected and sha256(path) != expected:
            raise LaunchError(f"{row['task_key']}/{row['task_id']} frozen prompt hash mismatch")
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    source = Path(str(row.get("source") or ""))
    candidates: list[Path] = []
    if row["benchmark"] == "SWE-bench":
        if row["task_key"] == "O03":
            candidates.append(SUITE / "harbor-ordinary-o03" / "instruction.md")
        prompt_root = os.environ.get("SWEBENCH_PROMPT_ROOT", "").strip()
        if prompt_root:
            candidates.append(Path(prompt_root) / f"{row['task_id']}.md")
    else:
        candidates.extend([source / "instruction.md", source / "TASK.md", source / "start.md"])
    for path in candidates:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    raise LaunchError(f"{row['task_key']}/{row['task_id']} has no frozen prompt; refusing synthetic task text")


def build_manifest(n: int, rows: list[dict], profile: dict, rounds: int) -> dict:
    tasks = []
    for row in rows:
        key = str(row["task_key"])
        timeout = int(row.get("official_agent_timeout_seconds") or 1800)
        tasks.append({
            "task_key": key, "task_id": row["task_id"], "benchmark": row["benchmark"], "stratum": row["stratum"],
            "interaction": row["interaction"], "persona_id": row.get("persona_id"), "description": prompt_for(row),
            "workspace": f"/opt/hse-run/workspaces/{key}/repo" if row["benchmark"] == "SWE-bench" else f"/opt/hse-run/workspaces/{key}",
            "workspace_setup": [], "official_agent_timeout_seconds": timeout, "outer_timeout_seconds": timeout + 600,
            "agent_payload": row["agent_payload"], "agent_payload_sha256": row["agent_payload_sha256"],
            "grader_payload": row["grader_payload"], "grader_payload_sha256": row["grader_payload_sha256"],
            "grader": {"payload": f"/opt/hse-run/payloads/grader/{key}.tar.gz"},
        })
    config = read_json(CONFIG)
    return {
        "schema_version": "hse-mixed-task-runtime-v1",
        "n": n,
        "rounds": rounds,
        "tasks": tasks,
        "profile": profile,
        # Persist the timeout policy in the runtime manifest as well as the
        # environment. This makes the triage timeout classification auditable
        # from the remote artifact, rather than only from controller logs.
        "timeouts": config.get("timeouts") or {},
    }


def archive_tree(source: Path, destination: Path, arcname: str) -> None:
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(source, arcname=arcname, filter=lambda info: None if any(part in {".git", "__pycache__", ".pytest_cache", ".venv", "build", "dist"} for part in Path(info.name).parts) else info)


def payload_bundle(rows: list[dict], destination: Path) -> None:
    with tarfile.open(destination, "w:gz") as bundle:
        for row in rows:
            for kind in ("agent", "grader"):
                bundle.add(row[f"{kind}_payload"], arcname=f"payloads/{kind}/{row['task_key']}.tar.gz")


def source_archive(destination: Path) -> None:
    sys.path.insert(0, str(SUITE))
    from run_n1_e2b import archive_sources
    archive_sources(destination)


def remote_files(
    manifest: dict,
    creds: dict[str, str],
    repo: str,
    config: dict,
    profile: dict,
    run_id: str,
    *,
    experiment_id: str | None = None,
    config_hash_override: str | None = None,
    plan_hash_override: str | None = None,
) -> dict[str, str]:
    roles = read_json(MIXED)["roles"]
    timing_policy = (config.get("timeouts") or {}).get("latency_isolated_timeout") or {}
    receipt_root = SUITE / "prepared" / "scaling-e2b-20260922" / f"n{manifest['n']}"
    if manifest["n"] == 1 and not receipt_root.is_dir():
        receipt_root = SUITE / "prepared" / "scaling-e2b-20260922" / "n4"
    receipt = read_json(receipt_root / "receipt.json")
    values = {
        "USER_LLM_MODEL": roles["user_simulator"]["model"], "USER_LLM_BASE_URL": creds["BOYUE_OPENAI"], "USER_LLM_API_KEY": creds["BOYUE_API_KEY"],
        "HARNESS_LLM_MODEL": roles["harness"]["model"], "HARNESS_LLM_BASE_URL": creds["BOYUE_OPENAI"], "HARNESS_LLM_API_KEY": creds["BOYUE_API_KEY"],
        "DESIGNER_LLM_MODEL": roles["designer"]["model"], "DESIGNER_LLM_BASE_URL": creds["BOYUE_OPENAI"], "DESIGNER_LLM_API_KEY": creds["BOYUE_API_KEY"],
        "DEVELOPER_LLM_MODEL": roles["developer"]["model"], "DEVELOPER_LLM_BASE_URL": creds["BOYUE_ANTHROPIC"], "DEVELOPER_LLM_API_KEY": creds["BOYUE_API_KEY"],
        "AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT": "1" if timing_policy.get("enabled", False) else "0",
        "AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS": str(int(timing_policy.get("wall_guard_grace_seconds", 600))),
        "ANTHROPIC_MODEL": roles["developer"]["model"], "ANTHROPIC_SMALL_FAST_MODEL": roles["developer"]["model"], "ANTHROPIC_BASE_URL": creds["BOYUE_ANTHROPIC"], "ANTHROPIC_AUTH_TOKEN": creds["BOYUE_API_KEY"], "PYTHONUNBUFFERED": "1",
        "CLAUDE_CODE_SUBAGENT_MODEL": roles["developer"]["model"], "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1",
    }
    backend_env = "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    gitea_env = "\n".join((f"GITEA_URL={creds['GITEA_URL']}", f"OWNER={creds['GITEA_USER']}", f"REPO={repo}", f"TOKEN={creds['GITEA_TOKEN']}", ""))
    persona_ids: list[str] = []
    for row in manifest["tasks"]:
        persona_id = str(row.get("persona_id") or "")
        if persona_id and persona_id not in persona_ids:
            persona_ids.append(persona_id)
    roster = {"personas": [{"id": persona_id} for persona_id in persona_ids]}
    experiment_id = experiment_id or f"hse-n{manifest['n']}-e2b-20260922"
    config_hash = config_hash_override or sha256(CONFIG)
    plan_hash = plan_hash_override or sha256(MIXED)
    controller_sha = str(receipt.get("controller_sha") or "")
    latency_enabled = "1" if timing_policy.get("enabled", False) else "0"
    latency_guard = int(timing_policy.get("wall_guard_grace_seconds", 600))
    round_wait = int((config.get("delivery") or {}).get("round_wait_seconds", 86400))
    run = f'''#!/usr/bin/env bash
set -u
mkdir -p /opt/hse-run
exec >> /opt/hse-run/controller.log 2>&1
export PATH=/opt/hse-venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONPATH=/opt/hse-round/backend PYTHONDONTWRITEBYTECODE=1
export MIXED_TASK_MANIFEST=/opt/hse-round/mixed-task-manifest.json PERSONA_ROSTER=/opt/hse-round/persona-roster.json AUTO_DESIGNER_GITEA_ENV_FILE=/opt/hse-round/backend/deploy/gitea/.env
export AUTO_DESIGNER_EXPERIMENT_ID={experiment_id} AUTO_DESIGNER_RUN_ID={run_id} AUTO_DESIGNER_CONFIG_HASH={config_hash} AUTO_DESIGNER_CONTROLLER_SHA={controller_sha} AUTO_DESIGNER_PLAN_HASH={plan_hash} AUTO_DESIGNER_RECOVERY_ROOT=/opt/hse-run/recovery
export AUTO_DESIGNER_HARNESS_ARCHIVE=/opt/hse-round/harness-v0-cade14d.tar.gz AUTO_DESIGNER_OBJECTIVE_EVALUATION=0 TOTAL_ROUNDS={int(config['rounds'])} SESSIONS_PER_ROUND={int(profile['user'])} N_USERS={int(profile['user'])}
export AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT={latency_enabled} AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS={latency_guard}
export ROUND_DELIVERY_TIMEOUT_SEC={round_wait}
export N_TRIAGERS={int(profile['triager'])} N_DESIGNERS={int(profile['designer'])} N_DEVELOPERS={int(profile['developer'])} N_DIVERGENTS={int(profile['pm'])} N_OWNERS={int(profile['owner'])} MAX_PARALLEL_USERS={int(profile['task_parallel'])} OPENAGENTS_PERMISSION_MODE=bypassPermissions VIGIL_MODE=subprocess
set +e
/opt/hse-venv/bin/python -u /opt/hse-round/backend/scripts/run_mixed_closed_loop.py
code=$?
echo "$code" > /opt/hse-run/exit_code
exit "$code"
'''
    return {"/opt/hse-round/backend/.env": backend_env, "/opt/hse-round/backend/deploy/gitea/.env": gitea_env, "/opt/hse-round/mixed-task-manifest.json": json.dumps(manifest, ensure_ascii=False) + "\n", "/opt/hse-round/persona-roster.json": json.dumps(roster, ensure_ascii=False) + "\n", "/opt/hse-round/run.sh": run, "/opt/hse-round/.runtime-identity.json": json.dumps({"run_id": run_id, "n": manifest["n"]}) + "\n"}


def setup_script() -> str:
    return r'''set -eux
mkdir -p /opt/hse-round/backend/deploy/gitea /opt/hse-run/payloads-incoming /opt/hse-run/workspaces
tar -xzf /tmp/hse-code.tar.gz -C /opt/hse-round
tar -xzf /tmp/hse-openagents.tar.gz -C /opt/hse-round
tar -xzf /tmp/hse-nexau.tar.gz -C /opt/hse-round
mkdir -p /opt/hse-round/harness
install -m 0644 /tmp/hse-harness.tar.gz /opt/hse-round/harness-v0-cade14d.tar.gz
tar -xzf /tmp/hse-harness.tar.gz -C /opt/hse-round/harness
install -m 0755 /tmp/claude-bin /usr/local/bin/claude
curl -fL --retry 3 'https://github.com/astral-sh/python-build-standalone/releases/download/20260814/cpython-3.12.14%2B20260814-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz' -o /tmp/python312.tar.gz
echo '5acfa3e9ba26b51ae161c83aff278da915b590d22373a424b2ba55b8afe91fcc  /tmp/python312.tar.gz' | sha256sum -c -
tar -xzf /tmp/python312.tar.gz -C /opt
/opt/python/bin/python3 -m venv /opt/hse-venv
/opt/hse-venv/bin/pip install --no-cache-dir requests ruamel.yaml jsonschema fastapi uvicorn pyarrow
/opt/hse-venv/bin/pip install --no-cache-dir -e /opt/hse-round/NexAU
/opt/hse-venv/bin/pip install --no-cache-dir 'ag-ui-protocol==0.1.22' 'e2b==2.51.0'
/opt/hse-venv/bin/pip install --no-cache-dir -e /opt/hse-round/OpenAgents
tar -xzf /opt/hse-run/payloads-incoming/task-payloads.tar.gz -C /opt/hse-run/payloads-incoming
for archive in /opt/hse-run/payloads-incoming/payloads/agent/*.tar.gz; do tar -xzf "$archive" -C /opt/hse-run/workspaces; done
cp -a /opt/hse-run/payloads-incoming/payloads /opt/hse-run/
chmod +x /opt/hse-round/run.sh
touch /opt/hse-round/.gitignore
git -C /opt/hse-round init -b main
git -C /opt/hse-round config user.name hse-runtime
git -C /opt/hse-round config user.email hse-runtime@localhost
git -C /opt/hse-round add .gitignore backend/auto_designer backend/agent_defs backend/harness_template backend/run.py backend/scripts backend/persona_library.json pyproject.toml
git -C /opt/hse-round commit -m 'Snapshot uploaded controller sources'
chown -R user:user /opt/hse-round /opt/hse-run
'''


def create_sandbox(
    manifest: dict,
    creds: dict[str, str],
    repo: str,
    config: dict,
    profile: dict,
    run_id: str,
    *,
    experiment_id: str | None = None,
    config_hash_override: str | None = None,
    plan_hash_override: str | None = None,
):
    from e2b import Sandbox
    temp = Path(tempfile.mkdtemp(prefix=f"hse-n{manifest['n']}-"))
    code, oa, nexau, payloads = (temp / name for name in ("code.tar.gz", "openagents.tar.gz", "nexau.tar.gz", "payloads.tar.gz"))
    source_archive(code)
    archive_tree(OPENAGENTS, oa, "OpenAgents")
    archive_tree(NEXAU, nexau, "NexAU")
    payload_bundle(manifest["tasks"], payloads)
    sandbox = Sandbox.create(template=(config.get("e2b") or {}).get("template_alias") or "base", timeout=int((config.get("e2b") or {}).get("lifetime_seconds", 86400)), allow_internet_access=True, metadata={"experiment_id": experiment_id or f"hse-n{manifest['n']}-e2b-20260922", "run_id": run_id}, api_key=creds["E2B_API_KEY"])
    try:
        sandbox.commands.run("mkdir -p /opt/hse-round/backend/deploy/gitea /opt/hse-run/payloads-incoming", user="root", timeout=30)
        def upload(local: Path, remote: str) -> None:
            with local.open("rb") as stream:
                sandbox.files.write(remote, stream, request_timeout=1800, use_octet_stream=True)
        for local, remote in ((code, "/tmp/hse-code.tar.gz"), (oa, "/tmp/hse-openagents.tar.gz"), (nexau, "/tmp/hse-nexau.tar.gz"), (payloads, "/opt/hse-run/payloads-incoming/task-payloads.tar.gz"), (HARNESS_ARCHIVE, "/tmp/hse-harness.tar.gz"), (CLAUDE, "/tmp/claude-bin")):
            if not local.is_file():
                raise LaunchError(f"upload source missing: {local}")
            upload(local, remote)
        for path, text in remote_files(
            manifest, creds, repo, config, profile, run_id,
            experiment_id=experiment_id,
            config_hash_override=config_hash_override,
            plan_hash_override=plan_hash_override,
        ).items():
            sandbox.files.write(path, text)
        setup = sandbox.commands.run(setup_script(), user="root", timeout=3600)
        if setup.exit_code != 0:
            raise LaunchError(f"E2B setup failed: {setup.stderr or setup.stdout}")
        return sandbox
    except Exception:
        try:
            sandbox.kill()
        except Exception:
            pass
        raise


def start_remote(sandbox, resume: bool, extra_env: dict[str, str] | None = None):
    envs = {"AUTO_DESIGNER_RUN_MODE": "resume" if resume else "fresh"}
    envs.update(extra_env or {})
    return sandbox.commands.run("bash /opt/hse-round/run.sh", envs=envs, user="user", background=True, timeout=86400)


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def start_status_relay(*, run_id: str, sandbox_id: str) -> int | None:
    """Start the non-critical E2B -> VPS status relay for this run."""
    relay = SUITE / "sync_status_vps.py"
    vps_file = ROOT.parent / ".vps"
    if not relay.is_file() or not vps_file.is_file():
        return None
    # Do not create duplicate relays when an operator resumes a run.
    try:
        existing = subprocess.run(
            ["pgrep", "-f", f"sync_status_vps.py --run-id {run_id} "],
            capture_output=True, text=True, check=False,
        )
        if existing.stdout.strip():
            return int(existing.stdout.splitlines()[0])
    except (OSError, ValueError):
        pass
    proc = subprocess.Popen(
        [sys.executable, str(relay), "--run-id", run_id, "--sandbox-id", sandbox_id,
         "--vps-file", str(vps_file)],
        cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return proc.pid


def start_lifecycle_guardian(*, run_id: str, sandbox_id: str, receipt: Path) -> int | None:
    """Keep a fresh scaling sandbox leased and persist E2B snapshots.

    The controller's round checkpoints are not E2B snapshots.  The guardian
    is deliberately host-side so a controller crash cannot take the only
    copy of the recovery state with it.
    """
    guardian = SUITE / "e2b_lifecycle_guardian.py"
    e2b_file = ROOT.parent / ".e2b"
    if not guardian.is_file() or not e2b_file.is_file():
        return None
    proc = subprocess.Popen(
        [sys.executable, str(guardian), "--run-id", run_id,
         "--sandbox-id", sandbox_id, "--receipt", str(receipt),
         "--e2b-env", str(e2b_file), "--interval", "600",
         "--snapshot-interval", "1800"],
        cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return proc.pid


def fresh(n: int, config: dict, creds: dict[str, str]) -> int:
    rows, profile = task_rows(n), config["profiles"][str(n)]
    manifest = build_manifest(n, rows, profile, int(config["rounds"]))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
    repo = f"hse-n{n}-20260922-{run_id}"
    ensure_repo(creds, repo, resume=False)
    sandbox = create_sandbox(manifest, creds, repo, config, profile, run_id)
    command = start_remote(sandbox, False)
    path = SUITE / "runs" / "scaling-e2b-20260922" / f"n{n}" / run_id / "state.json"
    write_state(path, {"n": n, "run_id": run_id, "sandbox_id": sandbox.sandbox_id, "gitea_repo_name": repo, "manifest": manifest, "command_id": getattr(command, "cmd_id", None), "started_at": datetime.now(UTC).isoformat()})
    guardian_receipt = path.parent / "guardian.jsonl"
    guardian_pid = start_lifecycle_guardian(
        run_id=run_id, sandbox_id=sandbox.sandbox_id, receipt=guardian_receipt
    )
    relay_pid = start_status_relay(run_id=run_id, sandbox_id=sandbox.sandbox_id)
    state = read_json(path)
    state["guardian_pid"] = guardian_pid
    state["guardian_receipt"] = str(guardian_receipt)
    state["status_relay_pid"] = relay_pid
    write_state(path, state)
    print(f"STARTED run_id={run_id} E2B_SANDBOX_ID={sandbox.sandbox_id} STATE={path}")
    return 0


def resume(n: int, run_id: str, creds: dict[str, str], *, allow_failed: bool = False) -> int:
    path = SUITE / "runs" / "scaling-e2b-20260922" / f"n{n}" / run_id / "state.json"
    state = read_json(path)
    if int(state.get("n")) != n:
        raise LaunchError("state N mismatch")
    ensure_repo(creds, state["gitea_repo_name"], resume=True)
    from e2b import Sandbox
    sandbox = Sandbox.connect(state["sandbox_id"], api_key=creds["E2B_API_KEY"], timeout=86400, on_resume="restore")
    controller = sandbox.commands.run("pgrep -af '[p]ython.*scripts/run_mixed_closed_loop.py' || true", timeout=30)
    if controller.stdout.strip():
        print("ALREADY_RUNNING")
        return 0
    probe = sandbox.commands.run("test -f /opt/hse-run/exit_code && cat /opt/hse-run/exit_code || true", timeout=30)
    exit_text = probe.stdout.strip()
    if exit_text and (not allow_failed or exit_text == "0"):
        print(f"ALREADY_FINISHED exit_code={exit_text}")
        return int(exit_text)
    policy = (read_json(CONFIG).get("timeouts") or {}).get("latency_isolated_timeout") or {}
    extra_env = {}
    if policy.get("enabled"):
        extra_env = {
            "AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT": "1",
            "AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS": str(int(policy.get("wall_guard_grace_seconds", 600))),
        }
    extra_env["ROUND_DELIVERY_TIMEOUT_SEC"] = str(
        int((read_json(CONFIG).get("delivery") or {}).get("round_wait_seconds", 86400))
    )
    if exit_text:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = "/opt/hse-run/recovery-overrides/auto-resume-" + stamp
        sandbox.commands.run(
            f"mkdir -p {backup} && mv /opt/hse-run/exit_code {backup}/exit_code.previous",
            user="root", timeout=20,
        )
    command = start_remote(sandbox, True, extra_env=extra_env)
    state["resume_command_id"] = getattr(command, "cmd_id", None)
    state["status_relay_pid"] = start_status_relay(run_id=run_id, sandbox_id=state["sandbox_id"])
    write_state(path, state)
    print(f"RESUMED run_id={run_id} E2B_SANDBOX_ID={state['sandbox_id']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, choices=(1, 4, 8, 16, 32), required=True)
    parser.add_argument("--gitea-env", type=Path)
    parser.add_argument("--gitea-source-sandbox-id", help="relay the validated Gitea credentials from an existing N=1 E2B sandbox")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-failed-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        config = read_json(CONFIG)
        if args.dry_run:
            print(json.dumps({"n": args.n, "rounds": config["rounds"], "profile": config["profiles"][str(args.n)]}, ensure_ascii=False, indent=2))
            return 0
        creds = credentials(
            args.gitea_env.expanduser().resolve() if args.gitea_env else None,
            args.gitea_source_sandbox_id,
        )
        if args.resume:
            if not args.run_id:
                raise LaunchError("--resume requires --run-id")
            return resume(args.n, args.run_id, creds, allow_failed=args.allow_failed_resume)
        return fresh(args.n, config, creds)
    except (LaunchError, OSError, KeyError, ValueError) as exc:
        print(f"LAUNCH_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
