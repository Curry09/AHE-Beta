---
number: "0082"
title: "Consistency of feedback source code, direct evidence, and timeout boundaries"
issue: 0
slug: feedback-runtime-integrity
summary: "Bind requirement source code to the trial SHA, retain records of actual direct execution, leave finalization headroom within internal budgets, and use bounded retries for triage without a commit."
tasks:
- id: T1
  title: "Requirement role gathers evidence from the trial source snapshot"
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/demand/source.py
  - backend/ahe_beta/demand/agent_runtime.py
  - backend/ahe_beta/demand/evidence_contract.py
  - backend/ahe_beta/loop/feedback_pipeline.py
  - backend/ahe_beta/loop/orchestrator.py
  - backend/ahe_beta/experiment/controllers/feedback.py
  - backend/agent_defs/triage_agent/agent.yaml
  - backend/agent_defs/architect/agent.yaml
  - backend/agent_defs/divergent_pm/agent.yaml
  scope: "Read-only commit export, propagated across threads; historical reports bound to source SHA."
  acceptance: "Leave the seed worktree unchanged; the role reads the full SHA; no fallback when the commit is missing."
- id: T2
  title: "Separate product budgets from infrastructure deadlines"
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/harness/budget.py
  - backend/ahe_beta/harness/launcher.py
  - backend/ahe_beta/experiment/context.py
  - backend/ahe_beta/experiment/schemas/experiment-v2.json
  - backend/tests/test_experiment_local_backend.py
  scope: "Schema 2 freezes the budget and wrap-up allowance, with both backends sharing the same propagation path."
  acceptance: "A wrap-up reply can be returned within the allowance; the source of a hard stop can be inspected; legacy configuration identities remain unchanged."
- id: T3
  title: "Save the execution record actually received by direct."
  status: done
  priority: P1
  tags: []
  depends-on:
  - T2
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/loop/sim_user.py
  - backend/ahe_beta/demand/session_timeline.py
  - backend/tests/user/test_direct_session.py
  scope: "Save all received progress and reply steps in the existing sim_user adapter, and consistently project timeline/beat/step at query time."
  acceptance: "Persist received steps in full for both direct and simulated interactions, without losing long bodies or intermediate indices; share query summary/expansion limits; do not fabricate SimTrace or intermediate user reviews; preserve authorization boundaries."
- id: T4
  title: "Bounded triage finalization and full acceptance verification"
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
  - backend/ahe_beta/demand/triage.py
  - backend/tests/test_feedback_runtime_integrity.py
  - backend/tests/test_experiment_config_v2.py
  - backend/tests/test_experiment_engine.py
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  scope: "Add one eight-iteration call when a call returns normally without a submission, along with documentation and independent verification."
  acceptance: "At most two calls; still fail if no submission is made; verify with real local processes and independent E2B execution; do not rewrite old experiments."
---

# 0082 · Consistency of feedback source code, direct evidence, and timeout boundaries

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

Bind the requirements role's source view to the full commit SHA actually tried by the user; reserve separate infrastructure finalization grace time for the product's internal request budget; save received progress, reply steps, and termination sources for direct requests. When triage returns normally without a structured submission, allow only one bounded finalization call while retaining the failure gate.

## Motivation

The N8 all-direct control run exited during triage in the second round: the first call exhausted its iterations without submitting a disposition, and the recovery gate blocked further delivery. During recovery, we found that the requirements role was reading the seed working tree while the user had already tried a later commit; even if a subsequent submission succeeded, its source attribution could still be wrong. The old N8 also had this source mismatch, so it cannot be attributed to persona reuse.

direct previously had only tasks and final-state reviews, with no SimTrace; the timeline/beat tools could not read execution progress that had already been received. When both the product's default budget and the launcher's absolute deadline were 1800 seconds, the outer layer could force termination first, leaving the product no time to submit a timeout explanation. These issues concern source identity, evidence visibility, and supervisory deadlines, respectively, and should not be resolved by opening access to run directories, fabricating traces, or relaxing the recovery gate.

## Guide-level explanation

For regular and additional rounds, export a read-only source view of the trial SHA during the feedback stage for the role to read, leaving the delivery checkout unchanged. When processing historical backlog reports, triage reads the SHA of the Session from which the report originated. Role records retain the source SHA and export directory; the export directory is deleted after the stage ends and can be reconstructed from the SHA.

Public schema 2 may declare the following runtime configuration fragment:

```json
{
  "runtime": {
    "harness": {
      "request_budget_seconds": 3600,
      "termination_grace_seconds": 60
    }
  }
}
```

“3600 seconds” in the task body is not equivalent to a configured budget. The launcher passes the explicit budget through the message and compatible product environments, and the outer layer forces termination only after 3660 seconds. Whether the product implements an internal budget is still determined by the selected Harness. When no budget is configured, old frozen inputs remain unchanged; only a default 60-second grace period is added to the existing launcher limit and recognizable product environment deadlines.

New direct Sessions save `execution_record` and actual steps, preserving everything received by the platform in full, just as simulated interactions do, and applying shared limits only when projecting timeline/beat/step queries. The persona still receives only the final-state reply and reviews it once, without receiving intermediate progress or additional interactions. Internal execution that was not received remains unknown, and old direct records will not be fabricated retroactively.

## Reference-level explanation

### Source identity

`HarnessSource` uses ContextVar to bind the repository and full SHA, lazily exporting through `git archive` to a temporary directory without `.git` or delivery runtime files; files and directories are read-only. The first actual read verifies that the commit exists and the SHA is complete; errors directly block role execution without falling back to the working tree. The feedback stage shares one exported view; thread pools and model threads copy the context. An individual historical report may nest a binding to its own SHA, restoring the current round's context afterward.

`run_agent_def` sets the work_dir of the NexAU local sandbox for each call, avoiding the use of shared environment variables to pass source directories for concurrent roles. Source identity is written into invocation evidence. When an old envelope lacks identity, retrieve it only from Session provenance or trusted observation receipts, without modifying the old Session or guessing a SHA from user free text. Reports without a usable identity remain marked unavailable.

### Budget and terminal state

`runtime.harness` is optional; when provided, it requires a positive `request_budget_seconds` (at most 86400), with an optional positive `termination_grace_seconds` (at most 300, defaulting to 60 when omitted). local/e2b use the same frozen environment mapping, do not inherit host settings, and do not add default fields to old normalized configurations.

The launcher writes the explicit budget into `budget_seconds` in the message and sets the compatibility variables `HARNESS_TASK_BUDGET_SECONDS`, `HARNESS_CALL_TIMEOUT`, and `HARNESS_TURN_TIMEOUT`; Docker completes the mapping before constructing run arguments. The outer termination deadline is the explicit budget plus the grace period. Without an explicit budget, it is the maximum of the existing 1800-second limit and valid legacy environment deadlines, plus the grace period; invalid legacy variables retain their original fallback behavior, while the new public variables strictly reject invalid values.

The request outcome retains the product budget, infrastructure deadline, grace period, and termination source. Forced termination is recorded as infrastructure; a normal protocol reply from the product is recorded as harness_reply. An infrastructure timeout proves only that a reply was not received in time; it does not claim a confirmed API failure or livelock.

### Direct evidence

In the existing direct adapter in `loop/sim_user.py`, collect stdout observations and native reply steps actually received by the launcher, preserving received lists, bodies, and metadata in full according to the existing persistence principles for simulated interactions. When native steps are absent, derive them only from real progress frames; raw frames remain fully preserved in events. Save them before closing the connection even on abnormal termination. Do not add a separate records module or impose direct-specific limits on record counts or body lengths.

Both modes share the query limits of `demand/session_timeline.py`: beat returns at most 80 items, with tool summaries limited to 220 characters and result summaries to 280 characters; a single step expansion is limited to 6000 characters. direct L2 stdout summaries contain at most 8 items of 160 characters each and return only declared summary fields, without including complete raw frames in query results. Truncation occurs only in query projections; original intermediate step_i values are not renumbered, and bodies exceeding query limits remain stored in the Session. Content that the Harness or upstream producer did not output or already truncated cannot be fabricated.

direct projections explicitly specify `interaction_mode: direct` and `reviewer_visibility: terminal_reply_only`; beat uses existing real requests and replies without creating SimTrace or a goal ledger. L2/L3/L4 permissions retain existing tool boundaries without expanding access to raw Session files; observation-package not_supported remains not_supported, and new records must not be used to infer whether files at absolute paths exist.

### Bounded finalization and recovery

Only when the first triage call returns normally but lacks the `dispositions` array, invoke the same role once more, with at most 8 iterations and a prompt to submit needs_info if evidence is insufficient. The second call starts anew from the original report and available evidence, without carrying over unsaved reasoning from the first call. Do not swallow exceptions, retry indefinitely, force acceptance, or synthesize a disposition; if neither call produces a submission, retain the original failure gate and checkpoint recovery.

## Drawbacks

Exporting source code adds temporary disk usage, and missing commits cause explicit failures. The grace period increases the worst-case wait; bounded finalization can still fail and consumes one additional model call. Fully preserving received long logs may increase Session size, while queries still truncate; these records are not equivalent to complete model or sub-Agent traces. Read-only file modes and the existing tool jail do not constitute OS isolation against malicious code.

## Rationale and alternatives

Do not checkout/reset the shared delivery repository, to avoid conflicts with concurrent OpenAgents changes. Do not allow reading `.openagents/worktrees` to locate versions, preserving evidence boundaries and preventing reads of incorrect runtime artifacts. Do not universally make the outer deadline infinite or silently change budgets based on natural-language task text. Do not fabricate simulated user decisions or scores for direct, preserving the original interaction comparison criteria. Do not automatically treat a missing submission as needs_info; that judgment must be explicitly submitted by the role.

## Prior art

Existing frozen user_sha, RecoveryStore stage gates, role UsageContext, Session transcript, launcher progress, and request status provide the identities and observations needed for implementation. Spec-0080 addresses only profile reuse identity; the independent task environment design in Spec-0081 remains to be implemented.

## Unresolved questions

This work does not determine whether all proposals in the old N8 affected by the source mismatch were wrong, nor does it rewrite existing results. The old experiment has been paused and archived; its frozen controller is not automatically upgraded. Passing independent verification proves only that the fixed path works, not that the five-round experiment has resumed or completed.

## Future possibilities

Rerun the control with the fixed frozen controller and audit the source basis of old proposals; complete internal traces and independent E2B task sandboxes require separate designs. Further retry strategies should be based on observed failure categories and must not expand into infinite retries.

