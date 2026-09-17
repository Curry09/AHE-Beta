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
A Docker daemon is not required. Keep concurrency at 1 for this pilot and inject
secrets only at runtime. Never write credentials into a manifest or committed
configuration.

Before running a preflight:

```bash
export DAYTONA_API_KEY='...'
export OPENROUTER_API_KEY='...'
export HARNESS_V0_ARCHIVE=/absolute/path/to/harness-v0-cade14d.tar.gz
```

`HARNESS_V0_ARCHIVE` must have the SHA-256 recorded in `protocol.json`. The
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
