---
name: extract-github-persona
description: >-
  Extract behavior-first personas of real developers from their GitHub footprint
  (public repos, issues, and PRs) to drive simulated users of a coding-agent
  harness. Use when building or expanding the user-agent persona library at the
  competent/expert end, extracting a persona from a GitHub user or issue-reporter,
  or auditing observed-source persona authenticity. Emits the shared persona card
  defined in ../card-schema.md (the single public contract); this skill is one
  thin "spoke" among the observed-behavior spokes (Stack Overflow) and the
  self-report spoke. GitHub is an OBSERVED source: it reliably grounds only the
  capability (D1) and domain/stack (D5) axes; the attitude axes (D2 acceptance,
  D4 trust, D6 autonomy, D7 time temperament — and most of D3) are NOT visible
  in a footprint and default to injected priors. The authenticity gate is a
  trace-floor + cross-layer-consistency check, not a performative-content check.
  Read the "Limitations and Defects" section before treating any single card's attitude axes as real.
---

# Extract GitHub Persona

A **thin extraction skill (spoke)**: extracts personas from developers' **public GitHub footprints** (repos / issues / PRs)
for simulated users in a coding-agent harness. The card schema / enums / D5 vocabulary / injection distributions / authenticity adjudication vocabulary
all come from the sole public contract [`../card-schema.md`](../card-schema.md). This file describes only the source-specific aspects of **extracting from GitHub footprints as an observational source and determining which dimensions can be reliably grounded**; it does not embed the schema or depend on any other skill.

> **Naming**: The source skill is named `extract-cc-user-persona` ("cc" refers to the Claude Code /
> Codex-style harnesses these personas will drive), but **the actual extraction source is GitHub footprints**—so it was renamed `extract-github-persona` when incorporated into this repository,
> aligning with the `extract-<source>-persona` convention.

It complements `extract-stackoverflow-persona` (also observational, reading help seekers) and `extract-selfreport-persona` (self-reported,
reading how people describe their own workflows). GitHub reveals **what a person has done**—their coding capability and technology stack are visible,
but **not** how they steer an agent, how much they trust it, where they draw the acceptance line, or **how long they can tolerate waiting idly**. Thus, GitHub reliably grounds only
**D1 (capability) and D5 (domain/stack)**; the attitude/interaction axes **D2/D4/D6/D7 (and most of D3)** are largely silent in these footprints,
and **by default are injected and marked `confidence: low`** (see “Limitations and Defects” below).

## Core Principles (Reversal Relative to Self-Reported Spokes)

1. **Tool-independent: model only “who this person is and how they work.”** Never draw material from “how people use AI assistants,” and never include
   traces of AI generation. The persona models the person; the agent is handed to them only during the experiment.
2. **Observations are facts, but cover only D1/D5.** GitHub is an `observed` source: label dimensions that can be grounded `basis: "observed"`
   (look at what they do; hard evidence). But it **reveals only capability/domain**—do not treat “inferring trust or acceptance from CVE hygiene / auto-merge / comprehensive CI”
   as grounded; that is reviewer extrapolation, not a transcribed fact (see principle 4).
3. **Counts and stars are worthless.** issue/PR/repo counts, stars, and followers can all be inflated. Judge substance, never quantity. High volume
   is a **contamination warning**, not a quality signal: it is authentic only when the substance is deep and **consistent within a single domain**; high volume + incoherent cross-stack activity = `contaminated`.
4. **Attitude axes default to inject; do not infer grounded values from behavior.** D4 trust, D7 time temperament, and **D2 acceptance without firsthand statements**
   default to `source: injected` / `confidence: low`—`grounded` (basis `stated`) **only when the footprint contains the person's own firsthand statements about trust/acceptance/waiting**.
   This aligns with the position in `extract-selfreport-persona` that “self-reports are the real-person anchors for D4/D7.”
5. **Ground D1/D5 (`observed`); D2/D3/D4/D6/D7 default to injected.** See the table below and reference.md.
6. **Dimensions are orthogonal—never derive one dimension from another.** Same as iron rule #3 in card-schema.md. **In particular, do not** infer `impatient` from PR/commit speed or
   issue closure speed; do not bind `on_offtrack=fix-self` (the person submits the fix themselves) inseparably to `patient`—
   the two are independently injected/grounded.
7. **Same schema, strip PII.** Produce the card shape defined in card-schema.md (D1–D7 + `authenticity` + `era` +
   `provenance`); hash the handle into `id`, and store only the derived profile; use public verbatim quotes + source refs as `evidence_quotes`. Never store
   name/employer/location/email/social.

## Which dimensions GitHub can reliably ground (a complementary mirror of self-report sources)

| Dim | GitHub strength | Ground from (footprints) | basis / source |
|-----|-------------|------------------|----------------|
| **D1 evaluation_capability** | **Strong (verifiable)** | Technical depth of issue bodies (precise repro / root-cause reasoning) + actual substance of PRs (real logic fixes vs docs/version bumps) | `grounded` / `observed` |
| **D5 domain** | **Strong** (area+depth+stack) | Actual technical → `area` (controlled vocabulary) + `stack` (specific technologies) of repos/PRs; `depth` from substance | `grounded` / `observed` |
| **D3 interaction_style** | Weak→mostly injected | Only delegation can be **weakly observed** from how issues are written; on_offtrack=`fix-self` is `observed` only when **the person actually submitted a fix PR themselves** (quality-failure strategy, ≠waiting); supervision=process involvement, essentially unobservable from footprints → inject | Actual behavioral traces exist→`observed`, otherwise `injected` |
| **D2 acceptance_bar** | Weak→injected by default | `grounded` (basis `stated`) only when an issue/PR contains **the person's own firsthand acceptance statement** | Firsthand statement exists→`grounded`/`stated`, otherwise `injected` |
| **D4 trust_model** | None→injected by default | Cannot observe “how much they trust the agent” | Firsthand statement exists→`grounded`/`stated`, otherwise `injected` |
| **D6 autonomy_expectation** | None→injected by default | Cannot observe “what role they expect the agent to play” | `injected` |
| **D7 time_temperament** | None→injected by default | Footprints reveal almost nothing about “how long they can tolerate simply waiting”; deriving this from PR volume/commit frequency is **prohibited** | `injected` (`stated` only for an extremely rare firsthand statement about waiting) |

For `era`, use `owner.created_at` + activity dates (split around 2025-10), and cite the dates in `era.basis`.
**Injected dimensions do not carry `basis`**—`basis` describes only “how evidence was obtained for an already grounded value” (observed/stated); injection is a reviewer prior with no transcription basis.

## Workflow: L0–L5 recursive evidence-gathering pipeline

```
GitHub persona extraction progress:
- [ ] L-1 recruitment (optional)  → Choose a target profile → priority domain + pool（recruitment/）
- [ ] L0 profile             → Identity skeleton + era annotation（created_at）
- [ ] L1 repos (all)         → Technical fingerprint + output patterns (evidence)
- [ ] L2 key repo contents   → Engineering standards（tsconfig/CI/tests/release）——Note: this is behavior, not the person's own acceptance statement
- [ ] L3 cross-project issue bodies → D1 Depth signals; ground D2 only when there is a firsthand acceptance statement
- [ ] L4 cross-project PRs    → D1 Capability + D5 substance; on_offtrack=fix-self if the person actually submitted a fix
- [ ] L5 gate → (a) trace-floor, then (b) cross-layer consistency → adjudication
- [ ] Map: D1/D5 grounded(observed); D2/D4/D6/D7（+ most D3）inject and mark low (unless there is a firsthand statement)
      ——Sample D7 and on_offtrack independently; do not derive impatient from PR speed
- [ ] Strip PII, hash id, produce the card-schema.md card shape (must include D7_time_temperament)
```

A layer that returns 0 results (0 repos / 0 PRs) is **not** a grounding layer—do not write it into `provenance.layers`.
L-1 (recruitment) is decoupled and optional: see [`recruitment/`](recruitment/) (`domains.md` domain registration +
`swe-bench.md` / `terminal-bench.md` profiles). The profile determines only *whom to look at*, not how to rate the card.

For GitHub endpoints, D1/D5 evidence-gathering details, authenticity gate details (trace-floor + cross-layer consistency), attitude-axis injection, and three examples
(authentic / contaminated / insufficient_evidence), see [reference.md](reference.md). For enums / D5 vocabulary /
injection distributions / card shape / authenticity verdict vocabulary, see [`../card-schema.md`](../card-schema.md).

## Limitations and Defects (Content Quality Boundaries of Observational Methods)

GitHub footprints are an **observational** source, and their content quality boundaries must be recorded honestly—the attitude axes on an individual card **are not faithful to the real person's "attitudes"**:

- **Only D1 (capability) × D5 (domain/stack) are reliably supported by firsthand observation.** The **attitude/interaction axes D2/D3/D4/D6/D7**
  that drive user experience (acceptance, process involvement, trust, autonomy, **waiting temperament**)
  **are injected priors or extrapolations from behavior** in footprints—GitHub cannot reveal
  "how much he trusts the agent, where he sets the acceptance bar, or how long he can tolerate waiting idly."
- **Inferences spanning too large a gap are unreliable.** Inferring trust/acceptance/autonomy/waiting from external behavior (CVE hygiene → skeptical,
  fast PRs → impatient) is fragile extrapolation. Therefore, all these axes are downgraded `injected`; **real-person anchors for attitude and waiting temperament must come from
  `extract-selfreport-persona`**.
- **Source bias: GitHub skews toward publicly active people and builders.** Most people with low literacy fall below the trace-floor and should be routed to SO.
- **Usage boundary: These cards are suitable for building out the D1×D5 coverage grid.** **Do not** use their D2/D4/D6/D7 as real-person attitude/waiting anchors—
  those are priors sampled per card.

(This section is consistent with "Authenticity First" in card-schema.md: for axes that cannot be grounded, prefer marking them injected/low rather than pretending attitudes were observed.)

## Report on Completion

Report: which dimensions are GitHub-grounded (`observed`; or, in rare cases, firsthand statements `stated`) vs injected, the authenticity verdict,
and behavioral predictions. Explicitly **reject** contaminated / insufficient_evidence. If extracting under a recruitment profile, also report the
`priority_domain` bucket. **Remember**: D2/D4/D6/D7 from this source are mostly injected priors—label them honestly in the report.
