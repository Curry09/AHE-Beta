# SPEC: Harness experiment preparation and sandbox execution

- **Spec ID:** HSE-20260920-01
- **Status:** ordinary pilot task/model/grader freeze complete; Harbor batch integration specified
- **Scope:** the 20 ordinary tasks, 12 mechanism seeds, ordinary 1/4/12/20 pilots, and nested 16/24/32 mixed runs in `task-manifest.json`
- **Outer run orchestrator:** Harbor
- **Primary trial execution provider:** Daytona
- **Fallback provider:** local provider for protocol/adapter smoke tests only

## 1. Objective

Prepare a reproducible harness experiment in which task execution, harness execution, user interaction, and grading are separated and auditable.

The experiment must support both interaction policies:

1. `direct`: one initial user message, then the harness runs to a terminal reply or timeout.
2. `simulated_user`: an LLM user observes public progress/heartbeats and may wait, ask a follow-up, interrupt, continue, or accept.

The 32-task main set is:

```text
20 ordinary benchmark/dev-like tasks + 12 mechanism seeds
```

Scaling uses fixed nested sets:

```text
1  = ordinary_1
4  = ordinary_4
12 = ordinary_12
20 = ordinary_20
16 = ordinary_12 + mechanism_4
24 = ordinary_16 + mechanism_8
32 = ordinary_20 + mechanism_12
```

The ordinary pilot sets are deliberately task-only (no mechanism seeds):

```text
ordinary_1 = [O03]                         # SWE-bench dev anchor
ordinary_4 = [O03, O09, O14, O18]           # SWE + Terminal + TUA + τ³
```

The exact pilot freeze is recorded in `freeze-record.json`. That receipt is
the authoritative source for task IDs, source revisions/material hashes,
grader contracts, model roles, and the v0 harness archive. It is a preparation
freeze, not a score or a claim that the remote provider is launch-ready.

Both `direct` and `simulated_user` conditions use exactly the same task
membership. The interaction condition is changed by the execution policy, not
by selecting different tasks or injecting a prewritten follow-up.

## 2. Execution-plane decision

### Local execution is not required for task execution

With Daytona, the following do not need to run on the local machine:

- benchmark repository and task workspace;
- harness process and its terminal/file tools;
- task setup and dependency installation;
- grader/verifier;
- per-trial transcript and runtime logs while the trial is running.

The local Docker setup used by the old pilot is therefore not part of the standard run path.

### Harbor support

The complete experiment is Harbor-runnable. Harbor is the outer rollout and
artifact/checkpoint layer; it does not replace the per-trial interaction
protocol or become a second user simulator. The supported shape is:

```text
one Harbor task = one complete experiment batch (4/8/12/16/20/24/32)
  └── coordinator/scheduler
        └── one fresh Daytona sandbox per trial
              ├── harness + task workspace
              ├── direct or simulated-user loop
              └── official grader/verifier
```

The Harbor task receives the frozen manifest, harness/model configuration, and
an optional previous checkpoint artifact. At trial and batch boundaries it
emits the run ledger, transcripts, grader results, and checkpoint artifacts.
Restarting a Harbor task from the latest checkpoint must skip terminal trials,
recreate only missing/invalid Daytona trials, and preserve the original
manifest hash and seeds. A Harbor retry is therefore an infrastructure retry,
not a second measurement of a completed trial.

The Daytona real-developer smoke has validated the critical inner path through
actual model execution, PR creation, review, merge, and issue closure. The
Harbor adapter still owns batch scheduling/checkpoint plumbing; it must consume
the same provider interface described below and must not change the historical
user-simulation semantics.

The 2026-09-20 Boyue/Harbor canary verified both gateway protocols and Harbor
0.23.0's local Docker lifecycle. The frozen `harness-v0` adapter then passed a
one-trial local end-to-end run with verifier reward `1.0`. A credentialed
Daytona run created the sandbox and executed the adapter, but repeated TLS
connection errors from Daytona to the Boyue endpoint prevented a model reply;
that reward-zero run is diagnostic only. The generic Harbor Claude Code canary
stalled while installing runtime packages into a minimal image; the formal
runner must preinstall those dependencies in its pinned image or use the
existing `harness-v0` adapter. These are integration preparation findings, not
benchmark scores.

### A control plane is still required

Something must run the coordinator. It can be the local machine, CI, or a small always-on VM; it does not have to be the developer laptop. The coordinator creates and polls remote sandboxes, but it does not replace the historical user-simulation runtime.

The control plane owns:

- loading and validating the frozen manifest;
- creating/deleting Daytona sandboxes;
- uploading the task package, harness archive, and driver;
- starting/monitoring the in-sandbox interaction driver;
- collecting artifacts and writing the run ledger;
- retrying infrastructure failures only.

The control plane must not solve the task, inspect hidden grader state, or inject private grading information into the user simulator.

For Harbor execution, this control plane is the Harbor task entrypoint (or a
worker launched by it). Harbor may restart the control plane from a checkpoint,
but it must not silently retry a task/harness/model outcome that is already a
valid measurement.

## 3. Recommended topology

```text
                         control plane
                 manifest / scheduler / ledger
                              |
                         Daytona API
                              |
                 one ephemeral sandbox per trial
                              |
       historical local interaction loop (unchanged)
          ├── LLM user/persona + private read/run tools
          ├── harness session + task workspace
          └── grader/verifier
```

The user simulator must run in the same per-trial sandbox/workspace as in the prior local experiments. Its private `read_file`, `run_shell`, optional `write_file`, and `report_issue` tools remain subject to the existing persona capability gate and workspace path jail. Daytona changes the runtime location only; it does not change what the simulated user can observe, inspect, or do.

## 4. Per-trial lifecycle

1. Validate the task manifest and resolve every task to a pinned revision/digest.
2. Freeze the trial row: task ID, harness ID/hash, model, interaction mode, seed, timeout, provider, and resource class.
3. Create one ephemeral Daytona sandbox with a digest-pinned image.
4. Upload or materialize the task package, harness, historical user-simulator runtime, user instruction, and grader.
5. Start the in-sandbox interaction loop with the official task timeout. The harness and user simulator share the trial workspace exactly as before. If no official timeout exists, use **1800 seconds for the whole trial**, not per turn.
6. Run either the direct interaction or the heartbeat-supervised simulated-user interaction.
7. Run the objective grader inside the sandbox after the agent session ends, unless the benchmark's official protocol defines another order.
8. Download transcript, stderr, user trace, grader result, and declared artifacts.
9. Write a terminal outcome to the run ledger.
10. Delete the ephemeral sandbox, including on exceptions.

The existing `harness_bench` Daytona provider implements the provider boundary needed for this topology. Its generic `remote_driver`/`simulated_user` path is useful for direct/public-observation smoke tests, but it must not replace the historical persona loop for the paper's mechanism comparison. The paper runner must package the existing `AgenticPersonaClient`/persona loop and its workspace runtime into the Daytona trial. The local provider remains useful for protocol and adapter smoke tests, not for the paper run.

The Harbor integration consumes this provider boundary rather than calling
Daytona primitives from benchmark/task code. In particular, the Harbor layer
owns batch lifecycle and checkpoint artifacts; the Daytona provider owns
sandbox lifecycle; the trial driver owns direct/simulated-user interaction;
and the grader owns objective scoring.

## 5. Interaction contract

### User acceptance is not objective grading

There are two different questions:

1. **User acceptance:** would this user reasonably accept the visible delivery and continue/stop the conversation?
2. **Objective correctness:** does the artifact pass the benchmark's hidden or official grader?

The LLM user measures the first question. The in-sandbox grader measures the second. A user may accept an apparently credible delivery that later fails the hidden grader, or reject a correct artifact because the assistant failed to explain or deliver it. Both outcomes are meaningful and must remain separate in the report.

### Historical local acceptance mechanism

The user simulator keeps the prior local semantics. It can use its bounded private tools to inspect the shared trial workspace when its persona capability allows it; this is how it validates a claimed change, runs a check, or reviews a diff. This private check is part of the simulator's own judgment and is not an objective grader result.

The simulator still must not read another trial, the coordinator's run ledger, or hidden data outside its own workspace. The existing workspace path jail and persona tool-stack gate remain unchanged. Do not introduce a new `public_evidence` channel or replace private checks with a sanitized artifact projection for this experiment.

### Direct

- Exactly one official initial user message.
- No fixed follow-up disguised as a user simulator.
- End states distinguish normal final reply, harness self-timeout, official task timeout, and infrastructure failure.

### Simulated user

- The simulator receives the same task, transcript, progress, and private-workspace tool access as the historical local run.
- Heartbeats are control-plane observations, not synthetic user messages.
- The simulator may wait when progress is credible, ask a targeted follow-up when clarification is needed, interrupt harmful/off-track work, or accept a verified final reply.
- The simulator must have its own model, seed, heartbeat interval, and trace recorded.
- Simulator failure is not silently converted into task failure; it is a separate invalid/infrastructure outcome.

## 6. Isolation and security requirements

- One fresh ephemeral sandbox per trial; no workspace reuse across tasks or harness variants.
- Harness image and task source are pinned by digest/revision.
- Secrets are injected only into the component that needs them and never written into task artifacts.
- The user simulator may inspect only its own task workspace through the historical path-jail/tool-stack rules; it cannot access other trials, the coordinator ledger, or unrelated host paths.
- Network egress is limited to the benchmark minimum plus the configured model endpoint/package mirror.
- The grader runs from a trusted task package and its output is captured as an artifact; model-visible output is kept separate from grader-private data.

## 7. Required artifacts

Every trial must produce an immutable `result.json` conforming to
`schemas/trial-result.schema.json`, plus:

```text
trial.json                 frozen variables and provider metadata
transcript.jsonl           harness/user-visible protocol frames
harness-stderr.log         harness diagnostics
user-simulator.json        simulator calls and actions (simulated_user only)
grader-result.json         objective score/verdict
artifacts/                 declared task outputs
```

Every batch must additionally produce:

```text
config.json                frozen copy of the experiment config
manifest.json              frozen task manifest
events.jsonl               append-only lifecycle ledger
batch-result.json          deterministic aggregate, schema-validated
checkpoints/               ordered checkpoint files and optional archives
```

At minimum, `trial.json` records:

- `task_id`, `benchmark`, `stratum` (`ordinary` or `mechanism`);
- `mechanism` when applicable;
- harness ID and SHA-256;
- harness model and user-simulator model;
- interaction mode and random seed;
- official/fallback timeout and heartbeat configuration;
- provider name, sandbox ID, image digest, and resource class;
- start/end timestamps and terminal outcome.

`batch-result.json` is the only file used for headline tables. It contains
task-pass rate, harness-completion rate, user-acceptance rate (when present),
mean objective score, and breakdowns by benchmark and interaction condition.
The aggregate is generated mechanically by
`tools/summarize_results.py`; an agent is not allowed to infer or rewrite the
headline numbers from free-form logs.

### Checkpoint contract

Checkpoints are execution state, not extra results. Each checkpoint conforms to
`schemas/checkpoint.schema.json` and records the immutable config/manifest
hashes, completed trial IDs, pending trial IDs, retryable infrastructure
failures, and an artifact index. A checkpoint is written atomically after each
terminal trial (or an explicitly recorded infrastructure interruption). Older
checkpoints remain immutable; recovery loads the newest hash-valid checkpoint,
skips completed trials, and never re-counts their result files. The helper
`tools/checkpoint_store.py` implements the atomic write and hash checks.

## 8. Outcome taxonomy

The report must keep these categories distinct:

- task passed/failed;
- harness terminal failure or self-timeout;
- user-simulator failure;
- protocol-invalid trial;
- grader failure;
- infrastructure failure or sandbox provisioning failure;
- deadline/timeout.

Only infrastructure-invalid attempts may be retried automatically. Task, harness, simulator, and deadline outcomes remain measurements.

## 9. Preparation checklist before the first paper run

- [x] Freeze the ordinary pilot task records: `O03`, `O09`, `O14`, and `O18`.
- [x] Freeze their task IDs, source revisions/package hashes, grader contracts, official timeouts, and resource classes in `freeze-record.json`.
- [x] Freeze the harness to `baseline-v0-cade14d` and the model roles to harness/user `glm-5.3-flash` and design/developer `glm-5.3` (Owner mechanical review=false).
- [ ] Replace the remaining `needs-dev-freeze` ordinary slots before expanding beyond `ordinary_4`.
- [ ] Pin source revision/digest, task package, grader, timeout, and resource limits for every ordinary task beyond the pilot.
- [ ] Materialize the 8 newly authored mechanism seed packages (`M05`–`M12`) with task materials and evaluators.
- [ ] Build one Daytona image per required resource class, each pinned by digest.
- [ ] Obtain a Daytona-to-Boyue egress allowlist or proxy path, then rerun the
      Harbor adapter canary remotely (the credentialed sandbox-only canary is
      already recorded, but is not valid until the model call succeeds).
- [ ] Run one direct and one simulated-user smoke trial through Daytona.
- [x] Run one Harbor-wrapped adapter smoke in local Docker (1 trial, verifier
      reward `1.0`); the remote Daytona version remains gated by model egress.
- [ ] Run one Harbor-wrapped batch smoke (at least 1 direct + 1 simulated-user trial),
      verify checkpoint emission, restart-from-checkpoint, and no duplicate
      accounting for the completed trial.
- [ ] Verify the historical persona tool-stack and path jail: the simulator can inspect only its own trial workspace and cannot escape to the coordinator, other trials, or unrelated host paths.
- [ ] Verify sandbox deletion and artifact download after success, timeout, and coordinator interruption.
- [ ] Freeze the final manifest hash before comparing harness versions or models.

The pilot model matrix is fixed as follows:

```text
Harness under test : baseline-v0-cade14d
User + harness     : glm-5.3-flash
Design + developer : glm-5.3
Owner              : mechanical_review_false
```

The four pilot task records contain the source revision, task/package digest,
grader contract, timeout, and resource class. The remaining 16 ordinary tasks
are intentionally not considered frozen by this pilot configuration.

## 10. Decision summary

For the planned evaluation, use **Harbor as the outer batch runner and remote Daytona sandboxes for all task/harness/user-simulator/grader execution**. Keep only the Harbor control plane and artifact ledger outside the trial sandboxes; it may run locally at first, but the same task should also run from CI or a small remote worker. Do not download or execute the full benchmark environments on the local machine merely because Harbor or the coordinator is local. The only intentional change from the historical local experiment is the execution provider; the user-simulation mechanism and its private workspace checks stay unchanged.

### Model gateway constraint observed in validation

The formal pilot gateway is Boyue, with both its OpenAI-compatible `/v1` base
URL and Anthropic-compatible base URL recorded in the freeze receipt. The
validated 2026-09-20 canary returned both requested GLM5.3 model IDs. Any old
OpenRouter fallback smoke remains infrastructure-only and must not be mixed
with Boyue/GLM benchmark scores. The runner must record the actual gateway and
model in every `trial.json`.
