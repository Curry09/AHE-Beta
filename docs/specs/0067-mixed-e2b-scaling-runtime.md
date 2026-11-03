---
number: "0067"
title: "Mixed Harness E2B Scaling Runtime"
issue: 0
slug: mixed-e2b-scaling-runtime
summary: "Retain the current underlying direct-session and terminal-review contracts; archive the historical mixed E2B scaling runtime and do not extend the current v2 single-task entry point."
tasks:
  - id: T2
    title: "Underlying direct-session and terminal-review contracts"
    status: done
    priority: P0
    tags: [e2b, interaction]
    depends-on: []
    relates-to:
      - ref: 0065/T4
        type: extends
    parallel: false
    files:
      - backend/ahe_beta/loop/sim_user.py
      - backend/tests/user/test_direct_session.py
    scope: "Retain the existing direct single Harness input and bounded terminal review interfaces in sim_user, separate from simulated-user heartbeat interaction; the old mixed executor is archived, and this interface does not make the current v2 single-task entry point support N4/N8."
    acceptance: "direct produces no heartbeat/follow-up, terminal review and issue/session records are traceable; direct-session tests pass; the current public configuration continues to reject multi-task plans."
---

# 0067 · Mixed Harness E2B Scaling Runtime

## Summary

> Current contract after 0071 cleanup: the old mixed E2B materialization, launch, recovery, and research-manual T1/T3/T4 items have exited the living task list, and the original implementation is archived. Only the existing direct input/terminal-review interfaces in sim_user are retained; this does not mean that the current v2 entry point supports direct scaling or N4/N8. The E2B+Boyue, N=1/4/8/16/32, and resume procedures below are historical design records; reproduction must use the frozen checkout recorded in research/inventory.json and must not run from the archive directory or the current CLI.

Official scaling uses E2B + Boyue. N=1, 4, 8, 16, and 32 are five mutually isolated experimental units: each unit has its own controller, sandbox, Gitea repository, run ID, and recovery identity, and runs five rounds. Physical sandboxes are created directly at peak development-stage resources; user, triage, architect/PM, and developer are logical stages, and sandbox specifications are not adjusted between stages.

Task assignment is frozen before execution. Agent and grader payloads are separated, and the receipt binds the configuration, task revision, prompt/grader SHA, model gateway, template build, timeout, and canary evidence. The launch gate checks these constraints before any credential, network, or paid-resource call.

## Interaction and lifecycle

`simulated_user` retains the existing persona, heartbeat, workspace/check access, and multi-turn termination rules; fixed follow-up questions are no longer injected. `direct` has only one initial harness input, waits for the terminal result, and then has the user model perform one bounded terminal review; it has no heartbeat or mid-session follow-up, but still enters the same triage → architect/PM → developer → grader pipeline.

Each round executes the interaction, triage, architect/PM, developer, and grader stages in order and writes an atomic checkpoint before the next round. Whether the final round is users-only is determined by configuration. On disconnection, resume may connect only to the sandbox/repository/identity recorded in the receipt; it must not create replacement resources or replay completed sessions or deliveries.

## Operator path

Operators should read `evaluation/harness-suite-20260920/EXPERIMENT-QUICKSTART.md` and complete payload materialization, receipt freeze, and a single N `check-launch` in sequence, then start the five independent terminals as needed. Runtime artifacts are placed in the local controller's `runs/` and the remote `/opt/hse-run/artifacts`; these generated directories are excluded by gitignore and are not committed. Detailed runtime constraints are specified in `evaluation/harness-suite-20260920/SPEC-mixed-scaling-e2b-executor.md`.

## Motivation

Previously, launch scripts for different N values separately managed sandboxes, Gitea, user interaction, and recovery state, making identity crossover, duplicate controllers, or replacement of original resources with new resources likely. 0067 fixes each N as an independent auditable experimental unit and places freezing, launch, checkpointing, and recovery in one receipt-driven workflow.

## Guide-level explanation

First materialize and freeze the agent/grader payloads, then execute the launch gate for one N; only after it passes are paid resources created. Write an atomic checkpoint at the end of each round. Disconnection recovery accepts only the sandbox, repository, run_id, and recovery identity recorded in the original receipt; completed sessions or deliveries are not replayed.

## Reference-level explanation

The receipt binds the task revision, prompt/grader SHA, model gateway, template build, resources, timeout, and canary evidence. direct sends only one harness input and performs one terminal review; simulated-user retains heartbeat and limited follow-up. The controller, remote run.sh, and result report must output the same session, trace, grader, user outcome, and timeout class.

## Drawbacks

Maintaining independent resources for each N increases launch costs and the operational surface; five rounds of checkpoints, receipts, and recovery identities also increase the volume of disk and audit data. The benefit is avoiding cross-experiment contamination and reliably reconnecting to the original runtime.

## Rationale and alternatives

Isolation by N rather than sharing one large sandbox gives concurrent scaling and failure recovery clear boundaries. Receipt freezing rather than relying only on configuration files prevents task, grader, or timeout drift during execution. Sharing a controller or rebuilding resources during recovery is simpler, but would undermine traceability and could cause duplicate charges.

## Prior art

0065 defines the evaluation plan, interaction modes, and unified result; 0064 defines phase recovery and idempotent side effects; 0066 defines official budgets and provider-latency isolation. This spec combines the three into the practical E2B scaling path.

## Unresolved questions

Whether N=32 and above requires sharded controllers, cross-region resources, and finer-grained artifact backpressure will be determined by official scaling data; for now, retain the single-N, single-controller constraint.

## Future possibilities

Automatic scheduling, cross-N aggregation, and fault injection can be added without changing receipt semantics, using the same recovery identity to replay infrastructure-invalid attempts while preventing business terminal states from being rerun.
