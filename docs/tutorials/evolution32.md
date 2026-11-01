# Four six-round E2B evolution experiments

English | [简体中文](evolution32.zh-CN.md)

This tutorial uses four configurations in `examples/experiments/`. Each uses `backend/scripts/experiment.py`, starts from the current builtin seed and selects a subset of the original 32-task set. There is no need to copy materials, environments or personas from an old experiment directory. Run every command from the repository root.

See the [task catalog](../../examples/tasks/evolution32/README.md) for task content, provenance and published materials. These are new experiment examples, not byte-for-byte reproductions of a historical run. Material checks and tool probes do not establish that a complete six-round experiment has run.

| Configuration | Sessions per round | simulated_user / direct | Distinct personas | Triager / Synthesizer / Divergent | User / Developer concurrency |
| --- | --- | --- | --- | --- | --- |
| u8-mixed-e2b.json | 8 | 6 / 2 | 5 | 4 / 1 / 1 | 4 / 4 |
| u8-direct-e2b.json | 8 | 0 / 8 | 5 | 4 / 1 / 1 | 4 / 4 |
| u16-mixed-e2b.json | 16 | 12 / 4 | 8 | 8 / 1 / 1 | 4 / 4 |
| u32-mixed-e2b.json | 32 | 25 / 7 | 15 | 16 / 1 / 1 | 4 / 4 |

Each configuration starts from the builtin seed frozen during preparation and runs six rounds. R1–R5 include trials, feedback and delivery; R6 only tries the final Harness. Six rounds therefore contain five between-round delivery batches. Owner is mechanical, `synthesizer_grouping` is false and per-round official grading is disabled. Disabling official grading does not disable persona feedback or terminal review; user acceptance is not an official benchmark pass.

Each experiment uses one 4 CPU / 8192 MiB E2B sandbox, with separate Docker task environments for each session/attempt. Public examples explicitly use user concurrency 4; some historical runs started with different concurrency. This is not a guarantee that all selected tasks can reach peak resource use simultaneously. Slots have separate sessions and environments but may reuse a persona, so U32 does not mean 32 independent human profiles.

The U8 pair has identical tasks, initial inputs, persona bindings, six-round order, seed, models, roles, resources and concurrency. The direct configuration uses `interaction_overrides` to change only the original six simulated-user tasks to direct. The other two tasks remain direct. Names, repository prefixes and derived identities distinguish the two runs.

## Prepare materials and credentials

Use Linux or WSL2, Git, Python 3.12 and uv on the management machine. The E2B runtime template provides Docker remotely; Docker Desktop is not required on this machine for this route. Task definitions and the original persona library are in the repository. Larger inputs and recipes use fixed Release materials, and images use public registry digests. Preparation verifies checksums and does not need anyone's historical E2B template.

The main repository is currently private. Anonymous downloads of the material Release still require verification after it becomes public; current authenticated release checks do not establish anonymous access.

```bash
git clone https://github.com/Curry09/auto-designer.git
cd auto-designer
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
```

Fill `.env.experiment`; do not put keys in JSON:

| Credential fields | Purpose |
| --- | --- |
| USER_LLM_BASE_URL / USER_LLM_API_KEY | Simulated users and terminal review, OpenAI-compatible Chat Completions |
| HARNESS_LLM_BASE_URL / HARNESS_LLM_API_KEY | The evolving Harness, OpenAI-compatible Chat Completions |
| DEMAND_LLM_BASE_URL / DEMAND_LLM_API_KEY | Triage, Synthesizer and Divergent, OpenAI-compatible Chat Completions |
| ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN | OpenAgents Claude Code delivery, Anthropic-compatible protocol with bearer authentication |
| E2B_API_KEY | E2B access that can create the required sandbox resources and templates |
| GITEA_TOKEN | Your own Gitea.com token, allowing creation and read/write access to experiment private repositories, issues, comments and attachments |
| GITEA_USER | Optional account check for the identity resolved from the token |

The first three URLs are OpenAI base URLs, usually ending in `/v1`, not full `/chat/completions` request URLs. Delivery uses the provider's Anthropic base URL for Claude Code, not the full `/v1/messages` request URL. A gateway may expose both protocols; an OpenAI-only endpoint cannot be used directly as Claude Code's Anthropic endpoint.

The public model names are `glm-5.3-flash` for user/Harness and `glm-5.3` for demand/delivery. Before preparation, replace the four `models.*.model` values with IDs your provider actually accepts, keeping both U8 configurations equal. The examples contain no internal services, server-side thinking settings or additional model budgets.

Current User, builtin-seed Harness and demand roles request `max_tokens: 32768`, with a default input threshold of 256000. These examples do not add `limits`: provider capacity is reported as unverified instead of inferred from a model name. `reserved_output_tokens` is capacity accounting, not an output-setting switch; setting it to 128000 does not enable 128k output. An evolved Harness can change its own configuration, so inspect each round's frozen version; static capacity reports do not prove evolved request parameters. Confirm that your provider can accommodate the actual input and output total. Claude Code's own client/provider controls its output policy; do not extend the 32768 claim to delivery.

Gitea.com needs available repository capacity. Each run has its own repository, which `destroy` preserves by default. Sequential batches do not release repository slots. First-time template creation, image downloads and dependency preparation can take longer than cached runs.

## Check and start one experiment

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

Preparation streams frozen files instead of reading an entire archive into memory. Upload connection, read and write waits increase with file size. These are finite I/O waits, not a strict deadline for the entire transfer, and they do not change task or model budgets. Setup progress identifies each file being transferred.

## Collect, stop and resume

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID" --secrets-file .env.experiment
```

The cloud supervisor/controller runs independently after launch. A separate background collector on the management machine periodically collects status and artifacts. Exiting log-following does not stop the experiment. Shutting down the management machine prevents local collection; cloud execution remains subject to the provider lifecycle.

There is currently no automatic lease-renewal loop. `runtime.e2b.timeout_seconds: 86400` is the sandbox lease set at creation, not unlimited lifetime or a model budget. `stop` stops the controller while leaving the sandbox running. CLI `resume` restores checkpoints on the same running sandbox; it is not provider auto-pause/auto-resume. A paused sandbox needs explicit provider recovery. An expired or deleted instance is LOST and cannot be replaced while claiming an uninterrupted run. Long six-round experiments can exceed a day: inspect actual `expires_at`, keep collection available and retain complete archives. This tutorial does not prescribe an automatic renewal command that the runtime does not implement.

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
