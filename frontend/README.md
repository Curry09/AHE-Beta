# auto-designer 观测看板（前端）

> 交互与视觉参考 [vibe-kanban](https://github.com/BloopAI/vibe-kanban)（BloopAI）——四列同屏、极简看板风格。

极简 vibe-kanban 风格的只读看板：同一页四列——用户 / 设计师 / 开发者的运行中状态 +
Issues·Main 栏。顶部可切「运行中 / +已完成」，已完成按轮分组；点任意方块，第四栏展示
该对象的完整信息（用户会话完整对话、dev/designer 完整过程流与最终报告、issue 正文+评论、
commit 全文+diff），支持 issue/tag/commit 交叉跳转。

## 运行

```bash
# 后端（数据源，:8000）
PYTHONPATH=backend .venv/bin/uvicorn auto_designer.web.api:app --port 8000

# 前端 dev（:5173，/api 代理到 :8000）
cd frontend && npm install && npm run dev

# 生产：构建后由 FastAPI 直接托管 dist（访问 :8000 即可）
npm run build
```

数据契约见 `src/types.ts`，与 `backend/auto_designer/web/api.py` 一一对应，两侧须同步改。
轮询 3s（无 WebSocket）；后端不可达时保留上次数据不闪空。
