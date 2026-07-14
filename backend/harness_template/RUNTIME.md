# Harness Runtime（owner / 设计师 / 开发者）

短宪法：本仓怎么接框架、能改什么、能读什么。  
**不是** NexAU 百科——框架细节去读钉死的 NexAU 源码（只读）。

## 工作边界（硬）

| 范围 | 权限 | 说明 |
|------|------|------|
| **本 harness 仓** | 读 + 写 | 被进化对象；改动只落这里 |
| **NexAU 库**（环境所挂的那份，只读） | **只读** | 查 API / 多 agent / 锁与 session 等；**禁止修改** |
| auto-designer 编排仓、`data/sessions`、`data/harness_runs` | **禁止** | 轨迹/编排细节 → 过拟合 |

未记载的「发明框架用法」：先读 NexAU，再只在 **本仓** 落地；不要改 NexAU，不要翻轨迹。

## 仓内四层（改哪里）

| 层 | 文件 | 动它当… |
|----|------|---------|
| L1 用户契约 | `MANUAL.md` | 用户可观察行为变了必须同步 |
| L2 进程契约 | `entry.py` | JSONL、打断/超时、session 生命周期、多 agent 编排 |
| L3 本文件 | `RUNTIME.md` | 边界与本仓硬约束（保持短） |
| L4 行为/工具 | `agent.yaml` · `agents/` · `tools/` | prompt、工具、预算钮 |

## 本仓硬约束（接线，不是框架说明书）

1. **进程级固定 `session_id`**；超时/强打断 `rebuild` 只换 `agent_id` 避锁，并 **显式回灌 history**。  
   换实例 ≠ 换 session。失忆 = 本仓接线 bug。
2. **优雅打断**（`force_stop` 成功）→ 同实例，回 `[interrupted]`。  
3. **硬超时** → rebuild + 回 `[timeout]`（可续聊），不闷头静默重试同一轮。  
4. **两条状态轴**：对话记忆（NexAU history）≠ 盘面（`SANDBOX_WORK_DIR`）。记忆必须接上；半成品可能仍在磁盘。
5. **一级钮**：`entry.py` 的 `_CALL_TIMEOUT` / `_RUN_RETRIES`；`agent.yaml` 的 `max_iterations` / llm timeout。先质疑这些和交付方式，再堆恢复逻辑。

框架侧（如何 `Agent(...)`、history key、多 agent 原语等）→ **读 NexAU**，以你环境里 import 到的那份为准。
