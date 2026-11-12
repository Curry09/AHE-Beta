# Read-only Observation API

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

Query the API directly, for example with `curl http://127.0.0.1:8000/api/overview`.
The server does not host a frontend application. For a prepared experiment, use
`backend/scripts/experiment.py dashboard RUN_ID` to bind the API to that run's artifacts.
