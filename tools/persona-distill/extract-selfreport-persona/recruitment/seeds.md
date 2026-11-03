# Recruitment: self-report persona seeds (pluggable)

Discovering self-report sources cannot rely on a crawler: there is no searchable index
of people who have blogged about their own AI-coding workflows. This file makes discovery
**repeatable** through a curated seed list organized by **dimension-scale extremes** and a
search recipe for fresh first-person material. Pick an **under-anchored extreme**, choose
the next target, then run the SKILL.md L0→emit pipeline and the gate in reference.md §3.
A seed determines only *whom to examine*.

Seeds are anchors (anchor-B), not the bulk sample: use **1–3 strong cards per extreme** to
calibrate the scale, then let bulk sampling (dev.to / HN, anchor-A) fill out the volume.

## Extremes to anchor (calibration grid)

Prioritize what the library lacks. Each extreme is a (D1 × D2/D4) region that needs a
high-fidelity, fully grounded card to anchor it.

| Extreme | Target dimensions | Why it matters |
|------|--------|----------|
| **over-trust / ship-fast / non-technical** | D1 `blind`, D4 `over-trust`, D2 `ship-fast` | The pure vibe extreme; user experience = "it runs, anyway" |
| **expert × over-trust (orthogonal)** | D1 `expert`, D4 `over-trust`, D3 `hands-off` | Demonstrates D1 ⟂ D4; calibrates capability ≠ rigor |
| **Pragmatic middle** | D1 `competent`, D4 `balanced`, D2 `ship-fast` | The large real-world middle; ships rough work that runs in production |
| **skeptical / rigorous** | D1 `expert`, D4 `skeptical`, D2 `modern-correct` | The disciplined agentic-engineering / TDD end |
| **type-safety-purist** | D2 `type-safety-purist`, flags `types` | A correctness-focused acceptance gate (still thinly covered) |
| **advisory-only** | D6 `advisory` | Wants answers/snippets without letting the agent act |

## Curated seeds (by extreme)

Use these as starting targets; each has extensive, verifiable first-person long-form
material. Names are for *recruitment* only: emitted cards use hashed IDs and retain derived
personas plus public quotations; see principle #6 in SKILL.md.

- **over-trust / ship-fast / non-technical** → Viral retrospectives on "vibe coding went
  wrong and got hacked," such as EnrichLead's long thread saying "I was attacked / I am
  not technical." Acknowledging the mistake provides grounding, corroborated by the public outcome.
- **expert × over-trust** → Karpathy's original definition plus any first-person account
  of "letting it run on my weekend project." Capability is corroborated; stance is stated.
- **Pragmatic middle** → indie-hacker / build-in-public interviews, such as Lex #440 with
  levelsio: "ship rough, ship fast," running production solo and fixing things as needed.
- **skeptical / rigorous** → Simon Willison's blog corpus and conference fireside talks;
  TDD / "code proven to run" / "I do not commit what I cannot explain."
- **type-safety-purist** → TS/Rust correctness bloggers describing how they constrain
  agents: strict types, "no `any`," exhaustive matching. Find them with the search recipe.
- **advisory-only** → Senior developers blogging "I treat it as smarter autocomplete / I
  ask for options but write the code myself." Find them with the search recipe.

## Search recipe (fresh first-person material)

When an extreme has no seed, or you want more, search and then **read the person's own
long-form material**. Do not extract from search hits alone:

- **dev.to** (Forem API, no key required):
  `GET https://dev.to/api/articles?tag=vibecoding&top=30`
  (also use tags `ai`, `cursor`, `aiagents`); then use `GET /api/articles/{id}` to retrieve
  the full `body_markdown`. Keep first-person "how I use it / what I learned" posts;
  discard tool advertisements.
- **Hacker News** (Algolia, no key required):
  `GET https://hn.algolia.com/api/v1/search?query=<workflow phrase>&tags=comment`
  (for example, "I never read the diffs," "I always review," "claude code workflow").
  High volume, low signal-to-noise: filter aggressively, then follow the author to their
  blog and read long-form material.
- **Direct**: Authors' blog indexes, "uses" pages, and newsletter archives often contain
  the richest and most specific workflow posts.

Apply the gate in SKILL.md / reference.md §3 to every source. Reject `promotional`
(course funnels), `second_hand` (writing about someone else), `contaminated` (AI SEO
content mills), and `insufficient_evidence` (opinions without concrete workflow details).

## Coverage discipline

- If over-trust/blind still has no card, do not add a third skeptical-expert card. Fill
  the **thinly covered extremes** first.
- Every anchor card must be **fully grounded**. This is anchor-B; heavily injected cards
  defeat its purpose. Route those volume needs to dev.to/HN sampling instead.
- Record which extreme each card anchors so the library can track calibration coverage
  alongside grid coverage in future observational spokes.
