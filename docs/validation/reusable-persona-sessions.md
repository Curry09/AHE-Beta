# Reusable persona sessions (Spec-0080)

Validated on 2026-10-04 in `feat/unified-experiment-entry`.

```bash
backend/scripts/e2e-spec-0080-reusable-persona-sessions.sh
```

Result: **253 passed in 54.36s**. Ruff check and format checks passed for changed Python files.

The tests execute the current Orchestrator, SessionStore, tracker, live records and recovery ledger with scripted model clients. Task workspaces run actual shell subprocesses. They do not call paid models or establish N8 cloud task readiness.

- A single selected card supports multiple execution slots; explicit identical pairs and default rotation both freeze successfully. Persona selection/library uniqueness, unknown IDs and incorrect list lengths remain invalid.
- Two concurrent slots using the same persona/task pair have separate client objects, conversation state, session IDs and writable directories, in direct and simulated-user modes. Files carry their own session identity. Live/history, L1 evidence and report references retain independent attribution.
- After one slot succeeds and the other fails during setup, recovery preserves the successful Session and its reports, retries only the failed slot with attempt 2, and does not duplicate completed work on another resume.
- Duplicate, skipped and boolean slot indices remain rejected. N1/N4 compiler identities match golden config/plan hashes and session keys captured from commit `684dd9b` before this change.
- Current collect → continuation source → child prepare → child collect preserves three repeated slots and one frozen card. Parent archive bytes remain unchanged.

Manual review: configure one selected persona and three identical pairs; check and prepare should show slots 0/1/2. Inspect distinct Session IDs and task directories, interrupt one incomplete session, and resume; completed sessions should remain unchanged. Reused persona cards are not independent human samples.

The N8 system environment is a separate operational prerequisite. Namespace isolation and dedicated E2B task sandboxes are deferred; this change does not make legacy N8 manifests public schema-2 configurations.
