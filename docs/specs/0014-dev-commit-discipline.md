---
number: "0014"
title: "Legacy Built-in Developer Commit Discipline (Retired)"
issue: 0
slug: dev-commit-discipline
summary: "The legacy built-in Developer's two commit middleware components and their assembly tasks have been retired and no longer serve as current runtime safeguards; the historical design and implementation remain in Git history."
tasks: []
---

# 0014 · Legacy Built-in Developer Commit Discipline (Retired)

## Summary

This group has no active tasks. The legacy built-in Developer's incremental commit reminders, completion checks, and corresponding configuration wiring have been retired. This cleanup deletes two middleware components not loaded by the current runtime and their dedicated tests; the original tasks are removed from the active snapshot through `spec abandon`.

## Motivation

The requirements side and delivery side have been separated, with code implementation performed by the independent OpenAgents CLI. Retaining unwired legacy middleware would mislead maintainers into thinking that intermediate commits, manual synchronization, and main-entry AST checks are still running.

## Guide-level explanation

This legacy middleware group is not configured in the current system. The requirements Agent file-access checks, orchestration repository integrity checks, and Harness commit hooks that remain active are located in `backend/ahe_beta/guards/`; they are not equivalent to the legacy Developer's commit discipline.

## Reference-level explanation

T1, T2, and T3, which specifically assembled them, have been retired; this group no longer owns any code files. Past source files, parameters, tests, and implementations can be traced through Git history. Currently, `guards/` contains only `workspace_jail.py`, `repo_guard.py`, `harness_boundary.py`, and the package entry point, with no forwarding exports for the old modules.

## Drawbacks

The current release no longer provides importable entry points for these two legacy middleware components; experiments that depend on the legacy built-in Developer must use the original version.

## Rationale and alternatives

Middleware without runtime references is not moved into `guards/`, because that would continue to confuse active safeguards with historical implementations; nor is it ported to OpenAgents, because that involves a separate execution protocol and quality gate design.

## Prior art

The old design attempted to impose incremental commit and completion constraints within the Agent. Current OpenAgents performs engineering delivery according to its own configuration; this group does not claim that it equivalently implements all checks from the legacy middleware.

## Unresolved questions

None. Retirement is limited to the legacy commit middleware and its configuration wiring; active boundary checks are retained.

## Future possibilities

If specific commit discipline needs to be restored on the delivery side, propose separate requirements and verify the actual assembly and effects in the OpenAgents repository.
