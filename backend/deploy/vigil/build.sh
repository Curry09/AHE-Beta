#!/usr/bin/env bash
# Spec-0033/T1：构建 vigil 容器镜像。build context = 本地 OpenAgents checkout（版本 pin 由
# checkout 决定——checkout 到含 forge/Gitea driver 的分支/commit 再构建）。
# 用法：./build.sh <OpenAgents 仓路径>
set -euo pipefail

OPENAGENTS_PATH="${1:?用法: build.sh <OpenAgents 仓路径>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

test -f "$OPENAGENTS_PATH/pyproject.toml" || {
  echo "不是 OpenAgents 仓（缺 pyproject.toml）：$OPENAGENTS_PATH" >&2
  exit 1
}
grep -q 'name = "openagents"' "$OPENAGENTS_PATH/pyproject.toml" || {
  echo "pyproject 不是 openagents 包：$OPENAGENTS_PATH" >&2
  exit 1
}

docker build -f "$HERE/Dockerfile" -t auto-designer-vigil:latest "$OPENAGENTS_PATH"
echo "✓ 镜像 auto-designer-vigil:latest 构建完成（pin = $(git -C "$OPENAGENTS_PATH" rev-parse --short HEAD 2>/dev/null || echo '非 git checkout')）"
