---
number: '0072'
title: "Migration of existing capabilities and execution fixes for the unified entrypoint"
issue: 0
slug: experiment-capability-migration
summary: "Complete existing configuration, interaction plans, and dashboard wiring; fix single-round readiness and delivery authentication; and verify real consumers on both backends."
tasks:
- id: T1
  title: "Configuration and consumer environments, authentication, and Owner wiring"
  status: done
  priority: P0
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/config.py
  - backend/ahe_beta/experiment/context.py
  - backend/ahe_beta/experiment/runtime.py
  - backend/ahe_beta/experiment/schemas/experiment-v2.json
  - backend/ahe_beta/experiment/schemas/task-package-v1.json
  - backend/tests/test_experiment_config_v2.py
  - backend/tests/test_experiment_engine.py
  - backend/tests/test_experiment_lifecycle_v2.py
  scope: "Strict schema, frozen defaults, shared environments for both backends, and preflight authentication"
  acceptance: "Original configurations remain readable, explicit policies are not filtered out, API key/Bearer/OAuth names are independent, Owner llm can be enabled, and invalid policies are rejected during check"
- id: T2
  title: "Freeze explicit plans and direct interactions"
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: true
  files:
  - backend/ahe_beta/experiment/materials.py
  - backend/ahe_beta/experiment/controllers/ordinary.py
  - backend/ahe_beta/experiment/controllers/swebench.py
  - backend/tests/test_experiment_materials.py
  - backend/tests/test_run_swebench_closed_loop.py
  - backend/tests/test_run_vigil.py
  - backend/tests/test_experiment_interactions.py
  scope: "Plan validation and freezing, consumption by both controllers, and Docker delivery parameters"
  acceptance: "Single-task AABB can be frozen and executed according to plan, direct and simulated_user are actually dispatched, idle timeout is passed through to Docker, and modifying original materials does not change prepared experiments"
- id: T3
  title: "Backend single-round readiness and non-root delivery execution"
  status: done
  priority: P0
  tags: []
  depends-on: []
  relates-to: []
  parallel: true
  files:
  - backend/ahe_beta/experiment/backends/local.py
  - backend/ahe_beta/experiment/backends/e2b.py
  - backend/ahe_beta/experiment/backends/e2b_bootstrap.py
  - backend/deploy/vigil/entrypoint.sh
  - backend/tests/test_experiment_local_backend.py
  - backend/tests/test_experiment_e2b_backend.py
  - backend/tests/test_experiment_e2b_bootstrap.py
  scope: "Fix local single-round execution and explicitly isolate E2B management and execution identities"
  acceptance: "Single rounds complete normally without waiting for Vigil, multiple rounds retain owned readiness; controller/Claude run as non-root with consistent dependencies, artifacts, and stop/collect permissions"
- id: T4
  title: "Observation dashboard entrypoint bound to a run"
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: true
  files:
  - backend/ahe_beta/experiment/dashboard.py
  - backend/ahe_beta/experiment/cli.py
  - backend/ahe_beta/web/api.py
  - backend/tests/test_experiment_dashboard.py
  - backend/tests/test_experiment_cli_v2.py
  scope: "Launch explicit run observation through the unified command, avoiding reads of old default data"
  acceptance: "Current local sessions/live/usage/role_runs are correctly bound, collected E2B artifacts are viewable, uncollected artifacts produce clear errors, and tokens do not enter receipts or the API"
- id: T5
  title: "Capability matrix, examples, and integration acceptance for both backends"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  - T2
  - T3
  - T4
  relates-to: []
  parallel: false
  files:
  - backend/scripts/e2e-spec-0072-capability-migration.sh
  - backend/scripts/check_experiment_repository.py
  - backend/tests/test_experiment_capability_migration.py
  - backend/tests/test_experiment_repository.py
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  - docs/QUICKSTART.md
  - docs/QUICKSTART.zh-CN.md
  - docs/tutorials/u1-experiment.md
  - docs/tutorials/u1-experiment.zh-CN.md
  - docs/architect-grouping.md
  - README.md
  - README.zh-CN.md
  - frontend/README.md
  - examples/experiments/u1-local.json
  - examples/experiments/u1-e2b.json
  - examples/experiment.env.example
  scope: "Public documentation, real consumer matrix, and online evidence boundaries"
  acceptance: "schema→freeze→both backends→real consumer regression passes, documentation lists migrated/pending scope, and actual online coverage is recorded without falsely claiming complete cloud delivery"
---

# 0072 · Migrating Existing Capabilities to the Unified Entry Point and Fixing Execution

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in 9 rust-RFC sections. -->

## Summary

Complete the reusable capabilities with existing real consumers in the unified experiment entry point: grouping, USER/DEMAND reasoning effort, latency-isolated timing, delivery wait/coordination/permission/idle parameters, alarm thresholds, direct interaction, explicit per-round plans, and a dashboard for the current run. Fix single-round local Vigil readiness and delivery authentication type mapping. On 2026-10-03, the user authorized implementation based on the capability audit; commit baseline cleanup separately, without mixing this round's functional changes into cleanup commits.

## Motivation

The old launchers export actual switches, but unified schema 2 has no corresponding fields, and the credential allowlist filters these settings out; archiving historical launchers does not complete capability migration. Although single-round configurations are valid, the local backend unconditionally waits for Vigil, which has not been started; delivery treats arbitrary credential variable names as Bearer, losing explicit API key/OAuth semantics. Old E2B delivery used bypassPermissions as non-root, while the new execution chain switched to root and acceptEdits; the previous five-round cloud experiment had no issues/delivery and did not cover actual code delivery. After data moved to separate runs, the live dashboard still reads the old directory.

This group fixes omissions with clear consumers and execution errors; multi-task/N4/N8, historical lineage imports, engineering CI runner lifecycles, official scoring, and seed libraries/plain-text input, explicitly deferred by the previous public contract, are not claimed as completed by this group. Owner model review already has a complete pipeline; restore explicit mechanical/llm selection.

## Guide-level explanation

Keep schema_version=2 and add optional policies, with defaults for all fields included in the frozen configuration produced by prepare; env files store only credentials/addresses, and same-named host variables still do not implicitly affect experiments.

- policies.architect_grouping: false; models.user/demand.reasoning_effort: optional nonempty string.
- policies.timing.latency_isolated: false; wall_guard_seconds: 0 (uses the existing default grace period of 600 seconds; the total wall-clock limit is the role budget plus the grace period).
- policies.delivery.timeout_seconds: 86400; poll_seconds: 15; coordination: soft/off/dependencies, default soft; permission_mode: bypassPermissions/acceptEdits/default, default bypassPermissions; the process executing delivery must be non-root; idle_timeout_seconds: 300, with 0 disabling it.
- policies.alarms.proposal_depth/ready_depth: 20; roles.owner_mode: mechanical/llm, retaining the existing mechanical default.
- models.delivery.auth_type: api-key/bearer/oauth; explicit selection is independent of the api_key_env name. Old v2 configurations without this setting retain behavior based on existing standard names; new examples explicitly use bearer; explicit OAuth is no longer changed to Bearer.
- task package interaction: simulated_user/direct, default simulated_user; workload.interaction_plan can specify [[persona_id,task_id]] for each round; the current single-task mode still has one session per round. By default, continue rotating personas.
- Add the experiment dashboard RUN_ID command to bind sessions/live/usage/role_runs and the current Gitea for local runs or collected E2B artifacts; the dashboard starts only observation services. When cloud data has not been collected, explicitly prompt for collect; do not read historical default directories and present them as the current run.

check --offline rejects invalid configurations/plans before any provider operation; prepare freezes defaults, plans, and source hashes; modifying the host env, original plan, or configuration cannot change a frozen run.

## Reference-level explanation

### Configuration and consumers

Add policies, role reasoning parameters, auth_type, owner_mode, and task interaction/plan to the strict JSON schema. Configuration loading normalizes the new defaults; the model authentication helper separates source variable names from exported protocol variables; retain execution defaults when reading old manifests, without rewriting old manifests/hashes. Each of the three public API key, Bearer, and OAuth branches exports only one credential, and model preflight uses the same authentication decision.

build_controller_environment exports ARCHITECT_GROUPING, USER/DEMAND_LLM_REASONING_EFFORT, AHE_BETA_LATENCY_ISOLATED_TIMEOUT, AHE_BETA_LATENCY_WALL_GUARD_SECONDS, ROUND_DELIVERY_TIMEOUT_SEC/POLL_SEC, VIGIL_COORDINATION, OPENAGENTS_PERMISSION_MODE, OPENAGENTS_CLAUDE_IDLE_TIMEOUT, PROPOSAL/READY_DEPTH_ALARM, and N_OWNERS from the frozen configuration. Docker delivery must additionally pass through the idle timeout; runtime policies must not be populated from the credential dictionary. Alarm thresholds must be positive integers, and ordinary/SWE share the actual backpressure checks; latency wall-clock protection retains the old consumer's semantics of “role budget plus grace period,” with 0 using the default 600 seconds.

Uniformly validate plans for round count, session count per round, whether personas are selected, whether tasks match, and duplicates; register the normalized plan as frozen material and ensure ordinary/SWE actually consume it. Write task interaction into the actual workspace, using the existing mixed dispatcher to preserve both session behaviors and loading on recovery.

local launch waits for Vigil only for multiple rounds; single-user controller completion does not fail because a delivery process is absent. E2B retains root for resource management, explicitly hands the run's directories over to the non-root user before startup, and makes executable dependencies in bootstrap readable/executable by that user; actual controller/OpenAgents subprocesses run as user. inspect/stop/collect/destroy still run as root and retain resource identity validation. Local delivery processes must also not execute Claude directly as root merely because role_runs is mounted.

The dashboard uses runtime loading to validate the current manifest/materials, then constructs explicit create_app inputs and a tracker from run paths; the UI does not access tokens. E2B binds collected local artifacts and clearly identifies their source, without treating the local API as real-time cloud data. If collect runs again while the service is running, the snapshot time/consistency/terminal state of the data being read and runmeta must stay synchronized; an intermediate replacement state or validation failure returns unavailable, and must not display new data with an old timestamp.

### DAG and file allocation

T1 configuration/environment/authentication foundations, T2 plans/interaction, T3 backend execution, and T4 dashboard each implement defined field contracts, with mutually exclusive file assignments, and can be implemented collaboratively; once all are complete, proceed to T5 integration matrix and documentation. frontmatter is the authoritative data for file allocation and acceptance.

e2e script: backend/scripts/e2e-spec-0072-capability-migration.sh. It must cover the chain from configuration to frozen material to local/E2B environment to actual consumers; add meaningful regression tests rather than substituting assertions that the schema exists for behavioral acceptance.

## Drawbacks

More configuration fields require complete defaults and bilingual documentation, and latency isolation cannot eliminate infrastructure risks. direct reuses existing behavior and does not mean the multi-task entry point is complete. Non-root execution requires checking dependency directories and run write permissions; offline argv/ownership tests cannot prove that cloud model delivery works.

## Rationale and alternatives

Reject restoring arbitrary host env passthrough: it cannot freeze provenance and determinism, and would leak private model configurations again. Reject restoring the old runner wrapper: bypassing through old configuration cannot provide consistent capabilities across both backends. Choose typed, freezable public fields and connect them directly to existing consumers. Authentication type is a separate field, and variable names only locate values; only old v2 configurations without the field retain known-name defaults, to avoid changing frozen experiments.

Handle permissions and runtime identity together, without blindly setting bypassPermissions on root Claude processes. The bypass default supports unattended delivery in existing isolated containers/sandboxes, while retaining explicit acceptEdits/default for users to select.

## Prior art

The actual execution paths of old ordinary/SWE, auditable/mixed, and N1/scaling provide policy exports and consumers respectively. Existing grouped_architect, agent_runtime, round_gate, Owner, mixed dispatcher, and the OpenAgents Claude backend are the implementations reused by this group. The capability audit is dated 2026-10-03 and includes offline reproductions of single-round misclassification, credential mapping, and AABB plans; the necessary background is explained within this group.

## Unresolved questions

No questions block implementation of this group. Nonempty cloud delivery must have its actual acceptance recorded separately; when resources/services are unavailable, record specific limitations, and do not claim online delivery passed based on an empty-demand closed loop or mocks.

## Future possibilities

Complete multi-task/N4/N8, historical continuation/new-lineage, engineering CI, official scoring within the entry point, and seed input adaptation separately. The capability matrix must distinguish migrated, explicitly retired, and pending migration; do not reclassify capabilities pending migration as nonexistent.
