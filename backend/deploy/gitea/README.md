# 本地 Gitea（spec-0002/T1）

旧单实例联调入口；并行实验优先用 `backend/deploy/experiment/`。端口仅绑定 loopback，bootstrap 要求显式管理员密码，凭证文件使用私有权限。

issue 与 harness 仓的家。单服务 + sqlite，最小运维面；非生产化（无 TLS/外部 DB/HA）。

## 启动

```bash
docker compose -f backend/deploy/gitea/docker-compose.yml up -d
```

Gitea 在固定端口 `http://localhost:3000`（`GET /api/v1/version` 返回 200 即就绪）。

## 一键初始化 / 拿 token

```bash
read -rs -p "Gitea admin password: " GITEA_ADMIN_PASS
export GITEA_ADMIN_PASS
bash backend/deploy/gitea/bootstrap.sh
```

幂等，可重跑。完成后产出 `backend/deploy/gitea/.env`（已 gitignore，不入库）：

```
GITEA_URL=http://localhost:3000   # 无尾斜杠、无 /api/v1 后缀
OWNER=designer
REPO=auto-designer-work
TOKEN=<write:issue,write:repository scope 的 access token>
```

该文件是 T1 与 `GiteaTracker`(T2) / `bootstrap_harness.py`(T3) 之间的唯一配置契约面。

可用环境变量覆盖默认值：`GITEA_ADMIN_USER` / `GITEA_ADMIN_PASS` / `GITEA_WORK_REPO` / `GITEA_TOKEN_NAME`。

## 验证（建一条 issue）

```bash
source backend/deploy/gitea/.env
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: token $TOKEN" \
  -X POST "$GITEA_URL/api/v1/repos/$OWNER/$REPO/issues" \
  -H 'Content-Type: application/json' -d '{"title":"smoke","body":"hello"}'
# 期望 201
```

## 重置数据卷（清空所有 issue / 仓 / 用户）

```bash
docker compose -f backend/deploy/gitea/docker-compose.yml down -v
rm -f backend/deploy/gitea/.env
```
