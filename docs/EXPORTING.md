# 公开静态快照

```bash
uv run --locked python backend/scripts/export_experiment_snapshot.py   "$EXPERIMENT_ROOT" "$NEW_PUBLIC_DIRECTORY" --public-id demo --title "Synthetic demo"
```

输出目录必须用于本次公开数据。脚本读取 `telemetry/monitor-latest.json` 与可选 `monitor.jsonl`，生成索引、latest、timeline 和前端静态 API。

允许导出的内容只有已知状态、规范化时间、非负整数计数、布尔值、已知角色，以及通用告警数量。原始告警、未知字段、Agent ID/标签/自由文本状态、日志、prompt、issue/PR 正文和详情不公开。Agent ID 替换为序号，默认实验 ID 是源目录名的散列。

`--title` 和 `--public-id` 是操作者主动指定的公开元数据，发布前须人工确认。散列只避免直接带出目录名，不承诺不可关联或匿名性。默认 URL 与旧版的源目录名 URL 不同；需要保留公开 URL 时显式传入经确认的 `--public-id`。

脚本不会删除旧文件或重新清洗索引中已有的其他实验。**修复导出器后，应在全新目录重新导出并替换旧公开资产**，不能只覆盖一个 latest 文件。公开前检查生成目录；不要把原始 telemetry、session 或整个实验 archive 放到 Pages。

## 历史快照与实时观测

静态 Pages 展示已导出的历史记录：页面明确显示“历史快照”，索引 `updated_at` 显示为 UTC 记录时间，`status` 显示为“当时状态”。例如 RUNNING 表示采集时仍在运行，不证明现在仍运行，也不应改写成未经验证的 COMPLETED。标题避免使用“当前实验”。记录时间来自监控数据的 `time`，重新构建 Pages 或再次导出同一份旧监控数据都不会刷新它。

已显式绑定数据源的实时观测使用后端 `/api`；默认开发 app 不会自动选择 v2 run，当前实验进度使用统一入口的 `status` / `logs`。完整实验的收集命令是 `backend/scripts/experiment.py collect <run_id>`；本脚本是公开数据导出，不替代原始证据收集。历史研究配置与冻结版本见[研究索引](../research/README.zh-CN.md)。

## 角色名称

当前导出的结构综合角色为 `synthesizer`，对应事件为 `synthesizer_run`，与 API 和前端类型一致。已有公开实验快照属于冻结证据，保持原样。
