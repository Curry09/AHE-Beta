---
number: "0062"
title: "Delivery failure terminal-state protocol compatibility"
issue: 0
slug: delivery-failure-terminal
summary: "The current-round delivery gate recognizes automation-failed, retains needs-human compatibility, and prevents failed rounds from advancing."
tasks:
  - id: T1
    title: "Current and historical failure terminal states and closed-loop regression"
    status: done
    priority: P1
    depends-on: []
    files:
      - CLAUDE.md
      - backend/ahe_beta/loop/round_gate.py
      - backend/tests/loop/test_round_gate.py
      - backend/tests/loop/test_orchestrator.py
    scope: "Code changes are complete. Both automation-failed and needs-human take precedence over closed; exceptions preserve accurate failure reasons and issue numbers."
    acceptance: "Both failure types immediately stop the round; failure to close an issue does not count as success, and the next round is not started. Normal delivery and timeout paths remain unchanged."
---

# 0062 · Delivery failure terminal-state protocol compatibility

## Summary

Code changes are complete. Fixes the framework's current-round delivery gate recognizing only the legacy needs-human label.
2026-09-09 full test suite: 856 passed; targeted terminal-state gate and orchestration regression: 38 passed.
Test entry point: `.venv/bin/python -m pytest backend/tests/loop/test_round_gate.py backend/tests/loop/test_orchestrator.py -q`.
Original experiment results are available in Git history; see `docs/VERIFICATION.zh-CN.md` for current reproducible checks.

## Motivation

In the Spec61 two-user experiment, OpenAgents labeled issue #8 automation-failed, while this framework still treated it as
inflight and waited for the four-hour limit. The experiment was restored after one manual verification and has been archived; this fix does not change the original run's audit attribution.

## Guide-level explanation

If any admitted issue has automation-failed or needs-human, the current round immediately raises RoundDeliveryBlocked;
it must not be finalized as successful or start the next user round. The stop is an explicit failure, not a silent stall.

## Reference-level explanation

classify_issue checks both failure labels before checking closed. wait_round_delivery preserves deduplicated issue numbers,
and determines reasons from the actual failure labels in the current snapshot; mixed failures consistently list both reasons without incorrectly reporting the legacy label.
The delivery runner database is not read directly; both sides remain decoupled through forge state and the mainline SHA alone.

## Drawbacks

Even a briefly occurring terminal state stops the current experiment. This is a conservative choice in the terminal-state contract; the delivery side must avoid false failure/revival oscillation.

## Rationale and alternatives

Do not extend timeouts to conceal failures, let closed override failure labels, or repair delivery worktrees within this framework.

## Prior art

This repository's Spec-0050 terminal-state gate; OpenAgents Spec-0081 machine failure projection and Spec-0088 convergence fix.
See the archive and manual intervention records in ahe-beta-experiments/spec61-two-user-glm53-glm52-20260908 for evidence.

## Unresolved questions

The real two-user experiment involved one manual correction and cannot be claimed as fully autonomous success. The new image containing the fix requires a separate experiment for verification.

## Future possibilities

If the cross-framework terminal-state protocol adds states, expand contract regression coverage first, then freeze the framework version for the next experiment.
