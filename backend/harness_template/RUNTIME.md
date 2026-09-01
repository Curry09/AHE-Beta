# Runtime Notes

This file is for maintainers of this harness. Human-facing help is returned by `/help` from `HELP.md`. Process I/O details are owned by the embedding runtime or client integration.

## Runtime boundary

| Area | Access | Notes |
|------|--------|-------|
| This harness repository | Read + write | Product code and configuration live here |
| Configured workspace (`SANDBOX_WORK_DIR`) | Read + write | User project where commands and edits happen |
| NexAU runtime/library | Read-only / 只读 | Consult for APIs and behavior; do not vendor or patch it here |
| Secrets and environment | Read env values only as needed | Never write filled secret files to the repository |

The harness repository is not the user's project. Do not copy the user's project source, generated packages, or task-specific scaffolding into this repository. General assistant improvements belong here; user project work belongs in `SANDBOX_WORK_DIR`.

## Process model

- `entry.py` is the process entrypoint declared by `params.yaml`.
- The process reads JSON Lines from stdin and writes JSON Lines to stdout.
- The process handles one request at a time.
- If another message arrives while a request is running, the process emits a visible queued status and handles that message after the current response. Starting a queued message also emits a visible status line.
- `/help` is recognized as ordinary message text, returns `HELP.md`, and keeps the session open.
- `/exit` and `/quit` are recognized as ordinary message text and close the session.

## Session and recovery

- A process keeps one conversation context while it is alive.
- Internally, the runtime uses a stable `session_id` for the process. 换实例 ≠ 换 session: rebuilding an internal agent instance must preserve the user conversation.
- A soft interrupt attempts to stop the current request while preserving context.
- A hard timeout returns a structured `timed_out` reply. In the auto-designer session runtime this is terminal: the launcher destroys the whole session container because an abandoned worker may still be writing.
- Partial file changes may exist at timeout, but that workspace is contaminated and must not be accepted, resumed, or used as objective evidence.

## User-visible behavior changes

When a change affects what a human user can observe — replies, progress, interrupt behavior, slash commands, workspace behavior, or limits — update `HELP.md`. If process I/O changes, coordinate with the clients or embedding runtime that launch this process.
