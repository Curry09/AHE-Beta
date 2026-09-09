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

## GitHub Pages 多实验共享

设置 `VITE_STATIC_SITE=1` 构建时，页面从 `public/experiments/<experiment-id>/api/`
读取脱敏快照，并通过顶部选择器切换实验。不要把原始 prompt、完整 session、token、容器名或内部日志
放进 `public/`。可用仓库脚本从一次实验的监控目录生成快照：

```bash
python backend/scripts/export_experiment_snapshot.py \
  /root/src/auto-designer-experiments/<run-id> frontend/public/experiments \
  --title "实验标题"
```

GitHub Actions 会构建并发布 `frontend/dist` 到 Pages；正在运行的实验仍应通过单独部署的后端 API
查看，Pages 适合公开静态回放。
轮询 3s（无 WebSocket）；后端不可达时保留上次数据不闪空。
