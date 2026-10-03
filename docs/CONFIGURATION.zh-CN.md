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
| `runtime.local` | 可选镜像覆盖、`ci_enabled: false`；不支持启用尚未注册的 CI runner |
| `runtime.e2b` | `cpu_count`、`memory_mb`、`timeout_seconds`（300–86400）；可选兼容 template |
| `harness.source` | `builtin`，或 `archive` 加归档路径及 SHA-256 |
| `workload` | `task_packages` 列表，或旧 `kind` + `task_package`；persona 库、实际 ID 及可选 interaction_plan |
| `rounds` | 轮数、每轮 session 数、最大用户并发数 |
| `roles` | Triage/Synthesizer/divergent/developer 数量；`owner_mode: mechanical` / `llm` |
| `models` | User、Harness、共享需求面、Claude Code 交付模型 |
| `evaluation.official_grading` | `false`，官方评分单独运行 |
| `source` | 可选无凭证 HTTPS 仓库地址、完整固定提交；默认取 `release/compatibility.json` |

可选一个或多个任务包；sessions_per_round 不超过所选不同 persona 的数量，max_parallel_users 不超过 sessions_per_round。同轮不同 persona 可使用同一任务，各包自行声明 kind 和 interaction。历史结果导入后追加一轮仍不支持。N=1 示例选一位 persona、一个 Triage、一个 Synthesizer、零个 divergent PM、一个交付 worker，共五轮；最后一轮始终只试用。

`builtin` 冻结当前 checkout 的 `backend/harness_template/`，不是历史 `cade14d` Harness。复现旧基线必须显式提供那份归档和真实校验和。

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

本地路径启动每实验独立的 Gitea 和 egress proxy，然后启动所属 Vigil、用户 session 容器。Gitea 宿主端口动态分配并绑定 loopback，status 提供实际地址。模型域名、端口从显式 endpoint 生成。当前工程 CI 跳过，不启动空 token runner。

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

计划校验每轮 session 数量及已选 persona/task ID。同轮 persona 不重复，task 可以重复。省略计划时，按全局槽 k=(round_no-1)*sessions_per_round+slot，从配置顺序取 persona_ids[k % P] 和 task_packages[k % T]。这种简单轮转不保证覆盖全部 persona × task 组合；AABB、固定分组和交叉任务覆盖请写显式计划。`rounds.count: 1` 可只试用用户，不等待 Vigil；多轮仍须验证交付进程就绪。

`experiment dashboard RUN_ID` 绑定该 run 的 sessions、live 和 usage。local 是实时本地产物；E2B 必须先 collect，显示已收集快照时间，不冒充云端实时活动。Gitea 连接独立读取该 run 的地址和凭证；无 token 时仍能看本地产物。

本次已迁入上述设置、交互和看板；工程 CI、入口内官方评分、历史产物追加轮、旧 seed 库及纯文本任务仍待实现。多任务/N4/N8 已使用上述冻结 workload 契约。旧 v2 run 继续使用原冻结源码，resume 不升级实验。[验收报告](validation/spec0072-capability-migration.md)区分离线回归和真实云端覆盖。

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
