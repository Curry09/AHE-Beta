---
number: "0004"
title: "Harbor run and recoverable checkpoint"
issue: 0
slug: harbor-run-and-checkpoint
summary: "This group adds a **recoverable runtime** to the closed loop: all agents run **in one pass in a single sandbox** (option A, the entire run = 1 harbor task), using harbor's task→artifact channel to export checkpoints from the sandbox and feed them back in for recovery. It spans a/b/c: checkpoints maintain user-side state (completed sessions / experience), developer-side state (issue assignments, candidate branches), and other orchestration intermediate state (round / stage / release_ref / pending merges) at **unit boundaries**."
tasks:
  - id: T1
    title: "Checkpoint storage and retrieval (STATE_DIR ↔ artifact)"
    status: pending
    priority: P1
    tags: []
    depends-on:
      - 0001/T6
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/checkpoint.py
      - backend/ahe_beta/loop/run_state.py
      - backend/tests/loop/test_checkpoint.py
      - backend/tests/loop/test_run_state.py
    scope: "What to do:\n- Define the STATE_DIR layout: aggregate Gitea data(sqlite+repos), data/sessions/, data/metrics.jsonl, and run_state.json in a single directory that is self-contained and can be packaged as a whole.\n- Implement checkpoint saving: atomically package STATE_DIR → checkpoint artifact (downloadable from the sandbox).\n- Implement checkpoint loading: restore STATE_DIR from an artifact.\n- Define, read, and write run_state: the orchestration cursor + intermediate-state markers for all three sides, as a fallback for what “cannot be directly observed from artifacts”.\nWhat not to do:\n- Do not drive the round loop or call orchestrator (the responsibility of the 0004/T2 runner).\n- Do not implement harbor task scheduling or the artifact channel (the responsibility of the harbor platform).\n- Do not snapshot agent process memory / mid-session state (recovery reruns from unit boundaries, see T2).\n- Do not dual-write authoritative state with Gitea/SessionStore: a checkpoint is a complete snapshot of these authoritative sources and does not introduce a second authority."
    acceptance: "- save_checkpoint produces a self-contained artifact containing all four of gitea/, sessions/, metrics.jsonl, and run_state.json.\n- After load_checkpoint restores it, STATE_DIR is equivalent to its pre-save state (round-trip).\n- save is atomic: failure partway through does not damage an existing usable checkpoint.\n- run_state round-trip: reading after writing returns an equal value, including done_session_keys and issue_assignments; reading an empty STATE_DIR → round=0 without throwing."
  - id: T2
    title: "Recoverable harbor runner (task entry point + per-round checkpoint + recovery)"
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - 0003/T6
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/runner.py
      - backend/tests/loop/test_runner.py
    scope: "What to do:\n- Implement the harbor task entry point (option A): one task wraps the entire run; inputs = pinned initial harness version + persona/scenario set + previous checkpoint artifact (may be null on the first run).\n- At startup: if a checkpoint exists, load it to restore STATE_DIR; read run_state to obtain the recovery point (round/stage/release_ref/completed units).\n- Drive orchestrator.run_round round by round; at each round boundary: write_run_state → save_checkpoint → export from the sandbox through the harbor artifact channel (downloadable).\n- Idempotent resumption: skip completed units: rerun whole sessions on the user side (based on artifacts/done_session_keys), resume developer-side work from the candidate branch head, and skip release when the tag exists.\nWhat not to do:\n- Do not implement orchestrator/the individual components (the responsibility of 0003 and 0001); the runner only adds recovery and checkpoints around them.\n- Do not reuse the harbor batch episode interface for turn-by-turn human dialogue: turn-by-turn dialogue still uses the standalone spec-0001 protocol (consistent with the 0001/T2 decision); harbor only wraps the outer rollout lifecycle.\n- Do not implement multi-container / Gitea process orchestration inside the sandbox (a deployment concern), or concurrent pipelines (MVP is sequential and single-round).\n- Do not snapshot agent process memory / mid-session state."
    acceptance: "- First run (checkpoint=None): start from initial_release_ref and run for n rounds, producing one checkpoint artifact at the end of each round, and return the latest artifact at the end.\n- Recovery run (given the previous checkpoint): restore STATE_DIR and resume from the checkpoint round without repeating completed sessions or creating duplicate release tags.\n- orchestrator can be injected and mocked: the runner only verifies restore→loop→emit ordering and idempotent skipping, not orchestration internals.\n- Turn-by-turn dialogue does not use the harbor batch interface (harbor is used only for the outer task/artifact)."
---

# 0004 · Harbor Execution and Recoverable Checkpoints

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a nine-section, group-level rust-RFC overview. -->

## Summary

This group adds a **recoverable runtime** to the closed loop: all agents **run in one pass within a single sandbox** (Option A, the entire run = 1 harbor task), using harbor's task→artifact channel to export checkpoints from the sandbox and feed them back in for recovery. It spans a/b/c: checkpoints maintain user-side state (completed sessions / user experience), developer-side state (issue assignments, candidate branches), and other intermediate orchestration state (round / phase / release_ref / pending merges) at **unit boundaries**.

Layering is central to this group and is consistent with spec-0001/T2's decision to “define a separate protocol for turn-by-turn dialogue”: harbor wraps only the **outer rollout lifecycle**; **inner** turn-by-turn human dialogue between the user and harness continues to use the separate protocol established by spec-0001, without touching harbor's batch episode interface.

```
harbor task (option A: entire run = 1 task) ────────────────────────
 Input: pinned harness version + persona/scenario set + previous checkpoint artifact
 In sandbox: restore(checkpoint) → orchestrator runs round by round (0003/T6)
             save_checkpoint at the end of each round → export from sandbox via harbor artifact
 Output: incremental checkpoint artifact per round (latest used for next restore)
 Inner user↔harness turn-by-turn dialogue: spec-0001's own protocol (not the harbor batch interface)
```

Supporting components: **T1** defines checkpoint save/load and a self-contained STATE_DIR (gitea + sessions + metrics + run_state); **T2** provides a recoverable harbor runner, adding recovery and per-round checkpoints outside the orchestrator. This group's constraint: **recovery uses idempotent reruns at unit boundaries** (rerun entire sessions, resume developer work from the branch head, skip releases when the tag exists), without snapshotting agent process memory.

## Motivation

Option A puts the entire closed loop into a single harbor sandbox to run to completion in one pass, avoiding the complexity of cross-sandbox orchestration. The cost is that the sandbox itself is ephemeral—if it terminates midway, both in-process state and disk state are lost. Making long-running execution recoverable first requires answering “what goes into a checkpoint, how is it self-contained, and how is it written atomically?” Otherwise, recovery either omits state or drifts from authoritative sources such as Gitea/SessionStore; this is the problem T1 addresses. The next question is “who is responsible for saving and loading checkpoints at the right time?” This responsibility cannot simply be inserted into the orchestrator—0003/T6 has already defined orchestrator.run_round as a pure orchestration function with no hidden state. Embedding recovery logic in it would reintroduce state and impair its unit testability. Recovery must therefore reside in a runner outside the orchestrator, implemented by T2: it drives harbor's task→artifact channel to export checkpoints from the sandbox and feed them back into the next task for recovery.

## Guide-level explanation

T1 defines a single self-contained STATE_DIR and its dump/load interfaces, which together with the run_state cursor constitute the entire checkpoint—it is a complete snapshot of authoritative sources such as Gitea/SessionStore, without establishing a second authority. T2 builds a recoverable harbor task entry point on top of this: following Option A, it wraps the entire run as one harbor task, drives the orchestrator round by round inside the sandbox, and invokes T1's save/load primitives at each round boundary to export an incremental checkpoint artifact; feeding the latest artifact into a new task enables idempotent resumption from the checkpoint.

## Reference-level explanation

The full flow has two layers: T1 provides state save/load primitives and data structures; T2 implements a recoverable harbor task entry point on top of them and consumes T1. They are coupled only through the two data structures STATE_DIR and RunState, without intruding into each other's implementation.

**STATE_DIR layout and run_state (T1)**

STATE_DIR is a single self-contained directory aggregating all recoverable state required for one round of the closed loop:

- `gitea/` — Gitea data directory (sqlite + harness repository), the authoritative source for issues and harness versions.
- `sessions/` — Persistent storage for the spec-0001 SessionStore (user experience + transcript + issue receipts), the data source for experience curves and regression baselines.
- `metrics.jsonl` — append-only, observations of issue count over time and user experience trends.
- `run_state.json` — Orchestration cursor + three categories of intermediate-state markers.

run_state maintains “the state of the entire process,” specifically: the orchestration cursor (round, phase, current_release_ref); user-side state (the set of completed (persona, scenario) session keys in this round's fixed_set, corresponding to persisted Sessions in sessions/); developer-side state (a mapping from assigned issues → candidate branch refs, whether candidates have passed the gate, and whether they have been merged/tagged); and other transient orchestration state (this round's test verdict, pending merge queue, etc.). User/developer agent “state” specifically means their **persistent progress at unit boundaries** (completed sessions, candidate branch commits), excluding nexau process memory or mid-session state—the latter is not included in checkpoints, and recovery reruns the entire unit (see T2's recovery semantics below).

Save/load contract: saving atomically packages the state (tmp + rename / write first, then set the flag) to produce a self-contained artifact; partial writes must not corrupt the previous usable checkpoint. Loading restores STATE_DIR under the specified root and marks it usable only after verifying that all four categories are present. run_state reads/writes use atomic JSON writes; reading an empty STATE_DIR returns the initial run_state(round=0).

Key design tradeoffs: package a single STATE_DIR in its entirety rather than export multiple sources separately—a checkpoint is a single complete snapshot, avoiding inconsistencies across sources and matching the usage pattern of “just download the checkpoint from the sandbox”; a checkpoint is a snapshot of authoritative sources (Gitea/SessionStore), not a second authority, so it introduces no dual-write drift; run_state records only “unobservable” cursors and assignments, while progress that can be inferred from artifacts (session file existence, branch head, tag existence) is inferred preferentially, with run_state serving only as a fallback to reduce the risk of stale cursors; saving uses atomic writes because the sandbox may die midway through writing a checkpoint, and the previous checkpoint must always remain usable.

T1's type contract: `save_checkpoint(state_dir: Path, dest: Path) -> Path` (returns the artifact path); `load_checkpoint(artifact: Path, state_dir: Path) -> None`; the `RunState` data structure contains `round:int`, `phase:str`, `current_release_ref:str`, `done_session_keys:set[str]`, `issue_assignments:dict[int,str]`, `pending:list`; `read_run_state(state_dir: Path) -> RunState`, `write_run_state(state_dir: Path, run_state: RunState) -> None`.

Test coverage: save→load round-trip (construct a STATE_DIR containing all four categories → save → load into a new directory → equivalent structure and contents); self-containment validation (load errors if any category is missing, without silently marking it usable); atomicity (simulate interruption midway through save; the existing checkpoint can still be loaded); run_state read/write round-trip (including set/map fields; reading an empty STATE_DIR returns the initial run_state(round=0)).

**Recoverable harbor runner (T2)**

T2 implements Option A: the entire run is wrapped as one harbor task, with inputs consisting of a pinned initial harness version, a persona/scenario set, and the previous checkpoint artifact (may be empty for the first run). The runner inside the sandbox first uses T1's load_checkpoint to restore STATE_DIR and reads run_state to locate the recovery point, then calls orchestrator.run_round (0003/T6) round by round. At each round boundary, it performs write_run_state → save_checkpoint, exporting the checkpoint from the sandbox through harbor's artifact channel:

```
harbor task (option A: entire run = 1 task)
  Input: pinned harness version + persona/scenario set + previous checkpoint artifact
  Runner in sandbox:
    restore: load_checkpoint(artifact) → STATE_DIR; read_run_state → resume point
    loop:    for round: orchestrator.run_round(release_ref) → new_release_ref
             end of each round: write_run_state → save_checkpoint → export from sandbox via harbor artifact
  Output artifact: incremental checkpoint per round (latest used for next restore)
  Inner user↔harness turn-by-turn dialogue: spec-0001's own protocol (not the harbor batch interface)
```

Recovery semantics follow “per-round checkpoints + unit idempotency”: recovery can only return to the most recent round already exported as an artifact. If the sandbox dies unexpectedly, anything not exported is lost; the cost is several in-flight sessions or one issue fix (a few LLM calls) in the current round, which is acceptable. Resumption skips work idempotently at unit boundaries—on the user side, skip a session if it exists (rerun entire sessions, without mid-session recovery); on the developer side, resume from the candidate branch head; for releases, skip if the tag exists. When determining completion, preferentially infer it from artifacts (session files, branch heads, tags), using run_state only as a fallback cursor. For resources and lifecycle management, increase sandbox specifications (vCPU/RAM/disk) as needed, clean up harness versions after use (retain only the current version + baseline), and rotate sessions/checkpoints to control disk usage.

Key design tradeoffs: choose Option A (the entire run = 1 task) rather than one task per round—run in one pass inside the sandbox, with harbor responsible only for starting the task, periodically collecting artifacts, and restarting with the artifact attached, keeping the harbor layer as thin as possible; incremental checkpoint exports each round already provide recovery points, so no harbor-side task chain is needed, at the cost of long-running individual tasks. Put recovery logic in the runner (outside the orchestrator) rather than embedding it in the orchestrator—keep orchestrator.run_round a pure function with no hidden state (the 0003/T6 decision), prevent checkpoint/recovery concerns from intruding into orchestration, and allow both to be unit-tested independently, at the cost of an additional layer. Choose entire-session reruns as the unit rerun granularity rather than mid-session recovery—mid-session state is complex and offers little benefit, at the cost of rerunning an entire session if it is lost. Choose per-round rather than per-step checkpoints—align with harbor's batch granularity and keep the artifact count manageable, at the cost of losing at most one round of in-flight work. Keep turn-by-turn dialogue off harbor's batch interface—uphold 0001/T2's decision to “define a separate turn-by-turn protocol,” with harbor carrying only the outer rollout lifecycle.

T2's type contract: `run(initial_release_ref: str, fixed_set, checkpoint_artifact: Path | None) -> Path` (returns the final checkpoint artifact; this is the harbor task entry point); internally, `restore(checkpoint_artifact) -> (state_dir, RunState)`, and `emit_checkpoint(state_dir) -> Path` each round; dependency injection for the orchestrator (0003/T6) and T1's checkpoint save/load.

Test coverage: first run (mock orchestrator.run_round, assert that save_checkpoint is called once per round and the latest artifact is returned); recovery (construct a checkpoint with “round k completed” → run starts at round k+1, assert that completed sessions/tags are not executed again, i.e., idempotent skipping); simulated sandbox death midway (only the latest round's artifact is available → recover from that round, not from a later incomplete state); resource cleanup (assert that multiple harness versions are cleaned up after use, if this strategy is implemented).

**File allocation**

| File | Owning Task |
| --- | --- |
| `backend/ahe_beta/loop/checkpoint.py` | T1 |
| `backend/ahe_beta/loop/run_state.py` | T1 |
| `backend/tests/loop/test_checkpoint.py` | T1 |
| `backend/tests/loop/test_run_state.py` | T1 |
| `backend/ahe_beta/loop/runner.py` | T2 |
| `backend/tests/loop/test_runner.py` | T2 |

Dependency DAG: `0001/T6 → T1`, `T1 → T2`, `0003/T6 → T2`

## Drawbacks

<!-- TODO -->

## Rationale and alternatives

Save/load layer (T1) tradeoffs: package a single STATE_DIR in its entirety vs. incremental exports per source—choose complete packaging for Occam's razor, self-containment, and easy recovery, at the cost of larger checkpoints, mitigated by checkpointing once per round and cleaning up versions after use; record cursors in run_state vs. infer entirely from artifacts—choose “prefer inference + run_state fallback,” because pure inference is the most robust but some transient orchestration state (pending merges, this round's verdict) has no artifact from which to infer it, while a pure cursor approach is prone to becoming stale, hence the compromise; this group does not bind the checkpoint's final destination (harbor artifact channel)—it defines only the save/load contract and artifact form, leaving the decision to T2 when integrating with harbor.

Execution layer (T2) tradeoffs: one task for the entire run vs. one task per round—choose the entire run (Option A) for Occam's razor and the thinnest possible harbor-side layer, at the cost of very long-running individual tasks, offset by per-round artifacts providing intermediate recovery points; recovery logic in an outer runner vs. embedded in the orchestrator—choose the outer runner to keep the orchestrator purely focused on orchestration and unit-testable, at the cost of an additional layer; choose entire-session reruns as the unit rerun granularity rather than mid-session recovery—mid-session state is complex and offers little benefit, at the cost of rerunning an entire session if it is lost; choose per-round rather than per-step checkpoints—align with harbor's batch granularity and keep the artifact count manageable, at the cost of losing at most one round of in-flight work.

## Prior art

Each of the four categories of state aggregated by STATE_DIR has an established authoritative source: SessionStore (spec-0001/T6) persists sessions/; Gitea (spec-0002) is the authoritative source for gitea/, i.e., the authoritative source for issues and the harness repository; the writer of metrics.jsonl is the orchestrator from spec-0003/T6. T1's save/load primitives are consumed by T2's runner; orchestrator.run_round/run driven by T2 also comes from spec-0003/T6. Its outer recovery mechanism assumes that “turn-by-turn dialogue uses a separate protocol and does not occupy harbor's batch episode interface,” a decision from spec-0001/T2; for harbor's role as the rollout foundation, see “harbor as the rollout foundation” in CLAUDE.md. The two state destination conventions in CLAUDE.md, “user experience + session → local data/sessions/” and “issue → Gitea,” directly determine that STATE_DIR must package both categories of data to be self-contained.

## Unresolved questions

The specific binding between checkpoint artifacts and harbor's artifact channel—object format and size limit—as well as the specific APIs for harbor task inputs/outputs and the artifact channel, and the upper limits on sandbox specifications, remain to be finalized during actual harbor integration. This group locks down only the internal STATE_DIR/RunState contract, without pre-binding harbor-side details.

## Future possibilities

<!-- TODO -->

