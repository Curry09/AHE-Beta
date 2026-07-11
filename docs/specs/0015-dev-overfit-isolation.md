---
number: "0015"
title: 开发者侧过拟合泄漏隔离：提交边界 + trace 物理隔离 + 工作区 jail
issue: 0
slug: dev-overfit-isolation
summary: 堵 dev/designer 把「某个具体任务的产物」焊进通用 harness 的过拟合泄漏，三道机制层防线：① harness 仓 pre-commit 提交边界钩子——暂存区出现 harness 本体之外路径即拒（任务代码/被测项目脚手架进不来）；② sandbox 工作目录下沉到独立父目录（data/harness_sandbox/harness_repo），使 trace 目录（data/sessions 体感+会话、data/harness_runs 运行副本）不再是其 ../ 同级、断掉相对路径可达；③ WorkspaceJailMiddleware——nexau read 类工具/只读 bash 不走权限，用 wrap_tool_call 把文件/shell 操作关进 SANDBOX_WORK_DIR，越界读写一律拒。落点 backend/auto_designer/dev/ + run.py。
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
    title: WorkspaceJailMiddleware：工具级越界读写一律拒
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/dev/workspace_jail.py
      - backend/tests/dev/test_workspace_jail.py
    scope: nexau 权限体系不足以「按路径禁读」：read 类工具（read_file/list_directory/glob/search_file_content/read_many_files…）不走 check_path_permission，只读 bash（cat/grep/find/less）又在白名单无条件放行。故用 wrap_tool_call 自研 jail：文件类工具把路径参数（仅审 path 参数键，不碰 old_string/pattern 等内容参数）按 work_dir resolve，逃出 work_dir（含符号链接、.. 归一、解析失败）一律拒、直接返回拒绝结果不调 call_next；run_shell_command 做 best-effort 静态扫描——命中 trace 目录名兜底正则（harness_runs 唯一、sessions 仅当以 ../ 或绝对路径的路径段出现），或 shlex 分词后任一 path-like token 逃出 work_dir 即拒（heredoc 正文跳过避免误伤）。work_dir 取 sandbox.work_dir，无 sandbox/取不到则放行（不改既有行为）。caveat：python -c 动态拼绝对路径静态扫不出，100% airtight 需 OS 级沙箱，出本层范围；但对非对抗 LLM 已堵住所有现实发现路径。同一中间件挂 dev 与 designer 两个角色。
    acceptance: 文件类工具目标路径逃出 work_dir（绝对路径/..//符号链接）被拒、返回 WORKSPACE_JAIL_DENIED；仓内路径放行；run_shell_command 引用 data/sessions 或 data/harness_runs（经 ../ 或绝对路径）被拒；heredoc 正文里的类路径词不误伤；无 sandbox 时放行。dev 与 designer 配置均挂该中间件。单测覆盖：各文件工具越界/合规、shell path token 越界、trace 正则、heredoc 豁免、无 work_dir 放行。
---

# 0015 · 开发者侧过拟合泄漏隔离：提交边界 + trace 物理隔离 + 工作区 jail

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

堵一个关键的架构级漏洞：dev/designer agent 把「某个具体被测任务的产物」焊进**通用** harness，导致过拟合——训练目标（体感）与测试目标（benchmark）互相污染，正是项目约束要极力避免的。三道正交的机制层防线：

1. **提交边界硬闸**——harness 仓 `pre-commit` 钩子，暂存区出现 harness 本体之外的路径即拒；
2. **trace 物理隔离**——sandbox 工作目录下沉到独立父目录，使 `data/sessions`/`data/harness_runs` 不再是其 `../` 同级、断掉相对路径可达；
3. **工作区 jail**——`WorkspaceJailMiddleware` 用 `wrap_tool_call` 把文件/shell 操作关进 `SANDBOX_WORK_DIR`，越界读写一律拒（补 nexau「read 不走权限」的缺口）。

## Motivation

**现状与事故（就地复述，本 spec 自包含）。** 项目的核心约束是「训练信号（体感）与测试（benchmark held-out）分离，persona 来自真实数据、不依据 benchmark 或轨迹构造」——目的是让 harness 的进化不被 benchmark 特征污染、避免过拟合。dev/designer 的 sandbox 工作目录就是 harness 仓；harness 是**通用编码助手**，仓里只该有它自身的制品（`entry.py`/`agents/`/`tools/`/`MANUAL.md`/配置/`tests/`）。

真实闭环里观测到两类泄漏：

1. **写侧泄漏（焊任务代码进 harness）。** 用户 agent 把「跑不动某 benchmark 任务（如 unidecode）」当 bug 提 issue，dev 领到后照字面 `mkdir -p unicode_ascii/tables; cat > pyproject.toml …`，把**被测项目本体**一行行写进 harness 仓并提交——通用工具被过拟合成某具体任务；且 dev 把整轮迭代耗在建/装/测这个包上（实测 issue #69 用掉 23 次 shell 调用），直接爆迭代。
2. **读侧泄漏（翻任务轨迹）。** dev/designer 顺 `../sessions`/`../harness_runs` 就能读到别人跑某任务的轨迹（某库 API、某类文件、预期输出）；逐行看会把任务专属知识带进 harness，同样是过拟合。而 nexau 的 read 类工具**不走权限体系**、只读 bash（`cat`/`grep`/`find`）又在白名单无条件放行——原生权限挡不住。

**为什么要机制、且要三道。** 这不是「提醒 agent 别这么做」能解决的：写侧靠仓钩子（agent 绕不过，除非显式 `--no-verify`，指令不会那么做），读侧靠「目录布局 + 工具级 jail」双保险。三道正交、互为兜底。

## Guide-level explanation

从 dev/designer 的视角，能做与不能做：

- **能做**：在自己的 harness 仓内 `git`、`pytest`、读写仓内源码——合法工作全在仓内。
- **不能提交**：harness 本体之外的任何文件。`git commit` 时若暂存区有 `unicode_ascii/`、`pyproject.toml`、顶层 `test_*.py` 之类，`pre-commit` 钩子直接拒、列出越界清单，逼它删掉只提交对 harness 能力的改动。
- **不能读到 trace**：`data/sessions`/`data/harness_runs` 既不在工作目录的 `../` 同级（物理隔离），工具层也拒——`read_file ../sessions/x.json`、`grep ... ../harness_runs` 一律返回 `[workspace-jail] 拒绝`。诊断只能靠 `git log` + 读仓内源码，不靠翻轨迹。
- **designer 同样被 jail**：designer 也只读 harness 仓 + 自己的定义目录，不能翻 trace。

对 dev 的净效果：把「照 issue 字面把任务代码写进 harness」这条过拟合路径，从「靠自觉避免」变成「机制上做不到」。

## Reference-level explanation

### 现状代码锚点

- `dev/harness_boundary.py`：`ALLOWED_TOP`（白名单顶层路径）、`violations()`、`_HOOK_TEMPLATE`（自包含 pre-commit 脚本，白名单内联）、`render_hook()`、`install_pre_commit(repo)`。
- `run.py`：`_SANDBOX_ROOT = DATA/"harness_sandbox"`、`HARNESS_REPO = _SANDBOX_ROOT/"harness_repo"`（下沉布局）；`_seed_harness_repo()` 建仓 + `install_pre_commit`；`launcher` 的 `runs_root=DATA/"harness_runs"`、`store=DATA/"sessions"`。
- `dev/workspace_jail.py`：`WorkspaceJailMiddleware.wrap_tool_call`、`_PATH_PARAMS`（各工具的路径参数键）、`_escapes()`（resolve 后逃逸判定）、`_shell_offender()`（shlex 分词 + trace 正则 `_TRACE_REF`）、`_deny()`。
- `agent_defs/developer_agent/agent.yaml` 与 `agent_defs/designer/agent.yaml`：中间件链首位挂 `WorkspaceJailMiddleware`（注册在各自 agent 定义里，跨 0014/0016 组）。

### 三道防线职责

| 防线 | 机制 | 挡什么 | 绕不过的原因 |
|---|---|---|---|
| 提交边界（T1） | git pre-commit 钩子 | 写：任务代码进 harness 仓 | 仓层钩子，非 `--no-verify` 拦不掉 |
| trace 物理隔离（T2） | sandbox 目录下沉 | 读：`../sessions`/`../harness_runs` 相对路径 | 布局上不再可达 |
| 工作区 jail（T3） | `wrap_tool_call` | 读/写：任何越界路径（含绝对路径） | 直接短路工具、不调 call_next |

### DAG

```mermaid
graph LR
  T1[T1 提交边界 pre-commit 钩子]
  T2[T2 sandbox 下沉·trace 物理隔离]
  T3[T3 WorkspaceJail 中间件]
  T1 --> T2
```

T2 的 `_seed_harness_repo` 调用 T1 的 `install_pre_commit`，故 T2 依赖 T1；T3（工具级 jail）独立，可并行。三者 `files` 互斥（T1 落 `harness_boundary.py`，T2 落 `run.py`，T3 落 `workspace_jail.py`）。

### 文件分配（各 Task `files` 互斥）

- **T1**：`dev/harness_boundary.py`、`dev/agentic_developer.py`、`tests/dev/test_harness_boundary.py`
- **T2**：`run.py`、`tests/test_sandbox_isolation.py`
- **T3**：`dev/workspace_jail.py`、`tests/dev/test_workspace_jail.py`

> 中间件注册在 `developer_agent/agent.yaml` 与 `designer/agent.yaml`，这两个文件分别归 0014/T3 与 0016/T2 所有（跨组重叠，OVERVIEW 会标）。

## Drawbacks

- **jail 静态扫描非 airtight**：`run_shell_command` 若用 `python -c` 动态拼绝对路径读文件，静态 token 扫描扫不出；100% 密封需 OS 级沙箱（容器/`sandbox-exec`），出本层范围。对非对抗性 LLM 已堵住所有现实发现路径。
- **白名单是硬编码策略**：`ALLOWED_TOP` 若未来 harness 需要新顶层结构，得改钩子模板并重装。
- **误伤风险**：jail 的 shell 扫描对含 `/` 的搜索词/参数可能误判；已用「只审 path 参数键」「heredoc 跳过」「trace 正则区分路径段 vs 搜索词」压低误伤，但非零。
- **钩子可被 `--no-verify` 绕过**：机制假设 dev 指令不会显式跳钩子；对抗场景不成立。

## Rationale and alternatives

选「三道正交机制」，因为写侧与读侧是不同攻击面、单一手段都有缺口，且都必须是机制（软提示实测被无视）。

- **备选 A：只用 nexau 原生权限体系。** 实测不足——`check_path_permission` 只管写、read 类工具与只读 bash 白名单绕过，无法「按路径禁读」。故自研 jail。
- **备选 B：只靠 prompt 告诫「别翻 trace / 别写任务代码」。** 正是被泄漏事故证伪的基线。
- **备选 C：只做目录下沉、不做工具 jail。** 挡住相对路径，但绝对路径仍可达；反之只做 jail 不下沉则依赖扫描无死角。二者互补更稳。
- **备选 D：把 trace 完全移出机器/加密。** 过重，且观测层本身要读 trace；隔离到「dev/designer 读不到」这一粒度即可。

## Prior art

- **项目约束（CLAUDE.md）**：「benchmark 全程 held-out、persona 不依据 benchmark 或轨迹构造」——本组是「不让 harness 演化过程接触任务特征」的机制落地。
- **0007 纯 trunk dev**：dev 直推 main、无门禁，使「坏提交立即生效」，更需要边界钩子挡住结构性错误提交。
- **沙箱/越权防护**：seccomp、容器、chroot 等 OS 级隔离思想的轻量应用层近似（`wrap_tool_call` 拦截）。

## Unresolved questions

- **是否上 OS 级沙箱**：`python -c` 动态路径的残余缺口是否值得引入容器/`sandbox-exec`，还是维持「对非对抗 LLM 足够」的现状。
- **ALLOWED_TOP 演进**：harness 若合法地需要新顶层目录（如 `data/` 内部缓存），白名单与钩子的升级流程。
- **jail 误伤的可观测性**：被拒的合法操作如何回流为「误伤率」指标以便调 `_TRACE_REF`/token 规则。

## Future possibilities

- 把三道防线的拦截事件计数进观测看板，量化「泄漏尝试率」，作为 harness 是否在过拟合的信号。
- 钩子从「顶层白名单」升级为「内容级」检查（如禁 `import` 被测项目、禁 `pyproject.toml` 新增依赖）。
- 用 OS 级沙箱替换静态扫描，消除动态路径缺口。

