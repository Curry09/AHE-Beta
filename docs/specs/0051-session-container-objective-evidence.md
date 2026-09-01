---
number: "0051"
title: 会话容器隔离与客观验收证据
issue: 0
slug: session-container-objective-evidence
summary: 每个用户会话从可运行 seed image 启动独立容器；persona 与 harness 只在容器工作区执行；超时回收整个容器执行边界；主观接受与新鲜 SWE-bench 客观执行结果分栏落盘，假接受不得计为通过。
tasks:
  - id: T1
    title: 隔离与验收契约
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0051-session-container-objective-evidence.md
    scope: 冻结每会话容器、超时回收、双结论与证据字段，明确旧实验不可追溯修补。
    acceptance: 九段 RFC 完整；容器生命周期、客观判定、审计最小字段和失败闭合规则均明确。
  - id: T2
    title: 会话运行时与容器 seed
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/runtime.py
      - backend/auto_designer/user/sim/workspace.py
      - backend/auto_designer/user/sim/seed_source.py
      - backend/auto_designer/user/sim/sources/docker_seed.py
      - backend/auto_designer/user/sim/deps.py
      - backend/auto_designer/user/sim/sandbox.py
      - backend/auto_designer/user/sim/tools.py
      - backend/tests/user/sim/test_docker_seed_source.py
      - backend/tests/user/sim/test_workspace_runtime.py
      - backend/scripts/prepare_swebench_runtime_tree.py
    scope: 以显式 WorkspaceRuntime 取代 docker cp 到宿主；docker-seed 每次 provision 创建独立容器，读写与命令均通过容器运行时。
    acceptance: docker-seed 不执行 docker cp 导出 repo；两个 provision 返回不同容器；路径逃逸被拒；命令超时会使运行时进入污染态并可被回收。
  - id: T3
    title: harness 容器执行与强制终止
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/harness/launcher.py
      - backend/harness_template/entry.py
      - backend/auto_designer/loop/orchestrator.py
      - backend/auto_designer/loop/sim_user.py
      - backend/auto_designer/user/sim/persona_client.py
      - backend/tests/harness/test_launcher.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_sim_user.py
    scope: launcher 对容器运行时用 docker exec 启 harness；编排 finally 关闭会话容器；wire reply 带 completed/timed_out/interrupted/crashed，超时后销毁执行边界。
    acceptance: harness 与 persona 看到同一容器 cwd；超时状态结构化可读且旧工作线程不能继续；异常路径也清理容器。
  - id: T4
    title: 双结论、客观执行与假接受
    status: done
    priority: P0
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/evaluation/swebench.py
      - backend/auto_designer/evaluation/__init__.py
      - backend/auto_designer/models.py
      - backend/auto_designer/user/session_store.py
      - backend/auto_designer/user/sim/loop.py
      - backend/tests/evaluation/test_swebench.py
      - backend/tests/user/test_session_store.py
      - backend/tests/user/sim/test_loop.py
      - backend/tests/test_models.py
      - pyproject.toml
    scope: 保留 persona end_reason，同时在新鲜官方实例容器执行 canonical evaluator 并落 stdout/stderr/exit/hash；派生 valid_accept/false_accept/unverified_accept。
    acceptance: 超时后 accept 必为 false_accept；未配置 evaluator 必为 unverified_accept；只有 fresh evaluator passed 才是 valid_accept；索引默认不把假接受当通过。
  - id: T5
    title: 可运行镜像、一键入口与审计冒烟
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/deploy/swebench-seed/Dockerfile
      - backend/deploy/swebench-seed/runtime.Dockerfile
      - backend/scripts/build_swebench_runtime_image.sh
      - backend/scripts/run_auditable_experiment.py
      - backend/scripts/run_swebench_closed_loop.py
      - backend/scripts/e2e-spec-0051-session-container.sh
      - CLAUDE.md
    scope: 提供从现有 seed 资产构建可运行镜像的入口，并让一键实验 fail-closed 校验 image；用冒烟脚本证明无宿主工作区泄漏、结果证据可追溯。
    acceptance: 一键入口启动前检查 runnable image 标签/协议；e2e 不访问真实 LLM，验证容器名、diff hash、请求结果和客观判定落盘。
---

# 0051 · 会话容器隔离与客观验收证据

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

SWE-bench 用户会话不再把 seed image 中的仓库 `docker cp` 到 WSL/宿主临时目录后执行。每一局从同一个**可运行** seed image 创建一个独立容器；harness、persona 的 `read_file`/`run_shell` 和依赖准备都只通过该容器访问 `/workspace/<instance_id>/repo`。同一轮可并行 16 个容器，镜像只存一份，容器各有自己的可写层。

用户是否接受仍是产品体验结论，不能冒充题目通过。会话结束后只导出 git diff，并在一个新鲜的官方 SWE-bench instance image 中应用 diff、执行 canonical evaluator。落盘同时保存 `user_outcome`、`objective_evaluation` 与派生的 `accept_validity`；超时、崩溃、缺 evaluator 或客观失败均不得成为 `valid_accept`。

审计不是给 persona 看，而是给实验操作者、复核者及以后写报告的人看：他们应能从 session JSON 还原“哪个容器、哪次请求、何时超时、导出了什么 diff、客观命令返回什么”。本组只做最小证据链，不建设通用合规日志平台。

## Motivation

0044 把 seed image 定义成 `FROM scratch` 的存储包，并明确选择 `docker create → docker cp → docker rm`。随后 orchestrator 把得到的宿主绝对路径同时传给 harness 和 persona；harness 又是宿主 Python 子进程，persona sandbox 也是宿主 `subprocess`。所以用户能看到 `/mnt/c/Users/.../Temp/sim_ws_docker_seed_*` 不是 Docker 逃逸，而是实现从未把执行放进容器。

另一条错误是把“用户愿意接受”当成“实现已经通过”。现有状态机允许 final check 失败或不可用后继续 accept；harness 的 240 秒超时只放弃 daemon thread，旧工作可能继续写盘；accept 的说明文字还会被投影成一条实际发送给 harness 的 user turn。结果是 `sr-12-steinberger` 一类会话在测试超时后仍说“verified / Done”，产生假接受和不可审计的成功率。

之前已跑的数据不能事后补成可信数据：其执行边界、超时后的写入和接受依据已经丢失。本组只保证新 session 的证据完整，旧 run 保留原样并标记为历史无效实验。

## Guide-level explanation

一局的生命周期固定为：

1. `docker-seed` 校验 image 带有 runnable 协议标签，为该 session 创建唯一命名容器并启动；工作目录是容器内 `/workspace/<instance_id>/repo`。
2. persona 工具经 `WorkspaceRuntime` 读写/执行；harness checkout 作为只读输入复制进容器的 `/opt/auto-designer/harness/<sha>`，随后由 `docker exec -i` 启动。不得把 repo 导出成宿主工作目录。
3. 每个 harness reply 带机器状态：`completed | timed_out | interrupted | crashed`。`timed_out`/无法确认终止时，立即停止并删除整个会话容器；该 session 不再续聊，避免旧线程继续修改可写层。
4. 正常结束时从会话容器导出 `git diff --binary` 文本及 SHA-256；随后删除会话容器。
5. evaluator 从对应的官方 SWE-bench instance image 启动**新容器**，应用 diff 并运行 canonical eval 命令。交互容器里的依赖、未跟踪进程和测试缓存不带入验收。
6. session 同时展示主观与客观两栏。persona accept 但客观失败/交互超时是 `false_accept`；未执行官方 evaluator 是 `unverified_accept`；只有 fresh evaluator 明确通过才是 `valid_accept`。

实验仍用一键入口，但启动前必须 fail-closed 检查 runnable image。配置了 16 并发时是最多 16 个会话容器，不是 16 份镜像；五轮按 session 生命周期累计最多 80 次创建/销毁。

## Reference-level explanation

### 运行时协议

`WorkspaceRuntime` 是消费侧唯一接缝：`cwd`、`read_text`、`write_text`、`run`、`export_patch`、`close`。本地 fixture 由 `LocalWorkspaceRuntime` 包装以保持开发/单测兼容；`docker-seed` 返回 `DockerWorkspaceRuntime`，不再返回 `str`。任何需要 cwd 的调用点必须消费该协议，不得用 `Path(runtime)` 或宿主 `open()` 绕过。

容器创建须使用：唯一 session 名、`--label auto-designer.session=<id>`、非特权、无宿主 bind mount、工作目录为 repo。网络默认 `none`；正式 GLM 实验由 runner 显式配置 bridge 以访问 `172.22.64.1` 网关，后续可收紧为 egress allowlist。镜像标签 `org.auto-designer.seed-runtime=1` 是可运行契约；存储型旧镜像没有标签，启动即失败并提示重建，不能静默回退到 `docker cp`。

### 终止语义

wire v1 的 terminal reply 增加 `status`。launcher 将最近请求结果记录为 `{request_id,status,started_at,finished_at}`。`timed_out` 与 `crashed` 是 session 级污染：不允许 rebuild 后继续对话，不允许接受；orchestrator `finally` 关闭 runtime。宿主等待的绝对上限触发时同样杀容器，而非只杀 `docker exec` 客户端。

### 双结论

落盘字段：

| 字段 | 含义 |
|---|---|
| `user_outcome` | persona 的 `end_reason` 与 terminal note；仅主观体验 |
| `request_outcomes` | 每次 harness 请求的 id、状态、UTC 起止时间 |
| `workspace_evidence` | image digest、container id/name、workspace、diff SHA-256 |
| `objective_evaluation` | evaluator、fresh image digest、命令、exit code、stdout/stderr、UTC、passed |
| `accept_validity` | `valid_accept / false_accept / unverified_accept / not_applicable` |

派生函数是 fail-closed 的纯函数：非 accept → `not_applicable`；accept 且任一请求超时/崩溃 → `false_accept`；无完整客观结果 → `unverified_accept`；`passed=false` → `false_accept`；只有 `fresh=true && passed=true` → `valid_accept`。index 保留体验评分，但通过率消费者只数 `valid_accept`。

accept 动作的 `message` 政名义为 `terminal_note`，不路由给 harness，也不投影为 transcript 的 user turn。

### 客观 evaluator

适配器只接受 argv，不经 shell；它为单个 patch 生成官方 prediction JSONL，调用 `swebench.harness.run_evaluation`。官方 runner 自行创建新 instance 容器、应用 patch/test patch 并执行 canonical eval script；本系统保留其 `results.json`、退出码与限长输出。官方 evaluator 或 image 缺失时返回 `unavailable`，不得以 persona 自跑的 pytest 替代。

### 最小审计

session JSON 是权威载体；事件按单调 `seq` 排序且用 UTC wall-clock，不使用进程局部 monotonic 作为跨进程时间。必须记录容器 start/stop、harness request terminal、patch export、evaluation terminal。正文可截断，但 hash、退出码、状态和时间不可省略。

### Task DAG

```mermaid
flowchart TD
  T1[契约] --> T2[WorkspaceRuntime]
  T2 --> T3[容器 harness 与终止]
  T3 --> T4[客观验收与双结论]
  T4 --> T5[镜像与一键 e2e]
```

## Drawbacks

可运行 image 比存储型 scratch image 多一套 Python、shell、git 与 NexAU runtime，镜像增大；16 个并发容器还会各自占用进程 RSS 和可写层。代价是执行边界真实存在。镜像层共享，所以不是把 2–5 GB 镜像复制 16 次。

超时后整局终止会损失尚未导出的修改，也不能“再问一句”。这是刻意的 fail-closed：一旦旧线程是否仍会写盘不可证明，该工作区便不再能作为审计证据。

官方 fresh evaluation 增加一次容器启动和测试时间。它与 persona 的快速核实不能合并，因为二者回答的问题不同。

## Rationale and alternatives

选择每 session 一个容器，而不是每轮一个共享容器：共享容器的 cwd、进程、缓存和未跟踪文件会跨 16 个任务互相污染，无法把 diff 与一次会话对应。选择一个 seed image 多次起容器，而不是复制 16 份 image：Docker 的只读层本来就共享。

选择显式 runtime 对象，而不是继续传 `workspace_dir: str` 再靠调用方判断路径前缀：字符串无法表达生命周期、远端执行和污染态，迟早会被 `open()` 或 `subprocess(cwd=...)` 绕回宿主。

选择“主观 + 客观并列”，而不是禁止用户在测试失败后 accept：用户可以因为体验、时间或信任选择接受，这是有效产品信号；错误只在于把它计成技术通过。也不采用“persona 自己跑 pytest 就算客观”，因为它可能选择错测试、使用被污染环境或在超时后误判。

选择最小事件证据而非哈希链/WORM 存储：当前目标是可复核实验，不是对抗能修改整个实验目录的恶意管理员。若以后需要合规防篡改，可在不改字段语义的前提下追加签名链。

## Prior art

SWE-bench 官方 harness 以 instance 为单位构建/启动 Docker image，在容器内应用候选 patch 和 test patch，并根据 FAIL_TO_PASS/PASS_TO_PASS 解析结果。它的关键性质是“每个候选在新鲜实例环境客观执行”，本组将这个性质保留为交互后的独立阶段。

容器编排中的 disposable worker、Kubernetes Job 以及 CI 的 ephemeral runner 都把一次不可信执行绑定到一个可整体回收的进程命名空间；只终止宿主等待线程不等价于终止任务。

## Unresolved questions

无阻塞问题。操作者已确定：使用做好的 image 起 Docker；persona 保留直接查看工作区的能力；主观接受与客观执行结果都保留；审计先做最小可复核证据。

正式 16×5 重跑前仍需构建新的 runnable seed image。旧的 `auto-designer-seed:swebench-medium-hard-16` 是 storage-only，按本 spec 必须被启动检查拒绝，而不是兼容运行。

## Future possibilities

把容器资源上限按 repo 历史峰值自动分档；将网络从 `none` 扩展为只允许 GLM 网关的 egress allowlist；客观 evaluator 直接接官方 SWE-bench Python API 并产官方 prediction/report 目录；将 session 证据签名并生成整轮 manifest；失败后保留可选的只读 forensic snapshot，但不得让它继续参与会话或验收。
