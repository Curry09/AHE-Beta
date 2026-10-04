---
number: "0081"
title: E2B 独立任务环境与 N8 交互对照
issue: 0
slug: e2b-task-environments
summary: 在统一入口冻结非代码输入、环境配方及任务来源，为 E2B 会话建立可核验的独立文件与服务环境，复用现有闭环并生成 N8 混合及全 direct 对照材料；local 明确拒绝不支持的环境。
tasks:
  - id: T1
    title: 当前任务及环境材料契约
    status: pending
    priority: P1
    tags: []
    depends-on:
      - 0080/T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/config.py
      - backend/auto_designer/experiment/schemas/task-package-v1.json
      - backend/auto_designer/experiment/environment.py
      - backend/auto_designer/experiment/materials.py
      - backend/tests/test_experiment_environment_config.py
      - backend/tests/test_experiment_environment_materials.py
    scope: 扩展真实 benchmark 来源和可选 environment v1；冻结 inputs/runtime lock/scripts/services/output 声明并校验后端能力。
    acceptance: 材料/hash/mode/目标冲突和访问角色完整校验；local/未知版本/答案及管理边界错误在 provider 或模型操作前拒绝；无 environment 旧任务身份不变。
  - id: T2
    title: 工作区进程与观测统一边界
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/runtime.py
      - backend/auto_designer/harness/launcher.py
      - backend/auto_designer/observations/publication.py
      - backend/tests/harness/test_launcher.py
      - backend/tests/user/sim/test_environment_runtime.py
      - backend/tests/observations/test_environment_collection.py
    scope: 以具体 runtime 进程句柄、staging/目录读取/终止边界接入 namespace；保留 Local/Docker 原实现及 Harness 黑盒协议。
    acceptance: JSONL/UTF-8 任意分块即时可见，stdout/stderr/EOF/interrupt/exit/timeout 正确；shell、文件、patch、观测和 Harness 使用同一环境，无旧路径回退。
  - id: T3
    title: E2B 所属任务根与服务管理
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/environments/__init__.py
      - backend/auto_designer/experiment/environments/registry.py
      - backend/auto_designer/experiment/environments/broker.py
      - backend/auto_designer/experiment/environments/namespace.py
      - backend/auto_designer/experiment/environments/services.py
      - backend/auto_designer/user/sim/sources/namespaced.py
      - backend/tests/test_environment_registry.py
      - backend/tests/test_environment_namespace.py
      - backend/tests/test_environment_services.py
    scope: root 管理固定环境操作；按 session/attempt 创建完整独立 mount/PID/network/root，降权执行、登记服务和管理 companion，提供有界收集及清理。
    acceptance: 同路径/同端口并发不串数据；任务看不到管理/其他任务/秘密材料；服务先就绪后运行、finalize 后收集，丢失或归属冲突停止，资源清理可对账。
  - id: T4
    title: 接入统一生命周期及当前归档
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/backends/e2b.py
      - backend/auto_designer/experiment/backends/e2b_bootstrap.py
      - backend/auto_designer/experiment/backends/e2b_template.py
      - backend/auto_designer/experiment/context.py
      - backend/auto_designer/experiment/workload.py
      - backend/auto_designer/experiment/runtime.py
      - backend/auto_designer/experiment/collection.py
      - backend/auto_designer/experiment/controllers/unified.py
      - backend/auto_designer/loop/orchestrator.py
      - backend/auto_designer/experiment/continuation/source.py
      - backend/auto_designer/experiment/continuation/export.py
      - backend/tests/test_experiment_environment_lifecycle.py
      - backend/tests/test_experiment_environment_continuation.py
    scope: prepare 检查实际 template 能力、生成 prepared workspace，controller 选择 runtime；资源 registry 贯通 stop/resume/collect/destroy 和 continuation。
    acceptance: 初始化/会话/服务/收集失败均有恢复证据，不重复完成会话；数据库/工作簿/输出在回收前保存；普通两后端、batch/grade 与旧冻结 run 保持合同。
  - id: T5
    title: 当前 N8 配对材料与双语启动教程
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T4
      - 0080/T4
    relates-to: []
    parallel: false
    files:
      - examples/task-environments/README.md
      - examples/task-environments/README.zh-CN.md
      - examples/task-environments/isolated-files/task.json
      - examples/task-environments/isolated-files/source/README.md
      - examples/task-environments/isolated-files/instruction.md
      - examples/task-environments/isolated-files/setup.sh
      - examples/task-environments/isolated-files/requirements.lock
      - examples/task-environments/isolated-files/runtime-lock.json
      - examples/task-environments/isolated-files/initialize.sh
      - examples/task-environments/isolated-files/verify.sh
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - docs/tutorials/n8-interaction-control.md
      - docs/tutorials/n8-interaction-control.zh-CN.md
      - docs/audits/unified-entry-capability-migration-20261003.md
      - CLAUDE.md
    scope: 恢复八项真实原始材料并构造仓外当前 pack；公开仅维护小型环境示例、来源和教程，给出 mixed/direct 当前配置及 batch、配对差异验收。
    acceptance: 源码/指令/环境/画像/初始 Harness/模型/策略相同，仅六个 interaction 及派生身份不同；通过公开 check，原始包不修改，历史大包和秘密不提交。
  - id: T6
    title: 环境与完整 N8 路径实测
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/scripts/e2e-spec-0081-e2b-task-environments.sh
      - backend/tests/test_experiment_environment_contract.py
      - backend/tests/test_n8_interaction_control.py
      - docs/validation/e2b-task-environments.md
      - .github/workflows/experiment-contract.yml
    scope: 完成离线错误边界、真实 E2B 隔离/服务/产物/恢复、八场景 readiness 和公开入口模型交互验收；区分探针、环境准备与正式五轮结果。
    acceptance: 八真实场景不换 toy 替代；至少两并发同路径/端口环境及有界实际交互、KV finalize/产物清理通过；未完成正式两组五轮不得标实验完成，测试/Ruff/spec 校验通过。
---

# 0081 · E2B 独立任务环境与 N8 交互对照

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

为当前任务包增加可选、版本化的环境声明，冻结任务来源、非代码输入、运行时配方、绝对路径、服务和产物清单。在 E2B 实验沙箱内由管理进程创建每个 session/attempt 所属的文件系统、PID 和网络环境，任务与 Harness 以非 root 执行，复用现有用户交互、恢复、需求交付和 Gitea.com 证据发布。

首个实际使用是 N8 混合交互及全 direct 两组：同一初始 Harness、任务与画像配对、模型、资源、服务和预算，只改变六个任务的 interaction。local 保持现有支持，对本组新增的隔离环境明确拒绝；不引入历史格式执行器、N8 特殊 controller 或第二个实验入口。

## Motivation

当前统一入口的任务包只支持 `ordinary`（要求显式声明非 benchmark）和 `swebench`；冻结源码、指令、Python setup 和 requirements。E2B 所有会话在同一个实验沙箱中运行，复制各自代码目录并重建 venv。它没有表达非代码文件、绝对 `/app` 路径、运行服务、独立端口或代码目录之外的产物。

原 N8 八场景包含两项 SWE、Terminal-Bench 排程与 KV 热替换、TUA Excel、NL2Repo TinyDB，以及 SQLFluff/Superset 机制任务。排程依赖三份数据库与 DB gateway，Excel 使用固定工作簿，KV 依赖被热替换的目标进程及独立负载生成器。修改任务的 interaction 字段不能恢复这些环境；将 benchmark 任务谎称 `not_in_benchmark=true` 也不是合法迁移。

仅把历史快照填进 `runtime.e2b.template` 仍不足：快照中的工作区可能已有上轮输出、正在运行的服务或旧 controller；多个会话共享 `/app`、端口和系统进程。prepare/run 必须验证并重新建立明确的初始环境，不能把“文件夹存在”当作任务准备成功。

2026-10-04 的独立短时探针确认：`ghl1296845690/n8-targeted-latest-harness-20260929:default` 标签存在，所选 build 为 `967ff8dc-1188-4a84-9498-c60bc1c36ebd`，观察到 template ID `t6wttai7asfxkpqot9l9`、4 CPU/8192 MiB。mount+PID、network namespace 及独立 `/app` 挂载均通过；八份 agent payload 均存在并记录哈希。探针没有恢复全部任务、验证服务或运行模型，沙箱已清理；这些结果只支持实现方案，不是 N8 实验验收。

## Guide-level explanation

继续使用 `backend/scripts/experiment.py check/prepare/run/status/stop/resume/collect/destroy`。普通源码/venv 任务无需新增字段，保留既有路径。需要独立系统环境的任务包增加 `environment`，示意如下：

```json
{
  "schema_version": 1,
  "kind": "benchmark",
  "id": "production-planning",
  "benchmark": {"suite": "Terminal-Bench", "instance_id": "production-planning"},
  "interaction": "direct",
  "environment": {
    "version": 1,
    "mode": "isolated-system",
    "workspace_path": "/opt/hse-run/workspaces/O09",
    "inputs": [
      {"id": "planning-data", "path": "./planning-data.tar.gz", "sha256": "<SHA256>", "target": "/app/data"}
    ],
    "runtime_lock": "./runtime-lock.json",
    "initialize_script": "./initialize.sh",
    "verify_script": "./verify.sh",
    "writable_paths": ["/app/output"],
    "services": [],
    "collect": [
      {"path": "/app/output", "name": "writebacks"},
      {"path": "/app/data", "name": "final-data"}
    ]
  }
}
```

此片段省略已有必填源码、指令与 setup，不是可直接运行的完整任务包。新 `benchmark` 种类保留真实来源，不能添加 `not_in_benchmark`，suite/instance 只作任务来源，不自动启用官方评分。普通机制材料仍声明真实非 benchmark 来源；两项 SWE 继续保持固定 Git revision 和现有评分接口。

环境检查分三层：`check --offline` 校验声明、输入与后端能力；`prepare` 冻结材料并验证一次性环境；正式会话从原始基线重新创建并记录 readiness。只有准备成功才能运行模型。服务未就绪、输入哈希错误、模板漂移或无法建立所需隔离时停止，不降级为共享目录执行。

原 N8 初始 Harness 为 `356dc344e2f2e02db8d765c7e003c39d7c859380`，从明确 archive 输入使用；不能以当前 builtin 替代。两组各五轮、每轮八个会话，共四次反馈交付，最后一轮只试用。八个有序配对使用原五张画像，排程/TinyDB 显式绑定 `sr-15-swyx`；画像复用由现有 slot/session 身份区分。

混合组保持六项 `simulated_user` 和排程/TinyDB 两项 direct；对照组八项均 direct。direct 保留终态 persona 评阅与现有报告行为，不能把报告数等同投诉数，也不把接受、feeling 或 shell exit code 当作官方任务通过。

## Reference-level explanation

### 1. 任务及环境契约

任务包仍由当前严格 schema 校验，新增 `kind=benchmark` 与必需来源对象 `benchmark={suite,instance_id}`。它与 ordinary 的非 benchmark 声明及 swebench 的 Git 元数据互斥；不携带 gold patch、grader/test payload、oracle 或评测答案。现有 official grade 仅处理 swebench，其他种类明确记录未支持，不伪造客观成绩。

`environment.version=1` 为独立环境配方版本，`mode=isolated-system` 首版只由 E2B 支持；未知版本、未知能力和 local 输入在 provider 操作前拒绝。普通任务不补环境默认字段，既有有效任务 digest/hash 不变；带环境的包通过已有 package/content hashes 参与身份。workspace contract 新能力显式区分，不能复用 `prebuilt` 状态伪装系统环境已准备。

inputs 是当前本地文件/安全归档；每项含唯一 id、固定 SHA-256、绝对目标和访问角色（默认任务可见；`management-only` 用于不向任务暴露的服务输入）。runtime lock 记录所需解释器、工具、库及实际可验证身份；initialize/verify 是冻结的受信任环境配方，不是模型工具或隐藏 grader。services 使用有界启动/就绪/终止声明；collect 是任务可见结果的有界白名单，不递归打包整个沙箱。

校验目标路径冲突、目录重叠、遍历、链接、特殊文件、管理根和环境资源边界。inputs、配方、runtime lock、service 配置和所有文件 inventory 均冻结到材料清单；修改任何内容会使校验失败。私有负载生成器数据保存为管理专用材料，不放进任务命名空间或普通用户观测包。

### 2. 分离 provider、环境与 Agent 编排

provider 仍拥有唯一实验沙箱、Gitea 仓与总体资源生命周期。新增 task environment 模块只负责具体 attempt 的创建、readiness、受限执行边界、服务、收集和回收；不理解 triage/synthesizer/Owner 或轮次交付，不新增任意 DAG/workflow 引擎。

统一 controller 根据经过验证的 prepared workspace kind 装配 runtime。需求与交付进程继续在原环境运行；只有任务、persona 的文件/命令工具及 Harness 进入对应 task runtime。直接与模拟交互共用同一个 runtime，禁止二者使用不同初始化或服务配方。

具体内部边界为 `prepare_environment(task)`、`open_attempt(bound_identity)`、`verify_attempt()`、`finalize_attempt()`、`collect_attempt()`、`close_attempt()`。准备身份是配方内容身份，执行身份是 run/config/task/session/attempt/nonce；不能用 persona ID、宿主路径或 PID 代替 session 身份。

### 3. E2B 管理进程及独立任务根

在沙箱的 root 管理层安装冻结的环境管理程序。它持有 root-owned 注册表及私有 Unix channel，只接受当前 manifest 中存在的任务和已经登记的 bound attempt；提供固定的环境操作，不接收任意 root 命令。任务的初始化和受声明限制的服务管理由此执行；模型命令始终在所属环境中降权运行。

每个 attempt 有独立 mount、PID、network namespace 与任务 root。先隔离 mount propagation，再建立新 `/app`、HOME、tmp、任务工作区、最小 `/dev` 和所属 `/proc`。只映射所需只读运行工具、选定任务源码/输入以及独立 Harness staging；不映射整个 controller/role-run、父实验材料、管理 socket、provider/Gitea 凭证、其他任务或祖先工作区。不以单独 bind-mount `/app` 冒充完整任务根隔离。

可写源码/数据库/工作簿由 pristine 输入逐 attempt 构造，不复制快照中未经核验的当前输出。原路径通过环境声明恢复，不改写任务指令成另一项任务。新 root 中使用的解释器、依赖及命令需与 runtime lock 匹配；历史 venv 不按目录存在就可信，也不强制所有任务改用当前 Python 3.12.13。管理进程核验原 seed 配方与实际 runtime，必要兼容变更记录在本次两组相同的配方中，不能宣称与历史运行逐字节等价。

网络由管理层创建所属 peer/egress 配置，固定端口属于 attempt 私有空间，不使用全局 host 网络规避冲突。记录命名空间、链接、服务与稳定进程句柄，清理时按归属操作；不执行按进程名全局 kill、全局网络删除或 blanket privileged 用户 shell。

### 4. 服务与 KV 负载生成器

服务声明有唯一 id、任务/管理 companion 的 placement、有序依赖、固定 argv、就绪探针、启动上限、日志和终止步骤。它只管理环境服务，不引入模型 subagent。

KV server 在目标任务环境中以用户身份运行，允许任务按原场景进行 ptrace/热替换；loadgen 在任务不可访问的独立管理侧进程与网络空间运行。两者经所属 peer 网络通信。目标任务不获得管理权限、服务源代码、负载原始结果或 grader。root-only 初始化负责系统配置，不能把 sudo 权限交给 persona/Harness。

readiness 核验输入二进制/版本、端口 9000/9001、负载 health、初始状态及隔离条件。finalize 使用冻结的测量收尾配方等待业务测量边界，并有明确上限；不能在 Harness 返回时立即杀负载并把未完成测量当作任务结果。结束后收集可声明的状态与日志，再停止所属服务。

### 5. Harness 进程与观测边界

`WorkspaceRuntime` 增加具体进程启动/终止及目录读取边界，launcher 不再以 `isinstance(DockerWorkspaceRuntime)` 判断唯一隔离执行形式。普通 Local/Docker 路径由原 subprocess/docker exec 实现；namespace runtime 由管理层提供所属环境的进程句柄与 stdin/stdout/stderr 通道。管理层掌握所属进程的启动、状态和信号；模型不掌握管理 channel。

`_HarnessHandle` 继续处理现有 stdio-jsonl-v1 和 legacy 协议，字节流必须边生成边读，不能先等命令结束再把完整输出返回。允许 JSONL 被拆为任意 chunk、UTF-8 跨 chunk、无换行进度、stderr 和 EOF；检查点、中断、退出和超时仍使用既有 request outcome 语义。错误的通道断开不算正常 reply。

Harness staging、执行 cwd、模型环境及 observation 目录由 runtime 明确映射；读文件、run_shell、patch export、persona 检查和 Harness 指向同一任务环境。观测 collection 使用该 runtime 的有界读取，不在宿主同名目录寻找证据。标准发布端和固定 OpenAgents reader 继续使用现有 Gitea.com ZIP/R2 合同，不需要两仓新增读取协议。

### 6. 产物、恢复与资源清理

环境注册表在副作用前记录创建意图，关联 run/config/session/attempt/task digest/recipe/nonce、namespace/process/service identities 和状态。异常后对账登记资源，不凭路径存在直接复用，也不把失去资源的 attempt 宣称仍在运行。

每局 finalize 后、close 前，将白名单中的输出文件、最终数据库/工作簿、patch、readiness/finalization/service 日志及清理 receipt 保存到 `runtime/task-artifacts/<session>/<attempt>/`，有路径、mode、bytes、hash 和截断/缺失原因。管理数据与用户结果按访问角色区分；隐藏评分数据不进入 Session 或需求/交付证据。收集失败明确保留可诊断状态，不先删根目录再声称完整。

恢复复用已完成 Session 与 receipt，不重发报告；中断尝试先核对并收集/终止旧所属资源，再按现有 recovery attempt 语义从 pristine seed 创建新 attempt，不从上次写坏的 `/app` 继续。不能在仍存活的 KV 任务上隐式 reset 服务。完成用户 stage 与 round seal 仍由既有 Orchestrator 判定。

stop/destroy 管理所属 namespace、服务、peer 与子进程；无法证明清理成功时保留失败记录并停止后续会话。资源统计与 collect 包含环境状态及 task-artifacts；自动销毁实验 compute 前检查所有执行资源和收集状态，保留 Gitea 仓及冻结原始输入。旧已准备 run 用原 controller 和资源合同，不进行升级或历史格式导入。

continuation export/source 保留环境材料、runtime 身份和新的 workspace 能力；旧环境外形不变。子 run 继承完整环境配方及 task/persona/interaction，不把管理私密数据映射成用户可见输入。离线任务 grading、批量调度仍使用现有入口和本地轮号。

### 7. N8 材料与配对审计

八份 agent payload 的原始 hash、固定任务指令、公开 case/candidate、数据库、工作簿和所需管理服务材料分别核验；grader payload 不用作初始化。只提取显式选定的任务输入，不让 agent archive 原始内容整体在任务根中可读。提取和过滤保留来源 inventory/hash，不改原输入文件；发现答案或不可重建的基线则拒绝准备，不用 toy 任务替代。

私有实验 pack 存在仓外，分别给出当前 task-package-v1、环境 inputs/locks/scripts、原始 Harness archive、画像库、两份 schema-2 experiment 和 batch JSON。公开仓库仅放明确可发布的小型环境示例及材料说明，不把历史大包散落进 examples，不包含机器绝对开发路径。

两组固定相同五轮、每轮八个 slot、max_parallel_users、role roster、grouping、delivery coordination/并发、model/API 配置、reasoning/timing 和任务预算。默认建议两组均使用 `glm-5.3`；这与历史 user/Harness 的 `glm-5.3-flash` 不同，正式分析以本次配对重跑为因果对照，历史五轮只作参考。初始 Harness、源码/指令/环境/画像与运行策略的哈希必须相同；仅六个 interaction 字段、派生 task/catalog/plan/session 身份及 run/resource 坐标可不同。审批后的启动仍使用 check→prepare→run，无专用 N8 launcher。

### 8. Task DAG 与验收

六个任务分别负责包/材料契约、运行边界、E2B 环境管理、统一生命周期、材料/教程及实际验收。画像复用与现有执行身份的方案在完整场景前完成；文件分配与跨组依赖列于 frontmatter。端到端脚本为 `backend/scripts/e2e-spec-0081-e2b-task-environments.sh`。

| 验收 | 必须观察的结果 |
| --- | --- |
| 旧行为 | 未带 environment 的 N1/N4 task/config/hash 和两后端路径保持原合同，旧冻结 run 不升级 |
| 能力检查 | local/未知环境/材料损坏在模型和 provider 操作前拒绝，不能声称 offline 已验证 namespace |
| 独立根与端口 | 两并发 attempt 使用相同 `/app` 路径及端口，写文件/数据库/运行服务互不影响；用户看不到其他 slot、管理根或隐私数据 |
| N8 初始化 | 八个真实环境分别验证 source/runtime/files/services，original SHA/inventory 与 receipt 一致，不从上轮输出构建基线 |
| 流与控制 | 实际 stdio JSONL 跨 chunk、长时间无工具、stderr、EOF、interrupt、进程退出均正确；不等待整段执行后回放 |
| 服务收尾 | KV 有独立 loadgen、正确初始版本与就绪证据，finalize 不丢测量，失败与清理有可核验原因 |
| 非代码产物 | 真实数据库、工作簿和 `/app/output` 被收集并保留 bytes/hash；销毁执行根后仍可检查 |
| 恢复 | 初始化半完成、Harness 中断、服务收尾与收集失败后重试，既有完成 Session 不重跑；资源归属不明则停止 |
| 继承 | 含环境的完整当前归档可继承，输入不变且父管理数据不变成子可见材料 |
| 两组配对 | 本次 mixed/direct 只改变 interaction 与派生身份，分别有合法当前配置及八个有序配对；未实跑不能标实验完成 |

## Drawbacks

系统环境适配需要管理进程、隔离能力及服务收尾，比普通目录/venv 任务复杂。选择可选契约及独立模块，复杂度不进入需求角色或一般用户流程。

E2B 中 namespace 能力依赖实际 template/kernel，必须实际探测，不承诺任意模板都支持。资源仍是一个实验沙箱的 CPU/内存共享；不能将 namespace 描述为独立 E2B VM 或任意恶意代码隔离保证。

当前实现边界仅 E2B；local 富系统环境后续需要独立 Docker/companion 配方，不能复制 E2B root 管理实现进去。初次材料构造有成本，但比反复手改旧脚本更可验证和可复用。

## Rationale and alternatives

选择版本化 task environment 和 E2B 所属 namespace：原场景的文件、服务和测量有显式合同，同时仍只有一个实验 provider 与现有 Agent 编排。实际快照能力探针支持此路径，正式环境完整验收仍必需。

不只放开 task kind 并共享 `/app`。串行会话也不能自动保证 pristine 基线、正确服务状态、任务隐私与结果保留；串行化不是环境适配。

不为每个 task/session 再创建一个 E2B VM。此方案可行但增加 provider 资源、费用、跨沙箱 stdio streaming、证据下载和 LOST 对账面；现有快照已支持 namespace，因此首版不增加另一套云任务调度。

不把旧 tasks.json、固定路径或历史 continuation 脚本嵌入当前 controller。历史数据只用于明确构造当前材料，公开执行始终消费一个严格任务/环境契约，不分 N8 特殊分支。

不将所有任务重写成 ordinary，亦不通过更换 persona、替换 toy 工作区或将终态报告当作官方通过绕过验证。

## Prior art

当前 WorkspaceRuntime 已提供文件、shell、staging、patch 和清理边界，Docker 路径已有隔离会话容器；prebuilt 有 attempt identity、nonce 和有界 setup。E2BBackend 已分离 root 管理与 non-root controller，并核验 provider 身份和 LOST 状态。现有 observation collector 和 Gitea.com 发布/读取合同可复用。

历史 N8 的 task environment 检查包含 workbook hash、三份数据库、KV/loadgen readiness、public case/candidate 和用户权限，其 reset 脚本展示了非代码数据与服务基线的重要性。本组把所需事实纳入当前配方与独立资源归属，不转调该旧脚本。

## Unresolved questions

用户已选择首版补齐 E2B + Gitea.com 的完整 N8 路径，local 对不支持环境明确拒绝。交互两组的正式模型、并发和预算将在当前实验配置中冻结；启动前展示完整配对差异，不用历史不一致模型配置冒充严格对照。

原始公开输入可读性、runtime lock、KV 完整测量和 namespace egress 的实际验收必须在实施中完成。若有一项无法建立，不扩大权限或替换任务规避；修订本设计并报告真实缺口。当前短时探针不能预先把这些事项标为已通过。

## Future possibilities

后续可按同一任务环境声明实现 local Docker 及 companion，或在不同需求下实现独立 E2B task VM。其他 benchmark 的评分仍是独立事后适配器；不在本组自动把环境准备、用户评阅或服务日志转为官方评估结论。

