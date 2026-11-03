---
number: "0080"
title: "Independent Session Orchestration for the Same Persona"
issue: 0
slug: reusable-persona-sessions
summary: "Distinguish concurrent sessions using existing round/slot/session identities, allowing reuse of the same persona and pairings while keeping frozen plans, recovery, and continuation archives consistent, without duplicating persona cards."
tasks:
  - id: T1
    title: "Allow persona reuse in configuration and the pairing compiler"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/config.py
      - backend/ahe_beta/experiment/workload.py
      - backend/tests/test_experiment_config_v2.py
      - backend/tests/test_experiment_workload.py
    scope: "Remove persona uniqueness restrictions on session counts and pairings, while preserving uniqueness in the selection set and the existing serialization and hashing algorithms."
    acceptance: "Different tasks for one persona and repeated complete pairings can both be compiled; unknown IDs/incorrect lengths/duplicate library IDs are still rejected; existing N1/N4 outputs and hashes remain unchanged."
  - id: T2
    title: "Independent session execution and partial failure recovery"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/orchestrator.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_recovery.py
      - backend/tests/test_reusable_persona_sessions.py
    scope: "Orchestrator verifies and executes the complete binding using the existing round/slot, removes persona-level deduplication, and verifies client/workspace/Issue ownership."
    acceptance: "Two concurrent slots with the same persona and complete pairing have distinct keys/sessions/clients/workspaces; failures rerun only the failed session, reports are idempotent, and out-of-order or duplicate slots are still rejected."
  - id: T3
    title: "Archive and inheritance round trip for repeated pairings"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/materials.py
      - backend/tests/test_experiment_continuation_workload.py
      - backend/tests/test_experiment_continuation_contract.py
      - backend/tests/test_experiment_continuation_export.py
      - backend/tests/test_experiment_continuation_source.py
    scope: "The inheritance preview uses the unique persona set; repeated pairings in the final round are fully exported, verified, projected, and compiled for new rounds."
    acceptance: "The round trip from collect to child preserves the order and number of all slots, and each persona card is frozen only once; parent archive bytes remain unchanged, and unknown personas/digest inconsistencies are still rejected."
  - id: T4
    title: "Documentation and independent session acceptance"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - docs/tutorials/multi-user-experiment.md
      - docs/tutorials/multi-user-experiment.zh-CN.md
      - backend/scripts/e2e-spec-0080-reusable-persona-sessions.sh
    scope: "Update the semantics of persona selection and execution lists, and document recovery/observation/attribution acceptance and the scope of direct review."
    acceptance: "The Chinese and English documentation no longer require personas to be unique within a round; live/report/L1 retain independent sessions, and scripts verify concurrent execution/recovery/inheritance with repeated personas. Reused personas must not be treated as independent human samples."
---

# 0080 · Independent session orchestration for the same persona

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

Allow the same persona to correspond to multiple independent sessions in a round, including repeated trials of the same task. A persona represents an immutable profile, while the existing `round_no + slot` represents a session position; continue deriving the session ID from the operation key containing the complete binding. Relax the restriction on profile reuse without adding a participant table, card aliases, runtime switches, or another orchestration system.

## Motivation

The current configuration requires `sessions_per_round <= len(persona_ids)`, and the regular and inherited plan compilers and Orchestrator each reject duplicate personas within a round. Actual workspaces, recovery units, live, SessionStore, and evidence already distinguish sessions by session ID; the profile uniqueness constraint is stronger than execution identity requires.

The eight tasks in historical N8 do not correspond to eight distinct profiles: pvlib and astroid both use `sr-15-swyx`; the direct paths for scheduling and TinyDB also fall back to this profile. Excel, KV, SQLFluff, and Superset use kellan, xe-iaso, ronacher, and kenton-varda respectively, so the eight sessions use five profiles. A comparison that changes only the interaction mode should not require three new profiles or copies of profiles with modified IDs.

The unified entry point already freezes slot, task, persona, interaction, and task digest. Allowing duplicates through the existing session identity can restore the original pairings without changing the existing serialization shape or hashing algorithm, and support independent repeat trials of the same profile and task.

## Guide-level explanation

`workload.persona_ids` remains the unique set of selected profiles; IDs in the persona library must also be unique. `interaction_plan` in each round is an ordered session list that allows duplicate personas or complete pairings, for example:

```json
{
  "workload": {
    "persona_ids": ["sr-15-swyx"],
    "interaction_plan": [
      [["sr-15-swyx", "task-a"], ["sr-15-swyx", "task-b"], ["sr-15-swyx", "task-a"]]
    ]
  },
  "rounds": {"count": 1, "sessions_per_round": 3, "max_parallel_users": 2}
}
```

This is a configuration fragment; a complete definition must still provide the backend, materials, roles, and models. The three positions are slots 0/1/2. Even if slots 0 and 2 have identical pairings, they produce different session IDs, recovery units, and workspaces. Default rotation allows the profile library to be smaller than the number of sessions per round; round length, selected IDs, slot order, and concurrency limits are still checked.

Reports and dashboards display the profile and independent session/slot. They must not treat matching profiles as the same session or interpret reused profiles as multiple independent human samples. Whether multiple feedback items share a common mechanism remains a judgment for the existing requirements role; the entry point does not automatically merge them by persona.

The N8 mixed and all-direct groups explicitly use the same ordered pairings. direct still consists of one frozen task message followed by one persona review after completion, with no follow-up questions, heartbeat, redirection, or acceptance messages during execution; the existing direct code submits a report even when the terminal verdict is accept. This group does not change report generation, scoring, or acceptance criteria.

## Reference-level explanation

### Inputs and identity

Modify `config.load_config_v2` to remove the restriction that the number of sessions cannot exceed the number of profiles; retain the schema's uniqueItems constraint on `persona_ids`, the nonempty library requirement, unknown-field checks, round count, concurrency, and all material checks.

`workload.interaction_plan` no longer deduplicates personas. The inheritance branch of `compile_session_plan` also preserves duplicates as ordered pairs, continuing to validate that task/persona exist and that task digest and interaction are consistent. The six fields of each binding remain unchanged. slot must equal its list position; out-of-order slots, missing slots, duplicate numbers, or bool values masquerading as integers are not accepted.

Orchestrator `_logical_plan` likewise removes the persona uniqueness check while retaining the other structural checks. The session key continues to use `operation_key(run_id, "users", binding)`; the slot in the binding already ensures different keys for duplicate pairings. Session provenance, UsageContext, client creation, and task runtime ownership retain their original implementations, with no added mutable state on persona cards.

Only the range of pairings accepted by new configurations is expanded. Previously valid inputs processed by the new default compiler produce exactly the same plan, config hash, binding hash, and session key as before. Prepared runs continue to use their frozen controller and are not updated in place.

### Execution, recovery, and archiving

Create a separate client, workspace, and attempt for each slot; threads share only immutable profiles. Failure recovery reruns only incomplete session units; it neither skips a slot because another slot with the same persona has completed nor uses that slot's Issue or files as this slot's results.

SessionStore and live store data by session ID; role evidence authorization and grouped architect process data by source session/report. Do not reinterpret Metrics based on persona counts or add profile-level execution deduplication.

continuation export preserves all final-round pairings by slot, and source verifies the set of completed users by session ID; profile materials freeze only the ordered unique set of cards. In the inherited preview, `persona_ids` is obtained from `source.personas` instead of being listed repeatedly from each pair. Duplicate parent pairings are compiled into each added round in their original order; profile deduplication must not shorten boundaries or change the session count.

### Comparison and acceptance

Changing interaction changes the task digest, catalog/plan hash, and session key; this is the result of correctly deriving identity. The pairing audit compares source code, instructions, environment, models, initial Harness, profile cards, and ordered slots; only interaction and its derived identities, plus each run's coordinates, may differ. The two groups must not be required to share session IDs, and completed sessions from one group must not be reused.

The four tasks cover configuration/compilation, execution/recovery, archiving/inheritance, and documentation/acceptance respectively; file assignments follow the frontmatter. The end-to-end script is `backend/scripts/e2e-spec-0080-reusable-persona-sessions.sh`. Do not use forwarding scripts from old experiment artifacts as public entry points.

| Acceptance | Required observations |
| --- | --- |
| New configuration | One profile with three slots passes validation; duplicate library IDs, unknown IDs, incorrect plan lengths, and out-of-order slots are still rejected |
| Old inputs | Existing N1/N4 compilation outputs, hashes, and keys remain unchanged |
| Independent execution | Two concurrent slots with the same persona/task each have their own client, session ID, attempt, and writable workspace; file modifications do not leak across sessions |
| Failure recovery | When one slot completes and another is interrupted, only the latter is rerun; Issues are idempotent and source sessions are not confused |
| Archive round trip | Final-round duplicate pairings retain their order and count through collect→source→child run; profile cards are frozen only once, and parent bytes remain unchanged |
| Feedback and observability | live/L1/report associate multiple distinct sessions; direct terminal review remains unchanged, and report counts are not treated as complaint counts or official pass rates |

## Drawbacks

Multiple sessions with the same profile are more correlated and cannot be treated as independent user samples when calculating statistical significance. The entry point displays execution ownership, but experiment analysis must still explain the repetition structure of profiles and tasks.

Relaxing the constraint makes previously rejected configurations runnable, so all subsequent deduplication checks must be updated together to avoid successful preparation followed by failure during execution or inheritance.

## Rationale and alternatives

Use the existing slot as the execution position because current hashing, recovery, and workspaces already use it to distinguish sessions. Adding a participant model would duplicate existing concepts and expand the Session/provenance/archive contracts; it is not currently needed.

Do not copy persona cards or add aliases to them. Copying would fabricate “different users” and introduce profile identity differences into the comparison; reuse of the same profile should be faithfully preserved in provenance records.

Do not add an allow_duplicate_persona switch: unique profiles are not a prerequisite for safe execution, and retaining a switch that rejects duplicates by default would give the same mechanism two sets of semantics. The selection set remains unique while the execution list permits duplicates; the boundary is already clear.

## Prior art

The current Orchestrator's complete binding key, prebuilt session/attempt directories, immutable SimPersona, session ID live labels, and continuation slot/session validation already provide the required execution identity. The historical direct runner uses the first profile among the selected simulated personas, whose actual value in N8 is `sr-15-swyx`; the two new configurations explicitly freeze this fallback.

## Unresolved questions

The interface design is settled: the profile selection set is unique, the session list allows duplicates, and no runtime entities or switches are added. Rich task environments belong to a separate environment proposal; completion of this group alone cannot establish that the original N8 files, services, and environments have been restored, nor justify launching an eight-scenario experiment without environment acceptance records.

## Future possibilities

The analysis interface could add views showing repeated trials by profile, task, and slot. Independent statistical repetition counts or random seeds should be designed separately when there is a clear experimental need; this group does not include incidental changes to scoring, reporting policies, or sampling methods.

