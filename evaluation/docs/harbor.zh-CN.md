# Harbor Index 评测框架

只编辑根目录 `evaluation.yaml`。API 密钥写入 `.env`；运行参数快照、任务配置和运行记录由框架生成，不需要维护其他实验配置文件。

## 目录

```text
workspace/
├── harnesses/                  # 已单独发布的 Harness 源码包
└── auto-designer/
    ├── evaluation.yaml         # 唯一手动编辑的评测配置
    ├── .env.example            # 复制为 .env 后填写密钥
    ├── evaluation/             # 调度、适配器、用户模拟和评分实现
    ├── runtime/                # 固定 Python / NexAU 运行材料
    ├── evaluation/requirements.lock  # 主机依赖锁定文件
    ├── .cache/                 # 首次准备后自动生成
    └── runs/                   # 启动后自动生成
```

当前直接支持已有七种 Harness。新的第三方 Harness 需要另写适配器，并非填写任意目录即可执行。

框架运行在 Linux / WSL，Python 3.12。Windows 上的目录可通过 WSL 使用。

## 安装和运行

在仓库根目录执行。先从本仓库的 [框架 Release](https://github.com/Curry09/auto-designer/releases/tag/harbor-evaluation-framework-v1.0.0) 下载 `harbor-evaluation-runtime-v1.0.0.zip` 并解压到仓库根目录（得到 `runtime/`）。从 [Harness Release](https://github.com/Curry09/auto-designer/releases/tag/harbor-evaluation-results-20261030) 下载 `harnesses.zip`，解压到仓库的上一级目录，或修改 `paths.harnesses`。

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

- `tasks: published38` 对应已发布的 38 道题；也可填题目 ID 列表或 `all`。`all` 包含 E2B 可能无法承载的题目，环境失败会单独记录。
- `harnesses` 支持 `v0`、`u8`、`u8-direct`、`u16`、`u32`、`claude-code`、`meta-harness`。
- `actor` 配置解题模型。默认显式 `reasoning_effort: max`、最大输出 65,536；所选提供商必须支持这些参数，框架不静默降低强度或输出上限。
- `stream: native` 保留 Harness 原生行为。自有 Harness 可显式设为 `true` / `false`；固定版本 Meta-Harness 只消费完整返回，Claude Code 由其原生 CLI 控制。
- `user.enabled: true` 开启用户模拟。固定 persona 与原评测一致：接收完整交付回复和公开 git diff，可以反馈、追问和验收，不能执行命令或修改代码。首条请求固定为官方题目原文。用户模型、地址和密钥变量可在 `user` 内指定。
- `judge` 仅控制官方裁判的接口地址和密钥变量。裁判模型、测试和分数定义仍由官方题目决定。未填地址时使用 Anthropic 官方地址。
- 使用 Claude Code 时必须填写 `actor.anthropic_base_url`。可用 `actor.anthropic_api_key_env` 指向独立密钥；不会使用裁判密钥作为解题密钥。
- `execution.concurrency` 控制并发题数，`repetitions` 控制预先声明的重复次数；不会因为得分低自动重跑解题。
- 官方题目规定整题解题时限，单次解题 LLM 请求超时取同一时限。用户模拟的思考和交互也计入解题时间。不会扣除 API 等待或延长官方解题预算。
- `execution.time_adaptation` 控制自有 Harness 的公开剩余时间协议；关闭时不向其注入执行时间协议。原生 CC / Meta 保留自身实现，不使用自有 Harness 的预算接口。实际设置记录在逐题快照中。
- 体验评分在解题结束、提交物冻结后进行，不占用解题预算；统一使用原 persona、保存的完整用户可见对话和终止事实，不读取官方成绩、隐藏测试或 Harness 内部推理。没有充分记录时保留缺失，不编造评分。

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
