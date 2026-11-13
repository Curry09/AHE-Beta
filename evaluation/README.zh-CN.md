# Harbor 统一评测框架

[English](README.md) · [完整中文教程](docs/harbor.zh-CN.md)

在仓库根目录只维护一个 [`evaluation.yaml`](../evaluation.yaml)，密钥放被忽略的 `.env`。支持 v0、u8、u8-direct、u16、u32、Claude Code、Meta-Harness 和固定版本的 AHE，可选直接解题或带用户模拟。

默认 `task_source: harbor_index` 使用固定版本的官方任务；也可选择 `task_source: harbor`，传入已准备好的标准 Harbor 任务包路径。任务名单、下载和裁判规则由对应 profile 解释，配置及执行层不套用 Index 规则；示例见完整教程。

仅评测 AHE 时，可直接使用下节自包含安装步骤，无需访问 Legacy 的二进制运行材料。

请按完整教程在独立虚拟环境安装 `evaluation/requirements.lock` 和本目录；运行材料从 [Release](https://github.com/Curry09/AHE-Beta-Legacy/releases/tag/harbor-evaluation-framework-v1.0.0) 下载。

```bash
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
python -m evaluation report runs/<运行ID>
```

恢复用 `resume`；仅补体验分用 `review`；符合条件的裁判失败用 `regrade` 恢复。已有有效得分不会触发自动重新解题。运行输出、完整 trace 和真实凭证不进入源码仓库。

独立于自进化入口 `backend/scripts/experiment.py`。已完成离线回归及标准 Terminal-Bench 任务 `fix-code-vulnerability` 的真实 E2B 验收：通过 `task_source: harbor` 使用当前 seed 与 GLM-5.3-Flash，原仓 367 项和任务附加 6 项测试全部通过，reward 为 1.0。记录见 `evaluation/verification/`。新第三方 Harness 仍需实现适配器。

## AHE 的 Anthropic Messages 适配

`ahe` 选择第三方 [agentic-harness-engineering evolved harness](https://github.com/china-qijizhifeng/agentic-harness-engineering/tree/182ea06e578df7b1d503eca537503c1e4c5a8a58/experiments/evolved_harness)，固定到 `182ea06e578df7b1d503eca537503c1e4c5a8a58`。原提示词、记忆、工具、风险中间件和 300 次迭代上限保持原样；适配仅处理传输、模型运行参数与观测，不启动其自进化循环。

只评测 AHE 时，无需下载旧 runtime 或 harnesses 压缩包。按完整教程使用 uv-managed CPython 3.12（建议 3.12.13）安装 Python 依赖，并安装 Git 和 uv，再从仓库根目录执行：

```bash
python -m evaluation.harness.ahe --destination ../harnesses/ahe --build-runtime
cp examples/evaluation/ahe-messages.yaml evaluation.yaml
# 修改 evaluation.yaml 中的接口地址，在 .env 填写所需凭据。
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
```

命令拒绝覆盖已有源码或 runtime 目录。它从固定提交 `28511d9f0362191a6c378fd441b2be55309a9e32` 构建原生 NexAU 到 `runtime/ahe/`，不修改控制器 SDK；也可用 `--runtime-wheel PATH` 导入已有原生 wheel。包内文件必须匹配固定源码指纹，ZIP 构建元数据允许不同。准备阶段再次验证材料哈希和冻结的依赖锁。kit 自带 Python 压缩包：存在基础 runtime 时复用其压缩包，否则打包当前 uv-managed CPython 3.12；也可通过 --python-archive PATH 显式提供已有压缩包。仅评 AHE 不依赖 Legacy Release，生成的 kit 不提交 Git。

模板需先复制到根目录，其路径按根目录配置解释。默认一题、一次重复；需要时显式改为 `tasks: published38` 或设置 `execution.repetitions`。`actor.api_type: anthropic_chat_completion` 仅允许与 `harnesses: [ahe]` 配合；`actor.base_url` 填原生 SDK 的 Messages 服务根地址，模拟用户使用独立的 OpenAI 兼容地址。ACTOR_API_KEY、USER_API_KEY、E2B_API_KEY 和题目需要的 JUDGE_API_KEY 放入 `.env`。模板显式设置 max 推理强度、65,536 最大输出、thinking 和原生流式，提供商须支持这些参数。不填写 api_type 保留上游 Responses；也支持显式 openai_responses 和 openai_chat_completion。

保持 `execution.time_adaptation: false`：AHE 没有剩余时间适配，仍遵守官方整题共享预算及 HTTP/read 超时。`user.enabled: true` 使用现有回复后追问策略，false 为 direct。现有两种任务源均保留支持。原生 SDK 回放 signed thinking 和工具历史，缓存 Token 只计算一次，没有 message_stop 的流保持统计不完整，输出上限终止记为 ModelOutputLimit，不额外添加适配器重试。完整轨迹和凭据属于私有运行产物。

本地 HTTP fixture 覆盖真实固定版本 Agent 和 shell 工具、流式、反馈、signed thinking 回放和错误处理。真实模型和提供商评测通过独立的运行记录验证。

真实 Agent 测试要求主机安装固定版本的 NexAU，否则跳过对应测试。仓库 CI 在执行前通过 `uv sync --locked --extra experiments --extra dev --extra harbor-evaluation` 安装并校验该 SDK。Fixture 测试不需要模型密钥。
