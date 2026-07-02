#!/usr/bin/env bash
# 启动真实端到端闭环（backend/run.py）。
# persona / 种子卡库两个「给定输入」作为参数注入，可用环境变量覆盖：
#   PERSONA_LIBRARY=/path/to/persona.json SEED_CARDS=/path/to/seeds.json ./run.sh
# 也可透传任意 run.py 参数（追加在末尾，覆盖上面的默认注入）：
#   ./run.sh --persona-library <path> --seed-cards <path>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
PERSONA_LIBRARY="${PERSONA_LIBRARY:-$ROOT/backend/persona_library.json}"
SEED_CARDS="${SEED_CARDS:-$ROOT/backend/seeds.json}"

cd "$ROOT"
PYTHONPATH=backend "$PYTHON" backend/run.py \
  --persona-library "$PERSONA_LIBRARY" \
  --seed-cards "$SEED_CARDS" \
  "$@"
