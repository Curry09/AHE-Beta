---
number: "0006"
title: "Persona pipeline: collection (distillation) and injection into sim"
issue: 0
slug: persona-pipeline
summary: "This group implements the persona pipeline: linking “collect personas from real data” with “inject personas into the control envelope sim” in a single chain to supply real user profiles to 0005's heavyweight user-side implementation. This corresponds to the CLAUDE.md “distillation module” and enforces the constraint that “personas come from real data and are not constructed from benchmarks or trajectories”."
tasks:
  - id: T1
    title: "Persona collection (distillation, in skill form)"
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0005/T1
        type: note
    parallel: false
    files:
      - tools/persona-distill/card-schema.md
      - tools/persona-distill/extract-selfreport-persona/SKILL.md
      - tools/persona-distill/extract-selfreport-persona/reference.md
      - tools/persona-distill/extract-selfreport-persona/recruitment/seeds.md
      - backend/ahe_beta/distill/library.py
      - backend/tests/distill/test_library.py
    scope: "Implement the collection side using a hub-and-spoke architecture and define the persona card library format. Scope of this step: ① card-schema.md (the sole public contract: card schema + enums + D5 vocabulary + injection distributions + authenticity gate principles, source-agnostic); ② extract-selfreport-persona (a thin skill that extracts from first-person self-reports and references the contract); ③ library.py read/write. Do not integrate specific data sources or implement card→sim injection mapping (belongs to T2). cc/so/not-yet-sourced are later thin skills under the same contract, to be added later (see open-questions)."
    acceptance: "card-schema.md is the sole source-agnostic public contract (card schema + enums + D5 vocabulary + injection distributions + authenticity gate principles); extract-selfreport-persona is a thin skill that only references the contract, with no skill→skill dependencies or dangling references; library reads and writes a library of multiple cards according to the contract, supports retrieval by id, and is forward-compatible with unknown keys; card records contain no benchmark/trajectory-derived fields; D5.area is a single token from a controlled vocabulary."
  - id: T2
    title: "Persona injection into sim"
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - 0005/T1
    relates-to:
      - ref: 0005/T1
        type: extends
      - ref: 0005/T5
        type: note
    parallel: false
    files:
      - backend/ahe_beta/user/sim/persona_io.py
      - backend/tests/user/sim/test_persona_io.py
    scope: "Inject persona cards (0006/T1) into sim: card_to_persona maps a card → dimensions.Persona, passes grounded axes through unchanged, and finalize_persona fills only derived dimensions not grounded in the card (grounded values override derived values); handle field alignment between 6-dimensional cards↔9 dimensions, enum alignment (surface↔shallow, etc.), defaults, and validation. Do not change the card format (belongs to T1); make only the supporting change to the sim dimension model to make finalize fallback-only (contract in 0005/T1, a dependency of this group). Do not construct harness/client (0005/T6)."
    acceptance: "card_to_persona produces a complete immutable Persona for a valid card: grounded d3 (card D2)/trust (card D4) are preserved unchanged, and derived dimensions not grounded in the card (those missing among d3/trust/d6) are filled by finalize_persona; after injection of an expert×over-trust card, trust remains the mapped value for over-trust (not overwritten to skeptical by derive_trust); missing fields/invalid enums raise explicit errors; the injection result can be fed directly to 0005/T5 run_session to complete a session."
  - id: T3
    title: "Observational persona spokes: SO / GitHub integration (including limitations statements)"
    status: done
    priority: P1
    tags:
      - persona-distill
      - observed-source
    depends-on:
      - T1
    relates-to:
      - ref: T2
        type: note
    parallel: false
    files:
      - tools/persona-distill/extract-stackoverflow-persona/SKILL.md
      - tools/persona-distill/extract-stackoverflow-persona/reference.md
      - tools/persona-distill/extract-github-persona/SKILL.md
      - tools/persona-distill/extract-github-persona/reference.md
      - tools/persona-distill/extract-github-persona/recruitment/domains.md
      - tools/persona-distill/extract-github-persona/recruitment/swe-bench.md
      - tools/persona-distill/extract-github-persona/recruitment/terminal-bench.md
    scope: "Adapt and implement two **observational** spokes (following the T1 extract-selfreport-persona structure), within this task's scope:\n① extract-github-persona (source: extract-cc-user-persona; actual source is GitHub activity in repos/issues/PRs) — includes\nSKILL.md + reference.md + recruitment/ (domains.md domain registry + swe-bench.md + terminal-bench.md);\n② extract-stackoverflow-persona (source: extract-so-user-persona; Stack Overflow API) — includes SKILL.md +\nreference.md. Three changes: reference the contract and remove spoke→spoke dependencies, add basis, and downgrade attitude axes to injected (downgrade SO's D1 to medium).\nEach spoke must have a “Limitations and Defects” section that prominently records the content-quality boundaries of observational methods. **Do not modify** card-schema.md (the contract, belongs to T1),\ndo not modify extract-selfreport-persona/ (belongs to T1), do not modify backend code (library.py/validate_card/persona_io.py belong to T1/T2),\nand do not modify the NexAU originals (the vendored adapted versions go into this repository). Library-side hard gates (mandatory basis / mandatory injected attitude axes for observational sources) are out of scope for this task;\nsee open-questions."
    acceptance: "Both spokes are located under tools/persona-distill/, structurally aligned with extract-selfreport-persona, and reference only ../card-schema.md;\nno spoke→spoke reverse schema references, no bundled complete schema, and no dangling references; each grounded dimension envelope has basis (observed for observational sources), while injected dimensions have no basis and have confidence=low; the GitHub spoke defaults D4/D2 without firsthand evidence to injected, with D1/D5 grounded; the SO spoke caps grounded D1 at medium, defaults D4 to injected, and has D1/D5 grounded; each spoke contains a prominent “Limitations and Defects” section (documenting D1×D5 reliability, attitude-axis injection/extrapolation, source bias, and usage boundaries); each spoke's worked-example card passes PersonaLibrary.validate_card and can be consumed by card_to_persona; rename to conform to extract-<source>-persona."
---

# 0006 · Persona Pipeline: Collection (Distillation) and Injection into sim

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level rust-RFC 9-section overview. -->

## Summary

This group implements the persona pipeline: it connects “collecting personas from real data” with “injecting personas into the control-envelope sim” as one chain, supplying the user-focused implementation in 0005 with real profiles. It corresponds to the “distillation module” in CLAUDE.md and implements the constraint that “personas come from real data and are not constructed from benchmarks or trajectories.”

Data-flow backbone:

```
Real usage data (first-person self-reports · GitHub activity · Stack Overflow · future sources)
        │  collection/synthesis (T1, hub-and-spoke: shared card contract + thin extraction skills)
        ▼
   persona card library (6-dimensional behavioral cards: D1–D6 + authenticity/era/provenance)
        │  injection (T2, card_to_persona: pass grounded axes through + override derived values)
        ▼
   spec-0005 dimensions.Persona ─► 0005/T5 run_session runs one session ─► user experience + issue
```

The diagram defines the tasks: **T1** specifies “what to collect and what the card looks like”—it does not create another skill, but incorporates the existing real extraction methods (previously written in the NexAU repository, not methods belonging to NexAU itself), organized in a **hub-and-spoke** structure: the sole shared contract `card-schema.md` (6-dimensional card schema + enums + D5 vocabulary + injection distributions + two-way authenticity-gate principles, source-agnostic) + each “thin extraction skill” describes only “extract from a given source type + which dimensions to ground,” depends only on the contract, and does not depend on the others. This step first lands the contract + `extract-selfreport-persona` (first-person self-report, the only grounding-trust axis for D4 and including card_to_persona override rules); cc/so/unsupported sources are added later as thin skills under the same contract. The library schema is this contract. **T2** specifies “how a card becomes a Persona that sim can run” (the sole bridging layer, card_to_persona).

**Derived-dimension override (key constraint)**: the 6-dimensional card is a “real profile with orthogonal grounding,” with evidence for each dimension; among sim’s 9 dimensions, d3/trust/d6 were originally “derived from D1/D5.” During injection, **the grounded acceptance D2 in the card → sim d3, and trust D4 → sim trust directly; they must not be overwritten by derive_*** (these two are precisely sim’s derived dimensions). finalize_persona only fills derived dimensions that are not grounded in the card—otherwise expert×over-trust (selfreport example C / Karpathy) would be simulated as the opposite, skeptical×rigorous. This constraint is stated in the extract-selfreport-persona reference example C (card_to_persona), and requires 0005/T1 to reduce finalize_persona to fallback-only (the same change is made in this group).
Note: card D6 autonomy → sim D5Autonomy is a sampling dimension (written directly; it has no derive function). sim’s derived dimension D6Authz has no corresponding source in the card, so it is still derived from D5Autonomy + task_risk (see T2).

Relationship to 0005: this group is the upstream provider for 0005 (the control-envelope user simulator). The final integration of the 6-dimensional card ↔ sim’s 9 dimensions ↔ spec-0001 models.Persona is recorded in each Task’s open-questions and will be determined after real data and downstream requirements converge.

## Motivation

The training signal for the entire evolution comes from user experience on the “simulated real-use” distribution, and its authenticity is rooted in whether personas come from real data. The three existing real extraction methods (previously written in the NexAU repository, not methods belonging to NexAU itself: extract-selfreport-persona, extract-cc-user-persona, extract-so-user-persona) have already established “evidence or discard / orthogonal dimensions / two-way authenticity gates”—rewriting them would inevitably lose fidelity, so they are incorporated rather than recreated (T1 incorporates selfreport; T3 incorporates the other two observation-based methods). More importantly, this supports **extensibility**: currently these methods write the shared schema only in cc, while so/selfreport reference cc in reverse (skill→skill dependency), which is the root cause of basis/provenance drift among the three. The hub-and-spoke structure extracts the shared portion into a single contract; each spoke depends only on the contract and remains independent of the others—a contract change takes effect for all of them in one place, and adding a source requires only adding a thin spoke without touching the others. T1 first lands the contract and the first spoke; T3 adds the other two according to this plan.

In addition to incorporation, T3 must tighten the attitude axis through content review: observation-based sources (GitHub activity and Stack Overflow answers) reliably observe only capability and domain. Inferring trust/acceptance/autonomy from external behavior (for example, inferring trust from CVE hygiene or auto-merge records) is fragile extrapolation. These dimensions must be explicitly downgraded to injected, with the quality boundary documented, to prevent a single card from being mistaken for a real-person “attitude” anchor and contaminating the authenticity of the training signal.

After collection, the injection layer (T2) faces another tension: collection produces a “real profile with orthogonal grounding,” while sim consumes “9-dimensional structured coefficients.” The formats differ, so an explicit, measurable mapping layer is required. More importantly, sim’s d3/trust/d6 were originally “derived from D1/D5.” If injection always calls finalize, it will rewrite the card’s real grounded trust/acceptance/authorization values with synthetic values—for example, Karpathy’s expert×over-trust (selfreport example C) would be simulated as the opposite, skeptical×rigorous, directly contaminating the authenticity of the training signal. The injection layer must therefore allow grounded values to override derived values.

## Guide-level explanation

The collection side uses a **hub-and-spoke** structure and does not create a large new skill: the sole shared contract, card-schema.md (source-agnostic), defines the 6-dimensional behavior card schema (D1–D6 + authenticity + era + provenance), dimension enums, the controlled vocabulary for D5.area, injection distributions, and two-way authenticity-gate principles. It incorporates the latest conventions from the existing selfreport skill (source+basis+confidence for each dimension, provenance union, value keys). The three thin extraction spokes each depend only on this contract and not on one another: extract-selfreport-persona (T1) extracts from first-person self-reports (blogs/interviews/talks/long-form posts), and is the only source that can ground the attitude axis D4 trust; extract-github-persona and extract-stackoverflow-persona (T3, adapted from the existing extract-cc-user-persona / extract-so-user-persona and renamed to align with the extract-<source>-persona convention) observe GitHub activity and Stack Overflow answers. The dimensions reliably grounded are D1 capability and D5 domain·stack; the attitude axes (D2 acceptance, D3 interaction, D4 trust, D6 autonomy) are downgraded to injected by default for observation-based sources (D1 for SO is additionally capped at medium because the evidence is weak), preventing a single card from being mistaken for a real-person attitude anchor. This step first lands the contract + selfreport (T1); cc/so are added later as thin spokes under the same contract (T3 fulfillment), while unsupported sources remain for later addition. The card records delivered by the three spokes are read and written uniformly by library.py (T1), stored according to the contract, and consumed by the injection layer.

Injecting a collected persona card into the control-envelope sim is the sole bridging layer (T2): card_to_persona maps one card to sim’s dimensions.Persona—grounded axes in the card are passed through directly, while finalize_persona fills only derived dimensions that are not grounded in the card (the “derived-dimension override”: grounded acceptance/trust/authorization are not overwritten by derive_*). The resulting artifact is passed directly to spec-0005/T5 run_session.

## Reference-level explanation

### Collection side: the hub-and-spoke contract and three extraction spokes (T1, T3)

The collection-side implementation consists of “one shared contract + three independent thin extraction spokes + one read/write library,” all organized in a hub-and-spoke structure under tools/persona-distill/:

```
tools/persona-distill/
  card-schema.md                     sole shared contract (hub, source-agnostic, owned by T1)
  extract-selfreport-persona/        self-report spoke (T1, grounds attitude axes D2/D3/D4/D6)
  extract-github-persona/            observational spoke (T3, grounds D1/D5)
  extract-stackoverflow-persona/     observational spoke (T3, grounds the low end of D1/D5)
```

Hard rule: spokes depend only on the contract and **do not depend on one another’s schemas** (preventing spoke→spoke dependencies and drift among multiple copies)—this is the key design that fixes the root cause of the existing methods, where the “shared schema is written only in cc, while so/selfreport reference cc in reverse,” causing basis/provenance drift.

card-schema.md (T1, the shared contract) defines the 6-dimensional behavior card: D1 capability assessment | D2 acceptance threshold (primary+flags) | D3 interaction (delegation·supervision·on_offtrack) | D4 trust | D5 domain (area+depth+stack+weak) | D6 autonomy expectation; each dimension carries {value | (primary,flags), source(grounded|injected), basis(observed|stated|stated+observed), confidence}; meta contains authenticity / era{value,basis} / provenance (union: layers? · sources? · self_report? · reputation? + evidence_quotes[{quote,source}]); it also includes D1–D6 enum values, the controlled vocabulary for D5.area, injection distributions, and two-way authenticity-gate principles.

Each of the three spokes describes only “extract from a given source type + which dimensions to ground.” They complement one another; together they ensure that every axis is observed or self-report-grounded by at least one source: extract-selfreport-persona (T1) extracts from first-person self-reports and strongly grounds D2/D3/D4/D6 (acceptance/interaction/trust/autonomy); D1/D5 require corroboration and are medium, with stated→confidence rules and performative/promotional/second-hand authenticity gates. It is the only source that can ground the trust axis D4. extract-github-persona and extract-stackoverflow-persona (T3, respectively adapted from the existing extract-cc-user-persona and extract-so-user-persona and renamed to align with the extract-<source>-persona convention—“cc” originally referred to the driver harness rather than the source; the actual source is GitHub activity) observe behavior trajectories and reliably ground D1 capability and D5 domain·stack. The attitude axes are tightened through content review: GitHub’s D4 trust and D2 acceptance without first-hand evidence are downgraded to injected by default (replacing the earlier wording that inferred grounded D4 from CVE hygiene/auto-merge; only first-hand trust/acceptance statements are grounded); SO’s D4 remains injected by default, and D1 is capped at medium based on the weak signal from a single post + reputation (no longer blind@high). The T3 adaptations also perform two structural cleanups: ① delete the complete “shared schema is written only in cc, while so references cc in reverse” schema table and reverse reference from both spokes (the root cause of drift), replacing them with a reference to ../card-schema.md; ② add basis to every grounded dimension (grounded values from observation are marked observed, distinguishing transcriptional facts from review judgments; injected dimensions do not carry basis). Each observation-based spoke includes a prominent “Limitations and defects” section: only D1×D5 is reliably supported by first-hand observation; the attitude axes D2/D3/D4/D6 are injected priors/extrapolations in observation-based sources, and a single card is not faithful to a real person’s attitude. The sources are biased (SO toward people who get stuck and ask questions / survivor self-selection, GitHub toward public and active users). The usage boundary is “suitable for laying out a D1×D5 coverage grid; real-person anchors for attitude axes must come from selfreport.” The recruitment multi-source profiles attached to the GitHub spoke (swe-bench.md / terminal-bench.md / domains.md) are shared recruitment data (determining whom to look at); the SO spoke references its pools.stackoverflow. This does not constitute a schema contract and does not count as schema drift.

The card records produced by the three spokes are read and written uniformly by library.py (T1): one library file holds multiple card records; the records are pure data, bidirectionally serializable, forward-compatible with unknown keys (evolution-friendly), and provide the minimal load / get(id) / add read/write operations. The card format is decoupled from sim’s 9-dimensional Persona—the card is a “collected real profile (with orthogonal grounding),” and mapping to sim dimensions belongs to the injection layer (T2).

**Interface**

```
PersonaLibrary(root|path)
- load() -> list[dict]            # Read the entire library (card records)
- get(persona_id: str) -> dict    # Retrieve one card by ID
- add(record: dict) -> None       # Append a card record
```

The card schema is defined by card-schema.md (the sole contract); its integration with spec-0001 models.Persona is covered under Unresolved questions.
The two observation-based spokes (T3) introduce no new code interfaces. They produce the same card shape defined by card-schema.md, which can be validated by PersonaLibrary.validate_card and consumed by T2’s card_to_persona.

**Tests**

Unit tests (T1, library.py):
- PersonaLibrary read/write: after add, load contains the added record, get(id) retrieves an equivalent record, and load on an empty library returns an empty list.
- Card schema round-trip: for a record containing source/basis/confidence and provenance-union fields, to/from dict preserves fields identically; unknown keys are ignored without errors (forward compatibility).
- Constraint validation: card records contain no benchmark/trajectory-derived fields (field allowlist assertion); D5.area ∈ the controlled vocabulary in card-schema.md.

Verification (T3, spoke incorporation, doc/skill level, with no new library-side code/tests):
- The worked-example cards from both spokes (GitHub example A, Stack Overflow example A) run through PersonaLibrary.validate_card successfully and card_to_persona produces a usable Persona (grounded axes pass through, while injected attitude axes are finalized through derived values).
- Static checks: neither spoke contains a spoke→spoke reverse schema reference or its own schema table; every grounded dimension includes basis; D5.area ∈ the controlled vocabulary in card-schema.md.
- spec validate has no errors, and spec render has no drift.

**Files (single-writer ownership)**

T1:
  - `tools/persona-distill/card-schema.md`
  - `tools/persona-distill/extract-selfreport-persona/SKILL.md`
  - `tools/persona-distill/extract-selfreport-persona/reference.md`
  - `tools/persona-distill/extract-selfreport-persona/recruitment/seeds.md`
  - `backend/ahe_beta/distill/library.py`
  - `backend/tests/distill/test_library.py`

T3:
  - `tools/persona-distill/extract-stackoverflow-persona/SKILL.md`
  - `tools/persona-distill/extract-stackoverflow-persona/reference.md`
  - `tools/persona-distill/extract-github-persona/SKILL.md`
  - `tools/persona-distill/extract-github-persona/reference.md`
  - `tools/persona-distill/extract-github-persona/recruitment/domains.md`
  - `tools/persona-distill/extract-github-persona/recruitment/swe-bench.md`
  - `tools/persona-distill/extract-github-persona/recruitment/terminal-bench.md`

### Injection side: card_to_persona bridge layer (T2)

Collected cards must pass through the sole bridge layer card_to_persona (T2) before entering sim: field mappings translate cards into sim dimensions—

| Card dimension | sim dimension | Description |
|---|---|---|
| D1 Evaluation ability | D1Eval | Unify surface↔shallow |
| D5 Domain(area/depth/stack/weak) | D2Domain + D2Depth | |
| D2 Acceptance threshold(primary) | D3Accept | Derived dimension; write directly when grounded (override derivation) |
| D3 Interaction(delegation/supervision/on_offtrack) | D41Grain / D42Supervise / D43Correct | |
| D4 Trust(over-trust/balanced/skeptical) | trust(blind/balanced/skeptical; over-trust↔blind) | Derived dimension; write directly when grounded (override derivation) |
| D6 Autonomy expectations(advisory/collaborative/agentic) | D5Autonomy | Sampled dimension; write directly |

Axes with source=grounded in the card are written directly to the corresponding sim dimensions; among them, D2→d3 and D4→trust map to sim's derived dimensions, while the others
(D1/D5/D3/D6) map to sampled dimensions and are already written directly; missing derived dimensions are filled in by spec-0005/T1 finalize_persona.

**Overriding derivation** is the core design of this layer: sim has only three derived dimensions, d3/trust/d6. Of these, d3 (from card D2) and trust (from card D4)
are written directly when already grounded in the card and are not rewritten by derive_d3/derive_trust—otherwise, expert×over-trust (selfreport example C /
Karpathy) would be simulated as its opposite, skeptical×rigorous. This design depends on spec-0005/T1 reducing finalize_persona to
fallback-only (filling only derived dimensions not supplied by the card); this task group makes the corresponding adjustment there. sim D6Authz (authorization scope, a derived dimension) has no corresponding
axis in the card—the semantics of card D6 are “what role the agent is expected to play” rather than “what it is authorized to do,” so it is not grounded and is still filled in by finalize through derivation from
D5Autonomy + task_risk. Invalid/missing enum values raise explicit errors (no silent fallback), exposing
collection quality issues at the injection boundary; the batch entry point is card_to_personas(library).

**Interface**

```
card_to_persona(record: dict) -> Persona        # Single card → sim Persona; pass grounded axes through, derive the rest via finalize
card_to_personas(library: PersonaLibrary) -> list[Persona]
```

**Tests**

Unit tests:
- Overriding derivation (core): after injecting selfreport example C / Karpathy (D1=expert, D4=over-trust, D2=ship-fast, all grounded),
  Persona.trust = the mapped value of over-trust (not derive_trust(expert)=skeptical), and d3 is not rigorous—that is, grounded values have not been rewritten.
- Pass-through + derivation: grounded axes pass through; missing derived axes are correctly and reproducibly filled in by finalize.
- Enum unification/validation: mappings such as surface↔shallow are correct; invalid/missing enum values → explicit errors (no silent fallback).
- End-to-end: feed the injection output to 0005/T5 run_session (offline ScriptedPersonaClient + scripted harness) and complete one session.
- Batch: card_to_personas maps multiple cards to a Persona list of the same length.

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/persona_io.py`
  - `backend/tests/user/sim/test_persona_io.py`

Dependency DAG: `T1 → T2`, `0005/T1 → T2`, `T1 → T3`

## Drawbacks

The costs of this proposal are concentrated in four areas: ① On the collection side, the three real extraction methods are incorporated as vendored adaptations rather than reused directly from the source repository, requiring manual
synchronization—if the methods' previous location (the NexAU repository) later evolves the contract, this repository's card-schema.md will not follow automatically and will require a separate port;
② Observational sources (GitHub / Stack Overflow) can reliably ground only D1 ability and D5 domain·stack; attitude axes (D2/D3/D4/D6)
are almost entirely downgraded to injected. Observational spokes expand coverage breadth rather than attitude depth, and diversity in
real-person attitude anchors in the training signal still depends on selfreport as the sole source; ③ To preserve grounded values against derivation overrides, the injection layer (T2) must explicitly distinguish
grounded/injected by source and raise errors for invalid enums. This is more complex than a design in which "cards and sim are isomorphic," and depends on the external prerequisite that spec-0005/T1 finalize_persona
be reduced to fallback-only; ④ This task group explicitly does not add library-side hard gates to the contract (mandatory basis validation and mandatory
injected attitude axes for observational sources). In the short term, contract enforcement depends on each spoke author's voluntary compliance rather than tool-based validation as a backstop.

## Rationale and alternatives

- **Hub-and-spoke shared contract vs each spoke carrying its own schema**: choose hub-and-spoke (T1 establishes the hub, and T3 follows the same pattern when expanding the spokes). Separate schemas
  inevitably drift—the existing methods currently define the shared schema only in cc, with so/selfreport referencing cc, and basis/provenance have already
  drifted across the three; a contract change in one place takes effect for all, and each new source adds only a thin spoke, keeping them decoupled and extensible. The cost is first extracting the shared parts into a contract (T1),
  and, when T3 incorporates the two observational spokes, simultaneously removing their bundled schema tables and reverse references.
- **Incorporate real methods vs rewrite**: choose incorporation (for both T1's selfreport and T3's GitHub/StackOverflow). The existing methods already encode
  “evidence or abstention / orthogonal dimensions / bidirectional authenticity gates (represented by the trace-floor authenticity gate for observational sources).” Rewriting would inevitably distort them and violate
  the constraint that “personas come from real data”; the cost is that artifacts brought in from another repository must be vendored with their origins identified, without modifying the originals.
- **A selfreport-only first slice vs all three sources at once**: choose selfreport as the first slice (T1), with cc/so inserted later as thin spokes under the same contract
  (delivered by T3). selfreport is the only source that grounds trust axis D4 and includes card_to_persona rules for overriding derivation (exactly what T2 needs), avoiding
  an oversized first slice.
- **Downgrade observational-source attitude axes to injected vs retain grounded values inferred from behavior** (T3): choose downgrading to injected. Inferring trust/acceptance from CVE hygiene/auto-merge/
  reputation is fragile extrapolation that would contaminate the training signal by treating synthetic attitudes as real-person attitudes; the cost is that attitude axes in observational cards are almost all
  injected (correctly reflecting the fact that “observational sources cannot observe attitudes”), with real-person attitude anchors left to selfreport.
- **Place the recruitment profile in the github spoke for SO to reference vs duplicate it in each** (T3): choose the former. The profile is inherently multi-source (one profile lists both
  github repos and SO tags), and duplication would introduce drift across copies; this leaves only one cross-spoke reference to shared recruitment data, which is not a schema contract.
- **T3 only incorporates documentation/skills, without adding library-side hard gates**: choose documentation first. Hard gates (mandatory basis and mandatory injected attitude axes for observational sources) are library-side
  hardening that changes validate_card, with greater risk and scope; defer to follow-up work (see Unresolved questions).
- **Grounded values override derivation vs always finalize** (T2): choose overriding. Always finalizing would discard genuinely grounded trust/acceptance/
  authorization in the card, collapsing an orthogonal real profile onto sim's derived surface (violating the authenticity of the training signal; see selfreport example C); the cost is that the injection layer must distinguish
  grounded/injected by source.
- **Explicit mapping table vs cards and sim being isomorphic (no mapping)** (T2): choose explicit mapping. Cards retain the original real profiles, sim uses controlled enums, and the mapping layer
  absorbs the differences.
- **Errors for invalid values vs safe defaults** (T2): choose errors—defaults would silently turn poor-quality collection into "apparently valid" personas, contaminating the signal.

## Prior art

The three tasks in this group all originate from a set of real extraction methods previously stored in the NexAU repository, but not methods of NexAU itself:
extract-cc-user-persona (GitHub traces L0–L5, the original source of the shared schema/enums/D5.area vocabulary/injection distributions, renamed in this group to
extract-github-persona), extract-so-user-persona (Stack Overflow API, renamed to
extract-stackoverflow-persona), and extract-selfreport-persona (first-person self-reports; reference example C explicitly states that
card_to_persona must use grounded D2/D4 to override derive_trust/derive_d3, otherwise real people are simulated as their opposites—this is precisely
the direct basis for T2's design for overriding derivation). T1 uses the latest conventions of extract-selfreport-persona as its template (structure and writing style), consolidating the shared parts of all three
into the sole contract tools/persona-distill/card-schema.md (6-dimensional card + enums + D5 vocabulary + injection distributions + authenticity gates +
basis quadruple + iron rules: grounded must have evidence_quote, injected confidence=low); T3 brings vendored adaptations into this repository,
without modifying the originals, incorporating the other two methods as observational spokes that follow the same contract. T2's injection layer depends on spec-0005/T1
dimensions.Persona and finalize_persona (the fallback-only contract; this group depends on its reduction to that role), and the spec-0005/T5 run_session
entry point; on the consumer side, backend/ahe_beta/distill/library.py (PersonaLibrary/
validate_card) is also confirmed able to consume the output and is not modified. Overall, this corresponds to CLAUDE.md's “distillation module” and the constraint that “personas come from real data, not constructed from benchmarks or trajectories,”
as well as the Persona field conventions in spec-0001/T1.

## Unresolved questions

- **Source coverage (T1/T3)**: cc/so have been added by T3; when/whether “future sources” will be added as subsequent thin spokes under the same contract remains undecided.
- **Library-side enforcement of the contract (T3)**: should library-side hard gates be added to card-schema.md (hardening through mandatory basis field validation / mandatory
  injected attitude axes for observational sources)? This group explicitly does not do so (the user is deferring library-side hard gates); this is follow-up work, which will change the card-schema.md contract +
  validate_card (T1 files).
- **T2 prerequisites**: overriding derivation depends on spec-0005/T1 reducing finalize_persona to fallback-only (changed alongside this group); if it is not
  ready, overriding derivation cannot take effect.
- **Eventual unification of the card schema and sim/models.Persona**: how to ultimately unify the 6-dimensional behavioral card, spec-0001 models.Persona (a quintuple), and sim's
  9 dimensions remains undecided; details of the 6-dimensional card → 9-dimensional enum mapping table will converge as the T1 contract evolves, and the derivation
  rules for sim D6Authz as an injection axis remain undecided; if they are later unified into a shared Persona, the T2 injection layer can be reduced to thin validation or removed.
- **Cross-spoke sharing of the recruitment profile (T3)**: should pools.stackoverflow, which the SO spoke references in the github spoke,
  be further extracted to a neutral location to fully eliminate this last spoke→spoke reference? Current assessment: recruitment data is inherently multi-source and is not a schema
  contract, so retain it for now.
- **Whether to refactor the source repository as well**: should the methods' previous location (the NexAU repository) also be refactored into hub-and-spoke form (shared contract + thin skills, adding
  basis/unifying provenance/adding card_to_persona override notes)? This would change their source repository and is a separate matter; this repository's card-schema.md
  consistently follows T1's latest selfreport conventions.
- **Seed scenario library**: should a “seed scenario library” (SeedScenario) also be distilled? CLAUDE.md's distillation module includes a scenario library; this group focuses first on
  personas, with the scenario library to be discussed separately.

## Future possibilities

Future extensions include: ① Continue adding thin spokes for more sources under the same contract (“future sources” beyond the already incorporated selfreport / GitHub / Stack
Overflow); ② Add library-side hard gates to card-schema.md (hardening through mandatory basis field validation and mandatory
injected attitude axes for observational sources), upgrading constraints that currently depend on voluntary adherence to documentation into enforcement by validate_card; ③ Ultimately unify the 6-dimensional behavioral card, spec-0001
models.Persona (a quintuple), and sim's 9 dimensions into one shared Persona representation, at which point the T2 injection layer can be reduced to thin validation or even
removed; ④ Refactor the corresponding source methods in their previous location (the NexAU repository) into hub-and-spoke form as well (shared contract + thin skills),
keeping the contracts on both sides aligned over the long term; ⑤ Distill a “seed scenario library” (SeedScenario) alongside personas, covering the other half of the scope of CLAUDE.md's distillation
module.

