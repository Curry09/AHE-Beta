# Spec0073 multi-task, multi-user validation

Recorded on 2026-10-03 on `feat/unified-experiment-entry`, before committing Spec0073. This report separates offline execution from provider verification. The [tutorial](../tutorials/multi-user-experiment.md) and [中文教程](../tutorials/multi-user-experiment.zh-CN.md) use the same commands and plan.

## Reproduce offline verification

```bash
bash backend/scripts/e2e-spec-0073-multi-task-users.sh
```

The script uses locked dependencies and does not launch a model, Docker, E2B or Gitea. It checks all four maintained N1/N4 configurations, current entry points, materials, logical bindings, controller behavior and the complete offline loop. Offline configuration previews remain unfrozen and do not fetch Git or claim final source digests.

## Executed loop and boundaries

`backend/tests/test_experiment_multitask_e2e.py` passed both local and E2B resource-shape cases. Each case freezes two fixture tasks, compiles a two-round/four-persona plan, builds the real frozen controller context, and uses the production mixed-interaction session factory. Both task kinds and both `simulated_user` and `direct` interactions execute. Eight actual SessionStore results carry the expected task digest, persona, round/slot, stable session ID and Harness SHA. Per-session source copies remain separate and the frozen baselines retain their original bytes.

The test uses real Triager, Synthesizer and mechanical Owner drivers, actual issue-creation side effects and RecoveryStore. Model responses are scripted at their boundary. The first round produces nonempty source issues, a synthesis proposal and admitted delivery tickets. A delivery substitute writes and commits a change in a real temporary Harness Git repository, closes the admitted tickets, and lets the runner seal the resulting SHA. The second round uses that SHA and produces no second delivery batch.

A provider-boundary failure occurs before one unfinished user's model call. Reopening the recovery ledger and changing the provider coordinate resumes the unfinished sessions. Complete session bytes remain unchanged, completed users execute only once, and another run of the same sealed rounds creates no additional delivery or session calls. The test observes at most two concurrent active user sessions.

Git fetch, model/persona decisions, provider provisioning, forge transport and external `wait_delivery` are substitutes. This is an offline core integration test, **not** a real OpenAgents delivery, a Gitea.com run, a Docker run or an E2B run. It demonstrates ledger interruption and recovery inside the actual orchestrator; lifecycle CLI stop/resume behavior is covered separately by lifecycle tests. It does not prove real provider cleanup, cloud permissions or model quality.

## Supporting checks

- Public examples and repository checks: 26 tests passed; all four example configurations pass offline checks. N4 examples select four existing persona cards and the same explicit task-swapping plan across local/E2B and English/Chinese documentation.
- The material/configuration/workload suite checks final catalog/plan digests, mutation rejection, strict contract-version types, and unchanged handling of old frozen N1 runs. Old input is normalized at the configuration boundary; old frozen inputs are not rewritten.
- Controller tests cover same-task N4/N8 users, frozen mixed-task resolution, logical session identity, invalid cached results before model/provisioning, and recovery. Lifecycle, observation and usage tests cover their own boundaries.
- Backend and launcher verification performed during this change: 297 tests passed across launcher/E2B/simulation tests, including actual Harness and tool subprocess inheritance of session HOME, independent venv, nonce, cache and copy mode. These subprocess tests do not establish a live E2B sandbox deployment.
- Dashboard/lifecycle/status verification: 144 tests passed; frontend 19 tests passed and its build succeeded. Metadata includes task/session/Harness provenance and collected snapshot source; unknown provider state does not imply completion.
- The paired OpenAgents checkout at `a752e8830a13f44d97a3043d1f3e8dd16bd8d8aa` passed the OpenAgents configuration contract and observation contract: gzip/zip accepted and 15 invalid-evidence cases rejected. The old local OpenAgents checkout was not used as the paired contract reference.

The targeted script passed **136 tests in 28.30 seconds**. The whole-repository pytest run passed **1477 tests, with 2 skipped, in 107.56 seconds**. Repository-wide Ruff lint and format checks passed for 498 Python files. These counts cover offline tests, not live acceptance.

The ordinary example's actual hashed setup also ran in a fresh temporary venv with `UV_OFFLINE=1`. It installed the five locked packages, imported the task module and ran its visible tests: **4 passed, 2 failed**. The two expected failures reproduce the missing quantity multiplication in a multi-unit order and a mixed cart. The checked-in source intentionally preserves this task fault for the user to repair.

## Live verification in progress

On 2026-10-03 Docker became available (engine 27.5.1, Compose v2.32.4). The operator explicitly authorized deleting one named old Gitea.com test repository; its Git mirror and API metadata were backed up before deletion. Only an empty repository created by this verification's failed bootstrap was subsequently removed to retry; unrelated repositories and sandboxes were retained.

The first E2B launch exposed a real bootstrap import error: its task-preflight subprocess had no frozen `controller/backend` on `PYTHONPATH`. The fix now sets that path explicitly. The regression actually executes the portable bootstrap and worker subprocesses from archived source with a poisoned ambient package, rather than injecting the developer checkout into its test interpreter. Its related regression suite passed 49 tests.

The first local launch exposed an observation error: all four user units were marked running before the two-worker pool dispatched them. `begin_unit` now runs after a worker is acquired. A real thread barrier verifies two running/two pending slots, no started event or incremented attempt for a queued slot, and four completed slots after release. The related controller/recovery suite passed 65 tests.

The initial frozen runs were retained as evidence and their compute was destroyed. New runs freeze both fixes: local `20261003T045007Z-38f9ccbb` and E2B `20261003T045007Z-da1645b2`. Both maintained N4 configurations passed online checks, preparation, provider preflight and controller startup with their configured `claude-opus-5-5` models. Both entered R1 with two running and two pending sessions; the E2B run produced a real Harness reply. Both subsequently saved complete user sessions. Local stop/resume preserved the first two complete session files byte for byte and retried unfinished users. E2B stop/resume retained its sandbox/repository, preserved both complete session files and their attempt-one ledger entries, and retried only the unfinished users. A real cloud session automatically published a source-feedback Issue with its evidence; the local and collected-cloud dashboard read routes passed against actual run artifacts. These are **provider/session/recovery checks, not a completed two-round acceptance**.

The remaining live acceptance is check → prepare → run → status/logs → stop/resume → collect/dashboard → destroy, retaining actual session/round seals, nonempty R1 delivery and the R2 Harness SHA. Successful offline tests, startup or collection alone cannot replace those records. This section must be updated with actual terminal evidence before claiming that coverage.
