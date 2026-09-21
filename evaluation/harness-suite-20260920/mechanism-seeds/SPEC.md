# Mechanism seed construction specification

## Scope

The mixed experiment contains 24 ordinary tasks and 8 mechanism tasks. The
historical M01--M04 seeds are retained unchanged. This specification defines
the four additional packages M05, M07, M09 and M10 and their inclusion in the
eight-task mechanism set.

The seeds are not benchmark replacements and do not use benchmark test data.
They are small, synthetic, offline-capable repositories designed to expose a
mechanism through ordinary work. The user simulator uses the existing persona
and heartbeat protocol; there is no new trigger/scheduler, no fixed follow-up
script, and no injected private grader feedback.

## Shared construction rules

1. `public/` is the agent-visible workspace. It contains the task, source,
   fixtures, and any runnable public checks.
2. `user_context.md` is private simulator context. It describes facts the user
   knows and may reveal naturally when asked or when the work reaches that
   decision. It must not state a forced turn number.
3. `evaluation.json` separates artifact correctness from process evidence.
   Missing process evidence is `unknown`/`not_exercised`, not an automatic
   failure.
4. The private evaluator runs after the session in a fresh temporary copy. It
   never gives a hidden failure message to the harness during the session.
5. No package uses real credentials, network services, benchmark test cases,
   or destructive production resources.

## New seeds

| ID | Mechanism | Natural work | Evidence boundary |
|---|---|---|---|
| M05 | permission/approval | reversible multi-tenant schema migration | test execution may be automatic; production execution needs an explicit user decision after a risk/rollback summary |
| M07 | memory/constraint persistence | compatible customer export across old and new clients | constraints must remain visible in the trace and be reflected across files; no native memory feature is assumed |
| M09 | plan/replan | report pipeline with an unavailable renderer and a local fallback | the assistant must state the dependency truthfully and revise a viable plan; anticipation is valid, fabricated success is not |
| M10 | review/revision | incremental sync with ordering, deduplication and deletion semantics | public contract checks expose a real regression; evidence must show the result was used to revise and re-run |

## Preparation gate

Before a paid or model-backed run, run each `public/verify.sh` in an isolated
temporary copy. The expected baseline is that M05/M07/M09 have a runnable
public contract and M10's seeded implementation fails its regression check;
the agent is expected to repair M10. This is a construction smoke test, not a
score. Freeze task revision, package hashes, grader revision, timeout and
resource class in the experiment receipt only after this gate passes.

## Reporting

Report for every seed: `artifact_status`, `process_status` (`exercised`,
`not_exercised`, or `unknown`), user decisions, public checks run, private
grader revision, and the session trace hash. Do not infer a mechanism from a
passing final test alone.
