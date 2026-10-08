---
number: "0046"
title: 冻结设计产物到 OpenAgents 的隔离验证交接
issue: 0
slug: frozen-openagents-validation-handoff
summary: 将冻结需求面 summary 或只读 Gitea 快照复制到全新验证仓库，选择性保留交付令牌并生成不可覆盖 manifest；随后以显式 Anthropic-compatible 网关配置启动隔离 vigil，保证实验可复用且不污染来源。
tasks:
  - id: T1
    title: Fresh-target 与不可变 Manifest 契约
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0046-frozen-openagents-validation-handoff.md
    scope: 定义来源只读、目标必须不存在、manifest 不覆盖、本地可验证错误先于外部 mutation、issue 编号稳定与凭证不落盘等实验交接不变量。
    acceptance: 九段 Spec 完整；source=target、缺失 issue、畸形 summary、既有 manifest 均 fail closed；spec validate/render/graph 与 pytest 通过。
  - id: T2
    title: 冻结 Summary 物化为验证仓库
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tools/dev/delivery/prepare_openagents_from_summary.py
      - backend/tests/test_prepare_openagents_from_summary.py
    scope: 预检连续 issue 快照和 harness 目录；复制时排除 Git/字节码运行态，在全新 Gitea 仓建立 main 并按原编号恢复 issue 状态与标签，写 source/main SHA/交付选择 manifest。
    acceptance: 所有本地输入在建仓前验证；源目录与 summary 不修改；目标 issue 编号、状态、标签与交付选择一致；manifest 原子边界明确且不含凭证；测试与真实 fresh-target 记录通过。
  - id: T3
    title: 只读 Gitea 快照的选择性交付复制
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tools/dev/delivery/prepare_openagents_validation.py
      - backend/tests/test_prepare_openagents_validation.py
    scope: 先读取并验证 source main 与 issue/comment 快照，再创建 fresh target；复制 Git 时清除已跟踪字节码，只有显式 --deliver issue 保留 openagents 令牌，其余事实与评论保持。
    acceptance: source 与 target 必须不同；选择的 issue 必须存在；预检失败不创建 target；main/issue/comment/state 稳定复制且来源不变；manifest 保存选择与 SHA；测试及真实回放记录通过。
  - id: T4
    title: 隔离 Vigil 启动与网关协议转换
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - tools/dev/delivery/run_openagents_validation.py
      - backend/tests/test_run_openagents_validation.py
    scope: 把共享 WIS env 转为 Anthropic-compatible base/auth/model，校验 config 与并发度，以独立容器名启动 vigil；Gitea/模型凭证只经 subprocess env，代理和 no_proxy 大小写完整注入。
    acceptance: 带空格/引号 env 可解析，/v1 只移除末尾版本段，缺字段与非法并发在 docker 前失败；命令不含密钥值；容器网络/只读挂载/代理参数完整；pytest 与 ruff 通过。
---

# 0046 · 冻结设计产物到 OpenAgents 的隔离验证交接

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

提供一条只面向实验验证的冻结交接路径：从离线设计 summary 或现有 Gitea 实验快照创建全新目标仓库，复制
固定 main、issue、评论和状态，并仅为显式选择的候选保留 `openagents` 交付令牌。来源始终只读，目标必须
不存在，manifest 必须是新文件；任何能在本地或只读阶段发现的错误都必须在创建目标前失败。

准备完成后，独立启动脚本把共享 WIS 配置转换为 Claude Code 所需的 Anthropic-compatible 环境，并以
专用容器名、只读配置挂载和隔离网络启动 vigil。凭证只经 subprocess env，不进入命令参数、manifest 或
目标仓库。本组验证冻结设计产物的实现可行性，不接回生产需求面，也不自动合并实验结果。

## Motivation

需求面角色、Prompt 或 schema 变化后，需要复用已经昂贵地产生的用户交互与提案，重新验证 OpenAgents，而
不重跑用户模型、修改原实验仓或复用残留 PR/label 状态。直接在旧仓恢复标签会使前后实验不可区分；手工
复制又容易遗漏 closed state、评论、main SHA 或交付选择。

此前恢复脚本在验证选定 issue 之前创建目标仓，输入错误会留下半成品；复制带 `.git` 的 harness 也可能
继承来源历史与 remote。网关启动若手工拼 env，`/v1` 路径和 Anthropic 客户端追加规则容易形成重复版本
段。需要一个 fail-closed、fresh-target、可审计且不保存密钥的实验工具边界。

## Guide-level explanation

有两种输入入口：

```text
frozen summary + harness dir ── prepare_from_summary ─┐
                                                     ├─ fresh Gitea target + manifest
read-only Gitea source ───── prepare_validation ─────┘
                                                                  │
WIS env + model + config ───── run_openagents_validation ─────────┘
                                                                  ▼
                                                        isolated vigil container
```

summary 入口适合离线角色回放；Gitea 入口适合从某轮完整事实仓选择 1..n 个交付候选。两者都先拒绝既有
manifest 和既有 target。Gitea 入口复制全部 issue 事实，但从未选 issue 移除交付令牌；它不删除 issue、
评论或来源标签。manifest 记录 source、target、main SHA、issue 快照、delivery issues 和
`openagents_started=false`，启动行为另行发生。

## Reference-level explanation

summary 必须含 issue 对象列表，编号从 1 连续且唯一，title/body 为字符串，labels 为字符串数组，state 只
允许 open/closed；harness 目录必须存在。这些检查在 Gitea API 前完成。复制 harness 时排除 `.git`、
`__pycache__` 与 `*.pyc`，在临时目录初始化 fresh main，推送后按编号创建 issue；编号漂移立即失败。

Gitea 快照入口先构造 source tracker，读取所有 issue 和选择集合，验证 source/target 不同、编号合法唯一、
selected 全部存在；通过后才创建 target。Git clone 来源 main，移除已跟踪 bytecode 并补通用 `.gitignore`，
以新 commit 保存清理（如有），再将 origin 切到 target 并 push。issue、评论和 closed state 按编号恢复，
仅 selected 保留 `openagents`。

启动脚本要求 config 目录含 `openagents.yml`、parallel >= 1、WIS env 含 base/key。仅当 URL path 末尾为
`/v1` 时移除该段，避免误改中间路径；转换结果通过 env 提供 `ANTHROPIC_BASE_URL/AUTH_TOKEN/MODEL`。
Docker 命令只列 env 键名，不含值，配置与 entrypoint 只读挂载，使用 vigil 隔离网络和完整大小写 proxy。

## Drawbacks

外部 mutation 仍无法事务化：目标创建成功后若 git push 或第 N 个 issue 写入失败，可能保留部分目标仓。
本组保证可预检错误不产生 mutation，但不宣称跨 Gitea/Git 请求原子。连续编号要求限制了任意 issue 子集的
summary 输入；这是为了可靠恢复原编号。复制完整仓库和全部 issue 也增加时间与存储。

## Rationale and alternatives

选择 fresh target 而不是恢复原仓状态，换取实验隔离和清晰审计。选择 manifest 不覆盖，避免后一次运行
抹掉前一次来源。未直接调用生产 `start_vigil`，因为验证需要独立 repo、模型、container name 和配置目录；
但复用同一 env parser、镜像和 entrypoint，避免协议分叉。

未把临时 owner/synthesize 恢复脚本纳入本组：它们会修改既有仓库且缺少完整前态快照，只适合保留为事故
证据。未把密钥写入临时 env 文件或 manifest；subprocess env 是唯一凭证通道。

## Prior art

Spec 0042/0043 的 replay 工具冻结需求面输入、Prompt hashes 和角色产物，并在 OpenAgents 前停止；本组从该
边界继续。Spec 0032/0033 定义 Gitea 交付令牌与 vigil 容器隔离，Spec 0045 提供 OpenAgents/NexAU 双 pin
镜像。本组不改变这些生产契约，只提供实验复制与启动适配。

## Unresolved questions

Gitea 缺少跨仓 clone/issue 批量事务；未来是否在失败时自动删除 fresh target，需要单独授权，因为删除远端
仓库是破坏性操作。当前 manifest 在成功末尾写入，外部失败只留远端证据而无本地 failure manifest；是否
增加逐阶段 journal 需要后续设计。

## Future possibilities

可增加 dry-run plan、source/target 快照哈希、容器 image digest、OpenAgents/NexAU SHA 和逐阶段 journal，
形成完整实验 provenance。若 forge 提供仓库模板或事务导入 API，可替换逐请求复制，但必须保留 source
只读、fresh target、显式选择和凭证不落盘不变量。
