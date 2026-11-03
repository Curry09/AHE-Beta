# Harness Meta-Spec

## Observability lifecycle

### Two categories of objectives

- **User-facing status feedback**: Helps users understand the current situation during use and decide what to do next; assessed by whether the information actually visible at the decision point is accurate, timely, and supports the required judgments.
- **Diagnostics and observability for design and development**: Helps maintainers reconstruct what happened, distinguish causes, and validate changes; assessed by whether the records and documentation for the corresponding version can answer specific diagnostic questions.

Distinguish these two categories by whom the information serves and what judgments it supports, not by the role of the person discovering it, the output format, or the underlying event source.
They MAY share events and Implementation, but the existence of logs does not mean users received feedback, and status messages do not mean diagnostic evidence is sufficient.

### Diagnostic records and development responsibilities

Diagnostic records, correlation methods, and reading guidance belong to this harness and evolve alongside its features. The current NexAU starting point is maintained through
`observability.py` and `OBSERVABILITY.md`; these MAY be replaced when switching runtimes, with no requirement to preserve internal event fields.
`params.yaml` declares `observations: artifact-observations-v1`, and the runner provides
`HARNESS_OBSERVATION_DIR`; the artifact publishes a relative file manifest, `manifest.json`, and its `reading` entry point.
The manifest indicates complete/partial. The framework handles only transport, versioning, integrity, and authorization; it does not wrap the artifact's private functions.

A feature's SDD Spec / Objective Contract separately describes, within its existing sections, its “user feedback impact”: when users need to know what, and what decisions this supports; and its “diagnostic observability impact”: what maintainers need to reconstruct or distinguish, and whether existing evidence is sufficient. Describe changes and validation separately; if there is no impact, a brief explanation of the reason is acceptable. Additional events or section formats are not mandatory.
The Developer maintains affected user output/help, diagnostic records/reading guidance, and tests in sync. Both categories of objectives MAY be delivered in the same issue, but review accepts them separately; passing one cannot close the other. Historical logs are interpreted according to their historical versions, and tests of new logs are bound to the actual HEAD; “a success log was emitted” cannot substitute for the feature passing.

When a maintainer's specific diagnostic question cannot be resolved because of insufficient coverage, propose a diagnostic observability enhancement, preserving the scope already investigated, unknown facts, the impact on maintenance judgments, the desired ability to distinguish cases, and validation scenarios; there is no requirement to first prove a root cause that is not yet observable, nor may one be fabricated.
Insufficient user feedback is an ordinary product requirement and does not use the diagnostic enhancement entry point. User feedback requirements do not require the internal root cause to be established first, and diagnostic enhancements do not require proof of user dissatisfaction first; declare dependencies and blockers only when it is actually impossible to select an approach or validate it. Related objectives retain independent acceptance and status; do not alter frozen objectives without authorization. Host export, permission, or retention failures are infrastructure diagnostic matters handled by environment maintainers; this harness is not required to modify the host.

Records MUST be bounded and minimized by default, and MUST NOT retain full prompts, full tool arguments/returns, credentials, hidden prompts, or protected evaluation reference data; write failures MUST NOT change task results or block indefinitely. Records left unfinished by exit/crash SHOULD be explicitly marked partial rather than presented as complete.

## 1. Purpose and authority

This file is the project-level Meta-Spec for the harness: it provides subsequent Spec Writers, Developers, and maintainers with a shared starting point, describing the current artifact's skeleton, main control points, terminology, and evolution principles.

It is neither an SDD Spec nor a frozen Implementation checklist. An issue's objectives, tradeoffs, and acceptance are governed by its corresponding SDD Spec or Objective Contract; code and tests are the ultimate facts about current behavior. Both the harness repository and the NexAU dependency are within the scope of modification; when a new Spec intentionally changes the boundaries described here, the new Spec, Implementation, and acceptance results SHOULD take precedence, and the affected sections of this document SHOULD be corrected after merging.

## 2. Terminology and naming standard

### 2.1 Artifact terms

- **Meta-Spec**: The current project-level baseline. Records the shared skeleton, responsibilities, control points, principles, and update rules; does not freeze Implementation.
- **SDD Spec (Spec group)**: A self-contained design contract for a feature in `docs/specs/NNNN-slug.md`, recording objectives, motivation, approach, tradeoffs, tasks, and acceptance.
- **Objective Contract**: A compact design contract for a single v0.2 issue, located in `docs/objectives/issue-*.md`; it is the frozen Implementation target for that issue and is not equivalent to the project Meta-Spec. “compact Spec” in code and prompts is its compatibility shorthand.
- **Implementation**: Actual changes to code, configuration, and tests.
- **Derived View**: A view generated from a Spec or code, such as `OVERVIEW.md` or `ARCHITECTURE.md`; it cannot instead be manually maintained as source data.

Use only one formal name for the same concept: use `Meta-Spec`, `SDD Spec`, `Objective Contract`,
`Implementation`, and `Derived View`. Do not call the Meta-Spec a “runtime Spec,” and do not conflate
Objective Contracts, Tasks, or Implementation approaches with SDD Specs.

Historical compatibility note: `RUNTIME.md` appearing in existing historical Specs or their Derived Views is the old maintenance document name,
which has been replaced by `META_SPEC.md`. Historical records retain the original wording to preserve decision traceability; new or modified artifacts MUST NOT continue to use
that name unless citing it in an explicit migration note.

### 2.2 Causal and evidence terms

The following fields follow the OpenAgents v0.2 causal Spec contract and use English snake_case:

- `ownership`: Which component actually owns the target behavior;
- `delivery`: How the change reaches the target component and execution path;
- `control_effect`: How the mechanism changes user-observable results, rather than merely being loaded or called;
- `evidence`: Source-code, configuration, execution, or test facts supporting a judgment;
- `assumptions`: Premises not yet confirmed by current evidence;
- `failure_modes`: Ways the mechanism may fail or appear to succeed;
- `scope_coverage`: The extent to which the original objective is included in the contract, taking `FULL`, `PARTIAL`, or `NONE`;
- `evidence_level`: The strength of evidence, taking `HYPOTHESIS`, `STRUCTURAL`, or `BEHAVIORAL`.

`scope_coverage=FULL` does not mean the feature has been implemented; effects not yet implemented can still be honestly represented using
`evidence_level=HYPOTHESIS`.

### 2.3 Topology terms

- **Spec topology**: The `depends-on` / `relates-to` relationships between Specs and between Tasks; source data resides in Spec frontmatter.
- **Code topology**: The import and docstring relationships in the actual code; generated by `spec graph`.
- **Execution DAG**: The execution graph calculated from issue dependencies and file conflicts during a particular v0.2 batch run; it is not a permanent Spec relationship.
- **Dependency relation**: Indicates that one node must wait for another; do not call every association a dependency.

### 2.4 Normative language

- **MUST / required**: Safety or an already committed external contract; changes MUST first explicitly establish a new contract and validate it;
- **SHOULD / recommended**: The currently recommended default practice, which a reasonable Spec MAY override;
- **MAY / permitted**: A permitted Implementation choice;
- **OBSERVED / current fact**: Behavior observed in code or tests, which does not automatically constitute a design requirement.

Unless marked `MUST` or `SAFETY`, the current files, symbols, and call chains in this document are only navigation information
and cannot be interpreted as a fixed Implementation checklist for the Developer.

### 2.5 Terminology is an evolution invariant

When adding or modifying the Meta-Spec, SDD Specs, Objective Contracts, role prompts, code documentation, and
Derived Views, the formal names, fields, and relationship terms defined in this section MUST be used. If a new term is genuinely needed,
first define its meaning, its level, its relationship to existing terminology, and transitional compatibility aliases in this section, then use it in other artifacts;
synonyms MUST NOT be silently created during iteration, nor may old terms be used to express new semantics.

## 3. Current product boundary

This artifact is a launchable terminal coding assistant. External clients send user
messages and receive status, progress, and final replies through a process protocol; internally, it uses NexAU Agent to execute model calls and tool operations.
Clients should not depend on the internal agent topology.

The current primary call chain is:

```text
params.yaml
  -> entry.py
      -> agent.yaml / agents/main.md
          -> NexAU Agent.run
              -> configured tools / workspace
      -> protocol reply, status, progress and usage events
```

This is a guide to the current Implementation; it does not require retaining the same filenames or invocation methods in the future.

The terminal state of a request is determined using NexAU's `after_agent` stop reason and `after_tool` completion-tool result,
not inferred from a nonempty reply, error text, or the model's own account. `completed` means only that this run successfully submitted an answer through
`complete_task`; it does not prove that the task is correct or has passed objective acceptance. Iteration/context boundaries,
replies that do not invoke the completion tool, and missing execution evidence are marked `incomplete`, with partial results and the session retained for the user
to continue; runtime errors are marked `crashed`, and user interruptions are marked `interrupted`. Output messages use `type`
to distinguish replies, progress, status, and errors; the final reply contains `text`, `status`, and
`termination_reason`. Clients MUST read the terminal state and MUST NOT treat receipt of a reply
as evidence of success. This determination does not extend the budget, automatically add problem-solving rounds, or change the existing iteration,
model-request, tool, or token limits.

### Autonomous and interactive execution conditions

After receiving a clear objective, execution should proceed autonomously; subsequent user input is an optional channel for control, authorization, and supplemental information, and it must not be assumed that the user will send a continuation.
The runner provides stable task_id/message_id, followup_input, and an explicit task budget in the message.
At enqueue time, remaining_budget_seconds anchors a local monotonic deadline; only an earlier deadline is permitted for the same task;
queuing, control, subsequent input, or reconnection cannot renew the lease. The wall timestamp is used only for auditing.
After the deadline, only cancellation, preservation of partial results, and cleanup are allowed; no new problem-solving calls may begin; the stop is marked incomplete with a reason.
When human input availability is undeclared, keep it unknown; do not infer a budget. A builtin_command acknowledgment for a built-in command belongs only to that message
and does not indicate task completion. The final task reply is associated with task_id/message_id and contains valid status/termination_reason.

Currently, max_iterations=100 and max_tokens=32768; a long outer budget does not guarantee that the model will exhaust it.
max_context_tokens is an input threshold and can be explicitly lowered; static checks of declared total capacity do not amount to reliable dynamic token measurement or compression.
An identifiable deterministic context overflow returns incomplete, without adding a retry of the same full Agent.run;
the SDK itself may already have made multiple HTTP attempts, and diagnostics need to distinguish these two layers. The native asynchronous cancellation path remains available.

## 4. Repository skeleton

| Path | Current responsibility | Change guidance |
|---|---|---|
| `params.yaml` | Declares the launch command and external protocol name | Changes may affect the launcher/client |
| `entry.py` | Process entry point, protocol adaptation, request lifecycle, reply packaging | Main intersection of user-visible behavior and NexAU adaptation |
| `agent.yaml` | NexAU Agent configuration, model parameters, tool bindings, sandbox type | Can be adjusted as needed; do not treat current values as a permanent solution |
| `agents/main.md` | Agent product behavior and working guidance | Behavioral objectives are determined primarily by the issue Spec |
| `tools/*.tool.yaml` | Tool descriptions and tool contracts | Tool implementations may come from NexAU or this repository |
| `HELP.md` | End-user documentation of commands and observable behavior | Review alongside changes to user-visible behavior |
| `scripts/` | Local launch, smoke-test, and check entry points | Prefer reusing these as validation entry points |
| `tests/` | Behavioral and protocol regression tests for the harness itself | New behavior should add observable regression coverage |
| `docs/specs/` | SDD design artifacts (if this harness uses this directory) | Put specific decisions, history, and acceptance in the corresponding Spec |

## 5. Ownership and changeability

The following table describes current responsibility assignments, not boundaries that prohibit modification:

| Surface | Current primary control points | Current nature |
|---|---|---|
| Launch and input protocol | `params.yaml`, `entry.py` | `COMPAT`: Can be changed, but client impact must be explained |
| session, interrupt, queuing | `session_id` / `agent_id` in `entry.py` and the NexAU Agent interface | `OBSERVED`: Can be refactored; user semantics need to be preserved or redefined |
| Model and tool execution | NexAU Agent, `agent.yaml`, tool binding | `CURRENT`: Both the harness and NexAU can be modified |
| workspace location and write scope | `SANDBOX_WORK_DIR`, sandbox configuration | `SAFETY`: Can be redesigned, but boundary violations and side effects MUST be validated |
| Replies, status, progress events | `entry.py`, tracer, `HELP.md` | `COMPAT`: Can be changed, but validation and client agreements must be updated |

Meaning of the labels:

- `SAFETY`: Current safety requirements; changes require explicit safety impact and tests;
- `COMPAT`: An external compatibility surface; changes require migration or an explicit new contract;
- `CURRENT`: Current responsibilities or integration methods, which can be rewritten by a new Spec;
- `OBSERVED`: Implementation facts observed in source code/tests, which do not automatically constitute design requirements.

Do not turn “current control points” into “changes can only ever be made here.” The actual judgment comes from the current issue's
causal chain, repository evidence, and acceptance results.

## 6. Evolution principles

### 6.1 Shared principles

1. Establish a minimal usable model of the current system before proposing changes; the Meta-Spec helps avoid starting from an ungrounded state.
2. Do not automatically treat historical implementations, current filenames, or existing call chains as permanent architecture.
3. Both the harness and NexAU can be modified; cross-repository changes must make the new ownership, delivery, and validation surfaces explicit.
4. The SDD Spec or Objective Contract is responsible for the current objective and design tradeoffs; the Meta-Spec provides only long-term context and navigation.
5. Source code, tests, and actual execution results take precedence over an outdated Meta-Spec; correct the documentation when conflicts are found.
6. Do not duplicate all of NexAU, the entire repository, or the local details of every issue for the sake of documentation completeness.
7. Terminology conventions are an evolution invariant: all subsequent artifacts use the formal names and fields in this document; terminology changes MUST first update the glossary and explain compatibility relationships.

### 6.2 Spec Writer

- Focus on the causal chain leading to the target outcome; do not treat “the file exists, the prompt is referenced, or the configuration is loaded” as proof of effect.
- Distinguish behavioral ownership, actual delivery, and control effect.
- Evaluate candidate solutions using the same evidence standard, and make assumptions, failure modes, and independent means of falsification explicit.
- Current judgments in this document may be overturned; cite new source-code, execution, or test evidence when doing so.

### 6.3 Developer

- Use the frozen Objective Contract (v0.2) or the corresponding SDD Spec as the objective contract for the current work, and use this document as project navigation; do not mechanically copy the existing Implementation.
- Locate the actual control points before deciding whether to modify the harness, NexAU, or both.
- Do not abandon a better design merely because this document describes a current state; if shared boundaries change, update the Spec and this document.
- Modify only the scope needed to achieve the objective, and validate the results with relevant tests or black-box behavior.

### 6.4 Acceptance

- Focus on user-observable behavior and actual execution results, rather than checking only whether files, functions, or prompts exist.
- For compatibility surfaces such as protocols, safety boundaries, and session, validate the new contract after the change rather than assuming that old behavior is always correct.

## 7. How to use and update this file

When starting work, first read the structural outline, ownership, and relevant role principles in this file; then still verify the source code, dependencies, and tests according to the issue scope. This document does not replace necessary in-depth investigation.

Update this document only in the following cases:

- Project-level startup flows, responsibility boundaries, or key control points change;
- The harness/NexAU integration approach changes;
- Protocols, workspace, security, session, or user-visible behavior establish new long-term contracts;
- Stable facts or historical pitfalls are discovered that would repeatedly lead subsequent developers to incorrect judgments.

Do not normally update this document for the following changes:

- Internal refactoring that leaves the control plane and behavior unchanged;
- Local implementation details of a single issue;
- Temporary experiments, parameter tuning, or one-off troubleshooting information.

Keep updates narrowly scoped: describe the current state, control locations, and verification basis; do not expand new implementation details into permanent constraints. Code and the Meta-Spec should be submitted in the same change, and acceptance verification should confirm that the documentation does not mislead subsequent development. Changes involving terminology MUST also check the affected Specs, role materials, and Derived View to avoid undeclared alternative names for the same concept across different artifacts.

## 8. Specs and topology

The SDD Spec carries feature-level detailed decisions and history; the v0.2 Objective Contract is the frozen objective for a single issue; the Meta-Spec retains only the shared map across issues.
Adding a Spec does not require rewriting this entire document.

If the project uses OpenAgents' Spec tools:

- Spec source data in `docs/specs/` is rendered into `OVERVIEW.md` through `spec render`; the cross-feature dependency/relationship graph in it should be re-rendered along with the Spec source data;
- `spec graph` generates `ARCHITECTURE.md` from actual code imports and docstrings; it is a code topology, not a Spec relationship graph;
- In v0.2, `docs/objectives/issue-*.md` contains frozen contracts for individual issues; the batch DAG is computed dynamically at runtime based on issue dependencies and file conflicts, and is not equivalent to a permanent repository-wide Spec topology.

Therefore, as Specs grow, the affected Spec relationship sources should be updated and the corresponding views regenerated; update this file only when the project-level structure or shared principles change.

## 9. Known gaps

- This file describes the current baseline and may lag behind unmerged branches; in the event of a conflict, the current code, tests, and latest approved Spec take precedence.
- The actual version, public interfaces, and internal implementation of NexAU may change; when dependency control points are involved, the version and source code loaded by the current interpreter still need to be checked.
- The existing file layout is a navigation aid, not an implementation checklist that the Developer MUST follow.
- Progressive upgrades to the Meta-Spec (automatically expanding or refining the shared map through multiple rounds of experiments) are deferred. Until an independent SDD Spec, explicit ownership/delivery/control_effect, and controlled experiments are established, do not continue adding one-off experimental observations or local details of individual issues to this file.
