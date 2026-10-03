# 实验配置

[English](CONFIGURATION.md) | 简体中文

新实验采用 `schema_version: 2` 的 JSON，通过[快速开始](QUICKSTART.zh-CN.md)里的统一入口运行。复制[本地示例](../examples/experiments/synthesizer-n1-local.json)或 [E2B 示例](../examples/experiments/synthesizer-n1-e2b.json)。未知字段会报错，历史 evaluation schema 与 v1 生命周期命令在 provider 操作前拒绝执行。

## 用户需要提供的文件

| 输入 | 格式 | 示例 |
| --- | --- | --- |
| 实验定义 | v2 JSON：后端、Harness、任务、轮次、角色、模型 | `examples/experiments/synthesizer-n1-local.json` |
| 任务包 | v1 JSON：任务文本、代码来源、安装脚本、依赖锁 | `examples/tasks/pvlib-1478/task.json` |
| 任务文本 | UTF-8，不含标准答案或隐藏测试 | `examples/tasks/pvlib-1478/instruction.md` |
| 安装配方 | 受信任 shell 脚本，创建独立任务环境 | `examples/tasks/pvlib-1478/setup.sh` |
| 任务依赖 | 完整固定版本及 SHA-256 的 requirements | `examples/tasks/pvlib-1478/requirements.lock` |
| Persona | 符合仓内 persona schema 的 JSON 数组 | `examples/personas/n1.json` |
| 凭证 | 显式环境变量，或权限 0600 的 env 文件 | `examples/experiment.env.example` |

N1 示例使用 `examples/personas/n1.json`；N4 从通用主库 `examples/personas/library.json` 选择四张真实卡片。ID 必须存在于所选库中，不同 persona 的数量必须至少覆盖 sessions_per_round。

实验中的路径相对于实验 JSON；任务包中的路径相对于任务 JSON。`check --offline` 只给尚未冻结的分配预览，不拉取 Git。`prepare` 冻结每个任务的包、指令、setup、依赖锁及已验证源码 archive，再生成 `materials/task-catalog.json`、`materials/session-plan.json`、persona roster、Harness archive 和哈希清单，无需手工拼装。

## 实验字段

| 字段 | 含义 |
| --- | --- |
| `name` | 显示名称，程序自动生成唯一 `run_id` |
| `runtime.backend` | `local` 或 `e2b` |
| `runtime.gitea` | 本地用 `localhost`，E2B 用 `gitea.com`；另填仓库名前缀 |
| `runtime.local` | 可选镜像覆盖、`ci_enabled`（默认 `false`）；本地工程 CI 必须使用已核验的专属 runner |
| `runtime.e2b` | `cpu_count`、`memory_mb`、`timeout_seconds`（300–86400）；可选兼容 template |
| `harness.source` | `builtin`、`archive` 加路径和 SHA-256，或配合父来源的 `continuation` |
| `workload` | 任务包与 persona 输入及可选 interaction_plan，或继承时仅填 `{"source":"parent"}` |
| `rounds` | 轮数、每轮 session 数、最大用户并发数；继承时轮数表示新增用户轮 |
| `continuation` | 可选的当前父 `archive` 路径和预期 `sha256`；须同时声明两个父输入来源 |
| `roles` | Triage/Synthesizer/divergent/developer 数量；`owner_mode: mechanical` / `llm` |
| `models` | User、Harness、共享需求面、Claude Code 交付模型 |
| `evaluation.official_grading` | `false`，演化期间不评分；独立事后评分用 `grade` 命令 |
| `source` | 可选无凭证 HTTPS 仓库地址、完整固定提交；默认取 `release/compatibility.json` |

可选一个或多个任务包；sessions_per_round 不超过所选不同 persona 的数量，max_parallel_users 不超过 sessions_per_round。同轮不同 persona 可使用同一任务，各包自行声明 kind 和 interaction。带 continuation export 的完整当前归档可继承到新 run 追加轮次，见[追加教程](tutorials/experiment-continuation.zh-CN.md)。N=1 示例选一位 persona、一个 Triage、一个 Synthesizer、零个 divergent PM、一个交付 worker，共五轮；最后一轮始终只试用。

`builtin` 冻结当前 checkout 的 `backend/harness_template/`，不是历史 `cade14d` Harness。复现旧基线必须显式提供那份归档和真实校验和。

## 继承当前完整归档

把下面的输入声明合入完整 v2 定义；[追加教程](tutorials/experiment-continuation.zh-CN.md)提供从现有模板生成完整 local/E2B 子配置的命令。

```json
{
  "harness": {"source": "continuation"},
  "workload": {"source": "parent"},
  "continuation": {
    "archive": "/absolute/path/to/parent/artifacts.tar.gz",
    "sha256": "EXPECTED_64_CHARACTER_SHA256"
  },
  "rounds": {"count": 2, "sessions_per_round": 4, "max_parallel_users": 2}
}
```

三项来源声明必须同时出现。`continuation` 只接受 `archive` 与 `sha256`，路径按子 JSON 所在目录解析。父来源必须是 collection `COMPLETE`、`controller.experiment_complete=true`、`continuation_ready=true`，并具有版本化最终 tree export。缺失或不支持的 export 在资源创建前拒绝，旧冻结 controller 不升级。

每个新增轮继承父末轮 task/persona/interaction 配对，包括 `direct` 会话。`sessions_per_round` 等于该边界人数，`max_parallel_users` 可降低；workload 不能混入覆盖项。有 pending report 时 Triage 和 Synthesizer 各至少一个。模型、runtime、角色、策略和凭证由子配置显式决定；可选 CI 沿用子实验的本地契约。

子实验先在独立恢复域处理父反馈并等待交付，即使 count 为一也执行初始化。随后 `count` 只计新增用户轮，最后一个新增轮仍只试用。父逻辑 R5 加两轮，对应子本地 R1/R2 和逻辑 R6/R7；再追加一轮从逻辑 R8 开始。stop/resume 操作新 run，父证据与评分不混入新增用户指标；grade 和 batch 使用本地轮号。独立[验收记录](validation/experiment-continuation.md)区分合同检查与真实后端执行。

## 模型和凭证

每个模型填写 `model`、`base_url_env`、`api_key_env`。后两者是变量名，不是密钥或包含凭证的 URL。模型名在 JSON 中，prepare 后被冻结；env 提供连接凭证。

| 角色 | 示例变量 | 协议 |
| --- | --- | --- |
| 模拟用户 | `USER_LLM_BASE_URL`、`USER_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| Harness | `HARNESS_LLM_BASE_URL`、`HARNESS_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| Triage、Synthesizer、PM | `DEMAND_LLM_BASE_URL`、`DEMAND_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| OpenAgents 交付 | `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` | Anthropic-compatible Claude Code |
| E2B 基础设施 | `E2B_API_KEY` | E2B API |
| Gitea.com | `GITEA_TOKEN`；可选 `GITEA_USER` | 通过 API 解析账户 |

使用标准 Anthropic API key 时，将交付 JSON 的 `auth_type` 设为 `api-key`，`api_key_env` 填存放该密钥的变量名，并提供该变量。交付端不能填只支持 Chat Completions 的地址。同一供应商密钥可以重复填入所需 env 变量；文件不启用 dotenv 变量插值。

显式 `--secrets-file` 覆盖同名进程变量，不隐式读取 `backend/.env`、个人 Claude 配置或试跑目录。程序可以记录受保护凭证文件的路径，内容不进入材料快照或归档。迁移凭证时管理命令可用新的 `--secrets-file`。status、collect、destroy 不要求模型密钥，但云操作仍需基础设施凭证。

## 任务包

公开示例为：

```json
{
  "schema_version": 1,
  "kind": "swebench",
  "id": "pvlib__pvlib-python-1478",
  "instruction_file": "instruction.md",
  "source": {
    "kind": "git",
    "url": "https://github.com/pvlib/pvlib-python.git",
    "revision": "3f397ed44075b01f4ba535750356859195a51b2d",
    "repo": "pvlib/pvlib-python"
  },
  "setup": {"script": "setup.sh", "requirements_lock": "requirements.lock"},
  "difficulty": "15 min - 1 hour"
}
```

自有普通任务用 `kind: ordinary`，显式声明 `not_in_benchmark: true`，代码来源可为固定 Git 或 `source: {"kind": "local", "path": "./my-task"}`。SWE 任务必须使用固定 Git revision，不能声明 `not_in_benchmark`。旧单包形式的 workload.kind 必须与包一致；task_packages 列表分支不填全局 kind。

安装脚本在任务 checkout 中运行，程序注入 `TASK_ROOT`、`TASK_PYTHON`、`REQUIREMENTS_LOCK`、`VIRTUAL_ENV`、`UV_BIN`。TASK_PYTHON 是受管解释器，VIRTUAL_ENV 指向任务自己的 `.venv`。先安装带 hash 的任务依赖，再安装任务源码且不额外下载未声明依赖。controller 和 OpenAgents 分别使用自己的锁定环境。

## 后端边界和生命周期

本地路径启动每实验独立的 Gitea 和 egress proxy，然后启动所属 Vigil、用户 session 容器。Gitea 宿主端口动态分配并绑定 loopback，status 提供实际地址。模型域名、端口从显式 endpoint 生成。工程 CI 可选且默认关闭；关闭时不创建 runner。

E2B 在一个沙箱内运行 controller 与交付进程，不依赖嵌套 Docker；任务目录在沙箱内隔离，与本地每 session 容器的隔离不同。程序核对实际 CPU、内存、template/build 身份和到期时间并记录。示例请求 4 CPU、8192 MiB；耗时和费用由模型及云资源运行决定。

本地证据使用协商后的 gzip/direct；Gitea.com 使用 ZIP 和受约束的 R2 下载。预检检查实际固定版本的 OpenAgents reader，禁用自更新，并在正式用户实验前验证发布和读取。原自建 Gitea 的 gzip handle 仍受支持。

冻结 `manifest.json` 描述输入；可变 `runtime.json`、资源/controller receipt 描述实际观察。三个状态独立：实验 `COMPLETED` 可以与资源 `DESTROYED`、收集 `COMPLETE` 同时存在。Provider 不可达只表示观察未知，不代表完成。resume 要求原身份、仓库、资源及 recovery 数据；正常完成后，只有完整收集才释放专有计算资源。E2B stop 进程本身不释放沙箱。

用全局 `--runs-dir /absolute/path/runs` 放在子命令前可改运行根目录，后续管理始终使用同一根目录。prepare 后编辑原 JSON 或源码 checkout 不影响既有 run；改变实验定义应重新 prepare。

实验凭证统一使用 `examples/experiment.env.example` 模板。历史 profile 和 launcher 从[研究索引](../research/README.zh-CN.md)查找，需使用原 checkout，不作为当前 v2 配置来源。[开发维护工具](../tools/dev/README.md)各自要求显式输入。已准备的 v2 实验在本次清理后继续保留冻结源码和输入哈希；resume 不升级其中的 controller。

pvlib 配方对历史 Versioneer 使用仅构建时有效的 Python 3.12 兼容 shim，恢复已删除的 `configparser` 别名以完成 editable 安装，不修改冻结任务源码，构建后删除 shim。任务环境同时安装带 hash 的固定版本 pytest，供用户侧检查。

## 运行策略与能力迁移

可选 `policies` 控制运行行为，`prepare` 会补齐默认值并冻结进 manifest。这些设置不放在 env 文件，也不继承宿主机的同名变量。

| 字段 | 默认值与行为 |
| --- | --- |
| `policies.synthesizer_grouping` | `false`；`true` 启用已有分组调度，N1 也可使用 |
| `models.user.reasoning_effort`、`models.demand.reasoning_effort` | 可选，例如 `high`；分别交给用户客户端及共享需求角色，供应商须支持该值 |
| `policies.timing.latency_isolated` | `false`；启用后需求角色计时排除已标记的 provider 等待 |
| `policies.timing.wall_guard_seconds` | 额外宽限秒数；`0` 使用已有默认 600 秒。开启隔离时，总墙钟上限 = 角色预算 + 宽限；正整数覆盖宽限 |
| `policies.delivery.timeout_seconds`、`poll_seconds` | `86400`、`15`；本轮准入票终态等待与轮询 |
| `policies.delivery.coordination` | `soft`；也可选 `off` 或 `dependencies` |
| `policies.delivery.permission_mode` | `bypassPermissions`；也可选 `acceptEdits`、`default`。交付进程以非 root 执行；改变权限会影响无人值守的 git 操作 |
| `policies.delivery.idle_timeout_seconds` | `300`；`0` 关闭 Claude 无活动超时 |
| `policies.alarms.proposal_depth`、`ready_depth` | `20`、`20`，均须为正整数；告警阈值，不是队列容量限制或自动扩容 |
| `roles.owner_mode` | 示例为 `mechanical`；`llm` 启用已有 Owner 模型评审，共用 DEMAND 模型 |

例如在实验 JSON 增加以下片段（不替代完整实验定义）：

```json
{
  "policies": {
    "synthesizer_grouping": true,
    "timing": {"latency_isolated": true, "wall_guard_seconds": 7200},
    "delivery": {"timeout_seconds": 3600, "poll_seconds": 5, "coordination": "dependencies"}
  }
}
```

交付模型用 `models.delivery.auth_type` 明确选择 `api-key`、`bearer` 或 `oauth`；`api_key_env` 只负责寻找凭证，即使名称是 `MY_KEY` 也不会覆盖显式协议。OAuth 指 Claude `setup-token`，导出为 `CLAUDE_CODE_OAUTH_TOKEN`。旧配置未写 auth_type 时保留标准变量名的默认映射；新示例显式写 `bearer`。OAuth 可正常配置运行，但 `check --probe-models` 的 SDK 探针不支持订阅协议，会在 provider 请求前报错；用普通 check，再由实际 Claude Code 验证，不会把 SDK 探测包装成 OAuth 验证。

任务包可设 `interaction: "direct"`，由 Harness 直接完成任务；默认 `simulated_user` 使用模拟用户逐步交互。两者都保留证据与会话恢复。单任务也可显式配置 `workload.interaction_plan`；下面片段要求 count=4，且两个 persona 都已列入 persona_ids：

```json
{
  "workload": {
    "interaction_plan": [
      [["persona-a", "your-task-id"]],
      [["persona-a", "your-task-id"]],
      [["persona-b", "your-task-id"]],
      [["persona-b", "your-task-id"]]
    ]
  }
}
```

计划校验每轮 session 数量及已选 persona/task ID。同轮 persona 不重复，task 可以重复。省略计划时，按全局槽 k=(round_no-1)*sessions_per_round+slot，从配置顺序取 persona_ids[k % P] 和 task_packages[k % T]。这种简单轮转不保证覆盖全部 persona × task 组合；AABB、固定分组和交叉任务覆盖请写显式计划。普通实验的 `rounds.count: 1` 可只试用用户，不等待 Vigil；多轮和继承初始化仍须验证交付进程就绪。

`experiment dashboard RUN_ID` 绑定该 run 的 sessions、live 和 usage。local 是实时本地产物；E2B 必须先 collect，显示已收集快照时间，不冒充云端实时活动。Gitea 连接独立读取该 run 的地址和凭证；无 token 时仍能看本地产物。

本次已迁入上述设置、交互和看板；可选本地工程 CI 见下方说明，当前归档追加已接入，见[追加教程](tutorials/experiment-continuation.zh-CN.md)。旧 seed 库及纯文本任务已通过 ordinary 任务包转换接入，见下方导入说明。官方 SWE 任务评分已提供独立事后命令，演化循环内评分仍按设计关闭。多任务/N4/N8 已使用上述冻结 workload 契约。旧 v2 run 继续使用原冻结源码，resume 不升级实验。[验收报告](validation/spec0072-capability-migration.md)区分离线回归和真实云端覆盖。

## 本地工程 CI

在 local + localhost 配置中设置 `runtime.local.ci_enabled: true`，启用现有 OpenAgents 工程 CI 门禁。省略或设为 `false` 沿用原有行为，不向旧冻结配置加入 CI 默认字段。E2B + Gitea.com 不支持此 CI runner 契约；E2B 配置不能包含 `runtime.local`。

| 字段 | 默认值与行为 |
| --- | --- |
| `runtime.local.ci_enabled` | `false`；`true` 请求专属 Gitea Actions runner，并核验就绪 |
| `runtime.local.runner_image` | 可选覆盖；默认 `gitea/act_runner:0.2.11`；必须使用显式版本标签或摘要 |
| `runtime.local.ci_job_image` | 可选覆盖；默认使用固定摘要的 `catthehacker/ubuntu`；必须使用显式版本标签或摘要 |

两个镜像覆盖字段都要求 `ci_enabled: true`；`:latest` 和无版本引用会被拒绝。准备阶段记录实际 image ID。冻结 Harness 必须包含使用 `ubuntu-latest` 的 PR 工作流，runner 将此标签映射到固定 job 镜像。后端核验注册、镜像、所有权和网络身份，再执行包含 checkout 与 Python smoke 的真实探针 PR。只有该 PR 当前 head SHA 的检查成功后，才发放就绪收据并启用 OpenAgents 的 `ci: agent` stage。失败或超时阻止启动并保留诊断；启用后不能静默退回 `skip`。

每个 run 还使用私有 Docker daemon 和 job 存储，内部 `docker:27.5.1-dind` 配方按实际 image ID 固定。runner 的内部 `DOCKER_HOST` 连接此 daemon，不发布 daemon 宿主端口、不向 runner 挂载宿主 Docker socket。job 容器、名称和工具缓存都在此 run 的 daemon 内。job 的 `host` 网络模式指的是位于 run 的 CI 网络上的私有 daemon 网络命名空间。本地 Docker 必须支持该 privileged daemon 容器；preflight 核验其身份及就绪。此执行边界面向可信代码，不提供恶意代码隔离。

`status RUN_ID` 单独报告 CI。收集保存就绪收据和 main/PR 当前提交状态；旧 head 的绿灯不能证明新提交通过。`stop` 暂停所属 runner、处理所属 job 并停止私有 daemon，保留其存储和注册以供恢复。`resume` 核验原 daemon、镜像、存储及注册身份，再重新检查就绪，不注册替代 runner。`destroy` 移除所属执行资源和 CI job 存储，保留列明名称的 Gitea 和 runner 私密注册卷；收据列出保留卷。runner 注册凭据保存在私有卷内，不进入普通收集产物。

CI 只对可信 Harness 代码做工程检查，不调用模型、不运行 benchmark。官方 SWE 任务 `grade` 和 Harness 留出评估继续作为独立事后流程。命令及实际核验范围见[本地 CI 教程](tutorials/local-engineering-ci.zh-CN.md)和[验收报告](validation/local-engineering-ci.md)。

## seed 卡库与文本指令

`task import-seeds LIBRARY --output DIR [--seed ID ...]` 和 `task from-text --instruction PATH --id ID --output DIR --not-in-benchmark` 将明确提供的非 benchmark 输入转为 ordinary 任务包。两个命令都支持 `--interaction direct|simulated_user` 和父级 `--json`；不读凭证、不请求网络/模型/provider、不执行 setup。输出目录必须尚不存在。

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json task import-seeds examples/seed-inputs/library.json --output /absolute/path/to/new-seed-tasks
uv run --locked --extra experiments python backend/scripts/experiment.py --json task from-text --instruction examples/seed-inputs/instruction.md --id weekly-notes --output /absolute/path/to/new-text-task --not-in-benchmark
```

结果的 `task_packages` 是绝对路径数组：移除 `workload.kind`、`task_package` 及不再适用的 `interaction_plan` 后，赋给 `workload.task_packages`。生成的 `tasks.json` 只是以输出目录为基准的相对路径索引，不是可运行实验，也不能替代该数组。复制实验 JSON 时，persona/Harness 等相对路径也须按原 JSON 目录解析。[完整导入教程](tutorials/seed-task-import.zh-CN.md) 提供将数组写入两个当前 N1 后端模板的精确 Python 命令及离线检查。

无仓库卡和文本指令使用本地 scratch 源目录，其中初始 README 不包含答案。有仓库卡支持转为 GitHub HTTPS 的 owner/repo 标识或无凭证 HTTPS 地址，并要求固定的 40 位小写 SHA。导入只映射 prompt/source/setup，不把 oracle、env.test_cmd、gates、provenance 复制到材料或 sidecar；不会自动锁定旧 setup 依赖，也不恢复旧镜像/外部服务。prepare 前审阅生成的 setup 和 requirements。导入或离线检查成功不证明任务通过或历史环境可复现；实验仍使用 check/prepare/run。

## 多任务包

新多任务定义用 `workload.task_packages`；它与 `kind`、`task_package` 互斥，这个分支不填全局 kind。各包沿用 task-package-v1，并拥有全局唯一的安全 ID，如普通任务 `order-service` 和 SWE 的 `pvlib__pvlib-python-1478`。原单包形式在新 prepare 的输入边界转换一次；已冻结 run 保留原 config、hash 及 archive 内的 controller，未知 workload 契约版本拒绝。

`runtime.local.seed_image` 保留单任务覆盖含义，选择多个包时填写会报错；自动逐任务构建支持混合任务。本地 session 使用独立容器；E2B 复制各任务纯源码基线，在最终 session 目录重建 venv。下载/wheel 缓存可共享，可写 repo 和已安装环境不共享。E2B 同一 Unix 用户不提供等同 Docker 的恶意跨目录访问防护。

两个任务的显式计划、成本及证据路径见[完整 N4 教程](tutorials/multi-user-experiment.zh-CN.md)。

## 批次配置

批次列表独立于成员的 v2 实验 JSON。公开的 [local](../examples/batches/n1-n4-local.json)和 [E2B](../examples/batches/n1-n4-e2b.json)示例引用现有完整 N1/N4 配置。N1 为五轮、N4 为两轮，因此它们是调度示例，不构成公平的因果对照。

```json
{
  "schema_version": 1,
  "name": "synthesizer-n1-n4-local",
  "max_parallel_runs": 1,
  "entries": [
    {"id": "n1", "config": "../experiments/synthesizer-n1-local.json"},
    {"id": "n4", "config": "../experiments/synthesizer-n4-local.json"}
  ]
}
```

| 字段 | 契约 |
| --- | --- |
| `schema_version` | 整数 `1`，拒绝布尔值 |
| `name` | 非空显示名称；prepare 自动生成唯一 batch ID |
| `max_parallel_runs` | 正整数，默认 `1`；覆盖本批次活动和不确定的运行租约，持续到终态收集 |
| `entries` | 非空有序列表；唯一 `id` 用小写字母/数字及分隔连字符，最多 48 字符；完整实验 `config` 路径相对批次 JSON |

同批所有成员必须使用同一后端。未知字段、局部配置覆盖、shell executor 和参数矩阵拒绝。模型、角色、材料及每个 run 的用户并发仍在各成员配置中；凭证使用已有显式 env 文件/进程变量，不进入冻结批次材料。

`batch check --offline` 验证全部本地成员，不读凭证、不调用 provider。在线检查无法确认剩余仓库配额时报告容量未知，不证明名额足够。`batch prepare` 顺序冻结所有成员，全部成功后才可启动。前台 `batch run` 在启动确认之后继续持有运行租约，覆盖不确定观测和终态收集。Ctrl+C 退出监督但不停止子实验；`batch stop`、`batch resume` 沿用相同成员身份与恢复数据。FAILED/LOST 成员阻止其余 pending 启动；终态收集不完整时仍占名额。成功要求全部成员实验 COMPLETED、收集 COMPLETE。

批次位于 `<runs-dir>/.batches/<batch_id>/`；各成员沿用正常 run 目录，存放在 `children/<entry_id>/<run_id>/`。`intent.json`、`manifest.json` 保留不可变输入身份，runtime receipt 和 journal 保存观测。直接管理成员时，在单实验命令前指定 `--runs-dir <runs-dir>/.batches/<batch_id>/children/<entry_id>`；batch status 在 `entries` 中报告子实验 run ID，在 `child_roots` 中报告目录，再结合教程的管理和清理命令使用。修改原配置不会改变已冻结批次。

并发上限不是账户全局上限，也不是已分配资源数上限；停止/完成的沙箱及其他批次可能仍占配额。批次管理不自动销毁计算或删除仓库，顺序执行也可能耗尽仓库名额。按[批次教程](tutorials/batch-experiment.zh-CN.md)逐项收集并显式清理。

## 实验后 SWE 评分

评分输入独立于实验 JSON。`grade RUN_ID` 必填 `--dataset PATH`（本地 JSON/JSONL/parquet）和 `--dataset-sha256 SHA`；`--round` 选择正整数且已封口的轮次，默认 `config.rounds.count`。`--timeout-seconds` 默认每会话 `1800` 秒。`--offline` 只验证绑定，不调用 Docker、不写评分结果。自定义根目录或批次成员使用全局 `--runs-dir`，机器可读输出用 `--json`。此命令不读凭证文件。

安装 `uv sync --locked --extra experiments --extra dev --extra evaluation`。local 与 E2B 均在操作者的 Docker 主机上，以经过验证的终态 COMPLETE 归档评分，并要求新控制器保存的完整预测回执。每次结果写入独立的 `evaluation/<attempt_id>/`，原实验产物不改。gold patch 与隐藏测试是外部评分输入，不能成为冻结演化材料。只有 hash 的旧会话无法还原。详见[事后评分教程](tutorials/post-run-grading.zh-CN.md)和[验收报告](validation/post-run-grading.md)。这些用户任务成绩与 Harness 留出泛化测试分开，不进入反馈或 CI 门禁。
