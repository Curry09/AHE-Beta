#!/bin/sh
set -eu
test -s /eval-out/session.json
test -f /eval-out/model.patch
mkdir -p /logs/verifier
printf '1\n' > /logs/verifier/reward.txt
