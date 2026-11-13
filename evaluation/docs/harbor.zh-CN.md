# Harbor Index 评测框架

只编辑根目录 `evaluation.yaml`。API 密钥写入 `.env`；运行参数快照、任务配置和运行记录由框架生成，不需要维护其他实验配置文件。
固定版本 AHE 的 Messages 适配、源码与 runtime 准备及配置模板见 [AHE 安装说明](../README.zh-CN.md#ahe-的-anthropic-messages-适配)。AHE 必须关闭 time_adaptation，官方任务预算及两种任务源的原有约定不变。


## 目录

```text
workspace/
├── harnesses/                  # 已单独发布的 Harness 源码包
└── ahe-beta/
    ├── evaluation.yaml         # 唯一手动编辑的评测配置
    ├── .env.example            # 复制为 .env 后填写密钥
    ├── evaluation/             # 调度、适配器、用户模拟和评分实现
    ├── runtime/                # 固定 Python / NexAU 运行材料
    ├── evaluation/requirements.lock  # 主机依赖锁定文件
    ├── .cache/                 # 首次准备后自动生成
    └── runs/                   # 启动后自动生成
```

当前直接支持八种 Harness，包括固定版本的第三方 AHE。新的第三方 Harness 需要另写适配器，并非填写任意目录即可执行。

框架运行在 Linux / WSL，Python 3.12。Windows 上的目录可通过 WSL 使用。

## 安装和运行

在仓库根目录执行。先从本仓库的 [框架 Release](https://github.com/Curry09/AHE-Beta-Legacy/releases/tag/harbor-evaluation-framework-v1.0.0) 下载 `harbor-evaluation-runtime-v1.0.0.zip` 并解压到仓库根目录（得到 `runtime/`）。从 [Harness Release](https://github.com/Curry09/AHE-Beta-Legacy/releases/tag/harbor-evaluation-results-20261030) 下载 `harnesses.zip`，解压到仓库的上一级目录，或修改 `paths.harnesses`。

```bash
uv venv --python 3.12.13 --managed-python --seed .venv-evaluation
source .venv-evaluation/bin/activate
pip install --require-hashes -r evaluation/requirements.lock
pip install --no-deps -e ./evaluation
cp .env.example .env
# 填写 .env，并修改 evaluation.yaml 的模型及接口地址。
# 首次建议在同一 YAML 中只选一种 Harness 和一道题。
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
```

`validate` 离线检查配置和 Harness 源码位置。`prepare` 下载并校验固定版本的官方题目，打包 Harness；这两步不会创建解题沙箱或调用模型。`run` 打印运行目录，然后执行评测。首次 E2B 镜像构建需要网络和相应账号资源。

```bash
python -m evaluation resume runs/<运行ID>
python -m evaluation report runs/<运行ID>
python -m evaluation review runs/<运行ID>
python -m evaluation regrade runs/<运行ID> --trial <题目运行ID>
```

`resume` 使用该运行目录内的冻结参数，连接已有工作进程或启动尚未执行的题目。`review` 仅补评缺失或失败的体验分，保留已经有效的体验分。`regrade` 仅重新执行官方裁判，要求原提交物仍在且题目使用独立裁判环境，不重新解题。

相同配置和材料再次执行 `run` 会复用运行身份。明确需要新一轮实验时执行 `python -m evaluation run --new-run`。恢复运行需保留同一框架版本、运行材料和原路径；框架会检查内容指纹，拒绝混用代码版本。

## 配置约定

- `task_source` 选择任务源。默认 `harbor_index` 的目录、裁判和准备规则都由对应 profile 提供，通用配置层不解释这些规则。
- 在 `task_source: harbor_index` 下，`tasks: published38` 对应已发布的 38 道题；也可填题目 ID 列表或 `all`。`all` 包含 E2B 可能无法承载的题目，环境失败会单独记录。
- `harnesses` 支持 `v0`、`u8`、`u8-direct`、`u16`、`u32`、`claude-code`、`meta-harness`、`ahe`。
- `actor` 配置解题模型。默认显式 `reasoning_effort: max`、最大输出 65,536；所选提供商必须支持这些参数，框架不静默降低强度或输出上限。
- `stream: native` 保留 Harness 原生行为。自有 Harness 可显式设为 `true` / `false`；固定版本 Meta-Harness 只消费完整返回，Claude Code 由其原生 CLI 控制。
- `user.enabled: true` 开启用户模拟。固定 persona 与原评测一致：接收完整交付回复和公开 git diff，可以反馈、追问和验收，不能执行命令或修改代码。首条请求固定为官方题目原文。用户模型、地址和密钥变量可在 `user` 内指定。
- `judge` 配置官方裁判的接口地址、密钥变量和可选网关兼容。裁判模型、测试和分数定义仍由官方题目决定。未填地址时使用 Anthropic 官方地址。
- 使用 Claude Code 时必须填写 `actor.anthropic_base_url`。可用 `actor.anthropic_api_key_env` 指向独立密钥；不会使用裁判密钥作为解题密钥。
- `execution.concurrency` 控制并发题数，`repetitions` 控制预先声明的重复次数；不会因为得分低自动重跑解题。
- 官方题目规定整题解题时限，单次解题 LLM 请求超时取同一时限。用户模拟的思考和交互也计入解题时间。不会扣除 API 等待或延长官方解题预算。
- `execution.time_adaptation` 控制自有 Harness 的公开剩余时间协议；关闭时不向其注入执行时间协议。原生 CC / Meta 保留自身实现，不使用自有 Harness 的预算接口。实际设置记录在逐题快照中。
- 体验评分在解题结束、提交物冻结后进行，不占用解题预算；统一使用原 persona、保存的完整用户可见对话和终止事实，不读取官方成绩、隐藏测试或 Harness 内部推理。没有充分记录时保留缺失，不编造评分。

### 裁判网关兼容

以下选项仅属于 `task_source: harbor_index`。默认 `judge.model: claude-opus-5`、`judge.normalize_usage: false`。若网关要求模型名带提供商前缀，可配置：

```yaml
judge:
  base_url: https://your-gateway.example/api
  api_key_env: JUDGE_API_KEY
  model: anthropic/claude-opus-5
  normalize_usage: true
```

`model` 只接受 `claude-opus-5` 和 `anthropic/claude-opus-5`，是同一官方裁判的接口名称选择，不允许替换模型或改变三次投票。操作者须确认网关确实提供该裁判；名称校验不证明网关背后的模型身份。

只有网关返回 `usage.server_tool_use: null`、导致官方 ARE 镜像内旧版 LiteLLM 解析失败时，才需要开启 `normalize_usage`；它要求显式填写 `base_url`。该选项仅为 ARE 的非流式运行时裁判启动隔离环境内的回环代理，将该字段的 `null` 转成 `{}`，不修改请求、裁判正文或 token 数值；最终评分仍调用题目原有评分器。标准接口保持关闭。

代理使用动态端口并检查就绪，读取等待取官方题目解题预算，整题截止时间仍由外层执行器约束，不增加解题时长。裁判配置保存在冻结 manifest 的 `metadata.evaluation_runtime.judge`，比较入口会拒绝将不同裁判渠道、别名或兼容设置当作相同条件。恢复已有运行仍使用其冻结配置，修改 YAML 不会改写既有成绩。

这些规则由 Harbor Index 的 profile 解释，通过环境实例的 `benchmark_options` 传入 ARE；通用 worker 不导入具体基准，也不设置基准专用的全局环境变量。普通 Harbor 任务包不接收 Index 选项；需要额外支持的任务来源在 profile 内实现扩展。

### 使用其他标准 Harbor 任务包

已准备好的 Harbor 任务包可以使用同一入口；每个目录包含自己的 `task.toml`、公开题面、环境定义和测试：

```yaml
task_source: harbor
tasks:
  - ./my-tasks/task-a
  - ./my-tasks/task-b
judge:
  base_url: null
  api_key_env: JUDGE_API_KEY
```

其余 Harness、模型和执行设置沿用同一 YAML。路径相对于配置文件，任务目录名必须互不重复；准备时按实际文件内容冻结哈希，运行前检查材料是否变化。该来源不下载或改写任务，也不套用 Index 的任务名单、模型白名单或评分证据规则。切换来源时应移除 Index 专属的 `judge.model` 和 `judge.normalize_usage`，否则明确报错，不静默忽略。E2B 的镜像、任务格式及执行能力限制仍适用。

当前 E2B 路径要求预构建镜像固定到 digest。若原任务只声明 tag，应在物料准备阶段将它解析为同一镜像的不可变摘要，并保存这项差异；题面、测试、时限和资源声明保持原值。真实验收的 `fix-code-vulnerability` 按此方式准备，使用公开入口完成一次运行，原仓 367 项及附加 6 项测试通过、reward 为 1.0；记录见 `verification/standard-harbor-e2b-smoke.json`。

新的任务源若需要下载、独立评分规则或环境适配，在 `benchmarks` 中注册 profile，并实现配置校验、任务选择和准备合同；通用 parser、preparation 和 worker 无须增加按基准名称判断的分支。

## 记录和统计

每次运行保存 `manifest.json`、`state.json`、`summary.json` 和逐题目录。逐题保留官方结果、提交物、验证日志、交互记录和体验评分请求与响应。解题成功、失败、超时、基础设施故障、裁判故障分别统计；官方仍判通过的超时提交物保留通过结果，同时记录超时标记。

自有 Harness、Meta 和用户模拟保存可截获的 API 原始请求与响应，包括提供商返回的 reasoning 和工具参数/结果；中断调用保留已接收部分和中断状态。提供商未返回的内容无法保存。Claude Code 保存原生 CLI 轨迹，当前适配器不截获其 Node 进程底层 HTTP，覆盖范围明确记录。完整记录含任务代码和对话，默认仅本机可读；公开发布前应另行制作脱敏导出。

Token 统计为解题模型与在线用户模拟之和，不含官方裁判及结束后的体验评分。缺失 usage 会记录覆盖信息，不能将不完整统计当作完整开销。体验评分用量单独保存在体验记录中。

默认官方题目固定在 Harbor Index `35f01ec42b14c2b5da476099f5b0d209240bca5b`。Claude Code 固定 2.1.119；Meta 固定 `57fefdb2ff84af3fd81b69d67814acbe69bd0743`，通过兼容适配器接入 Harbor 0.24 / LiteLLM 1.104.2，保留原生提示、工具和完成机制。自有 Harness 原源码不修改，每个源码版本只生成一份运行归档；模型参数在运行时注入并记录。

## 验证

单元和回归测试可执行：

```bash
pip install -e './evaluation[test]'
PYTHONPATH=. python -m pytest -q -c /dev/null -p no:cacheprovider evaluation/tests
```

`evaluation/tests/offline_smoke.py` 还可在装有 NexAU 0.4.1 的开发环境下，通过本地模拟接口检查五种自有 Harness 的完整调用链，不使用真实模型或 E2B。验证摘要位于 `evaluation/verification/`。本次整理完成了离线测试，未启动新的付费端到端评测。
