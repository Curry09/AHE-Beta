---
number: "0030"
title: "harness productization boundary: /help user documentation, platform-side interfaces, and connector adaptation"
issue: 0
slug: harness-product-interface
summary: "Refine harness into a product that real users can run: retain only HELP.md as the /help content source and RUNTIME.md as maintenance guidance in the harness template; README/USER/MANUAL are no longer template documents, and INTERFACE belongs on the AHE-Beta platform side; connector adapts sim-user to the human-facing interface; launcher/template support stdio-jsonl-v1 and remain compatible with legacy."
tasks:
  - id: T1
    title: "Write the 0030 living snapshot"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0030-harness-product-interface.md
    scope: "Define harness as a product that real users can run, ahe-beta as the training/observation platform, and connector as the adapter from sim-user to the human-facing interface; user help is read from HELP.md by /help; platform interface documentation belongs in ahe-beta; do not put persona/feeling/issue/round/triage/sim_trace/user simulator in harness."
    acceptance: "spec validate passes; the body contains Summary/Motivation/Reference-level explanation/Rationale and alternatives; tasks are clearly allocated across HELP/RUNTIME, platform-side interfaces, connector/protocol, and boundaries."
  - id: T2
    title: "Streamline harness_template to HELP/RUNTIME/scripts/deps"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/LICENSE
      - backend/harness_template/HELP.md
      - backend/harness_template/RUNTIME.md
      - backend/harness_template/.env.example
      - backend/harness_template/requirements.txt
      - backend/harness_template/scripts/run.sh
      - backend/harness_template/scripts/smoke.sh
      - backend/harness_template/scripts/check.sh
    scope: "Retain only HELP.md as the /help content source, RUNTIME.md as maintenance guidance, and env/deps/scripts as a self-contained runtime suite in the harness template; do not retain README.md, USER.md, MANUAL.md, or INTERFACE.md."
    acceptance: "After checkout, the new template can be understood and run using HELP/RUNTIME/scripts/env/deps; HELP and RUNTIME have clearly separated responsibilities; template documentation does not contain platform concepts such as persona/feeling/issue/round/triage/sim_trace/user simulator."
  - id: T3
    title: "/help slash command and template self-tests"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/entry.py
      - backend/harness_template/agents/main.md
      - backend/harness_template/tests/test_smoke.py
    scope: "Add the /help slash command: read HELP.md and return the help text without ending the session; /exit and /quit still end the session; remove platform terminology from entry.py / agents/main.md; template self-tests cover the presence of HELP, /help behavior, scripts shebangs, and prohibited platform terminology."
    acceptance: "Running python3 -m unittest discover -s tests -p 'test_*.py' from the backend/harness_template root passes; /help returns the contents of HELP.md and the session continues; /exit|/quit still exit; default self-tests do not depend on real LLM network access."
  - id: T4
    title: "Product commit boundary: reject secrets and runtime state"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/guards/harness_boundary.py
      - backend/tests/guards/test_harness_boundary.py
    scope: "guards/harness_boundary uses a product commit denylist: reject .env, .env.* (except .env.example), and top-level .openagents; normal product code, documentation, and configuration may be committed."
    acceptance: "HELP/RUNTIME/docs/src and .env.example may be committed; .env, .env.local, and .openagents are rejected; local hooks and seed smoke rules are consistent."
  - id: T6
    title: "connector and stdio-jsonl-v1 protocol adaptation"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/harness/connector.py
      - backend/tests/harness/test_connector.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/tests/loop/test_sim_user.py
      - backend/ahe_beta/user/sim/loop.py
      - backend/tests/user/sim/test_heartbeat.py
      - backend/ahe_beta/harness/launcher.py
      - backend/tests/harness/test_launcher.py
      - backend/harness_template/params.yaml
      - backend/ahe_beta/harness/INTERFACE.md
    scope: "connector serves as a platform-side adapter, mapping sim-user's send/interrupt/shutdown to the human-facing interface; launcher selects stdio-jsonl-v1 or legacy wire based on params.yaml protocol/interface; the template declares v1 and reads both legacy and v1; platform-side INTERFACE.md documents the connector/launcher protocol."
    acceptance: "connector satisfies HarnessInterface; interrupt/give_up use the connector's named API; launcher v1 fake entry tests for message/progress/reply/error/interrupt pass, and legacy continues to pass; sim_user runs successfully offline; platform-side INTERFACE.md exists and documents v1/legacy."
---

# 0030 · Harness productization boundary: /help user guidance, platform-side interface, and connector adaptation

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level rust-RFC nine-section overview. -->

## Summary

The old built-in Developer wrap-up middleware and its configuration wiring (the original T5) have been retired; platform-side reading of HELP.md remains covered by T6's launcher and interface tests.

This group refines harness from “a fragment of the system under test in the ahe-beta closed loop” into a seed for “a product that real users can run”: the harness template retains only `HELP.md` as the content source for `/help` and `RUNTIME.md` as maintainer guidance, together with `.env.example` / `requirements.txt` / `scripts/` / `tests/` to support independent operation and self-testing; `README.md`, `USER.md`, and `MANUAL.md` are no longer template documents, and `INTERFACE.md` belongs on the AHE-Beta platform side.

At the same time, the platform side adds `HarnessConnector` as an adapter from sim-user to the human-facing interface, and enables launcher/template to support `stdio-jsonl-v1`: the new template declares v1 through `params.yaml`, while the old wire remains compatible. harness does not accept training/observation concepts such as persona, feeling, issue, round, triage, or sim_trace.

## Motivation

The point of a “self-contained harness” is not to pile up documentation, but to let real users or maintainers understand how to use and maintain the product by looking only at the harness repo, while allowing the AHE-Beta platform to adapt to it through connector. Previously, README / USER / MANUAL / INTERFACE coexisted with overlapping responsibilities, making it easy to put platform integration documentation into harness itself; this would mix training platform concepts into the target of evolution and weaken the boundary.

This group consolidates user help in the in-product `/help`, moves protocol documentation to the platform side, and uses connector to adapt simulated user actions into actions a human would perform on harness. Thus harness is the product, ahe-beta is the training/observation platform, and connector/launcher form the integration boundary.

## Guide-level explanation

```text
AHE-Beta
  user simulator / feeling / issue / triage / metrics / orchestrator
          │
          ▼
  HarnessConnector + HarnessLauncher (platform-side integration seam)
          │  stdio-jsonl-v1 / legacy
          ▼
harness repo
  entry.py + HELP.md + RUNTIME.md + agents/tools/scripts/tests
```

There are only two types of textual guidance in the harness repo:

- `HELP.md`: the `/help` content source for real users, describing what the product can do, how to exit, how to interrupt, and workspace semantics.
- `RUNTIME.md`: runtime boundaries for maintainers, describing maintenance constraints for the harness repo, workspace, NexAU, session/timeout/interrupt, and so on.

The programmatic interface documentation is not placed in the harness template; it is placed in `backend/ahe_beta/harness/INTERFACE.md` because it serves connector/launcher maintainers.

## Reference-level explanation

### Harness template file responsibilities

`LICENSE` is distributed with the standalone seed Harness and retains the project's MIT license; it is not content for `/help`.

| File | Responsibility |
|------|------|
| `backend/harness_template/HELP.md` | Content returned by `/help`, describing user capabilities |
| `backend/harness_template/RUNTIME.md` | Runtime boundaries for maintainers |
| `backend/harness_template/.env.example` | `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` / `SANDBOX_WORK_DIR` template |
| `backend/harness_template/requirements.txt` | Minimal dependency list for harness itself |
| `backend/harness_template/scripts/*.sh` | Run, self-test, and unified check |
| `backend/harness_template/tests/*` | Self-tests for harness itself; no task project tests |

The template no longer contains `README.md`, `USER.md`, `MANUAL.md`, or `INTERFACE.md`.

### Slash help

`/help` is a product command inside an ordinary message:

```text
message: /help
→ entry.py reads HELP.md
→ outputs reply
→ session continues
```

`/exit` and `/quit` still end the session after outputting a reply. Unknown slash commands are still passed to the agent as ordinary user messages.

### Connector and protocol

`HarnessConnector` provides a platform-side semantic API:

- `send_user_message(text)` / `send(text)`: forward only text that a human can enter.
- `interrupt()`: interrupt the current request.
- `shutdown()`: end the current harness process.

Training/observation data does not pass through connector into harness.

`HarnessLauncher` uses `params.yaml` as follows:

- `protocol: stdio-jsonl-v1` → send `{"type":"message","text":...}` / `{"type":"interrupt"}` / `{"type":"shutdown"}`, read `type=progress/reply/error`.
- Missing or `legacy` → old `{"message"}` / `{"control"}` and `{"reply"}` / `{"progress"}`.

### Boundary

The current commit boundary uses a denylist: normal product code, documentation, and configuration may be committed; reject `.env`, `.env.*` (except `.env.example`), and top-level `.openagents`. Legitimate extensions are no longer restricted to fixed product filenames.

### DAG / file allocation

```text
T1 ─┬→ T2 ─┬→ T3
    │      ├→ T4
    │      └→ T6
```

- T1 writes the spec.
- T2 consolidates template documentation/scripts/dependencies.
- T3 implements `/help` and adds self-tests.
- T4 maintains the product commit denylist.
- The old wrap-up check wiring from the original T5 has been retired; platform-side reading of HELP.md is maintained by T6.
- T6 handles connector and v1/legacy protocol adaptation.

### E2E verification path

```bash
./tools/spec-driven-development/spec validate
python backend/scripts/check-spec-number-conflicts.py
uv run pytest backend/tests/user/sim/test_heartbeat.py backend/tests/harness/test_connector.py backend/tests/loop/test_sim_user.py backend/tests/harness/test_launcher.py backend/tests/guards/test_harness_boundary.py backend/tests/test_bootstrap_harness.py
(cd backend/harness_template && python3 -m unittest discover -s tests -p 'test_*.py')
```

## Drawbacks

- The v1 and legacy stacks will coexist in the short term, until the old wire is confirmed to be unnecessary.
- Removing README/USER/MANUAL leaves fewer entry points for people browsing the repo directly, making them dependent on the division of responsibilities between `/help` and `RUNTIME.md`.

## Rationale and alternatives

### Why HELP.md instead of USER.md / MANUAL.md

User help is a product capability, and the most natural entry point is `/help`. `HELP.md` as the content source for `/help` is closer to CLI product conventions than `USER.md` / `MANUAL.md`, and also avoids confusion between old document names and platform-side reading behavior.

### Why INTERFACE is not in harness_template

Protocol details serve AHE-Beta connector/launcher maintainers, not as capability documentation for real users. Placing them on the platform side prevents the harness template from taking on responsibility for integration documentation.

### Why not retain README

The current seed already provides entry points for usage and maintenance through `HELP.md`, `RUNTIME.md`, scripts, and tests. README would overlap with HELP and add weight to the template. If standalone distribution is needed in the future, a separate spec can reintroduce a minimal README.

### Why retain legacy

Historical harness refs and existing tests still use the legacy wire. v1 is explicitly enabled through `params.yaml`, while old refs default to legacy, reducing migration risk.

## Prior art

- 0013: harness present protocol, basic reply/progress/steps/interrupt semantics.
- 0019: launcher accepts non-reply sideband.
- 0022: internal and external channels, interrupt and slash semantics.
- 0023: event-driven wait loop and try_reply.
- 0014: dev-side commit discipline and a hard gate for synchronizing user-visible help.
- 0015: harness commit boundary and isolation from overfitting leakage.

## Unresolved questions

- When to retire the legacy wire.
- Whether to allow `harness/` as a directory for product source growth in the future; this group does not address it.

## Future possibilities

- Further split launcher into protocol codec + process transport + connector factory.
- Make connector the default return object of `HarnessLauncher.launch()`, avoiding repeated wrapping by upper layers.
- After the legacy wire is retired, remove the `control()` public method and retain only the `interrupt()/shutdown()` semantic API.
- If standalone distribution proves necessary in the future, reintroduce a minimal README or package manifest.
