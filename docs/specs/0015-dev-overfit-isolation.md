---
number: "0015"
title: 开发者侧过拟合泄漏隔离：提交边界 + trace 物理隔离 + 工作区 jail
issue: 0
slug: dev-overfit-isolation
summary: 堵 dev/designer 把「某个具体任务的产物」焊进通用 harness 的过拟合泄漏，三道机制层防线：① harness 仓 pre-commit 提交边界钩子——暂存区出现 harness 本体之外路径即拒；② sandbox 工作目录下沉到独立父目录，断掉相对路径可达 trace；③ WorkspaceJailMiddleware——写只许 harness 仓；读放行 harness 仓 + NexAU 源码 + NexAU 运行时临时目录（nexau_bash_tool_results / nexau_tool_outputs），trace（sessions/harness_runs）仍一律拒。落点 backend/auto_designer/dev/ + run.py。
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
      - backend/auto_designer/dev/harness_boundary.py
      - backend/auto_designer/dev/agentic_developer.py
      - backend/tests/dev/test_harness_boundary.py
    scope: 'harness 是通用编码助手，仓里只该有它自身的制品。装一个自包含的 git pre-commit 钩子（只依赖 python3 stdlib + git、不 import 本包，因 harness 是独立仓）：暂存区出现 ALLOWED_TOP 之外的顶层路径就拒绝提交、打印越界清单与原因。ALLOWED_TOP={MANUAL.md, agent.yaml, params.yaml, entry.py, agents/, tools/, tests/, .gitignore}——tests/ 收 harness 自身回归测试（任务代码已被本闸挡在仓外，tests/ 里只可能测 harness 本体，放开不重开泄漏口）；顶层散落 test_*.py 仍拒，逼测试统一进 tests/。构建噪声（__pycache__/*.pyc）跳过、不为它拒整次提交。violations() 与钩子模板同源逻辑。install_pre_commit(repo) 写入 .git/hooks/pre-commit 并置可执行。agentic_developer 侧的 dev 任务消息/提示与该边界对齐（改的是 harness 能力、不是把任务代码写进来）。动机实测：用户把「跑不动某 benchmark 任务」当 bug 提 issue，dev 照字面把被测项目本体一行行写进 harness 仓并提交（issue #69 耗 23 次 shell、爆迭代），正是要堵的过拟合。'
    acceptance: 种出的 harness 仓 .git/hooks/pre-commit 存在且可执行；提交仅含白名单路径（entry.py/agents/tools/MANUAL.md/tests/…）时通过；提交含被测项目代码（如 unicode_ascii/、pyproject.toml、顶层 test_*.py）时被拒、stderr 列出越界文件；__pycache__/*.pyc 不触发拒绝；tests/ 下的 harness 自测放行。单测覆盖 violations() 各情形 + 钩子在临时仓上的放行/拒绝端到端。
  - id: T2
    title: sandbox 工作目录下沉，物理隔离 trace
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/run.py
      - backend/tests/test_sandbox_isolation.py
    scope: 把 dev/designer 的 sandbox 工作目录（= harness 仓）下沉到独立父目录 data/harness_sandbox/harness_repo，使 trace 目录（data/sessions 体感+会话、data/harness_runs 运行副本）不再是它的 ../ 同级——agent 顺 ../sessions/*.json、../harness_runs/** 这类相对路径不再命中真数据，从目录布局上断掉「顺手翻轨迹」的现实路径。run.py 的 _seed_harness_repo 在此新布局下建仓、并调 install_pre_commit（T1）装边界钩子；launcher/store/runs_root 指向相应目录。与 WorkspaceJail（T3）互补：本任务改目录布局（被动隔离），T3 改工具行为（主动拒绝）。
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
      - backend/auto_designer/dev/workspace_jail.py
      - backend/tests/dev/test_workspace_jail.py
    scope: nexau 权限体系不足以「按路径禁读」，故用 wrap_tool_call 自研 jail。写类工具（write_file/replace/multiedit）：目标必须在 harness work_dir 内，越界一律拒。读类工具：放行根=_read_roots_for(work_dir)= harness 仓 + NexAU 源码仓根（import nexau 解析）+ NexAU 运行时临时目录（优先 nexau path_helpers 的 get_local_bash_tool_results_dir / get_local_tool_output_dir，失败则 tempfile 下 nexau_bash_tool_results / nexau_tool_outputs）——框架落盘的 bash/tool stdout，不是任务轨迹；拒读会误伤正常工具环。run_shell_command：path-like token 同读规则；命中 trace 兜底正则（harness_runs；sessions 经 ../ 或绝对路径段）仍一律拒。heredoc 只剥正文、保留重定向行以便扫越界写。无 sandbox 则放行。同一中间件挂 dev 与 designer。
    acceptance: 写逃出 work_dir 被拒；读 work_dir / NexAU 源码 / nexau_* 临时目录放行；读 sessions/harness_runs 被拒；shell 同口径；heredoc 正文不误伤、重定向越界仍拒；无 sandbox 放行。单测覆盖：读写分流、NexAU 只读根、运行时临时目录放行、trace 拒绝、heredoc、无 work_dir。
---

# 0015 · 开发者侧过拟合泄漏隔离：提交边界 + trace 物理隔离 + 工作区 jail

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

堵 dev/designer 把任务产物焊进通用 harness 的过拟合泄漏，三道机制：

1. **提交边界**——pre-commit 拒非 harness 白名单路径；
2. **trace 物理隔离**——sandbox 下沉，断掉 `../sessions` / `../harness_runs`；
3. **WorkspaceJail**——**写**只许 harness 仓；**读**放行 harness 仓 + **NexAU 源码** + **NexAU 运行时临时目录**（`nexau_bash_tool_results` / `nexau_tool_outputs`）；trace 仍一律拒。

## Motivation

写侧：照 issue 字面把被测项目写进 harness。读侧：翻轨迹过拟合；但若连 NexAU 自己的 bash/tool 临时输出也拒读，会误伤正常工具环。故读写分流：挡 trace，放行框架只读根。

## Guide-level explanation

- **能写/提交**：仅 harness 本体白名单。
- **能读**：仓内 + NexAU 库源码 + nexau 临时输出目录。
- **不能读**：`data/sessions` / `data/harness_runs`（布局 + jail 双挡）。

## Reference-level explanation

### 代码锚点

- `harness_boundary.py`；`run.py` 下沉布局；`workspace_jail.py`：`_WRITE_TOOLS`、`_read_roots_for`、`_nexau_repo_root`、`_nexau_runtime_read_roots`、`_TRACE_REF`。

### 三道防线

| 防线 | 挡什么 |
|---|---|
| pre-commit | 任务代码进仓 |
| 目录下沉 | 相对路径翻 trace |
| jail | 写越界；读 trace；读侧放行 NexAU |

### DAG

```mermaid
graph LR
  T1[T1 提交边界]
  T2[T2 sandbox 下沉]
  T3[T3 WorkspaceJail]
  T1 --> T2
```

## Drawbacks

静态 shell 扫描非 airtight（`python -c`）；白名单硬编码；钩子可被 `--no-verify` 绕过。

## Rationale and alternatives

- 仅 nexau 原生权限：read 不走权限。
- 仅 prompt：已被泄漏事故证伪。
- 读侧一律 work_dir：误伤 NexAU 工具环。

## Prior art

CLAUDE.md train/test 分离；0007 无门禁更需边界。

## Unresolved questions

是否上 OS 级沙箱；ALLOWED_TOP 演进；误伤可观测性。

## Future possibilities

拦截事件进看板；内容级提交检查。
