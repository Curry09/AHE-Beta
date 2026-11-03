# Persona Card Schema — Sole Public Contract (hub)

<!-- Spec-0037/T3: D7 time_temperament + supervision/on_offtrack semantic note; co-evolves with the 0006/T1 spoke contract -->

> This file is the **sole source-agnostic public contract** on the persona distillation side. All “thin extraction skills” (spokes,
> such as `extract-selfreport-persona/`, `extract-github-persona/` / `extract-stackoverflow-persona/`)
> describe only “what to extract from a given source type + which dimensions to ground”; **enumerations / vocabularies / card shape / injection distribution / authenticity gate principles must all reference this file**,
> and must not depend on one another. Change the contract in one place and it takes effect for everyone; adding a new source only adds a thin skill and does not touch the others.
>
> Corresponding spec: `docs/specs/0006-persona-pipeline.md` (T1 collection, T2 injection sim); human-axis semantic evolution is documented in
> `docs/specs/0037-persona-time-temperament-reframe.md` (D7 / process involvement / quality failure ⊥ waiting).
> The injection mapping for card → sim `dimensions.Persona` is defined by `0006/T2` + `0037/T4` (`card_to_persona`), and is outside this contract.

## Non-negotiable Rules

1. **Hub-and-spoke**: this file is the hub, and extraction skills are spokes. Each spoke depends only on this contract, **and spokes do not depend on one another**
   (preventing skill→skill references and schema drift across copies).
2. **Evidence or discard**: every grounded dimension must be traceable to one `evidence_quotes`; if it cannot be grounded, inject it and lower confidence.
3. **Dimension orthogonality**: D1–D7 are independent of one another; **never derive one dimension from another** (including `on_offtrack` ⊥ `time_temperament`).
   A single `expert` being simultaneously `over-trust` / `Accept-All` is real and common (see selfreport reference example C /
   Karpathy); do not let high D1 pull D2/D4 toward rigor.
4. **Do not introduce benchmark / trajectory-derived fields**: the card contains only “personas collected from real data” and must not include any benchmark scores,
   trajectory features, or downstream sim-derived quantities (to keep the training signal real and prevent contamination with the test target).

## Card Record Shape

A card is a JSON object:

```json
{
  "id": "<source-hash>",               // handle/source hash; stores derived persona, does not store PII
  "authenticity": "authentic",          // authenticity ruling; see §Authenticity Gate
  "era": {"value": "post_vibe", "basis": "<date/basis>"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
    "D2_acceptance_bar":        {"primary": "...", "flags": ["..."], "source": "...", "basis": "...", "confidence": "..."},
    "D3_interaction_style": {
      "delegation":  {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
      "supervision": {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
      "on_offtrack": {"value": "...", "source": "...", "basis": "...", "confidence": "..."}
    },
    "D4_trust_model":           {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
    "D5_domain":                {"area": "...", "depth": "...", "stack": ["..."], "weak": ["..."], "source": "...", "basis": "...", "confidence": "..."},
    "D6_autonomy_expectation":  {"value": "...", "source": "...", "basis": "...", "confidence": "..."},
    "D7_time_temperament":      {"value": "...", "source": "...", "basis": "...", "confidence": "..."}
  },
  "provenance": {
    "layers": ["L0", "..."],            // Optional: evidentiary layer for observational sources (GitHub)
    "sources": [{"url": "...", "type": "..."}],  // Optional: self-report source list
    "self_report": true,                 // Optional: whether it is a first-person self-report
    "reputation": "...",                 // Optional: independently corroborated public reputation
    "evidence_quotes": [{"quote": "...", "source": "..."}]
  },
  "behavioral_prediction": "<one sentence: how this persona uses harness, what drives its user experience>"
}
```

Rejected card (not stored) shape:

```json
{"id": "...", "authenticity": "suspect|contaminated|insufficient_evidence",
 "reject_reason": "...", "action": "not admitted; ..."}
```

### Per-Dimension Envelope

Except for D2 (using `primary` + `flags`), D3 (each of the three sub-axes has its own envelope), and D5 (structured `area/depth/stack/weak`),
each dimension carries the same four-tuple:

- `value` (or `primary`+`flags` for D2): value; see the enumerations below.
- `source`: `grounded` (evidence exists) | `injected` (no evidence; filled by sampling).
- `basis`: `observed` (based on what it does) | `stated` (based on what it says, self-report) | `stated+observed` (self-report with observational corroboration).
- `confidence`: `low | medium | high`.

## Dimension Enumerations

```
D1 evaluation_capability : blind | surface | competent | expert
D2 acceptance_bar.primary: ship-fast | functional | modern-correct | type-safety-purist
   acceptance_bar.flags  ⊆ {tests, types, scope, security, style, a11y, perf}
D3 interaction_style.delegation  : vibe-dump | loose | spec-driven
   interaction_style.supervision : hands-off | reviews | micromanage
     (semantics = process involvement: the need to have visibility into what is happening while the assistant is working; not a product button)
   interaction_style.on_offtrack : abandon | retry | correct | fix-self | file-issue
     (semantics = strategy after a quality failure; does not drive patience with waiting)
D4 trust_model           : over-trust | balanced | skeptical
D5 domain.depth          : shallow | working | deep
D6 autonomy_expectation  : advisory | collaborative | agentic
D7 time_temperament      : patient | steady | impatient
     (tolerance for waiting/idling; orthogonal to on_offtrack)
era.value                : pre_vibe | post_vibe        (split by publication date, approximately 2025-10)
```

> Authorization level (read-only/writable/runnable) **does not enter the card store**: it is a session/product policy, partially derived by sim from autonomy preference.

### D5.area Controlled Vocabulary

`area` takes a **single token** (library coverage can be measured); use `cross-stack` when there is genuinely no central domain across domains. Put specific technology stacks in `stack`, not in `area`.

```
web-backend | web-frontend | scientific-computing | data-viz | ml-ai |
data-analysis | dev-tooling | data-eng | infra-devops | databases |
systems-runtime | security | mobile | cross-stack
```

（`data-analysis` = pandas/numpy/excel/notebook data organization, distinct from the `data-eng` pipelines and `scientific-computing` numerical/symbolic libraries.）

`stack` = the specific technology actually used (for example, `["typescript","node"]`). `weak` = a subdomain that lowers effective capability by one level (for example, `["timezones/DST"]`),
and is a strong behavior-shaping signal (causing an otherwise competent user to miss a certain class of domain bugs); if it cannot be grounded, inject 0–2 of them or leave `[]`.

## Controlled Injection Distribution

When a source is **genuinely silent** on a given axis, independently sample from the following distributions **once per card** (orthogonally to dimensions that have already been grounded),
and set `source: injected` / `confidence: low`:

- `delegation`: vibe-dump 25% / loose 45% / spec-driven 30%
- `supervision`: hands-off 30% / reviews 45% / micromanage 25%
- `on_offtrack`: abandon 20% / retry 20% / correct 30% / fix-self 15% / file-issue 15%
- `trust_model`: over-trust 30% / balanced 45% / skeptical 25%
- `autonomy_expectation` (D6): advisory 35% / collaborative 40% / agentic 25%
- `time_temperament` (D7): patient 25% / steady 50% / impatient 25%
- `D5.weak`: inject 0–2 reasonable weaknesses according to `area`, or `[]`.

**Orthogonality is mandatory**: `on_offtrack` and `time_temperament` must be sampled independently—do not lock them together by level, such as «abandon must be paired with impatient» or «file-issue must be paired with patient».

When weak priors are available, sampling may be biased (a self-described vibecoder → over-trust + vibe-dump; a library maintainer → skeptical + spec-driven). The proportions are initial defaults and may be adjusted to the target-user distribution.

**Sample; do not lock by level (mandatory)**: injection means “draw once from the real distribution for each card,” not “deterministically map from D1.” If every `surface` card becomes
`functional+balanced+reviews+retry`, and every `blind` card becomes `ship-fast+over-trust+hands-off`, then the levels have been locked together—
redraw. Draw each injection dimension independently (weak priors only slightly adjust the odds), and visually inspect the post-batch distribution to check whether it has collapsed.

## Authenticity Gate Principles (Bidirectional)

The authenticity gate is **bidirectional**. Select the corresponding side according to the source type; every grounded dimension must **pass through the gate before mapping**.

- **Observational sources** (look at what they do, e.g. GitHub activity): the gate is **trace-floor + consistency**. Below the evidence floor (too few owned repos + real PRs +
  diagnosed issues in total, especially 0 repo and 0 PR) → `insufficient_evidence`, do not admit to the repository; a shallow profile ⊥ deep output /
  implausible cross-stack implementation speed / AI formatting traces (`id=` fences, excessive templating) → `contaminated`, quarantine and never admit to the repository;
  ≥2 **non-empty** layers are consistent → `authentic`. High volume is a contamination indicator, not a quality signal.
- **Self-reported sources** (look at what they say, e.g. blogs/interviews/talks/long tweets): the gate is **performative / promotional / second-hand**.
  Course marketing / influencer product promotion / incentive-driven content → `promotional` reject; third-party retellings, not the person's own words → `second_hand` reject (seek first-hand sources);
  mass-produced AI SEO content, zero specific personal details → `contaminated` quarantine; first-person accounts with no workflow details whatsoever → `insufficient_evidence` reject.
  **Exaggeration does not equal distortion**: exaggeration in an authentic first-person account ("I never read diffs") genuinely conveys a *stance*—extract the stance, mark `stated`,
  set `confidence: medium`, do not reject.

Adjudication values: `authentic | suspect | contaminated | insufficient_evidence`. Source-specific gate details are documented in the corresponding thin skills;
this contract establishes only **principles and the adjudication vocabulary**.

## `stated` → confidence rules (self-reported sources)

- Grounded solely in self-report: `source: grounded` + `basis: stated` + **`confidence` capped at medium**.
- Upgrade to `high` + `basis: stated+observed`: only with corroborating observational traces (publicly measurable output / track record as a well-known maintainer / live product).
- "Admitting weaknesses" ("I don't have a technical background") carries little incentive to fabricate → may use `high`; "self-proclaimed expertise" carries a strong incentive to fabricate → without corroboration, remain at `medium`.

## Conformance Rules

1. Single-value dimensions (D1/D4/D6/D7 + the three D3 sub-axes) use key `value`; D2 uses `primary`+`flags`; D5 uses `area/depth/stack/weak`.
2. `D5.area` ∈ the controlled vocabulary above, and must be a **single token**.
3. Dimensions with `source: grounded` must have at least one corresponding `evidence_quotes`.
4. For dimensions with `source: injected`, `confidence` must be `low`.
5. Card records **must not** contain any benchmark / trajectory-derived fields.
6. For unknown keys: readers must be forward-compatible (ignore without error), to facilitate schema evolution.
7. When `D7_time_temperament` is absent, the injection side falls back to `steady` (compatibility with old cards); new cards should specify it explicitly.
