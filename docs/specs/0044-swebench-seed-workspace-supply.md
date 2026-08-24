---
number: "0044"
title: 可复用 SWE-bench Seed 工作区供给
issue: 0
slug: swebench-seed-workspace-supply
summary: 以显式 manifest、可恢复构建状态、prebuilt 与 storage-only Docker 镜像，为并发用户会话提供隔离且可审计的预构建工作区；闭环按题归属并保留 git 回退路径。
tasks:
  - id: T1
    title: Manifest 与供给契约
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0044-swebench-seed-workspace-supply.md
      - backend/swebench_pools/medium_hard_16.json
    scope: 定义题池 manifest、instance_id 唯一性、难度元数据核验、存储边界与实例归属；具体题目集合是可替换实验配置，不是产品规则。
    acceptance: Spec 九段完整；manifest 非空、instance_id 唯一且与权威数据集难度一致；spec validate/render/graph 通过。
  - id: T2
    title: Prebuilt 隔离复制与虚拟环境迁移
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/sources/prebuilt.py
      - backend/tests/user/sim/test_prebuilt_source.py
    scope: 从显式目录复制每局独立工作区，跳过陈旧虚拟环境备份，并将可安全识别的 venv 文本元数据从构建路径迁移到会话路径。
    acceptance: 源缺失显式失败；两次供给互不污染；原 workspace 不修改；venv 文本引用完成迁移；相关 pytest 与 ruff 通过。
  - id: T3
    title: Storage-only Docker seed 供给
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/user/sim/sources/docker_seed.py
      - backend/deploy/swebench-seed/Dockerfile
      - backend/deploy/swebench-seed/build.sh
      - backend/tests/user/sim/test_docker_seed_source.py
    scope: 构建不含执行入口的 storage-only 镜像；每次 provision 通过临时容器仅复制指定 instance workspace 与构建状态，校验安全 instance id，并在所有路径回收容器。
    acceptance: 缺 image/instance、非法路径段、镜像/实例缺失均显式失败；成功复制后迁移 venv；临时容器必回收；测试、ruff 与镜像结构验证通过。
  - id: T4
    title: 可恢复批量构建与镜像校验
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/scripts/build_swebench_seed_workspaces.py
      - backend/scripts/validate_swebench_seed_image.py
      - backend/tests/test_swebench_seed_builder.py
    scope: 按 manifest 增量准备 source/dependency 两阶段工作区，原子写构建状态并支持单实例恢复；parquet 路径必须由参数或环境显式提供；校验器逐实例提取并执行结构、venv 与 import 检查。
    acceptance: validate-only 不构建；已完成阶段可恢复跳过；失败状态可审计；无本机绝对路径默认值；镜像中所有 manifest 实例均通过校验；脚本测试与 ruff 通过。
  - id: T5
    title: 闭环题池选择与稳定实例归属
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/scripts/run_swebench_closed_loop.py
      - backend/auto_designer/loop/sim_user.py
      - backend/tests/loop/test_sim_user.py
      - backend/tests/test_run_swebench_closed_loop.py
    scope: 闭环支持 manifest、单题冒烟和每轮全题一次；按固定 seed 产生可复现计划；prebuilt/docker-seed/git 三种路径均把 instance_id 带入会话与 usage 上下文，缺 seed 时保留 git 供给。
    acceptance: 非法单题拒绝；全题模式每轮各实例恰好一次且 persona 确定性轮转；三种 source 均保留 instance_id；并发 session 不串题；相关 pytest 与 ruff 通过。
---

# 0044 · 可复用 SWE-bench Seed 工作区供给

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

为需要真实历史仓库与依赖环境的用户模拟预先构建工作区，并以两种可替换供给方式交给每个 session：
`prebuilt` 从宿主缓存复制，`docker-seed` 从只存储文件的镜像提取。每次供给仍产生独立目录，虚拟环境中
可识别的旧绝对路径在复制后迁移，不允许多个 session 共享可写工作区。

题池由显式 manifest 定义并与权威 SWE-bench Verified parquet 核对；parquet、输出目录和镜像名均由 CLI
或环境显式指定，不固化个人目录。构建器按 source 与 dependency 两阶段保存可恢复状态，镜像校验器逐题
提取验证。闭环可以选择 manifest、单题冒烟或每轮全量覆盖，并在所有供给路径保留 `instance_id`，供
session、usage 与实验结果审计。具体 16 题只是当前实验配置，不进入角色 Prompt 或产品判断规则。

## Motivation

直接在每个用户 session 内 clone 历史仓库并安装依赖会重复消耗网络、时间和存储写放大，也会让并发会话在
环境准备阶段阻塞。SWE-bench 历史快照还可能依赖已变化的构建工具；实时安装的结果随镜像源与发布日期
漂移，难以复现实验。

单纯复用同一目录又会破坏隔离：用户或 harness 的写入会影响后续题目，editable virtualenv 还会把构建机
绝对路径带入新会话。将整个可执行服务烘进题目镜像则扩大信任边界，并把运行时编排与实验数据绑定。
因此本组只预构建文件资产，运行进程仍由既有 harness launcher 创建；seed 是供给优化，不改变
`WorkspaceSpec -> directory` 的消费契约，也不替代 git source 回退路径。

## Guide-level explanation

操作者先选择 manifest 和对应 Verified parquet，执行 source-only 检查下载与存储，再按需打开依赖构建：

```text
manifest + verified parquet
          │ 核对 instance / difficulty
          ▼
build_swebench_seed_workspaces.py
          ├─ source prepared
          ├─ dependencies prepared
          └─ build-state.json（逐实例、可恢复）
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       宿主 prebuilt cache    storage-only image
              │                     │ docker create/cp/rm
              └──────────┬──────────┘
                         ▼
                 session 独立 repo 目录
                         │
                 relocate editable venv
```

`SWEBENCH_SEED_ROOT` 选择宿主 prebuilt，`SWEBENCH_SEED_IMAGE` 选择镜像；均未设置时沿用 git source。
`SWEBENCH_INSTANCE_FILE` 指定题池，`SWEBENCH_INSTANCE` 选择单题，`SWEBENCH_ALL_ONCE` 使每轮将题池
各运行一次。固定 `SESSION_SEED` 时，题目顺序与 persona 轮转可复现。无论使用何种 source，
`workspace.params.instance_id` 都进入 session usage context。

## Reference-level explanation

manifest 至少包含非空且唯一的 `instances[].instance_id`，并保存难度与可选主题等实验分层元数据。构建器
从 parquet 读取 repo、base commit、problem statement 与 difficulty；manifest 难度与数据集不一致时
fail closed。parquet 路径只能经 `--parquet` 或 `SWEBENCH_PARQUET` 提供。

构建输出为 `workspace/<instance_id>/repo` 与 `build-state.json`。状态按实例记录 source/dependency 阶段、
原始构建路径、仓库和空间信息，并通过临时文件替换原子更新。失败不删除已成功阶段，重跑只继续未完成
工作。依赖兼容参数属于当前 manifest 的构建 profile，不进入用户、设计或交付角色上下文。

`PrebuiltSource` 使用 `copytree` 创建新目录，跳过 `.venv.stale-*`，只在 venv 的已知文本元数据与脚本中
替换旧根路径。它不修改源缓存，也不扫描产品仓任意文件。`DockerSeedSource` 要求 image 与安全的单路径段
instance id；以 `docker create` 建临时容器，读取 `/build-state.json` 验证实例后复制
`/workspace/<instance>/repo`，并在 `finally` 中回收容器。镜像 `FROM scratch`，无入口和执行工具，仅作为
可寻址文件载体。

闭环的题池选择在进程启动时完成。单题必须属于当前 pool；all-once 每轮复制并洗牌 instance 列表，persona
按轮偏移确定性分配。普通模式维持有放回抽样。session 在运行前生成 id，并从 WorkspaceSpec 读取
instance id；因此用户与 harness usage 共享题目归属，而不同并发 session 仍由独立 context 隔离。

## Drawbacks

预构建依赖占用可观存储，storage-only 镜像不会自动去重所有文件内容；构建 profile 也需要随基础 Python、
包索引和历史项目兼容性维护。复制完整 virtualenv 比共享只读层慢，但换取了 session 写隔离和明确回收。
Docker 供给依赖本机 daemon，无法使用 Docker 时只能选择宿主 prebuilt 或 git 回退。

## Rationale and alternatives

选择“文件资产镜像 + 每局复制”，而不是在镜像内运行 harness：后者会改变既有 launcher、sandbox 和 stdio
协议，并将题目环境提升为新的执行信任边界。选择可恢复的逐实例状态，而不是一次性大脚本：16 题依赖构建
耗时长，网络或单题失败不应使已完成资产失效。

未选择共享可写缓存，因为它会导致跨 session 污染；未选择将 parquet 放进仓库，因为它体积大且属于外部
权威数据；未选择从文本或 instance id 推断难度，manifest 必须与数据集字段核对。具体依赖 pin 保留在 seed
builder，而不进入通用 SeedSource 接口。

## Prior art

Spec 0008/0009 已建立 `WorkspaceSpec`、SeedSource 注册和每局物化目录；本组新增两种 source，不改变消费
港口。Spec 0017 已要求并发 session 工作区隔离。Spec 0041 使用 `workspace.params.instance_id` 做 Token
归属，本组负责在三种 SWE-bench source 中稳定提供该元数据。容器镜像作为离线文件载体与 Docker
multi-stage/cache export 的思想相近，但本组刻意不在镜像中执行目标项目。

## Unresolved questions

当前没有统一的内容寻址去重层；不同题目共享的大型 wheel 或 site-packages 是否值得抽成只读基础层，需要以
实际存储收益和复制成本评估。依赖构建 profile 目前由脚本维护，未来是否拆为 manifest 外部的版本化 profile
文件，也需在题池扩展后决定。本组不承诺跨 CPU 架构复用已构建 virtualenv。

## Future possibilities

后续可以为 build-state 增加源 commit、构建工具与镜像 digest 的完整 provenance，提供只读 layer 加 copy-on-
write 工作区，或将 seed 校验接入离线 CI。题池可替换为其他 benchmark manifest，只要继续满足唯一实例 id、
权威元数据核对和独立工作区契约；角色 Prompt 与产品设计流程不应感知 benchmark 名称或题目内容。
