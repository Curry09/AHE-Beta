---
number: "0010"
title: "Seed scenario pipeline: collection (distillation) and injection into SeedSource"
issue: 10
slug: seed-scenario-pipeline
summary: "This group implements the seed scenario pipeline: it connects “collecting seed scenarios from real data” and “injecting seed cards into SeedSource provisioning” into a single chain, supplying real tasks for 0009's SeedSource (the workspace provisioning seam) and 0005's user-side simulation. It corresponds to the **seed scenario library** half of the output from the “distillation module” in CLAUDE.md (the persona half is 0006; this group mirrors it symmetrically), enforcing the constraint that “seeds come from real data, and benchmarks remain held-out throughout.” It provides upstream inputs to 0009's SeedSource, with zero changes on the consumer side (models / seed_source / sources / run.py)."
tasks:
  - id: T1
    title: "Seed scenario collection (distillation, in skill form)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0006/T1
        type: note
      - ref: 0009/T1
        type: note
    parallel: false
    files:
      - tools/seed-distill/seed-card-schema.md
      - tools/seed-distill/extract-harness-seed/SKILL.md
      - tools/seed-distill/extract-harness-seed/reference.md
      - backend/ahe_beta/distill/seed_library.py
      - backend/tests/distill/test_seed_library.py
    scope: "Implement collection using a hub-and-spoke structure and define the seed card library format. Scope of this step: ① seed-card-schema.md (the sole public contract: seed card schema + enums\n+ two-gate principles + held-out field storage conventions, source-agnostic); ② extract-harness-seed (a thin skill that harvests from real sources such as closed\nissues+merged fix PRs and references the contract); ③ seed_library.py reads and writes. Does not integrate concrete data source fetching implementations or implement\ncard→SeedScenario injection mapping (assigned to T2). Logs/SO/future sources will be added later as thin skills under the same contract (see open-questions).\nIntelligent pairing (persona×seed), containers/private repository authentication, and the oracle objective scoring runtime are all out-of-scope (see open-questions)."
    acceptance: "seed-card-schema.md is the sole source-agnostic public contract (seed card schema + enums + two-gate principles + held-out field storage\nconventions); extract-harness-seed is a thin skill that only references the contract, has no skill→skill dependencies or dangling references, and does not actually copy NexAU's skill\nfiles into this repository (the spec only describes deliverables); seed_library reads and writes libraries containing multiple cards according to the contract, supports retrieval by id, and is forward-compatible with unknown keys; card records'\n`source.not_in_benchmark` is always true (a contract-level assertion); domain ∈ controlled vocabulary, capability_probed ⊆ capability taxonomy."
  - id: T2
    title: "Seed injection (card → SeedScenario)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to:
      - ref: 0006/T2
        type: note
      - ref: 0009/T1
        type: note
      - ref: 0009/T4
        type: note
      - ref: 0009/T3
        type: note
    parallel: false
    files:
      - backend/ahe_beta/distill/seed_adapter.py
      - backend/tests/distill/test_seed_adapter.py
    scope: "Inject seed cards (0010/T1) into SeedScenario: card_to_seed maps fields (see the mapping table in design) and outputs an `{version, seeds}`\nenvelope; for text-only scenarios without a repo, it produces `workspace: null` or `kind=\"empty\"`; for git scenarios, it produces `WorkspaceSpec{kind=\"git\",\nparams={repo, commit}, setup}` (setup is prefixed for the venv according to 0009/T3). Does not change the card format (assigned to T1); does not change SeedScenario/\nWorkspaceSpec/SeedSource (0009, zero consumer-side changes; this group only reads their contracts). **Does not implement** intelligent pairing (persona×seed, see\nopen-questions), containers/private repository authentication, or an oracle scoring runtime."
    acceptance: "For valid cards, card_to_seed produces SeedScenario instances that can be materialized by 0009 SeedSource: git cards produce `WorkspaceSpec{kind=\"git\",\nparams={repo=https://github.com/…git, commit=resolved SHA}}` with setup already prefixed for the venv; text-only cards produce workspace=null\nor kind=\"empty\". **Held-out red line**: the resulting SeedScenario (and to_dict/envelope JSON) **must never contain** oracle/test_cmd/\ngates; these are extracted separately via extract_sidecar. card_to_seeds produces an `{version, seeds}` envelope that can be fed directly to run.py's\n_load_seeds with zero consumer-side changes. Missing repo_at / unresolved placeholders / invalid enums → explicit errors."
---

# 0010 · Seed Scenario Pipeline: Harvest (Distillation) and SeedSource Injection

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level, nine-section rust-RFC overview. -->

## Summary

This group implements the seed scenario pipeline: connecting “harvesting seed scenarios from real data” with “injecting seed cards into SeedSource for provisioning” as one chain,
providing real tasks for 0009’s SeedSource (workspace provisioning seam) and 0005’s user-side simulation. This corresponds to the **seed scenario library** half produced by the “distillation module” in CLAUDE.md
(the persona half is 0006; this group is its symmetric counterpart), enforcing the constraint that “seeds come from real data, and benchmarks are held out throughout.” Upstream provisioning feeds 0009’s SeedSource; the consumer side (models / seed_source / sources / run.py) requires no changes.

Data-flow spine:

```
Real-world sources (closed issue+merged PR · logs · Stack Overflow · future sources)
        │  Collect/synthesize (T1, hub-and-spoke: shared contract seed-card-schema.md + thin extraction skills)
        ▼
   Seed card library (source-agnostic seed cards: task/source/env/oracle… + authenticity and non-benchmark gates)
        │  Inject (T2, card_to_seed: field mapping → SeedScenario; oracle/test_cmd go into a sidecar, never into the loop)
        ▼
   spec-0001 models.SeedScenario{description, workspace} ─► 0009 SeedSource.provision materializes the workspace
        ─► 0005 sim run_session runs one session ─► user experience + issue
```

Read the diagram as the tasks: **T1** defines “what to harvest and what a seed card looks like” — rather than creating a new skill, it incorporates the existing real-data extraction method (previously documented in
the NexAU repository as `extract-harness-seed`), and organizes it in a **hub-and-spoke** structure: one shared contract, `seed-card-schema.md` (seed card schema +
enums + two-gate principle, source-agnostic), plus thin extraction skills that only describe “harvesting from a particular type of real source + applying the two gates,” depend only on the contract,
and do not depend on one another. This step first delivers the contract + `extract-harness-seed` (the harvest pipeline for closed issues + merged fix PRs, the sole real source of ground-truth
oracles); logs/SO/uncovered sources will be added later as thin skills using the same contract. The library schema is this contract. **T2** defines “how a seed card becomes
a SeedScenario that 0009 SeedSource can materialize” (the sole bridging layer, card_to_seed).

**Held-out discipline (critical constraint, red line)**: Seed cards collect the complete `oracle`/`test_cmd`/`gates` (objective scoring evidence), but these are
**benchmark-side** artifacts: when injected, `task.prompt → SeedScenario.description` **must never carry oracle/test_cmd**; scoring fields go into a
**sidecar**, not `SeedScenario`, and not into the training loop. The rationale comes from CLAUDE.md: “benchmarks are held out throughout: they do not participate in training or release
gates” — training signals come only from user experience on the “simulated real usage” distribution, while objective oracle scoring belongs to the parallel evaluation system on the harbor side.

Relationship to 0009: this group is the upstream provider for 0009’s pluggable SeedSource provisioning. The seed card’s `source.repo`+`env.repo_at` map to
0009/T4’s `WorkspaceSpec{kind="git", params={repo, commit}}`, while `env.setup` maps to `WorkspaceSpec.setup` (prefixed for the venv according to
the 0009/T3 convention); repo-free plain-text scenarios fall back to `workspace: null` or `kind="empty"`. Intelligent pairing
(persona×seed) and heavier capabilities such as container/private-repository authentication are **out of scope for this group**, recorded as open questions / out of scope (see each Task).

## Motivation

The training signal for the entire evolution comes from user experience on the “simulated real usage” distribution; its authenticity depends on seed scenarios coming from real data rather than being constructed from
benchmarks (a CLAUDE.md constraint). The existing real-data harvest method (`extract-harness-seed` in the NexAU repository) has already established “harvest,
don’t author / derive oracles from resolved real artifacts / two gates (oracle gate + harbor reproducibility gate) / decouple from held-out benchmarks” — rewriting it would distort the method, so T1 incorporates it rather than recreating it. More importantly, this supports **extensibility**: mirroring persona collection, shared elements (seed card
schema + enums + two gates) are extracted into a single contract; each thin skill depends only on the contract and is independent of the others. A contract change takes effect for all skills, and adding a new real source requires only
adding a thin skill without touching the others.

However, harvesting produces complete seed cards containing “real tasks + benchmark-side scoring evidence,” while SeedSource consumes “description +
WorkspaceSpec.” The formats differ, so they need an explicit, testable mapping layer; this is the motivation for T2. More importantly, **held-out
discipline**: seed cards carry oracle/test_cmd/gates (objective scoring). If these enter SeedScenario during injection, benchmark features leak into the
training loop and held-out scoring is exposed to user-side simulation — directly violating CLAUDE.md’s “benchmarks are held out throughout: they do not participate in training or release
gates,” and breaking the separation whereby “training signals come only from user experience.” Therefore, the injection layer must strip scoring fields at the boundary: description retains only the original
text of the real request, while scoring evidence goes into a sidecar for parallel evaluation on the harbor side.

## Guide-level explanation

The collection (distillation) side (T1) uses a **hub-and-spoke** structure, symmetrically mirroring 0006/T1 (persona collection), rather than creating a large new skill: the single shared contract,
seed-card-schema.md (source-agnostic), defines the seed card schema (source · task · domain · capability_probed ·
difficulty · scope · autonomy_required · oracle · env · pairing_constraints · gates · provenance) + enums
+ the two-gate principle (authenticity/non-benchmark gate + oracle and harbor reproducibility gate) + conventions for storing **held-out fields** (oracle/test_cmd/gates).
The thin extraction skill, extract-harness-seed, describes only “harvesting from closed issues + merged fix PRs and other real sources + passing
the two gates + grounding which fields”; it only references the contract and has no dependencies on other skills, incorporating the existing NexAU method in `extract-harness-seed`. This step
first delivers these two items; logs/SO/uncovered sources will be added later as thin skills using the same contract. Deliverables also include seed_library.py for reading and writing
the seed card library (storing and retrieving card records according to the contract), for use by the injection side.

The collected seed cards are then injected into 0009’s SeedSource provisioning through card_to_seed (T2): one card is mapped to spec-0001
models.SeedScenario — `task.prompt` becomes description, `source.repo`+`env.repo_at` becomes a Git workspace (0009/T4),
and `env.setup` becomes venv-prefixed setup (0009/T3). **Held-out red line**: objective scoring artifacts (oracle/test_cmd/gates) go into a
sidecar; they never enter SeedScenario or the training loop. The output is an `{version, seeds:[...]}` envelope, aligned with seed_scenarios.json and
run.py’s _load_seeds. T1→T2 forms the sole bridge between “collection” and the “0009 SeedSource engine,” symmetrically mirroring 0006 (persona
collection and injection).

## Reference-level explanation

The collection side (T1) is implemented as a hub-and-spoke directory structure (`tools/seed-distill/`, symmetric with `tools/persona-distill/` (0006)):

```
seed-card-schema.md            Single shared contract (hub), source-agnostic
extract-harness-seed/          Thin skill (spoke), depends only on the contract (incorporates existing NexAU methods)
(future) extract-log-seed / extract-so-seed / …  Each is a thin skill, also depending only on the contract
```

Iron rule: skills depend only on the contract and **not on one another** (preventing skill-to-skill dependencies and multi-copy drift). seed-card-schema.md (the shared contract)
defines source-agnostic seed card fields: `source{repo, issue_url?, fix_ref, not_in_benchmark}` (real source + non-
benchmark assertion), `task{prompt, context}` (preserve the original form of the real request; do not sanitize it; the prompt is the original text injected into
SeedScenario.description), `domain / capability_probed / difficulty / scope / autonomy_required`
(calibration and pairing metadata), `oracle{tier, spec, reference_solution, confidence}`, `env{repo_at, setup, test_cmd,
base_image, external_deps, budget}`、`pairing_constraints`、`gates{oracle_gate, harbor_repro_gate}`,
`provenance`. It also contains controlled values for each enum (the domain vocabulary is shared with persona D5.area, plus the capability taxonomy,
difficulty/scope/autonomy/oracle tier, etc.), the two-gate principle (oracle gate: success must be independently harnessable and judgeable; harbor reproducibility
gate: the environment can be set up deterministically and the oracle run), and the **storage convention for held-out fields** — `oracle`/`test_cmd`/`gates` are benchmark-
side objective scoring artifacts. The contract specifies that they are collected with the card but placed in a sidecar during injection and never included in SeedScenario (T2 enforces this red line; the contract declares it here). extract-harness-seed (the thin skill) incorporates the existing NexAU method and only describes “harvesting one card from resolved
real artifacts such as closed issues + merged fix PRs / highly upvoted Q&A + passing the two gates + transcribing FACT fields / judging JUDGMENT fields”; enums, gates, and card shape
are all referenced from seed-card-schema.md rather than embedded again. **Incorporation means referencing the contract only; NexAU’s skill files are not copied into this repository** (the spec describes
deliverables only). seed_library.py uses one library file to hold multiple seed card records; it is pure data, supports bidirectional serialization, is forward-compatible with unknown keys (evolution-
friendly), and provides minimal load / get(id) / add operations, mirroring 0006’s PersonaLibrary. The card format is decoupled from models.SeedScenario: a card is “a real task collected + benchmark-side scoring
evidence,” and mapping it to SeedScenario (including stripping held-out fields) belongs to T2.

T1 interface:

```
SeedLibrary(root|path)
- load() -> list[dict]           # Read the entire library (seed card records)
- get(seed_id: str) -> dict      # Retrieve one card by id
- add(record: dict) -> None      # Append one card record
```
The seed card schema is defined by seed-card-schema.md (the sole contract); mapping to models.SeedScenario is described in T2.

T1 tests (backend/tests/distill/test_seed_library.py) cover three areas: SeedLibrary read/write (after add, load includes the entry;
get(id) retrieves an equivalent record; loading an empty library returns an empty list); card schema round-trip (for a record containing source/task/env/oracle/gates/
provenance, to/from dict fields match exactly; unknown keys are ignored without errors for forward compatibility); constraint validation (reject a card record if
source.not_in_benchmark is not true, to prevent benchmark contamination; domain ∈ the controlled vocabulary in seed-card-schema.md,
capability_probed ⊆ the capability taxonomy).

The injection side (T2) centers on card_to_seed(record: dict) -> models.SeedScenario, using the following table to translate a seed card into
a SeedScenario:

| Seed card field | SeedScenario target | Rule |
|---|---|---|
| `task.prompt` | `SeedScenario.description` | Pass through the original text; **must not include oracle/test_cmd/acceptance criteria** (held-out) |
| `source.repo` + `env.repo_at` | `workspace.kind="git"` + `params.repo` + `params.commit` | repo(owner/repo) → `https://github.com/owner/repo.git`; commit=repo_at (**must be resolved to a real SHA**; reject placeholders such as `<parent-...>`) |
| `env.setup` | `workspace.setup` | **Prefix for the venv** (aligned with 0009/T3): inject `python -m venv .venv` at the beginning; rewrite pip steps to `.venv/bin/pip …` |
| Repo-free plain-text scenario | `workspace: null` or `WorkspaceSpec{kind="empty"}` | Put the prompt in description (for an empty source, optionally put the description in a doc; see 0009/T2) |
| `oracle` / `env.test_cmd` / `gates` | **Do not include in SeedScenario** | Put in a sidecar (see held-out red line), for evaluation on the harbor side; invisible to the training loop |

The card_to_seeds(library) output envelope produces `{"version": <int>, "seeds": [SeedScenario.to_dict(), …]}`, shaped to match
backend/seed_scenarios.json and run.py’s _load_seeds (which can consume `data["seeds"]` or a bare array), so the injection output can be
fed directly to the existing loader with no changes to the consumer side. **Held-out discipline (red line)**: oracle / test_cmd / gates are benchmark-side objective scoring
artifacts. During mapping, card_to_seed **strips** them into a sidecar (such as a sidecar file/return structure for `{seed_id: {oracle, test_cmd, gates, provenance}}`); SeedScenario and its to_dict **must never contain** these keys. Rationale: CLAUDE.md says “benchmarks are
held out throughout” — training signals come only from user experience, and oracles belong to parallel evaluation on the harbor side; the two are physically isolated at the injection boundary. Assertion: the injected JSON
contains no oracle/test_cmd/gates. Venv prefixing (aligned with the 0009/T3 convention): for the card’s `env.setup` (such as
`["pip install -e ."]`), prepend `python -m venv .venv` during injection and rewrite bare `pip`/`python` as
`.venv/bin/pip`/`.venv/bin/python`. This enables 0009/T3’s ensure_deps to create a per-workspace venv and makes Sandbox detection of `.venv`
take effect. Missing fields or invalid values (such as a Git-type card without repo_at, an unresolved placeholder in repo_at, or an out-of-vocabulary domain) must produce explicit errors (no silent fallback), exposing
collection quality issues at the injection boundary; this follows the same policy as 0006/T2, which raises an error rather than using a safe default.

T2 interface:

```
card_to_seed(record: dict) -> SeedScenario          # Single card → SeedScenario; held-out fields are stripped
card_to_seeds(library: SeedLibrary) -> dict         # {version, seeds:[SeedScenario.to_dict()...]} envelope
extract_sidecar(record: dict) -> dict               # Stripped oracle/test_cmd/gates (for the harbor side, excluded from the training loop)
```
git type: WorkspaceSpec(kind="git", params={repo, commit}, with env.setup prefixed for venv); plain-text type:
workspace=None (or kind="empty"). The consumer is 0009 SeedSource (this group only reads its contract and makes zero changes to its files).

T2 tests (backend/tests/distill/test_seed_adapter.py) cover: the held-out red line (core; after injecting a card containing oracle/test_cmd/gates, neither SeedScenario.to_dict() nor the card_to_seeds envelope JSON contains these three keys, while extract_sidecar can recover them); git-type mapping (source.repo=owner/repo + env.repo_at=<SHA> → WorkspaceSpec(kind="git", params.repo HTTPS URL, params.commit=SHA), with env.setup prefixed for venv, and the first item being `python -m venv .venv`, pip→`.venv/bin/pip`); plain-text type (a card without source.repo → workspace=None or kind="empty", with prompt populated from description); envelope shape (card_to_seeds produces {version, seeds:[...]}, which can be passed to run.py._load_seeds to obtain an equally long list of SeedScenario objects); validation (missing repo_at / repo_at being an unresolved placeholder / domain outside the vocabulary → explicit errors, with no silent fallback); end to end (optional; injected artifacts are provisioned through 0009 SeedSource.provision, using a local temporary repository and offline mode for git sources, materializing a workspace directory).

File allocation (single-writer ownership):

| Task | Files |
|---|---|
| T1 | `tools/seed-distill/seed-card-schema.md` |
| T1 | `tools/seed-distill/extract-harness-seed/SKILL.md` |
| T1 | `tools/seed-distill/extract-harness-seed/reference.md` |
| T1 | `backend/ahe_beta/distill/seed_library.py` |
| T1 | `backend/tests/distill/test_seed_library.py` |
| T2 | `backend/ahe_beta/distill/seed_adapter.py` |
| T2 | `backend/tests/distill/test_seed_adapter.py` |

Dependency DAG: `T1 → T2`

## Drawbacks

<!-- TODO -->

## Rationale and alternatives

On the collection side (T1), we choose the “hub-and-spoke shared contract” over “a schema bundled with each skill” (as in 0006): individually bundled schemas inevitably drift; changing the contract in one place takes effect for everyone, while a new real source only requires inserting one thin skill, keeping the skills decoupled and extensible. The cost is that the shared portion must first be extracted into a contract. Between “adopting NexAU extract-harness-seed” and “writing a separate seed-distill skill,” we choose adoption: the existing method has already established “harvest, do not author / two gates / decoupling from held-out”; rewriting it would lose fidelity and violate “seeds come from real data.” The cost is bringing in a cross-repository artifact that must be vendored and annotated with its source. For contract field selection, we choose to retain the complete oracle/env/gates (including test_cmd) instead of keeping only the fields needed for injection: a seed card is a faithful transcription of a real artifact, and the scoring evidence must be retained with the card for harbor-side evaluation; held-out discipline is enforced by the injection boundary (T2), rather than discarding the fields during collection—discarding them would make the card unsuitable for reuse in objective evaluation.

On the injection side (T2), among “put held-out fields in a sidecar,” “discard them directly,” and “carry them in unchanged,” we choose the sidecar: carrying them in violates benchmark held-out (contaminating the training signal); discarding them makes the seed card unsuitable for reuse in harbor objective evaluation; a sidecar physically isolates them at the injection boundary and achieves both goals, at the cost of an additional out-of-band artifact that must be managed. Between “use a single bridging layer for field mapping” and “make the card and SeedScenario isomorphic (eliminating mapping),” we choose explicit mapping: the seed card preserves the original real artifact (including benchmark-side fields), SeedScenario is a minimal injection contract, and the mapping layer absorbs the differences and performs held-out stripping here—this is exactly where the red line belongs. repo_at must already be resolved to a real SHA rather than accepting a placeholder/ref (the placeholder `<parent-commit>`, for example, is rejected): 0009/T4 git sources are checked out by commit; an unresolved placeholder would fail only during materialization, so validating earlier at the injection boundary exposes collection defects sooner. For invalid values, we choose explicit errors instead of safe defaults: defaults would silently turn poor collection into “seemingly valid” scenarios and contaminate the signal.

## Prior art

The technical source for the collection side (T1) is the existing real-data harvest method (the NexAU repository `extract-harness-seed`, the original source of the shared schema/two gates): SKILL.md (capability taxonomy, two gates, harvest pipeline), reference.md (enums/oracle tier/repro tier/harvest mechanics), artifact examples seeds/seed-pytest-13537.json and seed-requests-6964.json, and the validator validate_seed.py; this group consolidates their shared portion into the seed-card-schema.md contract, mirroring 0006 (persona collection), with the domain vocabulary shared with persona D5.area.

The consumer/provider contract for the injection side (T2) comes from spec-0001/T1 models.SeedScenario / WorkspaceSpec (read-only, zero changes by this group), the 0009/T1 SeedSource seam and top-level provision, the 0009/T4 git source (kind="git" + params{repo, commit}), 0009/T3 dependency provisioning (the venv-prefixed setup convention, ensure_deps + Sandbox probing .venv), backend/seed_scenarios.json and run.py._load_seeds envelope shape {version, seeds}, the upstream seed-card schema supplied by T1, and the symmetric counterpart 0006/T2 card_to_persona.

The shared normative basis for both Tasks is the CLAUDE.md “distillation module,” “the seed scenario library comes from real data, benchmark held-out throughout,” and the spec-0001/T1 SeedScenario field definition; the basis for the T2 held-out red line is CLAUDE.md “benchmark held-out throughout: it does not participate in training or release gates.”

## Unresolved questions

- Intelligent pairing (persona×seed, domain matching + capability credibility + autonomy fit) is **out of scope for this group**: seed-card includes constraint information such as pairing_constraints (domain/min_capability/autonomy), but pairing logic is an independent downstream spec; run.py currently uses persona[i]×seed[i % len] modulo rotation, and both T1 and T2 explicitly treat this as out of scope and do not make it a task.
- env.base_image / external_deps (container provisioning) and authentication for private repositories (token/ssh injection for clone): T2’s git source + venv-prefixed setup covers only “clone@commit + pip dependencies.” Instances requiring system dependencies or official images, and private repositories requiring authentication, are still not guaranteed to run/be usable—these are all referred to the 0009/T4 open-question, marked as beyond the current capabilities of this framework; the injection layer does not handle authentication.
- Objective oracle scoring (running upstream tests to determine whether a fix is correct) belongs to the harbor-side parallel evaluation system; the held-out red line is maintained, and it never enters this framework’s training loop. T2 only guarantees stripping it into a sidecar at the injection boundary; the runtime form of the sidecar (an out-of-band JSON file versus a returned structure) and how the harbor side consumes it remain to be determined.
- When to add logs/SO (and un sourced items) as “thin skills depending only on seed-card-schema.md”: T1 first lands the contract + extract-harness-seed; the rest will be inserted later.
- Should NexAU’s source skill (only its previous storage location) also be refactored into the hub-and-spoke model (shared contract + thin skill)? This would modify its source repository and is a separate matter; this repository’s seed-card-schema.md uniformly follows the latest extract-harness-seed convention.

## Future possibilities

<!-- TODO -->

