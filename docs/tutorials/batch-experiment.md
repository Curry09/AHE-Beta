# Run a batch of complete experiments

English | [简体中文](batch-experiment.zh-CN.md)

A batch freezes a list of existing experiment configurations and supervises their complete runs. Each member has its own frozen inputs, Harness repository, resources, checkpoints and results. The same `backend/scripts/experiment.py` entry manages both the batch and individual members; the batch does not introduce another controller.

The public examples list N1 and N4 on the same backend. **They demonstrate batch execution, not a fair causal comparison:** N1 runs five rounds on one task, while N4 runs two rounds on two tasks. Those settings remain unchanged. See the [N1](n1-experiment.md) and [N4](multi-user-experiment.md) tutorials for their full workflows. For a controlled comparison, prepare separate complete configurations with the factors you intend to compare.

## 1. Install and select the list

Use the [Quickstart](../QUICKSTART.md) to install dependencies and fill credentials. Local requires Docker with Compose; E2B requires E2B capacity and your own Gitea.com account. Run commands from the repository root.

```bash
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
RUNS_DIR=.experiments
BATCH_CONFIG=examples/batches/n1-n4-local.json
# BATCH_CONFIG=examples/batches/n1-n4-e2b.json
```

Fill `.env.experiment` before online checks. To change models, rounds or personas, copy and edit each experiment JSON before preparation; keep its relative material paths valid. Then point each batch entry at that complete configuration. Keep credentials in the protected env file, never in either JSON.

A batch uses `schema_version: 1`, a name, `max_parallel_runs` (default `1`) and nonempty `entries` with unique `id` and `config` fields. Configuration paths are relative to the batch JSON. All entries must use the same backend. Partial overrides, parameter matrices, arbitrary shell commands and mixed-backend batches are unsupported. See [configuration](../CONFIGURATION.md#batch-configuration).

## 2. Check and freeze all members

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch check --config "$BATCH_CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch check --config "$BATCH_CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch prepare --config "$BATCH_CONFIG" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
```

Offline check validates each member's local materials without credentials, Git fetches or provider operations. Online check reuses the single-run credential/provider checks. It reports repository capacity as unknown when the provider cannot establish a remaining quota; unknown is not proof that enough repositories are available.

Preparation freezes members sequentially and records their exact run IDs. It starts no experiment resources or model calls. Wait for all members to prepare successfully. Preparation errors block startup; they do not permit a partially prepared batch to run. If preparation was interrupted, `batch resume` reconciles that batch's existing children; it does not silently prepare replacement experiments for an existing failed child.

## 3. Run under foreground supervision

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch run "$BATCH_ID" --secrets-file .env.experiment
```

Keep this command running. Unlike single-run `run`, which returns a startup acknowledgement, `batch run` supervises members through terminal collection. A started member still occupies its slot. Unknown activity, an operation still in progress, or incomplete terminal collection also retains the slot and prevents unsafe dispatch. A failed or lost member blocks remaining pending members; already active members continue to be observed and collected.

Ctrl+C detaches batch supervision and stops new queued dispatch. **It does not stop started experiments.** Reattach with `batch resume`; to stop their processes use `batch stop`. Another terminal can inspect the batch:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch status "$BATCH_ID" --secrets-file .env.experiment
```

`max_parallel_runs` limits active or uncertain run leases in this batch. It is neither an account-wide limit nor a maximum number of allocated sandboxes or model calls. Each child retains its configured `max_parallel_users`; N4 uses two concurrent user sessions. Stopped or completed resources may still be allocated, and independent experiments or batches are outside this limit.

## 4. Stop, resume and collect the same members

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch stop "$BATCH_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch resume "$BATCH_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" batch collect "$BATCH_ID" --secrets-file .env.experiment
```

Stop persists the pause request before stopping started children. A stopping or unreachable child is not immediately reported as paused. Resume attaches to active children, resumes stopped children from their original checkpoint, and starts only members that have never started. It preserves frozen models, tasks and plans; it does not upgrade code or replace a LOST sandbox.

Collection reports complete, partial or failed collection per member. A successful batch requires every experiment to be `COMPLETED` and every terminal collection to be `COMPLETE`. Collection success alone does not prove experiment success or benchmark performance. Keep the host online until terminal collection succeeds.

## 5. Inspect one child and clean up retained resources

The batch is stored in `$RUNS_DIR/.batches/$BATCH_ID/`. Its `intent.json` and `manifest.json` preserve the selected members; `runtime.json` and `journal.jsonl` record scheduling observations. Each child lives under `children/<entry_id>/<run_id>/` and retains its normal single-run artifacts. Copy the child's run ID from `entries[entry_id].run_id` and its root from `child_roots[entry_id]` in batch status, then use the commands below.

For the `n1` entry, replace the printed run ID below; use `children/n4` for the other member:

```bash
CHILD_RUNS_DIR="$RUNS_DIR/.batches/$BATCH_ID/children/n1"
RUN_ID=REPLACE_WITH_PRINTED_CHILD_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" status "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" logs "$RUN_ID" --follow --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" dashboard "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" collect "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$CHILD_RUNS_DIR" destroy "$RUN_ID" --confirm "$RUN_ID" --secrets-file .env.experiment
```

Always pass the child's `--runs-dir`; its ID is not located at the outer runs root. E2B dashboards show a collected snapshot, so collect first. Destroy only after complete collection. Batch management does not automatically destroy compute or delete repositories. Stopping an E2B process retains its allocated sandbox; inspect resource state and use the explicit cleanup commands. Compute destruction preserves the Gitea repository. Remove old repositories yourself only after preserving any needed records.

These examples normally need two separate Harness repositories. Serial execution can still exhaust repository quota because repositories remain after earlier members finish. The N1/N4 list schedules thirteen user sessions in total, plus their Harness requests and requirements/delivery work; concurrency limits do not reduce total calls or cost. Cloud allocation, dependency builds and model generation add their own costs. Neither a capacity-unknown check nor this tutorial claims that a provider account has enough quota.

The [single-run multi-user validation report](../validation/spec0073-multi-task-users.md) applies to independent N4 runs. It is not evidence of a live local/E2B batch. Batch tests using scripted provider/model boundaries must be recorded separately from live execution.
