---
number: "0026"
title: 观测看板前端全面重构：浅/深主题可切换 + 分诊(triager)可见 + persona 展示 + 设计 token 化
issue: 0
slug: frontend-observability-redesign
summary: 观测看板前端从「纯黑底+白字、四栏、只显 SR-001 标识」全面重构为一套有设计系统的界面：① 引入设计 token 层（颜色/间距/字阶/圆角/阴影/层级）+ 浅/深主题可切换（跟随系统、localStorage 持久）；② 看板补齐 triager（分诊）房间——闭环 a→d1(triage)→d2(architect)→b 五角色都可见，各角色一致的强调色；③ 用户卡展示 persona（identity + 水平/领域/目标），不只 SR-001；issue/commit 卡在 0025 徽标基础上排版收敛；④ 详情面板信息架构刷新 + persona 块；⑤ 体感/backlog 曲线可视化（消费既有 /api/overview）；⑥ 响应式（页面不横向滚动、宽内容内部滚动）+ 两主题对比度/焦点态。后端仅小改：live 补 triager 排序、用户 agent 活动载荷带 persona 摘要。纯只读观测，不改闭环语义、不引 benchmark。
tasks:
  - id: T1
    title: 后端：live 补 triager 排序 + 用户 agent 活动载荷带 persona 摘要
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/loop/live.py
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/tests/loop/test_live.py
    scope: live.py 的 _ROLE_ORDER 加 triager（排在 user 之后、architect 之前）；update_agent 增可选 meta(dict)——只读透传，前端展示用，不参与任何决策；run.py 用户 status 回调传 persona 摘要（identity/level/domain/goal）进 meta；read_agents 排序含 triager。纯观测数据补齐，不动闭环。
    acceptance: read_agents 里 triager 排在 user 与 architect 之间；用户 agent 槽带 persona 摘要 meta；老调用不传 meta 时退化为 None 不崩；test_live 覆盖排序与 meta 透传。
  - id: T2
    title: 设计 token 层 + 浅/深主题（跟随系统 + localStorage 持久）+ 全局 CSS
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - frontend/src/styles.css
      - frontend/src/hooks/useTheme.ts
      - frontend/src/components/ThemeToggle.tsx
    scope: styles.css 重构为设计 token（CSS 变量：色板 bg/surface/surface-raised/border/text/text-dim/text-faint/accent + 四角色强调色、间距阶、字阶、圆角、阴影、层级）；语义色都走 token、组件不再写死 hex。:root 定义浅色，:root[data-theme=dark] 覆盖深色（换掉纯黑，用柔和深蓝灰）；全局响应式与焦点态一并收进 styles.css（页面 body 永不横向滚动、宽内容自身 overflow-x）。useTheme hook 读/写 localStorage、首屏读 prefers-color-scheme、在 html 打 data-theme；ThemeToggle 组件（挂载由 T3 的 TopBar 负责）。样式类沿用现有命名，两主题都成体系。
    acceptance: 浅/深两套都成体系（对比度达标）；useTheme 切换即时生效、刷新保持；无写死颜色残留（关键类走 token）；页面不横向滚动；npm build 通过。
  - id: T3
    title: 应用外壳 + 类型（AgentRole triager / Agent.meta）+ TopBar（主题开关）+ 概览曲线
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - frontend/src/types.ts
      - frontend/src/App.tsx
      - frontend/src/components/TopBar.tsx
      - frontend/src/components/Charts.tsx
    scope: types.ts 的 AgentRole 加 triager、Agent 加可选 meta(persona 摘要，供 T4 用)；App.ROLES 插入「分诊」房间（顺序 用户→分诊→设计师→开发者，对齐闭环 a→d1→d2→b）并按新 token 布局；TopBar 挂 T2 的 ThemeToggle；新增 Charts 组件（内联 SVG 折线，消费既有 /api/overview 的 feeling_trend 与 issue_curve[backlog 口径 0025/T7]，双主题配色、不横向溢出），置于概览区。
    acceptance: 前端出现分诊房间位；主题开关可用；两条曲线在浅/深主题下清晰不溢出；build 通过。
  - id: T4
    title: 角色列 + 卡片：triager 房间渲染 + 角色强调色 + 用户卡 persona + issue/commit 卡收敛
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - frontend/src/components/AgentColumn.tsx
      - frontend/src/components/Card.tsx
    scope: AgentColumn/Card 的 role→强调色映射含 triager（用 T2 角色 token），渲染分诊房间的活动与按轮归档；用户卡主行显 identity、副行显 水平·领域、goal 进 tooltip/次要位（老后端无 meta 时退回只显 identity 不崩）；issue/commit 卡在 0025/T8 徽标基础上做排版收敛（对齐、留白、截断）。
    acceptance: 分诊房间的 triager 活动/归档可见；用户卡显示 persona 三要素而非只有 SR-001，缺 meta 退化不崩；角色强调色成套；issue/commit 卡排版整齐；build 通过。
  - id: T5
    title: 详情面板信息架构刷新（agent/session/issue/commit + 侧栏）+ persona 块
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - frontend/src/components/detail/AgentRunDetail.tsx
      - frontend/src/components/detail/SessionDetail.tsx
      - frontend/src/components/detail/IssueDetail.tsx
      - frontend/src/components/detail/CommitDetail.tsx
      - frontend/src/components/SidePanel.tsx
    scope: 四个详情视图 + 侧栏按新 token 刷新排版（分区/层次/留白/等宽块），SessionDetail 补 persona 信息块（identity/level/domain/goal + 体感分与原因），过程流/评论时间线可读性优化；不新增后端端点，仅重排既有数据。
    acceptance: 四类详情 + 侧栏信息层次清晰、两主题可读；SessionDetail 有 persona 块；build 通过。
---

# 0026 · 观测看板前端全面重构：浅/深主题可切换 + 分诊(triager)可见 + persona 展示 + 设计 token 化

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把只读观测看板前端从「纯黑底 + 白字、四栏、agent 只显 SR-001 这类 identity 标识」重构成一套有设计系统、信息更友好的界面。四件事：**设计 token 化 + 浅/深主题可切换**、**补齐 triager（分诊）房间让闭环五角色全可见**、**用户卡展示 persona（不只标识符）**、**详情/曲线可视化与响应式收尾**。后端只做很小的观测数据补齐（live 排序含 triager、用户 agent 活动载荷带 persona 摘要），不改任何闭环语义、不引 benchmark。

## Motivation

现状三个体感/可用性问题，都在只读看板这一层：

1. **纯黑底 + 白字太生硬**，没有层次与强调，长时间盯着累；配色是逐组件写死的 hex，无设计 token，改主题、加浅色无从下手。
2. **分诊 agent（triager）在前端完全不可见**：闭环已是 a→d1(triage)→d2(architect)→b，但前端 ROLES 只有 用户/设计师/开发者三个房间，triager 发的 `role="triager"` 活动被直接过滤掉——用户既看不到分诊在做什么，也就无从判断「issue 一直 needs-triage」是分诊没跑、跑崩、还是没产出（本次线上正遇到）。
3. **agent 卡只显 identity 标识（SR-001 这种）**，看不到该 persona 是谁（水平/领域/目标），交互时缺上下文。

这些不是闭环逻辑问题，而是观测界面的表达问题；单独立一个前端 spec 重构，和后端进化解耦。

## Guide-level explanation

重构后用户看到：

- **顶栏一个主题开关**：浅色 / 深色一键切换，首次进入跟随系统偏好，选择记在 localStorage，刷新不丢。深色不再是纯黑，而是柔和的深蓝灰、有分层表面与细边框；浅色是干净的白/浅灰底 + 深字。
- **看板五个区**：用户 → 分诊 → 设计师 → 开发者 四个角色列 + 右侧 Issues·Main 侧栏，顺序对齐闭环 a→d1→d2→b。每个角色一个一致的强调色（色点、卡片高亮、列头）。分诊房间实时显示 triager 在分诊哪些 issue、结果如何，并按轮归档回看。
- **用户卡显示 persona**：主行是 identity，副行是「水平·领域」，目标在 tooltip/次要位；点开详情有完整 persona 块（含体感分与原因）。
- **issue/commit 卡** 沿用 0025/T8 的 kind/优先级/轮次/覆盖徽标，但排版更整齐、留白更舒适。
- **顶部概览多两条曲线**：体感随时间 + 可执行 backlog 随时间（0025/T7 口径），直接消费既有 `/api/overview`。
- 整体**响应式**：窄屏不撑破页面，宽内容（表格/曲线/长代码）在自己的容器里横向滚动，页面 body 永不横向滚动。

对后端使用者：仅多了「用户 agent 活动可带一份 persona 摘要」这一只读字段，和 triager 在活动列表里的排序位；其余零改动。

## Reference-level explanation

**后端（T1，最小改动）**：`loop/live.py` 的 `_ROLE_ORDER` 增 `triager`（介于 user 与 architect 之间）；`update_agent` 增一个可选 `meta: dict | None`（只读透传、默认 None、老调用不受影响），落进 agent 槽；`run.py` 的用户 status 回调把 persona 摘要（identity/level/domain/goal）放进 meta。纯观测字段，不进任何决策、不碰 tracker/git。

**前端设计系统（T2，地基）**：`styles.css` 重构为 CSS 变量 token——色板（bg/surface/surface-raised/border/text/text-dim/text-faint/accent + 四角色强调色）、间距阶、字阶、圆角、阴影、层级。`:root` 定义浅色为基准，`:root[data-theme="dark"]` 覆盖深色；`useTheme` hook 读/写 localStorage、首屏读 `prefers-color-scheme`、在 `<html>` 打 `data-theme`；`ThemeToggle` 挂 TopBar。组件层不再写死颜色，全部走 token。

**前端结构与信息（T3/T4/T5）**：
- T3（外壳/类型/概览）：`AgentRole` 加 `triager`、`Agent` 加可选 `meta`；`App.ROLES` 插「分诊」并按 token 布局；`TopBar` 挂 `ThemeToggle`；新增 `Charts`（内联 SVG，消费 `/api/overview`）。
- T4（列与卡）：`AgentColumn`/`Card` 角色→强调色含 triager、渲染分诊房间；用户卡渲染 persona 三要素（缺 meta 退化只显 identity）；issue/commit 卡排版收敛。
- T5（详情/侧栏）：四个详情视图 + `SidePanel` 按新 token 重排；`SessionDetail` 补 persona 块。

**DAG**：T1、T2 无依赖（可并行起步）；T3←T2；T4←T1+T3；T5←T2+T3。**文件按 task 单一归属、互不重叠**：T1=live/run/test_live，T2=styles.css/useTheme/ThemeToggle，T3=types/App/TopBar/Charts，T4=AgentColumn/Card，T5=detail/*+SidePanel。跨组重叠（types.ts 与 0020/0025）仅为观测性警告，不阻塞。

**Non-goal**：不改闭环 a/d/b/c 语义；不新增后端观测端点（曲线用既有 /api/overview，详情用既有 /api/*）；不引 benchmark；不做鉴权/多用户；不改 issue schema 与 triage/architect/dev 逻辑（那是 0025）。

## Drawbacks

- 前端一次性改动面较大（styles.css 全量 token 化 + 多组件），review/回归成本高于局部改；靠分 6 个 task、每个都以 `npm build` 通过 + mock 退化不崩为验收来控风险。
- 双主题要维护两套色值，后续加组件需两主题都照顾（用 token 后成本可控）。
- 后端多一个 `meta` 字段，属观测面轻微扩面（但只读、默认 None，风险低）。

## Rationale and alternatives

- **为何浅/深可切换（而非只精致深色）**：用户明确要两套可切换；token 化后维护两主题成本可控，且给不同环境（投屏/白天）留弹性。
- **为何 persona 摘要走后端 meta（而非前端关联 session）**：live 卡是运行中的临时槽、此时还没有落盘 session_id，前端无从关联；由后端在活动回调里带一份轻量摘要最直接，且只读、解耦。
- **为何单独立 spec（而非并进 0025）**：0025 是 issue triage 漏斗（后端闭环语义），此重构是观测界面表达，关注点不同、文件也基本不重叠；分开便于独立 review 与回滚。
- **备选**：只加 triager 房间 + 修配色的「聚焦式」小改——已与用户确认走「全面重构 + 浅深可切换」，故取全量。

## Prior art

- 既有 0011（agentboard 卡通页）确立了四栏看板与卡片范式；本 spec 在其上做设计系统化与主题化。
- 0025/T8 已给 issue/commit 卡加了 kind/优先级/覆盖徽标与分组，本 spec 复用并做视觉收敛。
- 主题 token + `data-theme` 切换、跟随 `prefers-color-scheme` 是前端通行做法（Linear/Notion 等的浅色、各类 dashboard 的深色）。

## Unresolved questions

- 角色强调色的具体色值待 T2/T3 定稿（需在浅/深两主题都达对比度）。
- 曲线组件的形态（迷你 sparkline vs 带坐标的折线）待 T6 依概览区空间定；先以「清晰、不溢出、双主题」为准。
- persona 摘要在卡片上的信息取舍（副行放 水平·领域 还是 领域·目标）待 T4 依卡片宽度定。

## Future possibilities

- 主题可扩到高对比/护眼等更多档；token 层就绪后成本低。
- 曲线可加交互（hover 取值、按轮标注 RFC 落地点）。
- 可加轮次时间轴总览、issue 漏斗（needs-triage→triaged→RFC→closed）转化视图，进一步贴合 CLAUDE.md 的观测指标。
