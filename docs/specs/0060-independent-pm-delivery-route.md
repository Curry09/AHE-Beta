---
number: "0060"
title: "Independent PM route and dual-track delivery coordination"
issue: 0
slug: independent-pm-delivery-route
summary: "PM hands off independently to Owner and is excluded from Architect inputs and evidence authorization; Architect synthesizes delivery-route proposals; Owner explicitly associates shared work and preserves independent acceptance."
tasks:
  - id: T1
    title: "Dual-track role boundaries and coordination contract"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/ahe_beta/demand/owner.py
      - backend/ahe_beta/demand/agent_contract.py
      - backend/ahe_beta/loop/orchestrator.py
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/tools/submit_admission.tool.yaml
      - backend/agent_defs/architect/tools/submit_rfcs.tool.yaml
      - CLAUDE.md
    scope: "Exclude PM from Architect inputs and evidence authorization; Owner annotates delivery_overlaps without subsuming independent goals."
    acceptance: "PM proposal/ready items do not enter Architect inputs; PM references are rejected as invisible sources, and covers cannot close PM items; Owner preserves independent handoffs."
  - id: T2
    title: "Role and cross-round observation regression tests and experiment auditing"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/tests/demand/test_role_contract_flow.py
      - backend/tests/demand/test_owner.py
      - backend/tests/demand/test_observation_provider.py
    scope: "Verify lossless dual-track handoffs and cross-round reads after renaming and format changes; audit real evidence gathering across two sessions, distinguishing read compatibility from gaps in automatic publication."
    acceptance: "Relevant tests pass; record evidence-gathering effectiveness and semantic limitations by role; do not misreport two sessions on a single version as a multi-round closed loop."
---

# 0060 · Independent PM route and dual-track delivery coordination

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level rust-RFC overview in 9 sections. -->

## Summary

Restore the independent product route: PM → Owner, converging with Triage → Architect → Owner. Architect does not read
PM proposals, cannot reference or close PM items, and cannot rewrite PM product insights as structural proposals. Owner identifies
shared work across routes and expresses it through associations and independent acceptance, without restoring product-value review or arbitrary semantic merging.

## Motivation

In the 0059 two-session experiment, all three PM proposals were absorbed into structural proposals. Synthesis reduced duplicate reports, but also meant
PM product goals could enter delivery only as structural solutions. For example, “redirect work, query progress, and control investigation effort at any time” was
further unified under stage boundaries, although the evidence did not establish that these capabilities had to share those boundaries. Independent discovery does not imply independent delivery.

## Guide-level explanation

The first beat still runs Triage and PM in parallel, the second beat runs Architect, and Owner then receives both routes in a batch.
Independence here concerns semantic routing and delivery eligibility; it does not promise an immediate early Owner invocation when PM finishes.

Architect sees only open proposals and ready work items from the delivery route. PM provenance is `from-divergent`;
historical `divergent` is also filtered out, including admitted PM work items. The absence of structural outputs, Architect failure, or
model overreach does not eliminate PM. Existing cross-proposal synthesis requirements remain, without additionally computing a “number of non-PM sources”.

Owner uses optional `delivery_overlaps` to reference visible proposal/ready items and explains shared work
and each item's acceptance boundaries in the handoff. Two related issues with different goals are admitted separately; associations do not create dependencies, close issues, or automatically
schedule a shared implementation. The delivery side decides task decomposition and implementation reuse.

## Reference-level explanation

The Architect driver filters out PM by provenance before assembling any inputs; normal invocations and protocol recovery invocations reuse
the same filtered result. ProposalView, ready items, referenceable sources, the covers set, and session authorization are all generated from that
result. If the model independently references a PM issue number, existing source checks return `foreign-source` and record
`rejected_proposals`; no PM-specific source-counting rules are added. Valid structural issues inherit only the sessions of visible
sources they reference. A PM-only session does not become authorized for Architect evidence gathering merely because a PM issue exists.

Owner's schema adds the optional integer array `delivery_overlaps`. The driver filters out self-references, reports, unknown issues,
and non-integers, and records invalid metadata without discarding the handoff because of an invalid coordination field. Associations are saved with handoff comments,
preserving the automation identity. The existing exact-duplicate compatibility path remains unchanged; non-exact duplicates still cannot merge.

T1 changes responsibility prompts, schemas, drivers, and architecture documentation; T2 verifies overreach protection, real-model replay with fixed outputs, and
cross-version observation reads. For currently reproducible checks, see [Verification methods](../VERIFICATION.zh-CN.md).

## Drawbacks

The number of delivery issues may increase, and OpenAgents still needs to consume handoff comments and coordinate shared implementations. Associations can only explicitly express overlap;
they cannot mechanically guarantee that the model finds all overlap or that the delivery side avoids duplicate development. Routing changes alone also cannot automatically eliminate PM's tendency to express ideas in technical terms.

## Rationale and alternatives

Continuing to let Architect absorb PM wholesale is rejected because it ultimately compresses two cognitive perspectives into a single structural language.
The initial version of this group used “may be referenced but not subsumed”, then changed to input isolation following user clarification: Architect does not need to read PM first
and then comply with a set of usage exceptions. Product and structural perspectives converge only at Owner, without restoring additional value review or implementation-level arbitration.

## Prior art

0029 distinguishes discovery/delivery, and 0043 preserves PM's product perspective. 0052 assigns absorption of open sources to Architect;
this group narrows its inputs and permissions to exclude PM and adds Owner associations for delivery across routes. The 0059 evidence tools remain unchanged;
Architect authorization is still derived from visible proposal references and therefore narrows with input filtering.

## Unresolved questions

The new prompts have not yet undergone real-model dual-track comparison or post-delivery outcome evaluation. The closed loop for production artifact observation publication, version verification, and
legacy package retention from 0059 is not automatically completed by this group either; this group audits that gap without deploying the experiment-specific exporter to production.

## Future possibilities

Evaluate product-goal fidelity and duplicate delivery on the same fixed experience set, then run at least two rounds of “merge delivery → users try the new version” verification.
Artifacts are responsible for updating logs and documentation with each version; the platform is responsible only for a stable shell, restricted exports, version associations, retention, and authorization.
