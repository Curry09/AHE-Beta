# Reference: Harness-Seed Harvesting (source-specific rules for the thin extract-harness-seed skill)

This file contains only the extraction rules for `extract-harness-seed` sources: closed issues with
merged fix PRs and highly voted Q&A. It covers oracle tiers, harbor reproducibility tiers, difficulty
calibration, harvesting mechanics, and examples. **The card field schema, enums, domain vocabulary,
two-gate principles, and held-out storage conventions are in the sole shared contract,
[`../seed-card-schema.md`](../seed-card-schema.md), and are not duplicated here.**

## 1. Identify capability from what the resolution proves was required

The taxonomy itself is in the contract's capability section. Label what the *resolution* reveals
the task truly requires, rather than its surface wording.

- `intent-inference`: an ambiguous request ("make it faster" / "doesn't work") whose fix reveals an intent that must be inferred or clarified.
- `correctness-edgecase`: a small fix dependent on subtle cases: off-by-one, null/empty, quoting, ordering, or races.
- `long-output`: resolution requires a whole-file rewrite, multiple files, or a large artifact. Tests truncation, missing chunks, and "the rest is unchanged" shortcuts.
- `tool-use-verification`: only running tests/builds/reproductions establishes correctness. Tests actual verification rather than merely claiming completion.
- `scope-discipline`: the merged fix is deliberately minimal; a tempting broader change would break neighboring behavior.
- `env-setup`: the task is making dependencies/build/configuration work: CI, packaging, or toolchains.
- `error-recovery`: the thread shows iteration, with a failed first fix and successful second fix. Tests an effective debugging loop rather than abandonment or idle repetition.
- `explanation-teaching`: the asker has limited capability; success means an answer they can act on.

A card may have 2–3 labels, but choose the **primary** capability it isolates most cleanly.

## 2. Oracle tiers: strongest to weakest, using the strongest supported by artifacts

See the contract's enum section for `oracle.tier` values. Sources and fidelity by tier:

| tier | Meaning | Harvest source | Automated | Fidelity |
|------|---------|----------------|-----------|----------|
| `executable-test` | A specific test that changes FAIL→PASS with the fix | Tests **added/changed** by the fix PR | ✅ | Highest |
| `test-suite` | Existing suite passes at the fix commit | Run suite @fix versus @parent | ✅ | High |
| `sandbox-run` | Scripted reproduction of expected output/behavior | Constructed from the issue's reproduction and expected behavior | ✅/partial | High–medium |
| `rubric` | Checklist of required properties | Requirements and accepted answer | ⚠️ judge | Medium |
| `llm-judge` | Compare harness output with a reference solution | Merged diff / accepted answer as reference | ⚠️ noisy | Low–medium |
| `none` | No harness-independent check: pure design/opinion | — | — | **Exclude** |

Prefer `executable-test`: a fix PR adding a regression test is an ideal seed.
`rubric`/`llm-judge` may be admitted, but cap `oracle.confidence` at `medium` and mark low fidelity.
The oracle must be **independent of the harness**: never define success using the harness's own output.
Record the **verbatim** resolution text in `provenance.resolution_quote`: test name, assertion, or key accepted-answer sentence.

## 3. Harbor reproducibility gate: tiers within the contract's second gate

| tier | Conditions | Action |
|------|------------|--------|
| `easy` | Single repo, standard package management, hermetic unit tests | Admit. |
| `medium` | Containerizable service (postgres/redis) or vendored data fixtures required | Admit; declare them in the env spec. |
| `hard` → **reject** | Live cloud, specific OS/hardware, huge datasets, live third-party APIs, flaky/timing/network tests | Reject, or downgrade the oracle to `rubric` and mark `env.reproducible: "hard-rubric-only"`. |

`env` is consumed by harbor: `base_image` / `repo_at` (parent commit SHA) / `setup` (deterministic, pinned) /
`test_cmd` / `external_deps` (`none`|`containerizable:[...]`|`live(REJECT)`) / `budget`.
**Pin everything**, including lockfiles and image digests. No "latest" and no unpinned network installation.

## 4. Calibrate difficulty and scope

- `difficulty`: `trivial|easy|medium|hard`, based on the fix's **conceptual depth**, not line count.
  A 3-line race-condition fix can be `hard`.
- `scope`: `single-file|multi-file|cross-module|repo-wide`.
- These determine **pairing**: raise `pairing_constraints.min_capability` with difficulty
  (`hard` ABI seeds require `expert`; `trivial` syntax seeds pair with `surface`).
  They also clarify **attribution**: low user experience on a `hard` seed may reflect task difficulty
  rather than a poor harness; the oracle disambiguates.

## 5. Harvest sources and outputs

| Source | Best use | Oracle yield | Notes |
|--------|----------|--------------|-------|
| Closed issue + **merged fix PR with tests** | Gold-standard seeds | `executable-test` | SWE-bench recipe, **not benchmark** instances |
| Merged fix PR without tests | Logic seeds | `test-suite` / `sandbox-run` | Run suite @fix versus @parent. |
| Accepted / highly voted SO answer | Lower-tier and how-do-I seeds | `sandbox-run` / `rubric` | Pair with blind/surface personas. |
| Feature request + implemented PR | `scope-discipline` seeds | `rubric` / `test-suite` | Check reproducibility. |

Collect in the same domain as personas so seeds and personas can be paired by domain,
but harvest them **from different instances** and exclude held-out benchmarks.

## 6. Harvesting mechanics: operator SOP

**Two field classes, two rules:** transcribe FACT fields verbatim or derive them with commands; never invent them.
Judge JUDGMENT fields using §1–§4 of this skill. The contract's card-shape comments map fields to sources.

### 6.1 Discovery queries: find high-quality artifacts

First establish the domain from the harvested repository: it is a FACT.
Then find a **merged PR that closes an issue and adds/changes tests**:

```bash
# 1. Merged PRs in a repo that reference a closed issue
gh search prs --repo pytest-dev/pytest --state closed --merged \
  --match body "fixes #" -L 50 --json number,title,url,closedAt
# 2. Keep only those changing test files (executable-test candidates)
gh pr view <N> --repo pytest-dev/pytest --json files \
  -q '[.files[].path | select(test("(^|/)tests?/|test_.*\\.py$"))]'
```

### 6.2 `repo_at`: derive the parent, unfixed commit with commands; injection requires a resolved SHA

The state to reproduce is base-before-merge: the merge commit's first parent.

```bash
MERGE=$(gh pr view <N> --repo OWNER/REPO --json mergeCommit -q .mergeCommit.oid)
gh api repos/OWNER/REPO/commits/$MERGE -q '.parents[0].sha'   # -> repo_at (resolved 40-character SHA)
```

**Resolve `repo_at` to a real SHA during harvest.** Leaving `<parent-commit-...>` or another placeholder
in the card means harvesting is incomplete. 0010/T2 injection **rejects placeholders**, exposing the
problem at injection rather than waiting for materialization to fail. The commit checked for PASS is `MERGE` itself.

### 6.3 `not_in_benchmark`: machine-check, never assume

- **Date rule:** admit only when the PR's `merged_at` is later than the benchmark collection cutoff.
  SWE-bench instances generally predate that cutoff.
- **ID rule:** load the benchmark instance table and assert that `f"{repo}-{issue_number}"`
  and the SWE-bench `OWNER__REPO-NNNN` form are **absent**.

Record which rule passed. If neither can be evaluated, **do not** set `true`: withhold the card.

### 6.4 `external_deps`: read rather than guess

```bash
gh pr diff <N> --repo OWNER/REPO | grep -E '^\+\s*(import|from) '   # Test dependencies
ls .github/workflows && grep -RnE 'services:|postgres|redis|docker' .github/workflows
```

Only stdlib/in-repo dependencies → `none`; containerizable postgres/redis or similar services →
`containerizable:[...]` (repro `medium`); live cloud / third-party APIs / devices / specific OS →
`live(REJECT)` (reject or downgrade under §3).

### 6.5 Reproduce once: the real S7 check, beyond the validator

```bash
git clone https://github.com/OWNER/REPO && cd REPO
git checkout <repo_at>      && <setup> && <test_cmd>   # Expected: fail
git checkout <merge_commit> && <setup> && <test_cmd>   # Expected: pass
```

Only `FAIL@parent → PASS@fix` proves that `repo_at`/`test_cmd`/`oracle` are trustworthy.
A mismatch means a FACT is wrong: correct it rather than admitting the card.

## 7. Examples

### A — admit: easy, executable-test

A closed dbt-core issue: long-name generic test nodes lose `depends_on`; the merged PR adds
`test_long_name_resolution`. A single repo, pip installation, and hermetic tests make it easy;
a FAIL→PASS test supplies an executable oracle. **Admit.**

### B — reject: not reproducible

A Spark-on-AKS issue reproduces only against live Azure Cosmos DB. Live cloud cannot be provisioned
deterministically in harbor. Emit a rejected card:
`{"reject_reason": "harbor_repro_gate: requires live Azure Cosmos DB + AKS", "action": "not admitted; if env-setup coverage is sparse, find an equivalent in-repo hermetic instance instead"}`.

### C — admit: rubric oracle, low fidelity

An accepted SO answer explains warning about unsaved edits before leaving a React page.
There is no single repo/unit test, but the accepted answer defines required properties.
`sandbox-run` is unavailable, so use a `rubric` oracle with `oracle.confidence: medium`,
`env.reproducible: hard-rubric-only`, and `gates.harbor_repro_gate: downgraded`.
**Admit with low fidelity.**

## 8. Library coverage

As with personas, the real object is a **distribution**, here over `domain × capability`.
Track filled cells: a capability with no reproducible seeds is a harness blind spot.
Do not over-harvest one repo/capability. Fill underrepresented cells, especially
`tool-use-verification` and `long-output`, which the old text-only simulation could not stress-test.
