---
number: "0065"
title: "Standardized Harness Evaluation Framework"
issue: 0
slug: standardized-harness-evaluation
summary: "Drive Harness evaluation in isolated sandboxes with immutable plans, standardizing official time budgets, direct-output and heartbeat-enabled LLM user simulation, the official grader, failure classification, recovery, and reproducible experiment reports."
tasks:
  - id: T1
    title: "Versioned Evaluation Plans and Immutable Manifests"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/schema.py
      - evaluation/harness_bench/config.py
      - evaluation/harness_bench/manifest.py
      - evaluation/harness_bench/cli.py
      - evaluation/tests/harness_bench/test_config.py
      - evaluation/tests/harness_bench/test_manifest.py
    scope: "Define a versioned schema for suites, cases, Harnesses, models, interaction modes, official budgets, sandbox resources, repetition counts, and random seeds; after preflight, freeze a hashable run manifest and provide validate/plan CLI commands."
    acceptance: "Plans missing pins, budget sources, mode compatibility, or hidden-data boundaries fail closed; identical inputs generate stable digests; the manifest contains no secrets and can fully explain the variables of every trial."
  - id: T2
    title: "Pluggable Sandbox Providers and Isolated Lifecycles"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/providers/base.py
      - evaluation/harness_bench/providers/daytona.py
      - evaluation/harness_bench/providers/local.py
      - evaluation/harness_bench/sandbox.py
      - evaluation/tests/harness_bench/test_sandbox.py
    scope: "Establish a provider-neutral sandbox interface, with Daytona as the first supported implementation; handle image pinning, resource quotas, file injection, long-running command sessions, log collection, concurrent scheduling, and cleanup in finally."
    acceptance: "Physically isolate the agent and grader by default; controller-private data must not enter the agent; record network settings, resources, and image digests in the manifest; creation, disconnection, recovery, and deletion must all be auditable, and infrastructure failures must not count as task failures."
  - id: T3
    title: "Harness persistent sessions and streaming control protocol"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/harness/protocol.py
      - evaluation/harness_bench/harness/session.py
      - evaluation/harness_bench/harness/adapters.py
      - evaluation/tests/harness_bench/test_harness_session.py
    scope: "Define protocols for persistent messages, progress, usage, reply, error, interrupt, and shutdown; support nonblocking poll, terminal-state pairing, in-flight messages, and identification of Harness-owned timeouts."
    acceptance: "Create only one persistent session per trial; do not misclassify progress as reply; allow additional messages or interruption during heartbeats; handle late-reply races deterministically; distinguish Harness self-termination, evaluation deadlines, crashes, and protocol errors."
  - id: T4
    title: "Direct-output and heartbeat-driven LLM user simulation strategies"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/interactions/base.py
      - evaluation/harness_bench/interactions/direct.py
      - evaluation/harness_bench/interactions/simulated_user.py
      - evaluation/harness_bench/interactions/native_user.py
      - evaluation/tests/harness_bench/test_interactions.py
    scope: "Implement the direct single-message strategy and an LLM user supervisor outside the agent sandbox that can observe public progress and perform keep_waiting/send_message/interrupt/give_up during execution; support benchmark-native user simulation."
    acceptance: "direct must never generate a second user message; simulated_user runs with a frozen persona/model/seed/heartbeat/turn configuration and cannot see the grader; do not send stale actions when a reply races with a heartbeat decision; generating a single follow-up only after one reply must not be presented as heartbeat mode."
  - id: T5
    title: "Benchmark plugins, official budgets, and hidden graders"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/benchmarks/base.py
      - evaluation/harness_bench/benchmarks/swebench.py
      - evaluation/harness_bench/benchmarks/terminal_bench.py
      - evaluation/harness_bench/benchmarks/tua_bench.py
      - evaluation/harness_bench/benchmarks/tau3.py
      - evaluation/tests/harness_bench/test_benchmarks.py
    scope: "Provide task preparation, mode capabilities, official agent/verifier budget parsing, artifact export, and official grader adapters for SWE-bench Verified, Terminal-Bench, TUA-Bench, and tau3."
    acceptance: "Read official time limits from locked task metadata; when no official agent time limit exists, consistently use and label a 1800-second fallback; the outer deadline must not be shorter than the selected task budget; hidden tests, gold, solution, and grader outputs must not enter the agent or general-purpose user simulation context."
  - id: T6
    title: "Resumable orchestration, unified results, and paired reports"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - evaluation/harness_bench/orchestrator.py
      - evaluation/harness_bench/state.py
      - evaluation/harness_bench/outcomes.py
      - evaluation/harness_bench/report.py
      - evaluation/tests/harness_bench/test_orchestrator.py
      - evaluation/tests/harness_bench/test_reporting.py
    scope: "Execute according to the trial state machine, resume from checkpoints, and perform precise retries; normalize terminal states for tasks, the Harness, simulated users, graders, and infrastructure, and generate reports by benchmark and mode, along with paired A/B reports."
    acceptance: "Do not rerun application-level failures; attempts invalidated by infrastructure may be rerun under the same manifest; report pass, terminal replies, non-timeout replies, grader reach, latency, and the three cost categories separately; results with different plan digests must not be merged, and reports must be traceable to raw traces and cleanup status."
---

# 0065 · Standardized Harness Evaluation Framework

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

Establish a standardized evaluation control plane independent of any specific Harness, sandbox provider, or benchmark. Operators use a versioned
evaluation plan to declare the task set, Harness artifacts, models, interaction mode, budget sources, repetition count, and isolation policy; the framework
parses official metadata for each benchmark, freezes an immutable run manifest, then executes persistent Harness
sessions in temporary sandboxes, collects public traces, and invokes hidden graders. All results can be traced back to inputs, artifact digests, protocol events, costs, and cleanup
status.

The initial release officially supports two mutually exclusive interaction modes:

- `direct`: Send the official task input exactly once, generate no additional user messages, and wait for a normal terminal state, a Harness-defined terminal state, or
  the resolved task deadline.
- `simulated_user`: An LLM user supervisor runs outside the agent sandbox. While the Harness is working, it can read public
  progress on each heartbeat and choose to keep waiting, send an additional message, interrupt, or abandon. It can also continue a multi-turn conversation after the Harness replies. Official user simulators
  supplied by benchmarks integrate through the same interface while retaining their native action spaces and termination rules.

The framework separates task correctness, Harness availability, and evaluation infrastructure health. An `[timeout]` terminal reply only increases the terminal reply
rate; it does not count as normal completion. Harness self-termination, evaluation deadline expiry, crashes, grader failures, and sandbox failures have distinct outcomes.
Official time limits are the maximum allowed budgets, not success criteria; the evaluator must not replace them with shorter temporary limits. A Harness choosing
to terminate early is still preserved as behavior of the product under test and reported separately.

## Motivation

The existing public-bench pilot has demonstrated that Daytona can run SWE-bench Verified, Terminal-Bench, TUA-Bench,
and tau3 in isolation, but execution logic is scattered across per-task scripts, with protocols and reporting conventions added incrementally across experiments. Recent trial runs exposed four classes of systemic problems:

1. A uniformly hardcoded 360-second controller deadline is shorter than the official agent budgets of 1–2 hours for Terminal-Bench and 40 minutes for TUA-Bench,
   causing environment verification results to be misread as official benchmark failures.
2. baseline v0 returns `[timeout]` at 240 seconds, and the old summary counted this as Harness completion because a reply was received; this conflates
   “a terminal reply was received,” “normal completion,” and “task passed.”
3. Non-tau3 tasks first block until a complete Harness reply arrives, then have an LLM generate one follow-up question; this half-duplex wrapper does not
   integrate existing persona heartbeats, in-flight messages, or interrupt, and cannot answer whether user intervention improves user experience or correctness.
4. Manifests, failure normalization, and comparison JSON for ad hoc runs are assembled manually; setup errors, missing patches,
   grader 0, internal timeouts, and outer timeouts for the same task can easily enter different denominators, and recovery can incur duplicate charges or omit remote command logs.

The standardized framework is not intended to replace each benchmark’s official grader or create a new aggregate leaderboard. It provides
a reproducible experimental shell so that “comparing Harness versions,” “comparing direct with simulated-user,” and “comparing models”
each change only the declared experimental variables. Small-sample pilots can still provide only directional evidence, but must no longer produce incorrect conclusions
because of drift in execution budgets, interaction protocols, or statistical conventions.

## Guide-level explanation

### Core objects

- **Suite**: A task set pinned to a revision and its benchmark plugin configuration.
- **Plan**: An experimental design declaring the Harness, models, mode, budget policy, repetitions, and scheduling.
- **Run**: An immutable execution instance frozen after plan preflight, with unique `run_id` and `manifest_digest`.
- **Trial**: The logical measurement unit of `case × harness × model × interaction × seed × repetition`.
- **Attempt**: One infrastructure attempt for a trial. Only invalid infrastructure attempts may be rerun; business terminal states are not rerun.

### Operator workflow

Plans are written in YAML, and secrets are injected only through the runtime environment:

```yaml
schema_version: 1
suite: public-harness-pilot-19
harnesses:
  - id: baseline-v0
    archive: /artifacts/harness-v0.tar.gz
    sha256: dd7cdd91...
models:
  harness: z-ai/glm-5.2
interactions:
  - mode: direct
  - mode: simulated_user
    policy: heartbeat-persona-v1
    model: z-ai/glm-5.2
    seed_set: [17, 29, 43, 71]
    heartbeat_seconds: 90
budgets:
  agent: benchmark
  harness_self_timeout: as_shipped
provider:
  type: daytona
measurement:
  repetitions: 3
```

The standard entry points are:

```text
hbench validate plan.yaml
hbench plan plan.yaml
hbench run plan.yaml
hbench resume <run-id>
hbench summarize <run-id>
hbench compare <run-a> <run-b>
```

`validate` checks the schema, task resolution, mode compatibility, artifact digests, and hidden-data boundaries offline. `plan` resolves image
digests, official benchmark budgets, and provider capacity online, producing a manifest awaiting signature without consuming model resources. `run` accepts only a frozen
manifest; after an interruption, `resume` reconciles attempt states and remote sandboxes. It must not silently resume from modified YAML.

### Two interaction modes

`direct` writes the official instruction into a persistent Harness session as the only user message. progress, usage, and heartbeat
are observation events only and must not be treated as replies; the mode ends when the Harness returns a normal reply, its own timeout, or a crash, or when the trial deadline
is reached. This mode applies to SWE, Terminal, and TUA. Tasks that require user actions must reject direct at the plan stage;
an empty user or fixed follow-up must not be used to simulate support.

`simulated_user` runs a supervisor outside the agent sandbox. The initial message still comes from public benchmark input; while the Harness is in flight,
each heartbeat supplies the frozen user policy with public progress, cumulative waiting time, HELP capabilities, and conversation history. The policy may choose only
`keep_waiting`, `send_message`, `interrupt`, or `give_up`. If a Harness reply arrives during decision-making, the pending action
is invalidated and the reply is read first, preventing continued pressure based on stale state. The next turn after a reply is determined by the same persona and session state,
until acceptance, abandonment, the maximum turn count, or the task budget is reached.

Benchmark-native users such as tau3 implement the same supervisor interface, but their official simulator, seed, maximum turn count, tool
actions, and reward rules remain unchanged. Generic personas do not replace native simulators. A policy that generates a single
LLM follow-up only after the first complete reply may exist as an explicit experimental extension, but must not be labeled `simulated_user/heartbeat-persona-v1`.

### Budgets and interpreting results

Before starting, each trial produces `BudgetResolution`, separately listing budgets and sources for the agent, user simulation, verifier, environment build, and cleanup.
Terminal/TUA must read the pinned `task.toml`; when a task provides no official agent response time limit, the standard suite
uses 1800 seconds and records `fallback_no_official_timeout`. The evaluator deadline must not precede the resolved agent
budget; transport/cleanup grace may be used only for finalization and must not allow the Agent to keep working.

The Harness’s own timeout is preserved as `as_shipped` by default. Returning a timeout early is valid behavior under test and counts as
a Harness failure/task failure, not infrastructure invalidity. If an experiment aligns it with the task budget through public configuration, it must use
a separate manifest and the `task_aligned` label; it must not silently change one side of an A/B comparison.

Reports must show at least the following side by side: end-to-end pass rate, terminal reply rate, normal non-timeout reply rate, grader reach rate, evaluation deadline
rate, infrastructure invalidity rate, latency, and separate token usage and costs for the Harness, user simulation, and judge. Different interaction modes
must appear in separate tables; differences are calculated only when tasks, seeds, budgets, models, and resources are fully paired.

## Reference-level explanation

### 1. Control plane, data plane, and trust boundaries

The controller holds only plans, credential references, and controller-private benchmark data. The agent sandbox receives only public
instructions, the task environment, Harness artifacts, and the minimum network permissions needed to complete the task. The generic user simulator runs outside the agent
sandbox and can see only what a real user could see: instructions, Harness HELP, visible progress/replies, and messages it has
sent. It cannot read solutions, gold patches, tests, grader criteria, or grader output.

By default, the grader uses a fresh sandbox and receives declared artifacts or patches exported after the agent exits. Plugins such as TUA that require the original task state may
delay uploading tests to the same task sandbox, but must first terminate the Harness, revoke model credentials, and prove that controller-private paths did not previously
exist. tau3 computes rewards through its native environment. All exceptions must be explicitly declared through plugin capabilities; the runner must not implement branches
based on task names.

The sandbox provider interface must provide at least `create`, `upload`, `exec_async`, `poll`, `download`, `inspect`, and
`delete`. Long-running remote commands must use reconnectable session/command ids; a controller HTTP timeout must not be equated with remote
command failure. Resource capacity is bin-packed according to declared CPU, memory, and disk requirements; per-trial quotas must not change with parallelism.

### 2. Plan and immutable manifest

The plan schema includes at least:

```text
suite revision, case ids, case digests
harness artifact digest, adapter digest, launch contract
agent model/provider/base URL identity, prompt/tool-schema digest
interaction mode and policy digest
user model/persona/temperature/seed/heartbeat/max-turns
budget values, clock semantics and provenance
sandbox provider, image digests, resources, network policy
repetitions, scheduling seed, retry policy, cost ceiling
grader plugin/version/digest and isolation mode
redaction policy and artifact retention policy
```

The manifest replaces mutable tags with digests after environment resolution, expands every trial id, and records the framework commit. Credential values
are never serialized; only secret slot names are stored. The manifest uses canonical JSON to compute SHA-256; resume, summarize, and
compare all verify the digest. Environment verification and formal measurement have distinct stages and trial ids; the former must not enter formal scores.

### 3. Budget resolution and clocks

Benchmark plugins return structured budgets:

```text
agent_timeout_seconds
verifier_timeout_seconds
environment_build_timeout_seconds
source = official_metadata | suite_custom
clock = trial_wall | benchmark_native
```

When official metadata is missing, use a fixed 1800-second fallback and explicitly record the source; do not silently inherit runner defaults.
A separately declared `suite_custom` must specify a value and rationale, and propagate to filenames, report headers, and comparison compatibility checks.
bootstrap/build does not consume the agent budget; the agent
clock starts when the official instruction is successfully written to the Harness. direct stops at a terminal state. Generic simulated-user uses the trial wall clock by default: in-flight heartbeats and user actions do not
reset the deadline. If a benchmark’s official protocol pauses the clock during user thinking time, the native plugin implements this and marks the different clock
in the manifest.

The controller may have a fixed transport grace period to read terminal states generated before the deadline and perform cleanup, but must not
continue model or tool work during grace. If the controller configuration is earlier than the resolved budget, preflight fails; if an implementation bug still causes early interruption, the outcome is
`protocol_invalid` and must not count as a Harness failure.

### 4. Harness session protocol

The unified event envelope contains `schema_version`, `trial_id`, `session_id`, `request_id`, monotonically increasing `seq`, a timestamp,
`type`, and a payload. The minimum event set is:

```text
controller: message | control.interrupt | shutdown
harness: accepted | progress | usage | reply | error | exited
```

Each user message receives a unique request id; progress/usage belong to the current request but do not close it. `reply` must carry
`terminal_kind = normal | self_timeout | interrupted | refused`. Older Harness versions that cannot be upgraded may be parsed by an adapter based on
explicit, version-pinned protocol markers; arbitrary natural-language text containing “timeout” must not be used to infer a terminal state. If an older version has only a declared sentinel
prefix, the adapter must preserve the original text and the parsing-rule digest.

The session exposes non-blocking `write_message`, `poll(timeout)`, `try_reply`, `interrupt`, `shutdown`, and public event
snapshots. It allows queued messages to be received while the Harness is working, but the interaction policy determines when to send them. A trial uses only one logical session
from its initial message through termination; reconstruction of the underlying process must be accompanied by continuity evidence exposed by the Harness itself, otherwise it is classified as a crash.
The controller must not silently create a new session to continue.

### 5. Interaction state machine

```mermaid
flowchart TD
    S[send official instruction] --> W[await event]
    W -->|progress| W
    W -->|normal reply| D{mode}
    W -->|self timeout/crash/deadline| X[terminal]
    D -->|direct| G[grade]
    D -->|simulated_user| J[user judge/intent/act]
    W -->|heartbeat due| H[user waiting decision]
    H -->|keep_waiting| W
    H -->|send_message| W
    H -->|interrupt/give_up| X
    J -->|send_message| W
    J -->|accept/give_up|max turns| G
    G --> R[result]
```

Every primary user decision and waiting decision preserves the raw model call, structured action, visible-context summary, duration, and usage. Protocol parsing
failures allow limited retries; repeated failures produce an invalid trial with `simulator_failure`, without fabricating user actions. The heartbeat count limit must
cover the trial budget, for example `ceil(agent_timeout / heartbeat_seconds)` plus an explicit margin; a fixed limit of 12 must not cause
the user framework to forcibly abandon a two-hour task after 18 minutes.

### 6. Benchmark plugin contract

Plugins implement the following capabilities, while the orchestrator does not read benchmark-private formats:

```text
resolve_case() -> immutable CaseSpec
supported_interactions() -> capabilities
resolve_budgets() -> BudgetResolution
prepare_agent_input() -> public payload
provision_agent() -> sandbox recipe
export_submission() -> declared artifacts/patch/trajectory
grade() -> raw official result + normalized pass
validate_oracle() -> optional environment preflight
```

The SWE plugin exports a patch and runs F2P/P2P in a fresh official image; a missing patch is a task failure, not a controller failure.
The Terminal plugin reads agent/verifier/build timeouts from `task.toml` and exports only paths declared in `artifacts`. The TUA plugin
preserves task state and injects the verifier after the Harness exits. The tau3 plugin uses the official simulator, environment, tool schema,
turn cap, and reward; if a task does not support direct, the capability check fails before any model budget is spent.

### 7. Outcome classification and scoring

Trial terminal states are normalized using structured evidence:

| Outcome | Included in valid trial denominator | Description |
|---|---:|---|
| `task_success` | Yes | Official grader passed |
| `task_failure` | Yes | Normal submission but grader did not pass, or a declared deliverable is missing |
| `harness_self_timeout` | Yes | Harness timed out of its own accord before the task deadline |
| `evaluator_deadline` | Yes | Full official/custom budget exhausted without a terminal state |
| `harness_crash` / `harness_protocol_error` | Yes | Artifact under test crashed or violated the protocol |
| `simulator_failure` | No | Evaluation user model or action protocol failed |
| `grader_failure` | No | Grader itself unavailable or result unparseable |
| `infrastructure_failure` | No | Sandbox, image, network control plane, or provider failure |
| `protocol_invalid` | No | Plan or runner violated the frozen protocol, such as by cutting off early or leaking tests |

`task_pass_rate = task_success / valid_trials`. In addition, calculate the terminal reply, normal reply, grader reach,
self-timeout, deadline, crash, and invalid attempt rates separately. Receiving `[timeout]` cannot increase normal completion;
Harness failures that do not reach the grader remain in the task pass denominator. Reruns after manual environment repairs retain the original attempt and do not delete history.

Costs are divided into `harness_agent`, `simulated_user`, `benchmark_native_user`, `judge/grader`, and `controller`; the main table
must list at least the first three separately, without using user model costs to obscure Harness costs. For latency, report provision, time-to-first-
progress, active trial, time-to-terminal, grader, and total wall-clock time.

### 8. Recovery, Retries, and Artifact Layout

Run state uses atomic snapshots and an append-only journal. Trial states include at least `planned → provisioning → running →
collecting → grading → terminal`, with additional states `invalid` and `cleanup_pending`. Each remote operation records the provider id,
command id, and postconditions; resume first inspects existing sandboxes and files, then decides whether to continue collection, perform a missing grade, or create a new attempt.

Business terminal states, Harness timeout/crash, and grader 0 are not automatically rerun. Invalid attempts caused by infrastructure, grader, or simulator failures
may be rerun under the original trial with an incremented attempt number, but the manifest must remain unchanged. Call-level retries for the model API are limited by the frozen policy
and recorded individually; fallback to a different model is prohibited. Full-task repeats are only for invalid attempts; selecting the best result is not allowed.

The directory structure is:

```text
runs/<run-id>/
  manifest.json
  state.json
  journal.jsonl
  trials/<trial-id>/attempt-<n>/
    controller.jsonl
    trajectory.jsonl
    harness.stdout.jsonl
    harness.stderr.log
    usage.jsonl
    submission/
    grader/
    result.json
    cleanup.json
  summary.json
  report.md
```

Trajectories are redacted by structured field; deleting an entire tool result must not be used in a way that compromises auditability. A digest is recorded for each file; the summary
references only sealed attempts. Large artifacts may be deleted when the retention period expires, but manifests, results, digests, and deletion receipts are retained long term.

### 9. Comparison Design and Reporting Gates

A/B comparisons must use the same case digest, model, interaction policy, budget, resources, network, grader, and seed; only the
declared Harness artifact or target variable may vary. Scheduling order is randomized using a frozen seed, and each pair should be placed in the same time block where possible,
to prevent provider fluctuations from completely coinciding with version effects. Different modes must not be combined into a single overall score.

Environment verification is performed once per case and is not scored. The plan declares the number of repetitions for formal measurement; the recommended low-cost default is at least three repetitions for direct
and coverage of at least four frozen seeds when using a stochastic LLM user. Reports include both per-case paired outcomes and aggregate intervals;
when the sample is insufficient, explicitly mark it preliminary and do not infer a stable improvement from a single winner. Historical trials may be reused only when the complete trial key and
manifest digest match; results must not be combined across protocols merely because the “tasks are the same”.

## Drawbacks

Adhering to official long-task budgets will substantially increase sandbox occupancy, model tokens, and completion time; even formal small samples across four benchmarks may
require tens of sandbox hours. A user supervisor with heartbeats also adds separate model costs and sources of variation. Strict retention of trajectories, image digests, and
remote command logs increases storage requirements, and a provider-neutral abstraction requires more code than per-case scripts.

A unified outcome will not eliminate attribution disputes. For example, a provider 502 may be correctly recovered from by the Harness, or it may trigger a Harness
crash; the framework can classify only according to frozen rules and evidence, and cannot change criteria after seeing scores. `as_shipped` makes a built-in short timeout
a real disadvantage of the Harness, whereas `task_aligned` evaluates a configured product; both are reasonable but must not be reported together.

An LLM simulated user is not equivalent to a real person; its patience, wording, and acceptance criteria are affected by the model. Even with heartbeats, it can see only progress exposed by the protocol
and cannot judge internal work that is not exposed. This mode is suitable for comparing interaction resilience and should not replace direct or the official native simulator.

## Rationale and alternatives

“Immutable plan + plugins + state machine” is chosen over continuing to extend per-case scripts because the main risks to comparability come from implicit defaults across layers:
task time limits, Harness self-termination, user policy, sandbox resources, and grader isolation must be resolved together before a run. Only the frozen
manifest can prove that two runs are identical apart from the target variable.

User simulation uses an external supervisor and a persistent bidirectional protocol rather than placing the user LLM in the agent prompt. The latter cannot observe or interrupt
while the Harness is busy, and also mixes user tokens, hidden policies, and Agent context. A single fixed follow-up is inexpensive
and can serve as a smoke test, but cannot represent a real multi-turn or waiting experience. A fully synchronous request/reply API is simple to implement, but reproduces
the error in this case where “the user can never intervene before the complete reply”.

Budget defaults respect benchmark metadata rather than selecting a uniform minimum for quick trial runs. A uniform short budget is suitable for an explicitly named
latency stress suite, but cannot produce scores under official criteria. The framework does not forcibly extend the Harness's own timeout, because returning
control early is product behavior; when budget alignment is needed, an explicit policy creates a separate experimental condition.

The official grader is chosen as the sole authority for task pass; an LLM judge does not replace deterministic tests. An LLM judge can produce secondary metrics such as user experience,
but must be billed separately, use a fixed model, and not change pass. Infrastructure-invalid attempts are excluded from the denominator so that
Daytona or grader failures are not attributed to the Harness; Harness errors remain in the denominator to prevent improving the conditional success rate by “not submitting a result”.

## Prior art

Harbor/Terminal-Bench's `task.toml` already provides agent, verifier, and build budgets and resource declarations; the official SWE-bench
evaluation harness provides patch-level F2P/P2P verification; TUA uses a task environment and verifier; tau3 provides native simulated users,
tool trajectories, and reward. This framework reuses these authoritative resources without rewriting tasks or graders.

The repository's existing `ahe_beta.user.sim.loop` already implements `write_message/poll/interrupt` heartbeat supervision, late reply races,
and persona action logs; 0064's recoverable experiment execution provides ideas for atomic state, operation keys, and external state reconciliation. The current
public-bench pilot's agent/grader isolation, Daytona async command, and prepared data boundaries are transferable verification
assets, but the temporary runner and manual aggregation are not part of the new framework API.

The run manifests, content-addressed artifacts, paired trials, and invalid-run classifications of common benchmark harnesses provide the same
reproducibility principles: execution environments and grading rules must be locked first, failure causes and task scores must be kept separate, and raw trajectories are the audit
source for aggregate figures.

## Unresolved questions

1. Whether `task_aligned` should be the main table for Harness comparisons, or whether to report only `as_shipped`. The former is closer to equal compute budgets,
   while the latter is closer to the actual product users receive; the spec requires them to be separated but does not decide their priority in advance.
2. How to freeze the persona set and satisfaction metrics for generic LLM users. Existing demanding personas can be reused, but care must be taken to prevent the simulator
   from knowing the benchmark type or grader conditions, and the protocol validity rate must be verified across different models.
3. Whether to establish an explicit `stress-budget` for a low-cost preliminary suite when official agent time limits are long. If established, it can only be compared with
   the same stress plan and cannot be mixed with official-budget results.
4. If Daytona's image digest, pause/resume, and long-session retention capabilities are insufficient, what evidence permits a disconnected attempt to be classified as an infrastructure
   invalid attempt rather than a Harness deadline; this must be determined through fault injection.
5. Applying a generic simulated-user to originally single-turn SWE/Terminal/TUA effectively creates a new interactive benchmark
   variant. Its user-driven improvement should be analyzed using paired comparisons within each Harness; whether to publish an aggregate score across benchmarks remains an empirical question.

## Future possibilities

After the first phase, E2B and local Docker/Kubernetes providers can be added while retaining the same manifest and outcome contracts; provider capacity and pricing estimates
can also be added to `plan` to provide sandbox-hour, token, and storage limits before a run.

After enough repetitions have accumulated, paired bootstrap intervals, cost-normalized frontiers, time-to-progress survival curves, and user action
transition diagrams can be generated. The framework can also support deterministic replay of recorded real-user interactions, simulated-user shadow mode (decisions only, no execution), and causal decomposition of the same
Harness under the three conditions `direct/as_shipped`, `direct/task_aligned`, and `simulated_user`.

Once the event protocol is stable, a minimal conformance kit can be released so that a new Harness can verify
progress, reply, usage, interrupt, timeout, and recovery semantics before entering expensive benchmarks; benchmark plugins can also be registered by independent packages without modifying the
orchestrator.
