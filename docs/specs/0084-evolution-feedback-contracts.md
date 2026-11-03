---
number: "0084"
title: "Feedback, Execution Contracts, and Per-Round Acceptance for Autonomous and Interactive Evolution"
issue: 0
slug: evolution-feedback-contracts
summary: "Calibrate feedback across both modes, carry execution conditions throughout, correct the Seed baseline run boundary, and conduct independent acceptance before feedback in each round; retain cross-round error correction without adding a candidate elimination gate."
tasks:
  - id: T1
    title: "Canonical Feedback, Execution Contracts, and Missing-Measurement Read Models"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/models.py
      - backend/ahe_beta/execution_contract.py
      - backend/ahe_beta/user/session_store.py
      - backend/tests/web/test_api.py
      - backend/ahe_beta/web/api.py
      - backend/ahe_beta/loop/metrics.py
      - backend/ahe_beta/evaluation/acceptance.py
      - backend/tests/user/test_session_store.py
      - backend/tests/loop/test_metrics.py
      - backend/tests/evaluation/test_grading_contracts.py
      - backend/tests/test_experiment_grading_compatibility.py
      - backend/tests/test_execution_contract.py
      - frontend/src/types.ts
      - frontend/src/components/detail/SessionDetail.tsx
      - frontend/src/components/detail/SessionDetail.test.tsx
      - frontend/src/components/Charts.tsx
    scope: "Establish a single canonical feedback and execution contract, with nullable scores and their provenance carried through indexing, statistics, acceptance relationships, and the interface."
    acceptance: "The four axes do not substitute for one another; scores are strictly integers, and missing measurements are not filled with scores; old records are read-only; sessions with missing measurements remain available for evidence collection, and the frontend has no null references."
  - id: T2
    title: "Dual-Mode Review, Artifact Ownership, and Report Recovery"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/user/sim/loop.py
      - backend/ahe_beta/user/sim/feeling.py
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/persona_client.py
      - backend/ahe_beta/user/sim/clauses.py
      - backend/ahe_beta/user/sim/runtime.py
      - backend/tests/user/test_direct_session.py
      - backend/tests/loop/test_sim_user.py
      - backend/tests/user/sim/test_feeling.py
      - backend/tests/user/sim/test_loop.py
      - backend/tests/user/sim/test_prompt.py
      - backend/tests/user/sim/test_workspace.py
      - backend/tests/user/sim/test_feedback.py
      - backend/tests/user/sim/test_persona_client_agentic.py
      - backend/tests/user/sim/test_inner_prompt.py
      - backend/tests/user/sim/test_persona_usage.py
      - backend/tests/test_feedback_runtime_integrity.py
      - backend/tests/test_experiment_grading_artifact_lifecycle.py
      - backend/tests/user/test_prediction_artifacts.py
      - backend/ahe_beta/user/sim/tools.py
      - backend/ahe_beta/user/sim/sandbox.py
      - backend/ahe_beta/user/sim/sources/docker_seed.py
      - backend/tests/user/sim/test_docker_seed_source.py
    scope: "Preserve the interactive user's ability to verify according to persona, run tests, and write; share the scale and canonical feedback, freeze artifacts before read-only terminal-state review, and idempotently publish 0 to many issues according to the frozen report plan."
    acceptance: "Interactive judge/final-check can read, run, and write according to their capabilities and retain the user's contribution history; only the terminal-state Reviewer is prohibited from writing and using shell; successful runs may produce zero issues, and no conclusions are invented when attribution is unclear; recovery does not duplicate Actor/Reviewer or Issue, and grading bytes remain unchanged after freezing."
  - id: T3
    title: "Seed Request Contracts, Budgets, and Capacity Boundaries"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/harness/budget.py
      - backend/ahe_beta/harness/launcher.py
      - backend/ahe_beta/experiment/config.py
      - backend/ahe_beta/experiment/context.py
      - backend/ahe_beta/experiment/workload.py
      - backend/ahe_beta/experiment/model_limits.py
      - backend/ahe_beta/experiment/schemas/experiment-v2.json
      - backend/ahe_beta/experiment/schemas/task-package-v2.json
      - backend/harness_template/entry.py
      - backend/harness_template/agent.yaml
      - backend/harness_template/agents/main.md
      - backend/harness_template/META_SPEC.md
      - backend/ahe_beta/harness/INTERFACE.md
      - backend/tests/harness/test_seed_terminal_status.py
      - backend/tests/harness/test_seed_execution_contract.py
      - backend/tests/harness/test_launcher_budget.py
      - backend/tests/test_experiment_config_v2.py
      - backend/tests/test_experiment_workload.py
      - backend/tests/test_experiment_model_limits.py
      - backend/harness_template/.env.example
      - backend/harness_template/params.yaml
      - backend/tests/harness/test_launcher.py
      - backend/tests/harness/test_interface.py
      - backend/tests/harness/test_template_entry.py
    scope: "Freeze the total task budget and input availability, fix queue fields, task deadlines, and terminal-state decoding; unify static capacity validation and deterministic classification of limit overruns."
    acceptance: "7200 seconds with no hidden truncation to 1800; control does not renew leases; the grace period is not used to solve tasks; missing status is not success; capacity conflicts are rejected without breaking native asynchronous cancellation, and no new recovery policy is introduced."
  - id: T4
    title: "Preserve Trustworthy Usage Conditions Across the Requirements and Delivery Chain"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/evidence_contract.py
      - backend/ahe_beta/demand/session_timeline.py
      - backend/ahe_beta/demand/agent_runtime.py
      - backend/ahe_beta/demand/triage.py
      - backend/ahe_beta/demand/divergent.py
      - backend/ahe_beta/demand/architect.py
      - backend/ahe_beta/demand/grouped_architect.py
      - backend/ahe_beta/demand/owner.py
      - backend/ahe_beta/demand/proposal_view.py
      - backend/ahe_beta/demand/delivery_evidence.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/owner/systemprompt.md
      - backend/tests/demand/test_evidence_contract.py
      - backend/tests/demand/test_proposal_view.py
      - backend/tests/demand/test_triage.py
      - backend/tests/demand/test_divergent_gate.py
      - backend/tests/demand/test_owner.py
      - backend/tests/demand/test_grouped_architect.py
      - backend/tests/demand/test_delivery_evidence.py
    scope: "Use existing grants to associate execution contracts with safe acceptance summaries, carrying them through role projections, proposal aggregation, admission, and delivery publication without relying on model restatement."
    acceptance: "Trimming and merging do not lose input conditions; applicable scopes are retained for multiple sources; unclear attribution does not erase undelivered items; no hidden grader information leaks, and old and new readers do not silently mismatch."
  - id: T5
    title: "Per-Round Independent Acceptance and External Grading Endpoint"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/evaluation/service.py
      - backend/ahe_beta/evaluation/contracts.py
      - backend/ahe_beta/evaluation/adapters/custom.py
      - backend/ahe_beta/evaluation/adapters/swebench.py
      - backend/ahe_beta/evaluation/adapters/terminal_bench.py
      - backend/ahe_beta/evaluation/adapters/tua_bench.py
      - backend/ahe_beta/evaluation/adapters/nl2repo.py
      - backend/ahe_beta/evaluation/artifacts.py
      - backend/ahe_beta/experiment/assessment_worker.py
      - backend/ahe_beta/loop/round_assessment.py
      - backend/ahe_beta/experiment/grading.py
      - backend/ahe_beta/experiment/continuation/evidence.py
      - backend/ahe_beta/experiment/grading_inputs.py
      - backend/ahe_beta/experiment/materials.py
      - backend/ahe_beta/experiment/runtime.py
      - backend/ahe_beta/experiment/cli.py
      - backend/ahe_beta/experiment/controllers/unified.py
      - backend/ahe_beta/experiment/collection.py
      - backend/ahe_beta/experiment/manifest.py
      - backend/ahe_beta/experiment/backends/base.py
      - backend/ahe_beta/experiment/backends/local.py
      - backend/ahe_beta/experiment/backends/e2b.py
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/loop/feedback_pipeline.py
      - backend/ahe_beta/loop/recovery.py
      - backend/tests/test_experiment_round_grading.py
      - backend/tests/test_assessment_plan_preflight.py
      - backend/tests/test_experiment_continuation_evidence.py
      - backend/tests/test_unified_assessment_recovery.py
      - backend/tests/test_assessment_receipt_recovery.py
      - backend/tests/test_experiment_local_backend.py
      - backend/tests/test_experiment_assessment_worker.py
      - backend/tests/test_experiment_grading.py
      - backend/tests/test_experiment_grading_plan.py
      - backend/tests/loop/test_feedback_pipeline.py
      - backend/tests/loop/test_recovery.py
      - backend/tests/test_experiment_engine.py
      - backend/tests/test_experiment_lifecycle_v2.py
      - pyproject.toml
      - uv.lock
    scope: "Extract a shared grading service and add sealed session requests, trusted external workers, and per-round grading recovery; private plans do not enter the task side."
    acceptance: "local/E2B share requests; the final round is also subject to acceptance; failures do not eliminate candidates; a missing worker is shown as waiting and recovery is possible; online and post-hoc results match, old grade validation is not relaxed, and failures are not scored as 0."
  - id: T6
    title: "Joint Acceptance, Configuration Examples, and Bilingual Documentation"
    status: in-progress
    priority: P1
    tags: []
    depends-on:
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/scripts/e2e-spec-0084-evolution-feedback.sh
      - backend/scripts/check_observation_contract.py
      - backend/scripts/check_experiment_repository.py
      - backend/tests/test_evolution_feedback_e2e.py
      - backend/tests/test_experiment_public_examples.py
      - backend/tests/test_experiment_repository.py
      - release/compatibility.json
      - .github/workflows/ci.yml
      - examples/experiments/evolution-feedback-local.json
      - examples/experiments/evolution-feedback-e2b.json
      - docs/tutorials/evolution-feedback.md
      - docs/tutorials/evolution-feedback.zh-CN.md
      - docs/ARCHITECTURE.md
      - docs/specs/0048-user-sim-final-check-convergence.md
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - docs/QUICKSTART.md
      - docs/QUICKSTART.zh-CN.md
      - CLAUDE.md
      - backend/tests/fixtures/execution_evidence_contract.json
      - tools/dev/delivery/__init__.py
      - tools/dev/delivery/run_openagents_validation.py
      - backend/tests/test_run_openagents_validation.py
      - backend/ahe_beta/experiment/controllers/runtime.py
      - tools/dev/delivery/prepare_openagents_from_summary.py
      - tools/dev/delivery/prepare_openagents_validation.py
      - backend/tests/test_prepare_openagents_from_summary.py
      - backend/tests/test_prepare_openagents_validation.py
    scope: "Verify real readers, model boundaries, and grading canaries on both backends; document the supported scope, worker dependencies, historical read-only access, and research metrics."
    acceptance: "Retain separate evidence for offline contracts and real execution; real positive and negative controls, worker disconnection recovery, and Direct with zero follow-ups all pass; unsupported managed tasks are explicitly rejected; no Task may be marked done without real-world testing."
---

# 0084 · Feedback, Execution Contracts, and Per-Round Acceptance for Autonomous and Interactive Evolution

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a nine-section group-level rust-RFC overview. -->

## Summary

Correct the measurement and runtime prerequisites of evolution experiments so that the same Harness artifact can autonomously handle an explicit goal and accept subsequent user control. The changes consist of four areas:

| Area | Correction in this change | Acceptance result |
| --- | --- | --- |
| 1. Feedback measurement | Separate task assessment, experience, attribution, and improvement opportunities; share the same rating scale across both interaction modes; make terminal review read-only | A completed session without a rating is no longer automatically converted into a low or medium score; successful sessions may have zero Issues |
| 2. End-to-end execution contract | Pass follow-up input availability, goals, budget, and delivery prerequisites as trusted structured facts to all requirement and delivery roles | Direct recovery plans cannot depend on a nonexistent second user message |
| 3. Seed baseline boundaries | Consume structured budget and input conditions, distinguish the total task deadline from the message activity boundary, and add terminal-state decoding and model-capacity preflight checks | Do not infer budget from natural language, renew the lease because of control messages, or treat missing state as success |
| 4. Independent per-round acceptance | Freeze the actual Actor artifact, accept it through the existing scoring adapter before requirement generation, and verify experiment-material consistency | Each round provides a verifiable task result; infrastructure failures and unaccepted results are not recorded as task failures |

Retain the workflow of “user trial → feedback → requirements and delivery → correction in the next round.” A task that does not pass may still enter subsequent rounds for discovery and repair. This group does not add candidate elimination, automatic rollback, or pre-release capability gates; does not patch the final evolved artifact specifically for evaluation; and does not preimplement complete automatic continuation, context compression, or watchdog strategies.

The design baseline is AHE-Beta `5cccb3642c04bf278ae44e5dba9691dfb68ddf11`. This document and the accompanying OpenAgents contract design have been reviewed and approved. Implementation status is updated according to task acceptance records; only development acceptance canaries are run, and archived or paused large-scale experiments are not restarted.

## Motivation

In a six-round all-Direct experiment with 48 sessions, 42 had a feeling of 1, and 31 were marked accept by reviewers, including 26 that were both accepted and scored 1. Formal objective task acceptance was zero. These results are insufficient to establish actual task success rates: Direct prompt examples fixed `score:1`, while accept mixed “the task was completed” with “there was no need to attribute this to a Harness bug.” Some sessions acknowledged that nothing had been delivered but were accepted on the grounds of “honestly reporting failure and handling it after the user’s next message.”

The new main can still locate the following problems, rather than relying only on historical experiments:

- `loop/sim_user.py::make_direct_run_session_fn` contains fixed scoring examples, a fallback to 3 when scoring is missing, unconditional creation of a bug Issue, and final artifact collection only after the Reviewer has used the workspace.
- `user/sim/loop.py` constructs a score of 2 or a derived score when evaluation is invalid; the adapter also writes the derived score into the official feeling. Missing measurement is not a rating.
- `demand/evidence_contract.py::build_l1_summary` does not fix execution prerequisites such as follow-up input availability; the body of `proposal_view.py` is truncated, and attribute labels cannot carry the contract either.
- The Launcher has already sent `budget_seconds`. The Seed queue stores only text/queued; the Launcher resets the timer for new messages and control messages, and may still treat missing status as completed when reading a task reply.
- The public experiment schema fixes `evaluation.official_grading` to false. Existing post hoc scoring must wait for the experiment terminal state and complete archive and cannot be called directly during execution. Its adapter depends on Docker, while the E2B controller does not have equivalent execution capability.

Prompt-file loading, NexAU provider SDK compatibility, Seed completion-tool detection, source SHA binding, Direct execution evidence, triage submission, and recovery have already been fixed in the baseline. This group preserves their regressions and does not rewrite them. Observations of early stopping after evolution can support analysis of specific control paths, but cannot directly derive overall causality across different Seeds, model backends, and resource conditions.

The central problem is that the faulty design did not receive a stable and faithful correction signal. Engineering tests can show that code conforms to a Spec, but if the Spec has already treated “wait for the user to continue” as the recovery method for an unattended task, local implementation correctness cannot prove completion of the original task. Therefore, fix the research instrumentation and contract first, then observe whether later rounds naturally correct the strategy.

## Guide-level explanation

### Usage and result interpretation

Operators still prepare and start experiments through `backend/scripts/experiment.py`. The task package declares the public goal, deliverables, and execution budget; the interaction plan selects direct or simulated_user; and the private grading plan is supplied independently and cannot be placed in the task directory or sent to roles.

Add the following configuration fragment. Existing configurations that do not declare per-round acceptance remain explicitly marked as having acceptance unconfigured; no default success rate is added:

```json
{
  "evaluation": {
    "session_grading": {
      "plan_sha256": "<64-character digest>",
      "worker_key_sha256": "<digest of the grading worker's Ed25519 verification public key>",
      "runner": "external"
    }
  }
}
```

When per-round acceptance is enabled, `check/prepare` receives `--grading-plan /private/plan.json` and `--grading-worker-public-key /path/worker.pub`, freezes the plan and signing identity, and checks coverage, artifacts, and execution capability for each task. Existing `official_grading:false` configurations retain their original identity; the old and new shapes are mutually exclusive, and no second scoring semantics is introduced. The complete private plan is stored only at the trusted scoring endpoint. The controller knows only the digest, coverage, and security contract; the public key is not secret.

The trusted scoring machine runs the following proposed command:

```bash
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/experiment.py assessment-worker RUN_ID \
  --plan /private/plan.json --signing-key /private/worker.key --follow
```

This command only claims sealed scoring requests, calls the existing adapter, and returns a safe receipt. It does not start or rerun the Harness and does not take on responsibilities of a new experiment scheduler. Local and E2B use the same request format; the scoring machine requires Docker, and E2B does not run nested Docker. The scoring process may be deployed on the operator’s long-running server. If it runs only on a personal computer, shutting down that computer pauses the scoring endpoint; the experiment will show that acceptance is pending and cannot claim to proceed end to end independently of that machine.

Each round first ends the Actor and seals the artifacts; the Reviewer can read only the snapshot. Independent scoring then completes, and the safe summary enters the requirements phase. The final round performs collection, review, and acceptance even if no further delivery occurs. Official results do not backfill or modify the original Session.

Results are displayed by axis:

- User task assessment: fulfilled, unfulfilled, or unknown, with the assessment source and supporting evidence.
- Experience: a valid self-rating from 1–4 or the reason for missing data; 1=bad, 2=poor, 3=ok, 4=good. Derived scores are listed separately and cannot replace the self-rating.
- Component attribution: claims with evidence levels and uncertainty; they do not automatically equal confirmed bugs.
- Improvement opportunities: zero or more suggestions, capability gaps, or issues requiring investigation.
- Independent acceptance: the status, raw metric, passed value, and execution contract from the scoring service. It is parallel to the user assessment and is not filled in by the Reviewer.

For example, after an API stalls, “honestly exits without delivery” may have a task assessment of unfulfilled, receive a positive experience assessment for honesty, leave the root cause uncertain, and produce an exploration opportunity for recovery capability. Honesty cannot make the task completed, and task failure cannot establish a confirmed Harness code defect.

### Retaining the shared core of autonomy and interaction

The Harness receives only general runtime facts, such as “follow-up user input is unavailable for this task” and “7200 seconds of budget remain.” It does not receive the benchmark name, scoring answer, round number, or experiment-group name. When a user is present, subsequent messages are control or supplementary information; when no user is present, the Harness cannot assume that it will receive a continuation instruction. Missing required authorization, missing critical facts, unrecoverable errors, or exhaustion of the total budget may still cause an honest termination; perpetual execution is not required.

This group corrects the contract and measurement; it does not promise to increase the task score of arbitrary models. Direct is not given a user who helps solve the task, and no particular automatic recovery algorithm is mandated.

## Reference-level explanation

### 1. Single source of feedback truth and missing data

In `models.py` define a versioned normalized `Session.feedback`. Do not add multiple competing accept/result/pass concepts. Its four components are `task_assessment`, `experience`, `attribution`, and `opportunities`. Each component carries its source, evidence references, and validity; the user task assessment does not have official acceptance authority.

`experience` distinguishes the states rated, missing, invalid, and unavailable. score is strictly an integer from 1–4 or null; booleans, float truncation, and numeric strings are rejected. Direct and simulated interaction reuse the same scale and validation function. Protocol failures, model-call failures, and missing fields preserve their actual causes and cannot default to 1, 2, or 3. Behavior-derived feeling may remain in a separate derived diagnostic but does not enter the self-rating average.

`Session.feeling` becomes a nullable display projection generated consistently from the new feedback. Old records are interpreted read-only using only their existing fields and are not rewritten during loading. SessionStore indexes, rebuilding, Metrics, requirement trends, controller live metadata, and frontend types and details all support missing data. Statistics provide both the valid-sample count and missing-data count, grouped by interaction condition; one average is not used to cancel out degradation in another capability.

Formal acceptance continues to use the existing scoring result model and independent receipt. Acceptance relationships are derived by reading the explicit task acceptance assessment; new records no longer treat Direct’s “no need to file a bug” as user confirmation of completion. Old ambiguous accepts identify their old source and unverified status; historical success is not backfilled. Reviewer-service failure alone must not prevent trusted Actor artifacts from receiving objective scoring; if the execution protocol or artifacts themselves are untrusted, scoring is still rejected separately.

### 2. Freezing Actor output, read-only review, and report publication

The session order is fixed as follows:

```text
Actor ends → Stop and confirm no further writes → finalize → Freeze the complete patch/declared artifacts and hash
          → Read-only terminal review → Save Session and the report publication plan → Publish 0..n reports idempotently
```

Both runners reuse the existing artifact collector instead of duplicating collection logic in Direct. The bytes used for acceptance must come from the sealed state at Actor termination; the Reviewer cannot re-export a patch after review and count its own modifications as delivery.

Register a terminal review phase explicitly for Direct. In simulated interaction, `main_final_check` occurs before the user decides whether to accept or continue and belongs to the simulated user while it is still using tools: retain the live workspace and persona tool capabilities, and do not close the Actor early. The ordinary main/waiting judge also exposes capabilities according to D1. competent/expert may write tests, run commands, or modify code according to a collaborative or takeover tendency; whether these actions are taken is determined by the persona, and every user is not forced to complete the task personally. Private tools are unavailable at startup; intent/rejudge/reintent/act remain tool-free; final-check still permits at most once per cycle and at most four tool calls, and does not publish a report during that check.

Only after the session truly ends are the Actor and write processes stopped and the collaborative workspace artifacts frozen. The terminal Reviewer receives only snapshot read/list/diff access; write_file, arbitrary shell, the live workspace, and private scoring materials are not exposed. The independent grader performs the official tests. The interactive user and terminal Reviewer do not share permission policies; if the terminal phase needs unrestricted execution for checks, an isolated copy must be designed separately. User tests, commands, writes, supplementary information, and authorization during interaction are stored in sim_trace. Frozen artifacts may contain user contributions; independent acceptance measures this final task artifact and does not automatically equal the Harness’s independent-solving score. Existing traces provide operational evidence but do not claim complete file-by-file or line-by-line contribution attribution.

The user-model client’s explicit non-closure of the reasoning path for GLM also recognizes provider/model, glm-5.3, and glm53 deployment names, while sending the actual model ID unchanged. When reasoning_effort is not configured, retain the server default; do not reinject enable_thinking=false because of a deployment alias. This naming compatibility does not infer context capacity or change the 32768 output budget.

Direct no longer creates bugs unconditionally. When success is reliable and there are no problems, there are zero tickets; non-blocking suggestions are phrased as features/suggestions; when a task fails and attribution is unknown, a diagnostic or general capability-opportunity report may be created, with the body clearly stating that it is not a confirmed root cause. Triage still investigates autonomously and does not automatically convert objective failure into an approved requirement. Successful samples remain evidence for later capability comparison; no second task-pool manager is created for this purpose.

Before calling the tracker, persist the determined publication plan, including a stable operation key and complete IssueDraft, or an immutable payload reference and hash; saving only a body summary is insufficient for recovery. Persist per-ticket publication progress in an independent receipt. Only after all publications complete may issue_refs be appended once according to existing SessionStore rules; the Session is not rewritten per ticket. Recovery retries only incomplete publications and does not call the Actor or Reviewer again or regenerate the body. A zero-report plan is also explicitly completed. Continue using `create_issue_once` and permitted handoff enrichment; do not relax Session immutability to backfill scores.

### 3. Trusted execution contracts and role propagation

Define the contract and its safe projection in a pure data module `execution_contract.py`. Experiment configuration, Launcher, Session, and the requirements surface reuse it; the module does not depend on the provider, model client, or grader. The stable portion includes at least:

| Field | Source and purpose |
| --- | --- |
| task_id / task_digest / contract_id | Identity of the frozen task and usage conditions; not generated by the model |
| original_goal_ref / public_deliverables / public_acceptance | Public goal and delivery prerequisites; retain readable references without mixing in hidden tests |
| followup_input | unavailable, possible, or unknown; possible cannot be treated as a guaranteed reply |
| task_budget_seconds / budget_source | Total activity budget and its source, distinguishing official metadata from the operator’s experimental quota |
| user_assistance | References to assistance that actually occurred, including control, authorization, facts, preferences, and solution contributions; do not invent assistance from guesses |
| runtime_facts_ref | References to actual task/message identity, deadlines, durations, and terminal receipts |

The contract itself contains only declarations frozen before startup. Assistance that has already occurred and runtime_facts are associated through Session execution receipts; they do not write back to the contract or change its identity.

Session may separately store the experimental interaction mode as an analysis label, but the runtime context sent to the Harness contains only facts such as general input availability and the public goal. It neither injects benchmark characteristics nor modifies the original task body to avoid parsing problems.

Retain the contract as the fixed L1 section; ordinary event trimming cannot delete it. Direct’s goal summary is built from the actual SeedScenario and execution receipts; it does not fabricate a SimTrace or simulated-user goal ledger. When the original goal is too long, use a hashed reference and bounded summary so that a large contract does not exceed the existing evidence-access boundary.

Triage’s original report, normalized proposal, PM `evidence_sessions`, Architect `source_proposals/covers`, Owner merge, and admission continue to obtain their sources through the existing trusted-grant union. The framework generates an independent machine contract section and bounded summary; the model does not handwrite sources or reparse them from the end of the body. `ProposalView` places the contract in an independent field, unaffected by the 3000-character body truncation or direct-label filtering. Mixed sources retain the conditions applicable to each source and cannot be summarized as “the user can continue.”

Roles continue to have distinct responsibilities: PM reads user-level goals, experience, and usage conditions; Triage/Owner and others read objective evidence according to their existing authorization. Exposing execution prerequisites to all roles does not open all verification logs. Safe scoring summaries are provided through an explicit evidence channel; specific hidden assertions, expected output, reference answers, and raw verifier logs do not enter the requirements model.

Proposals and Specs may change existing stopping strategies, but cannot place the original goal, user-cancellation semantics, or unattended-input conditions in non-goals and then claim that they are solved. Conforming to the old Spec only shows implementation consistency; it does not automatically eliminate an ongoing delivery capability gap. It is permissible to reject an unsupported attribution while retaining task_assessment and real acceptance facts for subsequent analysis.

Delivery evidence publication reuses the existing gzip/ZIP, hash, and authorized bundle, adding only versioned safety contract blocks and result references. The corresponding OpenAgents reader must verify provenance and version, and provide bounded conditions directly in the actual contexts of the Spec Writer, Architect, Implementer, and Reviewer, rather than providing only attachment paths. Its separate design resides in the OpenAgents repository; cross-repository joint acceptance for this group must not be marked complete until that reader is available. `release/compatibility.json`, preflight capabilities, and the pinned reader SHA must be updated together; a new publisher must not silently lose fields when paired with an old reader.

The shared wire contract between the two repositories is the `execution_evidence` object in the existing observation bundle, with required fields `schema_version:1`, `issue`, `execution_contracts`, `assessment_summaries`, and `payload_sha256`. The contract requires `contract_id`, `session_id`, `task_id`, `task_digest`, `followup_input`, `task_budget_seconds` (nullable), `budget_source`, and `public_refs`; each public reference consists of kind/path/sha256. The summary requires `receipt_id`, `session_id`, `contract_id`, `status`, `passed`, nullable score/metric definitions, acceptance type, and a provenance summary. Arrays may be empty, but when required is enabled they must cover all authorized sources for the issue; empty arrays cannot be used to bypass this requirement.

The payload digest is computed over the object after removing `payload_sha256`: UTF-8, `ensure_ascii=false`, sorted keys, no extraneous whitespace, and rejection of non-finite numbers; contract arrays are sorted by stable ID. contract_id is the digest of the declared content excluding contract_id, computed using the same normalization rules. Actual execution facts are attached separately and do not redefine the original contract. References to public objectives, artifacts, and runtime facts must all be relative path + SHA256 within the authorized bundle; host absolute paths and private evaluation paths are prohibited. Private scoring provides only opaque receipt IDs and allowlisted summaries; the reader does not retrieve private logs. Each repository maintains the same protocol fixture, and joint checks verify their consistency.

The required expectation must also be carried into trusted dispatch through the project delivery configuration negotiated during preparation; it cannot exist only in an attachment or Issue marker that can be deleted. A task declared required must fail if the marker/attachment is missing; only an ordinary Issue without that negotiated declaration may be treated as having no contract. Implementation must use OpenAgents' pinned configuration/dispatch seam and must not determine the trust level from historical trajectory content.

### 4. Seed, Launcher, and Budget Consistency

Continue using `harness/budget.py`, adding explicit task-wide deadline and message activity boundaries without creating a parallel timer. The task clock starts when the first objective is delivered after the environment is ready and advances in wall-clock time; queued, control, heartbeat, and subsequent messages for the same task cannot renew the total deadline. The available activity budget for each message cannot exceed the task's remaining time. Explicit budget changes must pass the current operator authorization policy and leave a receipt; the appearance of wait in text does not automatically extend the deadline.

Task package schema 2 may provide structured `execution`: budget source, duration in seconds, and public delivery prerequisites; the existing runtime budget serves as the operator fallback, and precedence and the actual selected value are recorded in the frozen contract. If the structured official deadline differs from the operator quota, it must be explicitly labeled a quota experiment and must not be presented as the official budget. Perform consistency preflight checks on instruction deadlines for known task packages: report conflicts before invoking the model and require changes to the materials or an explicitly registered override; do not silently rewrite task text or automatically determine runtime deadlines using natural-language regexes. CPU, memory, task concurrency, and environment identity for shared computing resources are also frozen; do not call directory isolation resource isolation.

The public fields are fixed as `execution.budget_seconds`, `budget_source` (task_metadata/operator_quota), and optional `quota_override_reason`. Prefer the task budget; use `runtime.harness.request_budget_seconds` only when none is declared. The message activity limit for the same request is separately constrained by optional `runtime.harness.message_activity_seconds`. Validate deadlines for known sources against their pinned metadata; arbitrary free text cannot automatically prove consistency and is recorded as instruction_budget_unverified. Common explicit deadline conflicts may be reported as lint errors but are not budget sources. The model capacity fields are `models.<role>.limits.context_window_tokens`, `reserved_output_tokens`, and `input_headroom_tokens`, plus optional `max_context_tokens` (effective input threshold, default remains 256000 and may be explicitly lowered); these are declared values and static-check inputs, not actual token counts assumed to be subject to hard enforcement.

Protocol messages retain stable task/message IDs, input conditions, the task deadline, and the remaining budget. Seed's message queue stores and consumes these structured fields. Cross-host wall timestamps are for audit only; Runner is the deadline authority, and Seed anchors a local monotonic deadline to the remaining time upon enqueue. Subsequent frames for the same task may only use `min(existing_deadline, now + remaining)`. Dequeueing, reconnecting, and repackaging messages cannot refund or reallocate the full budget; missing fields or unknown identities must not silently start a new task or fall back to 1800 seconds. Connection latency does not extend Runner's authoritative deadline.

The infrastructure hard-stop deadline is the task deadline plus an independent termination grace period; the grace period is only for cancellation, terminal-state explanation, and recordkeeping, and cannot be used to start new problem-solving calls. A 7200-second task's deadline is not overridden by the internal 1800/1860 fallback. Human interaction without an explicit contract retains explicit unknown/undeclared semantics without guessing the total budget; new research experiments freeze the complete contract at prepare time.

Change the Seed main prompt and META_SPEC to “Proceed autonomously after receiving an explicit objective; user input is an optional control channel”; do not preset specific watchdog thresholds or automatic recovery implementations. Finite iterations, output truncation, and missing necessary information may still produce incomplete; it is a task outcome to improve, not proof of completion. Retain the existing `max_iterations=100` and `max_tokens=32768`; this group does not promise two hours of continuous computation merely because a task has 7200 seconds.

Public task replies must have a valid status and termination_reason and be associated with an identity; Launcher no longer defaults a missing status to completed. Internal slash commands use explicit builtin_command/confirmation semantics, confirming only that command without ending the active task or clearing its deadline. Replies with mismatched task/message IDs cannot be consumed by the current task. The raw reason enters the request outcome, and platform hard stops and normal Harness replies retain distinct sources. Continue using the corrected completion-tool hook and cancellation path.

Add declarable total context capacity, reserved output, and input headroom to direct model configurations for user/harness/demand, while retaining the existing output defaults. Preflight checks that the effective input threshold + reserved output + headroom do not exceed total capacity only when an explicit capacity is available; unknown capacity is marked unverified and cannot be inferred from the model name. For example, when capacity is 262144, 256000+32768 must be rejected; that combination cannot be recorded as having passed verification.

The pinned NexAU context counting and limit enforcement cannot currently provide reliable dynamic hard guarantees: some hooks swallow exceptions, the default token counter is an estimate, and model wrapping may also change native asynchronous cancellation. Therefore, this group will not fork NexAU or introduce this wrapper, and does not promise dynamic compression. Only correct the configuration statically, and record identifiable deterministic context overflow as incomplete, preventing Seed from appending another full Agent.run of the same scale. NexAU internal HTTP retries and outer attempts are recorded separately; do not claim that only one actual HTTP request occurred.

### 5. Per-Round Acceptance Service and Trusted Executor

Add `evaluation/service.py` to extract the common logic for building/validating `GradingRequest`, invoking registered adapters, and normalizing results. The post-hoc `experiment/grading.py` retains its checks for “terminal run, complete archive, generation, seal, hash”; do not relax these requirements for the online path. Online scoring reads only a different, explicitly sealed session artifact bundle and verifies the same level of task, session, provenance, and byte identity; do not pass a boolean switch that skips validation.

Add `loop/round_assessment.py` for controller-side recovery units and `experiment/assessment_worker.py` for claiming and execution on trusted scoring machines; the provider adds only ownership-constrained request/artifact download and receipt upload capabilities. These components contain no scoring rules, do not schedule new Actors, and are not responsible for delivery. External workers can be reused in local and E2B scenarios; task outputs and management directories must not expose private plans. The worker uses the existing Docker adapter; do not mount the Docker socket or private grader in the E2B user environment.

```text
users (including frozen artifacts and subjective review)
  → objective_grading (request → external worker → verify result receipt)
  → Safe feedback projection
  → triage ∥ PM → architect → owner → delivery → next round
```

The recovery operation identity binds at least run, round, slot/session, the actual trial user_sha, task_digest, artifact_digest, plan_digest, adapter version, and scoring implementation digest. Persist the result and hash before completing the unit; repeated claims reuse the verified result, do not rerun the Actor, do not modify old Sessions, and do not replace the trial SHA with the post-delivery sealed_sha.

Scoring requests use a versioned JSON envelope that always contains the above identity, controller generation/nonce, request_digest, and artifact manifest; request directories must not carry arbitrary shell commands. Workers claim atomically, establishing a monotonically increasing claim_epoch, worker_nonce, and lease. Every submission is bound to request_digest, the current claim_epoch, worker_nonce, the private raw result digest, and safe_summary_digest; the controller accepts a valid claim for the current generation only once. Old workers, expired epochs, duplicate submissions with different results, and incorrect provenance cannot overwrite an accepted receipt or feedback projection.

Worker identity is verified using the signature-verification public key registered at prepare time; the private key remains only on the trusted scoring machine. The worker signs the result envelope; a content hash or random nonce cannot serve as identity authentication. Transport continues to use the provider's ownership verification and management channel; do not create a new public HTTP scoring server. Isolation of managed control state still follows the current backend boundary; do not portray workspace directory isolation as a security sandbox against malicious code. New scoring rules must use a separate attempt and cannot be substituted through resume.

When acceptance is enabled in the configuration, prepare verifies private plan coverage and backend capabilities, and verifies the worker's usable identity, plan digest, and execution capability before the formal user run. If the worker is interrupted or transport status is unknown, show assessment_pending and prevent progression to dependent stages under the pretense that scoring is available; recovery resumes scoring only and does not rerun the session. The operator may terminate the experiment or record this assessment as unavailable after an explicit audit; do not silently convert it to 0. This is a measurement completeness constraint, not a reason to reject a version because its task score is low.

Waiting for acceptance is a phase fact within the existing running experiment: keep experiment_state=RUNNING, phase=objective_grading, and separately set assessment_state=PENDING; do not create a separate experiment top-level state machine just to wait for scoring.

Valid result semantics reuse the existing adapter: a technical conclusion is available only when completed and the verification contract is valid; false is a real failure and still proceeds to subsequent rounds; unsupported, missing_artifact, ungradable, unavailable, crashed, and timed_out retain passed=null. Only tasks with continuous metrics retain the original score; do not invent passed when no binary rule is defined. When per-round acceptance is not configured, explicitly record not_configured; do not rename Reviewer judgments as an official pass rate.

Private scoring results remain on the trusted scoring side and in private evaluation storage, and do not enter public archives, readable source snapshots, model Prompts, or Issue attachments. The controller receives only allowlisted summaries with verifiable provenance and opaque references. The result summaries themselves do not reveal specific hidden assertions or correct answers. Freeze the round's projection digest before the first feedback consumption; scoring added afterward remains a separate record and does not silently change the evidence the roles saw at the time.

The initial batch of real acceptance is limited to existing verified adapters/profiles and artifacts that can be fully sealed. Mechanism tasks use explicit custom verifiers and are not represented as official. Tasks dependent on the original environment or managed KV measurement may be enabled only when the existing environment and trusted collection contracts are satisfied; prepare rejects tasks for which capabilities are currently missing, and this cannot be used to declare the complete N8 E2B path finished. The independent Harness→Harbor research evaluation entry point remains unchanged; this group does not duplicate its task reruns, resource scheduling, or manifest.

### 6. Task DAG, File Ownership, and Verification

Implementation scheduling refinement: T2's read-only review/report recovery and T5's pure scoring service/worker can be developed in parallel after T1; their Runner integration and overall acceptance still await T3's budget interface, and T6 verifies the complete chain.

| Task | Responsibilities | Primary dependencies |
| --- | --- | --- |
| T1 | Normalize feedback, execution contract pure data, missing-measurement storage/statistics/UI, and acceptance relationships | None |
| T2 | Dual-mode sessions, freeze before read-only review, 0..n reports, and idempotent recovery | T1, T3 |
| T3 | Seed/Launcher, public configuration, task budget and model capacity preflight | T1 |
| T4 | Demand role, proposals, authorized evidence, and delivery contract propagation | T1, T2, T3 |
| T5 | Shared scoring service, external workers, per-round recovery, and private material lifecycle | T1, T2, T3 |
| T6 | Cross-repository contract and real-backend acceptance, documentation, and migration boundaries | T4, T5 |

Precise file ownership is specified in the frontmatter, with no overlap within the group. OpenAgents reader/context/role checks are assigned in its own repository; do not list external source files as files in this repository. T6 is joint interface acceptance; a publisher-only fixture cannot substitute for a real reader.

The end-to-end script is `backend/scripts/e2e-spec-0084-evolution-feedback.sh`, supporting offline deterministic contract tests and explicitly enabled real local/E2B paths. Acceptance must cover at least:

1. Normal delivery produces zero Issues; suggestions and failures with unknown attribution are reported separately; missing, boolean, string, and invalid ratings do not produce scores; the frontend does not dereference null.
2. Reviewer write access and shell tools are unavailable, and the bytes/hash used for scoring are identical before and after review; valid Actor deliverables can still pass acceptance when the Reviewer API fails.
3. Direct receives no second user message from the initial message through the final protocol response; interaction controls remain available; the contract retains the condition that input is unavailable after passing through triage, PM, architect, merge admission, and actual OpenAgents role contexts.
4. Architecture/code review flags unattended recovery acceptance that says “stop and ask the user to continue”; “conforms to the old Spec” must not be treated as evidence of completion. Tests do not supply hidden answers to evaluation tasks.
5. Use an injected clock to verify 7200 seconds, queuing, controls, budget expiration, and a separate wrap-up allowance; do not actually spend two hours. A missing terminal state does not count as success, and built-in commands are not misclassified.
6. Static capacity conflicts are rejected, unknown capacity is represented accurately, and deterministic limit violations do not append another outer attempt of the same size; preserve native asynchronous cancellation and regression coverage for actual SDK construction.
7. The same frozen artifact yields identical adapter results through online and post-hoc services; actual positive/negative controls, continuous scores, missing artifacts, and verifier failures are classified separately; test control materials are not misrepresented as successful Harness samples.
8. Interrupt and recover separately when the Actor has completed, the report is pending publication, the scoring result has been written but the ledger is incomplete, the worker disconnects, and an item is claimed repeatedly; do not repeat the Actor/Reviewer, completed scoring, or Issue publication.
9. Acceptance still applies when the final round is trial-only; low scores do not trigger candidate elimination; old archive bytes, Session hash, and recovery identity remain unchanged; private materials do not appear in role inputs or public archives.

For actual acceptance, first run a minimal local custom/SWE or file task and an E2B+external grader canary, retaining actual receipts. Only then freeze a small paired pilot with the same Seed, SDK, model service, budget, and task resources: report technical results, experience, missing measurements, and user assistance separately for all-Direct and Mixed. A new large-scale six-round experiment requires a separate operator launch; this group does not automatically rerun historical experiments or treat changes on one or two questions as proven generalized improvement.

## Drawbacks

Nullable scores affect storage, trends, roles, and the frontend; changing the Prompt alone is insufficient for delivery. Freezing artifacts before review reduces the Reviewer's freedom to inspect, requiring an independent grader to provide technical acceptance instead of letting the Reviewer fix the task.

Per-round scoring increases runtime cost and duration and requires a long-lived trusted execution endpoint; E2B experiments cannot rely solely on a controller without Docker to be self-sufficient. This dependency must be explicitly deployed and monitored, not disguised as a free capability. The supported scope remains limited while complete environment contracts, such as KV, are unavailable.

Contracts and result summaries consume additional role context; they should be bounded, deduplicated by source, and retain citations. More accurate measurement does not guarantee that the model will immediately learn better recovery mechanisms, and early results may include more honestly recorded failures.

## Rationale and alternatives

Adopt “one feedback source of truth, one execution contract, the existing adapter service, and one narrow scoring worker”. Data, sessions, Seed, requirements and delivery, and scoring execution each have a single place of maintenance; no second user loop, benchmark framework, or experiment scheduler is introduced.

The first alternative is to add “do not stop early” to the Direct Prompt only. It cannot fix missing scores, lost budgets, forced issue creation for successes, reviewers modifying artifacts, or lost delivery conditions, so it is not adopted.

The second alternative is to automatically send “continue” whenever the Harness exits early, or add a problem-solving user to Direct. This changes the measurement of autonomous capability and artifact behavior and could count user debugging contributions as Harness improvements, so it is not adopted.

The third alternative is to require every delivery to pass all capability questions or else reject the merge or roll back. This design retains the experiment design that allows later rounds to correct errors and does not mix that into the same variable; independent acceptance provides feedback but is not a candidate elimination gate.

The fourth alternative is to mount a Docker socket, scoring plan, or reference answers inside E2B, or reimplement the official tests for online scoring. This would expand the materials visible to the task and create two sets of scoring rules, so an external trusted grader and shared adapter are used.

The fifth alternative is to immediately implement a complete environment broker, a general plugin platform, dynamic hard token management, and automatic recovery. These are not necessary prerequisites for fixing measurement and contracts; this group only declares capabilities and rejects unsupported paths, leaving each to evolve later in response to actual feedback.

## Prior art

This repository already has a user-goal ledger, layered user/objective evidence, read-only SHA source snapshots, immutable Sessions, idempotent Issue publication, RecoveryStore, public artifact declarations, and independent scoring adapters, all of which can be reused directly. Existing post-hoc scoring and independent Harness research evaluations respectively handle “acceptance of sessions that have occurred” and “rerunning a specified Harness on new tasks”; this group retains that distinction.

The accompanying OpenAgents already injects observation context through a unified runtime engine and can continue to be extended with a narrow safety contract; it is not required to understand experiment groups, private grading plans, or benchmark-specific rules.

## Unresolved questions

The proposal has been reviewed and approved and will be implemented within the boundaries of this document. The external grader is an explicit dependency, the Reviewer is read-only, the total task budget is separate from the message activity budget, and cross-round error correction is retained. The accompanying reader has been pushed as an immutable review candidate and compatibility has been backfilled; formal release still requires joint review and merge. Early unpublished local snapshots are used only for development acceptance and do not serve as release pins.

## Future possibilities

Observe new evolution under faithful feedback and contracts, then separately evaluate automatic recovery, context compression, independent task sandboxes, paired parent-version rechecks, or candidate selection mechanisms. Success/failure samples can be used for stratified capability trends, but research questions already incorporated into feedback must no longer be called unseen tests.

Other execution backends may be added to the trusted scoring service in the future; they should implement the same scoring service contract, without requiring a new runner for every new benchmark or changes to the user session loop.
