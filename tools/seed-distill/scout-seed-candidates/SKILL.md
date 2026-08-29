---
name: scout-seed-candidates
description: >-
  Discover real, resolved, non-benchmark medium or hard seed candidates for an
  assigned domain and capability slice, preserving raw source evidence. Use for
  candidate scouting only; do not author prompts, build seed cards, reproduce
  oracles, or approve candidates.
---

# Scout Seed Candidates

Find candidate source artifacts. Your output is an evidence-backed candidate queue, not a seed library.
Do not extract a final card and do not claim that a candidate is reproducible or admitted.

When available, use the source mechanics in
[`../extract-harness-seed/reference.md`](../extract-harness-seed/reference.md) and the controlled domain and
capability vocabulary in [`../seed-card-schema.md`](../seed-card-schema.md).

## Inputs

Require an assignment containing:

- allowed domains;
- primary-capability gaps;
- candidate target and stopping condition;
- allowed difficulty (`medium | hard` only);
- benchmark exclusion manifest or frozen dataset identifiers;
- allowed source types and runtime/environment limits.

If the exclusion snapshot is missing, candidates may be marked `needs_exclusion_check` but never
`not_in_benchmark=true`.

## Discovery priorities

Prefer, in order:

1. a closed issue linked to a merged fix PR that added or changed a focused regression test;
2. a resolved real user/agent trace with a recoverable workspace and outcome;
3. a feature request with an implemented PR and focused acceptance evidence;
4. an accepted Q&A/support artifact with a deterministic sandbox oracle.

Reject obvious easy tasks, pure opinions, live-cloud/hardware-only failures, flaky/timing-only reports,
unresolved artifacts, and PRs that mix several unrelated product changes.

Do not search only for `correctness-edgecase`. Follow the assigned primary-capability gaps. A candidate
may have several apparent capabilities, but propose exactly one primary capability based on what the
real resolution shows was essential.

## Evidence rules

- Use primary sources. Record immutable issue, PR, commit, trace, or answer URLs.
- Capture the issue/user text that existed before the resolution. Do not rewrite it into a specification.
- Keep `raw_prompt_excerpt` verbatim and within applicable quotation limits; otherwise store a source
  pointer plus a faithful local snapshot reference.
- Verify the issue↔PR relationship from platform metadata or explicit closing syntax. Similar titles are
  not evidence.
- Record whether test files changed, but do not infer that the test passes or fails.
- Perform only preliminary benchmark checks. Record the exact snapshot/check used; do not rely on
  memory or a vague date claim.
- Do not use knowledge of current harness failures to choose candidates.

## Candidate output

Emit one JSON object per candidate:

```json
{
  "candidate_id": "candidate-owner-repo-issue",
  "assignment_id": "scout-a",
  "source_type": "closed_issue+fix_pr",
  "repo": "owner/repo",
  "issue_url": "https://...",
  "fix_url": "https://...",
  "merged_at": "ISO-8601",
  "raw_prompt_source": "issue body/comments before resolution",
  "raw_prompt_excerpt": "verbatim or snapshot reference",
  "changed_test_files": ["tests/..."],
  "proposed_domain": "dev-tooling",
  "proposed_primary_capability": "tool-use-verification",
  "proposed_difficulty": "medium",
  "difficulty_evidence": "short evidence, not a line-count guess",
  "preliminary_benchmark_checks": [
    {"snapshot": "<name+digest>", "method": "issue-id", "result": "no-match"}
  ],
  "possible_blockers": [],
  "status": "candidate_only"
}
```

## Stop conditions

Stop when the assigned candidate target is reached, primary sources become unavailable, or further
search would require expanding beyond the assigned domains/source types. Report shortages instead of
filling them with easy, synthetic, unresolved, or unverifiable tasks.
