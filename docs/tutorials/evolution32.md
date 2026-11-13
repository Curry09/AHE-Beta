# Four six-round E2B evolution experiments

English | [简体中文](evolution32.zh-CN.md)

This tutorial covers the six-round U8 mixed, U8 direct, U16 mixed and U32 mixed experiments. Each starts through `backend/scripts/experiment.py` from the current seed Harness and selects a subset of the 32-task collection. Task definitions, environment recipes and personas are included in the repository; preparation acquires larger materials. Run every command from the repository root.

The [task catalog](../../examples/tasks/evolution32/README.md) records task content, provenance, pinned versions and material locations. Preparation freezes these inputs together with the configuration, controller and seed Harness to create an independent run.

| Configuration | Sessions per round | simulated_user / direct | Distinct personas | Triager / Architect / Divergent | User / Developer concurrency |
| --- | --- | --- | --- | --- | --- |
| u8-mixed-e2b.json | 8 | 6 / 2 | 5 | 4 / 1 / 1 | 4 / 4 |
| u8-direct-e2b.json | 8 | 0 / 8 | 5 | 4 / 1 / 1 | 4 / 4 |
| u16-mixed-e2b.json | 16 | 12 / 4 | 8 | 8 / 1 / 1 | 4 / 4 |
| u32-mixed-e2b.json | 32 | 25 / 7 | 15 | 16 / 1 / 1 | 4 / 4 |

Each configuration starts from the builtin seed frozen during preparation and runs six rounds. R1–R5 include trials, feedback and delivery; R6 only tries the final Harness. Six rounds therefore contain five between-round delivery batches. Owner is mechanical, `architect_grouping` is false and per-round official grading is disabled. Disabling official grading does not disable persona feedback or terminal review; user acceptance is not an official benchmark pass.

Each experiment uses one 4 CPU / 8192 MiB E2B sandbox, separate Docker task environments per session attempt, and user concurrency four. Choose concurrency with task memory and service requirements in mind. Sessions and environments are separate, but personas may be reused: U32 means 32 sessions per round, with the distinct persona count shown above.

The U8 pair has identical tasks, initial inputs, persona bindings, six-round order, seed, models, roles, resources and concurrency. The direct configuration uses `interaction_overrides` to change only the original six simulated-user tasks to direct. The other two tasks remain direct. Names, repository prefixes and derived identities distinguish the two runs.

## Prepare materials and credentials

Use Linux or WSL2, Git, Python 3.12 and uv on the management machine. The E2B runtime template provides Docker remotely; Docker Desktop is not required on this machine for this route. Task definitions and the original persona library are in the repository. Larger inputs and recipes use fixed Release materials, and images use public registry digests. Preparation verifies checksums and does not need anyone's historical E2B template.

Task materials come from the versioned Release recorded in the manifest. Confirm that the management host can access those download URLs. Preparation verifies material hashes; offline checks list uncached remote materials as pending.

```bash
git clone https://github.com/Curry09/AHE-Beta.git
cd AHE-Beta
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

Fill `.env.experiment`; do not put keys in JSON:

| Credential fields | Purpose |
| --- | --- |
| USER_LLM_BASE_URL / USER_LLM_API_KEY | Simulated users and terminal review, OpenAI-compatible Chat Completions |
| HARNESS_LLM_BASE_URL / HARNESS_LLM_API_KEY | The evolving Harness, OpenAI-compatible Chat Completions |
| DEMAND_LLM_BASE_URL / DEMAND_LLM_API_KEY | Triage, Architect and Divergent, OpenAI-compatible Chat Completions |
| ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN | OpenAgents Claude Code delivery, Anthropic-compatible protocol with bearer authentication |
| E2B_API_KEY | E2B access that can create the required sandbox resources and templates |
| GITEA_TOKEN | Your own Gitea.com token, allowing creation and read/write access to experiment private repositories, issues, comments and attachments |
| GITEA_USER | Optional account check for the identity resolved from the token |

The first three URLs are OpenAI base URLs, usually ending in `/v1`, not full `/chat/completions` request URLs. Delivery uses the provider's Anthropic base URL for Claude Code, not the full `/v1/messages` request URL. A gateway may expose both protocols; an OpenAI-only endpoint cannot be used directly as Claude Code's Anthropic endpoint.

The public model names are `glm-5.3-flash` for user/Harness and `glm-5.3` for demand/delivery. Before preparation, replace the four `models.*.model` values with IDs your provider actually accepts, keeping both U8 configurations equal. The examples contain no internal services, server-side thinking settings or additional model budgets.

Current User, builtin-seed Harness and demand roles request `max_tokens: 32768`, with a default input threshold of 256000. These examples do not add `limits`: provider capacity is reported as unverified instead of inferred from a model name. `reserved_output_tokens` is capacity accounting, not an output-setting switch; setting it to 128000 does not enable 128k output. An evolved Harness can change its own configuration, so inspect each round's frozen version; static capacity reports do not prove evolved request parameters. Confirm that your provider can accommodate the actual input and output total. Claude Code's own client/provider controls its output policy; do not extend the 32768 claim to delivery.

Gitea.com needs available repository capacity. Each run has its own repository, which `destroy` preserves by default. Sequential batches do not release repository slots. First-time template creation, image downloads and dependency preparation can take longer than cached runs.

## Check and start one experiment

Eight tasks have a 1-, 2-, or 8-hour execution limit, as stated in their instructions. The clock starts with the first task message. Setup and terminal review are outside that window, and follow-up messages do not reset it. At the deadline, the controller stops the Harness and saves the available outputs. It then makes one request for user feedback, with a 300-second limit. The other tasks have no task-wide limit in these examples.

```bash
CONFIG=examples/experiments/u8-mixed-e2b.json
# Alternatives: u8-direct-e2b.json, u16-mixed-e2b.json, u32-mixed-e2b.json.
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py run --config "$CONFIG" --secrets-file .env.experiment
```

Offline checking validates configuration, personas, round plans and material declarations without cloud resources or model requests. Ordinary `check` checks credentials/provider access; only explicit `--probe-models` sends model connectivity requests. A connectivity probe does not establish successful task execution or six-round completion.

`run --config` prepares before starting. Successful preparation freezes the current controller, builtin seed, OpenAgents, tasks and configuration identities. To inspect preparation separately:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
```

A failed prepare retains verified caches. Printing a run ID does not mean preparation succeeded. Before model requests, the runtime checks actual sandbox, Docker and image capabilities; each attempt initializes its task and checks service readiness before starting its Actor. Materials, toolchain probes and a complete model-driven six-round experiment are separate validation claims.

When an E2B run starts, the controller streams the files saved during preparation, one at a time. The startup log shows which file is uploading. Larger files get longer connection, read, and write timeouts. These timeouts apply to network operations for each file; they do not cap the total upload time or change task and model budgets.

## Try a single round

To try U32 for a single round, make a copy of `u32-mixed-e2b.json` in the same directory so the relative paths to tasks and personas still work. In the copy, set `rounds.count` to `1` and keep only the first round in `workload.interaction_plan`.

To run locally, replace the copy's entire `runtime` section with the one from `u4-local.json` and choose a different repository prefix for this run. Local runs need Docker Engine and Compose and start their own Gitea, so no E2B or Gitea.com credentials are needed. For either runtime, point `CONFIG` to the copied file and follow the steps above to check the configuration, prepare the inputs, and start the run.

A single round lets you check whether the seed Harness can complete user sessions in the task environments and whether the run can collect the resulting artifacts. Since this is also the final round, it skips requirements processing and OpenAgents delivery. To test delivery, use a smaller two-round example such as U4 and keep both session plans. OpenAgents picks up work only if the first round produces an issue approved for delivery.

## Collect, stop and resume

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID" --secrets-file .env.experiment
```

The cloud supervisor/controller runs independently after launch. A separate background collector on the management machine periodically collects status and artifacts. Exiting log-following does not stop the experiment. Shutting down the management machine prevents local collection; cloud execution remains subject to the provider lifecycle.

A `PARTIAL` archive preserves the evidence collected so far for inspection. `resume` uses the original run and its checkpoints in the original environment; it does not restore from the archive. Starting a new run from an archive requires a [completed experiment with a continuation-ready archive](experiment-continuation.md).

If local Docker restarts, wait until `docker info` succeeds before running `resume`. The controller reuses completed sessions and tries to finish collecting any missing outputs from the original task environment. If Docker confirms that the original environment is gone, only the affected session is retried with the same round inputs and Harness version. If the controller cannot verify the original environment or determine whether a finalization script finished, keep the run directory and its archives for diagnosis. Once a session's result is saved, a cleanup failure is recorded separately and does not block the next round.

E2B sandbox leases are not automatically renewed. `runtime.e2b.timeout_seconds: 86400` sets the creation lease and is independent of model output budgets. `stop` stops the controller and retains the sandbox; CLI `resume` requires the original sandbox to be running. Restore paused instances through the provider first; expired or deleted instances are marked `LOST`. Six-round experiments may exceed a day, so monitor actual `expires_at`, keep management-host collection available and retain complete archives.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID"
```

After successful terminal collection, the background collector releases completed runs' compute. Manual `destroy` preserves Gitea and collected local artifacts. Data that exists only inside the sandbox is not yet a delivered archive.

## Run the four-group batch

```bash
BATCH=examples/batches/evolution-four-e2b.json
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config "$BATCH" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config "$BATCH" --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID" --secrets-file .env.experiment
```

The batch uses `max_parallel_runs: 1`, running one group at a time. This limits experiment groups, not users or Developers. `batch run` is a foreground supervisor: keep that machine/session running, or use a persistent terminal. It does not use each single run's detached collector.
