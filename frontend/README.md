# auto-designer 观测看板（前端）

> 交互与视觉参考 [vibe-kanban](https://github.com/BloopAI/vibe-kanban)（BloopAI）——多列同屏、极简看板风格。

实时 API 模式的只读看板展示用户 / 分诊 / 发散 PM / Synthesizer（结构综合）/ Owner 的运行中状态 +
Issues·Main 栏。顶部可切「运行中 / +已完成」，已完成按轮分组；点任意方块，详情栏展示
该对象的完整信息（用户会话完整对话、dev/synthesizer 完整过程流与最终报告、issue 正文+评论、
commit 全文+diff），支持 issue/tag/commit 交叉跳转。

## 开发默认看板

下面的默认 API 读取 `backend/data/sessions`，不会自动选择 `.experiments/<run_id>`，也不会自动加载该 run 的 Gitea 配置。它用于开发现有看板；直接启动它不等于连接新的 v2 实验。当前 v2 实验用统一入口的 `status` / `logs` 查看进度，用 `collect` 收集证据。按 run 选择实时 API 尚未接入。

```bash
# 后端（数据源，:8000）
PYTHONPATH=backend .venv/bin/uvicorn auto_designer.web.api:app --port 8000

# 前端 dev（:5173，/api 代理到 :8000）
cd frontend && npm ci && npm run dev

# 生产：构建后由 FastAPI 直接托管 dist（访问 :8000 即可）
npm run build
```

数据契约见 `src/types.ts`，与 `backend/auto_designer/web/api.py` 一一对应，两侧须同步改。
结构综合角色使用 `synthesizer`、`synthesizer_run` 和 `roster.synthesizer`。

## GitHub Pages 历史快照

设置 `VITE_STATIC_SITE=1` 构建时，页面从 `public/experiments/<experiment-id>/api/`
读取脱敏快照，并通过顶部选择器切换实验。页面标注“历史快照”，显示 UTC 记录时间和当时状态；RUNNING 只表示采集时的状态，不代表当前仍在运行。不要把原始 prompt、完整 session、token、容器名或内部日志
放进 `public/`。可用仓库脚本从一次实验的监控目录生成快照：

```bash
uv run --locked python backend/scripts/export_experiment_snapshot.py \
  "$EXPERIMENT_ROOT" "$NEW_PUBLIC_DIRECTORY" \
  --public-id demo --title "历史实验标题"
```

在仓库根目录执行导出命令，EXPERIMENT_ROOT 指向该实验的监控目录，NEW_PUBLIC_DIRECTORY 使用全新导出目录。检查后再替换 `frontend/public/experiments/`；详见[公开导出说明](../docs/EXPORTING.md)。完整实验仍通过 [QuickStart](../docs/QUICKSTART.zh-CN.md) 的统一入口启动，源码目录内的历史记录从[研究索引](../research/README.zh-CN.md)访问。

GitHub Actions 会构建并发布 `frontend/dist` 到 Pages，适合公开静态回放。已显式绑定数据源的后端 API 可提供实时观测；默认开发 API 不自动绑定 v2 run。
轮询 3s（无 WebSocket）；后端不可达时保留上次数据不闪空。
