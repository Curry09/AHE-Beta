# Reference: GitHub Persona Extraction

<!-- Spec-0037/T5: D7 defaults to injected; never infer impatient from PR speed; enums come only from the hub. -->

GitHub evidence collection by dimension, trace-floor and cross-layer consistency authenticity gates,
attitude-axis injection, endpoint reference, three examples, and recruitment profiles.
Read this file when performing an extraction.

All dimension **enums, the controlled `D5.area` vocabulary, injection distributions, card shape,
and authenticity verdicts** are defined in the sole shared contract,
[`../card-schema.md`](../card-schema.md). This file covers only what differs for GitHub as an **observational** source.

## 1. Ground dimensions from GitHub activity

GitHub is an `observed` source: dimensions grounded from it carry `basis: "observed"`.
**Only D1/D5 can be observed reliably.** Attitude axes (D2/D4/D6/D7 and most of D3) default to `injected` (see §3).

### D1 evaluation_capability — *strong, verifiable*
`blind | surface | competent | expert` (see card-schema.md for the enum)
- **Ground from GitHub:** technical depth in issue bodies (precise reproductions, root-cause reasoning)
  and the substance of PRs (real logic fixes versus documentation/version bumps). Read the intent of the diff, not activity counts.
- blind = no code evidence; surface = builds apps but never reviews deeply; competent = real bug fixes;
  expert = library maintenance / substantial fixes spanning modules. **Mark `grounded` / `basis: "observed"`.**

### D5 domain — *strong: area+depth+stack*
`{area, depth, stack, weak}`; `area` must be a single token from card-schema.md's controlled vocabulary.
- **Ground from GitHub:** the actual technology in repos/PRs determines `area` and `stack`
  (a concrete technology array such as `["typescript","node"]`). Derive `depth ∈ {shallow|working|deep}`
  from substance. `weak` lists subdomains where effective capability drops one tier: ground it from evidence
  of clear avoidance or mistakes; otherwise inject 0–2 entries or `[]`. **Mark `grounded` / `basis: "observed"`.**
- Determine `area` from **what the library is**, not *who happens to use it* (see recruitment/domains.md for disambiguation).

### D2 acceptance_bar — *weak; default to injected*
`primary ∈ {ship-fast|functional|modern-correct|type-safety-purist}`, `flags ⊆ {tests,types,scope,security,style,a11y,perf}`
- **Default to `injected`.** CI/tests/strict-tsconfig in a repo are **behavior**, not the person's stated
  acceptance criteria. Do not mark acceptance grounded by inferring an attitude from their output.
- **Exception permitting grounded:** only a **first-hand statement of acceptance criteria** in an issue/PR,
  such as "I will not merge changes without tests" or "Any `any` is unacceptable", supports `grounded` /
  `basis: "stated"`. **Each flag needs its own supporting quote**; omit unsupported flags rather than filling them in.
  Pure self-report is capped at `confidence: medium` (see card-schema.md's `stated` → confidence rules).

### D3 interaction_style — *weak; mostly injected*
`delegation ∈ {vibe-dump|loose|spec-driven}`, `supervision ∈ {hands-off|reviews|micromanage}`, `on_offtrack ∈ {abandon|retry|correct|fix-self|file-issue}`
(Semantics: supervision means process involvement; on_offtrack means the response to quality failure and **does not drive waiting patience**. See card-schema.md.)
- **delegation:** issue-writing style is a **weak observation**: a minimal sentence suggests `vibe-dump`;
  a structured issue with reproduction steps leans toward `spec-driven`. Clear evidence supports `grounded` /
  `observed` with conservative confidence; otherwise inject.
- **on_offtrack:** use `fix-self` only when **the person actually submitted a fix PR** (real behavior, `observed`);
  use `file-issue` only for an actual structured bug report. Otherwise inject. **Do not** interpret fast commits
  as impatient: that belongs to D7.
- **supervision:** GitHub does not show whether someone needs visibility while an **agent is working**.
  Default to `injected` / `low`.

### D7 time_temperament — *unobservable; default to injected*
`patient | steady | impatient`
- **Default to `injected` / `low`.** Activity traces almost never reveal tolerance for waiting without activity.
- **Never** infer `impatient` or `patient` from PR/commit frequency, issue-closing speed, or contribution volume.
- **Never** couple it to on_offtrack (fix-self ≠ patient; abandon ≠ impatient). Sample independently from the contract's injection distribution.
- **Exception:** only a first-hand statement about waiting, which is extremely rare, supports `grounded` /
  `stated` (for example, "I give up after waiting half an hour" in an issue).
  `extract-selfreport-persona` supplies real-person anchors for waiting temperament.

### D4 trust_model — *unobservable; default to injected*
`over-trust | balanced | skeptical`
- **Default to `injected` / `confidence: low`.** GitHub does not show how much someone trusts an **agent**.
- **Do not** infer grounded trust from CVE hygiene, auto-merge, or review habits: that is fragile extrapolation (principle 4).
- **Exception:** a first-hand trust statement, which is rare, supports `grounded` / `stated`.
  `extract-selfreport-persona` supplies real-person anchors for trust.

### D6 autonomy_expectation — *unobservable; default to injected*
`advisory | collaborative | agentic`
- GitHub does not show the role someone expects an agent to play: default to `injected` / `low`.
  Heavy reliance on automation (CI/CD/bots/"automate …") may bias sampling as a **weak prior**, but the result remains injected.

## 2. Authenticity gates: trace floor and cross-layer consistency

Observational sources use **trace-floor and consistency** gates, rather than self-report's
performative/promotional gate (verdict vocabulary is in card-schema.md).
Run Step 1 (floor), then Step 2 (consistency), before mapping dimensions.

| Verdict | Trigger | Action |
|---------|---------|--------|
| `insufficient_evidence` | Below the evidence floor: own repos + real PRs + diagnosed issues total < ~3, especially 0 repos and 0 PRs | **Do not admit**; route to a non-GitHub source. These blind newcomers / vibe users exist outside GitHub. |
| `authentic` | Shallow signals (profile/repos) agree with deep signals (issue/PR substance) across **≥2 nonempty layers** | Admit; mark D1/D5 `observed`. |
| `contaminated` | Learner-level profile contradicts expert-level PRs; implausible cross-stack speed; AI formatting (`id=` fences, excessive templating) | **Isolate; never admit.** |
| `suspect` | Partial or ambiguous evidence | Isolate for human review. |

`authentic` requires **≥2 nonempty layers**. A layer returning 0 results never counts as grounding.
Never upgrade `contaminated` to `authentic`, or use injected values to upgrade `insufficient_evidence` to `authentic`.
**Volume check:** large counts (1000+ PRs) suggest contamination. Admit only if the deep substance is
**consistent within one domain**; high volume across unrelated stacks means `contaminated`.

## 3. Inject attitude axes: default for D2/D4/D6/D7 and most of D3

GitHub does not reveal attitude axes or waiting temperament. When an axis is genuinely unsupported,
**sample independently per card from card-schema.md's controlled injection distributions**, orthogonally
to grounded D1/D5. Set `source: "injected"` / `confidence: "low"`; injected dimensions **have no basis**.

- See card-schema.md for the delegation / supervision / on_offtrack / trust_model / autonomy /
  **time_temperament** / D5.weak proportions. Do not duplicate them here: in the hub-and-spoke design,
  the contract is the single source of truth.
- **Mandatory orthogonality:** `on_offtrack` ⊥ `time_temperament`. Never require fix-self to pair with patient,
  or abandon with impatient.
- Weak priors may bias sampling (self-described vibecoders toward over-trust + vibe-dump;
  library maintainers toward spec-driven), but **still mark the values injected**.
  **Do not use weak priors for D7:** activity provides no reliable signal.
- **Sample; never lock combinations by tier (mandatory).** Make a real independent draw for each card,
  rather than deterministically mapping from D1. If every `surface` card becomes
  `ship-fast+over-trust+hands-off`, the dimensions are coupled: resample. Inspect the batch for distribution collapse.

## 4. GitHub endpoint reference

```
GET /users/{u}                                              # L0 profile (created_at→era, bio)
GET /users/{u}/repos?sort=pushed&per_page=100               # L1 langs, own/fork ratio, themes
GET /repos/{owner}/{repo}/contents                          # L2 tsconfig/CI/tests/CHANGELOG/release (behavior, not an acceptance statement)
GET /repos/{owner}/{repo}/contents/{path}                   #    Inspect specific files
GET /search/issues?q=author:{u}+type:issue&sort=created     # L3 issue bodies → D1 depth; only first-hand acceptance statements ground D2
GET /search/issues?q=author:{u}+type:pr&sort=created        # L4 PR substance → D1, D5; a personally submitted fix → on_offtrack=fix-self
```

`/search/issues` returns `body`/`title`/`repository_url`: read the body, not just the title.
Unauthenticated Search API quotas are low; use authentication at scale.
**Strip every PII field:** `name`, `company`, `location`, `email`, `blog`, `twitter_username`.

## 5. Examples: D1/D5 grounded observed, attitude axes injected

### A — authentic: admit

Investigate the handle through L0–L4. Shallow evidence (14-year veteran, TS bio) agrees with deep evidence:
maintains a 134★ type-safe DI library with Turborepo + release-please; 105 issues with precise TS reproductions;
246 PRs including manual CVE backports. **Consistency → authentic.**
D1/D5 are grounded (`observed`). A **first-hand acceptance statement** grounds D2 (`stated`, medium).
An **actual submitted PR** grounds on_offtrack=fix-self (`observed`); issue style weakly grounds delegation.
**No first-hand evidence for D4 trust / D6 autonomy / supervision / D7 waiting temperament → injected (`low`).**
The old inference of skeptical from CVE hygiene has been removed.
D7 is **independent** of fix-self: submitting a fix does not imply patient.

```json
{
  "id": "gh-example-a",
  "authenticity": "authentic",
  "era": {"value": "pre_vibe", "basis": "account created 2012-08; first repos 2013"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "expert", "source": "grounded", "basis": "observed", "confidence": "high"},
    "D2_acceptance_bar": {"primary": "type-safety-purist", "flags": ["types"], "source": "grounded", "basis": "stated", "confidence": "medium"},
    "D3_interaction_style": {
      "delegation": {"value": "spec-driven", "source": "grounded", "basis": "observed", "confidence": "medium"},
      "supervision": {"value": "reviews", "source": "injected", "confidence": "low"},
      "on_offtrack": {"value": "fix-self", "source": "grounded", "basis": "observed", "confidence": "medium"}
    },
    "D4_trust_model": {"value": "balanced", "source": "injected", "confidence": "low"},
    "D5_domain": {"area": "dev-tooling", "depth": "deep", "stack": ["typescript","node"], "weak": ["timezones/DST"], "source": "grounded", "basis": "observed", "confidence": "high"},
    "D6_autonomy_expectation": {"value": "collaborative", "source": "injected", "confidence": "low"},
    "D7_time_temperament": {"value": "steady", "source": "injected", "confidence": "low"}
  },
  "provenance": {
    "layers": ["L0","L1","L2","L3","L4"],
    "evidence_quotes": [
      {"quote": "skipLibCheck ... not a long term solution; I don't accept any implicit any in this codebase", "source": "github.com/.../issues/11552"},
      {"quote": "backport esbuild 0.28.1 ... fixes GHSA", "source": "github.com/.../issues/NNNNN"},
      {"quote": "I'm willing to submit a PR", "source": "github.com/.../issues/MMMMM"}
    ]
  },
  "behavioral_prediction": "Gives precise constrained tasks, submits his own fix when the agent stalls; Low experience ratings for any/implicit-magic (his one STATED standard). Trust/autonomy/waiting temperament are injected priors, not observations; real-person trust and D7 anchors must come from selfreport."
}
```

### B — contaminated: reject

Shallow evidence: a 2024 account, leetcode/hackathon repos, bio "continuously learning".
Deep evidence: 80 PRs with substantial redis sentinel fixes, oxc (Rust) semantic binding, and strapi races;
one issue has `id=` fences. **Learner-level profile ⊥ cross-stack expert speed + AI formatting → contaminated.**

```json
{
  "id": "gh-example-b",
  "authenticity": "contaminated",
  "reject_reason": "cross-layer contradiction: learner profile vs Rust/redis expert PRs; AI-format issue; implausible velocity",
  "action": "isolated, not admitted to persona library"
}
```

### C — insufficient_evidence: reject

0 public repos, 0 PRs, account created 2024-08, and only one issue ("BUILD: issue loading the python library":
an ipython traceback with no diagnosis). Below the trace floor, consistency cannot be checked;
D2/D3/D4 would be ~100% injected. **Reject as `insufficient_evidence`; do not admit.**

```json
{
  "id": "gh-example-c",
  "authenticity": "insufficient_evidence",
  "reject_reason": "0 repos, 0 PRs, 1 undiagnosed issue — below trace floor; cannot ground D1/D5; gate cannot run",
  "action": "not admitted; route this user type (blind newcomer) to Stack Overflow / off-GitHub sourcing"
}
```

The gate must reject this anti-pattern: mark a nearly empty account `authentic`, inject most dimensions,
and list empty layers (`L1`,`L4`) in `provenance.layers`. The blind traceback-pasting newcomer *type*
matters for diversity, but **cannot honestly be extracted from an empty GitHub account**.
Use `extract-stackoverflow-persona` or beginner forums instead.

## 6. Source-to-output responsibilities

| Source | Spoke | observed vs stated | Reliably grounds | Best use |
|--------|-------|--------------------|------------------|----------|
| **GitHub footprint** | **extract-github (this skill)** | **observed** | **D1, D5** | Builder personas at expert/competent tiers; D1×D5 coverage grid |
| Stack Overflow | extract-stackoverflow-persona | observed | D1, D5 (+ weak delegation evidence) | blind/surface help-seekers |
| blogs / interviews / talks | extract-selfreport-persona | stated | D2, D3, D4, D6, D7 | Attitude/interaction/waiting anchors; **the only reliable source for grounding D4 and D7** |
| dev surveys (SO/JetBrains) | (weights) | aggregate | distribution | Sampling weights |

The three extraction spokes complement one another: no source grounds every axis, but **every axis
can be grounded from observations or self-reports by at least one source**.
**Observational sources (GitHub/SO) ground capability/domain; self-reports ground attitudes and waiting temperament.**
Do not expect genuine D7 evidence from observational sources.

## 7. Pluggable recruitment profiles: choose before L0

Domain coverage is a **library-level** goal, **decoupled** from individual extraction.
Never distort a card's D5 to meet a quota. A recruitment profile only guides *whom to extract next*.
Profiles are plugin files under [`recruitment/`](recruitment/); replacing or adding one does not change the core skill.

A profile declares:
- `priority_domains`: the subset of the controlled D5 vocabulary to cover.
- `pools`: **multiple sources**. `github` (repos / skill-profiles) serves this skill;
  `stackoverflow` (tags) serves `extract-stackoverflow-persona`. One profile, the same domains, both ends of D1:
  GitHub fills expert/competent, SO fills blind/surface.
- Recruitment across the contributor ladder (core maintainer → drive-by reporter), preventing a domain's D1 distribution from collapsing to expert.

Available profiles:
- [`recruitment/swe-bench.md`](recruitment/swe-bench.md): library/source-editing domains (Python).
- [`recruitment/terminal-bench.md`](recruitment/terminal-bench.md): ops / systems / CLI domains.
- [`recruitment/domains.md`](recruitment/domains.md): domain registry, with anchor repos and disambiguation for each controlled token.

Choose the next underfilled `priority_domain`, use its pool, select an issue reporter/contributor,
and run **L0–L5 plus the gates** as usual. Admit the card on its own merits; the profile decides only *whom to inspect*.
If `D5.area` falls outside `priority_domains`, mark it **off-target**: it may still be admitted on substance,
but does not count toward that target's coverage. Do not keep filling already saturated domains.

## 8. Library distribution discipline: the library is the real object

A card is only a sample. A **distribution of cards** approximating real users drives correct,
generalizable harness improvements. Evaluate the library, not just its cards:
- **Cell coverage:** the important cells are `D1 tier × D5 domain` within `priority_domains`.
  Each relevant cell needs **≥ ~3–5 cards** for its mean user experience to become a signal.
  GitHub fills `competent`/`expert` rows; SO fills `blind`/`surface` rows.
- **Marginal balance:** no single value should dominate an axis. If 80% of cards are `infra-devops` or `surface`,
  coverage is clustered: fill sparse cells.
- **Clone check:** inspect injected D2/D3/D4/D6/D7 after each batch. A tier collapsing to one combination,
  or `abandon` always pairing with `impatient`, means coupled sampling: resample (§3).
- **Usable ≠ counted:** usability requires the count threshold **and** marginal balance **and** passing the clone check.
