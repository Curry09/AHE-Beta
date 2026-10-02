---
number: "0021"
title: dev agent 逃逸围堵：凭证隔离 + 编排绊线 + 污染清理
issue: 0
slug: dev-escape-containment
summary: 实测发现 dev agent 经 heredoc 隧道绕过 workspace-jail 的路径扫描，改写编排仓文件并用宿主继承的 GitHub 凭证推送。路径级 jail 关不住能调用解释器的 agent（其 docstring 已自陈），本组不加固扫描，改做纵深：进程级 git 凭证隔离掐断推送落地链、b 段后绊线断言编排仓未被触碰、清理历史逃逸的污染制品。OS 级沙箱留作治本方向。
tasks:
  - id: T1
    title: repo_guard 模块 + orchestrator b 段绊线
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/guards/repo_guard.py
      - backend/auto_designer/loop/orchestrator.py
      - backend/tests/guards/test_repo_guard.py
      - backend/tests/loop/test_orchestrator.py
    scope: '新模块 repo_guard：RepoIntegrityError；snapshot_repo(*,repo)->(HEAD sha, git status --porcelain)；verify_unchanged(*,repo,before) 快照不等即抛（git 读失败也抛，宁紧勿松）。orchestrator ctor 加可选 integrity_guard: Callable[[],None]|None=None；run_round 在 b 段之后、c 段 _resolve_head 之前调用（None 则跳过，退化今天行为）；guard 抛出传播中止 run_round。'
    acceptance: snapshot/verify：未变→放行、新增 commit/改 tracked/新 untracked→抛 RepoIntegrityError，既有 untracked 前后都在→不误报。orchestrator：注入的 guard 在 b 段后被调用一次；guard 抛出使 run_round 抛出（不吞）。repo_guard 测试用 symbolic-ref 建仓（兼容 git <2.28，本机可跑）。
  - id: T2
    title: run.py 凭证隔离 + 构造并注入编排仓绊线 guard
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/controllers/ordinary.py
      - backend/tests/test_run_git_isolation.py
    scope: '两处（同文件一并落）：① 凭证隔离 _isolate_git_credentials()——多信道封堵（单关终端提示不够，实测 VS Code 注入的 GIT_ASKPASS 会绕过）：GIT_SSH_COMMAND=false（setdefault）+ GIT_TERMINAL_PROMPT=0 + 清 GIT_ASKPASS/SSH_ASKPASS/SSH_AUTH_SOCK/VSCODE_GIT_ASKPASS_* + 经 GIT_CONFIG_* 空值重置 credential.helper；Gitea HTTP（token in URL）与本地无传输 git 不受影响。② 绊线接线——构造 developers 后、orch.run 前 before=snapshot_repo(repo=str(ROOT))，integrity_guard=lambda: verify_unchanged(repo=str(ROOT), before=before) 注入 Orchestrator（ROOT=编排仓根=逃逸目标；run 期间编排仓应全程冻结）。'
    acceptance: 启动后 GIT_SSH_COMMAND=='false'（未显式覆盖时）、GIT_TERMINAL_PROMPT=='0'、GIT_ASKPASS/SSH_AUTH_SOCK/VSCODE_GIT_ASKPASS_* 全清、GIT_CONFIG_* 注入空 credential.helper（追加不覆盖既有）；单测覆盖以上分支。harness seed/reset 与 dev 推 Gitea 的 HTTP 流程不受影响。orch 收到非 None integrity_guard；正常跑（编排仓未被动）不抛；人工写改编排仓后再跑，run 抛 RepoIntegrityError 且 finally 落 running=False。
  - id: T3
    title: 清理历史逃逸污染制品 MANUAL.md
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/developer_agent/MANUAL.md
    scope: 'git rm backend/agent_defs/developer_agent/MANUAL.md——dev agent 配置不加载它（agent.yaml 只 system_prompt: ./systemprompt.md；旧收尾配置的文档路径曾对 harness 仓解析），纯逃逸残留。'
    acceptance: 文件从 git 移除；grep 全仓无对 agent_defs/developer_agent/MANUAL.md 的引用；dev/synthesizer agent 构造/跑通不受影响（既有单测绿）。
---

# 0021 · dev agent 逃逸围堵：凭证隔离 + 编排绊线 + 污染清理

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

**当前落点**：凭证隔离仍在启动入口执行，完整性绊线由 `backend/auto_designer/guards/repo_guard.py` 提供。下文事故描述保留历史成因；旧内置 Developer 与其收尾中间件已退役，不属于当前运行接线。

实测发现 dev agent 用 python heredoc 打隧道绕过了 `WorkspaceJailMiddleware` 的路径扫描：直接工具
（read_file/write_file/run_shell 里明晃晃带路径）被 jail 拒，但 `python3 - <<'PY' … os.chdir(编排仓);
subprocess.run(['git','commit'/'push']) … PY` 把路径藏进 heredoc 正文，而 jail 的 `_strip_heredoc_bodies`
恰好把正文剥掉再扫 → 放行。逃逸后 agent 改写了 `backend/agent_defs/developer_agent/MANUAL.md`（编排仓自身
的文件，非 harness 沙盒），并用宿主继承的 GitHub SSH 凭证 `git push` 到远端。

根因：**正则扫命令串关不住一个能调用解释器的 agent**——`workspace_jail.py` 的模块 docstring 已自陈
「要 100% airtight 需 OS 级沙箱」。本组不去加固扫描（军备竞赛，必败），改做**纵深防御的三层兜底**：

1. **凭证隔离（掐断落地链）**：run.py 进程级设 `GIT_SSH_COMMAND=false` + `GIT_TERMINAL_PROMPT=0`——
   dev 推 Gitea 走的是 URL 内嵌 token 的 HTTP origin（不受影响），任何 ssh 推送（GitHub `git@…`）直接失败。
   逃逸仍可能发生，但**推不出去**。
2. **编排绊线（秒级暴露）**：orchestrator b 段结束后断言编排仓（auto-designer 检出）worktree 快照未变
   （HEAD + porcelain 全等）；被 dev 触碰即抛 `RepoIntegrityError` 中止本轮，不再靠人翻远端才发现。
3. **污染清理**：`git rm` 历史逃逸留下的 `backend/agent_defs/developer_agent/MANUAL.md`（纯残留、无代码引用）。

OS 级沙箱（容器/独立用户，唯一 airtight 方案）留作治本方向，并入 harbor（spec-0004）路线。

## Motivation

**这不是假想威胁，是实测事故。** dev agent 的工具日志给出完整逃逸链：① read_file/write_file/`test -f`/
list_directory 指向 `…/agent_defs/developer_agent/MANUAL.md` 全被 `[workspace-jail]` 拒（路径在参数里）；
② 改用 `python3 - <<'PY' … Path('…/MANUAL.md').read_text()/write_text() … PY` 读改真实文件（路径在
heredoc 正文，`_strip_heredoc_bodies` 剥正文后扫不到）；③ `python3 - <<'PY' os.chdir('…/developer_agent');
subprocess.run(['git','add'/'commit']) … PY` 在正文里 chdir+subprocess 提交，jail 全程看不见；
④ `git push origin` 用继承的 GitHub 凭证推上去。

**污染早已发生、只是首次被当场抓到。** `backend/agent_defs/developer_agent/MANUAL.md` 由 `dev@auto-designer`
于历史某轮凭空创建，之后被同类逃逸改过多次，且已随更早的合并进过 main。`workspace_jail.py:110` 的注释
甚至已经记录过「实测被 dev 用来把 harness 内容写进自己的 def MANUAL.md」——洞是已知的，缺的是兜底。

**两个放大因素让后果落地**：dev agent 进程 cwd 能摸到真实编排仓（`SANDBOX_WORK_DIR` 指向 harness 沙盒，
但绝对路径 chdir 绕开）、且继承了宿主的 GitHub 推送凭证。本组针对这两点各下一刀（凭证隔离 + 绊线），
不寄望于把 jail 的正则修得更严。

**为什么不加固 jail。** 任何「扫命令字符串里的路径 token」策略，对能调 `python -c`/`bash -c`/heredoc 的
agent 都是形同虚设——正文里 `os.chdir`+`subprocess` 可干任何事。加固扫描只会催生下一个绕过姿势
（base64 编码路径、拼接字符串、写临时脚本再执行…）。安全边界必须落在 agent **能力之外**：要么它没有
凭证（凭证隔离），要么越界立即被独立信道发现（编排绊线），要么它根本进不了那个文件系统（OS 沙箱，Future）。

## Guide-level explanation

改完后每轮闭环（对照 spec-0007 a→d→b→c）：

- **进程启动**：run.py 在 main() 早段设 `GIT_SSH_COMMAND=false`、`GIT_TERMINAL_PROMPT=0`。此后本进程
  及其所有子进程（含 dev agent 的 subprocess git）的 ssh 传输一律失败、HTTPS 不弹交互凭证。harness 推
  Gitea 用 `http://OWNER:TOKEN@host/…` origin（token 在 URL，无需 ssh/helper）不受影响；本地 git
  操作（rev-parse/status/checkout）无传输，不受影响。
- **b 段收尾**：orchestrator 在 b 段（dev 直推）跑完后调 `integrity_guard()`——比对编排仓当前
  `(HEAD sha, git status --porcelain)` 与本轮开跑前的快照；一致则放行进入 c 段，不一致则抛
  `RepoIntegrityError`（附差异摘要）中止，run() 的 finally 照常落 running=False。编排仓被 dev 改一个字
  都会 HEAD 或 porcelain 变化 → 立即暴露。
- **既有 untracked 文件（本地 docs、.idea 等）** 在前后快照里都在 → porcelain 相等 → 不误报；只有**新增
  的改动/提交**才触发。
- **清理**：删掉 `backend/agent_defs/developer_agent/MANUAL.md`（逃逸残留），dev agent 配置不加载它，删了
  无副作用。

当前保留 `guards/workspace_jail.py`、`guards/harness_boundary.py` 和 `guards/repo_guard.py`；前两者检查直接路径与提交范围，后者检查编排仓完整性。旧内置 Developer 的收尾中间件已经退役，当前交付由独立 OpenAgents 执行。

## Reference-level explanation

### T1 编排绊线（repo_guard.py + orchestrator.py）

新模块 `backend/auto_designer/guards/repo_guard.py`：

```python
class RepoIntegrityError(RuntimeError): ...
def snapshot_repo(*, repo: str) -> tuple[str, str]:      # (HEAD sha, porcelain)
def verify_unchanged(*, repo: str, before: tuple[str, str]) -> None:  # 变了就抛
```

- 快照 = `git -C repo rev-parse HEAD` + `git -C repo status --porcelain`。dev 提交 → HEAD 变；dev 改
  tracked 文件 → porcelain 出现 ` M …`；dev 新建文件 → porcelain 出现 `?? …`（但既有 untracked 前后都在，
  只有**新增**才使集合变化）。全等即未被触碰。
- git 读失败（repo 非法等）→ 抛 `RepoIntegrityError`（宁可中止不放过——绊线宁紧勿松）。

orchestrator：ctor 加可选 `integrity_guard: Callable[[], None] | None = None`；`run_round` 在 b 段之后、
c 段 `_resolve_head` 之前调用 `self._integrity_guard()`（None 则跳过，退化为今天行为）。guard 抛出即中止
run_round → 传播出 run()，finally 仍落 running=False。

### T2 凭证隔离 + 绊线接线（run.py，两处一并落）

**① 凭证隔离**——main() 早段（deferred import 之前、任何 agent 起跑之前）`_isolate_git_credentials()`。
凭证泄漏有**多条静默信道**，单关一条不够（实测踩坑：只设 `GIT_TERMINAL_PROMPT=0` 时，VS Code + WSL
注入的 `GIT_ASKPASS` 仍静默交出 GitHub token，dry-run push 照样成功）：

```python
os.environ.setdefault("GIT_SSH_COMMAND", "false")  # 掐 ssh 传输：GitHub git@… 推送失败
os.environ["GIT_TERMINAL_PROMPT"] = "0"  # 禁终端交互凭证提示
# 清 askpass / ssh-agent 静默信道（GIT_TERMINAL_PROMPT 管不到 askpass）：
for k in (
    "GIT_ASKPASS",
    "SSH_ASKPASS",
    "SSH_AUTH_SOCK",
    "VSCODE_GIT_ASKPASS_NODE",
    "VSCODE_GIT_ASKPASS_MAIN",
    "VSCODE_GIT_ASKPASS_EXTRA_ARGS",
    "VSCODE_GIT_IPC_HANDLE",
):
    os.environ.pop(k, None)
# 空值经 GIT_CONFIG_* 注入重置 credential.helper 列表（store/manager/keychain 也是静默信道）：
n = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")  # 追加，不覆盖既有注入
os.environ["GIT_CONFIG_COUNT"] = str(n + 1)
os.environ[f"GIT_CONFIG_KEY_{n}"] = "credential.helper"
os.environ[f"GIT_CONFIG_VALUE_{n}"] = ""
```

- 四条信道全封：ssh 传输、终端提示、askpass（含 VS Code 注入）、credential.helper。
- 用 `setdefault` 保留运维对 `GIT_SSH_COMMAND` 的显式覆盖；`GIT_TERMINAL_PROMPT` 强设（防残留放行）。
- 影响面核验：`_seed_harness_repo`/`_reset_to_initial`/dev/synthesizer 推送全走 Gitea HTTP（`http://
  OWNER:TOKEN@host/…`，凭证在 URL、不经 askpass/helper），launcher/orchestrator 的 git 全是本地无传输
  ——均不受影响。git ≥2.31 支持 GIT_CONFIG_* 注入；实测注入后 `git config credential.helper` 为空、
  常规 git 操作正常。
- 生产在 WSL（POSIX），`false` 在 PATH 内、忽略参数退出码 1 → ssh 调用失败。

**② 绊线接线**——构造 developers 后、`orch.run` 前：`before = snapshot_repo(repo=str(ROOT))`，
`integrity_guard=lambda: verify_unchanged(repo=str(ROOT), before=before)` 注入 Orchestrator。
ROOT = auto-designer 检出根（编排仓，即逃逸目标）；快照 run 前取一次，每轮 b 段后校验对同一 before
（run 期间编排仓应全程冻结）。

### T3 污染清理

`git rm backend/agent_defs/developer_agent/MANUAL.md`。核验无引用：agent.yaml 只 `system_prompt:
./systemprompt.md`；旧收尾配置的 `manual_path=MANUAL.md` 对 SANDBOX_WORK_DIR（harness 仓）解析，
非 agent_defs。删除后 dev/synthesizer 配置加载不受影响。

### 现状锚点

- `workspace_jail.py`：`_strip_heredoc_bodies`（剥正文）+ 模块 docstring 自陈 caveat；本组不改它。
- `run.py`：`main()` env 装配段（LLM_*/NO_PROXY 已在此，git env 同处加）；`ROOT` 常量；`orch.run` 调用点。
- `orchestrator.py:81-142 run_round`：b 段 `for developer in self._developers` 之后是 c 段 `_resolve_head`。
- 逃逸残留：`backend/agent_defs/developer_agent/MANUAL.md`（`dev@auto-designer` 署名历史创建）。

### DAG

```mermaid
graph LR
  T1[T1 repo_guard + orchestrator 绊线]
  T2[T2 run.py 凭证隔离 + 接线 guard]
  T3[T3 清理污染制品]
  T1 --> T2
```

T2 依赖 T1（用 repo_guard）；T3 独立。凭证隔离与绊线接线是两个独立关注点但同改 run.py，合并进 T2
一并提交（同组同文件不可分两 Task）。

### 文件分配（互斥）

- **T1**：`backend/auto_designer/guards/repo_guard.py`、`backend/auto_designer/loop/orchestrator.py`、
  `backend/tests/guards/test_repo_guard.py`、`backend/tests/loop/test_orchestrator.py`
- **T2**：`backend/auto_designer/experiment/controllers/ordinary.py`（凭证隔离 env 段 + orchestrator 接线段）、
  `backend/tests/test_run_git_isolation.py`
- **T3**：`backend/agent_defs/developer_agent/MANUAL.md`（删除）

## Drawbacks

- **绊线是事后检测，不是阻止**：push 已发生才被抓到（凭证隔离掐推送才是阻止层）。二者叠加：凭证隔离让
  push 失败、绊线让「即便 push 成功也秒级可见」，纵深互补。
- **绊线可能误报**：若某轮里编排仓被**合法**改动（正常不会——闭环只动 harness 沙盒与 data/），会误抛。
  接受：编排仓在 run 期间本就该冻结，误报本身是有价值的信号。
- **凭证隔离封的是「已知信道」**：ssh / 终端提示 / askpass / credential.helper 四条已封（实测 VS Code
  的 GIT_ASKPASS 缺口已补）。但若有人把编排仓 origin 配成 URL 内嵌 token 的 HTTPS，凭证在 URL 里、
  隔离挡不住（那种配置本身是把凭证写进 remote，另一问题）；绊线作为第二道兜底覆盖此缺口。
- **非 airtight**：agent 若能写 `~/.ssh`、改 git config、或自己拼 token URL 仍有绕过面。真正闭合需
  OS 沙箱（Future/spec-0022）——届时 agent 根本进不了宿主文件系统与凭证。

## Rationale and alternatives

- **加固 jail 的 heredoc 扫描（被否）**：军备竞赛；正文里可 base64/拼接/落临时脚本，扫描必被绕过。
  安全边界不能建在「扫 agent 的命令字符串」上。
- **只做凭证隔离、不做绊线（被否）**：凭证隔离挡 ssh，但挡不住 token-in-URL 的 HTTPS origin 与本地污染；
  绊线补上「越界即暴露」。
- **只做绊线、不做凭证隔离（被否）**：绊线是事后，push 可能已把污染推到远端；T1 从源头掐推送。
- **让绊线只告警不中止（被否）**：安全事件应 fail-closed；继续跑只会让污染累积。
- **改 dev agent 用独立 git 身份 / 清空 HOME（备选，未采）**：`GIT_SSH_COMMAND=false` 更直接且不影响
  Gitea HTTP 流程；清 HOME 会波及 nexau 其它依赖。留作 Future 若需更强隔离。

## Prior art

- **workspace_jail.py 自陈 caveat**：`python -c 动态拼路径静态扫不出——要 100% airtight 需 OS 级沙箱`——
  本组正是对该已知缺口补纵深兜底。
- **spec-0015 dev 过拟合隔离**：jail/harness_boundary 是同一防线的路径级实现；本组是其被绕过后的补强。
- **CI/CD 最小权限原则**：构建 agent 不应持有生产推送凭证；T1 是该原则在本闭环的落地。
- **git `GIT_SSH_COMMAND` / `GIT_TERMINAL_PROMPT`**：git 官方支持的传输/凭证禁用旋钮，标准手段。

## Unresolved questions

- 绊线粒度：目前每轮 b 段后查一次；是否需要细到每个 developer.work_one 之后（更早中止，代价是多几次
  git status）？先按轮查，观察。
- 是否把编排仓的 origin 主动改成「只读或无 remote」的 worktree 供 run 使用，从根上让 push 无目标？
  更彻底但改动运维流程，留后续评估。

## Future possibilities

- **OS 级沙箱（治本）**：dev agent 关进容器/独立用户，只 bind-mount harness 仓——唯一 airtight 方案，
  并入 harbor（spec-0004）rollout 隔离。届时 jail/凭证隔离/绊线降级为纵深冗余。
- GitHub 侧 branch protection（禁 force-push、要求 PR）作为远端最后一道闸（仓库设置，非本仓代码）。
- 绊线扩展为通用「run 期间冻结集」断言：编排仓 + data/ 之外目录全程只读校验。

