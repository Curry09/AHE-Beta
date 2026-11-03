---
number: "0066"
title: "Provider latency isolation and official budget timeouts"
issue: 0
slug: provider-latency-isolated-timeout
summary: "Preserve full wall time while isolating model provider wait from the mechanism's active-time budget, and standardize the official task's inner budget and outer budget plus 600 seconds rule."
tasks:
  - id: T1
    title: "Unified time ledger and provider scope"
    status: done
    priority: P0
    tags: [timeout, observability]
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/usage.py
      - backend/ahe_beta/loop/live_tracer.py
      - backend/ahe_beta/user/sim/persona_client.py
    scope: "Record wall, active, provider wait, and unknown time and model call events; overlapping provider intervals are counted by their union."
    acceptance: "Each call has a correlatable call_id; records are replayable and contain no credentials; legacy usage records remain compatible."
  - id: T2
    title: "Timeout classification by role and recoverable cancellation"
    status: done
    priority: P0
    tags: [timeout, recovery]
    depends-on: [T1]
    relates-to:
      - ref: 0064/T2
        type: extends
    parallel: false
    files:
      - backend/ahe_beta/demand/agent_runtime.py
      - backend/ahe_beta/demand/grouped_architect.py
      - backend/ahe_beta/loop/sim_user.py
    scope: "Distinguish mechanism, provider, infrastructure, and controller timeouts, and retain deadline evidence in the recovery ledger."
    acceptance: "Provider wait is not misreported as a mechanism failure; the outer wall guard remains bounded; completed operations are not replayed on resume."
  - id: T4
    title: "Time classification regression acceptance"
    status: done
    priority: P1
    tags: [tests, docs]
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/tests/test_time_accounting.py
    scope: "Retain the current wall/active/provider-wait classification and timeout regressions; historical scaling configuration propagation and research quickstart have been archived and are not part of the current startup contract."
    acceptance: "Current time classification tests pass without relying on archived launchers; the original timeout policy in historical run records remains unchanged."
---

# 0066 · Provider Latency Isolation and Official Budget Timeout

## Summary

> Current contract after 0071 cleanup: retain the current time ledger, role cancellation, and time-classification tests. Only the historical scaling configuration/remote propagation T3 has exited the living task list; the descriptions below of the historical remote run.sh, fixed scaling configuration, and its quickstart are original research records and are not current v2 launch requirements. The original materials are traced from research/inventory.json and the frozen checkout.

Evaluation must retain both the original wall time and interpretable active time. Model-serving queueing, time to first token, streaming reads, and retries are provider wait; local tools, parsing, workspace operations, checkpoints, and Harness control are active work. Mechanism timeouts are determined only by the active budget; provider wait and infrastructure timeouts are classified separately and must not be disguised as task failures.

The inner deadline for each task is the official agent timeout; the outer deadline is fixed at `official_agent_timeout_seconds + 600`. The 1800-second fallback is used only when no official budget exists, and its source is marked in the manifest/receipt. This rule applies to both direct and simulated-user interactions.

## Contract

At runtime, each role operation stores `wall_elapsed`, `active_elapsed`, `provider_wait_ms`, `unknown_elapsed_ms`, the call count, and the timeout class. Provider requests have their own deadlines; the entire task also has an outer wall guard. If the outer deadline occurs during provider wait, the result is an infrastructure timeout; only when active work exceeds the mechanism budget is it a mechanism timeout.

`latency_isolated_timeout.enabled` is a compatibility switch. The official E2B scaling configuration enables it and propagates `wall_guard_grace_seconds=600` to the controller, remote bundle, receipt, and run.sh. Credentials may still be provided only through `.e2b`, `.boyue`, or the injected environment.

## Verification

Changes must pass the time-accounting, direct-session, grouped-architect, infrastructure, and closed-loop regression tests; before launch, the receipt must also bind the config/task/template SHA, canary evidence, and timeout policy. Detailed implementation constraints are specified in `evaluation/harness-suite-20260920/SPEC-time-accounting-provider-latency.md`.

## Motivation

The existing runtime mixes model-serving queueing, streaming time-to-first-token latency, and local mechanism work into one deadline, causing slow providers to be misreported as agent failures and making it impossible to determine during recovery whether replay is needed. 0066 fixes the time ledger and timeout classification for shared use by direct, simulated-user, and E2B control-plane workflows.

## Guide-level explanation

Each role operation records wall, active, provider-wait, and unknown time simultaneously. Provider requests have their own deadlines; the mechanism budget consumes only active work, while the outer wall guard provides a fallback. During recovery, continue unfinished steps according to the operation key and the saved deadline evidence; do not replay side effects that have already been submitted.

## Reference-level explanation

Time intervals are associated with a stable call_id through call events; overlapping provider intervals are counted by their union. The manifest, receipt, remote run.sh, and controller all carry the same timeout policy, and the launch gate checks that the policy summaries match. The 1800-second fallback with a source marker is used only when no official budget exists; the outer deadline is fixed at the inner deadline plus 600 seconds.

## Drawbacks

The ledger fields and receipt are more complex, and old consumers need backward-compatible reading; when provider events are missing, unknown time may still remain and must be shown separately in reports rather than silently classified as active.

## Rationale and alternatives

Explicitly separating time instead of simply extending the total timeout preserves the true wall time while preventing server-side queueing from contaminating mechanism metrics. The alternative is to continue using a single wall budget, but it cannot distinguish model-provider failures, infrastructure failures, and agent timeouts, and recovery cannot be judged safely.

## Prior art

0064 provides phase cursors, operation keys, and delivery recovery boundaries; 0065 provides official budgets, direct/simulated-user modes, and a unified outcome. This spec applies those constraints to provider latency and the outer wall guard.

## Unresolved questions

Whether retry waits from different providers should be further split in reports into queueing, time to first token, and streaming-read subclasses will be decided after sufficient real-run samples are available and based on whether the schema should be upgraded.

## Future possibilities

Cross-role latency percentiles and budget forecasts can be generated from call_id, and historical provider wait can be used before launch to estimate whether concurrency or resources need adjustment, without changing the official agent timeout.
