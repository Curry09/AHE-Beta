#!/usr/bin/env bash
# Spec-0033/T1：构建 vigil 容器镜像。OpenAgents 和 NexAU 的版本 pin 均由传入
# checkout 决定；Docker 命名 build context 使两个仓无需复制到共同父目录。
# 用法：./build.sh <OpenAgents 仓路径> <NexAU 仓路径>
set -euo pipefail

OPENAGENTS_PATH="${1:?用法: build.sh <OpenAgents 仓路径> <NexAU 仓路径>}"
NEXAU_PATH="${2:?用法: build.sh <OpenAgents 仓路径> <NexAU 仓路径>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIP_INDEX_URL="${VIGIL_PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
CLAUDE_CODE_VERSION="${VIGIL_CLAUDE_CODE_VERSION:-2.1.261}"

test -f "$OPENAGENTS_PATH/pyproject.toml" || {
  echo "不是 OpenAgents 仓（缺 pyproject.toml）：$OPENAGENTS_PATH" >&2
  exit 1
}
grep -q 'name = "openagents"' "$OPENAGENTS_PATH/pyproject.toml" || {
  echo "pyproject 不是 openagents 包：$OPENAGENTS_PATH" >&2
  exit 1
}

test -f "$NEXAU_PATH/pyproject.toml" || {
  echo "不是 NexAU 仓（缺 pyproject.toml）：$NEXAU_PATH" >&2
  exit 1
}
grep -q 'name = "nexau"' "$NEXAU_PATH/pyproject.toml" || {
  echo "pyproject 不是 nexau 包：$NEXAU_PATH" >&2
  exit 1
}

docker build \
  --build-context "nexau=$NEXAU_PATH" \
  --build-arg "PIP_INDEX_URL=$PIP_INDEX_URL" \
  --build-arg "CLAUDE_CODE_VERSION=$CLAUDE_CODE_VERSION" \
  --build-arg "HTTP_PROXY=${http_proxy:-${HTTP_PROXY:-}}" \
  --build-arg "HTTPS_PROXY=${https_proxy:-${HTTPS_PROXY:-}}" \
  --build-arg "NO_PROXY=${no_proxy:-${NO_PROXY:-}}" \
  -f "$HERE/Dockerfile" \
  -t auto-designer-vigil:latest \
  "$OPENAGENTS_PATH"
echo "✓ 镜像 auto-designer-vigil:latest 构建完成（OpenAgents pin = $(git -C "$OPENAGENTS_PATH" rev-parse --short HEAD 2>/dev/null || echo '非 git checkout')，NexAU pin = $(git -C "$NEXAU_PATH" rev-parse --short HEAD 2>/dev/null || echo '非 git checkout')）"
