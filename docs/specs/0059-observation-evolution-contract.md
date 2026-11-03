---
number: "0059"
title: "Observation file access and on-demand evidence gathering by design roles"
issue: 0
slug: observation-evolution-contract
summary: "Allow Triage, the independent PM, and Architect to inspect the artifact's own observation files through ordinary file tools according to their responsibilities, preserving existing requirements outputs and role assignments."
tasks:
  - id: T1
    title: "Read-only access to artifact observation files and access auditing"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/observation_provider.py
      - backend/ahe_beta/demand/agent_runtime.py
      - backend/ahe_beta/guards/workspace_jail.py
    scope: "Register session-associated manifests; read declared files through ordinary file tools; preserve text formats, line numbers, queries, and permission auditing."
    acceptance: "Read renamed logs and documentation without interpreting event schemas; prevent reads across sessions, of undeclared files, and through symbolic links; operate normally without logs."
  - id: T2
    title: "On-demand evidence gathering and continuity of evidence references for the independent PM and structural synthesis"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/ahe_beta/demand/architect.py
      - backend/ahe_beta/demand/proposal_view.py
      - backend/ahe_beta/demand/evidence_contract.py
      - backend/ahe_beta/demand/session_timeline.py
      - backend/tests/loop/test_architect.py
      - backend/agent_defs/architect
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/triage_agent/systemprompt.md
    scope: "PM observes independently using the experience index; Architect verifies only sessions referenced by visible proposals; synthesis outputs deterministically inherit source references and remain compatible with legacy evidence tools."
    acceptance: "PM does not wait for Triage approval; Architect references are not lost through the 3000-character display limit or source consolidation; no new review gates."
  - id: T3
    title: "Boundary regression tests and single-path replay with a real model"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/tests/demand/test_observation_provider.py
      - tools/dev/replay/replay_observation_synthesis.py
    scope: "Verify reads through ordinary tools and source chains, replay PM and Architect with fixed evidence, and audit actual reads and outputs."
    acceptance: "Offline tests pass; real-model results retain inputs, outputs, access records, and timing, distinguishing mechanism accessibility from actual drill-down."
---

# 0059 · Observation file access and on-demand evidence gathering by design roles

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level rust-RFC overview in 9 sections. -->

## Summary

Provide read-only access to artifact observation files for design roles. PM independently discovers product opportunities from user experience; Architect synthesizes structural relationships from
existing proposals; Triage continues to handle individual reports. Roles use existing file tools to gather evidence as needed,
with their respective tasks, output schemas, and submission conditions unchanged.

## Motivation

Human developers first form questions from user feedback, then verify them against the relevant version, request logs, source code, and documentation.
Logs are part of the artifact, and event names, content, and query methods change with the implementation. If the orchestrator predefines the fields and interpretation of every
internal event, it becomes deeply coupled to the evolving artifact; providing only user-visible conversations cannot distinguish normal
slow operations from causes such as internal recovery. This change fixes evidence location and read boundaries while leaving content interpretation to the roles.

## Guide-level explanation

Role inputs remain primarily user evidence or proposals, supplemented by a short list of available manifest addresses. The model can use `read_file`
to read the entry point and documentation, then use `list_directory`, `search_file_content`, and paginated `read_file` to locate specific evidence.
Roles are not required to inspect logs every round; no additional model classifies logs, and no new diagnostic forms are mandatory.

For example, a user reports “no response for a long time”. Logs may show a model output error followed by recovery, or they may show
normal execution of a long-running tool. PM uses this to assess the waiting experience, while Architect uses it to determine whether two proposals involve the same mechanism;
evidence of internal retries does not itself mean “the product must show users the details of every retry”. When logs are missing, retain uncertainty;
valid requirements can still be proposed based on user evidence.

The evidence available for roles to inspect here is diagnostic evidence for maintainers. Whether users could understand the state at the time and decide what to do next falls under the
user-facing status feedback goals of 0035; the diagnostic observability enhancement entry point in 0061 addresses only gaps in maintainers' evidence gathering. The two types of goals and their acceptance
remain separate. When PM discovers insufficient user feedback, it still submits an ordinary product proposal without first having to complete internal logs.

## Reference-level explanation

T1 provides an ObservationProvider without a model, bound per invocation by the shared agent runtime.
The infrastructure specifies only `<observation_root>/<session_id>/manifest.json`; the manifest contains the identically named `session_id`
and `files: [{path: "relative path", ...}]`. All other metadata, reading instructions, formats, and event names belong to the artifact.
The artifact should document release versions, request associations, and log semantics in the manifest or declared documentation files.
The default root is observations alongside sessions, configurable through `AHE_BETA_OBSERVATION_ROOT`.

Workspace middleware allows ordinary file tools to read only declared files, preserving original text, line numbers, and query locations. New events
do not require framework parser changes; renaming files requires only an artifact manifest update. Undeclared files, other sessions, and symbolic
links are not read. Searches target only authorized files; output length is limited, and reads support offset/limit. Known environment
credentials are redacted from returned text. Publishers should not export raw credentials, persona prompts, or oracles into observation packages;
the Provider does not claim to automatically identify every secret in arbitrary log content. Failures or missing data are not disguised as empty successes.

T2 binds scope by responsibility: Triage to the current report's session; PM to the sessions in the current experience index;
Architect to sessions explicitly referenced by visible proposal/ready items; Owner has no raw observations. Architect
supports 0055 L2/L3/L4 reference drill-down, with permissions enforced by tools. Truncating displayed body text at 3000 characters does not lose evidence handles;
synthesized artifacts deterministically inherit selected source references so that closing the original proposal does not break the observation chain.

Architect no longer receives the legacy runtime_agg by default: this aggregator interprets existing transcript fields, reply text, and
fixed source-code constants, and cannot represent internal facts of the evolved artifact. Controlled replay has shown the model using
zero counts caused by missing fields as supporting evidence for attribution, so this default input is removed in this change; legacy statistics code may remain for historical diagnostics, while roles inspect
the relevant artifact's actual observations as needed.

Provider reads record the role, session, file, line range or search terms, and success/denial status, reusing
`evidence_access.jsonl`; role traces retain tool results. Ordinary file-tool operations themselves are recorded,
without adding a gate that requires the model to provide a “reason for gathering evidence” before proceeding. Legacy timeline/beat/step still accept reason.

T3 verifies different log formats, renamed files, read isolation, graceful degradation for missing data, thread context, and reference continuity, and performs real-model replay with fixed
evidence, separately reporting whether reading is possible, whether roles proactively read, and output quality. Task and file assignments are in
frontmatter. This scope covers wiring consumption on the design side; internal logs not collected in existing historical runs cannot be fabricated retroactively.
Artifact log collection and container finalization exports for complete new experiments must be integrated through the corresponding artifact/startup contracts before coverage can be claimed.

Actual verification: 150 relevant tests passed; in real GLM-5.3 replay, PM performed 8 native file reads and
2 timeline reads, while Architect performed 7 native file reads. Architect submitted one
structural proposal in 204.268 seconds; PM submitted late, after the 360-second replay time limit, and was not counted as successful. The zero-count misinterpretation discovered in replay was used to
remove the legacy aggregate default input described above; no claim is made that improved model output quality after the correction has been measured again.
Complete local record: `backend/data/observation-replays/0059-pm-architect-20260908/AUDIT.md`.

## Drawbacks

A real model may choose not to inspect logs, or may inspect them but attribute causes incorrectly; accessibility does not prove design benefits.
Text return budgets may truncate long lines, so audits must also consult original files. The current file entry point covers only explicitly configured export directories;
it neither automatically discovers arbitrary logs on the host nor automatically converts existing NexAU trace databases.

## Rationale and alternatives

A thin file entry point is chosen because evolution must accommodate the artifact's own diagnostic language. Dedicated functions for fixed event types would require
synchronized orchestrator changes for every internal change. Giving roles the entire sessions/host directory would expand irrelevant input.
A single static development manual is also insufficient: documentation can evolve with the artifact, but each run must still correctly associate documentation, logs, and versions
and make them readable by roles. Here, evolving documentation files are read as ordinary artifact files, while the infrastructure only maintains location boundaries.

## Prior art

Reuse the on-demand timeline from 0024, the role cognitive contracts from 0043, invocation persistence from 0049, and evidence boundaries from 0055.
Continue the verified Triage observation replay through ordinary file tools without changing Triage's report normalization goal.

## Unresolved questions

Collection and export coverage of native NexAU logs in each new experiment requires follow-up checks by run entry point. Current tests
do not equate controlled replay with all internal events in a real closed loop having been persisted.

## Future possibilities

Artifacts can evolve diagnostic events, association methods, and reading instructions in their own meta-spec and development specs; real troubleshooting questions from user
experiments can then test whether these reduce uncertainty. The infrastructure does not need to prescribe every diagnostic event in advance.
