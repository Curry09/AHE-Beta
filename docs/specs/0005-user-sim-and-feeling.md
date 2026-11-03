---
number: "0005"
title: "Heavyweight user-side implementation: control-envelope simulator and experience scoring"
issue: 0
slug: user-sim-and-feeling
summary: "This group implements the heavyweight version of **a｜user side** in the evolutionary closed loop: it replaces the minimal stub in spec-0001/T3 with a “control-envelope” architecture so that the user agent uses the harness more realistically over multiple turns (capability-dependent branching, follow-up questions, workarounds, abandonment), and completes the training signal **FeelingScore (1–4 experience score)** from spec-0001. Located at `backend/ahe_beta/user/sim/`, it **coexists with, rather than overwrites**, the 0001 minimal implementation."
tasks:
  - id: T1
    title: "Persona dimension model and wording"
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0001/T1
        type: extends
    parallel: false
    files:
      - backend/ahe_beta/user/sim/dimensions.py
      - backend/ahe_beta/user/sim/clauses.py
      - backend/tests/user/sim/test_dimensions.py
    scope: "Define a 9-dimensional structured persona (D1 evaluation ability/D2 domain depth/D3 acceptance threshold/D4.1-4.3 interaction/D5 autonomy/D6 authorization + trust) and its deterministic derivations (derive_d3/derive_trust/derive_d6/finalize_persona), along with a lookup table (clauses) mapping dimensions → English injection text. The persona consists of session-level static coefficients and does not change within the loop."
    acceptance: "For a persona specifying only freely sampled dimensions, finalize_persona produces a complete immutable persona, with deterministic and reproducible derivation mappings; for a persona with explicitly provided d3/trust/d6, all three are preserved as-is without being overwritten (fallback-only); compile_block_p produces the corresponding wording for every dimension value, with no missing keys."
  - id: T2
    title: "Action model, action space, and state machine"
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/actions.py
      - backend/ahe_beta/user/sim/action_space.py
      - backend/ahe_beta/user/sim/state.py
      - backend/tests/user/sim/test_action_space.py
      - backend/tests/user/sim/test_state.py
    scope: "Action catalog (five attributes fixed for executor×channel×effect) + action-space derivation (phase ∩ capability mask D1 ∩ authorization D6 ∪ patience-gate termination ∪ accept) + classification of freely generated output/projection of unauthorized actions/channel validation + patience/trust state machine (consumes only subjective verdicts). This round does not implement the objective ground-truth track (objective/gold/GAP/control-plane); state is driven solely by subjective verdicts."
    acceptance: "The derived action space correctly adds/removes actions according to phase/D1/D6/patience; resolve_action ensures that the result is within the space and that channel↔message is consistent; apply_verdict changes patience/trust only according to subjective verdicts; state evolution never reads any objective ground truth."
  - id: T3
    title: "Prompt assembly and persona LLM backends"
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/persona_client.py
      - backend/tests/user/sim/test_prompt.py
    scope: "system (fixed BLOCK-G + BLOCK-P persona instance, KV-cache friendly) + per-turn user message + end-of-session self-rating request via build_rating_turn. The PersonaClient protocol has two backends: ApiPersonaClient (OpenAI-compatible gateway) / ScriptedPersonaClient (offline script, including a self-rating branch). Can later converge on 0003/T2 nexau_runtime."
    acceptance: "The build_system prefix is stable; build_rating_turn produces an instruction requiring {score,reason} JSON; ScriptedPersonaClient returns a 1–4 self-rating for <rate_experience>; _parse_json is tolerant (strip fences/extract the first {}) and does not crash on parse failure."
  - id: T4
    title: "Experience score (both paths emitted)"
    status: pending
    priority: P1
    tags: []
    depends-on:
      - 0001/T1
    relates-to:
      - ref: 0001/T1
        type: extends
      - ref: 0001/T3
        type: note
    parallel: false
    files:
      - backend/ahe_beta/user/sim/feeling.py
      - backend/tests/user/sim/test_feeling.py
    scope: "Align the end-of-session output of the control envelope with the training signal FeelingScore in spec-0001 (1–4 + reason, with construction-time range assertions and bidirectional serialization). Emit both paths: ① parse_feeling_llm parses the persona LLM's end-of-session self-rating (the spec-0001/T3 output method); ② derive_feeling deterministically aggregates from the subjective end state (end_reason/failed_blame_harness count/trust), for cross-checking and as a fallback when LLM parsing fails. Never read objective ground truth (gold held-out) throughout."
    acceptance: "Out-of-range FeelingScore (0/5) causes a construction-time assertion failure, and to_dict/from_dict round-trip consistently; parse_feeling_llm produces a FeelingScore for valid {score,reason}, and returns None for missing fields/non-integers/out-of-range values; derive_feeling maps accepted→4 (reduced to 3 with substantial friction)/max_turns, issue_filed→2/abandoned→1; neither path depends on gold."
  - id: T5
    title: "Session main-loop engine"
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - T4
    relates-to:
      - ref: 0001/T3
        type: extends
      - ref: 0001/T2
        type: note
    parallel: false
    files:
      - backend/ahe_beta/user/sim/loop.py
      - backend/tests/user/sim/test_loop.py
    scope: "Control-envelope main loop (≈ the heavy implementation of spec-0001/T3 UserAgent.run): each turn derives the action space→makes three-layer persona decisions (perceive/verdict/action/message)→resolves→writes state back→checks termination; SessionResult aggregates turns/signals/issue_artifact + the two end-of-session experience scores (feeling=LLM self-rating as the primary signal / feeling_derived=framework-derived). This round does not implement an objective ground-truth path (no gold/GAP/control-plane hard override); harness replies are text only. Each turn uses a standalone live-dialogue protocol (does not use the harbor batch API)."
    acceptance: "Given persona+client+harness+task, run to produce a SessionResult; both self-determined termination and the MAX_TURNS fallback take effect; at session end, both feeling and feeling_derived are valid FeelingScore values (when LLM parsing fails, feeling falls back to derived); experience scores and state depend only on subjective signals throughout and never read objective ground truth."
  - id: T6
    title: "Harness stubs and run entry points"
    status: pending
    priority: P2
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/harness_adapter.py
      - backend/ahe_beta/user/sim/scenarios.py
      - backend/ahe_beta/user/sim/demo.py
      - backend/ahe_beta/user/sim/run_live.py
      - backend/tests/user/sim/test_harness_adapter.py
    scope: "The scripted harnesses (ScriptedHarness/SplitBillHarness) directly implement HarnessInterface (send/reset/close): send→str\nDemonstrate capability-branching scenarios along preset trajectories, with bugs represented only in reply text (send does not return gold/exit_code, aligning with this round's lack of an objective path, and the harness outputs\ntext only); reset resets script progression, and close is an idempotent no-op. Provide two run entry points: demo (offline scripted backend, runs without a key) and run_live (real NexAU gateway),\nprinting both experience scores and behavior signals side by side. In production, replace this adapter layer with a real CLI harness (also implementing HarnessInterface,\nowned by the 0003/T1 launcher)."
    acceptance: "ScriptedHarness/SplitBillHarness satisfy HarnessInterface (isinstance passes, with send/reset/close all present); behavior matches FakeHarness: sending or resetting after close raises RuntimeError, repeated close calls are idempotent and do not raise; demo runs both personas with ScriptedPersonaClient without a key and prints llm-rated/derived experience scores; run_live can run against a real user-agent when the gateway is configured; harness stubs produce the expected text trajectories for the 'request execution/probe edge cases' branches."
---

# 0005 · Heavyweight User-Side Implementation: Control Envelope Simulator and Experience Score

<!-- This file is maintained by the spec tool: frontmatter is structured source data (including the tasks DAG), and the body is a nine-section group-level rust-RFC overview. -->

## Summary

This group implements the heavyweight version of the evolution loop **a | user side**: replacing the minimal stub spec-0001/T3 with a “control envelope” architecture, so the user agent can use the harness over multiple turns more realistically (capability branching, follow-up questions, detours, giving up), and adding the training signal spec-0001
**FeelingScore (experience score, 1–4)**. The implementation lives in `backend/ahe_beta/user/sim/` and **coexists with, rather than replacing**, the 0001 minimal implementation.

Data-flow backbone (spanning T1…T6):

```
Persona dimensions (T1) ─► Action space/state machine (T2) ◄─ Prompt + LLM backend (T3)
                                             │  Three-layer persona decision each turn
                                             ▼
                                 Session main loop (T5) ⇄ Harness stubs (T6)
                                             │  End of session
                                             ▼
                             Dual experience scores (T4) ─► FeelingScore 1–4 (training signal)
```

Read the diagram as a task map: **T1** defines static persona coefficients; **T2** defines “what can be done each turn + how emotions evolve” (a purely subjective state machine);
**T3** feeds context to the LLM and obtains structured judgments, including a self-rating request at the end of the session; **T5** orchestrates these into “running a session”; **T4**
produces a training signal at the end of the session (primarily LLM self-rating + framework-derived fallback/validation); **T6** provides an offline-runnable harness stub and execution entry point.

**This iteration is purely subjective (the objective line is not implemented)**: this group uses only user experience as a training signal; the objective ground-truth line (gold / GAP / ESCAPED_BUG /
control-plane) is deferred in its entirety. It is not written to state, does not enter the experience score, and the harness stub returns text only. Capability branching is instead driven by “persona capability + text perception,”
and bugs are reflected directly in harness response text. This is consistent with the project principle “training signal = user experience, benchmark held-out”; observation of the objective ground-truth
line is deferred to a later spec.

**Relationship to 0001 and the loop**: This group is the heavyweight implementation/evolution of 0001 user side (a). The contract alignment needed for actual integration into the loop
(engine `run_session` ↔ 0001/T4, harness stub ↔ 0001/T2 `HarnessInterface`, alignment of the 9-dimensional Persona with
`FeelingScore` and `models`, LLM backend convergence 0003/T2 `nexau_runtime`, `issue_artifact` → `IssueDraft`)
is documented in the open questions of the relevant Tasks and belongs to later Tasks/groups.

## Motivation

The credibility of training signals depends on how realistically the persona is played: free-text personas cannot reliably drive capability branching (under the same harness
trajectory, a novice user accepts while an expert sees through it). Therefore, T1 converges the persona into a 9-dimensional structured model with deterministic derivation, making it reproducible,
sampleable, and amenable to codegen, and quantifying “what can be perceived” and “to what extent it is verified” as coefficients consumable by the action space and state machine. On this
foundation, T2 converges “what the user can do this turn and how their emotions change afterward” from unconstrained LLM behavior into a controllable, reproducible, pure-code mechanism:
capability masks prevent low-capability personas from performing out-of-scope checks (without violating G1, “do not peek at ground truth”), while the patience/trust state machine integrates emotions into a terminable
trajectory.

The persona’s subjective judgments ultimately need to be generated by the LLM in character, and its output must also be consumable by the framework in structured form. This is why T3 provides prompt assembly and dual
LLM backends: layered prompts separate the stable prefix (role/ground rules/output contract) from the changing state to save tokens, while the two backends (real gateway / offline script) let the entire loop run
in environments without keys (CI, demo), decoupling real inference from framework orchestration; T3’s end-of-session self-rating request is also the entry point for the experience score.

The gap between the control-envelope engine, which previously produced only structured verdicts and termination reasons, and the spec-0001 training-signal contract (FeelingScore 1–4)
is precisely why T4 exists: LLM self-rating is close to actual satisfaction but noisy and may fail to parse, while framework derivation is reproducible and always available. Producing both provides cross-validation and a fallback,
filling this signal gap is a prerequisite for connecting the control envelope to the user side of the closed loop.

The minimal stub spec-0001/T3 drives multiple turns using “sentinel + max_turns,” which offers limited realism; the authenticity of training signals depends precisely on
whether real usage behaviors such as follow-up questions, detours, getting stuck, and giving up can be represented. This is why T5 exists: it assembles the scattered T1–T4 components into
the sole “run a session” engine, reusable by user side (a) and subsequent dev-side experience gates. To verify this entire loop offline and deterministically (runnable in CI/demo without a key),
and to demonstrate how capability branching produces different user experiences under the same harness trajectory, T6 provides a scripted harness stub and execution entry point. This is the smallest vehicle for explaining and regression-testing the engine; in production, it will be replaced by a real CLI harness.

## Guide-level explanation

The control envelope starts with persona as its static coefficients: the 9-dimensional model (D1 evaluation capability / D2 domain depth / D3 acceptance threshold / D4.1–4.3
delegation · supervision · correction / D5 autonomy / D6 authorization + derived trust) is defined by T1, together with a deterministic lookup table from dimensions to English injection text
(clauses). The persona is fixed at the start of a session and remains unchanged throughout the loop. It is the structured, heavyweight version of spec-0001/T1 free-text Persona.

On top of the persona, T2 forms the deterministic mechanism layer of the control envelope: the action catalog fixes the three axes of executor×channel×effect and the termination reason for each action;
the action space is derived from “state of play ∩ capability mask (D1) ∩ authorization (D6) ∪ termination actions unlocked by the patience gate ∪ accept”;
free-form output is categorized and projected when over-privileged, with strict channel↔message validation and fallback to the legal set; the patience/trust state machine evolves only from subjective verdicts.
This iteration is purely subjective and excludes the objective ground-truth line.

T3 connects these two layers to the LLM: the system prompt is assembled from BLOCK-G (fixed role/ground rules/output contract) and BLOCK-P (the persona instance compiled by T1),
with a KV-cache-friendly layout (the invariant prefix comes first); each turn’s user message carries <task><history><harness_output>
<self_observation><action_space><mood>; at the end of the session, a build_rating_turn self-rating request is appended. The PersonaClient protocol
provides two backends: ApiPersonaClient connects to an OpenAI-compatible gateway (with reasoning-model hardening), while ScriptedPersonaClient
provides an offline script (including a self-rating branch), allowing the entire loop to be deterministically reproduced in an environment without a key.

At the end of the session, T4 aligns the verdict / end_reason / signals natively produced by the control envelope with the spec-0001 training-signal contract,
FeelingScore: one path is LLM self-rating (the persona rates 1–4 in character according to its own acceptance threshold, with a reason, using T3’s end-of-session request,
aligned with spec-0001/T3 “produce FeelingScore via LLM at the end of the session”); the other path is framework-derived (deterministically aggregated from end_reason and subjective
verdict/trust, and reproducible). The former is the primary signal; the latter provides cross-validation and a fallback if LLM parsing fails. Both inputs
are subjective signals; objective truth (gold) is held out throughout and does not participate.

T5 is the main loop that orchestrates T1–T4 into a complete session, and is the heavyweight implementation of spec-0001/T3 “user agent driver”: each turn proceeds through
“derive action space → persona’s three-layer decision (perceive/verdict/action/message) → resolve categorization and projection → write back state
→ termination check”; at the end of the session, both experience-score paths produce their results. This iteration is purely subjective (it excludes the objective ground-truth line); turn-by-turn human conversation uses an independent protocol,
not harbor’s batch episode interface.

Finally, T6 provides a scripted harness stub and two execution entry points: harness_adapter.ScriptedHarness / scenarios.
SplitBillHarness directly implements spec-0001/T2’s HarnessInterface (send/reset/close, send(message) -> str),
replaying capability-branching scenarios from preset trajectories (timeutils DST, split_bill lost cents). Bugs are reflected only in response text (e.g.
sum=99.99), for the persona to identify using its own capabilities. In this iteration, send returns text only, with no gold/exit_code (no objective line). The demo
uses the offline scripted backend to demonstrate branching trajectories for two personas (runnable without a key); run_live connects to a real NexAU gateway to run the entire loop,
and both print the two experience scores alongside the behavioral signals.

## Reference-level explanation

### User modeling core: persona dimensions, action space, and state machine (T1, T2)

Persona dimensions are arranged in five layers: A capability foundation (D1,D2), B acceptance (D3, derived from D1×D2), C interaction (D4.1/4.2/4.3), D session configuration
(D5,D6, partially derived), and E derived (trust = f(D1,D2)). The caller supplies freely sampled dimensions; derived dimensions (d3/trust/d6) are filled in by
finalize_persona: derive_d3 sets the baseline tier according to D1, then adjusts it by D2.depth (senior +1 / novice -1), clamped within the enum ordering;
derive_trust maps BLIND→blind, EXPERT→skeptical, and all others to balanced; derive_d6 sets the baseline according to D5, tightens authorization by one tier when task_risk is high,
and opens it up to can-run for collaborative personas with low-risk tasks. Derivation follows **fallback-only (orthogonal contract)**: finalize_persona
fills only derived dimensions that were “not provided”; explicitly grounded d3/trust/d6 values supplied by the caller are preserved as-is, and derive_* does not overwrite them. The implementation uses a None
sentinel to distinguish “not provided” from “already grounded” (d3/d6/trust default to None; finalize fills only the ones that are None). This contract is motivated by the fact that real-persona acceptance/trust/authorization should be directly settable to grounded values (dimensions are orthogonal; an expert can over-trust; see
extract-selfreport-persona example C). 0006/T2 uses this to preserve fidelity when injecting real cards; otherwise, it would overwrite grounded truth with synthetic
values. For each dimension value, clauses provides one English injection sentence; compile_block_p assembles BLOCK-P (for the persona LLM, without numeric
state values).

On top of the persona, T2 forms the deterministic layer for actions and state. The action catalog (actions) lists send_task / refine_request /
give_feedback / verify_self / ask_harness_run / request_evidence / grant_autorun / accept /
give_up / file_issue, fixing for each action executor∈{PERSONA_LOCAL,HARNESS,FRAMEWORK}, channel∈{EMIT,SILENT},
effect∈{ADVANCE,VERIFY,TERMINATE}, and strictly validating channel↔message consistency. The action space (action_space) is
LEGAL_BY_PHASE ∩ cap_mask(D1) ∩ authz(D6); when patience <=0, it unlocks the termination action selected by D4.3; when an acceptable artifact is available, it adds
accept. resolve_action categorizes the LLM’s free-form or over-privileged output and projects it back into the legal set. In the state machine (state), apply_verdict
changes patience/trust only according to subjective verdicts (satisfied increases trust, failed_blame_harness reduces patience and trust, and so on); the rate of evolution is determined by persona-derived coefficients (make_coef). Objective ground truth does not participate in state evolution (the objective line is not implemented in this iteration).

**Interface**

```
Persona(persona_id, d1, d2, d41, d42, d43, d5, d3=None, d6=None, trust=None)   # Frozen dataclass; None means a derived dimension was not provided
finalize_persona(p: Persona, task_risk: str = "low") -> Persona      # Fill only missing (None) derived dimensions; preserve grounded values
compile_block_p(p: Persona) -> str                                   # Dimensions → BLOCK-P text

derive_action_space(phase, persona, state, has_artifact) -> list[str]
resolve_action(ret: dict, space: list[str], persona) -> tuple[action_id, message]
apply_verdict(state, verdict, coef) -> State
```

**Tests**

Unit tests:
- finalize_persona (derivation): given only freely sampled dimensions, derived d3/trust/d6 match the lookup table and are reproducible; derive_d3
  moves senior up one tier and novice down one tier, clamped within the enum ordering (no out-of-bounds values).
- finalize_persona (fallback-only): after finalize, personas with explicitly provided d3/trust/d6 retain those values; values not provided
  are filled by derive_*.
- compile_block_p: every dimension value resolves to text, with no KeyError; frozen persona is immutable.
- derive_action_space: OPENING contains only send_task; ACTIVE adds or removes verify_self/
  request_evidence according to the D1 capability mask; READ_ONLY/WRITE_NO_RUN authorization removes ask_harness_run/grant_autorun; patience<=0
  unlocks the corresponding termination action; accept is added when an artifact is available.
- resolve_action: free-form output → categorized as a legal action; over-privileged output → projected to an action with the same effect; SILENT clears message, EMIT uses a fallback if empty;
  final assert_channel passes.
- apply_verdict: changes to patience/trust for satisfied/ failed_blame_harness/ failed_blame_self/ unsure match the coefficients; purely subjective—the state machine depends only on verdict, and every branch can be driven using input constructed without any objective fields.

**Files (single-writer ownership)**

| Task | Files |
|---|---|
| T1 | `backend/ahe_beta/user/sim/dimensions.py`, `backend/ahe_beta/user/sim/clauses.py`, `backend/tests/user/sim/test_dimensions.py` |
| T2 | `backend/ahe_beta/user/sim/actions.py`, `backend/ahe_beta/user/sim/action_space.py`, `backend/ahe_beta/user/sim/state.py`, `backend/tests/user/sim/test_action_space.py`, `backend/tests/user/sim/test_state.py` |

### Prompt assembly and persona LLM backends (T3)

In the prompt module, BLOCK_G is fixed (ROLE / GROUND RULES G1-G5 / ACTION SEMANTICS / OUTPUT CONTRACT),
build_system = BLOCK_G + compile_block_p(persona); build_user_turn composes the per-turn context, with mood represented only by discrete labels
(full/lowered/low/exhausted + trust), not numeric values; build_rating_turn overrides the action contract and requests only
{"score","reason"}. In the persona_client module, the PersonaClient protocol specifies respond(system, user) -> dict:
ApiPersonaClient uses LLM_BASE_URL/LLM_API_KEY, enable_thinking=False suppresses CoT, empty content falls back to
reasoning_content, with backoff retries and tolerant JSON parsing; ScriptedPersonaClient reads the D1/D3 tiers from system and
branches on harness_output/mood from user, and self-rates for <rate_experience>. make_client uses the
Api backend when a gateway/OPENAI_API_KEY is detected; otherwise it falls back to Scripted.

**Interface**

```
build_system(persona) -> str; build_user_turn(task, history, harness_output, action_space, state) -> str
build_rating_turn(task, history, state) -> str
PersonaClient(Protocol).respond(system: str, user: str) -> dict   # {perceive,verdict,action,message} or {score,reason}
make_client() -> PersonaClient
```

**Tests**

Unit tests:
- build_system prefix is stable (consistent across repeated calls with the same persona); build_user_turn includes all sections; build_rating_turn
  includes the 1–4 instructions and {"score","reason"}.
- ScriptedPersonaClient: sends send_task at session start; <rate_experience> returns 1–4; exhausted → file_issue/
  give_up; capability-tier branching behaves as expected.
- _parse_json: strips the ```json fence, extracts the first {...}, and falls back to a safe dict on parse failure without raising.

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/prompt.py`
  - `backend/ahe_beta/user/sim/persona_client.py`
  - `backend/tests/user/sim/test_prompt.py`

### Experience scoring: two parallel outputs (T4)

Both scores are produced once at the end of the session, independently of each other. ① LLM self-rating (parse_feeling_llm): the prompt (0005/T3
build_rating_turn) asks the persona to step outside the conversation and assign 1–4 + a one-sentence reason according to their own acceptance threshold (G4), overriding the action OUTPUT
CONTRACT to require only {"score","reason"}. Fault-tolerant parsing returns None for a missing score, a non-integer, or an out-of-range value (the assertion failure for an out-of-range value in
FeelingScore.__post_init__ is caught), leaving the caller to fall back to the derived score without crashing the loop. ② Framework-derived scoring
(derive_feeling) uses only subjective terminal state:

| end_reason              | base |
|-------------------------|------|
| accepted                | 4    |
| max_turns / issue_filed | 2    |
| abandoned               | 1    |

All other end_reason values map to 2. Friction adjustment: accepted with failed_blame_harness>=2 or terminal trust=skeptical → reduce to 3.
The FeelingScore contract aligns with spec-0001/T1: score:int(1..4) + reason; __post_init__ fails on out-of-range values;
to_dict/from_dict provide bidirectional serialization (from_dict ignores unknown keys for forward compatibility). Held-out boundary: inputs to both scoring paths are subjective signals
(end_reason / verdict / trust); neither reads objective gold.

**Interface**

```
FeelingScore(score: int, reason: str)            # __post_init__ asserts 1<=score<=4; to_dict/from_dict serialization
parse_feeling_llm(ret: dict) -> FeelingScore | None   # Parse the LLM self-rating; return None for missing fields, non-integers, or out-of-range values
derive_feeling(end_reason: str, turns: list) -> FeelingScore  # Read only verdict/trust from turns via duck typing
```

**Tests**

Unit tests:
- FeelingScore round-trip(to_dict/from_dict) preserves every field; out-of-range values (0/5) trigger assertion failures during construction.
- parse_feeling_llm: valid {score,reason}→FeelingScore; missing score / non-integer score / out-of-range value (5) → None;
  reason defaults to an empty string.
- derive_feeling: accepted+few failures→4; accepted+failed_blame_harness>=2→3; accepted+trust=skeptical→3;
  max_turns→2; issue_filed→2; abandoned→1; unknown end_reason→2.
- Held-out: construct turns containing only subjective fields and verify that the derived score reads no gold fields.

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/feeling.py`
  - `backend/tests/user/sim/test_feeling.py`

### Session main-loop engine (T5)

Pipeline for each turn (turn < MAX_TURNS):

```
① Receive harness_output as text from the harness stub (T6)
② Derive action space: phase ∩ capD1 ∩ authzD6 ∪ patience gate ∪ accept (T2)
③ Three-layer persona LLM → {perceive, verdict, action, message} (T3 client; pass harness text unchanged)
④ Resolve: classify/validate the action and validate its channel (T2)
⑤ Write state: apply_verdict consumes only subjective verdicts (T2)
⑥ Check termination: Effect.TERMINATE → record end_reason and break
⑦ Route: EMIT → advance the harness to the next turn; verify_self → inject raw observations (latest harness text)
```

At session end (outside the loop): first produce the derived score with derive_feeling; then send build_rating_turn to obtain the LLM self-rating,
parse it with parse_feeling_llm, and fall back to the derived score on failure. Store the two in SessionResult.feeling / feeling_derived, respectively.

signals are behavioral signals (such as a low-capability user abandoning the task because they cannot fix it themselves), derived from the persona and session trajectory; this round includes no signals dependent on objective
truth (GAP/ESCAPED_BUG/control-plane are deferred; see the related Unresolved questions in T2).

The perception side no longer filters capabilities at the code level: the prototype used perceive_filter (which guessed “source lines” from indentation/keywords and erased them) + _filter_self_obs
(which replaced substrings Traceback/Error with a stock “I ran it once and it crashed” string) to mechanically rewrite inputs fed to the LLM. Such string heuristics are fragile—missed detections
allow a strong model to “mentally execute” source code beyond the low-capability tier (violating G1), while false positives delete normal text or fabricate negative perceptions based on substrings; both contaminate experience signals.
This version removes both: the persona sees raw harness text, verify_self injects raw observations, and capability branching is achieved through prompt (G1) + persona
tier constraints instructing the LLM to “perceive only within their own capabilities,” rather than through mechanical framework filtering of inputs.

file_issue writing turn: when the current turn's action is classified as file_issue, the main loop does not use the brief in-conversation message as the issue body.
Instead, it adds a dedicated writing turn within the loop—using T3's build_issue_turn to have the persona step outside the conversation and write
what they want to report to the developer as a self-contained body in their own first person (overriding the action contract to take only {issue}). issue_artifact = this first-person body +
`---` separator + machine footnote (automatically collected metadata such as persona_id/capability tier/turn count/symptoms in the final reply); it no longer uses a third-person template wrapper such as “### What the user
reported.” The body is the user's own words, and the metadata is explicitly labeled as an auto-collected footnote.

**Interface**

```
run_session(persona: Persona, client: PersonaClient, harness, task: str) -> SessionResult
SessionResult(persona_id, end_reason, turns: list[TurnLog], signals: list[str],
              issue_artifact: str | None,
              feeling: FeelingScore | None,          # LLM self-rating (primary signal)
              feeling_derived: FeelingScore | None)  # Framework-derived score (cross-check/fallback)
```

Note: this is the engine's native signature; alignment with the spec-0001/T4 run_session(persona, scenario, harness, user_agent,
tracker, store) contract is deferred until closed-loop integration (see Unresolved questions).

**Tests**

Unit/integration tests (offline ScriptedPersonaClient + scripted harness):
- Complete one session: given persona+client+harness+task, return SessionResult with turns matching the send/receive sequence.
- Self-determined termination: the persona emits a terminal action on turn k → exactly k turns; never terminates → truncate when the turn count reaches MAX_TURNS.
- Two experience scores: at session end, feeling and feeling_derived are both valid FeelingScore values; if LLM self-rating parsing fails, feeling falls back to derived.
- Purely subjective: the session runs successfully with harness text replies containing no objective fields; state/experience does not depend on gold.
- Capability branching: a low-capability persona accepts after passing a normal test case (high experience score); a high-capability persona presses for evidence until patience is exhausted → file_issue (low experience score).
- Perception inputs passed through unchanged: after removing perceive_filter/_filter_self_obs, run_session feeds raw harness text to the client,
  and verify_self injects raw observations (no longer fabricating “crashed/no error” based on substrings); capability branching relies on the prompt, not framework filtering.
- file_issue body uses the user's voice: the file_issue branch calls build_issue_turn once specifically for writing; the issue_artifact body consists of the user's own first-person
  words, with machine metadata relegated to an auto-collected footnote after `---` (assert that there is no third-person template heading, and that the footnote exists and includes capability tier/action).

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/loop.py`
  - `backend/tests/user/sim/test_loop.py`

### Harness stubs and entry points (T6)

The harness stubs implement HarnessInterface (send/reset/close): send responds according to preset steps, branching the trajectory only on whether the message “requests
execution / probes a non-evenly-divisible boundary,” and returns plain text (str); reset resets script progression to zero; close sets a closed flag (no actual
resources) and is idempotent; send/reset after close raise RuntimeError (aligned with FakeHarness to expose misuse). Bugs appear in the text
(e.g., split_bill(100,3) -> sum=99.99); a high-capability persona can identify them by reading the text, while a low-capability persona accepts after seeing a normal case
(sum=100)—branching is driven entirely by persona capability + textual perception, without gold. The demo uses make_client (no key
→ ScriptedPersonaClient) to run fresh harness trajectories for each of two personas (SHALLOW+FEEDBACK / EXPERT+FILE_ISSUE),
and print_result prints turns / both experience scores / behavioral signals / issue artifact side by side; run_live always uses
ApiPersonaClient (through the repo .env gateway) to run SplitBillHarness against a real user-agent.

**Interface**

```
ScriptedHarness / SplitBillHarness implement spec-0001/T2 HarnessInterface:
  send(message: str) -> str   # Return text only in this iteration (no gold/exit_code)
  reset() -> None             # Reset script progression; idempotent
  close() -> None             # Mark closed (no real resources); idempotent; subsequent send/reset raises RuntimeError
demo.main() / run_live.main()   # Two __main__ entry points
```

**Tests**

Unit/smoke tests:
- Contract alignment: isinstance(ScriptedHarness()/SplitBillHarness(), HarnessInterface) is true; after reset, the script restarts from the first step; send/reset after close raise RuntimeError, and repeated close calls are idempotent and do not raise (aligned with FakeHarness).
- Harness stubs: the first turn pastes code without running it; request execution → echo the normal case (no error); probe a non-evenly-divisible boundary → text exposes lost cents/DST errors; send returns str.
- The demo runs both personas without a key, and its output includes both llm-rated and derived experience scores; assert capability branching (shallow accept / expert file_issue).

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/harness_adapter.py`
  - `backend/ahe_beta/user/sim/scenarios.py`
  - `backend/ahe_beta/user/sim/demo.py`
  - `backend/ahe_beta/user/sim/run_live.py`
  - `backend/tests/user/sim/test_harness_adapter.py`

Dependency DAG: `T1 → T2`, `T1 → T3`, `T2 → T3`, `0001/T1 → T4`, `T1 → T5`, `T2 → T5`, `T3 → T5`, `T4 → T5`, `T5 → T6`

## Drawbacks

This group trades engineering complexity for realism, with costs concentrated in several areas: the 9-dimensional structured persona (T1) significantly increases modeling and maintenance costs compared with the free-text
five-tuple in spec-0001/T1, and requires a None sentinel to distinguish “not provided” from “already grounded” derived dimensions, making the interface less
intuitive than free text. Producing both experience scores (T4) costs an additional LLM call and a redundant field (feeling_derived). Assembling T1–T4 into a single session main-loop
engine (T5) significantly increases complexity and dependencies across modules; experience is scored only once at session end, losing the finer detail of “which
turn it deteriorated on.” After replacing code filtering on the perception side with pure prompt constraints (G1 + persona tier), the realism of capability branching depends entirely
on prompt quality, with no code-level fallback; degraded prompts may let low-capability personas identify bugs beyond their tier or cause high-capability personas to make incorrect
judgments. The harness stubs in T6 are scripted shims that cover only preset branching trajectories, not yet real CLI harnesses, so their representativeness is limited. The most fundamental
limitation is that this round does not implement the objective ground-truth track (gold/GAP/ESCAPED_BUG/control-plane) at any point: experience and issues are based entirely on subjective
signals, so the accuracy of the persona's own judgments cannot be verified; convergence can only be approached indirectly through subsequent rounds of iteration and calibration with real data.

## Rationale and alternatives

### Core user modeling: persona dimensions and action space/state machine (T1, T2)

- 9-dimensional structured representation vs the free-text five-tuple in spec-0001/T1: choose structured representation (to drive capability branching and enable reproducibility/sampling), at the cost of modeling effort;
  convergence with models.Persona is deferred until closed-loop integration (see Unresolved questions).
- Deterministic lookup tables vs LLM inference for derived dimensions: choose determinism to ensure reproducibility and codegen compatibility, preventing sampling noise from entering static coefficients.
- Fallback-only derivation vs unconditional derivation: choose fallback. A real persona's acceptance/trust/authorization should be directly specifiable through grounded values (the dimensions
  are orthogonal; see selfreport example C: an expert can over-trust); unconditional derivation would overwrite grounded truth with a synthetic profile (injecting 0006/T2 would immediately distort it).
  The cost is that Persona needs a None sentinel to distinguish “not provided” from “already grounded.”
- Fixing both executor×channel axes vs a single run_once action: choose both axes to eliminate attribution ambiguity between “run it oneself vs have the harness run it.”
- Capability masks gating actions + perception inputs vs gating only actions: choose to gate both, preventing a strong model from “mentally executing” source code beyond the low-capability tier (G1).
- Purely subjective this round (no objective track) vs including gold/GAP: choose purely subjective. Training signals use only user experience; the objective ground-truth track (GAP/
  ESCAPED_BUG/control-plane) is deferred in its entirety to avoid introducing oracle dependencies prematurely; open a separate spec later if observation is needed.

### Prompt assembly and persona LLM backend (T3)

- Textual OUTPUT CONTRACT conventions vs enforced JSON schema / tool-calling: choose textual conventions + fault-tolerant parsing to avoid strong assumptions about model
  interfaces (aligned with “compatibility with multiple agents/models”), with safe degradation on parse failure.
- Bundled openai client vs convergence on 0003/T2 nexau_runtime: currently bundled (so sim can run independently); converge on a single
  nexau runtime during closed-loop integration (single-runtime constraint); see Unresolved questions.

### Experience scoring: two parallel outputs (T4)

- Emit both paths vs select only one: emit both. Using only the LLM self-assessment yields no signal when parsing fails and is not reproducible; using only the derived score loses the persona's genuine in-character satisfaction. Emit both, with the LLM as primary and the derived score as fallback and validation, at the cost of one additional LLM call and a redundant field.
- Aggregate the derived score in code vs have the LLM score directly: spec-0001/T3 literally requires LLM output; however, the control envelope already produces a verdict each turn, so asking the LLM to additionally assign a score of 1–4 is redundant and introduces noise. Compromise: retain the LLM self-assessment to align with the spec, while deriving a score in code for reproducible cross-validation.
- Reuse 0001 models.FeelingScore vs define a custom type within sim: sim currently uses a self-contained definition (zero cross-package coupling, independently testable); switch to models.FeelingScore when integrating into the closed loop, as discussed in Unresolved questions.
- Handle out-of-bounds values with assert+catch as None vs raise directly: choose the former. This preserves a single validation point for the rule “out of bounds is invalid” (T1 __post_init__) without allowing one bad self-assessment to crash the entire session.

### Session main loop engine (T5)

- Control envelope engine vs spec-0001/T3 minimal stub: choose the engine. The minimal stub has only sentinel+max_turns and cannot express capability branching or emotional evolution, distorting the training signal; the engine is closer to real usage, at the cost of complexity and multi-module dependencies.
- Standalone turn-by-turn protocol vs reuse harbor batch episodes: choose standalone. The harbor interface operates at episode granularity; applying it to the semantics of “turn-by-turn human conversation + user-determined termination” would be a semantic mismatch (consistent with the decisions in spec-0001/T2 and 0004).
- Produce a final-state experience score vs score every turn: choose one final-state score (aligned with FeelingScore's “one overall score per session”), losing the granularity of “which turn got worse”; upgrade later if needed.
- Code filtering vs prompt constraints for perceived capability branching: the prototype mechanically filters input fed to the LLM using perceive_filter/_filter_self_obs. Its substring/indentation heuristics are brittle (false negatives allow perception beyond the persona's tier, violating G1; false positives remove normal text or fabricate negative perceptions). Switch to feeding input unchanged and rely on prompt(G1)+persona tier constraints for LLM self-discipline in capability branching, removing the brittle string-rule layer (at the cost of making branching fidelity more dependent on prompt quality).

### harness stub and run entry point (T6)

- Scripted harness vs real CLI harness: this group uses a scripted harness (deterministic, regression-testable, and free of external dependencies), but both it and the real integration implement the same spec-0001/T2 HarnessInterface (send/reset/close); real CLI integration belongs to the 0003/T1 launcher.
- Return str from send vs return a tuple of three (including exit_code/gold): choose str. This round does not implement the objective line, and there are no consumers of gold/exit_code; this is consistent with the spec-0001/T2 send->str contract, so the stub can be fed directly to consumers that depend on HarnessInterface.

## Prior art

### User modeling core: persona dimensions and action space/state machine (T1, T2)

spec-0001/T1 Persona field conventions, spec-0001/T2 black-box conversation protocol (aligned channel semantics). CLAUDE.md: persona comes from real data, not constructed from benchmarks; benchmark held-out. extract-selfreport-persona example C (orthogonal dimensions: expert×over-trust, derive_* must be overridable by grounded values). See this group's prototype for the reference implementation (dimensions.py / clauses.py / actions.py / action_space.py / state.py).

### Prompt assembly and persona LLM backend (T3)

spec-0001/T3 LLM backend injected as Callable. CLAUDE.md single runtime nexau (0003/T2).
See this group's prototype for the reference implementation (prompt.py / persona_client.py).

### Experience scoring: emit both paths (T4)

spec-0001/T1 FeelingScore data contract; spec-0001/T3 “produce FeelingScore via LLM at the end of the session”.
CLAUDE.md user side (a): experience score as a training signal, benchmark held-out. See this group's prototype for the reference implementation (feeling.py).

### Session main loop engine (T5)

spec-0001/T3 user agent driver (minimal stub), T2 black-box conversation protocol, T4 session orchestration run_session.
spec-0004 layering (harbor wraps only the outer rollout, with standalone turn-by-turn conversation). See this group's prototype for the reference implementation (loop.py).

### harness stub and run entry point (T6)

spec-0001/T2 HarnessInterface + FakeHarness (send/reset/close), spec-0003/T1 harness launcher (real integration).
See this group's prototype for the reference implementation (harness_adapter / scenarios / demo / run_live.py).

## Unresolved questions

### User modeling core: persona dimensions and action space/state machine (T1, T2)

- When integrating into the closed loop, how should the 9-dimensional Persona be aligned with spec-0001 models.Persona (five-tuple): extend models.Persona, or add a 9-dimensional↔five-tuple conversion layer? This group remains self-contained for now; the decision is deferred to dev-side integration.
- The objective ground-truth line (objective/gold/GAP/control-plane) is not implemented this round and is deferred in full to a later observability spec; it will then be restored under the held-out constraint of “bypass only, no writes to state/persona, no inclusion in the experience score”.

### Prompt assembly and persona LLM backend (T3)

When integrating into the closed loop, should PersonaClient converge on 0003/T2 nexau_runtime (single-runtime constraint)? The existing ApiPersonaClient and nexau_runtime.Agent have different backend interfaces (respond(system,user)->dict vs run(input)->str), requiring an adapter layer; the decision is deferred until integration.

### Experience scoring: emit both paths (T4)

When integrating into the closed loop, should sim's FeelingScore converge on reuse of spec-0001 models.FeelingScore (deduplication, single data contract)?
When the two scores disagree (e.g. 1 vs 2), whether the training signal uses the LLM self-assessment, the derived score, or a combination is to be decided during integration with the dev-side experience gate (0003/T4).
The scoring rules (thresholds/weights) are CLAUDE.md pending item #1; this group provides an initial coarse mapping, pending calibration with real data.

### Session main loop engine (T5)

The harness has been standardized on spec-0001/T2 HarnessInterface(send/reset/close) (this group's T6). Closed-loop integration still requires adapting the engine's native run_session(persona, client, harness, task) to spec-0001/T4's run_session(persona, scenario,
harness, user_agent, tracker, store): project turns to Transcript, convert issue_artifact to IssueDraft through IssueTracker, and align the 9-dimensional Persona and FeelingScore with models. This adaptation belongs to a later Task/group.

### harness stub and run entry point (T6)

The stub implements HarnessInterface (send/reset/close); real CLI harness integration still belongs to the 0003/T1 launcher. Whether to restore the control plane (process exit_code) and the objective ground-truth line later belongs to a later observability spec and is out of scope this round.

## Future possibilities

Several lines of work deliberately set aside by the control envelope are natural extensions after this group: first, restore the objective ground-truth line (gold/GAP/
ESCAPED_BUG/control-plane), integrating it as “bypass only, no writes to state/persona, no inclusion in the experience score” to check consistency between subjective user experience and the actual defect detection rate (see Unresolved questions); second, upgrade experience scoring from “once at session end” to per-turn scoring, restoring the granularity of “which turn got worse” (the tradeoff is already mentioned in T5 Rationale and can be revisited later if needed); third, replace T6's scripted harness stub with a real CLI harness in production (also implementing HarnessInterface, belonging to the 0003/T1 launcher), covering a broader distribution of real defects than preset trajectories; fourth, once 0006/T2 distills persona cards from real data, use real grounded d3/trust/d6 values to calibrate T1's current deterministic derivation lookup table and assess its fit to the real user distribution.

