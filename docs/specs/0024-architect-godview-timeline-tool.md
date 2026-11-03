---
number: "0024"
title: "Persist the user's god-view + on-demand access for the architect"
issue: 0
slug: architect-godview-timeline-tool
summary: "Persist the full god-view in Session.sim_trace; three layers of on-demand evidence retrieval for the architect—usage-event timeline projection (get_session_timeline, including utterance↔answers request–reply pairing) → beat-level harness activity (get_harness_beat) → single-step expansion (get_harness_step); user experience curves include session handles; jail still prohibits direct reads of sessions/. This group does not retire runtime_agg."
tasks:
  - id: T1
    title: "Persist Session.sim_trace (TurnLog→SimTrace)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/models.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/user/sim/loop.py
      - backend/ahe_beta/user/sim/persona_client.py
      - backend/tests/test_models.py
      - backend/tests/loop/test_sim_user.py
    scope: "Add optional sim_trace (SimTurn/SimTrace/PersonaCallTrace) to Session; run_session collects persona_trace/persona_tail; sim_user.result_to_sim_trace persists it. Older JSON without this field remains compatible with None."
    acceptance: "Session JSON for new sessions contains sim_trace.turns (including perceive/verdict/action/harness_output/persona_trace); from_dict on older sessions yields sim_trace=None; related unit tests pass."
  - id: T2
    title: "Extend index with issue_numbers + include session_id in user experience curves"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/session_store.py
      - backend/tests/loop/test_architect.py
      - backend/tests/user/test_session_store.py
    scope: "SessionStore.save writes index.issue_numbers; _feeling_trend/_format_trend output [session=…] handles so the architect can inspect the timeline for individual user experience data points. (The feeling formatting implementation currently resides in architect.py and belongs to the T5 file set.)"
    acceptance: "New index entries contain issue_numbers; user experience lines in propose_once task messages contain session=; unit tests cover trend four-tuples."
  - id: T3
    title: "get_session_timeline tool entry point (on-demand evidence retrieval path)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files: []
    scope: "Introduce get_session_timeline(issue|session_id) and bind_session_store to enable on-demand evidence retrieval under jail. The initial tool output passed through persisted data unchanged; the current output format is handled by the T4 projection and T5 beat/step registration (see T4/T5 for file ownership; this Task retains its DAG node)."
    acceptance: "The architect can retrieve process evidence for a session via the tool (rather than reading sessions/); return ok=false if no store is bound or the session is not found; jail still denies reads of sessions."
  - id: T4
    title: "get_session_timeline usage-event projection (remove the simulation wrapper)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/session_timeline.py
      - backend/agent_defs/architect/tools/get_session_timeline.tool.yaml
      - backend/tests/demand/test_session_timeline.py
    scope: "Change format_session_timeline from passthrough to event projection: retain wanted/process_read/capability_gap (include available only when misaligned)/saw_activity/private_check/silent_stop/feeling/issue; remove system/user/raw, persona_id, persistent action_space, patience/trust, role names, tracker URLs, and full stdout. Session.sim_trace persisted to disk remains complete and authoritative. Implement projection functions for get_harness_beat/get_harness_step in the same module (see T5 for tool registration)."
    acceptance: "format_session_timeline output contains no LLM system/user/raw or persona_id; capability_gap appears only when there is a gap and includes available; beat/step functions can return stop_kind and truncated/expanded bodies by turn/step_i; unit tests cover projection stripping, beat classification, and step expansion."
  - id: T5
    title: "Architect tool wiring for progressive drill-down (beat/step)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/architect/tools/get_harness_beat.tool.yaml
      - backend/agent_defs/architect/tools/get_harness_step.tool.yaml
      - backend/agent_defs/architect/agent.yaml
      - backend/agent_defs/architect/systemprompt.md
      - backend/ahe_beta/demand/architect.py
    scope: "Register get_harness_beat / get_harness_step; specify progressive usage in systemprompt and the propose_once task text: first get_session_timeline → get_harness_beat(turn) when needed → get_harness_step(step_i) only when truncated and truly necessary. The jail continues to prohibit direct reads of sessions/."
    acceptance: "agent.yaml contains both tool bindings; the prompt/task text specifies three levels of evidence gathering; the architect can call them as needed in propose_once (observable via probes); drilling down into every beat by default is not required."
  - id: T6
    title: "Request-reply pairing: heard.answers → utterance"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/tests/user/sim/test_heartbeat.py
    scope: "Assign an utterance_id to each outbound user→harness instruction; the one opened by begin is the current open; while waiting, mark emit/send_message with delivery=queued + queued_behind=open; write answers_utterance_id (and an answers_said preview) to received harness_output/heard. Do not change the harness wire protocol. Implement this in the existing T1/T4/T5 file set (loop/models/session_timeline/systemprompt/tool yaml); this group's files list only the newly required heartbeat unit tests. The timeline and architect prompt must make it immediately clear which utterance each reply answers."
    acceptance: "New-session sim_trace/timeline: outbound instructions have utterance; queued interjections include queued_behind; heard includes answers pointing to the corresponding utterance; the reply received first after an interjection still has answers pointing to the begin utterance rather than the interjection; support older sessions with missing fields; unit tests cover pairing and projection."
---

# 0024 · Persisting the user's god-view + on-demand access for designers

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG); the body is a nine-section, group-level rust-RFC overview. -->

## Summary

**Fully persist** the user simulation's **god-view** with `Session` as `sim_trace` (authoritative raw data, including original persona LLM records, for post hoc debugging). Designers do **not** receive the entire bundle in the first-turn prompt; instead, they gather evidence **on demand and progressively** through tools:

1. `get_session_timeline` → **usage-event timeline projection** (intent/process judgments/capability gaps/private verification; private verification comes from inner persona tool steps, not the outer `verify_self`; **`utterance`↔`answers` request–reply pairing**; no system/user/raw);
2. `<private_evidence>` → the user simulation's own private evidence memory across turns (also sourced from inner persona tool steps, but supplied only to subsequent user-sim prompts, not a timeline raw dump);
3. `get_harness_beat(turn)` → inspect the inner harness tool sequence for a specific beat (short excerpts of the content) and `stop_kind`;
4. `get_harness_step(step_i)` → expand a single step (hard character cap).

The experience curve carries an `[session=…]` handle. Jail (0015) continues to prohibit direct reads of `sessions/`. This group does not deprecate `runtime_agg`.

## Motivation

The architect's entry signals (0016, etc.) are primarily the open issue backlog, experience curve, and `runtime_agg`—these are **summaries of outcomes and mechanisms**. They do not reveal “why the user waited, when they gave up, or how their internal assessment diverged from their outward wording,” and make it difficult to distinguish whether the budget was spent on exploration or just before delivery when hitting max_iterations versus a wall-clock timeout.

Putting the complete god-view / all harness_steps into the first-turn prompt causes a token explosion (in actual measurements, three unmodified sessions can reach hundreds of thousands of tokens). Persisting them without providing an access route leaves `sessions/` blocked by jail. What is needed is “**full persistence + tool-side projections and progressive drill-down**.”

## Guide-level explanation

**For user simulation / orchestration**

1. After each session, `Session` writes the full `sim_trace` in addition to conversation `transcript`, feeling, and issue_refs.
2. `index.json` entries in `SessionStore` include `issue_numbers` to facilitate reverse lookup of sessions by issue.

**For designers (progressive evidence gathering)**

1. The first turn of `propose_once` still supplies only: the open issue backlog + experience curve (with `[session=…]`) + `runtime_agg` (if available).
2. When process evidence is needed:
   - `get_session_timeline(issue_number|session_id)` → usage-event timeline (projection);
   - A beat's `heard` indicates a timeout/limit, or `saw_activity` is too coarse → `get_harness_beat(turn=…)`;
   - A step has `truncated=true` and its content is truly needed → `get_harness_step(turn=…, step_i=…)` (still hard-capped; do not put large blocks of stdout into proposals).
3. Do not use `read_file` / `list_directory` to scan `sessions/` (jail remains in effect).

**Relationship to “indirect session data”**

| Signal | This group's position | Reason |
| --- | --- | --- |
| Open issue backlog | **Retain** | Entry point for designers to select topics |
| Experience curve (+session handle) | **Retain** | Select “which sessions warrant drilling down” |
| `runtime_agg` | **Not deprecated by this group** | Orthogonal to qualitative process evidence |
| Direct reads of `sessions/` | **Still prohibited** | 0015 jail; all access goes through tools |

## Reference-level explanation

### Task DAG

`T1` (persistence) → `T2` (index + experience handle) → `T3` (tool access-route node) → `T4` (projection + beat/step functions) → `T5` (beat/step registration and prompts) → `T6` (utterance↔answers pairing).

### Data model (authoritative persisted data)

| Type | Key points |
| --- | --- |
| `PersonaCallTrace` | One persona LLM call: role / system / user / raw / parsed / steps |
| `SimTurn` | One beat: turn / phase / perceive / action / message / harness_output / harness_steps / persona_trace; T6 adds `utterance_id` / `delivery` / `queued_behind` / `answers_utterance_id` / `answers_said` |
| `SimTrace` | `turns` + optional `persona_tail` (rate / file_issue) + `end_reason` / `signals` |
| `Session.sim_trace` | Full persistence; missing fields in old JSON → `None` / empty string |

Collection: `persona_client` → `run_session` tags the role → `sim_user.result_to_sim_trace` → `SessionStore.save`.

### Request–reply pairing (T6)

No changes to the harness wire protocol. Simulation-side `_UtteranceLedger`:

| Timing | Persisted data |
| --- | --- |
| Main-loop outbound EMIT (begin) | `utterance_id=uN`, `delivery=open` |
| `send_message` / emit while waiting | New `utterance_id`, `delivery=queued`, `queued_behind=<current open instruction>` |
| Receipt of reply / interrupt acknowledgment | The Turn carrying `harness_output` in the next beat writes `answers_utterance_id` + `answers_said` (the open entry being closed) |

Timeline projection: `utterance` / `delivery` / `queued_behind` / `answers` / `answers_said`. For the first reply arriving after an interjection `queued`, `answers` still points to the open entry at that time (the begin entry), rather than the interjection.

### Usage-event projection (T4 · `format_session_timeline`)

Top-level JSON: `session_id` / `started_at` / `feeling` / `issues[{number,state}]` / `timeline{end_reason,events[]}`.

Common fields in each `events[]`:

| Field | Meaning | When present |
| --- | --- | --- |
| `t` | `SimTurn.turn` (use sequence numbers to preserve order when no wall-clock time is available) | Turn events |
| `when` | `opening` / `during_wait` / `after_reply` / `closing` | Mapped from phase |
| `thought` | Cleaned-up, plain-language observation (`[judgment\|intent→action]` header removed) | perceive is nonempty |
| `process_read` | on_track / off_track / unclear | A waiting judgment exists |
| `wanted` | Free-form intent before convergence | parsed.intent is nonempty |
| `did` / `said` | Final action / emitted message | Written if present |
| `utterance` | ID of the instruction sent in this beat (`uN`) | EMIT has content |
| `delivery` / `queued_behind` | `open` or `queued` (and which open entry it is queued behind) | T6; queued only for interjections while waiting |
| `heard` | Harness terminal reply (length-limited) | harness_output is nonempty |
| `answers` / `answers_said` | Utterance closed by this heard entry + preview | T6; heard exists and can be paired |
| `saw_activity` | Short activity-entry titles (skip tool_result content; at most the last 8 tools) | harness_steps exists |
| `capability_gap` | `{wanted,did,available,note}` | Only `parsed.gap==true` |
| `private_check` | User's local verification steps (truncated) | Private tool/tool_result/tool_error appears in persona_trace; does not depend on outer `verify_self` |
| `silent_stop` | `true` | `did==interrupt` |
| `issue_text` / `feeling` | End-of-session exit | persona_tail |

**Deliberately excluded from the projection**: system/user/raw, persona_id, the complete persistent action_space table, patience/trust, waiting_* role names, fake:// URLs, full stdout, and verbatim machine-signal strings.

`private_check` and `<private_evidence>` share the same source but serve different purposes: the former is a usage-event projection in the timeline for designers/auditors; the latter is the user-sim's own within-session memory, formatted as `[E# phase/stage] Private tools ... Conclusion/Observed ...` and fed back into subsequent main/waiting judge/intent/act prompts. Neither may contain complete stdout/full file contents or a benchmark oracle; complete raw data remains stored only in `Session.sim_trace.persona_trace.steps`.

### Progressive drill-down contract

**Session resolution** (shared by all three tools): prioritize `session_id`; otherwise reverse-lookup `issue_number` → index.`issue_numbers`, falling back to a disk scan for old indexes; no bound store / not found → `{ok:false,error}`.

#### `get_session_timeline`

- Input: `issue_number?` | `session_id?`
- Output: `{ok, session_id, timeline}`, with `timeline` as the projected JSON string

#### `get_harness_beat` (T4 function + T5 wiring)

- Input: `turn` (required, = timeline `t`), `occurrence?` (when multiple beats share a turn, defaults to 0; prioritize candidates with harness output/steps)
- Output highlights: `when` / `user_did` / `heard` / `stop_kind` / `steps[{i,kind,text,truncated?}]` / `n_steps_raw`
- `steps`: tool titles approximately 220 characters, result/assistant approximately 280 characters; above approximately 80 steps, retain the first 20 + the tail, with `omitted` in the middle
- **`stop_kind` ↔ top-level harness controls** (for attribution; do not tie to specific SWE tasks):

| stop_kind | Typical heard | Source reference |
| --- | --- | --- |
| `max_iterations` | `Maximum iteration limit reached` | `agent.yaml` → `max_iterations` |
| `wall_timeout` | Historical `[timeout]` / infrastructure limit | Old harness deadline / launcher absolute limit |
| `interrupt` | `[interrupted]…` | User-side interrupt / control |
| `completed` | Normal delivery text | — |
| `empty` | No harness_output | Waiting beats, etc. |

#### `get_harness_step`

- Input: `turn` + `step_i` (= the beat's `steps[].i`, i.e., the raw `harness_steps` index) + session selection as above
- Output: `text` (newlines preserved), `n_chars_raw` / `n_chars_returned` / `truncated`; current hard cap is **6000** characters
- Purpose: only when the beat has `truncated=true` and the architect judges that the step's content remains critical; embedding large blocks of stdout in proposals remains prohibited

### Wiring and injection (T5)

- `agent_defs/architect/agent.yaml`: register timeline / beat / step
- `systemprompt.md` + `Architect._run_agent` task text: stipulate “timeline first → then beat → step if necessary”
- `bind_session_store`: `ContextVar` + module-level `_STORE_FALLBACK` (nexau tool callbacks often run in another thread)
- `SANDBOX_WORK_DIR`: points to the harness repository's **absolute path** during architect runs (for grounding through source-code reads)

### Verification signals (not acceptance gates; for comparison)

On a SWE-bench_Verified real-repository probe, observable architect behavior is: first read `entry.py`/`agent.yaml`, then use `get_session_timeline` for 6 sessions, then use `get_harness_beat` for timeout beats (`stop_kind` distinguishes iteration vs wall); `get_harness_step` is not mandatory (it can be skipped when the beat provides enough evidence for attribution).

### Boundaries (still outside this group's scope)

- Do not change the architect activation model (still once per round, with the full backlog).
- Do not delete `runtime_agg`.
- Do not provide unlimited raw log downloads; further truncation after the hard cap serves only as a “too large” signal.
- Removing soft steering from user sim prompts and SWE-bench probe scripts: outside this group's file set and excluded from this Task.

## Drawbacks

- Persisted data remains large (full raw data); tool-side injection volume is controlled, but disk costs remain.
- Risk of losing details in projection: mitigated by beat/step; if designers never drill down, they may miss “which tool call consumed the budget.”
- `issue_number` still points to “the latest session containing that number”; use `session_id` for history across multiple sessions.
- Three tool layers increase the selection burden; prompts constrain this with “stop by default once there is enough,” relying on model self-discipline.

## Rationale and alternatives

- **Persist full data vs store summaries only**: Full data can be reprocessed later; choose full persistence + tool-side projection (replacing the initial passthrough).
- **Tool drill-down vs first-turn injection**: Consistent with “review the entire backlog before selecting topics.”
- **One timeline layer vs three progressive layers**: One layer is either too coarse or too bulky; three layers default to coarse detail, with finer detail on demand. In practice, designers go timeline→beat, opening step only when the body content remains critical.
- **Extend 0024 vs open a new 0025**: Both address “god-view persistence + on-demand evidence retrieval”; the Future section of 0024 already anticipated projection, so `add-task` belongs in this group rather than under a new number.
- **Deprecate `runtime_agg`?**: **No (in this group)**.

Alternatives considered: sidecar, a turn-paginated API, and automatic pre-injection of low-score sessions—excluded from the MVP.

## Prior art

- 0015: Architect jail.
- 0016: Experience reason + `runtime_agg`.
- 0022 / 0023: User simulation IO and event-driven waiting (god-view field semantics).
- Initial T3 passthrough in this group: Changed to T4 projection due to context explosion (evolution of the live snapshot).

## Unresolved questions

1. **Step hard cap and secondary truncation**: Is 6000 appropriate? Is `offset/limit` needed to read oversized stdout in segments?
2. **Whether to retain `runtime_agg`**: Should it be downgraded to dashboard-only in the architect prompt? (Still retained in this group.)
3. **Multiple sessions / same issue**: Should listing all related sessions be supported?
4. **Beat step-type annotations**: Should the proportions of “exploration/editing/testing” be marked directly at the beat layer to further reduce step expansion?

## Future possibilities

- Return structured proportions of “exploration vs verification” step types at the beat layer.
- Cross-session aggregation: Cluster by `stop_kind` / gap patterns to generate a list of hypotheses about harness problems.
- Reuse the same timeline / beat format for the dashboard read-only API.
- Support byte-offset pagination for step (only if testing shows the hard cap is insufficient).
