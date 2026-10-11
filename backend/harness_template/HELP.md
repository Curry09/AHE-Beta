# Harness CLI Help

## NAME

harness — terminal AI coding assistant for a local project workspace.

## SYNOPSIS

```text
<message>
/help
/exit
/quit
```

## DESCRIPTION

Send a natural-language request or follow-up. The assistant works in the configured project workspace, reports short progress updates while it runs, and returns one final reply for each request.

## COMMANDS

| Command | Description |
|---------|-------------|
| `/help` | Show this help text. The session stays open. |
| `/exit` | Close the current session. |
| `/quit` | Close the current session. |

Unknown slash commands are treated as normal user messages.

## Workspace

The assistant runs file and shell operations in `SANDBOX_WORK_DIR`. Treat that directory as the project root for edits, commands, and tests.

## Behavior

- One request is handled at a time.
- If you send another message while a request is still running, it is queued and the assistant shows a visible status line. The queued message is handled after the current response.
- Progress and status lines are updates, not the final answer.
- The final reply states what changed, what was checked, and any remaining blocker.
- Interrupting stops the current request and preserves the session for a follow-up.
- A `completed` reply means the completion tool successfully submitted an answer;
  it does not certify that the task passed its tests.
- An `incomplete` reply preserves partial work and explains why execution ended,
  such as an iteration limit or a response without the completion tool. You can
  send a follow-up in the same session.
- Runtime failures are marked as errors, rather than normal completion.

## Examples

```text
Fix the failing parser test and add a regression case.
Run the smallest relevant test after the change.
/help
/exit
```
