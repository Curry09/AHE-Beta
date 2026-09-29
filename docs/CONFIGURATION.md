# 配置与默认行为

## 模型与凭证

| 角色 | 入口 | 说明 |
| --- | --- | --- |
| 模拟用户 | `USER_LLM_MODEL/API_KEY/BASE_URL` | 用户侧模型；环境变量完整名称由前缀与斜杠后的字段组合 |
| 需求生成 | `DEMAND_LLM_MODEL/API_KEY/BASE_URL` | Triage、Synthesizer、PM、Owner 共用模型配置；可用 `DEMAND_LLM_REASONING_EFFORT` 设置已有推理强度选项 |
| 被试 Harness | `HARNESS_LLM_MODEL/API_KEY/BASE_URL` | launcher 转为 Harness 使用的 `LLM_*` |
| Claude Code 交付 | `ANTHROPIC_*` 或 `CLAUDE_CODE_OAUTH_TOKEN` | 独立 CLI 凭证，按入口选择；并非 `DEV_LLM_*` |
| OpenAgents NexAU 交付 | `OPENAGENTS_NEXAU_MODEL/BASE_URL/API_KEY` | 选用 `backend: nexau` 时，使用 Anthropic-compatible Messages 端点 |

`backend/.env.example` 对应旧 `backend/run.py` 的本地模型配置。可审计 launcher 则从 `$EXPERIMENTS_ROOT/.profiles/<models.profile>.env` 加载 profile；示例见 `examples/models.env.example`，文件权限设为 0600。两种入口的配置不要混用。profile 的模型名来自冻结实验 JSON，不能靠修改 shell 环境绕过 source/model pin。

`.env`、`.env.*`（示例除外）、`.e2b`、`.boyue`、`.profiles/` 和默认实验输出已被忽略；这只能阻止新文件误入版本控制，不能清理已提交的历史内容。

## Synthesizer 配置

共享需求角色代码位于 `backend/auto_designer/demand/`，结构综合角色定义位于 `backend/agent_defs/synthesizer/`。主入口、回放脚本、看板和恢复键统一使用 `synthesizer`，对应事件为 `synthesizer_run`。

| 设置 | 当前名称 |
| --- | --- |
| 结构综合实例数 | `N_SYNTHESIZERS` |
| 前置分组开关 | `SYNTHESIZER_GROUPING` |
| 实验编制 / 模型 | `roster.synthesizer` / `models.synthesizer` |
| 审计实验分组开关 | `execution.synthesizer_grouping` |

开发配置使用以上名称。`examples/experiments/synthesizer-*.json` 提供配置样例，实际运行前填写本次实验的源码和资产 pin。冻结历史材料保持原样，开发者按需要手动准备输入；原有配置结构、身份和摘要校验保持不变。

项目名 `auto-designer`、顶层包 `auto_designer`、项目变量 `AUTO_DESIGNER_*` 和既有 Gitea 仓库账号不随角色改名。分组行为见[分组综合](synthesizer-grouping.md)。

## 默认交付配置

`backend/run.py:write_openagents_config()` 每次生成 Harness 仓的 `.openagents/openagents.yml`：

| 设置 | 当前行为 |
| --- | --- |
| forge | `gitea`，token 通过环境变量传入，YAML 只存 `token_env` 名称 |
| flow | 不写此键，OpenAgents 回落到 `standard` |
| coordination | `soft`，可用 `VIGIL_COORDINATION=off/dependencies` 覆盖 |
| CI / e2e | 默认 `skip`；CI 基建就绪后可设 `VIGIL_CI_STAGE=agent` |
| RFC / architecture / review / merge | `agent`；自动交付与合并 |
| release | `manual`；决定发版时机，不表示逐个 PR 都人工审批 |

`auto-designer/v0.2` 是 OpenAgents 源码分支名。运行时 `flow: v0.2` 是另一项显式配置，示例见 `examples/openagents-v02-nexau.yml`。这个示例用于独立 OpenAgents 配置/契约检查，不能放进旧 launcher 后期待它不被生成器覆盖。

## 部署边界

首发目标是 Linux/WSL2 的受信任本地部署。实时 API 不是匿名公网服务；Gitea 本地映射绑定 loopback。runner 挂载 Docker socket，具有相应宿主权限；Vigil 的网络限制不等于整个实验系统可安全执行任意不可信代码。

容器模式还需要配置模型域名的 egress allowlist；改 API URL 后连接失败，应同时核对协议、凭证和网络出口。宿主 subprocess 模式缺少容器边界，仅用于有人观察的调试。

## Gitea.com 证据传输

<!-- Spec-0070/T5 -->

附件格式按服务器公布的允许类型选择：优先 gzip，否则 ZIP；权限错误或网络错误会明确失败，不会触发格式回退。Gitea.com 使用 ZIP 和 `gitea-com-r2-v1` 下载策略。原自建 Gitea 的 gzip 字节、机器句柄及直接下载路径保持兼容。

实验在模型运行前写入观测目录的 `.transport-profile.json`，固定仓库、编码、下载策略和预算。`.framework-contract.json` 保持旧结构。恢复旧目录且没有 profile 时按 gzip/direct 解释；不能通过删文件把同一实验切换到新格式。站点不再支持原路径时需新建实验身份。

ZIP 或 R2 路径要求实际交付运行时的 `openagents observation-capabilities --json` 通过检查；stdout 上限 16 KiB、限时 10 秒。预检及正式交付都关闭 OpenAgents 自更新。subprocess 使用检查过的 executable；容器使用检查过的 immutable image ID；复用容器会检查盒内 reader，并要求原进程已设 `OPENAGENTS_NO_SELF_UPDATE=1`，否则须重新创建容器。`.reader-capabilities.json` 保存能力和实际运行时身份，不存 token/签名 URL。

构建支持该路径的独立候选镜像：

```bash
VIGIL_OBSERVATION_PROFILE=gitea-com-r2-v1 \
VIGIL_IMAGE_TAG=auto-designer-vigil:hosted-candidate \
VIGIL_OBSERVATION_RECORD=/absolute/path/new-image-record.json \
  bash backend/deploy/vigil/build.sh ../OpenAgents ../NexAU
```

构建脚本要求显式非 `latest` tag，比较构建前后源码摘要，并在新镜像内断网执行能力检查后才写记录。记录包含真实 image ID、两份源码 HEAD/dirty/content digest；有未提交改动的镜像只能作为评审候选。正式部署把 `AUTO_DESIGNER_VIGIL_IMAGE` 设为该次验证记录中的 image ID 或发布的 digest。

两个 Compose 模板默认沿用原出口规则。托管路径需显式选择代理配置，并重新创建对应 proxy 服务使挂载生效：

```bash
AUTO_DESIGNER_EGRESS_CONFIG=./egress-gitea-com.conf \
  docker compose -f backend/deploy/experiment/docker-compose.yml config
# 使用该模板的实验启动环境也须保留同一个变量。
```

扩展只放行 HTTPS 443 的 `gitea.com` 与精确 32 位十六进制 R2 主机名；客户端还会校验附件确属当前 Issue、最多一次跳转和总时间/大小预算。R2 请求不携带 Gitea token、Cookie 或 netrc 认证。此开关不放行额外模型网关。

Gitea.com 的容器内默认地址为公网 `https://gitea.com`；自建本地实例仍映射为 `http://gitea:3000`。`VIGIL_GITEA_INTERNAL_URL` 的显式覆盖保持生效。旧 `backend/deploy/gitea/egress-proxy.conf` 还包含开发环境的上游 `cache_peer`，使用该单实例模板前应配置可达的上游；本次实测托管链路使用每实验的 `backend/deploy/experiment/` 模板。
