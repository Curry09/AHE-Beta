#!/usr/bin/env bash
set -euo pipefail
mkdir -p /logs/verifier
if test "$(cat /app/answer.txt)" = "OK"; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
  exit 1
fi
