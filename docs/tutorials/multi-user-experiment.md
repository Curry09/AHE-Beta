# Run a two-task, four-user experiment

English | [简体中文](multi-user-experiment.zh-CN.md)

This tutorial uses the maintained U4 local/E2B examples: four distinct personas per round, two tasks, two rounds and at most two active user sessions. Every session uses the same round's Harness SHA in its own writable task workspace. The experiment evolves one shared Harness, rather than either task repository.

Run the checks in the [verification guide](../VERIFICATION.md) against this checkout. For live provider/model results, inspect the artifacts of the U4 run you start.

## 1. Install and choose a backend

Use Linux or WSL2, Git, Python 3.12 and uv. Local requires a running Docker daemon with Compose; E2B requires your API key and capacity to create a repository on your Gitea.com account. Both use the same lifecycle commands.

```bash
git clone https://github.com/Curry09/AHE-Beta.git
cd AHE-Beta
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
CONFIG=examples/experiments/u4-local.json
# CONFIG=examples/experiments/u4-e2b.json
```

Fill `.env.experiment` using [the credential guide](../CONFIGURATION.md): User, Harness and demand use OpenAI-compatible Chat Completions, delivery uses Anthropic-compatible Claude Code. E2B additionally uses `E2B_API_KEY` and `GITEA_TOKEN`; local creates its own localhost Gitea credentials. Do not put keys into JSON. If changing model names, edit the four `models.*.model` fields before prepare. A copied JSON must retain correct relative material paths.

## 2. Understand the materials and plan

`workload.task_packages` lists `examples/tasks/pvlib-1478/task.json` and `examples/tasks/order-service/task.json`. Each package has its own kind, ID, instruction, fixed source, setup and hashed lock. pvlib is fixed Git source; order-service is a small MIT demonstration project with visible tests and an existing quantities bug. The ordinary package declares `not_in_benchmark: true`. Both default to stepwise `simulated_user`; change a task package to `interaction: "direct"` before prepare for one Harness task request followed by a persona review.

Simulated personas are derived from public material in `examples/personas/library.json`. The explicit plan intentionally lets two personas try the same task in a round, then swaps tasks:

| Persona | R1 | R2 |
| --- | --- | --- |
| `sr-01-willison` | `pvlib__pvlib-python-1478` | `order-service` |
| `sr-02-ronacher` | `pvlib__pvlib-python-1478` | `order-service` |
| `sr-07-baldur` | `order-service` | `pvlib__pvlib-python-1478` |
| `sr-15-swyx` | `order-service` | `pvlib__pvlib-python-1478` |

Each round has four sessions, with `max_parallel_users: 2`. R1 waits for all terminal user sessions, runs Triage/Architect/Owner, and waits for admitted delivery tickets to reach terminal state before sealing. R2 only tries the sealed Harness; it does not generate another delivery batch. Outcomes, user satisfaction and infrastructure failures remain distinct.

For another experiment, select existing persona IDs and unique task-package IDs. `task_packages` is mutually exclusive with the old `kind` + `task_package` input. If omitting interaction_plan, global slot k=(round_no-1)*sessions_per_round+slot chooses persona k % P and task k % T. This simple rotation does not guarantee all persona × task pairs; write an explicit plan for coverage or fixed groups. The selected persona IDs remain unique; the execution list may reuse a card or complete persona/task pair. sessions_per_round counts slots, not distinct cards. Each slot has independent conversation, client, workspace and recovery identity. Repeated cards do not represent independent human samples.

## 3. Check, freeze and prepare every task

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

Offline check validates every local file, persona/task reference and round slot, showing an unfrozen preview. It does not fetch Git or produce final source-content digests. Ordinary check checks credentials and provider access; `--probe-models` is a separate optional model request. Preparation obtains pinned OpenAgents, verifies each fixed Git revision, freezes all task source inventories/instructions/setup/locks, and finally binds task digests into SessionPlan. Failure on a task does not publish a runnable partially frozen bundle.

Wait for prepare to finish; an early printed ID does not indicate readiness. Local preparation builds a shared controller/delivery base and per-task images. `runtime.local.seed_image` is only a single-task override; it cannot cover these two tasks. E2B prepares task baselines when provisioning the sandbox at run time. Cold dependency and image builds may take longer than subsequent cached runs.

## 4. Run and inspect

```bash
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

Copy the printed ID exactly. Logs identify the active stage; Ctrl+C while following logs stops the log follower. Status reports task preparation and ledger-backed per-round completed/running/pending/failed session counts. Without a ledger or reachable provider, it reports unknown rather than inferring completion from the configured eight sessions. A terminal outcome is not automatically a successful task or positive user acceptance.

The frozen bundle under `.experiments/$RUN_ID/` contains `manifest.json`, `materials/task-catalog.json`, `materials/session-plan.json` and `materials/tasks/<task_id>/` for each package/instruction/setup/lock/source archive. `resources.json` records provider resources; `runtime/task-workspaces.json` is the controller's task-workspace mapping. For local execution, actual session JSON lives in `data/role_runs/$RUN_ID/sessions/` relative to the run directory; checkpoints and round seals are under `checkpoints/`. For E2B, these paths first exist in the sandbox's run directory. After collect, their host copies are under `runtime/cloud-snapshot/data/role_runs/$RUN_ID/sessions/` and `runtime/cloud-snapshot/checkpoints/`. Check task ID/digest, persona, round/slot, stable session ID and Harness SHA together when auditing feedback.

## 5. Stop and resume the same run

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
```

Stop retains the frozen identity and checkpoint. Complete, correctly bound SessionStore results reconcile without replaying their user session or creating duplicate issues; interrupted uncompleted sessions start a clean attempt. Resume validates the original resources and logical task/persona binding. It does not mutate already finalized results, add a round, import historical archives or upgrade frozen code. An E2B sandbox that has expired or been deleted is LOST and cannot be silently replaced.

The two task packages in this tutorial use source recipes. Local sessions have separate containers; E2B copies sources and creates a new virtual environment in each session directory. Downloads and wheels may be cached while writable sources and environments remain separate. Experiments using v3 container tasks instead create task containers through the sandbox’s Docker daemon; see [backend boundaries](../CONFIGURATION.md#backend-boundaries-and-lifecycle).

## 6. Collect, view and clean up

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py dashboard "$RUN_ID" --secrets-file .env.experiment
```

The selected local dashboard reads live artifacts; E2B shows the most recent collect snapshot with its timestamp. Collect again to refresh it. Session details preserve task/persona/session/round/Harness SHA, and feedback evidence preserves the task origin. Without a tracker token, local collected artifacts are still readable offline and do not claim a connected Gitea view. If using Vite, run `cd frontend && npm ci && npm run dev` in another terminal.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

Collect at the terminal state before destruction. Destruction releases this run's compute resources, preserving the Gitea repository, collected artifacts and shared build caches. E2B stop alone leaves the sandbox allocated. The host monitor only collects while your host is online, so stay online until terminal collection succeeds.

## Cost and verification limits

This example runs eight user sessions plus their Harness requests, and one requirements/delivery round; role/model calls depend on the produced issues. Concurrency limits active sessions, not the total calls or cost. Two tasks can have different dependency-build costs. Completion requires both configured rounds to be sealed and controller completion; successful collection alone is not experiment success.

Run the offline integration check with `bash backend/scripts/e2e-spec-0073-multi-task-users.sh`. It uses real compilation, session runners, SessionStore, RecoveryStore and demand drivers, with scripted provider/model boundaries. It does not validate real Docker/E2B/Gitea or model behavior. Inspect the run’s records for actual backend and model results; current development checks are listed in [Verification](../VERIFICATION.md).
