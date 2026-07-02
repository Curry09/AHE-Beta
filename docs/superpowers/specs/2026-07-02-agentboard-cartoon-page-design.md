# AgentBoard —— 卡通形式的活动 Agent 页面

日期：2026-07-02
状态：设计已确认，待写实现计划

## 背景与目标

前端观测看板目前把 agent 活动塞在一个嵌于每页顶部的朴素折叠列表 `AgentsPanel` 里。
本设计新增一个**独立页面 AgentBoard**，用卡通形式（emoji 头像 + CSS 动画）展示当前活动
的 agent，展示其身份，并支持点击。卡通页取代旧的顶部面板。

数据源已存在，无需后端改动：`/api/agents` 已经返回实时 agent 注册表
（`data/live/agents.json` 的投影），2 秒轮询。

## 范围

- 新增 `/agentboard` 路由页与导航入口。
- 从 `Shell`（`main.tsx`）移除常驻顶部的 `AgentsPanel`；删除 `AgentsPanel.tsx`（仅此一处引用）。
- 用 emoji 头像 + CSS 动画重新表现 agent；两类卡片均可点。
- **零新依赖、零后端改动。**

不在范围内：修改 agent 注册表结构、给 agents.json 补 session_id、任何 benchmark 相关。

## 数据契约（沿用现有，不改）

`/api/agents` → `{ agents: Agent[] }`，`Agent` 见 `frontend/src/types.ts`：
`agent_id, role("user"|"developer"), label, running, status, turns[], detail, started_at, updated_at`。

- 用户 agent：`agent_id = "user-{identity}"`，`label = identity`。
- 开发者 agent：`agent_id = "dev-0"/"dev-1"`，`label = "dev#1"/"dev#2"`，无 turns、有 detail。
- 后端 `_summarize` 的 `persona_identity === session.persona.identity === 用户 agent 的 label`，
  三者同源（`run.py` 中 `mp.identity = sp.persona_id`，`label = identity`）。这是用户卡点击跳转的关联依据。

## 组件结构

```
pages/AgentBoard.tsx        # 页面：轮询 → 按 role 分组 → 渲染卡片墙
components/AgentCard.tsx     # 单个 agent 卡：emoji 头像 + 身份 + 状态 + 动画 + 点击
lib/agentHealth.ts          # 共享：health(a, now) 健康判定 + fmtDur（从旧 AgentsPanel 抽出）
lib/avatar.ts               # 确定性 emoji 头像：hash(label) → 一张脸；role → 装饰
```

- `AgentBoard`：`useLiveData(getAgents, 2000)` → `now = Date.now()` → 拆 `users`/`devs` 两组 →
  各渲染一个卡片墙（`flex-wrap`）。两组均空时显示「暂无活动 agent」。
- `AgentCard`：接收 `agent` 与 `now`，算 `health`，渲染头像 + role 中文名 + label + status。
- `agentHealth.ts`：搬运旧 `AgentsPanel` 的 `health()`（异常 > 卡顿 > 运行 > 完成）与 `fmtDur()`，
  避免逻辑重复；`STALE_MS = 330_000` 常量一并搬入。

## 卡通表现（emoji + CSS，零依赖）

- **头像**：`avatar.ts` 用简单字符串哈希把 `label` 映射到一组固定 emoji 脸之一（同一 agent 永远同一张脸）；
  `role` 决定角标——用户叠 🙋、开发者叠 🛠️。
- **身份**：卡片显示 role 中文名（「用户 Agent」/「开发者 Agent」）+ `label` + 一行 `status`。
- **状态动画**（CSS keyframes，健康态 → class）：
  - 运行中（ok）：轻微上下浮动 + 彩色光环（沿用绿 `#1a7f37`）。
  - 卡顿（warn）：黄色慢摇摆。
  - 异常（err）：红色抖动。
  - 完成/空闲（idle）：头像变暗 + 😴 角标，无动画。
- 复用现有 CSS 色板（`ok/warn/err/idle` 的绿/黄/红/灰），新增卡片与 keyframes 样式写入 `index.css`。

## 点击行为（两类均可点）

- **用户 agent 卡**：点击 → 拉 `/api/sessions`（已有 `getSessions`）→ 找 `persona_identity === label`
  的最新一条（按 `created_at` 倒序取首个）→ `navigate('/sessions/:session_id')`。
  找不到（该 persona 尚无落库会话）→ 就地展开卡片 status/detail 作降级，不报错。
- **开发者 agent 卡**：无会话可跳（数据现实）→ 点击就地展开该卡片的 `status` 与 `detail`（内联小面板）。
- 内联展开用受控 state（点击 toggle），不依赖 `<details>`，以便对两类卡片统一交互。

## 错误处理与边界

- `/api/agents` 加载失败：`useLiveData` 已回传 `error`，页面显示「加载失败：{error}」。
- 无任何 agent：两组皆空 → 显示「暂无活动 agent（跑闭环后实时出现）」。
- 用户卡点击时 `/api/sessions` 为空或无匹配：降级为就地展开，不抛错、不跳空白页。
- 旧数据缺 `started_at`：沿用旧面板容错（缺失时回退到 `updated_at`）。

## 测试与验收

- 前端为轻量 SPA，无既有单测框架；验收以构建 + 手工冒烟为准：
  1. `npm run build`（`tsc --noEmit && vite build`）通过，无类型错误。
  2. 导航出现「AgentBoard」入口，旧顶部面板不再出现在任何页。
  3. 造一份 `data/live/agents.json`（含 running 用户 + 完成用户 + 开发者各若干），启动
     后端 + 前端，肉眼确认：卡通头像、身份、状态动画、2s 刷新。
  4. 点击运行中用户卡 → 跳到该 persona 最新会话详情；点击开发者卡 → 就地展开 detail。
- 后端有对应 pytest（`/api/agents` 已被 `backend/tests/web/test_api.py` 覆盖），本设计不改后端，
  故 `pytest` 应保持全绿（回归确认即可）。

## 遵循的项目理念

- **奥卡姆剃刀**：零新依赖、零后端改动，emoji + CSS 即卡通。
- **模块解耦**：健康判定/头像逻辑抽成 `lib/`，页面与卡片职责分离。
- **结构化管理**：`pages/` 放页面、`components/` 放卡片、`lib/` 放纯函数工具。
