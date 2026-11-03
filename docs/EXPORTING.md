# Public Static Snapshots

Static snapshots are used to share a summary of an experiment’s progress. The exporter retains only predefined status and count fields; raw sessions, task code, and diagnostic logs remain in the private experiment record.

## Export

Run from the repository root. The input directory should contain `telemetry/monitor-latest.json` and may also contain historical records `telemetry/monitor.jsonl`:

```bash
uv run --locked python backend/scripts/export_experiment_snapshot.py \
  "$EXPERIMENT_ROOT" "$NEW_PUBLIC_DIRECTORY" \
  --public-id demo --title "Experiment snapshot"
```

Set `EXPERIMENT_ROOT` to the experiment directory containing the existing monitoring records, and `NEW_PUBLIC_DIRECTORY` to a new directory for this export. The script generates an experiment index, the latest status, a timeline, and static API data for the frontend.

## Public Content

The export includes known statuses, normalized timestamps, non-negative integer counts, Boolean values, known roles, and alert counts. Agent identifiers are replaced with sequence numbers; unless `--public-id` is specified, experiment directory names are converted to hash identifiers.

Prompts, issue/PR bodies, raw alerts, logs, unknown fields, and free-text statuses are not exported. `--title` and `--public-id`, however, are public information provided by the operator; confirm that they contain no private content before publication. Hash identifiers do not directly expose source directory names, but they do not guarantee anonymity.

The exporter updates the target index but does not delete existing files or reprocess other experiments in the target directory. To recreate the complete set of public assets, export to a new directory, inspect the contents, and then replace the old assets. Publish only the generated static data; do not put raw telemetry, sessions, or complete experiment archives on a public site.

## Snapshot Times and Live Observations

Static pages show the status and time as recorded at collection. For example, `RUNNING` indicates that the run was still in progress when the record was created. `updated_at` in the index comes from `time` in the monitoring data and is displayed in UTC; rebuilding the site or exporting the same data again does not refresh the record time.

To view experiments while they are running, use `backend/scripts/experiment.py status`, `logs`, or `dashboard` bound to that run. The default development API does not automatically select an experiment; the E2B dashboard reads the most recently collected snapshot, so `collect` must be used again to update the data.

Exporting public snapshots and collecting experiment artifacts are separate operations. To save the complete experiment record, use `backend/scripts/experiment.py collect RUN_ID`; see [Quick Start](QUICKSTART.md).
