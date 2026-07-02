# Frontend Observation Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only web dashboard that visualizes the auto-designer closed-loop's observability data — feeling trend, issue curve, and per-session transcripts.

**Architecture:** A thin read-only FastAPI layer (`backend/auto_designer/web/api.py`) serializes the existing `Metrics`/`SessionStore`/`IssueTracker` read paths to JSON; a React+Vite+TS SPA (`frontend/`) fetches `/api/*` and renders charts + a session browser. No new storage, no writes, no benchmark.

**Tech Stack:** Python 3.12 / FastAPI / uvicorn / Starlette TestClient (backend); React 18 / Vite / TypeScript / react-router / Recharts (frontend).

## Global Constraints

- Python: `requires-python >=3.12`.
- Backend deps to add (exact): `fastapi>=0.110`, `uvicorn[standard]>=0.27`.
- Ruff line-length 100; lint select includes `ASYNC` → API endpoint handlers are **synchronous `def`** (they read local files), never `async def` doing blocking IO.
- Python function params: no positional-only `/`; private functions (`_`-prefixed, non-dunder) take NO default values and callers pass every arg explicitly, by keyword.
- Conventional Commits: `<type>(<scope>): <desc>`. Commit + push after each task. Branch already exists: `feat/frontend-observation-dashboard`.
- Tests run via `PYTHONPATH` from `pyproject.toml` (`pythonpath=["backend","backend/scripts"]`, `testpaths=["backend/tests"]`). Run with `.venv/bin/python -m pytest`.
- Frontend gate is `npx tsc --noEmit` + `npx vite build` (no JS test framework — YAGNI).
- DTO field names are contract: backend and `frontend/src/types.ts` must match exactly.

---

### Task 1: Backend web package + deps + `/api/health` + app factory

**Files:**
- Modify: `pyproject.toml:6-12` (add fastapi + uvicorn to `[project.dependencies]`)
- Create: `backend/auto_designer/web/__init__.py`
- Create: `backend/auto_designer/web/api.py`
- Create: `backend/tests/web/__init__.py`
- Test: `backend/tests/web/test_api.py`

**Interfaces:**
- Produces:
  - `create_app(*, store: SessionStore, tracker: IssueTracker | None) -> FastAPI` — builds the app with injected deps (tests pass fakes; module `app` passes real ones).
  - `GET /api/health` → `{"status": "ok"}`.

- [ ] **Step 1: Add dependencies**

Edit `pyproject.toml` `[project.dependencies]` list (currently lines 6–12) to append:

```toml
    # 前端观测看板的只读 HTTP 层
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
```

- [ ] **Step 2: Install deps**

Run: `.venv/bin/python -m pip install "fastapi>=0.110" "uvicorn[standard]>=0.27"`
Expected: installs without error (or `uv pip install` if uv is the manager — check which `.venv` uses).

- [ ] **Step 3: Write the failing test**

Create `backend/tests/web/__init__.py` (empty file).

Create `backend/tests/web/test_api.py`:

```python
"""前端观测看板只读 API 单测：TestClient + 临时 SessionStore + FakeTracker，不触网。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from auto_designer.models import (
    FeelingScore,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
    Transcript,
    Turn,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.web.api import create_app


def _persona() -> Persona:
    return Persona(
        identity="独立开发者",
        level="中级",
        domain="Python 后端",
        goal="让慢查询快起来",
        speaking_style="口语",
    )


def _session(*, score: int, n_issues: int) -> Session:
    refs = [IssueRef(number=i + 1, url=f"fake://issues/{i + 1}", state="open") for i in range(n_issues)]
    return Session(
        persona=_persona(),
        scenario=SeedScenario(description="我有个 Django 接口很慢，帮我排查优化。" * 4),
        transcript=Transcript(turns=[Turn(role="user", content="hi"), Turn(role="harness", content="yo")]),
        feeling=FeelingScore(score=score, reason="还行"),
        issue_refs=refs,
    )


def _client(tmp_path: Path, *, tracker: object | None) -> TestClient:
    store = SessionStore(tmp_path / "sessions")
    return TestClient(create_app(store=store, tracker=tracker))


def test_health(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=FakeTracker())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/web/test_api.py::test_health -v`
Expected: FAIL with `ModuleNotFoundError: auto_designer.web.api`.

- [ ] **Step 5: Write minimal implementation**

Create `backend/auto_designer/web/__init__.py` (empty file).

Create `backend/auto_designer/web/api.py`:

```python
"""前端观测看板的只读 HTTP 层（FastAPI）。

复用既有 Metrics/SessionStore/IssueTracker 的只读路径，序列化为 JSON 供前端 SPA 消费。
不新增存储、不写任何状态、不引入 benchmark。端点为同步 def（读本地文件，避免阻塞 event loop 的
ASYNC 告警）。create_app 注入依赖（测试传 Fake，运行时传真），便于无网络单测。
"""

from __future__ import annotations

from fastapi import FastAPI

from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore


def create_app(*, store: SessionStore, tracker: IssueTracker | None) -> FastAPI:
    app = FastAPI(title="auto-designer observation dashboard", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/web/test_api.py::test_health -v`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
.venv/bin/python -m ruff check backend/auto_designer/web backend/tests/web
.venv/bin/python -m ruff format backend/auto_designer/web backend/tests/web
git add pyproject.toml backend/auto_designer/web backend/tests/web
git commit -m "feat(web): 只读看板 API 骨架 + /api/health + app 工厂"
git push
```

---

### Task 2: `/api/overview` endpoint

**Files:**
- Modify: `backend/auto_designer/web/api.py`
- Test: `backend/tests/web/test_api.py`

**Interfaces:**
- Consumes: `create_app(*, store, tracker)` from Task 1; `Metrics(tracker, store)` from `auto_designer.loop.metrics` whose `feeling_trend()`/`issue_curve()` ignore the tracker.
- Produces: `GET /api/overview` → `{ open_issue_count: int|null, session_count: int, feeling_trend: [[str,int]], issue_curve: [[str,int,int]] }`. `open_issue_count` is `null` when tracker is `None` or `list_open_issues()` raises.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/web/test_api.py`:

```python
def test_overview_empty(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=FakeTracker())
    body = client.get("/api/overview").json()
    assert body == {
        "open_issue_count": 0,
        "session_count": 0,
        "feeling_trend": [],
        "issue_curve": [],
    }


def test_overview_with_sessions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.save(_session(score=3, n_issues=1))
    store.save(_session(score=2, n_issues=2))
    tracker = FakeTracker()
    from auto_designer.models import IssueDraft

    tracker.create_issue(IssueDraft(title="t", body="b", labels=["bug"]))
    client = TestClient(create_app(store=store, tracker=tracker))

    body = client.get("/api/overview").json()
    assert body["session_count"] == 2
    assert body["open_issue_count"] == 1
    assert len(body["feeling_trend"]) == 2
    # issue_curve net_open 累计：第一局 opened=1 net=1，第二局 opened=2 net=3
    nets = [row[2] for row in body["issue_curve"]]
    assert nets == [1, 3]


class _BrokenTracker:
    def list_open_issues(self):
        raise RuntimeError("gitea down")


def test_overview_tracker_degrades_to_null(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    client = TestClient(create_app(store=store, tracker=_BrokenTracker()))
    assert client.get("/api/overview").json()["open_issue_count"] is None


def test_overview_no_tracker_null(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=None)
    assert client.get("/api/overview").json()["open_issue_count"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/web/test_api.py -k overview -v`
Expected: FAIL with 404 (route not defined) / KeyError.

- [ ] **Step 3: Implement the endpoint**

In `backend/auto_designer/web/api.py`, add imports at top:

```python
from auto_designer.loop.metrics import Metrics
```

Add a module-level private helper (no defaults, keyword args):

```python
def _open_issue_count(*, tracker: IssueTracker | None) -> int | None:
    """当前 open issue 数；无 tracker 或读取失败时降级为 None（不抛 500）。"""
    if tracker is None:
        return None
    try:
        return len(tracker.list_open_issues())
    except Exception:
        return None
```

Inside `create_app`, before `return app`, add:

```python
    @app.get("/api/overview")
    def overview() -> dict[str, object]:
        metrics = Metrics(tracker, store)  # tracker 仅 open_issue_count 用，trend/curve 不触
        return {
            "open_issue_count": _open_issue_count(tracker=tracker),
            "session_count": len(store.index()),
            "feeling_trend": metrics.feeling_trend(),
            "issue_curve": metrics.issue_curve(),
        }
```

Note: `Metrics(tracker, store)` accepts `tracker=None` because `feeling_trend`/`issue_curve` never touch it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/web/test_api.py -k overview -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check backend/auto_designer/web backend/tests/web
.venv/bin/python -m ruff format backend/auto_designer/web backend/tests/web
git add backend/auto_designer/web backend/tests/web
git commit -m "feat(web): /api/overview（体感/issue 曲线 + open 数降级）"
git push
```

---

### Task 3: `/api/sessions` list + `/api/sessions/{id}` detail

**Files:**
- Modify: `backend/auto_designer/web/api.py`
- Test: `backend/tests/web/test_api.py`

**Interfaces:**
- Consumes: `create_app`, `store.index()` rows `{session_id, score, created_at, n_issues}`, `store.load(session_id) -> Session`.
- Produces:
  - `GET /api/sessions` → `SessionSummaryDTO[]`, each `{ session_id, created_at, score, n_issues, persona_identity, scenario }` (scenario truncated to 80 chars).
  - `GET /api/sessions/{session_id}` → full `Session.to_dict()`; 404 `{"detail": "..."}` if missing.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/web/test_api.py`:

```python
def test_sessions_list(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.save(_session(score=4, n_issues=0))
    client = TestClient(create_app(store=store, tracker=FakeTracker()))

    rows = client.get("/api/sessions").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["score"] == 4
    assert row["n_issues"] == 0
    assert row["persona_identity"] == "独立开发者"
    assert len(row["scenario"]) <= 80
    assert set(row) == {"session_id", "created_at", "score", "n_issues", "persona_identity", "scenario"}


def test_session_detail_ok(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sess = _session(score=3, n_issues=1)
    store.save(sess)
    client = TestClient(create_app(store=store, tracker=FakeTracker()))

    body = client.get(f"/api/sessions/{sess.session_id}").json()
    assert body["session_id"] == sess.session_id
    assert body["feeling"]["score"] == 3
    assert body["transcript"]["turns"][0]["role"] == "user"
    assert body["issue_refs"][0]["number"] == 1


def test_session_detail_404(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=FakeTracker())
    assert client.get("/api/sessions/nope").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/web/test_api.py -k "sessions or detail" -v`
Expected: FAIL with 404 (routes not defined).

- [ ] **Step 3: Implement endpoints**

In `backend/auto_designer/web/api.py`, add imports:

```python
from fastapi import FastAPI, HTTPException
```

Add a module-level helper:

```python
def _summarize(*, store: SessionStore, row: dict) -> dict[str, object]:
    """index 行 + 从全量补 persona_identity 与截断后的 scenario，组装列表摘要 DTO。"""
    session = store.load(row["session_id"])
    scenario = session.scenario.description
    return {
        "session_id": row["session_id"],
        "created_at": row["created_at"],
        "score": row["score"],
        "n_issues": row["n_issues"],
        "persona_identity": session.persona.identity,
        "scenario": scenario[:80],
    }
```

Inside `create_app`, before `return app`:

```python
    @app.get("/api/sessions")
    def sessions() -> list[dict[str, object]]:
        rows = sorted(store.index(), key=lambda e: e["created_at"], reverse=True)
        return [_summarize(store=store, row=row) for row in rows]

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: str) -> dict[str, object]:
        try:
            return store.load(session_id).to_dict()
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
```

(Remove the now-duplicate `from fastapi import FastAPI` line; keep the combined import.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/web/test_api.py -v`
Expected: PASS (all tests in file).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/python -m ruff check backend/auto_designer/web backend/tests/web
.venv/bin/python -m ruff format backend/auto_designer/web backend/tests/web
git add backend/auto_designer/web backend/tests/web
git commit -m "feat(web): /api/sessions 列表 + /api/sessions/{id} 详情（404）"
git push
```

---

### Task 4: Module-level `app`, CORS, static mount, run docs

**Files:**
- Modify: `backend/auto_designer/web/api.py`
- Create: `backend/auto_designer/web/README.md`

**Interfaces:**
- Consumes: `create_app`.
- Produces: module attribute `app` runnable via `uvicorn auto_designer.web.api:app`; CORS allowing the Vite dev origin; optional static mount of `frontend/dist`.

- [ ] **Step 1: Add CORS + static + module app (no test — config glue)**

In `backend/auto_designer/web/api.py`, add imports:

```python
import os
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
```

Inside `create_app`, right after building `app` and before route defs, add CORS:

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
```

At the end of `create_app`, just before `return app`, mount static if a built frontend exists:

```python
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")
```

After the `create_app` function, add a module-level default app:

```python
def _default_store() -> SessionStore:
    data = Path(__file__).resolve().parents[2] / "data" / "sessions"
    return SessionStore(data)


def _default_tracker() -> IssueTracker | None:
    """有 Gitea 环境变量则接真 tracker，否则 None（open 数显示 —）。"""
    base_url = os.environ.get("GITEA_URL")
    owner = os.environ.get("OWNER")
    repo = os.environ.get("REPO")
    token = os.environ.get("TOKEN")
    if not (base_url and owner and repo and token):
        return None
    from auto_designer.tracker.gitea import GiteaTracker

    return GiteaTracker(base_url=base_url, owner=owner, repo=repo, token=token)


app = create_app(store=_default_store(), tracker=_default_tracker())
```

Verify `parents[3]` resolves to repo root: `api.py` is at `backend/auto_designer/web/api.py` → `parents[0]=web`, `[1]=auto_designer`, `[2]=backend`, `[3]=repo root`. `frontend/dist` is under repo root. ✓ And `_default_store` uses `parents[2]=backend` → `backend/data/sessions`. ✓

- [ ] **Step 2: Verify import + existing tests still pass**

Run: `.venv/bin/python -c "import os; os.environ.clear() if False else None; from auto_designer.web.api import app; print('ok')"` with `PYTHONPATH=backend`
Expected: prints `ok` (module `app` builds with no Gitea env → tracker None).

Run: `.venv/bin/python -m pytest backend/tests/web -v`
Expected: PASS (all).

- [ ] **Step 3: Write run README**

Create `backend/auto_designer/web/README.md`:

```markdown
# 观测看板只读 API

复用 Metrics/SessionStore/IssueTracker，只读序列化为 JSON。

## 端点
- `GET /api/health` → `{status: ok}`
- `GET /api/overview` → `{open_issue_count, session_count, feeling_trend, issue_curve}`
- `GET /api/sessions` → 会话摘要列表
- `GET /api/sessions/{id}` → 单局全量（404 若不存在）

## 起服务
```bash
PYTHONPATH=backend .venv/bin/uvicorn auto_designer.web.api:app --port 8000
```
有 Gitea 时设 `GITEA_URL/OWNER/REPO/TOKEN` 环境变量，`open_issue_count` 才有值，否则为 `null`。
构建过前端（`frontend/dist` 存在）则根路径 `/` 直接托管 SPA。
```

- [ ] **Step 4: Lint + commit**

```bash
.venv/bin/python -m ruff check backend/auto_designer/web
.venv/bin/python -m ruff format backend/auto_designer/web
git add backend/auto_designer/web
git commit -m "feat(web): 模块级 app + CORS + frontend/dist 静态托管 + 运行说明"
git push
```

---

### Task 5: Frontend scaffold + types + API client

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/index.css`
- Modify: `.gitignore` (ignore `frontend/node_modules`, `frontend/dist`)
- Replace: `frontend/README.md`

**Interfaces:**
- Produces (consumed by Tasks 6–8):
  - `types.ts`: `Overview`, `SessionSummary`, `SessionDetail`, `Turn`, `IssueRef`.
  - `api.ts`: `getOverview(): Promise<Overview>`, `getSessions(): Promise<SessionSummary[]>`, `getSession(id: string): Promise<SessionDetail>`.

- [ ] **Step 1: Scaffold files**

Create `frontend/package.json`:

```json
{
  "name": "auto-designer-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "recharts": "^2.12.7"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.0"
  }
}
```

Create `frontend/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev 时把 /api 代理到 uvicorn（默认 8000），生产由 FastAPI 托管 dist。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
```

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>auto-designer 观测看板</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 2: Create types + api client**

Create `frontend/src/types.ts`:

```ts
// 镜像后端 DTO（backend/auto_designer/web/api.py）。字段名是契约，须与后端一致。

export interface Overview {
  open_issue_count: number | null;
  session_count: number;
  feeling_trend: [string, number][]; // [created_at, score]
  issue_curve: [string, number, number][]; // [created_at, opened, net_open]
}

export interface SessionSummary {
  session_id: string;
  created_at: string;
  score: number;
  n_issues: number;
  persona_identity: string;
  scenario: string;
}

export interface Turn {
  role: "user" | "harness";
  content: string;
}

export interface IssueRef {
  number: number;
  url: string;
  state: string;
}

export interface SessionDetail {
  session_id: string;
  created_at: string;
  persona: {
    identity: string;
    level: string;
    domain: string;
    goal: string;
    speaking_style: string;
  };
  scenario: { description: string };
  transcript: { turns: Turn[] };
  feeling: { score: number; reason: string };
  issue_refs: IssueRef[];
}
```

Create `frontend/src/api.ts`:

```ts
import type { Overview, SessionSummary, SessionDetail } from "./types";

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${path} → ${resp.status}`);
  return (await resp.json()) as T;
}

export const getOverview = () => get<Overview>("/api/overview");
export const getSessions = () => get<SessionSummary[]>("/api/sessions");
export const getSession = (id: string) => get<SessionDetail>(`/api/sessions/${id}`);
```

- [ ] **Step 3: Create entry + base styles (router stubs filled in Tasks 6–8)**

Create `frontend/src/index.css`:

```css
:root { font-family: system-ui, -apple-system, "PingFang SC", sans-serif; color: #1f2328; }
* { box-sizing: border-box; }
body { margin: 0; background: #f6f8fa; }
a { color: #0969da; text-decoration: none; }
.container { max-width: 1080px; margin: 0 auto; padding: 24px; }
nav { display: flex; gap: 16px; padding: 16px 24px; background: #fff; border-bottom: 1px solid #d0d7de; }
nav a { font-weight: 600; }
.cards { display: flex; gap: 16px; margin: 16px 0; }
.card { flex: 1; background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 16px; }
.card .label { color: #656d76; font-size: 13px; }
.card .value { font-size: 28px; font-weight: 700; margin-top: 4px; }
.panel { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 16px; margin: 16px 0; }
table { width: 100%; border-collapse: collapse; background: #fff; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #d0d7de; font-size: 14px; }
.bubble { max-width: 70%; padding: 10px 14px; border-radius: 12px; margin: 8px 0; white-space: pre-wrap; }
.bubble.user { background: #ddf4ff; margin-left: auto; }
.bubble.harness { background: #f0f0f0; margin-right: auto; }
.reason { background: #fff8c5; border: 1px solid #d4a72c; border-radius: 8px; padding: 12px; }
.muted { color: #656d76; }
```

Create `frontend/src/main.tsx` (router with placeholder pages; real pages land in Tasks 6–8):

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import "./index.css";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <nav>
        <Link to="/">概览</Link>
        <Link to="/sessions">会话</Link>
      </nav>
      <div className="container">{children}</div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Shell>
        <Routes>
          <Route path="/" element={<div>概览（Task 6）</div>} />
          <Route path="/sessions" element={<div>会话列表（Task 7）</div>} />
          <Route path="/sessions/:id" element={<div>会话详情（Task 8）</div>} />
        </Routes>
      </Shell>
    </BrowserRouter>
  </React.StrictMode>
);
```

- [ ] **Step 4: gitignore + install + build gate**

Append to `.gitignore`:

```
# 前端构建产物与依赖
frontend/node_modules/
frontend/dist/
```

Replace `frontend/README.md`:

```markdown
# frontend — 观测看板（React + Vite + TS）

只读看板：消费 `backend/auto_designer/web/api.py` 的 `/api/*`，可视化体感曲线、issue 曲线与会话明细。

## 开发
```bash
cd frontend && npm install
# 另一终端起后端：PYTHONPATH=backend .venv/bin/uvicorn auto_designer.web.api:app --port 8000
npm run dev   # http://localhost:5173 ，/api 代理到 8000
```

## 构建
```bash
npm run build   # tsc --noEmit + vite build → dist/，由 FastAPI 托管
```
```

Run: `cd frontend && npm install && npm run build`
Expected: install succeeds; `tsc --noEmit` passes; `vite build` writes `frontend/dist/`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/tsconfig.node.json frontend/index.html frontend/src frontend/README.md
git commit -m "feat(frontend): Vite+React+TS 脚手架 + 类型/API 客户端 + 路由壳"
git push
```

---

### Task 6: Overview page (KPI cards + two charts)

**Files:**
- Create: `frontend/src/components/KpiCard.tsx`, `frontend/src/components/LineChartPanel.tsx`
- Create: `frontend/src/pages/Overview.tsx`
- Modify: `frontend/src/main.tsx` (wire `/` route)

**Interfaces:**
- Consumes: `getOverview()`, `Overview` type.
- Produces: `<Overview />` default export.

- [ ] **Step 1: KpiCard component**

Create `frontend/src/components/KpiCard.tsx`:

```tsx
export function KpiCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}
```

- [ ] **Step 2: LineChartPanel component**

Create `frontend/src/components/LineChartPanel.tsx`:

```tsx
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export interface SeriesSpec {
  key: string;
  name: string;
  color: string;
}

export function LineChartPanel({
  title,
  data,
  series,
  yDomain,
}: {
  title: string;
  data: Record<string, number | string>[];
  series: SeriesSpec[];
  yDomain?: [number, number];
}) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      {data.length === 0 ? (
        <p className="muted">暂无数据</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="t" tick={{ fontSize: 11 }} />
            <YAxis domain={yDomain ?? ["auto", "auto"]} allowDecimals={false} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend />
            {series.map((s) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Overview page**

Create `frontend/src/pages/Overview.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getOverview } from "../api";
import type { Overview as OverviewData } from "../types";
import { KpiCard } from "../components/KpiCard";
import { LineChartPanel } from "../components/LineChartPanel";

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getOverview().then(setData).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!data) return <p className="muted">加载中…</p>;

  const feeling = data.feeling_trend.map(([t, score]) => ({ t: t.slice(5, 16), score }));
  const issues = data.issue_curve.map(([t, opened, net]) => ({ t: t.slice(5, 16), opened, net }));

  return (
    <div>
      <h2>概览</h2>
      <div className="cards">
        <KpiCard label="当前 open issue" value={data.open_issue_count ?? "—"} />
        <KpiCard label="会话总数" value={data.session_count} />
        <KpiCard
          label="最新体感"
          value={data.feeling_trend.length ? data.feeling_trend[data.feeling_trend.length - 1][1] : "—"}
        />
      </div>
      <LineChartPanel
        title="体感趋势（1–4）"
        data={feeling}
        series={[{ key: "score", name: "体感", color: "#0969da" }]}
        yDomain={[1, 4]}
      />
      <LineChartPanel
        title="issue 曲线"
        data={issues}
        series={[
          { key: "opened", name: "新产", color: "#cf222e" },
          { key: "net", name: "累计", color: "#1a7f37" },
        ]}
      />
    </div>
  );
}
```

- [ ] **Step 4: Wire route**

In `frontend/src/main.tsx`, add import `import Overview from "./pages/Overview";` and replace the `/` route element with `<Overview />`.

- [ ] **Step 5: Build gate + commit**

Run: `cd frontend && npm run build`
Expected: passes.

```bash
git add frontend/src
git commit -m "feat(frontend): 概览页（KPI 卡片 + 体感/issue 曲线）"
git push
```

---

### Task 7: Sessions list page

**Files:**
- Create: `frontend/src/pages/Sessions.tsx`
- Modify: `frontend/src/main.tsx` (wire `/sessions`)

**Interfaces:**
- Consumes: `getSessions()`, `SessionSummary`.
- Produces: `<Sessions />` default export.

- [ ] **Step 1: Sessions page**

Create `frontend/src/pages/Sessions.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSessions } from "../api";
import type { SessionSummary } from "../types";

export default function Sessions() {
  const [rows, setRows] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSessions().then(setRows).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!rows) return <p className="muted">加载中…</p>;
  if (rows.length === 0) return <p className="muted">暂无会话</p>;

  return (
    <div>
      <h2>会话（{rows.length}）</h2>
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>用户画像</th>
            <th>场景</th>
            <th>体感</th>
            <th>issue 数</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.session_id}>
              <td>{r.created_at.slice(0, 16).replace("T", " ")}</td>
              <td>{r.persona_identity}</td>
              <td>
                <Link to={`/sessions/${r.session_id}`}>{r.scenario}</Link>
              </td>
              <td>{r.score}</td>
              <td>{r.n_issues}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Wire route**

In `frontend/src/main.tsx`, add `import Sessions from "./pages/Sessions";` and set the `/sessions` route element to `<Sessions />`.

- [ ] **Step 3: Build gate + commit**

Run: `cd frontend && npm run build`
Expected: passes.

```bash
git add frontend/src
git commit -m "feat(frontend): 会话列表页"
git push
```

---

### Task 8: Session detail page (transcript + feeling + issues)

**Files:**
- Create: `frontend/src/components/TranscriptThread.tsx`
- Create: `frontend/src/pages/SessionDetail.tsx`
- Modify: `frontend/src/main.tsx` (wire `/sessions/:id`)

**Interfaces:**
- Consumes: `getSession(id)`, `SessionDetail`, `Turn`, `IssueRef`.
- Produces: `<SessionDetail />` default export.

- [ ] **Step 1: TranscriptThread component**

Create `frontend/src/components/TranscriptThread.tsx`:

```tsx
import type { Turn } from "../types";

export function TranscriptThread({ turns }: { turns: Turn[] }) {
  return (
    <div>
      {turns.map((turn, i) => (
        <div key={i} className={`bubble ${turn.role}`}>
          <strong>{turn.role === "user" ? "用户" : "harness"}</strong>
          <div>{turn.content}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: SessionDetail page**

Create `frontend/src/pages/SessionDetail.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getSession } from "../api";
import type { SessionDetail as Detail } from "../types";
import { TranscriptThread } from "../components/TranscriptThread";

export default function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getSession(id).then(setData).catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <p className="muted">加载失败：{error}</p>;
  if (!data) return <p className="muted">加载中…</p>;

  return (
    <div>
      <p>
        <Link to="/sessions">← 返回会话列表</Link>
      </p>
      <h2>会话 {data.session_id.slice(0, 8)}</h2>
      <div className="panel">
        <div className="muted">
          {data.persona.identity} · {data.persona.level} · {data.persona.domain} · 目标：{data.persona.goal}
        </div>
        <p>{data.scenario.description}</p>
      </div>

      <div className="panel">
        <h3>对话</h3>
        <TranscriptThread turns={data.transcript.turns} />
      </div>

      <div className="panel">
        <h3>体感：{data.feeling.score} / 4</h3>
        <div className="reason">{data.feeling.reason}</div>
      </div>

      <div className="panel">
        <h3>产出 issue（{data.issue_refs.length}）</h3>
        {data.issue_refs.length === 0 ? (
          <p className="muted">无</p>
        ) : (
          <ul>
            {data.issue_refs.map((ref) => (
              <li key={ref.number}>
                <a href={ref.url} target="_blank" rel="noreferrer">
                  #{ref.number}
                </a>{" "}
                <span className="muted">({ref.state})</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire route**

In `frontend/src/main.tsx`, add `import SessionDetail from "./pages/SessionDetail";` and set the `/sessions/:id` route element to `<SessionDetail />`.

- [ ] **Step 4: Build gate + commit**

Run: `cd frontend && npm run build`
Expected: passes.

```bash
git add frontend/src
git commit -m "feat(frontend): 会话详情页（transcript 回放 + 体感 + issue 链接）"
git push
```

---

### Task 9: End-to-end smoke + CLAUDE.md frontend pointer

**Files:**
- Modify: `CLAUDE.md` (frontend 目录说明：从「占位」改为「观测看板」)
- (No code; verification + docs)

**Interfaces:** none new.

- [ ] **Step 1: Full backend test run**

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: all pass (including existing suites + new `tests/web`).

- [ ] **Step 2: Manual e2e smoke (documented, run if data exists)**

```bash
# 终端 A：起后端
PYTHONPATH=backend .venv/bin/uvicorn auto_designer.web.api:app --port 8000
# 终端 B：构建并让后端托管，或起 dev server
cd frontend && npm run build
# 浏览器访问 http://localhost:8000/ ，确认：KPI 卡片、两张曲线、会话表、点进详情看到 transcript/体感/issue
```

If `backend/data/sessions` is empty, run `PYTHONPATH=backend .venv/bin/python backend/run.py` first (needs LLM + Gitea env per `backend/run.py` docstring), or rely on the empty-state placeholders.

Expected: dashboard renders without console errors; empty data shows "暂无数据/暂无会话" rather than crashing.

- [ ] **Step 3: Update CLAUDE.md目录结构**

In `CLAUDE.md`, update the `frontend/` line in the 目录结构 block from `frontend/ # 前端（占位，暂无内容）` to:

```
frontend/                # 前端：React+Vite+TS 只读观测看板（消费 backend web API）
```

And in the architecture/目录结构 prose where the backend tree is described, add under `auto_designer/` a line for `web/ # 只读看板 FastAPI（/api/overview /api/sessions）`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 标记 frontend 为观测看板 + backend web 模块"
git push
```

- [ ] **Step 5: Open PR**

```bash
gh pr create --title "feat: 前端只读观测看板 + FastAPI 读 API" \
  --body "$(cat <<'EOF'
## 概要
只读观测看板：FastAPI 读 API（/api/overview、/api/sessions、/api/sessions/{id}）+ React/Vite/TS SPA（概览曲线 + 会话浏览）。复用既有 Metrics/SessionStore/IssueTracker，零新增存储、benchmark held-out。

## 验证
- backend/tests/web 全绿（TestClient + FakeTracker，不触网）
- frontend `npm run build`（tsc + vite build）通过
- 手动 e2e：uvicorn + dist，看板渲染 KPI/曲线/会话/详情

spec: docs/superpowers/specs/2026-06-26-frontend-observation-dashboard-design.md
plan: docs/superpowers/plans/2026-06-26-frontend-observation-dashboard.md
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- §3 read API (overview/sessions/detail/health, degradation, CORS, static, deps) → Tasks 1–4. ✓
- §4 frontend (scaffold, pages, components) → Tasks 5–8. ✓
- §5 data flow → exercised by Task 6 + Task 9 smoke. ✓
- §6 tests (backend TestClient; frontend build gate) → Tasks 1–3 tests + per-task `npm run build`. ✓
- §7 constraints (sync def, private-fn keyword args, held-out) → Global Constraints + helpers `_open_issue_count`/`_summarize`/`_default_*` all keyword-only, no defaults on the data-bearing params. ✓
- §8 follow-ups (release history/console) explicitly out of scope. ✓

**Placeholder scan:** Router stubs in Task 5 are intentional, real elements replace them in Tasks 6–8 (each "wire route" step is concrete). No TBD/TODO. ✓

**Type consistency:** `getOverview/getSessions/getSession` names identical across `api.ts` (Task 5) and pages (Tasks 6–8). DTO field names match backend dict keys: `open_issue_count`, `session_count`, `feeling_trend`, `issue_curve`, `persona_identity`, `scenario`, `issue_refs`. `LineChartPanel` `data`/`series`/`yDomain` props consistent with Overview usage. ✓
