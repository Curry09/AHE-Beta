# auto-designer

[English](README.md) | 简体中文

通过模拟用户反馈，迭代改进编码 Agent Harness 的研究框架。
Python 3.12+ · Linux / WSL2 · MIT。通过快速开始选择本地 Docker 或 E2B。

auto-designer 模拟用户使用 Harness，把使用轨迹转为需求，再交给独立的 [OpenAgents](https://github.com/Curry09/OpenAgents) 实现。每轮交付封口后，用户试用新的 Harness；末轮只试用，不再交付。体感、技术验收和 留出基准测试 分开记录。

**Synthesizer（结构综合）**综合相关提案，形成结构性改进方向，不负责代码实现。Triage、Synthesizer、PM 共用 `auto_designer.demand` 包和 `DEMAND_LLM_*` 模型配置。仍有效的文件访问、编排仓完整性与 Harness 提交边界检查位于 `auto_designer.guards`。

当前代码和开发配置直接使用 `synthesizer`、`N_SYNTHESIZERS`、`SYNTHESIZER_GROUPING`。详见[配置说明](docs/CONFIGURATION.zh-CN.md)和[分组综合](docs/synthesizer-grouping.md)。

本仓是**实验控制器**；OpenAgents 是**交付 CLI**；`backend/harness_template/` 是**被进化产品的初始源码**。实验迭代得到的 Harness 应作为带版本的独立产物发布。

## 运行实验

选择本地 Docker + 自动启动的 localhost Gitea，或 E2B + 本人的 Gitea.com 账户。两者使用同一入口、相同实验格式。仓内 N=1 示例在固定 pvlib 任务上跑五轮：R1–R4 包含交付，R5 只试用最终 Harness。

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

先看[快速开始](docs/QUICKSTART.zh-CN.md)，再按[完整 N=1 教程](docs/tutorials/n1-experiment.zh-CN.md)操作，了解材料、模型协议、provider 凭证、进度、停止/恢复、收集与清理。prepare 自动获取固定版本 OpenAgents，不需要提前放置 sibling checkout。[验证报告](docs/validation/spec-0069-new-user.md)独立记录实际检查结果。

无需模型或基础设施的脚本演示：

```bash
uv run --locked python backend/scripts/offline_demo.py
```

当前采用源码运行，尚无 PyPI 入口；`uv.lock` 固定 NexAU 和兼容依赖。

## 文档和开发

- [配置说明](docs/CONFIGURATION.zh-CN.md)：v2 JSON、任务包、persona、凭证。
- [当前架构](docs/ARCHITECTURE.md)：需求面、交付面和产物边界。
- [公开快照](docs/EXPORTING.md)：发布粗粒度进度，原始会话留本地。
- [联合发布清单](docs/RELEASING.md)：版本冻结与发布步骤。
- [贡献指南](CONTRIBUTING.zh-CN.md)、[安全说明](SECURITY.zh-CN.md)、[第三方来源](THIRD_PARTY.md)、[变更记录](CHANGELOG.md)。

```bash
uv sync --locked --extra experiments --extra dev
uv run --locked --extra experiments --extra dev pytest -q
```

前端开发需要 Node.js 22，在 `frontend/` 执行 `npm ci`、`npm test`、`npm run build`。实时 API 面向本地受信环境，静态 Pages 是另一条发布路径。

`docs/specs/` 保存设计契约和任务映射，`evaluation/` 与带日期脚本保留历史研究流程和各自冻结版本。新实验使用统一入口。用户体感、闭环完成不等于官方 benchmark 通过，留出评分仍独立执行。

## 许可证

项目代码采用 [MIT 许可证](LICENSE)。第三方材料保留各自的许可条款，详见[第三方来源说明](THIRD_PARTY.md)。
