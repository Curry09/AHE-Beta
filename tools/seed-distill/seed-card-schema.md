# Seed Card Schema — Sole Public Contract (hub)

> This file is the **sole source-agnostic public contract** for seed scenario distillation. All “thin extraction skills” (spokes,
> such as `extract-harness-seed/` and future `extract-log-seed/` / `extract-so-seed/`) describe only
> “harvest a seed card from a particular type of real source + pass two gates + ground specified fields”; **the field schema / enums /
> vocabulary / card shape / two-gate principles / held-out field storage conventions must all reference this file**, with no dependencies on one another. Change the contract in one place,
> and it applies to all; adding a new real source requires only a new thin skill, without touching the others.
>
> Corresponding spec: `docs/specs/0010-seed-scenario-pipeline.md` (T1 collection, T2 injection into SeedSource).
> The injection mapping from card → `models.SeedScenario` (including held-out field stripping) belongs to `0010/T2` (`card_to_seed`),
> outside this contract. This is a symmetric mirror of the persona-side [`../persona-distill/card-schema.md`](../persona-distill/card-schema.md);
> the `domain` vocabulary and persona `D5.area` share the same 14 token controlled vocabulary.

## Hard Rules

1. **Hub-and-spoke**: This file is the hub, and extraction skills are spokes. Spokes depend only on this contract; **spokes do not depend on one another**
   (preventing skill→skill references and schema drift across multiple copies).
2. **Harvest, do not author**: Seed cards are distilled from **resolved** real artifacts (closed issue + merged fix PR,
   highly voted Q&A). That real-world resolution *is* the ready-made oracle—you transcribe it, not invent it. Never fabricate tasks.
3. **Non-benchmark**: `source.not_in_benchmark` is always true—never harvest cards from held-out benchmark instances
   (which would contaminate training and test targets). This is a **contract-level hard constraint**; `validate_card` rejects violating cards before ingestion.
4. **Preserve real requests as originally expressed (do not sanitize)**: `task.prompt` preserves the user's actual wording and level of specification
   (including underspecification, ambiguity, and missing context)—*how a request is expressed* is itself a signal for stress-testing intent-inference.
5. **Collect held-out fields with the card; strip them at injection time**: `oracle`/`env.test_cmd`/`gates` are objective
   scoring artifacts on the benchmark side, faithfully captured with the card (for parallel evaluation on the harbor side), but stored in a sidecar when injecting into SeedScenario and **never enter
   the training loop** (this boundary is enforced by 0010/T2 and declared here in this contract; see §Held-out Field Storage Conventions).

## Card Record Shape

Each card is a JSON object; `source` · `task` · `oracle` · `env` are required; the remaining fields follow the table below:

```json
{
  "id": "seed-<repo-short>-<issue_number>",     // Stable deduplication key (source-hash / repo+issue)
  "source": {
    "type": "closed_issue+fix_pr",              // Source artifact type (see §Enums source.type)
    "repo": "owner/repo",                        // Actual source repository (owner/repo); plain-text sources may use "n/a"
    "issue_url": "https://github.com/.../issues/NNN",   // Optional
    "fix_ref": "https://github.com/.../pull/MMM (merged)",
    "not_in_benchmark": true                     // Always true (iron rule #3); otherwise validate_card rejects
  },
  "task": {
    "prompt": "The user's actual verbatim request (natural, possibly underspecified)",   // The original text injected into SeedScenario.description
    "context": "The minimal context a user would actually provide"
  },
  "domain": "dev-tooling",                        // Single token ∈ §domain controlled vocabulary (shared with persona D5.area)
  "capability_probed": ["correctness-edgecase"],  // ⊆ §capability taxonomy
  "difficulty": "medium",                          // ∈ §difficulty
  "scope": "single-file",                          // ∈ §scope
  "autonomy_required": "collaborative",            // ∈ §autonomy_required
  "oracle": {                                      // held-out (written to sidecar at injection time)
    "tier": "executable-test",                     // ∈ §oracle.tier
    "spec": "path::node（FAIL@parent → PASS@fix）",
    "reference_solution": "fix PR diff summary or url",
    "confidence": "high"                           // ∈ §confidence
  },
  "env": {
    "reproducible": "easy",                        // ∈ §env.reproducible
    "base_image": "python:3.11",
    "repo_at": "<parent-commit-sha>",              // Actual SHA of the parent (unfixed) commit; must already be resolved at injection time (placeholders rejected)
    "setup": ["pip install -e ."],                 // Deployment command; prefixed according to 0009/T3 venv at injection time
    "test_cmd": "pytest tests/test_x.py::test_y",  // held-out (written to sidecar at injection time)
    "external_deps": "none",                        // ∈ §env.external_deps
    "budget": {"timeout_s": 600, "mem_gb": 4}
  },
  "pairing_constraints": {"domain": "dev-tooling", "min_capability": "competent"},
  "gates": {"oracle_gate": "pass", "harbor_repro_gate": "pass"},   // held-out (written to sidecar at injection time)
  "provenance": {
    "resolution_quote": "A verbatim original sentence from closing PR/answer that defines success",
    "source": "https://github.com/.../pull/MMM"
  }
}
```

Shape of a rejected card (not ingested and does not enter the seed library):

```json
{"id": "seed-...", "reject_reason": "harbor_repro_gate: requires live Azure Cosmos DB",
 "action": "not admitted; if this capability is undercovered, look instead for equivalent instances of in-repo, hermetic"}
```

## Enums (controlled values)

```
source.type        : closed_issue+fix_pr | merged_fix_pr | accepted_so_answer | feature_request+pr
capability_probed ⊆ { intent-inference, correctness-edgecase, long-output,
                      tool-use-verification, scope-discipline, env-setup,
                      error-recovery, explanation-teaching }
difficulty         : trivial | easy | medium | hard
scope              : single-file | multi-file | cross-module | repo-wide
autonomy_required  : advisory | collaborative | agentic
oracle.tier        : executable-test | test-suite | sandbox-run | rubric | llm-judge | none(excluded)
confidence         : low | medium | high        (rubric/llm-judge capped at medium)
env.reproducible   : easy | medium | hard-rubric-only     (hard and cannot be downgraded → reject)
env.external_deps  : none | containerizable:[...] | live(REJECT)
gates.*            : pass | downgraded | fail(excluded)
```

### Capability Taxonomy

The library's actual focus is **coverage of the taxonomy** (the distribution of `domain × capability`), not a pile of tasks. Each card must have at least one
`capability_probed` label; a capability without a reproducible seed is a blind spot that the loop can never improve.

| capability | When to stress-test it | Failure exposed |
|---|---|---|
| `intent-inference` | Underspecified / ambiguous requests | Guessing instead of clarifying |
| `correctness-edgecase` | Success depends on subtle / edge cases | Seemingly correct but actually wrong |
| `long-output` | Large / whole-file / multi-file output required | Truncation, missing chunks |
| `tool-use-verification` | Correctness requires actually running / testing / verifying | Claiming completion without verification |
| `scope-discipline` | Only a minimal fix is appropriate; excessive changes break other things | Overengineering / collateral damage |
| `env-setup` | Dependencies / builds / configuration must be made to work | Cannot run |
| `error-recovery` | First attempt fails; a debugging loop is required | Giving up / spinning wheels |
| `explanation-teaching` | Low-skill users must be able to act on it | Correct but unusable |

### Domain Controlled Vocabulary (Shared with Persona D5.area)

`domain` takes a **single token** (so library coverage is measurable), determined by the repository where harvest occurs (FACT, not fabricated after the fact); for genuinely cross-domain cases,
use `cross-stack`. This is the same vocabulary used on the persona side, ensuring that seeds and personas can be **paired within the same domain**.

```
web-backend | web-frontend | scientific-computing | data-viz | ml-ai |
data-analysis | dev-tooling | data-eng | infra-devops | databases |
systems-runtime | security | mobile | cross-stack
```

## Two-Gate Principles

Every card must pass **two gates** before entering the library (both `gates.oracle_gate` and `gates.harbor_repro_gate` must be non-fail):

1. **oracle gate**: success must be **harness-independent** and decidable (ideally executable). Reject tasks that can only be judged by user experience. For tiers, see
   §Enums `oracle.tier`—prefer `executable-test` (regression tests added by a fix PR are ideal seeds); `rubric`/`llm-judge`
   are admissible, but `oracle.confidence` is capped at `medium` and marked low-fidelity; those without any harness-independent check (pure design/opinion)
   `tier=none`→**are not seeds**.
2. **harbor reproducibility gate**: harbor must be able to **deterministically** (a) set up the environment, (b) run the harness in it, and (c) run the oracle,
   all within budget. Disqualifiers: live cloud (AKS/Cosmos/BigQuery), specific OS (macOS), specific hardware
   (Android/GPU-only), very large datasets, live third-party APIs, flaky/timing/network tests. Containerizable services
   (postgres/redis) and vendored fixtures are admissible (tier `medium`). Non-reproducible → reject, or downgrade to a `rubric`
   oracle and mark `env.reproducible: "hard-rubric-only"`.

FACT fields (`repo_at`/`test_cmd`/`not_in_benchmark`/`resolution_quote`/urls/`external_deps`) are **transcribed verbatim from
raw tool output or derived from commands, never invented**; JUDGMENT fields (`task.prompt`/`domain`/`capability_probed`/
`difficulty`/`scope`/`oracle.tier`…) are determined according to the thin skill's criteria.

## Held-out Field Storage Conventions

`oracle` / `env.test_cmd` / `gates` are objective scoring artifacts on the **benchmark side**. They are **collected with the card** (for reuse in harbor-side
parallel evaluation), but when injecting `models.SeedScenario`, 0010/T2's `card_to_seed` **strips them into a sidecar**;
`SeedScenario` (and its `to_dict` / `{version, seeds}` envelope JSON) **never contains** these three keys.

In accordance with CLAUDE.md, “benchmark remains held-out throughout: it does not participate in training or release gating”—training signals come only from user experience on the distribution of “simulated real
usage”; objective oracle scoring belongs to the harbor-side parallel evaluation system, and the two are **physically isolated at the injection boundary**.
These fields are **retained** on the collection side (rather than discarded) so that seed cards can be reused for objective evaluation; held-out discipline is achieved through **stripping at the injection boundary**,
not by deleting fields on the collection side.

## Conformance Rules

1. `source` / `task` / `oracle` / `env` are required; `oracle.tier != none`.
2. `source.not_in_benchmark` is always true (iron rule #3; otherwise `validate_card` rejects).
3. `domain` ∈ §domain controlled vocabulary and is a **single token**; `capability_probed` ⊆ §capability taxonomy.
4. Admission to the library requires both gates `gates.oracle_gate` / `gates.harbor_repro_gate` to be non-`fail`; rejected cards are recorded only as
   `{reject_reason, action}` and do not enter the seed library.
5. `provenance.resolution_quote` is a **verbatim** original sentence from an actual solution artifact (evidence for the oracle).
6. Card records **must not** contain any benchmark score / trajectory-derived fields (reject any top-level key outside the whitelist).
7. On encountering unknown keys: readers are forward-compatible (ignore without errors and preserve unchanged), facilitating schema evolution (Postel's law).
