# LLM Token 用量监测设计

## 数据流与归属

每个模型请求产生一条追加事件，原始事件写入 `backend/data/usage.jsonl`，聚合值不另作权威存储。
`UsageContext` 使用 `contextvars` 绑定 `run_id / round_no / session_id / instance_id /
interaction_id / turn_no / agent_id / role`；
现有 NexAU worker 线程通过 `copy_context()` 继承绑定，因此并发 session 不共享可变全局上下文。
API 汇总始终由过滤后的原始事件求和。

事件不保存 API key、prompt 或请求正文。usage 缺失仍记录调用，Token 字段为 `null` 且
`usage_source=unavailable`；当前没有以字符数估算 Token。每次重试都是独立请求和独立事件。
JSONL 的进程内追加由锁保护，解析时跳过意外损坏的行。所有监测写失败均为 best effort，不影响主流程。

## 精确度矩阵

| 角色/链路 | 状态 | 来源 |
| --- | --- | --- |
| user persona | reported（精确） | OpenAI-compatible `ChatCompletion.usage` |
| triager/designer/divergent/owner | reported（上游提供时精确） | NexAU LLM tracer 完整响应中的 `usage` / `usageMetadata` |
| harness | reported（上游提供时精确） | harness NexAU tracer 经专用 stdout usage 旁路回传，宿主补 session/instance 归属 |
| developer/vigil | unavailable | vigil 在独立容器内经 OpenAgents/Claude 调用；宿主目前只有文本日志，没有逐调用结构化 usage 或归属协议 |

当前生产接线所固定的 OpenAgents 版本尚未向宿主提供逐调用 usage 事件：容器入口只启动
`openagents vigil`，宿主只消费普通运行日志。该判断针对结构化接口能力，而不是某个本机 checkout
路径；升级 OpenAgents pin 时必须重新审计，并在实验记录中保存对应 commit SHA 与事件样例。
因此 vigil 的后续接入点是让容器以同一 JSONL 事件 schema 输出 sidecar/挂载文件或 HTTP 事件，并显式传入
`run_id / round_no / instance_id / agent_id`。在上游暴露该协议前不从日志字符数伪造精确 Token。

## 查询

- `GET /api/usage/events`：原始事件
- `GET /api/usage/summary`：总量及按角色汇总
- `GET /api/usage/sessions/{session_id}`：单 session 汇总

前两个接口支持 `run_id、round_no、session_id、instance_id、interaction_id、turn_no、role、agent_id、model`
查询参数。看板展示总量、输入、输出、角色分布、按题 user/harness 分项与调用明细。

## 运行边界

监测仅对加载新代码后的进程生效，不能精确补算正在运行或已完成的历史调用。`AUTO_DESIGNER_RUN_ID`
可由编排环境显式指定；未指定时进程启动生成唯一值。当前写锁保证单进程多线程安全；未来若多个宿主进程
直接共享同一 JSONL，应改为文件锁或单写入服务。
