---
number: "0047"
title: 并行实验运行时与真实模型认证
issue: 0
slug: parallel-experiment-runtime
summary: 保留当前实验身份、不可变 manifest、隔离本地基础设施与 v2 生命周期接线；旧 v1 命令、容量保护与认证设计已退出并归档。
tasks:
  - id: T1
    title: 当前实验身份与隔离契约
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0047-parallel-experiment-runtime.md
    scope: 保留当前 v2 实验身份、资源所有权、不可变输入和可审计管理边界；旧 v1 生命周期、容量租约与认证方案已由 0071 退出。
    acceptance: 当前公开流程仅 check/prepare/run/status/logs/stop/resume/collect/destroy；单任务限制和两后端差异明确，历史契约不作为当前启动条件。
  - id: T2
    title: 不可变 Manifest 与共享身份原语
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/__init__.py
      - backend/auto_designer/experiment/config.py
      - backend/auto_designer/experiment/manifest.py
      - backend/tests/experiment/test_manifest.py
      - backend/tests/test_experiment_config_v2.py
    scope: 保留实验 ID、config hash、Compose project 派生与不可变 manifest/journal 原语，供当前 v2 生命周期调用；旧 v1 配置解析器已退出。
    acceptance: manifest 拒绝覆盖和输入漂移，追加 journal 与恢复身份可重验；现行 v2 配置及 manifest 测试通过。
  - id: T3
    title: 每实验独立本地基础设施
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/deploy/experiment/docker-compose.yml
      - backend/deploy/experiment/egress-proxy.conf
      - backend/auto_designer/experiment/infrastructure.py
      - backend/tests/experiment/test_infrastructure.py
    scope: 保留 Compose 项目、Gitea/egress 网络和卷的所有权检查，供 v2 local 后端使用；当前流程不启动未注册的 CI runner。
    acceptance: 本地资源按实验隔离，错误 label 拒绝；stop 保留数据，destroy 仅作用所属资源；基础设施测试通过。
  - id: T4
    title: 当前 v2 生命周期与闭环接线
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/runtime.py
      - backend/auto_designer/experiment/cli.py
      - backend/scripts/experiment.py
      - backend/auto_designer/experiment/controllers/ordinary.py
      - backend/auto_designer/experiment/controllers/swebench.py
      - backend/tests/test_run_vigil.py
      - backend/tests/test_run_swebench_closed_loop.py
      - backend/tests/test_experiment_cli_v2.py
      - backend/tests/test_experiment_lifecycle_v2.py
      - backend/scripts/e2e-spec-0047-parallel-experiment-runtime.sh
    scope: 通过 v2 check/prepare/run 和管理命令启动冻结 controller，复用隔离基础设施与恢复身份；旧 create/plan/preflight/start/archive、单例入口、容量保护和认证门不再受支持。
    acceptance: 重复启动不创建第二个 controller；停止和恢复保持冻结身份；旧命令在 provider 操作前拒绝；当前 v2 CLI、生命周期及隔离测试通过。
---

# 0047 · 并行实验运行时与真实模型认证

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

> 0071 清理后的当前契约：保留身份/manifest、local 隔离基础设施与 v2 生命周期接线；容量租约/health 实现 T5 与未落地真实认证 T6 已退出 living task 列表。当前入口由 0069/0071 约束，仅 check/prepare/run/status/logs/stop/resume/collect/destroy，local+localhost 或 E2B+Gitea.com，任务包每轮一个 session。以下原设计中的 v1 命令、共享模型容量与认证强制门是历史背景，不是当前支持或验收承诺；原实现及记录从 research/inventory.json 和 Git 追溯。

将“跑一次闭环”升级为可复用的实验运行时。操作者只提交一份不含密钥的实验配置，系统便为该实验派生
独立目录、固定源码 worktree、Harness 起点、Gitea/Runner/egress/Vigil 容器、网络、卷、动态端口、
模型容量租约、日志、telemetry、checkpoint 与不可变 manifest，并通过统一 CLI 完成规划、预检、启动、
观察、停止、恢复、归档和显式销毁。所有可写资源以 `experiment_id` 为命名和权限边界；只读镜像与 seed
image 可以按 digest 共享。

完整闭环在启动前还必须消费与精确 OpenAgents SHA、Vigil 镜像 digest、Claude Code 版本、模型 profile
绑定的真实模型认证。认证不是一次简单 API smoke，而是角色协议、真实 Git 修改以及隔离 Gitea
`issue → RFC → implement → test → review → PR → merge` 的行为验收。由此，多条进化谱系可以同时运行，
且不再依赖操作者逐次修改 `run.py` 全局常量、Gitea `.env`、仓名、容器名或配置挂载。

## Motivation

当前闭环实现按“机器上同时只有一个实验”设计：运行数据固定落在 `backend/data`，Harness 固定落在
`data/harness_sandbox/harness_repo`，Vigil 配置固定落在 `data/vigil_config`，默认 Vigil 容器名固定为
`auto-designer-vigil`。启动逻辑发现同名容器正在运行时会直接复用它。Gitea Compose 也固定容器名、网络、
卷和宿主端口。单次运行时这些约定简单有效；两个实验并发时，它们会产生配置覆盖、日志混写、错误容器
attach、共享 OpenAgents runtime state、误领另一个仓库 issue，以及停止一个实验时影响另一个实验的风险。

过去为规避冲突，实验脚本反复覆写模块全局量、复制 runner、临时改仓名和容器名。每次实验都要重新检查
哪些资源必须改名，恢复也依赖操作者记住某批目录和进程。这种操作知识没有形成机器契约，导致环境准备成本
高于实验设计本身，也使“可恢复汇总”和“统一批次”容易混淆。

只隔离目录仍不够。Vigil 持有 Gitea token；如果多个实验共享同一 Gitea 用户，即使配置指向不同仓库，
真实模型仍可能通过 API 越过目标仓边界。共享 Runner、队列、volume 和固定容器名也会形成共同故障域。
因此正式进化实验默认需要项目级强隔离，而不只是独立 repo 名。镜像层可以安全复用，但可写状态、凭证和
生命周期必须独立。

另一个问题来自真实 LLM 的非确定性。现有 OpenAgents 离线测试可以证明状态机、schema、Gitea driver、
worktree 和门禁代码在 mock backend 下成立，却不能证明指定 GLM 会稳定返回可解析结构、正确使用工具、
遵守角色边界、完成提交推送，或在 Reviewer 要求返工后继续收敛。历史运行已经出现“语义正确但协议不可
解析”“代码已经推送但包装器误判”“模型未采用设计要求的标记”等预期与实况偏差。真实模型是系统的一部分，
其关键行为必须成为正式实验的发布前认证，而不能由一次长跑偶然发现。

## Guide-level explanation

操作者为一条新谱系创建配置，例如（源码与资产 pin 必须填入本次验证的实际值）：

```yaml
schema_version: 1
experiment_id: glm-evolution-e0
mode: full-evolution
source:
  auto_designer_sha: <verified-controller-sha>
  openagents_sha: <verified-openagents-sha>
  nexau_sha: <verified-nexau-sha>
  harness:
    kind: git
    revision: <verified-harness-sha>
images:
  vigil: sha256:<immutable-digest>
  seed: sha256:<immutable-digest>
models:
  profile: glm-5.2-fp8-local
  user: glm-5-2-fp8-wangyiding-mlcoding
  harness: glm-5-2-fp8-wangyiding-mlcoding
  synthesizer: glm-5-2-fp8-wangyiding-mlcoding
  delivery: glm-5-2-fp8-wangyiding-mlcoding
capacity:
  endpoint: glm-local
  user_parallel: 2
  delivery_parallel: 1
infrastructure:
  isolation: dedicated
retention:
  keep_on_stop: true
```

配置只保存标识、pin 和策略；endpoint URL、token 和 API key 由命名的 secret profile 在运行时解析，绝不
复制进配置、manifest、命令行、日志或认证证据。正式实验禁止使用浮动 Git 分支、`latest` 镜像或宿主脏
worktree。CLI 的典型操作为：

```text
experiment create  --config glm-evolution-e0.yaml
experiment plan    glm-evolution-e0
experiment preflight glm-evolution-e0
experiment start   glm-evolution-e0
experiment status  glm-evolution-e0
experiment stop    glm-evolution-e0
experiment resume  glm-evolution-e0
experiment archive glm-evolution-e0
experiment destroy glm-evolution-e0 --confirm glm-evolution-e0
```

`create` 只创建 fresh 实验根和不可变初始 manifest；目标已存在即拒绝。`plan` 只读展示将要创建的目录、
Compose project、容器、网络、卷、端口策略、模型容量和认证要求。`preflight` 在任何付费模型调用前检查
源码/镜像/seed pin、Docker 能力、资源碰撞、secret profile、容量租约、OpenAgents 认证和 Harness 起点。
`start` 按 journal 幂等推进；`stop` 只停止进程并保留 Gitea volume、仓库、checkpoint 和 telemetry；
`resume` 从本实验最后一个闭合阶段恢复。`archive` 生成只读证据包但不销毁运行态。只有带完整实验 ID 确认的
`destroy` 可以删除资源，且选择器必须同时匹配 Docker label 和 manifest 中的具体资源 ID。

默认 `dedicated` 基础设施为每个实验启动独立 Gitea、Actions Runner、egress proxy 和 Vigil。Docker image
只读层可以共享，以下可写或有权限的资源不能共享：

| 资源 | 并行实验策略 |
|---|---|
| 实验根、session、telemetry、checkpoint | 每实验独立目录 |
| Auto Synthesizer/OpenAgents/NexAU | 精确 SHA 的只读 worktree 或镜像 |
| Harness 仓与每题 workspace | 每实验、每题独立 |
| Gitea 数据、用户、token、repo | 每实验独立实例与 volume |
| Runner 数据与 job 容器 | 每实验独立 Runner 和网络 |
| Vigil clone 与 `.openagents` state | 每实验独立容器文件系统 |
| egress proxy | 每实验独立容器与 allowlist 配置 |
| 镜像和 SWE-bench seed image | 可按 digest 共享只读层 |
| 模型 endpoint | 可共享，但必须先取得全局容量租约 |

Gitea 的宿主 HTTP 端口由 Docker 动态分配，解析后写入 runtime journal；容器内部始终使用该 Compose project
的服务别名。每个 Docker 资源都带 `io.openagents.experiment_id`、manifest SHA 和 role label。系统绝不因
“名字相同”就复用资源；只有 label、image digest、配置 hash 和 manifest resource ID 全部一致时，幂等命令
才能继续操作既有资源。

完整闭环还要求一份 `certification.json`。它绑定：

```text
OpenAgents SHA
+ Vigil image digest
+ Claude Code version
+ model profile hash / protocol
+ certification suite version
```

任一项变化都会使认证失效。用户交互-only 模式可以不要求 OpenAgents 认证；只要启用 Triage 后的真实交付
阶段，preflight 就必须验证认证。认证使用极小的合成代码仓，禁止使用 SWE-bench 或正式进化题目，避免把
benchmark 变成交付测试资料。

## Reference-level explanation

### 模型网关的精确出口授权

T3 的独立代理在默认拒绝之外保留已有模型服务域名，以及用户指定的 Boyue 网关
`35.220.164.252/32` 的 HTTP `3888` 端口。新增授权必须同时匹配地址和端口，不开放任意外网或任意端口。
密钥仍只经私有 profile/进程环境传递，不写进 Squid 模板。直连 API 成功不能替代开发容器通过代理的验证；
当前网关使用明文 HTTP，因此网络链路不提供 TLS 的保密性，此授权不等于生产级网络安全承诺。

### 1. 实验身份与目录

`ExperimentConfig` 是用户输入，`ExperimentManifest` 是系统冻结结果，二者分离。`experiment_id` 仅允许
小写字母、数字和单连字符，规范化后仍须保留一个配置 hash 短后缀，避免 Docker 长度截断造成碰撞。
默认实验根由 `EXPERIMENTS_ROOT` 指定，缺省为仓外的 `../auto-designer-experiments`。任何解析后的可写路径
必须位于该实验根内；符号链接、`..`、空路径、workspace root 和其他实验根均 fail closed。

```text
<experiments-root>/<experiment-id>/
├── config.yaml                 # 不含密钥的用户输入快照
├── manifest.json               # create 原子创建，后续不可覆盖
├── journal.jsonl               # append-only 生命周期事实
├── checkpoints/
├── telemetry/
├── logs/
├── sessions/
├── workspaces/
├── source/
│   ├── auto-designer/
│   ├── harness/
│   └── pins.json
├── infrastructure/
│   ├── compose.env             # 无模型/Gitea secret 值
│   ├── runtime.json            # 动态端口与资源 ID
│   └── vigil-config/
├── secrets/                    # 0600，永不进 archive/日志/manifest
└── archive/
```

manifest 记录配置 hash、Git SHA、tree dirty=false 证明、image digest、任务/Persona/seed artifact SHA、模型
profile、角色模型矩阵、采样配置、容量预算、Compose project、隔离级别和认证 hash。动态事实只追加到 journal，
不能“更新 manifest”伪装起点未变化。journal 行带单调 sequence、UTC 时间、前态、后态、动作、资源 ID 和
错误分类；写入使用临时文件/append lock，两个进程并发 create/start 同一 ID 时只有一个成功。

### 2. 生命周期状态机

```text
ABSENT
  └─ create ─► CREATED
                 └─ provision ─► PROVISIONED
                                     └─ preflight ─► READY
                                                          └─ start ─► RUNNING
RUNNING ── stop ─► STOPPED ── resume ─► RUNNING
RUNNING/STOPPED ── archive ─► ARCHIVED
任一进行态 ── failure ─► FAILED（保留已完成阶段，可检查后 resume）
CREATED..ARCHIVED ── destroy --confirm <id> ─► DESTROYED
```

状态是观测事实，不以单个进程是否存在推断。每个阶段先写 intent，再创建资源，再写带客观资源 ID 的
completion；进程在中间死亡时，下一次命令通过 label、inspect 和 Gitea health 做 reconciliation。无法证明
资源归属时停止并请求人工处理，禁止猜测或按宽泛名称清理。

`stop` 是可恢复操作：停止需求面、日志跟随器和 Vigil，但默认不删除容器 volume、远端分支、Gitea 数据、
workspace 或容量历史。`archive` 复制脱敏 manifest/journal、session、usage、状态、Git bundle/refs、Gitea
issue/PR/comments 和容器/image provenance，排除 secrets 与工作目录中的凭证。`destroy` 是唯一删除入口，
必须显式确认并逐项报告删除对象；不提供按前缀或 glob 递归删除。

### 3. 基础设施隔离

实验 Compose 模板不得使用 `container_name`、显式全局 network name 或共享 named volume。Compose project
由 manifest 固定；Gitea、Runner、proxy 和 Vigil 都在 project-scoped 网络中。Gitea data、Runner data 是
project-scoped volume。Gitea host HTTP 端口请求 Docker 随机映射，SSH 默认不暴露；必须时也随机映射。

每个实例 bootstrap 独立 owner 和 token。token 仅能访问该独立 Gitea 实例，并以 0600 secret 文件或进程
env 传递；Vigil 只有该实例 token、模型凭证和项目内网访问能力。Vigil 仍以非 root 用户运行、零宿主代码
挂载、自 clone Harness 仓；只读挂载实验自己的 OpenAgents 配置与 entrypoint。egress proxy 只允许该模型
profile 声明的域，配置 hash 进入 manifest。Runner job 只能加入本项目 CI 网络，不得加入另一实验网络。

共享镜像必须以 digest 引用；tag 仅用于人类显示。启动后记录容器实际 image ID 并与 manifest 比对。
源代码从精确 commit 建 detached clean worktree，宿主仓 dirty 状态不会进入实验。v0/v1/v2 等 Harness 起点
是显式 seed pin，不允许从当前宿主 `backend/data/harness_repo` 猜测。

### 4. CLI 与闭环接线

`ExperimentContext` 取代实验路径和容器资源的模块全局单例，至少提供 `data_root`、`harness_repo`、
`harness_runs_root`、`sessions_root`、`vigil_config_root`、`vigil_container`、`compose_project`、Gitea host/internal
连接、模型 profile 和 telemetry context。`run.py` 与 SWE-bench runner 从上下文读取这些值；旧入口未提供
上下文时仍维持单实验默认行为并打印 deprecation 告警，但不允许与 Experiment Runtime 管理的资源互相 attach。

CLI 所有会改变状态的命令先输出 plan；`--json` 提供机器可读结果。`status` 同时展示实验状态、各容器 health、
Gitea 可达性、队列/PR、当前 Harness main、模型租约、错误保护和最近 checkpoint。`start` 可按 scope 启动
`user-only`、`design-only`、`delivery-only` 或 `full-evolution`，但 scope 必须在初始配置中声明，不能在 resume
时暗改。阶段完成写 checkpoint；任务级 salvage 必须在同一 manifest/pin 下逐题保存，汇总报告明确标注统一
批次或可恢复汇总，不能混称。

### 5. 共享模型容量与故障保护

Docker 隔离不能隔离共享 GLM endpoint 的吞吐。`capacity.py` 维护一个 experiments-root 级锁保护的容量租约
registry。endpoint profile 声明总容量单位；实验 preflight 根据用户并发、设计角色并发、Vigil 并发和协议
开销申请最大预算。只有持有租约才能进入模型阶段。租约含 owner experiment、进程/容器 identity、心跳、
申请量和到期时间；过期回收必须先核验对应进程/容器不再运行，不能仅凭时钟删除活租约。

首版按实验峰值预留，不构造会改写 OpenAI/Anthropic payload 的中间代理。各入口把已获预算机械映射到
`MAX_PARALLEL_USERS`、设计 shard 和 `VIGIL_PARALLEL`，禁止代码绕过配置自行放大。容量不足时 `start` 排队
或 fail closed，由配置决定，不通过重试风暴争抢。

`health.py` 按实验统计滚动成功率、HTTP/transport 分类、延迟、连续空响应和无 token 记录；保护触发只暂停
当前实验并写 checkpoint，不停止共享 endpoint 或其他实验。usage 事件必须带 experiment/run/round/task/role/
model/protocol，排队时间和 API latency 分开记录。模型服务本身的共同故障仍是实验限制，报告必须披露同一
时间窗口是否有其他实验共享 endpoint。

### 6. OpenAgents 真实模型认证

OpenAgents 在自身仓库以对应 Spec 实现 live suite，本仓只定义消费契约。live suite 不进入默认 pytest，
必须显式 opt-in 且使用专用临时 Gitea。它包含三层：

1. **角色协议 canary**：Drafter、Architect、Refiner、Implementer、Tester、Reviewer、Merger 分别在有界输入上
   返回真实结构化结果；每个角色连续三次一次解析成功，必填字段/schema/终态正确，不断言具体措辞。
2. **真实工具与 Git canary**：在极小仓库中让模型读取 issue、修改限定文件、运行真实测试、commit 和 push；
   客观断言修改范围、测试由红转绿、HEAD 前移、remote head 一致且无伪造结果。
3. **隔离 Gitea 完整闭环**：合成小 bug 经真实 RFC、架构、实现、测试、评审、PR 和 merge 连续两次无人介入
   完成；至少一次覆盖 Reviewer REWORK 或小型 conflict recovery。不得使用正式实验题或 benchmark。

认证输出只保存脱敏客观证据：绑定 tuple、调用次数、解析结果、tool 名、commit/PR/merge SHA、测试命令退出
状态、token/耗时和失败分类，不保存 prompt、文件正文、命令参数中的凭证或普通模型思维文本。
`certification.json` 的内容 hash 写入实验 manifest。认证 tuple 任一项变化、真实套件未达门槛、证据缺失或
模型 endpoint 协议不匹配时，启用 delivery 的实验在 API 前拒绝启动。

### 7. 并行端到端验收

最终脚本为 `backend/scripts/e2e-spec-0047-parallel-experiment-runtime.sh`。离线层同时创建两个 fake/model-free
实验，断言所有路径、Compose project、容器 label、网络、卷、动态端口、Gitea repo/token、Vigil state、
日志和 checkpoint 不同；停止、恢复、归档其中一个时另一个状态不变；错误 label 和跨实验资源 ID 被拒绝。
真实层在认证通过后启动两个最小闭环，故意交错 issue、PR、日志和 stop/resume，断言不存在跨仓领票、跨卷
状态、跨日志写入或容量超售。测试结束默认保留失败现场；只有显式 test cleanup 对已记录的两个实验 ID 执行
精确销毁。

Task DAG 与文件所有权：

| Task | 责任 | 主要产物 |
|---|---|---|
| T1 | 完整运行时与认证契约 | 本 Spec |
| T2 | 配置、命名、manifest 和 journal | `experiment/config.py`、`manifest.py` |
| T3 | project-scoped Gitea/Runner/proxy/Vigil | experiment Compose、`infrastructure.py` |
| T4 | 生命周期 CLI 与现有闭环上下文化 | `runtime.py`、CLI、`run.py` 接线 |
| T5 | 跨实验模型容量和实验级故障保护 | `capacity.py`、`health.py` |
| T6 | 真实模型认证消费与双栈 E2E | certification、live/e2e 脚本与迁移说明 |

```text
T1 ─► T2 ─┬─► T3 ─► T4 ─┐
          └─► T5 ────────┼─► T6
               T3 ───────┘
```

## Drawbacks

默认每实验独立 Gitea、Runner 和 proxy 会增加容器数量、启动时间、磁盘 volume 与维护面；虽然镜像层共享，
长时间保留多个实验仍会消耗显著存储。动态端口降低冲突，却使人工访问地址必须从 status/manifest 获取，不能
再凭记忆使用固定 `localhost:3000`。

Experiment Runtime 本身成为新的基础设施组件。manifest、journal、Docker reconciliation、容量租约和归档
如果实现不严谨，会把过去显式的手工风险转化为隐蔽的平台风险，因此需要比普通 runner 更强的故障注入和
双栈验收。保留旧入口也会在一段时间内形成两条路径，必须明确 deprecated 边界。

真实模型认证会产生费用和时间，且模型本身非确定；连续三次角色 canary、两次完整交付不能证明未来永不
失败，只能证明精确组合达到最低工程契约。认证题过于简单可能漏掉长程问题，过于复杂又会成为另一个昂贵
benchmark。首版接受这个局限，以最小集成契约替代能力评测。

峰值容量预留偏保守，两个低负载实验可能因总预算不足不能同时启动；但它避免依赖瞬时平均值造成请求风暴。
模型 endpoint 仍是共同外部故障域，除非部署独立模型副本，否则并行结果不能宣称基础设施完全独立。

## Rationale and alternatives

选择“每实验独立基础设施栈”作为正式实验默认，而不是共享 Gitea 后只换 repo 名。共享 Gitea 的成本更低，
但 token 权限、Runner 队列、volume、服务重启和模型越界访问仍是共同故障域；它可以作为显式
`isolation: shared-dev` 的本地短 smoke 模式，不能用于论文或长期进化结果。

选择声明式 ExperimentConfig + 不可变 manifest + append-only journal，而不是继续维护每批 `run_*.py`
wrapper。wrapper 可以覆写常量，却无法形成统一碰撞检查、恢复、归档、销毁和来源证明；配置/manifest 把这些
要求变成可验证接口。没有选择直接重构为 Kubernetes operator：当前规模在单机 Docker，Compose project
已经提供足够的命名与网络边界，Kubernetes 会引入远高于需求的控制面。

选择动态宿主端口，而不是从实验 ID hash 计算固定端口。hash 仍可能与现存非实验服务碰撞，也需要中央注册；
让 Docker 分配并把实际端口写入 journal 更可靠。容器内部使用稳定 service alias，业务配置不依赖宿主端口。

选择“容量租约 + 既有客户端并发接线”，而不是首版实现透明模型代理。透明代理同时支持 OpenAI-compatible
和 Anthropic-compatible 流式协议、usage 与重试语义，容易改变被测请求。峰值租约虽保守，但不会触碰 payload，
更适合先建立实验隔离。未来如需细粒度调度，可在保持请求字节与调用顺序可证明不变后增加代理。

选择真实行为认证而不是扩大 mock 测试。mock 仍承担快速、确定性的默认回归；live suite 只在镜像/模型/
协议变更和正式实验启动前运行。断言面向 schema、Git、测试、PR 和 merge 等客观结果，不要求模型输出固定
文本，从而减少把随机措辞误判为失败。

## Prior art

Docker Compose project 原生以项目名隔离默认网络、容器和 named volume；本设计在其上增加 manifest 资源 ID
与自定义 label，防止仅凭 Compose 命名推断所有权。CI 系统常用 ephemeral environment/preview environment
为每个变更创建独立服务栈，实验运行时采用相同的生命周期思想，但默认保留失败现场和证据。

实验编排系统普遍区分声明配置、不可变 run manifest 和事件日志；作业调度器也通过资源 reservation/admission
control 防止并行任务超售共享加速器。认证 tuple 类似构建 provenance/attestation：只有精确源码、镜像、工具
和依赖组合通过规定测试，产物才可进入下一环境。

仓库现有隔离 Vigil 验证脚本已经证明独立容器名、fresh Gitea target 和只读配置挂载可行；现有做法仍共享
Gitea 服务、网络和运行目录。本设计将这些一次性验证技巧提升为全生命周期、默认强隔离的平台契约，并新增
双栈并发与真实模型稳定性门。

## Unresolved questions

首版只承诺 Linux/WSL Docker Engine；Windows 原生 Docker Desktop 的文件锁、动态端口和权限语义不作为正式
实验支持面。Runner job 镜像缓存是否做宿主级共享只影响性能；无论取舍，job writable layer 与网络必须保持
project-scoped。

模型 endpoint 的容量单位需要由部署 profile 显式标定。首版不根据历史延迟自动推断容量，也不允许运行时
自适应提高预算；形成足够 telemetry 后，再决定是否引入基于队列和延迟的动态 admission。若未来为每个实验
提供独立 GLM 副本，可以把 endpoint profile 标成 dedicated 并跳过全局竞争，但仍保留实验内并发上限。

OpenAgents live suite 的具体合成仓内容由其对应 Spec 确定，但必须保持小、公开、非 benchmark、无历史实验
答案，并固定版本。认证初版不设置按日期过期；精确 tuple 或 suite version 变化即失效。后续是否增加周期性
再认证由实际漂移数据决定。

## Future possibilities

运行时稳定后可以增加 Web 实验控制台，以同一只读 API 展示所有实验的状态、资源、模型租约、成本、错误保护、
Harness 谱系和认证情况；所有 mutation 仍走同一 runtime 命令，不在前端复制生命周期逻辑。

可增加资源配额与保留策略：按实验设置 CPU、内存、磁盘预算，archive 后自动压缩 Git/Gitea 证据，并在人工
批准后回收 volume。可把 manifest 和 certification 组合成可签名 provenance，供论文结果或跨机器复现实验
验证来源。

若单机并发达到瓶颈，ExperimentConfig、manifest、label 和状态机可以映射到远程 Docker host 或 Kubernetes
namespace；因为实验身份和资源接口已独立于当前 Compose 实现，迁移无需改变实验语义。模型容量租约也可演进
为真正的全局流式调度代理，但必须保持协议透明和逐实验审计。

更长期可以支持谱系级控制器：从同一 Harness v0 创建多条模型/Prompt/交付策略分支，自动比较每轮用户体感、
合并质量、token 和 wall-clock，并使用独立 holdout 评测；每个分支仍由本 Spec 的实验运行时提供隔离，避免
谱系控制逻辑重新接触 Docker/Gitea 细节。
