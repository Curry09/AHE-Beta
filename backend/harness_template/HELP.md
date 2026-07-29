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
- Progress lines are status updates, not the final answer.
- The final reply states what changed, what was checked, and any remaining blocker.
- Interrupting stops the current request and preserves the session for a follow-up.

## Examples

```text
Fix the failing parser test and add a regression case.
Run the smallest relevant test after the change.
/help
/exit
```
