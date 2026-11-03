# Reference: Stack Overflow Persona Extraction

<!-- Spec-0037/T5: D7 defaults to injected; disappearing after posting does not imply impatient; enums come only from the hub. -->

Stack Exchange API facts, targeting recipes, the reversed authenticity gate, attitude-axis injection,
and two examples. Read this file when extracting.

All dimension **enums, the controlled `D5.area` vocabulary, injection distributions, card shape,
and authenticity verdicts** are defined in the sole shared contract,
[`../card-schema.md`](../card-schema.md). This file covers only what differs for SO as an **observational** source.

## 1. Stack Exchange API (v2.3) facts

- Base: `https://api.stackexchange.com/2.3/`; **always include `site=stackoverflow`**.
- **Auth (2026-06 change):** key/token authentication uses the `Authorization: Bearer {KEY_OR_TOKEN}`
  header, no longer query parameters. Anonymous low-volume use is supported; an app key raises the
  quota to 10k/day (register at stackapps.com).
- **Bodies:** include `filter=withbody`; the default omits `*.body`.
- **Rate limits:** ≤30 req/s/IP; obey `backoff`; `pagesize≤100`; anonymous pagination is limited to ~25 pages.
  Do not repeat semantically identical requests within <1min.
- **Wrapper fields:** inspect `has_more`, `quota_remaining`, `backoff`, and `error_*`.

### Endpoint reference

```
GET /questions?site=stackoverflow&tagged={tag}&sort=creation&filter=withbody&pagesize=50  # askers + bodies + tags + owner.reputation
GET /search/advanced?site=stackoverflow&q={phrase}&filter=withbody                        # Blind-phrase search
GET /users/{ids}?site=stackoverflow                                                       # reputation, creation_date, badge_counts
GET /users/{id}/questions?site=stackoverflow&filter=withbody                              # Question history
GET /users/{id}/answers?site=stackoverflow                                               # 0 answers + low rep = consumer-only/newcomer
GET /users/{id}/tags?site=stackoverflow                                                  # Domain activity
```

Important per-question signals: `owner.reputation`, `owner.user_id`, `owner.creation_date`, `tags`,
`score`, `answer_count`, `is_answered`, `view_count`, `body`.
**`owner.reputation` is the cheapest proxy for technical sophistication.**

## 2. Target blind / newcomer askers

- Filter for **low `owner.reputation` (≤ ~50)** and recent `creation_date`.
- Target **domains underrepresented on GitHub** through `tagged`: `reactjs`/`next.js`/`html`/`css` (web),
  `pandas`/`numpy`/`dataframe` (data-analysis), `python`+beginner, `excel`/`vba`.
- Blind-phrase `search/advanced?q=`: "why doesn't it work", "how do i", "not working", and raw tracebacks without diagnosis.
- Cross-check: ~0 entries in `users/{id}/answers` plus low reputation suggests a help-seeker only.
- Closed/downvoted questions can indicate newcomers, but exclude spam and homework farms.

## 3. D1 from reputation and question quality: **cap at medium**

- **blind:** rep ≈ 1–20; pasted error / "doesn't work"; no MRE; no diagnosis.
- **surface:** moderate reputation; can *describe* a problem superficially; copy/paste-oriented; **no root-cause reasoning**.
- **competent / expert:** any **competent tell** places the candidate **out of scope: isolate**
  (`action: out-of-scope, route to GitHub skill`). Never relabel someone `surface` to admit them here.
  Tells include precise expected/actual behavior, a clean MRE, reproduction against a known-good baseline,
  an existing self-built workaround, multiple isolated failure cases, or precise mechanism/boundary questions.
  *Being stuck does not imply low technical sophistication.*

**Record `owner.reputation` in every card's `provenance`**: it is the cheapest sophistication proxy
and a primary basis for D1 alongside question quality. Marking D1 `grounded` without recording reputation
is noncompliant. **Grounded D1 is capped at `confidence: medium`**, with basis `observed`:
a single post plus reputation is weak evidence and cannot support high.

## 4. D3 from question style

- **delegation:** raw code+error dumps / "just make it work" → `vibe-dump`; partial context → `loose`;
  a clean MRE with expected/actual behavior → `spec-driven` (rare here, but allowed when genuine).
  Observe delegation from the **actual question text**, mark `grounded` / `basis: "observed"`, and use
  conservative confidence for a single post. Do not derive it from the tier.
- **supervision (process involvement) / on_offtrack (quality-failure response):** responding to clarification
  comments and iterating suggests `reviews` / `retry`; disappearing after posting suggests `hands-off` / `abandon`.
  **No comment thread → `injected`.** `file-issue` is **rare** at blind/surface tiers; assign it only
  when the question itself reads like a deliberate bug report.
- **on_offtrack ≠ waiting patience.** Disappearing after posting is weak evidence of a quality-failure/
  abandonment path, **not** evidence for D7=`impatient`.

## 4b. D7 time_temperament — *unobservable; default to injected*

`patient | steady | impatient`. Help-seeking posts almost never state tolerance for waiting without activity.
**Default to injection** from the contract distribution, **independently of on_offtrack**.
Never require abandon to pair with impatient. Use self-report for real-person waiting-temperament anchors.

## 5. Inject attitude axes: default for D2/D4/D6/D7

Help-seekers rarely reveal acceptance criteria, trust, or waiting temperament.
**Sample per card from card-schema.md's controlled injection distributions**, setting
`source: "injected"` / `confidence: "low"`; injected dimensions **have no basis**.

- The exact proportions, including **time_temperament**, are in card-schema.md. Do not duplicate them:
  the shared contract is the hub-and-spoke design's single source of truth.
- **Mandatory orthogonality:** `on_offtrack` ⊥ `time_temperament`.
- **SO weak priors, leaning toward blind:** lower tiers may bias sampling toward over-trust / advisory,
  but **still mark injected / low**. **Do not use weak priors for D7.**
- Ground **D5.stack** from `tags`; **D5.weak** is often `[]` at lower tiers.
- **Sample; never lock combinations by tier (mandatory).** Draw independently per card and inspect batch
  spread, including D7. SO's self-selection bias gives it the **highest** risk of stereotyped cards.

## 6. Reversed authenticity gate: SO-specific

**No trace floor.** A single coherent question plus low reputation can admit a `blind` card.
A sparse trace is the target, not a defect.

| Verdict | Trigger | Action |
|---------|---------|--------|
| `authentic` | Sincere, *messy* human question from someone stuck; reputation agrees with topic depth (low rep ⇄ beginner topic) | Admit. |
| `contaminated` | rep≈1/new account with polished AI-formatted questions (template sections, `id=` fences); rep≈1 contradicts expert-level subject matter | Isolate; do not admit. |
| `suspect` | Homework farm / spam / ambiguity | Isolate. |

Messiness is useful. The risk is the opposite of GitHub's: not fake expert PRs, but
**AI-generated/copied questions** that are implausibly polished for the account behind them.

## 7. Card schema: the shared contract

Produce the **same card shape** from card-schema.md so all three spokes feed one library.
Nested dimensions carry inline `source`+`basis`+`confidence`; single-valued dimensions use `value`;
`era` is `{value, basis}`; `provenance.evidence_quotes` entries are `{quote, source}`.
See card-schema.md for full compliance rules, including **a single controlled token for `D5.area`**,
evidence_quote for grounded dimensions, and confidence=low for injected dimensions.

SO-specific rules: `era.basis` comes from `owner.creation_date`; `evidence_quotes` contain question-body
excerpts and question URLs; use SO layers such as `["SO-profile","SO-questions"]` in `provenance.layers`.
**`provenance` must include the asker's `reputation`**, for example `"reputation": 1`.
Include `D6_autonomy_expectation`, defaulting to `injected` with weak wording-based priors.

## 8. Example A — authentic blind newcomer: admit

rep 1, account created 2025-12, tags `[python, pandas]`; the question pastes a `KeyError` traceback,
asks "why doesn't it work", and does not isolate the failure. This card fills a
**blind + post_vibe + data-analysis** gap. D1 blind is grounded (`observed`) but **capped at medium**:
one post and rep=1 are weak evidence. D5 is grounded (`observed`); question text grounds delegation (`observed`).
**D2/D4/D6/D7/supervision/on_offtrack are injected (`low`) without basis.** The example deliberately combines
`on_offtrack=abandon` × injected `D7=patient` to demonstrate orthogonality: do not couple abandon with impatient.

```json
{
  "id": "so-3f2a1c9d",
  "authenticity": "authentic",
  "era": {"value": "post_vibe", "basis": "owner.creation_date 2025-12"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "blind", "source": "grounded", "basis": "observed", "confidence": "medium"},
    "D2_acceptance_bar": {"primary": "ship-fast", "flags": [], "source": "injected", "confidence": "low"},
    "D3_interaction_style": {
      "delegation": {"value": "vibe-dump", "source": "grounded", "basis": "observed", "confidence": "medium"},
      "supervision": {"value": "hands-off", "source": "injected", "confidence": "low"},
      "on_offtrack": {"value": "abandon", "source": "injected", "confidence": "low"}
    },
    "D4_trust_model": {"value": "over-trust", "source": "injected", "confidence": "low"},
    "D5_domain": {"area": "data-analysis", "depth": "shallow", "stack": ["python","pandas"], "weak": [], "source": "grounded", "basis": "observed", "confidence": "high"},
    "D6_autonomy_expectation": {"value": "advisory", "source": "injected", "confidence": "low"},
    "D7_time_temperament": {"value": "patient", "source": "injected", "confidence": "low"}
  },
  "provenance": {
    "layers": ["SO-profile","SO-questions"],
    "reputation": 1,
    "evidence_quotes": [
      {"quote": "i get KeyError and i dont know why it doesnt work, here is my code", "source": "stackoverflow.com/q/NNNNNN"}
    ]
  },
  "behavioral_prediction": "Pastes the error and asks 'why doesn't it work'; can't judge a fix, runs whatever the agent gives and accepts it if it stops erroring. Trust/acceptance/autonomy/waiting temperament are injected priors; abandon ⟂ patient demonstrates orthogonality."
}
```

## 9. Example B — suspicious AI polish: reject

rep 1, account created 2026-01, yet the question is perfectly templated (Description / Repro / Expected /
Actual sections, `id=` fences) and asks about deep Rolldown-RSC build internals.
**rep≈1 ⊥ expert subject matter + AI formatting → contaminated.**

```json
{
  "id": "so-9b7e22a1",
  "authenticity": "contaminated",
  "reject_reason": "rep≈1 account ⊥ deep RSC-internals topic; AI-format question (templated sections, id= code fences)",
  "action": "isolated, not admitted"
}
```

## 10. Library role and recruitment

This skill fills the **lower tiers**: `blind`/`surface`, domains sparse on GitHub (web/frontend,
data-analysis, beginner scripting), and `post_vibe` newcomers. Do not recruit experts here.
Use library quotas to target the tier×domain cells GitHub cannot supply.

**Pluggable recruitment, decoupled and optional.** To fill a benchmark domain's lower tiers, consume
the same multi-source recruitment profiles as `extract-github-persona`, with their `pools.stackoverflow` **tag** lists:

- `../extract-github-persona/recruitment/swe-bench.md`
- `../extract-github-persona/recruitment/terminal-bench.md`

Read `pools.stackoverflow` and target **low-reputation askers** under those tags.
One profile covers both D1 extremes: GitHub fills expert/competent, this skill fills blind/surface,
for the same `priority_domains`. Profiles decide only *which tags to search*;
rate cards with the SO authenticity gate (§6).

**Distribution discipline**, shared with the GitHub spoke (see `../extract-github-persona/reference.md` §8):
SO fills the `blind`/`surface` rows of the `D1 tier × D5 domain` grid. Evaluate cell coverage,
marginal balance, and clone checks, rather than raw counts.
