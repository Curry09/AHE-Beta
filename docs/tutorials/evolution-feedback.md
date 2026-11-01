# Feedback and objective assessment during evolution

English | [简体中文](evolution-feedback.zh-CN.md)

This tutorial starts a small experiment with independent assessment after each user round. The Harness calculates a total and writes `answer.json`, which a private custom verifier checks after freezing. The example demonstrates the complete flow from public task inputs through private assessment to feedback processing.

## What changes in the loop

The two interaction modes share one feedback structure:

| Axis | Meaning |
| --- | --- |
| `task_assessment` | Reviewer's `fulfilled`, `unfulfilled` or `unknown` observation, with source/evidence references; independent grader receipts remain separate |
| `experience` | `rated` with an integer 1–4, or `missing` / `invalid` / `unavailable` with `score: null` and a reason |
| `attribution` | Confirmed, uncertain or unknown causes; a task failure alone does not prove a Harness defect |
| `opportunities` | Zero or more suggestions; success does not require filing an Issue |

In `direct`, the Actor receives the task once and cannot expect another user message. An interacting `simulated_user` retains the tools available to that persona: main/waiting judge and `main_final_check` use the live workspace. Competent/expert users may write tests, run commands and edit code according to their working style. Checking remains optional; users are not required to take over. A final-check episode is still limited to four tool calls, once per decision cycle, before re-judgment and the next action.

Only when the session terminates are the Actor and background writers stopped and full scoring artifacts frozen. Terminal reviewers can inspect captured files/diffs but cannot edit files, execute shell commands or send another task message. The user's operations remain in `sim_trace`; the frozen workspace may include their contributions, so passing assessment of that result does not establish independent Harness success. Existing traces do not provide complete line-level attribution. Missing experience is not replaced by a derived diagnostic score.

A complete report plan is saved before publishing Issues. Each successful publication gets a separate receipt; recovery resumes that plan without rerunning the Actor/reviewer or duplicating Issues. An empty plan is valid. The round's objective-assessment stage runs before requirements processing, including in the final user-only round. Safe summaries inform later correction; failing an assessment does not automatically reject or roll back a delivered candidate.

## 1. Install and pin the verifier image

From the repository root, on a trusted host with Docker:

```bash
uv sync --locked --extra experiments --extra evaluation --extra dev
docker info
# Resolve the actual registry image digest used by your worker:
docker pull python:3.12-slim
GRADER_IMAGE=$(docker image inspect python:3.12-slim --format '{{index .RepoDigests 0}}')
test -n "$GRADER_IMAGE"
```

The image is only the isolated custom verifier environment. Task/controller images use the normal backend configuration. A local immutable `sha256:...` image ID also works on the same worker host; use a registry digest when another host must obtain it.

## 2. Generate public and private materials

Choose a new directory outside the repository:

```bash
CASE_DIR="$HOME/evolution-feedback-local"
bash backend/scripts/e2e-spec-0084-evolution-feedback.sh \
  --prepare-example "$CASE_DIR" --backend local --grader-image "$GRADER_IMAGE"
# For E2B, use a different new CASE_DIR and --backend e2b.
```

The generator starts no resources or model requests. It creates:

| Path under `CASE_DIR` | Use |
| --- | --- |
| `experiment.json` | Complete experiment with `evaluation.session_grading` enabled and real digests |
| `public/task/` | Public instruction, source, setup, task contract and `answer.json` export declaration |
| `private/grading-plan.json`, `private/verifier.py` | Fixed custom rule and image; never task materials |
| `private/worker.key`, `private/worker.pub` | Newly generated Ed25519 signing key and public key; private key is mode 0600 |
| `private/controls.json`, `private/positive.json`, `private/negative.json` | Operator-owned verifier controls, not Harness outputs |

The repository's `examples/experiments/evolution-feedback-local.json` and `evolution-feedback-e2b.json` are ungraded base templates. The generator replaces the task and enables assessment with actual hashes. It does not insert placeholder hashes or distribute a reusable private key.

Edit the four model selections in `experiment.json` to match your provider. Copy `examples/experiment.env.example` to `"$CASE_DIR/secrets.env"`, set mode 0600 and fill the role credentials. E2B also needs `E2B_API_KEY` and a Gitea.com token. See [configuration](../CONFIGURATION.md) for the protocols and explicit context limits. Keep private files outside `public/task/` and the task source.

The generated task uses a 600-second operator quota for this small example. A real task may instead declare `execution.budget_seconds: 7200` with `budget_source: task_metadata`. That total starts at first task dispatch and is not renewed by messages. It overrides the runtime fallback of 1800 seconds. Optional `runtime.harness.message_activity_seconds` can add a shorter per-message bound; it is absent by default. Termination grace is for cleanup only. Seed defaults remain 100 iterations and 32768 output tokens, so available time is not a guarantee of completing or running for that long.

## 3. Check and prepare

Preparation pins the OpenAgents execution-evidence reader through the [compatibility manifest](../../release/compatibility.json), preferring `execution_evidence.reader_release_commit` and otherwise using `reader_candidate_commit`. An explicit `source.openagents` must also identify an immutable revision supporting the same execution-evidence contract. Preflight checks the actual reader capabilities. See the [release guide](../RELEASING.md) for paired version updates.

```bash
CONFIG="$CASE_DIR/experiment.json"
PLAN="$CASE_DIR/private/grading-plan.json"
PUBLIC_KEY="$CASE_DIR/private/worker.pub"
SECRETS="$CASE_DIR/secrets.env"

uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  check --config "$CONFIG" --grading-plan "$PLAN" \
  --grading-worker-public-key "$PUBLIC_KEY" --offline
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  check --config "$CONFIG" --grading-plan "$PLAN" \
  --grading-worker-public-key "$PUBLIC_KEY" --secrets-file "$SECRETS"
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  prepare --config "$CONFIG" --grading-plan "$PLAN" \
  --grading-worker-public-key "$PUBLIC_KEY" --secrets-file "$SECRETS"
```

`check --offline` validates configuration/materials without model or provider operations. `prepare` freezes the task, Harness, execution/feedback conditions, public worker identity and grading implementation. The private plan and key are not copied into task materials. Wait for successful preparation and copy its run ID. Changing grading files or implementation after preparation is rejected; prepare a new run for changed inputs.

`plan_sha256` hashes the grading-plan file's exact bytes. `worker_key_sha256` hashes the raw 32-byte Ed25519 public key, not the PEM text. The generator computes both. Do not run `sha256sum worker.pub` and use that as the worker identity.

An optional verifier-only check is:

```bash
bash backend/scripts/e2e-spec-0084-evolution-feedback.sh --grader-controls "$CASE_DIR"
```

It requires Docker and executes both controls through the shared production grading service. `verifier-controls/summary.json` should show positive `completed / true` and negative `completed / false`. These controls do not exercise an Actor, an experiment backend or the worker exchange.

## 4. Start the experiment, then its worker

```bash
RUN_ID=REPLACE_WITH_PREPARED_RUN_ID
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  run "$RUN_ID" --secrets-file "$SECRETS"
```

In another terminal on the same trusted host, restore `RUN_ID`, `CASE_DIR`, `PLAN` and `SECRETS`, then run:

```bash
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py \
  assessment-worker "$RUN_ID" --plan "$PLAN" \
  --signing-key "$CASE_DIR/private/worker.key" --secrets-file "$SECRETS" --follow
```

This foreground worker needs Docker for **both** local and E2B experiments. E2B does not receive a Docker socket or private verifier files. The worker uses the same prepared run directory and provider access to exchange sealed requests and signed results. If you used global `--runs-dir`, put the same option before every subcommand, including `assessment-worker`. A separate worker host must have the same prepared run state, compatible checkout and credentials; the command is not a remote-worker registration service.

Before worker readiness, `objective_grading / PENDING / worker_not_ready` is expected. Start the worker to proceed. Keep it running during the experiment; `--follow` continues polling and exits when the controller is `EXITED` or `STOPPED` with no pending requests. Ctrl+C can stop the worker earlier. Without `--follow`, it processes currently pending work and exits. Restart it with the same plan/key after an interruption. Accepted receipts are reused; stale worker generations and conflicting duplicate results are rejected. This recovery does not create a new user attempt.

## 5. Inspect, collect and interpret

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID"
```

Use the normal [stop/resume/cleanup commands](../QUICKSTART.md#4-stop-resume-and-collect). Keep the host and worker available until the final round is assessed and collection is complete. After completion, stop the worker with Ctrl+C; stopping only that process does not destroy experiment resources.

| Observation | Interpretation |
| --- | --- |
| `completed`, `passed: true/false` | The declared independent rule ran and produced a valid task outcome |
| `ungradable`, `unavailable`, `crashed`, `timed_out` | No valid binary task outcome; `passed` stays null |
| `not_configured` | No objective assessment was requested |
| Experience `missing`, `invalid`, `unavailable` | No valid subjective score; excluded from rated-score statistics |
| Assessment `PENDING` | The stage is waiting; it is neither a pass nor a failure |

The run retains contracts, full Actor artifacts and report receipts. Controller-side `assessment/` stores requests, accepted signed receipts and safe round feedback. The worker keeps private execution details under its local run's `evaluation/online/`; these files are excluded from collection and from Issue/demand evidence. Safe summaries contain outcome, identity and digest fields, not verifier assertions, hidden tests or stdout. The reviewer observation and independent result can disagree without one overwriting the other.

The online contract supports assessments reproducible from retained workspace artifacts. It rejects profiles requiring a still-live original task environment or trusted managed-service measurements. Keep unsupported results explicit rather than guessing a new environment. [Post-run grading](post-run-grading.md) uses the same assessment service after collection and remains independent; held-out Harness benchmark runs under `evaluation/` also remain separate. See the [verification guide](../VERIFICATION.md) for checks you can run on this checkout.
