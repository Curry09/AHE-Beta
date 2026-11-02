---
number: "0077"
title: 本地工程 CI runner 生命周期
issue: 0
slug: local-engineering-ci
summary: 可选启用本地实验专属 Gitea Actions runner，核验就绪后才开启 OpenAgents CI 门禁，并纳入资源所有权和清理。
tasks:
  - id: T1
    title: 配置材料与环境门控
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/schemas/experiment-v2.json
      - backend/ahe_beta/experiment/config.py
      - backend/ahe_beta/experiment/materials.py
      - backend/ahe_beta/experiment/context.py
      - backend/tests/test_experiment_ci_config.py
    scope: 可选本地CI配置、工作流预检查、只接受核验收据的CI环境
    acceptance: 默认关闭兼容旧哈希；E2B拒绝；缺工作流或错收据不能启动CI门
  - id: T2
    title: 专属 runner 与执行生命周期
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/backends/local_ci.py
      - backend/ahe_beta/experiment/backends/local.py
      - backend/ahe_beta/experiment/infrastructure.py
      - backend/deploy/experiment/docker-compose.yml
      - backend/tests/test_experiment_local_ci.py
    scope: 固定镜像、Compose、注册、真实PR探针、身份校验及停止恢复清理
    acceptance: 真实当前head成功才ready；失败保留诊断；不清理其他实验资源；恢复不重注册
  - id: T3
    title: 双语工程 CI 使用文档
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/tutorials/local-engineering-ci.md
      - docs/tutorials/local-engineering-ci.zh-CN.md
      - docs/tutorials/seed-task-import.md
      - docs/tutorials/seed-task-import.zh-CN.md
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - README.md
      - README.zh-CN.md
      - CLAUDE.md
    scope: 说明启用、可信代码及本地范围，更新能力审计
    acceptance: 中英命令一致，明确工程CI与事后评分不同，验收事实不夸大
  - id: T4
    title: 工程状态采集和端到端实证
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
      - backend/ahe_beta/experiment/collection.py
      - backend/tests/test_experiment_ci_collection.py
      - backend/ahe_beta/user/sim/runtime.py
      - backend/tests/user/sim/test_process_cleanup.py
      - backend/scripts/e2e-spec-0077-local-engineering-ci.sh
      - .github/workflows/experiment-contract.yml
    scope: 当前提交状态与CI收据采集，离线回归和真实Docker PR红绿及生命周期验收
    acceptance: 新head不会沿用旧绿灯；注册秘密不进入归档；真实PR红绿、恢复与清理有记录
---

# 0077 · 本地工程 CI runner 生命周期

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

为 local + localhost 实验增加可选工程 CI。默认关闭不变；启用时准备固定 runner/job 镜像、注册专属 Gitea Actions runner、执行真实 PR smoke，并在身份与就绪收据核验后才把 OpenAgents CI stage 设为 agent。CI 只检查 Harness 工程结构，不调用模型或运行 benchmark。E2B + Gitea.com 此次仍不支持 CI。

## Motivation

历史本地 Gitea 部署包含 act_runner 和 Harness 的 .gitea/workflows/smoke.yml，但统一入口只创建关闭 Actions 的 Gitea 与代理，ci_enabled 只能为 false。固定 OpenAgents 在 CI 门开启时读取 PR 当前 head SHA 的 combined commit statuses；零检查或 pending 会持续等待，failure 会进入 fix-ci。仅允许 true 或启动 runner 进程不能证明 checkout、Node action、网络和状态回传可用。旧服务使用全局网络与容器名，也不符合当前每个 run 的资源所有权、收集、停止及恢复要求。

## Guide-level explanation

在 local 配置中设置 runtime.local.ci_enabled=true，仍使用原 check/prepare/run/status/stop/resume/collect/destroy。可选 runner_image 和 ci_job_image 必须有版本或摘要，实际 image_id 在准备时固定。没有此设置的已有配置与冻结运行保持原语义。准备与 run preflight 增加真实 Actions 验证，失败会保留诊断和明确错误，不降级为 skip。status 单列 CI 状态、注册身份与运行证据。停止暂停 runner 并处理所属 job；恢复复用同一身份并再次探测；销毁移除执行资源，保留明确列出的 Gitea 与 runner 私有卷。

## Reference-level explanation

配置与冻结：ci_enabled 为可选 boolean；E2B 继续禁止 local 设置。启用时检查冻结 Harness 具备能覆盖 PR 的 ubuntu-latest 工作流，未启用不引入新默认字段破坏旧哈希。默认 runner 为 gitea/act_runner:0.2.11，job 镜像使用固定摘要的 catthehacker/ubuntu，准备记录实际 IDs。

资源：每个 run 专属 runner 服务/数据卷与 ci 网络，不引入 container_name 或全局网络；关闭时不创建 runner。runner 配置关闭共享 cache，job 容器注入 run_id、config_hash 和 CI role 标签，限制默认容量为一，使用本次固定 job image。runner 使用每个 run 专属的 docker:27.5.1-dind 执行器；该 daemon 不暴露宿主端口，只有当前专属 ci 网络可访问。runner 不挂宿主 Docker socket。job 镜像从已固定的宿主镜像流式预载到私有 daemon，job 的 host 网络指的是该隔离 daemon 的网络命名空间，不是宿主网络，因此仍可访问同一 run 的 Gitea。act_runner 的全局任务容器名和 act-toolcache 名称隔离在各自 daemon 中，不跨实验共享。daemon 镜像与容器/卷也按当前 run 标签和 image_id 核验。注册 token 仅临时私密输入，不能进入普通 compose.env、日志、public receipts 或归档；注册文件保存在专属私有卷，收据只包含非敏感注册 ID/名称/实例/标签。

就绪：核验容器标签、镜像、项目网络、注册身份与独立 daemon 身份；专属技术 probe 仓库提交最小工作流并创建 PR，真实执行 checkout + Python smoke，必须看到 PR 当前 head 的 count>0 和 success 才发放 readiness。探针不冒充用户反馈，删除仅由当前运行创建的临时 probe 仓。注册/工作流/API失败或有界超时均 fail closed。build_controller_environment 只在 ci_enabled 与已核验 resource receipt 一致时输出 agent；否则 enabled 配置报错，disabled 继续 skip。

生命周期：stop 先终止 controller/Vigil，再有界停止 runner、处理带双重所有权标签的 CI job，随后保存终态 forge/status/CI 证据并停止基础设施。恢复不重复注册，不变更 image/network/runner identity，并再次执行 readiness。destroy 不按 act-* 名称、全局网络或其他 run 的容器清理；所属 job 删除后才能声明 DESTROYED。保留 runner 注册卷的原因和名称明确写入收据；destroy 在确认 daemon 已停止后移除其专属 Docker 数据卷和全部内层任务/cache，stop 则保留该卷供恢复。无法核验所有权或无法停止时保留资源并报错。collect 对启用 CI 的运行保存主分支和 PR 当前 SHA 的状态以及 readiness，未启用不额外访问 CI endpoint；不会复制 runner 私密注册文件。

工作分解：T1 配置/材料预检查/环境门控与对应测试；T2 镜像准备、Compose、专属 CI helper、backend 生命周期与测试；T3 双语教程/配置/迁移审计；T4 forge 状态收集、端到端脚本、真实验收与 CI 工作流。T1/T2/T3 按固定接口并行，T4 依赖前三项。具体文件由 frontmatter 单独分配，组级 spec 与生成索引由协调者维护。端到端脚本 backend/scripts/e2e-spec-0077-local-engineering-ci.sh。

## Drawbacks

启用时增加镜像下载、注册与真实 Actions 探针耗时。专属 daemon 需要本地 Docker 支持 privileged 容器，适用于用户信任的自有 Harness 代码；这解决不同实验任务名称/cache 的隔离，不宣称抵御恶意 PR 的安全沙箱。保留 runner 卷会保留私密注册凭据，不能作为公开产物上传。当前单 runner 容量有限，不提供跨实验容量调度。

## Rationale and alternatives

不直接复用旧全局 gitea/act_runner 服务，因为会共享账户、网络和清理边界；不只添加 ci_enabled=true，因为零 checks 的 OpenAgents 门会持续等待；不把工程 CI 合并进事后 SWE grade，因为工程测试与 benchmark/gold 成绩用途不同。先迁入有宿主 Docker 的 local 路径；E2B + Gitea.com 没有等价 runner 托管契约，保持明确关闭。runner 集中在 helper 中，避免把注册/探针/状态机全部堆入现有大 backend。

## Prior art

历史 backend/deploy/gitea 的注册与固定工作流证明所需基础构件存在，但全局所有权不适用于公开 run。现行 local 工具链实际 image_id、Compose 标签、私密 provider.env、终态 forge 证据及恢复身份校验提供复用边界。固定 OpenAgents 的 ci:agent 是状态门与红灯修复编排，不是执行器。

## Unresolved questions

回归验收发现现有 attempt 超时清理直接调用可选的 Python pidfd API；当前锁定 Python 无此接口时会失败。T4 增加 Linux x86_64/aarch64 原生 pidfd syscall 兼容，继续获取稳定句柄并复核 nonce，不退回未经句柄保护的 PID 信号。未知平台/不支持的内核保留失败诊断，不宣称清理成功。此修正作为通过现有必要回归的前置条件，不改变 workspace 模型。

无阻塞产品选择；本组范围固定为 local+localhost、默认关闭与可信自有代码。真实验收区分人工制造的红绿技术对照与模型自动修复，不把前者宣称为后者。

## Future possibilities

E2B CI 可在有明确托管 runner 服务及身份契约后单独设计。历史产物导入追加轮继续独立迁移；本组不改变 resume 的同一 run 身份或冻结 controller。未来可增加更严格 CI 执行隔离、多 runner 容量与自定义标签，但不恢复全局旧 wrapper。
