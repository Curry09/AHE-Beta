---
name: extract-selfreport-persona
description: >-
  Extract behavior-first personas of real AI-coding practitioners from their
  long-form FIRST-PERSON self-disclosure (personal blogs, interview / podcast
  transcripts, conference talks, build-in-public tweet-threads). Use when building
  the user-agent persona library and you need the attitude/interaction axes
  (acceptance bar, interaction style, trust, autonomy, time temperament) grounded
  rather than injected, or when you need high-fidelity anchor personas to calibrate
  the dimension scales. Emits the shared persona card defined in
  ../card-schema.md (the single public contract); this skill is one thin "spoke"
  among observed-behavior spokes (GitHub / Stack Overflow). Self-report
  inverts those: the source is STATED behavior, so it grounds exactly the
  D2/D3/D4/D6/D7 axes observed sources can only inject (or mostly inject);
  the authenticity gate targets performative/promotional/second-hand content
  instead of a trace floor; and discovery is per-subject (seed list + search),
  not crawlable — this is the anchor-B source, not a bulk sampler.
---

# Extract Self-Report Persona

A **thin extraction skill (spoke)**: extract personas from AI-coding practitioners' **long-form first-person self-reports** (personal blogs, interview/podcast
transcripts, conference talks, long build-in-public tweets). The card schema / enums / D5 vocabulary / injection distributions /
authenticity gate vocabulary all come from the sole shared contract [`../card-schema.md`](../card-schema.md). This file specifies only the source-specific details of **which dimensions to extract and ground from self-report sources**; it neither embeds the schema nor depends on any other skill.

It complements observational spokes (GitHub footprints, Stack Overflow): those read **what a person did**, but cannot see
*how they manage an agent, how much they trust it, or how long they can tolerate waiting*—and can only **inject** most attitude/interaction axes (including D7). This skill reads
**what a person says about their own AI-coding workflow**—blogs/interviews/talks—precisely where people articulate their acceptance thresholds, process involvement,
trust stance, autonomy expectations, and tolerance for waiting/idling. Thus self-report **Ground D2/D3/D4/D6/D7**,
filling in the behavioral axes missing from observational sources (and serving as the primary real-person anchor for waiting temperament D7).

The costs must be acknowledged honestly: this is **stated** (self-reported, subject to self-report bias), not observed; sources skew toward **the extremes** (celebrity experts + viral failure stories),
with sparse coverage in the middle; discovery **does not scale** (there is no searchable index of "people who have blogged about their own workflows"). Hence its role: **anchor B**—a small number of high-fidelity cards
to calibrate dimension scales and serve as gold-standard examples—paired with bulk sampling (dev.to / HN), not replacing it.

## Core Principles (Reversal Relative to Observational Spokes)

1. **First person + concrete workflow, or do not extract.** The source must be the person describing **their own** workflow with concrete details (does the process need to be visible?
   What if the result is inadequate? How long can they tolerate waiting idly? What counts as done?). Reject third-party accounts, listicles about them, and opinion pieces without workflow details—
   these cannot ground behavior. Find a firsthand source.
2. **Label `stated`; do not pretend it is observed.** Every dimension grounded in self-report must carry `basis: "stated"` in provenance,
   and **`confidence` is capped at `medium`**, unless corroborated by observational traces (then upgrade to `high` + `basis: "stated+observed"`).
   This is the inverse of observational sources—there, the evidence *is* behavior. For rule details, see “`stated` → confidence rules” in card-schema.md.
3. **The gate targets performance and incentives, not the trace floor.** Failure modes are **promotional** (selling courses/products, incentive-driven, low-signal),
   **second-hand** (not the person's own words), and **AI-spam** (SEO content-mill prose, excessive uniformity, zero concrete personal details). Exaggeration in genuine first-person accounts
   ("I always Accept All") is **genuine as a stance**—extract the stance, label `stated`, and do not reject it. See card-schema.md for the gate vocabulary.
4. **Cross-check capability (D1) claims.** If someone calls themselves an "expert" without corroborating outputs, `D1 confidence` is at most `medium`; when the person can be independently corroborated
   (well-known maintainer, public projects), upgrade to `high` + `basis: "stated+observed"`.
5. **Ground D2/D3/D4/D6/D7; D1/D5 are medium.** See the table in reference.md. Together, the three source types provide “hard observational or self-report evidence” for every axis;
   self-report is the only primary source that can reliably ground the trust axis (D4) and waiting temperament (D7).
6. **Same schema, mergeable; strip PII.** Produce the card shape defined in card-schema.md (D1–D7 + `authenticity` + `era` +
   `provenance`). Hash handles into `id`; store only the derived profile; use public verbatim statements + source URLs as `evidence_quotes`.
7. **Dimensions are orthogonal—never derive one dimension from another.** Same as iron rule #3 in card-schema.md; this source is precisely its proof: a
   `expert` who is simultaneously `over-trust` + `Accept-All` (Karpathy in vibe mode) is real and common. Do not let high D1 pull D2/D4
   toward rigor—ground each axis in its own verbatim statements. **Especially `on_offtrack` ⊥ `D7_time_temperament`**:
   “If the result is inadequate, I finish it myself” ≠ “I lose it after waiting idly for two minutes”—put the two statements into separate dimensions; never lock them together.

## Which dimensions self-report strongly grounds (a complementary mirror of observational sources)

| Dim | self-report strength | Ground from (self-report) |
|-----|------------------|------------------|
| **D2 acceptance_bar** | **Strong** | What they call "done/good enough," what they ship, the threshold they state ("roughly usable" vs "I can prove it is correct") |
| **D3 interaction_style** | **Strong** | How delegation is written (delegation); whether the process needs to be visible (supervision=process involvement); what they do when **result quality is inadequate** (on_offtrack) |
| **D4 trust_model** | **Strong** | Explicit trust statements ("I no longer read diffs" → over-trust; "I won't commit code I can't explain" → skeptical) |
| **D6 autonomy_expectation** | **Strong** | What they expect the agent **to be** ("It is a builder too" → agentic; "typing assistant" → advisory) |
| **D7 time_temperament** | **Strong (when verbatim statements about waiting exist)** | Tolerance for waiting/idling ("Go get a cup of coffee and come back" → patient; "I can't stand waiting idly for two minutes" → impatient); inject if there are no verbatim statements about waiting |
| **D1 evaluation_capability** | medium (stated; corroborated) | How they describe their own judgment + any verifiable outputs; capped at `medium` without corroboration |
| **D5 domain** | medium | stated domain/stack + corroborating projects; `weak` is often grounded in self-acknowledged blind spots |

Use the source's **publication date** for `era` (split at approximately 2025-10). Most vibe-coding self-reports are naturally `post_vibe`; cite the date in `era.basis`.

## Workflow

```
Self-report persona extraction progress:
- [ ] L-1 recruitment (optional): select a target from the seed list/search recipes (recruitment/seeds.md)
      (a named practitioner, or search for first-person posts)
- [ ] L0 source intake: collect the person's own **long-form first-person accounts** (blogs/transcripts/talks/long tweets); record {url, type, date} for each
- [ ] L1 gate: first-person + concrete workflow? No → promotional / second-hand / ai-spam / insufficient → do not admit (find a firsthand source)
- [ ] L2 quote mining: extract verbatim quotes → map to D2/D3/D4/D6/D7 (strong), D1/D5 (medium)
      —quotes about waiting/idling go into D7; quotes about quality failures go into on_offtrack; do not mix dimensions
- [ ] L3 stated/observed: label each grounded dimension basis:"stated"; corroborate D1/D5 where possible; pure stated is capped at medium
- [ ] inject only for axes on which the source is genuinely silent (including a silent D7); mark low; extract on_offtrack ⊥ D7 independently
- [ ] strip PII, hash id, produce the card-schema.md card shape (must include D7_time_temperament)
```

For the source-type vocabulary, detailed gate rules, `stated`→confidence rules, discovery/seed recipes, and four examples (two admitted poles, an orthogonal case, and one rejected marketing case),
see [reference.md](reference.md). For enums / D5 vocabulary / injection distributions / card shape / authenticity-gate vocabulary, see [`../card-schema.md`](../card-schema.md).

## Completion report

Report: which dimensions are grounded (`stated` vs `stated+observed`) vs injected, the authenticity verdict, and a behavioral prediction (one sentence: how this persona uses the
harness and what drives their user experience). Explicitly **reject** promotional / second-hand / AI-spam rather than downgrading them. Since this is anchor-B, also note which **dimension-scale pole** the card
anchors (e.g., "over-trust / ship-fast extreme" or "patient × fix-self orthogonality"), so the library knows which calibration cell it fills.
