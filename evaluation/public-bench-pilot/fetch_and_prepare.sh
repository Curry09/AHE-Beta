#!/usr/bin/env bash
set -euo pipefail

PILOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PILOT_SOURCE_CACHE="${PILOT_SOURCE_CACHE:-/tmp/public-bench-pilot-sources}"
PILOT_UV_CACHE="${PILOT_UV_CACHE:-/tmp/public-bench-pilot-uv-cache}"
PILOT_UV_TOOLS="${PILOT_UV_TOOLS:-/tmp/public-bench-pilot-uv-tools}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

mkdir -p "$PILOT_SOURCE_CACHE/terminal-tasks"

curl -L --fail --retry 3 --continue-at - \
  -o "$PILOT_SOURCE_CACHE/tua-bench-3497fd32.tar.gz" \
  https://github.com/facebookresearch/TUA-Bench/archive/3497fd320abcafaf4797424192c891a593fd7964.tar.gz

curl -L --fail --retry 3 --continue-at - \
  -o "$PILOT_SOURCE_CACHE/tau3-bench-fc0055dc.tar.gz" \
  https://github.com/sierra-research/tau2-bench/archive/fc0055dc4e0a316c3f83133267fbd6faaa770992.tar.gz

download_terminal_task() {
  local task_ref="$1"
  local task_name="${task_ref%%@*}"
  task_name="${task_name##*/}"
  if [[ -d "$PILOT_SOURCE_CACHE/terminal-tasks/$task_name" ]]; then
    return
  fi
  UV_CACHE_DIR="$PILOT_UV_CACHE" UV_TOOL_DIR="$PILOT_UV_TOOLS" \
    uvx --from 'harbor==0.23.0' --with 'httpx[socks]' harbor task download \
    "$task_ref" --output-dir "$PILOT_SOURCE_CACHE/terminal-tasks" --export
}

download_terminal_task 'terminal-bench/html-js-filter@sha256:832a5b309edca4f1a7c728da5f1ca530c2712f20a0b7f1db6d1bb6e3171a8866'
download_terminal_task 'terminal-bench/music-harmony@sha256:f5ba5ef9140c164e1c3654425caea7dc0f74423c9632f5e0c9a6dc9001d38f00'
download_terminal_task 'terminal-bench/production-planning@sha256:3207b248738c9e6d497559b90a2a85d43dddde1caea12a5e17e4871e985fe7de'
download_terminal_task 'terminal-bench/payments-pipeline-fix@sha256:05cbd702e9efc41264e495e6afda5faa34f7672fa4f6faaeaf66106f03af8c6c'
download_terminal_task 'terminal-bench/lake-temp-glm@sha256:8ef0ba42c13ce6ed6454e40389907d8781a681605d07a1fdc48fb5913c46388d'

"$PYTHON_BIN" "$PILOT_DIR/prepare_evalset.py" \
  --swe-parquet "${SWE_BENCH_PARQUET:?set SWE_BENCH_PARQUET to the Verified parquet path}" \
  --terminal-tasks "$PILOT_SOURCE_CACHE/terminal-tasks" \
  --tua-archive "$PILOT_SOURCE_CACHE/tua-bench-3497fd32.tar.gz" \
  --tau3-archive "$PILOT_SOURCE_CACHE/tau3-bench-fc0055dc.tar.gz"

"$PYTHON_BIN" "$PILOT_DIR/validate_evalset.py"
