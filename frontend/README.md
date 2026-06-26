# frontend — 观测看板（React + Vite + TS）

只读看板：消费 `backend/auto_designer/web/api.py` 的 `/api/*`，可视化体感曲线、issue 曲线与会话明细。

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
- `src/api.ts` — 类型化 fetch 客户端
- `src/pages/` — Overview（KPI+曲线）/ Sessions（列表）/ SessionDetail（transcript+体感+issue）
- `src/components/` — KpiCard / LineChartPanel（Recharts）/ TranscriptThread
