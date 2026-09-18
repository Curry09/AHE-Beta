# Harness Bench

`harness_bench` is the implementation of Spec 0065. It freezes the experimental
variables before launch, resolves official task budgets, runs one persistent
Harness session, and keeps task outcomes separate from evaluation-infrastructure
failures.

Supported interaction policies:

- `direct`: one official user message, no follow-up.
- `simulated_user`: an external LLM user that observes public progress every
  heartbeat and may wait, send a message, interrupt, give up, or continue after a
  reply.
- `benchmark_native`: the official user protocol for benchmarks such as tau3.

Budget policy is fixed: use pinned official `[agent].timeout_sec` when present;
otherwise use 1800 seconds and record `fallback_no_official_timeout`. The budget
belongs to the whole trial, not each turn. Harness self-timeouts remain visible
product behavior.

Validate and freeze a plan:

```bash
python -m evaluation.harness_bench.cli validate /path/to/plan.yaml
python -m evaluation.harness_bench.cli plan /path/to/plan.yaml
```

Execution uses an injected trial executor because task provisioning is benchmark
and provider specific:

```bash
python -m evaluation.harness_bench.cli run plan.yaml \
  --executor package.module:execute_trial
```

The executor receives the frozen trial row, attempt number, and attempt artifact
directory and returns `TrialResult`. It cannot change the manifest. Invalid
infrastructure attempts may be retried; task failures, Harness failures, and
deadlines are terminal measurements.
