---
number: "0015"
title: Harness 边界与需求工具访问：提交拒绝清单、trace 隔离与工作区检查
issue: 0
slug: dev-overfit-isolation
summary: 保留三项有效边界机制：Harness 提交钩子拒绝密钥与运行态，sandbox 工作目录与原始 trace 分离，需求 Agent 通过 guards 的工具路径检查及显式观测授权读取文件。
tasks:
- id: T1
  title: harness 仓提交边界硬闸（pre-commit 钩子）
  status: pending
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/guards/harness_boundary.py
  - backend/tests/guards/test_harness_boundary.py
  scope: 'guards/harness_boundary 生成自包含 pre-commit 钩子；拒绝路径中的 .env、.env.*（.env.example 例外）与顶层 .openagents，放行正常产品代码和文档。钩子仅依赖 Python 标准库与 Git，由 run.py 在 seed 提交后安装。规则与 seed smoke 的服务端检查保持一致。'
  acceptance: 临时仓安装钩子后，普通源码、docs/specs 与 .env.example 提交通过；.env、.env.local、.openagents 状态被拒。钩子不依赖编排包，模板规则与 violations() 同源。
- id: T2
  title: sandbox 工作目录下沉，物理隔离 trace
  status: pending
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/controllers/ordinary.py
  - backend/tests/test_sandbox_isolation.py
  scope: 把 需求 Agent 的 sandbox 工作目录（= harness 仓）下沉到独立父目录 data/harness_sandbox/harness_repo，使 trace 目录（data/sessions 体感+会话、data/harness_runs 运行副本）不再是它的 ../ 同级——agent 顺 ../sessions/*.json、../harness_runs/** 这类相对路径不再命中真数据，从目录布局上断掉「顺手翻轨迹」的现实路径。run.py 的 _seed_harness_repo 在此新布局下建仓、并调 install_pre_commit（T1）装边界钩子；launcher/store/runs_root 指向相应目录。与 WorkspaceJail（T3）互补：本任务改目录布局（被动隔离），T3 改工具行为（主动拒绝）。
  acceptance: HARNESS_REPO = data/harness_sandbox/harness_repo，与 data/sessions、data/harness_runs 无父子/兄弟可达关系；从 harness_repo 出发的 ../sessions / ../harness_runs 相对路径不指向真 trace；_seed_harness_repo 在新布局建仓并装 pre-commit 钩子。单测断言目录布局隔离（trace 不在 work_dir 的 ../ 同级）。
- id: T3
  title: WorkspaceJailMiddleware：写关仓内、读放行 NexAU 源码与运行时临时目录
  status: pending
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/guards/workspace_jail.py
  - backend/tests/guards/test_workspace_jail.py
  scope: WorkspaceJailMiddleware 位于 guards；写工具限制在 Harness 工作区，读工具允许工作区、NexAU 源码与框架临时输出。Triage、Architect、PM、Owner 的 agent YAML 装配它；观测制品须经过声明和 session 授权才能读取，不能通过路径重命名扩大证据范围。此检查不是操作系统沙箱。
  acceptance: 四角色 YAML 装配新 guards binding；合法源码/临时输出可读，越界读写拒绝；按调用授权的观测读取与原始 trace 拒绝保持原契约；无工作区和 heredoc 的既有行为不变。
---

# 0015 · Harness 边界与需求工具访问

## Summary

当前保留三项机制：Harness 提交拒绝清单、工作目录与原始 trace 的布局隔离、需求 Agent 的工具文件路径检查。实现位于 `backend/ahe_beta/guards/`，不再归属一个内置开发角色。

## Motivation

产品仓不应收入密钥和实验运行态，需求 Agent 也不应随意读取原始任务轨迹。路径检查可阻挡直接越界访问，但不能约束解释器执行的所有行为，因此不得将它描述为操作系统沙箱。

## Guide-level explanation

- `harness_boundary.py` 生成独立 pre-commit 钩子，拒绝 `.env`、`.env.*` 与顶层 `.openagents`；`.env.example` 和正常产品文件允许提交。
- `run.py` 将 Harness 放在 `data/harness_sandbox/harness_repo`，避免原始 trace 成为工作区的同级目录。
- Triage、Architect、PM、Owner 通过 `WorkspaceJailMiddleware` 检查工具访问；声明的观测制品还须满足按调用和 session 的授权。

## Reference-level explanation

T1 拥有 `guards/harness_boundary.py` 及其测试；T2 拥有启动入口的目录布局和钩子安装；T3 拥有 `guards/workspace_jail.py` 及其测试。需求 Agent 定义引用 `ahe_beta.guards.workspace_jail:WorkspaceJailMiddleware`。

提交钩子在 seed 提交后安装，只依赖标准库和 Git。修改拒绝清单时同步 Harness 模板 smoke 的独立脚本。写操作限制于工作区；读操作放行工作区、NexAU 源码及框架临时输出，原始 session 与运行轨迹不因目录迁移而放行。显式观测授权仍由需求侧 observation provider 校验。

```mermaid
flowchart LR
    T1[提交钩子] --> T2[工作区布局与安装]
    T3[工具访问检查]
```

离线验证：`uv run --locked --extra dev pytest backend/tests/guards/test_harness_boundary.py backend/tests/guards/test_workspace_jail.py backend/tests/test_sandbox_isolation.py`。完整接线回归还检查四角色 YAML、临时仓提交与拒绝、观测授权。

## Drawbacks

工具参数级检查不能阻止解释器或任意 shell 的所有越界方式；目录隔离也不是权限隔离。容器或操作系统级隔离需要独立验证。

## Rationale and alternatives

保留有效检查并移入 `guards`，避免删除仍被装配的防线；采用明确拒绝清单而非旧的产品文件名白名单，使合法新增源码和 Spec 文档可以提交。

## Prior art

早期提交白名单和路径检查用于降低任务内容污染产品的风险。当前提交边界已经允许正常产品扩展，同时持续拒绝密钥与运行态。

## Unresolved questions

无。此整理保持现有检查行为和触发位置，不增加新沙箱能力。

## Future possibilities

可将提交钩子与 CI 的拒绝规则生成自同一份来源，并进一步验证操作系统级隔离；这些不是包迁移自动带来的保障。
