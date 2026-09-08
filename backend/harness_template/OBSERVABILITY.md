# NexAU seed observations

This directory belongs to the running harness version. The platform supplies
HARNESS_OBSERVATION_DIR and collects declared files; it does not interpret events.
Other harnesses may use different files, event names and recording mechanisms.

These files serve maintainer diagnosis: reconstructing execution, distinguishing
causes, and verifying changes. User-facing state feedback separately helps the user
understand the current situation and decide what to do next. Shared events can serve
both, but each goal needs its own acceptance: saved logs do not prove timely user
feedback, and visible progress does not prove adequate diagnostic evidence.

runtime-<process>.jsonl contains wall-clock `at`, a process identifier, and metadata:

- process_started/stopped identify a process, not a user's logical session.
- attempt_started/returned/failed describe one supervised agent invocation. An
  attempt identifier joins its boundaries; error_type is a class, not an error message.
- span_started/finished identify NexAU activities and elapsed time. `kind` is the
  span type. Tool arguments/results and model prompts/responses are not recorded.
- interrupt_requested records a control request, not proof that all work stopped.
- agent_rebuilt records a replacement agent and the number of restored history items,
  not the history contents or proof of successful recovery.

The manifest lists this version's files. `partial` means a process did not close
cleanly or records were dropped; missing events never prove an action did not occur.
An event named returned, or has_error=false, is not proof of task/test success.
Queue and disk budgets can truncate diagnostics without blocking agent execution.
One process writes at most 4 MB and the in-memory queue holds at most 512 events.
The directory has a 12 MB / 120-process recording budget across restarts; a
previous incomplete/dropped process keeps the bundle partial after later restarts.
The platform also bounds the aggregate bundle. Process restarts use separate files.

Compare internal evidence with the platform's user timeline to determine what the
user actually saw or intended. Preserve uncertainty if correlation is insufficient.
When functionality or topology changes, update the affected recording, this reading
guide and tests together. Do not copy task answers, credentials, private
instructions or protected evaluation reference data into diagnostic files.
