> Historical research workflow: depends on the suite for that date, the external sandbox, and the corresponding configuration. For generic installation, start from the root README / docs/QUICKSTART.md. Before running, explicitly configure your own Gitea/dashboard addresses; do not reuse the original experimental services.

# Scaling Experiment Quick Start Guide

This document is for operators taking over the repository for the first time. Formal scaling uses E2B + Boyue; each N is an independent controller, E2B sandbox, Gitea repository, and recovery identity. Do not put the five N values in the same process.

## 1. Credentials and Prerequisites

Prepare `.e2b` and `.boyue` in the repository root, or inject them through environment variables:

```bash
export E2B_API_KEY='...'
export BOYUE_API_KEY='...'
export GITEA_TOKEN='...'
export ALLOW_INSECURE_GITEA=1       # Only when Gitea uses a verified HTTP VPS
export PATH=/root/miniconda3/bin:$PATH
```

Credentials must not be written to configuration, receipts, logs, or git. The formal model is fixed as follows: the user/harness uses `glm-5.3-flash`, triage/designer/PM/developer use `glm-5.3`, and the owner handles the mechanical workflow.

## 2. Materialization and Freezing

When running for the first time or changing machines, regenerate the N-specific payload from the repository source data:

```bash
python evaluation/harness-suite-20260920/prepare_scaling_runtime_bundles.py \
  --n all --materialize
```

When freezing the receipt, you must provide a passed end-to-end canary; do not bypass the gate with an empty receipt:

```bash
python evaluation/harness-suite-20260920/freeze_scaling_runtime.py \
  --n all \
  --canary-receipt evaluation/harness-suite-20260920/prepared/scaling-e2b-20260922/existing-n1-round1-evidence.json
```

Check each group before starting:

```bash
python evaluation/harness-suite-20260920/run_scaling_e2b.py --n 16 --check-launch
python evaluation/harness-suite-20260920/run_scaling_e2b.py --n 32 --check-launch
```

The output must be `launchable: true`. If a check fails, first fix the receipt/config/payload; do not manually delete the gate or call the executor directly.

## 3. Startup

Use one independent terminal or tmux session for each N. `{n}` is a placeholder automatically replaced by the launcher; `--gitea-source-sandbox-id` is only for relaying credentials from the verified N1 sandbox relay VPS Gitea, and the token must not be written into the command line.

```bash
cd /root/src/auto-designer
export ALLOW_INSECURE_GITEA=1
export PATH=/root/miniconda3/bin:$PATH

bash evaluation/harness-suite-20260920/start_scaling_n16_e2b.sh \
  --executor 'python evaluation/harness-suite-20260920/run_scaling_bundle_e2b.py \
    --n {n} --gitea-source-sandbox-id <verified-n1-sandbox-id>'

bash evaluation/harness-suite-20260920/start_scaling_n32_e2b.sh \
  --executor 'python evaluation/harness-suite-20260920/run_scaling_bundle_e2b.py \
    --n {n} --gitea-source-sandbox-id <verified-n1-sandbox-id>'
```

The current role scales for N16/N32 are respectively:

| N | users | triage | designer | PM | developer |
|---:|---:|---:|---:|---:|---:|
| 16 | 16 | 8 | 1 | 1 | 4 |
| 32 | 32 | 16 | 2 | 2 | 8 |

Run 5 rounds for each group. `latency_isolated_timeout.enabled=true`, with the wall guard set to 600 seconds; during actual execution, explicitly export them through `AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT` and
`AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS`.

## 4. Viewing and Recovery

The local entry point only stores controller state; the actual closed-loop logs are in `/opt/hse-run/controller.log` in the E2B sandbox. The local state directory is:

```text
evaluation/harness-suite-20260920/runs/scaling-e2b-20260922/n{N}/<run_id>/
```

After an interruption, you may only use the corresponding resume wrapper; resume must reuse the original sandbox, Gitea repository, run ID, and recovery identity. The wrapper does not accept local parameters such as `--run-id`/`--sandbox-id`; the run ID is passed to the remote bundle by `--executor`, and the sandbox ID is read from the persistent state of that run:

```bash
bash evaluation/harness-suite-20260920/resume_scaling_n16_e2b.sh \
  --executor 'python evaluation/harness-suite-20260920/run_scaling_bundle_e2b.py \
    --n {n} --resume --run-id <run-id> \
    --gitea-source-sandbox-id <verified-n1-sandbox-id>'
```

Do not use `start` as a substitute for `resume`, and do not recreate the sandbox to “resume the run.”

## 5. Results and Cleanup

The session, trace, grader, and round checkpoint for each task are written by the remote runtime to `/opt/hse-run/artifacts`, and the controller updates the VPS dashboard through the state relay. Report the following separately when scoring:

- official grader correctness；
- harness/session completion；
- user acceptance/interaction outcome；
- provider/infrastructure timeout；
- raw wall time, active time, and provider wait。

Canary results must not be included in formal accuracy. The `prepared/`, `runs/`, and `harbor-canary-jobs/` generated by the experiment have been added to `.gitignore`; do not submit the payload, logs, sandbox state, or any credentials.
