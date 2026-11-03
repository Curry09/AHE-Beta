---
number: "0018"
title: "Unwrap architect proposal envelopes: complete_task deliveries are no longer silently discarded"
issue: 0
slug: architect-proposal-envelope
summary: "When the architect submits proposals using complete_task, nexau wraps the result in a tool envelope ({success,status,output:{result:\"[...]\"}}), while _parse_proposals deliberately avoids entering strings during its balanced-bracket scan and cannot find the top-level array → silently returns “no proposals this round.” In an actual 8-round long run, 0 of 6 structural proposals entered the backlog; the defect is also nondeterministic—when the agent follows instructions and calls complete_task, proposals are discarded, while disobeying and emitting a bare array gets them stored (the #6/#7/#8 issues that happened to be stored in round 6 immediately led dev to modify entry.py and tools/, proving that the structural evolution channel itself works and is simply blocked here). Implementation: unwrap envelopes at the architect/_run_agent exit + unit tests covering both paths (enveloped / bare array)."
tasks:
  - id: T1
    title: "Unwrap the complete_task envelope at the _run_agent exit"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/tests/loop/test_architect.py
    scope: "After architect/_run_agent receives the return value from agent.run(), unwrap nexau's complete_task envelope before passing it to _parse_proposals: add _unwrap_result()—unwrap envelopes shaped like {success,status,output:{result:<str|list>}} down to output.result (if result is already an array/object, use json.dumps to convert it back to a string; if it is a string, pass it through unchanged); return all non-envelope inputs (bare JSON arrays / prose / non-JSON) unchanged, preserving existing behavior. Leave _parse_proposals's balanced-bracket scan untouched (refusing to enter strings is the correct design and should not be relaxed to accommodate envelopes). Eliminate the perverse incentive whereby “an agent that follows instructions and delivers via complete_task has its output discarded.”"
    acceptance: "Enveloped returns (output.result is a JSON array string) can be parsed into proposals; the three existing paths—bare JSON arrays, json fenced code blocks, and arrays embedded in prose—retain their behavior; an empty result array in an envelope → 0 proposals (rather than an error); malformed/non-JSON envelopes fall back to the original text without raising exceptions. Unit tests cover the five cases above; use the actual original detail text from the 8-round long run as a regression fixture."
---

# 0018 · Unwrapping architect proposals: complete_task deliveries are no longer silently discarded

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level, nine-section rust-RFC overview. -->

## Summary

The architect **produced** structural proposals, but they were **silently discarded** by the parsing layer: nexau's `complete_task` wraps the result in a
tool envelope (`{success, status, output:{result:"[...]"}}`), turning the actual JSON array into a **string** inside the envelope;
meanwhile, the balanced-bracket scan in `_parse_proposals` **deliberately does not enter strings**, so it cannot find a top-level array → returns `[]` → records
“No structural proposals this round.” This group adds an envelope-unwrapping layer at the `_run_agent` output (T1) to reconnect this channel.

## Motivation

**This is not an observability flaw; it invalidates the premise of the entire experiment.**

The design workflow was intended to be “users produce bugs → the architect extracts structural root causes across issues from those bugs → developers make mechanism changes accordingly.”
With the middle link broken, the feedback loop degenerates into “users produce bugs → developers patch prompts”—exactly the outcome observed in the long run,
and contrary to the expectation of “evolving new tools / new orchestration.”

Empirical evidence (an 8-round long run, real model + real Gitea):

- In each of the first 5 rounds, the architect displayed “No structural proposals this round,” with **0 issues labeled `design`** in Gitea;
- The **original proposal text can be extracted** from the architect archive `detail` in `data/live/history.json`—they were there all along:

  ```
  Architect._parse_proposals(detail)   →  []  # Current behavior: everything is lost
  Parse after unwrapping the envelope  →  ['Missing latency budgets and validation intensity controls for small tasks']  # The proposal is actually there
  ```

- The cost is measurable: **6 structural proposals → 0 entered the backlog**.

### This bug is nondeterministic and **penalizes correct behavior**

The proposals in round 6 **were successfully stored** (issues #6/#7/#8). The only difference was **whether the agent actually called
`complete_task`** in that round:

| Round | architect return value | Result |
| --- | --- | --- |
| 1–5 | `{"success": true, "status": "TASK_COMPLETED", "output": {"result": "[...]"}}` (**envelope**) | Parsing failed; all 6 were lost |
| 6 | `[ { "title": "First-round budget prevents usable delivery", ... } ]` (**bare array**) | Parsing succeeded → #6/#7/#8 |

In other words: **when the agent follows the prompt and delivers through `complete_task`, its proposals are discarded; when it disobeys and emits an array directly, they are stored.**
Whether proposals enter the backlog depends on the model's random choice in that round—this is a perverse incentive that must be eliminated.

### Once the channel opened, developer behavior changed immediately (directly demonstrable causality)

| commit | Source issue | What changed |
| --- | --- | --- |
| `fix: issue #2~#5` | User bug | Only `agents/main.md` (prompt) + superficial tests asserting prompt content |
| **`fix: issue #6`** | **design proposal** | **`entry.py` +63 lines (the mechanism itself)** + MANUAL + 41 lines of substantive tests |
| **`fix: issue #7`** | **design proposal** | **`tools/complete_task.tool.yaml` (tool definition)** + prompt + MANUAL + tests |

**The developers were capable of making mechanism changes; they had simply never received mechanism-related tasks before.** The structural evolution channel itself works; it was just completely blocked here.

## Guide-level explanation

`_run_agent` now passes text through `_unwrap_result()` before handing it to `_parse_proposals`:

- If the return value is an `complete_task` envelope → unwrap it to `output.result` (the original proposal-array text);
- If the return value is a **bare JSON array / ```json fence / array embedded in prose** → **pass it through unchanged**, with exactly the same behavior.

There is no change to the behavioral requirements for the architect agent: it is still instructed to return a JSON array through `complete_task`.
The only difference is that now **following the instructions also succeeds**.

## Reference-level explanation

**DAG**: a single Task, with no dependencies.

**T1** (`architect.py` + `test_architect.py`):

```python
def _unwrap_result(out: object) -> str:
    """Unwrap the nexau complete_task envelope → output.result; return non-envelopes unchanged."""
```

- Input is not `str` → `str(out)` (preserve the existing fallback);
- Try `json.loads`; if it is not JSON, is not a dict, or has no `output.result` → **return the original text unchanged**;
- If `output.result` is `str` → return it directly; if it is `list`/`dict` → use `json.dumps` to convert it back to a string (the agent sometimes places the array
  directly in result rather than its string representation; both forms must be supported).

**Leave `_parse_proposals` unchanged**. Its balanced-bracket scan, which “respects string escapes and refuses to enter strings,” is **the correct design**
(to avoid being misled by `[]` in prose), and should not be relaxed to accommodate envelopes—that would turn a correct parser into a permissive one,
fixing the bug in the wrong place. Envelopes should be unwrapped **at the envelope layer**.

**Tests** (`test_architect.py`) cover five cases: an envelope (result is an array string), an envelope (result is the array itself),
a bare array, a fenced code block, and a malformed envelope falling back to the original text without raising an error; they also use **actual detail text** from the 8-round long run as a regression fixture.

## Drawbacks

- One additional parsing layer. The cost is minimal (one `json.loads` attempt), and failure falls back to the original text without changing the existing path.
- The envelope format is determined by nexau; if nexau changes the envelope schema, this code will need to follow suit. The “fall back to the original text if extraction fails” behavior reduces the risk to
  “revert to today's behavior” rather than “crash.”

## Rationale and alternatives

1. **Relax the scan in `_parse_proposals` so that it enters strings to find arrays** — Rejected. This would reintroduce the pitfall it deliberately
   avoided in the first place (being misled by `[]` in prose/strings), and fix the problem at the wrong layer.
2. **Change the prompt to tell the architect not to use `complete_task` and to emit a bare array directly** — Rejected. This makes the agent accommodate a framework
   bug and is unreliable (the model may still call the tool); the correct direction is exactly the opposite: following instructions should be rewarded.
3. **Unwrap envelopes centrally in `nexau_runtime`** — Deferred. Currently, only architect needs to parse structured agent returns
   (dev does not parse them, and the user side uses its own persona_io); extracting a shared layer prematurely would “add an entity.” If a second consumer emerges,
   move it up to `nexau_runtime` then (see Future possibilities).

## Prior art

**The same pitfall has already been fixed once in this repository**: `_unwrap_reply()` in `backend/harness_template/entry.py` specifically unwraps this same
layer of envelope (its comment says “Unwrap the envelope: the user only sees the final answer”). The harness side remembered to unwrap it; architect on the orchestration side missed it. This group applies
that lesson to architect.

`persona_io._parse_json` also encountered the related pitfall of “extracting JSON with crude find/rfind” and has already switched to robust parsing—this repository has
an established, consistent approach to “parsing LLM return values”: **parsers should be strict, and envelopes should be unwrapped at the envelope layer**.

## Unresolved questions

- In the architect archive, `round_no` is `None` (`history.json` shows `round None | proposals: None`);
  the round cursor was not persisted to the archive, so grouping by round on the board will be inaccurate. This is an observability-layer issue, outside this group's scope, and will be tracked separately.

## Future possibilities

- If dev / other roles also start parsing structured agent returns, move `_unwrap_result` up to `nexau_runtime`
  as the shared output interface of a single nexau adaptation layer.
- Further: have `complete_task` return result directly as a structured object (rather than a string), eliminating this unwrapping layer at the source.
