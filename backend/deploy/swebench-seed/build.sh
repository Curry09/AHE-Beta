#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CONTEXT="${SWEBENCH_SEED_CONTEXT:?Set the prepared seed workspace context}"
IMAGE="${SWEBENCH_SEED_IMAGE:?Set the output storage seed image}"

test -d "$CONTEXT/workspace" || {
  echo "seed workspace 不存在：$CONTEXT/workspace" >&2
  exit 1
}
test -f "$CONTEXT/build-state.json" || {
  echo "seed 状态文件不存在：$CONTEXT/build-state.json" >&2
  exit 1
}

docker build -f "$ROOT/backend/deploy/swebench-seed/Dockerfile" -t "$IMAGE" "$CONTEXT"
echo "✓ seed 镜像构建完成：$IMAGE"
