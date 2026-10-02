# Mixed scaling E2B executor specification

Status: **implemented; frozen runtime receipts and canary gate active**
Scope: the configured N=1/4/8/16/32 scaling runs defined by
`configs/scaling-e2b-20260922.json` and
`configs/mixed-scaling-20260922.tasks.json`.

This specification closes the missing runtime seam between a frozen task
assignment and the existing user → harness → triage → designer → developer
loop. It does not change the harness protocol, persona state machine, Owner
policy, grader policy, or task membership.

## 1. Goals and non-goals

The executor MUST:

1. run the frozen mixed task set inside one E2B sandbox per experiment;
2. support both interaction modes in the assignment file;
3. preserve the existing simulated-user behavior, including heartbeat,
   workspace access, checks, session traces, and persona acceptance semantics;
4. execute the configured number of rounds with a checkpoint after every round
   and after release;
5. resume the recorded run without creating a replacement sandbox, repository,
   session, or duplicate role operation;
6. emit deterministic, machine-readable artifacts suitable for scoring and
   post-hoc audit; and
7. fail closed when a task payload, grader, timeout, model, or resource
   identity differs from the frozen receipt.

The executor MUST NOT:

- substitute the N=1 SWE-only runner for N>1;
- turn a direct task into a simulated-user task by inventing follow-ups;
- expose grader tests, reference solutions, or held-out answers to the agent;
- use OpenRouter as an implicit fallback;
- modify the existing persona/action protocol; or
- treat infrastructure failure as a task pass or fail score.

## 2. Frozen input contract

The executor receives exactly one N-specific runtime receipt:

```text
prepared/scaling-e2b-20260922/n{N}/receipt.json
```

The receipt MUST bind:

- `config_sha256` and task-assignment SHA;
- harness archive ID and SHA;
- E2B template alias, template ID, immutable build ID, and effective resource
  profile;
- per-task task key, benchmark, task ID, revision/source SHA, prompt SHA,
  agent-payload SHA, grader-payload SHA, interaction mode, persona ID (or
  null), official timeout, outer timeout, and provenance;
- model/provider/base URL contract for each role;
- Gitea repository identity; and
- a passed one-task full-loop canary receipt.

The executor MUST refuse to start if any receipt field is absent, pending, or
inconsistent with the selected N/configuration. Dry-run and preflight MUST NOT
load model credentials or make model/resource calls.

## 3. Runtime topology

Each N is an independent controller and E2B sandbox:

```text
controller (one terminal)
  └─ one E2B sandbox (peak developer resources)
       ├─ task workspaces (one isolated workspace per task/session)
       ├─ harness process per task
       ├─ role runtime: triage → designer/PM → developer
       ├─ recovery ledger + round checkpoints
       └─ /opt/hse-run/artifacts/ (non-secret export)
```

The physical sandbox is not resized between phases. The formal profile is the
peak developer profile recorded in the scaling config (4 vCPU, 8192 MiB RAM,
10240 MiB storage). Logical interaction, triage, design, and development
profiles are metadata only.

Gitea is the per-experiment source of repository/issue/branch state. E2B is
the execution boundary. Boyue is the only formal model gateway.

## 4. Task adapter contract

Every task is normalized to an internal record:

```json
{
  "task_key": "O09",
  "benchmark": "Terminal-Bench",
  "task_id": "production-planning",
  "agent_payload": "...agent.tar.gz",
  "grader_payload": "...grader.tar.gz",
  "interaction": "direct",
  "persona_id": null,
  "official_agent_timeout_seconds": 1800,
  "outer_timeout_seconds": 2400,
  "revision": "...",
  "grader_revision": "..."
}
```

Adapters MUST materialize the same public task workspace contract for all
benchmarks. They MAY differ in setup and grading commands, but MUST expose:

- a task-local working directory;
- the frozen user-visible instruction;
- a task-specific official grader invocation;
- a bounded timeout; and
- an immutable task identity file.

The adapter MUST keep agent and grader payloads separate. Grader material is
mounted or copied only into the grader boundary after the agent/harness phase.

## 5. Interaction modes

### 5.1 `simulated_user`

This mode delegates to the existing historical agentic persona loop without
semantic changes:

- the assigned persona is loaded from the frozen persona-library hash;
- the user can read the task workspace and run checks as configured;
- heartbeat and liveness behavior remain enabled;
- the user may send multiple messages, wait, interrupt, or terminate using
  the existing action contract;
- every turn, raw harness event, persona decision, usage record, and session
  result is persisted; and
- the session closes only through the existing convergence/termination rules.

The executor MUST NOT synthesize fixed follow-ups for this mode.

### 5.2 `direct`

Direct mode has one harness input plus one terminal user review; it is not a
fixed-question or heartbeat-driven user simulator:

1. materialize the task workspace;
2. start the harness with the frozen task instruction as the sole harness input;
3. wait for the harness terminal result until the task outer deadline;
4. close the harness session and collect observation/patch evidence;
5. give the assigned user persona one bounded terminal review call over the
   final reply/artifact; and
6. hand that feedback to the same downstream triage/design/developer pipeline.

During the harness phase, direct mode MUST NOT:

- send a heartbeat;
- send a follow-up, nudge, acceptance, or withdrawal message;
- bypass harness protocol, workspace evidence, or official grading.

The terminal review is still a user-model call. It does not send another
message to the harness; it records verdict, feedback, score, and issue text in
the session and creates the normal triage report. `user_model` therefore names
the review model, while `harness_messages=1`, `review_calls=1`, and
`heartbeat=false` make the direct interaction boundary explicit.

Direct sessions still emit a `session.json` and `trace.jsonl`; the session
metadata records `interaction_mode=direct`, `harness_messages=1`,
`review_calls=1`, `heartbeat=false`, and the terminal review model.

The downstream pipeline is shared: direct changes only the interaction
boundary, not triage, designer/PM, developer, checkpoint, or grader behavior.

## 6. Round lifecycle contract

The round count and final-round policy are run parameters, not hard-coded
executor behavior. The selected experiment config supplies `rounds` and
`final_round_users_only`; the executor validates and snapshots those values.
This section specifies the lifecycle semantics that apply for any configured
round count.

For each configured round `r`:

1. load and validate the recovery ledger;
2. select the frozen task set for N;
3. run each task's interaction mode in bounded task parallelism;
4. persist user/harness session and observation artifacts;
5. run triage over the admitted evidence;
6. run grouped designer and configured PM/divergent roles;
7. dispatch developer workers through the existing Gitea/OpenAgents delivery
   contract;
8. wait for delivery completion under the configured delivery deadline;
9. run the official task grader in the grader boundary; and
10. atomically write `checkpoints/round-{r}.json` before admitting round `r+1`.

If `final_round_users_only` is true, the final configured round runs users only
after the preceding release; otherwise it follows the configured ordinary
round stages. A failed task does not abort independent tasks, but a failed
global stage prevents the next round from being admitted until resumed or
explicitly classified as infrastructure failure.

## 7. Timeouts and cancellation

For every task:

```text
inner deadline = official_agent_timeout_seconds
outer deadline = inner deadline + 600 seconds
```

The inner deadline applies to the harness agent execution. The outer deadline
covers task orchestration, artifact collection, and checkpoint persistence.
Direct and simulated-user tasks use the same rule; direct mode does not get an
implicit shorter timeout. Delivery and environment setup have separate budgets
from task deadlines.

On timeout the executor MUST persist:

- timeout scope and deadline;
- last heartbeat/observable event;
- process/sandbox termination evidence;
- partial trace/session artifacts; and
- `infrastructure_failure=true` when the timeout is caused by runtime
  infrastructure rather than the task's official grader result.

## 8. Checkpoint and resume contract

The recovery ledger is authoritative. Each task-stage operation has a stable
operation key derived from `(round, task_key, stage, attempt)`. The executor
MUST write intent before side effects and reconcile completed operations before
retrying.

Resume MUST:

- reconnect to the recorded E2B sandbox and Gitea repository;
- verify config, task assignment, harness, template, and bundle hashes;
- skip completed operation keys;
- continue incomplete operations; and
- preserve the original interaction mode and persona assignment.

Resume MUST NOT reset the repository, create a replacement sandbox, replay a
completed user session, or silently change a task from direct to simulated
user (or vice versa).

## 9. Artifact contract

For every round/task:

```text
{artifact_root}/round-{r}/trials/{task_key}/
  result.json
  session.json
  trace.jsonl
  usage.jsonl
  grader.json
  workspace-evidence.json
  role-runs/
```

At experiment level:

```text
{artifact_root}/checkpoints/round-{r}.json
{artifact_root}/release.json
{artifact_root}/summary.json
{artifact_root}/manifest.json
```

`result.json` MUST distinguish at least:

- `status`: passed, failed, timeout, infrastructure_failure, or incomplete;
- `interaction_mode`;
- `task_key`, benchmark, task ID, revision, and grader revision;
- harness completion and official grader result;
- user/session fields (null for direct user-model fields);
- round/checkpoint identity; and
- hashes of all referenced artifacts.

Raw secrets, API keys, hidden grader files, and private working-repository
contents MUST NOT appear in exported artifacts.

## 10. Scoring boundary

Official grader output is the task correctness signal. User feeling, persona
verdict, harness completion, delivery status, and infrastructure health are
reported as separate dimensions. Infrastructure failures are excluded from the
official accuracy denominator and reported separately. Direct and simulated
user tasks are included in the same mixed headline result, with interaction
mode and benchmark strata retained for analysis.

## 11. Launch gate and acceptance tests

The executor is launchable only when all selected N values pass preflight:

- executor entrypoint exists and is executable;
- every assigned task has ready agent/grader payloads;
- all task/revision/grader/timeout/mode/persona fields match the receipt;
- E2B template alias/build/resources match the receipt;
- Boyue connectivity and role model contract pass without OpenRouter fallback;
- one simulated-user canary completes a full user → triage → design →
  developer → grader loop;
- one direct canary completes a full initial-message → harness → triage →
  design → developer → grader loop;
- both canaries produce the required artifacts and checkpoint evidence;
- resume from an interrupted canary does not duplicate its completed session;
- no hidden grader material is present in the agent workspace; and
- all selected N processes pass preflight before any formal N starts.

Minimum automated tests:

1. direct mode sends exactly one harness message, then exactly one terminal
   user-review call, with zero heartbeat/follow-up harness messages;
2. simulated-user mode preserves heartbeat and multi-turn behavior;
3. a mixed N=4 fixture executes one task of each mode through the same
   downstream pipeline;
4. task timeout produces `outer_timeout = inner + 600` evidence;
5. resume is idempotent at every stage boundary;
6. grader payload is inaccessible during harness execution; and
7. a failed sibling task does not destroy successful sibling artifacts.

The shared N1 round-1 full-loop evidence is accepted as the canary for the
current frozen scaling receipts. Consequently the materialized N16/N32 receipts
are `launchable=true` and can be started after the single-N preflight; N4/N8 use
the same gate. A future change to the config, template, payload, or controller
invalidates the receipt and requires rerunning the acceptance checklist before
another formal run.
