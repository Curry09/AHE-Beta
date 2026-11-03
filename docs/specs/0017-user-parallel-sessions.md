---
number: "0017"
title: "Parallelize multi-user sessions: thread pool for stage a + lock shared state"
issue: 0
slug: user-parallel-sessions
summary: "Change user sessions in the closed-loop stage a from serial execution to ThreadPoolExecutor parallelism: the concurrency unit is an entire session (workspace + Harness subprocess + client + run_session as one package), while the envelope's internal ordering remains unchanged; correspondingly fix shared state (one client instance per session, move workspace provisioning earlier, lock SessionStore/live), and degrade a single-session failure without invalidating the entire round. Stages d/b remain serial due to inherent constraints (same-repository push + global env). Locations: loop/orchestrator + loop/sim_user + run.py + user/session_store + loop/live."
tasks:
  - id: T1
    title: "Lock storage and observation projections"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/session_store.py
      - backend/ahe_beta/loop/live.py
      - backend/tests/user/test_session_store.py
      - backend/tests/loop/test_live.py
    scope: "Give SessionStore an instance-level threading.Lock, with save holding the lock throughout (the order of writing the full record and then appending to the index remains unchanged; the lock only eliminates the concurrent lost-entry race); add one module-level lock to live.py, covering the full read-modify-write operations of update_agent/append_agent_log/archive_agent/update_live_run/clear_live—mkstemp atomic writes prevent torn writes but do not prevent two writers based on the same old snapshot from overwriting each other (lost updates). Lock granularity = the entire single-file operation; no network or subprocess waits occur while holding the lock, so there is no deadlock surface."
    acceptance: "After N concurrent save operations across multiple threads, index.json contains exactly N entries and the sessions directory contains N complete files (concurrency regression test); concurrent update_agent calls for different agent_id values preserve every slot in agents.json; concurrent append_agent_log calls do not lose lines; all existing single-threaded tests remain green."
  - id: T2
    title: "One client instance per session (factory injection)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/sim_user.py
      - backend/tests/loop/test_sim_user.py
      - backend/tests/user/sim/test_workspace.py
    scope: "Change the client parameter of make_sim_run_session_fn to client_factory: Callable[[], PersonaClient] (a breaking signature change; callers are run.py and the two tests test_sim_user/test_workspace); inside run(), create client = client_factory() for each session and then guard bind_session (call it only for implementations that have bind_session). The underlying ApiPersonaClient has no session state and can be shared globally; the factory only creates a new AgenticPersonaClient wrapper. Prevent cross-session contamination under concurrency, where a later bind overwrites an earlier bind."
    acceptance: "Unit-test assertions using a recording fake factory: each session receives an independent client instance, and each session's bound persona/workspace does not overwrite another's; two concurrent sessions (simulated with threads) produce correctly owned TurnLogs without cross-session contamination; all existing sim_user tests remain green after migration."
  - id: T3
    title: "Parallelize stage a + concurrency knob"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/tests/loop/test_orchestrator.py
    scope: "Split run_round stage a into two phases: phase one is serial preparation (materialize_workspace + ensure_deps / mkdtemp, avoiding concurrent git clone cache contention); phase two uses ThreadPoolExecutor(max_workers=min(n, max_parallel_users)) to run launch + run_session_fn in parallel, harvesting with as_completed; log and skip a single-session exception without invalidating the entire round. Add a max_parallel_users parameter to the Orchestrator constructor; run.py reads the MAX_PARALLEL_USERS environment variable (defaulting to the number of roster users) and passes it in, while connecting the client side to the T2 factory. Proceed to stages d/b only after all stage-a sessions have been collected (preserving serial execution)."
    acceptance: "With FakeHarness+Scripted and max_workers=4, run 8 sessions: all are persisted, and stages d/b execute only after stage a has been collected; when one session's launch raises an exception, the remaining sessions complete normally and the round is not interrupted; max_parallel_users=1 is equivalent to the old serial behavior (regression baseline); all existing orchestrator tests remain green."
  - id: T4
    title: "Concurrent end-to-end regression tests"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/tests/loop/test_parallel_sessions.py
    scope: "Add dedicated e2e tests for this group (all Fake, with no dependency on a real LLM/Gitea): ① Concurrency correctness—after 8 concurrent sessions, the sessions directory contains 8 complete files, index.json contains exactly 8 entries, and live history is fully archived by round; ② Slow-session injection—delay replies in the fake harness and assert that fast sessions finish first, the slow session does not block result collection, and all results are collected by the end of the round; ③ Crash injection—make send raise RuntimeError and assert that the in-session [harness error] signal path still works under concurrency and does not affect other sessions in the same batch."
    acceptance: "All three categories of dedicated tests pass; assertions use exact counts (index entries/file count/live slot count) to catch regressions involving lost updates due to races; the full pytest suite passes."
  - id: T5
    title: "harness checkout concurrency safety"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/harness/launcher.py
      - backend/tests/harness/test_launcher.py
    scope: "An audit gap exposed by a production run: parallel sessions in the same round at the same SHA → the same checkout dest, while _checkout's check-then-extract sequence has no lock—multiple threads pass the existence check simultaneously and run extractall concurrently into the same directory (two tar streams overwrite params.yaml, producing duplicate entry keys/garbled bytes), or B sees a “nonempty directory” while A is halfway through extraction and reuses an incomplete copy. Two safeguards for the fix: ① A launcher-instance-level threading.Lock covers the entire existence check+archive+extraction sequence (in-process mutual exclusion: the first thread does the work and the others hit the cache); ② Extract into a unique temporary directory (mkdtemp) under runs_root, then atomically rename it into place—a partially extracted directory can never exist under the name dest, and a process crash leaves only harmless orphaned tmp directories without contaminating the cache; if rename fails because dest is already in place (the loser across processes), discard tmp and reuse dest. Addition from the second production round: the shared module-level ruamel YAML singleton (_yaml) is not thread-safe, and concurrent _read_params calls during parallel launch corrupt the parser's internal state → remove the singleton and create a new YAML instance for each parse (construction overhead is negligible)."
    acceptance: "Release 8 threads simultaneously from a barrier to call _checkout concurrently on the same ref: all return the same directory, no tmp directories remain under runs_root, and params.yaml parses cleanly with safe YAML (duplicate keys trigger DuplicateKeyError to catch regressions); all existing launcher tests pass without regressions (marker reuse / cache invalidation on content changes retain the same semantics). Addition: release concurrent _read_params calls on the same params.yaml simultaneously from a barrier; all results are intact and identical; no shared YAML instance remains at module level."
  - id: T6
    title: "tracker HTTP session thread safety"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/tracker/gitea.py
      - backend/tests/tracker/test_gitea.py
    scope: "One finding from the repository-wide thread-safety audit of shared instances (discovered in the second production round): a single requests.Session in GiteaTracker is shared by all session threads; requests officially makes no guarantee that Session is thread-safe, and Gitea returns Set-Cookie (so concurrent cookiejar mutation actually occurs). Switch to thread-local Session: make _session a property that lazily creates an independent Session with all headers for each thread; retain the setter as a global injection point (override applies to all threads, preserving single-threaded test semantics). Do not lock the _label_ids cache—_create_label already has built-in fallback for 409/422 races (if created elsewhere, refresh and reuse), and run.py prewarms bug/feature before starting. The openai client (backed by httpx) is officially thread-safe; keep it shared."
    acceptance: "Different threads accessing _session receive different Session instances, each with the full Authorization header; the same thread reuses the same instance; after a test injects an override, all threads read the injected object; all existing GiteaTracker unit tests pass without regressions."
---

# 0017 · Parallel Multi-user Sessions: Phase a Thread Pool + Shared-state Locking

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level rust-RFC overview in 9 sections. -->

## Summary

Change phase a (user sessions) of a closed-loop round from sequential execution to **ThreadPoolExecutor parallelism**: the concurrency unit is **an entire session**
(the complete bundle of shared workspace + harness subprocess + persona client + `run_session`), without changing any threads in the single-threaded,
deterministic timing within the control envelope. Three supporting changes: ① change the persona client from a single instance reused across sessions to **one instance per session**
(factory injection, eliminating `bind_session` cross-session interference at its root); ② **move workspace provisioning (materialize + ensure_deps) ahead of the parallel phase
and complete it sequentially** (avoiding concurrent contention over the git clone cache); ③ lock shared state (the
index.json read-modify-write in `SessionStore.save` and the observation projection read-modify-write in `live.py`). Phase a wall-clock time for N users drops from ~ΣTᵢ to
~max(Tᵢ), and **concurrency does not change any signal semantics**. Phases d (architect) / b (developer) remain sequential; parallelizing them is an explicit
Non-goal (multiple devs pushing directly to the same main inevitably cause push conflicts + `SANDBOX_WORK_DIR` mutates global env; sequential execution is an inherent
constraint of the pure trunk model).

## Motivation

**Current state (restated here to keep this spec self-contained).** Phase a in `orchestrator.run_round` is a sequential for loop:
for each (persona, scenario) pair in the fixed set, it sequentially completes the entire flow: “materialize workspace → `launcher.launch(sha)`
starts a harness subprocess → `run_session` conducts ≤12 dialogue turns → persist to disk/file issues.” The roster defaults to 3 users, and each session
can easily take several minutes (1-2 persona LLM calls per outer turn + an inner tool loop of ≤4 steps + the harness's own LLM/bash calls;
a single harness reply can take ~16 minutes in the worst case). Phase a duration **grows linearly** with the number of users and accounts for most of the round's wall-clock time.
Expanding persona coverage (more anchor users) means either waiting longer or reducing the number of turns—both hurt training signal density.

User sessions, however, are **naturally fully isolated**: each has its own workspace directory (the orchestrator materializes/creates one with mkdtemp
per session), its own harness subprocess (one launcher handle, one process, one session), and its own client binding; they do not communicate
and have no shared writable state (except three explicit aggregation points: SessionStore, the live observation projection, and the issue tracker). This makes them ideal
candidates for parallelism.

**Why now (the prerequisites were resolved by 0012/0013).** A prerequisite for concurrency is that “a single session hanging/crashing must not bring down
the worker pool.” This did not hold in the old baseline (the launcher's `readline` had no timeout, and exceptions crashed the entire run), but
0012/0013 have already resolved this in place: launcher `begin/poll` polls in slices (if the process dies without returning a complete line → precisely detects the deadlock and raises it;
a 1800s absolute limit prevents livelock), and loop-side `route`/`_supervise_send` convert all harness exceptions into
`[harness error]` text fed back to the persona as observations (the session does not crash, and bad commits produce gradients). Therefore, this spec
**does not include any further timeout/exception translation work**; it only parallelizes the orchestration layer and consolidates shared-state access.

## Guide-level explanation

For operators: `./run.sh` behavior is unchanged, but the N user cards in phase a **pulse simultaneously** on the dashboard (there is already one slot per agent,
and the roster defines room capacity; this is how the dashboard “should have looked”). A new control, the `MAX_PARALLEL_USERS` environment variable (default =
number of users in the roster), controls concurrency; setting it to 1 restores today's sequential behavior. A round now has this shape:

```
round K:
  ┌─ Phase a (parallel, ≤max_parallel_users threads) ─┐
  │  user1: launch → run_session → persist to disk    │  ← Separate process tree + workspace + client per session
  │  user2: launch → run_session → persist to disk    │
  │  user3: launch → run_session → persist to disk    │
  └────────── Collect all with as_completed ──────────┘
  Phase d (architect, serial) → Phase b (developer, serial) → Phase c (feed back main HEAD SHA)
```

For signal consumers (designers/metrics/dashboard): **concurrency changes only wall-clock time, not signal semantics**—experience score distributions, issue
output, and TurnLog contents remain consistent with the sequential baseline; an unexpected failure in a single session (such as a launch crash) is logged and skipped, without invalidating the entire round
or blocking other sessions.

## Reference-level explanation

### Concurrency unit and invariants

Concurrency unit = the complete bundle for one session: `(persona, scenario, workspace_dir, harness_handle, client)`.
Inside the envelope (the `run_session` loop, `_supervise_send` heartbeats, and the inner tool-loop), single-threaded deterministic timing is preserved,
and behavior within each session is identical to sequential execution. The launcher handle already has an in-flight reader thread (`begin/poll` from 0013);
it is private to the handle and orthogonal to the session-level parallelism in this spec.

### T2: One client instance per session (the primary hazard)

`AgenticPersonaClient` has session-level state: `bind_session(persona, workspace_dir)` writes
`self._persona/_workspace_dir` (persona_client.py:447-453). Currently, run.py reuses one instance sequentially;
concurrency will inevitably cause cross-session interference (a later bind overwrites an earlier bind). Fix: change `make_sim_run_session_fn(client=...)` to
`client_factory: Callable[[], PersonaClient]`; inside `run()`, perform `client = client_factory()` for each session, then
conditionally call `bind_session` with a guard. The underlying `ApiPersonaClient.complete` has no session state (purely functional completion + 429 backoff),
and the openai SDK client is thread-safe. **All sessions share the same `ApiPersonaClient` instance**, each creating only a new wrapper:
`client_factory = lambda: AgenticPersonaClient(shared_api.complete)`. This is a breaking signature change; callers are
run.py (updated together with T3) and the two tests test_sim_user / test_workspace.

### T3: Split phase a into two stages + thread pool

```python
# Phase one (serial, fast): provision workspaces up front to avoid concurrent access races in the shared clone cache in sources/git.py
prepared = []
for persona, scenario in self._fixed_set:
    ws = materialize_workspace(scenario.workspace) if scenario.workspace else mkdtemp(...)
    if scenario.workspace:
        ensure_deps(ws, scenario.workspace)
    prepared.append((persona, scenario, ws))


# Phase two (parallel): launch + session
def _one(persona, scenario, ws):
    harness = self._launcher.launch(sha, workspace_dir=ws)
    return self._run_session(persona, scenario, harness, workspace_dir=ws)


with ThreadPoolExecutor(max_workers=min(len(prepared), self._max_parallel_users)) as pool:
    futs = {pool.submit(_one, p, s, ws): (p, s) for p, s, ws in prepared}
    for fut in as_completed(futs):
        try:
            fut.result()
        except Exception:  # Since 0012, exceptions within sessions are converted to signals; only unexpected failures such as launch errors remain here
            # A single session failure does not invalidate the entire round; collect the remaining sessions as usual.
            log.exception(...)
```

- `max_parallel_users` is injected through an Orchestrator constructor parameter; run.py reads the `MAX_PARALLEL_USERS` environment variable,
  defaulting to the number of users in the roster.
- Put launch in the thread (rather than moving it earlier): checkout reuses directories cached by SHA, but **cache writes must be concurrency-safe (T5)**.
  The initial version incorrectly assumed that “each session unpacking independently on the first concurrent round only wastes work and causes no conflict (overwrites with identical content)”—production runs disproved this: all sessions in the same round use the same
  SHA and dest. With unlocked check-then-extract, multiple threads concurrently running `extractall` on the same directory interleave writes to the same files
  (params.yaml develops duplicate entry keys/garbled bytes), and while A is halfway through extraction, B's “directory is nonempty” check treats the incomplete copy as
  a complete cache entry and reuses it. T5 fix: hold a launcher instance lock throughout the check + extraction + extract to a unique temporary directory and atomically rename it
  into place (an incomplete result never has the dest name; a crash leaves only a harmless orphan tmp directory).
- Enter phases d/b only after all of phase a has completed (the `as_completed` loop finishes); round-boundary semantics and checkpoints (spec-0004,
  at round granularity) are unaffected.

### T1: Shared-state locking (complete audit table)

| Shared point | Current state | Decision |
|---|---|---|
| `SessionStore.save` (index.json read-modify-write) | The docstring acknowledges that “the single-process MVP does not handle concurrent write races” | **Add locking**: instance-level `threading.Lock`; hold the lock throughout save (preserving the order: full data first, then index) |
| `live.py` agents/history/run.json | mkstemp atomic writes only prevent torn writes; `update_agent` and others remain read-modify-write operations, losing updates under concurrency | **Add locking**: one module-level lock around the entire read-modify-write operation in update_agent / append_agent_log / archive_agent / update_live_run / clear_live |
| `sources/git.py` clone cache | Concurrent provision calls for the same repository collide on the cache directory | **Avoid by moving earlier** (T3 stage one), without locking |
| `HarnessLauncher._checkout` (shared cache directory for the same SHA) | Unlocked check-then-extract: concurrent extractions interleave writes to params.yaml (duplicate keys/garbled bytes), and partially extracted directories are incorrectly treated as complete and reused—missed in the initial audit, encountered in production runs | **T5 locking + atomic rename of a temporary directory** |
| `GiteaTracker` (shared `requests.Session`) | requests does not officially guarantee Session thread safety, and Gitea returns Set-Cookie (concurrent cookiejar mutation)—the initial “monitor for now” decision was disproved by the second production round | **T6 thread-local Session** (one per thread; setter preserves the test injection point); the `_label_ids` cache relies on the existing 409/422 race fallback, without locking |
| `launcher._yaml` (module-level shared ruamel YAML instance) | ruamel YAML instances are not thread-safe (internal parser state is shared across calls); concurrent load calls during parallel launch interfere with one another—discovered in the second production round | **T5 addition: create a new instance for each parse** (construction overhead is negligible) |
| `ApiPersonaClient.client` (shared openai client) | Built on httpx; official documentation guarantees thread safety | No change needed |
| `os.environ` | Untouched in the user phase (launcher explicitly passes an env dict to Popen); global env is set only in the dev/architect phases | d/b are sequential, so there is inherently no conflict (one basis for the Non-goal) |
| run.py `current["round"]` | Read-only within phase a (the round cursor is written only at round boundaries) | No change needed |

### Task DAG and file allocation

```
T1 (storage/projection locking)───┐
                                  ├──> T3 (parallelize section a + knobs) ──> T4 (concurrent end-to-end regression)
T2 (client factory)───────────────┘
T5 (checkout concurrency safety, no dependencies—added after a production run exposed an audit omission)
```

| Task | files (mutually exclusive) |
|---|---|
| T1 | `backend/ahe_beta/user/session_store.py`, `backend/ahe_beta/loop/live.py`, `backend/tests/user/test_session_store.py`, `backend/tests/loop/test_live.py` |
| T2 | `backend/ahe_beta/loop/sim_user.py`, `backend/tests/loop/test_sim_user.py` |
| T3 | `backend/ahe_beta/loop/orchestrator.py`, `backend/ahe_beta/experiment/controllers/ordinary.py`, `backend/tests/loop/test_orchestrator.py` |
| T4 | `backend/tests/loop/test_parallel_sessions.py` (new, this group's e2e) |
| T5 | `backend/ahe_beta/harness/launcher.py`, `backend/tests/harness/test_launcher.py` |

e2e verification path: `backend/tests/loop/test_parallel_sessions.py` (all Fake, with no dependency on real LLM/Gitea).
There is also a **small-scale real-world verification excluded from CI**: 3 users × 1 round, comparing parallel execution against the sequential baseline for experience score distribution and issue
count magnitude, confirming no systematic shift (concurrency should change only wall-clock time).

### Frontend impact (audit conclusion: zero changes)

The full frontend flow has been checked. This spec includes no frontend tasks, for the following reasons:

- **Decoupling PERSONA_LIMIT (coverage) from max_parallel_users (concurrency) has zero frontend impact**: the room display
  actually follows “how many agent slots appear in the run” (`App.tsx` filters `/api/agents` by role), rather than any
  configuration value—the roster pipeline for `/api/config` is already in place (api.ts `getConfig` + the `Roster` type), but the frontend
  **has no call sites** (existing dead code, outside this spec). Concurrency is inherently invisible to the frontend; the two controls are independent and do not need
  awareness of each other.
- **Card order during a run is unaffected by concurrency**: the `live.read_agents` server sorts lexicographically by `(role, agent_id)`
  (`user-SR-001 < user-SR-002 < …`), independent of write/update order; column order remains stable whenever polled.
- **Within-round ordering semantics for “+Completed” change (accepted, no change)**: history is append-only and displays entries within a round in archive order;
  under sequential execution, archive order = fixed-set order (SR order); under parallel execution, it becomes **completion order** (whoever finishes first appears first, potentially differing between runs).
  This is considered acceptable, truthful semantics (first completed, first archived, also reflecting relative speed); if determinism is needed later, the frontend can sort within a round by label
  in one line, left to the frontend mainline.
- Multiple cards running simultaneously are already supported: each slot has independent status/`started_at` timing, and 3s polling makes no ordering assumptions; data-layer
  races are eliminated by T1's live lock.

## Drawbacks

- **Amplified LLM gateway pressure**: calls from N concurrent users × (≤12 outer turns + heartbeat wakeups + ≤4 inner steps) execute concurrently,
  increasing the probability of 429 responses; `ApiPersonaClient` already has backoff, and a cross-session semaphore is deferred for now (Unresolved #1).
- **Increased process count**: each session = 1 harness Python process + its bash/sandbox subprocesses; 3-4 concurrent sessions mean a dozen or so
  local processes, which is manageable, but higher concurrency needs attention.
- **Interleaved logs**: stderr/print output from multiple sessions interleaves; troubleshooting a single session requires filtering by session_id/agent slot (the dashboard already separates
  agents into slots, limiting the impact).
- Improper handling of exception-swallowing paths in the thread pool could silently drop sessions—prevented by T3's as_completed collection + explicit logging requirements.

## Rationale and alternatives

**Decision among three options (workload: a session spends ~100% of its time in blocking waits, releasing the GIL throughout—persona LLM network IO +
harness pipe IO are the two main components):**

| Approach | Decision | Rationale |
|---|---|---|
| **Thread pool** | ✅ Adopt | No rewrites to existing synchronous code; only the orchestration layer changes; the GIL is not a bottleneck (a workload consisting entirely of waiting); NexAU's own subagent_manager makes the same judgment |
| asyncio | ❌ | Requires rewriting the entire run_session / persona_client（AsyncOpenAI）/ launcher (asynchronous pipes) chain; the envelope's deterministic single-threaded ordering is a design asset; concurrency is only 3~10, so coroutine benefits would go unused—violates Occam's razor |
| Multiprocessing | ❌ | Isolation already exists in the right place—the heavy work for each session already runs in an independent subprocess (harness=Popen process tree), while orchestration threads only wait on pipes; adding multiprocessing would merely complicate cross-process on_turn callbacks, Session pickling, and live writes, with zero benefit |

**Alternative: retain serial execution and trade fewer personas for more rounds**—rejected: persona diversity is precisely the distributional foundation of user experience signals
(the observability metrics section explicitly states that issues dropping to zero too early = insufficient persona diversity); reducing coverage runs counter to the goal.

## Prior art

- **NexAU `subagent_manager`**: uses ThreadPoolExecutor for parallel subagents, applying the same judgment of “blocking IO agent workload + thread pool”; an existing precedent in this repository's runtime.
- **0012/0013 (this spec's robustness baseline, with key points restated here)**: launcher `begin/poll/control` splits a send round
  into polling slices (process alive = legitimate long-running task, no blind termination; process dead without returning a complete line = precise deadlock detection; 1800s absolute limit
  prevents livelock; `start_new_session`+`killpg` reclaims orphans as a group); on the loop side, all harness exceptions are converted to
  `[harness error]` and fed back to the persona as observations, so the session does not crash and crashes generate user experience + issue gradients. Without these, a hung
  harness is “visibly stuck” during serial execution but “silently exhausts the worker pool” during concurrent execution.
- **spec-0004 HarborRunner**: checkpoints are at round granularity; how execution is parallelized within a round is transparent to the runner—this spec is
  orthogonal to and compatible with Harbor mode.

## Unresolved questions

1. **Cross-session LLM concurrency semaphore**: is `threading.Semaphore(MAX_LLM_CONCURRENCY)` needed around
   `ApiPersonaClient._create`? Defer for now; observe gateway 429 frequency during execution before deciding (backoff already exists).
   (The original item 2, “Keep observing GiteaTracker Session,” was disproved by the second production round and converted into the T6 fix; see the audit table.)

## Future possibilities

- **Parallel phase b**: multiple dev agents each make changes in independent worktrees + rebase, then push serially (requires a conflict-handling design;
  create a separate spec).
- **Cross-session collaboration scenarios**: multiple personas share one harness (pairing/relay); the envelope needs inter-session communication primitives.
- **Adaptive concurrency**: dynamically reduce max_parallel_users based on the gateway 429 rate.
- **Harbor multi-task sharding**: shard phase a by persona across multiple harbor tasks (sandbox-level parallelism); checkpoint
  aggregation semantics need to be extended.

