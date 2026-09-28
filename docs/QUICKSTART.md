# 两仓联合 Quickstart

以下命令从两个 sibling checkout 开始。OpenAgents 当前先从功能分支取新版；功能和整理改动合入 main 后，两仓统一从 main 的发行 tag/SHA 获取。发布前使用维护者给出的候选分支；正式发布后应按 `release/compatibility.json` 中已验证的不可变提交或 tag 组合安装。单独追踪两个分支的最新 HEAD 不保证兼容。

## 1. 安装与无模型自检

```bash
git clone https://github.com/Curry09/auto-designer.git
git clone --branch auto-designer/v0.2 https://github.com/Curry09/OpenAgents.git
cd auto-designer
uv sync --locked --extra dev
uv run --locked python backend/scripts/offline_demo.py
uv run --locked python backend/scripts/check_openagents_contract.py --openagents ../OpenAgents
cd ../OpenAgents
uv sync --locked --extra dev
uv run --locked openagents --help
```

准备分支中的新文件合并前，直接 clone 默认分支还不会包含本指南的所有命令；评审者应先切到对应候选提交。

离线演示最后输出 `Offline demo complete`；契约检查输出 `PASS`。后者实际调用 auto-designer 配置生成器，再用 OpenAgents 解析器验证默认 Gitea / standard / soft，以及显式 v0.2 / NexAU 示例，无网络或模型调用。

需要把交付 CLI 安装到 PATH 时，在 OpenAgents 根目录执行 `uv tool install --from . openagents`；更换源码后用 `--force` 重装。NexAU 后端见 OpenAgents 的 `docs/AUTO_DESIGNER.md`，默认 Claude Code 后端不需要安装这个 extra。

## 2. 准备真实实验

真实闭环会调用付费模型、创建 Gitea issue/PR 并自动修改和合并 Harness，需单独的实验仓及受信任 Docker 主机。

1. 按 [配置说明](CONFIGURATION.md) 配置模型与交付后端，模型密钥放本地 profile，不写进实验 JSON。
2. 固定 auto-designer、OpenAgents、NexAU 与 seed Harness 的提交；构建并记录镜像 digest。Vigil 构建入口为 `backend/deploy/vigil/build.sh <OpenAgents-checkout> <NexAU-checkout>`，可用 `VIGIL_IMAGE_TAG` 指定候选镜像名。NexAU pin 见联合清单。运行时应使用 digest，不使用 `latest`。
3. 每实验独立的基础设施模板为 `backend/deploy/experiment/docker-compose.yml`；旧 `backend/deploy/gitea/` 是单实例联调路径。
4. 完整的可审计 SWE-bench 闭环入口是 `backend/scripts/run_auditable_experiment.py`。它需要 frozen config、只读源码 pin、已构建镜像、seed、模型 profile 及环境预检，并非仅凭模型 key 就能启动。

```bash
# 在 auto-designer 根目录。CONFIG 指向自行准备的冻结实验 JSON。
uv run --locked python backend/scripts/run_auditable_experiment.py --config "$CONFIG" --check --no-probe
# 去掉 --no-probe 后预检也会请求模型端点。
uv run --locked python backend/scripts/run_auditable_experiment.py --config "$CONFIG"
```

`--check --no-probe` 仍会检查源码、镜像及 profile，不是纯 JSON schema 检查。历史 E2B 套件另有 [实验指南](../evaluation/harness-suite-20260920/EXPERIMENT-QUICKSTART.md)，依赖特定部署与历史配置。

**当前尚未提供已完成真人验收的通用两轮真实 demo。** 首发前须补合成人格、自有小任务、固定两个用户轮次的最小配置，并跑通 R1 交付、R2 users-only 复测；结果口径见 [发布清单](RELEASING.md)。不要把上述历史 SWE-bench 入口标成通用的一键 demo。

## 3. 产物、停止与恢复

默认实验根目录是仓库内 `auto-designer-experiments/`，可用 `EXPERIMENTS_ROOT` 覆盖。每个实验保存 manifest、journal、checkpoints、sessions 和基础设施信息；凭证与原始会话均不应直接公开。

```bash
uv run --locked python backend/scripts/experiment.py status "$EXPERIMENT_ID"
uv run --locked python backend/scripts/experiment.py stop "$EXPERIMENT_ID"
uv run --locked python backend/scripts/run_auditable_experiment.py --config "$CONFIG" --resume
```

`experiment.py start` 管理基础设施，不等于自动启动完整需求闭环；真实闭环使用上面的专用 launcher。停止基础设施前应先停止前台 launcher，避免它继续调度；停止保留数据，恢复要求原冻结身份与 recovery 记录一致。`archive` 与 `destroy` 见 CLI 帮助，后者会删除资源，不能用作普通停止。

## 4. 前端

在 `frontend/` 执行 `npm ci && npm run build` 构建；开发预览用 `npm run dev -- --host 127.0.0.1`，默认把 `/api` 代理到本机 8000。实时数据需要实际后端；无实验时不应把空看板当作闭环失败。公开静态数据按 [导出说明](EXPORTING.md) 单独准备。
