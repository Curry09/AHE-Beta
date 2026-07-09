# Harness User Manual (v0)

This is the manual for the AI coding assistant ("the harness") you are using
through your terminal. It describes what it can do and how to work with it. This
is the ground truth for THIS tool's capabilities — do not assume features that
are not listed here.

## What it is
A terminal-based AI coding assistant. You send it a request in plain natural
language; it works on it and sends back a single final reply.

## How you interact
- **One request → one reply.** You type a message (a task, question, or
  follow-up). The assistant works, then returns one final text reply.
- **It's conversational.** Within a session it remembers earlier turns, so you
  can send follow-ups ("now add tests", "that's wrong, fix X") and it keeps
  context.
- **It works on real files.** It has a shell and a working directory (your
  project root); it can create/edit files and run commands and tests there. Its
  reply reports what it did.

## Progress while a request is running

For long-running requests, the harness may write concise progress lines to
`stderr` while it is working. These lines are informational only: they do not
replace the single final JSON reply on `stdout`, and they do not change the
one-request/one-reply protocol.

Progress lines can show heartbeat status, tool calls, tool results, errors, and
assistant text. Set `HARNESS_PROGRESS=0` to suppress stderr progress output.

## Getting good results
- Describe what you want clearly. It may ask a brief clarifying question.
- Iterate by replying with feedback.

## How it behaves
- It replies **once per request, when it is finished.** It works between your
  message and its reply; you receive the final reply when it is done. A large
  request can take a long time.
- It handles **one request at a time**, in order.
- Broad, multi-file, end-to-end, package-build, or otherwise large requests are
  constrained with a mandatory minimal-verifiable-slice directive before work
  starts. The assistant must first produce one independently checkable slice,
  report the touched files, verification command, and verification result, and
  must not claim the whole request is complete until that slice is verified.
- On a **very large request it can hit an internal limit and return an error**
  (for example a timeout or "maximum iteration" message) instead of a finished
  result.
- When bounded execution fails, the final reply includes an actionable summary:
  what was produced, whether anything was verified, what remains unverified, the
  blocking reason, and a concrete path to shrink scope for the next attempt.
  If the failure involved a timeout and agent rebuild, the reply also points to a
  recovery snapshot written in the workspace at `.harness_recovery.json`. That
  snapshot contains the blocking reason, attempt count, observed step count, and
  the last observed steps so the next request can continue from visible facts or
  deliberately narrow the scope.
  The raw internal process is still available through the `steps` field for
  diagnosis, but the user-facing `reply` should not be treated as completed work.
- Messages are plain natural language.

> This manual describes the current version. The tool evolves over time; when its
> behavior changes, this manual is expected to change with it.
