"""Spec-0073/T4: shared experiment runtime: repository, delivery process and round receipts."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # frozen backend source
DATA = ROOT / "data"
# dev/architect's sandbox working directory = harness repo. Sink it into an independent parent directory
# (data/harness_sandbox/harness_repo) containing only itself, so trace directories (data/sessions for context+sessions, data/harness_runs
# harness run copies) are no longer at its `../` peer level—— relative paths like `../sessions/*.json`, `../harness_runs/**`
# cannot reach them directly. Block the overfitting leak where "dev/architect reviews task trajectory → brings task-specific artifacts (repo API/file types/expected output)
# into harness" (same source as the submission boundary gate issue; see agent_defs/architect/systemprompt.md hard-forbidden section).
# Note: bash can still use absolute paths, but relative navigation (ls ..) cannot see trace, blocking the only realistic discovery path.
_SANDBOX_ROOT = DATA / "harness_sandbox"
HARNESS_REPO = _SANDBOX_ROOT / "harness_repo"
GITEA_ENV_FILE: Path | None = None  # assigned by explicit frozen context

TOTAL_ROUNDS = 0  # populated from explicit frozen inputs in main


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"')
    return out


def _git(repo: Path, *args: str) -> None:
    command = ["git", "-C", str(repo), "-c", "user.email=seed@x", "-c", "user.name=seed", *args]
    # A newly-created Gitea repository can accept ls-remote before its git
    # backend is ready for the first push.  Retry only push operations so this
    # transient race cannot abort an otherwise valid fresh experiment.
    attempts = 4 if args and args[0] == "push" else 1
    for attempt in range(attempts):
        try:
            subprocess.run(command, check=True, capture_output=True)
            return
        except subprocess.CalledProcessError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(2**attempt)


def _gitea_remote_url(gitea: dict[str, str]) -> str:
    """Construct a Gitea git remote URL with token: http://OWNER:TOKEN@host/OWNER/REPO.git."""
    from urllib.parse import urlparse, urlunparse

    u = urlparse(gitea["GITEA_URL"])
    netloc = f"{gitea['OWNER']}:{gitea['TOKEN']}@{u.netloc}"
    return urlunparse((u.scheme, netloc, f"/{gitea['OWNER']}/{gitea['REPO']}.git", "", "", ""))


def _isolate_git_credentials() -> None:
    """Process-level git credential isolation (Spec-0021/T2): escaped dev agent must not push to GitHub.

    Tested escape chain: dev agent uses python heredoc tunnel to bypass workspace-jail path scanning, `os.chdir` into the orchestration repo
    and `git push`. Credential leaks have **multiple silent channels**; blocking one channel is insufficient:
    - **ssh transport** (GitHub `git@…`): set `GIT_SSH_COMMAND=false` to fail ssh calls.
    - **terminal interactive prompt**: `GIT_TERMINAL_PROMPT=0`.
    - **askpass silent channel**: `GIT_ASKPASS`/`SSH_ASKPASS` point to a program that can directly emit credentials (tested: VS Code +
      WSL environment injects `GIT_ASKPASS`; when git uses HTTPS, it silently obtains GitHub token—— `GIT_TERMINAL_PROMPT=0`
      **cannot control it**). Also clear VS Code's `VSCODE_GIT_ASKPASS_*`/IPC.
    - **credential.helper silent channel**: store/manager/keychain also silently return credentials. Reset the helper list via empty value injected through GIT_CONFIG_*
      (append, not overwrite existing injections)—— git ≥2.31 supports this.

    No impact on legitimate workflows: dev/harness pushes to Gitea via `http://OWNER:TOKEN@host/…` (credentials in URL, not through
    askpass/helper); local non-transport git operations also do not involve credentials. `GIT_SSH_COMMAND` uses setdefault to leave room for ops override.
    """
    os.environ.setdefault("GIT_SSH_COMMAND", "false")
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    for _k in (
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "SSH_AUTH_SOCK",
        "VSCODE_GIT_ASKPASS_NODE",
        "VSCODE_GIT_ASKPASS_MAIN",
        "VSCODE_GIT_ASKPASS_EXTRA_ARGS",
        "VSCODE_GIT_IPC_HANDLE",
    ):
        os.environ.pop(_k, None)
    try:
        _n = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
    except ValueError:
        _n = 0
    os.environ["GIT_CONFIG_COUNT"] = str(_n + 1)
    os.environ[f"GIT_CONFIG_KEY_{_n}"] = "credential.helper"
    os.environ[f"GIT_CONFIG_VALUE_{_n}"] = ""


def _set_gitea_remote(repo: Path, gitea: dict[str, str]) -> None:
    """Configure only the local harness repo with Gitea origin (with token). Pushing is performed by the developer agent using the git tool itself, not here."""
    url = _gitea_remote_url(gitea)
    remotes = subprocess.run(
        ["git", "-C", str(repo), "remote"], capture_output=True, text=True
    ).stdout.split()
    if "origin" in remotes:
        _git(repo, "remote", "set-url", "origin", url)
    else:
        _git(repo, "remote", "add", "origin", url)


def _seed_harness_repo() -> Path:
    """Plant a local git repo from harness_template: main branch only (Spec-0007/T4: pure trunk, no longer create release branches)."""
    if HARNESS_REPO.exists():
        shutil.rmtree(HARNESS_REPO)
    HARNESS_REPO.mkdir(parents=True)
    archive_raw = os.environ.get("AHE_BETA_HARNESS_ARCHIVE", "").strip()
    if archive_raw:
        archive = Path(archive_raw).expanduser().resolve()
        if not archive.is_file():
            raise SystemExit(f"Frozen Harness archive does not exist: {archive}")
        try:
            with tarfile.open(archive, "r:gz") as bundle:
                bundle.extractall(HARNESS_REPO, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise SystemExit(f"Failed to unpack frozen Harness archive: {archive}: {exc}") from exc
    else:
        template = ROOT / "harness_template"
        for item in template.iterdir():
            dest = HARNESS_REPO / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    subprocess.run(
        ["git", "init", "-b", "main", str(HARNESS_REPO)], check=True, capture_output=True
    )
    # Spec-0079/T4: inherited trees bypass git add and clean filters entirely.
    inherited_path = os.environ.get("AHE_BETA_CONTINUATION_INPUT", "").strip()
    if inherited_path:
        _seed_inherited_tree(input_path=Path(inherited_path))
        return HARNESS_REPO
    # Clear bytecode cache from template copy, write .gitignore, so v0 seed contains only harness artifacts.
    # Spec-0032/T5: .openagents/ is vigil's local runtime state (queue db/claims/config), resets to zero with rmtree per run,
    # and is never committed.
    from ahe_beta.guards.harness_boundary import install_pre_commit  # noqa: PLC0415

    for pyc in HARNESS_REPO.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)
    (HARNESS_REPO / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.openagents/\n", encoding="utf-8"
    )
    _git(HARNESS_REPO, "add", ".")
    _git(HARNESS_REPO, "commit", "-m", "seed: harness v0")
    # Submission boundary hard gate: install pre-commit hook. After container containment, switch to rejection list (secrets / .openagents),
    # no longer use top-level whitelist locking down product shape (docs/specs, structural evolution should be allowed). git worktree shares hooks.
    # Hook installed after seed commit. Server-side fallback via boundary check step in smoke.yml (--no-verify cannot bypass it).
    install_pre_commit(HARNESS_REPO)
    return HARNESS_REPO


def _remote_tag_refs(ls_output: str) -> list[str]:
    """`git ls-remote --tags` output → list of deletable true tag refs.

    Spec-0032 empirical fix #2: annotated tags output two lines—`refs/tags/v1` and peeled line `refs/tags/v1^{}`;
    the latter is a dereference display, not a true ref. `push origin :refs/tags/v1^{}` crashes with code 128 and breaks the reset flow; must skip.
    """
    refs: list[str] = []
    for line in ls_output.splitlines():
        ref = line.split("\t")[-1]
        if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            refs.append(ref)
    return refs


def _reset_to_initial(repo: Path, tracker) -> None:
    """Reset to initial state before running tests: Gitea harness repo back to v0 + close stale issues + clear board data.

    - Gitea: force-push local v0 seed to origin/main, delete all remote vK tags — harness returns to v0 baseline
      (dev agent works in the same local repo, pushes to the same origin, so force-push here is compatible with subsequent fast-forward pushes).
    - issue: close all stale open issues (issue numbers/history cannot be erased via API, only the open set is reset).
    - board: clear data/live/ projection. Spec-0049/T4: must not delete role_runs (including their sessions);
      sessions have migrated to ROLE_RUNS_DIR/sessions and no longer follow shared DATA/sessions/*.json for erasure.
    """
    _git(repo, "push", "-f", "origin", "main")  # Override remote main back to v0 seed
    ls = subprocess.run(
        ["git", "-C", str(repo), "ls-remote", "--tags", "origin"],
        capture_output=True,
        text=True,
    ).stdout
    for ref in _remote_tag_refs(ls):
        _git(repo, "push", "origin", f":{ref}")  # Delete remote tags (legacy vK cleanup)
    for issue in tracker.list_open_issues():
        try:
            tracker.set_state(issue.number, "closed", "reset to initial before clean run")
        except Exception:  # noqa: BLE001  issue close failure does not block reset
            pass
    from ahe_beta.loop.live import clear_live  # noqa: PLC0415  same deferred import style as main()

    clear_live(data_dir=DATA)


# Spec-0032/T5: delivery surface stages finalized (single source of truth written to harness repo .openagents/openagents.yml).
# Spec-0040/T1: rfc changed from skip to agent—solve first has drafter land docs/specs, then implement
# (spec CLI runs in vigil image, not in harness repo). triage=skip: admission already completed by Owner;
# ci defaults to skip, enabled via VIGIL_CI_STAGE=agent—vigil decision table "zero check=perpetual CI wait", must verify first
# act_runner truly running before opening ci gate, otherwise all tickets block at the watchdog; e2e=skip in phase 2;
# review/merge=agent: engineering quality gates fully automated (review present, does not trigger OpenAgents "zero-gate forbidden" guard).
_VIGIL_STAGES: dict[str, str] = {
    "triage": "skip",
    "rfc": "agent",
    "conflict": "agent",
    "ci": "skip",  # write_openagents_config overrides per VIGIL_CI_STAGE
    "e2e": "skip",
    "review": "agent",
    "merge": "agent",
}
# vigil poll interval (seconds): tighter than OpenAgents default 60s—local Gitea has no rate pressure, reducing admission-to-pickup latency.
_VIGIL_INTERVAL = 30


def install_role_runs(*, data_root: Path) -> Path:
    """Nail AHE_BETA_RUN_ID / ROLE_RUNS_DIR / usage path for this process.

    Spec-0049/T4: one closed-loop process gets one slice; board data/sessions is merely an alias pointing to current sessions.
    """
    run_id = os.environ.get("AHE_BETA_RUN_ID", "").strip() or uuid.uuid4().hex
    os.environ["AHE_BETA_RUN_ID"] = run_id
    root = data_root / "role_runs" / run_id
    (root / "demand").mkdir(parents=True, exist_ok=True)
    (root / "delivery").mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    os.environ["ROLE_RUNS_DIR"] = str(root)
    os.environ["AHE_BETA_USAGE_PATH"] = str(root / "usage.jsonl")
    _alias_current_sessions(data_root=data_root, sessions_root=root / "sessions")
    return root


def experiment_run_mode() -> str:
    """Return the explicit lifecycle mode used by recoverable experiment runs."""
    mode = os.environ.get("AHE_BETA_RUN_MODE", "fresh").strip().lower() or "fresh"
    if mode not in {"fresh", "resume", "replay"}:
        raise SystemExit(f"AHE_BETA_RUN_MODE must be fresh, resume, or replay: {mode!r}")
    return mode


def load_recovery_store(*, mode: str):
    """Create/open the shared recovery ledger when an experiment identity is present."""
    root_raw = os.environ.get("AHE_BETA_RECOVERY_ROOT", "").strip()
    identity_names = {
        "experiment_id": "AHE_BETA_EXPERIMENT_ID",
        "run_id": "AHE_BETA_RUN_ID",
        "config_hash": "AHE_BETA_CONFIG_HASH",
        "controller_sha": "AHE_BETA_CONTROLLER_SHA",
        "plan_hash": "AHE_BETA_PLAN_HASH",
    }
    values = {field: os.environ.get(name, "").strip() for field, name in identity_names.items()}
    configured = bool(root_raw or any(values.values()))
    if not configured:
        return None
    missing = [name for field, name in identity_names.items() if not values[field]]
    if not root_raw:
        missing.append("AHE_BETA_RECOVERY_ROOT")
    if missing:
        raise SystemExit(
            "Recovery identity environment variables are incomplete: " + ", ".join(missing)
        )
    from ahe_beta.loop.recovery import RecoveryIdentity, RecoveryStore  # noqa: PLC0415

    identity = RecoveryIdentity(**values)
    root = Path(root_raw).expanduser().resolve()
    if mode in {"fresh", "replay"}:
        return RecoveryStore.initialize(root=root, identity=identity)
    return RecoveryStore.open(root=root, identity=identity)


def existing_harness_repo() -> Path:
    """Return the preserved harness repo required by resume without mutating it."""
    if not (HARNESS_REPO / ".git").is_dir():
        raise SystemExit(f"resume requires an initialized harness repository: {HARNESS_REPO}")
    return HARNESS_REPO


def _alias_current_sessions(*, data_root: Path, sessions_root: Path) -> None:
    """Point data/sessions at this run's sessions without deleting prior role_runs."""
    alias = data_root / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    try:
        if alias.is_symlink() or alias.is_file():
            alias.unlink()
        elif alias.is_dir():
            leftover = data_root / "sessions_pre_0049"
            if not leftover.exists():
                alias.rename(leftover)
            else:
                return
        alias.symlink_to(sessions_root, target_is_directory=True)
    except OSError:
        return


def current_role_runs_dir() -> Path | None:
    raw = os.environ.get("ROLE_RUNS_DIR", "").strip()
    return Path(raw) if raw else None


def apply_experiment_context(*, ctx: object) -> None:
    """Spec-0047/T4: use ExperimentContext to override singleton DATA/HARNESS/vigil resource names."""
    global \
        DATA, \
        HARNESS_REPO, \
        _SANDBOX_ROOT, \
        _VIGIL_CONTAINER, \
        _VIGIL_NETWORK, \
        _VIGIL_CONFIG_STAGING, \
        GITEA_ENV_FILE
    experiment_id = str(ctx.experiment_id)  # type: ignore[attr-defined]
    os.environ["AHE_BETA_EXPERIMENT_ID"] = experiment_id
    DATA = Path(ctx.data_root)  # type: ignore[attr-defined]
    _SANDBOX_ROOT = DATA / "harness_sandbox"
    HARNESS_REPO = Path(ctx.harness_repo)  # type: ignore[attr-defined]
    _VIGIL_CONTAINER = str(ctx.vigil_container)  # type: ignore[attr-defined]
    # Spec-0070/T3: early session preflight must resolve the same reusable container.
    os.environ["AHE_BETA_VIGIL_CONTAINER"] = _VIGIL_CONTAINER
    _VIGIL_NETWORK = str(ctx.vigil_network)  # type: ignore[attr-defined]
    _VIGIL_CONFIG_STAGING = Path(ctx.vigil_config_root)  # type: ignore[attr-defined]
    GITEA_ENV_FILE = DATA.parent / "secrets" / "demand-gitea.env"


def write_openagents_config(*, repo: Path, gitea: dict[str, str]) -> Path:
    """Write delivery surface declarative config to harness repo `.openagents/openagents.yml` (Spec-0032/T5).

    forge=gitea + connection tuple (token itself not persisted to disk, only token_env=GITEA_TOKEN declared, provided by vigil subprocess
    env); stages from _VIGIL_STAGES; labels=[openagents] (Owner admission handoff token = label vigil discovers).
    """
    config_dir = repo / ".openagents"
    config_dir.mkdir(parents=True, exist_ok=True)
    # Spec-0032/T6: ci gate switches when infrastructure is ready—set VIGIL_CI_STAGE=agent after act_runner verification is running.
    effective = dict(_VIGIL_STAGES)
    ci_stage = os.environ.get("VIGIL_CI_STAGE", "").strip().lower()
    if ci_stage in ("agent", "human", "skip"):
        effective["ci"] = ci_stage
    coordination = os.environ.get("VIGIL_COORDINATION", "soft").strip().lower()
    if coordination not in {"soft", "off", "dependencies"}:
        raise ValueError("VIGIL_COORDINATION must be soft, off, or dependencies")
    stages = "\n".join(f"  {stage}: {owner}" for stage, owner in effective.items())
    text = (
        "# Generated by the ordinary controller for each run (Spec-0032/T5); edit its canonical constants instead of this file.\n"
        "version: 1\n"
        "forge: gitea\n"
        "execution_evidence:\n"
        "  required: true\n"
        f"coordination: {coordination}\n"
        "gitea:\n"
        f"  base_url: {gitea['GITEA_URL']}\n"
        f"  owner: {gitea['OWNER']}\n"
        f"  repo: {gitea['REPO']}\n"
        "  token_env: GITEA_TOKEN\n"
        f"stages:\n{stages}\n"
        "release: manual\n"
        "defaults:\n"
        f"  interval: {_VIGIL_INTERVAL}\n"
        "  base: main\n"
        "  labels: [openagents]\n"
    )
    path = config_dir / "openagents.yml"
    path.write_text(text, encoding="utf-8")
    return path


def ensure_openagents_cli() -> None:
    """Delivery surface CLI pre-check (subprocess mode): `openagents` must be in PATH."""
    if shutil.which("openagents") is None:
        raise SystemExit(
            "Cannot find `openagents` on PATH (delivery CLI); "
            "uv tool install --from <OpenAgents-repo>@<revision-with-forge/Gitea-driver> openagents"
        )


# Spec-0033/T2: delivery surface execution mode. container (default) = sandbox: zero host mounts from clone, internal network +
# egress proxy allowlist; subprocess = host-direct run, no sandbox, only for ad-hoc debugging with human monitoring logs.
_VIGIL_IMAGE = os.environ.get("AHE_BETA_VIGIL_IMAGE", "").strip() or "ahe-beta-vigil:latest"
_VIGIL_CONTAINER = os.environ.get("AHE_BETA_VIGIL_CONTAINER", "").strip() or "ahe-beta-vigil"
# internal network in deploy/gitea compose (referenced by name)
_VIGIL_NETWORK = "ahe-beta-vigil-net"
_VIGIL_PROXY_URL = "http://egress-proxy:3128"  # only external network channel in the box (allowlist in egress-proxy.conf)
# config staging for container mode (read-only mounted to /config)
_VIGIL_CONFIG_STAGING = DATA / "vigil_config"
# claude credential one of three (Spec-0033): API key / gateway Bearer token (with ANTHROPIC_BASE_URL, must be
# Anthropic protocol endpoint, and gateway domain added to egress-proxy.conf allowlist) / subscription long-lived token (claude setup-token).
_CLAUDE_CRED_ENVS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
# claude non-credential config env (passed to container only if present): base_url (self-hosted/third-party Anthropic protocol gateway) + model override.
# When connecting to unofficial gateways (e.g., Anthropic endpoint on OpenAI-compatible gateway), model name is not claude-* but the gateway's own model id;
# must be overridden via ANTHROPIC_MODEL; claude has a "small/fast model" tier for lightweight calls (default haiku), must override if gateway lacks this model
# ANTHROPIC_SMALL_FAST_MODEL must point to the same one; otherwise that call will 404.
_CLAUDE_CONFIG_ENVS = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    # Spec-0069/T2: candidate versions stay pinned inside delivery containers too.
    "DISABLE_UPDATES",
    "OPENAGENTS_NO_SELF_UPDATE",
    "OPENAGENTS_CLAUDE_IDLE_TIMEOUT",
)


def _subagent_model_lock_env() -> dict[str, str]:
    """Keep OpenAgents' Claude Code subagents on the delivery session's model.

    FORCE defeats an Agent tool call's explicit ``model=sonnet``/``haiku`` on
    Claude Code >= 2.1.257.  Pinning the same model as well covers older
    supported CLIs where SUBAGENT_MODEL itself had higher precedence.
    """
    lock = {"CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"}
    model = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if model:
        lock["CLAUDE_CODE_SUBAGENT_MODEL"] = model
    return lock


# The product harness is a separate OpenAI-compatible client.  Pass its explicitly scoped GLM
# configuration into the delivery container under the plain names consumed by scripts/run.sh.
_HARNESS_LLM_SUFFIXES = ("MODEL", "BASE_URL", "API_KEY")


class VigilHandle:
    """Delivery-plane runtime handle: mode + managed process (subprocess=vigil itself; container=docker logs follower) + log handle.

    keep_alive: whether the demand-side cleanup should tear down vigil. Spec-0050/T4: default teardown; only if explicitly VIGIL_KEEP_ALIVE=1 or handle.keep_alive=True on deadlock do we keep the container.
    """

    def __init__(
        self, *, mode: str, proc: subprocess.Popen, log_handle: object, keep_alive: bool
    ) -> None:
        self.mode = mode
        self.proc = proc
        self.log_handle = log_handle
        self.keep_alive = keep_alive


def vigil_mode() -> str:
    """Parse VIGIL_MODE: container (default) / subprocess (explicit opt-in); other values fail-loud."""
    raw = os.environ.get("VIGIL_MODE", "").strip().lower() or "container"
    if raw not in ("container", "subprocess"):
        raise SystemExit(f"Invalid VIGIL_MODE: {raw!r} (choose container / subprocess)")
    return raw


def vigil_keep_alive() -> bool:
    """Return whether vigil should survive the demand-side finally.

    Spec-0050/T4: default teardown (not the final round pending delivery closure). Only explicit 1/true/yes/on enables persistent debugging. Deadlock paths are handled by the caller setting handle.keep_alive to True; this function is not called.
    """
    raw = os.environ.get("VIGIL_KEEP_ALIVE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _vigil_internal_gitea_url() -> str:
    """Gitea address from container perspective (same service name); localhost address in host .env is for orchestration layer only."""
    return os.environ.get("VIGIL_GITEA_INTERNAL_URL", "").strip() or "http://gitea:3000"


def _vigil_gitea_url(*, gitea: dict[str, str]) -> str:
    """Spec-0070/T3: only hosted Gitea defaults to its public address in the container."""
    from ahe_beta.tracker.attachment_transport import download_policy

    override = os.environ.get("VIGIL_GITEA_INTERNAL_URL", "").strip()
    if override:
        return override
    if download_policy(gitea["GITEA_URL"]) == "gitea-com-r2-v1":
        return gitea["GITEA_URL"].rstrip("/")
    return _vigil_internal_gitea_url()


def _prepare_vigil_evidence(*, gitea: dict[str, str], mode: str) -> dict | None:
    """Spec-0070/T3: check the real reader before dispatch or reuse, without changing legacy runs."""
    from ahe_beta.observations.preflight import (
        needs_reader_capabilities,
        prepare_observations,
        probe_reader,
        write_reader_record,
    )
    from ahe_beta.observations.transport import load_transport_profile
    from ahe_beta.tracker.attachment_transport import download_policy
    from ahe_beta.tracker.gitea import GiteaTracker

    runs = Path(os.environ.get("ROLE_RUNS_DIR", "").strip() or str(DATA))
    root = Path(os.environ.get("AHE_BETA_OBSERVATION_ROOT", str(runs / "observations")))
    repository = f"{gitea['GITEA_URL'].rstrip('/')}/api/v1/repos/{gitea['OWNER']}/{gitea['REPO']}"
    profile = load_transport_profile(root=root, repository=repository)
    if profile is None and download_policy(gitea["GITEA_URL"]) == "same-origin-v1":
        return None
    if profile is not None and not needs_reader_capabilities(profile=profile):
        return None
    container = None
    if mode == "container":
        running, existing_run, experiment = _container_state(name=_VIGIL_CONTAINER)
        ours = os.environ.get("AHE_BETA_EXPERIMENT_ID", "").strip()
        run_id = os.environ.get("AHE_BETA_RUN_ID", "").strip()
        if running and experiment and experiment != ours:
            raise ValueError("refusing to probe another experiment's delivery container")
        if running and (not run_id or existing_run == run_id):
            container = _VIGIL_CONTAINER
    result = probe_reader(mode=mode, image=_VIGIL_IMAGE, container=container)
    if profile is None:
        tracker = GiteaTracker(
            base_url=gitea["GITEA_URL"],
            owner=gitea["OWNER"],
            repo=gitea["REPO"],
            token=gitea["TOKEN"],
        )
        profile = prepare_observations(tracker=tracker, root=root, reader_probe=lambda: result)
    write_reader_record(root=root, profile=profile, result=result)
    return {**result, "profile": profile}


def _ensure_vigil_container_prereqs() -> None:
    """Pre-flight check for container mode (fail-loud): docker available + image built + claude credentials in place."""
    if shutil.which("docker") is None:
        raise SystemExit(
            "Cannot find docker on PATH (required for VIGIL_MODE=container; use VIGIL_MODE=subprocess for debugging)"
        )
    running, existing_run, _experiment = _container_state(name=_VIGIL_CONTAINER)
    run_id = os.environ.get("AHE_BETA_RUN_ID", "").strip()
    if not (running and (not run_id or existing_run == run_id)):
        inspect = subprocess.run(
            ["docker", "image", "inspect", _VIGIL_IMAGE], capture_output=True, text=True
        )
        if inspect.returncode != 0:
            raise SystemExit(
                f"Missing vigil image {_VIGIL_IMAGE}; build it first: backend/deploy/vigil/build.sh "
                "<OpenAgents-repo-path> <NexAU-repo-path>"
            )
    if not any(os.environ.get(key, "").strip() for key in _CLAUDE_CRED_ENVS):
        raise SystemExit(
            "Missing Claude credentials: set ANTHROPIC_API_KEY (API billing) / ANTHROPIC_AUTH_TOKEN (gateway Bearer; "
            "configure ANTHROPIC_BASE_URL and allow the gateway domain in egress-proxy.conf) / CLAUDE_CODE_OAUTH_TOKEN"
            " (subscription billing; generate with host `claude setup-token`) (Spec-0033)"
        )


def start_vigil(*, repo: Path, parallel: int, gitea: dict[str, str], log_path: Path) -> VigilHandle:
    """Start the delivery-plane according to VIGIL_MODE (including mode-specific pre-flight checks and config persistence), returning handle for finally block cleanup via stop_vigil.

    container (default): config written to staging read-only mount into container; harness repo cloned by container entrypoint (zero host mounts—the only bidirectional medium between sides is Gitea, host repo and delivery-plane are decoupled); credentials only via container env. subprocess: existing behavior (config written to host repo, direct Popen), no isolation, with prominent warnings.
    """
    mode = vigil_mode()
    keep_alive = vigil_keep_alive()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "subprocess":
        if os.environ.get("AHE_BETA_EXECUTION_BACKEND") == "e2b" and os.environ.get(
            "AHE_BETA_SANDBOX_ID"
        ):
            print(
                "[vigil] subprocess inside E2B sandbox; the sandbox is the isolation boundary, and all roles share its filesystem"
            )
        else:
            print(
                "[vigil] ⚠ subprocess mode is uncontained (nested agents can read the host filesystem and use unrestricted networking); "
                "use only for supervised debugging; use container mode for long-running evolution loops (Spec-0033)"
            )
        ensure_openagents_cli()
        observation_runtime = _prepare_vigil_evidence(gitea=gitea, mode=mode)
        write_openagents_config(repo=repo, gitea=gitea)
        return _start_vigil_subprocess(
            repo=repo,
            parallel=parallel,
            gitea_token=gitea["TOKEN"],
            log_path=log_path,
            keep_alive=keep_alive,
            observation_runtime=observation_runtime,
        )
    _ensure_vigil_container_prereqs()
    observation_runtime = _prepare_vigil_evidence(gitea=gitea, mode=mode)
    staging = _VIGIL_CONFIG_STAGING
    # Unique fork point between same config and two reachability domains: container-side base_url uses internal service name address.
    write_openagents_config(
        repo=staging, gitea={**gitea, "GITEA_URL": _vigil_gitea_url(gitea=gitea)}
    )
    return _start_vigil_container(
        parallel=parallel,
        gitea=gitea,
        staging=staging,
        log_path=log_path,
        keep_alive=keep_alive,
        observation_runtime=observation_runtime,
    )


def _openagents_identity_env() -> dict[str, str]:
    """Translate identity only at the pinned OpenAgents invocation boundary.

    Its invocation writer uses these external field names. They are not AHE-Beta
    configuration aliases; overwrite inherited values to avoid misattributing logs.
    """
    return {
        "AUTO_DESIGNER_RUN_ID": os.environ.get("AHE_BETA_RUN_ID", ""),
        "AUTO_DESIGNER_ROUND": os.environ.get("AHE_BETA_ROUND", ""),
    }


def _start_vigil_subprocess(
    *,
    repo: Path,
    parallel: int,
    gitea_token: str,
    log_path: Path,
    keep_alive: bool,
    observation_runtime: dict | None,
) -> VigilHandle:
    """Direct host execution: `openagents vigil --parallel K` (cwd=harness repo, logs to log_path).

    GITEA_TOKEN only passed via subprocess env (token does not persist in config file). Level-triggered: receive ticket whenever it appears.
    """
    log_handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115  lifecycle tied to vigil process; closed on stop
    env = {
        **os.environ,
        **_openagents_identity_env(),
        **_subagent_model_lock_env(),
        "GITEA_TOKEN": gitea_token,
    }
    executable = "openagents"
    if observation_runtime is not None:
        executable = observation_runtime["runtime"]["executable"]
        env["OPENAGENTS_NO_SELF_UPDATE"] = "1"
        env["AHE_BETA_OBSERVATION_DOWNLOAD_POLICY"] = observation_runtime["profile"][
            "download_policy"
        ]
    if not os.environ.get("ANTHROPIC_MODEL", "").strip():
        env.pop("CLAUDE_CODE_SUBAGENT_MODEL", None)
    proc = subprocess.Popen(
        [executable, "vigil", "--parallel", str(max(1, parallel))],
        cwd=str(repo),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return VigilHandle(mode="subprocess", proc=proc, log_handle=log_handle, keep_alive=keep_alive)


def _container_is_running(*, name: str) -> bool:
    running, _run_id, _experiment = _container_state(name=name)
    return running


def _container_state(*, name: str) -> tuple[bool, str, str]:
    """Return (running, run_id label, experiment_id label)."""
    inspect = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            '{{.State.Running}}|{{index .Config.Labels "io.ahe-beta.run_id"}}|{{index .Config.Labels "io.openagents.experiment_id"}}',
            name,
        ],
        capture_output=True,
        text=True,
    )
    if inspect.returncode != 0:
        return False, "", ""
    parts = inspect.stdout.strip().split("|", 2)
    running_s = parts[0] if parts else ""
    run_label = parts[1] if len(parts) > 1 else ""
    exp_label = parts[2] if len(parts) > 2 else ""
    return running_s.lower() == "true", run_label, exp_label


def _attach_container_logs(*, log_path: Path, keep_alive: bool) -> VigilHandle:
    """Wire `docker logs -f` to log_path; not responsible for docker run (both new creation and reuse use the same path)."""
    log_handle = open(log_path, "a", encoding="utf-8")  # noqa: SIM115  lifecycle tied to follower; closed on stop
    logs = subprocess.Popen(
        ["docker", "logs", "-f", _VIGIL_CONTAINER], stdout=log_handle, stderr=subprocess.STDOUT
    )
    return VigilHandle(mode="container", proc=logs, log_handle=log_handle, keep_alive=keep_alive)


def _start_vigil_container(
    *,
    parallel: int,
    gitea: dict[str, str],
    staging: Path,
    log_path: Path,
    keep_alive: bool,
    observation_runtime: dict | None,
) -> VigilHandle:
    """Hardened container: start vigil container with `docker run -d --rm`, follow logs via `docker logs -f` into log_path.

    Mounts are read-only in two places only: staging config (/config) and entrypoint script; credentials (Gitea token / claude credentials) injected only via container env (visible via `docker inspect` on host side—the host is already inside the trust boundary). Clone address and proxy are container internal network names (vigil-net internal; direct outbound connection to public internet is physically disabled).

    Container already running (left behind by previous demand-side keep-alive) → attach log follower only, no docker run (same name would collide). Spec-0049/T4: if keep-alive and AHE_BETA_RUN_ID changes, tear down old container and rebuild to avoid delivery hanging on wrong run.
    """
    run_id = os.environ.get("AHE_BETA_RUN_ID", "").strip()
    running, existing_run, experiment_id = _container_state(name=_VIGIL_CONTAINER)
    ours = os.environ.get("AHE_BETA_EXPERIMENT_ID", "").strip()
    if running and experiment_id and experiment_id != ours:
        raise SystemExit(
            f"Refusing to attach to experiment {experiment_id}'s vigil container {_VIGIL_CONTAINER}; "
            "use backend/scripts/experiment.py"
        )
    if running and (not run_id or existing_run == run_id):
        print(
            f"[vigil] Container {_VIGIL_CONTAINER} is already running; reusing it without docker run"
        )
        return _attach_container_logs(log_path=log_path, keep_alive=keep_alive)
    if running:
        print(
            f"[vigil] Container {_VIGIL_CONTAINER} run_id changed ({existing_run}→{run_id}); rebuilding"
        )
        subprocess.run(["docker", "rm", "-f", _VIGIL_CONTAINER], capture_output=True, text=True)
    repo_url = _gitea_remote_url({**gitea, "GITEA_URL": _vigil_gitea_url(gitea=gitea)})
    args = [
        "docker", "run", "-d", "--rm",
        "--name", _VIGIL_CONTAINER,
        "--network", _VIGIL_NETWORK,
        "-v", f"{(staging / '.openagents').resolve()}:/config:ro",
        "-v", f"{(ROOT / 'deploy' / 'vigil' / 'entrypoint.sh').resolve()}:/entrypoint.sh:ro",
        "-e", f"GITEA_TOKEN={gitea['TOKEN']}",
        "-e", f"GITEA_USER={gitea['OWNER']}",
        "-e", f"VIGIL_REPO_URL={repo_url}",
        "-e", f"VIGIL_PARALLEL={max(1, parallel)}",
        "-e", f"HTTPS_PROXY={_VIGIL_PROXY_URL}",
        "-e", f"HTTP_PROXY={_VIGIL_PROXY_URL}",
        "-e", f"https_proxy={_VIGIL_PROXY_URL}",
        "-e", f"http_proxy={_VIGIL_PROXY_URL}",
        "-e", "NO_PROXY=gitea,localhost,127.0.0.1",
        "-e", "no_proxy=gitea,localhost,127.0.0.1",
        # Container is a jail (proven by empirical fixes): claude by default acceptEdits only permits file edits; under headless, git commit/push
        # are rejected → deliver hangs on needs-human. Inside container use bypassPermissions (isolation managed by container; see spec-0033
        # §Guide); host-side env of same name can override. Note: claude refuses bypass under root—the image runs vigil as non-root user.
        "-e",
        (
            "OPENAGENTS_PERMISSION_MODE="
            f"{os.environ.get('OPENAGENTS_PERMISSION_MODE', '').strip() or 'bypassPermissions'}"
        ),
    ]  # fmt: skip
    if run_id:
        args += [
            "--label",
            f"io.ahe-beta.run_id={run_id}",
            "-e",
            f"AHE_BETA_RUN_ID={run_id}",
        ]
    if ours:
        args += ["--label", f"io.openagents.experiment_id={ours}"]
    manifest_sha = os.environ.get("AHE_BETA_CONFIG_HASH", "").strip()
    if manifest_sha:
        args += ["--label", f"io.openagents.manifest_sha={manifest_sha}"]
    delivery = _vigil_delivery_mount()
    if delivery is not None:
        # Root only prepares the host evidence mount. The entrypoint then drops to vigil
        # before cloning or starting OpenAgents/Claude, including bypassPermissions mode.
        args += [
            "--user",
            "root",
            "-v",
            f"{delivery}:/role_runs",
            "-e",
            "ROLE_RUNS_DIR=/role_runs",
            "-e",
            f"VIGIL_EXEC_UID={os.getuid() or 1000}",
            "-e",
            f"VIGIL_EXEC_GID={os.getgid() or 1000}",
        ]
    for key in (*_CLAUDE_CRED_ENVS, *_CLAUDE_CONFIG_ENVS):
        value = os.environ.get(key, "").strip()
        if value:
            args += ["-e", f"{key}={value}"]
    for key, value in _subagent_model_lock_env().items():
        args += ["-e", f"{key}={value}"]
    for key, value in _openagents_identity_env().items():
        args += ["-e", f"{key}={value}"]
    for suffix in _HARNESS_LLM_SUFFIXES:
        value = os.environ.get(f"HARNESS_LLM_{suffix}", "").strip()
        if value:
            args += ["-e", f"LLM_{suffix}={value}"]
    image = _VIGIL_IMAGE
    if observation_runtime is not None:
        image = observation_runtime["runtime"]["image_id"]
        args += [
            "-e",
            "OPENAGENTS_NO_SELF_UPDATE=1",
            "-e",
            "AHE_BETA_OBSERVATION_DOWNLOAD_POLICY="
            + observation_runtime["profile"]["download_policy"],
            # The immutable reader image may contain the original entrypoint.
            "-e",
            "AUTO_DESIGNER_OBSERVATION_DOWNLOAD_POLICY="
            + observation_runtime["profile"]["download_policy"],
        ]
    args += [image, "bash", "/entrypoint.sh"]
    started = subprocess.run(args, capture_output=True, text=True)
    if started.returncode != 0:
        raise SystemExit(f"Failed to start vigil container: {started.stderr.strip()[:300]}")
    return _attach_container_logs(log_path=log_path, keep_alive=keep_alive)


def _vigil_delivery_mount() -> str | None:
    """Host path of this run's delivery/ directory, or None when ROLE_RUNS_DIR is unset."""
    root = current_role_runs_dir()
    if root is None:
        return None
    delivery = root / "delivery"
    delivery.mkdir(parents=True, exist_ok=True)
    return str(delivery.resolve())


def _make_user_run_session_fn(**kwargs):
    """Both controllers dispatch the frozen task's interaction mode through one factory."""
    from ahe_beta.loop.sim_user import make_mixed_run_session_fn

    return make_mixed_run_session_fn(**kwargs)


def _alarm_threshold(env_key: str) -> int:
    raw = os.environ.get(env_key, "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else 20


def _check_backpressure(*, tracker, round_no: int) -> None:
    """Warn on the shared proposal/ready queue depths without blocking a completed round."""
    from ahe_beta.demand.issue_schema import PROPOSAL, READY, plane

    try:
        open_issues = tracker.list_open_issues()
    except Exception:  # noqa: BLE001 - observation failure must not block rounds
        return
    proposal_alarm = _alarm_threshold("PROPOSAL_DEPTH_ALARM")
    ready_alarm = _alarm_threshold("READY_DEPTH_ALARM")
    p_depth = sum(1 for issue in open_issues if plane(issue.labels) == PROPOSAL)
    r_depth = sum(1 for issue in open_issues if plane(issue.labels) == READY)
    if p_depth > proposal_alarm:
        print(
            f"[backpressure warning] End of round {round_no}: proposal depth {p_depth} > {proposal_alarm}: "
            "Admission may be too strict or generation excessive; manual intervention required (adjust hold criteria / reduce generators)."
        )
    if r_depth > ready_alarm:
        print(
            f"[backpressure warning] End of round {round_no}: ready depth {r_depth} > {ready_alarm}: "
            "Developers cannot keep up (a non-decreasing backlog signals degradation); manual intervention required (add developers / tighten admission)."
        )


def _on_round_end(k: int, sha: str, *, tracker, round_shas: list[str]) -> None:
    from ahe_beta.invocation import append_round
    from ahe_beta.loop.live import update_live_run

    round_shas.append(sha)
    user_sha = None
    recovery_root = os.environ.get("AHE_BETA_RECOVERY_ROOT", "").strip()
    if recovery_root:
        import json

        ledger = json.loads((Path(recovery_root) / "recovery.json").read_text())
        user_sha = ledger["rounds"][str(k)]["user_sha"]
    append_round(round_no=k, user_sha=user_sha, sealed_sha=sha)
    update_live_run(
        data_dir=DATA,
        running=True,
        round_no=k,
        total_rounds=TOTAL_ROUNDS,
        round_shas=round_shas,
    )
    _check_backpressure(tracker=tracker, round_no=k)


def _stop_managed_proc(*, proc: subprocess.Popen) -> None:
    """Stop managed process (container=log follower; subprocess=vigil itself). Kill on timeout."""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _stop_vigil_model_processes(*, vigil_pid: int, proc_root: Path) -> None:
    """Stop CLI agents owned by this run, including ones orphaned by an earlier Vigil.

    Claude Code starts its own process group, so terminating Vigil alone does not
    terminate an in-flight model call.  Scope orphan discovery to this run ID and
    direct descendants to this Vigil; never signal the controller's process group.
    """
    run_id = os.environ.get("AHE_BETA_RUN_ID", "").strip()
    processes: dict[int, tuple[int, int, str, bool]] = {}
    for entry in proc_root.iterdir() if proc_root.is_dir() else ():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text().split()
            command = (
                (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            )
            same_run = bool(run_id) and (
                f"AHE_BETA_RUN_ID={run_id}".encode()
                in (entry / "environ").read_bytes().split(b"\0")
            )
            processes[int(entry.name)] = (int(stat[3]), int(stat[4]), command, same_run)
        except (OSError, ValueError):
            continue
    roots = {
        pid
        for pid, (parent, _group, command, same_run) in processes.items()
        if command.startswith("claude -p ") and (parent == vigil_pid or same_run)
    }
    descendants = set(roots)
    while True:
        expanded = descendants | {
            pid
            for pid, (parent, _group, _command, _same_run) in processes.items()
            if parent in descendants
        }
        if expanded == descendants:
            break
        descendants = expanded
    own_group = os.getpgrp()
    for group in {processes[pid][1] for pid in descendants}:
        if group > 1 and group != own_group:
            try:
                os.killpg(group, signal.SIGKILL)
            except OSError:
                pass
    for pid in descendants:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def stop_vigil(handle: VigilHandle) -> None:
    """Stop the delivery-plane process according to keep_alive.

    Spec-0040/T1: when keep_alive, container only tears down log follower, no docker rm; subprocess does not kill vigil process itself.
    """
    try:
        if handle.keep_alive:
            if handle.mode == "container":
                _stop_managed_proc(proc=handle.proc)
            return
        if handle.mode == "container":
            subprocess.run(["docker", "rm", "-f", _VIGIL_CONTAINER], capture_output=True, text=True)
        _stop_managed_proc(proc=handle.proc)
        if handle.mode == "subprocess":
            pid = getattr(handle.proc, "pid", None)
            if isinstance(pid, int) and pid > 0:
                _stop_vigil_model_processes(vigil_pid=pid, proc_root=Path("/proc"))
    finally:
        try:
            handle.log_handle.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001  log close failure does not affect cleanup
            pass


# Spec-0079/T4: build an exact index from raw blobs, preserving ignored tracked paths.
def _seed_inherited_tree(*, input_path: Path) -> None:
    import hashlib
    import json

    from ahe_beta.guards.harness_boundary import install_pre_commit

    inherited = json.loads(input_path.read_text())
    harness = inherited["export"]["harness"]
    entries = []
    for relative, record in sorted(harness["files"].items()):
        path = HARNESS_REPO / relative
        if not path.is_file() or path.is_symlink():
            raise SystemExit("Inherited Harness is missing a regular tracked file")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise SystemExit("Inherited Harness file content differs from export")
        oid = (
            subprocess.check_output(
                ["git", "-C", str(HARNESS_REPO), "hash-object", "-w", "--stdin"], input=data
            )
            .decode()
            .strip()
        )
        if oid != record["blob_oid"] or record["mode"] not in {"100644", "100755"}:
            raise SystemExit("Inherited Harness blob identity or mode differs")
        path.chmod(0o755 if record["mode"] == "100755" else 0o644)
        entries.append(f"{record['mode']} {oid}\t{relative}\0".encode())
    subprocess.run(
        ["git", "-C", str(HARNESS_REPO), "update-index", "-z", "--index-info"],
        input=b"".join(entries),
        check=True,
        capture_output=True,
    )
    actual_tree = subprocess.check_output(
        ["git", "-C", str(HARNESS_REPO), "write-tree"], text=True
    ).strip()
    if actual_tree != harness["tree_id"]:
        raise SystemExit("Inherited Harness seed tree differs from parent tree")
    # Bind the new root commit to its parent even when tree and Git timestamps repeat.
    _git(
        HARNESS_REPO,
        "commit",
        "-m",
        "seed: inherited Harness tree",
        "-m",
        f"Parent Harness commit: {harness['commit']}",
    )
    # Exclusions are runtime metadata; the tracked parent .gitignore is untouched.
    (HARNESS_REPO / ".git/info/exclude").write_text(
        "__pycache__/\n*.pyc\n.openagents/\n", encoding="utf-8"
    )
    install_pre_commit(HARNESS_REPO)
