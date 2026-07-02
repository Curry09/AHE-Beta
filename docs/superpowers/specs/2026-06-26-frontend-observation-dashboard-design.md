# 前端观测看板设计（Frontend Observation Dashboard）

- 日期：2026-06-26
- 状态：已批准，待实现
- 定位：**只读观测看板**（read-only dashboard），不含控制台/触发能力

## 1. 背景与目标

后端 `backend/auto_designer/` 当前是纯编排库，无 HTTP 层。闭环跑出来的可观测数据散落在：

- `backend/data/sessions/`：每局 `<session_id>.json`（全量 Session）+ `index.json`（派生索引：`session_id/score/created_at/n_issues`）。
- Gitea：open issue 列表（经 `IssueTracker.list_open_issues()`）。
- `Metrics`（`loop/metrics.py`）：在上述之上算出 `feeling_trend()`、`issue_curve()`、`open_issue_count()`。

CLAUDE.md 的「观测指标」要求记录 **issue 数量随时间曲线** 与 **体感**，用于判断闭环是否健康（issue 长期不降=退化；过早归零=多样性不足）。本看板把这些指标 + 单局会话明细可视化，作为闭环的「观测窗口」。

**非目标（YAGNI）**：不触发跑闭环、不配置 persona/scenario、不浏览 Gitea issue 全量、不做 persona 库视图。这些留待后续「观测+控制台」演进。

## 2. 架构总览

```
浏览器 (React SPA)
   │  fetch /api/*
   ▼
FastAPI 只读 API  (backend/auto_designer/web/api.py)
   │  复用
   ▼
Metrics / SessionStore / IssueTracker   ← 既有编排库，零改动其语义
```

两个解耦单元：

1. **读 API**：把既有 `Metrics`/`SessionStore` 的只读结果序列化为 JSON。不新增存储、不写任何状态。
2. **前端 SPA**：纯展示，仅 `fetch` + 本地 `useState`，无全局状态库。

接口即边界：前端只认 `/api/*` 的 DTO 形状，不感知后端是读文件还是读 Gitea。

## 3. 后端读 API

模块：`backend/auto_designer/web/api.py`，FastAPI app 实例名 `app`。

构造期注入 `SessionStore`（指向 `backend/data/sessions`）与可选 `IssueTracker`（Gitea；缺省/失败时降级）。

### 端点

| 方法 | 路径 | 返回 |
|---|---|---|
| GET | `/api/overview` | `OverviewDTO` |
| GET | `/api/sessions` | `SessionSummaryDTO[]` |
| GET | `/api/sessions/{id}` | `SessionDetailDTO`（即 `Session.to_dict()`），404 若不存在 |
| GET | `/api/health` | `{ "status": "ok" }` |

### DTO 形状

```jsonc
// OverviewDTO
{
  "open_issue_count": 3 | null,        // Gitea 不可用时为 null，前端显示 "—"
  "session_count": 12,
  "feeling_trend": [["2026-06-26T10:00:00", 3], ...],     // [(created_at, score)]
  "issue_curve":   [["2026-06-26T10:00:00", 1, 1], ...]   // [(created_at, opened, net_open)]
}

// SessionSummaryDTO（index.json 行 + 从全量补 persona/scenario 摘要）
{
  "session_id": "ab12...",
  "created_at": "2026-06-26T10:00:00",
  "score": 3,
  "n_issues": 1,
  "persona_identity": "独立开发者",
  "scenario": "我有个 Django 接口很慢…"   // 截断到 ~80 字符
}

// SessionDetailDTO = Session.to_dict()（models.py 已定义，原样透传）
```

### 降级与错误

- `open_issue_count`：调用 `tracker.list_open_issues()`，捕获任何异常（Gitea 未起/网络）→ 返回 `null`，不抛 500。无 tracker 注入时同样 `null`。
- `/api/sessions/{id}`：`SessionStore.load` 抛 `FileNotFoundError` → 转 404。
- 空数据源（无 `index.json`）：`feeling_trend`/`issue_curve`/`sessions` 均为 `[]`，`session_count=0`，合法初始态。

### 静态托管与 CORS

- 开发：Vite dev server 独立端口，代理 `/api` → uvicorn（默认 `127.0.0.1:8000`）。CORS 允许 Vite origin。
- 生产：`vite build` 产物 `frontend/dist` 由 FastAPI `StaticFiles` 挂载在 `/`，单进程托管 API+静态。

启动：`uvicorn auto_designer.web.api:app`（`PYTHONPATH=backend`）。

### 依赖

`pyproject.toml` `[project.dependencies]` 增 `fastapi>=0.110`、`uvicorn[standard]>=0.27`。lint 沿用 Ruff（含 ASYNC 规则，端点用同步 def 读本地文件即可，避免阻塞 event loop 的告警）。

## 4. 前端 SPA

目录：`frontend/`（Vite + React + TypeScript）。

```
frontend/
  index.html
  package.json  vite.config.ts  tsconfig.json
  src/
    main.tsx            # 入口 + 路由
    api.ts              # 类型化 fetch 客户端
    types.ts            # 镜像后端 DTO
    pages/
      Overview.tsx      # KPI 卡片 + 两张曲线
      Sessions.tsx      # 会话表
      SessionDetail.tsx # transcript 回放 + 体感理由 + issue 链接
    components/
      KpiCard.tsx
      LineChartPanel.tsx  # 封装 Recharts
      TranscriptThread.tsx
```

- 路由：`react-router`。`/`=Overview，`/sessions`=列表，`/sessions/:id`=详情。
- 图表：Recharts。**体感趋势**（折线，y∈1..4）+ **issue 曲线**（折线，opened 与 net_open 双线）。
- 详情：transcript 渲染成聊天气泡（user / harness 左右分列）；`feeling.reason` 作高亮说明块；`issue_refs` 渲染为指向 Gitea `url` 的外链。
- 无状态库；每页 `useEffect` 拉数据 + `loading/error` 态。空数据显示占位文案而非报错。

## 5. 数据流（一次 Overview 加载）

1. `Overview.tsx` mount → `api.getOverview()` → `GET /api/overview`。
2. API：`Metrics(tracker, store)` 读 `index.json` 算 trend/curve；`tracker.list_open_issues()`（try/except 降级）。
3. 返回 `OverviewDTO` → 渲染 3 张 KpiCard + 2 张 LineChartPanel。

## 6. 测试与验收

- **后端**：`backend/tests/` 加 `test_web_api.py`，用 FastAPI `TestClient` + 临时 `SessionStore`（写 1–2 局假 Session）+ FakeTracker，断言：`/api/overview` 字段与曲线、`/api/sessions` 摘要、`/api/sessions/{id}` 404 与正常、Gitea 异常时 `open_issue_count=null`。不依赖真 Gitea/网络。
- **前端**：MVP 以 `tsc --noEmit` + `vite build` 通过为门禁（不引入测试框架，YAGNI）。
- **验收（成果导向）**：`uvicorn` 起 API + `vite build` 后访问看板，能看到 KPI、两张曲线、会话表、点进详情看到 transcript/体感/issue——基于 `backend/data/sessions` 真实产物。

## 7. 与既有约束的一致性

- 奥卡姆剃刀：只读、零新增存储、无状态库、两视图。
- 模块解耦：API 仅序列化既有只读结果；前端只认 DTO。
- benchmark held-out：看板不引入任何 benchmark，纯观测，与训练/门禁无关。
- 函数参数：后端新增私有函数遵循「无位置参数 `/`、private 无默认值、显式传参」。

## 8. 后续演进（不在本期）

- B：harness 发版历史面板（读 harness_repo 分支/tag）。
- 控制台：从前端触发跑一轮、配置 persona/scenario、实时进度（需后端补可写 API + 任务态）。
