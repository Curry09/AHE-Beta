# 两仓联合 Quickstart

以下命令从两个 sibling checkout 开始。OpenAgents 功能与开源整理均已合入 main；下面固定到 PR #186 的合并提交。auto-designer 整理合并并完成发布验收后，再补充正式发行 tag。发布前使用维护者给出的候选分支；正式发布后应按 `release/compatibility.json` 中已验证的不可变提交或 tag 组合安装。单独追踪两个分支的最新 HEAD 不保证兼容。

## 1. 安装与无模型自检

```bash
git clone https://github.com/Curry09/auto-designer.git
git clone https://github.com/Curry09/OpenAgents.git
git -C OpenAgents checkout --detach ee87df3acab036213cecbc35cdea01339a5dd988
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

### Gitea.com 证据支持候选版

上面的 `ee87df3…` 是旧配置契约基线，**不具备本次新增的 ZIP/R2 证据读取能力**。评审 Gitea.com 支持时，需要同时使用 auto-designer 0070 和 OpenAgents 0092 的实施 checkout；两侧候选分支为 `feat/gitea-com-evidence`。本地工作树未发布前，远端不会有该实现。正式 reader 提交尚未填写在 `release/compatibility.json`，不要把当前候选镜像当成正式发行版本。

切换到配套源码后，先运行无模型、无凭证的真实编码与读取契约：

```bash
# auto-designer 根目录；参数指向配套 OpenAgents 源码。
uv run --locked python backend/scripts/check_observation_contract.py --openagents ../OpenAgents
# 应包含 gzip、zip 两种 accepted 结果，各自读到授权文件。
```

实际执行的 OpenAgents 也必须来自该版本；仅更新 sibling 源码不等于更新 PATH 里的 CLI。宿主/E2B 的 `VIGIL_MODE=subprocess` 路径可重新安装 CLI 后验证：

```bash
uv tool install --force --from ../OpenAgents openagents
OPENAGENTS_NO_SELF_UPDATE=1 openagents observation-capabilities --json
```

需要单独验证账号和网络时，准备权限为 0600 的私密 env 文件，填写 `GITEA_URL`、`GITEA_USER`、`GITEA_TOKEN`。token 需要创建仓库、Issue、上传附件和读取私有仓库的权限。执行下面的显式探针会新建一个带 `observation-transport-probe` 前缀的私有仓库，发布合成证据，校验重试复用，再调用真实 OpenAgents `prepare` 核对 session 范围、历史文件、摘要和 `0400` 权限；结束关闭 Issue，保留探针仓库供审计。

```bash
uv run --locked python backend/scripts/check_gitea_evidence_transport.py \
  --live --openagents ../OpenAgents \
  --env-file /absolute/path/private-gitea.env \
  --output-dir /absolute/path/new-probe-results
```

自建 Gitea 通常选择 gzip；Gitea.com 选择 ZIP，并通过严格限制的 R2 单次跳转下载。探针通过证明证据链路可用，不代表完整模型实验已通过。容器构建和代理开关见[配置说明](CONFIGURATION.md#giteacom-证据传输)。E2B 仍需原有 E2B 凭证和运行环境，这次变更没有增加通用一键 E2B 启动器。

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

## 结构综合配置

结构综合角色使用 `synthesizer`，四类需求角色共享 `DEMAND_LLM_*`。可从 `examples/experiments/synthesizer-*.json` 准备开发配置，并填写本次源码与资产 pin；完整字段见[配置说明](CONFIGURATION.md)。冻结实验材料保持原样，开发者按需手动准备历史运行所需的输入和源码。
