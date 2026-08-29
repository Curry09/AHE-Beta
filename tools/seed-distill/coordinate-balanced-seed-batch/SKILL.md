---
name: coordinate-balanced-seed-batch
description: >-
  Plan and coordinate a balanced batch of real, non-benchmark seed scenarios by
  assigning non-overlapping search slices, tracking coverage, and selecting only
  independently verified medium or hard seeds. Use for seed-batch planning and
  multi-agent coordination; do not use to scout, extract, or verify individual seeds.
---

# Coordinate a Balanced Seed Batch

Coordinate the batch without performing candidate discovery, extraction, or verification yourself.
Keep those roles independent so one agent cannot admit its own work.

When operating inside auto-designer, read the shared card contract at
[`../seed-card-schema.md`](../seed-card-schema.md). User instructions override the default quotas below.

## Invariants

- Admit only real, resolved artifacts that are outside every frozen benchmark exclusion snapshot.
- Do not admit `trivial` or `easy` seeds. The allowed difficulty set is `medium | hard`.
- Do not select candidates because the current harness fails on them. Harness behavior may be used only
  for an operational smoke check after selection.
- Every seed has exactly one `primary_capability`; secondary capabilities do not satisfy batch quotas.
- A Scout or Extractor never approves its own candidate. Admission requires an independent Verifier
  attestation plus deterministic quota checks.
- Preserve rejected candidates and rejection reasons. Do not silently drop inconvenient evidence.

## Default batch target

For a 56-seed batch, use these defaults unless the user supplies another target:

- difficulty: 36 medium, 20 hard;
- domain: four seeds for each of the 14 domains in the shared contract;
- primary capability: seven seeds for each of the eight capabilities;
- scope: 16 single-file, 18 multi-file, 16 cross-module, 6 repo-wide;
- oracle: at least 40 executable-test seeds; the rest must use deterministic sandbox-run or test-suite;
- concentration: at most three admitted seeds per repository and five per organization;
- source diversity target: 36 issue+fix-PR, 12 real user/agent-log, 8 Q&A or support artifacts.

Treat these as batch constraints, not permission to fabricate a candidate to fill a cell. If a cell lacks
qualified candidates, report the shortfall and leave it unfilled.

## Workflow

1. Freeze a batch manifest containing the target counts, allowed source types, runtime budgets, and the
   exact benchmark manifests/digests to exclude.
2. Partition domains into non-overlapping Scout assignments. Give each Scout target primary-capability
   gaps and a finite candidate count.
3. Accept only structured candidate records from Scouts. Route candidates to Extractors; never let a
   Scout write the official seed library.
4. Route extracted bundles to Verifiers that did not scout or extract the same candidate.
5. Build the admitted set only from verifier-approved bundles. Use deterministic constraint selection;
   never change facts or labels merely to satisfy quotas.
6. Publish the selected batch, coverage table, exclusion snapshot, rejected set, and unresolved shortfalls.

## Scout assignment shape

```json
{
  "assignment_id": "scout-a",
  "domains": ["web-backend", "web-frontend"],
  "primary_capability_gaps": ["intent-inference", "tool-use-verification"],
  "difficulty_allowed": ["medium", "hard"],
  "candidate_target": 30,
  "benchmark_exclusion_manifest": "<path-or-digest>"
}
```

## Required handoff records

- Scout → candidate record with immutable source URLs and raw pre-resolution evidence.
- Extractor → candidate card, prompt provenance, test-only patch, environment recipe, and artifact hashes.
- Verifier → signed/hashed verification report classifying parent failure and fix success.
- Coordinator → batch manifest, selection report, coverage matrix, admitted IDs, rejected IDs and reasons.

## Completion report

Report exact achieved counts for domain, primary capability, difficulty, scope, oracle tier, source type,
repository concentration, and verification status. Explicitly list every unmet quota; do not describe a
partially filled batch as balanced.
