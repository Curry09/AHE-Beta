# Feedback and runtime integrity (Spec-0082)

Validated on 2026-10-05 in `feat/unified-experiment-entry`, after persona reuse commit `8293004`. These changes require a newly frozen controller; existing prepared runs retain their original implementation.

## Local regression

```bash
.venv/bin/pytest -q backend/tests
.venv/bin/ruff check backend/auto_designer backend/tests
PYTHONPATH=tools/spec-driven-development/vendor .venv/bin/python -m openagents.spec.cli validate
```

Focused validation covers actual Git exports and shell subprocesses, rather than depending solely on model output:

The initial Spec-0082 full backend suite passed: **2094 passed in 320.39s**. Ruff passed across backend source and tests; spec validation, generated architecture checks and Git whitespace checks passed. An earlier full run found an outdated direct outcome assertion and one batch preparation failure; the direct assertion now covers the added record, the batch case passed separately, and the unchanged final suite passed in full. The initial batch preparation failure's cause was not established. The subsequent direct storage alignment is verified separately below.

- Feedback roles read a shared immutable tested commit while the delivery checkout remains at the seed commit. Missing commits fail rather than falling back. Parallel and nested source bindings restore correctly; backlog triage and usage records use the report's commit.
- A real Harness subprocess receives the configured message/environment budget and returns its timeout reply during grace. Infrastructure timeout, transport exit, malformed protocol and product error have distinct receipts. The Docker command boundary forwards the budget before constructing its process arguments.
- A real direct subprocess emits progress and then stalls. The launcher terminates it at the outer deadline; the saved Session retains received steps and request termination. Timeline, beat and step tools can read those observations within existing role permissions. The direct persona still sends one message and reviews once; no SimTrace or intermediate user decision is fabricated.
- Public configuration rejects invalid budgets and uses frozen settings on both local and E2B. Old configurations do not gain budget defaults or silently inherit host knobs.
- Missing triage submission gets at most one completion retry, limited to eight iterations. A second missing submission remains a failure. This does not prove a submitted disposition is factually correct.

## Independent E2B and live model probe

An independent sandbox used the same template/build as the N8 environment, with a separately frozen verification controller. It did not connect to or alter the held N8 sandbox and did not create Gitea issues. It was released after verification.

- The initial integrity regression set passed in E2B: **18 passed in 6.71s**. Final transport/protocol and permission checks were subsequently covered by local tests.
- Actual `glm-5.3` executed the Triage agent with its real NexAU configuration and file tools. A test repository had two commits; its working tree deliberately stayed at the seed. The tested commit contained a random marker absent from the prompt and seed.
- The model read the exported tested source and returned that marker in a schema-validated `submit_triage` result. Six tool events were recorded. The checkout remained at the seed SHA.
- Seed SHA: `d786ffc9e02e0261ed1fd8c03716e72f732474b1`; tested SHA: `ef56b28e1bd398c70e4c752505a54de946351b71`.
- Frozen probe archive SHA-256: `098c7d3e45ebff5d3aa9690fe2cffb6870ed9839306368992403c0339867dc33`. The probe covered source binding, deadline grace and direct observations; subsequent receipt classifications and integer-compatible environment formatting were verified locally.

## Direct storage alignment

After review, the direct-only 256-item and 4000-character storage limits were removed. The small capture helper now lives with the existing direct adapter in `loop/sim_user.py`; the separate `harness/records.py` module was removed. Like simulated sessions, direct Sessions preserve received native steps, event frames, text and metadata without clipping them before storage. Query projections retain the shared limits; raw frames are not included in the L2 summary.

Focused regression result: **150 passed in 34.92s**, covering integrity, direct sessions, simulated session adapters, timeline/beat/step tools, Orchestrator, launcher, reusable personas and multi-task controllers. Ruff, spec validation, generated architecture and whitespace checks passed.

- Direct and simulated storage round-trip 300 steps/events with 5000- and 9000-character bodies and extra metadata. Native replies, progress-only fallback and nested progress frames are covered. The original middle step index 150 remains queryable.
- Both beat queries return at most 80 items; both step queries retain the same 6000-character expansion limit. A 5000-character body is fully retrievable; a 9000-character body is still fully stored while its query response is clipped.
- Direct stdout query summaries retain only eight short observations and exclude full raw frames. Malformed progress frames are preserved as received events without inventing steps. Existing real-process timeout and role-permission tests still pass.
- This correction was validated locally. The earlier E2B probe above tested the initial implementation, not the revised storage policy. No additional cloud experiment was started for this correction.

## Existing N8 evidence

The original all-direct run completed R1 and the eight R2 user sessions, then encountered missing triage submission. After retry it reached R2 delivery, but feedback had already read the seed checkout instead of the tested R2 SHA. Successful submission alone did not repair that evidence mismatch.

That sandbox was paused and its recovery ledger, role/session data and controller logs captured without rewriting previous results. The hold archive SHA-256 is `b98d3315c1f0138376cee337042f17ead9adc9d7d57266f0d8267f8aa261cdfe`. The run remains unfinished. The independent probe is not a completed N8 round, acceptance verdict, or proof that previous proposals were correct. Internal execution not received by the launcher and missing task artifacts remain unknown.
