# frontend — 像素小镇观测看板（React + Vite + TS + Phaser 3）

只读看板：消费 `backend/auto_designer/web/api.py` 的 `/api/*`。**左**是像素办公室小镇（agent 化身像素同事在工位间走动），**右**是 Issue 板 + main 分支板；点击小人时，该 agent 的完整对话覆盖右侧面板。

## 引用 / 致谢

小镇渲染引擎与像素素材移植自 **[geezerrrr/agent-town](https://github.com/geezerrrr/agent-town)**（MIT License，© Agent Town authors）。

- 复用范围：`src/components/game/**`、`src/lib/{events,logger,constants}.ts`、`src/types/game.ts`、`public/{maps,tilesets,characters,sprites,fonts}/**`（Phaser 场景 / 实体 / 系统 + 像素素材）。
- 改动：仅保留渲染层，去掉上游的 OpenClaw gateway / HUD / 任务执行层，改由本项目 backend 数据（agents / issues / commits / sessions）驱动。
- 完整归属见 [`NOTICE.md`](./NOTICE.md)。

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
- `src/App.tsx` — 顶层布局：左小镇 + 右侧栏（抬头 / Issue / main / 完整对话）
- `src/townBridge.ts` — 数据接线：agents → `SeatState[]`，经 `gameEvents` 驱动 Phaser 场景
- `src/panels/` — IssuesPanel / CommitsPanel / ConversationPanel（右侧面板）
- `src/components/game/` — 移植自 agent-town 的 Phaser 引擎（`OfficeScene` + Worker/Player/Pathfinder 等）
- `src/lib/events.ts` — `gameEvents` 事件总线（`seat-configs-updated` / `worker-clicked` 等，React ↔ 场景唯一解耦点）

## 数据流
```
/api/agents ──► townBridge.agentsToSeats ──► gameEvents "seat-configs-updated" ──► WorkerManager 增删小人
小人被点击   ──► gameEvents "worker-clicked" ──► App 选中 seatId ──► ConversationPanel 覆盖右侧
```
