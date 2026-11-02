# Quickstart

English | [简体中文](QUICKSTART.zh-CN.md)

This guide starts a complete Harness evolution experiment from an example configuration. Run every command from the repository root, using the shared entry point `backend/scripts/experiment.py`.

| Backend | Runtime | Repository hosting | Requirements |
| --- | --- | --- | --- |
| `local` | Local Docker containers | Local Gitea started automatically | Docker Engine, Compose and model credentials |
| `e2b` | One E2B sandbox per experiment | Your Gitea.com account | Model credentials, `E2B_API_KEY`, `GITEA_TOKEN` |

Start with U1: one simulated user tries the pvlib task each round for five rounds. R1–R4 include requirements processing and delivery; R5 tries the final Harness. U4 runs four user sessions across two tasks for two rounds, with user concurrency two. Both evolve the Harness, using task source code as the setting for simulated use.

The six-round U8 mixed/direct, U16 and U32 experiments use container task packages. Their materials and startup instructions are in the [six-round tutorial](tutorials/evolution32.md). The steps below use U1 to introduce the shared workflow.

## 1. Install

Use Linux or WSL2 with Git, Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/). Local execution also requires a running Docker Engine with Compose; Docker Desktop with WSL integration works.

```bash
git clone https://github.com/Curry09/AHE-Beta.git
cd AHE-Beta
uv sync --locked --extra experiments
```

Runtime recipes pin Python, uv and Claude Code versions in the [compatibility manifest](../release/compatibility.json). Preparation acquires fixed OpenAgents and NexAU versions; no separate OpenAgents checkout or personal Claude Code installation is required.

## 2. Choose the example and fill credentials

```bash
CONFIG=examples/experiments/u1-local.json
# E2B:
# CONFIG=examples/experiments/u1-e2b.json
# U4:
# CONFIG=examples/experiments/u4-local.json
# CONFIG=examples/experiments/u4-e2b.json
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

Fill `.env.experiment` with OpenAI-compatible endpoint URLs and keys for the simulated user, Harness and requirements agents, plus an Anthropic-compatible endpoint and credential for delivery. OpenAgents uses Claude Code for delivery and requires an endpoint supporting the Anthropic protocol.

U1/U4 select `claude-opus-5-5` by default. The six-round examples use `glm-5.3-flash` for users/Harness and `glm-5.3` for requirements/delivery. Before preparation, update the four `models.*.model` fields in JSON to names supported by your provider. Triage, Architect and PM share the requirements model; the examples use rule-based Owner admission.

E2B also requires a sandbox API key and a Gitea.com token permitted to create and read/write your repositories, issues, comments and attachments. Optional `GITEA_USER` checks the token's account. Local Gitea credentials are generated automatically; browser login details are saved in the run's `secrets/local-gitea-login.env`. See [configuration](CONFIGURATION.md) for the full set of fields.

## 3. Check, prepare and run

Check the configuration, then prepare experiment materials:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
```

`check --offline` validates configuration, local materials and session plans, listing uncached remote materials as pending. Online `check` also checks credentials and backend access. Model requests are sent only when you explicitly add `--probe-models`.

`prepare` freezes the controller, Harness, tasks and dependencies, downloads required sources and builds local backend images. First-time downloads and builds generally take longer than cached preparations. It prints a run ID before finishing; local builds also provide a `logs/prepare.log` path. Wait for preparation to finish successfully before starting the experiment.

After successful preparation, copy the printed ID into `RUN_ID`:

```bash
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

`run` returns after provisioning resources, checking the delivery interface and starting the controller. Query `status` from another terminal during startup: `OPERATION_IN_PROGRESS` means the operation is still working; `RUNNING` means the controller has been observed. Ctrl+C while following logs only exits the log viewer.

You can also prepare and start in one command, instead of separately calling `prepare` and `run RUN_ID`:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py run --config "$CONFIG" --secrets-file .env.experiment
```

## 4. Stop, resume and collect

Manage the experiment with the same run ID:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

`stop` preserves recovery records. `resume` continues with the original configuration, repository and resources. Local Gitea restores its original port; resolve any port conflict before retrying. To add rounds, create a child experiment from a complete archive as described in the [continuation tutorial](tutorials/experiment-continuation.md).

Default outputs are under `.experiments/<run_id>/`. Experiment, resource and collection states are recorded separately: `COMPLETED` means all configured rounds finished; collection `COMPLETE` means artifacts are complete, without implying task or experiment success. `destroy` releases compute while retaining collected artifacts, the Gitea repository and shared build caches. It refuses incomplete collection by default.

The single-run background monitor periodically collects artifacts. After successful experiment completion and complete collection, it automatically releases compute. Stopped or failed experiments need explicit cleanup. E2B `stop` only stops processes; the sandbox may still incur charges.

An E2B controller can continue after the local CLI exits, but background collection requires the management host to stay online and currently does not renew the sandbox lease. Examples set `runtime.e2b.timeout_seconds` to 86400 seconds. For long runs, monitor `expires_at` and collect regularly. CLI `resume` requires the original running sandbox; paused instances need operator recovery, and expired/deleted sandboxes are marked `LOST`. See the [six-round tutorial](tutorials/evolution32.md#collect-stop-and-resume).

## View the selected experiment

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py dashboard "$RUN_ID" --secrets-file .env.experiment
```

Local dashboards read the selected run's live artifacts. E2B dashboards show the latest `collect` snapshot and its timestamp; collect again to refresh it. With a frontend build, visit `http://127.0.0.1:8000`. For development, run `cd frontend && npm ci && npm run dev` in another terminal and visit `http://127.0.0.1:5173`.

## Enable assessment before each round’s feedback

Standard examples leave objective grading unconfigured. To provide independent task results to later requirements processing, follow the [per-round assessment tutorial](tutorials/evolution-feedback.md) to configure `evaluation.session_grading`, a private grading plan and worker keys.

Local and E2B experiments both use an `assessment-worker` on a trusted Docker host to grade frozen outputs. Start the run, then the worker. Until the worker is ready, the controller waits in `objective_grading / PENDING`. The final round also performs configured assessment. Experience ratings, task results, attribution and improvement suggestions are recorded separately.

## Grade saved session artifacts

You can also grade original session outputs after complete terminal collection, using a private grading plan:

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
GRADING_PLAN=/absolute/path/to/grading-plan.json
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py grade "$RUN_ID" --plan "$GRADING_PLAN" --offline
```

`--offline` only checks the plan and evidence bindings; remove it to execute the grader. The final round is selected by default; use `--round` for another completed, sealed round. Both local and E2B archives are graded on a Docker host without model credentials. See the [post-run grading tutorial](tutorials/post-run-grading.md) for material formats and supported cases.

To evaluate an existing Harness on new tasks, use the separate `evaluation.yaml` entry point described in the [Harbor evaluation guide](../evaluation/docs/harbor.md).

## Run a list of experiments

A batch list references complete single-experiment configurations:

```bash
BATCH_CONFIG=examples/batches/u1-u4-local.json
# BATCH_CONFIG=examples/batches/u1-u4-e2b.json
# Four six-round E2B experiments:
# BATCH_CONFIG=examples/batches/evolution-four-e2b.json
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config "$BATCH_CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config "$BATCH_CONFIG" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID" --secrets-file .env.experiment
```

Examples allow one active experiment at a time. `batch run` supervises through terminal collection in the foreground. Ctrl+C detaches supervision while started members keep running; `batch stop` stops members and `batch resume` reconnects to the same batch. Batches do not automatically destroy compute or delete repositories. See the [batch tutorial](tutorials/batch-experiment.md) for collection and cleanup.

## Offline demo and development

Offline interaction demo:

```bash
uv run --locked python backend/scripts/offline_demo.py
```

Development checks:

```bash
uv sync --locked --extra experiments --extra dev --extra harbor-evaluation
uv run --locked --extra experiments --extra dev --extra harbor-evaluation pytest -q
```

The [U1 walkthrough](tutorials/u1-experiment.md) covers expected artifacts and troubleshooting; [configuration](CONFIGURATION.md) covers models, budgets, grouping and delivery policies. For development, see [Contributing](../CONTRIBUTING.md). Reproduce historical experiments using the source revisions recorded in [research](../research/README.md).
