# Public harness pilot — 2026-09-17

This pilot contains 19 deliberately heterogeneous tasks:

- SWE-bench Verified: 6 repository-level software engineering tasks.
- Terminal-Bench 4.0: 5 long-horizon terminal tasks.
- TUA-Bench: 4 computer/tool-use tasks.
- tau3-bench Core/Text: 4 multi-turn user-and-tool interaction tasks.

The machine-readable selection, exact revisions, task IDs, task digests, and resource hints are in `selection.json`. The generated thin evaluation package lives in `prepared/`; rebuild it with `prepare_evalset.py` and verify it offline with `validate_evalset.py`. Generated benchmark data, run artifacts, credentials, and the harness archive are intentionally not committed.

The package has a hard data boundary:

- `prepared/agent-inputs/` may be passed to the harness or user simulator.
- `prepared/controller-private/` contains official tests, solutions, gold patches, and evaluation criteria. Never mount that directory into an agent sandbox.

To rebuild the thin package from the pinned public sources:

```bash
export SWE_BENCH_PARQUET=/absolute/path/to/swe-bench-verified/test.parquet
bash fetch_and_prepare.sh
```

The fetcher requires `curl`, `uv`, Python, and `pyarrow`. It downloads TUA-Bench and tau3-bench into a temporary source cache, resolves each Terminal-Bench task directly from Harbor Hub by content digest, builds `prepared/`, and runs the offline integrity/boundary validator. The SWE-bench parquet is supplied explicitly and checked against the digest in `selection.json`. The builder refuses to overwrite an existing `prepared/` directory.

## What this pilot measures

The selection is intended to expose different harness failure modes: repository navigation, long-running shell work, file and GUI-like artifact manipulation, process supervision, stateful tool use, conversational memory, and workflows in which the simulated user must also act. It is not large enough to estimate leaderboard performance.

## Current execution boundary: Daytona only

The active runners do not use local Docker or a local Harbor installation. The
host runs only the Daytona SDK controller, reads the small prepared task config,
uploads the 20 KiB frozen harness, and downloads result artifacts. Benchmark
source, benchmark Python dependencies, NexAU, the user simulator, model work,
and grading execute inside ephemeral Daytona sandboxes.

- SWE-bench: agent task image in Daytona; official test patch is hidden until
  the model patch is captured.
- Terminal-Bench: agent and Playwright verifier use two separate Daytona
  sandboxes; only the declared artifact crosses the boundary.
- TUA-Bench: task state lives in Daytona; tests are uploaded only after the
  agent exits.
- tau3-bench: the pinned source tree, official environment, official user
  simulator, tool execution, and reward calculation all run in Daytona.

Host requirements are therefore only Python 3.12, `uv`, the Daytona SDK, the
prepared thin task package, the frozen harness archive, and runtime credentials.
A Docker daemon is not required. The tested Daytona tier has a 10 GiB aggregate
memory limit, so schedule at most one 6 GiB plus one 4 GiB sandbox concurrently.
Inject secrets only at runtime. Never write credentials into a manifest or
committed configuration.

Before running a preflight:

```bash
export DAYTONA_API_KEY='...'
export OPENROUTER_API_KEY='...'
export HARNESS_ARCHIVE=/absolute/path/to/harness-under-test.tar.gz
export HARNESS_EVAL_LABEL=baseline-v0-cade14d
```

For the baseline-v0 run, `HARNESS_ARCHIVE` must have the SHA-256 recorded in
`protocol.json`. `HARNESS_V0_ARCHIVE` remains a deprecated compatibility alias;
it does not identify the actual version. The
runners create ignored `runs/` directories locally for downloaded logs and
manifests, and delete their remote sandboxes in a `finally` block.

The real preflight entry points are:

```bash
UV_CACHE_DIR=/tmp/daytona-uv-cache uv run --with daytona \
  python run_daytona_harnessv0_requests6028.py
UV_CACHE_DIR=/tmp/daytona-uv-cache uv run --with daytona \
  python run_daytona_terminal_preflight.py
UV_CACHE_DIR=/tmp/daytona-uv-cache uv run --with daytona \
  python run_daytona_tua_preflight.py
UV_CACHE_DIR=/tmp/daytona-uv-cache uv run --with daytona \
  python run_daytona_tau3_preflight.py
```

The parameterized expansion runners are `run_daytona_swe_case.py`,
`run_daytona_terminal_case.py`, and `run_daytona_tua_case.py`; the tau3 runner
accepts `--domain` and `--task-id`.

### Time-budget policy

Active runners no longer use the pilot's former hard-coded 360-second wait.
They resolve the whole-trial agent budget as follows:

- use pinned `[agent].timeout_sec` from the task's official `task.toml` when it
  exists;
- otherwise use 1800 seconds and record
  `agent_timeout_source=fallback_no_official_timeout`;
- share that one deadline across all conversation turns rather than granting a
  fresh budget to each follow-up;
- size the remote-command wait and Daytona TTL above the task, build, and
  verifier budgets so an outer controller cannot undercut the selected task
  limit.

Harness-owned early termination remains part of the artifact under test. A
Harness `[timeout]` reply is recorded as a self-timeout, not a normal completion.
The JSON results below that explicitly record `360` are historical pilot runs
and must not be reported as official-budget benchmark scores.

`run_daytona_tau3_preflight.py` fetches the locked tau3 source commit inside
the sandbox and sets `TAU2_DATA_DIR` to that retained source tree because the
upstream wheel does not include its task data. The tau3 project still exposes
the `tau2` Python package name.

## Connect the harness under test

This step is mandatory. Selecting Harbor's built-in Terminus, Claude, or Codex agent evaluates that agent integration, not the harness under test.

### Terminal/TUA adapter

The checked-in controller uses the shared stdio adapter directly in Daytona:

- install NexAU from the locked commit inside the sandbox;
- keep one headless harness process across the initial instruction and strict
  user follow-up;
- retain the raw transcript, stderr, artifact, grader log, and manifest;
- use async Daytona sessions for long agent commands so an HTTP read timeout
  cannot erase the remote command logs.

### tau3-bench adapter

Implement the official half-duplex agent interface or use its Gym external-control interface:

- Create exactly one persistent harness session per trial.
- Convert each simulated-user utterance into a harness input message.
- Expose tau tools as native callable tools. If the harness only accepts shell/MCP tools, use a narrow bridge that preserves tool names, arguments, results, and errors.
- Return the harness's assistant response and tool actions to the simulator without adding an extra policy model.
- Fix the user-simulator model, temperature, seed, and maximum turns across all harnesses being compared.

Using the repository's stock `llm_agent` would bypass the harness and answer the wrong experimental question.

## Preflight before spending model budget

1. Verify every selected task resolves under its pinned revision.
2. Run the available oracle/reference agent for each Harbor task. A failed oracle is an environment failure, not a harness failure.
3. Run `tau2 check-data`, then one inexpensive baseline/smoke trial in every selected tau domain.
4. Run one selected task end-to-end through each custom adapter and confirm that the grader result and the raw trace are both retained.
5. Confirm that hidden tests, reference answers, and oracle artifacts are not visible inside the agent context.
6. Deliberately trigger one agent timeout and one provider error to verify that infrastructure failures are classified separately from task failures.

The legacy Harbor compatibility modules remain for comparison, but are not used
by these Daytona entry points.

## Recorded environment-validation results

The four real Daytona preflights in `preflight-results.json` all reached their
official grader. SWE-bench `psf__requests-6028` and TUA-Bench
`106-create-charles-ssh-user` passed. Terminal-Bench `html-js-filter` reached
the grader but failed XSS blocking, and tau3 `airline/7` completed all five
action checks but missed the required user communication. Thus the diagnostic
preflight task success rate is 2/4, harness completion is 4/4, and the observed
infrastructure failure rate is 0/4. These validation runs are explicitly not a
reported benchmark score.

The later rerun in `preflight-results-strict-goal-r3.json` uses the exact
harness archive loaded by `harness-mixed16-20260916-strict-goal-r3` (SHA-256
`686b5eda...9cd4`). It again passes SWE-bench and TUA, again receives reward 0
on tau3 after completing all actions but omitting the required communication,
and fails to return the first Terminal-Bench reply within 360 seconds. Its
end-to-end pass rate remains 2/4 while harness completion drops from 4/4 to
3/4. Controller-only failed attempts are listed separately and excluded.

The eight-task expansion is recorded in
`expanded8-results-strict-goal-r3.json`. It uses two tasks per benchmark. Four
of eight tasks pass end to end, five of eight reach an official grader, one of
those five receives reward 0, and three time out before the first harness reply.
Thus end-to-end pass rate is 4/8, graded-task success is 4/5, and harness
completion is 5/8. Invalid setup/grader attempts fixed during bring-up are
listed separately and excluded from these rates.

The matched baseline-v0 rerun and the direct paired comparison are recorded in
`expanded8-comparison-v0-vs-strict-goal-r3.json`. Across the same eight tasks,
baseline v0 passes 2/8 and completes the harness interaction on 8/8, while
strict-goal-r3 passes 4/8 and completes 5/8. The latest harness wins two paired
tasks (Django and tau3 telecom), loses none on end-to-end pass/fail, and ties six;
however, it regresses completion on three tied-failure tasks by timing out before
its first reply where v0 returned a result. These are one-trial environment-
validation observations, not a statistically stable benchmark score.

The same eight-task paired run with both the harness model and tau3 user
simulator changed to the historical `deepseek/deepseek-v4-flash` model is in
`expanded8-comparison-ds4-flash.json`. The NL judge remains fixed at GPT-4.1.
Both harnesses pass 1/8 (astropy only). Baseline v0 completes 8/8, while
strict-goal-r3 completes 3/8: four first-reply timeouts plus one tau3 protocol
failure where it emits three tool requests in one turn. Both DS4 tau3 retail
runs and the v0 telecom run reach the 40-step maximum with reward 0. Compared
with the GLM-5.2 paired run, DS4 reduces baseline v0 from 2/8 to 1/8 and the
latest harness from 4/8 to 1/8 on this sample.

A separate no-user-interaction check is recorded in
`standard6-results-strict-goal-r3-glm52.json`. It excludes tau3, sends exactly
one official benchmark instruction to each of the six SWE/Terminal/TUA tasks,
and uses `z-ai/glm-5.2`. The latest harness passes 2/6 and completes 3/6. These
aggregate rates match its strict-follow-up run over the same six tasks, though
Django changes from pass to timeout and the TUA pivot task changes from timeout
to pass, showing material run-to-run variance.

The corrected GLM-5.2 LLM-user rerun is recorded in
`llm-user-comparison-glm52.json`. For each non-tau task, the official
instruction is followed by the first harness reply, one GLM-5.2-generated user
follow-up, and a second harness reply. The user model sees no grader or hidden
tests; its prompt, output, and usage are preserved per run. Existing tau3
official-user-simulator trials are reused rather than rerun. On the expanded
eight-task set, baseline v0 passes 4/8 and completes 8/8 interactions, while
strict-goal-r3 passes 3/8 and completes 4/8. These remain one-trial environment
validation observations rather than a stable causal estimate of user-simulator
impact.

## Pilot protocol

Use two stages:

1. Environment validation: one run per task. Do not include these numbers in the reported score.
2. Measurement: three independent trials per task. For tau3-bench, prefer four seeds because the simulated user adds variance; three is the minimum for a low-cost pilot.

Freeze the following in a run manifest:

- benchmark commit/tag and task ID;
- harness Git SHA and adapter SHA;
- exact model identifier and provider endpoint;
- system prompt and tool schema;
- time, token, turn, retry, and cost limits;
- network policy and concurrency;
- user-simulator model and seed for tau3-bench;
- container image digests, not only mutable tags.

Disable silent model fallback and automatic retries that restart a whole task. If API retries are allowed, cap them and record every retry.

## Results to retain

For every trial, retain:

- benchmark reward/pass and per-criterion grader details;
- outcome class: `task_failure`, `harness_failure`, `grader_failure`, or `infrastructure_failure`;
- wall-clock time, model tokens/cost, tool-call count, and retries;
- full assistant/user/tool trajectory with secrets redacted;
- container and harness logs;
- the immutable run manifest.

Report pass rate by benchmark and overall, but also report harness reliability separately:

```text
task_success_rate = passed / valid_trials
harness_completion_rate = trials_reaching_grader / launched_trials
infra_failure_rate = infrastructure_failures / launched_trials
```

Do not convert setup, image-pull, provider, or grader crashes into benchmark failures. Fix the environment and rerun those trials under the same manifest.
