#!/usr/bin/env bash
# Run all local checks for this harness.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

./scripts/smoke.sh
