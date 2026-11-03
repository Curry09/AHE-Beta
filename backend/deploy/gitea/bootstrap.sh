#!/usr/bin/env bash
# Gitea one-shot initialization (spec-0002/T1): wait for readiness → create admin → generate token → create working repo → ensure labels.
# Each step is idempotent and safe to re-run. Produces deploy/gitea/.env (GITEA_URL/OWNER/REPO/TOKEN), which serves as the sole configuration entry point for T2/T3.
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"
if [[ -f "$ENV_FILE" ]]; then chmod 600 "$ENV_FILE"; fi
COMPOSE="docker compose -f $HERE/docker-compose.yml"

GITEA_URL="${GITEA_URL:-http://localhost:3000}"
OWNER="${GITEA_ADMIN_USER:-designer}"
ADMIN_PASS="${GITEA_ADMIN_PASS:?Set GITEA_ADMIN_PASS before bootstrapping Gitea}"
ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-designer@example.com}"
REPO="${GITEA_WORK_REPO:-ahe-beta-work}"
TOKEN_NAME="${GITEA_TOKEN_NAME:-ahe-beta}"
LABELS=(bug feature)

GITEA_URL="${GITEA_URL%/}"   # Strip the trailing slash: the contract requires GITEA_URL to have no trailing slash and no /api/v1 suffix

# ① Readiness probe: poll /api/v1/version until it returns 200 or times out.
echo "[bootstrap] Waiting for Gitea to become ready ($GITEA_URL) ..."
for i in $(seq 1 60); do
  if curl -fsS "$GITEA_URL/api/v1/version" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
if [[ "${ready:-0}" != "1" ]]; then
  echo "[bootstrap] Readiness timed out: $GITEA_URL is unreachable; check '$COMPOSE ps'" >&2
  exit 1
fi

# ② Create the admin (if it already exists, treat as success; idempotent).
echo "[bootstrap] Ensuring admin user $OWNER exists ..."
$COMPOSE exec -T -u git gitea gitea admin user create \
  --admin --username "$OWNER" --password "$ADMIN_PASS" --email "$ADMIN_EMAIL" \
  --must-change-password=false 2>/dev/null || echo "[bootstrap] Admin already exists; skipping creation"

# ③ Generate the token: it is visible only at generation time. If a TOKEN already exists in .env, reuse it and do not generate a new one.
if [[ -f "$ENV_FILE" ]] && grep -q '^TOKEN=' "$ENV_FILE"; then
  TOKEN="$(grep '^TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  echo "[bootstrap] Reusing the existing TOKEN from .env"
else
  echo "[bootstrap] Generating access token ($TOKEN_NAME) ..."
  TOKEN="$($COMPOSE exec -T -u git gitea gitea admin user generate-access-token \
    --username "$OWNER" --token-name "$TOKEN_NAME" \
    --scopes write:user,write:issue,write:repository --raw | tr -d '[:space:]')"
  if [[ -z "$TOKEN" ]]; then
    echo "[bootstrap] Token generation failed; stopping without writing an empty token" >&2
    exit 1
  fi
fi
AUTH=(-H "Authorization: token $TOKEN")
API="$GITEA_URL/api/v1"

# ④ Create the working repo (auto_init=true); existing (409) counts as success.
echo "[bootstrap] Ensuring working repository $OWNER/$REPO exists ..."
code="$(curl -sS -o /dev/null -w '%{http_code}' "${AUTH[@]}" -X POST "$API/user/repos" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"$REPO\",\"auto_init\":true,\"private\":true}")"
if [[ "$code" != "201" && "$code" != "409" ]]; then
  echo "[bootstrap] Working repository creation failed: HTTP $code" >&2; exit 1
fi

# ⑤ Ensure labels {bug, feature}: create them if missing.
existing="$(curl -sS "${AUTH[@]}" "$API/repos/$OWNER/$REPO/labels")"
for label in "${LABELS[@]}"; do
  if echo "$existing" | grep -q "\"name\":\"$label\""; then
    echo "[bootstrap] Label $label already exists"
  else
    curl -sS -o /dev/null "${AUTH[@]}" -X POST "$API/repos/$OWNER/$REPO/labels" \
      -H 'Content-Type: application/json' \
      -d "{\"name\":\"$label\",\"color\":\"#ededed\"}"
    echo "[bootstrap] Creating label $label"
  fi
done

# ⑥ Actions runner registration token (Spec-0032/T6): reuse if one already exists; a generation failure does not block (degrade to a warning when Actions is not enabled).
if [[ -f "$ENV_FILE" ]] && grep -q '^RUNNER_TOKEN=' "$ENV_FILE"; then
  RUNNER_TOKEN="$(grep '^RUNNER_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  echo "[bootstrap] Reusing the existing RUNNER_TOKEN from .env"
else
  echo "[bootstrap] Generating an Actions runner registration token ..."
  RUNNER_TOKEN="$($COMPOSE exec -T -u git gitea gitea actions generate-runner-token 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ -z "$RUNNER_TOKEN" ]]; then
    echo "[bootstrap] Runner token generation failed (Actions is disabled or the version is too old); CI smoke checks are unavailable, so keep vigil ci=skip" >&2
  fi
fi

# Produce the connection-info contract .env (GITEA_URL with no trailing slash and no /api/v1 suffix). RUNNER_TOKEN doubles as compose interpolation
# (the act-runner service reads it to register; the .env in the same directory is loaded automatically by docker compose).
cat > "$ENV_FILE" <<EOF
GITEA_URL=$GITEA_URL
OWNER=$OWNER
REPO=$REPO
TOKEN=$TOKEN
RUNNER_TOKEN=${RUNNER_TOKEN:-}
EOF
echo "[bootstrap] Complete; connection information written to $ENV_FILE"

# ⑦ Start the runner (idempotent; the first registration uses RUNNER_TOKEN, afterwards it uses the credentials inside the runner_data volume).
if [[ -n "${RUNNER_TOKEN:-}" ]]; then
  echo "[bootstrap] Starting the Actions runner ..."
  $COMPOSE up -d act-runner
  echo "[bootstrap] Once the runner is ready, enable the delivery CI gate with VIGIL_CI_STAGE=agent (see the packaged ordinary controller; start new experiments through experiment.py)"
fi
