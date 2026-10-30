# Quickstart

English | [简体中文](QUICKSTART.zh-CN.md)

Run all commands from the auto-designer repository root. One entry point starts the complete experiment: `backend/scripts/experiment.py`. Choose a backend, then use the same commands.

| Backend | Execution | Git hosting | What you supply |
| --- | --- | --- | --- |
| `local` | Local Docker containers | A dedicated localhost Gitea started automatically | A running Docker daemon and model credentials |
| `e2b` | One E2B sandbox per experiment | Your own Gitea.com account | Model credentials, `E2B_API_KEY`, `GITEA_TOKEN` |

Choose N1 for one task and one user per round, or N4 for four users on two tasks with a concurrency limit of two. N4 runs two rounds: the first includes delivery, the second is user-only. Task-package lists and explicit persona/task plans use the same entry. Historical-result import for an extra round remains unsupported. The N1 example runs one simulated user per round for five rounds. R1–R4 include requirements and OpenAgents delivery; R5 only tries the final Harness. It evolves the Harness, using pvlib as a user task. It does not evolve the auto-designer or pvlib repository. Objective grading is unconfigured by default; optional per-round and separate post-run paths are described below.

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
CONFIG=examples/experiments/synthesizer-n1-local.json
# Alternatively, E2B + your Gitea.com account:
# CONFIG=examples/experiments/synthesizer-n1-e2b.json
# For four users and two tasks, select the matching backend:
# CONFIG=examples/experiments/synthesizer-n4-local.json
# CONFIG=examples/experiments/synthesizer-n4-e2b.json
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

Edit `.env.experiment`: fill the User, Harness and demand OpenAI-compatible base URLs/API keys, and the delivery Anthropic-compatible base URL/token. The example model is `claude-opus-5-5`; change the four `models.*.model` fields in a copied JSON if your provider uses another name. Demand is shared by Triage, Synthesizer and PM; Owner admission is mechanical.

For E2B also fill `E2B_API_KEY` and a Gitea.com token allowed to create and read your private repositories, issues, comments and attachments. `GITEA_USER` optionally checks the account resolved from the token. Local Gitea credentials are generated automatically; a newly created account’s browser login is saved in the run’s `secrets/local-gitea-login.env` with mode 0600. See [configuration](CONFIGURATION.md) for exact formats.

## 3. Check, prepare and run

The paired execution-evidence reader is pinned to a published review candidate in `release/compatibility.json`. Preparation uses that immutable revision by default; see the [readiness note](tutorials/evolution-feedback.md#3-check-and-prepare). The two repositories still need joint review before release.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

Offline checking validates JSON and referenced local materials without model calls or cloud resources. The second check validates configured credentials and Docker/provider access; it does not send model requests unless you explicitly add `--probe-models`. Preparation generates a unique run ID, freezes inputs, downloads fixed source revisions, and builds required local images. It does not call models or start experiment resources. After freezing, `[prepare]` prints the run ID and, for local builds, a log path. In another terminal, run `tail -f /printed/path/logs/prepare.log` to follow the first image build. The first run downloads sources, dependencies, Claude and Docker images; a cold build can take substantially longer than later cached preparations. Wait for preparation to finish successfully before running the experiment; the early ID does not mean it is ready. Copy the run ID:

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

Runs live under `.experiments/<run_id>/`. Experiment outcome, resource state and collection state are separate: `COMPLETED` requires every configured round to be sealed and the controller to finish; `COMPLETE` collection alone does not mean experiment success. The host monitor collects periodically while the host is online. Keep it online until terminal collection succeeds; cloud expiry can lose data not yet collected.

The [complete N=1 tutorial](tutorials/n1-experiment.md) explains every input, expected outputs, interruption boundaries and evidence. The [multi-user tutorial](tutorials/multi-user-experiment.md) runs N4 with two tasks, a fixed cross-round plan and stop/resume. Actual validation results are recorded in the [N1 report](validation/spec-0069-new-user.md) and [multi-user report](validation/spec0073-multi-task-users.md).

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
BATCH_CONFIG=examples/batches/n1-n4-local.json
# BATCH_CONFIG=examples/batches/n1-n4-e2b.json
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config "$BATCH_CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config "$BATCH_CONFIG" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID" --secrets-file .env.experiment
```

The examples use one active run at a time. `batch run` stays in the foreground through terminal collection; Ctrl+C detaches supervision and leaves started children running. Use `batch stop` to stop them, and `batch resume` to continue the original members. N1 runs five rounds and N4 two rounds, so these lists demonstrate scheduling, not a fair causal comparison. See the [complete batch tutorial](tutorials/batch-experiment.md) for status, child-specific `--runs-dir`, collection, costs and explicit cleanup. Batch management does not automatically destroy compute or delete repositories; E2B stop still retains its sandbox.


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
