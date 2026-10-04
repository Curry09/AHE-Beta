# Experiment configuration

English | [简体中文](CONFIGURATION.zh-CN.md)

New experiments use JSON with `schema_version: 2` and the unified entry described in [Quickstart](QUICKSTART.md). Copy either [local](../examples/experiments/synthesizer-n1-local.json) or [E2B](../examples/experiments/synthesizer-n1-e2b.json) example. Unknown fields are rejected; old evaluation schemas and v1 lifecycle commands are rejected before provider operations.

## Files you supply

| Input | Format | Example |
| --- | --- | --- |
| Experiment | v2 JSON: backend, Harness, workload, rounds, roles, models | `examples/experiments/synthesizer-n1-local.json` |
| Task | v1 JSON: instruction, source, setup script, dependency lock | `examples/tasks/pvlib-1478/task.json` |
| Instruction | UTF-8 task text, without a solution or hidden tests | `examples/tasks/pvlib-1478/instruction.md` |
| Setup | Trusted shell script; creates the isolated task environment | `examples/tasks/pvlib-1478/setup.sh` |
| Task dependencies | Fully pinned requirements with SHA-256 hashes | `examples/tasks/pvlib-1478/requirements.lock` |
| Personas | JSON array following the repository persona schema | `examples/personas/n1.json` |
| Credentials | Explicit environment variables or a mode-0600 env file | `examples/experiment.env.example` |

The N1 example uses `examples/personas/n1.json`. N4 uses four real cards from the maintained `examples/personas/library.json`. Select unique IDs present in the library. A persona card may be reused across multiple independent sessions in the same round.

Paths in the experiment are relative to that JSON; task paths are relative to the task package. `check --offline` shows an unfrozen allocation preview without fetching Git. `prepare` freezes each task's package, instruction, setup, dependency lock and verified source archive, then creates `materials/task-catalog.json`, `materials/session-plan.json`, the persona roster, Harness archive and hash manifest. You do not need to handcraft these.

## Experiment fields

| Field | Meaning |
| --- | --- |
| `name` | Display name; a unique `run_id` is generated automatically |
| `runtime.backend` | `local` or `e2b` |
| `runtime.gitea` | Provider `localhost` for local, `gitea.com` for E2B; repository prefix |
| `runtime.local` | Optional image overrides and `ci_enabled` (default `false`); local engineering CI requires a verified dedicated runner |
| `runtime.e2b` | Requested `cpu_count`, `memory_mb`, `timeout_seconds` (300–86400); optional compatible template |
| `runtime.harness` | Optional per-request budget and infrastructure termination grace; applies to both backends |
| `harness.source` | `builtin`, `archive` with a path and SHA-256, or `continuation` with the matching parent source |
| `workload` | Task packages with persona inputs/optional interaction_plan, or exactly `{"source":"parent"}` for continuation |
| `rounds` | `count`, `sessions_per_round`, `max_parallel_users`; continuation count means added user rounds |
| `continuation` | Optional current parent `archive` path and expected `sha256`; requires both parent input selectors |
| `roles` | Triage/Synthesizer/divergent/developer counts; `owner_mode: mechanical` / `llm` |
| `models` | User, Harness, shared demand and Claude Code delivery settings |
| `evaluation.official_grading` | `false`; evolution stays ungraded; use the independent post-run `grade` command |
| `source` | Optional credential-free HTTPS repository and full immutable revisions; defaults come from `release/compatibility.json` |

Choose one or more task packages. sessions_per_round counts execution slots and may exceed the number of selected personas; max_parallel_users must not exceed sessions_per_round. Both personas and complete persona/task pairs may repeat in one round. Each package supplies its own kind and interaction. Current complete archives with a continuation export support additional rounds in a new run; see [continuation](tutorials/experiment-continuation.md). The N=1 examples select one persona, one Triage, one Synthesizer, zero divergent PMs, one delivery worker, and five rounds. The last round is always user-only.

`builtin` freezes this checkout's `backend/harness_template/`. It is not the historical `cade14d` Harness. To reproduce that baseline, supply its actual archive and checksum explicitly.

### Harness request deadlines

To give each Harness request a one-hour budget, add this fragment to `runtime`:

```json
"harness": {
  "request_budget_seconds": 3600,
  "termination_grace_seconds": 60
}
```

The launcher sends the budget in the message and compatible product environment variables. The selected Harness must implement its internal budget; infrastructure terminates a request that has not replied after budget plus grace (3660 seconds here). Request receipts distinguish a Harness reply from infrastructure termination. These are request deadlines, separate from E2B sandbox lifetime and delivery-role timeouts. Writing a duration in task text does not configure a deadline.

The budget must be positive and at most 86400 seconds. Grace must be positive and at most 300 seconds; omission defaults to 60. Without `runtime.harness`, the launcher retains its existing 1800-second fallback, accounts for recognized legacy product limits, and adds 60 seconds of termination grace. Host settings are not inherited by the public entry; old frozen configurations do not gain new fields or change identity. Prepared runs continue using their frozen controller.

Feedback roles read a source snapshot at the tested commit, while triage of a historical report uses that report's recorded commit. A missing commit blocks source access rather than silently reading the current checkout. New direct sessions preserve the received progress and reply steps in full, following simulated-session storage; evidence queries use shared summary and expansion limits. Their persona reviewer still sees only the terminal reply. Older sessions without these records remain unknown.

## Continue from a current completed archive

Merge the following input selectors into a complete v2 definition; the [continuation tutorial](tutorials/experiment-continuation.md) generates full local/E2B configurations from existing templates.

```json
{
  "harness": {"source": "continuation"},
  "workload": {"source": "parent"},
  "continuation": {
    "archive": "/absolute/path/to/parent/artifacts.tar.gz",
    "sha256": "EXPECTED_64_CHARACTER_SHA256"
  },
  "rounds": {"count": 2, "sessions_per_round": 4, "max_parallel_users": 2}
}
```

All three selectors are required together. `continuation` accepts only `archive` and `sha256`; paths resolve relative to the child JSON. The parent must have collection `COMPLETE`, `controller.experiment_complete=true` and `continuation_ready=true`, including the versioned final-tree export. Unsupported or missing exports are rejected before provisioning; old frozen controllers are not upgraded.

Every added round inherits the parent's final task/persona/interaction pairs, including `direct` sessions. `sessions_per_round` equals that boundary's size; `max_parallel_users` may be smaller. Workload overrides are forbidden. Pending reports require Triage and Synthesizer counts of at least one. Models, runtime, roles, policies and credentials are explicit child choices; optional CI uses the child's normal local-only contract.

The child first runs an independent feedback initialization and waits for delivery, even when count is one. `count` then counts new users; the final new round remains users-only. Parent logical R5 plus count two gives child local R1/R2 at logical R6/R7; another one-round child starts logical R8. Stop/resume targets the new run. Parent evidence and ratings stay outside new-user metrics; grade and batch use local round numbers. The [separate validation record](validation/experiment-continuation.md) distinguishes contract checks from actual backend execution.

## Models and credentials

Each model setting contains a model name, `base_url_env` and `api_key_env`. These are names of variables, never keys or URLs containing credentials. Model names live in the JSON and are frozen by `prepare`; environment files supply connection credentials.

| Role | Example variables | Protocol |
| --- | --- | --- |
| Simulated user | `USER_LLM_BASE_URL`, `USER_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| Harness | `HARNESS_LLM_BASE_URL`, `HARNESS_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| Triage, Synthesizer, PM | `DEMAND_LLM_BASE_URL`, `DEMAND_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| OpenAgents delivery | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` | Anthropic-compatible Claude Code |
| E2B infrastructure | `E2B_API_KEY` | E2B API |
| Gitea.com | `GITEA_TOKEN`; optional `GITEA_USER` | Account resolved by API |

For standard Anthropic API keys set delivery's `auth_type` to `api-key` and `api_key_env` to the variable containing that key. Do not put a Chat Completions-only endpoint in the delivery setting. A shared provider key can be repeated in the required env variables; dotenv interpolation is not enabled.

The explicit `--secrets-file` overrides identically named process variables. No implicit `backend/.env`, user Claude settings or personal trial directory is read. The protected file path may be recorded for later management; secret contents are excluded from material snapshots and archives. To move credentials, pass another `--secrets-file` to the management command. Status, collection and destruction do not require model keys, but cloud operations still need provider credentials.

## Task package

The public example contains:

```json
{
  "schema_version": 1,
  "kind": "swebench",
  "id": "pvlib__pvlib-python-1478",
  "instruction_file": "instruction.md",
  "source": {
    "kind": "git",
    "url": "https://github.com/pvlib/pvlib-python.git",
    "revision": "3f397ed44075b01f4ba535750356859195a51b2d",
    "repo": "pvlib/pvlib-python"
  },
  "setup": {"script": "setup.sh", "requirements_lock": "requirements.lock"},
  "difficulty": "15 min - 1 hour"
}
```

An ordinary custom task uses `kind: ordinary`, explicitly sets `not_in_benchmark: true`, and can use fixed Git source or `source: {"kind": "local", "path": "./my-task"}`. A SWE task must use a fixed Git revision and must not declare `not_in_benchmark`. In the legacy single-package form, workload.kind must match the package. The task_packages list branch has no global kind.

Setup runs in the task checkout with `TASK_ROOT`, `TASK_PYTHON`, `REQUIREMENTS_LOCK`, `VIRTUAL_ENV` and `UV_BIN` provided. `TASK_PYTHON` is the managed interpreter; `VIRTUAL_ENV` points to the task's independent `.venv`. Install the hash-locked task dependencies there, then install the task source without downloading undeclared dependencies. Controller and OpenAgents have separate locked environments.

## Backend boundaries and lifecycle

Local execution starts per-experiment Gitea and an egress proxy, then owned Vigil and user-session containers. Gitea's host port is dynamically allocated on loopback; status reports its actual URL. Model domains/ports come from the explicit endpoints. Engineering CI is optional and disabled by default; disabled runs create no runner.

E2B runs the controller and delivery processes inside one sandbox without nested Docker. Task directories are isolated within that sandbox; this differs from local per-session container isolation. Actual CPU, memory, template/build identity and expiry are checked and recorded. The default example requests 4 CPUs and 8192 MiB. Model usage and cloud runtime determine cost and duration.

Local evidence uses the negotiated gzip/direct transport; Gitea.com uses ZIP and constrained R2 downloads. Preflight checks the actual pinned OpenAgents reader, disables self-update, and verifies publishing and reading before the user experiment. Original self-hosted gzip handles remain supported.

Frozen `manifest.json` describes inputs. Mutable `runtime.json` and provider/controller receipts describe observations. The three state axes are independent: experiment `COMPLETED` can coexist with resources `DESTROYED` and collection `COMPLETE`. An unreachable provider is an unknown observation, not proof of completion. Resume requires the original identity, repository, resources and recovery data. Normal completion releases dedicated compute only after complete collection; stopping E2B processes alone does not release its sandbox.

Use global `--runs-dir /absolute/path/runs` before the command to select another run root. Always use the same root for subsequent management. Editing the original JSON or source checkout after preparation does not change an existing run. For a changed experiment, prepare a new run.

Use `examples/experiment.env.example` as the experiment credential template. Historical profiles and launchers are indexed in [research](../research/README.md) and require their original checkout; they do not supply current v2 configuration. Developer diagnostics have separate, explicit inputs documented in [tools/dev](../tools/dev/README.md). Existing prepared v2 runs retain their frozen source and input hashes when managed after this cleanup; `resume` does not upgrade their controller.

The pvlib recipe includes a build-only shim for its historical Versioneer on Python 3.12. It restores removed `configparser` aliases during editable installation without patching the frozen task source, then removes the shim. The task environment includes hash-pinned pytest for user-side checks.

## Runtime policies and migrated capabilities

Optional `policies` control execution. `prepare` fills defaults and freezes them into the manifest. Put these settings in JSON; neither an env credential file nor identically named host variables override them.

| Field | Default and behavior |
| --- | --- |
| `policies.synthesizer_grouping` | `false`; `true` enables existing grouped scheduling, including N1 |
| `models.user.reasoning_effort`, `models.demand.reasoning_effort` | Optional, e.g. `high`; passed to the user client/shared demand roles. The provider must support the chosen value |
| `policies.timing.latency_isolated` | `false`; excludes instrumented provider waits from demand role execution budgets |
| `policies.timing.wall_guard_seconds` | Additional grace seconds; `0` retains the existing 600-second default. With isolation, the wall cap is role budget plus grace; positive values override the grace |
| `policies.delivery.timeout_seconds`, `poll_seconds` | `86400`, `15`; admitted-ticket terminal wait and polling interval |
| `policies.delivery.coordination` | `soft`; alternatives: `off`, `dependencies` |
| `policies.delivery.permission_mode` | `bypassPermissions`; alternatives: `acceptEdits`, `default`. Delivery runs as a non-root user. This choice affects unattended Git operations |
| `policies.delivery.idle_timeout_seconds` | `300`; `0` disables Claude's inactivity timeout |
| `policies.alarms.proposal_depth`, `ready_depth` | `20`, `20`, positive integers; alarm thresholds, not queue capacities or automatic scaling |
| `roles.owner_mode` | Examples use `mechanical`; `llm` enables existing model review using the shared DEMAND model |

An optional fragment to merge into your complete experiment JSON:

```json
{
  "policies": {
    "synthesizer_grouping": true,
    "timing": {"latency_isolated": true, "wall_guard_seconds": 7200},
    "delivery": {"timeout_seconds": 3600, "poll_seconds": 5, "coordination": "dependencies"}
  }
}
```

Choose `models.delivery.auth_type` explicitly: `api-key`, `bearer` or `oauth`. `api_key_env` only locates the credential; even a custom name such as `MY_KEY` cannot override the explicit protocol. OAuth means a Claude `setup-token` exported as `CLAUDE_CODE_OAUTH_TOKEN`. Definitions without auth_type retain conventional-variable defaults for older v2 inputs; new examples explicitly use `bearer`. OAuth runs are supported, but the SDK-based `check --probe-models` rejects subscription OAuth before provider requests. Use ordinary check, then validate it through actual Claude Code; an SDK request is not presented as OAuth validation.

Set task-package `interaction: "direct"` for Harness-driven execution; the default `simulated_user` uses stepwise simulated-user interaction. Both retain evidence and recovery. A single task can also use explicit `workload.interaction_plan`; this fragment requires count=4 and both personas in persona_ids:

```json
{
  "workload": {
    "interaction_plan": [
      [["persona-a", "your-task-id"]],
      [["persona-a", "your-task-id"]],
      [["persona-b", "your-task-id"]],
      [["persona-b", "your-task-id"]]
    ]
  }
}
```

The plan validates every round's session count and selected persona/task IDs. The selected persona_ids and library IDs remain unique. The ordered session list may repeat personas, tasks, or complete pairs; round/slot gives each its own session ID, client, writable workspace and recovery unit. Reused cards are not independent human samples. If omitted, global slot k=(round_no-1)*sessions_per_round+slot selects persona_ids[k % P] and task_packages[k % T] in their configured order. This simple rotation does not guarantee all persona × task combinations; use an explicit plan for AABB, fixed groups or cross-task coverage. Ordinary `rounds.count: 1` supports user-only trials without waiting for Vigil; multiple rounds and continuation initialization require delivery readiness.

`experiment dashboard RUN_ID` binds that run's sessions, live state and usage. Local artifacts are live; E2B requires collect first and reports the snapshot timestamp, rather than claiming live cloud activity. Gitea uses the selected run's address and credentials; local artifacts remain readable without a token.

These settings, interactions and dashboard binding are migrated. Optional local engineering CI is described below; current archive continuation is described in the [append-round tutorial](tutorials/experiment-continuation.md). Seed libraries and text instructions now convert to ordinary packages as described below. Official SWE task grading is available as a separate post-run command; in-loop grading remains disabled by design. Multi-task/N4/N8 plans now use the frozen workload contract described above. Older v2 runs retain frozen sources; resume does not upgrade them. The [validation report](validation/spec0072-capability-migration.md) separates offline regressions from actual cloud coverage.

## Local engineering CI

Set `runtime.local.ci_enabled: true` in a local + localhost configuration to enable the existing OpenAgents engineering CI gate. Omission or `false` retains the previous behavior and does not add CI defaults to older frozen configurations. E2B + Gitea.com does not support this CI runner contract; E2B configurations cannot include `runtime.local`.

| Field | Default and behavior |
| --- | --- |
| `runtime.local.ci_enabled` | `false`; `true` requests a dedicated Gitea Actions runner and verified readiness |
| `runtime.local.runner_image` | Optional override; default `gitea/act_runner:0.2.11`; an explicit version tag or digest is required |
| `runtime.local.ci_job_image` | Optional override; default uses a pinned `catthehacker/ubuntu` digest; an explicit version tag or digest is required |

Both image overrides require `ci_enabled: true`; `:latest` and unversioned references are rejected. Preparation records actual image IDs. The frozen Harness must contain a PR workflow using `ubuntu-latest`, which this runner maps to the fixed job image. The backend verifies registration, images, ownership and network identity, then runs a real probe PR with checkout and Python smoke. Only a successful check for that PR's current head SHA permits a readiness receipt and the OpenAgents `ci: agent` stage. Failure or timeout blocks startup and retains diagnostics; an enabled configuration cannot silently fall back to `skip`.

Each run also uses a private Docker daemon and job storage, with the internal `docker:27.5.1-dind` recipe frozen by actual image ID. The runner's internal `DOCKER_HOST` connects to that daemon, with no published daemon port or host Docker socket mounted into the runner. Job containers, names and tool caches stay within the run's daemon. Job network mode `host` refers to the private daemon's network namespace on the run's CI network. Local Docker must support this privileged daemon container; preflight checks its identity and readiness. This is a trusted-code execution boundary, without hostile-code isolation.

`status RUN_ID` reports CI separately. Collection preserves readiness and current main/PR commit statuses; a green status from an older head is not evidence for a newer commit. `stop` pauses the owned runner, handles its owned jobs and stops the private daemon while preserving its storage and registration for recovery. `resume` verifies the same daemon, images, storage and registration, then rechecks readiness without registering a replacement. `destroy` removes owned execution resources and CI job storage, retaining the named Gitea and private runner registration volumes; receipts list retained volumes. Runner registration credentials stay in the private volume, outside ordinary collected artifacts.

CI performs engineering checks on trusted Harness code without model calls or benchmark execution. Official SWE task `grade` and held-out Harness evaluation remain separate post-run workflows. See the [local CI tutorial](tutorials/local-engineering-ci.md) and [validation report](validation/local-engineering-ci.md) for commands and the recorded verification scope.

## Seed libraries and text instructions

`task import-seeds LIBRARY --output DIR [--seed ID ...]` and `task from-text --instruction PATH --id ID --output DIR --not-in-benchmark` convert explicitly supplied non-benchmark input into ordinary task packages. Both accept `--interaction direct|simulated_user` and the parent `--json`; they do not read credentials, call networks/models/providers, or execute setup. Output directories must not already exist.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json task import-seeds examples/seed-inputs/library.json --output /absolute/path/to/new-seed-tasks
uv run --locked --extra experiments python backend/scripts/experiment.py --json task from-text --instruction examples/seed-inputs/instruction.md --id weekly-notes --output /absolute/path/to/new-text-task --not-in-benchmark
```

The result's `task_packages` is an absolute path array: assign it to `workload.task_packages` after removing `kind`, `task_package` and any obsolete `interaction_plan`. The generated `tasks.json` only indexes relative paths from the output directory; it is not a runnable experiment or a replacement for that array. When copying an experiment JSON, also resolve its relative persona/Harness paths from the original JSON directory. The [complete import tutorial](tutorials/seed-task-import.md) provides exact Python commands for both maintained N1 backend templates and offline checks.

Cards without repositories and text instructions use a local scratch source directory with an initial README, containing no solution. Repository cards accept an owner/repo identifier resolved to GitHub HTTPS or a credential-free HTTPS URL, with an immutable 40-character lowercase SHA. The importer preserves prompt/source/setup mappings but does not copy oracle, env.test_cmd, gates or provenance into materials or sidecars. Old setup dependencies are not automatically locked, and old images/external services are not restored. Review the generated setup and requirements before preparation. Importing or offline checking is not proof of task success or a reproducible historical environment. Experiments still run through check/prepare/run.

## Multiple task packages

Use `workload.task_packages` for new multi-task definitions. It is mutually exclusive with `kind` and `task_package`; do not add a global kind to this branch. Each package uses task-package-v1 and has a globally unique, safe ID, including ordinary `order-service` and SWE IDs such as `pvlib__pvlib-python-1478`. The existing single-package form is converted once during new preparation. Already frozen runs keep their original config, hash and archived controller. Unknown workload contract versions are refused.

`runtime.local.seed_image` remains a single-task override and is rejected when more than one task package is selected. Automatic per-task image building handles mixed tasks. Local sessions use independent containers; E2B copies each task's pure baseline source and recreates its venv at the final session directory. Download/wheel caches may be shared, writable repos and installed environments are not. E2B's single Unix user does not provide malicious cross-directory isolation equivalent to Docker.

See [the complete N4 tutorial](tutorials/multi-user-experiment.md) for a two-task explicit plan, cost expectations and evidence paths.

## Batch configuration

A batch list is separate from the member's v2 experiment JSON. The public [local](../examples/batches/n1-n4-local.json) and [E2B](../examples/batches/n1-n4-e2b.json) examples reference complete existing N1/N4 configurations. The N1 configuration has five rounds; N4 has two, so this is a scheduling example rather than a fair causal comparison.

```json
{
  "schema_version": 1,
  "name": "synthesizer-n1-n4-local",
  "max_parallel_runs": 1,
  "entries": [
    {"id": "n1", "config": "../experiments/synthesizer-n1-local.json"},
    {"id": "n4", "config": "../experiments/synthesizer-n4-local.json"}
  ]
}
```

| Field | Contract |
| --- | --- |
| `schema_version` | Integer `1`; booleans are rejected |
| `name` | Nonempty display name; preparation generates a unique batch ID |
| `max_parallel_runs` | Positive integer, default `1`; covers this batch's active and uncertain run leases through terminal collection |
| `entries` | Nonempty ordered list; unique `id` uses lowercase letters/digits separated by hyphens (up to 48 characters); complete experiment `config` paths are relative to the batch JSON |

All members must use the same backend. Unknown fields, partial configuration overrides, shell executors and parameter matrices are rejected. Models, roles, materials and per-run user concurrency stay in each member configuration. Credentials use the existing explicit env file/process variables and are excluded from frozen batch materials.

`batch check --offline` validates all local members without providers or credentials. Online checking reports repository capacity as unknown when it cannot be established; it does not prove the account has enough quota. `batch prepare` freezes all members sequentially before any run starts. The foreground `batch run` retains the execution lease after a startup acknowledgement, through uncertain observations and terminal collection. Ctrl+C detaches supervision without stopping children; `batch stop` and `batch resume` use the same member identities and recovery data. Failed/LOST members block new pending starts; partial terminal collection retains its lease. Success requires every member experiment COMPLETED and collection COMPLETE.

A batch lives under `<runs-dir>/.batches/<batch_id>/`; each member's normal run directory is `children/<entry_id>/<run_id>/`. `intent.json` and `manifest.json` retain immutable input identities; runtime receipts and journal store observations. To manage a child directly, specify `--runs-dir <runs-dir>/.batches/<batch_id>/children/<entry_id>` before its single-run command. Batch status reports child run IDs in `entries` and their directories in `child_roots`; use them with the tutorial's management and cleanup commands. Editing source configurations never changes a frozen batch.

The parallel limit is not an account-wide limit or allocated-resource cap. Stopped/completed sandboxes and other batches may still consume quota. Batch management does not automatically destroy compute or delete repositories; even sequential runs may exhaust repository limits. Use the [batch tutorial](tutorials/batch-experiment.md) to collect and explicitly clean up each member.

## Post-run SWE grading

Grading inputs are separate from experiment JSON. `grade RUN_ID` requires `--dataset PATH` (local JSON/JSONL/parquet) and `--dataset-sha256 SHA`; `--round` selects a positive sealed round and defaults to `config.rounds.count`. `--timeout-seconds` defaults to `1800` per session. `--offline` validates bindings without Docker or result writes. Use global `--runs-dir` for a custom root or batch child root, and `--json` for machine-readable output. The command does not read a secrets file.

Install `uv sync --locked --extra experiments --extra dev --extra evaluation`. Both local and E2B runs are scored on the operator’s Docker host from a verified terminal COMPLETE archive, using complete prediction receipts from new controllers. Results go into independent `evaluation/<attempt_id>/` directories; original experiment artifacts remain unchanged. Gold patches and hidden tests are external grading inputs, never frozen evolution materials. Old hash-only sessions are not reconstructible. See the [post-run grading tutorial](tutorials/post-run-grading.md) and [validation report](validation/post-run-grading.md). These user-task scores are separate from held-out Harness generalization tests and do not become feedback or CI gates.
