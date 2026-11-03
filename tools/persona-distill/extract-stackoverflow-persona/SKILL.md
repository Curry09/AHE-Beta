---
name: extract-stackoverflow-persona
description: >-
  Extract behavior-first personas of low-literacy / newcomer / blind users from
  Stack Overflow to fill the segment the GitHub footprint spoke cannot reach. Use
  when building the user-agent persona library and needing blind/surface-tier or
  web/data-analysis personas, or when sourcing "stuck help-seeker" user types.
  Emits the shared persona card defined in ../card-schema.md (the single public
  contract); this skill is one thin "spoke" among the observed-behavior spokes
  (GitHub) and the self-report spoke. Stack Overflow is an OBSERVED source: it
  reliably grounds D1 (capability, at the low end) and D5 (domain/stack from tags),
  plus D3 delegation weakly from the question text; the attitude axes (D2 acceptance,
  D4 trust, D6 autonomy, D7 time temperament) are NOT visible and default to
  injected priors. The authenticity gate is INVERTED vs a trace floor — messy
  newbie questions are authentic; over-polished AI-formatted questions from
  competent askers are the ones to reject.
  rep≈1 accounts are suspect. Read the "Limitations and Defects" section before treating any
  single card's attitude axes as real.
---

# Extract Stack Overflow Persona

A **thin extraction skill (spoke)**: extracts personas of low-literacy / newcomer / blind users from **Stack Overflow**,
filling the segments that `extract-github-persona` (which reads builders with rich traces, is expert-skewed, and **rejects** the low-literacy majority at the trace-floor)
cannot reach. The card schema / enums / D5 vocabulary / injection distribution / authenticity adjudication vocabulary all come from the sole public contract
[`../card-schema.md`](../card-schema.md); this file covers only the source-specific aspects of **extracting from observational sources such as SO help-seeking posts and determining which dimensions can be reliably grounded**. It does not embed the schema or depend on any other skill.

Stack Overflow is a place where people **“ask only when they cannot solve it themselves”**, so the asker population **itself belongs to** the blind / surface / newcomer
segments. This skill's sole responsibility is to **fill the low-literacy + web/data-analysis quotas**, producing cards under the same contract for inclusion in a single library. It complements
`extract-github-persona` (also observational, reading builders with rich traces) and `extract-selfreport-persona` (self-reported, reading attitudes and disposition toward waiting).

## Core Principles (Reversal Relative to the GitHub Observational Spoke)

1. **Filler only—the only outputs of this skill are `blind`/`surface`.** Target low-end + GitHub-thin domains (web/frontend, data-analysis,
   beginner scripting). `competent`/`expert` questioners are **out of scope**: isolate them (`action: out-of-scope, route to GitHub skill`),
   **do not** collect them as `surface`. *Being stuck ≠ low sophistication*—a capable dev stuck on an obscure bug is still competent.
   **competent tells (any one qualifies as non-surface)**: gives precise expected/actual, posts a clean MRE, reproduces against a known-good baseline,
   has built a workaround, isolates multiple failure cases, or asks a precise mechanism/boundary question. surface = can describe the problem but is shallow, copy-paste-oriented, and lacks root-cause reasoning.
2. **No trace floor (reversed).** On GitHub, low trace → `insufficient_evidence`; here, **low reputation / a single stuck question
   is itself a persona signal**—a user with rep≈1 asking a genuinely beginner question is a complete, database-eligible `blind` card.
3. **Authenticity gate reversed.** A *messy* beginner question is **authentic** (people who are genuinely stuck write this way); the red flag is the opposite: a rep≈1 / brand-new account
   posting an **overly polished, AI-formatted question** (template sections, `id=` fences, deep topic ⊥ with low rep) → `suspect`/`contaminated`.
4. **Attitude axes (D2/D4/D6/D7) default to `injected`.** Help-seekers rarely expose acceptance criteria, trust models, or waiting temperament—inject them and mark
   `confidence: low`. SO reliably grounds **D1, D5** (+ weak observation of D3 delegation).
5. **Do not be overconfident about capability (D1).** A single post + reputation **is insufficient to** `blind@high`—rep and question quality are weak signals,
   **D1 grounded is capped at `confidence: medium`** (basis `observed`). Do not treat “rep=1 + a traceback” as high.
6. **Same schema, strip PII.** Produce the card shape from card-schema.md (D1–D7 + `authenticity` + `era` + `provenance`);
   every grounded value requires the question’s original wording + URL; discard display name / any real-identity fields.
7. **Dimensions are orthogonal—never derive one dimension from another, and never lock injected dimensions by tier.** Same as the iron rule #3 in card-schema.md.
   **Especially**: disappearance after posting → on_offtrack may be weakly observable `abandon`, but it is **forbidden** to lock `impatient` because of this—D7 is independently injected.

## Which SO dimensions are reliably grounded (the mirror of GitHub’s observation-oriented approach)

| Dim | SO strength | Ground from (question) | basis / source |
|-----|---------|------------------|----------------|
| **D1 evaluation_capability** | **Strong (low-end)** | `owner.reputation` + question quality; **capped at medium** | `grounded` / `observed` / **≤medium** |
| **D5 domain** | **Strong** (area+stack) | `tags` → `area` + `stack`; `weak` low-end cases are often `injected` or `[]` | `grounded` / `observed` |
| **D3 interaction_style** | weak observation of delegation | Question = delegation wording; with comment follow-up, → process involvement/quality failure is weakly observable; otherwise inject | delegation has textual evidence →`observed`; the rest are mostly `injected` |
| **D2 acceptance_bar** | no →`injected` | At most weakly inferred from “accept the first thing that runs” | `injected` / `low` |
| **D4 trust_model** | no →`injected` | Weakly inferred from blind copying of an accepted answer | `injected` / `low` |
| **D6 autonomy_expectation** | no →`injected` | Weakly inferred from wording (“just give me X” = advisory; “help me automate it” = agentic) | `injected` / `low` |
| **D7 time_temperament** | no →`injected` | Help-seeking posts almost never expose waiting temperament; **do not** derive impatient from “disappeared after posting” | `injected` / `low` |

`era` takes `owner.creation_date` (approximately 2025-10 split); brand-new accounts are common and welcome—fill both blind and the `post_vibe` gap.
**Injected dimensions carry no `basis`**—`basis` only describes how already-grounded values are evidenced (`observed` here).

## Workflow

```
SO persona extraction progress:
- [ ] Select a target gap (tier + domain)—can use pools.stackoverflow tags from a given recruitment profile
      (see ../extract-github-persona/recruitment/)
- [ ] Find candidate askers (low rep + target tags / blind-phrase search)
- [ ] Fetch the asker's profile (rep, creation_date, answers given, tags)—**record `reputation`**
- [ ] Read the question body (D1, D5 + era; delegation is a weak observation)
- [ ] Tier gate: if D1 reads as competent/expert (see competent tells) → isolate out-of-scope, stop
- [ ] SO authenticity gate (consistency + AI-polish check; no trace floor)
- [ ] Map: D1(≤medium)/D5 grounded(observed), delegation uses observed if text is present;
      D2/D4/D6/D7 inject(low, do not lock it down; on_offtrack ⊥ D7)
- [ ] Strip PII, hash id, produce the card-schema.md card structure (must include D7_time_temperament)
```

The Stack Exchange API, targeting recipe, gate details, injection, and two examples (database entry blind / reject AI polish) are in
[reference.md](reference.md). Enumeration / D5 vocabulary / injection distribution / card shape / authenticity-gate vocabulary are in
[`../card-schema.md`](../card-schema.md).

## Limitations and Defects (Content Quality Boundaries of Observational Methods)

SO is an **observation-oriented** source; its content-quality boundaries must be recorded honestly—on a single card, the attitude axes are **not faithful to a real person’s “attitude”**:

- **Only D1 (capability) × D5 (domain/stack) are supported by firsthand observation (and D1 is only ≤medium).** The attitude/interaction axes
  **D2/D3/D4/D6/D7** in a help-seeking post **are injected priors/extrapolations**—SO cannot observe acceptance criteria, trust, autonomy, or **waiting temperament**.
- **The strongest source bias: SO favors people who are stuck and come to ask.** It is extremely easy to hit the same stereotyped stuck-card pattern (every card becomes blind×vibe-dump×over-trust×impatient).
  Therefore, injected dimensions must be genuinely sampled card by card, followed by a post-batch clone check (including D7 ⊥ on_offtrack).
- **Inference spans that are too large are unreliable.** “Disappears after posting” supports at most a weak inference of on_offtrack=`abandon`; **do not** lock in D7=`impatient`.
  Real-person anchors for attitude and waiting temperament must come from `extract-selfreport-persona`.
- **Usage boundary: fill the low-end rows of the D1×D5 coverage grid.** **Do not** use its D2/D4/D6/D7 as real-person anchors.

(This section is consistent with the “authenticity first” principle in card-schema.md.)

## Completion Report

Report: the gaps filled (tier + domain + era), which dimensions are grounded (`observed`) versus injected, and the authenticity ruling. Explicitly **reject** AI-polished/AI-incoherent issues; route competent/expert questioners back to GitHub. **Remember**: in the source, D2/D4/D6/D7 are injected priors, and D1 is only ≤medium—label this truthfully in the report.
