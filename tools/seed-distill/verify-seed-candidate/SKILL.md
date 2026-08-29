---
name: verify-seed-candidate
description: >-
  Independently audit and reproduce an extracted seed candidate, verifying
  provenance, prompt non-leakage, benchmark exclusion, hermetic setup, and a
  meaningful base-fail/fix-pass oracle. Use as the admission gate; do not repair
  or rewrite the candidate being reviewed.
---

# Verify a Seed Candidate

Act as an independent, fail-closed auditor. Do not inherit the Scout or Extractor's conclusions. Review
only the candidate bundle and primary artifacts, then reproduce the claims in a clean isolated workspace.

When available, use [`../seed-card-schema.md`](../seed-card-schema.md) as the shared contract. Do not rely
on the repository's current `validate_card` alone; independently check the requirements below.

## Independence and mutation boundary

- You must not be the agent that scouted or extracted this candidate.
- Do not rewrite prompts, patches, SHAs, labels, or environment recipes to make the candidate pass.
- Minor verifier-only diagnostic commands are allowed, but any required candidate correction produces
  `changes_required` or `rejected`, not an in-place repair.
- Never run untrusted project code outside the approved sandbox/container boundary.

## Static audit

Verify:

- all required fields, enums, URLs, 40-character SHAs, unique ID, and artifact hashes;
- issue/trace↔resolution relationship from primary platform metadata;
- `prompt_raw` predates the resolution and `prompt_injected` contains no solution/test-derived leakage;
- exactly one primary capability and difficulty in `medium | hard`;
- causal scope is isolated and the solution patch does not bundle unrelated changes;
- benchmark exclusion is tied to named snapshot digests and covers source IDs, repo+commit, text
  similarity, and patch hashes;
- environment dependencies and image/toolchain identifiers are pinned.

Any missing FACT provenance, wrong source link, easy task, benchmark match, or prompt leakage is a hard
rejection.

## Reproduction audit

In two fresh workspaces using the same environment recipe:

1. restore the base snapshot and apply `oracle.patch` only;
2. confirm setup and test collection succeed;
3. run the oracle and require a product-behavior assertion failure;
4. restore the fix snapshot and apply the exact same `oracle.patch`;
5. run the same command and require success;
6. repeat at least twice; repeat three times for concurrency, timing, or nondeterministic-risk tasks.

Classify failures explicitly. `test-not-found`, collection, import, setup, timeout, network, crash caused
by the harness, or flaky outcomes are not valid base failures. The base failure must exercise the stated
behavior, and the fix success must not depend on a different test or environment.

Record command, environment digest, exit code, duration, stdout/stderr hashes, failure class, and attempt
number. Preserve full logs as artifacts without exposing solution/oracle content to the training side.

## Decision

Return exactly one status:

- `verified`: every hard gate passed and repeated reproduction is stable;
- `changes_required`: source is promising, but extraction artifacts must be regenerated;
- `rejected`: authenticity, benchmark, difficulty, oracle, causality, or reproducibility cannot satisfy
  the batch rules.

Do not use current harness performance, issue yield, or expected training value to make this decision.

## Verification report

```json
{
  "candidate_id": "candidate-owner-repo-issue",
  "verifier": "<agent-or-run-id>",
  "status": "verified",
  "source_audit": {"passed": true, "evidence": []},
  "prompt_audit": {"passed": true, "evidence": []},
  "benchmark_audit": {"passed": true, "snapshots": []},
  "environment_audit": {"passed": true, "digest": "..."},
  "oracle_attempts": [
    {"snapshot": "base", "failure_class": "assertion", "exit_code": 1},
    {"snapshot": "fix", "failure_class": "none", "exit_code": 0}
  ],
  "difficulty": "medium",
  "primary_capability": "tool-use-verification",
  "rejection_reasons": [],
  "report_hash": "..."
}
```

Give the Coordinator the report and immutable artifact references. Only the Coordinator's deterministic
batch selector may publish a verified candidate into the admitted library.
