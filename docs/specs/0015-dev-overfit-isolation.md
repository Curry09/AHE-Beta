---
number: "0015"
title: "Harness Boundaries and Requirements Tool Access: Commit Denylist, Trace Isolation, and Workspace Checks"
issue: 0
slug: dev-overfit-isolation
summary: "Retain three active boundary mechanisms: Harness commit hooks reject secrets and runtime state, sandbox working directories are separated from raw traces, and the requirements Agent reads files through guards tool-path checks and explicit observation authorization."
tasks:
- id: T1
  title: "Hard commit-boundary gate for the harness repository (pre-commit hook)"
  status: pending
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/guards/harness_boundary.py
  - backend/tests/guards/test_harness_boundary.py
  scope: "guards/harness_boundary generates a self-contained pre-commit hook; reject .env and .env.* in paths (except .env.example) and top-level .openagents, while allowing normal product code and documentation. The hook depends only on the Python standard library and Git, and is installed by run.py after the seed commit. Keep the rules consistent with the server-side checks in seed smoke."
  acceptance: "After installing the hook in a temporary repository, commits of normal source code, docs/specs, and .env.example pass; .env, .env.local, and .openagents state are rejected. The hook does not depend on the orchestration package, and template rules share the same source as violations()."
- id: T2
  title: "Nest the sandbox working directory more deeply to physically isolate traces"
  status: pending
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/controllers/ordinary.py
  - backend/tests/test_sandbox_isolation.py
  scope: "Move the requirements Agent's sandbox working directory (= harness repository) deeper under a separate parent directory, data/harness_sandbox/harness_repo, so that the trace directories (data/sessions for user experience + sessions, data/harness_runs for runtime copies) are no longer its siblings under ../—relative paths such as ../sessions/*.json and ../harness_runs/** used by the agent no longer reach real data, eliminating the practical route for “casually browsing traces” through directory layout. run.py's _seed_harness_repo creates the repository under this new layout and calls install_pre_commit (T1) to install the boundary hook; launcher/store/runs_root point to the corresponding directories. Complements WorkspaceJail (T3): this task changes directory layout (passive isolation), while T3 changes tool behavior (active rejection)."
  acceptance: "HARNESS_REPO = data/harness_sandbox/harness_repo, with no parent-child/sibling reachability relationship to data/sessions or data/harness_runs; relative paths ../sessions / ../harness_runs from harness_repo do not point to real traces; _seed_harness_repo creates the repository in the new layout and installs the pre-commit hook. Unit tests assert directory-layout isolation (traces are not siblings under work_dir's ../)."
- id: T3
  title: "WorkspaceJailMiddleware: confine writes to the repository, allow reads of NexAU source and runtime temporary directories"
  status: pending
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/guards/workspace_jail.py
  - backend/tests/guards/test_workspace_jail.py
  scope: "WorkspaceJailMiddleware resides in guards; write tools are restricted to the Harness workspace, while read tools allow the workspace, NexAU source, and framework temporary output. The agent YAML for Triage, Architect, PM, and Owner wires it in; observation artifacts must be declared and authorized for the session before they can be read, and path renaming cannot expand the evidence scope. This check is not an operating-system sandbox."
  acceptance: "The four roles' YAML wires in the new guards binding; legitimate source code/temporary output is readable, and out-of-bounds reads and writes are rejected; observation reads authorized per call and rejection of raw traces retain the original contract; existing behavior without a workspace and for heredoc remains unchanged."
---

# 0015 · Harness Boundaries and Requirement Tool Access

## Summary

Three mechanisms are currently retained: the Harness submission rejection list, isolation of the working-directory and raw-trace layouts, and tool file-path checks for the requirements Agent. The implementation is located in `backend/ahe_beta/guards/`, and no longer belongs to a built-in development role.

## Motivation

The product repository must not ingest keys or experiment runtime state, and the requirements Agent must not read raw task traces arbitrarily. Path checks can block direct out-of-bounds access, but cannot constrain all behavior executed by an interpreter; therefore, they must not be described as an operating-system sandbox.

## Guide-level explanation

- `harness_boundary.py` generates an independent pre-commit hook that rejects `.env`, `.env.*`, and top-level `.openagents`; `.env.example` and normal product files are allowed to be submitted.
- `run.py` places the Harness under `data/harness_sandbox/harness_repo`, preventing raw traces from becoming a sibling directory of the workspace.
- Triage, Architect, PM, and Owner check tool access through `WorkspaceJailMiddleware`; declared observation artifacts must also satisfy authorization by call and session.

## Reference-level explanation

T1 owns `guards/harness_boundary.py` and its tests; T2 owns the directory layout and hook installation for the startup entry point; T3 owns `guards/workspace_jail.py` and its tests. The requirements Agent definition references `ahe_beta.guards.workspace_jail:WorkspaceJailMiddleware`.

The submission hook is installed after the seed commit and depends only on the standard library and Git. When modifying the rejection list, update the independent script for the Harness template smoke test in sync. Write operations are restricted to the workspace; read operations allow the workspace, NexAU source code, and temporary framework output, while raw sessions and runtime traces are not made accessible by moving directories. Explicit observation authorization is still validated by the requirements-side observation provider.

```mermaid
flowchart LR
    T1[Commit hook] --> T2[Workspace layout and installation]
    T3[Tool access checks]
```

Offline verification: `uv run --locked --extra dev pytest backend/tests/guards/test_harness_boundary.py backend/tests/guards/test_workspace_jail.py backend/tests/test_sandbox_isolation.py`. Full wiring regression also checks the four-role YAML, temporary-repository submission and rejection, and observation authorization.

## Drawbacks

Tool-argument-level checks cannot prevent every out-of-bounds method available to an interpreter or arbitrary shell; directory isolation is also not permission isolation. Container- or operating-system-level isolation requires independent verification.

## Rationale and alternatives

Retain the effective checks and move them into `guards`, avoiding removal of defenses that are still assembled; use an explicit rejection list rather than the old product-file-name allowlist, so that legitimate new source code and Spec documents can be submitted.

## Prior art

Earlier submission allowlists and path checks were used to reduce the risk of task content contaminating the product. The current submission boundary already permits normal product expansion while continuing to reject keys and runtime state.

## Unresolved questions

None. This reorganization preserves the existing check behavior and trigger points and does not add new sandbox capabilities.

## Future possibilities

The submission hook and CI rejection rules could be generated from the same source, and operating-system-level isolation could be verified further; these protections do not arise automatically from package migration.
