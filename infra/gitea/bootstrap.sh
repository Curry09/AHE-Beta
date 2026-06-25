#!/usr/bin/env bash
# Gitea 一键初始化（spec-0002/T1）：等待就绪 → 建 admin → 生成 token → 建工作仓 → ensure 标签。
# 每步幂等，可重跑。产出 infra/gitea/.env（GITEA_URL/OWNER/REPO/TOKEN），作为 T2/T3 唯一配置入口。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/.env"
COMPOSE="docker compose -f $HERE/docker-compose.yml"

GITEA_URL="${GITEA_URL:-http://localhost:3000}"
OWNER="${GITEA_ADMIN_USER:-designer}"
ADMIN_PASS="${GITEA_ADMIN_PASS:-designer-pass-123}"
ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-designer@example.com}"
REPO="${GITEA_WORK_REPO:-auto-designer-work}"
TOKEN_NAME="${GITEA_TOKEN_NAME:-auto-designer}"
LABELS=(bug feature)

GITEA_URL="${GITEA_URL%/}"   # 去尾斜杠：契约要求 GITEA_URL 无尾斜杠、无 /api/v1 后缀

# ① 就绪探测：轮询 /api/v1/version 直至 200 或超时。
echo "[bootstrap] 等待 Gitea 就绪 ($GITEA_URL) ..."
for i in $(seq 1 60); do
  if curl -fsS "$GITEA_URL/api/v1/version" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
if [[ "${ready:-0}" != "1" ]]; then
  echo "[bootstrap] 就绪超时：$GITEA_URL 不可达，请检查 '$COMPOSE ps'" >&2
  exit 1
fi

# ② 建 admin（已存在则视为成功，幂等）。
echo "[bootstrap] 确保 admin 用户 $OWNER ..."
$COMPOSE exec -T -u git gitea gitea admin user create \
  --admin --username "$OWNER" --password "$ADMIN_PASS" --email "$ADMIN_EMAIL" \
  --must-change-password=false 2>/dev/null || echo "[bootstrap] admin 已存在，跳过"

# ③ 生成 token：仅生成时可见。已有 .env 的 TOKEN 则复用，不重复生成。
if [[ -f "$ENV_FILE" ]] && grep -q '^TOKEN=' "$ENV_FILE"; then
  TOKEN="$(grep '^TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  echo "[bootstrap] 复用 .env 中已有 TOKEN"
else
  echo "[bootstrap] 生成 access token ($TOKEN_NAME) ..."
  TOKEN="$($COMPOSE exec -T -u git gitea gitea admin user generate-access-token \
    --username "$OWNER" --token-name "$TOKEN_NAME" \
    --scopes write:issue,write:repository --raw | tr -d '[:space:]')"
  if [[ -z "$TOKEN" ]]; then
    echo "[bootstrap] token 生成失败，终止（不写入空 token）" >&2
    exit 1
  fi
fi
AUTH=(-H "Authorization: token $TOKEN")
API="$GITEA_URL/api/v1"

# ④ 建工作仓（auto_init=true）；已存在(409)视为成功。
echo "[bootstrap] 确保工作仓 $OWNER/$REPO ..."
code="$(curl -sS -o /dev/null -w '%{http_code}' "${AUTH[@]}" -X POST "$API/user/repos" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"$REPO\",\"auto_init\":true,\"private\":true}")"
if [[ "$code" != "201" && "$code" != "409" ]]; then
  echo "[bootstrap] 建工作仓失败：HTTP $code" >&2; exit 1
fi

# ⑤ ensure 标签 {bug, feature}：缺失则建。
existing="$(curl -sS "${AUTH[@]}" "$API/repos/$OWNER/$REPO/labels")"
for label in "${LABELS[@]}"; do
  if echo "$existing" | grep -q "\"name\":\"$label\""; then
    echo "[bootstrap] 标签 $label 已存在"
  else
    curl -sS -o /dev/null "${AUTH[@]}" -X POST "$API/repos/$OWNER/$REPO/labels" \
      -H 'Content-Type: application/json' \
      -d "{\"name\":\"$label\",\"color\":\"#ededed\"}"
    echo "[bootstrap] 建标签 $label"
  fi
done

# 产出连接信息契约 .env（GITEA_URL 无尾斜杠、无 /api/v1 后缀）。
cat > "$ENV_FILE" <<EOF
GITEA_URL=$GITEA_URL
OWNER=$OWNER
REPO=$REPO
TOKEN=$TOKEN
EOF
echo "[bootstrap] 完成，连接信息写入 $ENV_FILE"
