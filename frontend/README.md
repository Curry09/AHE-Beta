# AHE-Beta Observability Dashboard (Frontend)

> Interaction and visual reference: [vibe-kanban](https://github.com/BloopAI/vibe-kanban) (BloopAI)—multiple columns on one screen, minimalist kanban style.

A read-only dashboard for the real-time API mode, displaying the running status of User / Triage / Divergent PM / Architect / Owner + the Issues·Main panel.
The top can switch between “Running / +Completed”; completed items are grouped by round. Click any block to display the complete information for that object in the details panel (the user's complete session conversation, the complete dev/architect process stream and final report, the issue body + comments, and the complete commit text + diff). Cross-navigation among issues/tags/commits is supported.

## Default Development Dashboard

The unified entry point can now bind to a specified experiment. Run `uv run --locked --extra experiments python backend/scripts/experiment.py dashboard RUN_ID --secrets-file .env.experiment` from the repository root: local reads that run's real-time sessions/live/usage; E2B collects first and displays the collected snapshot. Without a Gitea token, local artifacts can still be viewed, but the connection will not be shown as established. The default development API below still reads `backend/data/sessions` for independent development and does not automatically select a v2 run.

```bash
# Backend (data source, :8000）
PYTHONPATH=backend .venv/bin/uvicorn ahe_beta.web.api:app --port 8000

# Frontend dev (:5173, /api proxies to :8000）
cd frontend && npm ci && npm run dev

# Production: after building, FastAPI serves dist (open :8000 )
npm run build
```

See `src/types.ts` for the data contract; it corresponds one-to-one with `backend/ahe_beta/web/api.py`, and both sides must be updated synchronously.
The structural synthesis roles use `architect`, `architect_run`, and `roster.architect`.

## GitHub Pages Historical Snapshots

When `VITE_STATIC_SITE=1` is set during the build, the page reads a sanitized snapshot from `public/experiments/<experiment-id>/api/`
and switches between experiments through the top selector. The page is labeled “Historical snapshot” and displays the UTC record time and the status at that time; RUNNING only indicates the status at collection time and does not mean it is still running now. Do not put the original prompt, complete sessions, tokens, container names, or internal logs
into `public/`. A repository script can generate a snapshot from an experiment's monitoring directory:

```bash
uv run --locked python backend/scripts/export_experiment_snapshot.py \
  "$EXPERIMENT_ROOT" "$NEW_PUBLIC_DIRECTORY" \
  --public-id demo --title "Historical experiment title"
```

Run the export command from the repository root, with EXPERIMENT_ROOT pointing to the experiment's monitoring directory and NEW_PUBLIC_DIRECTORY using a newly created export directory. After checking it, replace `frontend/public/experiments/`; see the [public export instructions](../docs/EXPORTING.md) for details. Complete experiments are still started through the unified entry point in [QuickStart](../docs/QUICKSTART.md), and historical records in the source directory are accessed from the [research index](../research/README.md).

GitHub Actions builds and publishes `frontend/dist` to Pages, which is suitable for public static playback. A backend API with an explicitly bound data source can provide real-time observability; the default development API does not automatically bind to a v2 run.
Poll 3s (no WebSocket); when the backend is unreachable, retain the previous data instead of flashing empty.
