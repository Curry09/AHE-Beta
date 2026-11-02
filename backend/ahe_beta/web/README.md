# 观测看板只读 API

复用 Metrics/SessionStore/IssueTracker，只读序列化为 JSON。不写状态、不引入 benchmark。

## 端点
- `GET /api/health` → `{status: ok}`
- `GET /api/overview` → `{open_issue_count, session_count, feeling_trend, issue_curve}`
- `GET /api/sessions` → 会话摘要列表
- `GET /api/sessions/{id}` → 单局全量（404 若不存在）

## 起服务
```bash
PYTHONPATH=backend .venv/bin/uvicorn ahe_beta.web.api:app --port 8000
```
有 Gitea 时设 `GITEA_URL/OWNER/REPO/TOKEN` 环境变量，`open_issue_count` 才有值，否则为 `null`。
构建过前端（`frontend/dist` 存在）则根路径 `/` 直接托管 SPA。
