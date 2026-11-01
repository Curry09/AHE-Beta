# 模型 Token 用量统计

迭代实验按模型请求记录 Token 用量，并按角色、会话和轮次汇总。原始事件是统计来源，汇总值由筛选后的事件计算。独立 Harbor 评测使用自己的用量记录，见[评测指南](../evaluation/docs/harbor.zh-CN.md)。

## 数据位置与归属

控制器通过 `AUTO_DESIGNER_USAGE_PATH` 指定本次运行的 `usage.jsonl`。统一实验入口将其放在运行数据目录的 `role_runs/<run_id>/` 下；未显式指定路径的独立进程默认写入 `backend/data/usage.jsonl`。E2B 中的记录需要通过 `collect` 收集到管理主机。

`UsageContext` 使用 `contextvars` 关联 run、轮次、会话、用户画像、任务、槽位、Harness 提交、角色和请求。NexAU worker 线程通过 `copy_context()` 继承这些信息，避免并发会话混用归属。

事件不保存 API 密钥、提示词或请求正文。提供商未返回 usage 时，仍记录调用，Token 字段为 `null`，`usage_source` 为 `unavailable`。系统不按字符数估算 Token；已接入监测的重试请求分别记录。

## 覆盖范围

| 链路 | 用量来源 | 可用性 |
| --- | --- | --- |
| 模拟用户 | OpenAI 兼容响应的 `usage` | 取决于提供商是否返回 |
| Triage、Synthesizer、Divergent、模型 Owner | NexAU tracer 响应中的 `usage` 或 `usageMetadata` | 取决于运行时与提供商是否提供 |
| 被试 Harness | Harness tracer 通过专用 stdout 通道回传，控制器补充会话归属 | 取决于具体 Harness 版本的接入情况 |
| OpenAgents 交付 | 独立进程或容器中的交付调用 | 当前控制器没有统一的逐请求 usage 接入 |

表中的用量来自上游返回值，计数口径由供应商决定。缺失部分应与已记录总量一起解释，不能把控制器的已知总量当作整场实验的完整账单，也不能从交付文本日志推算精确 Token。

汇总同时报告 `event_count` 和 `unavailable_count`。缺失用量不参与数值求和，因此总量需要结合缺失调用数阅读。

## 查询与展示

绑定实验后，可通过观测 API 查询：

- `GET /api/usage/events`：请求事件。
- `GET /api/usage/summary`：总量及分组汇总。
- `GET /api/usage/sessions/{session_id}`：指定会话的用量。

前两个接口支持按 `run_id`、`round_no`、`session_id`、`instance_id`、`interaction_id`、`turn_no`、`role`、`agent_id` 和 `model` 筛选。看板展示输入、输出、角色分布、会话用量和调用明细。使用统一入口的 `dashboard RUN_ID` 可明确绑定数据源，详见[快速开始](QUICKSTART.zh-CN.md#指定实验的观测看板)。

## 记录边界

监测只覆盖已接入的调用，无法精确补算缺失的历史请求。`AUTO_DESIGNER_RUN_ID` 由编排环境指定，独立运行且未指定时会生成唯一值。

JSONL 追加使用进程内锁，读取时跳过损坏的行。统计写入失败不阻断实验主流程。该锁保护单进程内的多线程写入，不提供多进程共享文件的写入协调。
