---
name: extract-harness-seed
description: >-
  Harvest one reproducible task seed (with a built-in oracle) from an
  already-resolved real artifact — a closed issue + merged fix PR, or a
  high-voted Q&A — to feed the seed library that drives the user → issue → experience
  loop. Use when building or expanding the seed library, sourcing real coding
  tasks for harness simulation, or auditing seed oracle/reproducibility quality.
  A seed = a real user demand + a harness-independent success oracle + a
  harbor-reproducible env, tagged by the harness capability it stresses. Emits
  the shared seed card defined in ../seed-card-schema.md (the single public
  contract); this skill is one thin "spoke" among future source spokes
  (extract-log-seed / extract-so-seed). It does NOT embed the schema/enums/gates
  — those live in the contract.
---

# Extract Harness-Seed

A **thin extraction skill (spoke)**: harvest **one seed card** from a **resolved real-world artifact** (closed issue + merged fix PR, accepted /
highly voted Q&A). The card schema / enums / domain vocabulary / two-gate principles / held-out field
storage conventions all come from the sole shared contract [`../seed-card-schema.md`](../seed-card-schema.md). This file describes only
**the source-specific details of harvesting from 'resolved artifacts', passing the two gates, and which fields to ground/transcribe**; it embeds no
schema and depends on no other skill.

It is the **WHAT + success criteria** half of `signal = persona × seed × judgment`: persona supplies WHO, seed supplies
the real task + objective oracle. Seeds and personas are **collected independently**, and paired downstream under constraints (domain match + credible capability +
autonomy fit) — pairing is outside this skill and outside the 0010 group.

> **Incorporation note**: This skill incorporates the established methods developed in NexAU repository `extract-harness-seed` (harvest, not author /
> two gates / decoupling from held-out), but **references only this repository's contract and does not copy NexAU's skill files**. The contract is defined by this repository's
> `seed-card-schema.md`.

## Core Principles (Specific to This Source; Refer to the Contract's Inviolable Rules for the Rest)

1. **Harvest, not author (the foundation of this source)**: Take cards only from **resolved** real-world artifacts. The actual real-world resolution
   *is* the established oracle — transcribe it, do not invent one. Regression tests added by the fix PR are the ideal oracle (FAIL@parent →
   PASS@fix, the SWE-bench recipe applied to **non-benchmark** instances). See contract inviolable rule #2.
2. **capability-first**: Retain only cards that stress-test a **distinct** harness capability (contract §capability taxonomy).
   The repository aims for **taxonomy coverage**, not a pile of tasks. Label `capability_probed` based on the real need *revealed by the fix*.
3. **Both gates are mandatory**: the oracle gate (success must be harness-independent and determinable) + the harbor reproducibility gate (the environment can be set up deterministically to run
   the oracle). For gate details, oracle tiers, and reproducibility tiers, see contract §Two-Gate Principles. If a card fails a gate, → produce a **rejected card**
   (`{reject_reason, action}`); do not add it to the repository.
4. **Preserve the original real-world request**: `task.prompt` preserves the user's original wording and level of specification (including underspecification / ambiguity / missing context);
   do not sanitize it into a clean spec. See contract inviolable rule #4.
5. **Non-benchmark + decoupled from current bugs**: Never harvest held-out benchmark instances (contract inviolable rule #3); nor harvest cards based on harness
   *currently known* bugs (otherwise they overfit today's failures rather than generalizable capabilities).
6. **FACT transcription / JUDGMENT determination**: `repo_at`/`test_cmd`/`not_in_benchmark`/`resolution_quote`/urls
   are transcribed verbatim from tool output or derived from commands (**never invented** — incorrect facts can silently reverse the oracle or prevent it from running);
   `task.prompt`/`domain`/`capability_probed`/`difficulty`/`scope`/`oracle.tier` are determined according to the criteria.

## Harvest Pipeline

```
Seed harvest progress:
- [ ] Select a target: (domain → its anchor repository) × (an under-covered capability)
- [ ] Find a RESOLVED artifact (closed issue + merged fix PR / accepted answer)—not a benchmark instance
- [ ] Extract task: natural request (retain messiness) + minimal context
- [ ] From the solved artifact harvest oracle; stratify; record reference_solution and resolution_quote
- [ ] Build env spec: base_image, repo@parent-commit (real SHA), setup, test_cmd, external_deps, budget
- [ ] oracle gate: Is success harness-independent and judgeable?
- [ ] harbor reproducibility gate: Can the environment be set up deterministically within budget and oracle be run?
- [ ] Calibrate difficulty/scope/autonomy_required; set pairing_constraints; produce cards in the shape of the contract
```

For the source-type vocabulary, oracle / repro tier tables, difficulty/scope calibration, harvest mechanics (discovery queries,
how to obtain `repo_at`, mechanical checks for `not_in_benchmark`, how to read `external_deps`, reproduce-once), and three examples
(admit / reject / rubric), see [reference.md](reference.md). For enums / domain vocabulary / card shape / the two gates /
held-out storage conventions, see [`../seed-card-schema.md`](../seed-card-schema.md).

## Report on Completion

Report: the `(domain × capability)` cell this card fills, oracle tier, harbor reproducibility tier, and difficulty. Prefer to **explicitly
reject** (oracle-less or irreproducible, producing a rejected card) rather than admit a card that cannot yield an attributable, runnable signal.
