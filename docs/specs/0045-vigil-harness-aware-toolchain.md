---
number: "0045"
title: Vigil Harness-aware 开发工具链
issue: 0
slug: vigil-harness-aware-toolchain
summary: 以显式 OpenAgents/NexAU 双 checkout pin 构建非 root vigil 镜像，提供 harness 内部编排所需的真实源码与测试工具；构建期依赖、Claude 版本、代理与运行配置均显式可审计。
tasks:
  - id: T1
    title: 工具链边界与双 pin 契约
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0045-vigil-harness-aware-toolchain.md
    scope: 定义 OpenAgents 交付编排与 NexAU harness 运行时的双 checkout pin、只读源码可见性、非 root 执行、安全凭证和本机部署覆盖边界；不改变 OpenAgents 仓源码。
    acceptance: 九段 Spec 完整；生产能力、实验分支和本机代理参数边界明确；spec validate/render/graph 通过。
  - id: T2
    title: 双 checkout 镜像与只读 NexAU 工具链
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/deploy/vigil/Dockerfile
    scope: build.sh 校验 OpenAgents/NexAU checkout 并通过 named context 构建；镜像无隔离安装两项目，保留只读 /opt/nexau-src，安装 ruff/pytest，固定并验证 Claude Code 版本，以 uid 1000 运行。
    acceptance: 缺参或错误 checkout fail closed；docker build 参数与两个 pin 可审计；容器内 OpenAgents/NexAU/ruff/pytest/Claude 可用，NexAU 源码不可写，uid 非 root；shell 与 pytest 通过。
  - id: T3
    title: 显式构建镜像源、版本与代理配置
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/deploy/vigil/build.sh
      - backend/tests/test_vigil_build.py
    scope: PIP index 与 Claude 版本提供可覆盖默认值；宿主 HTTP(S)/NO_PROXY 仅作为 build args 传递，不写凭证或本机 IP；本地 checkout 使用预装 build backend 避免重复隔离联网。
    acceptance: 默认值稳定且可经 VIGIL_PIP_INDEX_URL/VIGIL_CLAUDE_CODE_VERSION 覆盖；build 命令不展开或记录密钥；无硬编码宿主路径/IP；shell 测试与镜像构建通过。
  - id: T4
    title: 运行入口接线与配置优先级
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/tests/test_run_vigil.py
    scope: 缺镜像提示包含双 checkout 用法；容器同时注入大小写 HTTP(S)_PROXY/NO_PROXY；命令环境显式配置优先于仓内 .env；既有 keep-alive、复用、停止与凭证隔离不变。
    acceptance: docker run 参数完整且不泄露凭证；显式环境不被 .env 覆盖；镜像缺失提示可执行；test_run_vigil、ruff 与真实容器 smoke 通过。
---

# 0045 · Vigil Harness-aware 开发工具链

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

将 vigil 镜像从“只安装 OpenAgents 的交付容器”扩展为理解 harness 真实运行基础的开发工具链：构建时分别
接收 OpenAgents 与 NexAU checkout，安装两者并保留只读 `/opt/nexau-src`，使实现、评审和测试角色能够
验证 harness 内部编排而无需修改或 vendor NexAU。两个仓的 commit 分别构成可审计 pin。

镜像继续以非 root 用户执行，凭证只在运行时注入。Claude Code 版本、Python 镜像源与 build proxy 均为
显式可覆盖配置；本地项目使用预装 build backend 和 `--no-build-isolation`，避免在每个 checkout 安装时
重复创建联网构建环境。`run.py` 提供双 checkout 构建提示、完整代理环境和“进程显式配置优先于仓内
.env”的确定性规则。宿主代理 IP、端口及某次实验模型不属于本 Spec。

## Motivation

harness v0 的执行与 agent 定义基于 NexAU。只有 OpenAgents 源码和 Claude CLI 的 vigil 可以修改普通产品
文件，却无法运行 harness 测试或核对 NexAU API；实现者因此会猜测 tracer、AgentConfig 与 tool binding，
评审者也无法验证架构修改。这不是让交付流程修改 NexAU，而是让它在固定版本上拥有与被开发对象一致的
只读技术上下文。

早期 Dockerfile 每次从本地 checkout 安装时允许 pip 创建隔离构建环境，可能重复联网下载 hatchling、
setuptools 和 wheel；Claude native installer 也未固定版本，重建同一 commit 得到的工具链可能漂移。
WSL/容器环境还同时存在大小写 proxy 变量；只注入 `HTTPS_PROXY` 会使部分工具直连失败。最后，仓内 `.env`
曾覆盖启动命令显式注入值，临时切换网关或模型时产生违反直觉的配置优先级。

## Guide-level explanation

构建入口显式接收两个 checkout：

```text
build.sh <OpenAgents checkout> <NexAU checkout>
             │                    │
             │ docker context     │ named context: nexau
             └─────────┬──────────┘
                       ▼
           ahe-beta-vigil:latest
             ├─ openagents CLI
             ├─ claude (fixed version)
             ├─ nexau package + /opt/nexau-src (read-only)
             ├─ ruff / pytest
             └─ USER vigil (uid 1000)
```

`VIGIL_PIP_INDEX_URL` 与 `VIGIL_CLAUDE_CODE_VERSION` 可覆盖默认值。构建继承宿主大小写 proxy 作为 Docker
build args，但不把凭证写入镜像。运行时 `run.py` 向容器同时传递 `HTTP_PROXY/HTTPS_PROXY` 及其小写形式，
Gitea 内网地址进入 `NO_PROXY/no_proxy`。启动命令环境已有的 LLM 配置保持不变，仓内 `.env` 只补缺失键。

## Reference-level explanation

`build.sh` 对两个路径执行 fail-closed 形状校验：都必须有 `pyproject.toml`，且项目名分别为
`openagents`、`nexau`。Docker 使用 OpenAgents 为主 context，通过 `--build-context nexau=<path>` 传入
第二仓，不复制到共同父目录。构建完成消息分别输出两个 checkout 的短 SHA；非 Git 目录明确标记，而不
伪造版本。

Dockerfile 先安装 hatchling、setuptools 与 wheel，再以 `--no-build-isolation` 安装本地项目。NexAU
checkout 保留在 `/opt/nexau-src`，安装后移除所有写权限；运行用户 uid 1000 只能读取。构建以 import
`Agent/AgentConfig/Span/SpanType` 验证关键 API。Claude installer 接收显式版本并以 `claude --version`
核对；ruff/pytest 在镜像构建期安装，运行时无需访问包索引。

`run.py` 的镜像预检错误必须给出两个 checkout 参数。容器启动仍保持 Spec 0033 的挂载与凭证边界，只增加
大小写 proxy 变量；Gitea token、Anthropic 凭证和模型网关凭证只经 env。`_apply_env_defaults` 使用
`os.environ.setdefault`，由通用入口和 SWE-bench 闭环入口复用，保证命令环境 > 仓内 `.env`。

本 Spec 不拥有 `egress-proxy.conf` 中的本机上游。WSL 宿主地址、代理端口和当前 API allowlist 是部署
覆盖，应在提交时与可复用工具链分离；通用仓库不得固定个人网络拓扑。

## Drawbacks

安装 NexAU 及其源码使镜像增大，双 checkout 也增加构建输入与 pin 管理成本。保留只读源码仍会让 Agent
读取更多实现细节，因此角色 Prompt 和取证预算必须继续限制从头调查；本组只提供能力，不授权无限读取。
固定 Claude 版本减少漂移，但需要显式升级维护。

## Rationale and alternatives

选择本地 checkout pin，而不是仅从 PyPI 安装 NexAU wheel，因为 harness 可能依赖尚未发布的接口，评审也
需要核对源码；只读 checkout 比允许 Agent 修改 NexAU 更符合仓库边界。选择 Docker named context，而不是
复制两个仓到临时聚合目录，避免额外资产与来源不清。

未将 NexAU vendor 进 OpenAgents 或 Auto Architect；三仓仍独立演进。未允许运行时 pip 安装，因为 egress
通常只放行模型与 forge 服务，且会破坏复现性。未将宿主代理写进 Dockerfile：代理只作为 build/run 参数。

## Prior art

Spec 0033 建立 vigil 非 root 容器、凭证隔离和 egress 边界；本组是工具能力的后继扩展，不削弱 containment。
Spec 0040 打开 OpenAgents 的 Spec/实现阶段并保持 vigil 常驻，本组为实现者提供真实 harness 依赖。Spec
0041 仍将 developer usage 视为 capability-dependent；安装 NexAU 不等于自动获得 OpenAgents 逐调用 Token
协议。

## Unresolved questions

当前镜像同时保留 OpenAgents 安装副本与构建 context 源码，NexAU 只明确保留源码；是否也需要只读
`/opt/openagents-src` 的稳定审计接口由 OpenAgents 自身决定。镜像 digest 与两个 Git SHA 尚未写入统一
provenance manifest，发布前可作为后续增强，但不应通过解析镜像日志猜测。

## Future possibilities

可增加机器可读的 toolchain manifest，记录基础镜像 digest、OpenAgents/NexAU SHA、Claude/ruff/pytest
版本，并在 vigil 启动时只读展示。构建可采用 wheel cache 或多阶段镜像降低体积；任何缓存都必须保留双 pin
和非 root、只读源码、不含凭证等不变量。
