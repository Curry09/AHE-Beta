---
name: extract-seed-candidate
description: >-
  Convert one evidence-backed seed candidate into a reviewable seed bundle with
  faithful prompt provenance, separated oracle and solution patches, fixed
  commits, and a reproducible environment recipe. Use after scouting and before
  independent verification; do not approve or publish the seed.
---

# Extract a Seed Candidate

Turn a Scout candidate into artifacts that another agent can verify independently. You may inspect the
resolution, but resolution-derived information must never leak into the user-visible prompt.

When operating inside auto-designer, read [`../seed-card-schema.md`](../seed-card-schema.md) and the source
mechanics in [`../extract-harness-seed/reference.md`](../extract-harness-seed/reference.md).

## Inputs

- one structured Scout candidate record;
- access to the primary issue/trace and resolution artifacts;
- the frozen benchmark exclusion manifest;
- the batch environment and runtime budget.

Reject the candidate if its source relationship cannot be verified or its task is actually trivial/easy.
Do not repair missing source facts by guessing.

## Prompt boundary

Produce both:

- `prompt_raw`: immutable pre-resolution user text or a source snapshot reference;
- `prompt_injected`: the minimal user-visible request derived only from information available before the
  resolution.

Do not add root-cause analysis, solution structure, regression-test details, edge cases discovered only
in the fix, or acceptance criteria learned from the PR. Record every removal or normalization in a
`prompt_transform` log. If a faithful prompt cannot be formed, reject the candidate.

## Source and commit extraction

- Machine-check the issue↔fix relationship.
- Record immutable base and fix commit SHAs and the merge strategy.
- Do not assume the merge commit's first parent is always a fully unfixed state. Identify a base state
  that precedes all causal fix commits, then leave final confirmation to the Verifier.
- If a PR contains unrelated commits, isolate the minimal causal fix commit/patch or reject it.

## Oracle separation

Create two distinct artifacts:

- `oracle.patch`: tests or a deterministic reproduction only; no solution code;
- `solution.patch`: the causal solution patch, stored only for provenance and verification.

The same `oracle.patch` must be applicable to both base and fix snapshots. A regression test newly added
by the PR is not an oracle until it has been separated and can be applied to the base snapshot. Do not
claim `FAIL@base -> PASS@fix`; that assertion belongs to the independent Verifier.

## Environment recipe

Prefer a hermetic recipe with:

- image digest rather than a floating image tag;
- pinned interpreter/toolchain;
- lockfile, wheel/cache, or dependency digest;
- deterministic setup commands;
- explicit external services and runtime/memory budget.

Reject live cloud/API, unavailable hardware, unpinned network-only setup, or an environment that cannot
fit the batch budget. Do not treat `pip install -e .` alone as a reproducibility proof.

## Benchmark exclusion bundle

Record checks against the exact frozen snapshots using all available identifiers: source URL, issue/PR
ID, repo+base commit, problem-text similarity, and oracle/solution patch hashes. A date-after-cutoff check
is supporting evidence, not sufficient on its own.

## Output bundle

Produce a directory or manifest containing:

```text
candidate-card.json
prompt-source.json
oracle.patch
solution.patch
environment.json
benchmark-exclusion.json
artifact-hashes.json
```

The candidate card must set `status: ready_for_independent_verification`; it must not set `admitted` or
claim that either gate passed. Include exactly one `primary_capability`, difficulty `medium` or `hard`,
and provenance pointers for every FACT field.

## Completion report

Report extracted artifacts, unresolved facts, prompt transformations, merge/base selection reasoning,
environment risks, and any reason the Verifier should fail closed. Never substitute confidence language
for missing evidence.
