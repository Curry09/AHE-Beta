# 公开静态快照

```bash
uv run --locked python backend/scripts/export_experiment_snapshot.py   "$EXPERIMENT_ROOT" "$NEW_PUBLIC_DIRECTORY" --public-id demo --title "Synthetic demo"
```

输出目录必须用于本次公开数据。脚本读取 `telemetry/monitor-latest.json` 与可选 `monitor.jsonl`，生成索引、latest、timeline 和前端静态 API。

允许导出的内容只有已知状态、规范化时间、非负整数计数、布尔值、已知角色，以及通用告警数量。原始告警、未知字段、Agent ID/标签/自由文本状态、日志、prompt、issue/PR 正文和详情不公开。Agent ID 替换为序号，默认实验 ID 是源目录名的散列。

`--title` 和 `--public-id` 是操作者主动指定的公开元数据，发布前须人工确认。散列只避免直接带出目录名，不承诺不可关联或匿名性。默认 URL 与旧版的源目录名 URL 不同；需要保留公开 URL 时显式传入经确认的 `--public-id`。

脚本不会删除旧文件或重新清洗索引中已有的其他实验。**修复导出器后，应在全新目录重新导出并替换旧公开资产**，不能只覆盖一个 latest 文件。公开前检查生成目录；不要把原始 telemetry、session 或整个实验 archive 放到 Pages。

## 角色名称

当前导出的结构综合角色为 `synthesizer`，对应事件为 `synthesizer_run`，与 API 和前端类型一致。已有公开实验快照属于冻结证据，保持原样。
