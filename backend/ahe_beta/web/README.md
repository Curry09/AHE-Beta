# Read-only Dashboard API

The API serializes data from Metrics, SessionStore, and IssueTracker as JSON. It does not modify state or run benchmarks.

## Endpoints

- `GET /api/health` → `{status: ok}`
- `GET /api/overview` → `{open_issue_count, session_count, feeling_trend, issue_curve}`
- `GET /api/sessions` → session summaries
- `GET /api/sessions/{id}` → full session details (`404` if the session does not exist)

## Start the Server

```bash
PYTHONPATH=backend .venv/bin/uvicorn ahe_beta.web.api:app --port 8000
```

For Gitea-backed issue counts, set `GITEA_URL`, `OWNER`, `REPO`, and `TOKEN`. Otherwise, `open_issue_count` is `null`.

If the frontend has been built (`frontend/dist` exists), the server also serves the SPA at `/`.
