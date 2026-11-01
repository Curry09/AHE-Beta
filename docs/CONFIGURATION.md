# Experiment configuration

English | [简体中文](CONFIGURATION.zh-CN.md)

Experiment definitions use JSON with `schema_version: 2` and run through `backend/scripts/experiment.py`. Start from the [local](../examples/experiments/u1-local.json) or [E2B](../examples/experiments/u1-e2b.json) example and follow [Quickstart](QUICKSTART.md). Unknown fields are rejected. Independent Harness evaluation uses a separate `evaluation.yaml` configuration.

## Files you supply

| Input | Format | Example |
| --- | --- | --- |
| Experiment | v2 JSON: backend, Harness, workload, rounds, roles, models | `examples/experiments/u1-local.json` |
| Task | v1/v2 source/setup recipes, or v3 container environments with fixed inputs/services and artifact declarations | `examples/tasks/pvlib-1478/task.json`; `examples/tasks/evolution32/*/task.json` |
| Instruction | UTF-8 task text, without a solution or hidden tests | `examples/tasks/pvlib-1478/instruction.md` |
| Setup | Trusted shell script; creates the isolated task environment | `examples/tasks/pvlib-1478/setup.sh` |
| Task dependencies | Fully pinned requirements with SHA-256 hashes | `examples/tasks/pvlib-1478/requirements.lock` |
| Personas | JSON array following the repository persona schema | `examples/personas/u1.json` |
| Credentials | Explicit environment variables or a mode-0600 env file | `examples/experiment.env.example` |

The U1 example uses `examples/personas/u1.json`. U4 selects four simulated profiles derived from public developer material in `examples/personas/library.json`. Select unique IDs present in the library. A persona card may be reused across multiple independent sessions in the same round.

Paths in the experiment are relative to that JSON; task paths are relative to the task package. `check --offline` shows an unfrozen allocation preview without fetching Git. `prepare` freezes each task's package, instruction, setup, dependency lock and verified source archive, then creates `materials/task-catalog.json`, `materials/session-plan.json`, the persona roster, Harness archive and hash manifest. You do not need to handcraft these.

Container task packages freeze their declared input hashes, image digests, environment recipe and artifact contract without requiring an additional Python setup script or virtual environment. Remote inputs not already cached remain pending during offline checks; preparation must verify their actual bytes before publishing a prepared run.

## Experiment fields

| Field | Meaning |
| --- | --- |
| `name` | Display name; a unique `run_id` is generated automatically |
| `runtime.backend` | `local` or `e2b` |
| `runtime.gitea` | Provider `localhost` for local, `gitea.com` for E2B; repository prefix |
| `runtime.local` | Optional image overrides and `ci_enabled` (default `false`); local engineering CI requires a verified dedicated runner |
| `runtime.e2b` | Requested `cpu_count`, `memory_mb`, `timeout_seconds` (300–86400); optional compatible template |
| `runtime.harness` | Fallback task budget, optional message activity limit and termination grace; both backends |
| `harness.source` | `builtin`, `archive` with a path and SHA-256, or `continuation` with the matching parent source |
| `workload` | Task packages with persona inputs/optional interaction_plan, or exactly `{"source":"parent"}` for continuation |
| `rounds` | `count`, `sessions_per_round`, `max_parallel_users`; continuation count means added user rounds |
| `continuation` | Optional current parent `archive` path and expected `sha256`; requires both parent input selectors |
| `roles` | Triage/Synthesizer/divergent/developer counts; `owner_mode: mechanical` / `llm` |
| `models` | User, Harness, shared demand and Claude Code delivery settings |
| `evaluation.official_grading` | Must be `false`; configure per-round assessment through `session_grading` |
| `evaluation.session_grading` | Optional external per-round assessment; frozen plan/key digests and `runner: external` |
| `source` | Optional credential-free HTTPS repository and full immutable revisions; defaults come from `release/compatibility.json` |

Choose one or more task packages. sessions_per_round counts execution slots and may exceed the number of selected personas; max_parallel_users must not exceed sessions_per_round. Both personas and complete persona/task pairs may repeat in one round. Each package supplies its own kind and interaction. Current complete archives with a continuation export support additional rounds in a new run; see [continuation](tutorials/experiment-continuation.md). The U1 examples select one persona, one Triage, one Synthesizer, zero divergent PMs, one delivery worker, and five rounds. The last round runs users and any configured independent assessment, with no requirements or delivery stage.

`builtin` freezes `backend/harness_template/` from the current checkout. To use a specific Harness version, select `archive` and provide its path and SHA-256.

### Six-round study configurations

The [E2B tutorial](tutorials/evolution32.md) provides U8 mixed/direct, U16 mixed and U32 mixed configurations using the first eight, first sixteen or all thirty-two tasks in [evolution32](../examples/tasks/evolution32/README.md). All use experiment schema 2, the current builtin seed, six rounds, 4 CPU/8192 MiB and explicit user/Developer concurrency four. Their Triager counts are 4/4/8/16; Synthesizer and Divergent are one each, Owner is mechanical and grouping is false. R6 only runs users and any configured assessment; these examples leave official grading unconfigured.

Original task/persona bindings remain fixed while each round rotates the execution list by one slot within its selected subset. `persona_ids` contains unique IDs, but the six round arrays in `interaction_plan` reuse them across separate slots. Original direct tasks use `sr-15-swyx` for terminal feedback, not simulated interaction. U8 direct overrides only the six original simulated tasks by their actual task IDs in `workload.interaction_overrides`; it does not edit shared task files or change persona assignments. Unknown override IDs are rejected. Models are public replaceable IDs: User/Harness `glm-5.3-flash`, demand/delivery `glm-5.3`; credentials remain env references.

### Task deadlines and message activity

Declare the task's total budget in its v2/v3 task package:

```json
"execution": {
  "budget_seconds": 7200,
  "budget_source": "task_metadata",
  "public_deliverables": ["The requested source changes"],
  "public_acceptance": ["The behavior described in the public instruction"]
}
```

This is a fragment, not a complete package. An operator quota uses `budget_source: "operator_quota"`; document its reason with `quota_override_reason`. A reason is required when overriding a task-declared deadline. Do not present a quota as the official task budget. Public acceptance text must not contain hidden tests or answers.

The clock starts when the first task goal is dispatched. Queued messages, follow-ups and controls do not renew it. `direct` records `followup_input: unavailable`; `simulated_user` records `possible`. Feedback and delivery retain this condition rather than assuming somebody can send “continue”.

An optional experiment-level fallback goes under `runtime`:

```json
"harness": {
  "request_budget_seconds": 1800,
  "termination_grace_seconds": 60
}
```

Despite its existing name, `request_budget_seconds` provides the fallback when the task has no explicit execution budget. A 7200-second task declaration takes precedence over this 1800-second fallback. `message_activity_seconds` is a separate optional per-message limit; leave it absent to avoid a shorter message boundary. It cannot extend the task deadline.

Budgets must be positive and at most 86400 seconds. Grace must be positive and at most 300 seconds, defaulting to 60. Grace permits cancellation, cleanup and receipt collection, not additional solving time. Sandbox lifetime and delivery timeouts are separate. Duration in task prose alone does not configure a deadline. The current seed retains `max_iterations: 100` and `max_tokens: 32768`; a longer budget does not guarantee use of all available time. Exhaustion, interruption and replies without a valid completion status are not successful completion.

The public entry does not inherit arbitrary host Harness settings. Prepared runs keep their frozen controller and seed. Feedback roles read the tested source commit; a missing commit blocks source access rather than silently reading another checkout. Direct and interactive sessions retain progress/replies. Terminal reviewers see frozen read-only task evidence and cannot run arbitrary shell commands or change scored artifacts. Interactive `main_final_check` still precedes the decision to continue or accept.

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

The child first runs an independent feedback initialization and waits for delivery, even when count is one. `count` then counts new users; the final new round remains users-only. Parent logical R5 plus count two gives child local R1/R2 at logical R6/R7; another one-round child starts logical R8. Stop/resume targets the new run. Parent evidence and ratings stay outside new-user metrics; grade and batch use local round numbers. See the [verification guide](VERIFICATION.md) for current checks.

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

### Static context-capacity declarations

`models.user`, `models.harness` and `models.demand` each accept `limits`. For a provider declaring a 262144-token total context window, this example fits:

```json
"limits": {
  "context_window_tokens": 262144,
  "max_context_tokens": 220000,
  "reserved_output_tokens": 32768,
  "input_headroom_tokens": 8192
}
```

Preflight requires input threshold + reserved output + headroom <= declared capacity. Default input remains 256000 and output remains 32768; declaring only a 262144-token capacity is therefore rejected. Set the input threshold explicitly. `reserved_output_tokens` must cover 32768 and does not change actual `max_tokens`. Headroom may be zero; other limits must be positive integers.

This is static validation, not proof of the provider's token counting or dynamic compression. Without declared capacity the report says `unverified`; names do not imply capacity. Deterministic context-limit failures are classified separately rather than retried unchanged as transient errors.

The current User client, builtin Harness seed and demand definitions actually request 32768 output tokens; the four study examples do not add a 128k override or another model budget. Inspect each evolved Harness version for its actual parameters. Claude Code delivery has a separate client/provider output policy. User and builtin Harness apply configured input-threshold overrides; demand roles currently keep their YAML input threshold of 256000, so a demand `limits` declaration is a static capacity check rather than a runtime YAML override.

## Per-round objective assessment

Preparation selects a pinned OpenAgents revision from `execution_evidence` in the [compatibility manifest](../release/compatibility.json): `reader_release_commit` takes priority, followed by `reader_candidate_commit`. An explicit `source.openagents` may select another immutable revision; preflight verifies its execution-evidence capabilities. See the [release guide](RELEASING.md) for paired version updates and validation.

By default `evaluation: {"official_grading": false}` records `not_configured`, not a pass or zero. To opt in, use `evaluation.session_grading`:

| Field | Meaning |
| --- | --- |
| `runner` | Must be `external` |
| `plan_sha256` | SHA-256 of the exact private grading-plan file bytes |
| `worker_key_sha256` | SHA-256 of the Ed25519 public key's raw 32 bytes, not its PEM file |

The [assessment tutorial](tutorials/evolution-feedback.md) generates a complete example with real digests. Both `check` and `prepare` require `--grading-plan` and `--grading-worker-public-key`. The plan covers every selected task and pins adapters, materials, images and timeouts. Registration binds the grading implementation too; changing it requires a new prepared run.

After `run`, start `assessment-worker RUN_ID --plan PATH --signing-key PATH --follow` on a trusted Docker host with the same prepared run state, checkout and provider access. Local and E2B both require this worker. Task sandboxes receive neither the grading host’s Docker socket nor the private grader. Without a ready worker the controller reports `objective_grading / PENDING / worker_not_ready`; starting it lets the run proceed. Recovery retains accepted results without rerunning the Actor or reviewer.

Each round, including the final user-only round, seals Actor outputs before assessment and consumes authenticated safe summaries before requirements processing. Only `completed / passed=false` is a valid task failure; ungradable/unavailable/crashed/timed-out assessments retain `passed=null`. Experience is separately a strict integer 1–4 or a missing state. Task success and missing ratings neither invent a score nor require an Issue. Attribution and improvement suggestions remain separate axes.

Private plans, tests, answers and keys stay at operator-provided paths on the trusted host; worker execution copies and detailed verifier outputs stay under the run's `evaluation/online` area. Neither enters experiment collection or demand-role evidence. The online path accepts reproducible workspace artifacts; profiles requiring managed-service measurements or the original live environment are rejected. Assessment informs later correction without automatically rejecting or rolling back a delivered Harness. Local engineering CI and independent held-out Harness evaluation remain separate.

## Task package

Task-package versions are independent of the experiment's schema 2. The evolution32 collection uses schema 3 with `environment.kind: container`. Its fixed image digest and workdir, SHA-256-bound inputs, initialization/readiness/finalization commands, finite task/companion services and declared capabilities form the environment recipe. See the [task catalog](../examples/tasks/evolution32/README.md) for complete definitions rather than copying an old launcher.

Services are fixture processes, not model Agents. Inputs may belong to the task container or an explicitly declared companion; management-only service outputs are not exposed as Actor inputs. Files and public service handles use the common `artifacts` contract. Non-Git tasks declare patch capture not applicable; SWE tasks retain real repository/revision metadata. Environment and capture failures are recorded separately as infrastructure failures. The environment driver does not perform official scoring.

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

E2B runs the controller and delivery processes inside one sandbox. Existing v1/v2 source recipes retain their directory/workspace behavior; v3 container tasks use the sandbox's verified Docker daemon to create separate task containers and owned service networks for each attempt. They do not run the Actor on the controller's filesystem. Actual CPU, memory, Docker/image capabilities, template/build identity and expiry are checked and recorded. The default examples request 4 CPUs and 8192 MiB. Model usage and cloud runtime determine cost and duration.

Preparation verifies frozen material hashes before uploading files as binary streams. Transfer I/O waits scale with file size; they do not impose a strict whole-transfer deadline or modify task/model budgets. File-scoped upload signatures are excluded from progress, transport logs and reported errors.

Local evidence uses the negotiated gzip/direct transport; Gitea.com uses ZIP and constrained R2 downloads. Preflight checks the actual pinned OpenAgents reader, disables self-update, and verifies publishing and reading before the user experiment. Original self-hosted gzip handles remain supported.

Frozen `manifest.json` describes inputs. Mutable `runtime.json` and provider/controller receipts describe observations. The three state axes are independent: experiment `COMPLETED` can coexist with resources `DESTROYED` and collection `COMPLETE`. An unreachable provider is an unknown observation, not proof of completion. Resume requires the original identity, repository, resources and recovery data. Normal completion releases dedicated compute only after complete collection; stopping E2B processes alone does not release its sandbox.

The single-run background monitor runs on the management machine and collects periodically; the cloud supervisor runs the controller independently. Neither currently renews the E2B creation lease. The example's `timeout_seconds: 86400` is not unlimited lifetime, and a six-round job may exceed it. Status retains actual `expires_at`; a provider-paused instance needs explicit recovery, and an expired/deleted one is LOST. CLI `resume` does not silently replace or provider-resume such an instance. Keep collection available and retain verified archives.

Use global `--runs-dir /absolute/path/runs` before the command to select another run root. Always use the same root for subsequent management. Editing the original JSON or source checkout after preparation does not change an existing run. For a changed experiment, prepare a new run.

Use `examples/experiment.env.example` as the experiment credential template. Historical profiles and launchers are indexed in [research](../research/README.md) and require their original checkout; they do not supply current v2 configuration. Developer diagnostics have separate, explicit inputs documented in [tools/dev](../tools/dev/README.md). Prepared runs retain their frozen source and input hashes; `resume` does not upgrade their controller.

The pvlib recipe includes a build-only shim for its historical Versioneer on Python 3.12. It restores removed `configparser` aliases during editable installation without patching the frozen task source, then removes the shim. The task environment includes hash-pinned pytest for user-side checks.

## Runtime policies

Optional `policies` control execution. `prepare` fills defaults and freezes them into the manifest. Put these settings in JSON; neither an env credential file nor identically named host variables override them.

| Field | Default and behavior |
| --- | --- |
| `policies.synthesizer_grouping` | `false`; `true` enables existing grouped scheduling, including U1 |
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

`experiment dashboard RUN_ID` binds that run's sessions, live state and usage. Local artifacts are live; E2B requires collect first and reports the snapshot timestamp. Gitea uses the selected run's address and credentials; local artifacts remain readable without a token.

Runtime policies, interaction plans and dashboard settings are frozen with each experiment. Prepare a new run after changing them; recovery retains the original configuration. Task import, archive continuation and grading are described below and in their respective tutorials.

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

CI performs engineering checks on trusted Harness code without model calls or benchmark execution. Official SWE task `grade` and held-out Harness evaluation remain separate post-run workflows. See the [local CI tutorial](tutorials/local-engineering-ci.md) and [verification guide](VERIFICATION.md) for setup and current checks.

## Seed libraries and text instructions

`task import-seeds LIBRARY --output DIR [--seed ID ...]` and `task from-text --instruction PATH --id ID --output DIR --not-in-benchmark` convert explicitly supplied non-benchmark input into ordinary task packages. Both accept `--interaction direct|simulated_user` and the parent `--json`; they do not read credentials, call networks/models/providers, or execute setup. Output directories must not already exist.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json task import-seeds examples/seed-inputs/library.json --output /absolute/path/to/new-seed-tasks
uv run --locked --extra experiments python backend/scripts/experiment.py --json task from-text --instruction examples/seed-inputs/instruction.md --id weekly-notes --output /absolute/path/to/new-text-task --not-in-benchmark
```

The result's `task_packages` is an absolute path array: assign it to `workload.task_packages` after removing `kind`, `task_package` and any obsolete `interaction_plan`. The generated `tasks.json` only indexes relative paths from the output directory; it is not a runnable experiment or a replacement for that array. When copying an experiment JSON, also resolve its relative persona/Harness paths from the original JSON directory. The [complete import tutorial](tutorials/seed-task-import.md) provides exact Python commands for both maintained U1 backend templates and offline checks.

Cards without repositories and text instructions use a local scratch source directory with an initial README, containing no solution. Repository cards accept an owner/repo identifier resolved to GitHub HTTPS or a credential-free HTTPS URL, with an immutable 40-character lowercase SHA. The importer preserves prompt/source/setup mappings but does not copy oracle, env.test_cmd, gates or provenance into materials or sidecars. Old setup dependencies are not automatically locked, and old images/external services are not restored. Review the generated setup and requirements before preparation. Importing or offline checking is not proof of task success or a reproducible historical environment. Experiments still run through check/prepare/run.

## Multiple task packages

Use `workload.task_packages` for new multi-task definitions. It is mutually exclusive with `kind` and `task_package`; do not add a global kind to this branch. Each package uses a supported v1/v2 source-task or v3 container-task schema and has a globally unique, safe ID, including ordinary `order-service` and SWE IDs such as `pvlib__pvlib-python-1478`. The existing single-package form is converted once during new preparation. Already frozen runs keep their original config, hash and archived controller. Unknown workload contract versions are refused.

`runtime.local.seed_image` is a single-task override; multi-task configurations use per-task environment preparation. Source tasks use separate session containers locally, or copied baseline sources and newly created per-session virtual environments on E2B. V3 container tasks use the Docker environment driver on either backend to create separate task containers and services. Download caches may be shared; writable sources and installed environments remain separate. E2B source-directory mode shares a Unix user and has different access boundaries from container mode.

See [the complete U4 tutorial](tutorials/multi-user-experiment.md) for a two-task explicit plan, cost expectations and evidence paths.

## Batch configuration

A batch list is separate from the member's v2 experiment JSON. The public [local](../examples/batches/u1-u4-local.json) and [E2B](../examples/batches/u1-u4-e2b.json) examples reference complete existing U1/U4 configurations. The U1 configuration has five rounds; U4 has two, so this is a scheduling example rather than a fair causal comparison.

```json
{
  "schema_version": 1,
  "name": "u1-u4-local",
  "max_parallel_runs": 1,
  "entries": [
    {"id": "u1", "config": "../experiments/u1-local.json"},
    {"id": "u4", "config": "../experiments/u4-local.json"}
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

## Post-run session grading

Grading inputs are separate from experiment JSON. `grade RUN_ID` requires `--plan PATH`; the private plan selects task IDs, adapters and hashed materials. SWE declares its local official JSON/JSONL/parquet dataset in that plan. `--round` selects a positive sealed round and defaults to `config.rounds.count`. Each grader declares its required `timeout_seconds` in the plan. `--offline` validates bindings without Docker or result writes. Use global `--runs-dir` for a custom root or batch child root, and `--json` for machine-readable output. The command does not read a secrets file.

Install `uv sync --locked --extra experiments --extra dev --extra evaluation`. Both local and E2B runs are scored on the operator’s Docker host from a verified terminal COMPLETE archive, using complete prediction receipts from new controllers. Results go into independent `evaluation/<attempt_id>/` directories; original experiment artifacts remain unchanged. Gold patches and hidden tests are external grading inputs, never frozen evolution materials. Old hash-only sessions are not reconstructible. See the [post-run grading tutorial](tutorials/post-run-grading.md) and [verification guide](VERIFICATION.md). These user-task scores are separate from held-out Harness generalization tests and do not become feedback or CI gates.
