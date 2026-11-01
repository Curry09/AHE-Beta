# Quickstart

English | [简体中文](QUICKSTART.zh-CN.md)

Run all commands from the auto-designer repository root. One entry point starts the complete experiment: `backend/scripts/experiment.py`. Choose a backend, then use the same commands.

| Backend | Execution | Git hosting | What you supply |
| --- | --- | --- | --- |
| `local` | Local Docker containers | A dedicated localhost Gitea started automatically | A running Docker daemon and model credentials |
| `e2b` | One E2B sandbox per experiment | Your own Gitea.com account | Model credentials, `E2B_API_KEY`, `GITEA_TOKEN` |

Choose U1 for one task and one user per round, or U4 for four users on two tasks with a concurrency limit of two. U4 runs two rounds: the first includes delivery, the second is user-only. Task-package lists and explicit persona/task plans use the same entry. Complete current-format archives can [append rounds](tutorials/experiment-continuation.md); old layouts are not automatically converted. The U1 example runs one simulated user per round for five rounds. R1–R4 include requirements and OpenAgents delivery; R5 only tries the final Harness. It evolves the Harness, using pvlib as a user task. It does not evolve the auto-designer or pvlib repository. Objective grading is unconfigured by default; optional per-round and separate post-run paths are described below.

For the original task environments, use the [six-round E2B tutorial](tutorials/evolution32.md): U8 mixed/direct have 6/2 and 0/8 simulated/direct sessions, U16 has 12/4 and U32 has 25/7. These configurations select real task packages, inputs, services and original persona bindings rather than only increasing a session count. They start from the current builtin seed, use four user and four Developer workers, and leave per-round official grading disabled. R1–R5 include delivery; R6 is trial-only. Material availability and provenance are listed in the [task catalog](../examples/tasks/evolution32/README.md).

## 1. Install

Use Linux or WSL2, Git, Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/). Local execution also requires Docker Engine with Compose; Docker Desktop with WSL integration works.

```bash
git clone https://github.com/Curry09/auto-designer.git
cd auto-designer
uv sync --locked --extra experiments
```

The runtime recipes pin uv 0.11.28, Python 3.12.13 and Claude Code 2.1.284. OpenAgents and NexAU revisions come from [the compatibility manifest](../release/compatibility.json); preparation obtains OpenAgents automatically. No sibling checkout or personal Claude installation is required.

## 2. Choose the example and fill credentials

```bash
# Local Docker + localhost Gitea:
CONFIG=examples/experiments/u1-local.json
# Alternatively, E2B + your Gitea.com account:
# CONFIG=examples/experiments/u1-e2b.json
# For four users and two tasks, select the matching backend:
# CONFIG=examples/experiments/u4-local.json
# CONFIG=examples/experiments/u4-e2b.json
# Six-round E2B study configurations:
# CONFIG=examples/experiments/u8-mixed-e2b.json
# CONFIG=examples/experiments/u8-direct-e2b.json
# CONFIG=examples/experiments/u16-mixed-e2b.json
# CONFIG=examples/experiments/u32-mixed-e2b.json
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

Edit `.env.experiment`: fill the User, Harness and demand OpenAI-compatible base URLs/API keys, and the delivery Anthropic-compatible base URL/token. U1/U4 use `claude-opus-5-5`; the four six-round study configurations use `glm-5.3-flash` for User/Harness and `glm-5.3` for demand/delivery. Change the four `models.*.model` fields before preparation if your provider uses other names. Demand is shared by Triage, Synthesizer and PM; Owner admission is mechanical. An OpenAI-only endpoint is insufficient for Claude Code delivery, which needs its own compatible Anthropic base URL.

For E2B also fill `E2B_API_KEY` and a Gitea.com token allowed to create and read your private repositories, issues, comments and attachments. `GITEA_USER` optionally checks the account resolved from the token. Local Gitea credentials are generated automatically; a newly created account’s browser login is saved in the run’s `secrets/local-gitea-login.env` with mode 0600. See [configuration](CONFIGURATION.md) for exact formats.

## 3. Check, prepare and run

Once credentials are filled, a single command prepares and starts the run. Use its printed run ID for status, logs and collection:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py run --config "$CONFIG" --secrets-file .env.experiment
```

Alternatively, use the separate steps below to inspect preparation before starting. Choose one approach.

The paired execution-evidence reader is pinned to a published review candidate in `release/compatibility.json`. Preparation uses that immutable revision by default; see the [readiness note](tutorials/evolution-feedback.md#3-check-and-prepare). The two repositories still need joint review before release.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

Offline checking validates JSON and referenced local materials without model calls or cloud resources. Remote inputs not present in the verified cache remain pending; an offline pass does not prove downloaded bytes or provider readiness. The second check validates configured credentials and Docker/provider access; it does not send model requests unless you explicitly add `--probe-models`. Preparation generates a unique run ID, freezes inputs, downloads fixed source revisions, and builds required local images. It does not call models or start experiment resources. After freezing, `[prepare]` prints the run ID and, for local builds, a log path. In another terminal, run `tail -f /printed/path/logs/prepare.log` to follow the first image build. The first run downloads sources, dependencies, Claude and Docker images; a cold build can take substantially longer than later cached preparations. Wait for preparation to finish successfully before running the experiment; the early ID does not mean it is ready. Copy the run ID:

```bash
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

`run` provisions resources, checks the actual delivery reader and launches the controller, then prints its result. During startup, use `status` in another terminal to inspect the last recorded state; `OPERATION_IN_PROGRESS` means the startup operation is still working. Resource creation alone is not `RUNNING`. Following logs can be stopped with Ctrl+C without stopping the experiment. The first cloud run may build an E2B template.

## 4. Stop, resume and collect

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

`stop` retains the identity, repository and recovery checkpoint. Locally it stops Gitea/egress and removes execution containers while retaining Gitea data; resume restores the original loopback port and repository. If that port is occupied, resolve the conflict and retry resume rather than editing the frozen address. An E2B sandbox remains allocated after stopping its processes. Resume uses the same frozen inputs and surviving resources; an expired or deleted sandbox is `LOST` and cannot be silently replaced. Destruction preserves collected artifacts, the Gitea repository and shared build caches; it refuses to discard uncollected results unless explicitly requested.

Runs live under `.experiments/<run_id>/`. Experiment outcome, resource state and collection state are separate: `COMPLETED` requires every configured round to be sealed and the controller to finish; `COMPLETE` collection alone does not mean experiment success. While the host is online, the monitor periodically collects results and automatically releases compute after experiment `COMPLETED` and collection `COMPLETE`, retaining archives and the Gitea repository. Stopped and failed experiments do not use this automatic cleanup path. Keep the host online until terminal collection succeeds; cloud expiry can lose data not yet collected.

The E2B creation lease is `runtime.e2b.timeout_seconds`, set to 86400 in the examples. The current background collector does not renew it. The cloud supervisor can keep running after the local CLI exits, but a long six-round job can exceed a day. Inspect actual `expires_at` and collect regularly; CLI `resume` requires the original running sandbox and does not automatically restore a provider-paused instance. See the [six-round tutorial](tutorials/evolution32.md#collect-stop-and-resume) for this lifecycle boundary.

The [complete U1 tutorial](tutorials/u1-experiment.md) explains every input, expected outputs, interruption boundaries and evidence. The [multi-user tutorial](tutorials/multi-user-experiment.md) runs U4 with two tasks, a fixed cross-round plan and stop/resume. Actual validation results are recorded in the [U1 report](validation/spec-0069-new-user.md) and [multi-user report](validation/spec0073-multi-task-users.md).

## Enable assessment before each round’s feedback

The standard examples leave objective grading unconfigured. To use independent task results in later feedback, follow the [per-round assessment tutorial](tutorials/evolution-feedback.md). It generates a public task, private grading plan and worker key, then uses the same `check → prepare → run` entry with an external `assessment-worker`. Both local and E2B require a trusted Docker host for this worker. Start the run first, then the worker in another terminal. Without it, the controller waits in `objective_grading / PENDING` rather than reporting a pass or zero. The final user-only round is assessed too.

Actor outputs are frozen before terminal read-only review. Experience ratings, task results, cause attribution and suggestions are separate; missing ratings remain null and a successful session may publish no Issues. An explicit 7200-second task budget overrides the runtime's 1800-second fallback. See [configuration](CONFIGURATION.md) for message limits and static context-capacity checks. This optional path does not change the post-run command below or the independent Harness benchmark framework.

## Grade saved session artifacts

After complete terminal collection, install the evaluation extra and prepare a private grading plan. The plan selects original task IDs, adapters and local materials with SHA-256 hashes; SWE declares its official dataset there too. Local and E2B archives are both scored on this host with Docker; `grade` needs no model or provider credentials.

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
GRADING_PLAN=/absolute/path/to/grading-plan.json
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py grade "$RUN_ID" --plan "$GRADING_PLAN" --offline
```

Run the same command without `--offline` to execute the selected graders; SWE uses an official fresh-instance container. The default is the configured final round; `--round 1` selects an earlier sealed round. These are scores for original user-session artifacts, not a new held-out Harness evaluation, and they never enter the evolution loop. Each grading attempt preserves original artifacts. Older controllers without full prediction receipts need a new experiment. See the [grading tutorial](tutorials/post-run-grading.md) for plan templates, material formats, supported tasks and failure states.

## Run a list of experiments

After filling the same `.env.experiment`, choose a batch list instead of one run configuration:

```bash
BATCH_CONFIG=examples/batches/u1-u4-local.json
# BATCH_CONFIG=examples/batches/u1-u4-e2b.json
# Four six-round E2B study configurations, one active run at a time:
# BATCH_CONFIG=examples/batches/evolution-four-e2b.json
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config "$BATCH_CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config "$BATCH_CONFIG" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID" --secrets-file .env.experiment
```

The examples use one active run at a time. `batch run` stays in the foreground through terminal collection; Ctrl+C detaches supervision and leaves started children running. Use `batch stop` to stop them, and `batch resume` to continue the original members. U1 runs five rounds and U4 two rounds, so these lists demonstrate scheduling, not a fair causal comparison. See the [complete batch tutorial](tutorials/batch-experiment.md) for status, child-specific `--runs-dir`, collection, costs and explicit cleanup. Batch management does not automatically destroy compute or delete repositories; E2B stop still retains its sandbox.


## Offline demo and development

For a short scripted interaction without models or Docker:

```bash
uv run --locked python backend/scripts/offline_demo.py
```

For controller development:

```bash
uv sync --locked --extra experiments --extra dev
uv run --locked --extra experiments --extra dev pytest -q
```

The public examples directory contains only current v2 definitions. [Developer tools](../tools/dev/README.md) are separate diagnostics, not alternate experiment launchers. [Historical research](../research/README.md) is archived with source revisions and an inventory; reproduction uses the recorded version in a separate checkout. New experiments use the unified entry above. The optional frontend is described in [the README](../README.md).

## View the selected experiment

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py dashboard "$RUN_ID" --secrets-file .env.experiment
```

Local dashboards read live artifacts from the selected run. For E2B, collect first, then start dashboard: it shows the latest collected snapshot. Collect again to refresh artifacts while the cloud run continues. Without a frontend build, run `cd frontend && npm ci && npm run dev` in another terminal; with a build, visit `http://127.0.0.1:8000` directly. The default development API does not automatically select a run; use this command.

See [configuration](CONFIGURATION.md) for grouping, reasoning effort, latency isolation, delivery settings, Owner model review, direct interaction and explicit round plans. Prepare a new experiment after changing them; existing runs are not upgraded.
