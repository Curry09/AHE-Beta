---
number: "0032"
title: 开发者侧换轨 OpenAgents：需求面/交付面二分 + Gitea forge 适配
issue: 0
slug: openagents-gitea-dev-plane
summary: 现行开发者侧是过渡实现（spec-0025/T5 自述）：nexau dev 领 ready 票后直推 main，无分支/PR/评审/CI，坏 commit 只能靠后续多轮迭代回正；且多 dev 因同仓 push 互斥只能串行。OpenAgents（RFC 驱动多 agent 交付框架，独立仓）已把「issue→分支/worktree→spec→PR→CI→评审→合并」的交付闭环打磨成一个 level-triggered 守夜人（vigil），其执行面入口恰好与我方三平面（spec-0029）的终点同名同义——双方都以 `ready` label 为唯一工作队列白名单。本 spec 把接缝切在准入这一刀上：ahe-beta 保留需求面（用户模拟→证据→提案→Owner 唯一准入），OpenAgents 接管交付面（ready→PR→合并），两系统仅通过 issue 标签与 main SHA 交互、零代码耦合。职责裁决：OpenAgents 的 triager/admitter 停用（准入职责已归 Owner，`stages.triage=skip`）、curator/drafter/implementer/reviewer/deliver/merger/replier 接管交付面；我方 AgenticDeveloper + developer_agent 整体退役，orchestrator 删 dev 拍（c 步回灌 main SHA 语义不变，天然兼容 PR 合并模型）。平台约束：本仓基建在本地 Gitea（spec-0002），而 OpenAgents 的 utils/github.py 全绑 gh CLI——故 OpenAgents 仓新增 forge 分发层（alias-import 零 call-site 改动）+ Gitea REST driver（checks→commit status、blocked_by→issue dependencies、draft→WIP 前缀、merge/update→Gitea pulls API 等语义映射）。直推 trunk 升级为 PR 门禁不违反 held-out 约束：CI/评审是工程质量闸（harness 仓冒烟，绝不跑 benchmark），体感仍纯观测、benchmark 全程 held-out。vK tag 体系退役，观测锚点=merge commit。
tasks:
  - id: T1
    title: OpenAgents 仓：forge 分发层——alias-import 接缝 + 配置段 + merger 提示词参数化
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - OpenAgents/openagents/utils/forge.py
      - OpenAgents/openagents/utils/agent_config.py
      - OpenAgents/openagents/recipes/vigil.py
      - OpenAgents/openagents/recipes/stages.py
      - OpenAgents/openagents/recipes/backfill.py
      - OpenAgents/openagents/runtime/gates.py
      - OpenAgents/openagents/runtime/context.py
      - OpenAgents/openagents/utils/identity.py
      - OpenAgents/openagents/utils/release.py
      - OpenAgents/openagents/cli.py
      - OpenAgents/openagents/agents/merger.py
      - OpenAgents/tests/test_forge.py
    scope: 新建 utils/forge.py 分发模块：读 `.openagents/openagents.yml` 新增的 `forge=github|gitea` 段（缺省 github，存量用户零感知），按配置 import 对应 driver 模块并以 `__getattr__` 委托全部公共名。改线走 alias-import：8 个消费文件（vigil/stages/backfill/gates/context/identity/release/cli）把 `from ..utils import github` 改为 `from ..utils import forge as github`，全部 `github.xxx()` call site 零改动。agent_config.py 加 `forge` 段 schema（gitea 需 base_url/owner/repo/token_env 四键，token 本体只从环境变量读——延续「不存 token」纪律）。merger 提示词的 `gh pr merge` / `gh pr view` 硬编码改为 `$merge_command` / `$verify_command` 占位符，由派发处（vigil）经 forge 提供的命令文本注入（github driver 给 gh 命令、gitea driver 给等价 REST/tea 指令或改由 stage 机械落合并，取舍见正文 §Unresolved）。全仓 prompt 扫一遍 gh 引用一并参数化。本任务在 OpenAgents 仓按其 spec 流程另立对应 spec 落地，此处为镜像描述。
    acceptance: forge 缺省回落 github、既有测试全绿（存量零回归）；`forge=gitea` 时 forge.* 解析到 gitea driver；merger PROMPT 无 gh 字面量；hermetic 测试不触网。
  - id: T2
    title: OpenAgents 仓：Gitea REST driver——github.py 同名公共面对 Gitea /api/v1
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - OpenAgents/openagents/utils/gitea.py
      - OpenAgents/tests/test_gitea_driver.py
    scope: 新建 utils/gitea.py，实现 vigil 新栈实际消费的 github.py 公共面（函数清单见正文 §4.2，约 28 个函数 + Issue/PR/Comment/CheckStatus/Mergeability/PRSnapshot/CheckSnapshot/Blocker 数据类直接复用 github.py 定义），全部打 Gitea /api/v1（stdlib urllib，不给 OpenAgents 加 requests 依赖；瞬时错误指数退避骨架对齐 github.py）。语义映射：checks→commit combined status（/commits/{ref}/status）；mergeable→PR.mergeable bool（false→DIRTY，Gitea 异步计算期→UNKNOWN 收敛策略见正文）；draft→标题 WIP 前缀（mark_ready=去前缀 PATCH）；blocked_by→issue dependencies API；merge_pr→POST /pulls/{index}/merge；update_branch→POST /pulls/{index}/update；close 联动→PR 正文 closing keywords（Gitea 原生支持）；ensure_prerequisites→token 存在 + API 可达 + repo 可写预检（取代 gh auth status）。凡 1.22 端点实证不符处以最小语义降级并在 driver 注释记录（见 §Unresolved 实证清单）。
    acceptance: 假 HTTP 层 hermetic 测试覆盖全部公共面函数的请求形状与响应解析；语义映射逐条有测试（含 mergeable 三态收敛、WIP 前缀往返、zero-status 与 zero-check 等价）；对本仓 deploy/gitea 起的真 Gitea 1.22 手工冒烟一轮（建 issue→打 label→开 PR→merge→issue 自动关）。
  - id: T3
    title: 准入交接：Owner 改打 openagents 发现标签，plane READY 收编 {ready, openagents}
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/issue_schema.py
      - backend/ahe_beta/demand/owner.py
      - backend/tests/demand/test_issue_schema.py
      - backend/tests/demand/test_owner.py
    scope: issue_schema 新增 `OPENAGENTS = "openagents"`（交付面发现标签，Owner 准入的交接令牌）；plane() 的 READY 平面判定收编为 `ready | openagents`（准入已定、交付面接手中/已接手都算工作队列）；is_ready 随 plane 自动生效（本方案后仅剩 metrics/web 读侧消费）。owner.py `_ready_labels` 改产出 OPENAGENTS（不再直接打 READY）——原因：vigil `_intake` 对已带 ready 的票直接跳过，curator 依赖排序只在「本轮有新准入」时触发，Owner 直打 ready 会让 curator 永不运行、多 worker 并行失去 blocked_by 保护。covers 级联合并/decline/hold 语义全部不动（Owner 仍是唯一准入点）。背压 READY_DEPTH_ALARM 经 plane 自动覆盖两标签。
    acceptance: admit 后 issue 带 openagents 且 plane==READY；vigil 盖 ready 后 plane 仍 READY（幂等）；covers 级联回归测试不变绿；老标签映射不回归。
  - id: T4
    title: dev 侧退役：AgenticDeveloper/developer_agent 删除，orchestrator 去 dev 拍
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/dev/agentic_developer.py
      - backend/agent_defs/developer_agent/agent.yaml
      - backend/agent_defs/developer_agent/systemprompt.md
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/loop/roster.py
      - backend/ahe_beta/loop/live_tracer.py
      - backend/tests/dev/test_agentic_developer.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_parallel_sessions.py
      - backend/tests/loop/test_roster.py
    scope: 删除 dev/agentic_developer.py 与 agent_defs/developer_agent/ 整目录（职责落入 OpenAgents implementer+deliver+merger）。orchestrator：ctor 去 developer_agents 参数，run_round 删 dev 串行拍；c 步回灌保持「main 最新 HEAD SHA 纯观测游标」原样（spec-0007 语义，谁推进 main 都兼容——本方案后推进者是 vigil 的 merge）。roster：developer 数改语义为「交付面并发 K」（映射 vigil --parallel，默认 1），键名保留 developer 以兼容 env N_DEVELOPERS。测试同步：test_agentic_developer 删除，orchestrator 测试改为断言无 dev 拍且 c 步读 SHA，roster 测试改新语义。
    acceptance: 全量后端测试绿；orchestrator run_round 仅含 a 两拍生成 + Owner 准入 + c 步；仓内无 AgenticDeveloper 引用残留（grep 零命中）。
  - id: T5
    title: vigil 接线：run.py 写 openagents.yml、管 vigil 子进程生命周期、vK tag 退役
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/ahe_beta/experiment/controllers/swebench.py
      - backend/tests/test_run_vigil.py
    scope: run.py：种子推送后在 HARNESS_REPO 写 `.openagents/openagents.yml`（forge=gitea + deploy/gitea 的 base_url/owner/repo/token_env、stages 定稿 triage=skip / rfc=skip(起步，显式告警可接受) / conflict=agent / ci=skip(T6 就位后改 agent) / e2e=skip / review=agent / merge=agent、labels=[openagents]、interval=30、release=manual）；以 subprocess.Popen 启动 `openagents vigil --parallel K`（cwd=HARNESS_REPO，K=roster developer 数，stdout/stderr 落 data/vigil.log），run 退出时 terminate+wait 兜底 kill。openagents 以独立 CLI 接入（uv tool install 钉版本，不 vendor 不 import，见正文 §4.3 部署形态），run.py 启动前预检 `openagents` 命令存在。vigil 的本地状态（.openagents/ 下 sqlite 队列、claims flock、runtime-state）随 _seed_harness_repo 的 rmtree 每次 run 自然重置，无跨 run 脏状态。退役 vK tag 全链路：dev 预算 env（DEV_BUDGET_*）、_next_version/ls-remote tags 逻辑、banner 文案更新。平台注记：vigil 依赖 fcntl.flock，交付面仅 Linux/macOS 可跑（生产环境 Linux 满足）；Windows 本地只跑单测。凭证注记：交付面 coding 后端是 claude CLI（OpenAgents claude_code backend），DEV_LLM_* 不再消费，宿主需登录 claude CLI；Gitea token 经 GITEA_TOKEN env 传给 vigil 子进程。
    acceptance: 单测（mock Popen）断言 yml 内容与 stages 定稿一致、vigil 启停与日志路径正确、异常退出有兜底；banner/预算 env 无 vK 残留；Linux 生产环境手工冒烟一轮闭环（Owner admit → vigil 开 PR → merge → c 步游标前移）。
  - id: T6
    title: harness 仓最小 CI：Gitea Actions runner + 冒烟 workflow
    status: done
    priority: P2
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: true
    files:
      - backend/deploy/gitea/docker-compose.yml
      - backend/deploy/gitea/bootstrap.sh
      - backend/harness_template/.gitea/workflows/smoke.yml
    scope: docker-compose 开 GITEA__actions__ENABLED=true 并加 act_runner 服务（注册 token 走 bootstrap.sh）；harness_template 随种子带 .gitea/workflows/smoke.yml——最小冒烟：起 entry 子进程、发一条固定消息、断言回一行合法 JSON reply（不跑 benchmark、不调真 LLM，用 stub 模型 env）。ci 闸经 env `VIGIL_CI_STAGE=agent` 切换开启（缺省 skip——vigil 判定表第⑦条「零 check=永等 CI」，须先在部署环境实证 act_runner 真在跑再开，bootstrap.sh 有提示；比「随任务硬切 agent」多一步实证，防止 runner 未就绪时全部票卡到看门狗）。
    acceptance: push 到 Gitea 后 commit status 可见且 smoke 绿；红 CI 的 PR 被 vigil 派 implementer 打回（fix-ci 路径手工验证一次）；VIGIL_CI_STAGE 覆盖有单测；部署实证后置 agent。
  - id: T7
    title: 交付面观测：GiteaTracker PR 读路径 + web API + 前端交付面视图
    status: done
    priority: P2
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/tracker/gitea.py
      - backend/ahe_beta/web/api.py
      - backend/tests/web/test_api.py
      - frontend/src/types.ts
      - frontend/src/api.ts
      - frontend/src/lib/issueMeta.ts
      - frontend/src/App.tsx
      - frontend/src/components/SidePanel.tsx
      - frontend/src/components/DeliveryPanel.tsx
    scope: GiteaTracker 加观测读路径 list_pulls（号/标题/状态/关联 issue/head 分支/mergeable/labels，纯读）。web/api overview 加 delivery 段（open PR 列表 + needs-human 票数告警）。前端：developer 列退役，新增交付面面板（PR 卡片：票号→PR→状态；needs-human 积压高亮——无人值守环里这是唯一需要人清的死票队列）。funnel/plane 展示随 T3 的 READY 收编自动正确。
    acceptance: api 测试覆盖 delivery 段形状；前端 tsc+build 绿；needs-human>0 时面板有显式告警态。
  - id: T8
    title: 文档收尾：CLAUDE.md 架构段与 spec 制品再生成
    status: done
    priority: P2
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: true
    files:
      - CLAUDE.md
    scope: CLAUDE.md 架构段更新：开发者侧描述从「带 git 工具的 nexau agent 直推 main」改为「OpenAgents 交付面（vigil）：Owner 准入的 ready 票经分支/PR/CI/评审合并进 main；CI/评审为工程质量闸，体感仍纯观测、benchmark 全程 held-out 不变」；目录结构表 dev/ 条目更新。OVERVIEW/ARCHITECTURE 随 spec render/graph 再生成。
    acceptance: CLAUDE.md 与实况一致；spec validate/render/graph 全绿无 drift。
---

# 0032: 开发者侧换轨 OpenAgents：需求面/交付面二分 + Gitea forge 适配

## Summary

把闭环切成**需求面**与**交付面**两半：ahe-beta 保留需求面（用户模拟 → 证据 → 提案 → Owner 唯一准入），OpenAgents 接管交付面（ready issue → 分支/worktree → PR → CI → 评审 → 合并）。两个系统**只通过 issue 标签和 main SHA 交互**，零代码耦合。平台保持本地 Gitea：OpenAgents 仓新增 forge 分发层与 Gitea REST driver（alias-import 零 call-site 改动）。我方 nexau 开发者（AgenticDeveloper + developer_agent）整体退役，直推 main 升级为 PR 门禁交付；orchestrator 的 c 步回灌（main 最新 SHA 纯观测游标）语义不变。

## Motivation

**现行 dev 是自述的过渡实现**（spec-0025/T5：「dev 侧为过渡实现，后续换仓 agent 接入时再完善」）：领票后 checkout main → 改文件 → commit → tag → push，一把梭直推。三处结构性短板：

1. **无质量闸**：坏 commit 直接落 main，只能靠后续多轮迭代回正（梯度下降式）。这在小步长下可行，但没有任何机制阻止一次大破坏（比如把 entry 改崩），之后每一局用户会话都在崩的 harness 上白跑。
2. **无真并行**：多 dev 同仓推 main 互斥，只能串行（orchestrator dev 拍逐个 work_one）。
3. **无工程闭环**：没有分支/PR/评审/CI/冲突处理的概念，issue→交付的中间态不可见、不可干预。

OpenAgents（独立仓，RFC 驱动多 agent 交付框架）已把这条交付链打磨了 60+ 个 spec：level-triggered reconcile 调度（判定表纯函数、丢任意轮次可自愈）、worktree 隔离真并行、head-advanced/evidence-stamp/round-cap 确定性硬闸防 agent 空转撒谎、needs-human 一等出口。**重造这条链是最大的浪费；接上它才是正解。**

接入的两个前提问题，恰好都有干净答案：

- **职责重叠怎么裁**：OpenAgents 自带准入面（triager 分诊 / admitter 人闸 / curator 排依赖），与我方三平面（spec-0029）的 triager/Owner 重叠。裁决原则：**准入职责已归 Owner（三平面唯一准入不动摇），OpenAgents 准入面停用（`stages.triage: skip`），只留无重叠的 curator**（依赖排序，我方没有，且是并行交付缺的能力）。
- **平台怎么接**：OpenAgents 的 `utils/github.py`（全部 gh CLI 封装）是唯一的平台咬合点，且消费方全走模块函数调用——一个 forge 分发层 + Gitea driver 即可换轨，编排层 195KB 的 vigil 一行业务逻辑都不用动。

## Guide-level explanation

### 二分模型

```
┌─ 需求面（ahe-beta，round-based）────────────────┐
│ user sim ──报告──▶ report 平面                        │
│ triager/architect/divergent ──提案──▶ proposal 平面  │
│ Owner 唯一准入（admit/merge/decline/hold + covers 级联）│
│        │ admit = 打 `openagents` 发现标签              │
└────────┼─────────────────────────────────────────────┘
         ▼  接口①：issue 标签（Gitea issue 为总线）
┌─ 交付面（OpenAgents vigil，level-triggered 常驻）─────┐
│ _intake：发现 openagents 票 → triage:skip 直接盖 ready │
│          → curator 排 blocked_by 依赖边               │
│ 执行面：worktree/分支 → (rfc) → implement → review 循环│
│          → deliver push → PR → conflict/CI/review 闸  │
│          → merger 合并（Closes #N 自动关票）           │
└────────┼─────────────────────────────────────────────┘
         ▼  接口②：main 最新 SHA
  orchestrator c 步回灌（纯观测游标，spec-0007 语义原样）
```

### 角色裁决表

| 角色 | 归属 | 裁决 |
|---|---|---|
| user sim / triager / architect / divergent / **Owner** | 需求面（我方） | 原样保留，spec-0029 不动 |
| OpenAgents triager（单票矛盾自检） | 交付面准入 | **停用**（`triage: skip`）——准入已由 Owner 在上游完成，双重把关收益趋零 |
| OpenAgents admitter（读人是否点头） | 交付面准入 | 仅 `triage: human` 时启用，无人值守环里**自然闲置** |
| OpenAgents curator（ready 票依赖排序） | 交付面准入 | **采纳**——我方没有的能力，多 worker 并行的 blocked_by 保护 |
| drafter / implementer / reviewer / deliver / merger / replier / tester | 交付面执行 | 接管；tester(e2e) 起步 skip |
| **AgenticDeveloper + developer_agent** | 旧 dev | **整体退役** |

边界一句话：**需求面决定「做什么、先做什么」，交付面决定「怎么做完、何时算完」**；Owner 是仅有的准入裁决者，vigil 是仅有的 main 推进者。

### 准入交接协议（关键细节）

Owner 准入**不直接打 `ready`**，而是打 `openagents` 发现标签。原因：vigil 的 `_intake` 对已带 `ready` 的票直接跳过，而 curator 只在「本轮有新准入」时触发——Owner 直打 ready 会让 curator 永不运行，并行交付失去依赖保护。流转：

```
Owner admit ─▶ +openagents（-proposal，priority 保留）
vigil _intake ─▶ 发现（labels=[openagents]）→ triage:skip → +ready → curator 排边
vigil 执行面 ─▶ list_issues(labels=[ready]) 领活 → … → merge（Closes #N 关票）
```

我方 `plane()` 的 READY 平面判定收编为 `{ready, openagents}`：准入一落地即计入工作队列（metrics funnel、背压告警、前端分组随之自动正确），vigil 随后盖 ready 幂等无感。covers 级联合并仍完整发生在 Owner 准入时；交付面只关自己 `Closes #N` 的票——与 spec-0029「dev 只关自己的票」边界一致。

### 一轮走读（接入后）

1. 需求面照旧：a 两拍生成 → Owner 批量准入，N 张票带上 `openagents`；
2. vigil（常驻，30s tick）下一 tick 发现新票：盖 `ready`、curator 补 blocked_by 边；
3. K 个 worker 领无阻塞票：建 worktree 分支 `openagents/issue-<N>`、实现、评审循环、deliver push、开 PR；
4. 合并流水线：conflict → CI（T6 前 skip）→ review → merge，任一闸失败派 implementer 打回迭代；干不动就打 `needs-human` 留言退出（人定期清）；
5. merge 落 main，`Closes #N` 自动关票；orchestrator 下一轮 c 步读到新 SHA，新 harness 回灌用户侧。

## Reference-level explanation

### §4.1 OpenAgents forge 接缝（T1）

- **分发模块** `utils/forge.py`：读配置一次，`import` 对应 driver（github/gitea），`__getattr__` 委托全部公共名。
- **零 call-site 改动**：消费方共 8 个文件（vigil/stages/backfill/gates/context/identity/release/cli），只改 import 行为 `from ..utils import forge as github`，数百个 `github.xxx()` 调用点原样不动。
- **配置**：`openagents.yml` 新增顶层 `forge` 段；`gitea` 需 `base_url/owner/repo/token_env`，token 本体只从环境变量读（延续「OpenAgents 不存 token」纪律，gh 委托改为 env 委托）。缺省 `github`，存量用户零感知。
- **提示词参数化**：merger 的 PROMPT 硬编码了 `gh pr merge $pr_number --merge` 与 `gh pr view`（agents/merger.py），改占位符由派发处注入 forge 对应命令；全仓 prompt 审计 gh 字面量。
- 数据类（Issue/PR/Comment/CheckStatus/Mergeability/PRSnapshot/CheckSnapshot/Blocker）保留在 github.py，gitea driver 直接 import 复用（import 不触发 gh 调用，安全）。

### §4.2 Gitea driver 公共面与语义映射（T2）

新栈实际消费的函数面（grep 实证，github.py 其余函数不在首批范围）：

issue 侧 `ensure_label / create_issue / get_issue / list_issues / issue_comment / list_issue_comments / issue_add_label / issue_remove_label / close_issue / list_blocked_by / add_blocked_by`；PR 侧 `create_pr / pr_for_branch / list_open_prs / pr_head_branch / pr_snapshot / check_snapshot / check_status / check_logs / list_comments / post_comment / add_label / remove_label / has_label / mark_ready / update_branch / merge_pr / branch_ci_green / code_fingerprint`；预检 `ensure_prerequisites`。

| GitHub 语义 | Gitea 1.22 映射 | 备注 |
|---|---|---|
| checks API（check runs） | commit combined status `GET /commits/{ref}/status` | 状态集 success/failure/pending/error 收敛到 CheckStatus；**零 status 与零 check 等价**（判定表⑦「等待 CI」→看门狗），故 T6 前必须 `ci: skip` |
| mergeable 三态（MERGEABLE/CONFLICTING/UNKNOWN） | PR `mergeable: bool` | false→DIRTY；Gitea 后台计算期的空窗按 UNKNOWN 收敛（保守等待，level-triggered 下一 tick 自愈） |
| draft PR | 标题 `WIP:` 前缀 | `is_draft`=前缀判定，`mark_ready`=PATCH 去前缀 |
| 原生 blocked_by dependencies | issue dependencies API `GET/POST /issues/{index}/dependencies` | curator 落边/`deps_done` 复核走此 |
| `gh pr merge` | `POST /pulls/{index}/merge` | merger 占位符注入（§4.1） |
| update branch | `POST /pulls/{index}/update` | BEHIND 分支前移 |
| PR 正文 `Closes #N` 合并自动关票 | Gitea 原生 closing keywords | 交付面关票机制不变 |
| `gh auth status` 预检 | token 非空 + API 可达 + repo push 权限探测 | ensure_prerequisites 改写 |

实现用 stdlib urllib（OpenAgents 依赖面保持 ruamel.yaml+jsonschema 最小化），重试骨架（瞬时错误指数退避）对齐 github.py。凡 1.22 实证与上表不符，driver 内做最小语义降级并注释记录（实证清单见 Unresolved）。

### §4.3 进程模型与生命周期（T5）

**双进程、双节拍**：需求面 orchestrator 照旧 round-based；交付面 `openagents vigil --parallel K` 为**常驻子进程**（run.py Popen 托管，cwd=HARNESS_REPO，退出 terminate 兜底 kill，日志落 data/vigil.log）。两面无需同步——vigil 是 level-triggered 的，票何时出现何时接；c 步游标永远读 live main。

**世界重置天然干净**：vigil 全部本地态（SQLite work_queue、claims flock、runtime-state）落在 `<repo>/.openagents/`，随 `_seed_harness_repo` 的 rmtree 每次 run 一并归零；Gitea 仓由 bootstrap 重建。这是本地 Gitea 相对 GitHub 方案的一个实际优势（GitHub issue 不可批量删除，每 run 需新建仓）。

**平台/凭证约束**：vigil 用 `fcntl.flock` 判死回收——交付面仅 Linux/macOS 可跑（生产 Linux 满足；Windows 本地只跑单测）。coding 后端是 claude CLI（OpenAgents claude_code backend，nexau backend 未实现、二期补），宿主需登录 claude CLI；`DEV_LLM_*` 退役。Gitea token 经 env 传入 vigil 子进程。

**部署形态**：OpenAgents 以**独立 CLI 工具**接入（`uv tool install --from <OpenAgents 仓>@<pin> openagents`，钉在含 forge/Gitea driver 的 commit/tag），不 vendor 源码进本仓、不作为 Python 包 import——ahe-beta 对它的全部依赖 = 宿主 PATH 上的 `openagents` 命令 + Gitea 标签契约，进程边界天然隔离两侧崩溃。run.py 启动前对 `openagents --help` 做存在性预检、缺失即报错（与 claude CLI 预检并列）。本仓工作区内的 OpenAgents/ 目录只是本地开发副本（T1/T2 在其中按该仓 spec 流程落地），保持 untracked；开发迭代用 `uv tool install --force --from ./OpenAgents` 即时生效（uv tool 为快照，不重装跑旧码）。

### §4.4 stages 定稿与门禁语义

```yaml
forge: gitea
gitea: { base_url: <deploy/gitea>, owner: <bootstrap>, repo: <harness>, token_env: GITEA_TOKEN }
stages:
  triage: skip      # 准入已归 Owner（三平面唯一准入）
  rfc: skip         # 起步：harness 仓无 spec 工具链（显式告警可接受；二期评估引入）
  conflict: agent
  ci: skip          # T6 落地后改 agent（零 check 会永等，见 §4.2）
  e2e: skip         # 二期
  review: agent     # 工程质量闸（review:skip+merge:agent 被 OpenAgents 拒——不许零闸）
  merge: agent
release: manual     # 不用；vK tag 退役，观测锚点=merge commit
defaults: { interval: 30, base: main, labels: [openagents] }
```

**与 held-out 约束的关系**：spec-0005/0007 去掉的是**体感门禁**（防训练信号变发版门禁）；本 spec 带回的 CI/评审是**工程质量闸**（防 harness 仓被改坏），维度不同。harness 仓 CI 只做冒烟（stub 模型、不调真 LLM），**绝不跑 benchmark**；体感仍纯观测、benchmark 全程 held-out，CLAUDE.md 三约束原样成立。「坏 commit 靠多轮迭代回正」升级为「坏 PR 在 CI/reviewer 处打回、不落 main」。

### §4.5 围堵（对照 spec-0021/0022）

- **凭证面不扩大**：交付面全部凭证 = 本地 Gitea token + claude CLI 登录，爆炸半径仍是本机与本地 Gitea（0022 的「无外部凭证」姿态保持；这是否决 GitHub 迁移方案的主因之一）。
- **jail 变弱需正视**：claude_code backend 是 `claude -p` + acceptEdits，靠提示词约束（禁改 .claude/），弱于 nexau workspace_jail 三层兜底。缓解：worktree 隔离天然限定改动面；harness 仓 pre-commit 边界钩子随种子安装（worktree 共享 hooks）继续兜「把被测项目代码写进 harness 仓」类越界；网络出口 allowlist 仍是环境级建议（0022 遗留，不在本 spec 范围）。
- **硬闸恒在**：head-advanced/evidence-stamp/round-cap 是 OpenAgents 确定性硬闸，`skip` 关不掉——「agent 自称做完但没 commit」在交付面同样被机械拦截（对齐我方「仓状态是 ground truth」的旧原则）。

## Drawbacks

1. **双仓维护**：forge 层与 Gitea driver 落在 OpenAgents 仓（按其 spec 流程另立 spec），我仓 CI 无法覆盖，契约漂移靠 OpenAgents 自身测试 + 本仓 T5 冒烟兜。
2. **交付面观测降级**：dev 逐步时间线（StepTracer 流）没了，换成 PR 粒度观测（T7）+ vigil 日志；needs-human 死票需要人定期清。
3. **异构后端**：被进化的 harness 用 nexau，进化它的交付面用 claude CLI——多一个环境依赖（claude 登录），且 dev 行为不再受 DEV_LLM_* 配置控制。
4. **时延**：直推（秒级落 main）变 PR 流水线（分钟级、多轮打回可能横跨多个 tick）；一轮内准入的票未必当轮合并——但 c 步游标语义本就不要求同步，闭环不受影响。
5. **Windows 本地跑不了交付面**（flock）。

## Rationale and alternatives

- **为什么切在准入**：两边模型在 `ready` label 上天然咬合（我方三平面终点 = vigil 执行面入口，同名同义同白名单）；且「issue/标签为总线、无中心消息机制」正是 OpenAgents 的去中心化设计理念，接口零发明。
- **弃案一：harness 仓迁 GitHub（OpenAgents 零改动）**——被平台约束否决：本仓基建在 Gitea（spec-0002），迁移引入外部凭证（违 0022 围堵姿态）、GitHub issue 不可批量删除与每 run 建仓的运维负担、外网依赖。用户裁决保 Gitea。
- **弃案二：薄集成（只借 prompts+engine+backend+worktree，自研 Gitea PR 编排）**——等于在我仓复刻一个 mini-vigil：与 OpenAgents 编排层职责重叠（正是本次要消灭的问题），且丢掉 60+ spec 的韧性积累（防空转指纹、看门狗、硬闸、打回回环），只换来约 10 个提示词文件的复用。
- **为什么 alias-import 而非 forge Protocol 大重构**：vigil 195KB、数百 call site，改 import 行是唯一 O(文件数) 而非 O(调用数) 的方案；分发模块 `__getattr__` 委托保持 github.py 公共面为事实接口契约，不预建抽象（奥卡姆：不为「第三个 forge」付费）。
- **为什么 Owner 打 openagents 而非 ready**：见 §Guide 准入交接——保 curator 存活是唯一原因，否则两标签合一更简。

## Prior art

- OpenAgents 自身 60+ spec（level-triggered reconcile 引 Kubernetes 架构第一原则；「判断归 agent、机械归代码」总纲）——本 spec 全部交付面语义以其现行实现为准，不复述细节。
- spec-0029（三平面单一准入）：本 spec 是其「平面3 工作队列」的消费端换轨，准入模型零改动。
- spec-0007（纯 trunk 直推）：本 spec 承认其「过渡实现」自述并升级交付通道，回灌游标语义原样继承。
- Gitea /api/v1（1.22）：commit status、pulls merge/update、issue dependencies、closing keywords 均为官方 API 能力（T2 实证）。

## Unresolved questions

1. **Gitea 1.22 端点实证清单**（T2 开工首件事）：issue dependencies API 端点形状；PR 响应有无 draft 字段（否则 WIP 前缀方案）；`/pulls/{index}/update` 可用性；combined status 的 error/warning 态映射。以 deploy/gitea 真实例验证为准，spec 映射表随实证微调。
2. **merger 机械化 vs 提示词参数化**：Gitea 下合并动作是否干脆由 stage 代码机械执行（更符合「机械归代码」，但偏离 OpenAgents 0017/T3「生命周期动作归 agent 层 + needs-human 最后出口」的取舍）——T1 实施时与 OpenAgents 仓一起定，本 spec 默认参数化（改动最小）。
3. **rfc 阶段二期是否启用**：给 harness 仓引入轻量 spec 体系（drafter 需要 spec CLI）——对「结构性改进」目标有利，但为被进化对象增加制度负担，观察首月交付质量后再定。
4. **needs-human 清理节奏**：无人值守下积压死票的处理界面（T7 只做告警）；是否给 Owner 增加「读 needs-human 理由 → decline/改写重投」的回收路径，留待运行数据。
5. **nexau backend**：AgentBackend 协议极薄（run(work_dir, task, context)→AgentResult），但 OpenAgents 的「末行 JSON」输出契约需 nexau agent 遵守——二期在 OpenAgents 仓补适配器，恢复 dev 行为可由 DEV_LLM_* 类配置控制。

## Future possibilities

- nexau AgentBackend 适配器（交付面回到与需求面同构的运行时，支持混接对比实验）。
- e2e 闸接通：tester 对 harness 跑真实一轮对话取证（evidence-stamp 硬闸已就位）。
- forge 层上游化：Gitea driver 若稳定，可作为 OpenAgents 的正式多 forge 能力（GitLab 等同法扩展）。
- 交付面指标入 metrics：PR 打回轮数、merge lead time、needs-human 率——作为 harness 演化健康度的新观测维度（与 issue 曲线并列）。
