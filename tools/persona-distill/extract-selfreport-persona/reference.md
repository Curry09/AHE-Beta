# Reference: Self-Report Persona Extraction

<!-- Spec-0037/T5: ground/inject D7 and keep on_offtrack ⊥ time_temperament; enums still come only from the hub. -->

Source-type vocabulary, dimension grounding from self-reports, performative/promotional authenticity gates,
`stated`→confidence rules, discovery recipes, and four examples. Read this file during extraction.

All dimension **enums, the controlled `D5.area` vocabulary, injection distributions, card shape,
and authenticity verdicts** are defined in the sole shared contract,
[`../card-schema.md`](../card-schema.md). This file covers only what differs for self-report sources.

## 1. Source types: record `type` for each source

```
blog                | Personal blog / Substack / engineering blog (first-person)
interview-transcript| Podcast or video interview transcript (Lex, Latent Space, …)
conf-talk           | Conference/summit talk transcript or notes
tweet-thread        | First-person X/Mastodon/LinkedIn long post (build-in-public)
newsletter          | An issue of the author's own newsletter
```

Every source must be **first-person** ("This is how *I* …"). A third party describing someone is
`second-hand`: reject it and find a first-hand source. Retrieve the full text. Interviews and long
blog posts contain the workflow details: scan passages about process visibility, quality failure,
waiting tolerance, and what counts as done, rather than relying on titles.

## 2. Ground dimensions from self-reports

Self-report **reverses** the grounding strengths of observational sources: attitude/interaction axes,
including D7 waiting temperament, are its *strong* dimensions. Map explicit statements and quote them verbatim.

### D2 acceptance_bar — *strong: the user experience function*
`primary ∈ {ship-fast | functional | modern-correct | type-safety-purist}`, `flags ⊆ {tests,types,scope,security,style,a11y,perf}`
- Ground the threshold the person **states**. "Not too bad for throwaway weekend projects" and "it works tho"
  imply `ship-fast`. "Deliver code you have proven to work" and "I won't commit code I cannot explain"
  imply `modern-correct` plus the `tests` flag. In production contexts, a lack of security/test concerns
  is itself a signal (Leo: `ship-fast`, no `security` flag).

### D3 interaction_style — *strong*
`delegation ∈ {vibe-dump|loose|spec-driven}`, `supervision ∈ {hands-off|reviews|micromanage}`, `on_offtrack ∈ {abandon|retry|correct|fix-self|file-issue}`
(See card-schema.md for enums and authoritative semantic notes.)
- delegation: "Decrease sidebar padding by half" / a one-line app request implies `vibe-dump`;
  "Write a function with input X and output Y" / "I specify the stack" implies `spec-driven`.
- **supervision = process involvement**, the need for visibility while the assistant works, not a product button:
  "Send it off and leave it alone; a black box is fine" → `hands-off`;
  "I need to see what it is doing / align at checkpoints" → `reviews`;
  "I must watch every step; opacity makes me uneasy" → `micromanage`.
  Reading diffs can corroborate process involvement, but **do not** hard-code interrupt/queued/slash behavior into this axis.
- **on_offtrack = response to quality failure**: what to do when the deliverable is wrong; **it does not drive waiting patience**.
  "Ask for random changes until it goes away" → `retry`; "It is faster to finish it myself" → `fix-self`;
  giving up/closing the task → `abandon`. **Never** put impatience or demands for progress in on_offtrack: that belongs to D7.

### D7 time_temperament — *strong when waiting is explicitly discussed*
`patient | steady | impatient` (see card-schema.md)
- Tolerance for **waiting/inactivity**, **orthogonal** to on_offtrack; the contract requires independent sampling.
- "Get coffee / do something else while it runs / overnight is fine" → `patient`;
  "I can usually wait a while, then check if there is no progress" → `steady`;
  "Two minutes of idle waiting drives me mad; I must see activity" → `impatient`.
- **No explicit waiting/inactivity statement → inject** from the contract distribution. Do not derive D7 from on_offtrack or supervision.
- Demanding but patient (`fix-self`/`file-issue` × `patient`) and casually accepting but impatient (`retry` × `impatient`)
  are both real combinations: ground the dimensions separately.

### D4 trust_model — *strong*
`over-trust | balanced | skeptical`
- Direct trust statements are often explicit: "AI is no longer just an assistant; it is also the builder"
  / "I always Accept All" → `over-trust`; "You are responsible" / "Always verify" → `skeptical`;
  pragmatic ship-but-watch → `balanced`.

### D6 autonomy_expectation — *strong*
`advisory | collaborative | agentic`
- "It is also the builder" / "Forget that the code exists" → `agentic`;
  "Typing assistant" / "Give me options; I will integrate them" → `advisory`;
  "It runs tests, but I review / intervene" → `collaborative`.

### D1 evaluation_capability — *medium; corroborate*
`blind | surface | competent | expert`
- Self-report alone caps `confidence: medium`. "I'm not technical… I cannot figure it out" → `blind`;
  admitting a weakness is a strong signal and may support `high`.
  Claims of `expert`/`competent` need corroboration (known maintainer, public projects, verifiable history)
  to reach `high`, with `basis: "stated+observed"`.
- ⚠️ Capability means what the person **can** judge, not what they **choose** to judge.
  Karpathy is `expert` but **chooses** `hands-off`/`over-trust`: keep D1 about capability and record this opt-out in D3/D4.

### D5 domain — *medium*
`{area, depth, stack, weak}`; `area` comes from card-schema.md's controlled vocabulary.
- A stated domain/stack corroborated by known projects supports `medium`/`high`.
  Self-admitted blind spots often **ground** `weak` here: "Too lazy to find the padding" → weak `web-frontend/css`;
  nontechnical founder → weak `security/auth`. These are strong signals that shape behavior.

## 3. Authenticity gates: performative / promotional / second-hand

There is no trace floor as used for observational sources, and no AI-polish-of-a-newbie test.
The risks differ (see card-schema.md for verdict vocabulary):

| Verdict / action | Trigger | Action |
|------------------|---------|--------|
| `authentic` | First-person, concrete workflow details, consistent across sources | Admit; mark grounded dimensions `stated`. |
| Reject — `promotional` | Courses/tool marketing, influencer "10x with my method", incentives; workflow is only a sales pitch | Do not admit: incentive bias, low signal. |
| Reject — `second_hand` | Third-party account; "according to …"; no first-person voice | Do not admit; find a first-hand source. |
| `contaminated` | AI-generated SEO content, unnaturally uniform sections, no concrete personal details, `id=` fences | Isolate; never admit. |
| `insufficient_evidence` | First-person opinions without workflow details or "how I …" | Do not admit: behavior cannot be grounded. |

**Exaggeration is not a failure.** A real first-person claim such as "I never read diffs" or "I always
Accept All" conveys a *stance*. Extract that stance, mark `stated`, and set `confidence: medium`.
Reject only for incentive-driven promotion, second-hand attribution, machine-generated content,
or insufficient detail, using the corresponding verdicts above.

## 4. `stated` → confidence rules: mandatory

See the corresponding section in card-schema.md. Pure grounded self-report uses `basis: "stated"`
and is capped at `medium`; observational corroboration permits `high` plus `basis: "stated+observed"`.
Admissions of weakness have little incentive for fabrication and may support `high`.
Uncorroborated claims of expertise remain `medium`.

## 5. Injection: rare, only for genuinely unsupported axes

Self-report usually grounds D2/D3/D4/D6/D7 directly; injection should be the exception, which is why
this source is used. When a source genuinely says nothing about an axis (D7 is often absent because
people rarely discuss how long they wait), sample from card-schema.md and set `source: "injected"` /
`confidence: "low"`. **Sample independently per card; never lock combinations by tier.**
Unsupported `on_offtrack` and `time_temperament` **must** be sampled independently: never require
abandon to pair with impatient, or file-issue with patient.

## 6. Discovery / recruitment: make the nonscalable step repeatable

Discovery must not become a crawler. Use **seed lists and search recipes** from
[`recruitment/seeds.md`](recruitment/seeds.md), through two entry points:

1. **Curated seeds:** named practitioners organized by the *extreme* they anchor
   (over-trust/ship-fast, skeptical/rigorous, non-technical/blind). Choose the underrepresented extreme, then the next person.
2. **Search recipes:** find recent first-person posts.
   - dev.to (Forem API, no key): `GET https://dev.to/api/articles?tag=vibecoding&top=30`, then
     `GET /api/articles/{id}` for full `body_markdown`. Keep first-person "how I use …" posts; skip tool marketing.
   - HN (Algolia, no key): `GET https://hn.algolia.com/api/v1/search?query=<workflow>&tags=comment`.
     Do not add `numericFilters=points>N` with `tags=comment` (400). High volume, low signal-to-noise:
     use it for skeptical/senior voices and quotes, with strict filtering.
   - Both sources also support **bulk sampling** (anchor A). Here they only *identify candidates*;
     then read the person's own long first-person account.

Both entry points feed the same L0→emit pipeline; the route only decides *whom to inspect*.

## 7. Source-to-output responsibilities

| Source | Spoke | observed vs stated | Grounds | Best use |
|--------|-------|--------------------|---------|----------|
| GitHub footprint | extract-github-persona | observed | D1, D5 (+ weak D3) | Builder personas at expert/competent tiers |
| Stack Overflow | extract-stackoverflow-persona | observed | D1, D5 (+ weak delegation) | blind/surface help-seekers |
| **blogs / interviews / talks** | **extract-selfreport (this skill)** | **stated** | **D2, D3, D4, D6, D7** | **Attitude/interaction/waiting anchors; calibration** |
| dev surveys (SO/JetBrains) | (weights) | aggregate | distribution | Sampling weights |
| dev.to / HN bulk | (sampler A) | mixed | candidates | Breadth / proportions |

The three extraction spokes complement one another: no source grounds every axis, but **every axis
can be grounded from observations or self-reports by at least one source**.
Self-report is the only primary source that reliably grounds trust (D4) and waiting temperament (D7).
Observational sources default D7 to injected.

## 8. Examples: real public first-person sources

### A — authentic: skeptical/rigorous anchor; admit with corroboration → high

Simon Willison: personal blogs across years plus a 2026 conference fireside conversation.
Explicit, concrete workflow; decades of public, verifiable output corroborate `stated+observed`.

```json
{
  "id": "selfreport-example-a",
  "authenticity": "authentic",
  "era": {"value": "post_vibe", "basis": "AI-coding essays 2024-09 → 2026-03 (agentic engineering)"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "expert", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D2_acceptance_bar": {"primary": "modern-correct", "flags": ["tests","scope","security"], "source": "grounded", "basis": "stated", "confidence": "high"},
    "D3_interaction_style": {
      "delegation": {"value": "spec-driven", "source": "grounded", "basis": "stated", "confidence": "high"},
      "supervision": {"value": "reviews", "source": "grounded", "basis": "stated", "confidence": "high"},
      "on_offtrack": {"value": "fix-self", "source": "grounded", "basis": "stated", "confidence": "high"}
    },
    "D4_trust_model": {"value": "skeptical", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D5_domain": {"area": "dev-tooling", "depth": "deep", "stack": ["python","sqlite","django"], "weak": [], "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D6_autonomy_expectation": {"value": "collaborative", "source": "grounded", "basis": "stated", "confidence": "medium"},
    "D7_time_temperament": {"value": "patient", "source": "injected", "confidence": "low"}
  },
  "provenance": {
    "sources": [
      {"url": "simonwillison.net/2025/Mar/19/vibe-coding", "type": "blog"},
      {"url": "simonwillison.net/2025/Dec/18/code-proven-to-work", "type": "blog"},
      {"url": "simonwillison.net/2026/Mar/14/pragmatic-summit", "type": "conf-talk"}
    ],
    "self_report": true,
    "evidence_quotes": [
      {"quote": "I won't commit any code to my repository if I couldn't explain exactly what it does to somebody else.", "source": "simonwillison.net/2025/Mar/19/vibe-coding"},
      {"quote": "Your job is to deliver code you have proven to work ... bundle the change with an automated test ... That test should fail if you revert the implementation.", "source": "simonwillison.net/2025/Dec/18/code-proven-to-work"},
      {"quote": "I start by saying ... 'use red-green TDD' ... the chances of you getting code that works go up so much if they're writing the test first.", "source": "Pragmatic Summit 2026-03"},
      {"quote": "it was faster for me to step in and finish the project rather than keep on trying to get there with prompts.", "source": "simonwillison.net/2025/Mar/11/using-llms-for-code"}
    ]
  },
  "behavioral_prediction": "Spec-driven skeptic: precise instructions + 'use red-green TDD', high process involvement, takes over on quality stall (on_offtrack=fix-self). D7 injected patient — source silent on wait temperament; demonstrates fix-self ⟂ waiting (not welded to impatient)."
}
```

### B — authentic: over-trust/blind anchor; admit, nontechnical with corroborated admissions of weakness

Leo Acevedo / EnrichLead: first-person posts in March 2025 plus a public retrospective.

```json
{
  "id": "selfreport-example-b",
  "authenticity": "authentic",
  "era": {"value": "post_vibe", "basis": "EnrichLead launch + 'under attack' posts 2025-03"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "blind", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D2_acceptance_bar": {"primary": "ship-fast", "flags": [], "source": "grounded", "basis": "stated", "confidence": "high"},
    "D3_interaction_style": {
      "delegation": {"value": "vibe-dump", "source": "grounded", "basis": "stated", "confidence": "high"},
      "supervision": {"value": "hands-off", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
      "on_offtrack": {"value": "retry", "source": "grounded", "basis": "stated+observed", "confidence": "high"}
    },
    "D4_trust_model": {"value": "over-trust", "source": "grounded", "basis": "stated", "confidence": "high"},
    "D5_domain": {"area": "web-backend", "depth": "shallow", "stack": ["cursor-generated","javascript"], "weak": ["security/auth","api-keys"], "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D6_autonomy_expectation": {"value": "agentic", "source": "grounded", "basis": "stated", "confidence": "high"},
    "D7_time_temperament": {"value": "steady", "source": "injected", "confidence": "low"}
  },
  "provenance": {
    "sources": [
      {"url": "x.com/leojr94_ (archived) 2025-03-17", "type": "tweet-thread"},
      {"url": "vibegraveyard.ai/story/enrichlead-vibe-coded-saas-shutdown", "type": "blog"}
    ],
    "self_report": true,
    "evidence_quotes": [
      {"quote": "my saas was built with Cursor, zero hand written code. AI is no longer just an assistant, it's also the builder.", "source": "x.com/leojr94_ 2025-03-17"},
      {"quote": "guys, i'm under attack ... random things are happening ... I'm not technical so this is taking me longer that usual to figure out.", "source": "x.com/leojr94_ 2025-03-19"},
      {"quote": "When he tried to use Cursor to fix the problems, the AI 'kept breaking other parts of the code.'", "source": "vibegraveyard.ai/.../enrichlead"}
    ]
  },
  "behavioral_prediction": "One-line production-grade dumps, low process involvement, treats AI as 'the builder'. High user experience as long as 'it works tho'; on quality failure retries then panics/abandons. D7 injected steady — do NOT derive impatient from panic-about-breakage (that's quality/capability, not wait temperament)."
}
```

### C — Orthogonality: expert × over-trust; do not let D1 determine D4

Karpathy in vibe mode, from the tweet that coined "vibe coding". Capability is `expert`, but he
**chooses** `hands-off` + `over-trust`. This demonstrates core principle #7 and explains why
`card_to_persona()` (spec-0006/T2) must use grounded D2/D4 to **override** the harness's
`derive_trust(expert)=skeptical` / `derive_d3(expert)=rigorous`. Otherwise the simulation would
turn this real person into their opposite.

```json
{
  "id": "selfreport-example-c",
  "authenticity": "authentic",
  "era": {"value": "post_vibe", "basis": "coined 'vibe coding' 2025-02-02"},
  "dimensions": {
    "D1_evaluation_capability": {"value": "expert", "source": "grounded", "basis": "stated+observed", "confidence": "high"},
    "D2_acceptance_bar": {"primary": "ship-fast", "flags": [], "source": "grounded", "basis": "stated", "confidence": "high"},
    "D3_interaction_style": {
      "delegation": {"value": "vibe-dump", "source": "grounded", "basis": "stated", "confidence": "high"},
      "supervision": {"value": "hands-off", "source": "grounded", "basis": "stated", "confidence": "high"},
      "on_offtrack": {"value": "retry", "source": "grounded", "basis": "stated", "confidence": "high"}
    },
    "D4_trust_model": {"value": "over-trust", "source": "grounded", "basis": "stated", "confidence": "high"},
    "D5_domain": {"area": "ml-ai", "depth": "deep", "stack": ["python","pytorch"], "weak": ["web-frontend/css"], "source": "grounded", "basis": "stated", "confidence": "medium"},
    "D6_autonomy_expectation": {"value": "agentic", "source": "grounded", "basis": "stated", "confidence": "medium"},
    "D7_time_temperament": {"value": "impatient", "source": "injected", "confidence": "low"}
  },
  "provenance": {
    "sources": [{"url": "x.com/karpathy 2025-02-02 (transcribed via simonwillison.net / pragmaticengineer.com)", "type": "tweet-thread"}],
    "self_report": true,
    "evidence_quotes": [
      {"quote": "I 'Accept All' always, I don't read the diffs anymore. When I get error messages I just copy paste them in with no comment, usually that fixes it.", "source": "x.com/karpathy 2025-02-02"},
      {"quote": "I ask for the dumbest things like 'decrease the padding on the sidebar by half' because I'm too lazy to find it.", "source": "x.com/karpathy 2025-02-02"},
      {"quote": "Sometimes the LLMs can't fix a bug so I just work around it or ask for random changes until it goes away. It's not too bad for throwaway weekend projects.", "source": "x.com/karpathy 2025-02-02"}
    ]
  },
  "behavioral_prediction": "Fire-and-forget vibe-dumper who CAN judge but opts out: one-line requests, low process involvement, retries on quality failure. D7 injected impatient — independent of on_offtrack=retry; demonstrates D1 ⟂ D3/D4 and on_offtrack ⟂ D7."
}
```

### D — Rejected as promotional; do not admit

A "vibe-coding coach" blog funnels every article into a paid course. Its "workflow" is a numbered
sales funnel ("My 5-step method for 10x"), with heavy CTAs and no concrete diff/test/stuck-workflow
details. Incentive-driven and lacking detail.

```json
{
  "id": "selfreport-example-d",
  "authenticity": "suspect",
  "reject_reason": "promotional: course-funnel content, incentive-biased, no concrete first-person workflow (no diff-reading / when-stuck / acceptance specifics)",
  "action": "not admitted; re-source from non-incentivized first-person material"
}
```
