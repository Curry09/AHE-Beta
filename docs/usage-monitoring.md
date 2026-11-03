# Model Token Usage Monitoring

Iterative experiments record Token usage per model request and aggregate it by role, session, and round. Raw events are the source of statistics, and aggregate values are calculated from filtered events. Independent Harbor evaluations use their own usage records; see the [evaluation guide](../evaluation/docs/harbor.md).

## Data Location and Attribution

The controller specifies this run's `usage.jsonl` through `AHE_BETA_USAGE_PATH`. The unified experiment entry point places it under `role_runs/<run_id>/` in the run data directory; an independent process with no explicitly specified path writes to `backend/data/usage.jsonl` by default. Records from E2B must be collected onto the management host through `collect`.

`UsageContext` uses `contextvars` to associate runs, rounds, sessions, user profiles, tasks, slots, Harness submissions, roles, and requests. NexAU worker threads inherit this information through `copy_context()`, preventing attribution from being mixed across concurrent sessions.

Events do not store API keys, prompts, or request bodies. When the provider does not return usage, the call is still recorded, the Token fields are `null`, and `usage_source` is `unavailable`. The system does not estimate Tokens from character counts; retry requests that are covered by monitoring are recorded separately.

## Coverage

| Path | Usage source | Availability |
| --- | --- | --- |
| Simulated user | `usage` in the OpenAI-compatible response | Depends on whether the provider returns it |
| Triage, Architect, Divergent, model Owner | `usage` or `usageMetadata` in the NexAU tracer response | Depends on whether the runtime and provider supply it |
| Subject Harness | Returned by the Harness tracer through a dedicated stdout channel, with the controller supplementing session attribution | Depends on integration by the specific Harness version |
| OpenAgents delivery | Delivery calls in an independent process or container | The current controller has no unified per-request usage integration |

The usage in the table comes from upstream return values, and the counting convention is determined by the provider. Missing portions should be interpreted together with the recorded total; the controller's known total must not be treated as the complete bill for the entire experiment, nor can precise Tokens be inferred from delivery text logs.

The aggregate reports both `event_count` and `unavailable_count`. Missing usage is not included in numerical summation, so the total must be read together with the number of missing calls.

## Querying and Display

After binding an experiment, the observation API can be used for queries:

- `GET /api/usage/events`: request events.
- `GET /api/usage/summary`: totals and grouped aggregates.
- `GET /api/usage/sessions/{session_id}`: usage for a specified session.

The first two interfaces support filtering by `run_id`, `round_no`, `session_id`, `instance_id`, `interaction_id`, `turn_no`, `role`, `agent_id`, and `model`. The dashboard displays input, output, role distribution, session usage, and call details. `dashboard RUN_ID` from the unified entry point can explicitly bind the data source; see the [Quickstart](QUICKSTART.md#view-the-selected-experiment) for details.

## Record Boundaries

Monitoring covers only integrated calls and cannot accurately reconstruct missing historical requests. `AHE_BETA_RUN_ID` is specified by the orchestration environment; for independent runs where it is not specified, a unique value is generated.

JSONL appending uses an in-process lock, and corrupted lines are skipped when reading. A statistics write failure does not block the main experiment flow. This lock protects multithreaded writes within a single process and does not provide write coordination for files shared across multiple processes.
