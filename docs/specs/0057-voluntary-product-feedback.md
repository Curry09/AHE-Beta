---
number: "0057"
title: "Voluntary product feedback in parallel with the primary interaction action"
issue: 0
slug: voluntary-product-feedback
summary: "Attach voluntary product feedback to existing user actions while preserving the semantics of continuing, waiting, accepting, or giving up; feedback reachability does not depend on tool capabilities or correction strategies, and format errors produce only warnings rather than automatically creating issues based on low scores."
tasks:
  - id: T1
    title: "Compatibility between feedback accompanying primary actions and existing issue creation"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/loop.py
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/clauses.py
    scope: "Distinguish the recipients of the current task and product feedback; main_act and waiting_act support an optional report_issue, deduplicate the body exactly, and create an issue during the existing closing phase."
    acceptance: "Valid feedback does not replace the primary action and does not add model calls; absent or invalid feedback does not automatically create an issue; a correct persona may provide feedback voluntarily without taking over the task."
  - id: T2
    title: "Action compatibility and persistence regression"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/tests/user/sim/test_feedback.py
      - backend/tests/user/sim/test_heartbeat.py
      - backend/tests/user/sim/test_prompt.py
    scope: "Cover reports accompanying continue, accept, wait, and terminal actions; verify equal reachability for Personas with different capabilities and persistence from session to needs-triage."
    acceptance: "Blind and expert Personas can both report; duplicate bodies create only one issue; invalid feedback and low-score silence do not change valid primary actions; existing terminal feedback remains usable."
---

# 0057 — Voluntary Product Feedback in Parallel with the Primary Interaction Action

## Summary

A user's primary action may be accompanied by one voluntary product feedback report, without requiring the user to pause, give up, or change the acceptance result because of the feedback.
Reachability does not depend on workspace tool permissions; the framework preserves both actual reports and silence and does not create issues based on the experience score.

## Motivation

Task completion and opportunities to improve the user experience can coexist. Although the old mechanism has a non-terminal
report_issue tool, it appears only in some Personas' perception tool stacks, while the intent/action phase
also prohibits tools. file_issue simultaneously carries exit semantics, so users who continue solving the task rarely report issues.
Reporting an experience does not require code-reading capability and should not require the user to stop working or prove the product's root cause.

## Guide-level explanation

The intent phase identifies two recipients: harness messages advance the current task; product feedback helps developers improve
future use and does not promise an immediate fix for the current task. Whether to report is chosen autonomously by the Persona, and silence is allowed.
A user report must not be created automatically based on a low score, complaint, repeated correction, or gap.

The existing JSON for main_act / waiting_act may additionally carry
`"report_issue": {"body": "The user's own feedback"}`. Continue, wait, interrupt, accept, or leave
may all be accompanied by a report; the primary action and goal semantics remain unchanged. An absent or null field means no report; no additional model call is made. All Personas/clients can use it, including blind Personas without workspace tools.
Retain the old perception-stage report_issue tool and terminal reporting path for compatibility with existing interactions.

The body describes what was actually experienced, what was expected, and the impact, optionally noting that it was later resolved. No technical diagnosis, proof of reproducibility, or development plan is required. Difficulty in the original task alone is not a required reason to file an issue.

## Reference-level explanation

Reuse the existing issue_notes → tracker.create_issue at session end → issue_refs path.
The original act-call trace retains the feedback choice and body; tracker stores the official body; the session issue_refs associates the official issue for triage. Subsequent history records that it has been logged and is awaiting closing submission, preventing the model from mistakenly believing that the development team is handling it.
Within one session, identical bodies are deduplicated exactly; semantically similar bodies are not merged without authorization.

A malformed feedback field records only a warning with its phase/round and does not trigger a retry of the primary action, change accept, force an exit, or infer a body from a complaint. Normal fields do not change the acceptance basis or goals regardless of the primary action. This change does not alter the existing session-closing submission timing, recovery from external tracker failures, or terminal-report semantics.

T1 handles the loop, prompts, and correction clauses; T2 depends on T1 and handles feedback, heartbeat, and prompt regression tests.
See the frontmatter for specific file assignments. The offline validation script is `backend/scripts/e2e-spec-0056-0057-user-semantics.sh`.

### Validation boundaries

Cover continue+report, accept+report, and heartbeat wait+report; blind/expert can submit equally; reports are associated with persisted sessions and enter needs-triage; duplicate bodies do not create duplicate issues; low scores without reports remain issue-free; invalid feedback does not block a valid primary action. Unit tests verify the mechanism but do not prove that a real model will provide feedback more autonomously or accurately; subsequent real replays should observe both useful feedback and excessive issue creation.

## Drawbacks

Only exactly identical bodies are removed within a session, so semantically similar duplicates may remain. Feedback is submitted during closing, and recovery from an external tracker after a sudden process crash is outside the scope of this change. Prompt reachability also cannot guarantee that the model will choose to provide feedback.

## Rationale and alternatives

We did not adopt forced issue creation for low scores because it would mistake text produced by the scoring rules for user opinion; nor did we add a mandatory feedback model call because it would increase latency and change users' willingness to report. Retain the old report_issue tool and terminal issue-reporting path; the new optional field only fills the reachability gap in the action phase.

## Prior art

Reuse the existing issue_notes, terminal reporting, and tracker/session association mechanisms without introducing a new reporting queue or feedback role.

## Unresolved questions

There are no open items requiring a decision for this submission; real feedback and false-positive rates are left to independent interaction observation.

## Future possibilities

Future work may improve recovery after submission failures and duplicate-report retrieval, but low scores or complaints must not be automatically converted into official reports.
