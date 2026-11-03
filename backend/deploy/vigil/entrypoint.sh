#!/usr/bin/env bash
# Spec-0033/T1: vigil container entry point——clone harness repo (no host mount) → copy in declarative config → exec vigil.
# executed by run.py at docker run time as read-only mount with `bash /entrypoint.sh` (not baked into image, iterative without rebuild).
# required env (injected by run.py):
#   VIGIL_REPO_URL   credential-bearing internal clone URL (http://owner:token@gitea:3000/owner/repo.git)
#   VIGIL_PARALLEL   vigil --parallel concurrency K (default 1)
#   /config/openagents.yml read-only mount (forge=gitea + finalized stages, token in env only, not on disk)
set -euo pipefail

# Spec-0069/T3: delivery must retain the installed frozen toolchain.
export DISABLE_UPDATES=1 OPENAGENTS_NO_SELF_UPDATE=1

# Spec-0070/T4: preserve the reader verified before dispatch throughout this run.
if [[ "${AHE_BETA_OBSERVATION_DOWNLOAD_POLICY:-same-origin-v1}" == "gitea-com-r2-v1" ]]; then
  export OPENAGENTS_NO_SELF_UPDATE=1
fi

: "${VIGIL_REPO_URL:?Missing VIGIL_REPO_URL (internal clone URL)}"
: "${VIGIL_PARALLEL:=1}"
: "${VIGIL_EXEC_UID:=1000}"
: "${VIGIL_EXEC_GID:=1000}"
if [[ ! "$VIGIL_EXEC_UID" =~ ^[1-9][0-9]*$ || ! "$VIGIL_EXEC_GID" =~ ^[1-9][0-9]*$ ]]; then
  echo "VIGIL_EXEC_UID/GID must be positive, non-root integers" >&2
  exit 1
fi
test -f /config/openagents.yml || { echo "Missing /config/openagents.yml mount" >&2; exit 1; }

# Spec-0072/T3: the host creates the per-run delivery directory as root, while the
# delivery process intentionally runs as the unprivileged `vigil` user.  Enter as
# root only long enough to hand this one bind mount to vigil, then permanently drop
# privileges before cloning or running any agent code.
if [[ "$(id -u)" == "0" ]]; then
  if [[ -n "${ROLE_RUNS_DIR:-}" ]]; then
    mkdir -p "$ROLE_RUNS_DIR"
    # Retained artifacts can also have root-owned private files. Transfer this
    # mount without following symlinks into other container directories.
    chown -R --no-dereference "$VIGIL_EXEC_UID:$VIGIL_EXEC_GID" "$ROLE_RUNS_DIR"
    chmod 0700 "$ROLE_RUNS_DIR"
  fi
  export HOME=/home/vigil USER=vigil LOGNAME=vigil
  mkdir -p "$HOME" /work
  chown -R --no-dereference "$VIGIL_EXEC_UID:$VIGIL_EXEC_GID" "$HOME" /work
  exec setpriv --reuid="$VIGIL_EXEC_UID" --regid="$VIGIL_EXEC_GID" --clear-groups --inh-caps=-all bash "$0" "$@"
fi

if [[ "$(id -u)" != "$VIGIL_EXEC_UID" ]]; then
  echo "vigil is not running with the configured non-root UID; refusing to start" >&2
  exit 1
fi

if [[ -n "${ROLE_RUNS_DIR:-}" ]]; then
  audit_probe="$ROLE_RUNS_DIR/.openagents-write-probe-$$"
  if ! (umask 077 && : >"$audit_probe" && rm -f "$audit_probe"); then
    echo "ROLE_RUNS_DIR is not writable; refusing to start vigil without auditing: $ROLE_RUNS_DIR" >&2
    exit 1
  fi
fi

WORK=/work/harness

# container rebuilds on each run → clone and .openagents runtime state naturally reset (original rmtree reset semantics preserved).
git clone "$VIGIL_REPO_URL" "$WORK"
# The credentialed clone URL is bootstrap-only.  Keep the visible remote free of tokens and let
# later fetch/push ask a helper that reads the already-scoped container environment at execution.
VIGIL_GIT_SCHEME="${VIGIL_REPO_URL%%://*}"
VIGIL_GIT_REST="${VIGIL_REPO_URL#*@}"
git -C "$WORK" remote set-url origin "${VIGIL_GIT_SCHEME}://${VIGIL_GIT_REST}"
unset VIGIL_REPO_URL VIGIL_GIT_SCHEME VIGIL_GIT_REST
mkdir -p "$WORK/.openagents"
cp /config/openagents.yml "$WORK/.openagents/openagents.yml"

# git identity for delivery-layer agent (commit attribution for deliver/merge; global within container, independent of host config).
git config --global user.name "openagents"
git config --global user.email "openagents@ahe-beta.local"
git config --global --add safe.directory "$WORK"
git config --global credential.helper \
  '!f() { if [ "$1" = get ]; then printf "%s\n" "username=${GITEA_USER}" "password=${GITEA_TOKEN}"; fi; }; f'

cd "$WORK"
# Final OpenAgents boundary: a model requested by Agent(model=sonnet/haiku) must
# not escape the delivery session's model. FORCE alone inherits the parent on
# Claude Code >= 2.1.257; the explicit pin also covers older installed CLIs.
export CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1
if [[ -n "${ANTHROPIC_MODEL:-}" ]]; then
  export CLAUDE_CODE_SUBAGENT_MODEL="$ANTHROPIC_MODEL"
else
  unset CLAUDE_CODE_SUBAGENT_MODEL
fi
exec openagents vigil --parallel "$VIGIL_PARALLEL"
