---
number: '0075'
title: "Post-experiment official SWE grading through a unified entry point"
issue: 0
slug: post-run-swe-grading
summary: "Preserve complete session patches, verify frozen tasks and archives, and independently run official fresh-container grading without feeding results back into evolution or modifying the original experiment."
tasks:
- id: T1
  title: "Complete session patches and immutable prediction receipts"
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/user/patches.py
  - backend/ahe_beta/loop/sim_user.py
  - backend/tests/user/test_prediction_artifacts.py
  - backend/ahe_beta/user/sim/runtime.py
  scope: "Both production runners atomically preserve complete patches and relative receipts, with compatibility for legacy Session and error exports"
  acceptance: "Preserve long and empty patches faithfully, reject conflicts/invalid paths, save in both direct and simulated modes, and avoid overwriting on resume"
- id: T2
  title: "Collected input binding and independent official grading"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/grading.py
  - backend/ahe_beta/evaluation/adapters/swebench.py
  - backend/tests/test_experiment_grading.py
  - backend/tests/evaluation/test_swebench_runner.py
  scope: "Strictly read terminal-state archives, match plans/resume data/predictions against the official dataset, reuse the evaluator, and retain each grading run independently"
  acceptance: "Reject mismatches/tampering/unknown reports, retain complete failure states, use the same path for local/E2B archives, and make no model/provider calls or writes to the original run"
- id: T4
  title: "Bilingual tutorial and historical capability status"
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - docs/tutorials/post-run-grading.md
  - docs/tutorials/post-run-grading.zh-CN.md
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  - docs/QUICKSTART.md
  - docs/QUICKSTART.zh-CN.md
  - README.md
  - README.zh-CN.md
  - CLAUDE.md
  scope: "Explain explicit local datasets and hashes, installation of the evaluation extra, grading for both backends, legacy prediction boundaries, and the absence of feedback into evolution"
  acceptance: "Keep English and Chinese commands consistent, distinguish held-out generalization from user-task grading, and accurately update historical gaps"
- id: T3
  title: "Unified grading CLI and complete production acceptance"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T2
  - T4
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/cli.py
  - backend/tests/test_experiment_cli_v2.py
  - backend/tests/test_experiment_grading_e2e.py
  - backend/scripts/e2e-spec-0075-post-run-grading.sh
  - backend/scripts/check_experiment_repository.py
  scope: "Wire up grade round selection/offline verification/JSON, connect real freezing/session/collection to grading, and run the full regression suite"
  acceptance: 
    "Generate patches through the production chain, then collect and grade; keep the original Session/manifest/checkpoint/archive unchanged, and accurately classify results and simulated official boundaries"
---

# 0075 · Post-experiment Official SWE Grading Through the Unified Entry Point

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

The unified experiment command now uses `grade RUN_ID --plan PATH` (0083 retired this group's original dataset parameter): for stopped and fully collected experiments, it verifies frozen tasks, round sessions, and complete patches, then independently invokes the official SWE-bench fresh-container evaluator. By default, it grades all SWE sessions in the final round; a completed round can be explicitly selected. Sessions for which no rule is selected are listed separately as not_configured in the current general report; no scores are fabricated. Post-experiment results are saved in a separate evaluation directory without modifying the original manifest, Session, checkpoint, Issue, seal, or archive.

## Motivation

The unified entry point can already execute mixed tasks and batches, but official grading still has only a low-level evaluator, with no public command bound to run materials. Sessions currently retain only a diff hash; direct review displays only a truncated patch, which cannot reconstruct a complete prediction. Restoring the old controller's online grading switch directly would introduce grading into the context during evolution, while E2B does not provide a fresh Docker instance. The chosen approach is therefore to perform post-experiment grading on the operator's Docker host after collect completes on either backend, and to save complete predictions for new sessions.

This command grades the user task patch for the selected round. It is not a new held-out generalization test of the Harness, and a score on one task cannot establish a general improvement. The existing standalone benchmark tool remains available for true held-out testing; official test_patch, gold patch, and grading conclusions never enter the frozen user/requirements/delivery inputs.

## Guide-level explanation

First run and collect the experiment, then prepare a private grading plan declaring the path and SHA-256 of a local official dataset (JSON/JSONL/parquet), and select the original tasks through the swebench adapter. The dataset is not included in the experiment JSON or task package; the operator installs the pinned evaluation extra and uses Docker locally. E2B experiments are also graded locally after retrieving their complete archives, without running nested Docker in the cloud.

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py grade RUN_ID --plan /path/to/grading-plan.json --offline
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py grade RUN_ID --plan /path/to/grading-plan.json
# Optional --round 1; defaults to config.rounds.count; each plan grader declares its limit in timeout_seconds.
```

The private plan's materials.dataset specifies the file path and sha256. The graders entries declare adapter=swebench, contract_version=1, the original task_ids, an inputs.dataset material reference, and timeout_seconds. The current public CLI does not retain compatibility with the dataset parameter; other suites use their own adapter materials and are not required to use a SWE dataset.

offline only validates collected inputs, bindings, and the dataset; it does not invoke Docker, models, Gitea, or E2B, and does not write grading artifacts. Actual grading runs a fresh evaluator for each session; outputs strictly distinguish completed/pass, completed/fail, missing prediction, unavailable, crashed, and timed_out. A missing prediction is not treated as an empty patch; a successfully exported empty patch with a matching hash can be graded. If an old frozen controller did not save the complete patch, it is explicitly ungradable and requires a new run; patches must not be inferred from truncated traces or current remote code. A complete experiment that has already been destroyed can still be graded without restarting experiment resources.

Official version 4.1.0 lists empty predictions separately as `empty_patch_ids` and skips instance testing. A successfully saved empty patch passes input validation, but is reported as `not_evaluated / official_empty_prediction / passed:null / fresh:false` in actual grading and does not count as complete grading; it is neither a missing prediction nor an evaluator crash. Contradictory reports that also list it as resolved/unresolved are rejected. The [pinned version's official report logic](https://github.com/SWE-bench/SWE-bench/blob/v4.1.0/swebench/harness/reporting.py) is the basis for this classification.

## Reference-level explanation

### Saving session predictions

Add `user/patches.py`. After successful workspace export in both production session runners, simulation and direct, atomically save the complete UTF-8 patch according to `store.root.parent/predictions/<session_id>.patch` (without depending on a mutable cwd or provider directory). Session.workspace_evidence holds an `prediction` receipt: contract_version=1, session_id, path=`predictions/<session_id>.patch`, sha256, bytes. If there is no workspace or export fails, no receipt is issued and failure evidence is retained. A write failure must not produce a fabricated receipt; a conflicting session ID must not overwrite an existing different patch. The complete patch is saved before Session is finally persisted; recovery reuses the original Session/patch. The truncated preview shown to users for direct review retains its existing meaning.

Both runners freeze Git HEAD as `workspace_evidence.diff_base_commit` before the Harness first uses the workspace. Final export produces the complete diff against that initial commit, including Harness commits, staged edits, and new files not ignored by Git; it uses a temporary index without changing the actual Git index or workspace. Failure to capture the baseline produces no gradable receipt. SWE grading requires this base to match the frozen task's Git revision, preventing an empty diff against a modified HEAD from being treated as the final prediction. Old exporters that do not declare the new baseline retain their existing semantics, but their results do not claim conformance to the new grading contract.

Export explicitly disables Git ext-diff and textconv to ensure an applicable raw patch rather than display text; when adding files to the temporary index, it excludes runtime artifacts such as `.venv/`, `__pycache__/`, and `*.py[cod]`. These files are not part of the frozen task source in the first place; dependency environments must not be included in predictions even when the task has no ignore rules of its own. The user's actual index, ignore files, and Git configuration are not modified.

### Binding collected inputs

`experiment/grading.py` reads only a matching schema2/workload-contract1 run, verifies the original materials and RecoveryIdentity, and then reads `archive/collection.json` and artifacts.tar.gz. It requires collection COMPLETE, consistent=true, and terminal=true, with the archive SHA and internal collection/file inventory matching the external receipt; path traversal, links, duplicate member names, and checksum drift are rejected. Archive bytes are authoritative; it does not read live sessions that may still change, the current repository, or a new collect. Inputs are accepted only when the archived manifest matches the current frozen identity and the collection controller nonce agrees with the archived recovery/supervisor terminal state; any unsupported legacy archive structure produces an explicit error, without implicitly rewriting materials.

Match the plan binding against recovery's round.user_sha and the users unit's key/session_id/completion status; verify persona, task_id/digest/kind, run_id, round_no/slot, harness_sha, and session_id for each Session. The selected round must be sealed; the original COMPLETE does not mean all users are valid. The prediction path must be the unique expected path for this session, and hash/bytes must match the complete archived patch and workspace diff hash. An invalid/infrastructure session is not promoted to valid completion; report its original status and grading applicability.

Also verify the current host runtime's experiment terminal state, collection COMPLETE, and the latest available controller nonce, rejecting old archives after resume/RUNNING, PROVISIONING, UNKNOWN, or PARTIAL; retaining an old archive file does not mean it remains usable for the current generation. Check again when reading and before starting an attempt, rejecting changes without invoking a provider for validation. The presence of sim_trace, evaluation_status, and interaction_status used to determine grading eligibility must agree with the normalized states of immutable recovery output; modifying Session's derived states must not promote an invalid session.

### Dataset and evaluator

Read fixed bytes from the local dataset and verify the user-provided SHA (reject changes before and after reading); JSON/JSONL/parquet must uniquely match the selected instance_id, and repo/base_commit must match the frozen SWE package's Git repo/revision. Copy the selected original official row into the grading attempt; hidden test/gold fields are used only in this directory and the evaluator's fresh container. Invalid inputs are rejected before invoking the evaluator. The internal _SWEbenchRunner reuses the official CLI (pinned to swebench 4.1.0); actual execution first checks that dependencies and Docker are available. An official report becomes completed only if it explicitly lists the target instance as resolved or unresolved and does not include it in the error/incomplete/missing sets; an unknown/malformed report is crashed and cannot be interpreted as an ordinary failure. Official version 4.1.0 sometimes still summarizes an instance as unresolved after pytest fails to load conftest or collect tests. If the formal test interval in its raw test_output contains explicit loading/collection failure diagnostics, classify it as crashed / official_test_start_failed and do not count it as an ordinary failure score; such errors may originate from the environment or the patch, and official tests and scoring are not rewritten. fresh is the official isolated execution contract. Record the evaluator version/command, patch/dataset hashes, and raw official reports; do not fabricate official success.

### Independent results and repeated operations

`run_dir/evaluation/<unique-attempt-id>/` stores the frozen grading intent, each prediction/official row, evaluator logs/reports, and the summary; a separate lock serializes grading for this run without writing to the run runtime/journal. To avoid reading partially persisted administrative operations, briefly open the existing operation lock read-only and acquire a shared lock, release it during execution, and verify the same host generation before starting an attempt and publishing a summary; if a change such as resume occurs, leave an incomplete attempt and refuse to produce a successful summary. offline creates no lock files or directories. Each actual invocation creates a new attempt without overwriting historical results; process interruption leaves an incomplete attempt, which is not treated as successful. The grading intent does not copy credentials or secrets_file. Results include the original run/config/catalog/plan/archive hashes, round, session/task/persona/Harness SHA, original user acceptance/validity, and grading status, without changing any user experience or acceptance. The CLI does not read --secrets-file; the summary does not include gold/test content from dataset rows.

### Task DAG and ownership

T1 complete predictions → T2 archive binding and official grading → T3 unified CLI and production verification; T4 tutorials and migration checklist proceed independently, with T3 ultimately verifying consistency of documentation/examples. Each Task's files are assigned in frontmatter; add the integration script `backend/scripts/e2e-spec-0075-post-run-grading.sh`. Key verification cases include complete patches exceeding 12000 characters, same-session conflicts, empty versus missing patches, incorrect task/round/SHA, corrupted/link-containing archives, dataset baseline mismatches, official failure/error/timeout, repeated grading invocations, unchanged original experiment bytes, and a shared read path for local/E2B-shaped archives. Offline tests use substitutes at the model/provider/official Docker boundaries. Real Docker verification is listed separately, and substitute reports are not called official scores.

## Drawbacks

Complete patches increase storage requirements; official images and fresh Docker grading require disk space, network access, and time. Historical Sessions containing only hashes cannot recover their predictions; the first version cannot migrate or repair old runs. Grading does not execute on E2B, so operators need a Docker-capable host. The first version grades sessions serially; batch users invoke the same command for each member themselves.

## Rationale and alternatives

Enabling objective evaluation directly inside the controller could reuse the old path, but would entangle grading with evolution isolation, runtime resources, and failure recovery; this option is rejected. Providing only a standalone hbench command would lack binding to the original run's session patches and could not determine whether a user trial technically passed. Reconstructing predictions from the current task repository or truncated output has no auditable provenance and is rejected. Using terminal archives and frozen materials decouples grading from the existing single-run lifecycle, preserving one user entry point and a separate research evaluation boundary.

## Prior art

The internal _SWEbenchRunner already wraps the official single-prediction CLI; standalone evaluation/harness_bench already supports held-out runs and is not replaced. Existing collect terminal inventory, Orchestrator logical binding/round seal, and Session immutable evidence can be reused; validity cannot be claimed solely from filenames or user acceptance.

## Unresolved questions

This work has no dependencies on unresolved choices. If live Docker/official images are unavailable, still complete reproducible offline integration verification and clearly state that live testing has not yet been performed; do not fabricate scores.

## Future possibilities

Future additions may include comparisons across attempts, batch grading scheduling, cross-version held-out suites, and an independent grading dashboard. Historical continuation, engineering CI, and seed input adaptation are designed separately; this group does not use grading to reopen old entry points.
