#!/usr/bin/env bash
# Spec-0033/T1：vigil 容器入口——clone harness 仓（零宿主挂载）→ 拷入声明式配置 → exec vigil。
# 由 run.py 在 docker run 时只读挂载并以 `bash /entrypoint.sh` 执行（不烘进镜像，可迭代免重建）。
# 所需 env（run.py 注入）：
#   VIGIL_REPO_URL   带凭证的内网 clone 地址（http://owner:token@gitea:3000/owner/repo.git）
#   VIGIL_PARALLEL   vigil --parallel 并发 K（缺省 1）
#   /config/openagents.yml 只读挂载（forge=gitea + stages 定稿，token 只在 env 不在盘）
set -euo pipefail

# Spec-0069/T3: delivery must retain the installed frozen toolchain.
export DISABLE_UPDATES=1 OPENAGENTS_NO_SELF_UPDATE=1

# Spec-0070/T4: preserve the reader verified before dispatch throughout this run.
if [[ "${AUTO_DESIGNER_OBSERVATION_DOWNLOAD_POLICY:-same-origin-v1}" == "gitea-com-r2-v1" ]]; then
  export OPENAGENTS_NO_SELF_UPDATE=1
fi

: "${VIGIL_REPO_URL:?缺 VIGIL_REPO_URL（内网 clone 地址）}"
: "${VIGIL_PARALLEL:=1}"
: "${VIGIL_EXEC_UID:=1000}"
: "${VIGIL_EXEC_GID:=1000}"
if [[ ! "$VIGIL_EXEC_UID" =~ ^[1-9][0-9]*$ || ! "$VIGIL_EXEC_GID" =~ ^[1-9][0-9]*$ ]]; then
  echo "VIGIL_EXEC_UID/GID 必须是非 root 的正整数" >&2
  exit 1
fi
test -f /config/openagents.yml || { echo "缺 /config/openagents.yml 挂载" >&2; exit 1; }

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
  echo "vigil 未以配置的非 root UID 执行，拒绝启动" >&2
  exit 1
fi

if [[ -n "${ROLE_RUNS_DIR:-}" ]]; then
  audit_probe="$ROLE_RUNS_DIR/.openagents-write-probe-$$"
  if ! (umask 077 && : >"$audit_probe" && rm -f "$audit_probe"); then
    echo "ROLE_RUNS_DIR 不可写，拒绝启动无审计 vigil：$ROLE_RUNS_DIR" >&2
    exit 1
  fi
fi

WORK=/work/harness

# 容器每 run 重建 → clone 与 .openagents 运行态天然归零（原 rmtree 重置语义保留）。
git clone "$VIGIL_REPO_URL" "$WORK"
# The credentialed clone URL is bootstrap-only.  Keep the visible remote free of tokens and let
# later fetch/push ask a helper that reads the already-scoped container environment at execution.
VIGIL_GIT_SCHEME="${VIGIL_REPO_URL%%://*}"
VIGIL_GIT_REST="${VIGIL_REPO_URL#*@}"
git -C "$WORK" remote set-url origin "${VIGIL_GIT_SCHEME}://${VIGIL_GIT_REST}"
unset VIGIL_REPO_URL VIGIL_GIT_SCHEME VIGIL_GIT_REST
mkdir -p "$WORK/.openagents"
cp /config/openagents.yml "$WORK/.openagents/openagents.yml"

# 交付面 agent 的 git 身份（deliver/merge 的 commit 归属；容器内全局，不依赖宿主配置）。
git config --global user.name "openagents"
git config --global user.email "openagents@auto-designer.local"
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
