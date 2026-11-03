---
number: "0037"
title: "Reframe the human axis: time temperament ⊥ quality failure · process involvement · distillation spoke alignment"
issue: 0
slug: persona-time-temperament-reframe
summary: "With the seam approaching a human-operated CLI, the gap in the waiting experience lies on the “human” axis: the old design hardwires patience to the quality-failure strategy (d43), while supervision remains turn-based monitoring. This group adds tempo (card D7) to drive patience, limits d43 to answering what to do when the result is wrong, reframes supervision as process involvement, and marks D6Authz as a session policy excluded from cards; the hub adds D7 and orthogonal injection; injection defaults to steady; three distillation spokes align ground/inject. No separate Translation module is introduced, and projection still follows judge→intent→act; interrupt/queued/slash are not hardwired into the human axis."
tasks:
  - id: T1
    title: "Write the 0037 live snapshot"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0037-persona-time-temperament-reframe.md
    scope: "Clearly document the motivation: after seam 0035/0036, the gap in the waiting experience lies on the human axis; the old d43 ties patience to it, distorting orthogonal personas; prohibit hardwiring interrupt/queued/slash into cards. Select tempo-driven patience, d43 limited to quality failure, supervision=process involvement, D6Authz excluded from cards, and hub D7 + spoke alignment. Explicitly state that no independent Translation module will be built and no experience uplift over the old system is claimed."
    acceptance: "spec validate passes; the body includes Summary/Motivation/Reference-level explanation/Rationale and alternatives; the DAG and file assignments are clear; Unresolved records backfilling existing cards and the D7 hard-gate boundary."
  - id: T2
    title: "sim: tempo-driven patience · process involvement semantics · D6Authz session policy"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/dimensions.py
      - backend/ahe_beta/user/sim/state.py
      - backend/ahe_beta/user/sim/clauses.py
      - backend/ahe_beta/user/sim/demo.py
      - backend/tests/user/sim/test_dimensions.py
      - backend/tests/user/sim/test_state.py
      - backend/tests/user/sim/test_heartbeat.py
    scope: "Add TimeTemperament/tempo to Persona; the patience baseline and decay in init_state/make_coef follow tempo rather than d43; high process involvement (d42 every_step) may add stuck_extra; clauses/BLOCK-P describe process involvement and time temperament, without wording that hardwires interrupt/queued/slash into dimensions; D6Authz documentation marks it as a session policy (semi-derived, not a human axis in the card library). The demo demonstrates tempo orthogonality. Include supporting unit tests."
    acceptance: "patience0/decay are tiered by tempo; the same d43 with different tempo values produces different patience; clauses include Process involvement / Time temperament; relevant pytest tests pass; the demo can print tempo and stuck_extra."
  - id: T3
    title: "hub: add D7 and semantic notes to card-schema"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tools/persona-distill/card-schema.md
    scope: "Add D7_time_temperament（patient|steady|impatient）and its injection distribution to the sole public contract; specify that supervision=process involvement and on_offtrack=quality-failure strategy and does not drive patience while waiting; enforce orthogonality: on_offtrack ⊥ time_temperament; conformance: when D7 is missing, fall back to steady on the injection side (backward compatibility with old cards); new cards should specify it explicitly. Do not modify the three spokes (assigned to T5)."
    acceptance: "card-schema includes the D7 enum, injection proportions, enforced orthogonality, and semantic notes for supervision/on_offtrack; the authorization scale remains excluded from the card library."
  - id: T4
    title: "Injection: card_to_persona reads D7→tempo"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/persona_io.py
      - backend/tests/user/sim/test_persona_io.py
    scope: "card_to_persona maps D7_time_temperament → Persona.tempo; a missing field falls back to steady (backward compatibility with old cards, without raising an error); invalid enum values still raise errors. D6Authz is still not read from cards. Include corresponding unit tests."
    acceptance: "Cards with D7 inject the correct tempo; cards without D7 use tempo=steady; invalid D7 raises an error; no regressions in existing grounded overrides of derivation (D2/D4)."
  - id: T5
    title: "Align distillation spokes with D7 and human-axis semantics"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T3
    relates-to:
      - ref: 0006/T1
        type: extends
      - ref: 0006/T3
        type: extends
    parallel: false
    files:
      - tools/persona-distill/extract-selfreport-persona/SKILL.md
      - tools/persona-distill/extract-selfreport-persona/reference.md
      - tools/persona-distill/extract-github-persona/SKILL.md
      - tools/persona-distill/extract-github-persona/reference.md
      - tools/persona-distill/extract-stackoverflow-persona/SKILL.md
      - tools/persona-distill/extract-stackoverflow-persona/reference.md
    scope: "Align the three thin spokes with the hub's D7 and semantic notes; continue to reference only ../card-schema.md without embedding enums. ① selfreport: add D7 to the ground table and quote mining (verbatim statements about tolerance for waiting/idle waiting); supervision→process involvement; clarify that on_offtrack≠patience while waiting; update the wording “6 dimensions” to include D7; add D7 to example cards. ② github/SO: D7 defaults to injected (using the hub distribution); state in the limitations section that waiting temperament cannot be observed; prohibit deriving impatient from PR volume/disappearing after posting or rigidly coupling it with abandon; add injected D7 to example cards. Do not modify card-schema (assigned to T3), modify the backend, or recollect the existing card library."
    acceptance: "No residual “only 6 dimensions” wording in the three spokes; the selfreport ground table includes D7 and an explanation of orthogonality; the two observational spokes explicitly state that D7 defaults to inject and prohibit incorrect derivation; example card structures include D7_time_temperament and can be consumed by validate_card/card_to_persona."
  - id: T6
    title: "Probes: orthogonal observability of tempo / process involvement / d43"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
      - T4
    relates-to: []
    parallel: false
    files:
      - tools/dev/probes/probe_persona_reframe.py
      - tools/dev/probes/probe_swebench_persona.py
      - tools/dev/probes/probe_d43_quality_fail.py
    scope: "Scripted probes verify that the refactored axes are observable: tempo A/B (differences in patience/waiting menus), differences in process involvement, and differences in d43 quality-failure paths; support overriding tempo/d42/d43. Do not claim user experience uplift relative to the old system; do not use probes as CI gates."
    acceptance: "All three probes can run independently (script/script harness/optional real seed); overrides are documented; do not modify sim core files (assigned to T2/T4)."
---

# 0037 · Persona-axis refactoring: Time temperament ⊥ quality failure · Process involvement · Distillation spoke alignment

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level nine-section rust-RFC overview. -->

## Summary

This group refactors the user-side **persona axis**: separate “how long can I tolerate waiting?” from “what do I do when the result is wrong?”, and align the distilled card library with sim consumption.

Core contract:

- Add **time temperament** `tempo` (card field `D7_time_temperament`: `patient | steady | impatient`) to drive the waiting-patience baseline and decay;
- **Quality failure strategy** (sim `d43` / card `on_offtrack`) only answers what to do when delivery quality is inadequate; it does **not** drive patience;
- **Process involvement** (sim `d42` / card `supervision`) answers whether visibility is needed during execution; it is **not** a product control (interrupt / queued / slash);
- Mark **authorization scope** `D6Authz` as session policy (partially derived from autonomy expectations); it **does not enter the card library**;
- Add D7, the injection distribution, and enforced orthogonality to the card contract hub (`tools/persona-distill/card-schema.md`); injected cards missing D7 → `steady`;
- Align the three distillation spokes on “which can ground D7 / which can only inject it”; prohibit coupling waiting temperament to on_offtrack.

Projection continues through the existing **judge → intent → act** path; **no** separate Translation module is introduced. This group **does not claim** user-experience uplift over the old system (axis observability ≠ proven net benefit).

## Motivation

### The interface is already close to a real CLI; the gap is in the “person”

The internal/external user↔harness channels and visible states have converged: internal=message (including out-of-band progress/status), external=interrupt; stdin uses unified writes and `type=reply` for soft wake-up; queued/status may be available while busy. Much of the variation among real people lies on the **time axis**: some keep_waiting after several minutes of idle waiting, while others lose patience after two minutes, ask for progress, or interrupt. If the persona axis still couples “patience” to “failure strategy,” then however realistic the interface becomes, simulated users will diverge only along quality-failure paths and collapse into the same kind of person during long waits.

### The old coupling: patience tied to d43 / on_offtrack

The old sim indirectly influenced waiting patience through quality failure strategies (such as give_up vs feedback). This distorts real orthogonal combinations, for example:

- **Demanding but patient**: wants to file-issue / handover when the result is inadequate, but still patiently keep_waiting during idle time;
- **Readily accepting but unable to wait**: accepts a roughly adequate delivery, but asks for progress/interrupts after two minutes of idle waiting.

Once the two are coupled, distilled card `on_offtrack=abandon` is easily misread as impatient, and the training signal conflates “giving up on the delivery” with “being unable to wait any longer.”

### Outdated supervision semantics

Card/sim supervision still carries a sense of “whether to read diffs / turn-based monitoring.” Now that the interface layer has visible in-progress events, the persona axis should express **process involvement** (whether opacity causes unease, whether visibility is needed), rather than coupling the current harness UX enums to personality.

### Distillation spokes lag behind the hub

Hub-and-spoke collection: a single contract `card-schema.md` + thin spokes (selfreport / github / stackoverflow). If the hub already has D7 but the spokes still teach extraction in “6 dimensions,” newly collected cards will lack D7 → injection will set all of them to `steady`, collapsing the tempo axis in the library and making sim-side A/B work pointless.

### Explicit non-goals

- Do not put interrupt / queued / slash into persona-axis enums or extraction guides;
- Do not introduce a separate “situation→action” Translation module;
- Do not reopen the persona pipeline epic or batch-backfill existing cards (old cards default to steady);
- Do not treat probes as CI gates or claim net benefit from A/B testing against the old system.

## Guide-level explanation

Three personas (describing people only, without tying them to v0 field names):

1. **Impatient**: becomes restless during idle time as soon as a task is submitted; when the progress bar stops, asks for an update or considers interrupting. How they handle a delivery quality failure is a separate matter—they may still be willing to let the agent try again, but **waiting** is uncomfortable.
2. **Patient**: can go do something else during the same long task; continues waiting when the heartbeat shows activity. If the final result is poor, they may finish it themselves or open an issue—**patience and failure strategy are orthogonal**.
3. **High process involvement**: not necessarily impatient, but dislikes black boxes; wants visible progress during execution, and prolonged silence makes them feel “stuck” sooner (with a small additional patience deduction), without implying that they must press a particular product button.

On the distillation side:

- When reading **self-reports** (blogs/interviews), ground statements such as “I cannot stand waiting without feedback” and “I will get a coffee and come back” in D7; ground “If the result is wrong, I will fix it myself” in on_offtrack—do not merge the two statements into one dimension.
- When reading **GitHub / SO** traces, waiting temperament is usually **not observable** → sample D7 from the contract's injection distribution and mark `injected` / `low`; do not infer impatient from PR frequency or “disappearing after posting” and lock it to abandon.

During a session: card → `card_to_persona` → `Persona.tempo` / `d42` / `d43` → state-machine patience coefficients + BLOCK-P wording → existing three-hop decision process.

## Reference-level explanation

### Persona-axis mapping (card ↔ sim)

| Card (hub) | sim | Semantics | Drives |
|----------|-----|------|------|
| `D7_time_temperament` | `Persona.tempo` | Tolerance for waiting/idle time | Initial patience and decay |
| `interaction_style.supervision` | `d42` | Process involvement (need for visibility) | Additional patience deductions when stuck, etc. |
| `interaction_style.on_offtrack` | `d43` | Strategy after quality failure | Intent on failure paths; does **not** drive patience |
| (Not in cards) | `D6Authz` | Session authorization scope | Partially derived from autonomy expectations |
| `interaction_style.delegation` | `d41` | Delegation granularity | Existing behavior |
| `D2_acceptance_bar` / `D4_trust_model` | `d3` / `trust` | Acceptance / trust | Existing override derivation |

Enums (card side; the contract source of truth is `card-schema.md`):

- D7: `patient | steady | impatient`
- supervision: `hands-off | reviews | micromanage` (semantics=process involvement)
- on_offtrack: `abandon | retry | correct | fix-self | file-issue` (semantics=quality failure; ≠waiting)

Injection distribution (unobserved axis): D7 is patient 25% / steady 50% / impatient 25%; sampling independently of on_offtrack is **mandatory**.

### State and wording

- `init_state`: initial patience is tiered by tempo (low for impatient, high for patient); task volume introduces only minor variation and does not override temperament tiers.
- `make_coef`: `patience_decay` follows tempo; `stuck_extra` is >0 for high process involvement.
- `clauses` / BLOCK-P: Process involvement + Time temperament; **do not** put current harness product controls into dimension wording as personality definitions.

### Injection and compatibility

`card_to_persona`: if `D7_time_temperament.value` exists → map tempo; if the field is missing → `steady` (old-card compatibility); invalid values raise errors. D6Authz is never read from cards.

### Distillation spokes (T5)

The hub-and-spoke structure is unchanged: spokes depend only on `../card-schema.md`, not on one another's schemas.

| Spoke | D7 | Key semantic revisions |
|-------|----|--------------|
| selfreport | May **ground** (verbatim statements about waiting/idle waiting); inject without evidence | supervision→process involvement; on_offtrack≠waiting; wording includes D7; add the field to example cards |
| github / SO | **Inject by default** | State “waiting temperament is not observable” in the limitations section; prohibit deriving impatient from PR volume/disappearing after posting or locking it to abandon; add injected D7 to examples |

Do not recollect the existing card library; do not change the hub (T3 has already established the contract).

### Probes (not gates)

- `tools/dev/probes/probe_persona_reframe.py` — scripted orthogonality
- `tools/dev/probes/probe_swebench_persona.py` — optional real seed; can override `--tempo/--d42/--d43`
- `tools/dev/probes/probe_d43_quality_fail.py` — quality-failure paths

Acceptance criteria: the axes are observable and orthogonality holds; do **not** write “better than the old system.”

e2e / probe entry points (not CI gates):

```text
tools/dev/probes/probe_persona_reframe.py
tools/dev/probes/probe_swebench_persona.py
tools/dev/probes/probe_d43_quality_fail.py
```

Current maintenance tools are invoked from the repository root using `PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.<module>`.
See `tools/dev/README.md` for each tool's explicit inputs, credentials, and whether it calls a model; they do not register another set of experiment configurations or multi-task entry points.

Implementation comment convention: code delivered in this group is traceable using “this number + task number” (a comment prefix such as this file's `number` plus `/T2`; see the comment conventions in tools/spec-driven-development).

### Task DAG and file allocation

```text
T1 Live snapshot
 ├─ T2 sim (dimensions/state/clauses/demo + unit tests)
 ├─ T3 hub card-schema
 │    └─ T5 three-spoke documentation alignment (done)
 └─ T2+T3 → T4 persona_io
              └─ T2+T4 → T6 probe
```

| Task | Status | Owned files (mutually exclusive) |
|------|------|------------------|
| T1 | done | `docs/specs/0037-persona-time-temperament-reframe.md` |
| T2 | done | `user/sim/{dimensions,state,clauses,demo}.py` + corresponding unit tests |
| T3 | done | `tools/persona-distill/card-schema.md` |
| T4 | done | `persona_io.py` + `test_persona_io.py` |
| T5 | done | `SKILL.md` / `reference.md` for the three spokes |
| T6 | done | Three `probe_*.py` |

Dependencies: `T1→T2`, `T1→T3`, `T1+T2+T3→T4`, `T1+T3→T5`, `T2+T4→T6`.

## Drawbacks

- All old cards without D7 use `steady`; newly collected selfreport/github cards explicitly include D7, but D7 from observational sources is still mostly injected, so “real-person waiting anchors” in the library still rely heavily on selfreport.
- D7 from observational sources is almost entirely injected → real-person anchors for waiting temperament still mainly rely on selfreport (structurally similar to the historical situation for attitude axes).
- Enum strings (hands-off/reviews, etc.) are retained for now, with only semantic comments changed; readers may briefly confuse old names with new meanings.
- Quality-failure paths such as handover have limited testability without a real writable workspace; probes cannot replace acceptance testing with a workspace.
- This group does not establish uplift over the old system, so product narratives must not overstate that “user-experience evolution has been verified.”

## Rationale and alternatives

- **Independent tempo axis vs continuing to use d43 as a patience proxy**: choose an independent axis. Coupling it to d43 cannot express orthogonal personas and contaminates distillation semantics.
- **Change process-involvement semantics vs introduce a new dimension to replace supervision**: choose changed semantics while retaining the enum slot. Occam's razor: avoid another disruption to card structure; product controls stay out of enums.
- **Keep D6Authz out of cards vs include it in the card library**: choose to keep it out. Authorization is session/product policy, not “who this person is”; including it in cards would couple experimental conditions to the profile.
- **Missing D7 → steady vs mandatory error**: choose steady for old-card compatibility; new cards should specify it explicitly. Leave a hard gate to Unresolved.
- **Align spokes in the same group vs open a separate distillation group**: choose the same group. Keeping contract changes and consumers (sim + spokes) in one group closes the loop; the spokes involve documentation alignment, not a new pipeline.
- **Independent Translation module vs existing three-hop process**: choose the three-hop process. Adding tempo/involvement to state coefficients and prompts is sufficient for projection; there is no necessary evidence for a separate entity.
- **Rejected alternative: put interrupt/queued into persona**: no. These belong to the harness product surface; the object being evolved must not be coupled to the persona source of truth.

## Prior art

- This repository's persona pipeline: hub-and-spoke `card-schema` + selfreport/github/SO spokes; `card_to_persona` is the sole card→sim bridge; override derivation preserves grounded trust/acceptance.
- User-side waiting loop and interface: heartbeat judge→intent→act; visible progress/status on stdout; unified stdin writes and reply soft wake-up—this group addresses “the gap is in the persona axis” rather than changing the wire protocol again.
- Probe practice: matrix probes verify axis observability without serving as release gates (benchmark held-out discipline remains unchanged).

## Unresolved questions

- In the merged library (`persona_library.json` = sr + gh), should **older legacy cards without D7** also receive batch backfilling (the current injection default is `steady`)?
- Should `validate_card` require D7 for **new cards** (while old cards remain valid)?
- Should behavior acceptance testing for handover in a real writable workspace have a separate probe/task?
- Should there be a large-N user-experience A/B test of the old system vs this group? This group explicitly does **not** make it a prerequisite for acceptance.
- Should the sampler explicitly mix “D1×D5 from GitHub + attitudes from selfreport/injection” (currently whole cards are used, without automatic axis composition)?

## Future possibilities

- Continue using selfreport to fill in real-person impatient/patient anchors and calibrate the injection distribution; use the SO spoke to fill the blind/surface grid.
- Library-side hard gates: mandatory basis, and observational-source attitude-axis/D7 injection constraints promoted to `validate_card`.
- If old enum names remain misleading, open another group for renaming (micromanage→high involvement, etc.) and card-library migration—outside this group's scope.
- Finer coupling between process involvement and visible events (progress/status), such as “no new progress” and stuck detection, can evolve on the waiting-loop side, while still keeping specific UX controls out of cards.
- Optional: separate card-library files (`persona_library_selfreport.json` / `persona_library_github.json`) + a merged default library, making experiments by source easier (already implemented on the runtime side, outside this group's Task file ownership).
