#!/usr/bin/env bash
# Spec-0033/T1：vigil 容器入口——clone harness 仓（零宿主挂载）→ 拷入声明式配置 → exec vigil。
# 由 run.py 在 docker run 时只读挂载并以 `bash /entrypoint.sh` 执行（不烘进镜像，可迭代免重建）。
# 所需 env（run.py 注入）：
#   VIGIL_REPO_URL   带凭证的内网 clone 地址（http://owner:token@gitea:3000/owner/repo.git）
#   VIGIL_PARALLEL   vigil --parallel 并发 K（缺省 1）
#   /config/openagents.yml 只读挂载（forge=gitea + stages 定稿，token 只在 env 不在盘）
set -euo pipefail

: "${VIGIL_REPO_URL:?缺 VIGIL_REPO_URL（内网 clone 地址）}"
: "${VIGIL_PARALLEL:=1}"
test -f /config/openagents.yml || { echo "缺 /config/openagents.yml 挂载" >&2; exit 1; }

WORK=/work/harness

# 容器每 run 重建 → clone 与 .openagents 运行态天然归零（原 rmtree 重置语义保留）。
git clone "$VIGIL_REPO_URL" "$WORK"
mkdir -p "$WORK/.openagents"
cp /config/openagents.yml "$WORK/.openagents/openagents.yml"

# 交付面 agent 的 git 身份（deliver/merge 的 commit 归属；容器内全局，不依赖宿主配置）。
git config --global user.name "openagents"
git config --global user.email "openagents@auto-designer.local"
git config --global --add safe.directory "$WORK"

cd "$WORK"
exec openagents vigil --parallel "$VIGIL_PARALLEL"
