# auto-designer

[English](README.md) | 简体中文

通过模拟用户反馈，迭代改进编码 Agent Harness 的研究框架。
Python 3.12+ · Linux / WSL2 · MIT。通过快速开始选择本地 Docker 或 E2B。

auto-designer 模拟用户使用 Harness，把使用轨迹转为需求，再交给独立的 [OpenAgents](https://github.com/Curry09/OpenAgents) 实现。每轮交付封口后，用户试用新的 Harness；末轮只试用，不再交付。体感、技术验收和 留出基准测试 分开记录。

**Synthesizer（结构综合）**综合相关提案，形成结构性改进方向，不负责代码实现。Triage、Synthesizer、PM 共用 `auto_designer.demand` 包和 `DEMAND_LLM_*` 模型配置。仍有效的文件访问、编排仓完整性与 Harness 提交边界检查位于 `auto_designer.guards`。

当前代码和开发配置直接使用 `synthesizer`、`N_SYNTHESIZERS`、`SYNTHESIZER_GROUPING`。详见[配置说明](docs/CONFIGURATION.zh-CN.md)和[分组综合](docs/synthesizer-grouping.md)。

本仓是**实验控制器**；OpenAgents 是**交付 CLI**；`backend/harness_template/` 是**被进化产品的初始源码**。实验迭代得到的 Harness 应作为带版本的独立产物发布。

## 运行实验

选择本地 Docker + 自动启动的 localhost Gitea，或 E2B + 本人的 Gitea.com 账户。两者使用 `backend/scripts/experiment.py` 和相同的 v2 实验格式。N1 示例是一位用户试用一个任务；N4 示例是四位用户试用普通任务和 SWE 任务。同轮可由不同 persona 重复试用同一任务，每个会话有独立可写工作区。历史结果导入后追加一轮仍不支持。仓内 N=1 示例在固定 pvlib 任务上跑五轮：R1–R4 包含交付，R5 只试用最终 Harness。

```bash
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
# 填写凭证；本地 Docker 改用 synthesizer-n1-local.json。
uv run --locked --extra experiments python backend/scripts/experiment.py check --config examples/experiments/synthesizer-n1-e2b.json --offline
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config examples/experiments/synthesizer-n1-e2b.json --secrets-file .env.experiment
# 复制生成的 run ID：
uv run --locked --extra experiments python backend/scripts/experiment.py run <run_id>
```

先看[快速开始](docs/QUICKSTART.zh-CN.md)，再按[完整 N=1 教程](docs/tutorials/n1-experiment.zh-CN.md)操作，了解材料、模型协议、provider 凭证、进度、停止/恢复、收集与清理。两轮四用户的完整示例见[多用户教程](docs/tutorials/multi-user-experiment.zh-CN.md)。prepare 自动获取固定版本 OpenAgents，不需要提前放置 sibling checkout。[N1 验证报告](docs/validation/spec-0069-new-user.md)和[多用户验证报告](docs/validation/spec0073-multi-task-users.md)独立记录实际检查结果。

连续执行多个完整实验时，使用[批量教程](docs/tutorials/batch-experiment.zh-CN.md)及 `examples/batches/` 的 local/E2B 列表。批次沿用成员各自的单实验生命周期，监督到终态收集才释放并发名额；Ctrl+C 退出监督，`batch stop` 才停止已启动成员。N1/N4 列表保留各自五轮/两轮的不同设置，演示执行方式，不构成公平的因果对照。

终态完整收集后，用 `grade RUN_ID --dataset PATH --dataset-sha256 SHA` 在本机 Docker 上通过官方 evaluator 评分已保存的 SWE 会话补丁，E2B 归档也使用此路径。这不是新的 Harness 留出测试，结果不回流演化。详见[事后评分教程](docs/tutorials/post-run-grading.zh-CN.md)；只有 hash 的旧预测不能猜回补丁评分。

自己的非 benchmark seed 卡库或文本指令可用 `task import-seeds` / `task from-text` 转为 ordinary 任务包，转换不请求模型/provider，不执行 setup。将返回的绝对 `task_packages` 数组写入实验 JSON 后，继续使用 check/prepare/run。[seed/文本导入教程](docs/tutorials/seed-task-import.zh-CN.md) 提供合成卡、可编辑的用户任务和 local/E2B 配置的完整离线检查；导入不复现旧镜像/服务，也不证明任务通过。

无需模型或基础设施的脚本演示：

```bash
uv run --locked python backend/scripts/offline_demo.py
```

当前采用源码运行，尚无 PyPI 入口；`uv.lock` 固定 NexAU 和兼容依赖。

## 文档和开发

- [配置说明](docs/CONFIGURATION.zh-CN.md)：v2 JSON、任务包、persona、凭证。
- [当前架构](docs/ARCHITECTURE.md)：需求面、交付面和产物边界。
- [公开快照](docs/EXPORTING.md)：发布粗粒度进度，原始会话留本地。
- [开发维护工具](tools/dev/README.md)：探针、证据回放和交付验证。
- [历史研究索引](research/README.zh-CN.md)：旧配置、源码版本和迁移清单。
- [联合发布清单](docs/RELEASING.md)：版本冻结与发布步骤。
- [贡献指南](CONTRIBUTING.zh-CN.md)、[安全说明](SECURITY.zh-CN.md)、[第三方来源](THIRD_PARTY.md)、[变更记录](CHANGELOG.md)。

```bash
uv sync --locked --extra experiments --extra dev
uv run --locked --extra experiments --extra dev pytest -q
```

前端开发需要 Node.js 22，在 `frontend/` 执行 `npm ci`、`npm test`、`npm run build`。实时 API 面向本地受信环境，静态 Pages 是另一条发布路径。默认开发 API 不自动选择 v2 run；当前实验进度使用统一入口的 `status`/`logs`，详见[前端说明](frontend/README.md)。

目录分工：

```text
examples/experiments/                    # 可运行的 v2 local/E2B 实验定义
examples/tasks/、examples/personas/      # 任务包和 persona 输入
backend/auto_designer/experiment/        # 生命周期与包内控制器
backend/scripts/                        # 公开入口、演示、导出、CI/构建检查
tools/dev/                              # 当前维护的诊断与回放工具
evaluation/                             # 独立留出评分与适配器
research/archives/                      # 冻结的历史研究记录
.experiments/                           # 忽略的运行输出
```

`docs/specs/` 保存设计契约和任务映射，`research/inventory.json` 记录历史资料的版本与迁移位置。复现历史实验时使用对应源码版本的独立 checkout，不在当前目录执行归档 launcher。用户体感、闭环完成不等于官方 benchmark 通过，留出评分仍独立执行。

## 许可证

项目代码采用 [MIT 许可证](LICENSE)。第三方材料保留各自的许可条款，详见[第三方来源说明](THIRD_PARTY.md)。

统一入口已支持运行策略、direct 交互、指定逐轮计划与 `dashboard RUN_ID`。详见[配置说明](docs/CONFIGURATION.zh-CN.md)和[迁移验收](docs/validation/spec0072-capability-migration.md)；多任务/N4/N8 已使用同一冻结 workload 契约；历史实验追加轮仍待迁入。见[多用户验收](docs/validation/spec0073-multi-task-users.md)。
