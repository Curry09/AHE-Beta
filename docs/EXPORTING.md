# 公开静态快照

静态快照用于分享实验的概要进度。导出器只保留预先定义的状态和计数字段，原始会话、任务代码与诊断日志继续保存在私有实验记录中。

## 导出

从仓库根目录运行，输入目录应包含 `telemetry/monitor-latest.json`，也可包含历史记录 `telemetry/monitor.jsonl`：

```bash
uv run --locked python backend/scripts/export_experiment_snapshot.py \
  "$EXPERIMENT_ROOT" "$NEW_PUBLIC_DIRECTORY" \
  --public-id demo --title "Experiment snapshot"
```

将 `EXPERIMENT_ROOT` 设为已有监控记录的实验目录，`NEW_PUBLIC_DIRECTORY` 设为本次导出的新目录。脚本会生成实验索引、最新状态、时间线和前端使用的静态 API 数据。

## 公开内容

导出范围包括已知状态、规范化时间、非负整数计数、布尔值、已知角色和告警数量。Agent 标识会替换为序号；未指定 `--public-id` 时，实验目录名会转换为散列标识。

提示词、Issue／PR 正文、原始告警、日志、未知字段和自由文本状态均不导出。`--title` 与 `--public-id` 则是操作者提供的公开信息，发布前应确认其中不含私密内容。散列标识不会直接暴露源目录名，但不构成匿名性保证。

导出器会更新目标索引，但不会删除已有文件或重新处理目标目录中的其他实验。重新制作整套公开资产时，请在新目录导出、检查内容后替换旧资产。仅发布生成的静态数据，不将原始 telemetry、会话或完整实验归档放入公开站点。

## 快照时间与实时观测

静态页面展示采集时的状态和时间。例如 `RUNNING` 表示记录产生时仍在运行。索引中的 `updated_at` 来自监控数据的 `time`，按 UTC 展示；重新构建站点或再次导出同一份数据不会刷新记录时间。

需要查看运行中的实验时，使用 `backend/scripts/experiment.py status`、`logs` 或绑定该 run 的 `dashboard`。默认开发 API 不会自动选择实验；E2B 看板读取最近一次收集的快照，需要再次 `collect` 更新数据。

公开快照导出与实验产物收集是两项操作。保存完整实验记录使用 `backend/scripts/experiment.py collect RUN_ID`，详见[快速开始](QUICKSTART.zh-CN.md)。
