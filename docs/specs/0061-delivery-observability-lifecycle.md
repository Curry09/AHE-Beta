---
number: "0061"
title: "Development-side observation use and the artifact log evolution loop"
issue: 0
slug: delivery-observability-lifecycle
summary: "Artifacts maintain diagnostic logs and version documentation, while the platform provides restricted evidence packages; gaps in maintainer evidence gathering lead to diagnostic enhancements, while user-facing status feedback goes through ordinary product proposals; feature designs describe the two types of impact separately and verify them independently."
tasks:
  - id: T1
    title: "Artifact-owned observation packages starting from NexAU"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/entry.py
      - backend/harness_template/observability.py
      - backend/harness_template/OBSERVABILITY.md
      - backend/harness_template/tests/test_observability.py
      - backend/tests/harness/test_template_entry.py
      - backend/harness_template/params.yaml
    scope: "Connect the seed's existing tracer to artifact-owned file outputs and documentation without relying on external scripts wrapping private functions; internal event formats may evolve."
    acceptance: "Normal operation, errors, interruptions, retries, and exit can be located using the documentation; recording failures do not change task results, resources are bounded, and sensitive data is not exported."
  - id: T2
    title: "Session collection, version binding, and historical retention"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/runtime.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/harness/launcher.py
      - backend/ahe_beta/observations/publication.py
      - backend/ahe_beta/observations/__main__.py
      - backend/ahe_beta/demand/observation_provider.py
      - backend/tests/observations/test_publication.py
    scope: "Establish the observation output directory at startup, collect files according to a restricted manifest before container cleanup, and have the platform bind them to the actual session and artifact version, verify publication integrity, and retain old packages."
    acceptance: "Attempt collection for both normal and abandoned sessions; crashes leave an explicit missing status; validate paths, sizes, and version digests, and do not overwrite earlier rounds."
  - id: T3
    title: "Development evidence handoff across containers"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/owner.py
      - backend/ahe_beta/demand/delivery_evidence.py
      - backend/ahe_beta/observations/grants.py
      - backend/ahe_beta/tracker/gitea.py
      - backend/tests/demand/test_delivery_evidence.py
    scope: "Publish audited delivery evidence packages from authorized references in admission issues; provide resolvable handles through the existing Gitea boundary, avoiding host paths and full session mounts. Platform-level gaps must not be misrouted to the harness queue."
    acceptance: "Development containers can locate the package for the corresponding version; references survive merges and truncation; permission failures result in explicit degradation, and external-link downloads and privilege escalation are prohibited."
  - id: T4
    title: "Observation responsibilities in development design, implementation, and review"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/META_SPEC.md
      - backend/deploy/vigil/observability-overlay.Dockerfile
      - backend/deploy/vigil/observation-runtime.json
      - OpenAgents/openagents/runtime/engine.py
      - OpenAgents/openagents/runtime/context.py
      - OpenAgents/openagents/recipes/stages.py
      - OpenAgents/openagents/recipes/vigil.py
      - OpenAgents/openagents/utils/gitea.py
      - OpenAgents/openagents/observations/evidence.py
      - OpenAgents/tests/test_observation_evidence.py
    scope: "Delivery roles read version-matched evidence as required by the task; functional contracts separately describe the impact on user feedback and diagnostic observation, implementation maintains the corresponding outputs, records, documentation, and tests, and the two types of objectives undergo independent acceptance. Cross-repository changes must be delivered separately and the pin updated."
    acceptance: "Do not mix evidence from old and new versions; separately verify the information visible at user decision points and the diagnostic questions for maintainers; explain the reason when there is no impact; do not add a new permanent review role."
  - id: T5
    title: "Diagnostic observation gap proposals and recoverable submission"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/observations/gaps.py
      - backend/ahe_beta/observations/delivery_gaps.py
      - backend/ahe_beta/demand/agent_runtime.py
      - backend/ahe_beta/demand/triage.py
      - backend/ahe_beta/demand/divergent.py
      - backend/ahe_beta/demand/architect.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/agent.yaml
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/agent.yaml
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/architect/agent.yaml
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/agent.yaml
      - backend/agent_defs/triage_agent/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/divergent_pm/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/architect/tools/submit_observation_gap.tool.yaml
      - backend/agent_defs/owner/tools/submit_observation_gap.tool.yaml
      - backend/tests/observations/test_gaps.py
      - OpenAgents/openagents/observations/gaps.py
      - OpenAgents/openagents/v02/openagents_adapter.py
    scope: "Both requirements and development roles can submit gaps in evidence gathering for maintainer diagnostics; the platform deterministically creates ordinary proposals, preserving the source, component, reason, and acceptance criteria. Insufficient user feedback goes through ordinary product proposals, not the diagnostic enhancement entry point; retries are idempotent and do not write back to frozen objectives."
    acceptance: "Neither type of requirement imposes a prerequisite gate on the other; user feedback and diagnostic enhancements have independent acceptance and status records; PM source isolation is maintained; retries of the same submission do not create duplicate issues; offline requests are submitted after restart."
  - id: T6
    title: "Cross-round and alternative harness verification"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/tests/observations/fixtures/alternate_v1.py
      - backend/tests/observations/fixtures/alternate_v2.py
      - tools/dev/replay/replay_observation_lifecycle.py
    scope: "First run a synthetic two-round test, then deliver an actual observation enhancement and recheck it in a session using the new version; use a non-NexAU starting point to verify that the platform does not parse internal events."
    acceptance: "Close the loop from a v1 gap through proposal, Owner, and delivery to actual v2 observations; retain old packages; include negative cases for leaks, out-of-order data, missing packages, budgets, and malicious input; do not use benchmarks as development signals."
---

# 0061 · Closing the Loop on Development-Side Observation Use and Artifact Log Evolution

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level nine-section rust-RFC overview. -->

## Summary

Logging is an evolvable harness capability, not an external platform adaptation to the current runtime. The NexAU starting point uses its existing
tracer to generate observation files and documentation; other harness starting points replace the artifact-side implementation. The platform fixes only the collection,
version association, retention, and authorization boundaries. Design and development roles use this evidence as needed, and when they encounter confirmed observation gaps,
both can submit ordinary enhancement proposals to improve the capability through the existing Owner and delivery processes.

Feature development separately considers “how users understand the current situation and decide what to do next” and “how maintainers reconstruct what happened, distinguish causes,
and verify changes.” Observation enhancements in this group refer specifically to the latter; the former belongs to user-side status feedback in 0035 and ordinary product requirements.
This does not require every change to add logs, prescribe a unified internal event dictionary, or add a permanent log review role.

See the task table for implementation status; see `docs/VERIFICATION.zh-CN.md` for currently reproducible checks.
Engineering closed-loop verification and whether real models actively and effectively use observations are two kinds of evidence; neither can stand in for the other.

This clarification of objective boundaries has been synchronized to role prompts, diagnostic tool field descriptions, proposal titles, and development context; 70 existing observation,
role handoff, and template entry-point regression checks passed, as did 15 OpenAgents observation regression checks. These verify wiring,
compatibility, and existing behavior; they do not prove that real models now reliably distinguish the two types of requirements, and the earlier controlled closed-loop test does not replace that verification.
The new delivery image was checked in a container with no network or host mounts to verify the installed source digest and context for eight role types;
historical verification records are available in Git history, and the version is recorded in the deployment pin; running experiments were not replaced.

## Motivation

The current NexAU harness already has `_StepCollector`, which outputs runtime information through steps/progress/usage.
The ObservationProvider from 0059 can already read artifact files using a session's manifest, but the seed
observation mechanism has not been fully wired into automatic publication for every round, nor has restricted evidence transfer usable by delivery containers been delivered. The recent two-session experiment
filled this gap by additionally wrapping internal functions and copying files during container finalization; it verified reading, not completion of production integration.

Developers currently receiving proposals, session references, and worktrees does not mean they have readable logs from that historical version.
Absolute host paths are unavailable in the vigil container; the current worktree also does not necessarily match the version at the time of the event.
If fixes are written solely from textual root-cause descriptions, or outdated log documentation is retained when refactoring a feature, roles in the next round may still misjudge the situation.

At the same time, inability to find information is itself a capability gap that can be improved. Proposing an enhancement must not require first proving the root cause using missing logs,
and discoverers must not be left merely writing “insufficient evidence” in an answer without an entry point for subsequent delivery.

## Guide-level explanation

### 0. Two Types of Objectives and Proposal Entry Points

| Category | Audience and judgment supported | Requirements entry point | Acceptance |
|---|---|---|---|
| User-side status feedback | Users understand the current situation during use and decide whether to wait, add requirements, interrupt, or accept | Existing Triage or independent PM ordinary product proposals | The information actually visible at decision time is accurate, timely, and supports the required judgment |
| Design- and development-side diagnostic observation | Maintainers reconstruct what happened, distinguish causes, and verify changes | `submit_observation_gap` or development-side diagnostic request files | Authorized evidence for the corresponding version can answer specific diagnostic questions |

Classification depends on whom the information serves and what judgment it supports, not on the discoverer's role or the underlying event source. When a PM's own investigation
lacks internal evidence, the PM submits a diagnostic enhancement; when a PM finds that users cannot understand the status, the PM submits a product proposal. “Both sides” in this document refers to
the requirements design side and the development delivery side, not users and maintainers; `observation-gap` and the tool name remain compatibility identifiers for the diagnostic entry point,
without adding category fields or a semantic classifier.

For example, during the same long wait, users need timely information about the current situation and available actions, while maintainers need to distinguish normal
execution, call failures, and recovery afterward. Adding logs does not automatically improve user feedback, and adding status messages does not automatically fill gaps in diagnostic evidence.
The two types of requirements can stand independently: insufficient user feedback does not require prior proof of an internal root cause, and diagnostic gaps do not require prior proof of user dissatisfaction.
Use the existing blocking/revision mechanism only when specific work actually depends on another item; do not automatically establish prerequisites by category.

The two may share event sources and a single delivery, but the handoff preserves their respective objectives and acceptance criteria; when one issue contains both types of objectives,
list their acceptance criteria separately. Related separate issues retain their own statuses; splitting issues is not mandatory, and completing one item does not close the other.

### 1. Responsibilities of the Three Parties

| Party | Responsible for | Not responsible for |
|---|---|---|
| harness artifact | What to record, when to record it, association semantics, file formats, documentation, overhead, and redaction; evolving together with the implementation | Turning current event names into permanent platform fields |
| Iteration framework (fixed before the experiment starts) | Providing the output location, prechecking storage and attachment capabilities, collecting declared files, binding trusted versions/sessions, safely retaining evidence, and handing it off according to task authorization | Inferring internal processes by wrapping fixed private functions, interpreting all logs uniformly, or becoming part of harness self-evolution |
| Design and development roles | Gathering evidence for specific questions, distinguishing facts from interpretations, identifying gaps, and implementing and verifying enhancements | Treating log counts as quality scores or treating missing records as proof that behavior did not occur |

### 2. How the Development Side Uses Observations

| Stage | How observations are used | Results to retain |
|---|---|---|
| Spec Writer / Drafter | Read the documentation for that version through the issue's restricted evidence entry point and investigate facts that affect solution selection; do not reread all logs by default | Known facts, unverified assumptions, behavior to change, and observation impact |
| Architect (when enabled in the process) | Check whether evidence can distinguish candidate root causes and whether the current log structure is being mistaken for an implementation requirement | Verification methods that can falsify a solution; necessary enhancement proposals or REWORK reasons |
| Developer | Compare historical evidence with current code and reproduce relevant behavior; maintain affected events, documentation, and tests when implementing features | Functional and observation changes in the same delivery, or an explanation of why observations need no changes |
| Reviewer / test verification | Actually locate execution using the documentation for the corresponding version, and verify behavior and diagnostic distinguishability | Behavioral evidence, observation evidence, and negative-case results; do not substitute “logs exist” for functional success |

Within existing sections, the SDD Spec / Objective Contract for new features separately describes “user feedback impact” and
“diagnostic observation impact”: the former explains what users need to know and when, and what decisions this supports; the latter explains what maintainers need to
reconstruct or distinguish and whether existing evidence is sufficient. Describe changes and verification separately for each. When there is no impact, give a brief reason; do not
force the addition of events or fixed tables. Implementation synchronously maintains affected user outputs/help, diagnostic records/reading documentation, and
regression tests; sharing a tracer does not mean that both objectives are complete.

Log-based evidence gathering does not replace source-code and black-box verification: for example, the appearance of “cancelled” proves only that the record was emitted; it is still necessary to verify
that the task actually stopped and queue handling meets the objective. New diagnostics must also not turn functionality that must take effect in real time into waiting for a stage to end.

### 3. Both Requirements Design and Development Delivery Roles Can Identify Diagnostic Gaps

| Discoverer | Typical trigger | Existing boundaries remain in effect |
|---|---|---|
| Triage | When investigating a single report, cannot distinguish the state after failure, waiting, or interruption | Use only the current report's authorized evidence |
| PM | Cannot compare user behavior with internal evidence or assess a particular user experience difference | Independent PM route to Owner; do not turn product opportunities into fixed event solutions |
| Architect | Lacks distinguishing evidence when verifying a shared mechanism across multiple delivery-route proposals | Investigate only sessions from visible sources; do not use the enhancement entry point to read PM material or discover unrelated requirements |
| Owner | Upstream handoff materials lack resolvable references, versions, or information needed to judge completion | No additional permission to read raw sessions/logs; the gap is based on the handoff materials themselves |
| Development, architecture, review, and verification roles | Cannot reproduce behavior, distinguish hypotheses, confirm the effect of changes, or verify recovery boundaries | Use only evidence authorized for the current issue and test evidence they produce themselves |

Everyone follows the same process: define the question → read the documentation and relevant records for that version → distinguish “not found” from “not recorded” →
confirm the gap and submit an enhancement proposal. A search that happens to miss something, insufficient permissions, or files not yet published must not all be interpreted as missing harness
events; nor is unlimited searching required before acknowledging uncertainty.

### 4. What an Enhancement Proposal Looks Like

This is an ordinary diagnostic capability proposal, with the compatibility marker observation-gap and the title “Diagnostic Observation Enhancement”;
it adds no new work plane or dedicated admission shortcut. User feedback requirements still go through ordinary product proposals and must not enter this entry point solely because “users do not know
what is happening.” question, impact, and verification should clearly state the questions maintainers need to answer,
the judgments affected, and diagnostic verification; users receiving progress messages must not count as diagnostic acceptance.
For example:

> Determine whether execution after a user interrupt belongs to the old request or a new one.
> The session manifest, descriptions, and relevant execution intervals have been inspected,
> but the existing records lack correlation information that distinguishes the two, so it is
> impossible to verify whether the old request resumed. Maintainers should be able to distinguish
> request ownership, termination, and subsequent execution. Verify this in a controlled scenario
> where old and new requests coexist; do not prescribe a request_id field, state machine, or
> storage format in advance.

The proposal retains: the question investigated, source version and references, scope already examined, cases that remain indistinguishable, impact on judgments,
expected diagnostic capability, and verification scenarios. It can be valid even when the root cause is unknown; the objective is to add the ability to distinguish cases, not to assert the root cause of the original problem.

The discoverer submits an independent gap request, and the platform creates an ordinary proposal and returns the issue number. PM sources retain from-divergent
and do not go to Architect; other sources retain the source role and relationship to the original issue. Gap proposals are not subject to Architect's
submission contract for “synthesizing multiple proposals,” because they are capability requests arising from a single restricted evidence-gathering failure, not
new structural synthesis outputs, and they grant no additional evidence-gathering scope.

When insufficient coverage is clearly identified, leave a proposal; if an equivalent proposal already exists, add evidence and reference it. Do not close a proposal on the basis that “we have already written
one log entry”; verify that the target phenomena can actually be distinguished.

## Reference-level explanation

### A. Artifact Logging Starting Point and Publication Boundary

The first version integrates the existing NexAU tracer inside the harness; the experiment wrapper no longer replaces `_make_step_collector`
or `_run_supervised`. The artifact itself decides how to add implementations or migrate to other runtimes or multi-agent implementations.
This group provides a default recording scope only for the NexAU seed: model/tool activity, request execution, error recovery, interruptions, and
exit, with accompanying explanations of what the records can and cannot prove; this is not an event schema that all future harnesses must share.

The launcher provides the dedicated output directory HARNESS_OBSERVATION_DIR, and the artifact declares
`observations: artifact-observations-v1` in params.yaml; older artifacts without a declaration return not_supported rather than pretending logs exist.
The artifact writes a file manifest and reading documentation there. The output directory is a collection contract, not an interface through which log contents can initiate execution
or read host files. The artifact manifest declares only relative files; the platform ultimately packages a manifest readable by 0059.

The platform binds the session, actual harness commit, runtime/image pin, and run identifier from the runtime control plane;
it must not blindly trust the version reported by the artifact itself. The package's stable envelope includes the file manifest, reading entry point, content digests, and integrity status;
log fields and filenames belong to that artifact version. Old and new packages coexist; old packages are not rewritten into a new format, and newly added documentation must not
retroactively masquerade as the original documentation of an old version. Publication retries are idempotent; different runs of the same session have separate run identifiers and do not overwrite old packages.

Finalization for normal completion, abandonment, errors, interruptions, and timeouts attempts bounded collection before container cleanup; when export fails, record the reason
and do not disguise a missing package as empty logs. Crashed, truncated, or unfinished content is marked partial/unavailable; only
packages that have completed validation become fully available entry points. Logging errors must not turn product behavior into success, and continuous logging must not
exhaust disk space or block exit indefinitely. When necessary, prioritize retaining bounded metadata and explicitly identify the scope of discarded/sampled content.

Before user interaction begins, the framework checks storage read/write access, remaining space, the recovery backlog, Gitea attachment capabilities, and repository write permissions,
binds the observation root directory to the current repository, and refuses to reuse authorized data from other repositories. Publication uses temporary directories and atomic switching,
digests, and idempotent run IDs; failures midway do not damage old versions. Collection retries are bounded; on failure, stop and retain the original container/local source,
write a recovery receipt, and do not delete the only remaining incident state first; an explicit recovery command reuses the original identity. An excessive backlog requires maintenance before the next startup,
rather than unlimited retries during user interaction. Permanent fault-free operation of disks/daemons cannot be promised, but hidden failures must not be used to pretend the loop is closed.

The platform checks relative paths, symbolic/hard links, file counts and sizes, archive extraction safety, and digests; exports do not include
raw credentials, hidden persona prompts, benchmark gold/oracle, or task answers. Redaction only at display time is insufficient;
the artifact records minimally by default, and filtering is repeated at the publication boundary. User behavior evidence uses existing authorized projections; the full session database is not delivered.

### B. Evidence Handoff from the Requirements Side to Development Containers

Owner still sees only references and is not responsible for downloading logs. For an admission issue, the platform resolves its trusted source references and generates a restricted evidence
manifest: historical artifact versions, authorized sessions/files, digests, reading entry points, and reasons for unavailability. A model writing a new
session_id in the body must not expand permissions; authorization must be traceable to the authorized set of that source invocation. References must survive long-body truncation
and sources becoming merged/closed.

Prefer publishing filtered evidence attachments and indexes within the existing Gitea instance. The delivery runner retrieves them according to the issue manifest into a separate
evidence directory, then provides the agent with ordinary file reading and search entry points. Do not mount the entire host observations or sessions
root directory for development agents, or put large packages/raw traces into harness main. The attachment API, size
limits, and deployment pin are verified through real integration. The current implementation uses the issue assets API and bounded gzip JSON text packages;
both compressed packages and decompression have byte budgets, and attachments are named by content digest. Issue the delivery token only after publication and read-back validation succeed; on failure, retain
the proposal and archive, and retry the same attachment at the next ordinary admission without automatically bypassing delivery. Entries exceeding the transfer budget are explicitly unavailable;
the original bounded packages remain in the platform archive, and text is not silently truncated.

Retrieval allows only the configured Gitea origin and objects authorized for that issue, verifies digests, and extracts safely; it does not follow
arbitrary external links or execute scripts inside packages. Credentials are managed by the runner and are not written into issues, files, or model input. Access has
retrieval records by role/issue/package and digests of authorized files. Actual reading through ordinary file tools is different from downloading/granting access;
a download receipt must not be passed off as proof that a role has understood the evidence. Packages retained by the platform are immutable evidence, and the development side reads copies in isolated directories;
if a copy is modified, digest verification prevents it from serving as original evidence.

Historical evidence and the current worktree are both labeled with versions. New logs generated by developers in their own tests are bound to the current head;
logs from after a fix cannot prove what happened before the fix. Keep test paths, redacted projections, and source-code drift explicitly distinguished.
Additional evidence gathering selects only from the existing authorization manifest; Developer curiosity does not open access to all user records in the same repository.

This design extends the existing Gitea handoff boundary; it does not add a public log service. Related OpenAgents changes are submitted separately
to its repository and the build pin updated; an ahe-beta spec does not mean deployed OpenAgents has been modified.

### C. Gap Proposal Submission, Routing, and Recovery

The design side provides the non-terminal submit_observation_gap diagnostic enhancement capability; after submission, the original role output must still be completed. It only records
the gap, references, and scope; it does not directly create ready or modify other issues. Owner may reference only handoff materials when using it.
The development side returns gap requests through delivery reports/automation comments with an equivalent structure, and the platform processes them from authenticated run sources,
without treating arbitrary user comments or forged JSON in logs as system submissions.

The platform persists submissions idempotently by submission request ID and returns an issue-number receipt; when the API is temporarily unavailable, retain a durable outbox and retry after restart or in the next
round. An agent's final sentence alone cannot justify claiming that an issue was successfully created. Both sides may first document uncertainty and continue evidence-supported work.
Whether different requests are semantically duplicates is determined by the existing proposal coordination process; string similarity is not used to automatically delete independent diagnostic capabilities.

Gaps must distinguish three areas of ownership:

- The harness does not record/associate/document the required facts: an artifact observation capability proposal, following the normal Owner→OpenAgents route;
- The iteration framework did not export data, permission mapping is incorrect, or historical files are missing: infrastructure diagnostics and maintenance receipts; the framework is fixed during the experiment,
  so do not create a harness proposal, apply openagents, or require harness developers to exceed their permissions to repair the framework;
- The original logs can already answer the question and only retrieval or version location is missing: locate them first; if there is an actual documentation/discoverability defect, propose the corresponding enhancement.

Do not automatically elevate all observation proposals to P0 or expand the recording scope because there are many proposals. Expected diagnostic outcomes, actual
impact, and verification necessity determine priority. After proposals enter the work queue, they still pass through normal engineering quality and scope constraints.

The design-side schema is in observations.gaps, and the four-role YAML has a drift guard. The PM origin and subsequent
Owner/developer enhancements retain from-divergent according to the trusted source; enhancements must not route them back to Architect. Architect's original
evidence access comes from source authorization saved by the framework, not from a session_id added to model-generated text. Historical
issues without trusted authorization must not acquire permissions from text; such migrations must reconstruct authorization from trusted session/call origins.

If the original feature can be implemented and verified independently using other evidence, observability enhancements may proceed in parallel, with independent acceptance for each;
if the gap prevents safe solution selection or proof that the objective is met, explicitly state why the original task is blocked and make the enhancement a prerequisite delivery. Do not silently
expand a frozen Objective Contract. Changes to dependencies or task splitting must use existing contract revision and delivery planning mechanisms; this group
does not dynamically insert new proposals into a running DAG or bypass the current-round delivery gate in 0050.

When an enhancement is already within the current change scope, still reference its proposal and include its tasks and acceptance in the same formal delivery without implementing it twice.
After the enhancement is merged, ask the original diagnostic question again in a reproduction/session on the new version; facts missing from the original logs cannot be fabricated retroactively.
Closing the enhancement and closing the original feature fix are two separate determinations.

### D. Delivery verification and task boundaries

T1 implements the artifact starting point; T2 implements platform collection; T3 implements cross-container handoff; T4 integrates developer roles and artifact development specifications;
T5 integrates proposals from both sides; T6 verifies the complete loop. Task files are expected control points, not a freeze on the future harness file layout.
The OpenAgents/ prefix denotes delivery scope in a separate repository; do not create a vendor copy with the same name in AHE-Beta.

Verification layers:

1. Engineering regression: normal/error/interruption paths, log budgets and failure isolation, integrity, unauthorized access, malicious paths,
   version mismatches, duplicate submissions, and offline retries; PM input isolation and Owner's lack of raw observation access must continue to hold.
2. Joint behavior and observability tests: the same user-visible symptoms with different internal conditions must be distinguishable using the documentation shipped with the version; also verify that
   success messages in logs cannot conceal product failure. Missing or sampled records must preserve uncertainty.
3. Synthetic cross-round test: insufficient v1 records → each side proposes gaps separately → Owner/delivery → v2 format and documentation → development and design
   read the same authorized package; the old version remains accessible. A non-NexAU fixture changes fields/files without modifying platform parsing code.
4. Real infrastructure loop: at least one enhancement is actually merged, followed by a new-version user run/controlled reproduction using a sealed SHA; record
   whether the original diagnostic question becomes answerable and the functional outcome. Two sessions using the same version cannot substitute for this layer.
   This controlled verification uses scripted role decisions, real Docker/Gitea/PR merges, and installed development images; it is neither
   long-running autonomous model evolution nor end-to-end acceptance of the vigil engineering quality gate. The report must clearly distinguish these.

CI verifies only engineering behavior and security contracts; the benchmark remains held-out throughout and is not used as a training signal for log selection, proposals, implementation,
or release gates. User experience is observed; the experience gate is not reinstated.

## Drawbacks

Recording, storage, and queries all add cost. Artifacts must maintain diagnostic documentation, the platform must handle redaction, retention, and attachment failures,
and cross-repository pin updates also add integration work. An observation package is not an omniscient record; limited samples cannot prove that a root cause is uniquely valid.
Enhancement proposals may crowd out feature work, so they must center on actual investigative questions rather than pursuing “record everything.”

Attachment access isolated only to the current experiment repository/controlled runner does not amount to a complete multitenant authorization system; if shared
user data is delivered across tenants in the future, identity isolation must be designed separately without relaxing this group's authorization boundaries.

## Rationale and alternatives

Artifact-owned logging is chosen over platform-wide instrumentation because only the current implementation knows which events are meaningful, and changing the starting point
should also replace the recording approach. A stable platform envelope preserves collection and read compatibility without freezing the internal schema.

Do not continue retaining experiment scripts that wrap private functions: this would prevent logging capabilities from updating with normal delivery. Nor is a new
logging service integrated by default; reuse the existing Gitea handoff boundary first. If measured capacity proves unsuitable, design content storage separately rather than
temporarily mounting the entire host dataset. Platform output of bounded packages does not require roles to fix their query methods in advance.

Do not add a log analysis/review role or let only Developer discover gaps: reasoning during design may also be constrained.
Having both sides propose specific enhancements during their existing work and advance them through the same proposal and delivery mechanisms is more direct than adding a separate inspection process.

## Prior art

0059 provides on-demand reading of artifact files, with the platform not interpreting event fields; 0060 preserves the independent PM route, and Architect
does not read PM. 0032/0033 separate requirements from container delivery; 0045 fixes toolchain pins; 0050 proceeds to the next round only after delivery is finalized.
The current Meta-Spec already requires development based on ownership/delivery/control_effect and
behavioral evidence. This group explicitly incorporates observability into those responsibilities without replacing the objective contract.

The logging entry point in the latest real experiment was placed in a harness copy, but release depended on experiment scripts; it is a useful NexAU
starting-point verification reference, not proof that the six tasks above have been implemented.

## Unresolved questions

The actual Gitea attachment API and cross-container access to private repositories have been confirmed through controlled verification; deployment updates must still use the recorded image pins.
Byte budgets, retention periods, and historical-version retention costs must be determined from actual package sizes and expressed as configuration rather than hardcoded in
role prompts. Output does not depend on a specific event schema, but release envelope upgrades still require compatibility verification.

Running legacy experiments are not replaced. New code connects to the common engine and covers the independent v0.2 Developer, Spec Writer,
Acceptance, and traditional Drafter/Architect/Implementer/Reviewer; new production experiments must select the corresponding images and updated seeds.
Dynamic DAG insertion during execution is not introduced for now;
how critical enhancements are split into independent prerequisite deliveries uses the existing blocking/revision paths and is confirmed through controlled verification.

## Future possibilities

Future comparisons may examine “diagnostic question answerability, incorrect attribution, missing-package rate, additional overhead, and repeated investigation time” before and after enhancements,
without optimizing for log volume. If another harness starting point changes only artifact recording and documentation and can be used by both sides without changes to platform event
parsing, that validates this group's evolution boundary.
