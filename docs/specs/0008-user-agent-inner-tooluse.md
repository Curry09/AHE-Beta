---
number: "0008"
title: "User agent inner tool use (verification in its own environment)"
issue: 8
slug: user-agent-inner-tooluse
summary: "This group upgrades the user-side “single `respond()` subjective judgment” in spec-0005 to an **inner tool-using agent that can verify in its own environment**: like a real person, the simulated user uses **its own tool stack** (reading code / running commands / writing scripts) to **actually execute** in its own sandbox when suspicious, grounding `verdict` in real results rather than speculation. **The outer control envelope (action space / state machine / user experience / termination) remains unchanged**; the only integration point is `PersonaClient.respond(system, user) -> dict`. The implementation target is `backend/ahe_beta/user/sim/`, an evolution of 0005/T3."
tasks:
  - id: T1
    title: "Seed workspace extension and shared injection (harness/user agent in the same directory)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0001/T1
        type: extends
      - ref: 0005/T5
        type: note
      - ref: 0003/T1
        type: note
      - ref: 0007/T2
        type: note
    parallel: true
    files:
      - backend/ahe_beta/user/sim/workspace.py
      - backend/seed_workspaces/billing-split/project/billing/core.py
      - backend/seed_workspaces/billing-split/manifest.yaml
      - backend/ahe_beta/models.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/harness/launcher.py
      - backend/tests/user/sim/test_workspace.py
      - backend/tests/harness/test_launcher.py
      - backend/tests/loop/test_orchestrator.py
    scope: "1) models.py: Add `workspace: WorkspaceSpec | None = None` to SeedScenario (defaulting to None falls back to today's text-only behavior, preserving all existing paths). 2) workspace.py: Define WorkspaceSpec (fixture name/relative path, setup-step placeholders) + materialize(spec, dest) -> str; the MVP only uses copytree to create a fresh isolated directory and returns its path. 3) seed_workspaces/billing-split/: An in-repo fixture—a minimal stdlib-only project (manifest.yaml describes metadata; project/billing/core.py contains runnable code). 4) Shared workspace wiring (v2): For each session, orchestrator.py calls materialize *before* launch to create a workspace workspace_dir, and passes it to both launcher and run_session; launch(ref, workspace_dir=None) in launcher.py injects it into the harness subprocess env as SANDBOX_WORK_DIR (the harness entry already reads this variable as the bash working root); run(..., workspace_dir=None) in sim_user.py reuses the supplied directory to bind the inner client (no longer calling materialize itself), falling back to materializing from scenario.workspace when no directory is supplied (direct-connection compatibility). Do not implement dependency provisioning (venv/pip) or git sources—only local fixture copytree. Do not change the run_session/respond engine signatures or the harness protocol."
    acceptance: "All existing behavior remains unchanged with SeedScenario(workspace=None); to_dict/from_dict round-trip consistently both with and without workspace (a missing field in an old dict → None). Given a billing-split spec, materialize returns a fresh, existing directory containing project/billing/core.py, which can be directly imported/executed by python (stdlib-only). Two materialize calls return different directories that do not affect each other (isolation). When workspace_dir is passed to launcher.launch, the harness subprocess env contains SANDBOX_WORK_DIR=workspace_dir (assert injection); when it is not passed, the env does not contain this key and the harness creates its own tmp (fallback). For each session, orchestrator calls materialize before launch and supplies the same workspace_dir to both launch and run_session (assert that launch and run_session receive the same directory). When workspace_dir is passed to sim_user, it binds directly to that directory without calling materialize itself; when no directory is passed but scenario.workspace is nonempty, it falls back to materializing the workspace itself; when ws is empty or the client has no bind_session, no call is made and no error is raised. The run_session/respond engine signatures and harness protocol remain unchanged. manifest.yaml can be parsed."
  - id: T2
    title: "Inner atomic tools and sandbox"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to:
      - ref: 0005/T2
        type: extends
    parallel: false
    files:
      - backend/ahe_beta/user/sim/tools.py
      - backend/ahe_beta/user/sim/sandbox.py
      - backend/tests/user/sim/test_tools.py
    scope: "1) tools.py: Implement three atomic tools, read_file / run_shell / write_file (a uniform signature and uniform return value {ok, stdout/content, error}); retain only a function/schema placeholder for web_search, returning not implemented when called. Define tool_stack(d1) -> list[tool]: Provide the available tool subset according to D1 (reuse the cap_mask gating approach from 0005/T2). 2) sandbox.py: Sandbox(workspace: str | None = None)—use workspace as cwd when supplied (from T1 materialize), or create an empty tempdir by default; provide restricted run_shell (timeout, stdout/stderr capture, working-directory isolation) and file reads/writes constrained to the workspace subtree. This is not a security sandbox (no Docker/seccomp), only a minimal isolated execution context."
    acceptance: "The three atomic tools are usable within Sandbox, and paths cannot escape the subtree; run_shell timeouts and nonzero exit codes are captured correctly. Sandbox(workspace=dir) uses dir as cwd and can run the code in T1's billing-split fixture; workspace=None falls back to an empty tempdir and still works independently. tool_stack: blind gets an empty set, shallow has no write_file, and competent/expert include write_file; web_search always returns not implemented."
  - id: T3
    title: "Prompt behavioral framework (optional verification) and placeholder skill interface"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0005/T3
        type: extends
      - ref: 0005/T1
        type: extends
      - ref: 0006/T1
        type: note
    parallel: true
    files:
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/clauses.py
      - backend/ahe_beta/user/sim/skills.py
      - backend/tests/user/sim/test_inner_prompt.py
    scope: "1) prompt.py / clauses.py: Update BLOCK-G—declare available tools (from T2 tool_stack), characterize verification as an “optional, costly in-character action,” and provide principles for when verification is worthwhile and when to make a subjective judgment directly (not mandatory). Update BLOCK-P—render “what verification you can perform/which tools you have” according to D1, and render “your current inclination to verify” according to D3 and the current trust/suspicion state. 2) skills.py: A placeholder select_skills(persona) -> list[Skill] (driven by D2), with Skill containing only name + a prompt fragment; return a minimal built-in set or an empty set in this round, without connecting to a real playbook library. 3) An assembly function that incorporates the tool list and skill fragments into the inner system section (for T4 to call)."
    acceptance: "build_inner_system renders different tool lists for different D1 values (blind has no tools; competent/expert include write_file); it renders different statements of verification inclination for different D3/trust values (low trust/strict D3 increases the inclination to verify). BLOCK-G explicitly states “verification is optional and costly; subjective judgment is the default.” The select_skills placeholder is callable, returns the correct structure, and its fragments contain no bug-specific or answer-specific content. T4 can use the assembled output directly as the inner system."
  - id: T4
    title: "Inner tool-using agent (AgenticPersonaClient)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to:
      - ref: 0005/T3
        type: extends
      - ref: 0005/T5
        type: note
    parallel: false
    files:
      - backend/ahe_beta/user/sim/persona_client.py
      - backend/tests/user/sim/test_persona_client_agentic.py
    scope: "1) persona_client.py: Add AgenticPersonaClient implementing the PersonaClient protocol. Inside respond(), run a bounded loop: build the inner system (call T3 build_inner_system) → feed it to the LLM → parse tool_call → execute in Sandbox (T2, cwd=T1 shared workspace) → feed the results back → until the LLM produces final structured output or reaches the step limit. Main verification path (T1 v2 shared workspace): the harness has already written its changes directly to the same directory, and the inner LLM uses read_file/run_shell to immediately read/run the harness's actual changes for verification—no need to extract code from text. Only when the harness has not written to disk and has provided only textual suggestions (as a last resort) may the inner LLM use write_file to write the code from the text into the workspace and then run it (a fallback capability, not the normal path or a hardcoded mechanism). Preserve the existing ApiPersonaClient/ScriptedPersonaClient without breaking them. 2) The output contract is exactly the same as 0005 (perceive/verdict/action/message), handed back to the outer resolve_action/apply_verdict."
    acceptance: "AgenticPersonaClient.respond returns fields consistent with the current protocol, consumable directly by the outer resolve_action/apply_verdict. Given a FakeToolLLM script that triggers tool calls: the loop correctly executes tool_call→observe→final output; a blind persona (no tools) falls back to text-only judgment. When the step limit is exceeded, output is invalid, or a tool raises an exception, fall back to a valid subjective judgment without crashing the outer layer. Complete one end-to-end session through run_session + the T1 billing-split fixture (FakeSandbox or real Sandbox), with no changes to the outer engine."
---

# 0008 · Inner tool-using user agent (verification in its own environment)

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level rust-RFC nine-section overview. -->

## Summary

This group upgrades the spec-0005 user side's「single `respond()` subjective judgment」to an **inner tool-using agent that can verify in its own environment**:
the simulated user, like a real person, uses **its own tool stack** (reading code / running commands / writing scripts) to **actually execute** checks in its own sandbox when suspicious,
grounding `verdict` in real results rather than speculation. **The outer control envelope (action space / state machine / user experience / termination) remains unchanged**,
and the sole seam is `PersonaClient.respond(system, user) -> dict`. The implementation lands at `backend/ahe_beta/user/sim/` and is an evolution of 0005/T3.

Data flow spine (numbering is execution order: establish the workspace in T1, then execute internally in T2/T4, with T3 in parallel):

```
seed scenario + workspace (T1: SeedScenario.workspace ─► orchestrator materializes it before each session ─► fresh project directory = shared by both sides)
   │  Injection chain: orchestrator passes the same workspace_dir to both launcher (which injects SANDBOX_WORK_DIR into the harness subprocess)
   │  and run_session → sim_user bind_session(persona, workspace_dir) (run_session/harness protocol unchanged)
   ▼
Outer control envelope (0005/T5 run_session, unchanged)
   │  Interface respond(system,user) -> {perceive,verdict,action,message}
   ▼
Inner tool-using agent (T4 AgenticPersonaClient)
   ├─ Tools = tool_stack(D1) ─► atomic tools read_file/run_shell/write_file (+web_search placeholder) execute in Sandbox(workspace) (T2)
   ├─ Prompt behavior framework: optional verification (CAN=D1 tool gating, WILL=trust/D3/suspicion, no checking by default) (T3)
   └─ Skill placeholder: D2 domain playbook extensions (general-purpose, not bug-specific, held-out) (T3)
```

The diagram maps directly to the tasks: **T1** first establishes the workspace foundation (the current repository's seed scenarios contain only `description: str`, with no project on disk to run)——add an optional workspace to
`SeedScenario` and materialize an in-repo baseline project fixture per session as the sandbox cwd; **T2** builds the inner
agent's「hands」——atomic tools + sandbox (using the workspace as cwd) + a tool set gated by D1; **T3** changes the system prompt's verification semantics
from「an obligation」to「optional and costly」and establishes a skill placeholder interface (in parallel with T1/T2); **T4** replaces the single `respond()` with a bounded
tool-calling inner loop (control inversion occurs only locally within this seam). Execution order is expressed by `depends-on` and matches the numbering:
**T1 → T2 → T4**, with T3 in parallel.

**Motivation**: 0005's capability differentiation relies on prompt G1「asking the LLM to exercise self-discipline and not peek at the answer」+ text-based perception, which is fragile——a strong model may「work out」a bug mentally,
or fabricate negative perceptions through speculation. This group bases capability differentiation on **tool accessibility (D1 mechanical gating) + actual execution results + whether suspicion arises (optional verification)**:
blind has no tools and can rely only on text, shallow can run code but cannot write a test suite, competent/expert can write their own tests, while the expert's ability to「construct tricky edge cases」
is an irreducible skill difference governed by prompt behavior.

**Still purely subjective, benchmark still held-out**: actual execution results are the same for everyone and **are not gold** (unrelated to the objective ground-truth line
`gold/GAP/ESCAPED_BUG/control-plane` deferred by 0005; the workspace also contains no gold tests); capability differentiation = tool gating + subjective interpretation + whether suspicion arises;
user experience/state still consume only subjective `verdict`. Verification is an **optional** in-character action for the persona——real people (including experts) do not run checks every time, only when suspicious and when it is worthwhile;
by default, they do not check.

**The harness and user agent share the same workspace (v2 correction, critical)**: this group's target scenario has always been「the assistant (harness) can modify and run code, and the user
agent actually verifies in the same directory」——purely textual advice cannot be truly verified. Therefore, T1 makes the workspace one directory shared by both sides: the orchestrator first
materializes it per session, injects SANDBOX_WORK_DIR into the harness subprocess via the launcher, and binds the same directory to the inner client; changes written by the harness (bash tool)
are immediately readable and runnable by the user agent's inner sandbox (shared FS, not advisory text). The initial version treated this as「the harness is advisory only, the user
pastes into their own workspace copy, and a shared workspace is deferred to a completely decoupled second-phase upstream spec」——this is now corrected as a flawed assumption: the shared workspace is implemented in this group's T1 (only
adding optional workspace_dir wiring, with a fallback path that leaves pure-text scenarios and direct calls unaffected), with no separate upstream spec. Turn-by-turn
stdio serialization naturally ensures no concurrent write contention between the two sides.

**Relationship to 0005 and the closed loop**: this group evolves the 0005/T3 LLM backend. The outer 0005/T5 engine retains the judge→intent→act control envelope, but outer actions express only external actions toward the harness/session. `web_search` tools, actual skill
content, and dependency provisioning (venv/pip, bypassed in the MVP with stdlib-only scenarios) are **placeholders / hooks only** this round (skills are constrained by the red line「general domain methods, never
bug/benchmark-specific」and integrate with 0006 distillation). Outer `verify_self`/`pending_self_obs` have been retired: private checks such as reading files, running commands, inspecting diffs, and verifying test output are all inner AgenticPersonaClient behavior, primarily used to form grounded `perceive/verdict` during the judge phase; if the user needs evidence from the harness, they make a natural-language request through outer `send_message`. Whether to feed explicit state signals to the inner agent, the source of the git workspace, and alignment with the tool-calling form of 0003/T2 `nexau_runtime` are recorded in the respective Task
open-questions for subsequent Tasks/groups.

## Motivation

The 0005 user agent's capability differentiation relies entirely on prompt-level self-discipline constraints (「asking the LLM to exercise self-discipline and not peek at the answer」) and purely text-based perception. This mechanism is fragile: a strong model may work out a bug mentally or invent negative perceptions from nothing, causing `verdict` to become detached from actual results. Grounding the differentiation on a firmer foundation——tool accessibility (mechanical gating) + actual execution results——requires three progressive layers of infrastructure, plus a final integration task.

The first layer is a place to execute (T1): the current repository's seed scenarios contain only `description: str`, with no executable project on disk. If the inner agent is to「actually verify」, it has nowhere to start and can only run isolated snippets in an empty tempdir, unable to run code with dependencies or multiple modules. Furthermore, this project's target scenario has always been「the harness (assistant) can modify and run code, and the user agent actually verifies in the same directory」——if, as initially envisioned, each side holds a private workspace copy and the harness outputs only textual advice, that advice cannot ultimately be truly verified. T1 must therefore make the workspace a single directory **shared** by the harness subprocess and the user agent's inner sandbox, so changes written by the harness are immediately readable and runnable by the user agent.

Once there is a place to run, the second layer provides「hands」that can actually execute (T2): three atomic tools (read_file / run_shell / write_file) and a minimal sandbox with the workspace as cwd, mechanically gating the available tool set by the persona's D1 dimension——blind has no tools and can rely only on text, shallow can read and run but cannot write tests, and only competent/expert receive write_file to write their own tests. Capability differentiation is thereby anchored in tool accessibility rather than prompt self-discipline. Atomic tools are the smallest composable units that cannot be subdivided further; run_tests/construct_edge_cases and similar behaviors are composite behaviors emerging from「atomic tools + LLM reasoning」and should not be made into tools (otherwise their semantics become bloated and implementation problems are more likely).

The third layer is a behavioral framework for appropriate tool use (T3): tools alone are insufficient to prevent degeneration——either never verifying (reverting to 0005's pure text), or verifying every turn (unrealistic and costly). Real people make an optional, costly decision to verify, checking only when suspicious and when it is worthwhile; T2 already mechanically gates the baseline of「whether they can check」(CAN), while T3 must characterize the individual differences in「whether they will check and how thoroughly」(WILL) at the prompt level, and reserve a skill placeholder extension point for high-depth D2 personas, subject to the red line「general domain methods, never bug/benchmark-specific」.

Finally, T4 integrates everything: connect the foundation (T1 workspace), hands (T2 tools/sandbox), and behavioral framework (T3 prompt) into AgenticPersonaClient, an inner agent that actually uses tools to verify. The key constraint is「change only the seam, not the envelope」——`PersonaClient.respond(system, user) -> dict` is the only change point; the outer engine is unaware of whether the inner agent is reasoning mentally with an LLM or actually running tools. Risk is therefore contained within one class, allowing gradual rollout and rollback.

## Guide-level explanation

Execution order matches the numbering: T1 → T2 → T4, with T3 parallel to T1/T2 and its output feeding into T4.

T1 lays the foundation: add an optional workspace field to SeedScenario so seed scenarios can carry an in-repo baseline project instead of only a pure-text description; the new workspace.py's materialize() copies the fixture (the first implementation is billing-split, stdlib-only with no third-party dependencies) into a fresh isolated directory for each session, for use as the inner sandbox's cwd. The v2 version further moves materialize up to the orchestrator, which materializes one workspace before launch, injects it into the harness subprocess env as SANDBOX_WORK_DIR via the launcher, and simultaneously binds the same directory to the inner client——the harness modifies files directly and the user agent actually verifies in the same directory, with both sides sharing the same filesystem (no longer holding separate private copies). This task comes first so T2's sandbox and T4's inner agent have a real project to run.

With the workspace in place, T2 builds the inner agent's「hands」: three atomic tools read_file / run_shell / write_file (plus a web_search placeholder, not implemented this round), and a minimal sandbox execution environment (tempfile + subprocess), using the workspace directory materialized by T1 as cwd. The tool set is mechanically gated by the persona's D1 dimension (tool_stack(D1)): lower-capability personas do not receive write_file, mechanically blocking high-capability actions such as「writing their own test suite」.

T3, parallel to T1/T2, changes the verification semantics of the inner system prompt from「an obligation」to「optional and costly」: verification is an in-character persona action, performed only when suspicious and when worthwhile, and not by default (real people, including experts, do not run checks every time). BLOCK-G specifies the tools'「optional verification」framework; BLOCK-P characterizes verification tendencies by D1 (whether they can check / which tools they can use) and D3/trust (whether they will check and how strict the threshold is); it also establishes a skill placeholder interface (select_skills, D2-driven) so expert personas can attach domain playbooks (placeholder only this round, purely prompt guidance). After 0031 converges, the judge prompt will make clear: if the current verdict has insufficient basis and can be checked at low cost, private checks should be completed in the judge's inner tool loop; checks are no longer deferred to `verify_self` in the act phase.

T4 is the integration task: replace PersonaClient's single「pure-function judgment」respond() with AgenticPersonaClient, a bounded tool-calling inner loop——the inner LLM receives the system assembled by T3 and the tool set from T2, actually executes verification in the shared workspace sandbox materialized by T1, and after several loop steps produces output fully consistent with the current protocol (perceive/verdict/action/message). Control inversion occurs locally within this one seam; the outer control envelope (0005/T5 run_session, action space, state machine, user experience, termination) remains layered: the act phase selects only `send_message` or a termination action, and private checks are no longer outer actions.

T4's private tool results must also generate lightweight session memory: whenever tool/tool_result/tool_error appears in a respond call, the framework organizes the tool actions and the short conclusion from that phase's `parsed.perceive` into `private_evidence` for subsequent main/waiting judge/intent/act to read. This allows the user to remember which files they have already read privately, which commands they have run, and which facts or conflicts they have observed; complete raw output is still persisted only in sim_trace and is not fed back into the prompt.

## Reference-level explanation

The following expands on four technical layers: workspace and injection chain (T1) → atomic tools and sandbox (T2, depending on the cwd provided by T1) → prompt behavioral framework and skill placeholder (T3, parallel to T1/T2) → inner loop AgenticPersonaClient (T4, integration, dependent on the preceding three).

### Shared workspace and injection chain (T1)

Shared workspace injection chain (v2; critical: the run_session and respond engine signatures and the harness stdio protocol remain unchanged): orchestrator.run_round first materializes the workspace for each session *before* launch——when scenario.workspace is nonempty, `workspace_dir = materialize(scenario.workspace)` (otherwise None, falling back to current behavior) ─► the same workspace_dir feeds both sides through two paths: (A) `launcher.launch(sha, workspace_dir=workspace_dir)`, the launcher writes it to the subprocess env as SANDBOX_WORK_DIR, and harness entry._setup_workspace() reads it and uses it as the bash working root (no longer creating its own harness_ws_* tmp); (B) `run_session(persona, scenario, harness, workspace_dir=workspace_dir)`, sim_user no longer materializes independently, instead using guarded `client.bind_session(persona=sim_persona, workspace_dir=workspace_dir)`, and the inner T4 AgenticPersonaClient uses it to create Sandbox(workspace=workspace_dir) (T2) as cwd. Both cwds point to the same directory ⇒ file changes written by the harness subprocess are immediately readable and runnable by the user agent's inner sandbox (shared FS, not advisory text). Why move materialize up to the orchestrator: launch happens before run_session, so to put the harness and user agent in the same directory, materialization must precede launch and workspace_dir must be accessible to both sides——the orchestrator is the only layer holding both launcher and run_session. Why still use bind instead of a run_session text parameter: run_session feeds only system/user text and does not pass persona/workspace objects, so session-level persona (selecting the tool set) + workspace (creating the Sandbox) can only be injected via bind_session; for Scripted/Api, which lack this method, it is a no-op. The SessionRunner protocol adds keyword-only `workspace_dir: str | None = None`; old direct calls (which do not pass it) materialize from scenario.workspace themselves, with unchanged behavior. Each session gets a fresh copy, isolated from the others; it can be cleaned up when the session ends. The fixture remains stdlib-only, reducing materialize to「only copytree」and deferring dependency provisioning; the fixture is placed at backend/seed_workspaces/ as a versioned asset, unrelated to the benchmark held-out red line (the workspace contains no gold tests).

**Interfaces**

WorkspaceSpec: a dataclass with fields `fixture: str` (directory name under seed_workspaces) and `setup: list[str] = []` (command hook, a placeholder, not executed in this round); includes to_dict/from_dict. materialize(spec, dest_root=None) -> str: copies seed_workspaces/<fixture>/project to a newly created isolated directory and returns its absolute path. SeedScenario: add `workspace: WorkspaceSpec | None = None` (serialization remains compatible with old data: missing field → None). launcher: `HarnessLauncher.launch(ref, workspace_dir: str | None = None) -> HarnessInterface`—when workspace_dir is nonempty, merge SANDBOX_WORK_DIR=workspace_dir into the subprocess env (overriding the same key in params.yaml); when empty, retain current behavior (the harness creates its own tmp workspace); keep the signature backward compatible (append keyword arguments only). SessionRunner protocol: `__call__(persona, scenario, harness, *, workspace_dir: str | None = None) -> object`. orchestrator: within run_round, `workspace_dir = materialize(scenario.workspace) if scenario.workspace else None`, then `launch(sha, workspace_dir=...)` and `run_session(..., workspace_dir=...)`. sim_user.run(persona, scenario, harness, *, workspace_dir=None): use workspace_dir for ws, falling back to `materialize(scenario.workspace)` when omitted (if scenario.workspace is nonempty); when ws is nonempty and client exposes bind_session, `bind_session(persona, workspace_dir=ws)`; the run_session/respond engine signatures and harness protocol remain unchanged.

**Tests**

test_workspace.py: (a) after materialize, the directory exists, contains the expected files, and can execute core.py; (b) two materialize calls are isolated (modifying one copy does not affect the other); (c) WorkspaceSpec defaults to an empty setup that is not executed in this round, and supports a to_dict/from_dict round trip; (d) SeedScenario.workspace defaults to None, the old construction pattern still works, and serialization round trips remain compatible with old data; (e) sim_user bridging: when workspace_dir is passed, call bind_session directly with (persona, workspace_dir) without performing materialize itself (use a fake client + monkeypatch materialize to assert it is not called); when workspace_dir is omitted but scenario.workspace is nonempty, fall back to materialize and then bind; when ws is empty or client has no bind_session, do not call it and do not raise an error. test_launcher.py: (f) when workspace_dir is passed to launch, the subprocess env contains SANDBOX_WORK_DIR=workspace_dir (assert using a fake/captured Popen); when omitted, that key is absent (fallback behavior). test_orchestrator.py: (g) run_round calls materialize before launch for each session (use a spy to assert the call order), and passes the same workspace_dir to both launch and run_session; when scenario.workspace is None, both receive None (fallback behavior, no materialize).

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/workspace.py`
  - `backend/seed_workspaces/billing-split/project/billing/core.py`
  - `backend/seed_workspaces/billing-split/manifest.yaml`
  - `backend/ahe_beta/models.py`
  - `backend/ahe_beta/loop/sim_user.py`
  - `backend/ahe_beta/loop/orchestrator.py`
  - `backend/ahe_beta/harness/launcher.py`
  - `backend/tests/user/sim/test_workspace.py`
  - `backend/tests/harness/test_launcher.py`
  - `backend/tests/loop/test_orchestrator.py`

### Atomic Tools and Sandbox (T2)

Sandbox holds a working directory (a workspace or a newly created tempdir); all tool calls resolve paths relative to it and prohibit escaping its subtree. run_shell executes via subprocess, with a timeout and output truncation. tool_stack(D1): blind→[] (no tools), shallow→[read_file, run_shell], competent/expert→[read_file, run_shell, write_file] (+ a web_search placeholder that is never actually enabled). Gating occurs at the layer that determines which tools are exposed to the LLM (enforced by the mechanism), without relying on prompt compliance. The tools themselves are workspace-independent: with workspace=None, an empty tempdir suffices for independent construction and unit testing—so T1 is a soft dependency in terms of sequencing/testing (allowing sandbox tests to run real fixtures), rather than a hard code dependency.

**Interfaces**

read_file(sandbox, path) -> {ok, content|error}; run_shell(sandbox, cmd, timeout=...) -> {ok, stdout, stderr, returncode}; write_file(sandbox, path, content) -> {ok|error}; web_search(query) -> {ok: False, error: "not_implemented"} (placeholder). Sandbox(workspace: str | None = None), with property cwd and methods resolve(path) (prevents escape) and cleanup(). tool_stack(d1: D1) -> list[ToolSpec], where ToolSpec contains name/schema/callable, for T4 to expose to the LLM and T3 to render the tool list in the prompt.

**Tests**

test_tools.py: (a) read/write/run work correctly within the sandbox; (b) path traversal (../../) is rejected; (c) run_shell returns the correct structure on timeout/nonzero exit codes; (d) Sandbox(workspace=a temporary billing-split copy) can import/run core.py; (e) tool_stack returns the correct tool subset for each D1 level; (f) web_search returns not_implemented. Use real tempdirs + small scripts; do not mock subprocess.

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/tools.py`
  - `backend/ahe_beta/user/sim/sandbox.py`
  - `backend/tests/user/sim/test_tools.py`

### Prompt Behavior Framework and Skill Placeholders (T3)

CAN (capability, mechanical): T2 tool_stack(D1) determines which tools are exposed—the prompt only describes them accurately and does not perform gating. WILL (willingness, prompt): BLOCK-P uses D3 (acceptance strictness) + trust/consecutive_blame state to render tendency statements; for example, low trust/high D3 → greater inclination to verify, and the reverse favors direct acceptance. Verification is characterized as an “optional action with a cost”: subjective judgment is the default, and tools are used only when doubts arise and the benefit justifies the cost. Phase assignment: private verification serves the judge's `perceive/verdict`; the act phase has no private verification action and can only `send_message` to ask the harness for evidence/to continue running, or choose to terminate. The skill injection point is the system section of the T4 inner loop; this task only establishes the interface and assembly point. Skill snippets contain general methodology (such as “reproduce first, then locate the cause”) and must never contain a specific bug/answer. clauses implement these as unit-testable pure functions (input: persona+state; output: text snippets).

**Interfaces**

build_inner_system(persona, tools, skills, state) -> str: assembles the inner system prompt (including the BLOCK-G optional verification framework + BLOCK-P personality tendencies + tool list + skill snippets). clause_verification_policy(persona, state) -> str; clause_capability(persona, tools) -> str. select_skills(persona) -> list[Skill]; Skill(name: str, prompt: str). T4 calls these functions whenever it builds the inner prompt.

**Tests**

test_inner_prompt.py: (a) the tool-list wording is correct for each D1 level; (b) clause_verification_policy varies with D3/trust (high strictness/low trust → inclination to verify; the reverse favors acceptance); (c) BLOCK-G includes wording conveying “optional/has a cost”; (d) select_skills returns a list of Skill objects, with snippets containing general methods (assert the absence of benchmark/bug keywords as a placeholder check); (e) end-to-end assembly by build_inner_system includes the tool list and skill section. Use text-only assertions; do not call an LLM.

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/prompt.py`
  - `backend/ahe_beta/user/sim/clauses.py`
  - `backend/ahe_beta/user/sim/skills.py`
  - `backend/tests/user/sim/test_inner_prompt.py`

### Inner Loop: AgenticPersonaClient (T4)

Loop: respond(system,user) → tool_stack(D1)+build_inner_system → multiple inner turns of [LLM→tool_call→Sandbox.run→observe], bounded by step/time limits → LLM produces final JSON (with the same fields as the current protocol) → validate and return. Session-level context: persona and workspace are bound at the start of each session by the sim_user bridge through bind_session(persona, workspace_dir) (run_session does not receive persona, and its signature remains unchanged); respond uses the bound workspace to construct Sandbox(workspace=dir). This dir is the shared harness/user-agent directory materialized by T1 v2—the harness subprocess has already written its changes there, and the inner LLM directly uses read_file/run_shell to read/run those actual changes for verification, grounding the verdict in real execution results (shared FS, rather than extracting code from textual advisories); in unavoidable cases where the harness provides only text without writing to disk, write_file serves as a fallback capability to write the textual code to disk and then verify it (emergent, not hardcoded). Failure fallback: if the LLM fails to produce valid JSON, a tool raises an exception, or the step limit is exceeded, fall back to a single subjective judgment (ensuring valid output is always returned and the outer layer does not crash). A blind persona with no tools, or a client without bind_session (no workspace), naturally falls back to text-only judgment (equivalent to the old behavior). If respond performs private tool-use, it should pass the tool actions and the final `perceive` summary to the outer layer for recording as private_evidence; this summary is user memory, not a message to the harness or a complete raw trace.

**Interfaces**

AgenticPersonaClient(llm, *, max_inner_steps: int = ..., timeout: float = ...) implements respond(system: str, user: str) -> dict (the same PersonaClient protocol, returning {perceive, verdict, action, message}); it also provides bind_session(persona, workspace_dir: str | None), called by sim_user for each session to bind the session-level persona+workspace (falling back to text-only behavior if not bound). Internal dependencies: T2 tool_stack/Sandbox, T3 build_inner_system, and the T1 workspace (injected through sim_user bind_session). Both outer-layer 0005/T5 signatures, run_session and respond(system,user), remain entirely unchanged.

**Tests**

test_persona_client_agentic.py: (a) FakeToolLLM performs multiple tool_call steps → FakeSandbox observe → final JSON; assert the loop step count and final contract; (b) blind/empty tools fall back to text-only behavior; (c) exceeding max_inner_steps falls back to valid output; (d) invalid JSON from the LLM triggers fallback to subjective judgment; (e) integration: run_session + T1 fixture; assert that the outer state machine/termination is unaffected and the output can be consumed by resolve_action; (f) ScriptedPersonaClient still works (no regression).

**Files (single-writer ownership)**

  - `backend/ahe_beta/user/sim/persona_client.py`
  - `backend/tests/user/sim/test_persona_client_agentic.py`

Dependency DAG: `T1 → T2`, `T1 → T4`, `T2 → T4`, `T3 → T4`

## Drawbacks

<!-- TODO -->

## Rationale and alternatives

Trade-offs in environment and isolation: T1 supports only local fixtures + stdlib-only, making materialize minimal (pure copytree), reproducible, and network-free, at the cost of being unable to run scenarios with third-party dependencies for now (a setup hook is reserved as a placeholder). Both sides share the same workspace directory rather than holding private copies, making harness changes immediately visible and runnable for the user agent (actual verification rather than textual advisory), at the cost of requiring guarantees around concurrent writes to the same FS—the framework's turn-by-turn stdio protocol is inherently serial (harness send and user turns do not run concurrently), so this is acceptable. Moving materialize up to the orchestrator makes the workspace ready before launch, at the cost of adding one optional keyword argument each to the orchestrator/launcher (cross-group file changes, but backward-compatible; the fallback paths of `workspace=None`/`workspace_dir=None` cause no breakage for existing text-only scenarios or direct calls, enabling incremental rollout). T2's Sandbox likewise provides only minimal isolation (cwd restriction + timeout), not strong isolation at the Docker/nsjail level—this is acceptable because the code being executed is proposed by the assistant and users voluntarily run it on their own machines; the threat model differs from that of a production sandbox, and strong isolation is left for later. The three tools are atomic rather than composite (such as run_tests/construct_edge_cases), providing clear semantics, easy testing, and composability, at the cost of requiring high-capability behavior to emerge through LLM orchestration, with no direct assertion that "tests were run"; D1's three-tier mechanical gating is simple and reliable, but relatively coarse-grained.

Trade-offs in behavioral control: T3 uses pure prompt guidance to characterize WILL (whether to investigate and how thoroughly), making implementation lightweight and evolvable, but less rigid than a mechanical mechanism—the LLM may not fully follow the tendencies. T2's mechanical gating already provides the baseline for CAN, and the prompt only supplements the soft differences between competent↔expert. skill remains a placeholder, without connecting to a real playbook library, avoiding premature design at the cost of limited prompt differences between expert and ordinary capability in the short term. Making verification optional means low-willingness personas will rarely verify—this is expected behavior (more realistic), not a defect.

Trade-offs in final integration: T4's multiple inner LLM calls increase latency and token costs, controlled jointly by max_inner_steps/timeout and T3's "do not investigate by default" approach; unstable tool-calling output is handled by requiring final structured JSON + falling back to subjective judgment on failure. Confining changes to the single seam `PersonaClient.respond` isolates risk and allows coexistence with ScriptedPersonaClient in CI, but actual end-to-end runs still require a real LLM, so integration tests instead use FakeToolLLM + FakeSandbox to cover the loop logic offline.

## Prior art

This entire group reuses and evolves existing spec interfaces rather than starting from scratch. T1 extends SeedScenario in models.py from 0001/T1, and its injection chain spans the caller sim_user from 0005/T5, the orchestrator from 0007/T2 (where materialize is moved up), and the launcher from 0003/T1 (where SANDBOX_WORK_DIR is injected)—overlap between their files and this group produces only a validate warning (the same pattern as models.py being referenced simultaneously by 0001/0008/0009); the run_session/respond engine signatures and harness stdio protocol remain unaffected. The harness-side entry point for reading this variable is `_setup_workspace()` in backend/harness_template/entry.py (the sandbox_config declaration in agent.yaml), and fixture assets reside in backend/seed_workspaces/. The directory materialized by T1 is used as cwd by T2's Sandbox and consumed by T4's `AgenticPersonaClient.bind_session`.

T2's capability gating reuses the cap_mask (D1) approach from 0005/T2 rather than reinventing a tiering mechanism; its atomic tools and sandbox are consumed by T4 (exposing tool_stack to the inner LLM and using Sandbox for actual execution), while the tool list is rendered into the system prompt by T3. Composite behaviors such as run_tests/construct_edge_cases are not implemented as tools; instead, they fall within T3's prompt-based behavioral framework and emerge through LLM orchestration.

T3 evolves the prompt structure (BLOCK-G/BLOCK-P) from 0005/T3 and the persona dimensions (D1/D2/D3) from 0005/T1; its tool list comes from this group's T2 tool_stack. The skill placeholder is constrained by the "general-purpose, not benchmark-specific" boundary and connects to the distillation pipeline from 0006/T1; its assembled output (build_inner_system) is invoked by T4 whenever it constructs an inner prompt.

T4 is the final integration point of the entire evolution chain: it evolves the LLM backend from 0005/T3, namely the `PersonaClient.respond` seam, with zero changes to the outer run_session engine from 0005/T5; it depends on this group's T2 tool_stack/Sandbox, T3 build_inner_system, and T1 workspace injection. Its inner tool-calling loop may converge with the tool-calling reference in 0003/T2 nexau_runtime in the future (see Unresolved questions); a unified implementation is not required in this round.

## Unresolved questions

Dependencies and sources: how to supply scenarios with third-party dependencies—whether the setup hook uses a cached venv or pip per session, and when to implement this (T1); whether workspace sources need to support git clone / a specified commit, to connect to more realistic project snapshots and integrate with the pluggable supply of 0009 SeedSource (T1); temporary-directory cleanup policy and disk-usage limits (T1).

Isolation and tool boundaries: write contention between the harness and user agent on a shared FS is currently avoided naturally by turn-by-turn stdio serialization; if the harness executes asynchronously/concurrently in the future, explicit locks or snapshot isolation will be needed (T1); observability of harness changes and the user agent's verification process in the shared directory, specifically whether persisted transcripts should record workspace diffs (T1); whether run_shell needs resource limits (memory/CPU/network disabling) for stronger isolation (T2); the interface and quotas for a real web_search implementation are left for later (T2); whether apply_patch/diff-style tools are needed or write_file is sufficient (T2); whether three D1 gating tiers are enough or a finer-grained tool-to-capability mapping table is needed (T2).

Verification behavior and skill: the source and organization of a real skill library—handwritten or distilled from successful conversations, still subject to held-out constraints (T3); whether pure prompt guidance at the WILL layer is sufficient, or whether the inner layer needs explicit "verification budget/cost" signals for harder constraints (T3); whether verification-tendency statements should use continuous granularity or discrete tiers (T3); whether to unify the increasingly redundant outer verify_self semantics with inner optional verification, and whether to simply remove outer verify_self/pending_self_obs (verification has moved into the inner layer)—this question spans T3 and T4 and remains unresolved.

Final integration and unified implementation: whether to feed explicit state signals (patience/trust) to the inner layer to make willingness to verify more controllable (T4); defaults and cost caps for max_inner_steps/timeout (T4); whether this group's inner loop and the tool-calling form in 0003/T2 nexau_runtime should be unified into one implementation (T4); schema selection for real LLM tool-calling—function calling or a text protocol (T4).

## Future possibilities

<!-- TODO -->

