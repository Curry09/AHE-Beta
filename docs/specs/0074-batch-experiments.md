---
number: '0074'
title: "Batch experiment management through a unified entry point"
issue: 0
slug: batch-experiments
summary: "Freeze batch members with an explicit configuration list, limit concurrency according to actual runtime state, and reuse the single-run checks, startup, collection, and stop/recovery."
tasks:
- id: T1
  title: "Batch inputs and the frozen-member ledger"
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/batch_config.py
  - backend/ahe_beta/experiment/batch_store.py
  - backend/ahe_beta/experiment/schemas/batch-v1.json
  - backend/tests/test_experiment_batch_config.py
  - backend/tests/test_experiment_batch_store.py
  scope: "Strictly validate the batch list and freeze configuration identity, separate immutable intent/manifest from mutable receipts, and support independent entry roots and prepare interruption recovery."
  acceptance: 
    "Provider-free checks and rejection of malicious fields/paths/types, atomic publication and hash-tampering rejection, recovery through the unique child manifest, without copying credentials or reconstructing an existing run."
- id: T2
  title: "Reuse single-run batch scheduling and recovery"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/batch.py
  - backend/tests/test_experiment_batch.py
  scope: "Limited-concurrency foreground supervision, persistent launch lease, reconcile before dispatch, terminal-state collect and stop/resume, UNKNOWN/LOST handling, and failure blocking."
  acceptance: 
    "Returning from run does not release a slot; UNKNOWN/collection failure retains the lease; after stopping, reconnect to the same run; a crashed startup intent must not repeat prepare/provision; failure blocks pending members but continues observing members already running."
- id: T3
  title: "Unified CLI batch subcommands and repository contract"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/cli.py
  - backend/tests/test_experiment_cli_v2.py
  - backend/scripts/check_experiment_repository.py
  - backend/tests/test_experiment_repository.py
  scope: "Wire up batch check/prepare/run/status/stop/resume/collect, preserve the single-run entry point and parameter semantics, and extend public repository checks."
  acceptance: "CLI JSON/exit codes and credential paths are accurate, old commands do not regress; only one public entry point; four run examples and two batch examples are checkable."
- id: T4
  title: "Batch examples and bilingual tutorials"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - examples/batches/u1-u4-local.json
  - examples/batches/u1-u4-e2b.json
  - README.md
  - README.zh-CN.md
  - docs/QUICKSTART.md
  - docs/QUICKSTART.zh-CN.md
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  - docs/tutorials/batch-experiment.md
  - docs/tutorials/batch-experiment.zh-CN.md
  - backend/tests/test_experiment_batch_examples.py
  scope: "Maintain configuration lists for both backends and consistent Chinese and English operational tutorials covering cost/concurrency/quota limits, foreground supervision, and resource retention."
  acceptance: "Material references are real and valid, examples contain no private paths/secrets, language and commands are consistent, and it is explicit that the N1/N4 examples use different original round counts and that unknown capacity is not proof that the quota is sufficient."
- id: T5
  title: "Batch end-to-end failure-recovery acceptance"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T2
  - T3
  - T4
  relates-to: []
  parallel: false
  files:
  - backend/tests/test_experiment_batch_e2e.py
  - backend/scripts/e2e-spec-0074-batch-experiments.sh
  scope: "Run the real batch store/scheduler and single-run integration, and use provider/model boundary substitutes to accept-test interruption, non-empty delivery, collection, and recovery, recording actual coverage."
  acceptance: 
    "At least two runs must actually complete terminal collect; UNKNOWN occupies a slot, quota failure, crash recovery, and repeated calls must not repeat runs/repositories; offline substitutes and live evidence must be clearly distinguished."
---

# 0074 · Batch Experiment Management Through a Unified Entry Point

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level, nine-section rust-RFC overview. -->

## Summary

Add a batch layer to the unified `experiment` CLI: users explicitly list several existing schema2 configurations, check and freeze all members first, then launch them with bounded concurrency. The batch persistently records member run IDs, continuously reconciles the actual state of each run, and aggregates results after terminal collection. Stop and resume reuse the original run's materials, repository, checkpoint, and backend, without adding a controller or restoring the historical launcher. The first version does not provide parameter matrices, additional historical rounds, or official scoring.

## Motivation

Individual runs already unify materials, credentials, controllers, and lifecycle across local/E2B, but executing N1/N4/N8 comparisons still requires repeated commands and manual run ID tracking. Historical scaling scripts provide selection sets, launch gates, and executor wrappers, but are tied to old directories, model env settings, and old cloud resources; their formal launch path also permits only one N at a time. Restoring those scripts directly would create a second entry point again.

More critically, `runtime.run_v2` returns launch acknowledgment, not experiment completion. Calling it through a thread pool and releasing concurrency slots when the function returns would turn “at most two running simultaneously” into “launch two at a time, with all of them eventually active.” A batch must hold execution leases and release them based on actual provider/controller state, and must be able to reconstruct the same scheduling decisions after the process exits.

## Guide-level explanation

Users prepare `examples/batches/u1-u4-local.json` or the corresponding E2B example. The public format for the first version is as follows:

```json
{
  "schema_version": 1,
  "name": "u1-u4-comparison",
  "max_parallel_runs": 1,
  "entries": [
    {"id": "u1", "config": "../experiments/u1-local.json"},
    {"id": "u4", "config": "../experiments/u4-local.json"}
  ]
}
```

Paths are resolved relative to the batch file; `id` is a safe, unique path segment. `schema_version` and `max_parallel_runs` accept only positive integers, not bool. The list must not be empty, and unknown fields are rejected. In the first version, all members of a batch must select the same backend; use separate batches for different backends so that a single max_parallel value does not obscure different provider quotas. Each entry is a complete existing configuration; partial overrides, shared writable directories, and arbitrary executor commands are not allowed. Credentials use only existing `--secrets-file`/explicitly injected environment variables and must not be written to the batch manifest, receipt, or logs.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config examples/batches/u1-u4-local.json --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config examples/batches/u1-u4-local.json --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py batch status "$BATCH_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py batch stop "$BATCH_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py batch resume "$BATCH_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py batch collect "$BATCH_ID"
```

`check --offline` invokes real offline material checks for each entry, without loading credentials, fetching Git, or fabricating a final digest; online checks reuse the ordinary check for each entry without additional model calls. `prepare` sequentially freezes and prepares all members, and the batch becomes launchable only after all succeed. `run` is a foreground batch supervision loop that continues waiting and reporting status after launching child experiments; do not describe “members started” as “the entire batch completed.” Ctrl+C stops batch supervision and subsequent queued launches, while already started child runs remain running; it must not silently turn Ctrl+C into cloud stop. Use `batch stop` to stop all child runs.

`resume` reconnects to the original batch members: attach only to existing active runs; use existing resume for STOPPED runs; perform a fresh run only for PREPARED members that have not started. Failures or LOST do not automatically create replacement experiments. `collect` reuses single-run collect for started, accessible members and reports COMPLETE/PARTIAL/error for each, without misreporting partial collection as completion of the entire batch. The first version provides no automatic destroy or repository deletion; users explicitly clean up using the single-run commands shown by status. Pausing a batch does not release allocated E2B resources.

## Reference-level explanation

### Persistent Materials and Ownership

The batch directory is `.batches/<batch_id>/` under the same runs root and must not be confused with an ordinary run ID. The directory rejects symlinks, out-of-bounds IDs, and moved identity. It contains immutable `intent.json` (saving resolved configurations, member order, the shared backend, input digests, and creation time before prepare), immutable `manifest.json` published atomically once after all members are frozen (adding a final snapshot of each item's final config/material identity), mutable `runtime.json`, append-only `journal.jsonl`, and `children/<entry_id>/<run_id>/` independent single-run roots. The intent and final manifest are each published only once; material hashes that change during prepare must not be repeatedly written into a supposedly immutable manifest. When the intent exists but the final manifest has not been published, run explicitly refuses, and resume only resumes the prepare phase. Single-run manifests, resources, and checkpoints are still written by the original runtime; the batch does not change their frozen identity.

Batch preparation first writes a prepare intent for each entry. Each entry uses a dedicated children root; the current prepare API has no interface for preallocating run IDs, so recovery checks for a unique complete manifest only within that entry's controlled root, without making time-based guesses across all global directories. Once the complete manifest matches the expected canonical config/material source, register the actual run ID and continue preparation. Zero complete manifests with only `.preparing-*` indicates interruption before atomic publication; clearly report that freezing has not completed and retry through an explicit prepare retry. Multiple complete manifests, mismatched identity, or an existing incomplete prepared run are all BLOCKED; the first version must not silently select one, delete directories, or rebuild materials. Running `prepare` again must not overwrite a frozen batch; preparation recovery uses the prepare-only state branch of `batch resume`. Existing child runs whose environment preparation failed are reported as BLOCKED_PREPARATION in the first version, pointing to single-run logs and manual handling, without pretending to support a nonexistent API for rebuilding the original materials.

The mutable receipt must save at least the batch revision, batch pause/supervision state, entry ID, unique run ID, child manifest/config/material digests, launch intent/attempt, most recently observed three-axis state (experiment/resource/collection), observation and time, active lease, collection receipt reference, and error classification. Error messages must reuse existing credential redaction and must not store raw exceptions containing secrets. Checkpoints, SessionStore, and the single-run journal always remain the sources of truth for single-run execution; the batch receipt is a scheduling record, not another experiment completion ledger.

### Concurrency and Scheduling

A batch uses a process-level file lock to ensure there is only one scheduler; atomic write + revision/intent ensure crash recovery. Observations and single-run operations use existing run locks. The batch control lock must not be held for an entire cloud request or experiment round, so that status/stop can submit visible control intents. State updates use short critical sections; the scheduler checks pause intent before and after actions.

A slot becomes occupied when a PREPARED entry is selected and its launch intent is durably written, covering provisioning, preflight, launch, active execution, STOPPING, unconfirmed states, and terminal collection. Ordinary queued PREPARED entries do not occupy slots. Prepare itself runs sequentially and does not start resources, so it cannot bypass the active limit. `run_v2` returning, receipt of an exit code, or a progress message are not grounds for releasing a slot.

When recovering the scheduler, first observe all members with launch intents and reconstruct leases before launching pending members; do not first use the free-slot count in the old receipt. `UNKNOWN`, `OPERATION_IN_PROGRESS`, and failures where it is unclear whether launch created resources continue to hold slots; do not release them because of timeouts, network errors, or “last seen FAILED.” Release an execution slot only after an authoritative observation confirms that the controller has stopped/exited and terminal collection is complete. An entry confirmed to have failed preparation with no provision intent has no active lease, but prevents the entire batch from starting. Report LOST separately as an infrastructure terminal state, without allowing fresh replacements; if the provider explicitly confirms that the resource has disappeared, the active lease may be released, but terminal collection that has not reached COMPLETE must retain the failure reason and old artifacts, and the batch cannot succeed.

Terminal `COMPLETED` must come from the single-run sealing determination. `FAILED`/`STOPPED` must also attempt collect, and only COMPLETE completes that terminal collection step; when collection is PARTIAL/fails, BLOCKED_COLLECTION retains the lease and stops subsequent launches, allowing explicit `batch collect` retries. For a conservative first version, stop launching remaining pending members after any member becomes FAILED/LOST; continue observing and collecting already running members, without automatically killing them or rerunning failed members. A batch succeeds only when all member experiments are COMPLETED and collection is COMPLETE; ordinary STOPPED means paused, not failure or success.

`max_parallel_runs` constrains this batch's active execution/uncertain leases, not the total number of cloud resources or global concurrency across the account. Independent runs, other batches, and other people's resources are outside this limit. Public status lists active/pending members, resources that remain allocated after stopping/completion, and configured per-run user concurrency; do not multiply the two and describe the result as a strict model-call limit.

### Quotas and Operations

In the first version, online preflight checks all configurations, credentials, and verifiable provider permissions before any start. If the Gitea repository quota is known to be insufficient, reject batch launch and report the number of new repositories this batch requires; the Gitea API does not guarantee that remaining quota is exposed, so explicitly report capacity as UNKNOWN when it cannot be established, without fabricating availability. Actual repository creation or E2B capacity errors use the original failure classifications, preserve intents/created resources, and block subsequent pending members. Each new single run generally needs its own repository; destroying compute does not delete the Gitea repository, so even sequential execution can exhaust the five-repository limit. Do not bypass limits by sharing repositories, overwriting old repositories, or automatically deleting repositories.

Stopping a batch first persists PAUSING and stops dispatch, then calls existing stop for each member, operating only on runs that have already started. STOPPING/UNKNOWN does not immediately become PAUSED; save PAUSED after stop is confirmed. Resume validates the batch and all child material digests without changing the model/task/plan; if credentials change, accept only authentication inputs supported by the existing runtime, without taking over old repositories across accounts. Status retains historical state and the latest observation, and does not infer sealed/collected when the provider is unknown. Collect must verify the current generation/nonce and existing terminal receipt to prevent old snapshots from posing as the latest completion.

### Task DAG and Exclusive File Ownership

| Task | depends-on | Exclusive files | scope / acceptance |
| --- | --- | --- | --- |
| T1 Batch input, frozen identity, and receipt | None | `backend/ahe_beta/experiment/batch_config.py`; `backend/ahe_beta/experiment/schemas/batch-v1.json`; `backend/ahe_beta/experiment/batch_store.py`; `backend/tests/test_experiment_batch_config.py`; `backend/tests/test_experiment_batch_store.py` | Strict public fields, independent entry roots, credential-free manifests, atomic revision/locking, rejection of tampering and out-of-bounds access, prepare intent recovery; no provider loading or model execution. |
| T2 Lifecycle scheduler | T1 | `backend/ahe_beta/experiment/batch.py`; `backend/tests/test_experiment_batch.py` | Call only existing runtime APIs; enforce a real active lease limit, without releasing on launch return; no duplicate repository/run creation across interruptions; UNKNOWN/LOST/collection failure/stop-resume and quota classification. If an interface audit proves that runtime extensions are necessary, the formal spec must assign `runtime.py` and its corresponding tests to this Task as well, without competing parallel edits. |
| T3 Unified CLI wiring and repository contracts | T1 | `backend/ahe_beta/experiment/cli.py`; `backend/tests/test_experiment_cli_v2.py`; `backend/scripts/check_experiment_repository.py`; `backend/tests/test_experiment_repository.py` | batch subcommand parsing, --runs-dir/--secrets-file alignment, existing single-run commands unchanged, JSON output and exit codes, no claims of completion when uncollected/unknown. |
| T4 Public examples and bilingual documentation | T1 | `examples/batches/u1-u4-local.json`; `examples/batches/u1-u4-e2b.json`; `README.md`; `README.zh-CN.md`; `docs/QUICKSTART.md`; `docs/QUICKSTART.zh-CN.md`; `docs/CONFIGURATION.md`; `docs/CONFIGURATION.zh-CN.md`; `docs/tutorials/batch-experiment.md`; `docs/tutorials/batch-experiment.zh-CN.md`; `backend/tests/test_experiment_batch_examples.py` | Same plan for both backends, real configuration paths/credential refs, consistent Chinese and English commands; clearly explain concurrency/cost/repository limits/retained resources and the difference between Ctrl+C and stop, with no private paths. |
| T5 End-to-end failure recovery and verification report | T2, T3, T4 | `backend/tests/test_experiment_batch_e2e.py`; `backend/scripts/e2e-spec-0074-batch-experiments.sh` | Real batch store/scheduler connected to the actual single-run runtime, with test doubles at provider/model boundaries; at least one nonempty delivery item, complete terminal collection for two runs; crash/restart, UNKNOWN occupying a slot, quotas, repeated operations; record actual provider evidence when real local/E2B is available, without presenting mocks as live execution. |

There are five Tasks in total, with DAG: T1→T2→T5, plus T1→T3→T5 and T1→T4→T5. T2's public Python interface is fixed, so T3 can complete CLI wiring independently; T5 must wait for scheduling, CLI, and documentation to finish. This group has established a formal group and ownership table through the spec tool, with e2e fixed as `backend/scripts/e2e-spec-0074-batch-experiments.sh`.

## Drawbacks

Adding a persistent scheduling and control state layer requires consistency with the three-axis state of each individual run. Conservatively reserving slots for UNKNOWN and blocking on collection failures will reduce throughput, but otherwise concurrency constraints and terminal-state evidence cannot be proven. The first version does not automatically destroy compute resources; users must handle retained resources and repository quotas. Sequential batches also increase total costs. Preparing all members may incur build time before discovering that one member failed to freeze. Batches cannot automatically make unavailable Docker, missing cloud quota, or lost old sandboxes available.

## Rationale and alternatives

An explicit configuration list, batches using the same backend, and a default concurrency of 1 were chosen because the current schema2 already describes all models, roles, tasks, and user materials; a thin wrapper should not redefine the experiment core. The scheduler calls the Python runtime to avoid duplicating authentication in shell subprocesses, treating output text as state, or omitting provider intent.

Alternative one is to document a shell for loop: easy to implement, but lacking persistent member mappings, stop and resume support, a true active limit, and a collection gate. Alternative two is to directly revive the historical scaling runner: its preparation checklist is useful, but it is tied to historical materials and the old executor, which would again create two entry points. Alternative three is to add parameter matrices, cross-backend resource scheduling, and automatic quota expansion: the scope is too broad to complete reliably in the same group as minimal batching. Alternative four is to end the worker as soon as run returns: this is invalid because the experiment is still executing remotely after the current run returns.

## Prior art

The active single-run implementation in the repository: check/prepare/run/status/stop/collect/destroy in `experiment/runtime.py`, manifest run locks, atomic runtime/journal, and terminal collection in the existing monitor. The new group reuses these sources of truth without rewriting the backend or controller.

The archived scaling runner provides historical plan, all-selected gate, and executor encapsulation ideas, but its formal start/resume originally required a single N, and it belongs to fixed historical source code that cannot be imported and called directly. The maintained hbench has an independent batch trial ledger whose distinction between terminal/invalid can serve as a reference; it must not be conflated with the evolution experiment ledger. Official grading and historical continuation remain separate groups; historical role replay can remap reports, but stops before OpenAgents and is not equivalent to batch resume.

## Unresolved questions

This group adopts conservative first-version policies: the same backend, default concurrency of 1, stopping pending members on failure, UNKNOWN occupying a slot, releasing slots after terminal-state collection, no automatic destroy, and no automatic reruns. The user has confirmed that batch experiment management takes priority; these boundaries are the agreed first-version contract for this group, and any changes require corresponding updates to state transitions and acceptance criteria. There is currently no repair API for members that have been frozen during batch preparation but whose environment preparation failed, so the first version blocks explicitly without promising automatic repair. If users need reliable automatic environment rebuilds, this should be included in T2 as a small, clearly defined interface extension in the formal group.

## Future possibilities

Once batch identity and resume verification are stable, provide configuration matrix compilation, repeated seeds/repeated trials, cross-batch account-level resource pools, explicit after-collect destruction policies, and budget-based stopping. Official grading with a pinned Harness SHA and continuation from historical artifacts will each establish independent contracts; they can become new batch member types in the future, but will not be squeezed into the current first version, which contains only schema2 experiment configurations. A public batch dashboard can subsequently reuse the existing run observation API rather than adding a parallel frontend in this group.

