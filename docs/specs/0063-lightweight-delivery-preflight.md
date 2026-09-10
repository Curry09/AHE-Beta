# 0063 — 轻量交付前置与软调度

状态：已实现并验证。对应 OpenAgents spec-0091。

第一性原理：优化「有效并行交付收益 − 协调成本 − 返工成本」。前置只买便宜的信息，
不要求规划绝对正确，不把可能共享实现误当成必须等待的依赖。

## 配置与边界

`backend/run.py` 生成 `coordination: soft`，经同一份 openagents.yml 进入 subprocess 或
vigil 容器。`VIGIL_COORDINATION=off` 关闭前置和自动排边，回到正常优先级/FIFO；
`dependencies` 显式恢复旧 Curator 排硬依赖。原有 forge 依赖在三种模式下都继续生效。
模式切换在下次启动生效，不修改正在运行的实验。

OpenAgents 需使用包含 spec-0091 的版本；容器部署需用该 checkout 重建 vigil 镜像。
旧版的严格 YAML schema 不认识 coordination，不能仅更新 Auto Designer 就使用旧镜像。

## 30 张 issue 进入后的实际流程

1. 用户在本轮冻结 main SHA 上交互。非末轮产生 proposal：PM 独立到 Owner，Triage 经
   Designer 到 Owner。Owner 分别保留每张票的交付目标和验收，准入后打 openagents。
2. Vigil 发现并打 ready。soft 模式收集最多 64 张 ready open issue，排除 automation-failed。
   这只是限长规划视图；完整原始 issue 留在 forge，开发时照常读取。没有合票、删票或改验收。
3. 一次前置生成至多 8 个共享机制候选、8 条建议先后、8 条复用提示。Claude/NexAU 前置
   关闭执行工具，单轮、8,192 输出 token 上限，90 秒墙钟预算，不再追加协议修复调用。
   准入者线程在该预算内等待，新票随后入队，原有 worker 继续运行。
4. 结果按 issue 内容指纹缓存；失败也缓存，重启不会对相同快照重复烧模型。
   Owner 逐张准入时，120 秒冷却避免每张票都调用；新票仍正常派发，后续 tick 再补建议。
   单纯闭票不会触发重算。截断、漏判、坏输出和超时均允许退回普通调度。
5. 发现顺序优先展示不同热点/建议先做的票；实际领取在 SQLite 事务内复算。
   回复、合并、评审等既有动作优先级优先；只在同级新开发票之间比较热点重叠和建议前序。
   有空槽就继续派，同热点与建议成环都不会阻塞；等待 15 分钟后以 FIFO 抵消建议偏好。
   BEGIN IMMEDIATE、flock、生存证明、崩溃回收与有界失败恢复照旧。
6. 每张票独立 worktree → RFC 草案 → architecture 评审/定向修订 → draft PR → 实现与
   自测/交付 → 冲突处理、配置启用的 CI/e2e、独立 review → 合并检查 → merge/close。
   提示明确标为非权威，开发者核实当前代码后可纠正；issue 编辑会使旧开发提示失效。
7. worker 完成即领下一张，不等这一批最慢的票。30 张票、K=4 时至多 4 个同时开发，
   至少仍要承担约 30/K 个任务的工作量，前置并不会把 K 自动改成 30。
8. Auto Designer 等本轮所有准入票终态后才开始下一轮用户。任何 automation-failed、
   历史 needs-human 或超时使实验停在本轮。末轮只做用户观察。benchmark 仍 held-out。

实际并发取 N_DEVELOPERS；内建默认 1，近期混合实验配置为 4。
当前生成的阶段仍是 triage/ci/e2e=skip，rfc/conflict/review/merge=agent；
CI 可由 VIGIL_CI_STAGE 开启。不能把“保留质量闸”误写成 CI/e2e 已默认启用。

## 验证与可观测性

OpenAgents 的 `.openagents/preflight.json` 留下指纹、状态、耗时和净化后的建议，
token 用量进入现有 token-usage.jsonl。前置失败不设置 automation-failed、不写 blocked_by。
详细验证结果见 OpenAgents `docs/e2e-results/preflight-20260911/REPORT.md`。

本次验证只跑前置模型、历史规划输出回放与本地并发队列压测，没有启动真实 developer A/B。
队列正确性与调度耗时可由压测检验；真实返工率、合并冲突率、端到端节省时间仍需后续
正常开发数据判断。启用不会自动提高 worker 数；先保留当前并发，观察后再调。
