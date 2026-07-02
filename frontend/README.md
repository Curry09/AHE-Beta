# frontend — 观测看板（React + Vite + TS）

只读看板：消费 `backend/auto_designer/web/api.py` 的 `/api/*`。「公司办公室组织看板」画风——
顶部公司抬头栏 + 左侧部门（用户部/开发部的员工工位卡片）+ 中央公告墙（Issue 公告 / main 分支更新）。
点击员工卡看详情抽屉（实时 status/对话/会话体感），点击公告条目跳 Gitea。

## 开发
```bash
cd frontend && npm install
# 另一终端起后端：PYTHONPATH=backend .venv/bin/uvicorn auto_designer.web.api:app --port 8000
npm run dev   # http://localhost:5173 ，/api 代理到 8000
```

## 构建
```bash
npm run build   # tsc --noEmit + vite build → dist/，由 FastAPI 托管
```

## 结构
- `src/types.ts` — 镜像后端 DTO（字段名是契约）
- `src/api.ts` — 类型化 fetch 客户端（overview / issues / commits / agents / sessions）
- `src/office/` — 看板本体：Office（布局）/ Header（抬头栏）/ DepartmentRail + EmployeeCard（员工工位）/
  IssueBoard + CommitBoard（中央公告墙）/ AgentDrawer（详情抽屉）/ roles（部门元信息）
- `src/components/` — TranscriptThread（对话气泡）
- `src/hooks/useLiveData` — 轮询；`src/lib/agentHealth` — 员工健康态判定
