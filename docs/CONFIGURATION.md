# 配置与默认行为

## 模型与凭证

| 角色 | 入口 | 说明 |
| --- | --- | --- |
| 模拟用户 | `USER_LLM_MODEL/API_KEY/BASE_URL` | 用户侧模型；环境变量完整名称由前缀与斜杠后的字段组合 |
| 需求生成 | `DESIGNER_LLM_MODEL/API_KEY/BASE_URL` | 设计侧角色的模型配置 |
| 被试 Harness | `HARNESS_LLM_MODEL/API_KEY/BASE_URL` | launcher 转为 Harness 使用的 `LLM_*` |
| Claude Code 交付 | `ANTHROPIC_*` 或 `CLAUDE_CODE_OAUTH_TOKEN` | 独立 CLI 凭证，按入口选择；并非 `DEV_LLM_*` |
| OpenAgents NexAU 交付 | `OPENAGENTS_NEXAU_MODEL/BASE_URL/API_KEY` | 选用 `backend: nexau` 时，使用 Anthropic-compatible Messages 端点 |

`backend/.env.example` 对应旧 `backend/run.py` 的本地模型配置。可审计 launcher 则从 `$EXPERIMENTS_ROOT/.profiles/<models.profile>.env` 加载 profile；示例见 `examples/models.env.example`，文件权限设为 0600。两种入口的配置不要混用。profile 的模型名来自冻结实验 JSON，不能靠修改 shell 环境绕过 source/model pin。

`.env`、`.env.*`（示例除外）、`.e2b`、`.boyue`、`.profiles/` 和默认实验输出已被忽略；这只能阻止新文件误入版本控制，不能清理已提交的历史内容。

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
