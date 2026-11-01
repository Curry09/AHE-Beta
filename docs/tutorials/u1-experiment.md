# A complete five-round U1 experiment

English | [简体中文](u1-experiment.zh-CN.md)

This walkthrough uses the checked-in pvlib task and `sr-15-swyx` persona. Local and E2B examples have the same task, persona, seed, roles, models and five-round semantics. Select infrastructure once; the remaining commands are identical. Run the checks in the [verification guide](../VERIFICATION.md) against this checkout.

This tutorial runs one simulated-user session per round (`rounds.sessions_per_round: 1`). See the [multi-user tutorial](multi-user-experiment.md) for four users and two tasks. `resume` continues the same run. To add rounds after a complete experiment, create a child run from an archive containing a continuation export as described in the [continuation tutorial](experiment-continuation.md).

## 1. Start from the repository

```bash
git clone https://github.com/Curry09/auto-designer.git
cd auto-designer
uv sync --locked --extra experiments
```

For local execution check `docker info` and `docker compose version`. For E2B create an E2B API key and a Gitea.com token for your own account. Preparation obtains pinned OpenAgents sources; the generated Harness repository is distinct from both the controller and the pvlib task repository.

```bash
CONFIG=examples/experiments/u1-local.json
# For cloud execution replace only the selection:
# CONFIG=examples/experiments/u1-e2b.json
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

Fill the model endpoint/key fields in the env file; E2B additionally needs its two provider keys. The models are configured as `claude-opus-5-5` in JSON. User/Harness/demand require Chat Completions-compatible endpoints; delivery needs an Anthropic-compatible endpoint. Do not expect the program to reuse another checkout's `.env` or your Claude login automatically.

## 2. Understand the input materials

| Material | What this experiment uses |
| --- | --- |
| Experiment JSON | `examples/experiments/u1-{local,e2b}.json` |
| Task metadata | `examples/tasks/pvlib-1478/task.json` |
| Requested work | ModelChain accepting time-varying albedo from a weather dataframe |
| Initial task code | `pvlib/pvlib-python` at `3f397ed44075b01f4ba535750356859195a51b2d` |
| Task environment | Checked-in setup script and dependency lock with hashes |
| Persona | `examples/personas/u1.json`, selected ID `sr-15-swyx` |
| Initial Harness | Current `backend/harness_template/`, frozen by preparation |
| Roles | One Triage, one Synthesizer, mechanical Owner, one developer; no divergent PM |

Only task text and initial code are exposed for the user workload. No gold patch or hidden test bundle is provided to optimization roles. The user can accept a result subjectively; that is distinct from official SWE-bench success, which this example does not grade.

## 3. Check and freeze

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

`check --offline` validates configuration, local materials and session plans. Online `check` also verifies credentials and Docker/provider access. Only explicit `--probe-models` sends model requests. Unknown fields, nonexistent personas and missing local files fail at this stage.

`prepare` downloads pinned sources, records material hashes and builds local runtime images. First-time preparation downloads sources, dependencies, Claude Code and Docker images, so it generally takes longer than a cached preparation. It makes no model requests or running experiment processes.

Preparation prints the run ID and frozen directory early, while the state may still be `PREPARING`. Local builds also provide `logs/prepare.log`; follow it with `tail -f /printed/path/logs/prepare.log` in another terminal. E2B preparation reports a material directory without a local image-build log. Wait for preparation to finish successfully before starting the experiment with that ID.

```bash
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
```

The snapshot is stored under `.experiments/$RUN_ID/`: `manifest.json`, `materials/`, source pins and generated plan. Use global `--runs-dir /absolute/path/runs` before every command if you chose another root. The run identity includes the config, controller and plan hashes. Later changes to your input JSON do not alter this run; prepare another run for changed settings.

## 4. Launch the complete controller

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

`run` waits for provisioning, preflight and controller startup before printing its final result; it does not stream provisioning progress to stdout. The runtime records `PROVISIONING` during startup. To inspect it, run `status` in another terminal: `OPERATION_IN_PROGRESS` means a lifecycle operation is still working, and the response includes its last recorded state. Local Gitea receives a dynamic loopback port; E2B records sandbox identity, actual capacity and expiry. Preflight validates identity, the pinned delivery reader and evidence transport. Status only reports `RUNNING` after observing the controller. Repeating run while it is alive does not start another controller.

Find the Gitea connection under `gitea` in `.experiments/<run_id>/resources.json`. Open `<url>/<owner>/<repo>` to inspect feedback, proposals, admitted delivery issues and PRs. If you selected another run root, use its corresponding resources file. For a newly created local account, the actual username and password are saved in `.experiments/<run_id>/secrets/local-gitea-login.env` with mode 0600. Read this file in your own terminal and use `GITEA_USER` / `GITEA_PASSWORD` to sign in at the URL above; keep its contents out of issues and shared logs. Resuming retains the same password. An older run without this record does not trigger a password reset. Cloud hosting uses your own Gitea.com account. Ctrl+C while following logs only stops the viewer.

## 5. Read the five-round sequence

| Round | User interaction | Requirements and delivery | Result |
| --- | --- | --- | --- |
| R1 | Tries the seed Harness | Triage/Synthesizer → mechanical Owner → OpenAgents | First sealed Harness SHA |
| R2 | Tries R1's sealed version | Same pipeline | R2 seal |
| R3 | Tries R2's sealed version | Same pipeline | R3 seal |
| R4 | Tries R3's sealed version | Same pipeline | R4 seal |
| R5 | Tries R4's sealed version | No new requirements or delivery | Final user-only seal |

A valid round can generate no admitted work, leaving its sealed SHA unchanged. Do not infer a code change just from the round number. An admitted ticket that blocks or fails automation stops the closed loop; the next round must not silently use an unsealed version.

Follow sessions, demand/Owner traces, delivery records and recovery seals together. Model output alone is insufficient evidence that files changed or a PR merged. The controller records which Harness SHA each round used and sealed.

## 6. Try stopping and resuming

While the controller is working:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

Expect a confirmed stop and preserved checkpoint. Local stop shuts down Gitea/egress and removes execution containers while retaining the repository data volume; its browser URL is unavailable while Gitea is stopped. Local resume restores the same host port and repository. Resume retains the same run ID, Gitea repository, frozen inputs and resource identity, reconciling in-flight delivery. An interrupted user session without a completion seal may need to run again. Duplicate resume must not create a second controller or deliver the same already-reconciled ticket twice.

E2B stopping processes retains an allocated sandbox. If its expiry passes or the sandbox is deleted, status becomes `LOST`; this is not recoverable by quietly provisioning another sandbox under the same identity. Keep the host online: its detached monitor periodically collects remote state, but is not permanent cloud storage.

## 7. Collect evidence and release compute

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
```

A running collection is best effort and marked `PARTIAL`. A consistent terminal archive is marked `COMPLETE`, with file hashes and an archive checksum. Inspect the reported archive path and receipt. A stopped or failed experiment can have a complete archive; its experiment outcome remains stopped or failed.

A successful five-round result requires all five recovery seals, completed recovery state, successful controller exit and matching sealed SHA. Check those records against Gitea's delivery history and the next round's actual Harness version. Normal completion releases dedicated compute after complete automatic collection. Otherwise explicitly release it after collecting:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

This keeps local evidence, Gitea repository and shared caches/templates. Destruction refuses uncollected results by default. If you deliberately accept losing those results, the explicit additional option is `--discard-uncollected`. Check status afterward: resource destruction does not turn a failed experiment into `COMPLETED`. After destruction, `collect` can package the retained host snapshot again; it does not recreate compute. For local Gitea, repository retention means its data volume is kept, not that the web service remains running.

## Troubleshooting

| Symptom | What to inspect |
| --- | --- |
| Offline check fails | Exact JSON field/file path in the error; [configuration formats](../CONFIGURATION.md) |
| Prepare fails | Download/build log, fixed source revision, dependency lock and Docker availability |
| Missing credential | Fill the named variable; confirm explicit secrets-file path and mode 0600 |
| Model request fails | Provider availability, model name, protocol/base URL and local egress; inspect controller logs |
| Resource is up but no rounds | Actual controller receipt and launch/preflight error; infrastructure alone is not success |
| Gitea.com repository creation returns HTTP 403 / maximum limit | Check your account’s repository quota. Preserve existing experiment repositories; remove an unused test repository or request a higher quota, then retry the same prepared run |
| Delivery blocked | Admitted issue/PR status and OpenAgents logs; do not advance to another round manually |
| Provider unreachable | Last observation/expiry and provider access; `UNKNOWN` does not prove a stopped controller |
| E2B lost | Last successful collection; an expired sandbox is not silently recreated by resume |
| Local resume reports a port binding conflict | Find the original port in `resources.json`; inspect listeners and Docker port mappings with the commands below, resolve the conflicting service, then retry `resume` without changing the frozen URL |
| Collection fails | Retained resource and previous archive; retry before destroying |

For a local port conflict, inspect the host before stopping the service you identify:

```bash
ss -ltnp
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Ports}}'
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID"
```

Retry resume after the original port is free. Do not edit `manifest.json`, `resources.json` or frozen evidence profiles to choose another port for this run.

There is no fixed duration guarantee: model latency, retries, task interactions and delivery steps vary. Use recorded timestamps and provider billing for actual runtime/cost. Inspect each run’s records for its actual progress and results.

The pvlib recipe includes a build-only shim for its historical Versioneer on Python 3.12. It restores removed `configparser` aliases during editable installation without patching the frozen task source, then removes the shim. The task environment includes hash-pinned pytest and pytest-mock for user-side checks. Task-environment checks are separate from official SWE-bench grading; see the [post-run grading tutorial](post-run-grading.md).

Historical experiments and their source revisions are indexed in [research](../../research/README.md). For standalone diagnostics or evidence replay, see [developer tools](../../tools/dev/README.md); their outputs are not another round of this experiment.

## View the selected experiment

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py dashboard "$RUN_ID" --secrets-file .env.experiment
```

Local dashboards read live artifacts from the selected run. For E2B, collect first, then start dashboard: it shows the latest collected snapshot. Collect again to refresh artifacts while the cloud run continues. Without a frontend build, run `cd frontend && npm ci && npm run dev` in another terminal; with a build, visit `http://127.0.0.1:8000` directly. The default development API does not automatically select a run; use this command.

See [configuration](../CONFIGURATION.md) for grouping, reasoning effort, latency isolation, delivery settings, Owner model review, direct interaction and explicit round plans. Prepare a new experiment after changing them; existing runs are not upgraded.
